# BTST 5D15 Boundary Contract Fill-Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a narrow validation cycle that tries to deterministically repair `short_trade_boundary` and `layer_b_boundary` rows into the round1 core explainability contract, while keeping quarantine as the fail-closed fallback.

**Architecture:** Add one focused helper module that defines the required boundary fill contract, repairs rows with explicit per-key provenance, and assigns row-level repair statuses plus a governed outcome. Then add one analysis script that rebuilds the verified 121-row boundary cohort, applies the repair helper, emits JSON/Markdown boards, and ends with a Chinese interpretation note documenting whether repaired rows may re-enter offline research.

**Tech Stack:** Python 3.12, pytest, existing BTST rebuild utilities under `scripts/`, JSON/Markdown report generation under `data/reports/`, Chinese governance note under `docs/prompt/find_actor_methord/`

---

## File Structure

- Reuse: `scripts/analyze_btst_5d_15pct_boundary_contract_inspection.py`
  - reuse the verified boundary-cohort filter so the fill-path cycle stays pinned to the 121-row surface
- Reuse: `scripts/analyze_btst_5d_15pct_missing_core_features_noise_compression.py`
  - reuse `CORE_EXPLAINABILITY_KEYS` as the required round1 key set
- Create: `scripts/btst_boundary_contract_fill_helpers.py`
  - define the required key contract, per-key deterministic fill rules, provenance capture, repair-status classification, and governance action helpers
- Create: `scripts/analyze_btst_5d_15pct_boundary_contract_fill_path.py`
  - rebuild the boundary cohort, apply fill-path repair, summarize source-level coverage, and render JSON/Markdown artifacts
- Create: `tests/test_btst_boundary_contract_fill_helpers.py`
  - unit tests for full / partial / irrecoverable repair behavior and provenance requirements
- Create: `tests/test_analyze_btst_5d_15pct_boundary_contract_fill_path_script.py`
  - end-to-end script test that proves the repaired-cohort and governance boards are deterministic
- Create: `docs/prompt/find_actor_methord/btst-5d15-boundary-contract-fill-path-2026-05-22.md`
  - Chinese interpretation of the live artifact, explicitly non-promotional and fail-closed

### Task 1: Add deterministic boundary fill helpers

**Files:**
- Create: `scripts/btst_boundary_contract_fill_helpers.py`
- Test: `tests/test_btst_boundary_contract_fill_helpers.py`

- [ ] **Step 1: Write the failing helper tests**

```python
from scripts.btst_boundary_contract_fill_helpers import (
    BOUNDARY_REQUIRED_CORE_KEYS,
    classify_boundary_repair_status,
    recommend_boundary_repair_action,
    repair_boundary_contract_row,
)


def test_repair_boundary_contract_row_fully_repairs_with_provenance() -> None:
    row = {
        "candidate_source": "short_trade_boundary",
        "boundary_context": {
            "breakout_freshness": 0.9,
            "trend_acceleration": 0.8,
            "volume_expansion_quality": 0.7,
            "close_strength": 0.6,
            "t0_tail_strength": 0.5,
            "trend_continuation": 0.4,
            "short_term_reversal": 0.3,
        },
        "metadata_keys": ["candidate_source", "layer_c_decision", "replay_context"],
    }

    repaired = repair_boundary_contract_row(row)

    assert repaired["repair_status"] == "fully_repaired_boundary_contract"
    assert repaired["missing_required_keys"] == []
    assert set(repaired["recovered_core_payload"]) == set(BOUNDARY_REQUIRED_CORE_KEYS)
    assert repaired["fill_provenance"]["trend_acceleration"] == "boundary_context.trend_acceleration"


def test_repair_boundary_contract_row_marks_irrecoverable_keys_explicitly() -> None:
    row = {
        "candidate_source": "layer_b_boundary",
        "boundary_context": {
            "breakout_freshness": 0.9,
            "close_strength": 0.4,
        },
        "metadata_keys": ["candidate_source", "layer_c_decision"],
    }

    repaired = repair_boundary_contract_row(row)

    # even with many missing keys, if we recovered any payload it should be "partially repaired"
    assert repaired["repair_status"] == "partially_repaired_boundary_contract"
    assert "trend_acceleration" in repaired["missing_required_keys"]
    assert "trend_acceleration" not in repaired["recovered_core_payload"]
    assert repaired["fill_provenance"]["breakout_freshness"] == "boundary_context.breakout_freshness"


def test_recommend_boundary_repair_action_only_allows_fully_repaired_rows_back() -> None:
    assert classify_boundary_repair_status([], 7) == "fully_repaired_boundary_contract"
    assert classify_boundary_repair_status(["trend_acceleration"], 6) == "partially_repaired_boundary_contract"
    assert recommend_boundary_repair_action(
        {
            "fully_repaired_row_count": 1,
            "partially_repaired_row_count": 2,
            "irrecoverable_row_count": 3,
        }
    ) == "quarantine_boundary_surface"
```

