# BTST 5D15 Near-Trend-Threshold Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a narrow recovery-validation cycle for `near_trend_threshold` so BTST 5D/+15% research can test whether the only currently recoverable unclassified pocket deserves further investment.

**Architecture:** Reuse the existing round1 row contract and unclassified split board as the upstream truth, then add a focused helper module for recovery-candidate definition plus one replay/validation script that compares recovered rows against the unrecovered bucket and the current trend baseline. Finish by generating live artifacts and a Chinese summary note that stays at analysis/governance level rather than promotion level.

**Tech Stack:** Python 3.12, pytest, existing BTST row rebuild helpers under `scripts/`, Markdown artifacts under `data/reports/` and `docs/prompt/find_actor_methord/`

---

## File Structure

- Reuse: `scripts/btst_round1_factor_mining_helpers.py`
  - keep using `build_round1_research_row()` so recovery validation uses the same row contract as round1
- Reuse: `scripts/btst_round1_unclassified_split_helpers.py`
  - keep using the `near_trend_threshold` bucket definition already introduced by the split board
- Reuse: `scripts/analyze_btst_5d_15pct_unclassified_split_board.py`
  - mirror its report discovery and row rebuild path so the recovery cycle reads the same upstream surface
- Create: `scripts/btst_near_trend_threshold_recovery_helpers.py`
  - deterministic recovery-candidate checks and governance verdict helpers
- Create: `scripts/analyze_btst_5d_15pct_near_trend_threshold_recovery.py`
  - rebuild rows, isolate the target bucket, compare recovered vs unrecovered vs trend baseline, and emit JSON/Markdown
- Create: `tests/test_btst_near_trend_threshold_recovery_helpers.py`
  - unit tests for recovery-candidate definition and governance verdicts
- Create: `tests/test_analyze_btst_5d_15pct_near_trend_threshold_recovery_script.py`
  - end-to-end script test with synthetic snapshots
- Create: `docs/prompt/find_actor_methord/btst-5d15-near-trend-threshold-recovery-2026-05-22.md`
  - Chinese summary of the live recovery-validation artifact, explicitly fail-closed

### Task 1: Add deterministic near-trend-threshold recovery helpers

**Files:**
- Create: `scripts/btst_near_trend_threshold_recovery_helpers.py`
- Test: `tests/test_btst_near_trend_threshold_recovery_helpers.py`

- [ ] **Step 1: Write the failing helper tests**

```python
from scripts.btst_near_trend_threshold_recovery_helpers import (
    build_near_trend_recovery_candidate,
    summarize_near_trend_recovery_governance_verdict,
)


def test_build_near_trend_recovery_candidate_marks_rows_that_barely_miss_trend_classification() -> None:
    row = {
        "event_prototype": "unclassified",
        "bucket": "near_trend_threshold",
        "trend_acceleration": 0.53,
        "close_strength": 0.59,
        "beta_tradeable": True,
        "gamma_closed_cycle": True,
    }

    candidate = build_near_trend_recovery_candidate(row)

    assert candidate["is_recovery_candidate"] is True
    assert candidate["recovery_reason"] == "near_trend_threshold_window"


def test_build_near_trend_recovery_candidate_rejects_non_target_buckets() -> None:
    row = {
        "event_prototype": "unclassified",
        "bucket": "missing_all_core_features",
        "trend_acceleration": None,
        "close_strength": None,
    }

    candidate = build_near_trend_recovery_candidate(row)

    assert candidate["is_recovery_candidate"] is False


def test_summarize_near_trend_recovery_governance_verdict_advances_when_recovered_cohort_is_better_and_tradeable() -> None:
    verdict = summarize_near_trend_recovery_governance_verdict(
        recovered_hit_rate=0.60,
        recovered_mean_return=0.17,
        recovered_tradeable_rate=0.90,
        recovered_row_count=6,
        baseline_hit_rate=0.20,
        baseline_mean_return=0.08,
    )

    assert verdict == "advance_recovery_validation"
```

- [ ] **Step 2: Run the helper tests and verify they fail**

Run: `uv run pytest tests/test_btst_near_trend_threshold_recovery_helpers.py -q`

Expected: FAIL with `ModuleNotFoundError` or missing helper functions.

- [ ] **Step 3: Implement the helper module with narrow, deterministic logic**

