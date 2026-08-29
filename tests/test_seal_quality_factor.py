"""封板质量复合因子契约 (R65, 候选 #4)。

全合成 hermetic。钉死:
- 三腿方向: 早封板/零炸板/大封单 → 高值 (手算精确)
- 同日秩基: 两日各自横截面, 跨日不可比
- 单腿缺失取余腿均值; 全缺无行并计数 (不冒充)
- 缺快照文件如实计数; 日历/日期契约
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from build_seal_quality_factor import (  # noqa: E402
    SealFactorError,
    build_factor,
)

CAL = ["20260101", "20260102", "20260105", "20260106"]


def _world(tmp_path: Path, boards: dict[str, list[dict]]):
    lu = tmp_path / "limit_up"
    lu.mkdir(parents=True, exist_ok=True)
    cols = ["trade_date", "ts_code", "close", "pct_chg",
            "first_time", "open_times", "fd_amount"]
    for day, rows in boards.items():
        pd.DataFrame([{**{c: None for c in cols}, **r} for r in rows],
                     columns=cols).to_csv(lu / f"lu_{day}.csv", index=False)
    cal = tmp_path / "cal.json"
    cal.write_text(json.dumps(CAL), encoding="utf-8")
    return lu, cal


def test_three_leg_directions_exact(tmp_path: Path) -> None:
    # 3 票: x1 全优 (早/0 炸/大封单), x3 全劣, x2 中
    boards = {"20260105": [
        {"ts_code": "x1", "first_time": 93000, "open_times": 0, "fd_amount": 9e7},
        {"ts_code": "x2", "first_time": 103000, "open_times": 1, "fd_amount": 5e7},
        {"ts_code": "x3", "first_time": 145000, "open_times": 3, "fd_amount": 1e7},
    ]}
    lu, cal = _world(tmp_path, boards)
    factor, summary = build_factor(lu_dir=lu, calendar_path=cal,
                                   start="20260105", end="20260105")
    got = {r.ts_code: r.factor for r in factor.itertuples()}
    # x1: 三腿秩全 1 → 1.0; x3: 三腿秩全 1/3 → 1/3; x2: 全 2/3
    assert got["x1"] == pytest.approx(1.0)
    assert got["x2"] == pytest.approx(2 / 3)
    assert got["x3"] == pytest.approx(1 / 3)
    assert summary["factor_rows"] == 3


def test_leg_direction_semantics(tmp_path: Path) -> None:
    # 单腿差异化: fd_amount 大者因子高 (其余同值)
    boards = {"20260105": [
        {"ts_code": "big", "first_time": 100000, "open_times": 1, "fd_amount": 9e7},
        {"ts_code": "small", "first_time": 100000, "open_times": 1, "fd_amount": 1e7},
    ]}
    lu, cal = _world(tmp_path, boards)
    factor, _ = build_factor(lu_dir=lu, calendar_path=cal,
                             start="20260105", end="20260105")
    got = {r.ts_code: r.factor for r in factor.itertuples()}
    assert got["big"] > got["small"]
    # first_time 早者因子高
    boards2 = {"20260105": [
        {"ts_code": "early", "first_time": 93000, "open_times": 1, "fd_amount": 5e7},
        {"ts_code": "late", "first_time": 143000, "open_times": 1, "fd_amount": 5e7},
    ]}
    lu2, cal2 = _world(tmp_path / "w2", boards2)
    (tmp_path / "w2/limit_up").mkdir(parents=True, exist_ok=True)
    factor2, _ = build_factor(lu_dir=lu2, calendar_path=cal2,
                              start="20260105", end="20260105")
    got2 = {r.ts_code: r.factor for r in factor2.itertuples()}
    assert got2["early"] > got2["late"]


def test_missing_leg_degrades_to_available_mean(tmp_path: Path) -> None:
    boards = {"20260105": [
        # y2 fd_amount 缺失 → 因子 = mean(r_first, r_open)
        {"ts_code": "y1", "first_time": 93000, "open_times": 0, "fd_amount": 5e7},
        {"ts_code": "y2", "first_time": 103000, "open_times": 2, "fd_amount": None},
    ]}
    lu, cal = _world(tmp_path, boards)
    factor, _ = build_factor(lu_dir=lu, calendar_path=cal,
                             start="20260105", end="20260105")
    got = {r.ts_code: r.factor for r in factor.itertuples()}
    # y2: r_first=1/3, r_open=2/3 (fd 腿 NaN 排除) → 0.5
    assert got["y2"] == pytest.approx(0.5)


def test_all_legs_missing_counted_not_faked(tmp_path: Path) -> None:
    boards = {"20260105": [
        {"ts_code": "z1", "first_time": None, "open_times": None, "fd_amount": None},
        {"ts_code": "z2", "first_time": 100000, "open_times": 1, "fd_amount": 5e7},
    ]}
    lu, cal = _world(tmp_path, boards)
    factor, summary = build_factor(lu_dir=lu, calendar_path=cal,
                                   start="20260105", end="20260105")
    assert set(factor["ts_code"]) == {"z2"}
    assert summary["all_legs_missing_rows"] == 1


def test_missing_file_counted_and_contracts(tmp_path: Path) -> None:
    lu, cal = _world(tmp_path, {"20260105": [
        {"ts_code": "x1", "first_time": 100000, "open_times": 0, "fd_amount": 1e7},
    ]})
    factor, summary = build_factor(lu_dir=lu, calendar_path=cal,
                                   start="20260105", end="20260106")
    assert summary["missing_files"] == 1      # 0106 无快照
    assert summary["days_requested"] == 2
    with pytest.raises(SealFactorError) as ei:
        build_factor(lu_dir=lu, calendar_path=cal, start="20260106",
                     end="20260105")
    assert ei.value.code == "invalid_date_args"
    # 日历过期
    stale = tmp_path / "stale.json"
    stale.write_text(json.dumps(["20251231"]), encoding="utf-8")
    with pytest.raises(SealFactorError) as ei3:
        build_factor(lu_dir=lu, calendar_path=stale, start="20260105",
                     end="20260105")
    assert ei3.value.code == "calendar_stale"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
