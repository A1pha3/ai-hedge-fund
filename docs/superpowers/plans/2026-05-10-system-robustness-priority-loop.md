# System Robustness Priority Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a closed-loop robustness upgrade that unifies BTST research metrics, execution realism, and rollout promotion gating so sample-out winners are also execution-aware and rollout-safe.

**Architecture:** Add three small shared backtesting helpers instead of stuffing more logic into large existing modules: one canonical BTST evaluation-bundle helper, one dynamic trading-constraint resolver, and one promotion-gate helper. Then wire those helpers into the existing param-search, trade execution, walk-forward, diagnostics, artifact, and runtime-observability paths so the same vocabulary is reused end-to-end.

**Tech Stack:** Python 3.11+/`uv run`, existing backtesting and BTST pipeline modules under `src/`, pytest, existing BTST regression tests, JSON artifact serialization

---

## File Structure

- Read: `docs/superpowers/specs/2026-05-10-system-robustness-priority-loop-design.md` — approved design spec and source of truth.
- Create: `src/backtesting/evaluation_bundle.py` — canonical BTST metric bundle helper that separates objective metrics, guardrail metrics, and context metrics.
- Create: `src/backtesting/trading_constraints.py` — dynamic trade-constraint resolver that maps liquidity/crowding/gap/exposure inputs to per-trade execution constraints.
- Create: `src/backtesting/promotion_gate.py` — shared promotion-gate helper that merges walk-forward rollout signals with risk-budget and exposure blockers.
- Modify: `src/backtesting/param_search.py` — consume the canonical evaluation bundle instead of reading raw BTST metrics ad hoc.
- Modify: `src/research/artifacts.py` — persist canonical evaluation-bundle payloads into replay artifacts where BTST metrics are already serialized.
- Modify: `src/backtesting/trader.py` — allow `TradeExecutor` to resolve dynamic per-trade constraints and surface last-trade diagnostics.
- Modify: `src/backtesting/engine_agent_mode.py` — pass baseline turnover inputs through the new execution-input interface.
- Modify: `src/backtesting/engine_pipeline_decisions.py` — pass BTST execution fragility fields into the new execution-input interface.
- Modify: `src/backtesting/walk_forward.py` — attach promotion-gate outputs to the existing rollout summary.
- Modify: `src/backtesting/cli.py` — print promotion-gate readiness/blockers next to the existing rollout summary.
- Modify: `src/execution/daily_pipeline_buy_diagnostics_helpers.py` — emit promotion-gate input payloads from the existing BTST risk-budget overlay summary.
- Modify: `src/paper_trading/runtime_observability_helpers.py` — accumulate promotion-gate counts using the same helper logic.
- Test: `tests/backtesting/test_param_search.py`
- Test: `tests/research/test_selection_artifact_writer.py`
- Test: `tests/backtesting/test_trading_constraints.py`
- Test: `tests/backtesting/test_walk_forward.py`
- Test: `tests/backtesting/test_cli.py`
- Test: `tests/test_btst_risk_budget_overlay.py`
- Test: `tests/backtesting/test_paper_trading_runtime.py`

### Task 1: Canonicalize the BTST evaluation bundle

**Files:**
- Create: `src/backtesting/evaluation_bundle.py`
- Modify: `src/backtesting/param_search.py`
- Modify: `src/research/artifacts.py`
- Test: `tests/backtesting/test_param_search.py`
- Test: `tests/research/test_selection_artifact_writer.py`

- [ ] **Step 1: Write the failing tests for the canonical bundle and artifact payload**

Add these tests:

```python
# tests/backtesting/test_param_search.py
from src.backtesting.evaluation_bundle import build_canonical_btst_evaluation_bundle


def test_build_canonical_btst_evaluation_bundle_separates_metric_roles():
    bundle = build_canonical_btst_evaluation_bundle(
        {
            "next_close_positive_rate": 0.58,
            "next_close_payoff_ratio": 1.9,
            "next_close_expectancy": 0.012,
            "next_high_hit_rate": 0.61,
            "t_plus_2_close_positive_rate": 0.55,
            "t_plus_3_close_positive_rate": 0.52,
            "t_plus_3_close_expectancy": 0.011,
            "downside_p10": -0.031,
            "sample_weight": 0.74,
            "projected_theme_exposure": 0.18,
        }
    )

    assert bundle.objective_metrics["next_close_positive_rate"] == pytest.approx(0.58)
    assert bundle.guardrail_metrics["downside_p10"] == pytest.approx(-0.031)
    assert bundle.context_metrics["projected_theme_exposure"] == pytest.approx(0.18)
```