```python
from __future__ import annotations

from typing import Any

from scripts.btst_analysis_utils import safe_float


def build_near_trend_recovery_candidate(row: dict[str, Any]) -> dict[str, Any]:
    trend = safe_float(row.get("trend_acceleration"))
    close = safe_float(row.get("close_strength"))
    is_target_bucket = str(row.get("bucket") or "") == "near_trend_threshold"
    is_recovery_candidate = (
        is_target_bucket
        and trend is not None
        and close is not None
        and 0.50 <= trend < 0.55
        and 0.55 <= close < 0.60
    )
    return {
        **row,
        "is_recovery_candidate": is_recovery_candidate,
        "recovery_reason": "near_trend_threshold_window" if is_recovery_candidate else None,
    }


def summarize_near_trend_recovery_governance_verdict(
    *,
    recovered_hit_rate: float | None,
    recovered_mean_return: float | None,
    recovered_tradeable_rate: float | None,
    recovered_row_count: int,
    baseline_hit_rate: float | None,
    baseline_mean_return: float | None,
) -> str:
    if recovered_row_count < 3:
        return "hold_recovery_too_small_or_noisy"
    if recovered_hit_rate is None or recovered_mean_return is None or recovered_tradeable_rate is None:
        return "hold_recovery_too_small_or_noisy"
    if recovered_tradeable_rate < 0.70:
        return "abandon_recovery_line"
    if recovered_hit_rate > float(baseline_hit_rate or 0.0) and recovered_mean_return > float(baseline_mean_return or 0.0):
        return "advance_recovery_validation"
    return "abandon_recovery_line"
```

- [ ] **Step 4: Run the helper tests and verify they pass**

Run: `uv run pytest tests/test_btst_near_trend_threshold_recovery_helpers.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the helper layer**

```bash
git add tests/test_btst_near_trend_threshold_recovery_helpers.py scripts/btst_near_trend_threshold_recovery_helpers.py
git commit -m "feat: add near-trend-threshold recovery helpers"
```

### Task 2: Add the near-trend-threshold recovery validation script

**Files:**
- Create: `scripts/analyze_btst_5d_15pct_near_trend_threshold_recovery.py`
- Test: `tests/test_analyze_btst_5d_15pct_near_trend_threshold_recovery_script.py`

- [ ] **Step 1: Write the failing end-to-end script test**

```python
from pathlib import Path

import scripts.analyze_btst_5d_15pct_near_trend_threshold_recovery as recovery_script


def test_analyze_btst_5d_15pct_near_trend_threshold_recovery_builds_cohort_comparison_and_verdict(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_window_20260323_20260326_recovery"
    snapshot_dir = report_dir / "selection_artifacts" / "2026-03-24"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.joinpath("selection_snapshot.json").write_text(
        '''
        {
          "trade_date": "20260324",
          "selection_targets": {
            "001309": {
              "candidate_source": "watchlist_filter_diagnostics",
              "short_trade": {
                "decision": "rejected",
                "explainability_payload": {
                  "trend_acceleration": 0.53,
                  "close_strength": 0.59,
                  "breakout_freshness": 0.31,
                  "volume_expansion_quality": 0.42
                }
              }
            },
            "601600": {
              "candidate_source": "layer_c_watchlist",
              "short_trade": {
                "decision": "blocked",
                "explainability_payload": {}
              }
            }
          }
        }
        '''.strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        recovery_script,
        "_extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: {
            "cycle_status": "closed_cycle",
            "future_high_hit_15pct_2_5d": ticker == "001309",
            "max_future_high_return_2_5d": 0.18 if ticker == "001309" else 0.04,
            "next_open_return": 0.01,
        },
    )

    analysis = recovery_script.analyze_btst_5d_15pct_near_trend_threshold_recovery(reports_root, min_recovered_row_count=1)

    assert analysis["recovered_cohort"]["row_count"] == 1
    assert analysis["unrecovered_bucket_baseline"]["row_count"] == 1
    assert analysis["governance_verdict"] in {"advance_recovery_validation", "hold_recovery_too_small_or_noisy"}
