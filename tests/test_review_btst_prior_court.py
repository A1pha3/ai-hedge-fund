"""review_btst_prior_court 纯函数回归网 (合成 fixture, 不依赖真实事件表)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import review_btst_prior_court as rpc  # noqa: E402


def _ev(rows: list[dict]) -> pd.DataFrame:
    cols = ["signal_date", "trigger_strength", "fillable", "gate_blocked", "gross_ret_t10", "regime"]
    df = pd.DataFrame(rows, columns=cols)
    return df.astype({"signal_date": str})


_PROD_DEFAULTS = {
    "degraded": False, "st_name": False, "industry_missing": False,
    "excluded_ticker": False, "price_ge_3": True,
}


def _ev_prod(rows: list[dict]) -> pd.DataFrame:
    """带生产过滤链列的 fixture (degraded/st/行业缺失/excluded/price<3)."""
    df = pd.DataFrame([{**_PROD_DEFAULTS, **r} for r in rows])
    return df.astype({"signal_date": str})


def test_net_cost_65bps_exact():
    assert rpc.net_ret(pd.Series([0.10, 0.0, -0.05])).tolist() == [0.0935, -0.0065, -0.0565]


def test_universe_filter_excludes_unfillable_gated_missing():
    ev = _ev([
        {"signal_date": "20260101", "trigger_strength": 0.9, "fillable": True, "gate_blocked": False, "gross_ret_t10": 0.02, "regime": "normal"},
        {"signal_date": "20260101", "trigger_strength": 0.9, "fillable": False, "gate_blocked": False, "gross_ret_t10": 0.02, "regime": "normal"},
        {"signal_date": "20260101", "trigger_strength": 0.9, "fillable": True, "gate_blocked": True, "gross_ret_t10": 0.02, "regime": "crisis"},
        {"signal_date": "20260101", "trigger_strength": 0.9, "fillable": True, "gate_blocked": False, "gross_ret_t10": None, "regime": "normal"},
    ])
    u = rpc.candidate_universe(ev)
    assert len(u) == 1


def test_stats_block_known_values():
    r = pd.Series([0.10, -0.05, 0.02])
    s = rpc.stats_block(r, days=pd.Series(["a", "a", "b"]), n_boot=200)
    assert s["n"] == 3
    assert abs(s["mean"] - r.mean()) < 1e-12
    assert abs(s["winrate"] - 2 / 3) < 1e-12
    assert s["ci90_low"] <= s["mean"] <= s["ci90_high"]


def test_stats_block_empty_is_honest():
    s = rpc.stats_block(pd.Series(dtype=float), days=pd.Series(dtype=object), n_boot=10)
    assert s["n"] == 0
    assert s["mean"] is None and s["winrate"] is None and s["ci90_low"] is None


def test_quintile_labels_and_monotone_boundaries():
    rows = []
    for i in range(10):
        rows.append({"signal_date": f"2026010{i%3}", "trigger_strength": 0.1 * (i + 1) - 0.05,
                     "fillable": True, "gate_blocked": False,
                     "gross_ret_t10": 0.01 * i - 0.04, "regime": "normal"})
    q = rpc.strength_quintiles(_ev(rows), n_boot=100)
    assert [g["label"] for g in q] == ["Q1", "Q2", "Q3", "Q4", "Q5"]
    assert sum(g["n"] for g in q) == 10
    assert q[0]["strength_min"] <= q[0]["strength_max"] < q[1]["strength_min"]


def test_daily_topk_nav_compounds_equal_weight():
    rows = [
        {"signal_date": "20260101", "trigger_strength": 0.9, "fillable": True, "gate_blocked": False, "gross_ret_t10": 0.10, "regime": "normal"},
        {"signal_date": "20260101", "trigger_strength": 0.8, "fillable": True, "gate_blocked": False, "gross_ret_t10": -0.10, "regime": "normal"},
        {"signal_date": "20260102", "trigger_strength": 0.7, "fillable": True, "gate_blocked": False, "gross_ret_t10": 0.02, "regime": "normal"},
    ]
    ev = _ev(rows)
    # 净口径 = 毛 - 0.0065 (65bps): day1 净 0.0935 / -0.1065, day2 净 0.0135
    # top-1: 01 取 0.9 → 0.0935; 02 取 0.7 → 0.0135 → NAV = 1.0935 * 1.0135
    t1 = rpc.daily_topk(ev, 1, n_boot=100)
    assert abs(t1["trade_mean"] - (0.0935 + 0.0135) / 2) < 1e-12
    assert abs(t1["nav_compound"] - 1.0935 * 1.0135) < 1e-9
    # top-2: 01 等权 (0.0935-0.1065)/2 = -0.0065; 02 仅 1 笔 0.0135 → NAV = 0.9935 * 1.0135
    t2 = rpc.daily_topk(ev, 2, n_boot=100)
    assert abs(t2["nav_compound"] - 0.9935 * 1.0135) < 1e-9


def test_deviation_ratios_hand_computed():
    prior = {"expected_return": 0.06, "winrate": 0.60}
    court = {"mean": 0.015, "winrate": 0.45}
    d = rpc.deviation_block(court, prior)
    assert abs(d["er_multiple"] - 4.0) < 1e-12
    assert abs(d["er_delta_pp"] - 4.5) < 1e-12
    assert abs(d["winrate_delta_pp"] - 15.0) < 1e-12


def test_report_includes_fingerprint_and_boundary():
    ev = _ev_prod([
        {"signal_date": "20260101", "trigger_strength": 0.6, "fillable": True, "gate_blocked": False, "gross_ret_t10": 0.01, "regime": "normal"},
    ])
    rep = rpc.build_report(ev, n_boot=50)
    fp = rep["fingerprint"]
    assert fp["rows"] == 1 and fp["date_min"] == "20260101"
    assert fp["prior"]["expected_return"] == 0.0056  # 生产常量原样引用 (2026-08-19 court 重校准值)
    assert "boundary" in rep and "不进 Kelly" in rep["boundary"]
    # 结构稳定: 无 blocked 行时返回诚实空结构而非 None
    assert rep["gate_blocked_contrast"]["n"] == 0
    assert rep["gate_blocked_contrast"]["mean"] is None


def test_gate_blocked_contrast_survives_when_present():
    ev = _ev_prod([
        {"signal_date": "20260101", "trigger_strength": 0.6, "fillable": True, "gate_blocked": False, "gross_ret_t10": 0.01, "regime": "normal"},
        {"signal_date": "20260101", "trigger_strength": 0.6, "fillable": True, "gate_blocked": True, "gross_ret_t10": -0.30, "regime": "crisis"},
    ])
    rep = rpc.build_report(ev, n_boot=50)
    assert rep["gate_blocked_contrast"]["n"] == 1
    assert abs(rep["gate_blocked_contrast"]["mean"] - (-0.3065)) < 1e-12  # 净口径: -0.30 - 65bps


def test_cluster_bootstrap_is_deterministic_per_seed():
    r = pd.Series(np.linspace(-0.05, 0.10, 60))
    days = pd.Series([f"d{i//6}" for i in range(60)])
    a = rpc.cluster_boot_ci_low(r, days, n_boot=300)
    b = rpc.cluster_boot_ci_low(r, days, n_boot=300)
    assert a == b


# ---- Round B: 事件表新鲜度 × 公式漂移守卫 ----

from datetime import date  # noqa: E402


def _manifest(built_at: str, setup_sha: str = "a" * 64) -> dict:
    return {
        "version": 1,
        "built_at": built_at,
        "formula_fingerprint": {"btst_breakout_sha256": setup_sha},
        "window": {"start": "20250701", "end": "20260815", "sessions": 268},
    }


def test_freshness_age_days_exact_and_boundary():
    today = date(2026, 10, 1)
    f = rpc.table_freshness(_manifest("2026-08-17"), "b" * 64, today)
    assert f["age_days"] == 45
    g = rpc.table_freshness(_manifest("2026-08-16"), "b" * 64, today)
    assert g["age_days"] == 46


def test_freshness_formula_match_boolean():
    m = _manifest("2026-08-17", setup_sha="a" * 64)
    ok = rpc.table_freshness(m, "a" * 64, date(2026, 8, 18))
    bad = rpc.table_freshness(m, "b" * 64, date(2026, 8, 18))
    assert ok["formula_match"] is True
    assert bad["formula_match"] is False


def test_freshness_missing_manifest_is_honest():
    f = rpc.table_freshness(None, "a" * 64, date(2026, 8, 18))
    assert f["manifest_present"] is False
    assert f["age_days"] is None and f["formula_match"] is None


def test_run_check_fails_closed_on_stale_or_drifted_table(tmp_path, monkeypatch, capsys):
    import pandas as _pd

    rows = [
        {"signal_date": "20260101", "trigger_strength": 0.9, "fillable": True,
         "gate_blocked": False, "gross_ret_t10": 0.02, "regime": "normal"},
        {"signal_date": "20260102", "trigger_strength": 0.8, "fillable": True,
         "gate_blocked": False, "gross_ret_t10": -0.01, "regime": "normal"},
    ]
    ev = _pd.DataFrame(rows)
    today = date(2026, 10, 1)  # 表龄 46 天 (>45)
    monkeypatch.setattr(rpc, "load_manifest", lambda: _manifest("2026-08-16", setup_sha="a" * 64))
    monkeypatch.setattr(rpc, "current_setup_sha", lambda: "b" * 64)  # 公式也漂移
    try:
        rpc.run_check(ev, today=today)
        raise AssertionError("stale+drifted table must fail closed")
    except SystemExit as exc:
        assert exc.code != 0
    out = capsys.readouterr().out + capsys.readouterr().err
    assert "btst_court_fetch" in out and "btst_court_build" in out  # 重建指引


def test_report_fingerprint_discloses_freshness():
    ev = _ev_prod([
        {"signal_date": "20260101", "trigger_strength": 0.6, "fillable": True,
         "gate_blocked": False, "gross_ret_t10": 0.01, "regime": "normal"},
    ])
    rep = rpc.build_report(ev, n_boot=50)
    fp = rep["fingerprint"]
    for key in ("manifest_present", "built_at", "age_days",
                "manifest_setup_sha", "current_setup_sha", "formula_match"):
        assert key in fp, key


# ---- Round C: 生产对齐宇宙 / 排除行披露 / 时间切片 (owner 重校准决策材料完整性) ----

import pytest  # noqa: E402


def _prod_row(sd, ret, strength=0.6, **kw):
    row = {"signal_date": sd, "trigger_strength": strength, "fillable": True,
           "gate_blocked": False, "gross_ret_t10": ret, "regime": "normal"}
    row.update(kw)
    return row


def test_production_universe_excludes_pipeline_filtered_rows():
    ev = _ev_prod([
        _prod_row("20260101", 0.02),                                   # 干净 → 保留
        _prod_row("20260101", -0.30, degraded=True),                   # degraded → 排除
        _prod_row("20260101", -0.20, st_name=True),                    # ST → 排除
        _prod_row("20260101", -0.10, industry_missing=True),           # 行业缺失 → 排除
        _prod_row("20260101", -0.05, excluded_ticker=True),            # 排除名单 → 排除
        _prod_row("20260101", -0.04, price_ge_3=False),                # 低价 → 排除
    ])
    u = rpc.candidate_universe(ev)
    p = rpc.production_universe(u)
    assert len(u) == 6 and len(p) == 1
    assert abs(rpc.net_ret(p["gross_ret_t10"]).iloc[0] - (0.02 - 0.0065)) < 1e-12


def test_production_universe_fails_closed_on_missing_columns():
    ev = _ev([_prod_row("20260101", 0.02)])  # 无生产过滤列
    u = rpc.candidate_universe(ev)
    with pytest.raises(Exception):
        rpc.production_universe(u)


def test_exclusion_disclosure_reports_each_dimension():
    ev = _ev_prod([
        _prod_row("20260101", -0.30, degraded=True),                   # 净 -0.3065
        _prod_row("20260101", 0.02),                                   # 干净 (不在披露内)
        _prod_row("20260101", -0.04, price_ge_3=False),                # 净 -0.0465
    ])
    u = rpc.candidate_universe(ev)
    d = rpc.exclusion_disclosure(u)
    groups = {g["key"]: g for g in d["groups"]}
    assert groups["degraded"]["n"] == 1
    assert abs(groups["degraded"]["mean"] - (-0.3065)) < 1e-12
    assert groups["price_lt_3"]["n"] == 1
    assert abs(groups["price_lt_3"]["mean"] - (-0.0465)) < 1e-12
    assert d["total_excluded"] == 2 and d["retained"] == 1
    # 空维度的组也出现 (n=0, mean=None) — 诚实披露全部维度
    assert groups["st_name"]["n"] == 0 and groups["st_name"]["mean"] is None


def test_time_slices_partition_and_top1():
    rows = []
    # 2025H2: 2 天各 2 笔; 2026H1: 1 天 2 笔; 2026H2+: 1 天 2 笔
    for sd, strengths, rets in (
        ("20250801", (0.9, 0.5), (0.10, -0.02)),
        ("20250901", (0.8, 0.6), (0.04, -0.03)),
        ("20260302", (0.9, 0.5), (0.02, -0.05)),
        ("20260706", (0.7, 0.5), (0.06, 0.01)),
    ):
        for s, r in zip(strengths, rets):
            rows.append(_prod_row(sd, r, strength=s))
    ev = _ev_prod(rows)
    u = rpc.production_universe(rpc.candidate_universe(ev))
    ts = rpc.time_slices(u, n_boot=100)
    labels = [t["label"] for t in ts]
    # R90 Op3: 窗口前扩重注册 — 切片表含 2025H1 段
    assert labels == ["2025H1", "2025H2", "2026H1", "2026H2+"]
    assert sum(t["n"] for t in ts) == len(u)  # 切片完备覆盖不重不漏
    h25 = {t["label"]: t for t in ts}["2025H2"]  # 按 label 取 (2025H1 前插后 ts[0] 不再是本段)
    assert h25["n"] == 4
    # top_1: 每天最高强度 → 2025H2 取 0.9(+0.10) 与 0.8(+0.04), 净后均值
    exp_top1 = ((0.10 - 0.0065) + (0.04 - 0.0065)) / 2
    assert abs(h25["top_1"]["trade_mean"] - exp_top1) < 1e-12
    assert h25["top_1"]["n"] == 2


def test_time_slices_empty_segment_is_honest():
    ev = _ev_prod([_prod_row("20260302", 0.02)])
    u = rpc.production_universe(rpc.candidate_universe(ev))
    ts = rpc.time_slices(u, n_boot=10)
    seg = {t["label"]: t for t in ts}
    assert seg["2026H1"]["n"] == 1
    assert seg["2025H2"]["n"] == 0 and seg["2025H2"]["mean"] is None


def test_build_report_mounts_new_views():
    ev = _ev_prod([
        _prod_row("20260302", 0.02),
        _prod_row("20260302", -0.30, degraded=True),
    ])
    rep = rpc.build_report(ev, n_boot=50)
    assert rep["production_aligned"]["n"] == 1
    assert abs(rep["production_aligned"]["mean"] - (0.02 - 0.0065)) < 1e-12
    assert rep["exclusion_disclosure"]["total_excluded"] == 1
    assert any(t["label"] == "2026H1" for t in rep["time_slices"])
    assert "production_aligned" in rep["deviation"]
    # 现行宇宙口径并列保留 (n 含 degraded 行)
    assert rep["all_candidates"]["n"] == 2


def test_render_md_contains_new_sections():
    ev = _ev_prod([
        _prod_row("20260302", 0.02),
        _prod_row("20260302", -0.30, degraded=True),
    ])
    md = rpc.render_md(rpc.build_report(ev, n_boot=50))
    assert "生产对齐宇宙" in md
    assert "排除行披露" in md
    assert "时间切片" in md
    assert "2026H1" in md


def test_time_slices_cover_extended_window_2025h1():
    """R90 Op3: 窗口前扩 (20250102) 后预注册切片表补 2025H1 段 —
    新审计段进时间切片视图, partition 覆盖前扩行。"""
    rows = []
    for sd, rets in (
        ("20250310", (0.05, -0.02)),   # 2025H1 (前扩新增段)
        ("20250801", (0.10, -0.02)),   # 2025H2
        ("20260302", (0.02, -0.05)),   # 2026H1
    ):
        for r in rets:
            rows.append(_prod_row(sd, r))
    ev = _ev_prod(rows)
    u = rpc.production_universe(rpc.candidate_universe(ev))
    ts = rpc.time_slices(u, n_boot=100)
    labels = [t["label"] for t in ts]
    assert labels == ["2025H1", "2025H2", "2026H1", "2026H2+"]
    assert sum(t["n"] for t in ts) == len(u)  # 不重不漏含前扩行
    h1 = ts[0]
    assert h1["n"] == 2
    assert abs(h1["mean"] - ((0.05 - 0.0065) + (-0.02 - 0.0065)) / 2) < 1e-12


def test_time_slices_outside_rows_fail_closed():
    """越界行 (切片表未覆盖的窗口移动) → fail-closed, 不静默缺段。"""
    import pytest
    ev = _ev_prod([
        _prod_row("20241231", 0.02),   # 早于全部预注册切片
        _prod_row("20260302", 0.02),
    ])
    u = rpc.production_universe(rpc.candidate_universe(ev))
    with pytest.raises(ValueError, match="1"):
        rpc.time_slices(u, n_boot=10)


def test_time_slices_2025h1_empty_segment_is_honest():
    """新段空段诚实披露 (n=0/mean=None)。"""
    ev = _ev_prod([_prod_row("20260302", 0.02)])
    u = rpc.production_universe(rpc.candidate_universe(ev))
    ts = rpc.time_slices(u, n_boot=10)
    seg = {t["label"]: t for t in ts}
    assert seg["2025H1"]["n"] == 0 and seg["2025H1"]["mean"] is None
