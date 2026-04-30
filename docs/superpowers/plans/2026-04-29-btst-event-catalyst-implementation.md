# BTST Event-Catalyst Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a phase-1 BTST event-catalyst proxy layer that improves T+1 win-rate selection quality without materially worsening payoff ratio.

**Architecture:** Introduce a focused helper that computes an `event_catalyst_score` from existing stable short-trade snapshot fields, then wire that score into the short-trade decision boundary as a bounded uplift / bounded retention rule. Surface the score in explainability and metrics payloads, add an explicit guarded profile variant, and validate the behavior through replay/frontier tooling instead of directly changing shipped defaults.

**Tech Stack:** Python 3.12, Pydantic models, BTST target-scoring helpers under `src/targets/`, replay-analysis scripts under `scripts/`, pytest

---

## File Structure

- Create: `src/targets/short_trade_event_catalyst_helpers.py` — pure helper for computing event-catalyst proxy score, gate hits, and bounded uplifts from existing snapshot metrics.
- Modify: `src/targets/profiles.py` — extend `ShortTradeTargetProfile` with explicit event-catalyst knobs.
- Modify: `src/targets/short_trade_target.py` — call the helper, apply selected / near-miss boundary adjustments, and attach the new payload to target results.
- Modify: `src/targets/short_trade_target_evaluation_helpers.py` — extend explainability state and top-reason generation so the new score is visible and debuggable.
- Modify: `src/targets/models.py` — expose event-catalyst score in `TargetEvaluationResult`.
- Modify: `src/targets/short_trade_metrics_payload_builders.py` — add metrics/explainability payload serialization for the new score.
- Modify: `src/targets/short_trade_target_profile_data.py` — add a named `event_catalyst_guarded` profile for replay/frontier comparison.
- Modify: `scripts/analyze_btst_profile_frontier.py` — include event-catalyst fields in frontier review output.
- Modify: `scripts/optimize_profile.py` — add an event-catalyst preset grid for replay search.
- Create: `tests/targets/test_short_trade_event_catalyst_helpers.py` — unit tests for score construction and overheat blocking.
- Modify: `tests/targets/test_target_models.py` — integration tests for selected-boundary uplift and near-miss retention using existing BTST target fixtures.
- Modify: `tests/test_analyze_btst_profile_frontier_script.py` — replay/frontier regression coverage for the new guarded profile.
- Modify: `tests/test_optimize_profile_script.py` — optimizer preset-grid coverage for event-catalyst search.

## Task 1: Build the event-catalyst helper and profile knobs

**Files:**
- Create: `src/targets/short_trade_event_catalyst_helpers.py`
- Modify: `src/targets/profiles.py`
- Test: `tests/targets/test_short_trade_event_catalyst_helpers.py`

- [ ] **Step 1: Write the failing helper test**

```python
import pytest

from src.targets.profiles import build_short_trade_target_profile
from src.targets.short_trade_event_catalyst_helpers import build_event_catalyst_assessment


def test_build_event_catalyst_assessment_scores_fresh_supported_event() -> None:
    profile = build_short_trade_target_profile(
        "default",
        overrides={
            "event_catalyst_enabled": True,
            "event_catalyst_min_score_for_selected_uplift": 0.72,
            "event_catalyst_selected_uplift": 0.03,
        },
    )
    snapshot = {
        "catalyst_freshness": 0.88,
        "sector_resonance": 0.72,
        "volume_expansion_quality": 0.76,
        "close_strength": 0.74,
        "trend_acceleration": 0.68,
        "extension_without_room_penalty": 0.05,
        "stale_trend_repair_penalty": 0.04,
        "overhead_supply_penalty": 0.03,
    }

    assessment = build_event_catalyst_assessment(
        snapshot=snapshot,
        profile=profile,
        candidate_source="catalyst_theme",
        candidate_reason_codes={"catalyst_theme_candidate_score_ranked"},
    )

    assert assessment.eligible is True
    assert assessment.selected_uplift == pytest.approx(0.03)
    assert assessment.score >= 0.72


def test_build_event_catalyst_assessment_blocks_extended_candidate() -> None:
    profile = build_short_trade_target_profile("default", overrides={"event_catalyst_enabled": True})

    assessment = build_event_catalyst_assessment(
        snapshot={
            "catalyst_freshness": 0.92,
            "sector_resonance": 0.76,
            "volume_expansion_quality": 0.80,
            "close_strength": 0.82,
            "trend_acceleration": 0.70,
            "extension_without_room_penalty": 0.88,
            "stale_trend_repair_penalty": 0.06,
            "overhead_supply_penalty": 0.04,
        },
        profile=profile,
        candidate_source="catalyst_theme",
        candidate_reason_codes={"catalyst_theme_candidate_score_ranked"},
    )

    assert assessment.eligible is False
    assert assessment.selected_uplift == 0.0
    assert assessment.near_miss_threshold_relief == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/targets/test_short_trade_event_catalyst_helpers.py::test_build_event_catalyst_assessment_scores_fresh_supported_event -q`

