"""Tests for P3 prior quality hard gate.

P3 adds BTST_0422_P3_PRIOR_QUALITY_MODE (off|enforce).
When enforce:
  - evaluable_count < 5 → blocks selected eligibility
  - evaluable_count < 3 → blocks near_miss eligibility
  - next_high_hit_rate_at_threshold == 0 → reject
  - next_close_positive_rate < 0.5 → downgrade to watch_only
When off: behaviour identical to baseline (P3 is a no-op).

Prior quality classification returns one of: execution_ready / watch_only / reject
"""
from __future__ import annotations

import pytest

from src.targets.prior_quality import (
    PriorQualityLabel,
    classify_prior_quality,
    apply_p3_prior_quality_gate_to_selection_targets,
)
from src.targets.models import DualTargetEvaluation, TargetEvaluationResult


# ---------------------------------------------------------------------------
# classifier unit tests
# ---------------------------------------------------------------------------


class TestClassifyPriorQualityRejectCases:
    """Classifier must return reject for zero-high-hit-rate (regardless of n)."""

    def test_zero_high_hit_rate_returns_reject(self):
        result = classify_prior_quality(
            evaluable_count=10,
            next_high_hit_rate_at_threshold=0.0,
            next_close_positive_rate=0.60,
        )
        assert result.label == PriorQualityLabel.REJECT

    def test_zero_high_hit_rate_with_small_n_returns_reject(self):
        result = classify_prior_quality(
            evaluable_count=2,
            next_high_hit_rate_at_threshold=0.0,
            next_close_positive_rate=0.55,
        )
        assert result.label == PriorQualityLabel.REJECT

    def test_reason_contains_zero_high_hit(self):
        result = classify_prior_quality(
            evaluable_count=8,
            next_high_hit_rate_at_threshold=0.0,
            next_close_positive_rate=0.65,
        )
        assert "high_hit_rate_zero" in result.reason


class TestClassifyPriorQualityWatchOnlyCases:
    """Classifier must return watch_only for low close-positive-rate."""

    def test_close_positive_rate_below_50_pct_returns_watch_only(self):
        result = classify_prior_quality(
            evaluable_count=10,
            next_high_hit_rate_at_threshold=0.30,
            next_close_positive_rate=0.45,
        )
        assert result.label == PriorQualityLabel.WATCH_ONLY

    def test_close_positive_rate_exactly_50_pct_is_execution_ready(self):
        result = classify_prior_quality(
            evaluable_count=10,
            next_high_hit_rate_at_threshold=0.30,
            next_close_positive_rate=0.50,
        )
        assert result.label == PriorQualityLabel.EXECUTION_READY

    def test_reason_contains_low_close_positive(self):
        result = classify_prior_quality(
            evaluable_count=10,
            next_high_hit_rate_at_threshold=0.30,
            next_close_positive_rate=0.40,
        )
        assert "low_close_positive_rate" in result.reason

    def test_zero_high_hit_takes_priority_over_watch_only(self):
        """Reject takes priority when both reject and watch_only conditions apply."""
        result = classify_prior_quality(
            evaluable_count=10,
            next_high_hit_rate_at_threshold=0.0,
            next_close_positive_rate=0.40,
        )
        assert result.label == PriorQualityLabel.REJECT


class TestClassifyPriorQualityExecutionReadyCases:
    """Classifier must return execution_ready for passing priors."""

    def test_good_prior_returns_execution_ready(self):
        result = classify_prior_quality(
            evaluable_count=8,
            next_high_hit_rate_at_threshold=0.50,
            next_close_positive_rate=0.65,
        )
        assert result.label == PriorQualityLabel.EXECUTION_READY

    def test_reason_is_none_or_empty_for_execution_ready(self):
        result = classify_prior_quality(
            evaluable_count=8,
            next_high_hit_rate_at_threshold=0.50,
            next_close_positive_rate=0.65,
        )
        assert not result.reason


# ---------------------------------------------------------------------------
# sample-size eligibility tests (classifier level)
# ---------------------------------------------------------------------------


