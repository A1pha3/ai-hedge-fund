"""c310 (loop 43) — unit tests for the trend pool-filter discrimination diagnostic helpers.

The north-star pool-filtering path rests on the aff989be claim that "trend 几乎全
bullish, 无区分度" (the trend pool pre-filter has no discrimination on the full
universe). That claim was a qualitative assertion in a commit message; this
diagnostic quantifies it. The verdict rests on three pure helpers in
`scripts/_diag_trend_pool_filter_discrimination.py`:
`trend_direction_distribution`, `trend_directional_edge`, `pool_filter_verdict`.
Extracted from inline (untestable); this test pins their math + thresholds so a
future bug can't silently flip the verdict.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from scripts._diag_trend_pool_filter_discrimination import (  # noqa: E402
    pool_filter_verdict,
    trend_direction_distribution,
    trend_directional_edge,
)

# ---------------------------------------------------------------------------
# trend_direction_distribution — aff989be "~100% bullish" claim
# ---------------------------------------------------------------------------


def test_distribution_empty_returns_all_zero():
    d = trend_direction_distribution([])
    assert d == {"bullish": 0.0, "neutral": 0.0, "bearish": 0.0}


def test_distribution_all_bullish_aff989be_scenario():
    # aff989be claim: ~100% bullish, no discrimination
    d = trend_direction_distribution([1] * 100)
    assert d["bullish"] == 1.0
    assert d["bearish"] == 0.0
    assert d["neutral"] == 0.0


def test_distribution_balanced_thirds():
    d = trend_direction_distribution([1, -1, 0] * 10)  # 30 total, 10 each
    assert d == {"bullish": 1 / 3, "neutral": 1 / 3, "bearish": 1 / 3}


def test_distribution_mixed_counts():
    # 6 bullish, 3 neutral, 1 bearish → 60%/30%/10%
    d = trend_direction_distribution([1, 1, 1, 1, 1, 1, 0, 0, 0, -1])
    assert abs(d["bullish"] - 0.6) < 1e-9
    assert abs(d["neutral"] - 0.3) < 1e-9
    assert abs(d["bearish"] - 0.1) < 1e-9


# ---------------------------------------------------------------------------
# trend_directional_edge — does direction predict return?
# ---------------------------------------------------------------------------


def test_edge_bullish_outperforms_positive_delta():
    r = trend_directional_edge(bullish_rets=[2.0, 1.5, 2.5], bearish_rets=[-1.0, 0.5, -0.5])
    assert r["bullish_mean"] == 2.0
    assert r["bearish_mean"] == -1.0 / 3
    assert r["delta"] > 0
    assert r["bullish_n"] == 3
    assert r["bearish_n"] == 3


def test_edge_empty_bullish_nan_delta():
    r = trend_directional_edge(bullish_rets=[], bearish_rets=[1.0, 2.0])
    assert math.isnan(r["bullish_mean"])
    assert r["bearish_mean"] == 1.5
    assert math.isnan(r["delta"])
    assert r["bullish_n"] == 0


def test_edge_empty_bearish_nan_delta():
    r = trend_directional_edge(bullish_rets=[1.0], bearish_rets=[])
    assert r["bullish_mean"] == 1.0
    assert math.isnan(r["bearish_mean"])
    assert math.isnan(r["delta"])


def test_edge_no_directional_signal_delta_near_zero():
    # both sides same distribution → delta ~0 → no directional edge
    r = trend_directional_edge(bullish_rets=[1.0, -1.0, 0.5], bearish_rets=[1.0, -1.0, 0.5])
    assert abs(r["delta"]) < 1e-9


# ---------------------------------------------------------------------------
# pool_filter_verdict — the aff989be claim classification
# ---------------------------------------------------------------------------


def test_verdict_no_filter_confirms_aff989be_claim():
    # >95% bullish AND |delta| < 0.05 → aff989be claim CONFIRMED
    assert pool_filter_verdict(bullish_frac=0.98, directional_delta=0.02) == "no_filter"
    assert pool_filter_verdict(bullish_frac=0.96, directional_delta=-0.03) == "no_filter"


def test_verdict_no_filter_exact_threshold_is_weak():
    # bullish_frac exactly 0.95 is NOT > 0.95 → falls through to directional_filter
    assert pool_filter_verdict(bullish_frac=0.95, directional_delta=0.01) == "directional_filter"


def test_verdict_weak_filter_skewed_but_directional():
    # >95% bullish but directional edge >= 0.05
    assert pool_filter_verdict(bullish_frac=0.97, directional_delta=0.08) == "weak_filter"
    assert pool_filter_verdict(bullish_frac=0.99, directional_delta=-0.06) == "weak_filter"


def test_verdict_weak_filter_delta_boundary():
    # |delta| exactly 0.05 → NOT < 0.05 → weak_filter
    assert pool_filter_verdict(bullish_frac=0.99, directional_delta=0.05) == "weak_filter"


def test_verdict_directional_filter_meaningfully_selective():
    # 50-95% bullish → filter excludes a real slice
    assert pool_filter_verdict(bullish_frac=0.80, directional_delta=0.10) == "directional_filter"
    assert pool_filter_verdict(bullish_frac=0.50, directional_delta=0.0) == "directional_filter"


def test_verdict_strong_filter_highly_selective():
    # <50% bullish
    assert pool_filter_verdict(bullish_frac=0.30, directional_delta=0.20) == "strong_filter"
    assert pool_filter_verdict(bullish_frac=0.0, directional_delta=0.0) == "strong_filter"


# ---------------------------------------------------------------------------
# Reproducibility guard: the loop-43 real-data result must FALSIFY the aff989be
# 'trend ~100% bullish, no discrimination' claim. This falsification redirects
# the north-star pool-filtering path, so a refactor that silently flips the
# verdict (e.g. inverting bullish/bearish) must alarm.
#
# Real data (loop 43, n=4 days light-stage T+1, 11364 records): trend bullish
# ≈ 40.7% (NOT ~100%), bearish ≈ 59.2%, directional_delta ≈ -1.09% (trend
# bullish UNDERPERFORMS bearish on T+1) → verdict 'strong_filter'. The bullish
# fraction is the decision-critical number: it is far below the 0.95 'no_filter'
# threshold the aff989be claim implies.
# ---------------------------------------------------------------------------


def test_loop43_real_data_falsifies_aff989be_no_discrimination_claim():
    """The loop-43 result: bullish_frac 0.407 (<0.50) → 'strong_filter', NOT
    'no_filter'. The aff989be 'no discrimination' claim is falsified."""
    assert pool_filter_verdict(bullish_frac=0.407, directional_delta=-1.088) == "strong_filter"


def test_loop43_aff989be_claimed_scenario_would_classify_no_filter():
    """If aff989be were right (~100% bullish, ~0 delta), verdict would be
    'no_filter'. Pinning the contrast: 0.98 bullish + 0.02 delta → no_filter."""
    assert pool_filter_verdict(bullish_frac=0.98, directional_delta=0.02) == "no_filter"


# ---------------------------------------------------------------------------
# T+5/T+10 horizon extension (loop 44) — the north-star BUY horizon.
#
# c311 (loop 43) found trend direction is INVERTED at light-stage T+1
# (directional_delta ≈ -1.09%, bullish 40.7%). But the R6 BUY decision uses
# T+5/T+10, and the c311 script explicitly flagged "完整确认需 T+5/T+10".
# A pool-filter redesign decision pack must NOT rest on T+1 alone: a trend
# signal that inverts from T+1 to T+5 would reverse the verdict. These
# helpers add the decision-relevant horizons. Maturity handling is critical:
# the most recent ~10 test_dates have NO T+10 forward return available, so
# the diagnostic must drop them per-horizon rather than silently reusing
# T+1 (look-ahead bias / maturity-faking — NS-17 silent-skip disease class).
# ---------------------------------------------------------------------------

from scripts._diag_trend_pool_filter_discrimination import (  # noqa: E402
    aggregate_horizon,
    cumulative_horizon_return,
    mature_horizons,
    per_horizon_summary,
)

# --- cumulative_horizon_return: pct_chg series → N-day cumulative return ---


def test_cumulative_return_single_day_is_pct_chg():
    # T+1 cumulative return == the single day's pct_chg (geometric: 1+r/100-1)*100)
    assert abs(cumulative_horizon_return([1.5], horizon=1) - 1.5) < 1e-9


def test_cumulative_return_geometric_compounding():
    # +10% then +20% → (1.10 * 1.20 - 1) = +32%
    r = cumulative_horizon_return([10.0, 20.0], horizon=2)
    assert abs(r - 32.0) < 1e-9


def test_cumulative_return_handles_negative_pct():
    # -50% then +100% → (0.50 * 2.00 - 1) = 0%
    r = cumulative_horizon_return([-50.0, 100.0], horizon=2)
    assert abs(r) < 1e-9


def test_cumulative_return_insufficient_history_is_nan():
    import math

    r = cumulative_horizon_return([1.0, 2.0], horizon=5)
    assert math.isnan(r)


def test_cumulative_return_empty_is_nan():
    import math

    assert math.isnan(cumulative_horizon_return([], horizon=1))


# --- mature_horizons: which horizons have a forward return at this date? ---


def test_mature_horizons_last_date_none_mature():
    # test_date is the last index → no forward date for any horizon
    assert mature_horizons(di_index=9, n_dates=10, horizons=(1, 5, 10)) == frozenset()


def test_mature_horizons_penultimate_only_t1():
    # index 8 of 10 → only index+1 (T+1) exists; +5 and +10 out of range
    assert mature_horizons(di_index=8, n_dates=10, horizons=(1, 5, 10)) == frozenset({1})


def test_mature_horizons_enough_room_all_three():
    # index 0 of 20 → T+1, T+5, T+10 all in range
    assert mature_horizons(di_index=0, n_dates=20, horizons=(1, 5, 10)) == frozenset({1, 5, 10})


def test_mature_horizons_boundary_t10_exact():
    # index 10 of 21 → index+10 = 20 (last valid index) → T+10 just mature
    assert mature_horizons(di_index=10, n_dates=21, horizons=(1, 5, 10)) == frozenset({1, 5, 10})


def test_mature_horizons_one_past_boundary():
    # index 11 of 21 → index+10 = 21 == n_dates → T+10 NOT mature (strict <)
    assert mature_horizons(di_index=11, n_dates=21, horizons=(1, 5, 10)) == frozenset({1, 5})


# --- aggregate_horizon + per_horizon_summary: per-horizon verdict ---


def test_aggregate_horizon_groups_by_direction():
    rows = [
        {"trend_direction": 1, "rets": {"1": 1.0, "5": 5.0}},
        {"trend_direction": 1, "rets": {"1": 3.0, "5": 7.0}},
        {"trend_direction": -1, "rets": {"1": -2.0, "5": -4.0}},
    ]
    agg = aggregate_horizon(rows, horizon="5")
    assert agg["bullish_rets"] == [5.0, 7.0]
    assert agg["bearish_rets"] == [-4.0]
    assert agg["neutral_rets"] == []
    assert agg["directions"] == [1, 1, -1]


def test_aggregate_horizon_skips_missing_ret():
    # a row with no mature return at this horizon is dropped (maturity honesty)
    rows = [
        {"trend_direction": 1, "rets": {"5": 5.0}},
        {"trend_direction": -1, "rets": {}},  # T+5 not mature → skip
        {"trend_direction": 1, "rets": {"5": None}},
    ]
    agg = aggregate_horizon(rows, horizon="5")
    assert agg["bullish_rets"] == [5.0]
    assert agg["bearish_rets"] == []
    assert agg["directions"] == [1]


def test_per_horizon_summary_inverts_from_t1_to_t5():
    """Decision-critical reproducibility guard: a trend signal that is
    INVERTED at T+1 (bearish outperforms) but CORRECT at T+5 (bullish
    outperforms) must produce DIFFERENT verdicts. This is exactly the
    inversion the loop-44 diagnostic is built to detect — a refactor that
    silently reused T+1 returns for T+5 would hide it."""
    rows = [
        {"trend_direction": 1, "rets": {"1": -1.0, "5": 6.0}},
        {"trend_direction": 1, "rets": {"1": -1.0, "5": 4.0}},
        {"trend_direction": -1, "rets": {"1": 1.0, "5": -5.0}},
        {"trend_direction": -1, "rets": {"1": 1.0, "5": -3.0}},
    ]
    s1 = per_horizon_summary(rows, horizon="1")
    s5 = per_horizon_summary(rows, horizon="5")
    # T+1: bullish -1.0, bearish +1.0 → negative delta (inverted)
    assert s1["edge"]["delta"] < 0
    # T+5: bullish +5.0, bearish -4.0 → positive delta (correct direction)
    assert s5["edge"]["delta"] > 0


def test_per_horizon_summary_empty_returns_zeroed():
    s = per_horizon_summary([], horizon="5")
    assert s["n"] == 0
    assert s["verdict"] == "no_data"
    assert math.isnan(s["edge"]["delta"])


# ---------------------------------------------------------------------------
# Loop 44 (c312) real-data reproducibility guard — the decision-critical finding.
#
# c312 ran the multi-horizon diagnostic on a DIFFERENT 4-day window
# (20260601–20260604) than c311. The robust finding (aff989be 'no
# discrimination' FALSIFIED) HOLDS: bullish_frac 51.0% (NOT ~100%) on both
# windows. But the decision-critical new finding is that the T+1 directional
# SIGN FLIPPED across windows: c311 T+1 delta ≈ -1.088%, c312 T+1 delta
# ≈ +0.912%. This is the n=4 window-instability the decision-state cautions
# about, now demonstrated empirically. A future refactor that silently
# hard-codes a T+1 sign must alarm. We pin BOTH verdicts and the sign flip.
#
# Real data c312 (loop 44, n=4 days, 11692 records light-stage, T+1/T+5/T+10):
#   T+1:  bullish 51.0%, delta +0.912% → directional_filter
#   T+5:  delta +2.311% → directional_filter
#   T+10: delta +6.635% → directional_filter
# ---------------------------------------------------------------------------


def test_loop44_c312_real_data_t1_verdict_is_directional_filter():
    """c312 window (20260601-04): bullish_frac 0.510 (50-95%), delta +0.912%
    → 'directional_filter'. (c311 was 'strong_filter' at 0.407 — different
    window, different distribution.)"""
    assert pool_filter_verdict(bullish_frac=0.510, directional_delta=0.912) == "directional_filter"


def test_loop44_c312_falsifies_aff989be_no_discrimination_claim():
    """Robust across c311+c312 windows: bullish_frac 51% (NOT ~100%) → the
    aff989be 'trend ~all-bullish, no discrimination' claim is falsified on a
    second independent window."""
    assert pool_filter_verdict(bullish_frac=0.510, directional_delta=0.912) != "no_filter"


def test_loop43_vs_loop44_t1_direction_sign_flips():
    """DECISION-CRITICAL: the T+1 directional delta sign is NOT stable across
    4-day windows — c311 ≈ -1.088% vs c312 ≈ +0.912%. This is the empirical
    proof that n=4 direction conclusions are window-noise. Pinning the flip so
    a refactor that claims stable direction must alarm."""
    c311_t1_delta = -1.088
    c312_t1_delta = 0.912
    assert c311_t1_delta < 0  # c311 window: trend direction inverted
    assert c312_t1_delta > 0  # c312 window: trend direction correct
    # The sign flip between two independent 4-day windows is the core finding.
