# BTST 5D15 Boundary Missing-Six-Core-Keys Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a narrow trace cycle that shows where the six missing round1 core keys disappear between boundary source generation and `selection_snapshot`, so Alpha/Beta/Gamma can decide whether the next fix belongs in the boundary source contract or the snapshot attachment contract.

**Architecture:** Add one focused trace helper that compares key presence across three layers: source payload, attached `selection_targets`, and serialized snapshot. Then add one analysis script that reconstructs the 121-row boundary cohort, emits key-level diagnosis boards plus a survivor-key contrast board for `t0_tail_strength`, and ends with a conservative Chinese note that remains fail-closed.

**Tech Stack:** Python 3.11+, pytest, existing BTST artifact builders in `src/research/artifacts.py`, boundary/offline analysis scripts under `scripts/`, Markdown/JSON artifacts under `data/reports/` and `docs/prompt/find_actor_methord/`

---

## File Structure

- Reuse: `src/research/artifacts.py`
  - use `build_selection_snapshot()` and the replay-input/build helpers as the authoritative upstream path for boundary data entering `selection_snapshot`
- Reuse: `scripts/analyze_btst_5d_15pct_boundary_contract_inspection.py`
  - reuse the verified boundary cohort filter (`root_cause == boundary_without_explainability`, `bucket == missing_all_core_features`, boundary sources only)
- Create: `scripts/btst_boundary_missing_core_key_trace_helpers.py`
  - encapsulate key-by-key trace logic and diagnosis status classification
- Create: `scripts/analyze_btst_5d_15pct_boundary_missing_six_core_keys.py`
  - reconstruct the trace boards and write JSON/Markdown artifacts
- Create: `tests/test_btst_boundary_missing_core_key_trace_helpers.py`
  - unit tests for source/attachment/snapshot key-trace status classification
- Create: `tests/test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_script.py`
  - end-to-end script tests for board generation and governance output
- Create: `docs/prompt/find_actor_methord/btst-5d15-boundary-missing-six-core-keys-2026-05-22.md`
  - Chinese interpretation of the live trace artifact, explicitly non-promotional and fail-closed

### Task 1: Add deterministic missing-key trace helpers

**Files:**
- Create: `scripts/btst_boundary_missing_core_key_trace_helpers.py`
- Test: `tests/test_btst_boundary_missing_core_key_trace_helpers.py`

- [ ] **Step 1: Write the failing helper tests**

```python
from scripts.btst_boundary_missing_core_key_trace_helpers import (
    BOUNDARY_TRACE_KEYS,
    classify_boundary_key_trace_status,
    summarize_boundary_key_trace_statuses,
)


def test_classify_boundary_key_trace_status_marks_missing_at_source() -> None:
    assert classify_boundary_key_trace_status(
        key="breakout_freshness",
        source_payload={},
        attached_target={},
        snapshot_target={},
    ) == "missing_at_source"


def test_classify_boundary_key_trace_status_marks_dropped_before_snapshot() -> None:
    assert classify_boundary_key_trace_status(
        key="trend_acceleration",
        source_payload={"trend_acceleration": 0.8},
        attached_target={},
        snapshot_target={},
    ) == "dropped_before_snapshot"


def test_classify_boundary_key_trace_status_marks_dropped_during_snapshot_serialization() -> None:
    assert classify_boundary_key_trace_status(
        key="volume_expansion_quality",
        source_payload={"volume_expansion_quality": 0.7},
        attached_target={"volume_expansion_quality": 0.7},
        snapshot_target={},
    ) == "dropped_during_snapshot_serialization"


def test_summarize_boundary_key_trace_statuses_counts_present_end_to_end() -> None:
    summary = summarize_boundary_key_trace_statuses(
        source_payload={"t0_tail_strength": 0.9},
        attached_target={"t0_tail_strength": 0.9},
        snapshot_target={"t0_tail_strength": 0.9},
    )

    assert summary["key_trace_statuses"]["t0_tail_strength"] == "present_end_to_end"
    assert summary["status_counts"]["present_end_to_end"] == 1
    assert set(summary["key_trace_statuses"]) == set(BOUNDARY_TRACE_KEYS)
```

