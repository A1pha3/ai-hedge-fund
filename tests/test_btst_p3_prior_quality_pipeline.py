"""Tests for P3 prior quality hard gate — pipeline enforcement and summary gaps.

Covers:
  1. Pipeline enforcement: _enforce_btst_prior_quality_p3 modifies plan when mode=enforce.
  2. DualTargetSummary: p3_execution_blocked_count and p3_prior_quality_distribution populated.
  3. Artifact propagation: p3 fields surfaced in plan.selection_targets and risk_metrics.
  4. Default-off: no change in behaviour when BTST_0422_P3_PRIOR_QUALITY_MODE is off.
  5. Buy-order filtering: P3-blocked tickers removed from plan.buy_orders in enforce mode.
  6. Summary refresh: plan.dual_target_summary reflects P3 counts after enforcement.
"""
from __future__ import annotations

import pytest

from src.execution.models import ExecutionPlan
from src.portfolio.models import PositionPlan
from src.targets.models import DualTargetEvaluation, DualTargetSummary, TargetEvaluationResult
from src.targets.router_build_helpers import build_dual_target_summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plan_with_selection_targets(
    targets: dict[str, DualTargetEvaluation],
) -> ExecutionPlan:
    plan = ExecutionPlan(
        date="20260422",
        portfolio_snapshot={"cash": 1_000_000, "positions": {}},
        risk_metrics={"counts": {"buy_order_count": 0}, "funnel_diagnostics": {}},
    )
    plan.selection_targets = targets  # type: ignore[assignment]
    return plan


def _make_plan_with_buy_orders(
    targets: dict[str, DualTargetEvaluation],
    buy_tickers: list[str],
) -> ExecutionPlan:
    """Create a plan that also has formal buy orders for the specified tickers."""
    plan = _make_plan_with_selection_targets(targets)
    plan.buy_orders = [PositionPlan(ticker=t, shares=100, amount=10_000.0) for t in buy_tickers]
    return plan


def _make_selected_evaluation(
    ticker: str,
    *,
    decision: str = "selected",
) -> DualTargetEvaluation:
    return DualTargetEvaluation(
        ticker=ticker,
        trade_date="20260422",
        short_trade=TargetEvaluationResult(
            target_type="short_trade",
            decision=decision,  # type: ignore[arg-type]
        ),
    )


def _bad_prior(ticker: str) -> dict:
    """Prior that fails P3 gate (n < 5, so selected blocked)."""
    return {
        "evaluable_count": 3,
        "next_high_hit_rate_at_threshold": 0.40,
        "next_close_positive_rate": 0.60,
    }


def _good_prior(ticker: str) -> dict:
    """Prior that passes P3 gate."""
    return {
        "evaluable_count": 8,
        "next_high_hit_rate_at_threshold": 0.50,
        "next_close_positive_rate": 0.65,
    }


# ---------------------------------------------------------------------------
# 1. Pipeline enforcement: _enforce_btst_prior_quality_p3 exists and is callable
# ---------------------------------------------------------------------------


class TestP3PipelineEnforcementExists:
    """_enforce_btst_prior_quality_p3 must be importable and exist in daily_pipeline."""

    def test_function_is_importable(self):
        from src.execution.daily_pipeline import _enforce_btst_prior_quality_p3  # noqa: F401

    def test_mode_constant_is_defined(self):
        from src.execution.daily_pipeline import (
            BTST_0422_P3_PRIOR_QUALITY_MODE_ENV,
            BTST_0422_P3_PRIOR_QUALITY_MODES,
        )
        assert BTST_0422_P3_PRIOR_QUALITY_MODE_ENV == "BTST_0422_P3_PRIOR_QUALITY_MODE"
        assert "off" in BTST_0422_P3_PRIOR_QUALITY_MODES
        assert "enforce" in BTST_0422_P3_PRIOR_QUALITY_MODES


# ---------------------------------------------------------------------------
# 2. Pipeline enforcement: mode=off is a no-op
# ---------------------------------------------------------------------------


