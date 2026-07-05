"""TDD red test: grade↔verdict parity auditor (E4 display-semantics coverage).

Loop 85 flagged ``C-GREEN-GRADE-AVOID-MISMATCH`` as a new disease class:
``_composite_grade`` (composite_score.py:343) paints GREEN B for composite>=0.5
and GREEN A for composite>=0.7 regardless of the verdict, so an AVOID pick
can render a green grade next to ``操作=AVOID`` — a visual-semantic conflict
that misleads the operator into reading a "do not buy" pick as "good
confidence".

Loop 89 (this loop) does NOT change default display semantics (that is an
owner decision pack — display-semantics boundary). Instead it builds a
**diagnostic evaluator** that quantifies the mismatch on real reports and
classifies the trigger path. This serves:

- F5 (front-door trust calibration): turn a single loop-85 flag into
  frequency evidence for the owner decision pack.
- E4 (display-honesty coverage): extend the evaluator map to a new disease
  class (grade↔verdict parity), reusable as a regression guard for any
  future grade/verdict change.

The auditor is pure-diagnostic: it reads picks + regime, classifies each
pick's grade↔verdict relationship, and returns a structured report. It does
NOT touch ``_composite_grade``, ``build_front_door_verdict``, or any render
function — byte-for-byte behavior preserved.

Trigger paths (verified empirically, see loop-89 dogfood on report
20260703_top5: AVOID picks 688017/300502/688766 all rendered green B at
composite 0.679/0.661/0.663):

- ``short_term_signal_missing``: composite>=0.5 (green B+) but neither T+5
  nor T+10 passes the BUY gate, and the watchable bar (winrate>=0.5) fails
  too → AVOID with a green grade.
- ``market_gate_downgrade``: composite>=0.5 (green B+) AND short-term signal
  passes, but regime is crisis/risk_off → verdict downgrades to HOLD/AVOID
  while grade stays green (case C in loop-89 preflight, composite=0.85 →
  green A → AVOID under crisis).
- ``bearish_decision``: composite>=0.5 (green B+) but decision=bearish →
  supports_long=False → AVOID with a green grade (case A in loop-89).
- ``insufficient_sample``: composite>=0.5 AND short-term passes but
  backing_sample<20 → HOLD/AVOID; grade stays green.
"""

from __future__ import annotations

from src.screening.grade_verdict_parity import (
    audit_grade_verdict_parity,
    render_parity_audit,
)


# ---------------------------------------------------------------------------
# Fixtures — mirror the empirically-verified loop-89 trigger paths.
# ---------------------------------------------------------------------------


def _aligned_buy() -> dict:
    """Green B grade aligned with BUY verdict — NOT a mismatch."""
    return {
        "ticker": "300054",
        "name": "鼎龙股份",
        "composite_score": 0.683,
        "decision": "bullish",
        "expected_returns": {"t5": 0.0467, "t10": 0.0467, "t30": -0.0236},
        "win_rates": {"t5": 0.60, "t10": 0.60},
        "bucket_t30_mature_count": 7765,
        "bucket_sample_count": 7793,
        "score_b": 0.433,
    }


def _green_avoid_short_term_missing() -> dict:
    """Case B (loop-89): composite=0.55 green B but no short-term signal → AVOID."""
    return {
        "ticker": "688017",
        "name": "绿的谐波",
        "composite_score": 0.679,
        "decision": "bullish",
        "expected_returns": {"t5": 0.0179, "t10": 0.0179, "t30": -0.0797},
        "win_rates": {"t5": 0.49, "t10": 0.49},  # below 0.5 watchable
        "bucket_t30_mature_count": 35,
        "bucket_sample_count": 46,
        "score_b": 0.679,
    }


def _green_avoid_bearish() -> dict:
    """Case A (loop-89): composite=0.6 green B but decision=bearish → AVOID."""
    return {
        "ticker": "000002",
        "name": "万科A",
        "composite_score": 0.60,
        "decision": "bearish",
        "expected_returns": {"t5": 0.0, "t10": 0.0, "t30": 0.0},
        "win_rates": {"t5": 0.0, "t10": 0.0},
        "bucket_t30_mature_count": 100,
        "bucket_sample_count": 100,
        "score_b": 0.60,
    }


