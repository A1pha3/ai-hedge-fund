# BTST Trend Continuation Governed Rollout Design

## Context

The retrospective shows the highest-upside unresolved line is still the Round 89 direction fix: stop rewarding short-term reversal and instead reward trend continuation. The repo already contains `trend_corrected_v1`, `trend_continuation_strength_v2`, and `trend_continuation_strength_v3`, but the current evidence chain is incomplete:

1. `trend_corrected_v1` has a dedicated rollout assessment and is still `hold`.
2. `trend_continuation_strength_v2` has multi-window validation, but no final rollout decision artifact.
3. `trend_continuation_strength_v3` is present in runtime/tests, but there is no governed rollout assessment artifact and the BTST skill does not know to read one.

## Approaches considered

### 1. Directly promote `trend_corrected_v1`

Fastest path to runtime adoption, but current evidence already says `hold`; this would violate the repository's rollout discipline.

### 2. Validate and govern `trend_continuation_strength_v3` against `trend_continuation_strength_v2` (**recommended**)

Treat the continuation-strength family as the live candidate branch after the Round 89 correction. Reuse the multi-window replay stack, add a dedicated rollout assessment artifact, and let the BTST skill read that artifact before describing the variant as active. This preserves discipline while still pushing the strongest unresolved alpha candidate forward.

### 3. Keep current runtime unchanged and only improve documentation

Safest, but it leaves the strongest candidate without a machine-readable promotion/hold decision, so the skill cannot consistently use the latest validated evidence.

## Recommended design

### Scope

Implement a governed rollout assessment for `trend_continuation_strength_v3` relative to `trend_continuation_strength_v2`, then teach `ai-hedge-fund-btst` to consume the resulting artifact and a dated Chinese factor note.

### Components

1. **Assessment helper/script**
   - Add a new helper and entrypoint modeled after the existing Round 89 rollout assessment.
   - Input: multi-window validation JSON for `trend_continuation_strength_v2` vs `trend_continuation_strength_v3`.
   - Output: JSON + Markdown assessment with `action=promote|hold`, blockers, and execution-eligible evidence.

2. **Skill integration**
   - Update `skills/ai-hedge-fund-btst/SKILL.md` so the skill reads the new trend-continuation rollout assessment alongside the existing Round 89 / admission-edge / strict-objective artifacts.
   - Hard rule: if the new assessment says `hold`, the skill must surface that status instead of implying the profile is production-ready.

3. **Validation artifact generation**
   - Run the multi-window validation script for `trend_continuation_strength_v2` vs `trend_continuation_strength_v3`.
   - Run the new rollout assessment script on top of that output.

4. **Chinese factor note**
   - Write a dated note under `docs/prompt/generate_file/` named with the factor and date.
   - Cover principle, uplift/limitations, how it was validated, and how the BTST skill should use it.

### Guardrails

1. Do not publish a new ready manifest unless the new assessment and current runtime artifacts support promotion.
2. Favor win-rate improvement only when payoff and downside are not worse.
3. Keep the skill evidence-first: current run artifacts still outrank historical factor notes.

### Files expected

- Add: `scripts/btst_trend_continuation_rollout_helpers.py`
- Add: `scripts/btst_trend_continuation_rollout_assessment.py`
- Add: `tests/test_btst_trend_continuation_rollout_helpers.py`
- Modify: `skills/ai-hedge-fund-btst/SKILL.md`
- Add: `docs/prompt/generate_file/btst-trend-continuation-governed-rollout-2026-05-20.md`

### Validation plan

1. Focused pytest baseline.
2. New helper/script tests.
3. Run multi-window validation for v2 vs v3.
4. Run rollout assessment script to produce JSON/MD.
5. Focused pytest again after edits.
