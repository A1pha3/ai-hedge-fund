# BTST 5D15 Missing-Core-Features Noise Compression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic missing-core-features noise-compression analysis cycle so the BTST 5D/+15% research surface can quarantine empty-payload noise before the next factor search.

**Architecture:** Reuse the existing round1 row rebuild plus unclassified bucket logic, then add a focused helper module for missing-core root-cause classification and compression actions. Build one analysis script that reconstructs the `missing_all_core_features` cohort, aggregates it into a root-cause board plus recommendation board, and then generate live artifacts with a Chinese interpretation note that stays at analysis/governance level.

**Tech Stack:** Python 3.12, pytest, existing BTST report/row rebuild helpers under `scripts/`, Markdown/JSON artifacts under `data/reports/` and `docs/prompt/find_actor_methord/`

---

## File Structure

- Reuse: `scripts/btst_round1_factor_mining_helpers.py`
  - keep using `build_round1_research_row()` so noise compression shares the same row contract as round1, split-board, and recovery analysis
- Reuse: `scripts/btst_round1_unclassified_split_helpers.py`
  - keep using `classify_unclassified_bucket()` so the new script filters exactly the current `missing_all_core_features` bucket
- Reuse: `scripts/btst_analysis_utils.py`
  - use the existing snapshot iteration, trade-date normalization, price-outcome extraction, and rounding helpers
- Create: `scripts/btst_missing_core_features_noise_helpers.py`
  - deterministic root-cause classification and per-row compression recommendations
- Create: `scripts/analyze_btst_5d_15pct_missing_core_features_noise_compression.py`
  - rebuild rows, isolate `missing_all_core_features`, aggregate root-cause summaries, and emit JSON/Markdown artifacts
- Create: `tests/test_btst_missing_core_features_noise_helpers.py`
  - unit coverage for root-cause classification and compression recommendation semantics
- Create: `tests/test_analyze_btst_5d_15pct_missing_core_features_noise_compression_script.py`
  - end-to-end script test with synthetic snapshots
- Create: `docs/prompt/find_actor_methord/btst-5d15-missing-core-features-noise-compression-2026-05-22.md`
  - Chinese summary of the live compression artifact, explicitly fail-closed and non-promotional

### Task 1: Add deterministic missing-core root-cause helpers

**Files:**
- Create: `scripts/btst_missing_core_features_noise_helpers.py`
- Test: `tests/test_btst_missing_core_features_noise_helpers.py`

- [ ] **Step 1: Write the failing helper tests**

```python
from scripts.btst_missing_core_features_noise_helpers import (
    classify_missing_core_root_cause,
    suggest_missing_core_compression_action,
)


def test_classify_missing_core_root_cause_marks_layer_c_watchlists_with_empty_payload_as_watchlist_noise() -> None:
    row = {
        "candidate_source": "layer_c_watchlist",
        "decision": "blocked",
        "explainability_key_count": 0,
        "has_short_trade": True,
    }

    assert classify_missing_core_root_cause(row) == "watchlist_empty_payload"


def test_classify_missing_core_root_cause_marks_boundary_rows_without_payload_as_contract_gap() -> None:
    row = {
        "candidate_source": "short_trade_boundary",
        "decision": "near_miss",
        "explainability_key_count": 0,
        "has_short_trade": True,
    }

    assert classify_missing_core_root_cause(row) == "boundary_without_explainability"


def test_suggest_missing_core_compression_action_inspects_boundary_contract_rows() -> None:
    row = {
        "root_cause": "boundary_without_explainability",
        "candidate_source": "short_trade_boundary",
        "decision": "near_miss",
    }

    assert suggest_missing_core_compression_action(row) == "inspect_candidate_source_contract"
```

- [ ] **Step 2: Run the helper tests and verify they fail**

Run: `uv run pytest tests/test_btst_missing_core_features_noise_helpers.py -q`

Expected: FAIL with `ModuleNotFoundError` or missing helper functions.

- [ ] **Step 3: Implement the helper module with narrow classification logic**