class TestP3PipelineOffModeIsNoop:
    """When BTST_0422_P3_PRIOR_QUALITY_MODE is off (or unset), the plan is unchanged."""

    def test_mode_off_does_not_set_p3_execution_blocked(self, monkeypatch):
        from src.execution.daily_pipeline import _enforce_btst_prior_quality_p3

        monkeypatch.delenv("BTST_0422_P3_PRIOR_QUALITY_MODE", raising=False)
        ev = _make_selected_evaluation("000001")
        plan = _make_plan_with_selection_targets({"000001": ev})
        prior_by_ticker = {"000001": _bad_prior("000001")}

        result = _enforce_btst_prior_quality_p3(plan, prior_by_ticker=prior_by_ticker)
        assert result.selection_targets["000001"].p3_execution_blocked is False

    def test_mode_explicit_off_does_not_set_p3_execution_blocked(self, monkeypatch):
        from src.execution.daily_pipeline import _enforce_btst_prior_quality_p3

        monkeypatch.setenv("BTST_0422_P3_PRIOR_QUALITY_MODE", "off")
        ev = _make_selected_evaluation("000001")
        plan = _make_plan_with_selection_targets({"000001": ev})
        prior_by_ticker = {"000001": _bad_prior("000001")}

        result = _enforce_btst_prior_quality_p3(plan, prior_by_ticker=prior_by_ticker)
        assert result.selection_targets["000001"].p3_execution_blocked is False

    def test_mode_off_returns_same_plan_object(self, monkeypatch):
        from src.execution.daily_pipeline import _enforce_btst_prior_quality_p3

        monkeypatch.setenv("BTST_0422_P3_PRIOR_QUALITY_MODE", "off")
        ev = _make_selected_evaluation("000001")
        plan = _make_plan_with_selection_targets({"000001": ev})
        result = _enforce_btst_prior_quality_p3(plan, prior_by_ticker={})
        assert result is plan


# ---------------------------------------------------------------------------
# 3. Pipeline enforcement: mode=enforce blocks bad priors
# ---------------------------------------------------------------------------