class TestClassifyPriorQualitySampleSizeRules:
    """Classifier must surface tiny-sample quality labels."""

    def test_n_below_5_returns_watch_only_selected_block(self):
        result = classify_prior_quality(
            evaluable_count=4,
            next_high_hit_rate_at_threshold=0.40,
            next_close_positive_rate=0.55,
        )
        # n < 5 cannot enter selected: classifier must at minimum degrade to watch_only
        assert result.label in (PriorQualityLabel.WATCH_ONLY, PriorQualityLabel.REJECT)
        assert result.selected_blocked is True

    def test_n_below_3_blocks_near_miss(self):
        result = classify_prior_quality(
            evaluable_count=2,
            next_high_hit_rate_at_threshold=0.40,
            next_close_positive_rate=0.55,
        )
        assert result.near_miss_blocked is True

    def test_n_exactly_5_does_not_block_selected(self):
        result = classify_prior_quality(
            evaluable_count=5,
            next_high_hit_rate_at_threshold=0.40,
            next_close_positive_rate=0.60,
        )
        assert result.selected_blocked is False

    def test_n_exactly_3_does_not_block_near_miss(self):
        result = classify_prior_quality(
            evaluable_count=3,
            next_high_hit_rate_at_threshold=0.40,
            next_close_positive_rate=0.60,
        )
        assert result.near_miss_blocked is False


# ---------------------------------------------------------------------------
# gate enforcement on selection_targets (requires P3 flag)
# ---------------------------------------------------------------------------


def _make_evaluation(ticker: str, short_trade_decision: str, *, historical_prior: dict | None = None) -> DualTargetEvaluation:
    short_trade = TargetEvaluationResult(
        target_type="short_trade",
        decision=short_trade_decision,  # type: ignore[arg-type]
    )
    ev = DualTargetEvaluation(
        ticker=ticker,
        trade_date="2026-04-22",
        short_trade=short_trade,
    )
    # Attach prior payload directly for testing
    object.__setattr__(ev, "_test_historical_prior", historical_prior or {})
    return ev


class TestP3GateEnforcementBlocksSelected:
    """When P3 enforce is on: n < 5 blocks selected eligibility."""

    def test_n_lt_5_blocks_selected_when_enforce(self):
        ev = DualTargetEvaluation(
            ticker="000001",
            trade_date="2026-04-22",
            short_trade=TargetEvaluationResult(
                target_type="short_trade",
                decision="selected",
            ),
        )
        prior = {
            "evaluable_count": 3,
            "next_high_hit_rate_at_threshold": 0.40,
            "next_close_positive_rate": 0.60,
        }
        targets = {"000001": ev}
        apply_p3_prior_quality_gate_to_selection_targets(targets, mode="enforce", prior_by_ticker={"000001": prior})

        assert ev.p3_execution_blocked is True
        assert ev.p3_prior_quality_label in ("watch_only", "reject")
        assert ev.p3_execution_block_reason is not None

    def test_n_ge_5_not_blocked_when_enforce(self):
        ev = DualTargetEvaluation(
            ticker="000002",
            trade_date="2026-04-22",
            short_trade=TargetEvaluationResult(
                target_type="short_trade",
                decision="selected",
            ),
        )
        prior = {
            "evaluable_count": 8,
            "next_high_hit_rate_at_threshold": 0.45,
            "next_close_positive_rate": 0.60,
        }
        targets = {"000002": ev}
        apply_p3_prior_quality_gate_to_selection_targets(targets, mode="enforce", prior_by_ticker={"000002": prior})

        assert ev.p3_execution_blocked is False

    def test_mode_off_does_not_block(self):
        ev = DualTargetEvaluation(
            ticker="000003",
            trade_date="2026-04-22",
            short_trade=TargetEvaluationResult(
                target_type="short_trade",
                decision="selected",
            ),
        )
        prior = {
            "evaluable_count": 1,
            "next_high_hit_rate_at_threshold": 0.0,
            "next_close_positive_rate": 0.30,
        }
        targets = {"000003": ev}
        apply_p3_prior_quality_gate_to_selection_targets(targets, mode="off", prior_by_ticker={"000003": prior})

        assert ev.p3_execution_blocked is False


class TestP3GateEnforcementZeroHighHit:
    """When P3 enforce is on: zero high-hit-rate priors are rejected."""

    def test_zero_high_hit_blocks_selected(self):
        ev = DualTargetEvaluation(
            ticker="000004",
            trade_date="2026-04-22",
            short_trade=TargetEvaluationResult(
                target_type="short_trade",
                decision="selected",
            ),
        )
        prior = {
            "evaluable_count": 10,
            "next_high_hit_rate_at_threshold": 0.0,
            "next_close_positive_rate": 0.70,
        }
        targets = {"000004": ev}
        apply_p3_prior_quality_gate_to_selection_targets(targets, mode="enforce", prior_by_ticker={"000004": prior})

        assert ev.p3_execution_blocked is True
        assert ev.p3_prior_quality_label == "reject"


