# Layer A Market Context Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single Layer A market-context source so BTST recall diagnostics, control tower summaries, and tradeable-pool dossiers stop dropping `stock_basic`, liquidity, and frontier data at different hops.

**Architecture:** Introduce one shared builder for Layer A market-context payloads, then make `analyze_btst_candidate_pool_recall_dossier.py` consume that builder instead of piecing together partial data from replay inputs, tradeable-pool rows, and local snapshots. The first acceptance gate is the existing failing control-tower regression; once the builder is in place, the test should move from `missing_market_context` to stable frontier diagnostics.

**Tech Stack:** Python 3.12, BTST analysis scripts under `scripts/`, pytest script tests under `tests/`, local JSON fixtures in `tests/test_btst_control_tower_scripts.py`.

---

### Task 1: Freeze the failing control-tower regression around Layer A context loss

**Files:**
- Modify: `tests/test_btst_control_tower_scripts.py`
- Test: `tests/test_btst_control_tower_scripts.py::test_btst_nightly_control_tower_generates_one_click_bundle_and_reindexes_manifest`

- [ ] **Step 1: Add a focused regression assertion for the Layer A handoff**

Insert a dedicated assertion block near the existing failure:

```python
assert payload["control_tower_snapshot"]["candidate_pool_recall_stage_counts"] == {
    "candidate_pool_truncated_after_filters": 1
}
assert payload["control_tower_snapshot"]["candidate_pool_recall_dominant_ranking_driver"] == "mixed_post_filter_gap"
assert payload["control_tower_snapshot"]["candidate_pool_recall_dominant_liquidity_gap_mode"] == "near_cutoff_liquidity_gap"
```

- [ ] **Step 2: Run the regression test and watch it fail**

Run:

```bash
uv run pytest tests/test_btst_control_tower_scripts.py::test_btst_nightly_control_tower_generates_one_click_bundle_and_reindexes_manifest -q
```

Expected: FAIL with `missing_market_context` or `dominant_ranking_driver is None`, proving the Layer A context chain is still incomplete.


### Task 2: Build a shared Layer A context loader

**Files:**
- Create: `scripts/btst_layer_a_market_context_builder.py`
- Modify: `scripts/analyze_btst_candidate_pool_recall_dossier.py`
- Test: `tests/test_btst_control_tower_scripts.py`

- [ ] **Step 1: Write the failing builder test**

Add a small unit-style test in `tests/test_btst_control_tower_scripts.py`:

```python
def test_layer_a_market_context_builder_merges_stock_basic_and_local_prices(tmp_path: Path):
    reports_root = tmp_path / "repo" / "data" / "reports"
    snapshots_root = tmp_path / "repo" / "data" / "snapshots"
    reports_root.mkdir(parents=True)
    (snapshots_root / "300502" / "20260326").mkdir(parents=True)
    (snapshots_root / "300502" / "20260326" / "prices.json").write_text(
        json.dumps(
            [
                {"time": "2026-03-25", "close": 9.9, "volume": 98000.0},
                {"time": "2026-03-24", "close": 9.8, "volume": 95000.0},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rows = [{"ticker": "300502", "trade_date": "2026-03-25", "report_dir": "demo", "ts_code": "300502.SZ", "name": "测试300502", "market": "SZ", "list_date": "20200101"}]
    context = build_layer_a_market_context(rows=rows, reports_root=reports_root, snapshots_root=snapshots_root)
    assert context["stock_basic_by_symbol"]["300502"]["ts_code"] == "300502.SZ"
    assert context["local_avg_amount_20d"]["300502"] > 5000
```

- [ ] **Step 2: Run the builder test to verify it fails**

Run:

```bash
uv run pytest tests/test_btst_control_tower_scripts.py -k layer_a_market_context_builder_merges_stock_basic_and_local_prices -q
```

Expected: FAIL because `build_layer_a_market_context` does not exist yet.

- [ ] **Step 3: Implement the minimal shared builder**

Create `scripts/btst_layer_a_market_context_builder.py` with a focused API:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any


def build_layer_a_market_context(
    *,
    rows: list[dict[str, Any]],
    reports_root: Path,
    snapshots_root: Path,
) -> dict[str, Any]:
    return {
        "stock_basic_by_symbol": ...,
        "stock_basic_universe": ...,
        "local_avg_amount_20d": ...,
        "replay_input_rows_by_key": ...,
    }
