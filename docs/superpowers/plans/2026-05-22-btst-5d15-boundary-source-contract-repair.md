# BTST 5D15 Boundary Source Contract Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the boundary source contract so `trend_continuation` and `short_term_reversal` stop showing up as `missing_everywhere` in the live boundary trace.

**Architecture:** First expose the two keys in the short-trade snapshot payload, because that is the clean upstream contract already backed by the signal-snapshot layer. Then extend the boundary source metrics payload builder to carry those keys into `short_trade_boundary_metrics`, and finally verify the repair by re-running the existing boundary trace workflow and refreshing the live artifacts and Chinese note without changing fail-closed governance.

**Tech Stack:** Python 3.11+, pytest, `src/targets/*`, `src/execution/*`, boundary trace scripts under `scripts/`, JSON/Markdown artifacts under `data/reports/` and `docs/prompt/find_actor_methord/`

---

## File Structure

- Modify: `src/targets/short_trade_target_snapshot_payload_helpers.py`
  - add `trend_continuation` and `short_term_reversal` to the target snapshot payload
- Create: `tests/targets/test_short_trade_target_snapshot_payload_helpers.py`
  - focused contract tests for the snapshot payload surface
- Modify: `src/execution/daily_pipeline_candidate_helpers.py`
  - extend `build_short_trade_boundary_metrics_payload()` to carry the two keys from `snapshot` / `raw_candidate_metrics`
- Create: `tests/execution/test_daily_pipeline_candidate_helpers.py`
  - focused source-contract tests for the boundary metrics payload builder
- Modify: `tests/test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_script.py`
  - regression proof that the trace stops classifying the two keys as `missing_everywhere` once the source contract is repaired
- Refresh: `data/reports/btst_5d_15pct_boundary_missing_six_core_keys_latest.json`
- Refresh: `data/reports/btst_5d_15pct_boundary_missing_six_core_keys_latest.md`
- Create: `docs/prompt/find_actor_methord/btst-5d15-boundary-source-contract-repair-2026-05-22.md`
  - Chinese interpretation note for this repair cycle, still explicitly fail-closed

### Task 1: Expose the two keys in the short-trade snapshot payload

**Files:**
- Modify: `src/targets/short_trade_target_snapshot_payload_helpers.py`
- Create: `tests/targets/test_short_trade_target_snapshot_payload_helpers.py`

- [ ] **Step 1: Write the failing snapshot payload test**

