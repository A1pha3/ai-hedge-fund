# BacktestEngine Refactor Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Break the 1761-line God Object `BacktestEngine` into focused, testable modules under 400 lines each.

**Architecture:** Extract cohesive method groups into standalone coordinator classes that receive dependencies via constructor injection. The engine becomes a thin orchestrator delegating to specialized components. Each extraction is tested by running the existing 1490-test regression suite.

**Tech Stack:** Python 3.12, pytest, dataclasses

---

## Current State Analysis

**engine.py: 1761 lines, 99 methods** organized into these logical groups:

| Group | Lines | Methods | Target |
|-------|-------|---------|--------|
| Init/Config | 134-241 | 4 | Keep |
| Logging/Telemetry | 243-267 | 3 | Keep |
| Artifacts/Checkpoint | 268-321 | 5 | Keep |
| Market Data Loading | 322-431 | 9 | Extract |
| Daily State | 433-506 | 4 | Keep |
| Agent Mode | 507-588 | 6 | Extract |
| Pending Order Processing | 590-735 | 9 | Simplify (thin wrappers) |
| Pipeline Context Loading | 736-815 | 6 | Keep |
| **Pipeline Decision Execution** | **816-1160** | **16** | **Extract** |
| **Pending Plan Runner** | **1161-1397** | **14** | **Extract** |
| Pipeline Mode Orchestration | 1398-1511 | 6 | Keep |
| Telemetry Payload Building | 1513-1716 | 9 | Simplify |
| Public API | 1717-1760 | 5 | Keep |

**Already extracted helpers:** `engine_checkpoint_helpers.py` (77L), `engine_pending_helpers.py` (199L), `engine_pipeline_helpers.py` (171L), `engine_telemetry_helpers.py` (185L)

---

## Task 1: Extract PipelineDecisionExecutor

**Files:**
- Create: `src/backtesting/engine_pipeline_decisions.py`
- Modify: `src/backtesting/engine.py` (lines 816-1160 → delegate to new class)
- Test: `tests/backtesting/` (regression)

**What moves:** 16 methods (lines 816-1160, ~350 lines) — all pipeline decision application, trade execution, queue management, and side-effect recording.

**New class:**
```python
class PipelineDecisionExecutor:
    """Handles applying pipeline decisions, executing trades, and managing pending queues."""

    def __init__(self, *, portfolio, executor, pending_buy_queue, pending_sell_queue,
                 exit_reentry_cooldowns, normalize_ticker_fn):
        self._portfolio = portfolio
        self._executor = executor
        self._pending_buy_queue = pending_buy_queue
        self._pending_sell_queue = pending_sell_queue
        self._exit_reentry_cooldowns = exit_reentry_cooldowns
        self._normalize_ticker = normalize_ticker_fn

    def apply_decisions(self, prepared_plan, current_prices, daily_turnovers,
                        limit_up, limit_down, trade_date_compact, decisions, executed_trades):
        ...

    # ... all 16 methods move here, using self._portfolio etc.
```

**Engine changes:**
```python
# In __init__:
self._decision_executor = PipelineDecisionExecutor(
    portfolio=self._portfolio,
    executor=self._executor,
    pending_buy_queue=self._pending_buy_queue,
    pending_sell_queue=self._pending_sell_queue,
    exit_reentry_cooldowns=self._exit_reentry_cooldowns,
    normalize_ticker_fn=self._normalize_ticker,
)

# Replace self._apply_pipeline_decisions(...) with:
self._decision_executor.apply_decisions(...)
```

**Step 1:** Create `engine_pipeline_decisions.py` with the `PipelineDecisionExecutor` class, moving all 16 methods verbatim.

**Step 2:** Update `engine.py` to create `PipelineDecisionExecutor` in `_initialize_engine_components` and delegate calls.

**Step 3:** Run `uv run pytest tests/ -x -q` — must pass 1490 tests.

**Step 4:** Commit.

---

## Task 2: Extract PendingPlanRunner

**Files:**
- Create: `src/backtesting/engine_pending_plan_runner.py`
- Modify: `src/backtesting/engine.py` (lines 1161-1397)
- Test: `tests/backtesting/` (regression)

**What moves:** 14 methods (lines 1161-1397, ~240 lines) — pending pipeline plan lifecycle: prepare, run intraday stages, merge decisions.

**New class:**
```python
class PendingPlanRunner:
    """Orchestrates the pending pipeline plan lifecycle: preparation, intraday execution, and result merging."""

    def __init__(self, *, pipeline, decision_executor, portfolio, build_confirmation_inputs_fn):
        self._pipeline = pipeline
        self._decision_executor = decision_executor
        self._portfolio = portfolio
        self._build_confirmation_inputs = build_confirmation_inputs_fn

    def run_pending_plan(self, *, pending_plan, day_context, decisions, executed_trades):
        ...
```

**Step 1:** Create `engine_pending_plan_runner.py` with `PendingPlanRunner`.

**Step 2:** Update `engine.py` to create `PendingPlanRunner` and delegate.

**Step 3:** Run `uv run pytest tests/ -x -q`.

**Step 4:** Commit.

---

## Task 3: Extract AgentModeRunner

**Files:**
- Create: `src/backtesting/engine_agent_mode.py`
- Modify: `src/backtesting/engine.py` (lines 507-588)
- Test: `tests/backtesting/` (regression)

**What moves:** 6 methods (lines 507-588, ~80 lines) — the entire agent mode backtest loop.

**Step 1:** Create `engine_agent_mode.py` with `AgentModeRunner`.

**Step 2:** Update engine to delegate.

**Step 3:** Run `uv run pytest tests/ -x -q`.

**Step 4:** Commit.

---

## Task 4: Simplify thin telemetry wrappers

**Files:**
- Modify: `src/backtesting/engine.py` (lines 1513-1716)
- Test: `tests/backtesting/` (regression)

**What changes:** 9 methods are kwargs-building wrappers around `engine_telemetry_helpers.py` functions. Many can be replaced with direct calls or inlined. Target: reduce from ~200 lines to ~60 lines.

**Step 1:** Identify which telemetry methods can be replaced with direct calls to helper functions.

**Step 2:** Inline or simplify each wrapper.

**Step 3:** Run `uv run pytest tests/ -x -q`.

**Step 4:** Commit.

---

## Task 5: Extract MarketDataLoader

**Files:**
- Create: `src/backtesting/engine_market_data.py`
- Modify: `src/backtesting/engine.py` (lines 322-431)
- Test: `tests/backtesting/` (regression)

**What moves:** 9 methods (lines 322-431, ~110 lines) — market data loading, price hydration, limit state detection, cooldown management.

**Step 1:** Create `engine_market_data.py` with `MarketDataLoader`.

**Step 2:** Update engine to delegate.

**Step 3:** Run `uv run pytest tests/ -x -q`.

**Step 4:** Commit.

---

## Expected Outcome

| File | Before | After |
|------|--------|-------|
| engine.py | 1761 lines, 99 methods | ~450 lines, ~30 methods |
| engine_pipeline_decisions.py | — | ~350 lines |
| engine_pending_plan_runner.py | — | ~240 lines |
| engine_agent_mode.py | — | ~80 lines |
| engine_market_data.py | — | ~110 lines |

The engine becomes a thin orchestrator that delegates to focused components. Each component is independently testable.
