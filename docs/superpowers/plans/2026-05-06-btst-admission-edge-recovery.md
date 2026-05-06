# BTST Admission Edge Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover a small positive-edge formal BTST surface on normal/strong days while keeping weak-regime protection and tightening hold posture around real close-retention evidence.

**Architecture:** Add a bounded regime-aware admission layer, make historical-prior shrinkage adaptive by sample quality and regime, then recalibrate preferred entry mode so hold-friendly execution only survives when calibrated close-retention evidence supports it. All changes stay profile-based, replay-testable, and visible in explainability/reporting payloads.

**Tech Stack:** Python 3.12, existing BTST target-evaluation helpers under `src/targets/`, market-state helpers under `src/screening/`, BTST reporting helpers under `src/paper_trading/`, pytest

---

## File Structure

- Modify: `src/targets/profiles.py` — add bounded profile knobs for regime-aware admission recovery and adaptive prior shrinkage posture.
- Modify: `src/targets/short_trade_target_profile_data.py` — define a guarded comparison profile for this recovery cycle.
- Modify: `src/screening/market_state_helpers.py` — keep regime classification stable and expose the fields needed by admission logic.
- Modify: `src/execution/daily_pipeline.py` — attach the already computed BTST regime gate payload so downstream target evaluation does not re-derive it.
- Modify: `src/targets/short_trade_target_rank_helpers.py` — make rank-threshold tightening and rank-cap relief aware of the regime gate.
- Modify: `src/targets/short_trade_target_prior_helpers.py` — implement adaptive shrinkage strength and expose the selected policy in calibrated prior output.
- Modify: `src/targets/short_trade_target.py` — thread regime payload and calibrated prior through target evaluation.
- Modify: `src/targets/short_trade_target_evaluation_helpers.py` — recalibrate preferred entry mode from adaptive close-retention evidence.
- Modify: `src/paper_trading/_btst_reporting/entry_mode_utils.py` — surface the stricter execution contract wording.
- Modify: `scripts/analyze_btst_selected_outcome_proof.py` — report the new posture recommendation in validation artifacts.
- Test: `tests/execution/test_phase4_execution.py`
- Test: `tests/test_btst_prior_shrinkage.py`
- Test: `tests/targets/test_target_models.py`
- Test: `tests/test_analyze_btst_selected_outcome_proof_script.py`

### Task 1: Regime-aware admission recovery

**Files:**
- Modify: `src/targets/profiles.py`
- Modify: `src/targets/short_trade_target_profile_data.py`
- Modify: `src/screening/market_state_helpers.py`
- Modify: `src/execution/daily_pipeline.py`
- Modify: `src/targets/short_trade_target_rank_helpers.py`
- Modify: `tests/execution/test_phase4_execution.py`
- Modify: `tests/targets/test_target_models.py`

- [ ] **Step 1: Write the failing tests for regime-aware relief**

```python
def test_normal_trade_regime_can_relax_rank_tightening_without_touching_weak_regime() -> None:
    profile = build_short_trade_target_profile(
        "default",
        overrides={
            "regime_admission_recovery_enabled": True,
            "regime_admission_recovery_selected_rank_tightening_lift_relief": 0.02,
            "regime_admission_recovery_allowed_gates": ["normal_trade", "aggressive_trade"],
        },
    )

    normal_snapshot = _apply_rank_based_threshold_tightening(
        {
            "effective_select_threshold": 0.40,
            "effective_near_miss_threshold": 0.34,
            "profile": profile,
            "btst_regime_gate": "normal_trade",
        },
        rank_hint=18,
    )
    weak_snapshot = _apply_rank_based_threshold_tightening(
        {
            "effective_select_threshold": 0.40,
            "effective_near_miss_threshold": 0.34,
            "profile": profile,
            "btst_regime_gate": "shadow_only",
        },
        rank_hint=18,
    )

    assert normal_snapshot["effective_select_threshold"] < weak_snapshot["effective_select_threshold"]
    assert weak_snapshot["rank_threshold_tightening"]["effective_select_threshold"] == pytest.approx(0.41)
```