```python
# tests/research/test_selection_artifact_writer.py
def test_file_selection_artifact_writer_includes_canonical_btst_evaluation_bundle(tmp_path):
    writer = FileSelectionArtifactWriter(artifact_root=tmp_path, run_id="session_eval_bundle")
    watchlist = [
        LayerCResult(
            ticker="688183",
            score_b=0.66,
            score_c=0.21,
            score_final=0.55,
            quality_score=0.64,
            decision="watch",
            metrics={
                "next_close_positive_rate": 0.58,
                "next_close_payoff_ratio": 1.9,
                "next_close_expectancy": 0.012,
                "next_high_hit_rate": 0.61,
                "t_plus_2_close_positive_rate": 0.55,
                "t_plus_3_close_positive_rate": 0.52,
                "t_plus_3_close_expectancy": 0.011,
                "downside_p10": -0.031,
                "sample_weight": 0.74,
                "projected_theme_exposure": 0.18,
            },
        )
    ]
    selection_targets, dual_target_summary = build_selection_targets(
        trade_date="20260322",
        watchlist=watchlist,
        rejected_entries=[],
        buy_order_tickers=set(),
        target_mode="short_trade_only",
    )
    plan = ExecutionPlan(
        date="20260322",
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        risk_metrics={"counts": {"watchlist_count": 1}, "funnel_diagnostics": {"filters": {}}},
        watchlist=watchlist,
        target_mode="short_trade_only",
        selection_targets=selection_targets,
        dual_target_summary=dual_target_summary,
    )

    result = writer.write_for_plan(plan=plan, trade_date="20260322", pipeline=None, selected_analysts=None)
    replay_input_payload = json.loads(Path(result.replay_input_path).read_text(encoding="utf-8"))
    bundle = replay_input_payload["watchlist"][0]["metrics"]["canonical_btst_evaluation_bundle"]

    assert bundle["objective_metrics"]["next_close_positive_rate"] == pytest.approx(0.58)
    assert bundle["guardrail_metrics"]["downside_p10"] == pytest.approx(-0.031)
    assert bundle["context_metrics"]["projected_theme_exposure"] == pytest.approx(0.18)
```

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork
uv run pytest tests/backtesting/test_param_search.py tests/research/test_selection_artifact_writer.py -k "canonical_btst_evaluation_bundle" -v
```

Expected: FAIL with an import error or missing-key assertion because `build_canonical_btst_evaluation_bundle()` and the serialized bundle do not exist yet.

- [ ] **Step 3: Create the new canonical bundle helper**

Create `src/backtesting/evaluation_bundle.py` with:

```python
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


_OBJECTIVE_KEYS = (
    "next_close_positive_rate",
    "next_close_payoff_ratio",
    "next_close_expectancy",
    "next_high_hit_rate",
    "t_plus_2_close_positive_rate",
    "t_plus_3_close_positive_rate",
    "t_plus_3_close_expectancy",
    "sample_weight",
)
_GUARDRAIL_KEYS = (
    "downside_p10",
    "projected_theme_exposure",
    "incremental_theme_exposure",
)
_CONTEXT_KEYS = (
    "theme_direction_peer_count",
    "theme_direction_rank",
    "liquidity_capacity_raw_100",
    "crowding_risk_raw_100",
    "gap_risk_raw_100",
)


@dataclass(frozen=True)
class CanonicalBTSTEvaluationBundle:
    objective_metrics: dict[str, float | None]
    guardrail_metrics: dict[str, float | None]
    context_metrics: dict[str, float | None]

    def lookup(self, key: str) -> float | None:
        if key in self.objective_metrics:
            return self.objective_metrics[key]
        if key in self.guardrail_metrics:
            return self.guardrail_metrics[key]
        return self.context_metrics.get(key)

    def to_payload(self) -> dict[str, dict[str, float | None]]:
        return {
            "objective_metrics": dict(self.objective_metrics),
            "guardrail_metrics": dict(self.guardrail_metrics),
            "context_metrics": dict(self.context_metrics),
        }


def _collect_numeric_metrics(metrics: dict[str, Any], keys: Sequence[str]) -> dict[str, float | None]:
    return {
        key: (None if metrics.get(key) is None else float(metrics[key]))
        for key in keys
    }


