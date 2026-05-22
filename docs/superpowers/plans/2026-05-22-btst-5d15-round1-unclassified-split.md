# BTST 5D15 Round1 Unclassified Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the round1 `unclassified` split board so BTST 5D/+15% research can separate missing-feature noise from recoverable near-threshold structure and choose the next validation cycle from evidence instead of guesswork.

**Architecture:** Keep the current round1 aggregate contract stable and add a standalone split-analysis layer that rebuilds row-level round1 data from report snapshots using existing helpers. The implementation is split into a small helper module for deterministic bucket/recoverability logic, one analysis script that emits JSON + Markdown artifacts, and one Chinese summary doc that records the live result without promoting any factor.

**Tech Stack:** Python 3.12, pytest, existing `scripts/` BTST analysis helpers, Markdown artifacts under `data/reports/` and `docs/prompt/find_actor_methord/`

---

## File Structure

- Reuse: `scripts/btst_round1_factor_mining_helpers.py`
  - keep using `build_round1_research_row()` so bucket analysis sees the same row contract as round1
- Reuse: `scripts/analyze_btst_5d_15pct_factor_research_round1.py`
  - mirror its report discovery, row rebuild, and JSON/Markdown persistence patterns
- Create: `scripts/btst_round1_unclassified_split_helpers.py`
  - deterministic bucket classification and recoverability verdict helpers for `event_prototype == "unclassified"` rows
- Create: `scripts/analyze_btst_5d_15pct_unclassified_split_board.py`
  - rebuild round1 rows, filter `unclassified`, aggregate split-board metrics, emit recovery recommendation board
- Create: `tests/test_btst_round1_unclassified_split_helpers.py`
  - unit tests for bucket assignment and recoverability logic
- Create: `tests/test_analyze_btst_5d_15pct_unclassified_split_board_script.py`
  - end-to-end script test with synthetic snapshots
- Create: `docs/prompt/find_actor_methord/btst-5d15pct-unclassified-split-board-2026-05-22.md`
  - Chinese summary of the live split-board artifact, explicitly non-promotional

### Task 1: Add deterministic unclassified bucket and recoverability helpers

**Files:**
- Create: `scripts/btst_round1_unclassified_split_helpers.py`
- Test: `tests/test_btst_round1_unclassified_split_helpers.py`

- [ ] **Step 1: Write the failing helper tests**

```python
from scripts.btst_round1_unclassified_split_helpers import (
    classify_unclassified_bucket,
    summarize_unclassified_recoverability,
)


def test_classify_unclassified_bucket_marks_rows_with_no_round1_features_as_missing_all_core_features() -> None:
    row = {
        "event_prototype": "unclassified",
        "breakout_freshness": None,
        "trend_acceleration": None,
        "volume_expansion_quality": None,
        "close_strength": None,
        "candidate_source": "layer_c_watchlist",
        "decision": "blocked",
    }

    assert classify_unclassified_bucket(row) == "missing_all_core_features"


def test_classify_unclassified_bucket_marks_rows_near_trend_threshold() -> None:
    row = {
        "event_prototype": "unclassified",
        "trend_acceleration": 0.53,
        "close_strength": 0.59,
        "breakout_freshness": 0.31,
        "volume_expansion_quality": 0.42,
        "candidate_source": "short_trade_boundary",
        "decision": "near_miss",
    }

    assert classify_unclassified_bucket(row) == "near_trend_threshold"


def test_summarize_unclassified_recoverability_flags_near_threshold_rows_as_recoverable() -> None:
    row = {
        "bucket": "near_breakout_threshold",
        "future_high_hit_15pct_2_5d": True,
        "max_future_high_return_2_5d": 0.16,
        "beta_tradeable": True,
        "gamma_closed_cycle": True,
    }

    verdict = summarize_unclassified_recoverability(row)

    assert verdict == "recover_threshold_near_miss"
```

- [ ] **Step 2: Run the helper tests and verify they fail**

Run: `uv run pytest tests/test_btst_round1_unclassified_split_helpers.py -q`

Expected: FAIL with `ModuleNotFoundError` or missing helper functions.

- [ ] **Step 3: Implement the helper module with minimal deterministic logic**

