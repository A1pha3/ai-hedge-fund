# BTST Watchlist Filter Diagnostics Selected-Only Shrink Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an offline `trend_continuation_strength_v3` candidate that shrinks unstable `watchlist_filter_diagnostics` names out of `selected` while preserving them as `near_miss`, then validate whether that improves T+1 quality.

**Architecture:** Reuse the existing BTST snapshot-threshold pipeline instead of adding a new execution path. Implement the new behavior as a source-specific select-threshold lift for `watchlist_filter_diagnostics`, expose it in explainability / metrics, and validate it first with focused target tests and then with 20-day + multi-window replay.

**Tech Stack:** Python 3.12, pytest, LangGraph BTST target stack, existing replay/validation scripts

---

## File Map

- **Modify:** `src/targets/profiles.py` — add profile knobs for the new selected-only shrink rule
- **Modify:** `src/targets/short_trade_target_profile_data.py` — register the offline derivative profile `trend_continuation_strength_v3`
- **Modify:** `src/targets/short_trade_target_watchlist_helpers.py` — add the source-specific selected-only shrink resolver
- **Modify:** `src/targets/short_trade_target_snapshot_relief_helpers.py` — apply the select-threshold lift without changing the near-miss threshold
- **Modify:** `src/targets/short_trade_target_evaluation_helpers.py` — expose the new guard in explainability / top reasons
- **Modify:** `src/targets/short_trade_target_snapshot_payload_helpers.py` — carry the new guard into the snapshot payload
- **Modify:** `src/targets/short_trade_metrics_payload_builders.py` — expose the new guard in metrics payloads
- **Test:** `tests/targets/test_target_models.py` — extend the existing watchlist diagnostics regression area

### Task 1: Add the failing watchlist selected-only shrink tests

**Files:**
- Modify: `tests/targets/test_target_models.py`
- Test: `tests/targets/test_target_models.py`

- [ ] **Step 1: Write the failing profile-contract test**

```python
def test_trend_continuation_strength_v3_enables_watchlist_selected_only_shrink() -> None:
    profile = build_short_trade_target_profile("trend_continuation_strength_v3")

    expected = {
        "watchlist_filter_diagnostics_selected_only_shrink_enabled": True,
        "watchlist_filter_diagnostics_selected_only_shrink_select_threshold_lift": 0.05,
        "watchlist_filter_diagnostics_selected_only_shrink_catalyst_freshness_max": 0.10,
        "watchlist_filter_diagnostics_selected_only_shrink_trend_acceleration_max": 0.40,
        "watchlist_filter_diagnostics_selected_only_shrink_close_strength_max": 0.58,
    }

    actual = {name: getattr(profile, name) for name in expected}
    assert actual == expected
```

- [ ] **Step 2: Write the failing selected→near_miss behavior test**

```python
def test_watchlist_filter_diagnostics_selected_only_shrink_blocks_selected_but_preserves_near_miss() -> None:
    entry = {
        "ticker": "000960",
        "candidate_source": "watchlist_filter_diagnostics",
        "candidate_reason_codes": ["watchlist_filter_diagnostics"],
        "score_b": 0.22,
        "score_c": 0.08,
        "score_final": 0.12,
        "quality_score": 0.58,
        "decision": "watch",
        "reason": "watchlist_filter_diagnostics",
        "strategy_signals": {
            "trend": _make_strategy_signal(
                direction=1,
                confidence=38.0,
                sub_factors={
                    "momentum": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "adx_strength": {"direction": 0, "confidence": 24.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 46.0, "completeness": 1.0},
                },
            ),
            "event_sentiment": _make_strategy_signal(direction=0, confidence=6.0).model_dump(mode="json"),
            "mean_reversion": _make_strategy_signal(direction=0, confidence=18.0).model_dump(mode="json"),
            "fundamental": _make_strategy_signal(direction=1, confidence=70.0).model_dump(mode="json"),
        },
    }

    baseline = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
        profile_name="trend_continuation_strength_v2",
    )
    shrink = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=entry,
        profile_name="trend_continuation_strength_v3",
    )

    assert baseline.decision == "selected"
    assert shrink.decision == "near_miss"
    assert shrink.metrics_payload["thresholds"]["effective_select_threshold"] > baseline.metrics_payload["thresholds"]["effective_select_threshold"]
    assert shrink.metrics_payload["thresholds"]["near_miss_threshold"] == pytest.approx(
        baseline.metrics_payload["thresholds"]["near_miss_threshold"]
    )
```

- [ ] **Step 3: Write the failing explainability / payload test**

```python
def test_watchlist_selected_only_shrink_guard_is_exposed_in_metrics_payload() -> None:
    result = evaluate_short_trade_rejected_target(
        trade_date="20260328",
        entry=_make_watchlist_filter_diagnostics_selected_only_entry(),
        profile_name="trend_continuation_strength_v3",
    )

    guard = result.metrics_payload["watchlist_filter_diagnostics_selected_only_shrink_guard"]
    assert guard["applied"] is True
    assert guard["select_threshold_lift"] == pytest.approx(0.05)
    assert "watchlist_filter_diagnostics_selected_only_shrink_applied" in result.negative_tags
```

