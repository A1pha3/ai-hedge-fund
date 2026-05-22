# BTST 5D15 Boundary Contract Inspection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a narrow boundary-contract inspection cycle so the BTST 5D/+15% research surface can decide whether `short_trade_boundary` and `layer_b_boundary` should be fixed or quarantined.

**Architecture:** Reuse the verified missing-core compression rebuild path, then add a focused helper module that summarizes boundary metadata-only contract shape and assigns a contract verdict plus governance action. Build one analysis script that isolates `boundary_without_explainability`, compares the two boundary sources, emits JSON/Markdown artifacts, and ends with a Chinese interpretation note that stays at governance level.

**Tech Stack:** Python 3.12, pytest, existing BTST row rebuild / missing-core helpers under `scripts/`, Markdown/JSON artifacts under `data/reports/` and `docs/prompt/find_actor_methord/`

---

## File Structure

- Reuse: `scripts/analyze_btst_5d_15pct_missing_core_features_noise_compression.py`
  - reuse its row-rebuild pattern so boundary inspection stays aligned with the verified missing-core surface
- Reuse: `scripts/btst_missing_core_features_noise_helpers.py`
  - reuse `boundary_without_explainability` classification instead of redefining the boundary cohort
- Create: `scripts/btst_boundary_contract_helpers.py`
  - summarize per-source metadata-only contract shape and map it to a contract verdict / governance action
- Create: `scripts/analyze_btst_5d_15pct_boundary_contract_inspection.py`
  - rebuild the boundary cohort, compare `short_trade_boundary` vs `layer_b_boundary`, and emit the comparison/recommendation artifacts
- Create: `tests/test_btst_boundary_contract_helpers.py`
  - unit coverage for boundary contract verdicts and governance actions
- Create: `tests/test_analyze_btst_5d_15pct_boundary_contract_inspection_script.py`
  - end-to-end script test with synthetic boundary rows
- Create: `docs/prompt/find_actor_methord/btst-5d15-boundary-contract-inspection-2026-05-22.md`
  - Chinese summary of the live boundary contract artifact, explicitly non-promotional

### Task 1: Add deterministic boundary contract helpers

**Files:**
- Create: `scripts/btst_boundary_contract_helpers.py`
- Test: `tests/test_btst_boundary_contract_helpers.py`

- [ ] **Step 1: Write the failing helper tests**

```python
from scripts.btst_boundary_contract_helpers import (
    classify_boundary_contract_verdict,
    recommend_boundary_contract_action,
    summarize_boundary_contract_group,
)


def test_summarize_boundary_contract_group_reports_metadata_only_boundary_contract() -> None:
    rows = [
        {
            "candidate_source": "short_trade_boundary",
            "decision": "near_miss",
            "metadata_keys": ["breakout_stage", "target_profile", "replay_context"],
            "core_explainability_key_count": 0,
        },
        {
            "candidate_source": "short_trade_boundary",
            "decision": "rejected",
            "metadata_keys": ["breakout_stage", "layer_c_decision", "replay_context"],
            "core_explainability_key_count": 0,
        },
    ]

    summary = summarize_boundary_contract_group(rows)

    assert summary["row_count"] == 2
    assert summary["metadata_only_rate"] == 1.0
    assert summary["top_metadata_keys"][:2] == ["breakout_stage", "replay_context"]
    assert classify_boundary_contract_verdict(summary) == "metadata_only_boundary_contract"


def test_recommend_boundary_contract_action_requests_fix_for_metadata_only_boundary_contract() -> None:
    summary = {
        "contract_verdict": "metadata_only_boundary_contract",
        "row_count": 5,
    }

    assert recommend_boundary_contract_action(summary) == "fix_candidate_source_contract"
```

- [ ] **Step 2: Run the helper tests and verify they fail**

Run: `uv run pytest tests/test_btst_boundary_contract_helpers.py -q`

Expected: FAIL with `ModuleNotFoundError` or missing helper functions.

- [ ] **Step 3: Implement the helper module with narrow verdict logic**

