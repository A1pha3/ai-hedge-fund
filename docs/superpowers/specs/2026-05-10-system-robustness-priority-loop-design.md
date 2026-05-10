# System Robustness Priority Loop Design

## Problem

The repository has recently strengthened several BTST and backtesting surfaces, including:

1. parameter-search guardrails in `src/backtesting/param_search.py`,
2. rollout readiness checks in `src/backtesting/walk_forward.py`,
3. richer BTST committee metrics such as liquidity capacity, crowding, gap risk, fragile breakout risk, and theme exposure in `src/targets/short_trade_target_committee_helpers.py` and `src/execution/daily_pipeline_post_market_helpers.py`.

Those pieces are valuable, but they still behave more like strong local improvements than one closed-loop system. The most urgent remaining gap is not "add more signals." It is making the research objective, execution realism, and rollout gate speak the same language so that sample-out performance improves for the right reasons instead of drifting across modules.

## Current Evidence

### 1. Research quality protection exists, but the optimization surface is still fragmented

- `src/backtesting/param_search.py` already supports:
  1. BTST-specific objective scoring,
  2. hard metric guardrails,
  3. ranking failing trials after passing trials.
- That means the repository already knows how to protect critical floors such as win rate, downside, and sample quality.
- However, BTST selection and committee logic still evaluate candidates through a broader heuristic stack, which means the system can still optimize one surface while informally judging another.

### 2. Execution realism exists, but it is still too static relative to the signal stack

- `src/backtesting/trader.py` currently uses:
  1. static commission,
  2. static stamp duty,
  3. base slippage,
  4. one low-liquidity slippage step function.
- Meanwhile, BTST selection already produces richer execution-related information such as:
  1. `liquidity_capacity_raw_100`,
  2. `gap_risk`,
  3. `crowding_risk`,
  4. `projected_theme_exposure`,
  5. `incremental_theme_exposure`.
- This mismatch risks overstating paper edge because the selection stack knows more about execution fragility than the backtest executor currently prices in.

### 3. Rollout readiness exists, but it is not yet a single system-wide promotion gate

- `src/backtesting/walk_forward.py` already emits:
  1. `rollout_ready`,
  2. `rollout_blockers`,
  3. streak and drawdown-based gate logic.
- The execution and BTST pipeline also tracks theme-exposure and risk-budget style information in post-market and diagnostics surfaces.
- The remaining gap is that these checks still need to be unified into one promotion decision that determines whether a profile or configuration is eligible to move forward.

## Goals

1. Improve sample-out stability by aligning research metrics, execution realism, and rollout policy.
2. Choose only three priority tasks that form one closed loop rather than three unrelated optimizations.
3. Ensure any future "best" profile also survives realistic execution costs and rollout admission rules.

## Non-Goals

1. Do not redesign the full analyst graph or LLM routing stack.
2. Do not add a large batch of new raw alpha factors in this cycle.
3. Do not build an order-book-level microstructure simulator.
4. Do not change frontend or authentication surfaces.
5. Do not broaden into new data-provider integrations.

## Alternatives Considered

### 1. Alpha-first only

Focus only on new factors, labels, and statistical filtering.

**Rejected** because stronger research metrics alone can still produce non-portable gains if execution realism and rollout policy remain loosely coupled.

### 2. Beta-first only

Focus only on slippage, capacity, and trade execution realism.

**Rejected** because a better execution simulator cannot rescue an optimization target that still drifts across research and selection layers.

### 3. Gamma-orchestrated closed loop

Treat the next cycle as one three-part control loop:

1. unify the research objective,
2. inject execution realism into the same loop,
3. promote only what survives sample-out and risk gating.

**Recommended** because it directly targets the user's priority: stable out-of-sample returns and generalization.

## Recommended Approach

### Task 1: Unify labels, objectives, and guardrails

Owner: **alpha**

The first task is to define one canonical research-evaluation bundle for BTST and adjacent strategy optimization surfaces.

That bundle should explicitly separate:

1. **optimization targets** — the metrics we want to maximize,
2. **hard guardrails** — the metrics that must not regress,
3. **context metrics** — the diagnostics we want to observe but not directly optimize.

At minimum, the unified bundle should cover:

1. next-close win rate,
2. payoff ratio,
3. expectancy,
4. downside tail behavior,
5. sample weight / support,
6. concentration or exposure-sensitive metrics where relevant.

The goal is not to add more factors. The goal is to stop different layers from silently using different definitions of "good."

### Task 2: Connect execution realism to the main backtest path

Owner: **beta**

The second task is to make the backtest executor consume execution fragility information already produced by the BTST stack.

The main change is conceptual:

`signal quality metrics -> execution fragility features -> dynamic trading constraints -> realized backtest outcome`

The upgraded backtest path should at least support:

1. tiered or dynamic slippage,
2. capacity penalties or sizing degradation,
3. conservative handling for low-liquidity or high-gap-risk setups,
4. explicit diagnostics for which constraint path was applied.

