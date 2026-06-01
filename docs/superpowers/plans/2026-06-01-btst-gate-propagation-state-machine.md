# BTST Gate Propagation State Machine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Make gate_locked_confirmation_only propagate into every executable BTST report section, add a shared execution state machine, and write the final state into quality summary and review ledger.

**Architecture:** Keep upstream selection logic unchanged. Extend the existing BTST enrichment layer with final execution semantics derived from control_tower, then render BTST-LLM and EXEC-CHECKLIST from that shared state instead of hard-coded formal-execution wording. Quality summary and review ledger must consume the same state so Markdown and machine-readable outputs cannot drift.

**Tech Stack:** Python 3.11+, pytest, existing BTST report generator, existing BTST decision enrichment helpers.

---

### Task 1: Lock The Regression With Failing Tests

**Files:**
- Modify: tests/test_generate_btst_doc_bundle_script.py
- Test: tests/test_generate_btst_doc_bundle_script.py

- [ ] **Step 1: Add a failing gate-locked regression test**

```python
def test_generate_btst_doc_bundle_confirmation_review_only_relabels_executable_sections(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_20260529_20260529_live_m2_7_short_trade_only_20260601_plan"
    brief_path = report_dir / "btst_next_day_trade_brief_latest.json"

    _write_json(
        report_dir / "session_summary.json",
        {
            "trade_date": "2026-05-29",
            "selection_target": "short_trade_only",
            "btst_followup": {"brief_json": brief_path.as_posix()},
        },
    )
    _write_json(
        brief_path,
        {
            "trade_date": "2026-05-29",
            "next_trade_date": "2026-06-01",
            "selection_target": "short_trade_only",
            "selected_actions": [
                {
                    "ticker": "300054",
                    "name": "鼎龙股份",
                    "action_tier": "primary_entry",
                    "preferred_entry_mode": "confirm_then_hold_breakout",
                    "score_target": 0.5588,
                    "historical_prior": {
                        "applied_scope": "same_ticker",
                        "evaluable_count": 15,
                        "next_close_positive_rate": 0.80,
                        "next_close_payoff_ratio": 1.62,
                        "next_close_expectancy": 0.018,
                    },
                }
            ],
            "watch_actions": [],
            "opportunity_actions": [],
        },
    )
    _write_json(
        report_dir / "selection_snapshot_2026-05-29.json",
        {
            "market_state": {"regime_gate_level": "crisis", "breadth_ratio": 0.2842},
            "funnel_diagnostics": {
                "btst_regime_gate_enforcement": {
                    "gate": "halt",
                    "enforced": True,
                    "buy_orders_cleared": True,
                    "buy_orders_cleared_count": 1,
                }
            },
        },
    )
    _write_json(reports_root / "btst_full_report_20260529.json", {"trade_date": "2026-05-29", "high_confidence": []})
    _write_json(reports_root / "btst_early_runner_v1_latest.json", {"daily_boards": [{"trade_date": "2026-05-29"}]})

    output_dir = tmp_path / "outputs"
    result = generate_btst_doc_bundle(
        "20260529",
        reports_root=reports_root,
        output_dir=output_dir,
        refresh_early_runner=False,
        include_extra_warning_docs=False,
        write_review_ledger=True,
    )

    llm_doc = (output_dir / "BTST-LLM-20260529.md").read_text(encoding="utf-8")
    checklist_doc = (output_dir / "BTST-20260529-EXEC-CHECKLIST.md").read_text(encoding="utf-8")
    quality_summary = json.loads(Path(result["quality_summary_json_path"]).read_text(encoding="utf-8"))
    ledger_payload = json.loads((output_dir / "20260529-btst-decision-review-ledger.json").read_text(encoding="utf-8"))

    assert "## 确认复核队列" in llm_doc
    assert "## 正式执行层" not in llm_doc
    assert "## 确认复核顺序" in checklist_doc
    assert "## 正式执行顺序" not in checklist_doc
    assert quality_summary["report_mode"] == "confirmation_review_only"
    assert quality_summary["semantic_conflicts"] == []
    assert quality_summary["forbidden_semantics_hits"] == []
    assert ledger_payload["rows"][0]["execution_state"] == "confirmable"
    assert ledger_payload["rows"][0]["max_allowed_state_today"] == "confirmable"
    assert ledger_payload["rows"][0]["formal_buy_allowed"] is False
```

- [ ] **Step 2: Run the new regression test and confirm it fails for the right reason**

Run: pytest tests/test_generate_btst_doc_bundle_script.py::test_generate_btst_doc_bundle_confirmation_review_only_relabels_executable_sections -v

Expected: FAIL because the current docs still render 正式执行层 / 正式执行顺序 and the quality summary lacks the new structured fields.

- [ ] **Step 3: Add a failing gate-allowed control test**

```python
def test_generate_btst_doc_bundle_formal_execution_keeps_formal_labels(tmp_path: Path) -> None:
    ...
    assert "## 正式执行层" in llm_doc
    assert "## 确认复核队列" not in llm_doc
    assert quality_summary["report_mode"] == "formal_execution"
    assert ledger_payload["rows"][0]["execution_state"] == "orderable"
    assert ledger_payload["rows"][0]["formal_buy_allowed"] is True
```