class TestP3PipelineEnforceModeBlocks:
    """When enforce, selection_targets with bad priors must be marked p3_execution_blocked."""

    def test_bad_prior_blocks_selected_in_enforce(self, monkeypatch):
        from src.execution.daily_pipeline import _enforce_btst_prior_quality_p3

        monkeypatch.setenv("BTST_0422_P3_PRIOR_QUALITY_MODE", "enforce")
        ev = _make_selected_evaluation("000001")
        plan = _make_plan_with_selection_targets({"000001": ev})
        prior_by_ticker = {"000001": _bad_prior("000001")}

        result = _enforce_btst_prior_quality_p3(plan, prior_by_ticker=prior_by_ticker)
        assert result.selection_targets["000001"].p3_execution_blocked is True

    def test_good_prior_not_blocked_in_enforce(self, monkeypatch):
        from src.execution.daily_pipeline import _enforce_btst_prior_quality_p3

        monkeypatch.setenv("BTST_0422_P3_PRIOR_QUALITY_MODE", "enforce")
        ev = _make_selected_evaluation("000002")
        plan = _make_plan_with_selection_targets({"000002": ev})
        prior_by_ticker = {"000002": _good_prior("000002")}

        result = _enforce_btst_prior_quality_p3(plan, prior_by_ticker=prior_by_ticker)
        assert result.selection_targets["000002"].p3_execution_blocked is False

    def test_zero_high_hit_rate_blocks_selected_in_enforce(self, monkeypatch):
        from src.execution.daily_pipeline import _enforce_btst_prior_quality_p3

        monkeypatch.setenv("BTST_0422_P3_PRIOR_QUALITY_MODE", "enforce")
        ev = _make_selected_evaluation("000003")
        plan = _make_plan_with_selection_targets({"000003": ev})
        prior_by_ticker = {"000003": {
            "evaluable_count": 10,
            "next_high_hit_rate_at_threshold": 0.0,
            "next_close_positive_rate": 0.70,
        }}

        result = _enforce_btst_prior_quality_p3(plan, prior_by_ticker=prior_by_ticker)
        assert result.selection_targets["000003"].p3_execution_blocked is True
        assert result.selection_targets["000003"].p3_prior_quality_label == "reject"

    def test_ticker_without_prior_is_not_blocked(self, monkeypatch):
        """When no prior data exists for a ticker, it must not be blocked."""
        from src.execution.daily_pipeline import _enforce_btst_prior_quality_p3

        monkeypatch.setenv("BTST_0422_P3_PRIOR_QUALITY_MODE", "enforce")
        ev = _make_selected_evaluation("000004")
        plan = _make_plan_with_selection_targets({"000004": ev})

        result = _enforce_btst_prior_quality_p3(plan, prior_by_ticker={})
        assert result.selection_targets["000004"].p3_execution_blocked is False

    def test_enforce_records_enforcement_in_risk_metrics(self, monkeypatch):
        """Enforcement payload must be recorded in risk_metrics for audit."""
        from src.execution.daily_pipeline import _enforce_btst_prior_quality_p3

        monkeypatch.setenv("BTST_0422_P3_PRIOR_QUALITY_MODE", "enforce")
        ev = _make_selected_evaluation("000001")
        plan = _make_plan_with_selection_targets({"000001": ev})
        prior_by_ticker = {"000001": _bad_prior("000001")}

        result = _enforce_btst_prior_quality_p3(plan, prior_by_ticker=prior_by_ticker)
        risk = result.risk_metrics or {}
        assert "btst_prior_quality_p3_enforcement" in risk, "enforcement payload must appear in risk_metrics"
        payload = risk["btst_prior_quality_p3_enforcement"]
        assert payload.get("mode") == "enforce"

    def test_enforce_updates_funnel_diagnostics(self, monkeypatch):
        """Funnel diagnostics must also record P3 enforcement payload."""
        from src.execution.daily_pipeline import _enforce_btst_prior_quality_p3

        monkeypatch.setenv("BTST_0422_P3_PRIOR_QUALITY_MODE", "enforce")
        ev = _make_selected_evaluation("000001")
        plan = _make_plan_with_selection_targets({"000001": ev})
        prior_by_ticker = {"000001": _bad_prior("000001")}

        result = _enforce_btst_prior_quality_p3(plan, prior_by_ticker=prior_by_ticker)
        funnel = (result.risk_metrics or {}).get("funnel_diagnostics", {})
        assert "btst_prior_quality_p3_enforcement" in funnel


# ---------------------------------------------------------------------------
# 4. DualTargetSummary: p3 counts and distribution populated
# ---------------------------------------------------------------------------


class TestDualTargetSummaryP3Fields:
    """build_dual_target_summary must aggregate p3_execution_blocked_count and distribution."""

    def test_p3_execution_blocked_count_incremented(self):
        ev = DualTargetEvaluation(
            ticker="000001",
            trade_date="20260422",
            short_trade=TargetEvaluationResult(target_type="short_trade", decision="selected"),
            p3_execution_blocked=True,
            p3_prior_quality_label="watch_only",
            p3_sample_size=3,
        )
        targets = {"000001": ev}
        summary = build_dual_target_summary(selection_targets=targets, target_mode="dual_target")
        assert summary.p3_execution_blocked_count == 1

    def test_p3_execution_blocked_count_zero_when_none_blocked(self):
        ev = DualTargetEvaluation(
            ticker="000001",
            trade_date="20260422",
            short_trade=TargetEvaluationResult(target_type="short_trade", decision="selected"),
            p3_execution_blocked=False,
            p3_prior_quality_label="execution_ready",
        )
        targets = {"000001": ev}
        summary = build_dual_target_summary(selection_targets=targets, target_mode="dual_target")
        assert summary.p3_execution_blocked_count == 0

    def test_p3_prior_quality_distribution_populated(self):
        e1 = DualTargetEvaluation(
            ticker="000001", trade_date="20260422",
            p3_prior_quality_label="watch_only",
        )
        e2 = DualTargetEvaluation(
            ticker="000002", trade_date="20260422",
            p3_prior_quality_label="execution_ready",
        )
        e3 = DualTargetEvaluation(
            ticker="000003", trade_date="20260422",
            p3_prior_quality_label="watch_only",
        )
        targets = {"000001": e1, "000002": e2, "000003": e3}
        summary = build_dual_target_summary(selection_targets=targets, target_mode="dual_target")
        assert summary.p3_prior_quality_distribution.get("watch_only") == 2
        assert summary.p3_prior_quality_distribution.get("execution_ready") == 1

    def test_p3_prior_quality_distribution_empty_when_no_labels(self):
        ev = DualTargetEvaluation(ticker="000001", trade_date="20260422")
        targets = {"000001": ev}
        summary = build_dual_target_summary(selection_targets=targets, target_mode="dual_target")
        assert summary.p3_prior_quality_distribution == {}

    def test_p3_execution_blocked_count_multiple(self):
        targets = {}
        for i in range(3):
            targets[f"00000{i+1}"] = DualTargetEvaluation(
                ticker=f"00000{i+1}",
                trade_date="20260422",
                p3_execution_blocked=True,
                p3_prior_quality_label="reject",
            )
        # One not blocked
        targets["000004"] = DualTargetEvaluation(
            ticker="000004",
            trade_date="20260422",
            p3_execution_blocked=False,
        )
        summary = build_dual_target_summary(selection_targets=targets, target_mode="dual_target")
        assert summary.p3_execution_blocked_count == 3