- [ ] **Step 2: Run the helper tests to verify they fail**

Run: `uv run pytest tests/test_btst_boundary_missing_core_key_trace_helpers.py -q`

Expected: FAIL with `ModuleNotFoundError` or missing helper symbols.

- [ ] **Step 3: Implement the trace helper module**

```python
from __future__ import annotations

from collections import Counter
from typing import Any

BOUNDARY_TRACE_KEYS = (
    "breakout_freshness",
    "trend_acceleration",
    "volume_expansion_quality",
    "close_strength",
    "trend_continuation",
    "short_term_reversal",
)


def classify_boundary_key_trace_status(*, key: str, source_payload: dict[str, Any], attached_target: dict[str, Any], snapshot_target: dict[str, Any]) -> str:
    source_has = source_payload.get(key) is not None
    attached_has = attached_target.get(key) is not None
    snapshot_has = snapshot_target.get(key) is not None
    if not source_has:
        return "missing_at_source"
    if not attached_has:
        return "dropped_before_snapshot"
    if not snapshot_has:
        return "dropped_during_snapshot_serialization"
    return "present_end_to_end"


def summarize_boundary_key_trace_statuses(*, source_payload: dict[str, Any], attached_target: dict[str, Any], snapshot_target: dict[str, Any]) -> dict[str, Any]:
    key_trace_statuses = {
        key: classify_boundary_key_trace_status(
            key=key,
            source_payload=source_payload,
            attached_target=attached_target,
            snapshot_target=snapshot_target,
        )
        for key in BOUNDARY_TRACE_KEYS
    }
    return {
        "key_trace_statuses": key_trace_statuses,
        "status_counts": dict(Counter(key_trace_statuses.values())),
    }
```

- [ ] **Step 4: Run the helper tests to verify they pass**

Run: `uv run pytest tests/test_btst_boundary_missing_core_key_trace_helpers.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the helper layer**

```bash
git add tests/test_btst_boundary_missing_core_key_trace_helpers.py scripts/btst_boundary_missing_core_key_trace_helpers.py
git commit -m "feat: add boundary missing-key trace helpers"
```

### Task 2: Add the boundary missing-six-core-keys analysis script

**Files:**
- Create: `scripts/analyze_btst_5d_15pct_boundary_missing_six_core_keys.py`
- Test: `tests/test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_script.py`

- [ ] **Step 1: Write the failing end-to-end script test**

```python
from pathlib import Path

import scripts.analyze_btst_5d_15pct_boundary_missing_six_core_keys as trace_script


def test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_builds_trace_and_governance_boards(tmp_path: Path, monkeypatch) -> None:
    traced_rows = [
        {
            "ticker": "001309",
            "candidate_source": "short_trade_boundary",
            "source_payload": {"t0_tail_strength": 0.9, "trend_acceleration": 0.8},
            "attached_target": {"t0_tail_strength": 0.9},
            "snapshot_target": {"t0_tail_strength": 0.9},
        },
        {
            "ticker": "300111",
            "candidate_source": "layer_b_boundary",
            "source_payload": {"t0_tail_strength": 0.7},
            "attached_target": {"t0_tail_strength": 0.7},
            "snapshot_target": {"t0_tail_strength": 0.7},
        },
    ]

    analysis = trace_script.analyze_btst_5d_15pct_boundary_missing_six_core_keys_from_rows(traced_rows)

    assert analysis["boundary_row_count"] == 2
    assert analysis["trace_status_board"][0]["key_trace_statuses"]["trend_acceleration"] == "dropped_before_snapshot"
    assert analysis["survivor_key_contrast_board"][0]["key"] == "t0_tail_strength"
    assert analysis["governance_diagnosis_board"][0]["action"] == "fix_boundary_source_contract"
