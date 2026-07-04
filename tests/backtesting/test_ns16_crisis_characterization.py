"""NS-16 characterization tests — backtest crisis_inputs hardcoded drawdown_pct=0.0.

Background (docs/cn/product/feature-proposals.md NS-16):
  `engine_pending_plan_runner.py:263` hardcodes `crisis_inputs={"drawdown_pct": 0.0}`
  when calling `DailyPipeline.run_intraday(...)`. As a result, `evaluate_crisis_response`
  never receives a real drawdown signal in backtest, and the -10% drawdown_warning /
  -15% drawdown_forced_reduce branches (crisis_handler.py:52-62) are dead code in
  backtest. This distorts backtest risk profile: a strategy that would have been
  force-reduced during a real drawdown never triggers that circuit breaker in
  backtest, so owner's factor tuning relies on a risk-sanitized equity curve that
  does not reflect crisis behavior.

These tests are CHARACTERIZATION tests (not behavior change). They lock the current
latent-defect behavior so that any future owner decision (wire real drawdown from
equity curve, OR env-flag disable + document) MUST break these tests, forcing
explicit acknowledgment of the behavior change.

Owner decision options (NS-16 backlog):
  (a) Wire real drawdown from equity curve → backtest reflects crisis
  (b) Env-flag disable + document → explicit latent-defect marking
  (c) Status quo (these tests guard the latent defect)

Engineering decision (this commit): characterization test + design packet only.
NO production code change. Does not confound rb030/rb034/rb035 observing
attribution (test-only, no behavior delta).
"""

from __future__ import annotations

import pandas as pd

from src.backtesting.engine_pending_plan_runner import PendingPlanRunner
from src.backtesting.engine_pipeline_helpers import build_pipeline_day_context
from src.backtesting.portfolio import Portfolio
from src.execution.crisis_handler import evaluate_crisis_response
from src.execution.models import ExecutionPlan
from src.portfolio.models import PositionPlan


class _CrisisInputsCapturingPipeline:
    """Pipeline mock that captures the crisis_inputs kwarg passed to run_intraday.

    Mirrors the CapturingPipeline pattern in test_pending_plan_runner_open_gap_pct.py
    but extends it to record crisis_inputs for NS-16 characterization.
    """

    def __init__(self) -> None:
        self.last_crisis_inputs: dict | None = None
        self.last_open_gap_pct: dict | None = None

    def run_pre_market(self, plan: ExecutionPlan, trade_date_t1: str, **kwargs) -> ExecutionPlan:
        self.last_open_gap_pct = kwargs.get("open_gap_pct")
        return plan

    def run_intraday(self, plan: ExecutionPlan, trade_date_t1: str, **kwargs):
        self.last_crisis_inputs = kwargs.get("crisis_inputs")
        return [], [], {"pause_new_buys": False, "forced_reduce_ratio": 0.0}


class _NoopDecisionExecutor:
    def apply_decisions(self, **kwargs) -> None:
        return None