# ---------------------------------------------------------------------------
# 5. Artifact propagation: p3 fields on DualTargetEvaluation survive serialization
# ---------------------------------------------------------------------------


class TestP3ArtifactPropagation:
    """p3 fields must survive model_dump so they appear in selection artifact context."""

    def test_p3_prior_quality_label_in_model_dump(self):
        ev = DualTargetEvaluation(
            ticker="000001",
            trade_date="20260422",
            p3_prior_quality_label="watch_only",
            p3_sample_size=4,
            p3_execution_blocked=True,
            p3_execution_block_reason="p3_prior_quality:watch_only:sample_small",
        )
        dumped = ev.model_dump()
        assert dumped["p3_prior_quality_label"] == "watch_only"
        assert dumped["p3_sample_size"] == 4
        assert dumped["p3_execution_blocked"] is True
        assert dumped["p3_execution_block_reason"] == "p3_prior_quality:watch_only:sample_small"

    def test_p3_fields_populated_by_pipeline_function_survive_dump(self, monkeypatch):
        from src.execution.daily_pipeline import _enforce_btst_prior_quality_p3

        monkeypatch.setenv("BTST_0422_P3_PRIOR_QUALITY_MODE", "enforce")
        ev = _make_selected_evaluation("000001")
        plan = _make_plan_with_selection_targets({"000001": ev})
        prior_by_ticker = {"000001": _bad_prior("000001")}

        result = _enforce_btst_prior_quality_p3(plan, prior_by_ticker=prior_by_ticker)
        target = result.selection_targets["000001"]
        dumped = target.model_dump()
        assert dumped["p3_execution_blocked"] is True
        assert dumped["p3_prior_quality_label"] is not None
        assert dumped["p3_sample_size"] == 3
        assert dumped["p3_execution_block_reason"] is not None

    def test_risk_metrics_p3_summary_count_matches_blocked_targets(self, monkeypatch):
        """risk_metrics enforcement payload must include p3_execution_blocked_count."""
        from src.execution.daily_pipeline import _enforce_btst_prior_quality_p3

        monkeypatch.setenv("BTST_0422_P3_PRIOR_QUALITY_MODE", "enforce")
        ev1 = _make_selected_evaluation("000001")
        ev2 = _make_selected_evaluation("000002")
        plan = _make_plan_with_selection_targets({"000001": ev1, "000002": ev2})
        prior_by_ticker = {
            "000001": _bad_prior("000001"),  # blocked
            "000002": _good_prior("000002"),  # not blocked
        }

        result = _enforce_btst_prior_quality_p3(plan, prior_by_ticker=prior_by_ticker)
        payload = (result.risk_metrics or {}).get("btst_prior_quality_p3_enforcement", {})
        assert payload.get("p3_execution_blocked_count") == 1