class TestP3GateEnforcementWatchOnly:
    """When P3 enforce is on: low close+ downgrades selected to watch_only (blocked)."""

    def test_low_close_positive_rate_blocks_selected(self):
        ev = DualTargetEvaluation(
            ticker="000005",
            trade_date="2026-04-22",
            short_trade=TargetEvaluationResult(
                target_type="short_trade",
                decision="selected",
            ),
        )
        prior = {
            "evaluable_count": 8,
            "next_high_hit_rate_at_threshold": 0.35,
            "next_close_positive_rate": 0.40,
        }
        targets = {"000005": ev}
        apply_p3_prior_quality_gate_to_selection_targets(targets, mode="enforce", prior_by_ticker={"000005": prior})

        assert ev.p3_execution_blocked is True
        assert ev.p3_prior_quality_label == "watch_only"

    def test_near_miss_not_blocked_by_watch_only_when_n_ge_3(self):
        """watch_only priors can still enter near_miss if n >= 3."""
        ev = DualTargetEvaluation(
            ticker="000006",
            trade_date="2026-04-22",
            short_trade=TargetEvaluationResult(
                target_type="short_trade",
                decision="near_miss",
            ),
        )
        prior = {
            "evaluable_count": 5,
            "next_high_hit_rate_at_threshold": 0.35,
            "next_close_positive_rate": 0.40,
        }
        targets = {"000006": ev}
        apply_p3_prior_quality_gate_to_selection_targets(targets, mode="enforce", prior_by_ticker={"000006": prior})

        assert ev.p3_execution_blocked is False

    def test_near_miss_blocked_when_n_lt_3(self):
        """near_miss blocked when n < 3 in enforce mode."""
        ev = DualTargetEvaluation(
            ticker="000007",
            trade_date="2026-04-22",
            short_trade=TargetEvaluationResult(
                target_type="short_trade",
                decision="near_miss",
            ),
        )
        prior = {
            "evaluable_count": 2,
            "next_high_hit_rate_at_threshold": 0.35,
            "next_close_positive_rate": 0.40,
        }
        targets = {"000007": ev}
        apply_p3_prior_quality_gate_to_selection_targets(targets, mode="enforce", prior_by_ticker={"000007": prior})

        assert ev.p3_execution_blocked is True


# ---------------------------------------------------------------------------
# P3 artifact payload
# ---------------------------------------------------------------------------


class TestP3ArtifactPayload:
    """DualTargetEvaluation must expose P3 prior quality fields after gate enforcement."""

    def test_evaluation_has_p3_prior_quality_label_field(self):
        ev = DualTargetEvaluation(ticker="000001", trade_date="2026-04-22")
        assert hasattr(ev, "p3_prior_quality_label")
        assert ev.p3_prior_quality_label is None

    def test_evaluation_has_p3_execution_blocked_field(self):
        ev = DualTargetEvaluation(ticker="000001", trade_date="2026-04-22")
        assert hasattr(ev, "p3_execution_blocked")
        assert ev.p3_execution_blocked is False

    def test_evaluation_has_p3_execution_block_reason_field(self):
        ev = DualTargetEvaluation(ticker="000001", trade_date="2026-04-22")
        assert hasattr(ev, "p3_execution_block_reason")
        assert ev.p3_execution_block_reason is None

    def test_evaluation_has_p3_sample_size_field(self):
        ev = DualTargetEvaluation(ticker="000001", trade_date="2026-04-22")
        assert hasattr(ev, "p3_sample_size")

    def test_gate_sets_label_and_reason_in_evaluation(self):
        ev = DualTargetEvaluation(
            ticker="000001",
            trade_date="2026-04-22",
            short_trade=TargetEvaluationResult(
                target_type="short_trade",
                decision="selected",
            ),
        )
        prior = {
            "evaluable_count": 2,
            "next_high_hit_rate_at_threshold": 0.0,
            "next_close_positive_rate": 0.30,
        }
        targets = {"000001": ev}
        apply_p3_prior_quality_gate_to_selection_targets(targets, mode="enforce", prior_by_ticker={"000001": prior})

        assert ev.p3_prior_quality_label is not None
        assert ev.p3_sample_size == 2
        assert ev.p3_execution_block_reason is not None


# ---------------------------------------------------------------------------
# Profile threshold honoring (P3 spec: thresholds must come from active profile)
# ---------------------------------------------------------------------------


