"""entry_limit_semantics_counterfactual 正确性回归网 (R210 Op1, hermetic fixture 世界).

固化入场限价执行语义反事实的契约: S1 (限价=信号收盘, 触及成交
min(open,limit)) 逐一复现 resolve_open_execution 判定 / S2 (开盘合约
口径) 基线 / 每准入期望差与配对聚类 CI / 高开低开桶分解 / 成交价
效应 / 缺失披露 / fail-closed 输入 / 确定性输出。

R208 补遗检查单: 全部测试零宿主 data/ 读取 (tmp fixture 世界);
trade calendar 经 _btst_court_common._TRADE_CAL_PATH monkeypatch 隔离。
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

import scripts._btst_court_common as court_common  # noqa: E402
import scripts.entry_limit_semantics_counterfactual as counterfactual  # noqa: E402
from scripts.entry_limit_semantics_counterfactual import (  # noqa: E402
    ROUNDTRIP_COST,
    assemble_report,
    bucket_split,
    build_rows,
    load_universe,
    next_session_after,
    render_md,
)

# ---------------------------------------------------------------------------
# fixture 世界: 40 个日历会话 + T+1 日线快照 + court 事件表
# ---------------------------------------------------------------------------

_CAL_START = pd.Timestamp("2025-07-01")
_SESSIONS = [
    (_CAL_START + pd.Timedelta(days=i)).strftime("%Y%m%d")
    for i in range(55)
    if (_CAL_START + pd.Timedelta(days=i)).weekday() < 5
]

# (ts_code, signal_date, signal_close, t1 open/high/low/close/pre_close,
#  gross_ret_t10)
_GEOMETRY = [
    # A: 高开不回踩 → S1 NO_FILL (limit_not_touched), S2 会赚 (静默丢弃的赢家)
    ("000001.SZ", "20250701", 10.00, (10.80, 11.00, 10.55, 10.90, 10.00), 0.02),
    # B: 高开回踩 → S1 触及成交于限价 (优于开盘), S2 亏
    ("000002.SZ", "20250701", 10.00, (10.60, 10.70, 9.90, 10.20, 10.00), -0.01),
    # C: 低开 → S1 于开盘成交 (与 S2 同价)
    ("300003.SZ", "20250702", 20.00, (19.50, 19.80, 19.20, 19.60, 20.00), 0.03),
    # D: 平开 → S1 于开盘成交 (与 S2 同价)
    ("300004.SZ", "20250702", 5.00, (5.00, 5.10, 4.95, 5.05, 5.00), 0.01),
]
# 与 _GEOMETRY 同序的 T+10 开盘价 (由入场= T+1 开盘 × (1+gross) 锚定)
_EXIT_OPEN_T10 = {
    "000001.SZ": 10.80 * 1.02,
    "000002.SZ": 10.60 * 0.99,
    "300003.SZ": 19.50 * 1.03,
    "300004.SZ": 5.00 * 1.01,
}


def _write_calendar(root: Path) -> None:
    payload = [
        f"{s[:4]}-{s[4:6]}-{s[6:8]}" for s in _SESSIONS
    ]
    (root / "trade_calendar.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_daily(root: Path, ts_code: str, session: str, ohlc: tuple) -> None:
    path = root / "raw" / "daily" / f"daily_{session}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts_code": ts_code,
        "trade_date": session,
        "open": ohlc[0],
        "high": ohlc[1],
        "low": ohlc[2],
        "close": ohlc[3],
        "pre_close": ohlc[4],
        "pct_chg": 1.0,
        "vol": 1000,
        "amount": 1000,
    }
    records = []
    if path.exists():
        records = pd.read_csv(path).to_dict("records")
    records.append(row)
    pd.DataFrame(records).to_csv(path, index=False)


def _event_row(
    ts_code: str,
    signal_date: str,
    signal_close: float,
    gross: float,
    *,
    fillable: bool = True,
    gate_blocked: bool = False,
) -> dict:
    return {
        "symbol": ts_code.split(".")[0],
        "ts_code": ts_code,
        "signal_date": signal_date,
        "regime": "normal",
        "trigger_strength": 0.60,
        "signal_close": signal_close,
        "gap_t1_open": None,  # 由 _write_world 填充
        "fillable": fillable,
        "t1_unbuyable": False,
        "t1_missing_bar": False,
        "degraded": False,
        "industry_missing": False,
        "industry_name": "x",
        "st_name": False,
        "excluded_ticker": False,
        "price_ge_3": True,
        "gate_blocked": gate_blocked,
        "exit_open_t10": _EXIT_OPEN_T10.get(ts_code),
        "gross_ret_t10": gross,
    }


def _write_world(tmp: Path, *, extra_rows: list[dict] | None = None) -> Path:
    """构建自足 fixture 世界, 返回项目式根目录 (calendar/raw/event-table)."""
    _write_calendar(tmp)
    rows = []
    for ts_code, sdate, sclose, ohlc, gross in _GEOMETRY:
        t1 = next_session_after(_SESSIONS, sdate)
        _write_daily(tmp, ts_code, t1, ohlc)
        row = _event_row(ts_code, sdate, sclose, gross)
        row["gap_t1_open"] = ohlc[0] / sclose - 1
        rows.append(row)
    rows.extend(extra_rows or [])
    table = tmp / "event_table_v1.csv.gz"
    pd.DataFrame(rows).to_csv(table, index=False, compression="gzip")
    return tmp


@pytest.fixture()
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _write_world(tmp_path)
    monkeypatch.setattr(
        court_common, "_TRADE_CAL_PATH", tmp_path / "trade_calendar.json"
    )
    return tmp_path


# ---------------------------------------------------------------------------
# 判定与行构建
# ---------------------------------------------------------------------------

def test_next_session_after_picks_following_session() -> None:
    assert next_session_after(_SESSIONS, "20250701") == "20250702"


def test_next_session_after_returns_none_past_calendar_end() -> None:
    assert next_session_after(_SESSIONS, _SESSIONS[-1]) is None


def test_s1_no_fill_when_high_gap_never_touches_limit(world: Path) -> None:
    rows = build_rows(
        load_universe(world / "event_table_v1.csv.gz"),
        raw_dir=world / "raw" / "daily",
        sessions=_SESSIONS,
    )
    a = next(r for r in rows if r["ts_code"] == "000001.SZ")
    assert a["s1_verdict"] == "NO_FILL"
    assert a["s1_reason"] == "limit_not_touched"
    assert a["s1_fill_cents"] is None
    assert a["s1_net"] is None


def test_s1_fills_at_limit_when_gap_up_pulls_back(world: Path) -> None:
    rows = build_rows(
        load_universe(world / "event_table_v1.csv.gz"),
        raw_dir=world / "raw" / "daily",
        sessions=_SESSIONS,
    )
    b = next(r for r in rows if r["ts_code"] == "000002.SZ")
    assert b["s1_verdict"] == "FILLED"
    assert b["s1_fill_cents"] == 1000  # min(open 1060, limit 1000)
    expected = _EXIT_OPEN_T10["000002.SZ"] / 10.00 - 1 - ROUNDTRIP_COST
    assert b["s1_net"] == pytest.approx(expected)


def test_s1_fills_at_open_when_open_at_or_below_limit(world: Path) -> None:
    rows = build_rows(
        load_universe(world / "event_table_v1.csv.gz"),
        raw_dir=world / "raw" / "daily",
        sessions=_SESSIONS,
    )
    by_code = {r["ts_code"]: r for r in rows}
    assert by_code["300003.SZ"]["s1_fill_cents"] == 1950  # = open
    assert by_code["300004.SZ"]["s1_fill_cents"] == 500  # = open = limit


def test_universe_excludes_gate_blocked_rows(tmp_path: Path, monkeypatch) -> None:
    blocked = _event_row("600005.SH", "20250703", 8.0, 0.0, gate_blocked=True)
    _write_world(tmp_path, extra_rows=[blocked])
    monkeypatch.setattr(
        court_common, "_TRADE_CAL_PATH", tmp_path / "trade_calendar.json"
    )
    universe = load_universe(tmp_path / "event_table_v1.csv.gz")
    assert "600005.SH" not in set(universe["ts_code"])


def test_missing_t1_bar_file_becomes_disclosed_unknown(
    world: Path,
) -> None:
    (world / "raw" / "daily" / "daily_20250702.csv").unlink()
    rows = build_rows(
        load_universe(world / "event_table_v1.csv.gz"),
        raw_dir=world / "raw" / "daily",
        sessions=_SESSIONS,
    )
    unknown = [r for r in rows if r["s1_verdict"] == "UNKNOWN"]
    assert {r["ts_code"] for r in unknown} == {"000001.SZ", "000002.SZ"}
    assert all(r["s1_reason"] == "missing_t1_bar" for r in unknown)


# ---------------------------------------------------------------------------
# 聚合: 每准入期望 / delta / 桶分解 / 价格效应
# ---------------------------------------------------------------------------

def _report(world: Path) -> dict:
    universe = load_universe(world / "event_table_v1.csv.gz")
    rows = build_rows(universe, raw_dir=world / "raw" / "daily", sessions=_SESSIONS)
    return assemble_report(rows, window={"start": "20250701", "end": "20250702"})


def test_fill_rate_counts(world: Path) -> None:
    report = _report(world)
    assert report["counts"] == {
        "admitted": 4,
        "filled": 3,
        "no_fill": 1,
        "unknown": 0,
        "missing_exit": 0,
    }
    assert report["fill_rate"] == pytest.approx(0.75)


def test_per_admitted_expectancy_exact_values(world: Path) -> None:
    report = _report(world)
    cost = ROUNDTRIP_COST
    # B 的 S1 gross: exit 10.494 / 限价入场 10.00 − 1
    b_s1_gross = _EXIT_OPEN_T10["000002.SZ"] / 10.00 - 1
    # S1: A 未成交贡献 0; B/C/D 以各自成交价入场
    s1 = (0.0 + (b_s1_gross - cost) + (0.03 - cost) + (0.01 - cost)) / 4
    # S2: 全体按 T+1 开盘入场 (逐行扣费)
    s2 = ((0.02 - cost) + (-0.01 - cost) + (0.03 - cost) + (0.01 - cost)) / 4
    assert report["s1_per_admitted_expectancy"] == pytest.approx(s1)
    assert report["s2_per_admitted_expectancy"] == pytest.approx(s2)
    assert report["delta_per_admitted"]["value"] == pytest.approx(s1 - s2)


def test_delta_ci_paired_and_deterministic(
    world: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # n=4 < MIN_CELL_N(30) 时 CI 诚实缺席; 降低门槛验证 CI 面本身。
    monkeypatch.setattr(counterfactual, "MIN_CELL_N", 4)
    universe = load_universe(world / "event_table_v1.csv.gz")
    rows = build_rows(universe, raw_dir=world / "raw" / "daily", sessions=_SESSIONS)
    first = assemble_report(rows, window={"start": "20250701", "end": "20250702"})
    second = assemble_report(rows, window={"start": "20250701", "end": "20250702"})
    ci_a = first["delta_per_admitted"]["cluster_ci"]
    ci_b = second["delta_per_admitted"]["cluster_ci"]
    assert ci_a == ci_b
    value = first["delta_per_admitted"]["value"]
    assert ci_a["ci_low"] <= value <= ci_a["ci_high"]


def test_bucket_split_high_vs_low(world: Path) -> None:
    report = _report(world)
    buckets = {b["label"]: b for b in bucket_split(
        build_rows(
            load_universe(world / "event_table_v1.csv.gz"),
            raw_dir=world / "raw" / "daily",
            sessions=_SESSIONS,
        )
    )}
    assert buckets["gap_high"]["admitted"] == 2
    assert buckets["gap_high"]["filled"] == 1
    assert buckets["gap_high"]["fill_rate"] == pytest.approx(0.5)
    assert buckets["gap_low"]["admitted"] == 2
    assert buckets["gap_low"]["fill_rate"] == pytest.approx(1.0)
    # 桶级 ΔE 必须是标量浮点 (尾逗号 1 元组曾使渲染面 n/a)
    assert isinstance(buckets["gap_high"]["s1_per_admitted_expectancy"], float)
    # S1 每准入 = 未成交 0 + 成交净收益 → 高开桶: B 净 − A 的 S2 被跳过
    cost = ROUNDTRIP_COST
    b_s1_gross = _EXIT_OPEN_T10["000002.SZ"] / 10.00 - 1
    expected_high = (0.0 + (b_s1_gross - cost)) / 2 - ((0.02 - cost) + (-0.01 - cost)) / 2
    assert buckets["gap_high"]["s1_per_admitted_expectancy"] == pytest.approx(
        expected_high
    )
    # 高开桶静默丢弃的 S2 期望 (A 是赢家) 必须显形
    assert buckets["gap_high"]["unfilled_s2_expectancy"] is not None
    assert buckets["gap_high"]["unfilled_s2_expectancy"] > 0


def test_price_effect_never_worse_than_open(world: Path) -> None:
    report = _report(world)
    effect = report["price_effect"]
    assert effect["n"] == 3
    assert effect["mean_rel_vs_open"] <= 0.0
    # 仅 B (1060→1000) 有价差, C/D 平价
    expected = (1000 / 1060 - 1 + 0.0 + 0.0) / 3
    assert effect["mean_rel_vs_open"] == pytest.approx(expected)


def test_filled_and_unfilled_sets_disclosed(world: Path) -> None:
    report = _report(world)
    filled = report["s1_filled"]
    unfilled = report["s1_unfilled_would_be"]
    assert filled["n"] == 3
    b_s1_gross = _EXIT_OPEN_T10["000002.SZ"] / 10.00 - 1
    cost = ROUNDTRIP_COST
    assert filled["expectancy"] == pytest.approx(
        (b_s1_gross - cost + 0.03 - cost + 0.01 - cost) / 3
    )
    assert unfilled["n"] == 1
    assert unfilled["expectancy"] == pytest.approx(0.02 - ROUNDTRIP_COST)


# ---------------------------------------------------------------------------
# 报告渲染与确定性
# ---------------------------------------------------------------------------

def test_render_md_contains_decision_lines(world: Path) -> None:
    report = _report(world)
    md = render_md(report)
    assert "每准入期望差" in md
    assert "限价==信号快照价" in md
    assert "owner gate" in md
    assert "不改变计划与执行决策" in md


def test_assemble_report_is_json_serializable(world: Path) -> None:
    payload = json.dumps(_report(world), ensure_ascii=False, sort_keys=True)
    assert "NaN" not in payload


def test_full_pipeline_writes_deterministic_files(world: Path, tmp_path: Path) -> None:
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    rc_a = counterfactual.main(
        ["--event-table", str(world / "event_table_v1.csv.gz"),
         "--raw-dir", str(world / "raw" / "daily"),
         "--out-dir", str(out_a)]
    )
    rc_b = counterfactual.main(
        ["--event-table", str(world / "event_table_v1.csv.gz"),
         "--raw-dir", str(world / "raw" / "daily"),
         "--out-dir", str(out_b)]
    )
    assert rc_a == rc_b == 0
    files_a = sorted(p.name for p in out_a.iterdir())
    files_b = sorted(p.name for p in out_b.iterdir())
    assert files_a == files_b and len(files_a) == 2
    for name in files_a:
        assert (out_a / name).read_bytes() == (out_b / name).read_bytes()


def test_missing_event_table_fails_closed(world: Path, tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        counterfactual.main(
            ["--event-table", str(world / "absent.csv.gz"),
             "--raw-dir", str(world / "raw" / "daily"),
             "--out-dir", str(tmp_path / "out")]
        )


def test_missing_calendar_fails_closed(tmp_path: Path, monkeypatch) -> None:
    _write_world(tmp_path)
    monkeypatch.setattr(
        court_common, "_TRADE_CAL_PATH", tmp_path / "absent_calendar.json"
    )
    with pytest.raises(SystemExit):
        counterfactual.main(
            ["--event-table", str(tmp_path / "event_table_v1.csv.gz"),
             "--raw-dir", str(tmp_path / "raw" / "daily"),
             "--out-dir", str(tmp_path / "out")]
        )


def test_window_end_names_report_files(world: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert counterfactual.main(
        ["--event-table", str(world / "event_table_v1.csv.gz"),
         "--raw-dir", str(world / "raw" / "daily"),
         "--out-dir", str(out)]
    ) == 0
    names = sorted(p.name for p in out.iterdir())
    assert names == [
        "entry_limit_semantics_counterfactual_20250702.json",
        "entry_limit_semantics_counterfactual_20250702.md",
    ]


def test_no_wall_clock_in_report(world: Path) -> None:
    report = _report(world)
    forbidden = {"generated_at", "now", "timestamp", "built_at"}
    assert not forbidden.intersection(report)


# ---------------------------------------------------------------------------
# R210 Op2 对抗性钉 (变异探针真盲区收口; 7 钉 + 1 不变量钉)
# ---------------------------------------------------------------------------

def _bucket_row(gap: float) -> dict:
    return {
        "gap_t1_open": gap,
        "s1_verdict": "FILLED",
        "s2_net": 0.01,
        "s1_net": 0.0,
        "signal_date": "20250701",
    }


def test_bucket_boundary_gap_exactly_at_threshold_is_high() -> None:
    # P05/P06: gap == GAP_HIGH_THRESHOLD 必须归高开桶 (>= 与 < 互斥完备,
    # 边界行不得在重构中静默换桶或双计)
    boundary = _bucket_row(counterfactual.GAP_HIGH_THRESHOLD)
    just_below = _bucket_row(counterfactual.GAP_HIGH_THRESHOLD - 1e-9)
    buckets = {
        b["label"]: b for b in bucket_split([boundary, just_below])
    }
    assert buckets["gap_high"]["admitted"] == 1
    assert buckets["gap_low"]["admitted"] == 1


def test_limit_cents_rejects_float_truncation() -> None:
    # P11: 19.9/4.1 的 ×100 落在浮点截断陷阱 (1989.99…/409.99…),
    # int() 直转少 1 分, 必须 round 吸收误差
    assert counterfactual._limit_cents(19.9) == 1990
    assert counterfactual._limit_cents(4.1) == 410
    assert counterfactual._limit_cents(10.0) == 1000


def test_price_effect_counts_only_strictly_better(world: Path) -> None:
    # P10: 平价成交行 (open==limit, C/D) 不得计入优于开盘
    report = _report(world)
    assert report["price_effect"]["n"] == 3
    assert report["price_effect"]["n_better_than_open"] == 1


def test_one_price_limit_up_t1_is_disclosed_unknown(world: Path) -> None:
    # P04: T+1 涨停一字 (四价合一于围栏) → UNKNOWN one_price_limit_up
    # 如实披露, 绝不误并成交集 — 涨停突破策略的核心人群, 此前无行为钉
    t1 = next_session_after(_SESSIONS, "20250703")
    _write_daily(world, "600006.SH", t1, (11.00, 11.00, 11.00, 11.00, 10.00))
    lock = _event_row("600006.SH", "20250703", 10.00, 0.0)
    lock["gap_t1_open"] = 0.10
    lock["exit_open_t10"] = 11.2
    table = world / "event_table_lock.csv.gz"
    base = pd.read_csv(world / "event_table_v1.csv.gz")
    pd.concat([base, pd.DataFrame([lock])]).to_csv(
        table, index=False, compression="gzip"
    )
    rows = build_rows(
        load_universe(table), raw_dir=world / "raw" / "daily", sessions=_SESSIONS
    )
    lock_row = next(r for r in rows if r["ts_code"] == "600006.SH")
    assert lock_row["s1_verdict"] == "UNKNOWN"
    assert lock_row["s1_reason"] == "one_price_limit_up"
    assert lock_row["s1_fill_cents"] is None
    assert lock_row["s1_net"] is None


def test_unknown_rows_disclosure_keeps_all_within_cap(world: Path) -> None:
    # P14: cap(50) 内的 UNKNOWN 披露必须全量保留, 截断不得静默收窄
    extra = []
    for i in range(6):
        row = _event_row(f"60010{i}.SH", "20250703", 9.0 + i, 0.0)
        row["gap_t1_open"] = 0.01
        row["exit_open_t10"] = 9.5 + i
        extra.append(row)
    table = world / "event_table_unknown.csv.gz"
    base = pd.read_csv(world / "event_table_v1.csv.gz")
    pd.concat([base, pd.DataFrame(extra)]).to_csv(
        table, index=False, compression="gzip"
    )
    rows = build_rows(
        load_universe(table), raw_dir=world / "raw" / "daily", sessions=_SESSIONS
    )
    report = assemble_report(
        rows, window={"start": "20250701", "end": "20250704"}
    )
    assert report["counts"]["unknown"] == 6
    assert len(report["unknown_rows"]) == 6


def test_render_md_prints_ci_low_before_high(
    world: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # P15: CI 展示必须 [low, high] 次序 (决策阅读面反转即 RED)
    monkeypatch.setattr(counterfactual, "MIN_CELL_N", 4)
    universe = load_universe(world / "event_table_v1.csv.gz")
    rows = build_rows(
        universe, raw_dir=world / "raw" / "daily", sessions=_SESSIONS
    )
    report = assemble_report(
        rows, window={"start": "20250701", "end": "20250702"}
    )
    ci = report["delta_per_admitted"]["cluster_ci"]
    assert ci is not None
    md = render_md(report)
    fmt = counterfactual._fmt
    assert md.index(fmt(ci["ci_low"])) < md.index(fmt(ci["ci_high"]))


def test_universe_rows_always_have_s2_net(world: Path) -> None:
    # P13 等价性的不变量钉: candidate_universe 要求 gross_ret_t10 非空,
    # 故 admitted 行 s2_net 恒非 None (paired == rows, 稀释分支不可达)。
    # 该不变量若失效 (宇宙口径演化), P13 稀释变异即成为真盲区。
    rows = build_rows(
        load_universe(world / "event_table_v1.csv.gz"),
        raw_dir=world / "raw" / "daily",
        sessions=_SESSIONS,
    )
    assert rows and all(r["s2_net"] is not None for r in rows)