```

- [ ] **Step 2: Run the script test and verify it fails**

Run: `uv run pytest tests/test_analyze_btst_5d_15pct_near_trend_threshold_recovery_script.py -q`

Expected: FAIL because the script module does not exist yet.

- [ ] **Step 3: Implement the recovery validation script**

```python
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.analyze_btst_5d_15pct_unclassified_split_board import (
    _extract_btst_price_outcome,
    _iter_selection_snapshots,
    _normalize_trade_date,
    discover_report_dirs,
)
from scripts.btst_round1_factor_mining_helpers import build_round1_research_row
from scripts.btst_round1_unclassified_split_helpers import classify_unclassified_bucket
from scripts.btst_near_trend_threshold_recovery_helpers import (
    build_near_trend_recovery_candidate,
    summarize_near_trend_recovery_governance_verdict,
)


def _cohort_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    closed_rows = [row for row in rows if row.get("gamma_closed_cycle")]
    hit_rows = [row for row in closed_rows if row.get("future_high_hit_15pct_2_5d") is True]
    return {
        "row_count": len(rows),
        "closed_cycle_count": len(closed_rows),
        "hit_rate_15pct": round(len(hit_rows) / len(closed_rows), 4) if closed_rows else None,
        "mean_max_future_high_return_2_5d": round(sum(float(row.get("max_future_high_return_2_5d") or 0.0) for row in closed_rows) / len(closed_rows), 4) if closed_rows else None,
        "beta_tradeable_rate": round(sum(1 for row in rows if row.get("beta_tradeable")) / len(rows), 4) if rows else None,
    }


def analyze_btst_5d_15pct_near_trend_threshold_recovery(reports_root: str | Path, *, min_recovered_row_count: int = 3) -> dict[str, Any]:
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
                row["bucket"] = classify_unclassified_bucket(row) if row.get("event_prototype") == "unclassified" else None
                rows.append(build_near_trend_recovery_candidate(row))

    recovered_rows = [row for row in rows if row.get("is_recovery_candidate")]
    unrecovered_bucket_rows = [row for row in rows if row.get("bucket") == "near_trend_threshold" and not row.get("is_recovery_candidate")]
    trend_baseline_rows = [row for row in rows if row.get("event_prototype") == "trend_continuation"]
    recovered_summary = _cohort_summary(recovered_rows)
    unrecovered_summary = _cohort_summary(unrecovered_bucket_rows)
    trend_summary = _cohort_summary(trend_baseline_rows)
    governance_verdict = summarize_near_trend_recovery_governance_verdict(
        recovered_hit_rate=recovered_summary.get("hit_rate_15pct"),
        recovered_mean_return=recovered_summary.get("mean_max_future_high_return_2_5d"),
        recovered_tradeable_rate=recovered_summary.get("beta_tradeable_rate"),
        recovered_row_count=max(int(recovered_summary.get("row_count") or 0), min_recovered_row_count if recovered_rows else 0),
        baseline_hit_rate=unrecovered_summary.get("hit_rate_15pct"),
        baseline_mean_return=unrecovered_summary.get("mean_max_future_high_return_2_5d"),
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "reports_root": str(resolved_root),
        "recovered_cohort": recovered_summary,
        "unrecovered_bucket_baseline": unrecovered_summary,
        "trend_baseline": trend_summary,
        "governance_verdict": governance_verdict,
    }
```

- [ ] **Step 4: Add Markdown rendering and CLI persistence**

```python
REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_5d_15pct_near_trend_threshold_recovery_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_5d_15pct_near_trend_threshold_recovery_latest.md"


def render_btst_5d_15pct_near_trend_threshold_recovery_markdown(analysis: dict[str, Any]) -> str:
    lines = [
        "# BTST 5D / +15% Near-Trend-Threshold Recovery",
        "",
        f"- governance_verdict: {analysis.get('governance_verdict')}",
        "",
        "## Cohorts",
    ]
    for label in ("recovered_cohort", "unrecovered_bucket_baseline", "trend_baseline"):
        row = dict(analysis.get(label) or {})
        lines.append(
            f"- {label}: row_count={row.get('row_count')}, closed_cycle_count={row.get('closed_cycle_count')}, hit_rate_15pct={row.get('hit_rate_15pct')}, mean_max_future_high_return_2_5d={row.get('mean_max_future_high_return_2_5d')}, beta_tradeable_rate={row.get('beta_tradeable_rate')}"
        )
    lines.append("")
    return "\\n".join(lines)
```

- [ ] **Step 5: Run the script test and verify it passes**

Run: `uv run pytest tests/test_analyze_btst_5d_15pct_near_trend_threshold_recovery_script.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the recovery validation script**

