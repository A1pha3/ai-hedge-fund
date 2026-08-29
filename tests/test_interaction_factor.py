"""交互因子构建器契约 (R63, 候选 #3: strength × (−industry_momentum))。

全合成 hermetic。钉死:
- 日内秩乘积: 手算精确 (秩在日内, 跨日不可比)
- 负号方向: --neg-b 使 B 的低值获得高秩
- 缺行如实: outer 合并后非双侧行被丢弃并计数, 不冒充
- 确定性: 同输入逐字节
- 方向在候选名预注册, 本工具零自由参数
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from build_interaction_factor import (  # noqa: E402
    InteractionFactorError,
    build_interaction,
)


def _csv(tmp_path: Path, name: str, rows: list[dict]) -> str:
    p = tmp_path / name
    pd.DataFrame(rows, columns=["signal_date", "ts_code", "factor"]).to_csv(
        p, index=False)
    return str(p)


def test_rank_product_exact(tmp_path: Path) -> None:
    # 日 D: 3 票, A 秩 = [1/3, 2/3, 1], B 秩 = [1, 1/2, 1/3] (B 值越大秩越高)
    a = _csv(tmp_path, "a.csv", [
        {"signal_date": "20260105", "ts_code": "x1", "factor": 10.0},
        {"signal_date": "20260105", "ts_code": "x2", "factor": 20.0},
        {"signal_date": "20260105", "ts_code": "x3", "factor": 30.0},
    ])
    b = _csv(tmp_path, "b.csv", [
        {"signal_date": "20260105", "ts_code": "x1", "factor": 0.05},
        {"signal_date": "20260105", "ts_code": "x2", "factor": 0.03},
        {"signal_date": "20260105", "ts_code": "x3", "factor": 0.01},
    ])
    rows, summary = build_interaction(a_spec=a, b_spec=b, court_path=None,
                                      neg_b=True)
    got = {r.ts_code: r.factor for r in rows.itertuples()}
    # neg-b: B 低值高秩 → x3: rank_a=1, rank_b=1 → 1.0 (强票+冷行业 = 满分)
    assert got["x3"] == pytest.approx(1.0)
    assert got["x1"] == pytest.approx((1 / 3) * (1 / 3))
    assert summary["dropped_outer_rows"] == 0


def test_cross_day_ranks_are_within_day(tmp_path: Path) -> None:
    # 两日各自 2 票: 秩必须按日归一 (跨日不可比)
    a = _csv(tmp_path, "a.csv", [
        {"signal_date": "20260105", "ts_code": "x1", "factor": 100.0},
        {"signal_date": "20260105", "ts_code": "x2", "factor": 1.0},
        {"signal_date": "20260106", "ts_code": "x3", "factor": 2.0},
        {"signal_date": "20260106", "ts_code": "x4", "factor": 3.0},
    ])
    b = _csv(tmp_path, "b.csv", [
        {"signal_date": "20260105", "ts_code": "x1", "factor": 0.1},
        {"signal_date": "20260105", "ts_code": "x2", "factor": 0.1},
        {"signal_date": "20260106", "ts_code": "x3", "factor": 0.1},
        {"signal_date": "20260106", "ts_code": "x4", "factor": 0.1},
    ])
    rows, _ = build_interaction(a_spec=a, b_spec=b, court_path=None, neg_b=False)
    got = {(r.signal_date, r.ts_code): r.factor for r in rows.itertuples()}
    # 0105 的 B 值并列 (0.1/0.1) → 平均秩 0.75; x1 日内最高 A → 1.0×0.75
    assert got[("20260105", "x1")] == pytest.approx(0.75)
    assert got[("20260106", "x3")] == pytest.approx(0.375)    # rank_a 0.5 × tie_b 0.75
    assert got[("20260106", "x4")] == pytest.approx(0.75)     # rank_a 1.0 × tie_b 0.75


def test_missing_pairs_counted_not_faked(tmp_path: Path) -> None:
    a = _csv(tmp_path, "a.csv", [
        {"signal_date": "20260105", "ts_code": "x1", "factor": 1.0},
        {"signal_date": "20260105", "ts_code": "x2", "factor": 2.0},
    ])
    b = _csv(tmp_path, "b.csv", [
        {"signal_date": "20260105", "ts_code": "x1", "factor": 0.1},
        {"signal_date": "20260105", "ts_code": "x9", "factor": 0.2},
    ])
    rows, summary = build_interaction(a_spec=a, b_spec=b, court_path=None,
                                      neg_b=False)
    assert set(rows["ts_code"]) == {"x1"}          # 只保留双侧
    assert summary["dropped_outer_rows"] == 2      # x2 (B 缺) + x9 (A 缺)


def test_determinism(tmp_path: Path) -> None:
    a = _csv(tmp_path, "a.csv", [
        {"signal_date": "20260105", "ts_code": "x1", "factor": 1.0},
        {"signal_date": "20260105", "ts_code": "x2", "factor": 2.0},
    ])
    b = _csv(tmp_path, "b.csv", [
        {"signal_date": "20260105", "ts_code": "x1", "factor": 0.2},
        {"signal_date": "20260105", "ts_code": "x2", "factor": 0.1},
    ])
    r1, _ = build_interaction(a_spec=a, b_spec=b, court_path=None, neg_b=True)
    r2, _ = build_interaction(a_spec=a, b_spec=b, court_path=None, neg_b=True)
    assert r1.equals(r2)


def test_contract_errors(tmp_path: Path) -> None:
    with pytest.raises(InteractionFactorError) as ei:
        build_interaction(a_spec=str(tmp_path / "absent.csv"),
                          b_spec=str(tmp_path / "absent2.csv"),
                          court_path=None, neg_b=False)
    assert ei.value.code == "factor_csv_not_found"
    bad = tmp_path / "bad.csv"
    bad.write_text("signal_date,ts_code\n20260105,x\n", encoding="utf-8")
    with pytest.raises(InteractionFactorError) as ei2:
        build_interaction(a_spec=str(bad), b_spec=str(bad),
                          court_path=None, neg_b=False)
    assert ei2.value.code == "factor_csv_missing_columns"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