```python
from src.targets.short_trade_target_snapshot_payload_helpers import build_short_trade_target_snapshot_payload


def test_build_short_trade_target_snapshot_payload_surfaces_continuation_and_reversal_keys() -> None:
    payload = build_short_trade_target_snapshot_payload(
        profile="demo-profile",
        signal_snapshot={
            "close_strength": 0.64,
            "sector_resonance": 0.33,
            "raw_catalyst_freshness": 0.27,
            "layer_c_alignment": 0.41,
            "long_trend_strength": 0.72,
            "event_freshness_strength": 0.55,
            "news_sentiment_strength": 0.44,
            "event_signal_strength": 0.58,
            "mean_reversion_strength": 0.12,
            "analyst_alignment": 0.35,
            "investor_alignment": 0.22,
            "analyst_penalty": 0.0,
            "investor_penalty": 0.0,
            "score_b_strength": 0.51,
            "score_c_strength": 0.42,
            "score_final_strength": 0.48,
            "momentum_strength": 0.78,
            "momentum_1m": 0.73,
            "momentum_3m": 0.67,
            "momentum_6m": 0.61,
            "volume_momentum": 0.59,
            "adx_strength": 0.71,
            "ema_strength": 0.69,
            "volatility_strength": 0.36,
            "volatility_metrics": {"volatility_regime": 0.22, "atr_ratio": 0.18},
            "trend_continuation": 0.88,
            "short_term_reversal": 0.12,
        },
        relief_snapshot={
            "breakout_freshness": 0.83,
            "trend_acceleration": 0.76,
            "volume_expansion_quality": 0.54,
            "catalyst_freshness": 0.31,
            "effective_near_miss_threshold": 0.55,
            "effective_select_threshold": 0.65,
            "selected_score_tolerance": 0.0,
            "market_state_threshold_adjustment": {},
            "selected_close_retention_adjustment": 0.0,
            "selected_close_retention_penalty": 0.0,
            "close_retention_score": 0.0,
            "breakout_close_gap": 0.0,
            "breakout_trap_guard": {},
            "layer_c_avoid_penalty": 0.0,
            "t_plus_2_continuation_candidate": {},
            "visibility_gap_continuation_relief": {},
            "merge_approved_continuation_relief": {},
            "historical_execution_relief": {},
            "historical_prior": {},
            "prepared_breakout_penalty_relief": {},
            "prepared_breakout_catalyst_relief": {},
            "prepared_breakout_volume_relief": {},
            "prepared_breakout_continuation_relief": {},
            "prepared_breakout_selected_catalyst_relief": {},
            "stale_trend_repair_penalty": 0.0,
            "overhead_supply_penalty": 0.0,
            "extension_without_room_penalty": 0.0,
            "event_catalyst_assessment": {},
            "positive_score_weights": {},
            "weighted_positive_contributions": {},
            "weighted_negative_contributions": {},
            "total_positive_contribution": 0.0,
            "total_negative_contribution": 0.0,
            "historical_continuation_prior_score": 0.0,
            "trend_continuation_strength_adjustment": 0.0,
            "score_target": 0.51,
            "profitability_relief": {
                "hard_cliff": False,
                "profitability_positive_count": 1,
                "profitability_confidence": 33.3333,
                "relief_enabled": False,
                "relief_gate_hits": {},
                "relief_eligible": False,
                "relief_applied": False,
                "soft_penalty": 0.0,
                "base_layer_c_avoid_penalty": 0.0,
            },
            "profitability_hard_cliff_boundary_relief": {},
            "upstream_shadow_catalyst_relief": {
                "enabled": False,
                "gate_hits": {},
                "eligible": False,
                "applied": False,
                "reason": "",
                "catalyst_freshness_floor": 0.0,
                "base_near_miss_threshold": 0.0,
                "near_miss_threshold_override": 0.0,
                "base_select_threshold": 0.0,
                "select_threshold_override": 0.0,
                "require_no_profitability_hard_cliff": False,
            },
            "catalyst_theme_penalty": {},
            "catalyst_theme_penalty_effective": 0.0,
            "watchlist_zero_catalyst_penalty": {},
            "watchlist_zero_catalyst_penalty_effective": 0.0,
            "watchlist_zero_catalyst_crowded_penalty": {},
            "watchlist_zero_catalyst_crowded_penalty_effective": 0.0,
            "watchlist_zero_catalyst_flat_trend_penalty": {},
            "watchlist_zero_catalyst_flat_trend_penalty_effective": 0.0,
            "watchlist_filter_diagnostics_flat_trend_penalty": {},
            "watchlist_filter_diagnostics_flat_trend_penalty_effective": 0.0,
            "watchlist_filter_diagnostics_selected_only_shrink_guard": {},
        },
        labels_and_gates={
            "positive_tags": [],
            "negative_tags": [],
            "blockers": [],
            "gate_status": {},
        },
    )

    assert payload["trend_continuation"] == 0.88
    assert payload["short_term_reversal"] == 0.12
```

- [ ] **Step 2: Run the snapshot payload test to verify it fails**

Run: `uv run pytest tests/targets/test_short_trade_target_snapshot_payload_helpers.py -q`

Expected: FAIL with missing `trend_continuation` / `short_term_reversal` keys in the payload.

- [ ] **Step 3: Add the two keys to the snapshot payload**

```python
payload["trend_continuation"] = signal_snapshot["trend_continuation"]
payload["short_term_reversal"] = signal_snapshot["short_term_reversal"]
```

- [ ] **Step 4: Run the snapshot payload test to verify it passes**

Run: `uv run pytest tests/targets/test_short_trade_target_snapshot_payload_helpers.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the snapshot payload contract change**

```bash
git add src/targets/short_trade_target_snapshot_payload_helpers.py tests/targets/test_short_trade_target_snapshot_payload_helpers.py
git commit -m "feat: expose continuation metrics in target snapshot payload"
```

### Task 2: Extend the boundary source metrics payload builder

**Files:**
- Modify: `src/execution/daily_pipeline_candidate_helpers.py`
- Create: `tests/execution/test_daily_pipeline_candidate_helpers.py`

- [ ] **Step 1: Write the failing boundary metrics payload tests**

```python
from src.execution.daily_pipeline_candidate_helpers import build_short_trade_boundary_metrics_payload