- [ ] **Step 2: Run the helper tests to verify they fail**

Run: `uv run pytest tests/test_btst_boundary_contract_fill_helpers.py -q`

Expected: FAIL with `ModuleNotFoundError` or missing helper symbols.

- [ ] **Step 3: Implement the narrow fill helper module**

```python
from __future__ import annotations

from typing import Any

from scripts.analyze_btst_5d_15pct_missing_core_features_noise_compression import CORE_EXPLAINABILITY_KEYS

BOUNDARY_REQUIRED_CORE_KEYS = tuple(CORE_EXPLAINABILITY_KEYS)


def classify_boundary_repair_status(missing_required_keys: list[str], recovered_key_count: int) -> str:
    if not missing_required_keys and recovered_key_count == len(BOUNDARY_REQUIRED_CORE_KEYS):
        return "fully_repaired_boundary_contract"
    if recovered_key_count > 0:
        return "partially_repaired_boundary_contract"
    return "irrecoverable_boundary_contract"


def repair_boundary_contract_row(row: dict[str, Any]) -> dict[str, Any]:
    boundary_context = dict(row.get("boundary_context") or {})
    recovered_core_payload: dict[str, Any] = {}
    fill_provenance: dict[str, str] = {}
    missing_required_keys: list[str] = []

    for key in BOUNDARY_REQUIRED_CORE_KEYS:
        if key in boundary_context:
            recovered_core_payload[key] = boundary_context[key]
            fill_provenance[key] = f"boundary_context.{key}"
        else:
            missing_required_keys.append(key)

    repair_status = classify_boundary_repair_status(missing_required_keys, len(recovered_core_payload))
    return {
        **row,
        "recovered_core_payload": recovered_core_payload,
        "fill_provenance": fill_provenance,
        "missing_required_keys": missing_required_keys,
        "repair_status": repair_status,
    }


def recommend_boundary_repair_action(summary: dict[str, Any]) -> str:
    if int(summary.get("irrecoverable_row_count") or 0) > 0:
        return "quarantine_boundary_surface"
    if int(summary.get("partially_repaired_row_count") or 0) > 0:
        return "hold_boundary_repair_until_more_context"
    return "allow_repaired_boundary_surface_for_offline_research"
```

- [ ] **Step 4: Run the helper tests to verify they pass**

Run: `uv run pytest tests/test_btst_boundary_contract_fill_helpers.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the helper layer**

```bash
git add tests/test_btst_boundary_contract_fill_helpers.py scripts/btst_boundary_contract_fill_helpers.py
git commit -m "feat: add boundary contract fill helpers"
```

### Task 2: Add the boundary fill-path analysis script

**Files:**
- Create: `scripts/analyze_btst_5d_15pct_boundary_contract_fill_path.py`
- Test: `tests/test_analyze_btst_5d_15pct_boundary_contract_fill_path_script.py`

- [ ] **Step 1: Write the failing end-to-end script test**

```python
from pathlib import Path

import scripts.analyze_btst_5d_15pct_boundary_contract_fill_path as fill_script