class TestClassifyPriorQualityProfileThresholds:
    """classify_prior_quality must respect caller-supplied threshold overrides.

    These tests document that the four thresholds are actual parameters, not
    module-level hardcoded constants invisible to the caller.
    """

    def test_custom_min_n_selected_raises_bar(self):
        """When min_n_selected=10, n=7 must be blocked (default threshold of 5 would pass)."""
        result = classify_prior_quality(
            evaluable_count=7,
            next_high_hit_rate_at_threshold=0.40,
            next_close_positive_rate=0.60,
            min_n_selected=10,
        )
        assert result.selected_blocked is True, (
            "n=7 must be selected_blocked when min_n_selected=10"
        )

    def test_custom_min_n_selected_below_default_relaxes_bar(self):
        """When min_n_selected=3, n=4 must not block selected (default threshold of 5 would block)."""
        result = classify_prior_quality(
            evaluable_count=4,
            next_high_hit_rate_at_threshold=0.40,
            next_close_positive_rate=0.60,
            min_n_selected=3,
        )
        assert result.selected_blocked is False, (
            "n=4 must NOT be selected_blocked when min_n_selected=3"
        )

    def test_custom_min_n_near_miss_raises_bar(self):
        """When min_n_near_miss=5, n=3 must block near_miss (default of 3 would allow it)."""
        result = classify_prior_quality(
            evaluable_count=3,
            next_high_hit_rate_at_threshold=0.40,
            next_close_positive_rate=0.60,
            min_n_selected=5,
            min_n_near_miss=5,
        )
        assert result.near_miss_blocked is True, (
            "n=3 must be near_miss_blocked when min_n_near_miss=5"
        )

    def test_custom_min_n_near_miss_below_default_relaxes_bar(self):
        """When min_n_near_miss=1, n=2 must not block near_miss (default of 3 would block)."""
        result = classify_prior_quality(
            evaluable_count=2,
            next_high_hit_rate_at_threshold=0.40,
            next_close_positive_rate=0.60,
            min_n_near_miss=1,
        )
        assert result.near_miss_blocked is False, (
            "n=2 must NOT be near_miss_blocked when min_n_near_miss=1"
        )

    def test_custom_close_positive_min_raises_bar(self):
        """When close_positive_min=0.70, rate=0.55 must be watch_only (default 0.50 would pass)."""
        result = classify_prior_quality(
            evaluable_count=10,
            next_high_hit_rate_at_threshold=0.40,
            next_close_positive_rate=0.55,
            close_positive_min=0.70,
        )
        assert result.label == PriorQualityLabel.WATCH_ONLY, (
            "rate=0.55 must be WATCH_ONLY when close_positive_min=0.70"
        )

    def test_custom_close_positive_min_below_default_relaxes_bar(self):
        """When close_positive_min=0.30, rate=0.40 must not be watch_only (default 0.50 would)."""
        result = classify_prior_quality(
            evaluable_count=10,
            next_high_hit_rate_at_threshold=0.40,
            next_close_positive_rate=0.40,
            close_positive_min=0.30,
        )
        assert result.label == PriorQualityLabel.EXECUTION_READY, (
            "rate=0.40 must be EXECUTION_READY when close_positive_min=0.30"
        )

    def test_default_thresholds_unchanged(self):
        """Verify default thresholds still produce same outcomes as the spec."""
        # n=4 is below default min_n_selected=5 → selected_blocked
        r1 = classify_prior_quality(
            evaluable_count=4,
            next_high_hit_rate_at_threshold=0.40,
            next_close_positive_rate=0.60,
        )
        assert r1.selected_blocked is True

        # n=5 is equal to default min_n_selected=5 → not selected_blocked
        r2 = classify_prior_quality(
            evaluable_count=5,
            next_high_hit_rate_at_threshold=0.40,
            next_close_positive_rate=0.60,
        )
        assert r2.selected_blocked is False

        # n=2 < default min_n_near_miss=3 → near_miss_blocked
        r3 = classify_prior_quality(
            evaluable_count=2,
            next_high_hit_rate_at_threshold=0.40,
            next_close_positive_rate=0.60,
        )
        assert r3.near_miss_blocked is True

        # close_positive_rate=0.49 < default 0.50 → watch_only
        r4 = classify_prior_quality(
            evaluable_count=10,
            next_high_hit_rate_at_threshold=0.40,
            next_close_positive_rate=0.49,
        )
        assert r4.label == PriorQualityLabel.WATCH_ONLY