Expected: FAIL with `ModuleNotFoundError` or `ImportError` because the helper does not exist yet.

- [ ] **Step 3: Write the minimal helper and profile fields**

```python
event_catalyst_enabled: bool = False
event_catalyst_candidate_sources: frozenset[str] = frozenset({"catalyst_theme", "short_trade_boundary"})
event_catalyst_catalyst_freshness_weight: float = 0.30
event_catalyst_sector_resonance_weight: float = 0.22
event_catalyst_volume_expansion_weight: float = 0.18
event_catalyst_close_strength_weight: float = 0.18
event_catalyst_trend_acceleration_weight: float = 0.12
event_catalyst_min_score_for_selected_uplift: float = 0.72
event_catalyst_min_score_for_near_miss_retain: float = 0.58
event_catalyst_selected_uplift: float = 0.03
event_catalyst_near_miss_threshold_relief: float = 0.02
event_catalyst_extension_penalty_max: float = 0.55
event_catalyst_stale_penalty_max: float = 0.50
event_catalyst_overhead_penalty_max: float = 0.50
```

```python
@dataclass(frozen=True)
class EventCatalystAssessment:
    score: float
    eligible: bool
    selected_uplift: float
    near_miss_threshold_relief: float
    gate_hits: dict[str, bool]
    component_scores: dict[str, float]


def build_event_catalyst_assessment(
    *,
    snapshot: dict[str, Any],
    profile: Any,
    candidate_source: str,
    candidate_reason_codes: set[str],
) -> EventCatalystAssessment:
    if not bool(getattr(profile, "event_catalyst_enabled", False)):
        return EventCatalystAssessment(0.0, False, 0.0, 0.0, {}, {})

    freshness = clamp_unit_interval(float(snapshot.get("catalyst_freshness", 0.0) or 0.0))
    resonance = clamp_unit_interval(float(snapshot.get("sector_resonance", 0.0) or 0.0))
    volume = clamp_unit_interval(float(snapshot.get("volume_expansion_quality", 0.0) or 0.0))
    close = clamp_unit_interval(float(snapshot.get("close_strength", 0.0) or 0.0))
    trend = clamp_unit_interval(float(snapshot.get("trend_acceleration", 0.0) or 0.0))
    extension_penalty = float(snapshot.get("extension_without_room_penalty", 0.0) or 0.0)
    stale_penalty = float(snapshot.get("stale_trend_repair_penalty", 0.0) or 0.0)
    overhead_penalty = float(snapshot.get("overhead_supply_penalty", 0.0) or 0.0)

    score = clamp_unit_interval(
        (float(profile.event_catalyst_catalyst_freshness_weight) * freshness)
        + (float(profile.event_catalyst_sector_resonance_weight) * resonance)
        + (float(profile.event_catalyst_volume_expansion_weight) * volume)
        + (float(profile.event_catalyst_close_strength_weight) * close)
        + (float(profile.event_catalyst_trend_acceleration_weight) * trend)
    )
    eligible = (
        candidate_source in set(profile.event_catalyst_candidate_sources)
        and extension_penalty <= float(profile.event_catalyst_extension_penalty_max)
        and stale_penalty <= float(profile.event_catalyst_stale_penalty_max)
        and overhead_penalty <= float(profile.event_catalyst_overhead_penalty_max)
    )
    return EventCatalystAssessment(
        score=score,
        eligible=eligible,
        selected_uplift=float(profile.event_catalyst_selected_uplift) if eligible and score >= float(profile.event_catalyst_min_score_for_selected_uplift) else 0.0,
        near_miss_threshold_relief=float(profile.event_catalyst_near_miss_threshold_relief) if eligible and score >= float(profile.event_catalyst_min_score_for_near_miss_retain) else 0.0,
        gate_hits={"eligible_source": candidate_source in set(profile.event_catalyst_candidate_sources)},
        component_scores={"freshness": freshness, "resonance": resonance, "volume": volume, "close": close, "trend": trend},
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/targets/test_short_trade_event_catalyst_helpers.py::test_build_event_catalyst_assessment_scores_fresh_supported_event -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/targets/profiles.py src/targets/short_trade_event_catalyst_helpers.py tests/targets/test_short_trade_event_catalyst_helpers.py
git commit -m "feat: add BTST event catalyst helper"
```