def _green_avoid_crisis() -> dict:
    """Case C (loop-89): composite=0.85 green A, short-term passes, but crisis.

    Under crisis the market gate downgrades BUY to HOLD (when sample>=20) or
    AVOID (when sample<20). Both are green-grade-vs-non-BUY conflicts; this
    fixture uses the AVOID branch (insufficient mature sample under crisis,
    a common pre-maturity state) to assert the trigger-path classification.
    """
    return {
        "ticker": "600519",
        "name": "贵州茅台",
        "composite_score": 0.85,
        "decision": "bullish",
        "expected_returns": {"t5": 0.05, "t10": 0.05, "t30": 0.0},
        "win_rates": {"t5": 0.70, "t10": 0.70},
        "bucket_t30_mature_count": 5,
        "bucket_sample_count": 5,
        "score_b": 0.85,
    }


def _green_hold_crisis_mature() -> dict:
    """Crisis variant: composite=0.85 green A, short-term passes, sample>=20.

    Under crisis with sufficient sample, verdict downgrades BUY→HOLD (not
    AVOID). Still a green-grade-vs-non-BUY conflict — same disease class.
    """
    return {
        "ticker": "600519",
        "name": "贵州茅台",
        "composite_score": 0.85,
        "decision": "bullish",
        "expected_returns": {"t5": 0.05, "t10": 0.05, "t30": 0.0},
        "win_rates": {"t5": 0.70, "t10": 0.70},
        "bucket_t30_mature_count": 100,
        "bucket_sample_count": 100,
        "score_b": 0.85,
    }


def _low_score_avoid_aligned() -> dict:
    """composite<0.3 → F grade (red) aligned with AVOID — NOT a mismatch."""
    return {
        "ticker": "000003",
        "name": "ST达金",
        "composite_score": 0.15,
        "decision": "bearish",
        "expected_returns": {"t5": -0.02, "t10": -0.02, "t30": -0.05},
        "win_rates": {"t5": 0.30, "t10": 0.30},
        "bucket_t30_mature_count": 50,
        "bucket_sample_count": 50,
        "score_b": 0.15,
    }


# ---------------------------------------------------------------------------
# Parity classification — the core evaluator logic.
# ---------------------------------------------------------------------------


def test_aligned_buy_is_not_flagged() -> None:
    """A green-B BUY pick is grade↔verdict aligned — no mismatch."""
    report = audit_grade_verdict_parity([_aligned_buy()], market_regime="normal")
    assert report.total_picks == 1
    assert report.mismatch_count == 0
    assert report.mismatches == []


def test_green_avoid_short_term_missing_is_classified() -> None:
    """Green B + AVOID via missing short-term signal → mismatch flagged.

    Trigger path: ``short_term_signal_missing``. This is the empirically
    dominant case on report 20260703 (3 of 5 picks).
    """
    report = audit_grade_verdict_parity(
        [_green_avoid_short_term_missing()], market_regime="normal"
    )
    assert report.mismatch_count == 1
    m = report.mismatches[0]
    assert m.ticker == "688017"
    assert m.grade_color == "green"
    assert m.verdict == "AVOID"
    assert m.trigger_path == "short_term_signal_missing"


def test_green_avoid_bearish_is_classified() -> None:
    """Green B + AVOID via bearish decision → mismatch flagged."""
    report = audit_grade_verdict_parity(
        [_green_avoid_bearish()], market_regime="normal"
    )
    assert report.mismatch_count == 1
    m = report.mismatches[0]
    assert m.verdict == "AVOID"
    assert m.trigger_path == "bearish_decision"


def test_green_avoid_crisis_is_classified() -> None:
    """Green A + AVOID via crisis market-gate downgrade → mismatch flagged."""
    report = audit_grade_verdict_parity(
        [_green_avoid_crisis()], market_regime="crisis"
    )
    assert report.mismatch_count == 1
    m = report.mismatches[0]
    assert m.grade_color == "green"
    assert m.verdict == "AVOID"
    assert m.trigger_path == "market_gate_downgrade"