def test_build_short_trade_boundary_metrics_payload_includes_continuation_and_reversal_from_snapshot() -> None:
    metrics_payload = build_short_trade_boundary_metrics_payload(
        snapshot={
            "breakout_freshness": 0.83,
            "trend_acceleration": 0.76,
            "volume_expansion_quality": 0.54,
            "catalyst_freshness": 0.31,
            "close_strength": 0.64,
            "sector_resonance": 0.33,
            "trend_continuation": 0.88,
            "short_term_reversal": 0.12,
            "gate_status": {"data": "pass"},
            "blockers": [],
        },
        compute_candidate_score_fn=lambda snapshot: 0.51,
    )

    assert metrics_payload["trend_continuation"] == 0.88
    assert metrics_payload["short_term_reversal"] == 0.12


def test_build_short_trade_boundary_metrics_payload_keeps_raw_candidate_metric_fallbacks() -> None:
    metrics_payload = build_short_trade_boundary_metrics_payload(
        snapshot={
            "breakout_freshness": 0.83,
            "trend_acceleration": 0.76,
            "volume_expansion_quality": 0.54,
            "catalyst_freshness": 0.31,
            "close_strength": 0.64,
            "sector_resonance": 0.33,
            "gate_status": {"data": "pass"},
            "blockers": [],
        },
        compute_candidate_score_fn=lambda snapshot: 0.51,
        raw_candidate_metrics={
            "trend_continuation": 0.66,
            "short_term_reversal": 0.34,
        },
    )

    assert metrics_payload["trend_continuation"] == 0.66
    assert metrics_payload["short_term_reversal"] == 0.34
```

- [ ] **Step 2: Run the boundary metrics payload tests to verify they fail**

Run: `uv run pytest tests/execution/test_daily_pipeline_candidate_helpers.py -q`

Expected: FAIL because the builder does not emit the two keys yet.

- [ ] **Step 3: Extend the builder without introducing a second calculation path**

```python
payload = {
    "breakout_freshness": round(float(snapshot.get("breakout_freshness", 0.0) or 0.0), 4),
    "trend_acceleration": round(float(snapshot.get("trend_acceleration", 0.0) or 0.0), 4),
    "volume_expansion_quality": round(float(snapshot.get("volume_expansion_quality", 0.0) or 0.0), 4),
    "catalyst_freshness": round(float(snapshot.get("catalyst_freshness", 0.0) or 0.0), 4),
    "close_strength": round(float(snapshot.get("close_strength", 0.0) or 0.0), 4),
    "sector_resonance": round(float(snapshot.get("sector_resonance", 0.0) or 0.0), 4),
    "trend_continuation": round(float(snapshot.get("trend_continuation", 0.0) or 0.0), 4),
    "short_term_reversal": round(float(snapshot.get("short_term_reversal", 0.0) or 0.0), 4),
    "candidate_score": compute_candidate_score_fn(snapshot),
    "gate_status": gate_status,
    "blockers": blockers,
}
for key, value in dict(raw_candidate_metrics or {}).items():
    payload.setdefault(str(key), value)
```

- [ ] **Step 4: Run the boundary metrics payload tests to verify they pass**

Run: `uv run pytest tests/execution/test_daily_pipeline_candidate_helpers.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the boundary source contract repair**

```bash
git add src/execution/daily_pipeline_candidate_helpers.py tests/execution/test_daily_pipeline_candidate_helpers.py
git commit -m "feat: carry continuation metrics into boundary source payload"
```

### Task 3: Re-run the boundary trace verifier and refresh live artifacts

**Files:**
- Modify: `tests/test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_script.py`
- Refresh: `data/reports/btst_5d_15pct_boundary_missing_six_core_keys_latest.json`
- Refresh: `data/reports/btst_5d_15pct_boundary_missing_six_core_keys_latest.md`
- Create: `docs/prompt/find_actor_methord/btst-5d15-boundary-source-contract-repair-2026-05-22.md`

- [ ] **Step 1: Add the failing trace regression proving the two keys stop being `missing_everywhere`**