class TestNS16PipelineCrisisInputsHardcoded:
    """Pipeline-level characterization: PendingPlanRunner hardcodes drawdown_pct=0.0.

    Locks the latent-defect behavior described in NS-16. If owner wires real
    drawdown or env-flag-disables, this test MUST break, forcing explicit
    acknowledgment in the commit that resolves NS-16.
    """

    def test_run_pending_pipeline_plan_passes_hardcoded_drawdown_zero(self) -> None:
        """NS-16 characterization: crisis_inputs always {"drawdown_pct": 0.0}.

        Reproduces the latent defect: regardless of portfolio drawdown state,
        PendingPlanRunner passes a fixed drawdown_pct=0.0 to DailyPipeline.run_intraday,
        which feeds evaluate_crisis_response. The -10%/-15% branches in
        crisis_handler.py:52-62 are therefore unreachable in backtest.
        """
        pipeline = _CrisisInputsCapturingPipeline()
        portfolio = Portfolio(tickers=["000001"], initial_cash=100_000.0, margin_requirement=0.0)
        runner = PendingPlanRunner(pipeline=pipeline, decision_executor=_NoopDecisionExecutor(), portfolio=portfolio)

        pending_plan = ExecutionPlan(
            date="20240301",
            buy_orders=[PositionPlan(ticker="000001", shares=100, amount=10_000.0)],
        )

        day_context = build_pipeline_day_context(
            current_date=pd.Timestamp("2024-03-04"),
            active_tickers=["000001"],
            current_prices={"000001": 10.0},
            daily_turnovers={},
            limit_up=set(),
            limit_down=set(),
            load_market_data_seconds=0.0,
        )

        def build_confirmation_inputs_fn(plan: ExecutionPlan, current_prices: dict[str, float], previous_date_str: str, current_date_str: str) -> dict[str, dict]:
            return {"000001": {"open_gap_pct": 0.0}}

        def process_pending_queues_fn(**kwargs):
            return [], [], []

        runner.run_pending_pipeline_plan(
            pending_plan=pending_plan,
            day_context=day_context,
            decisions={},
            executed_trades={},
            pending_buy_queue=[],
            pending_sell_queue=[],
            build_confirmation_inputs_fn=build_confirmation_inputs_fn,
            process_pending_queues_fn=process_pending_queues_fn,
        )

        # NS-16 latent defect: drawdown_pct hardcoded to 0.0, never reflects portfolio state.
        assert pipeline.last_crisis_inputs == {"drawdown_pct": 0.0}, "NS-16 characterization broken: crisis_inputs no longer hardcodes drawdown_pct=0.0. " "If this is an intentional owner decision (wire real drawdown or env-flag disable), " "update docs/cn/product/feature-proposals.md NS-16 row and this test together. " "See crisis_handler.py:52-62 for the -10%/-15% branches that were previously dead " "in backtest."


class TestNS16PureFunctionDrawdownZeroCharacterization:
    """Pure-function characterization: drawdown_pct=0.0 (backtest hardcoded input)
    never triggers drawdown_warning or drawdown_forced_reduce alerts.

    Documents the semantic contract: 0.0 means "no drawdown signal" in backtest,
    which is the value PendingPlanRunner hardcodes. Existing test_crisis_handler.py
    covers drawdown_pct=-0.10/-0.15 triggers, but does not explicitly characterize
    the 0.0 input as the backtest hardcoded value.
    """

    def test_drawdown_zero_never_triggers_drawdown_branches(self) -> None:
        """NS-16 characterization: evaluate_crisis_response(drawdown_pct=0.0)
        produces no drawdown-related alerts and no forced_reduce_ratio.

        This is the exact input backtest pipeline passes (hardcoded at
        engine_pending_plan_runner.py:263). Locks the semantic so any future
        change to either the hardcoded value OR the threshold logic must
        explicitly update this characterization.
        """
        result = evaluate_crisis_response(
            hs300_daily_return=0.0,
            limit_down_count=0,
            recent_total_volumes=[10000, 10000, 10000],
            drawdown_pct=0.0,  # backtest hardcoded value (NS-16)
        )

        assert "drawdown_warning" not in result["alerts"], "NS-16 characterization: drawdown_pct=0.0 must not trigger drawdown_warning. " "If this breaks, crisis_handler threshold logic changed — verify backtest " "still passes drawdown_pct=0.0 (engine_pending_plan_runner.py:263)."
        assert "drawdown_forced_reduce" not in result["alerts"], "NS-16 characterization: drawdown_pct=0.0 must not trigger drawdown_forced_reduce. " "If this breaks, crisis_handler threshold logic changed — verify backtest " "still passes drawdown_pct=0.0 (engine_pending_plan_runner.py:263)."
        assert result["forced_reduce_ratio"] == 0.0
        assert result["recovery_cooldown_days"] == 0

    def test_drawdown_zero_with_other_triggers_does_not_add_drawdown_alerts(self) -> None:
        """NS-16 characterization: even when other crisis branches fire (defense/shrink),
        drawdown_pct=0.0 (backtest hardcoded) contributes no drawdown-specific alert.

        Confirms the dead-code invariant in backtest: the -10%/-15% branches are
        unreachable regardless of other trigger states, because drawdown_pct is
        always 0.0.
        """
        # defense trigger fires (hs300 <= -5%)
        result = evaluate_crisis_response(
            hs300_daily_return=-0.06,
            limit_down_count=0,
            recent_total_volumes=[10000, 10000, 10000],
            drawdown_pct=0.0,  # backtest hardcoded value (NS-16)
        )

        assert "crisis_defense_mode" in result["alerts"]
        assert "drawdown_warning" not in result["alerts"]
        assert "drawdown_forced_reduce" not in result["alerts"]
        assert result["forced_reduce_ratio"] == 0.0