# ---------------------------------------------------------------------------
# 6. P1/P2 behaviour must remain intact (regression guard)
# ---------------------------------------------------------------------------


class TestP3DoesNotAffectP1P2:
    """P3 enforcement must not interfere with P1/P2 gate results."""

    def test_p2_execution_blocked_survives_p3_call(self, monkeypatch):
        from src.execution.daily_pipeline import _enforce_btst_prior_quality_p3

        monkeypatch.setenv("BTST_0422_P3_PRIOR_QUALITY_MODE", "enforce")
        ev = DualTargetEvaluation(
            ticker="000001",
            trade_date="20260422",
            p2_execution_blocked=True,
            short_trade=TargetEvaluationResult(target_type="short_trade", decision="selected"),
        )
        plan = _make_plan_with_selection_targets({"000001": ev})

        result = _enforce_btst_prior_quality_p3(plan, prior_by_ticker={})
        # P2 blocked state must not be cleared
        assert result.selection_targets["000001"].p2_execution_blocked is True

    def test_p3_off_does_not_clear_p2_blocked(self, monkeypatch):
        from src.execution.daily_pipeline import _enforce_btst_prior_quality_p3

        monkeypatch.setenv("BTST_0422_P3_PRIOR_QUALITY_MODE", "off")
        ev = DualTargetEvaluation(
            ticker="000001",
            trade_date="20260422",
            p2_execution_blocked=True,
        )
        plan = _make_plan_with_selection_targets({"000001": ev})

        result = _enforce_btst_prior_quality_p3(plan, prior_by_ticker={})
        assert result.selection_targets["000001"].p2_execution_blocked is True


# ---------------------------------------------------------------------------
# 7. Gap fix — buy-order filtering in enforce mode  (GAP 1)
# ---------------------------------------------------------------------------