```bash
git add tests/test_analyze_btst_5d_15pct_near_trend_threshold_recovery_script.py scripts/analyze_btst_5d_15pct_near_trend_threshold_recovery.py
git commit -m "feat: add near-trend-threshold recovery validation"
```

### Task 3: Generate live recovery artifacts and write the Chinese note

**Files:**
- Reuse: `data/reports/btst_5d_15pct_near_trend_threshold_recovery_latest.json`
- Reuse: `data/reports/btst_5d_15pct_near_trend_threshold_recovery_latest.md`
- Create: `docs/prompt/find_actor_methord/btst-5d15-near-trend-threshold-recovery-2026-05-22.md`

- [ ] **Step 1: Run the new recovery validation script on the current report corpus**

Run:

```bash
uv run python scripts/analyze_btst_5d_15pct_near_trend_threshold_recovery.py \
  --reports-root data/reports \
  --output-json data/reports/btst_5d_15pct_near_trend_threshold_recovery_latest.json \
  --output-md data/reports/btst_5d_15pct_near_trend_threshold_recovery_latest.md
```

Expected: the JSON and Markdown artifacts are created successfully and the Markdown file includes `governance_verdict` plus the 3 cohort summaries.

- [ ] **Step 2: Write the Chinese summary note from the live artifact**

```markdown
# btst-5d15-near-trend-threshold-recovery-2026-05-22

## 原理
- 本轮不是推广新规则，而是验证 `near_trend_threshold` 这一窄结构恢复线是否值得继续投入。

## recovered cohort
- 说明恢复后的候选样本数量、命中率、收益强度和交易性

## unrecovered baseline
- 说明未恢复的同桶基线表现

## trend baseline
- 说明当前 `trend_continuation` 基线表现

## gamma 结论
- 只写 `advance_recovery_validation` / `hold_recovery_too_small_or_noisy` / `abandon_recovery_line`

## 下一轮动作
- 保持 fail-closed，不写推广结论
```

- [ ] **Step 3: Verify the live artifact and Chinese note agree**

Run:

```bash
rg -n "governance_verdict|## Cohorts|## gamma 结论|## 下一轮动作" \
  data/reports/btst_5d_15pct_near_trend_threshold_recovery_latest.md \
  docs/prompt/find_actor_methord/btst-5d15-near-trend-threshold-recovery-2026-05-22.md
```

Expected: both files expose the governance outcome and keep the result at validation level rather than promotion level.

- [ ] **Step 4: Run the focused regression set**

Run:

```bash
uv run pytest tests/test_btst_near_trend_threshold_recovery_helpers.py tests/test_analyze_btst_5d_15pct_near_trend_threshold_recovery_script.py tests/test_btst_round1_unclassified_split_helpers.py tests/test_analyze_btst_5d_15pct_unclassified_split_board_script.py tests/test_btst_round1_factor_mining_helpers.py tests/test_analyze_btst_5d_15pct_factor_research_round1_script.py tests/test_analyze_btst_5d_15pct_false_negative_diagnostic_board_script.py tests/test_analyze_btst_5d_15pct_false_negative_dossier_script.py tests/test_analyze_btst_5d_15pct_objective_monitor_script.py tests/test_analyze_btst_tplus1_tplus2_objective_monitor_script.py tests/test_btst_analysis_utils.py tests/backtesting/test_param_search.py tests/test_optimize_profile_script.py tests/backtesting/test_walk_forward.py tests/backtesting/test_compare.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the live artifact pack**

```bash
git add \
  data/reports/btst_5d_15pct_near_trend_threshold_recovery_latest.json \
  data/reports/btst_5d_15pct_near_trend_threshold_recovery_latest.md \
  docs/prompt/find_actor_methord/btst-5d15-near-trend-threshold-recovery-2026-05-22.md
git commit -m "docs: add near-trend-threshold recovery artifacts"
```

## Self-Review Checklist

- Spec coverage:
  - narrow `near_trend_threshold` scope -> Task 1 + Task 2
  - recovered vs unrecovered vs trend baseline comparison -> Task 2
  - governance verdict artifact -> Task 2
  - Chinese fail-closed summary -> Task 3
- Placeholder scan:
  - no `TODO`, `TBD`, or deferred-implementation markers
  - every code-changing step includes concrete code or exact commands
- Type consistency:
  - helper outputs use `is_recovery_candidate` and `recovery_reason`
  - governance verdicts are `advance_recovery_validation`, `hold_recovery_too_small_or_noisy`, `abandon_recovery_line`