```python
from __future__ import annotations

from typing import Any

from scripts.btst_analysis_utils import safe_float


def classify_unclassified_bucket(row: dict[str, Any]) -> str:
    breakout = safe_float(row.get("breakout_freshness"))
    trend = safe_float(row.get("trend_acceleration"))
    volume = safe_float(row.get("volume_expansion_quality"))
    close = safe_float(row.get("close_strength"))
    candidate_source = str(row.get("candidate_source") or "")
    decision = str(row.get("decision") or "")

    if all(value is None for value in (breakout, trend, volume, close)):
        return "missing_all_core_features"
    if breakout is None and trend is not None and close is not None:
        return "missing_breakout_inputs_only"
    if trend is None and breakout is not None and volume is not None:
        return "missing_trend_inputs_only"
    if trend is not None and close is not None and 0.5 <= trend < 0.55 and 0.55 <= close < 0.60:
        return "near_trend_threshold"
    if breakout is not None and volume is not None and 0.5 <= breakout < 0.55 and 0.5 <= volume < 0.55:
        return "near_breakout_threshold"
    if decision == "blocked":
        return "blocked_before_structure_matures"
    if candidate_source == "layer_c_watchlist":
        return "watchlist_only_low_signal"
    return "other_unclassified"


def summarize_unclassified_recoverability(row: dict[str, Any]) -> str:
    bucket = str(row.get("bucket") or "")
    if bucket in {"near_trend_threshold", "near_breakout_threshold"}:
        return "recover_threshold_near_miss"
    if bucket in {"missing_breakout_inputs_only", "missing_trend_inputs_only"}:
        return "inspect_candidate_source_contract"
    if bucket == "blocked_before_structure_matures":
        return "revisit_blocker_family"
    return "ignore_noise"
```

- [ ] **Step 4: Run the helper tests and verify they pass**

Run: `uv run pytest tests/test_btst_round1_unclassified_split_helpers.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the helper layer**

```bash
git add tests/test_btst_round1_unclassified_split_helpers.py scripts/btst_round1_unclassified_split_helpers.py
git commit -m "feat: add BTST round1 unclassified split helpers"
```

### Task 2: Add the unclassified split board analysis script

**Files:**
- Create: `scripts/analyze_btst_5d_15pct_unclassified_split_board.py`
- Test: `tests/test_analyze_btst_5d_15pct_unclassified_split_board_script.py`

- [ ] **Step 1: Write the failing end-to-end script test**

```python
from pathlib import Path

import scripts.analyze_btst_5d_15pct_unclassified_split_board as split_script


def test_analyze_btst_5d_15pct_unclassified_split_board_builds_bucket_and_recommendation_boards(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_window_20260323_20260326_unclassified"
    snapshot_dir = report_dir / "selection_artifacts" / "2026-03-24"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.joinpath("selection_snapshot.json").write_text(
        '''
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
                "explainability_payload": {
                  "trend_acceleration": 0.53,
                  "close_strength": 0.59,
                  "breakout_freshness": 0.31,
                  "volume_expansion_quality": 0.42
                }
              }
            }
          }
        }
        '''.strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        split_script,
        "_extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: {
            "cycle_status": "closed_cycle",
            "future_high_hit_15pct_2_5d": ticker == "001309",
            "max_future_high_return_2_5d": 0.16 if ticker == "001309" else 0.04,
            "next_open_return": 0.01,
        },
    )

    analysis = split_script.analyze_btst_5d_15pct_unclassified_split_board(reports_root)

    assert analysis["row_count"] == 2
    assert analysis["unclassified_row_count"] == 2
    assert analysis["bucket_board"][0]["bucket"] == "near_trend_threshold"
    assert analysis["recommendation_board"][0]["action"] == "recover_threshold_near_miss"
```

- [ ] **Step 2: Run the script test and verify it fails**

Run: `uv run pytest tests/test_analyze_btst_5d_15pct_unclassified_split_board_script.py -q`

Expected: FAIL because the script module does not exist yet.

- [ ] **Step 3: Implement the split board script using existing round1 row rebuild patterns**

```python
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.analyze_btst_5d_15pct_factor_research_round1 import (
    _extract_btst_price_outcome,
    _iter_selection_snapshots,
    _normalize_trade_date,
    discover_report_dirs,
)
from scripts.btst_round1_factor_mining_helpers import build_round1_research_row
from scripts.btst_round1_unclassified_split_helpers import (
    classify_unclassified_bucket,
    summarize_unclassified_recoverability,
)