def _build_and_run_runner_once() -> _CrisisInputsCapturingPipeline:
    """Build a PendingPlanRunner with a capturing pipeline + run one plan (shared fixture)."""
    pipeline = _CrisisInputsCapturingPipeline()
    portfolio = Portfolio(tickers=["000001"], initial_cash=100_000.0, margin_requirement=0.0)
    runner = PendingPlanRunner(pipeline=pipeline, decision_executor=_NoopDecisionExecutor(), portfolio=portfolio)
    pending_plan = ExecutionPlan(
        date="20240301",
        buy_orders=[PositionPlan(ticker="000001", shares=100, amount=10_000.0)],
    )
    day_context = build_pipeline_day_context(
        current_date=pd.Timestamp("2024-03-04"),
        active_tickers=["000001"],
        current_prices={"000001": 10.0},
        daily_turnovers={},
        limit_up=set(),
        limit_down=set(),
        load_market_data_seconds=0.0,
    )
    runner.run_pending_pipeline_plan(
        pending_plan=pending_plan,
        day_context=day_context,
        decisions={},
        executed_trades={},
        pending_buy_queue=[],
        pending_sell_queue=[],
        build_confirmation_inputs_fn=lambda plan, prices, prev, cur: {"000001": {"open_gap_pct": 0.0}},
        process_pending_queues_fn=lambda **kw: ([], [], []),
    )
    return pipeline


class TestNS16CrisisDisabledObservability:
    """NS-16 observability (C253, 2026-06-30): the silently-dead crisis handler must be OBSERVABLE.

    The characterization tests above lock the latent defect (drawdown hardcoded 0.0).
    This class locks the observability sibling (BH-017 family drain): PendingPlanRunner
    emits a once-per-instance WARNING disclosing that crisis scenarios are NOT simulated
    in backtest. Behavior is unchanged (crisis_inputs stays {"drawdown_pct": 0.0}); only
    a log emission is added, so the latent-defect characterization above still holds.
    """

    def test_crisis_disabled_warning_emitted_on_run(self, caplog) -> None:
        import logging

        with caplog.at_level(logging.WARNING, logger="src.backtesting.engine_pending_plan_runner"):
            _build_and_run_runner_once()
        warnings = [r for r in caplog.records if "crisis" in r.message.lower() and "disable" in r.message.lower()]
        assert len(warnings) >= 1, "NS-16 observability: backtest must warn that crisis handler is disabled"

    def test_warning_emitted_at_most_once_per_runner(self, caplog) -> None:
        """Once-per-instance: two runs of the same runner emit the warning only once."""
        import logging

        pipeline = _CrisisInputsCapturingPipeline()
        portfolio = Portfolio(tickers=["000001"], initial_cash=100_000.0, margin_requirement=0.0)
        runner = PendingPlanRunner(pipeline=pipeline, decision_executor=_NoopDecisionExecutor(), portfolio=portfolio)
        pending_plan = ExecutionPlan(date="20240301", buy_orders=[PositionPlan(ticker="000001", shares=100, amount=10_000.0)])
        day_context = build_pipeline_day_context(
            current_date=pd.Timestamp("2024-03-04"),
            active_tickers=["000001"],
            current_prices={"000001": 10.0},
            daily_turnovers={},
            limit_up=set(),
            limit_down=set(),
            load_market_data_seconds=0.0,
        )
        with caplog.at_level(logging.WARNING, logger="src.backtesting.engine_pending_plan_runner"):
            for _ in range(3):
                runner.run_pending_pipeline_plan(
                    pending_plan=pending_plan,
                    day_context=day_context,
                    decisions={},
                    executed_trades={},
                    pending_buy_queue=[],
                    pending_sell_queue=[],
                    build_confirmation_inputs_fn=lambda plan, prices, prev, cur: {"000001": {"open_gap_pct": 0.0}},
                    process_pending_queues_fn=lambda **kw: ([], [], []),
                )
        warnings = [r for r in caplog.records if "crisis" in r.message.lower() and "disable" in r.message.lower()]
        assert len(warnings) == 1, f"NS-16: warning must be once-per-instance, got {len(warnings)}"