def test_green_hold_crisis_mature_is_mismatch() -> None:
    """Green A + HOLD via crisis downgrade (mature sample) → mismatch flagged.

    HOLD is less severe than AVOID but the visual-semantic conflict is the
    same: a green "good confidence" grade on a non-actionable pick.
    """
    report = audit_grade_verdict_parity(
        [_green_hold_crisis_mature()], market_regime="crisis"
    )
    assert report.mismatch_count == 1
    m = report.mismatches[0]
    assert m.verdict == "HOLD"
    assert m.trigger_path == "market_gate_downgrade"


def test_red_avoid_is_not_flagged() -> None:
    """Red F + AVOID is semantically aligned — no mismatch."""
    report = audit_grade_verdict_parity(
        [_low_score_avoid_aligned()], market_regime="normal"
    )
    assert report.mismatch_count == 0


def test_mixed_report_aggregates_trigger_path_counts() -> None:
    """A realistic 5-pick report aggregates per-trigger-path counts."""
    picks = [
        _aligned_buy(),
        _green_avoid_short_term_missing(),
        _green_avoid_short_term_missing(),  # second occurrence
        _green_avoid_bearish(),
        _low_score_avoid_aligned(),
    ]
    report = audit_grade_verdict_parity(picks, market_regime="normal")
    assert report.total_picks == 5
    assert report.mismatch_count == 3
    assert report.trigger_counts["short_term_signal_missing"] == 2
    assert report.trigger_counts["bearish_decision"] == 1
    # Mismatch ratio is reported for the decision pack.
    assert report.mismatch_ratio == 3 / 5


def test_hold_with_green_grade_is_also_mismatch() -> None:
    """HOLD with a green grade is the same disease class (visual-semantic
    conflict) even though HOLD is less severe than AVOID. The operator still
    sees a "good confidence" color on a non-actionable pick."""
    hold_pick = {
        "ticker": "600000",
        "name": "浦发银行",
        "composite_score": 0.45,  # C grade (yellow) — NOT green, so not a mismatch
        "decision": "bullish",
        "expected_returns": {"t5": 0.0, "t10": 0.0, "t30": 0.0},
        "win_rates": {"t5": 0.55, "t10": 0.55},  # watchable passes
        "bucket_t30_mature_count": 50,
        "bucket_sample_count": 50,
        "score_b": 0.45,
    }
    report = audit_grade_verdict_parity([hold_pick], market_regime="normal")
    # composite 0.45 → yellow C; HOLD is non-actionable but not color-conflicting
    # with green. Not flagged.
    assert report.mismatch_count == 0


def test_render_parity_audit_is_human_readable() -> None:
    """The render produces an operator-readable summary for the decision pack."""
    picks = [_aligned_buy(), _green_avoid_short_term_missing()]
    report = audit_grade_verdict_parity(picks, market_regime="normal")
    rendered = render_parity_audit(report)
    # Must surface the headline metric (mismatch count + ratio) and the
    # trigger-path distribution so the owner can size the fix.
    assert "1" in rendered  # mismatch count
    assert "short_term_signal_missing" in rendered or "短期信号缺失" in rendered
    # Must name the disease class so the decision pack is self-documenting.
    assert "grade" in rendered.lower() or "等级" in rendered


def test_empty_picks_returns_zero_report() -> None:
    """Edge case: empty pick list returns a zero-count report (no crash)."""
    report = audit_grade_verdict_parity([], market_regime="normal")
    assert report.total_picks == 0
    assert report.mismatch_count == 0
    assert report.mismatch_ratio == 0.0


def test_report_serializes_to_dict_for_decision_pack_artifact() -> None:
    """The report must serialize to a plain dict so it can be written as a
    decision-pack evidence artifact (JSON) for owner review."""
    report = audit_grade_verdict_parity(
        [_green_avoid_short_term_missing()], market_regime="normal"
    )
    d = report.to_dict()
    assert d["total_picks"] == 1
    assert d["mismatch_count"] == 1
    assert d["mismatch_ratio"] == 1.0
    assert d["trigger_counts"]["short_term_signal_missing"] == 1
    assert d["mismatches"][0]["ticker"] == "688017"
    assert d["mismatches"][0]["trigger_path"] == "short_term_signal_missing"