class TestApplyGateHonorsProfileThresholds:
    """apply_p3_prior_quality_gate_to_selection_targets must read all four thresholds from profile."""

    def test_profile_min_n_selected_overrides_default(self):
        """When active profile has min_n_selected=10, n=7 must be blocked."""
        from src.targets.profiles import use_short_trade_target_profile

        ev = DualTargetEvaluation(
            ticker="000001",
            trade_date="2026-04-22",
            short_trade=TargetEvaluationResult(
                target_type="short_trade",
                decision="selected",
            ),
        )
        prior = {
            "evaluable_count": 7,
            "next_high_hit_rate_at_threshold": 0.40,
            "next_close_positive_rate": 0.60,
        }
        targets = {"000001": ev}

        with use_short_trade_target_profile(
            overrides={"p3_prior_quality_min_n_selected": 10}
        ):
            apply_p3_prior_quality_gate_to_selection_targets(
                targets, mode="enforce", prior_by_ticker={"000001": prior}
            )

        assert ev.p3_execution_blocked is True, (
            "n=7 must be selected_blocked when profile.p3_prior_quality_min_n_selected=10"
        )

    def test_profile_min_n_selected_relaxed_allows_lower_n(self):
        """When active profile has min_n_selected=3, n=4 must NOT be blocked."""
        from src.targets.profiles import use_short_trade_target_profile

        ev = DualTargetEvaluation(
            ticker="000002",
            trade_date="2026-04-22",
            short_trade=TargetEvaluationResult(
                target_type="short_trade",
                decision="selected",
            ),
        )
        prior = {
            "evaluable_count": 4,
            "next_high_hit_rate_at_threshold": 0.40,
            "next_close_positive_rate": 0.60,
        }
        targets = {"000002": ev}

        with use_short_trade_target_profile(
            overrides={"p3_prior_quality_min_n_selected": 3}
        ):
            apply_p3_prior_quality_gate_to_selection_targets(
                targets, mode="enforce", prior_by_ticker={"000002": prior}
            )

        assert ev.p3_execution_blocked is False, (
            "n=4 must NOT be blocked when profile.p3_prior_quality_min_n_selected=3"
        )

    def test_profile_min_n_near_miss_overrides_default(self):
        """When active profile has min_n_near_miss=5, n=3 must block near_miss."""
        from src.targets.profiles import use_short_trade_target_profile

        ev = DualTargetEvaluation(
            ticker="000003",
            trade_date="2026-04-22",
            short_trade=TargetEvaluationResult(
                target_type="short_trade",
                decision="near_miss",
            ),
        )
        prior = {
            "evaluable_count": 3,
            "next_high_hit_rate_at_threshold": 0.40,
            "next_close_positive_rate": 0.60,
        }
        targets = {"000003": ev}

        with use_short_trade_target_profile(
            overrides={
                "p3_prior_quality_min_n_near_miss": 5,
                "p3_prior_quality_min_n_selected": 5,
            }
        ):
            apply_p3_prior_quality_gate_to_selection_targets(
                targets, mode="enforce", prior_by_ticker={"000003": prior}
            )

        assert ev.p3_execution_blocked is True, (
            "n=3 near_miss must be blocked when profile.p3_prior_quality_min_n_near_miss=5"
        )

    def test_profile_close_positive_min_overrides_default(self):
        """When active profile has close_positive_min=0.70, rate=0.55 must be watch_only/blocked."""
        from src.targets.profiles import use_short_trade_target_profile

        ev = DualTargetEvaluation(
            ticker="000004",
            trade_date="2026-04-22",
            short_trade=TargetEvaluationResult(
                target_type="short_trade",
                decision="selected",
            ),
        )
        prior = {
            "evaluable_count": 10,
            "next_high_hit_rate_at_threshold": 0.40,
            "next_close_positive_rate": 0.55,
        }
        targets = {"000004": ev}

        with use_short_trade_target_profile(
            overrides={"p3_prior_quality_close_positive_min": 0.70}
        ):
            apply_p3_prior_quality_gate_to_selection_targets(
                targets, mode="enforce", prior_by_ticker={"000004": prior}
            )

        assert ev.p3_execution_blocked is True, (
            "rate=0.55 must be blocked when profile.p3_prior_quality_close_positive_min=0.70"
        )

    def test_default_profile_produces_same_behavior_as_hardcoded(self):
        """Default profile thresholds must produce identical outcomes to old hardcoded behavior."""
        from src.targets.profiles import use_short_trade_target_profile

        ev = DualTargetEvaluation(
            ticker="000005",
            trade_date="2026-04-22",
            short_trade=TargetEvaluationResult(
                target_type="short_trade",
                decision="selected",
            ),
        )
        # n=4 → selected_blocked under default threshold of 5
        prior = {
            "evaluable_count": 4,
            "next_high_hit_rate_at_threshold": 0.40,
            "next_close_positive_rate": 0.60,
        }
        targets = {"000005": ev}
        # Use default profile (no overrides)
        with use_short_trade_target_profile():
            apply_p3_prior_quality_gate_to_selection_targets(
                targets, mode="enforce", prior_by_ticker={"000005": prior}
            )

        assert ev.p3_execution_blocked is True, (
            "n=4 must still be blocked under default profile (backward compat)"
        )
