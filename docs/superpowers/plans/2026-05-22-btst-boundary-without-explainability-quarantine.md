# BTST Boundary-Without-Explainability Quarantine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fail-closed quarantine artifact for the 121-row `boundary_without_explainability` cohort and make round1 factor research consume that artifact so the noise bucket stops polluting the factor surface.

**Architecture:** Reuse the existing `boundary_contract_inspection` output instead of inventing a second inspection path. Add a small row-classification helper, a boundary-quarantine analysis script that emits deterministic `allow / quarantine / separate_surface` outputs plus governance boards, then let `analyze_btst_5d_15pct_factor_research_round1.py` consume that artifact when present. Keep alpha math, backtest labels, and fill-path behavior unchanged.

**Tech Stack:** Python 3.12, argparse/json/pathlib, existing BTST script helpers, pytest.

---

### Task 1: Build the row-level quarantine helper

**Files:**
- Create: `scripts/btst_boundary_quarantine_helpers.py`
- Test: `tests/test_btst_boundary_quarantine_helpers.py`

- [ ] **Step 1: Write the failing helper tests**

Create `tests/test_btst_boundary_quarantine_helpers.py` with:

```python
from scripts.btst_boundary_quarantine_helpers import (
    classify_boundary_quarantine_decision,
    is_boundary_without_explainability_target,
    summarize_boundary_quarantine_rows,
)


def test_is_boundary_without_explainability_target_accepts_only_target_bucket() -> None:
    assert is_boundary_without_explainability_target(
        {
            "root_cause": "boundary_without_explainability",
            "bucket": "missing_all_core_features",
            "candidate_source": "short_trade_boundary",
        }
    ) is True
    assert is_boundary_without_explainability_target(
        {
            "root_cause": "diagnostic_probe_without_core_features",
            "bucket": "missing_all_core_features",
            "candidate_source": "watchlist_filter_diagnostics",
        }
    ) is False


def test_classify_boundary_quarantine_decision_marks_target_rows_quarantine() -> None:
    decision = classify_boundary_quarantine_decision(
        {
            "ticker": "001309",
            "candidate_source": "short_trade_boundary",
            "root_cause": "boundary_without_explainability",
            "bucket": "missing_all_core_features",
            "boundary_context": {"t0_tail_strength": 0.61},
        }
    )

    assert decision["research_surface_disposition"] == "quarantine"
    assert decision["governance_action"] == "inspect_candidate_source_contract"
    assert decision["factor_surface_allowed"] is False


def test_classify_boundary_quarantine_decision_fails_closed_for_ambiguous_rows() -> None:
    decision = classify_boundary_quarantine_decision(
        {
            "ticker": "300111",
            "candidate_source": "",
            "root_cause": "boundary_without_explainability",
            "bucket": "missing_all_core_features",
            "boundary_context": {},
        }
    )

    assert decision["research_surface_disposition"] == "separate_surface"
    assert decision["governance_action"] == "split_into_separate_research_surface"
    assert decision["factor_surface_allowed"] is False


def test_summarize_boundary_quarantine_rows_builds_disposition_counts() -> None:
    summary = summarize_boundary_quarantine_rows(
        [
            {"candidate_source": "short_trade_boundary", "research_surface_disposition": "quarantine", "governance_action": "inspect_candidate_source_contract"},
            {"candidate_source": "layer_b_boundary", "research_surface_disposition": "quarantine", "governance_action": "inspect_candidate_source_contract"},
            {"candidate_source": "layer_b_boundary", "research_surface_disposition": "separate_surface", "governance_action": "split_into_separate_research_surface"},
        ]
    )

    assert summary["disposition_counts"] == {
        "allow": 0,
        "quarantine": 2,
        "separate_surface": 1,
    }
    assert summary["source_summary_board"][0]["candidate_source"] == "layer_b_boundary"
```

- [ ] **Step 2: Run the helper tests and verify they fail**

Run:

```bash
uv run pytest tests/test_btst_boundary_quarantine_helpers.py -q
```

Expected: `FAIL` with import errors because `scripts/btst_boundary_quarantine_helpers.py` does not exist yet.

