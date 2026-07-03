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