def test_analyze_btst_5d_15pct_boundary_contract_fill_path_builds_repair_and_governance_boards(tmp_path: Path) -> None:
    rows = [
        {
            "candidate_source": "short_trade_boundary",
            "ticker": "001309",
            "trade_date": "20260324",
            "boundary_context": {
                "breakout_freshness": 0.9,
                "trend_acceleration": 0.8,
                "volume_expansion_quality": 0.7,
                "close_strength": 0.6,
                "t0_tail_strength": 0.5,
                "trend_continuation": 0.4,
                "short_term_reversal": 0.3,
            },
            "metadata_keys": ["candidate_source", "layer_c_decision", "replay_context"],
        },
        {
            "candidate_source": "layer_b_boundary",
            "ticker": "300111",
            "trade_date": "20260324",
            "boundary_context": {
                "breakout_freshness": 0.9,
                "close_strength": 0.4,
            },
            "metadata_keys": ["candidate_source", "layer_c_decision"],
        },
    ]

    analysis = fill_script.analyze_btst_5d_15pct_boundary_contract_fill_path_from_rows(rows)

    assert analysis["boundary_row_count"] == 2
    assert analysis["repair_status_board"][0]["repair_status"] == "fully_repaired_boundary_contract"
    assert analysis["repair_status_board"][1]["repair_status"] == "irrecoverable_boundary_contract"
    assert analysis["governance_decision_board"][0]["action"] == "quarantine_boundary_surface"
```

- [ ] **Step 2: Run the script test to verify it fails**

Run: `uv run pytest tests/test_analyze_btst_5d_15pct_boundary_contract_fill_path_script.py -q`

Expected: FAIL because the analysis module does not exist yet.

- [ ] **Step 3: Implement the fill-path analysis script**

```python
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.analyze_btst_5d_15pct_boundary_contract_inspection import analyze_btst_5d_15pct_boundary_contract_inspection
from scripts.btst_boundary_contract_fill_helpers import recommend_boundary_repair_action, repair_boundary_contract_row


def analyze_btst_5d_15pct_boundary_contract_fill_path_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    repaired_rows = [repair_boundary_contract_row(row) for row in rows]
    repair_counter = Counter(str(row["repair_status"]) for row in repaired_rows)
    summary = {
        "fully_repaired_row_count": repair_counter.get("fully_repaired_boundary_contract", 0),
        "partially_repaired_row_count": repair_counter.get("partially_repaired_boundary_contract", 0),
        "irrecoverable_row_count": repair_counter.get("irrecoverable_boundary_contract", 0),
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "boundary_row_count": len(repaired_rows),
        "repair_status_board": repaired_rows,
        "repair_summary_board": [summary],
        "governance_decision_board": [
            {
                "action": recommend_boundary_repair_action(summary),
                "reason": "boundary fill-path outcome is governed by irrecoverable and partial repair counts",
            }
        ],
    }