## Task 2: Wire the helper into short-trade decisions and explainability

**Files:**
- Modify: `src/targets/short_trade_target.py`
- Modify: `src/targets/short_trade_target_evaluation_helpers.py`
- Modify: `src/targets/models.py`
- Modify: `src/targets/short_trade_metrics_payload_builders.py`
- Test: `tests/targets/test_target_models.py`

- [ ] **Step 1: Write the failing integration test**

```python
def test_event_catalyst_boundary_relief_promotes_frontier_case_to_near_miss() -> None:
    baseline_result = evaluate_short_trade_rejected_target(
        trade_date="20260324",
        entry=_make_profitability_hard_cliff_boundary_frontier_entry(),
        profile_overrides={"event_catalyst_enabled": False},
    )
    relief_result = evaluate_short_trade_rejected_target(
        trade_date="20260324",
        entry=_make_profitability_hard_cliff_boundary_frontier_entry(),
        profile_name="event_catalyst_guarded",
    )

    assert baseline_result.decision in {"rejected", "near_miss", "selected"}
    assert relief_result.decision in {"near_miss", "selected"}
    assert relief_result.metrics_payload["event_catalyst"]["applied"] is True
    assert relief_result.metrics_payload["event_catalyst"]["gate_hits"]["eligible_source"] is True
    assert relief_result.explainability_payload["event_catalyst"]["score"] >= 0.72
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/targets/test_target_models.py::test_event_catalyst_boundary_relief_promotes_frontier_case_to_near_miss -q`

Expected: FAIL because short-trade results do not yet expose or apply the event-catalyst payload.

- [ ] **Step 3: Write the minimal scoring + payload integration**

```python
event_catalyst = build_event_catalyst_assessment(
    snapshot=snapshot,
    profile=profile,
    candidate_source=str(input_data.replay_context.get("source") or input_data.replay_context.get("candidate_source") or ""),
    candidate_reason_codes=set(_normalized_reason_codes(input_data.replay_context.get("candidate_reason_codes"))),
)
effective_select_threshold = max(0.0, effective_select_threshold - event_catalyst.selected_uplift)
effective_near_miss_threshold = max(0.0, effective_near_miss_threshold - event_catalyst.near_miss_threshold_relief)

result.event_catalyst_score = event_catalyst.score
result.metrics_payload["event_catalyst"] = _build_event_catalyst_metrics_payload(event_catalyst)
result.explainability_payload["event_catalyst"] = {
    "score": round(event_catalyst.score, 4),
    "eligible": event_catalyst.eligible,
    "applied": event_catalyst.selected_uplift > 0 or event_catalyst.near_miss_threshold_relief > 0,
    "gate_hits": dict(event_catalyst.gate_hits),
    "component_scores": dict(event_catalyst.component_scores),
}
```

