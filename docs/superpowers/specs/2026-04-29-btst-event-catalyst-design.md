# BTST Event-Catalyst Design

## Problem

Current BTST logic already contains catalyst-related signals such as `catalyst_freshness`, `sector_resonance`, and several catalyst-theme relief switches, but it does not treat **event-driven next-day continuation** as a first-class optimization target.

For A-share BTST, this leaves a meaningful gap:

1. Some names are not simply "strong technical breakouts" — they are **freshly catalyzed event trades** that attract next-day follow-through after announcements, policy headlines, industry catalysts, or sudden narrative re-pricing.
2. The system can currently reward catalysts indirectly, but it does not isolate the specific pattern the user wants: **good-news sensitivity that turns into next-day chasing demand**.
3. If this is implemented too aggressively, the strategy will drift into low-quality "news chasing", increasing heat-driven false positives and hurting payoff quality.

The design must therefore improve BTST T+1 win rate first, without materially worsening payoff ratio, and must do so using **only existing stable in-repo data proxies** in phase 1.

## Goals

1. Add an explicit **event-catalyst proxy score** that estimates whether a name looks like a fresh positive catalyst trade with next-day continuation potential.
2. Improve T+1 BTST selection quality while preserving existing regime gate, prior-quality, execution-contract, and risk-budget protections.
3. Start with a bounded, replay-testable design that can be evaluated on current `short_trade_only` report windows before any default rollout.

## Non-Goals

1. Do not integrate external news, announcement, or hot-list APIs in phase 1.
2. Do not turn BTST into a broad theme-rotation or pure sentiment-chasing strategy in phase 1.
3. Do not let the new score override regime gate, prior-quality gate, or clear overheat penalties.
4. Do not broadly widen candidate-pool admission or top300-like liquidity boundaries as part of this work.

## User-Approved Direction

The user approved the following constraints during brainstorming:

1. Focus the first sub-project on **good-news-driven next-day continuation**, not generic multi-day theme heat.
2. Use **existing stable data only** in phase 1.
3. Optimize for **T+1 win rate first**, with payoff ratio not materially worsening.
4. Start with a **message-proxy scoring layer** that acts as a BTST boundary refiner rather than replacing the current BTST control stack.

## Recommended Approach

### Phase 1: Event-catalyst proxy layer

Add a bounded `event_catalyst_score` that estimates the probability that a candidate is a **freshly catalyzed event trade** likely to retain demand into the next session.

This score should not be a general "good stock" score. It should specifically answer:

> Does this candidate look like a fresh catalyst-driven setup that is being recognized by the market early enough for BTST continuation, but not so overheated that the edge is already exhausted?

### Why this is the right starting point

This approach fits the current repository best:

1. The codebase already stores and uses catalyst-adjacent fields, so the new layer can be built from existing signal surfaces instead of inventing a parallel framework.
2. The system already has mature risk gates; a bounded proxy score can plug into those gates cleanly.
3. It keeps the work replay-friendly, allowing validation on current BTST report windows before any rollout.

## Alternatives Considered

### 1. Theme-heat-first model

Use sector/theme persistence as the primary driver and only treat event freshness as supporting context.

**Rejected for phase 1** because it is closer to narrative chasing than event continuation, and it is more likely to improve occasional upside while weakening T+1 stability.

### 2. Hybrid event + theme dual gate from day 1

Require both event-proxy strength and theme continuation evidence before any uplift.

**Deferred to phase 2** because it is directionally attractive but adds complexity before the event-proxy layer has been independently validated.

## Architecture

The design should add one new conceptual layer and reuse the existing BTST pipeline around it:

1. **Event proxy feature layer** — compute or derive event-catalyst component signals from current stable fields.
2. **Event confirmation layer** — distinguish likely true event continuation from generic strong-but-crowded momentum.
3. **BTST integration layer** — use the score to refine selected / near-miss boundary behavior rather than replacing the core score or gate stack.

This keeps the new logic isolated:

- the existing BTST stack still determines baseline eligibility;
- the new layer only helps identify a specific event-driven subtype of BTST candidate;
- the rollout can stay reversible and profile-based.

## Data Flow

The intended path is:

`existing candidate + short-trade features -> event proxy components -> event_catalyst_score -> bounded uplift / bounded penalty at BTST decision boundary -> existing BTST gates and reporting`

### Event proxy components

Phase-1 inputs should come from existing stable signals only:

1. **Catalyst freshness proxy**
   - `catalyst_freshness`
   - catalyst-related reason codes / candidate source hints when available

2. **Diffusion / spread confirmation**
   - `sector_resonance`
   - catalyst-theme or source-specific boundary context already used in current profiles

3. **Participation / acceptance confirmation**
   - `volume_expansion_quality`
   - `close_strength`