class TestP3EnforceBuyOrderFiltering:
    """In enforce mode, plan.buy_orders must NOT contain P3-blocked tickers."""

    def test_blocked_ticker_removed_from_buy_orders(self, monkeypatch):
        """The buy order for a P3-blocked ticker is dropped in enforce mode."""
        from src.execution.daily_pipeline import _enforce_btst_prior_quality_p3

        monkeypatch.setenv("BTST_0422_P3_PRIOR_QUALITY_MODE", "enforce")
        ev = _make_selected_evaluation("000001")
        plan = _make_plan_with_buy_orders({"000001": ev}, buy_tickers=["000001"])
        assert len(plan.buy_orders) == 1

        result = _enforce_btst_prior_quality_p3(plan, prior_by_ticker={"000001": _bad_prior("000001")})

        assert result.selection_targets["000001"].p3_execution_blocked is True
        remaining = [o.ticker for o in result.buy_orders]
        assert "000001" not in remaining, "P3-blocked ticker must not remain in buy_orders"

    def test_unblocked_ticker_stays_in_buy_orders(self, monkeypatch):
        """A ticker passing P3 gate keeps its buy order."""
        from src.execution.daily_pipeline import _enforce_btst_prior_quality_p3

        monkeypatch.setenv("BTST_0422_P3_PRIOR_QUALITY_MODE", "enforce")
        ev = _make_selected_evaluation("000002")
        plan = _make_plan_with_buy_orders({"000002": ev}, buy_tickers=["000002"])

        result = _enforce_btst_prior_quality_p3(plan, prior_by_ticker={"000002": _good_prior("000002")})

        assert result.selection_targets["000002"].p3_execution_blocked is False
        remaining = [o.ticker for o in result.buy_orders]
        assert "000002" in remaining, "Passing ticker must keep its buy order"

    def test_mixed_only_blocked_ticker_removed(self, monkeypatch):
        """Only the P3-blocked ticker is removed; passing tickers stay."""
        from src.execution.daily_pipeline import _enforce_btst_prior_quality_p3

        monkeypatch.setenv("BTST_0422_P3_PRIOR_QUALITY_MODE", "enforce")
        ev_bad = _make_selected_evaluation("000001")
        ev_good = _make_selected_evaluation("000002")
        plan = _make_plan_with_buy_orders(
            {"000001": ev_bad, "000002": ev_good},
            buy_tickers=["000001", "000002"],
        )
        prior_by_ticker = {
            "000001": _bad_prior("000001"),
            "000002": _good_prior("000002"),
        }

        result = _enforce_btst_prior_quality_p3(plan, prior_by_ticker=prior_by_ticker)

        remaining = [o.ticker for o in result.buy_orders]
        assert "000001" not in remaining
        assert "000002" in remaining

    def test_off_mode_buy_orders_unchanged(self, monkeypatch):
        """Off mode must not touch buy_orders even if a prior would fail P3."""
        from src.execution.daily_pipeline import _enforce_btst_prior_quality_p3

        monkeypatch.setenv("BTST_0422_P3_PRIOR_QUALITY_MODE", "off")
        ev = _make_selected_evaluation("000001")
        plan = _make_plan_with_buy_orders({"000001": ev}, buy_tickers=["000001"])

        result = _enforce_btst_prior_quality_p3(plan, prior_by_ticker={"000001": _bad_prior("000001")})

        assert len(result.buy_orders) == 1
        assert result.buy_orders[0].ticker == "000001"

    def test_enforcement_payload_records_buy_orders_removed_count(self, monkeypatch):
        """Enforcement payload in risk_metrics must expose how many buy orders were removed."""
        from src.execution.daily_pipeline import _enforce_btst_prior_quality_p3

        monkeypatch.setenv("BTST_0422_P3_PRIOR_QUALITY_MODE", "enforce")
        ev1 = _make_selected_evaluation("000001")
        ev2 = _make_selected_evaluation("000002")
        plan = _make_plan_with_buy_orders(
            {"000001": ev1, "000002": ev2},
            buy_tickers=["000001", "000002"],
        )
        prior_by_ticker = {
            "000001": _bad_prior("000001"),
            "000002": _good_prior("000002"),
        }

        result = _enforce_btst_prior_quality_p3(plan, prior_by_ticker=prior_by_ticker)

        payload = (result.risk_metrics or {}).get("btst_prior_quality_p3_enforcement", {})
        assert payload.get("buy_orders_removed") == 1, (
            "enforcement payload must record how many buy orders were removed"
        )

    def test_no_prior_ticker_with_buy_order_is_preserved(self, monkeypatch):
        """A ticker with no prior data must not have its buy order removed."""
        from src.execution.daily_pipeline import _enforce_btst_prior_quality_p3

        monkeypatch.setenv("BTST_0422_P3_PRIOR_QUALITY_MODE", "enforce")
        ev = _make_selected_evaluation("000099")
        plan = _make_plan_with_buy_orders({"000099": ev}, buy_tickers=["000099"])

        result = _enforce_btst_prior_quality_p3(plan, prior_by_ticker={})

        remaining = [o.ticker for o in result.buy_orders]
        assert "000099" in remaining


# ---------------------------------------------------------------------------
# 8. Gap fix — plan.dual_target_summary refreshed after enforcement  (GAP 2)
# ---------------------------------------------------------------------------