- [ ] **Step 4: Run the new tests to verify they fail**

Run:

```bash
uv run pytest tests/targets/test_target_models.py -k 'selected_only_shrink or watchlist_filter_diagnostics_selected_only' -q
```

Expected: FAIL because `trend_continuation_strength_v3` and the new selected-only shrink payload do not exist yet.

- [ ] **Step 5: Commit the red test scaffold**

```bash
git add tests/targets/test_target_models.py
git commit -m "test: add watchlist selected-only shrink regressions"
```

### Task 2: Add the profile knobs and offline candidate profile

**Files:**
- Modify: `src/targets/profiles.py`
- Modify: `src/targets/short_trade_target_profile_data.py`
- Test: `tests/targets/test_target_models.py`

- [ ] **Step 1: Add the new profile fields**

```python
watchlist_filter_diagnostics_selected_only_shrink_enabled: bool = False
watchlist_filter_diagnostics_selected_only_shrink_select_threshold_lift: float = 0.0
watchlist_filter_diagnostics_selected_only_shrink_catalyst_freshness_max: float = 0.0
watchlist_filter_diagnostics_selected_only_shrink_trend_acceleration_max: float = 1.0
watchlist_filter_diagnostics_selected_only_shrink_close_strength_max: float = 1.0
```

- [ ] **Step 2: Register the offline derivative profile**

```python
SHORT_TRADE_TARGET_PROFILES["trend_continuation_strength_v3"] = replace(
    SHORT_TRADE_TARGET_PROFILES["trend_continuation_strength_v2"],
    name="trend_continuation_strength_v3",
    watchlist_filter_diagnostics_selected_only_shrink_enabled=True,
    watchlist_filter_diagnostics_selected_only_shrink_select_threshold_lift=0.05,
    watchlist_filter_diagnostics_selected_only_shrink_catalyst_freshness_max=0.10,
    watchlist_filter_diagnostics_selected_only_shrink_trend_acceleration_max=0.40,
    watchlist_filter_diagnostics_selected_only_shrink_close_strength_max=0.58,
)
```

- [ ] **Step 3: Run the profile-contract test**

Run:

```bash
uv run pytest tests/targets/test_target_models.py::test_trend_continuation_strength_v3_enables_watchlist_selected_only_shrink -q
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/targets/profiles.py src/targets/short_trade_target_profile_data.py tests/targets/test_target_models.py
git commit -m "feat: add btst watchlist selected-only shrink profile"
```

### Task 3: Implement the selected-only threshold lift

**Files:**
- Modify: `src/targets/short_trade_target_watchlist_helpers.py`
- Modify: `src/targets/short_trade_target_snapshot_relief_helpers.py`
- Modify: `src/targets/short_trade_target_evaluation_helpers.py`
- Modify: `src/targets/short_trade_target_snapshot_payload_helpers.py`
- Modify: `src/targets/short_trade_metrics_payload_builders.py`
- Test: `tests/targets/test_target_models.py`

- [ ] **Step 1: Add the resolver in the watchlist helper module**

```python
def resolve_watchlist_filter_diagnostics_selected_only_shrink_impl(
    *,
    input_data: TargetEvaluationInput,
    catalyst_freshness: float,
    close_strength: float,
    trend_acceleration: float,
    profile: Any,
    clamp_unit_interval_fn: Callable[[float], float],
) -> dict[str, Any]:
    source = str(input_data.replay_context.get("source") or "").strip()
    enabled = bool(profile.watchlist_filter_diagnostics_selected_only_shrink_enabled)
    select_threshold_lift = clamp_unit_interval_fn(float(profile.watchlist_filter_diagnostics_selected_only_shrink_select_threshold_lift or 0.0))
    gate_hits = {
        "candidate_source": source == "watchlist_filter_diagnostics",
        "catalyst_freshness": catalyst_freshness <= clamp_unit_interval_fn(float(profile.watchlist_filter_diagnostics_selected_only_shrink_catalyst_freshness_max or 0.0)),
        "trend_acceleration": trend_acceleration <= clamp_unit_interval_fn(float(profile.watchlist_filter_diagnostics_selected_only_shrink_trend_acceleration_max or 1.0)),
        "close_strength": close_strength <= clamp_unit_interval_fn(float(profile.watchlist_filter_diagnostics_selected_only_shrink_close_strength_max or 1.0)),
    }
    applied = enabled and all(gate_hits.values()) and select_threshold_lift > 0.0
    return {
        "enabled": enabled,
        "eligible": enabled and gate_hits["candidate_source"],
        "applied": applied,
        "candidate_source": source,
        "gate_hits": gate_hits,
        "select_threshold_lift": select_threshold_lift if applied else 0.0,
    }
```