def analyze_btst_5d_15pct_unclassified_split_board(reports_root: str | Path) -> dict[str, Any]:
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
                row = build_round1_research_row(
                    ticker=str(ticker),
                    trade_date=trade_date,
                    report_dir_name=report_dir.name,
                    evaluation=dict(evaluation or {}),
                    price_outcome=_extract_btst_price_outcome(str(ticker), trade_date, price_cache),
                )
                rows.append(row)

    unclassified_rows = [row for row in rows if row.get("event_prototype") == "unclassified"]
    for row in unclassified_rows:
        row["bucket"] = classify_unclassified_bucket(row)
        row["recoverability_verdict"] = summarize_unclassified_recoverability(row)

    bucket_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in unclassified_rows:
        bucket_groups[str(row.get("bucket") or "other_unclassified")].append(row)

    bucket_board = []
    for bucket, group_rows in bucket_groups.items():
        decision_counts = Counter(str(row.get("decision") or "unknown") for row in group_rows)
        source_counts = Counter(str(row.get("candidate_source") or "unknown") for row in group_rows)
        bucket_board.append(
            {
                "bucket": bucket,
                "row_count": len(group_rows),
                "decision_counts": dict(decision_counts),
                "candidate_source_counts": dict(source_counts),
                "recoverability_verdict": Counter(str(row.get("recoverability_verdict") or "ignore_noise") for row in group_rows).most_common(1)[0][0],
            }
        )

    recommendation_board = [
        {
            "action": row["recoverability_verdict"],
            "focus": row["bucket"],
            "reason": f"bucket {row['bucket']} has {row['row_count']} rows",
        }
        for row in sorted(bucket_board, key=lambda item: (item["recoverability_verdict"] != "recover_threshold_near_miss", -item["row_count"], item["bucket"]))
    ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "reports_root": str(resolved_root),
        "row_count": len(rows),
        "unclassified_row_count": len(unclassified_rows),
        "bucket_board": bucket_board,
        "recommendation_board": recommendation_board,
    }
```

- [ ] **Step 4: Add Markdown rendering and CLI persistence**

```python
REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_5d_15pct_unclassified_split_board_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_5d_15pct_unclassified_split_board_latest.md"


def render_btst_5d_15pct_unclassified_split_board_markdown(analysis: dict[str, Any]) -> str:
    lines = [
        "# BTST 5D / +15% Unclassified Split Board",
        "",
        f"- row_count: {analysis.get('row_count')}",
        f"- unclassified_row_count: {analysis.get('unclassified_row_count')}",
        "",
        "## Bucket Board",
    ]
    for row in list(analysis.get("bucket_board") or []):
        lines.append(
            f"- {row.get('bucket')}: row_count={row.get('row_count')}, decision_counts={row.get('decision_counts')}, candidate_source_counts={row.get('candidate_source_counts')}, recoverability_verdict={row.get('recoverability_verdict')}"
        )
    if not list(analysis.get("bucket_board") or []):
        lines.append("- none")
    lines.extend(["", "## Recommendation Board"])
    for row in list(analysis.get("recommendation_board") or []):
        lines.append(f"- {row.get('action')}: focus={row.get('focus')}, reason={row.get('reason')}")
    if not list(analysis.get("recommendation_board") or []):
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 5: Run the script test and verify it passes**

Run: `uv run pytest tests/test_analyze_btst_5d_15pct_unclassified_split_board_script.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the split board script**

```bash
git add tests/test_analyze_btst_5d_15pct_unclassified_split_board_script.py scripts/analyze_btst_5d_15pct_unclassified_split_board.py
git commit -m "feat: add BTST 5D15 unclassified split board"
```

### Task 3: Generate live artifacts and write the Chinese summary note

**Files:**
- Reuse: `data/reports/btst_5d_15pct_unclassified_split_board_latest.json`
- Reuse: `data/reports/btst_5d_15pct_unclassified_split_board_latest.md`
- Create: `docs/prompt/find_actor_methord/btst-5d15pct-unclassified-split-board-2026-05-22.md`

- [ ] **Step 1: Run the new split board script on the current report corpus**

Run:

```bash
uv run python scripts/analyze_btst_5d_15pct_unclassified_split_board.py \
  --reports-root data/reports \
  --output-json data/reports/btst_5d_15pct_unclassified_split_board_latest.json \
  --output-md data/reports/btst_5d_15pct_unclassified_split_board_latest.md
