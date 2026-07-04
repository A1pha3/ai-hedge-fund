"""c315 (loop 47) — unit tests for the R6 multi-horizon incremental-accrual helpers.

The R6 north-star blocker (decision-state): c311/c312 measured trend direction
delta on n=4 day windows and the SIGN FLIPPED across windows (-1.088% vs
+0.912%). Direction sign is window-noise at n=4, so the C-R6-POOL-FILTER-
REDESIGN decision pack cannot act. The blocker is data volume, not engineering
— but the API throttle (~3min/day) makes a 20-day foreground run infeasible.

This loop builds an INCREMENTAL ACCRUAL diagnostic: run a few days now, persist,
resume tomorrow, accumulate to n=20+. The persistence + state-merge + resume-
plan logic is pure and decision-critical (a bug here silently drops days or
double-counts, faking a larger N than is real — NS-17 / data-truthfulness). The
helpers are extracted testable; the API I/O stays in the run loop.

Pure helpers under test (in scripts/_diag_r6_multihorizon_accrual.py):
  - load_state / save_state: atomic JSON read/write of {days_done, rows}
  - merge_day_rows: append one day's rows, dedup by (test_date) — never double-count
  - plan_next_batch: which test_dates are NOT yet done → the resume slice
  - maturity_for_window: per-horizon how many rows are mature (informational)
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from scripts._diag_r6_multihorizon_accrual import (  # noqa: E402
    load_state,
    merge_day_rows,
    plan_next_batch,
    maturity_for_window,
)

# ---------------------------------------------------------------------------
# load_state / save_state — atomic, missing-file-safe, schema-validated
# ---------------------------------------------------------------------------


def test_load_state_missing_file_returns_empty(tmp_path):
    """No prior run → empty state (no rows, no days done). Must NOT raise."""
    s = load_state(tmp_path / "does_not_exist.json")
    assert s["days_done"] == []
    assert s["rows"] == []


def test_load_state_roundtrip(tmp_path):
    """save then load preserves days_done + rows exactly."""
    p = tmp_path / "state.json"
    state = {
        "days_done": ["20260601", "20260602"],
        "rows": [
            {"trend_direction": 1, "rets": {"1": 0.5, "5": 2.0}},
            {"trend_direction": -1, "rets": {"1": -0.3}},
        ],
    }
    import scripts._diag_r6_multihorizon_accrual as m

    m.save_state(p, state)
    loaded = load_state(p)
    assert loaded["days_done"] == ["20260601", "20260602"]
    assert len(loaded["rows"]) == 2
    assert loaded["rows"][0]["rets"]["5"] == 2.0


def test_load_state_corrupt_file_returns_empty_not_raise(tmp_path):
    """NS-17 / data-truthfulness: a corrupt/partial-write state file must NOT
    crash the resume — it returns empty (re-accrue) rather than silently
    loading garbage that would fake a larger N. Operator is told via stderr."""
    p = tmp_path / "corrupt.json"
    p.write_text("{not valid json")
    s = load_state(p)
    assert s["days_done"] == []  # safe fallback, not a crash
    assert s["rows"] == []


def test_load_state_valid_json_non_dict_returns_empty_not_raise(tmp_path):
    """c317c (loop 51): valid JSON that is NOT a dict (e.g. ``42``, ``null``,
    ``[]``, ``"hello"`` — plausible outcomes of a truncated/garbled write or a
    hand-edit) must NOT crash the resume. The docstring promises '不 crash 不
    加载垃圾' but pre-fix load_state called raw.get() at L76 before any
    isinstance check, so a non-dict JSON raised AttributeError — directly
    contradicting the documented guard. JSONDecodeError + wrong-shape-dict
    were handled; valid-non-dict-JSON was the hole.
    """
    for bad_content in ("42", "null", "[]", '"hello"', "true"):
        p = tmp_path / f"nondict_{bad_content[:4]}.json"
        p.write_text(bad_content)
        s = load_state(p)  # must NOT raise AttributeError
        assert s["days_done"] == [], f"content={bad_content!r} should give empty state"
        assert s["rows"] == []


# ---------------------------------------------------------------------------
# merge_day_rows — the decision-critical dedup. Double-counting a day fakes N.
# ---------------------------------------------------------------------------


def test_merge_appends_new_day():
    state = {"days_done": ["20260601"], "rows": [{"trend_direction": 1, "rets": {"1": 1.0}}]}
    new_rows = [{"trend_direction": -1, "rets": {"1": -0.5}}]
    out = merge_day_rows(state, test_date="20260602", new_rows=new_rows)
    assert "20260602" in out["days_done"]
    assert len(out["rows"]) == 2  # 1 old + 1 new


def test_merge_dedups_already_done_day_no_double_count():
    """Re-running a day already accrued must NOT duplicate its rows. This is
    the core data-truthfulness guard: double-counting fakes a larger N and
    could flip the direction-delta verdict by overweighting one day."""
    state = {
        "days_done": ["20260601"],
        "rows": [{"trend_direction": 1, "rets": {"1": 1.0}}],
    }
    new_rows = [{"trend_direction": -1, "rets": {"1": 99.0}}]  # would skew if added
    out = merge_day_rows(state, test_date="20260601", new_rows=new_rows)
    assert out["days_done"] == ["20260601"]  # unchanged
    assert len(out["rows"]) == 1  # NOT 2 — the duplicate was rejected
    # and the original row is preserved (not overwritten by the new one)
    assert out["rows"][0]["rets"]["1"] == 1.0


def test_merge_empty_new_rows_does_not_mark_day_done():
    """A day that yielded zero rows (API failure / all stocks filtered) must
    NOT be marked done — otherwise resume skips it permanently (silent data
    gap). It stays pending for a retry."""
    state = {"days_done": [], "rows": []}
    out = merge_day_rows(state, test_date="20260603", new_rows=[])
    assert "20260603" not in out["days_done"]  # not done — retryable
    assert out["rows"] == []


# ---------------------------------------------------------------------------
# plan_next_batch — the resume slice (what to fetch next)
# ---------------------------------------------------------------------------


def test_plan_returns_pending_dates_only():
    """All test_dates not in days_done, capped at batch_size."""
    plan = plan_next_batch(
        test_dates=["20260601", "20260602", "20260603", "20260604"],
        days_done=["20260601"],
        batch_size=2,
    )
    assert plan == ["20260602", "20260603"]  # 20260601 done; cap 2


def test_plan_all_done_returns_empty():
    plan = plan_next_batch(
        test_dates=["20260601", "20260602"],
        days_done=["20260601", "20260602"],
        batch_size=5,
    )
    assert plan == []


def test_plan_batch_larger_than_pending_returns_all_pending():
    plan = plan_next_batch(
        test_dates=["20260601", "20260602"],
        days_done=[],
        batch_size=10,
    )
    assert plan == ["20260601", "20260602"]


def test_plan_preserves_test_dates_order():
    """Resume must process dates in chronological order (not set-iteration
    order) — order matters for maturity + reproducibility."""
    plan = plan_next_batch(
        test_dates=["20260601", "20260602", "20260603"],
        days_done=["20260602"],
        batch_size=5,
    )
    assert plan == ["20260601", "20260603"]  # order preserved


# ---------------------------------------------------------------------------
# maturity_for_window — per-horizon mature-row count (informational honesty)
# ---------------------------------------------------------------------------


def test_maturity_counts_only_non_none_rets():
    """A row with rets[h] is None did NOT mature at horizon h — must not be
    counted as mature. This is the same maturity-honesty principle as c312's
    aggregate_horizon (drop None, don't substitute T+1)."""
    rows = [
        {"trend_direction": 1, "rets": {"1": 1.0, "5": 2.0, "10": 3.0}},
        {"trend_direction": -1, "rets": {"1": -0.5, "5": None, "10": None}},  # T5/T10 immature
        {"trend_direction": 1, "rets": {"1": 0.3, "5": None, "10": None}},
    ]
    m = maturity_for_window(rows, horizons=(1, 5, 10))
    assert m["1"] == 3  # all three matured at T+1
    assert m["5"] == 1  # only the first row
    assert m["10"] == 1  # only the first row


def test_maturity_empty_rows_all_zero():
    m = maturity_for_window([], horizons=(1, 5, 10))
    assert m == {"1": 0, "5": 0, "10": 0}


# ---------------------------------------------------------------------------
# Reproducibility guard: the loop-47 design invariant.
#
# The whole point of accrual is to reach a larger N than a single foreground
# run allows. A bug that double-counts days would fake N and could flip the
# direction-delta verdict. This pins the invariant: accruing the SAME 4 days
# across 4 separate batch runs yields the SAME rows as one 4-day run.
# ---------------------------------------------------------------------------


def test_accrual_invariant_batched_equals_single_run():
    """4 days accrued one-at-a-time == 4 days accrued in one batch. No day
    double-counted, no row lost, no row duplicated."""
    day_rows = {
        "20260601": [{"trend_direction": 1, "rets": {"1": 1.0}}],
        "20260602": [{"trend_direction": -1, "rets": {"1": -0.5}}],
        "20260603": [{"trend_direction": 1, "rets": {"1": 0.3}}],
        "20260604": [{"trend_direction": -1, "rets": {"1": -0.2}}],
    }
    test_dates = list(day_rows.keys())

    # Path A: one batch
    state_a = {"days_done": [], "rows": []}
    for d in test_dates:
        state_a = merge_day_rows(state_a, d, day_rows[d])

    # Path B: simulate 4 separate resume runs (load → merge → save → reload)
    import scripts._diag_r6_multihorizon_accrual as m
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "state.json"
        m.save_state(p, {"days_done": [], "rows": []})
        for d in test_dates:
            s = load_state(p)
            s = merge_day_rows(s, d, day_rows[d])
            m.save_state(p, s)
        state_b = load_state(p)

    assert state_a["days_done"] == state_b["days_done"] == test_dates
    assert len(state_a["rows"]) == len(state_b["rows"]) == 4
    assert [r["rets"]["1"] for r in state_a["rows"]] == [1.0, -0.5, 0.3, -0.2]
    assert [r["rets"]["1"] for r in state_b["rows"]] == [1.0, -0.5, 0.3, -0.2]