```python
def test_build_btst_regime_gate_payload_is_reused_by_target_context(monkeypatch: pytest.MonkeyPatch) -> None:
    market_state = {
        "breadth_ratio": 0.68,
        "daily_return": 0.003,
        "style_dispersion": 0.18,
        "regime_flip_risk": 0.10,
        "regime_gate_level": "normal",
    }

    payload = _build_btst_regime_gate_payload(market_state)

    assert payload["gate"] == "normal_trade"
    assert payload["metrics"]["breadth_ratio"] == pytest.approx(0.68)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/execution/test_phase4_execution.py tests/targets/test_target_models.py -k 'regime_can_relax_rank_tightening or regime_gate_payload_is_reused' -q`

Expected: FAIL because the profile fields and regime-aware tightening logic do not exist yet.

- [ ] **Step 3: Add minimal regime-aware admission knobs**

```python
@dataclass(frozen=True)
class ShortTradeTargetProfile:
    ...
    regime_admission_recovery_enabled: bool = False
    regime_admission_recovery_allowed_gates: tuple[str, ...] = ("normal_trade", "aggressive_trade")
    regime_admission_recovery_selected_rank_tightening_lift_relief: float = 0.0
    regime_admission_recovery_near_miss_tightening_lift_relief: float = 0.0
```

```python
SHORT_TRADE_TARGET_PROFILES["btst_admission_edge_recovery"] = replace(
    SHORT_TRADE_TARGET_PROFILES["default"],
    name="btst_admission_edge_recovery",
    regime_admission_recovery_enabled=True,
    regime_admission_recovery_selected_rank_tightening_lift_relief=0.02,
    regime_admission_recovery_near_miss_tightening_lift_relief=0.01,
)
```

- [ ] **Step 4: Apply the minimal regime-aware tightening logic**

```python
def _apply_rank_based_threshold_tightening(snapshot: dict[str, Any], *, rank_hint: int | None) -> dict[str, Any]:
    adjusted = dict(snapshot)
    tightening = _resolve_rank_threshold_tightening(rank_hint)
    ...
    profile = adjusted.get("profile")
    regime_gate = str(adjusted.get("btst_regime_gate") or "").strip()
    if (
        getattr(profile, "regime_admission_recovery_enabled", False)
        and regime_gate in tuple(getattr(profile, "regime_admission_recovery_allowed_gates", ()))
    ):
        select_lift = max(0.0, select_lift - float(getattr(profile, "regime_admission_recovery_selected_rank_tightening_lift_relief", 0.0) or 0.0))
        near_miss_lift = max(0.0, near_miss_lift - float(getattr(profile, "regime_admission_recovery_near_miss_tightening_lift_relief", 0.0) or 0.0))
```

```python
def _historical_prior(input_data: TargetEvaluationInput) -> dict[str, Any]:
    historical_prior = dict(input_data.replay_context.get("historical_prior") or {})
    ...
    explicit_btst_regime_gate = str(
        input_data.replay_context.get("btst_regime_gate")
        or historical_prior.get("btst_regime_gate")
        or ""
    ).strip()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/execution/test_phase4_execution.py tests/targets/test_target_models.py -k 'regime_can_relax_rank_tightening or regime_gate_payload_is_reused' -q`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/targets/profiles.py src/targets/short_trade_target_profile_data.py src/screening/market_state_helpers.py src/execution/daily_pipeline.py src/targets/short_trade_target_rank_helpers.py tests/execution/test_phase4_execution.py tests/targets/test_target_models.py