- [ ] **Step 3: Write the minimal helper implementation**

Create `scripts/btst_boundary_quarantine_helpers.py`:

```python
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from scripts.btst_missing_core_features_noise_helpers import suggest_missing_core_compression_action

TARGET_BOUNDARY_SOURCES = {"short_trade_boundary", "layer_b_boundary"}


def is_boundary_without_explainability_target(row: dict[str, Any]) -> bool:
    return (
        str(row.get("root_cause") or "") == "boundary_without_explainability"
        and str(row.get("bucket") or "") == "missing_all_core_features"
        and str(row.get("candidate_source") or "") in TARGET_BOUNDARY_SOURCES
    )


def classify_boundary_quarantine_decision(row: dict[str, Any]) -> dict[str, Any]:
    governance_action = suggest_missing_core_compression_action(row)
    candidate_source = str(row.get("candidate_source") or "")
    boundary_context = dict(row.get("boundary_context") or {})

    if not candidate_source or not is_boundary_without_explainability_target(row):
        disposition = "separate_surface"
        governance_action = "split_into_separate_research_surface"
    elif not boundary_context:
        disposition = "separate_surface"
        governance_action = "split_into_separate_research_surface"
    elif governance_action == "inspect_candidate_source_contract":
        disposition = "quarantine"
    else:
        disposition = "separate_surface"

    return {
        **row,
        "governance_action": governance_action,
        "research_surface_disposition": disposition,
        "factor_surface_allowed": disposition == "allow",
    }


def summarize_boundary_quarantine_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    disposition_counts = Counter(str(row.get("research_surface_disposition") or "unknown") for row in rows)
    source_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        source_groups[str(row.get("candidate_source") or "unknown")].append(row)

    source_summary_board = []
    for candidate_source, source_rows in source_groups.items():
        source_summary_board.append(
            {
                "candidate_source": candidate_source,
                "row_count": len(source_rows),
                "quarantine_count": sum(1 for row in source_rows if row.get("research_surface_disposition") == "quarantine"),
                "separate_surface_count": sum(1 for row in source_rows if row.get("research_surface_disposition") == "separate_surface"),
                "allow_count": sum(1 for row in source_rows if row.get("research_surface_disposition") == "allow"),
            }
        )
    source_summary_board.sort(key=lambda row: (-int(row["row_count"]), str(row["candidate_source"])))

    return {
        "disposition_counts": {
            "allow": disposition_counts.get("allow", 0),
            "quarantine": disposition_counts.get("quarantine", 0),
            "separate_surface": disposition_counts.get("separate_surface", 0),
        },
        "source_summary_board": source_summary_board,
    }
```

- [ ] **Step 4: Run the helper tests and verify they pass**

Run:

```bash
uv run pytest tests/test_btst_boundary_quarantine_helpers.py -q
```

Expected: `4 passed`.

- [ ] **Step 5: Commit the helper**

Run:

```bash
git add scripts/btst_boundary_quarantine_helpers.py tests/test_btst_boundary_quarantine_helpers.py
git commit -m "feat: add boundary quarantine helper"
```

### Task 2: Build the boundary quarantine artifact script

**Files:**
- Create: `scripts/analyze_btst_5d_15pct_boundary_quarantine.py`
- Modify: `scripts/analyze_btst_5d_15pct_boundary_contract_inspection.py:79-119` (reference only; do not change unless needed for import compatibility)
- Test: `tests/test_analyze_btst_5d_15pct_boundary_quarantine_script.py`

- [ ] **Step 1: Write the failing script tests**

Create `tests/test_analyze_btst_5d_15pct_boundary_quarantine_script.py`:

```python
from pathlib import Path

import scripts.analyze_btst_5d_15pct_boundary_quarantine as quarantine_script


def test_analyze_btst_5d_15pct_boundary_quarantine_builds_boards_and_surface_lists(tmp_path: Path, monkeypatch) -> None:
    captured_rows = [
        {
            "ticker": "001309",
            "candidate_source": "short_trade_boundary",
            "root_cause": "boundary_without_explainability",
            "bucket": "missing_all_core_features",
            "boundary_context": {"t0_tail_strength": 0.61},
        },
        {
            "ticker": "300111",
            "candidate_source": "layer_b_boundary",
            "root_cause": "boundary_without_explainability",
            "bucket": "missing_all_core_features",
            "boundary_context": {},
        },
    ]

    monkeypatch.setattr(
        quarantine_script,
        "analyze_btst_5d_15pct_boundary_contract_inspection",
        lambda reports_root: {
            "generated_at": "2026-05-22T00:00:00Z",
            "reports_root": str(reports_root),
            "row_count": 2,
            "boundary_row_count": 2,
            "boundary_rows": captured_rows,
            "source_comparison_board": [],
            "governance_recommendation_board": [],
        },
    )

    analysis = quarantine_script.analyze_btst_5d_15pct_boundary_quarantine(tmp_path / "data" / "reports")

    assert analysis["boundary_row_count"] == 2
    assert analysis["research_surface_lists"] == {
        "allow": [],
        "quarantine": ["001309"],
        "separate_surface": ["300111"],
    }
    assert analysis["governance_decision_board"] == [
        {
            "action": "inspect_candidate_source_contract",
            "row_count": 1,
            "tickers": ["001309"],
        },
        {
            "action": "split_into_separate_research_surface",
            "row_count": 1,
            "tickers": ["300111"],
        },
    ]


def test_analyze_btst_5d_15pct_boundary_quarantine_handles_zero_rows() -> None:
    analysis = quarantine_script.analyze_btst_5d_15pct_boundary_quarantine_from_rows([])

    assert analysis["boundary_row_count"] == 0
    assert analysis["decision_rows"] == []
    assert analysis["research_surface_lists"] == {
        "allow": [],
        "quarantine": [],
        "separate_surface": [],
    }


def test_render_btst_5d_15pct_boundary_quarantine_markdown_includes_surface_lists() -> None:
    markdown = quarantine_script.render_btst_5d_15pct_boundary_quarantine_markdown(
        {
            "boundary_row_count": 1,
            "disposition_summary_board": [{"allow_count": 0, "quarantine_count": 1, "separate_surface_count": 0}],
            "source_summary_board": [{"candidate_source": "short_trade_boundary", "row_count": 1, "quarantine_count": 1, "separate_surface_count": 0, "allow_count": 0}],
            "governance_decision_board": [{"action": "inspect_candidate_source_contract", "row_count": 1, "tickers": ["001309"]}],
            "research_surface_lists": {"allow": [], "quarantine": ["001309"], "separate_surface": []},
        }
    )

    assert "## research_surface_lists" in markdown
    assert "- quarantine: ['001309']" in markdown
```

- [ ] **Step 2: Run the script tests and verify they fail**

Run:

```bash
uv run pytest tests/test_analyze_btst_5d_15pct_boundary_quarantine_script.py -q
```

Expected: `FAIL` with import errors because the script does not exist yet.

- [ ] **Step 3: Implement the quarantine analysis script**

Create `scripts/analyze_btst_5d_15pct_boundary_quarantine.py`:

```python
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.analyze_btst_5d_15pct_boundary_contract_inspection import analyze_btst_5d_15pct_boundary_contract_inspection
from scripts.btst_boundary_quarantine_helpers import (
    classify_boundary_quarantine_decision,
    is_boundary_without_explainability_target,
    summarize_boundary_quarantine_rows,
)

REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_5d_15pct_boundary_quarantine_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_5d_15pct_boundary_quarantine_latest.md"


def analyze_btst_5d_15pct_boundary_quarantine_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    decision_rows = [classify_boundary_quarantine_decision(row) for row in rows if is_boundary_without_explainability_target(row)]
    summary = summarize_boundary_quarantine_rows(decision_rows)
    governance_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in decision_rows:
        governance_groups[str(row.get("governance_action") or "unknown")].append(row)
    governance_decision_board = [
        {
            "action": action,
            "row_count": len(group_rows),
            "tickers": sorted(str(row.get("ticker") or "") for row in group_rows),
        }
        for action, group_rows in governance_groups.items()
    ]
    governance_decision_board.sort(key=lambda row: (-int(row["row_count"]), str(row["action"])))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "boundary_row_count": len(decision_rows),
        "decision_rows": decision_rows,
        "disposition_summary_board": [summary["disposition_counts"]],
        "source_summary_board": summary["source_summary_board"],
        "governance_decision_board": governance_decision_board,
        "research_surface_lists": {
            "allow": sorted(str(row.get("ticker") or "") for row in decision_rows if row.get("research_surface_disposition") == "allow"),
            "quarantine": sorted(str(row.get("ticker") or "") for row in decision_rows if row.get("research_surface_disposition") == "quarantine"),
            "separate_surface": sorted(str(row.get("ticker") or "") for row in decision_rows if row.get("research_surface_disposition") == "separate_surface"),
        },
    }


def analyze_btst_5d_15pct_boundary_quarantine(reports_root: str | Path) -> dict[str, Any]:
    inspection = analyze_btst_5d_15pct_boundary_contract_inspection(reports_root)
    return analyze_btst_5d_15pct_boundary_quarantine_from_rows(list(inspection.get("boundary_rows") or []))


def render_btst_5d_15pct_boundary_quarantine_markdown(analysis: dict[str, Any]) -> str:
    lists = dict(analysis.get("research_surface_lists") or {})
    lines = [
        "# BTST 5D / +15% Boundary Quarantine",
        "",
        f"- boundary_row_count: {analysis.get('boundary_row_count')}",
        "",
        "## disposition_summary_board",
        f"- {dict((analysis.get('disposition_summary_board') or [{}])[0])}",
        "",
        "## source_summary_board",
    ]
    for row in list(analysis.get("source_summary_board") or []):
        lines.append(f"- {row}")
    if not list(analysis.get("source_summary_board") or []):
        lines.append("- none")
    lines.extend(
        [
            "",
            "## governance_decision_board",
        ]
    )
    for row in list(analysis.get("governance_decision_board") or []):
        lines.append(f"- {row}")
    if not list(analysis.get("governance_decision_board") or []):
        lines.append("- none")
    lines.extend(
        [
            "",
            "## research_surface_lists",
            f"- allow: {lists.get('allow', [])}",
            f"- quarantine: {lists.get('quarantine', [])}",
            f"- separate_surface: {lists.get('separate_surface', [])}",
        ]
    )
    return "\\n".join(lines)
```

- [ ] **Step 4: Run the new script tests and existing inspection/fill-path tests**

Run:

```bash
uv run pytest \
  tests/test_btst_boundary_quarantine_helpers.py \
  tests/test_analyze_btst_5d_15pct_boundary_quarantine_script.py \
  tests/test_analyze_btst_5d_15pct_boundary_contract_inspection_script.py \
  tests/test_analyze_btst_5d_15pct_boundary_contract_fill_path_script.py \
  -q
```

Expected: all listed tests `PASS`.

- [ ] **Step 5: Commit the quarantine artifact script**

Run:

```bash
git add \
  scripts/btst_boundary_quarantine_helpers.py \
  scripts/analyze_btst_5d_15pct_boundary_quarantine.py \
  tests/test_btst_boundary_quarantine_helpers.py \
  tests/test_analyze_btst_5d_15pct_boundary_quarantine_script.py
git commit -m "feat: add boundary quarantine artifact"
```

### Task 3: Teach round1 factor research to consume the quarantine artifact

**Files:**
- Modify: `scripts/analyze_btst_5d_15pct_factor_research_round1.py:20-24`
- Modify: `scripts/analyze_btst_5d_15pct_factor_research_round1.py:81-124`
- Modify: `tests/test_analyze_btst_5d_15pct_factor_research_round1_script.py`

- [ ] **Step 1: Write the failing round1 consumer regression**

Append this test to `tests/test_analyze_btst_5d_15pct_factor_research_round1_script.py`:

```python
def test_analyze_btst_5d_15pct_factor_research_round1_excludes_quarantined_tickers(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    quarantine_artifact = reports_root / "btst_5d_15pct_boundary_quarantine_latest.json"
    quarantine_artifact.parent.mkdir(parents=True, exist_ok=True)
    quarantine_artifact.write_text(
        """
        {
          "research_surface_lists": {
            "allow": [],
            "quarantine": ["001309"],
            "separate_surface": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    report_dir = reports_root / "paper_trading_window_20260323_20260326_round1_a"
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
                "decision": "selected",
                "explainability_payload": {
                  "trend_acceleration": 0.64,
                  "close_strength": 0.67,
                  "volume_expansion_quality": 0.62,
                  "breakout_freshness": 0.58
                }
              }
            }
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        round1_script,
        "_extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: {
            "cycle_status": "closed_cycle",
            "future_high_hit_15pct_2_5d": True,
            "max_future_high_return_2_5d": 0.18,
            "time_to_hit_15pct": 2,
            "next_open_return": 0.01,
        },
    )

    analysis = round1_script.analyze_btst_5d_15pct_factor_research_round1(
        reports_root,
        min_closed_cycle_count=1,
        boundary_quarantine_artifact=quarantine_artifact,
    )

    assert analysis["row_count"] == 0
    assert analysis["alpha_beta_gamma_shortlist"] == []
```

- [ ] **Step 2: Run the new round1 regression and verify it fails**

Run:

```bash
uv run pytest tests/test_analyze_btst_5d_15pct_factor_research_round1_script.py::test_analyze_btst_5d_15pct_factor_research_round1_excludes_quarantined_tickers -q
```

Expected: `FAIL` because `analyze_btst_5d_15pct_factor_research_round1()` does not yet accept or consume a quarantine artifact.

- [ ] **Step 3: Implement the smallest consumption surface in round1**

Modify `scripts/analyze_btst_5d_15pct_factor_research_round1.py`:

```python
DEFAULT_BOUNDARY_QUARANTINE_ARTIFACT = REPORTS_DIR / "btst_5d_15pct_boundary_quarantine_latest.json"


def _load_boundary_quarantine_lists(path: str | Path | None) -> dict[str, set[str]]:
    if path is None:
        path = DEFAULT_BOUNDARY_QUARANTINE_ARTIFACT
    resolved = Path(path)
    if not resolved.exists():
        return {"allow": set(), "quarantine": set(), "separate_surface": set()}
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    research_surface_lists = dict(payload.get("research_surface_lists") or {})
    return {
        "allow": {str(ticker) for ticker in list(research_surface_lists.get("allow") or [])},
        "quarantine": {str(ticker) for ticker in list(research_surface_lists.get("quarantine") or [])},
        "separate_surface": {str(ticker) for ticker in list(research_surface_lists.get("separate_surface") or [])},
    }
```

Update the main analyzer signature and collection loop:

```python
def analyze_btst_5d_15pct_factor_research_round1(
    reports_root: str | Path,
    *,
    min_closed_cycle_count: int = 3,
    boundary_quarantine_artifact: str | Path | None = None,
) -> dict[str, Any]:
    resolved_root = Path(reports_root).expanduser().resolve()
    quarantine_lists = _load_boundary_quarantine_lists(boundary_quarantine_artifact)
```

```python
                if str(ticker) in quarantine_lists["quarantine"] or str(ticker) in quarantine_lists["separate_surface"]:
                    continue
```

Update the CLI:

```python
parser.add_argument("--boundary-quarantine-artifact", default=str(DEFAULT_BOUNDARY_QUARANTINE_ARTIFACT))
```

```python
analysis = analyze_btst_5d_15pct_factor_research_round1(
    args.reports_root,
    min_closed_cycle_count=args.min_closed_cycle_count,
    boundary_quarantine_artifact=args.boundary_quarantine_artifact,
)
```

- [ ] **Step 4: Run the round1 suite and quarantine suite together**

Run:

```bash
uv run pytest \
  tests/test_btst_boundary_quarantine_helpers.py \
  tests/test_analyze_btst_5d_15pct_boundary_quarantine_script.py \
  tests/test_analyze_btst_5d_15pct_factor_research_round1_script.py \
  -q
```

Expected: all listed tests `PASS`.

- [ ] **Step 5: Commit the round1 consumer integration**

Run:

```bash
git add scripts/analyze_btst_5d_15pct_factor_research_round1.py tests/test_analyze_btst_5d_15pct_factor_research_round1_script.py
git commit -m "feat: filter round1 research with boundary quarantine artifact"
```

### Task 4: Refresh diagnostics note and run the final focused verification

**Files:**
- Create: `docs/prompt/find_actor_methord/btst-boundary-without-explainability-quarantine-2026-05-22.md`
- Refresh local ignored artifacts: `data/reports/btst_5d_15pct_boundary_quarantine_latest.json`
- Refresh local ignored artifacts: `data/reports/btst_5d_15pct_boundary_quarantine_latest.md`

- [ ] **Step 1: Write the diagnosis-only note**

Create `docs/prompt/find_actor_methord/btst-boundary-without-explainability-quarantine-2026-05-22.md`:

```markdown
# btst-boundary-without-explainability-quarantine-2026-05-22

## 结论

- 本轮工作是 research-surface quarantine，不是 alpha 因子优化。
- 目标是把 `boundary_without_explainability` 这 121 行样本显式隔离出 round1/round2 因子研究面。
- 任何进入 `quarantine` 或 `separate_surface` 的 ticker，都不能推进到 `docs/prompt/find_actor/`，也不能接入 `ai-hedge-fund-btst`。

## 这轮解决什么

1. 把 `boundary_contract_inspection` 的结果转成可消费的 quarantine artifact。
2. 让 round1 因子研究默认跳过被 quarantine 的样本。
3. 保持 fill-path 仍然只做后置验证，不承担研究面清洗。

## 如何验证

1. `uv run pytest tests/test_btst_boundary_quarantine_helpers.py tests/test_analyze_btst_5d_15pct_boundary_quarantine_script.py -q`
2. `uv run pytest tests/test_analyze_btst_5d_15pct_factor_research_round1_script.py -q`
3. `uv run python scripts/analyze_btst_5d_15pct_boundary_quarantine.py`

## fail-closed 说明

- quarantine artifact 只用于隔离和治理，不代表这些样本已经修好。
- 后续只有在上游 contract 修复并且 fill-path 重新验证通过后，才允许重新讨论是否释放回研究面。
- 本文档不能进入 `docs/prompt/find_actor/`。
```

- [ ] **Step 2: Run the new quarantine script**

Run:

```bash
uv run python scripts/analyze_btst_5d_15pct_boundary_quarantine.py
```

Expected: writes `data/reports/btst_5d_15pct_boundary_quarantine_latest.json` and `.md`.

- [ ] **Step 3: Run the final focused verification bundle**

Run:

```bash
uv run pytest \
  tests/test_btst_boundary_quarantine_helpers.py \
  tests/test_analyze_btst_5d_15pct_boundary_quarantine_script.py \
  tests/test_analyze_btst_5d_15pct_boundary_contract_inspection_script.py \
  tests/test_analyze_btst_5d_15pct_boundary_contract_fill_path_script.py \
  tests/test_analyze_btst_5d_15pct_factor_research_round1_script.py \
  -q && \
uv run python scripts/analyze_btst_5d_15pct_boundary_quarantine.py
```

Expected: pytest bundle `PASS`es and the quarantine script rewrites the local ignored reports.

- [ ] **Step 4: Commit the note**

Run:

```bash
git add docs/prompt/find_actor_methord/btst-boundary-without-explainability-quarantine-2026-05-22.md
git commit -m "docs: record boundary quarantine governance"
```

## Spec coverage check

- Row-level quarantine classification is implemented in **Task 1**.
- Deterministic quarantine artifact + governance boards are implemented in **Task 2**.
- Round1 consumption of the artifact is implemented in **Task 3**.
- Diagnosis-only note and final verification are covered in **Task 4**.

## Placeholder scan

- No placeholders or vague “write tests later” steps remain.
- Every code-change step includes concrete code and an exact command.

## Type consistency check

- The plan consistently uses `research_surface_disposition` values `allow`, `quarantine`, and `separate_surface`.
- The round1 consumer only reads ticker lists from the quarantine artifact and does not redefine classifier semantics.
