# BTST Win-Rate-First Runtime Adoption Design

## Problem

The repo now has three separately validated pieces:

1. a stable ready-manifest resolution path for approved BTST optimized profiles,
2. a runtime P5 precision mode that tightens `selected` to `execution_ready` names,
3. rollout governance that already blocks premature promotion of weaker candidates.

But they are not yet combined into one default BTST win-rate-first runtime path. As a result, the system can still run a legitimate `short_trade_only` BTST replay without automatically expressing the strictest already-validated T+1 precision posture.

## Goal

Design a BTST runtime adoption path that:

1. uses the ready optimized manifest whenever the run is an implicit `short_trade_only` BTST replay,
2. enables P5 win-rate-first precision automatically for that governed path,
3. preserves explicit user overrides as an intentional bypass,
4. writes enough runtime provenance for `ai-hedge-fund-btst` to describe the run truthfully.

The target of this cycle is **runtime precision adoption**, not a new profile promotion.

## Non-Goals

1. Do not promote `trend_corrected_v1` or `trend_continuation_strength_*` into the active manifest.
2. Do not weaken existing rollout, strict-objective, or structural blockers.
3. Do not force precision mode on runs that explicitly choose another profile or explicit overrides.
4. Do not claim new win-rate uplift without replay evidence.

## Alternative Approaches Considered

### 1. Promote the Round 89 continuation profile now

Pros:

1. would attack factor directionality directly,
2. could eventually unlock a larger upside.

Cons:

1. current evidence is still mixed / hold,
2. not the highest-confidence production lever today,
3. risks confusing research candidates with approved runtime behavior.

### 2. Keep runtime unchanged and only improve rollout governance

Pros:

1. low-risk,
2. reduces false promotion.

Cons:

1. mostly defensive,
2. does not immediately improve the tradeable `selected` lane,
3. leaves a validated precision control underused.

### 3. Adopt ready manifest + precision mode as the governed BTST default **(recommended)**

Pros:

1. uses already-approved profile evidence,
2. aligns directly with strict T+1 win-rate and payoff protection,
3. is easy to verify with focused replay and regression tests,
4. keeps research candidates offline until they really clear governance.

Cons:

1. narrows coverage,
2. may reduce formal `selected` counts,
3. requires careful provenance handling so users know when precision mode was auto-enabled.

## Recommended Approach

Treat the implicit BTST win-rate-first runtime path as:

`short_trade_only + no explicit short-trade profile inputs + ready optimized manifest`

When that path is active:

1. resolve the ready manifest as today,
2. automatically enable `BTST_0422_P5_WIN_RATE_FIRST_PRECISION_MODE=true`,
3. record that the precision mode came from governed runtime adoption rather than an ad hoc shell export,
4. expose that provenance in session summary / printed output so the skill can describe it accurately.

If the user supplies an explicit short-trade profile or explicit overrides, do **not** auto-enable this precision mode. That remains an intentional bypass path.

## Architecture

### Runtime wiring

1. `scripts/run_paper_trading.py`
   - derive whether the run is an implicit governed BTST adoption path,
   - set the precision env var before runtime execution,
   - carry a structured adoption payload into summary output.

2. `src/execution/daily_pipeline.py`
   - no logic change to the precision gate itself unless a small provenance hook is needed,
   - keep the existing P5 downgrade semantics unchanged.

### Skill / reporting surfaces

1. `skills/ai-hedge-fund-btst/SKILL.md`
   - document that the default multi-agent BTST path uses the ready optimized manifest,
   - and may also use the governed P5 precision gate when the runtime artifacts confirm it.

2. `docs/prompt/generate_file/<dated-doc>.md`
   - explain the principle, effect, validation, trade-offs, and usage only after replay evidence passes.

### Tests

1. `tests/test_run_paper_trading_script.py`
2. `tests/test_task1_win_rate_first_precision.py`
3. focused BTST reporting / manifest provenance tests only if the summary surface changes.

## Data Flow

The intended path is:

`CLI args -> manifest resolution -> governed runtime adoption decision -> P5 precision env -> daily pipeline P5 enforcement -> session_summary provenance -> ai-hedge-fund-btst reporting`

This keeps the adoption decision in the paper-trading entrypoint while leaving the P5 contract logic itself centralized in the execution pipeline.

## Runtime Decision Rule

Auto-enable the governed precision path only when all of the following are true:

1. `selection_target == "short_trade_only"`,
2. no explicit `--short-trade-target-profile` is supplied,
3. no explicit `--short-trade-target-overrides` is supplied,
4. manifest resolution returns `mode="optimized"`,
5. the resolved manifest status is ready / approved rather than fallback.

Otherwise:

1. preserve existing runtime behavior,
2. preserve any explicit operator-supplied precision env choice,
3. do not label the run as governed precision unless the summary payload supports it.

## Validation Plan

### Code-level validation

Add / extend tests proving:

1. implicit governed BTST runs auto-enable the precision gate,
2. explicit profile inputs bypass the auto-enable behavior,
3. default-fallback manifest resolution does not claim governed precision adoption,
4. existing P5 precision behavior still downgrades only the intended names.

### Replay validation

Run paired BTST paper-trading / replay windows:

1. ready optimized manifest with governed precision disabled baseline,
2. the same ready optimized manifest with governed precision enabled.

Compare:

1. `optimization_profile_resolution`,
2. execution-eligible counts,
3. selected vs near-miss reshaping,
4. BTST follow-up / session summary evidence tied to T+1 quality.

## Failure Criteria

Stop and keep the current default behavior if any of the following remain true:

1. governed precision reduces coverage without improving tradeable quality evidence,
2. runtime provenance is too weak to tell whether precision was auto-enabled,
3. explicit profile inputs accidentally inherit auto-enabled precision,
4. replay evidence shows payoff or win-rate protection worsens under the governed path.

## Expected Deliverables

1. a governed runtime adoption path for ready optimized BTST manifests,
2. regression tests proving when precision mode is auto-enabled and when it is not,
3. runtime provenance that downstream reporting can trust,
4. a dated Chinese validation note under `docs/prompt/generate_file/` if replay evidence supports the change.

## Decision Rule

If the ready optimized manifest plus governed P5 precision produces cleaner tradeable surfaces and survives replay / regression checks, adopt it as the default BTST win-rate-first runtime path and update `ai-hedge-fund-btst` wording accordingly. Otherwise keep the current runtime default and leave the precision gate as an opt-in control.