```

- [ ] **Step 2: Run the script test to verify it fails**

Run: `uv run pytest tests/test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_script.py -q`

Expected: FAIL because the analysis module does not exist yet.

- [ ] **Step 3: Implement the trace analysis script**

```python
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.btst_boundary_missing_core_key_trace_helpers import BOUNDARY_TRACE_KEYS, summarize_boundary_key_trace_statuses


def analyze_btst_5d_15pct_boundary_missing_six_core_keys_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    trace_status_board: list[dict[str, Any]] = []
    key_status_counter: Counter[tuple[str, str]] = Counter()
    source_status_counter: dict[str, Counter[str]] = defaultdict(Counter)
    survivor_counter: Counter[str] = Counter()

    for row in rows:
        trace_summary = summarize_boundary_key_trace_statuses(
            source_payload=dict(row.get("source_payload") or {}),
            attached_target=dict(row.get("attached_target") or {}),
            snapshot_target=dict(row.get("snapshot_target") or {}),
        )
        enriched_row = {**row, **trace_summary}
        trace_status_board.append(enriched_row)
        candidate_source = str(row.get("candidate_source") or "unknown")
        for key, status in trace_summary["key_trace_statuses"].items():
            key_status_counter[(key, status)] += 1
            source_status_counter[candidate_source][status] += 1
            if status == "present_end_to_end":
                survivor_counter[key] += 1

    boundary_source_trace_board = [
        {
            "candidate_source": candidate_source,
            "status_counts": dict(counter),
            "row_count": sum(counter.values()) // len(BOUNDARY_TRACE_KEYS) if BOUNDARY_TRACE_KEYS else 0,
        }
        for candidate_source, counter in sorted(source_status_counter.items())
    ]
    key_trace_summary_board = [
        {"key": key, "status": status, "count": count}
        for (key, status), count in sorted(key_status_counter.items())
    ]
    survivor_key_contrast_board = [
        {"key": key, "surviving_row_count": count}
        for key, count in survivor_counter.most_common()
    ]
    if not survivor_key_contrast_board:
        survivor_key_contrast_board = [{"key": "none", "surviving_row_count": 0}]
    governance_action = "fix_boundary_source_contract" if any(item["status"] == "missing_at_source" for item in key_trace_summary_board) else "fix_snapshot_attachment_contract"
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "boundary_row_count": len(rows),
        "trace_status_board": trace_status_board,
        "key_trace_summary_board": key_trace_summary_board,
        "boundary_source_trace_board": boundary_source_trace_board,
        "survivor_key_contrast_board": survivor_key_contrast_board,
        "governance_diagnosis_board": [
            {
                "action": governance_action,
                "reason": "trace outcome points to the earliest confirmed boundary missing-key break",
            }
        ],
    }
```

- [ ] **Step 4: Run the script test to verify it passes**

Run: `uv run pytest tests/test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_script.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the trace script**

```bash
git add tests/test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_script.py scripts/analyze_btst_5d_15pct_boundary_missing_six_core_keys.py
git commit -m "feat: add boundary missing-six-core-keys trace"
```

### Task 3: Generate live trace artifacts, write the Chinese note, and run focused regressions

**Files:**
- Modify: `scripts/analyze_btst_5d_15pct_boundary_missing_six_core_keys.py`
- Create: `data/reports/btst_5d_15pct_boundary_missing_six_core_keys_latest.json`
- Create: `data/reports/btst_5d_15pct_boundary_missing_six_core_keys_latest.md`
- Create: `docs/prompt/find_actor_methord/btst-5d15-boundary-missing-six-core-keys-2026-05-22.md`
- Test: `tests/test_btst_boundary_missing_core_key_trace_helpers.py`
- Test: `tests/test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_script.py`
- Test: `tests/test_analyze_btst_5d_15pct_boundary_contract_inspection_script.py`

- [ ] **Step 1: Extend the script with artifact rendering and real-row reconstruction**