- [ ] **Step 2: Apply the lift only to the selected threshold**

```python
watchlist_filter_diagnostics_selected_only_shrink = resolve_watchlist_filter_diagnostics_selected_only_shrink(
    input_data=input_data,
    catalyst_freshness=state.raw_catalyst_freshness,
    close_strength=state.close_strength,
    trend_acceleration=threshold_state.trend_acceleration,
    profile=profile,
)

effective_select_threshold = min(
    0.95,
    float(selected_close_retention_adjustment["effective_select_threshold"])
    + float(watchlist_filter_diagnostics_selected_only_shrink["select_threshold_lift"]),
)
effective_near_miss_threshold = float(selected_close_retention_adjustment["effective_near_miss_threshold"])
```

- [ ] **Step 3: Expose the guard in payloads and reasons**

```python
"watchlist_filter_diagnostics_selected_only_shrink_guard": dict(
    snapshot["watchlist_filter_diagnostics_selected_only_shrink_guard"]
),
```

```python
"watchlist_filter_diagnostics_selected_only_shrink_applied"
if watchlist_filter_diagnostics_selected_only_shrink_guard["applied"]
else None
```

- [ ] **Step 4: Run the focused tests**

Run:

```bash
uv run pytest tests/targets/test_target_models.py -k 'selected_only_shrink or watchlist_filter_diagnostics_selected_only' -q
```

Expected: PASS

- [ ] **Step 5: Run the broader target regressions**

Run:

```bash
uv run pytest tests/targets/test_target_models.py tests/targets/test_trend_continuation_strength_v2.py -q
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/targets/short_trade_target_watchlist_helpers.py src/targets/short_trade_target_snapshot_relief_helpers.py src/targets/short_trade_target_evaluation_helpers.py src/targets/short_trade_target_snapshot_payload_helpers.py src/targets/short_trade_metrics_payload_builders.py tests/targets/test_target_models.py
git commit -m "feat: add watchlist selected-only shrink gate"
```

### Task 4: Validate the offline candidate

**Files:**
- Modify: `data/reports/btst_trend_continuation_strength_v3_20d.json`
- Modify: `data/reports/btst_trend_continuation_strength_v3_multi_window_validation.json`
- Modify: `data/reports/btst_trend_continuation_strength_v3_multi_window_validation.md`
- Modify: `data/reports/btst_strict_objective_gate.json`
- Modify: `data/reports/btst_strict_objective_gate.md`

- [ ] **Step 1: Run the 20-day validation**

Run:

```bash
uv run python scripts/btst_20day_backtest.py \
  --profiles btst_precision_v2,trend_continuation_strength_v3 \
  --output-json data/reports/btst_trend_continuation_strength_v3_20d.json
```

Expected: JSON artifact exists and shows whether `selected` count shrank while T+1 metrics improved.

- [ ] **Step 2: Run the multi-window replay validation**

Run:

```bash
PYTHONPATH="$(pwd)" uv run python scripts/analyze_btst_multi_window_profile_validation.py \
  --reports-root data/reports \
  --baseline-profile btst_precision_v2 \
  --variant-profile trend_continuation_strength_v3 \
  --output-json data/reports/btst_trend_continuation_strength_v3_multi_window_validation.json \
  --output-md data/reports/btst_trend_continuation_strength_v3_multi_window_validation.md
```

Expected: the changed windows previously dominated by `watchlist_filter_diagnostics` show reduced unstable selected exposure.

- [ ] **Step 3: Refresh the strict objective gate**

Run:

```bash
uv run python scripts/btst_strict_objective_gate.py \
  --input-md data/reports/btst_tplus1_tplus2_objective_monitor_latest.md \
  --output-json data/reports/btst_strict_objective_gate.json \
  --output-md data/reports/btst_strict_objective_gate.md
```

Expected: the final artifact remains authoritative for hold/promote.

- [ ] **Step 4: Run the focused regression slice before concluding**

Run:

```bash
uv run pytest tests/targets/test_target_models.py tests/targets/test_trend_continuation_strength_v2.py tests/test_btst_strict_objective_gate.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add data/reports/btst_trend_continuation_strength_v3_20d.json data/reports/btst_trend_continuation_strength_v3_multi_window_validation.json data/reports/btst_trend_continuation_strength_v3_multi_window_validation.md data/reports/btst_strict_objective_gate.json data/reports/btst_strict_objective_gate.md
git commit -m "chore: refresh btst watchlist shrink validation artifacts"
```

## Self-Review Notes

1. **Spec coverage:** the plan covers the new source-specific selected-only gate, explainability / metrics exposure, and the required 20-day + multi-window + strict-gate validation chain.
2. **No placeholders:** every task lists exact files, code, commands, and expected outputs.
3. **Type consistency:** the new runtime object is consistently named `watchlist_filter_diagnostics_selected_only_shrink_guard`, and the new candidate profile is consistently named `trend_continuation_strength_v3`.