```python
from __future__ import annotations

from typing import Any


def classify_missing_core_root_cause(row: dict[str, Any]) -> str:
    candidate_source = str(row.get("candidate_source") or "")
    decision = str(row.get("decision") or "")
    explainability_key_count = int(row.get("explainability_key_count") or 0)
    if candidate_source == "layer_c_watchlist" and explainability_key_count == 0:
        return "watchlist_empty_payload"
    if candidate_source in {"short_trade_boundary", "layer_b_boundary"} and explainability_key_count == 0:
        return "boundary_without_explainability"
    if candidate_source == "watchlist_filter_diagnostics" and explainability_key_count == 0:
        return "diagnostic_probe_without_core_features"
    if decision == "blocked" and explainability_key_count == 0:
        return "blocked_before_factor_evaluation"
    return "unknown_missing_core_contract"


def suggest_missing_core_compression_action(row: dict[str, Any]) -> str:
    root_cause = str(row.get("root_cause") or classify_missing_core_root_cause(row))
    if root_cause == "watchlist_empty_payload":
        return "ignore_observation_noise"
    if root_cause == "boundary_without_explainability":
        return "inspect_candidate_source_contract"
    if root_cause == "diagnostic_probe_without_core_features":
        return "exclude_from_factor_surface"
    if root_cause == "blocked_before_factor_evaluation":
        return "hold_until_more_context"
    return "split_into_separate_research_surface"
```

- [ ] **Step 4: Run the helper tests and verify they pass**

Run: `uv run pytest tests/test_btst_missing_core_features_noise_helpers.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the helper layer**

```bash
git add tests/test_btst_missing_core_features_noise_helpers.py scripts/btst_missing_core_features_noise_helpers.py
git commit -m "feat: add missing-core noise helpers"
```

### Task 2: Add the missing-core-features compression analysis script

**Files:**
- Create: `scripts/analyze_btst_5d_15pct_missing_core_features_noise_compression.py`
- Test: `tests/test_analyze_btst_5d_15pct_missing_core_features_noise_compression_script.py`

- [ ] **Step 1: Write the failing end-to-end script test**

```python
from pathlib import Path

import scripts.analyze_btst_5d_15pct_missing_core_features_noise_compression as compression_script