```

Expected: the JSON and Markdown artifacts are created successfully and the Markdown file contains `## Bucket Board` and `## Recommendation Board`.

- [ ] **Step 2: Write the Chinese summary doc from the live artifact**

```markdown
# btst-5d15pct-unclassified-split-board-2026-05-22

## 原理
- 本轮不是升级因子，而是拆开 round1 里的 `unclassified` 大样本，判断噪声与可恢复结构分别占多少。

## 主要桶
- 缺失特征桶
- 近阈值桶
- blocker / watchlist 主导桶

## alpha 结论
- 哪些桶只是噪声，哪些桶更接近 5D/+15% 目标

## beta 结论
- 说明交易性是否仍然不是主要矛盾

## gamma 结论
- 说明下一轮应该先做结构恢复还是继续精炼 trend/breakout

## 下一轮动作
- 只写 split board 给出的主建议，不写额外推广结论
```

- [ ] **Step 3: Verify the generated artifact and Chinese note agree on the recommendation**

Run:

```bash
rg -n "## Bucket Board|## Recommendation Board|## alpha 结论|## beta 结论|## gamma 结论|## 下一轮动作" \
  data/reports/btst_5d_15pct_unclassified_split_board_latest.md \
  docs/prompt/find_actor_methord/btst-5d15pct-unclassified-split-board-2026-05-22.md
```

Expected: both files contain the recommendation-oriented sections and the Chinese note keeps the result at analysis / routing level, not promotion level.

- [ ] **Step 4: Run the focused regression set**

Run:

```bash
uv run pytest tests/test_btst_round1_unclassified_split_helpers.py tests/test_analyze_btst_5d_15pct_unclassified_split_board_script.py tests/test_btst_round1_factor_mining_helpers.py tests/test_analyze_btst_5d_15pct_factor_research_round1_script.py tests/test_analyze_btst_5d_15pct_false_negative_diagnostic_board_script.py tests/test_analyze_btst_5d_15pct_false_negative_dossier_script.py tests/test_analyze_btst_5d_15pct_objective_monitor_script.py tests/test_analyze_btst_tplus1_tplus2_objective_monitor_script.py tests/test_btst_analysis_utils.py tests/backtesting/test_param_search.py tests/test_optimize_profile_script.py tests/backtesting/test_walk_forward.py tests/backtesting/test_compare.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the live artifact pack**

```bash
git add \
  data/reports/btst_5d_15pct_unclassified_split_board_latest.json \
  data/reports/btst_5d_15pct_unclassified_split_board_latest.md \
  docs/prompt/find_actor_methord/btst-5d15pct-unclassified-split-board-2026-05-22.md
git commit -m "docs: add BTST 5D15 unclassified split board artifacts"
```

## Self-Review Checklist

- Spec coverage:
  - `unclassified` split-first direction -> Task 1 + Task 2
  - deterministic bucket classifier -> Task 1
  - split leaderboard artifact -> Task 2
  - recovery recommendation board -> Task 2
  - Chinese non-promotional summary -> Task 3
- Placeholder scan:
  - no `TODO`, `TBD`, or deferred implementation markers
  - every code-changing step includes concrete code or command content
- Type consistency:
  - bucket names are `missing_all_core_features`, `missing_breakout_inputs_only`, `missing_trend_inputs_only`, `near_trend_threshold`, `near_breakout_threshold`, `blocked_before_structure_matures`, `watchlist_only_low_signal`, `other_unclassified`
  - recommendation actions are `ignore_noise`, `recover_threshold_near_miss`, `inspect_candidate_source_contract`, `revisit_blocker_family`, `advance_trend_breakout_refinement`