```python
from __future__ import annotations

from collections import Counter
from typing import Any

from scripts.btst_analysis_utils import round_or_none


def summarize_boundary_contract_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metadata_counter = Counter(key for row in rows for key in list(row.get("metadata_keys") or []))
    metadata_only_rate = round_or_none(sum(1 for row in rows if int(row.get("core_explainability_key_count") or 0) == 0) / len(rows)) if rows else None
    return {
        "row_count": len(rows),
        "decision_counts": dict(Counter(str(row.get("decision") or "unknown") for row in rows)),
        "metadata_only_rate": metadata_only_rate,
        "top_metadata_keys": [item[0] for item in metadata_counter.most_common(5)],
        "core_payload_empty_count": sum(1 for row in rows if int(row.get("core_explainability_key_count") or 0) == 0),
    }


def classify_boundary_contract_verdict(summary: dict[str, Any]) -> str:
    metadata_only_rate = float(summary.get("metadata_only_rate") or 0.0)
    if metadata_only_rate >= 0.95:
        return "metadata_only_boundary_contract"
    if metadata_only_rate <= 0.20:
        return "partial_factor_contract"
    return "mixed_boundary_contract"


def recommend_boundary_contract_action(summary: dict[str, Any]) -> str:
    verdict = str(summary.get("contract_verdict") or classify_boundary_contract_verdict(summary))
    if verdict == "metadata_only_boundary_contract":
        return "fix_candidate_source_contract"
    if verdict == "partial_factor_contract":
        return "hold_boundary_until_more_context"
    return "quarantine_boundary_surface"
```

- [ ] **Step 4: Run the helper tests and verify they pass**

Run: `uv run pytest tests/test_btst_boundary_contract_helpers.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the helper layer**

```bash
git add tests/test_btst_boundary_contract_helpers.py scripts/btst_boundary_contract_helpers.py
git commit -m "feat: add boundary contract helpers"
```

### Task 2: Add the boundary contract inspection script

**Files:**
- Create: `scripts/analyze_btst_5d_15pct_boundary_contract_inspection.py`
- Test: `tests/test_analyze_btst_5d_15pct_boundary_contract_inspection_script.py`

- [ ] **Step 1: Write the failing end-to-end script test**

```python
from pathlib import Path

import scripts.analyze_btst_5d_15pct_boundary_contract_inspection as boundary_script