def build_canonical_btst_evaluation_bundle(metrics: dict[str, Any] | None) -> CanonicalBTSTEvaluationBundle:
    payload = dict(metrics or {})
    return CanonicalBTSTEvaluationBundle(
        objective_metrics=_collect_numeric_metrics(payload, _OBJECTIVE_KEYS),
        guardrail_metrics=_collect_numeric_metrics(payload, _GUARDRAIL_KEYS),
        context_metrics=_collect_numeric_metrics(payload, _CONTEXT_KEYS),
    )
```

- [ ] **Step 4: Wire `param_search.py` and `artifacts.py` to use the helper**

Update `src/backtesting/param_search.py` and `src/research/artifacts.py` like this:

```python
# src/backtesting/param_search.py
from .evaluation_bundle import build_canonical_btst_evaluation_bundle


def compute_objective_score(metrics: dict[str, float | None], objective: SearchObjective) -> float | None:
    bundle = build_canonical_btst_evaluation_bundle(metrics)
    if objective == SearchObjective.EDGE:
        win_rate = bundle.lookup("next_close_positive_rate")
        payoff_ratio = bundle.lookup("next_close_payoff_ratio")
        expectancy = bundle.lookup("next_close_expectancy")
        next_high_hit_rate = bundle.lookup("next_high_hit_rate")
        t_plus_2_positive_rate = bundle.lookup("t_plus_2_close_positive_rate")
        downside_p10 = bundle.lookup("downside_p10")
        sample_weight = bundle.lookup("sample_weight")
        if (
            win_rate is None
            or payoff_ratio is None
            or expectancy is None
            or next_high_hit_rate is None
            or t_plus_2_positive_rate is None
            or downside_p10 is None
        ):
            return None
        normalized_payoff = clip(float(payoff_ratio) / 3.0, 0.0, 1.0)
        normalized_expectancy = clip((float(expectancy) + 0.03) / 0.06, 0.0, 1.0)
        downside_penalty = clip(abs(float(downside_p10)) / 0.06, 0.0, 1.0)
        effective_sample_weight = clip(float(sample_weight or 0.0), 0.0, 1.0)
        edge_score = (
            (0.28 * float(win_rate))
            + (0.22 * normalized_payoff)
            + (0.16 * float(next_high_hit_rate))
            + (0.14 * float(t_plus_2_positive_rate))
            + (0.20 * normalized_expectancy)
            - (0.18 * downside_penalty)
        )
        return edge_score * (0.40 + (0.60 * effective_sample_weight))


def check_guardrails(metrics: dict[str, float | None], guardrails: dict[str, float]) -> list[str]:
    bundle = build_canonical_btst_evaluation_bundle(metrics)
    violations: list[str] = []
    for key, floor in guardrails.items():
        value = bundle.lookup(key)
        if value is None or float(value) < float(floor):
            violations.append(key)
    return violations
```

```python
# src/research/artifacts.py
from src.backtesting.evaluation_bundle import build_canonical_btst_evaluation_bundle


def _serialize_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    payload = dict(metrics or {})
    bundle = build_canonical_btst_evaluation_bundle(payload)
    payload["canonical_btst_evaluation_bundle"] = bundle.to_payload()
    return payload
```

- [ ] **Step 5: Run the task-local regression tests**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork
uv run pytest tests/backtesting/test_param_search.py tests/research/test_selection_artifact_writer.py -k "canonical_btst_evaluation_bundle or guardrail" -v
```

Expected: PASS for the new canonical-bundle tests and existing guardrail tests.

- [ ] **Step 6: Commit the evaluation-bundle changes**

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork
git add src/backtesting/evaluation_bundle.py src/backtesting/param_search.py src/research/artifacts.py tests/backtesting/test_param_search.py tests/research/test_selection_artifact_writer.py
git commit -m "feat: unify canonical BTST evaluation bundle"
```

### Task 2: Make trade execution constraints dynamic and BTST-aware

**Files:**
- Create: `src/backtesting/trading_constraints.py`
- Modify: `src/backtesting/trader.py`
- Modify: `src/backtesting/engine_agent_mode.py`
- Modify: `src/backtesting/engine_pipeline_decisions.py`
- Test: `tests/backtesting/test_trading_constraints.py`

- [ ] **Step 1: Write the failing tests for dynamic trade constraints**

Create `tests/backtesting/test_trading_constraints.py` with:

```python
from src.backtesting.portfolio import Portfolio
from src.backtesting.trader import TradeExecutor
from src.backtesting.trading_constraints import TradeExecutionInputs, TradingConstraints, resolve_trade_constraints