class TestP3EnforceSummaryRefresh:
    """After P3 enforcement, plan.dual_target_summary must reflect current blocked counts."""

    def test_dual_target_summary_blocked_count_reflects_enforcement(self, monkeypatch):
        """plan.dual_target_summary.p3_execution_blocked_count must be updated after enforcement."""
        from src.execution.daily_pipeline import _enforce_btst_prior_quality_p3

        monkeypatch.setenv("BTST_0422_P3_PRIOR_QUALITY_MODE", "enforce")
        ev = _make_selected_evaluation("000001")
        plan = _make_plan_with_selection_targets({"000001": ev})
        # Summary starts at 0 (built before P3 enforcement)
        assert plan.dual_target_summary.p3_execution_blocked_count == 0

        result = _enforce_btst_prior_quality_p3(plan, prior_by_ticker={"000001": _bad_prior("000001")})

        assert result.dual_target_summary.p3_execution_blocked_count == 1, (
            "plan.dual_target_summary must be refreshed to reflect P3 enforcement"
        )

    def test_dual_target_summary_distribution_reflects_enforcement(self, monkeypatch):
        """plan.dual_target_summary.p3_prior_quality_distribution populated after enforcement."""
        from src.execution.daily_pipeline import _enforce_btst_prior_quality_p3

        monkeypatch.setenv("BTST_0422_P3_PRIOR_QUALITY_MODE", "enforce")
        ev = _make_selected_evaluation("000001")
        plan = _make_plan_with_selection_targets({"000001": ev})
        assert plan.dual_target_summary.p3_prior_quality_distribution == {}

        result = _enforce_btst_prior_quality_p3(plan, prior_by_ticker={"000001": _bad_prior("000001")})

        dist = result.dual_target_summary.p3_prior_quality_distribution
        assert dist, "distribution must be non-empty after enforcement"
        assert "watch_only" in dist or "reject" in dist, (
            "distribution must include the applied label"
        )

    def test_dual_target_summary_zero_when_no_enforcement_needed(self, monkeypatch):
        """When all priors pass, blocked_count stays 0 and distribution has only good labels."""
        from src.execution.daily_pipeline import _enforce_btst_prior_quality_p3

        monkeypatch.setenv("BTST_0422_P3_PRIOR_QUALITY_MODE", "enforce")
        ev = _make_selected_evaluation("000002")
        plan = _make_plan_with_selection_targets({"000002": ev})

        result = _enforce_btst_prior_quality_p3(plan, prior_by_ticker={"000002": _good_prior("000002")})

        assert result.dual_target_summary.p3_execution_blocked_count == 0
        dist = result.dual_target_summary.p3_prior_quality_distribution
        if dist:
            assert "execution_ready" in dist

    def test_dual_target_summary_unchanged_in_off_mode(self, monkeypatch):
        """Off mode must not modify plan.dual_target_summary."""
        from src.execution.daily_pipeline import _enforce_btst_prior_quality_p3

        monkeypatch.setenv("BTST_0422_P3_PRIOR_QUALITY_MODE", "off")
        ev = _make_selected_evaluation("000001")
        plan = _make_plan_with_selection_targets({"000001": ev})
        original_summary_id = id(plan.dual_target_summary)

        result = _enforce_btst_prior_quality_p3(plan, prior_by_ticker={"000001": _bad_prior("000001")})

        # In off mode, plan is returned as-is (same object, no changes)
        assert result.dual_target_summary.p3_execution_blocked_count == 0
        assert result.dual_target_summary.p3_prior_quality_distribution == {}

    def test_dual_target_summary_multiple_blocked_reflect_correctly(self, monkeypatch):
        """Multiple blocked targets are all reflected in the refreshed summary."""
        from src.execution.daily_pipeline import _enforce_btst_prior_quality_p3

        monkeypatch.setenv("BTST_0422_P3_PRIOR_QUALITY_MODE", "enforce")
        targets = {
            "000001": _make_selected_evaluation("000001"),
            "000002": _make_selected_evaluation("000002"),
            "000003": _make_selected_evaluation("000003"),
        }
        plan = _make_plan_with_selection_targets(targets)
        prior_by_ticker = {
            "000001": _bad_prior("000001"),
            "000002": _good_prior("000002"),
            "000003": _bad_prior("000003"),
        }

        result = _enforce_btst_prior_quality_p3(plan, prior_by_ticker=prior_by_ticker)

        assert result.dual_target_summary.p3_execution_blocked_count == 2


# ---------------------------------------------------------------------------
# 9. Gap fix — risk_metrics['counts']['buy_order_count'] synchronized after P3 (GAP 3)
# ---------------------------------------------------------------------------


