"""c308 (loop 41) — unit tests for the decision-critical R6 diagnostic helpers.

The R6 selection-bias conclusion (biggest finding of the multi-session arc) rests
on `summarize_r6_diagnostic` + `r6_selection_bias_verdict` in
`scripts/_diag_r6_full_universe.py`. These were inline (untestable) until c308
extracted them. This test pins their math so a future bug can't silently corrupt
the R6 verdict.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from scripts._diag_r6_full_universe import (  # noqa: E402
    r6_selection_bias_verdict,
    summarize_r6_diagnostic,
)

# ---------------------------------------------------------------------------
# summarize_r6_diagnostic — aggregation math
# ---------------------------------------------------------------------------


def test_summarize_empty_returns_zero_days():
    s = summarize_r6_diagnostic([], top_n_list=(3, 50))
    assert s == {"n_days": 0, "eq_all": None, "top_n": {}}


def test_summarize_computes_eq_all_mean_and_winrate():
    # 2 days: eq_all returns +1.0 and -3.0 → mean -1.0, winrate 50%
    daily = [
        {"date": "d1", "eq_all_ret": 1.0, "top3_ret": 2.0, "top3_beats_eq": True, "top50_ret": 1.5, "top50_beats_eq": True},
        {"date": "d2", "eq_all_ret": -3.0, "top3_ret": -1.0, "top3_beats_eq": True, "top50_ret": -2.0, "top50_beats_eq": True},
    ]
    s = summarize_r6_diagnostic(daily, top_n_list=(3, 50))
    assert s["n_days"] == 2
    assert s["eq_all"]["mean"] == -1.0
    assert s["eq_all"]["winrate"] == 0.5  # 1 of 2 positive


def test_summarize_top_n_delta_and_beats_eq():
    # top3 beats eq both days (delta positive), beats_eq fraction = 100%
    daily = [
        {"date": "d1", "eq_all_ret": 0.0, "top3_ret": 2.0, "top3_beats_eq": True, "top50_ret": 1.0, "top50_beats_eq": True},
        {"date": "d2", "eq_all_ret": -1.0, "top3_ret": 1.0, "top3_beats_eq": True, "top50_ret": 0.0, "top50_beats_eq": True},
    ]
    s = summarize_r6_diagnostic(daily, top_n_list=(3,))
    t3 = s["top_n"][3]
    assert t3["mean"] == 1.5
    assert t3["delta"] == 1.5 - (-0.5)  # top3 mean - eq mean = 1.5 - (-0.5) = 2.0
    assert t3["delta"] == 2.0
    assert t3["beats_eq"] == 1.0  # 2 of 2 days
    assert t3["winrate"] == 1.0  # both days top3 positive


def test_summarize_independent_per_top_n():
    # top3 loses, top50 wins on the same day → independent deltas
    daily = [
        {"date": "d1", "eq_all_ret": 1.0, "top3_ret": -2.0, "top3_beats_eq": False, "top50_ret": 2.0, "top50_beats_eq": True},
    ]
    s = summarize_r6_diagnostic(daily, top_n_list=(3, 50))
    assert s["top_n"][3]["delta"] == -3.0  # -2 - 1
    assert s["top_n"][50]["delta"] == 1.0  # 2 - 1


# ---------------------------------------------------------------------------
# r6_selection_bias_verdict — the classification driving the owner-facing verdict
# ---------------------------------------------------------------------------


def test_verdict_positive_when_top3_beats_eq():
    # delta>0 AND beats>0.5 → selection-bias artifact confirmed
    assert r6_selection_bias_verdict(top3_delta=0.44, top3_beats=0.63) == "positive"


def test_verdict_negative_when_top3_loses():
    # delta<0 AND beats<0.5 → genuine defect
    assert r6_selection_bias_verdict(top3_delta=-0.35, top3_beats=0.25) == "negative"


def test_verdict_ambiguous_when_delta_positive_but_beats_low():
    assert r6_selection_bias_verdict(top3_delta=0.10, top3_beats=0.40) == "ambiguous"


def test_verdict_ambiguous_when_beats_high_but_delta_negative():
    assert r6_selection_bias_verdict(top3_delta=-0.05, top3_beats=0.60) == "ambiguous"


def test_verdict_boundary_delta_zero_is_ambiguous():
    # delta exactly 0 → not strictly positive → ambiguous
    assert r6_selection_bias_verdict(top3_delta=0.0, top3_beats=0.90) == "ambiguous"


def test_verdict_boundary_beats_half_is_ambiguous():
    # beats exactly 0.5 → not strictly > 0.5 → ambiguous (delta positive)
    assert r6_selection_bias_verdict(top3_delta=0.5, top3_beats=0.5) == "ambiguous"


# ---------------------------------------------------------------------------
# Reproducibility guard: the c303 real-data result must classify as 'positive'
# (the selection-bias-artifact finding). If a refactor flips this, alarm.
# ---------------------------------------------------------------------------


def test_c303_real_data_result_classifies_positive():
    """The actual c303 20-day run: top3 delta +0.444%, beats-eq 0.632 → 'positive'."""
    assert r6_selection_bias_verdict(top3_delta=0.444, top3_beats=0.632) == "positive"