def test_resolve_trade_constraints_tightens_costs_for_crowded_low_capacity_trade():
    resolved = resolve_trade_constraints(
        TradingConstraints(),
        TradeExecutionInputs(
            daily_turnover=20_000_000.0,
            liquidity_capacity_raw_100=42.0,
            crowding_risk_raw_100=78.0,
            gap_risk_raw_100=64.0,
            projected_theme_exposure=0.31,
            incremental_theme_exposure=0.14,
        ),
    )

    assert resolved.constraint_bucket == "tightened"
    assert resolved.constraints.base_slippage_rate > 0.0015
    assert resolved.capacity_penalty_ratio > 0.0


def test_trade_executor_records_last_trade_diagnostics():
    portfolio = Portfolio(tickers=["300724"], initial_cash=100000.0, margin_requirement=0.0)
    executor = TradeExecutor()

    executed = executor.execute_trade(
        "300724",
        "buy",
        1000,
        10.0,
        portfolio,
        execution_inputs=TradeExecutionInputs(
            daily_turnover=20_000_000.0,
            liquidity_capacity_raw_100=42.0,
            crowding_risk_raw_100=78.0,
            gap_risk_raw_100=64.0,
        ),
        trade_date="20260422",
    )

    assert executed > 0
    assert executor.get_last_trade_diagnostics()["constraint_bucket"] == "tightened"
```

- [ ] **Step 2: Run the new test file and confirm it fails**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork
uv run pytest tests/backtesting/test_trading_constraints.py -v
```

Expected: FAIL because `trading_constraints.py`, `TradeExecutionInputs`, and `get_last_trade_diagnostics()` do not exist yet.

- [ ] **Step 3: Create the dynamic constraint resolver**

Create `src/backtesting/trading_constraints.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TradingConstraints:
    commission_rate: float = 0.00025
    stamp_duty_rate: float = 0.001
    base_slippage_rate: float = 0.0015
    low_liquidity_slippage_rate: float = 0.003
    low_liquidity_turnover_threshold: float = 50_000_000.0


@dataclass(frozen=True)
class TradeExecutionInputs:
    daily_turnover: float | None = None
    liquidity_capacity_raw_100: float | None = None
    crowding_risk_raw_100: float | None = None
    gap_risk_raw_100: float | None = None
    projected_theme_exposure: float | None = None
    incremental_theme_exposure: float | None = None


@dataclass(frozen=True)
class ResolvedTradeConstraints:
    constraints: TradingConstraints
    constraint_bucket: str
    capacity_penalty_ratio: float
    diagnostics: dict[str, float | str | None]


def resolve_trade_constraints(base: TradingConstraints, inputs: TradeExecutionInputs | None) -> ResolvedTradeConstraints:
    payload = inputs or TradeExecutionInputs()
    slippage = base.base_slippage_rate
    capacity_penalty_ratio = 0.0
    constraint_bucket = "baseline"

    if payload.daily_turnover is not None and payload.daily_turnover < base.low_liquidity_turnover_threshold:
        slippage = max(slippage, base.low_liquidity_slippage_rate)
        constraint_bucket = "tightened"
    if payload.liquidity_capacity_raw_100 is not None and payload.liquidity_capacity_raw_100 < 50.0:
        slippage += 0.001
        capacity_penalty_ratio += 0.15
        constraint_bucket = "tightened"
    if payload.crowding_risk_raw_100 is not None and payload.crowding_risk_raw_100 >= 70.0:
        slippage += 0.0005
        capacity_penalty_ratio += 0.10
        constraint_bucket = "tightened"
    if payload.gap_risk_raw_100 is not None and payload.gap_risk_raw_100 >= 60.0:
        slippage += 0.0005
        constraint_bucket = "tightened"

    resolved = TradingConstraints(
        commission_rate=base.commission_rate,
        stamp_duty_rate=base.stamp_duty_rate,
        base_slippage_rate=round(slippage, 6),
        low_liquidity_slippage_rate=max(base.low_liquidity_slippage_rate, round(slippage, 6)),
        low_liquidity_turnover_threshold=base.low_liquidity_turnover_threshold,
    )
    return ResolvedTradeConstraints(
        constraints=resolved,
        constraint_bucket=constraint_bucket,
        capacity_penalty_ratio=round(min(capacity_penalty_ratio, 0.35), 4),
        diagnostics={
            "constraint_bucket": constraint_bucket,
            "resolved_slippage_rate": resolved.base_slippage_rate,
            "capacity_penalty_ratio": round(min(capacity_penalty_ratio, 0.35), 4),
        },
    )
```