def test_analyze_btst_5d_15pct_missing_core_features_noise_compression_builds_root_cause_and_recommendation_boards(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_window_20260323_20260326_missing_core"
    snapshot_dir = report_dir / "selection_artifacts" / "2026-03-24"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.joinpath("selection_snapshot.json").write_text(
        """
        {
          "trade_date": "20260324",
          "selection_targets": {
            "601600": {
              "candidate_source": "layer_c_watchlist",
              "short_trade": {
                "decision": "blocked",
                "explainability_payload": {}
              }
            },
            "001309": {
              "candidate_source": "short_trade_boundary",
              "short_trade": {
                "decision": "near_miss",
                "explainability_payload": {}
              }
            },
            "300111": {
              "candidate_source": "watchlist_filter_diagnostics",
              "short_trade": {
                "decision": "rejected",
                "explainability_payload": {}
              }
            }
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        compression_script,
        "_extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: {
            "cycle_status": "closed_cycle",
            "future_high_hit_15pct_2_5d": ticker == "300111",
            "max_future_high_return_2_5d": 0.16 if ticker == "300111" else 0.04,
            "next_open_return": 0.01,
        },
    )

    analysis = compression_script.analyze_btst_5d_15pct_missing_core_features_noise_compression(reports_root)

    assert analysis["missing_core_row_count"] == 3
    assert {row["root_cause"] for row in analysis["root_cause_board"]} == {
        "watchlist_empty_payload",
        "boundary_without_explainability",
        "diagnostic_probe_without_core_features",
    }
    assert any(row["action"] == "inspect_candidate_source_contract" for row in analysis["compression_recommendation_board"])
```

- [ ] **Step 2: Run the script test and verify it fails**

Run: `uv run pytest tests/test_analyze_btst_5d_15pct_missing_core_features_noise_compression_script.py -q`

Expected: FAIL because the script module does not exist yet.

- [ ] **Step 3: Implement the compression analysis script**

```python
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.btst_analysis_utils import (
    extract_btst_price_outcome as _extract_btst_price_outcome,
    iter_selection_snapshots as _iter_selection_snapshots,
    normalize_trade_date as _normalize_trade_date,
    round_or_none as _round_or_none,
)
from scripts.btst_missing_core_features_noise_helpers import (
    classify_missing_core_root_cause,
    suggest_missing_core_compression_action,
)
from scripts.btst_report_utils import discover_nested_report_dirs as discover_report_dirs
from scripts.btst_round1_factor_mining_helpers import build_round1_research_row
from scripts.btst_round1_unclassified_split_helpers import classify_unclassified_bucket


def _build_missing_core_row(*, ticker: str, trade_date: str, report_dir_name: str, evaluation: dict[str, Any], price_outcome: dict[str, Any]) -> dict[str, Any]:
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
    row["has_short_trade"] = bool(short_trade)
    row["explainability_key_count"] = len(explainability)
    row["payload_is_empty"] = len(explainability) == 0
    row["root_cause"] = classify_missing_core_root_cause(row)
    row["compression_action"] = suggest_missing_core_compression_action(row)
    return row


def _root_cause_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    decision_counts = Counter(str(row.get("decision") or "unknown") for row in rows)
    source_counts = Counter(str(row.get("candidate_source") or "unknown") for row in rows)
    closed_rows = [row for row in rows if row.get("gamma_closed_cycle")]
    hit_rows = [row for row in closed_rows if row.get("future_high_hit_15pct_2_5d") is True]
    return {
        "row_count": len(rows),
        "decision_counts": dict(decision_counts),
        "candidate_source_counts": dict(source_counts),
        "closed_cycle_count": len(closed_rows),
        "hit_rate_15pct": _round_or_none(len(hit_rows) / len(closed_rows)) if closed_rows else None,
        "mean_max_future_high_return_2_5d": _round_or_none(sum(float(row.get("max_future_high_return_2_5d") or 0.0) for row in closed_rows) / len(closed_rows)) if closed_rows else None,
        "payload_empty_count": sum(1 for row in rows if row.get("payload_is_empty")),
        "action": Counter(str(row.get("compression_action") or "hold_until_more_context") for row in rows).most_common(1)[0][0],
    }
```

- [ ] **Step 4: Add the main analysis, Markdown rendering, and CLI persistence**

```python
REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_5d_15pct_missing_core_features_noise_compression_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_5d_15pct_missing_core_features_noise_compression_latest.md"


def analyze_btst_5d_15pct_missing_core_features_noise_compression(reports_root: str | Path) -> dict[str, Any]:
    resolved_root = Path(reports_root).expanduser().resolve()
    report_dirs = discover_report_dirs([resolved_root], report_name_contains="paper_trading_window")
    price_cache: dict[tuple[str, str], Any] = {}
    rows: list[dict[str, Any]] = []
    for report_dir in report_dirs:
        for snapshot in _iter_selection_snapshots(report_dir) or []:
            trade_date = _normalize_trade_date(snapshot.get("trade_date"))
            for ticker, evaluation in dict(snapshot.get("selection_targets") or {}).items():
                short_trade = dict((evaluation or {}).get("short_trade") or {})
                if not short_trade:
                    continue
                rows.append(
                    _build_missing_core_row(
                        ticker=str(ticker),
                        trade_date=trade_date,
                        report_dir_name=report_dir.name,
                        evaluation=dict(evaluation or {}),
                        price_outcome=_extract_btst_price_outcome(str(ticker), trade_date, price_cache),
                    )
                )

    missing_core_rows = [row for row in rows if row.get("bucket") == "missing_all_core_features"]
    root_cause_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in missing_core_rows:
        root_cause_groups[str(row.get("root_cause") or "unknown_missing_core_contract")].append(row)

    root_cause_board = [{"root_cause": root_cause, **_root_cause_summary(group_rows)} for root_cause, group_rows in root_cause_groups.items()]
    root_cause_board.sort(key=lambda row: (int(row.get("row_count") or 0), str(row.get("root_cause") or "")), reverse=True)
    compression_recommendation_board = [
        {
            "action": row["action"],
            "focus": row["root_cause"],
            "reason": f"root_cause {row['root_cause']} has {row['row_count']} rows",
        }
        for row in root_cause_board
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "reports_root": str(resolved_root),
        "row_count": len(rows),
        "missing_core_row_count": len(missing_core_rows),
        "root_cause_board": root_cause_board,
        "compression_recommendation_board": compression_recommendation_board,
    }
```

- [ ] **Step 5: Run the script test and verify it passes**

Run: `uv run pytest tests/test_analyze_btst_5d_15pct_missing_core_features_noise_compression_script.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the compression analysis script**

```bash
git add tests/test_analyze_btst_5d_15pct_missing_core_features_noise_compression_script.py scripts/analyze_btst_5d_15pct_missing_core_features_noise_compression.py
git commit -m "feat: add missing-core noise compression analysis"
```

### Task 3: Generate live compression artifacts and the Chinese note

**Files:**
- Reuse: `data/reports/btst_5d_15pct_missing_core_features_noise_compression_latest.json`
- Reuse: `data/reports/btst_5d_15pct_missing_core_features_noise_compression_latest.md`
- Create: `docs/prompt/find_actor_methord/btst-5d15-missing-core-features-noise-compression-2026-05-22.md`

- [ ] **Step 1: Run the new compression script on the current report corpus**

Run:

```bash
uv run python scripts/analyze_btst_5d_15pct_missing_core_features_noise_compression.py \
  --reports-root data/reports \
  --output-json data/reports/btst_5d_15pct_missing_core_features_noise_compression_latest.json \
  --output-md data/reports/btst_5d_15pct_missing_core_features_noise_compression_latest.md
```

Expected: the JSON and Markdown artifacts are created successfully and the Markdown file includes `root_cause_board` plus `compression_recommendation_board`.

- [ ] **Step 2: Write the Chinese summary note from the live artifact**

```markdown
# btst-5d15-missing-core-features-noise-compression-2026-05-22

## 原理
- 本轮不是找新因子，而是压缩 `missing_all_core_features` 这类空 payload 噪声，避免它继续稀释 5D/+15% 研究面。

## 主要 root cause
- 说明最大的 2-3 个 root-cause 家族、行数、候选来源和决策构成

## alpha 结论
- 说明噪声压缩能否让后续研究面更干净，但不把它写成 alpha 提升结论

## beta 结论
- 说明哪些 candidate source / contract 需要检查，哪些只该视为观察噪声

## gamma 结论
- 只写治理动作，例如 `exclude_from_factor_surface`、`inspect_candidate_source_contract`

## 下一轮动作
- 保持 fail-closed，不推进 runtime 集成
```

- [ ] **Step 3: Verify the live artifact and Chinese note agree**

Run:

```bash
rg -n "compression_recommendation_board|## gamma 结论|## 下一轮动作" \
  data/reports/btst_5d_15pct_missing_core_features_noise_compression_latest.md \
  docs/prompt/find_actor_methord/btst-5d15-missing-core-features-noise-compression-2026-05-22.md
```

Expected: both files expose the same governance/compression direction and keep the result at analysis level.

- [ ] **Step 4: Run the focused regression set**

Run:

```bash
uv run pytest tests/test_btst_missing_core_features_noise_helpers.py tests/test_analyze_btst_5d_15pct_missing_core_features_noise_compression_script.py tests/test_btst_near_trend_threshold_recovery_helpers.py tests/test_analyze_btst_5d_15pct_near_trend_threshold_recovery_script.py tests/test_btst_round1_unclassified_split_helpers.py tests/test_analyze_btst_5d_15pct_unclassified_split_board_script.py tests/test_btst_round1_factor_mining_helpers.py tests/test_analyze_btst_5d_15pct_factor_research_round1_script.py tests/test_analyze_btst_5d_15pct_false_negative_diagnostic_board_script.py tests/test_analyze_btst_5d_15pct_false_negative_dossier_script.py tests/test_analyze_btst_5d_15pct_objective_monitor_script.py tests/test_analyze_btst_tplus1_tplus2_objective_monitor_script.py tests/test_btst_analysis_utils.py tests/backtesting/test_param_search.py tests/test_optimize_profile_script.py tests/backtesting/test_walk_forward.py tests/backtesting/test_compare.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the live artifact pack**

```bash
git add \
  data/reports/btst_5d_15pct_missing_core_features_noise_compression_latest.json \
  data/reports/btst_5d_15pct_missing_core_features_noise_compression_latest.md \
  docs/prompt/find_actor_methord/btst-5d15-missing-core-features-noise-compression-2026-05-22.md
git commit -m "docs: add missing-core noise compression artifacts"
```

## Self-Review Checklist

- Spec coverage:
  - isolate `missing_all_core_features` and explain dominant root causes -> Task 1 + Task 2
  - distinguish observation noise vs contract/routing pollution -> Task 1 + Task 2
  - emit governed compression board -> Task 2
  - produce live artifact plus Chinese fail-closed summary -> Task 3
- Placeholder scan:
  - no `TODO`, `TBD`, or deferred implementation markers
  - each code-changing step includes concrete code or an exact command
- Type consistency:
  - helper outputs use `root_cause` and `compression_action`
  - board outputs use `root_cause_board` and `compression_recommendation_board`
  - governance actions stay within `ignore_observation_noise`, `exclude_from_factor_surface`, `inspect_candidate_source_contract`, `split_into_separate_research_surface`, and `hold_until_more_context`