class TestP3BuyOrderCountSynchronized:
    """After P3 removes blocked buy orders, risk_metrics['counts']['buy_order_count']
    must reflect the actual remaining buy order count (not the stale pre-enforcement value).
    This is critical when P3 runs alone with P2 off — no other stage updates the count.
    """

    def test_buy_order_count_decremented_after_p3_removes_blocked_order(self, monkeypatch):
        """buy_order_count must match len(plan.buy_orders) after P3 enforcement removes blocked ticker."""
        from src.execution.daily_pipeline import _enforce_btst_prior_quality_p3

        monkeypatch.setenv("BTST_0422_P3_PRIOR_QUALITY_MODE", "enforce")
        ev1 = _make_selected_evaluation("000001")
        ev2 = _make_selected_evaluation("000002")
        plan = _make_plan_with_buy_orders(
            {"000001": ev1, "000002": ev2},
            buy_tickers=["000001", "000002"],
        )
        # Simulate stale pre-enforcement count (as would be set by the pipeline).
        plan.risk_metrics["counts"]["buy_order_count"] = 2

        prior_by_ticker = {
            "000001": _bad_prior("000001"),   # will be blocked and removed
            "000002": _good_prior("000002"),  # passes, kept
        }

        result = _enforce_btst_prior_quality_p3(plan, prior_by_ticker=prior_by_ticker)

        remaining_count = len(result.buy_orders)
        recorded_count = (result.risk_metrics or {}).get("counts", {}).get("buy_order_count")
        assert remaining_count == 1, "one buy order must remain after P3 removes the blocked ticker"
        assert recorded_count == 1, (
            f"risk_metrics['counts']['buy_order_count'] must equal actual remaining buy orders "
            f"(got {recorded_count}, expected 1)"
        )

    def test_buy_order_count_unchanged_when_no_orders_removed(self, monkeypatch):
        """buy_order_count must not change when all tickers pass P3."""
        from src.execution.daily_pipeline import _enforce_btst_prior_quality_p3

        monkeypatch.setenv("BTST_0422_P3_PRIOR_QUALITY_MODE", "enforce")
        ev = _make_selected_evaluation("000002")
        plan = _make_plan_with_buy_orders({"000002": ev}, buy_tickers=["000002"])
        plan.risk_metrics["counts"]["buy_order_count"] = 1

        result = _enforce_btst_prior_quality_p3(plan, prior_by_ticker={"000002": _good_prior("000002")})

        assert (result.risk_metrics or {}).get("counts", {}).get("buy_order_count") == 1

    def test_buy_order_count_zero_when_all_orders_removed(self, monkeypatch):
        """buy_order_count must be 0 when all buy orders are removed by P3."""
        from src.execution.daily_pipeline import _enforce_btst_prior_quality_p3

        monkeypatch.setenv("BTST_0422_P3_PRIOR_QUALITY_MODE", "enforce")
        ev1 = _make_selected_evaluation("000001")
        ev2 = _make_selected_evaluation("000002")
        plan = _make_plan_with_buy_orders(
            {"000001": ev1, "000002": ev2},
            buy_tickers=["000001", "000002"],
        )
        plan.risk_metrics["counts"]["buy_order_count"] = 2

        prior_by_ticker = {
            "000001": _bad_prior("000001"),
            "000002": _bad_prior("000002"),
        }

        result = _enforce_btst_prior_quality_p3(plan, prior_by_ticker=prior_by_ticker)

        assert len(result.buy_orders) == 0
        assert (result.risk_metrics or {}).get("counts", {}).get("buy_order_count") == 0

    def test_buy_order_count_not_touched_in_off_mode(self, monkeypatch):
        """Off mode must not alter risk_metrics['counts']['buy_order_count']."""
        from src.execution.daily_pipeline import _enforce_btst_prior_quality_p3

        monkeypatch.setenv("BTST_0422_P3_PRIOR_QUALITY_MODE", "off")
        ev = _make_selected_evaluation("000001")
        plan = _make_plan_with_buy_orders({"000001": ev}, buy_tickers=["000001"])
        plan.risk_metrics["counts"]["buy_order_count"] = 99  # sentinel

        result = _enforce_btst_prior_quality_p3(plan, prior_by_ticker={"000001": _bad_prior("000001")})

        # Off mode returns the same plan object untouched.
        assert (result.risk_metrics or {}).get("counts", {}).get("buy_order_count") == 99
