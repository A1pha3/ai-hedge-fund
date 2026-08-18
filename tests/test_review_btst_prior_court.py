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
    ev = _ev([
        {"signal_date": "20260101", "trigger_strength": 0.6, "fillable": True, "gate_blocked": False, "gross_ret_t10": 0.01, "regime": "normal"},
    ])
    rep = rpc.build_report(ev, n_boot=50)
    fp = rep["fingerprint"]
    assert fp["rows"] == 1 and fp["date_min"] == "20260101"
    assert fp["prior"]["expected_return"] == 0.0657  # 生产常量原样引用
    assert "boundary" in rep and "不进 Kelly" in rep["boundary"]
    # 结构稳定: 无 blocked 行时返回诚实空结构而非 None
    assert rep["gate_blocked_contrast"]["n"] == 0
    assert rep["gate_blocked_contrast"]["mean"] is None


def test_gate_blocked_contrast_survives_when_present():
    ev = _ev([
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