- [ ] **Step 4: Wire the resolver into the trade executor and both execution call sites**

Update `src/backtesting/trader.py`, `src/backtesting/engine_agent_mode.py`, and `src/backtesting/engine_pipeline_decisions.py` like this:

```python
# src/backtesting/trader.py
from typing import Any

from .trading_constraints import TradeExecutionInputs, TradingConstraints, resolve_trade_constraints


class TradeExecutor:
    def __init__(self, constraints: TradingConstraints | None = None) -> None:
        self._constraints = constraints or TradingConstraints()
        self._last_trade_diagnostics: dict[str, Any] = {}

    def get_last_trade_diagnostics(self) -> dict[str, Any]:
        return dict(self._last_trade_diagnostics)

    def execute_trade(
        self,
        ticker: str,
        action: ActionLiteral,
        quantity: float,
        current_price: float,
        portfolio: Portfolio,
        *,
        is_limit_up: bool = False,
        is_limit_down: bool = False,
        daily_turnover: float | None = None,
        execution_inputs: TradeExecutionInputs | None = None,
        trade_date: str | None = None,
    ) -> int:
        resolved = resolve_trade_constraints(
            self._constraints,
            execution_inputs or TradeExecutionInputs(daily_turnover=daily_turnover),
        )
        self._last_trade_diagnostics = dict(resolved.diagnostics)
        slippage_rate = resolved.constraints.base_slippage_rate
        action_enum = coerce_trade_action(action)
        if action_enum == Action.BUY:
            if is_limit_up:
                return 0
            return execute_buy_trade(ticker, quantity, current_price, portfolio, slippage_rate, resolved.constraints.commission_rate)
        if action_enum == Action.SELL:
            if is_limit_down:
                return 0
            return execute_sell_trade(
                ticker,
                quantity,
                current_price,
                portfolio,
                slippage_rate,
                resolved.constraints.commission_rate,
                resolved.constraints.stamp_duty_rate,
                trade_date,
            )
        if action_enum == Action.SHORT:
            return execute_short_trade(ticker, quantity, current_price, portfolio, slippage_rate, resolved.constraints.commission_rate)
        if action_enum == Action.COVER:
            return execute_cover_trade(ticker, quantity, current_price, portfolio, slippage_rate, resolved.constraints.commission_rate)
        return 0
```

```python
# src/backtesting/engine_agent_mode.py
from .trading_constraints import TradeExecutionInputs

executed_qty = executor.execute_trade(
    ticker,
    action,
    decision.get("quantity", 0),
    current_prices[ticker],
    portfolio,
    execution_inputs=TradeExecutionInputs(daily_turnover=None),
    trade_date=trade_date,
)
```

```python
# src/backtesting/engine_pipeline_decisions.py
from .trading_constraints import TradeExecutionInputs

return self._executor.execute_trade(
    ticker,
    decision["action"],
    decision["quantity"],
    price,
    self._portfolio,
    is_limit_up=normalized_ticker in limit_up,
    is_limit_down=normalized_ticker in limit_down,
    daily_turnover=daily_turnovers.get(ticker),
    execution_inputs=TradeExecutionInputs(
        daily_turnover=daily_turnovers.get(ticker),
        liquidity_capacity_raw_100=_safe_float(decision.get("liquidity_capacity_raw_100")),
        crowding_risk_raw_100=_safe_float(decision.get("crowding_risk_raw_100")),
        gap_risk_raw_100=_safe_float(decision.get("gap_risk_raw_100")),
        projected_theme_exposure=_safe_float(decision.get("projected_theme_exposure")),
        incremental_theme_exposure=_safe_float(decision.get("incremental_theme_exposure")),
    ),
    trade_date=trade_date,
)
```

- [ ] **Step 5: Run the new execution-constraint tests**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork
uv run pytest tests/backtesting/test_trading_constraints.py -v
```

Expected: PASS. The resolver should tighten slippage for fragile trades and the executor should expose the last-trade diagnostics.

- [ ] **Step 6: Commit the dynamic-constraint changes**

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork
git add src/backtesting/trading_constraints.py src/backtesting/trader.py src/backtesting/engine_agent_mode.py src/backtesting/engine_pipeline_decisions.py tests/backtesting/test_trading_constraints.py
git commit -m "feat: add dynamic BTST trade constraints"
```