```python
def test_boundary_trace_stops_classifying_continuation_and_reversal_as_missing_everywhere_after_source_repair() -> None:
    script = _load_script_module()
    repaired_row = {
        "candidate_source": "short_trade_boundary",
        "ticker": "001309",
        "trade_date": "20260324",
        "source_payload": {
            "ticker": "001309",
            "candidate_source": "short_trade_boundary",
            "short_trade_boundary_metrics": {
                "breakout_freshness": 0.91,
                "trend_acceleration": 0.82,
                "volume_expansion_quality": 0.73,
                "close_strength": 0.64,
                "trend_continuation": 0.55,
                "short_term_reversal": 0.18,
            },
        },
        "attached_target": {
            "candidate_source": "short_trade_boundary",
            "short_trade": {
                "decision": "near_miss",
                "metrics_payload": {
                    "breakout_freshness": 0.91,
                    "trend_acceleration": 0.82,
                    "volume_expansion_quality": 0.73,
                    "close_strength": 0.64,
                    "trend_continuation": 0.55,
                    "short_term_reversal": 0.18,
                },
                "explainability_payload": {},
            },
        },
        "snapshot_target": {
            "candidate_source": "short_trade_boundary",
            "short_trade": {
                "decision": "near_miss",
                "metrics_payload": {
                    "breakout_freshness": 0.91,
                    "trend_acceleration": 0.82,
                    "volume_expansion_quality": 0.73,
                    "close_strength": 0.64,
                    "trend_continuation": 0.55,
                    "short_term_reversal": 0.18,
                },
                "explainability_payload": {},
            },
        },
    }

    analysis = script.analyze_btst_5d_15pct_boundary_missing_six_core_keys_from_rows([repaired_row])

    assert analysis["trace_status_board"][0]["missing_everywhere_missing_six_keys"] == []
```

- [ ] **Step 2: Run the trace regression to verify it fails**

Run: `uv run pytest tests/test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_script.py -q`

Expected: FAIL until the source contract repair from Tasks 1-2 is fully wired through the synthetic regression.

- [ ] **Step 3: Refresh the verifier artifacts and write the Chinese note**

Run:

```bash
uv run python scripts/analyze_btst_5d_15pct_boundary_missing_six_core_keys.py
```

Write:

```markdown
# btst-5d15-boundary-source-contract-repair-2026-05-22

## 本轮结论
- 本轮只验证 `trend_continuation` / `short_term_reversal` 的 source contract 修复是否生效。
- 目标不是 runtime 放行，也不是因子推广。

## 关键检查
- 这两个键是否已经从 `missing_everywhere` 下降到 0。
- 若仍然只是 nested-only，则记录为下一轮 surface 提升问题，而不是本轮失败外推。

## Alpha / Beta / Gamma 结论
- Alpha：仍不构成收益提升验证。
- Beta：source contract 修复若生效，下一轮再决定是否做 surface 提升。
- Gamma：继续 fail-closed，不进入 `docs/prompt/find_actor/`，不接入 `ai-hedge-fund-btst`。
```

- [ ] **Step 4: Run the focused regression bundle**

Run:

```bash
uv run pytest \
  tests/targets/test_short_trade_target_snapshot_payload_helpers.py \
  tests/execution/test_daily_pipeline_candidate_helpers.py \
  tests/test_btst_boundary_missing_core_key_trace_helpers.py \
  tests/test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_script.py \
  tests/test_analyze_btst_5d_15pct_boundary_contract_inspection_script.py \
  -q
```

Expected: PASS.

- [ ] **Step 5: Commit the repaired contract verification artifacts**

```bash
git add \
  tests/test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_script.py \
  data/reports/btst_5d_15pct_boundary_missing_six_core_keys_latest.json \
  data/reports/btst_5d_15pct_boundary_missing_six_core_keys_latest.md \
  docs/prompt/find_actor_methord/btst-5d15-boundary-source-contract-repair-2026-05-22.md
git commit -m "feat: verify boundary source contract repair"
```

## Self-Review Checklist

- Spec coverage: Task 1 covers the snapshot contract extension; Task 2 covers the boundary source payload repair; Task 3 covers the verifier regression, live artifacts, and the fail-closed Chinese note.
- Placeholder scan: No placeholder markers or cross-task shortcuts remain.
- Type consistency: The plan consistently uses `trend_continuation`, `short_term_reversal`, `build_short_trade_target_snapshot_payload()`, `build_short_trade_boundary_metrics_payload()`, and `analyze_btst_5d_15pct_boundary_missing_six_core_keys_from_rows()` across all tasks.