git commit -m "feat: add regime-aware BTST admission recovery"
```

### Task 2: Adaptive prior shrinkage for strong low-sample names

**Files:**
- Modify: `src/targets/profiles.py`
- Modify: `src/targets/short_trade_target_prior_helpers.py`
- Modify: `src/targets/short_trade_target.py`
- Modify: `tests/test_btst_prior_shrinkage.py`
- Modify: `tests/targets/test_target_models.py`

- [ ] **Step 1: Write the failing adaptive-shrinkage tests**

```python
def test_adaptive_shrinkage_is_lighter_for_close_continuation_in_normal_trade() -> None:
    prior = calibrate_short_trade_historical_prior(
        {
            "execution_quality_label": "close_continuation",
            "entry_timing_bias": "confirm_then_hold",
            "btst_regime_gate": "normal_trade",
            "evaluable_count": 3,
            "same_ticker_sample_count": 3,
            "next_high_hit_rate_at_threshold": 1.0,
            "next_close_positive_rate": 1.0,
            "next_open_to_close_return_mean": 0.03,
            "adaptive_prior_shrinkage_enabled": True,
        }
    )

    assert prior["adaptive_prior_shrinkage_applied"] is True
    assert prior["effective_prior_shrinkage_strength"] < 8.0
    assert prior["shrunk_close_positive_rate"] > 0.70
```

```python
def test_adaptive_shrinkage_stays_strict_for_weak_regime_intraday_only() -> None:
    prior = calibrate_short_trade_historical_prior(
        {
            "execution_quality_label": "intraday_only",
            "entry_timing_bias": "confirm_then_reduce",
            "btst_regime_gate": "shadow_only",
            "evaluable_count": 3,
            "same_ticker_sample_count": 3,
            "next_high_hit_rate_at_threshold": 1.0,
            "next_close_positive_rate": 1.0,
            "adaptive_prior_shrinkage_enabled": True,
        }
    )

    assert prior["effective_prior_shrinkage_strength"] >= 8.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_btst_prior_shrinkage.py -k 'adaptive_shrinkage' -q`

Expected: FAIL because adaptive shrinkage fields and policy are not implemented.

- [ ] **Step 3: Add the adaptive shrinkage policy fields**

```python
@dataclass(frozen=True)
class ShortTradeTargetProfile:
    ...
    adaptive_prior_shrinkage_enabled: bool = False
    adaptive_prior_shrinkage_low_sample_max_evaluable_count: int = 4
    adaptive_prior_shrinkage_strong_close_continuation_strength: float = 5.0
    adaptive_prior_shrinkage_default_strength: float = 8.0
```

```python
def _resolve_effective_prior_strength(prior: dict[str, Any]) -> float:
    evidence_count = max(_safe_int(prior.get("evaluable_count"), 0), _safe_int(prior.get("same_ticker_sample_count"), 0))
    execution_quality_label = str(prior.get("execution_quality_label") or "")
    btst_regime_gate = str(prior.get("btst_regime_gate") or "")
    adaptive_enabled = _safe_bool(prior.get("adaptive_prior_shrinkage_enabled"), False)
    if adaptive_enabled and evidence_count <= 4 and execution_quality_label == "close_continuation" and btst_regime_gate in {"normal_trade", "aggressive_trade"}:
        return _safe_float(prior.get("adaptive_prior_shrinkage_strong_close_continuation_strength"), 5.0)
    return _safe_float(prior.get("prior_shrinkage_strength"), DEFAULT_PRIOR_STRENGTH)
```

- [ ] **Step 4: Use the effective strength in calibration output**

```python
prior_strength = _resolve_effective_prior_strength(prior)
...
prior["adaptive_prior_shrinkage_applied"] = prior_strength != DEFAULT_P4_PRIOR_SHRINKAGE_K
prior["effective_prior_shrinkage_strength"] = prior_strength
```

```python
historical_prior.setdefault("adaptive_prior_shrinkage_enabled", bool(getattr(profile, "adaptive_prior_shrinkage_enabled", False)))
historical_prior.setdefault(
    "adaptive_prior_shrinkage_strong_close_continuation_strength",
    float(getattr(profile, "adaptive_prior_shrinkage_strong_close_continuation_strength", 5.0) or 5.0),
)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_btst_prior_shrinkage.py -k 'adaptive_shrinkage' -q`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/targets/profiles.py src/targets/short_trade_target_prior_helpers.py src/targets/short_trade_target.py tests/test_btst_prior_shrinkage.py tests/targets/test_target_models.py
git commit -m "feat: add adaptive BTST prior shrinkage"
```