### Task 3: Unify rollout, risk-budget, and promotion gating

**Files:**
- Create: `src/backtesting/promotion_gate.py`
- Modify: `src/backtesting/walk_forward.py`
- Modify: `src/backtesting/cli.py`
- Modify: `src/execution/daily_pipeline_buy_diagnostics_helpers.py`
- Modify: `src/paper_trading/runtime_observability_helpers.py`
- Test: `tests/backtesting/test_walk_forward.py`
- Test: `tests/backtesting/test_cli.py`
- Test: `tests/test_btst_risk_budget_overlay.py`
- Test: `tests/backtesting/test_paper_trading_runtime.py`

- [ ] **Step 1: Write the failing tests for the shared promotion gate**

Add these tests:

```python
# tests/backtesting/test_walk_forward.py
from src.backtesting.promotion_gate import build_promotion_gate_summary


def test_build_promotion_gate_summary_adds_risk_budget_blocker():
    summary = build_promotion_gate_summary(
        walk_forward_summary={"rollout_ready": True, "rollout_blockers": []},
        risk_budget_summary={
            "mode": "enforce",
            "suppressed_position_summary": {"zero_budget_count": 3, "reduced_budget_count": 2},
            "formal_exposure_distribution": {"zero_budget": 3, "reduced": 2},
        },
        exposure_summary={"max_projected_theme_exposure": 0.36, "max_incremental_theme_exposure": 0.14},
    )

    assert summary["promotion_ready"] is False
    assert "risk_budget_suppression_exceeded" in summary["promotion_blockers"]
    assert "theme_exposure_cap_breach" in summary["promotion_blockers"]
```

```python
# tests/backtesting/test_cli.py
from types import SimpleNamespace

import src.backtesting.cli as cli


def test_run_walk_forward_mode_prints_promotion_gate_summary(capsys):
    args = SimpleNamespace(
        start_date="2026-01-01",
        end_date="2026-04-30",
        train_months=1,
        test_months=1,
        step_months=1,
        max_test_trading_days=None,
        window_mode="rolling",
        walk_forward_preset=None,
    )
    original_build = cli.build_walk_forward_windows
    original_run = cli.run_walk_forward
    original_summary = cli.summarize_walk_forward
    try:
        cli.build_walk_forward_windows = lambda *args, **kwargs: [SimpleNamespace(test_start="2026-02-01", test_end="2026-02-28")]
        cli.run_walk_forward = lambda windows, factory: ["stub-result"]
        cli.summarize_walk_forward = lambda results: {
            "window_count": 1,
            "avg_sharpe": 0.1,
            "avg_sortino": 0.2,
            "avg_max_drawdown": -8.0,
            "rollout_ready": False,
            "rollout_blockers": ["majority_non_positive_sharpe_windows"],
            "promotion_ready": False,
            "promotion_blockers": ["risk_budget_suppression_exceeded"],
        }
        assert cli._run_walk_forward_mode(args, lambda _start, _end: object()) == 0
    finally:
        cli.build_walk_forward_windows = original_build
        cli.run_walk_forward = original_run
        cli.summarize_walk_forward = original_summary
    assert "Promotion Ready: NO" in captured.out
    assert "Promotion Blockers: risk_budget_suppression_exceeded" in captured.out
```

```python
# tests/test_btst_risk_budget_overlay.py
def test_btst_risk_budget_overlay_summary_emits_promotion_gate_inputs(monkeypatch):
    monkeypatch.setenv("BTST_0422_P6_RISK_BUDGET_MODE", "enforce")
    watchlist = [_watchlist_item(score_final=0.55, quality_score=0.5)]
    selection_targets = {"300724": _selection_target(gate="normal_trade", prior_quality_label="execution_ready", execution_eligible=True)}
    buy_orders, diagnostics = build_buy_orders_with_diagnostics(
        watchlist=watchlist,
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        trade_date="20260422",
        candidate_by_ticker={"300724": CandidateStock(ticker="300724", name="Test", industry_sw="电子", avg_volume_20d=1000000.0)},
        price_map={"300724": 10.0},
        blocked_buy_tickers={},
        selection_targets=selection_targets,
        normalize_blocked_buy_tickers_fn=lambda payload: payload or {},
        build_filter_summary_fn=lambda entries: {"filtered_count": len(entries), "reason_counts": {}, "tickers": entries},
        build_reentry_filter_entry_fn=lambda *args, **kwargs: None,
        resolve_continuation_execution_overrides_fn=lambda **kwargs: {},
        calculate_position_fn=__import__("src.portfolio.position_calculator", fromlist=["calculate_position"]).calculate_position,
        enforce_daily_trade_limit_fn=lambda plans, nav: plans,
    )
    assert diagnostics["btst_risk_budget_overlay"]["promotion_gate_inputs"]["mode"] == "enforce"
    assert diagnostics["btst_risk_budget_overlay"]["promotion_gate_inputs"]["suppressed_position_summary"]["reduced_budget_count"] >= 0
```