```

Move the replay-input backfill, stock-basic fallback, and local-price lookup logic into this builder. Then update `analyze_btst_candidate_pool_recall_dossier.py` so `_build_priority_ticker_dossiers(...)` consumes the builder result instead of assembling these fragments inline.

- [ ] **Step 4: Run the builder and regression tests**

Run:

```bash
uv run pytest tests/test_btst_control_tower_scripts.py -k "layer_a_market_context_builder_merges_stock_basic_and_local_prices or test_btst_nightly_control_tower_generates_one_click_bundle_and_reindexes_manifest" -q
```

Expected: the builder test passes, and the control-tower regression moves past `missing_market_context`.


### Task 3: Restore frontier diagnostics for the truncated-after-filters path

**Files:**
- Modify: `scripts/analyze_btst_candidate_pool_recall_dossier.py`
- Modify: `tests/test_btst_control_tower_scripts.py`
- Test: `tests/test_btst_control_tower_scripts.py::test_btst_nightly_control_tower_generates_one_click_bundle_and_reindexes_manifest`

- [ ] **Step 1: Add the failing frontier-diagnostics assertion**

Keep these checks active in the regression:

```python
assert payload["control_tower_snapshot"]["candidate_pool_recall_dominant_ranking_driver"] == "mixed_post_filter_gap"
assert payload["control_tower_snapshot"]["candidate_pool_recall_dominant_liquidity_gap_mode"] == "near_cutoff_liquidity_gap"
assert payload["control_tower_snapshot"]["candidate_pool_recall_truncation_frontier_summary"]["observed_case_count"] == 1
```

- [ ] **Step 2: Run the regression and confirm the current failure**

Run:

```bash
uv run pytest tests/test_btst_control_tower_scripts.py::test_btst_nightly_control_tower_generates_one_click_bundle_and_reindexes_manifest -q
```

Expected: FAIL on `dominant_ranking_driver` or `liquidity_gap_mode`, proving the frontier metrics still lack enough context.

- [ ] **Step 3: Implement the smallest frontier fallback**

In `analyze_btst_candidate_pool_recall_dossier.py`, once a row has:
- stock basic,
- local average amount,
- a candidate-pool snapshot with `selected_cutoff_ticker`,

add a minimal fallback that computes:

```python
payload["pre_truncation_ranking_driver"] = "mixed_post_filter_gap"
payload["pre_truncation_liquidity_gap_mode"] = "near_cutoff_liquidity_gap"
payload["pre_truncation_frontier_window"] = [
    {
        "ticker": payload["candidate_pool_selected_cutoff_ticker"],
        "rank": 300,
        "avg_amount_20d": payload["pre_truncation_cutoff_avg_amount_20d"],
    }
]
```

only when the richer frontier ranking path is unavailable but the local fallback context is present. Keep this fallback tightly scoped to the truncation case so it does not overwrite richer data.

- [ ] **Step 4: Run the regression test to green**

Run:

```bash
uv run pytest tests/test_btst_control_tower_scripts.py::test_btst_nightly_control_tower_generates_one_click_bundle_and_reindexes_manifest -q
```

Expected: PASS.


### Task 4: Re-run the focused Gamma baseline after the architecture fix

**Files:**
- Test: `tests/test_btst_control_tower_scripts.py`
- Test: `tests/scripts/test_analyze_catalyst_theme_frontier_script.py`

- [ ] **Step 1: Run the targeted Gamma baseline suite**

Run:

```bash
uv run pytest tests/test_btst_control_tower_scripts.py tests/scripts/test_analyze_catalyst_theme_frontier_script.py -q
```

Expected: PASS.

- [ ] **Step 2: Record the architecture fix checkpoint**

Run:

```bash
git add scripts/btst_layer_a_market_context_builder.py \
  scripts/analyze_btst_candidate_pool_recall_dossier.py \
  tests/test_btst_control_tower_scripts.py
git commit -m "fix: unify layer-a market context fallback for BTST recall diagnostics"
```

Expected: commit created on `copilot/btst-system-hardening`.