```python
def _build_event_catalyst_metrics_payload(event_catalyst: EventCatalystAssessment) -> dict[str, Any]:
    return {
        "score": round(event_catalyst.score, 4),
        "applied": event_catalyst.selected_uplift > 0 or event_catalyst.near_miss_threshold_relief > 0,
        "selected_uplift": round(event_catalyst.selected_uplift, 4),
        "near_miss_threshold_relief": round(event_catalyst.near_miss_threshold_relief, 4),
        "gate_hits": dict(event_catalyst.gate_hits),
        "component_scores": dict(event_catalyst.component_scores),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/targets/test_target_models.py::test_event_catalyst_boundary_relief_promotes_frontier_case_to_near_miss -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/targets/models.py src/targets/short_trade_target.py src/targets/short_trade_target_evaluation_helpers.py src/targets/short_trade_metrics_payload_builders.py tests/targets/test_target_models.py
git commit -m "feat: wire BTST event catalyst scoring into short trade decisions"
```

## Task 3: Add a guarded replay profile and frontier diagnostics

**Files:**
- Modify: `src/targets/short_trade_target_profile_data.py`
- Modify: `scripts/analyze_btst_profile_frontier.py`
- Test: `tests/test_analyze_btst_profile_frontier_script.py`

- [ ] **Step 1: Write the failing frontier test**

```python
def test_analyze_btst_profile_frontier_supports_event_catalyst_guarded(tmp_path, monkeypatch):
    replay_input_path = _write_profile_replay_input(tmp_path)
    monkeypatch.setattr("scripts.btst_analysis_utils.get_price_data", fake_get_price_data)

    analysis = analyze_btst_profile_frontier(
        replay_input_path,
        baseline_profile="default",
        variant_profiles=["event_catalyst_guarded"],
        next_high_hit_threshold=0.02,
    )

    assert analysis["variants"][0]["profile_name"] == "event_catalyst_guarded"
    top_row = analysis["variants"][0]["top_tradeable_rows"][0]
    assert "event_catalyst" in top_row["explainability_payload"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_analyze_btst_profile_frontier_script.py::test_analyze_btst_profile_frontier_supports_event_catalyst_guarded -q`

Expected: FAIL because the guarded profile does not exist yet and the replay output does not assert the new payload.

- [ ] **Step 3: Write the minimal guarded profile and diagnostics**

```python
"event_catalyst_guarded": replace(
    SHORT_TRADE_TARGET_PROFILES["default"],
    name="event_catalyst_guarded",
    event_catalyst_enabled=True,
    event_catalyst_candidate_sources=frozenset({"catalyst_theme", "short_trade_boundary"}),
    event_catalyst_min_score_for_selected_uplift=0.72,
    event_catalyst_min_score_for_near_miss_retain=0.58,
    event_catalyst_selected_uplift=0.03,
    event_catalyst_near_miss_threshold_relief=0.02,
)
```

```python
lines.append(f"- top_tradeable_event_catalyst: {[row.get('explainability_payload', {}).get('event_catalyst') for row in variant['top_tradeable_rows'][:3]]}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_analyze_btst_profile_frontier_script.py::test_analyze_btst_profile_frontier_supports_event_catalyst_guarded -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/targets/short_trade_target_profile_data.py scripts/analyze_btst_profile_frontier.py tests/test_analyze_btst_profile_frontier_script.py
git commit -m "feat: add guarded BTST event catalyst replay profile"
```

## Task 4: Add event-catalyst replay search support and validation workflow

**Files:**
- Modify: `scripts/optimize_profile.py`
- Modify: `tests/test_optimize_profile_script.py`

- [ ] **Step 1: Write the failing optimizer preset test**

```python
def test_build_grid_params_uses_event_catalyst_preset_for_guarded_profile() -> None:
    grid = optimize_profile.resolve_grid_params(
        grid_params=[],
        preset_grid=True,
        profile_name="event_catalyst_guarded",
    )

    assert grid["event_catalyst_selected_uplift"] == [0.02, 0.03]
    assert grid["event_catalyst_min_score_for_selected_uplift"] == [0.68, 0.72]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_optimize_profile_script.py::test_build_grid_params_uses_event_catalyst_preset_for_guarded_profile -q`

Expected: FAIL because no event-catalyst preset grid exists yet.

- [ ] **Step 3: Write the minimal preset support**

