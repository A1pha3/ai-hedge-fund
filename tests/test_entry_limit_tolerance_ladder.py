"""entry_limit_tolerance_ladder 正确性回归网 (R211 Op1, hermetic fixture 世界).

固化入场限价容忍度梯子的契约: t=0 与 Op1 反事实工具逐字节一致 (跨工具
单一实现钉) / fill_rate 随档位非降且中档严格升 / 期望差 ΔE(t) 精确值 /
涨停一字 UNKNOWN 各档如实披露 / 桶分解随档位恢复 / fail-closed 输入 /
确定性输出。

R208 补遗检查单: 全部测试零宿主 data/ 读取 (tmp fixture 世界);
trade calendar 经 _btst_court_common._TRADE_CAL_PATH monkeypatch 隔离。
fixture 世界复用 Op1 测试模块的单一实现 (同序 _GEOMETRY/_EXIT_OPEN_T10)。
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

import scripts._btst_court_common as court_common  # noqa: E402
import scripts.entry_limit_semantics_counterfactual as counterfactual  # noqa: E402
import scripts.entry_limit_tolerance_ladder as ladder  # noqa: E402
from scripts.entry_limit_tolerance_ladder import (  # noqa: E402
    TOLERANCES,
    assemble_ladder,
    build_ladder,
    limit_cents_at,
    render_md,
)
from tests.test_entry_limit_semantics_counterfactual import (  # noqa: E402
    _EXIT_OPEN_T10,
    _SESSIONS,
    _event_row,
    _write_daily,
    _write_world,
    next_session_after,
)

# 追加几何: gap 恰 4% 的高开候选 — 限价 10.00 时 T+1 low 10.20 不触及
# (NO_FILL), t=2% 限价 10.20 恰触及 (FILLED @ min(open 10.40, 10.20))。
_LADDER_ROW = ("600008.SH", "20250703", 10.00, (10.40, 10.60, 10.20, 10.30, 10.00), 0.04)
_EXIT_OPEN_LADDER = 10.40 * 1.04


@pytest.fixture()
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = _write_world(tmp_path)
    ts_code, sdate, sclose, ohlc, gross = _LADDER_ROW
    t1 = next_session_after(_SESSIONS, sdate)
    _write_daily(base, ts_code, t1, ohlc)
    row = _event_row(ts_code, sdate, sclose, gross)
    row["gap_t1_open"] = ohlc[0] / sclose - 1
    row["exit_open_t10"] = _EXIT_OPEN_LADDER
    table = base / "event_table_ladder.csv.gz"
    original = pd.read_csv(base / "event_table_v1.csv.gz")
    pd.concat([original, pd.DataFrame([row])]).to_csv(
        table, index=False, compression="gzip"
    )
    monkeypatch.setattr(
        court_common, "_TRADE_CAL_PATH", base / "trade_calendar.json"
    )
    return base


def _ladder(world: Path) -> dict:
    universe = counterfactual.load_universe(world / "event_table_ladder.csv.gz")
    rows_by_tolerance = build_ladder(
        universe, raw_dir=world / "raw" / "daily", sessions=_SESSIONS
    )
    return assemble_ladder(
        rows_by_tolerance, window={"start": "20250701", "end": "20250704"}
    )


# ---------------------------------------------------------------------------
# 跨工具一致性 / 档位语义
# ---------------------------------------------------------------------------

def test_t0_rows_identical_to_counterfactual_tool(world: Path) -> None:
    # 跨工具单一实现钉: t=0 档与 Op1 工具 build_rows 默认语义逐行一致
    universe = counterfactual.load_universe(world / "event_table_ladder.csv.gz")
    base_rows = counterfactual.build_rows(
        universe, raw_dir=world / "raw" / "daily", sessions=_SESSIONS
    )
    t0_rows = build_ladder(
        universe,
        raw_dir=world / "raw" / "daily",
        sessions=_SESSIONS,
        tolerances=(0.0,),
    )[0.0]
    assert base_rows == t0_rows


def test_limit_cents_at_scales_and_fights_float_truncation() -> None:
    assert limit_cents_at(10.0, 0.0) == 1000
    assert limit_cents_at(10.0, 0.02) == 1020
    assert limit_cents_at(19.9, 0.0) == 1990  # 浮点截断陷阱同 Op1 钉
    assert limit_cents_at(4.1, 0.01) == 414


def test_fill_rate_non_decreasing_and_strict_rise_at_touch_rung(world: Path) -> None:
    ladder_report = _ladder(world)
    fill_rates = [
        rung["report"]["fill_rate"]
        for rung in ladder_report["rungs"]
    ]
    assert fill_rates == sorted(fill_rates)
    # 5 准入几何: B/C/D 三行 t=0 即成交; 600008 (gap 4%, low 10.20) 在
    # t=2% 限价 10.20 恰触及 → 3/5 → 4/5; 000001 (low 10.55) 全档 NO_FILL
    assert fill_rates[0] == pytest.approx(3 / 5)
    assert fill_rates[2] == pytest.approx(3 / 5)
    assert fill_rates[3] == pytest.approx(4 / 5)
    assert fill_rates[4] == pytest.approx(4 / 5)


def test_delta_exact_value_at_touch_rung(world: Path) -> None:
    # t=2%: 限价抬升同时改变成交集与成交价 — B 成交价 min(1060, 1020)=1020,
    # 600008 成交 min(1040, 1020)=1020, C/D 仍按开盘
    cost = counterfactual.ROUNDTRIP_COST
    rung = _ladder(world)["rungs"][3]
    report = rung["report"]
    assert rung["tolerance"] == 0.02
    b_gross = _EXIT_OPEN_T10["000002.SZ"] / 10.20 - 1
    ladder_gross = _EXIT_OPEN_LADDER / 10.20 - 1
    s1 = (
        0.0
        + (b_gross - cost)
        + (0.03 - cost)
        + (0.01 - cost)
        + (ladder_gross - cost)
    ) / 5
    s2 = (
        (0.02 - cost) + (-0.01 - cost) + (0.03 - cost) + (0.01 - cost)
        + (0.04 - cost)
    ) / 5
    assert report["s1_per_admitted_expectancy"] == pytest.approx(s1)
    assert report["s2_per_admitted_expectancy"] == pytest.approx(s2)
    assert report["delta_per_admitted"]["value"] == pytest.approx(s1 - s2)


def test_lock_bar_disclosed_unknown_at_every_rung(world: Path) -> None:
    # 一字涨停 (四价合一围栏) → UNKNOWN one_price_limit_up 各档如实披露,
    # 容忍度抬高不改变判定表语义
    t1 = next_session_after(_SESSIONS, "20250703")
    _write_daily(world, "600009.SH", t1, (11.00, 11.00, 11.00, 11.00, 10.00))
    lock = _event_row("600009.SH", "20250703", 10.00, 0.0)
    lock["gap_t1_open"] = 0.10
    lock["exit_open_t10"] = 11.2
    table = world / "event_table_lock.csv.gz"
    original = pd.read_csv(world / "event_table_ladder.csv.gz")
    pd.concat([original, pd.DataFrame([lock])]).to_csv(
        table, index=False, compression="gzip"
    )
    universe = counterfactual.load_universe(table)
    rows_by_tolerance = build_ladder(
        universe, raw_dir=world / "raw" / "daily", sessions=_SESSIONS
    )
    for tolerance, rows in rows_by_tolerance.items():
        lock_row = next(r for r in rows if r["ts_code"] == "600009.SH")
        assert lock_row["s1_verdict"] == "UNKNOWN", tolerance
        assert lock_row["s1_reason"] == "one_price_limit_up", tolerance
        assert lock_row["s1_fill_cents"] is None, tolerance


def test_gap_high_bucket_fill_recovers_with_tolerance(world: Path) -> None:
    # 高开桶 (gap ≥ 0.05: 000001/000002) 在 t=5% 档前部分恢复成交;
    # 600008 gap 4% 属低开桶 — 桶归属不随档位漂移
    ladder_report = _ladder(world)
    highs = [
        next(
            b for b in rung["report"]["buckets"] if b["label"] == "gap_high"
        )
        for rung in ladder_report["rungs"]
    ]
    assert highs[0]["admitted"] == 2
    assert highs[-1]["admitted"] == 2
    high_fill = [b["fill_rate"] for b in highs]
    assert high_fill == sorted(high_fill)
    # t=5%: 000002 (gap 6%) 开盘 10.60 > 限价 10.50, low 9.90 触及 →
    # FILLED; 000001 (gap 8%) low 10.55 > 10.50 → NO_FILL
    assert highs[-1]["filled"] == 1


# ---------------------------------------------------------------------------
# 报告渲染 / 确定性 / fail-closed
# ---------------------------------------------------------------------------

def test_render_md_contains_ladder_table(world: Path) -> None:
    md = render_md(_ladder(world))
    assert "入场限价容忍度梯子反事实" in md
    assert "| 0.0% |" in md and "| 5.0% |" in md
    assert "owner gate" in md
    assert "宪法 #13" in md


def test_ladder_json_serializable_and_deterministic(world: Path, tmp_path: Path) -> None:
    payload = json.dumps(_ladder(world), ensure_ascii=False, sort_keys=True)
    assert "NaN" not in payload
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    argv_common = [
        "--event-table", str(world / "event_table_ladder.csv.gz"),
        "--raw-dir", str(world / "raw" / "daily"),
    ]
    assert ladder.main([*argv_common, "--out-dir", str(out_a)]) == 0
    assert ladder.main([*argv_common, "--out-dir", str(out_b)]) == 0
    names = sorted(p.name for p in out_a.iterdir())
    assert names == [
        "entry_limit_tolerance_ladder_20250703.json",
        "entry_limit_tolerance_ladder_20250703.md",
    ]
    for name in names:
        assert (out_a / name).read_bytes() == (out_b / name).read_bytes()


def test_missing_event_table_fails_closed(world: Path, tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        ladder.main(
            ["--event-table", str(world / "absent.csv.gz"),
             "--raw-dir", str(world / "raw" / "daily"),
             "--out-dir", str(tmp_path / "out")]
        )


def test_missing_raw_dir_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        ladder.main(
            ["--event-table", str(tmp_path / "absent.csv.gz"),
             "--raw-dir", str(tmp_path / "absent-dir"),
             "--out-dir", str(tmp_path / "out")]
        )


def test_no_wall_clock_in_ladder(world: Path) -> None:
    ladder_report = _ladder(world)
    forbidden = {"generated_at", "now", "timestamp", "built_at"}
    assert not forbidden.intersection(ladder_report)
    assert set(TOLERANCES) == {
        rung["tolerance"] for rung in ladder_report["rungs"]
    }