4. **Shape filter**
   - `trend_acceleration`
   - existing stale / extension / overhead penalties

### Score semantics

`event_catalyst_score` should be a normalized `0.0..1.0` score representing:

> the estimated probability that a candidate is an event-driven BTST continuation setup rather than a generic strong name or already-exhausted crowd trade.

The score must not mean:

- overall quality,
- long-run company quality,
- raw theme popularity,
- permission to ignore overheat or regime constraints.

## Integration Rules

Phase 1 should be intentionally conservative.

### Allowed effects

1. **Selected-boundary uplift**
   - High event-catalyst score may help a borderline candidate become selected.

2. **Near-miss retention**
   - Medium event-catalyst score may help a borderline name remain near-miss or watch-worthy instead of being fully discarded.

3. **Explanation enrichment**
   - Reporting should be able to surface that a name qualified partly because of event-proxy strength.

### Forbidden effects

1. Event score must not bypass:
   - regime gate,
   - prior-quality gate,
   - execution contract,
   - risk budget,
   - strong overheat / stale constraints.

2. Event score must not force promotion of clearly extended names solely because they look catalyst-driven.

3. Event score must not become a hidden widening of the formal tradeable surface.

## Error Handling and Safe Defaults

1. **Missing component data**
   - Missing event-proxy components should reduce confidence and default to neutral/no uplift, not hidden optimistic fallback.

2. **Conflicting evidence**
   - If catalyst freshness is strong but close/volume confirmation is weak, the score should remain bounded and conservative.

3. **Overheat conflict**
   - Strong event score with clearly bad stale/extension/overhead state should remain blocked or heavily limited.

4. **Sparse-sample windows**
   - Validation should not treat single-window improvements as rollout-ready evidence.

## Validation Strategy

Validation should happen in four steps.

### 1. Shadow evaluation

Compare baseline vs event-proxy variant on recent complete `short_trade_only` windows without changing shipped defaults.

Primary checks:

1. T+1 `next_close_positive_rate`
2. T+1 `next_close_payoff_ratio`
3. T+1 `next_high_hit_rate`
4. downside proxy such as `next_close_return_distribution.p10`

### 2. Small-window replay search

Use current replay-search infrastructure to test narrow parameter combinations for the event-proxy layer on complete mini-windows.

This is useful for identifying:

1. whether event-proxy uplift helps at all,
2. whether benefit is concentrated in narrow parameter bands,
3. whether the uplift mainly improves win rate, payoff, or only sample breadth.

### 3. Multi-window validation

Any candidate that looks promising in a mini-window must be checked across multiple windows before profile rollout.

A candidate fails if:

1. win rate improves only by materially widening low-quality names,
2. payoff ratio degrades materially,
3. benefit is isolated to one narrow topic cycle,
4. downside worsens enough to offset hit-rate gains.

### 4. Rollout gate

No shipped profile change should happen until the candidate shows:

1. T+1 win rate improvement or at least non-regression,
2. no meaningful payoff-ratio deterioration,
3. stable or improved `next_high_hit_rate`,
4. acceptable downside behavior,
5. evidence across more than one usable window.

## Success Criteria

Phase 1 is successful if all of the following hold:

1. A replay-testable event-proxy variant exists and can be compared against baseline.
2. The variant improves or preserves T+1 win rate.
3. The variant does not materially worsen T+1 payoff ratio.
4. The variant does not rely on bypassing current BTST safety gates.
5. The resulting behavior is explainable in reports and diagnostics.

## Failure Criteria

Phase 1 should be considered unsuccessful if any of the following dominate:

1. It mostly promotes already-overheated names.
2. It improves hit rate only by sacrificing payoff quality.
3. It behaves like a hidden sample-expansion trick rather than a true event-continuation edge.
4. It works only on one narrow narrative window with no broader stability.

## Expected Implementation Surfaces

Likely code areas, subject to plan refinement:

1. `src/targets/profiles.py`
2. `src/targets/short_trade_target_profile_data.py`
3. short-trade target scoring helpers under `src/targets/`
4. replay-analysis scripts:
   - `scripts/optimize_profile.py`
   - `scripts/analyze_btst_multi_window_profile_validation.py`
   - `scripts/analyze_btst_weekly_validation.py`
5. related tests under `tests/` and `tests/backtesting/`

The implementation plan should identify the exact scoring helper and profile data surfaces before any code changes.

## Phase 2 (Explicitly Deferred)

Only after phase 1 passes should the next-cycle design consider:

1. adding theme-heat persistence as a second gate,
2. modeling multi-day narrative continuation directly,
3. introducing optional external news/event sources behind a separate interface.

Phase 2 is intentionally not part of this spec.