def analyze_btst_5d_15pct_boundary_contract_fill_path(reports_root: Path) -> dict[str, Any]:
    inspection = analyze_btst_5d_15pct_boundary_contract_inspection(reports_root)
    rows = list(inspection["boundary_rows"])
    return analyze_btst_5d_15pct_boundary_contract_fill_path_from_rows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports-root", type=Path, default=Path("data/reports"))
    parser.add_argument("--output-json", type=Path, default=Path("data/reports/btst_5d_15pct_boundary_contract_fill_path_latest.json"))
    args = parser.parse_args()
    analysis = analyze_btst_5d_15pct_boundary_contract_fill_path(args.reports_root)
    args.output_json.write_text(json.dumps(analysis, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
```

- [ ] **Step 4: Run the script test to verify it passes**

Run: `uv run pytest tests/test_analyze_btst_5d_15pct_boundary_contract_fill_path_script.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the analysis script**

```bash
git add tests/test_analyze_btst_5d_15pct_boundary_contract_fill_path_script.py scripts/analyze_btst_5d_15pct_boundary_contract_fill_path.py
git commit -m "feat: add boundary fill-path analysis"
```

### Task 3: Generate live artifacts, write the Chinese note, and run focused regressions

**Files:**
- Modify: `scripts/analyze_btst_5d_15pct_boundary_contract_fill_path.py`
- Create: `data/reports/btst_5d_15pct_boundary_contract_fill_path_latest.json`
- Create: `data/reports/btst_5d_15pct_boundary_contract_fill_path_latest.md`
- Create: `docs/prompt/find_actor_methord/btst-5d15-boundary-contract-fill-path-2026-05-22.md`
- Test: `tests/test_btst_boundary_contract_fill_helpers.py`
- Test: `tests/test_analyze_btst_5d_15pct_boundary_contract_fill_path_script.py`
- Test: `tests/test_btst_boundary_contract_helpers.py`
- Test: `tests/test_analyze_btst_5d_15pct_boundary_contract_inspection_script.py`

- [ ] **Step 1: Extend the script with Markdown rendering and deterministic source-level summaries**

```python
def render_markdown_report(analysis: dict[str, Any]) -> str:
    summary = analysis["repair_summary_board"][0]
    governance = analysis["governance_decision_board"][0]
    lines = [
        "# BTST 5D / +15% Boundary Contract Fill Path",
        "",
        f"- boundary_row_count: {analysis['boundary_row_count']}",
        "",
        "## repair_summary_board",
        f"- fully_repaired_row_count: {summary['fully_repaired_row_count']}",
        f"- partially_repaired_row_count: {summary['partially_repaired_row_count']}",
        f"- irrecoverable_row_count: {summary['irrecoverable_row_count']}",
        "",
        "## governance_decision_board",
        f"- {governance['action']}: {governance['reason']}",
    ]
    return "\n".join(lines) + "\n"
```

- [ ] **Step 2: Run the live fill-path script**

Run: `uv run python scripts/analyze_btst_5d_15pct_boundary_contract_fill_path.py`

Expected: writes `data/reports/btst_5d_15pct_boundary_contract_fill_path_latest.json` and `data/reports/btst_5d_15pct_boundary_contract_fill_path_latest.md`.

- [ ] **Step 3: Write the Chinese interpretation note**

```markdown
# btst-5d15-boundary-contract-fill-path-2026-05-22

## 原理
- 本轮只验证 `short_trade_boundary` 和 `layer_b_boundary` 是否能被确定性补齐 round1 核心 explainability 键。
- 这不是 alpha 提升结论，而是 boundary contract 修复 / 隔离验证。

## repair summary
- 记录 fully repaired、partially repaired、irrecoverable 三类行数。
- 明确哪些 key 可以从 boundary context 前推，哪些 key 仍然缺失。

## alpha 结论
- 只有在 repaired rows 仍然保持结构一致时，才允许回到 offline research surface。

## beta 结论
- beta 必须说明每个被补齐 key 的 provenance，不能凭猜测造值。

## gamma 结论
- 如果仍存在 irrecoverable rows，默认动作保持 fail-closed。

## 下一轮动作
- 若允许回流，仅进入 offline research validation；仍不进入 runtime BTST。
- 若不能修复，则继续 `quarantine_boundary_surface`。
```

- [ ] **Step 4: Run the focused regression bundle**

Run: `uv run pytest tests/test_btst_boundary_contract_fill_helpers.py tests/test_analyze_btst_5d_15pct_boundary_contract_fill_path_script.py tests/test_btst_boundary_contract_helpers.py tests/test_analyze_btst_5d_15pct_boundary_contract_inspection_script.py tests/test_btst_missing_core_features_noise_helpers.py tests/test_analyze_btst_5d_15pct_missing_core_features_noise_compression_script.py tests/test_btst_near_trend_threshold_recovery_helpers.py tests/test_analyze_btst_5d_15pct_near_trend_threshold_recovery_script.py -q`

Expected: PASS, with only the pre-existing external warnings if any.

- [ ] **Step 5: Commit artifacts and documentation**

```bash
git add \
  scripts/analyze_btst_5d_15pct_boundary_contract_fill_path.py \
  tests/test_btst_boundary_contract_fill_helpers.py \
  tests/test_analyze_btst_5d_15pct_boundary_contract_fill_path_script.py \
  data/reports/btst_5d_15pct_boundary_contract_fill_path_latest.json \
  data/reports/btst_5d_15pct_boundary_contract_fill_path_latest.md \
  docs/prompt/find_actor_methord/btst-5d15-boundary-contract-fill-path-2026-05-22.md
git commit -m "feat: validate boundary contract fill path"
```

## Self-Review Checklist

- Spec coverage: Task 1 covers the required core-key contract map and per-key provenance; Task 2 covers repaired-cohort analysis and governance decisioning; Task 3 covers live artifact generation, Chinese interpretation, and focused regression evidence.
- Placeholder scan: No `TBD`, `TODO`, or unresolved pseudo-steps remain; each code step includes concrete snippets and each run step includes exact commands.
- Type consistency: The plan consistently uses `BOUNDARY_REQUIRED_CORE_KEYS`, `repair_boundary_contract_row()`, `classify_boundary_repair_status()`, `recommend_boundary_repair_action()`, and `analyze_btst_5d_15pct_boundary_contract_fill_path_from_rows()` across all tasks.