- [ ] **Step 2: Run the promotion-gate tests to verify they fail**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork
uv run pytest tests/backtesting/test_walk_forward.py tests/backtesting/test_cli.py tests/test_btst_risk_budget_overlay.py -k "promotion_gate or Promotion Ready" -v
```

Expected: FAIL because `build_promotion_gate_summary()` and the new summary fields do not exist yet.

- [ ] **Step 3: Create the shared promotion-gate helper**

Create `src/backtesting/promotion_gate.py` with:

```python
from __future__ import annotations

from typing import Any


def build_promotion_gate_summary(
    *,
    walk_forward_summary: dict[str, Any],
    risk_budget_summary: dict[str, Any] | None = None,
    exposure_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blockers = [str(item) for item in list(walk_forward_summary.get("rollout_blockers") or []) if str(item).strip()]
    risk_payload = dict(risk_budget_summary or {})
    exposure_payload = dict(exposure_summary or {})
    suppressed = dict(risk_payload.get("suppressed_position_summary") or {})

    if str(risk_payload.get("mode") or "off").strip().lower() == "enforce":
        zero_budget_count = int(suppressed.get("zero_budget_count") or 0)
        reduced_budget_count = int(suppressed.get("reduced_budget_count") or 0)
        if zero_budget_count > 0 or reduced_budget_count >= 3:
            blockers.append("risk_budget_suppression_exceeded")

    max_projected = float(exposure_payload.get("max_projected_theme_exposure") or 0.0)
    max_incremental = float(exposure_payload.get("max_incremental_theme_exposure") or 0.0)
    if max_projected >= 0.35 or max_incremental >= 0.12:
        blockers.append("theme_exposure_cap_breach")

    deduped_blockers = list(dict.fromkeys(blockers))
    return {
        "promotion_ready": not deduped_blockers,
        "promotion_blockers": deduped_blockers,
    }
```

- [ ] **Step 4: Wire the helper into walk-forward, CLI, BTST diagnostics, and runtime observability**

Apply these edits:

```python
# src/backtesting/walk_forward.py
from .promotion_gate import build_promotion_gate_summary

base_summary = {
    "window_count": len(results),
    "avg_sharpe": _average(sharpe_values),
    "avg_sortino": _average(sortino_values),
    "avg_max_drawdown": _average(max_drawdown_values),
    "positive_sharpe_window_count": positive_sharpe_window_count,
    "negative_sharpe_window_count": negative_sharpe_window_count,
    "zero_sharpe_window_count": zero_sharpe_window_count,
    "non_positive_sharpe_window_count": non_positive_sharpe_window_count,
    "positive_sharpe_window_ratio": positive_sharpe_window_ratio,
    "worst_sharpe": min(sharpe_values) if sharpe_values else None,
    "worst_max_drawdown": worst_max_drawdown,
    "max_non_positive_sharpe_streak": max_non_positive_sharpe_streak,
    "rollout_ready": not rollout_blockers,
    "rollout_blockers": rollout_blockers,
}
promotion_summary = build_promotion_gate_summary(walk_forward_summary=base_summary)
return {**base_summary, **promotion_summary}
```

```python
# src/backtesting/cli.py
if summary.get("promotion_ready") is not None:
    print(f"Promotion Ready: {'YES' if bool(summary['promotion_ready']) else 'NO'}")
    promotion_blockers = [str(blocker) for blocker in list(summary.get('promotion_blockers') or []) if str(blocker or '').strip()]
    if promotion_blockers:
        print(f"Promotion Blockers: {', '.join(promotion_blockers)}")
```

```python
# src/execution/daily_pipeline_buy_diagnostics_helpers.py
overlay_summary = _build_btst_risk_budget_overlay_summary(
    candidate_plans=candidate_plans,
    filtered_entries=filtered_entries,
)
overlay_summary["promotion_gate_inputs"] = {
    "mode": str(overlay_summary.get("mode") or "off"),
    "gate_distribution": dict(overlay_summary.get("gate_distribution") or {}),
    "formal_exposure_distribution": dict(overlay_summary.get("formal_exposure_distribution") or {}),
    "suppressed_position_summary": dict(overlay_summary.get("suppressed_position_summary") or {}),
}
summary["btst_risk_budget_overlay"] = overlay_summary
```

```python
# src/paper_trading/runtime_observability_helpers.py
from src.backtesting.promotion_gate import build_promotion_gate_summary

promotion_summary = build_promotion_gate_summary(
    walk_forward_summary={"rollout_blockers": []},
    risk_budget_summary=p6_payload,
    exposure_summary={
        "max_projected_theme_exposure": max_projected_theme_exposure,
        "max_incremental_theme_exposure": max_incremental_theme_exposure,
    },
)
summary["btst_promotion_gate_summary"] = promotion_summary
```

- [ ] **Step 5: Run the promotion-gate regression tests**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork
uv run pytest tests/backtesting/test_walk_forward.py tests/backtesting/test_cli.py tests/test_btst_risk_budget_overlay.py tests/backtesting/test_paper_trading_runtime.py -k "promotion_gate or rollout or risk_budget" -v
```

Expected: PASS. The walk-forward summary, CLI output, BTST diagnostics, and runtime summary should all agree on the promotion-gate vocabulary.

- [ ] **Step 6: Commit the promotion-gate changes**

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork
git add src/backtesting/promotion_gate.py src/backtesting/walk_forward.py src/backtesting/cli.py src/execution/daily_pipeline_buy_diagnostics_helpers.py src/paper_trading/runtime_observability_helpers.py tests/backtesting/test_walk_forward.py tests/backtesting/test_cli.py tests/test_btst_risk_budget_overlay.py tests/backtesting/test_paper_trading_runtime.py
git commit -m "feat: unify rollout and promotion gating"
```

### Task 4: Run the focused full-loop regression suite

**Files:**
- Read: `docs/superpowers/specs/2026-05-10-system-robustness-priority-loop-design.md`
- Read: `docs/superpowers/plans/2026-05-10-system-robustness-priority-loop.md`
- Test: `tests/backtesting/test_param_search.py`
- Test: `tests/research/test_selection_artifact_writer.py`
- Test: `tests/backtesting/test_trading_constraints.py`
- Test: `tests/backtesting/test_walk_forward.py`
- Test: `tests/backtesting/test_cli.py`
- Test: `tests/test_btst_risk_budget_overlay.py`
- Test: `tests/execution/test_phase4_execution.py`

- [ ] **Step 1: Run the focused regression suite for the three-task loop**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork
uv run pytest \
  tests/backtesting/test_param_search.py \
  tests/research/test_selection_artifact_writer.py \
  tests/backtesting/test_trading_constraints.py \
  tests/backtesting/test_walk_forward.py \
  tests/backtesting/test_cli.py \
  tests/test_btst_risk_budget_overlay.py \
  tests/execution/test_phase4_execution.py \
  -k "guardrail or canonical_btst_evaluation_bundle or trading_constraints or rollout or promotion_gate or risk_budget or theme_exposure or build_buy_orders" \
  -v
```

Expected: PASS across all affected regression surfaces.

- [ ] **Step 2: Run the existing BTST rollout/risk-budget smoke suite used by this repository**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork
uv run pytest -q tests/targets/test_short_trade_committee.py tests/test_btst_risk_budget_overlay.py tests/backtesting/test_walk_forward.py tests/backtesting/test_cli.py tests/execution/test_phase4_execution.py -k "build_buy_orders or risk_budget or theme_exposure or incremental_theme_exposure or rollout or walk_forward"
```

Expected: PASS. This confirms the new closed-loop vocabulary did not break the existing BTST safety surfaces.

- [ ] **Step 3: Inspect the diff for vocabulary drift before the final commit**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork
git --no-pager diff -- src/backtesting src/execution src/research tests | sed -n '1,240p'
```

Expected: The diff consistently uses the same names across modules:

1. `canonical_btst_evaluation_bundle`
2. `TradeExecutionInputs`
3. `promotion_ready`
4. `promotion_blockers`

- [ ] **Step 4: Commit the final regression-backed integration pass**

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork
git add src/backtesting src/execution/daily_pipeline_buy_diagnostics_helpers.py src/research/artifacts.py src/paper_trading/runtime_observability_helpers.py tests
git commit -m "feat: close the BTST robustness loop"
```