### Task 3: Recalibrate entry mode for payoff retention

**Files:**
- Modify: `src/targets/short_trade_target_evaluation_helpers.py`
- Modify: `src/paper_trading/_btst_reporting/entry_mode_utils.py`
- Modify: `scripts/analyze_btst_selected_outcome_proof.py`
- Modify: `tests/targets/test_target_models.py`
- Modify: `tests/test_analyze_btst_selected_outcome_proof_script.py`

- [ ] **Step 1: Write the failing payoff-posture tests**

```python
def test_close_continuation_with_weak_close_retention_downgrades_hold_posture() -> None:
    mode = _preferred_entry_mode_from_historical_prior(
        {
            "execution_quality_label": "close_continuation",
            "entry_timing_bias": "confirm_then_hold",
            "evaluable_count": 4,
            "calibrated_next_close_positive_rate": 0.46,
            "calibrated_next_high_hit_rate_at_threshold": 0.82,
            "calibrated_next_open_to_close_return_mean": 0.002,
            "prior_evidence_weight": 0.45,
        }
    )

    assert mode == "intraday_confirmation_only"
```

```python
def test_selected_outcome_proof_recommendation_flags_intraday_only_surface() -> None:
    recommendation = _build_recommendation(
        {
            "evidence_case_count": 2,
            "next_high_hit_rate_at_threshold": 1.0,
            "next_close_positive_rate": 0.0,
            "t_plus_2_close_positive_rate": 0.0,
        }
    )

    assert "intraday" in recommendation
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/targets/test_target_models.py tests/test_analyze_btst_selected_outcome_proof_script.py -k 'weak_close_retention_downgrades_hold_posture or intraday_only_surface' -q`

Expected: FAIL because close-retention posture downgrading is not implemented.

- [ ] **Step 3: Add the minimal posture downgrade logic**

```python
if execution_quality_label == "close_continuation":
    weak_close_retention = (
        has_calibrated_prior
        and calibrated_next_high_hit_rate >= 0.75
        and calibrated_next_close_positive_rate < 0.52
    )
    if weak_close_retention:
        return "intraday_confirmation_only"
```

```python
def _selected_holding_contract_note(preferred_entry_mode: str | None, historical_prior: dict[str, Any] | None) -> str | None:
    ...
    if preferred_entry_mode == "intraday_confirmation_only":
        return "历史证据更偏向盘中兑现，默认不把收盘持有当成基础执行合同。"
```

- [ ] **Step 4: Update selected-outcome proof recommendation wording**

```python
if summary["next_high_hit_rate_at_threshold"] >= 0.8 and summary["next_close_positive_rate"] < 0.4:
    return "当前 selected 路径更像 intraday-only 兑现，不应继续保留 confirm_then_hold 语义。"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/targets/test_target_models.py tests/test_analyze_btst_selected_outcome_proof_script.py -k 'weak_close_retention_downgrades_hold_posture or intraday_only_surface' -q`

Expected: PASS

- [ ] **Step 6: Run the focused regression bundle**

Run: `uv run pytest tests/test_btst_prior_shrinkage.py tests/targets/test_target_models.py tests/execution/test_phase4_execution.py tests/test_analyze_btst_selected_outcome_proof_script.py -q`

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/targets/short_trade_target_evaluation_helpers.py src/paper_trading/_btst_reporting/entry_mode_utils.py scripts/analyze_btst_selected_outcome_proof.py tests/targets/test_target_models.py tests/test_analyze_btst_selected_outcome_proof_script.py tests/test_btst_prior_shrinkage.py tests/execution/test_phase4_execution.py
git commit -m "feat: recalibrate BTST hold posture"
```