```python
def render_btst_5d_15pct_boundary_missing_six_core_keys_markdown(analysis: dict[str, Any]) -> str:
    governance = dict((analysis.get("governance_diagnosis_board") or [{}])[0])
    lines = [
        "# BTST 5D / +15% Boundary Missing Six Core Keys",
        "",
        f"- boundary_row_count: {analysis.get('boundary_row_count')}",
        "",
        "## key_trace_summary_board",
    ]
    for row in analysis.get("key_trace_summary_board") or []:
        lines.append(f"- {row.get('key')}: status={row.get('status')}, count={row.get('count')}")
    lines.extend(["", "## governance_diagnosis_board", f"- {governance.get('action')}: {governance.get('reason')}", ""])
    return "\n".join(lines)
```

- [ ] **Step 2: Run the live trace script**

Run: `uv run python scripts/analyze_btst_5d_15pct_boundary_missing_six_core_keys.py`

Expected: writes `data/reports/btst_5d_15pct_boundary_missing_six_core_keys_latest.json` and `.md`.

- [ ] **Step 3: Write the Chinese interpretation note**

```markdown
# btst-5d15-boundary-missing-six-core-keys-2026-05-22

## 原理
- 本轮只追 boundary source 到 `selection_snapshot` 这条链路中，为什么 6 个核心键仍然为 None。
- 这不是 alpha 提升结论，而是 boundary 上游 contract 诊断。

## 关键发现
- 逐键说明哪些键在 source 就缺失，哪些键在 snapshot 过程中丢失。
- 单独说明为什么 `t0_tail_strength` 能存活，而其余 6 键不能。

## alpha 结论
- 只要 6 个关键键仍然缺失，partial-only 边界样本就不能进入正式 alpha surface。

## beta 结论
- beta 必须把缺失点定位到 boundary source 还是 snapshot attachment，避免继续在 fill-path 层重复修补。

## gamma 结论
- 继续 fail-closed；诊断结果只能决定下一步修 source 还是修 snapshot，不构成 runtime 放行。

## 下一轮动作
- 若确认缺失发生在 source，则优先修 `fix_boundary_source_contract`。
- 若确认缺失发生在 snapshot，则优先修 `fix_snapshot_attachment_contract`。
- 在修复并重新验证前，不推进任何内容到 `docs/prompt/find_actor/`，也不接入 `ai-hedge-fund-btst`。
```

- [ ] **Step 4: Run the focused regression bundle**

Run: `uv run pytest tests/test_btst_boundary_missing_core_key_trace_helpers.py tests/test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_script.py tests/test_analyze_btst_5d_15pct_boundary_contract_inspection_script.py -q`

Expected: PASS.

- [ ] **Step 5: Commit artifacts and interpretation note**

```bash
git add \
  scripts/analyze_btst_5d_15pct_boundary_missing_six_core_keys.py \
  tests/test_btst_boundary_missing_core_key_trace_helpers.py \
  tests/test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_script.py \
  data/reports/btst_5d_15pct_boundary_missing_six_core_keys_latest.json \
  data/reports/btst_5d_15pct_boundary_missing_six_core_keys_latest.md \
  docs/prompt/find_actor_methord/btst-5d15-boundary-missing-six-core-keys-2026-05-22.md
git commit -m "feat: trace boundary missing six core keys"
```

## Self-Review Checklist

- Spec coverage: Task 1 covers the missing-key trace helper and status taxonomy; Task 2 covers the source/snapshot trace boards plus governance diagnosis; Task 3 covers live artifacts, the Chinese note, and focused regressions.
- Placeholder scan: No `TBD`, `TODO`, unresolved pseudo-steps, or cross-task “similar to” references remain; each step includes concrete code or exact commands.
- Type consistency: The plan consistently uses `BOUNDARY_TRACE_KEYS`, `classify_boundary_key_trace_status()`, `summarize_boundary_key_trace_statuses()`, `analyze_btst_5d_15pct_boundary_missing_six_core_keys_from_rows()`, `key_trace_summary_board`, `boundary_source_trace_board`, `survivor_key_contrast_board`, and `governance_diagnosis_board`.