- [ ] **Step 4: Run the second test and confirm it also fails before implementation**

Run: pytest tests/test_generate_btst_doc_bundle_script.py::test_generate_btst_doc_bundle_formal_execution_keeps_formal_labels -v

Expected: FAIL because the current implementation does not expose report_mode or execution_state.

- [ ] **Step 5: Commit checkpoint**

```bash
git add tests/test_generate_btst_doc_bundle_script.py
git commit -m "test: lock btst gate propagation semantics"
```

### Task 2: Add Shared Final Execution Semantics

**Files:**
- Modify: src/paper_trading/btst_decision_enrichment.py
- Test: tests/test_generate_btst_doc_bundle_script.py

- [ ] **Step 1: Add report-mode and veto-owner helpers**

```python
def build_report_mode(control_tower: dict[str, Any]) -> str:
    effective_trade_bias = str(control_tower.get("effective_trade_bias") or "")
    if effective_trade_bias == "gate_locked_confirmation_only":
        return "confirmation_review_only"
    if effective_trade_bias == "trade_allowed":
        return "formal_execution"
    return "confirmation_review_only"


def build_veto_owner(control_tower: dict[str, Any]) -> str:
    reason_codes = {str(code) for code in list(control_tower.get("reason_codes") or [])}
    if {"market_gate_downgraded_raw_trade_allowed", "market_gate_requires_confirmation"} & reason_codes:
        return "market_gate"
    if "selection_snapshot_missing" in reason_codes:
        return "manual_review"
    return "model_evidence"
```

- [ ] **Step 2: Add row-level execution semantics derived from report_mode**

```python
def attach_execution_semantics(
    row: dict[str, Any],
    *,
    report_mode: str,
    control_tower: dict[str, Any],
) -> dict[str, Any]:
    state_reason_codes = [str(code) for code in list(control_tower.get("reason_codes") or []) if str(code)]
    trade_bias = str(row.get("trade_bias") or "watch_only")

    if report_mode == "confirmation_review_only":
        if trade_bias == "skip":
            execution_state = "blocked"
            allowed_sections = ["blocked_only"]
        elif str(row.get("role") or "") == "formal_selected":
            execution_state = "confirmable"
            allowed_sections = ["review_queue"]
        else:
            execution_state = "watching"
            allowed_sections = ["watch_queue"]
        max_allowed_state_today = "confirmable"
        formal_buy_allowed = False
    else:
        if trade_bias == "trade_allowed" and str(row.get("role") or "") == "formal_selected":
            execution_state = "orderable"
            allowed_sections = ["formal_queue"]
            formal_buy_allowed = True
        elif trade_bias == "confirmation_only" and str(row.get("role") or "") == "formal_selected":
            execution_state = "confirmable"
            allowed_sections = ["formal_queue"]
            formal_buy_allowed = False
        elif trade_bias == "skip":
            execution_state = "blocked"
            allowed_sections = ["blocked_only"]
            formal_buy_allowed = False
        else:
            execution_state = "watching"
            allowed_sections = ["watch_queue"]
            formal_buy_allowed = False
        max_allowed_state_today = "orderable"

    enriched = dict(row)
    enriched.update(
        {
            "execution_state": execution_state,
            "max_allowed_state_today": max_allowed_state_today,
            "formal_buy_allowed": formal_buy_allowed,
            "allowed_sections": allowed_sections,
            "state_reason_codes": state_reason_codes,
        }
    )
    return enriched
```

- [ ] **Step 3: Extend the review ledger schema to persist the new semantics**

```python
ledger_rows.append(
    {
        ...,
        "report_mode": row.get("report_mode"),
        "execution_state": row.get("execution_state"),
        "max_allowed_state_today": row.get("max_allowed_state_today"),
        "formal_buy_allowed": row.get("formal_buy_allowed"),
        "allowed_sections": list(row.get("allowed_sections") or []),
        "state_reason_codes": list(row.get("state_reason_codes") or []),
    }
)
```

- [ ] **Step 4: Run the two focused tests and keep them red-green scoped**

Run: pytest tests/test_generate_btst_doc_bundle_script.py::test_generate_btst_doc_bundle_confirmation_review_only_relabels_executable_sections tests/test_generate_btst_doc_bundle_script.py::test_generate_btst_doc_bundle_formal_execution_keeps_formal_labels -v

Expected: still FAIL until the report generator starts consuming the new fields.

- [ ] **Step 5: Commit checkpoint**

```bash
git add src/paper_trading/btst_decision_enrichment.py tests/test_generate_btst_doc_bundle_script.py
git commit -m "feat: add btst execution semantics contract"
```

### Task 3: Wire Report Rendering And Quality Contracts

**Files:**
- Modify: scripts/generate_btst_doc_bundle.py
- Modify: tests/test_generate_btst_doc_bundle_script.py
- Test: tests/test_generate_btst_doc_bundle_script.py