This should remain deliberately simpler than a full market microstructure simulator. The right target is "materially more realistic than static costs," not "perfect tick-level execution."

### Task 3: Unify rollout, risk budget, and market gating

Owner: **gamma**

The third task is to establish one system-wide promotion gate that decides whether a profile is allowed to move forward after optimization or replay validation.

That gate should aggregate:

1. walk-forward rollout verdicts,
2. drawdown and streak blockers,
3. theme concentration and incremental exposure,
4. risk-budget overlay outputs,
5. kill-switch or recovery-state constraints where applicable.

The result should be a single promotion decision with explicit blockers, not several partially-overlapping readiness signals.

## Architecture

The recommended architecture is a closed loop with three ordered layers:

1. **Research layer** — canonical objective and guardrail bundle
2. **Execution layer** — dynamic trade realism derived from strategy diagnostics
3. **Promotion layer** — rollout and risk gate that decides eligibility

This preserves the existing repository structure and works mostly by tightening interfaces between current modules rather than introducing a new subsystem.

## Data Flow

The intended data flow is:

`selection / committee metrics -> canonical evaluation bundle -> parameter search + replay evaluation -> execution realism mapping -> realized backtest outputs -> walk-forward and risk-budget aggregation -> single promotion decision`

Required invariants:

1. the metrics used to optimize must be recognizable in downstream validation,
2. missing mandatory gate inputs must create blockers rather than silent passes,
3. execution realism must be traceable from diagnostics to realized outcome,
4. rollout promotion must depend on both sample-out evidence and exposure-aware risk control.

## Error Handling and Safe Defaults

1. If a required metric for the unified evaluation bundle is missing, the relevant evaluation should fail explicitly or mark the trial/profile as blocked.
2. If execution realism inputs are partially missing, the system may only fall back to an explicitly conservative default path and should record that fact in diagnostics or artifacts.
3. If rollout inputs are incomplete, the promotion gate should default to "not ready" with named blockers.
4. No layer should silently reinterpret another layer's metrics without a defined mapping.

## Validation Strategy

### Task 1 validation

Confirm that optimization, committee evaluation, and research artifacts share the same metric vocabulary and guardrail semantics.

Primary validation surfaces:

1. `tests/backtesting/test_param_search.py`
2. BTST committee-target tests
3. artifact serialization tests where metric payloads are persisted

### Task 2 validation

Confirm that execution realism changes the realized trading path rather than only adding metadata.

Primary validation surfaces:

1. backtesting trader / engine tests,
2. pipeline-mode backtesting tests,
3. BTST execution diagnostics tests where liquidity and exposure inputs already exist.

### Task 3 validation

Confirm that walk-forward, risk-budget, and rollout logic resolve to the same promotion verdict across backtesting and runtime surfaces.

Primary validation surfaces:

1. `tests/backtesting/test_walk_forward.py`
2. `tests/backtesting/test_cli.py`
3. `tests/test_btst_risk_budget_overlay.py`
4. paper-trading runtime tests where rollout state is consumed

## Success Criteria

This cycle is successful if all of the following become true:

1. the repository has one canonical definition of strategy quality for the targeted surfaces,
2. backtest results degrade or hold up in a way that reflects richer execution realism rather than static costs alone,
3. rollout eligibility is decided by one explicit promotion gate,
4. a profile cannot be considered "best" unless it passes all three layers.

## Failure Criteria

This cycle should be considered unsuccessful if:

1. optimization still uses one objective while rollout uses another implicit one,
2. execution realism remains mostly disconnected from realized results,
3. rollout verdicts can still disagree across backtesting, pipeline, and runtime surfaces,
4. the system still promotes profiles that look strong only before realistic cost and risk treatment.

## Expected Implementation Surfaces

Likely code surfaces for the next implementation plan:

1. `src/backtesting/param_search.py`
2. `src/backtesting/trader.py`
3. `src/backtesting/engine.py`
4. `src/backtesting/walk_forward.py`
5. `src/backtesting/cli.py`
6. `src/targets/short_trade_target_committee_helpers.py`
7. `src/execution/daily_pipeline_post_market_helpers.py`
8. `src/execution/daily_pipeline_buy_diagnostics_helpers.py`
9. `src/research/artifacts.py`
10. `tests/backtesting/test_walk_forward.py`
11. `tests/backtesting/test_cli.py`
12. `tests/test_btst_risk_budget_overlay.py`
13. BTST committee and execution regression tests

## Assumptions

This spec reflects user-approved priorities:

1. scope is the entire quantitative system rather than BTST only,
2. this round should produce the top three tasks plus a design/implementation plan rather than immediate code changes,
3. the primary optimization target is sample-out stability and generalization,
4. the preferred structure is the gamma-orchestrated closed loop rather than alpha-only or beta-only optimization.