def test_analyze_btst_5d_15pct_boundary_contract_inspection_builds_source_comparison_and_governance_boards(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_window_20260323_20260326_boundary_contract"
    snapshot_dir = report_dir / "selection_artifacts" / "2026-03-24"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.joinpath("selection_snapshot.json").write_text(
        """
        {
          "trade_date": "20260324",
          "selection_targets": {
            "001309": {
              "candidate_source": "short_trade_boundary",
              "short_trade": {
                "decision": "near_miss",
                "explainability_payload": {
                  "breakout_stage": "early",
                  "target_profile": "tight",
                  "replay_context": "demo",
                  "layer_c_decision": "hold"
                }
              }
            },
            "300111": {
              "candidate_source": "layer_b_boundary",
              "short_trade": {
                "decision": "rejected",
                "explainability_payload": {
                  "replay_context": "demo",
                  "layer_c_decision": "reject",
                  "candidate_source": "layer_b_boundary"
                }
              }
            }
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        boundary_script,
        "_extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: {
            "cycle_status": "closed_cycle",
            "future_high_hit_15pct_2_5d": False,
            "max_future_high_return_2_5d": 0.04,
            "next_open_return": 0.01,
        },
    )

    analysis = boundary_script.analyze_btst_5d_15pct_boundary_contract_inspection(reports_root)

    assert analysis["boundary_row_count"] == 2
    assert {row["candidate_source"] for row in analysis["source_comparison_board"]} == {
        "short_trade_boundary",
        "layer_b_boundary",
    }
    assert analysis["governance_recommendation_board"][0]["action"] == "fix_candidate_source_contract"
```

- [ ] **Step 2: Run the script test and verify it fails**

Run: `uv run pytest tests/test_analyze_btst_5d_15pct_boundary_contract_inspection_script.py -q`

Expected: FAIL because the script module does not exist yet.

- [ ] **Step 3: Implement the boundary inspection script**

```python
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.analyze_btst_5d_15pct_missing_core_features_noise_compression import CORE_EXPLAINABILITY_KEYS
from scripts.btst_analysis_utils import (
    extract_btst_price_outcome as _extract_btst_price_outcome,
    iter_selection_snapshots as _iter_selection_snapshots,
    normalize_trade_date as _normalize_trade_date,
)
from scripts.btst_boundary_contract_helpers import (
    classify_boundary_contract_verdict,
    recommend_boundary_contract_action,
    summarize_boundary_contract_group,
)
from scripts.btst_missing_core_features_noise_helpers import classify_missing_core_root_cause
from scripts.btst_report_utils import discover_nested_report_dirs as discover_report_dirs
from scripts.btst_round1_factor_mining_helpers import build_round1_research_row
from scripts.btst_round1_unclassified_split_helpers import classify_unclassified_bucket


def _build_boundary_row(*, ticker: str, trade_date: str, report_dir_name: str, evaluation: dict[str, Any], price_outcome: dict[str, Any]) -> dict[str, Any]:
    short_trade = dict((evaluation or {}).get("short_trade") or {})
    explainability = dict(short_trade.get("explainability_payload") or {})
    row = build_round1_research_row(
        ticker=ticker,
        trade_date=trade_date,
        report_dir_name=report_dir_name,
        evaluation=evaluation,
        price_outcome=price_outcome,
    )
    row["bucket"] = classify_unclassified_bucket(row) if row.get("event_prototype") == "unclassified" else None
    row["core_explainability_key_count"] = sum(1 for key in CORE_EXPLAINABILITY_KEYS if key in explainability)
    row["metadata_keys"] = sorted(key for key in explainability if key not in CORE_EXPLAINABILITY_KEYS)
    row["root_cause"] = classify_missing_core_root_cause(
        {
            **row,
            "explainability_key_count": len(explainability),
            "core_explainability_key_count": row["core_explainability_key_count"],
        }
    )
    return row
```

- [ ] **Step 4: Add the comparison board, governance board, Markdown rendering, and CLI persistence**

```python
REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_5d_15pct_boundary_contract_inspection_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_5d_15pct_boundary_contract_inspection_latest.md"


def analyze_btst_5d_15pct_boundary_contract_inspection(reports_root: str | Path) -> dict[str, Any]:
    resolved_root = Path(reports_root).expanduser().resolve()
    rows: list[dict[str, Any]] = []
    price_cache: dict[tuple[str, str], Any] = {}
    for report_dir in discover_report_dirs([resolved_root], report_name_contains="paper_trading_window"):
        for snapshot in _iter_selection_snapshots(report_dir) or []:
            trade_date = _normalize_trade_date(snapshot.get("trade_date"))
            for ticker, evaluation in dict(snapshot.get("selection_targets") or {}).items():
                short_trade = dict((evaluation or {}).get("short_trade") or {})
                if not short_trade:
                    continue
                rows.append(
                    _build_boundary_row(
                        ticker=str(ticker),
                        trade_date=trade_date,
                        report_dir_name=report_dir.name,
                        evaluation=dict(evaluation or {}),
                        price_outcome=_extract_btst_price_outcome(str(ticker), trade_date, price_cache),
                    )
                )

    boundary_rows = [
        row for row in rows
        if row.get("root_cause") == "boundary_without_explainability"
        and row.get("candidate_source") in {"short_trade_boundary", "layer_b_boundary"}
    ]
    source_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in boundary_rows:
        source_groups[str(row.get("candidate_source") or "unknown")].append(row)

    source_comparison_board = []
    for source, group_rows in source_groups.items():
        summary = summarize_boundary_contract_group(group_rows)
        verdict = classify_boundary_contract_verdict(summary)
        source_comparison_board.append(
            {
                "candidate_source": source,
                **summary,
                "contract_verdict": verdict,
                "action": recommend_boundary_contract_action({"contract_verdict": verdict, **summary}),
            }
        )
    source_comparison_board.sort(key=lambda row: (int(row.get("row_count") or 0), str(row.get("candidate_source") or "")), reverse=True)
    governance_recommendation_board = [
        {
            "action": row["action"],
            "focus": row["candidate_source"],
            "reason": f"source {row['candidate_source']} has verdict {row['contract_verdict']}",
        }
        for row in source_comparison_board
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "reports_root": str(resolved_root),
        "row_count": len(rows),
        "boundary_row_count": len(boundary_rows),
        "source_comparison_board": source_comparison_board,
        "governance_recommendation_board": governance_recommendation_board,
    }
```

- [ ] **Step 5: Run the script test and verify it passes**

Run: `uv run pytest tests/test_analyze_btst_5d_15pct_boundary_contract_inspection_script.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the boundary inspection script**

```bash
git add tests/test_analyze_btst_5d_15pct_boundary_contract_inspection_script.py scripts/analyze_btst_5d_15pct_boundary_contract_inspection.py
git commit -m "feat: add boundary contract inspection analysis"
```

### Task 3: Generate live boundary artifacts and the Chinese note

**Files:**
- Reuse: `data/reports/btst_5d_15pct_boundary_contract_inspection_latest.json`
- Reuse: `data/reports/btst_5d_15pct_boundary_contract_inspection_latest.md`
- Create: `docs/prompt/find_actor_methord/btst-5d15-boundary-contract-inspection-2026-05-22.md`

- [ ] **Step 1: Run the new boundary inspection script on the current report corpus**

Run:

```bash
uv run python scripts/analyze_btst_5d_15pct_boundary_contract_inspection.py \
  --reports-root data/reports \
  --output-json data/reports/btst_5d_15pct_boundary_contract_inspection_latest.json \
  --output-md data/reports/btst_5d_15pct_boundary_contract_inspection_latest.md
```

Expected: the JSON and Markdown artifacts are created successfully and the Markdown file includes `source_comparison_board` plus `governance_recommendation_board`.

- [ ] **Step 2: Write the Chinese summary note from the live artifact**

```markdown
# btst-5d15-boundary-contract-inspection-2026-05-22

## 原理
- 本轮不是修整个系统，而是只检查 `short_trade_boundary` / `layer_b_boundary` 为什么只输出 metadata-only payload，却没有 round1 核心因子键。

## source comparison
- 说明两个 boundary source 的行数、决策构成、metadata key 形状与 contract verdict

## alpha 结论
- 说明这轮工作是清理研究面污染，不是新增 alpha

## beta 结论
- 说明是否更像 fixable contract gap，还是应当隔离该 boundary surface

## gamma 结论
- 只写 `fix_candidate_source_contract` / `quarantine_boundary_surface` / `hold_boundary_until_more_context`

## 下一轮动作
- 保持 fail-closed，不推进 runtime 集成
```

- [ ] **Step 3: Verify the live artifact and Chinese note agree**

Run:

```bash
rg -n "governance_recommendation_board|## gamma 结论|## 下一轮动作" \
  data/reports/btst_5d_15pct_boundary_contract_inspection_latest.md \
  docs/prompt/find_actor_methord/btst-5d15-boundary-contract-inspection-2026-05-22.md
```

Expected: both files expose the same boundary governance direction and keep the result at analysis level.

- [ ] **Step 4: Run the focused regression set**

Run:

```bash
uv run pytest tests/test_btst_boundary_contract_helpers.py tests/test_analyze_btst_5d_15pct_boundary_contract_inspection_script.py tests/test_btst_missing_core_features_noise_helpers.py tests/test_analyze_btst_5d_15pct_missing_core_features_noise_compression_script.py tests/test_btst_near_trend_threshold_recovery_helpers.py tests/test_analyze_btst_5d_15pct_near_trend_threshold_recovery_script.py tests/test_btst_round1_unclassified_split_helpers.py tests/test_analyze_btst_5d_15pct_unclassified_split_board_script.py tests/test_btst_round1_factor_mining_helpers.py tests/test_analyze_btst_5d_15pct_factor_research_round1_script.py tests/test_analyze_btst_5d_15pct_false_negative_diagnostic_board_script.py tests/test_analyze_btst_5d_15pct_false_negative_dossier_script.py tests/test_analyze_btst_5d_15pct_objective_monitor_script.py tests/test_analyze_btst_tplus1_tplus2_objective_monitor_script.py tests/test_btst_analysis_utils.py tests/backtesting/test_param_search.py tests/test_optimize_profile_script.py tests/backtesting/test_walk_forward.py tests/backtesting/test_compare.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the live artifact pack**

```bash
git add \
  data/reports/btst_5d_15pct_boundary_contract_inspection_latest.json \
  data/reports/btst_5d_15pct_boundary_contract_inspection_latest.md \
  docs/prompt/find_actor_methord/btst-5d15-boundary-contract-inspection-2026-05-22.md
git commit -m "docs: add boundary contract inspection artifacts"
```

## Self-Review Checklist

- Spec coverage:
  - isolate `boundary_without_explainability` only -> Task 1 + Task 2
  - compare `short_trade_boundary` vs `layer_b_boundary` contract shape -> Task 2
  - emit one governance recommendation board -> Task 2
  - produce live artifact plus Chinese fail-closed summary -> Task 3
- Placeholder scan:
  - no `TODO`, `TBD`, or deferred implementation markers
  - each code-changing step includes concrete code or an exact command
- Type consistency:
  - helper outputs use `contract_verdict` and governance `action`
  - script outputs use `source_comparison_board` and `governance_recommendation_board`
  - governance actions stay within `fix_candidate_source_contract`, `quarantine_boundary_surface`, and `hold_boundary_until_more_context`