- [ ] **Step 1: Import the new semantics helpers and derive one shared report context**

```python
from src.paper_trading.btst_decision_enrichment import (
    attach_execution_semantics,
    build_decision_card,
    build_report_mode,
    build_review_ledger_rows,
    build_veto_owner,
    enrich_btst_row,
)


report_mode = build_report_mode(control_tower)
veto_owner = build_veto_owner(control_tower)
section_labels = {
    "formal_queue": "确认复核队列" if report_mode == "confirmation_review_only" else "正式执行层",
    "formal_order": "确认复核顺序" if report_mode == "confirmation_review_only" else "正式执行顺序",
}
```

- [ ] **Step 2: Apply execution semantics to all enriched formal rows before rendering**

```python
enriched_selected = [
    attach_execution_semantics(row, report_mode=report_mode, control_tower=control_tower)
    for row in _enrich_formal_rows(selected_actions, role="formal_selected", early_runner_status=early_status)
]
enriched_watch = [
    attach_execution_semantics(row, report_mode=report_mode, control_tower=control_tower)
    for row in _enrich_formal_rows(watch_actions, role="formal_watch", early_runner_status=early_status)
]
```

- [ ] **Step 3: Replace hard-coded section titles and add a per-row state table**

```python
lines.extend(["", f"## {section_labels['formal_queue']}", ""])
lines.extend(_render_enriched_stock_bullets(enriched_selected, limit=5))

lines.extend(["", "## 执行状态机", ""])
lines.extend(
    [
        "| 股票 | 当前状态 | 今日上限 | 允许章节 | 正式买入权限 | 下一步条件 | 取消条件 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
)
for row in enriched_selected[:5]:
    lines.append(
        f"| {_stock_label(row)} | {row.get('execution_state')} | {row.get('max_allowed_state_today')} | "
        f"{','.join(row.get('allowed_sections') or [])} | {row.get('formal_buy_allowed')} | "
        f"{row.get('must_confirm')} | {row.get('invalidate_if')} |"
    )
```

- [ ] **Step 4: Extend quality summary with machine-readable conflict checks**

```python
forbidden_semantics = {
    "confirmation_review_only": ["正式买入", "正式下单", "正式执行", "主执行顺序", "直接执行"],
    "formal_execution": [],
}

forbidden_hits = [
    token
    for token in forbidden_semantics[report_mode]
    if token in docs[f"BTST-{signal_date_compact}-EXEC-CHECKLIST.md"] or token in docs[f"BTST-LLM-{signal_date_compact}.md"]
]

return {
    ...,
    "report_mode": report_mode,
    "veto_owner": veto_owner,
    "semantic_conflicts": semantic_conflicts,
    "forbidden_semantics_hits": forbidden_hits,
    "source_of_truth_snapshot": {
        "effective_trade_bias": control_tower.get("effective_trade_bias"),
        "report_mode": report_mode,
        "veto_owner": veto_owner,
        "section_labels": section_labels,
        "formal_rows": [
            {
                "ticker": row.get("ticker"),
                "execution_state": row.get("execution_state"),
                "max_allowed_state_today": row.get("max_allowed_state_today"),
                "allowed_sections": list(row.get("allowed_sections") or []),
            }
            for row in enriched_selected
        ],
        "forbidden_semantics_hits": forbidden_hits,
    },
}
```

- [ ] **Step 5: Run the focused test file to get green**

Run: pytest tests/test_generate_btst_doc_bundle_script.py -v

Expected: PASS, including the new gate-locked regression and the gate-allowed control test.

- [ ] **Step 6: Commit checkpoint**

```bash
git add scripts/generate_btst_doc_bundle.py src/paper_trading/btst_decision_enrichment.py tests/test_generate_btst_doc_bundle_script.py
git commit -m "feat: propagate btst gate semantics into reports"
```

### Task 4: Final Verification

**Files:**
- Modify: none
- Test: tests/test_generate_btst_doc_bundle_script.py

- [ ] **Step 1: Re-run the narrow verification command fresh**

Run: pytest tests/test_generate_btst_doc_bundle_script.py -v

Expected: PASS with 0 failures.

- [ ] **Step 2: Spot-check the generated semantics in test assertions**

```python
assert quality_summary["veto_owner"] == "market_gate"
assert quality_summary["source_of_truth_snapshot"]["formal_rows"][0]["allowed_sections"] == ["review_queue"]
assert ledger_payload["rows"][0]["state_reason_codes"] == ["market_gate_downgraded_raw_trade_allowed"]
```

- [ ] **Step 3: Commit final checkpoint**

```bash
git add docs/superpowers/specs/2026-06-01-btst-gate-propagation-state-machine-design.md \
  docs/superpowers/plans/2026-06-01-btst-gate-propagation-state-machine.md \
  scripts/generate_btst_doc_bundle.py \
  src/paper_trading/btst_decision_enrichment.py \
  tests/test_generate_btst_doc_bundle_script.py
git commit -m "feat: add btst execution state machine contract"
```