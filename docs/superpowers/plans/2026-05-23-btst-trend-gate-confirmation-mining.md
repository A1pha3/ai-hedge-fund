# BTST Trend Gate Confirmation Mining Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a confirmation-grid analysis script that mines second-layer BTST confirmation factors inside the current best narrow catalyst trend gate.

**Architecture:** Reuse the existing trend-gate helper chain to collect rows and anchor the best base gate, then evaluate a small catalog of confirmation predicates on the deduped base universe. Keep decisions fail-closed so the script only produces research artifacts and never mutates runtime trading logic.

**Tech Stack:** Python 3.11+, existing BTST analysis scripts, pytest

---

### Task 1: Add the failing tests first

**Files:**
- Create: `tests/test_analyze_btst_5d_15pct_trend_gate_confirmation_grid_script.py`
- Reference: `tests/test_analyze_btst_5d_15pct_trend_gate_threshold_grid_script.py`
- Target: `scripts/analyze_btst_5d_15pct_trend_gate_confirmation_grid.py`

- [ ] Write the ranking, fail-closed, and CLI artifact tests.
- [ ] Run `uv run pytest tests/test_analyze_btst_5d_15pct_trend_gate_confirmation_grid_script.py -q`.
- [ ] Confirm the test file fails because the implementation module does not exist yet.

### Task 2: Implement the confirmation-grid script

**Files:**
- Create: `scripts/analyze_btst_5d_15pct_trend_gate_confirmation_grid.py`
- Reuse: `scripts/analyze_btst_5d_15pct_trend_top20_gate_diagnostics.py`
- Reuse: `scripts/analyze_btst_5d_15pct_trend_gate_oos_validation.py`

- [ ] Add the confirmation-spec parser and predicate builder.
- [ ] Anchor the fixed base gate using the existing top-fraction and entry-gap filters.
- [ ] Build one board row per confirmation candidate with deduped metrics.
- [ ] Add conservative ranking and fail-closed decision logic.
- [ ] Add Markdown/JSON artifact rendering and CLI output support.
- [ ] Re-run `uv run pytest tests/test_analyze_btst_5d_15pct_trend_gate_confirmation_grid_script.py -q` until green.

### Task 3: Run the adjacent regression stack

**Files:**
- Test: `tests/test_analyze_btst_5d_15pct_trend_gate_confirmation_grid_script.py`
- Test: `tests/test_analyze_btst_5d_15pct_trend_gate_threshold_grid_script.py`
- Test: `tests/test_analyze_btst_5d_15pct_trend_gate_sample_intake_board_script.py`
- Test: `tests/test_analyze_btst_5d_15pct_trend_top20_gate_diagnostics_script.py`

- [ ] Run the focused regression set:

```bash
uv run pytest \
  tests/test_analyze_btst_5d_15pct_trend_gate_confirmation_grid_script.py \
  tests/test_analyze_btst_5d_15pct_trend_gate_threshold_grid_script.py \
  tests/test_analyze_btst_5d_15pct_trend_gate_sample_intake_board_script.py \
  tests/test_analyze_btst_5d_15pct_trend_top20_gate_diagnostics_script.py -q
```

- [ ] Keep the work fail-closed unless every test passes.