```python
EVENT_CATALYST_GRID: dict[str, list[Any]] = {
    "event_catalyst_selected_uplift": [0.02, 0.03],
    "event_catalyst_near_miss_threshold_relief": [0.01, 0.02],
    "event_catalyst_min_score_for_selected_uplift": [0.68, 0.72],
    "event_catalyst_min_score_for_near_miss_retain": [0.54, 0.58],
    "event_catalyst_sector_resonance_weight": [0.18, 0.22],
}
```

```python
def resolve_grid_params(*, grid_params: list[str], preset_grid: bool, profile_name: str) -> dict[str, list[Any]]:
    resolved = parse_grid_params(grid_params)
    if preset_grid and profile_name == "event_catalyst_guarded":
        return {**PRESET_GRID, **EVENT_CATALYST_GRID, **resolved}
    if preset_grid:
        return {**PRESET_GRID, **resolved}
    return resolved
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_optimize_profile_script.py::test_build_grid_params_uses_event_catalyst_preset_for_guarded_profile -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/optimize_profile.py tests/test_optimize_profile_script.py
git commit -m "feat: add BTST event catalyst search preset"
```

## Task 5: Run phase-1 validation without changing shipped defaults

**Files:**
- Use: `scripts/analyze_btst_weekly_validation.py`
- Use: `scripts/optimize_profile.py`
- Use: `scripts/analyze_btst_multi_window_profile_validation.py`
- Review: `data/reports/btst_weekly_validation_latest.json`
- Review: `data/reports/param_search_report.json`

- [ ] **Step 1: Refresh the complete weekly validation window**

Run:

```bash
uv run python scripts/analyze_btst_weekly_validation.py \
  --reports-root data/reports \
  --start-date 2026-04-22 \
  --end-date 2026-04-24
```

Expected: `missing_trade_dates: []`

- [ ] **Step 2: Run event-catalyst replay search**

Run:

```bash
uv run python scripts/optimize_profile.py \
  --profile event_catalyst_guarded \
  --objective btst \
  --preset-grid \
  --reports-root data/reports \
  --weekly-start-date 2026-04-22 \
  --weekly-end-date 2026-04-24
```

Expected: new `data/reports/param_search_report.md` and `.json` artifacts with ranked event-catalyst settings.

- [ ] **Step 3: Compare the winning variant against baseline**

Run:

```bash
uv run python scripts/analyze_btst_multi_window_profile_validation.py \
  --reports-root data/reports \
  --baseline-profile default \
  --variant-profile event_catalyst_guarded \
  --variant-profile-overrides '{"event_catalyst_selected_uplift": 0.03, "event_catalyst_min_score_for_selected_uplift": 0.72}'
```

Expected: keep the guarded profile as a research variant unless T+1 win rate improves and payoff ratio does not materially worsen.

- [ ] **Step 4: Run the focused regression pack**

Run:

```bash
uv run pytest \
  tests/targets/test_short_trade_event_catalyst_helpers.py \
  tests/targets/test_target_models.py \
  tests/test_analyze_btst_profile_frontier_script.py \
  tests/test_optimize_profile_script.py \
  tests/test_analyze_btst_weekly_validation_script.py -q
```

Expected: PASS

- [ ] **Step 5: Do not update shipped default profiles unless the artifact evidence passes**

```python
winner = {
    "profile_name": "event_catalyst_guarded",
    "action": "keep_as_research_variant_until_multi_window_guardrails_pass",
}
```

## Spec Coverage Check

- Event-catalyst proxy score: covered by Tasks 1 and 2.
- Bounded uplift / retention only: covered by Task 2.
- Explainability and diagnostics: covered by Task 3.
- Replay search and rollout gate: covered by Tasks 4 and 5.
- No direct shipped-default change before evidence: covered by Task 5.

## Notes

- Keep the new logic isolated in `src/targets/short_trade_event_catalyst_helpers.py`; do not spread the score construction across multiple unrelated helpers.
- Use current stable data only; phase 2 external news integration is intentionally out of scope.
- Prefer the guarded research profile route over editing `default` or `momentum_optimized` during the first pass.
