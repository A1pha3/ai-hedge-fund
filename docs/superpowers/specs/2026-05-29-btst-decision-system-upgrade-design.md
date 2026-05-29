# BTST Decision System Upgrade Design

- **Date:** 2026-05-29
- **Topic:** BTST document readability, practical execution value, and accuracy governance
- **Recommended direction:** Upgrade the document bundle into a pre-trade decision system with evidence grading, action matrices, data-quality gates, and review feedback loops.

## 1. Problem Statement

The current BTST document bundle can already generate the main daily artifacts, including rule reports, multi-agent plans, execution checklists, and early-runner overlays. The recent historical-prior repair also gives each stock a clearer win-rate and payoff explanation.

The remaining problem is product shape. The documents still read more like generated research output than a trading desk decision pack:

1. The first screen does not immediately answer whether the next session should be traded, watched, or skipped.
2. Stock rows expose useful metrics, but the reader must still infer the final confidence level and execution priority.
3. `stale_fallback`, low sample count, missing payoff, and non-`same_ticker` priors are present as facts, but not yet promoted into hard evidence-quality gates.
4. Entry modes are shown as labels, but the documents do not consistently translate them into concrete opening scenarios and invalidation conditions.
5. There is no daily review ledger that connects pre-trade claims to next-day realized outcomes and weekly calibration.

The result is a system that is informative, but still leaves too much discretionary interpretation to the reader. A stronger system should reduce interpretation burden, prevent weak evidence from looking strong, and create a measurable feedback loop.

## 2. Goal and Non-Goals

### Goal

Build a BTST decision-document system that helps a user answer five questions in under one minute:

1. Can the next session be traded under current data quality and regime conditions?
2. Which stock is the primary candidate, and what evidence grade supports it?
3. What exactly must happen at the open before execution is allowed?
4. What conditions invalidate the plan?
5. How will the recommendation be reviewed after the next session closes?

### Non-Goals

1. Do not change the core selection model in the first implementation phase.
2. Do not let early-runner signals override formal BTST execution priority without evidence gates.
3. Do not claim that higher document quality guarantees market returns.
4. Do not add broad new alpha factors before the current evidence and review loop is governed.
5. Do not make forum or plain-language documents carry formal trading decisions.

## 3. Approaches Considered

### Approach A: Document Readability Only

Improve headings, ordering, wording, and table layout while preserving all current data fields.

**Pros**

1. Fastest path.
2. Low implementation risk.
3. Immediately easier to read.

**Cons**

1. Does little to improve decision accuracy.
2. Still leaves evidence quality and invalidation logic implicit.
3. Does not create review data for future calibration.

### Approach B: Evidence Grading Layer

Add per-stock evidence grades, sample reliability, payoff interpretation, data freshness warnings, and execution-quality flags.

**Pros**

1. Directly reduces misreading of weak historical priors.
2. Uses data already present in current artifacts.
3. Improves both readability and decision discipline.

**Cons**

1. Still mostly improves rows, not the whole daily workflow.
2. Does not fully solve post-trade review and weekly calibration.

### Approach C: Full Decision-System Upgrade (Recommended)

Add a pre-trade decision card, evidence grading, opening action matrices, data-quality gates, review ledger output, and weekly calibration reports.

**Pros**

1. Turns the document bundle into a repeatable trading workflow.
2. Improves practical use and accuracy governance at the same time.
3. Keeps weak or stale evidence from silently influencing execution.
4. Creates data needed to evaluate whether the system is actually improving.

**Cons**

1. More moving parts than a pure template rewrite.
2. Requires a phased rollout to avoid changing too many behaviors at once.

## 4. Recommended Design

The first release should implement the smallest useful version of Approach C:

1. Keep the existing selection logic unchanged.
2. Enrich each selected/watch row with evidence and action fields.
3. Render a 30-second decision card at the top of the main documents.
4. Add hard data-quality gates to every formal trading recommendation.
5. Emit a review ledger that can later be joined with realized next-day outcomes.

This gives the user immediate practical value without turning the first phase into a model rewrite.

## 5. Core Concepts

### 5.1 Decision Card

The decision card is the first block in `BTST-LLM` and `EXEC-CHECKLIST`. It should answer:

1. `trade_bias`: `trade_allowed`, `confirmation_only`, `watch_only`, or `skip`.
2. `primary_ticker`: the first formal candidate after evidence gates.
3. `evidence_grade`: `A`, `B`, `C`, or `D`.
4. `data_quality`: `fresh`, `usable_with_warning`, `stale_reference`, or `insufficient`.
5. `risk_posture`: `normal`, `reduced`, `micro`, or `no_trade`.
6. `must_confirm`: one concise opening confirmation condition.
7. `invalidate_if`: one concise condition that cancels the plan.

The card should prefer plain trading language over internal labels. Internal fields remain visible later in the detailed evidence section.

### 5.2 Evidence Grade

Each stock receives an evidence grade derived from existing metrics:

| Grade | Meaning | Typical Requirements |
| --- | --- | --- |
| `A` | Execution-grade evidence | Fresh data, same-ticker or highly specific prior, enough samples, win rate and payoff both supportive, no divergence warning |
| `B` | Tradable after confirmation | Fresh or usable data, reasonable sample count, at least one of win rate or payoff strong, no severe quality issue |
| `C` | Watch or reduced-risk only | Mixed win/payoff, small sample, non-specific prior, or payoff divergence |
| `D` | Research-only / skip | Stale data, missing key metrics, very weak expectancy, or explicit execution blocker |

The grade is not a new alpha score. It is a governance label that says how much trust the document is allowed to place on the evidence.

### 5.3 Action Matrix

Each formal candidate should render a compact action matrix:

| Scenario | Action |
| --- | --- |
| Opens strong and confirms continuation | Follow the entry mode, then manage by BTST contract |
| Opens high but fails confirmation | No chase; downgrade to watch |
| Opens weak but stabilizes with volume/price repair | Recheck only if the original trigger still holds |
| Breaks invalidation condition | Skip and record the reason |

The first implementation can keep scenario wording rule-based by `preferred_entry_mode`, `evidence_grade`, and payoff profile. It should avoid inventing price levels unless they exist in upstream artifacts.

### 5.4 Data-Quality Gate

The renderer should compute a visible data-quality state before making any recommendation:

1. `stale_fallback` early-runner data cannot upgrade priority.
2. `evaluable_count < 5` should force weak-reference wording.
3. `evaluable_count < 10` should force confirmation-only wording.
4. Missing payoff fields should be explicit and should not be treated as neutral.
5. Non-`same_ticker` priors should be labeled as bucket evidence, not stock-specific evidence.
6. `win_rate_payoff_divergence=true` should cap the evidence grade unless a stronger rule overrides it.

This gate is the main accuracy-protection layer. It prevents a polished document from overstating weak evidence.

### 5.5 Review Ledger

Every generated bundle should optionally emit a machine-readable review ledger:

```json
{
  "signal_date": "2026-05-28",
  "next_trade_date": "2026-05-29",
  "ticker": "002222",
  "role": "formal_selected",
  "evidence_grade": "B",
  "data_quality": "fresh",
  "trade_bias": "confirmation_only",
  "win_rate": 0.7273,
  "payoff_ratio": 1.0792,
  "expectancy": 0.0272,
  "entry_mode": "confirm_then_hold_breakout",
  "must_confirm": "continuation confirmation before entry",
  "invalidate_if": "no confirmation or early fade",
  "realized_next_open": null,
  "realized_next_high": null,
  "realized_next_close": null,
  "review_label": null
}
```

The initial ledger can leave realized fields empty. A follow-up script can fill them after next-day market data is available.

## 6. Document Responsibilities

### `BTST-LLM-YYYYMMDD.md`

Primary decision narrative. It should contain:

1. 30-second decision card.
2. Formal execution layer with evidence grades.
3. Watch layer with explicit downgrade reasons.
4. Early-runner status and whether it can influence priority.
5. Detailed evidence notes only after the decision summary.

### `BTST-YYYYMMDD-EXEC-CHECKLIST.md`

Opening execution surface. It should contain:

1. Same 30-second decision card in compressed form.
2. Checklist rows grouped by `execute`, `confirmation_only`, `watch`, and `skip`.
3. Action matrix per formal candidate.
4. Explicit invalidation conditions.

### `BTST-YYYYMMDD-EARLY-WARNING.md`

Supplemental observation surface. It should contain:

1. Whether early-runner is exact, stale, or unavailable.
2. Research-only rows separated from actionable rows.
3. Evidence grades and data-quality warnings for supplemental names.
4. No upgrade language when the board is stale.

### `BTST-YYYYMMDD.md`

Rule-report base layer. It should stay close to rule evidence and avoid pretending that raw rule score is the same as execution quality.

### Plain and Forum Documents

These are explanation and communication documents. They may summarize the decision card, but they should not add new formal trading instructions.

## 7. Architecture

### New Shared Enrichment Module

Add a small shared module, for example:

```text
src/paper_trading/btst_decision_enrichment.py
```

Responsibilities:

1. Normalize row metrics from nested `historical_prior` or row-level fields.
2. Compute evidence grade.
3. Compute data-quality label.
4. Compute trade bias.
5. Generate action and invalidation text.
6. Return structured objects that renderers can consume.

This keeps `scripts/generate_btst_doc_bundle.py` from becoming a large text-formatting file with hidden trading logic.

### Renderer Changes

Update `scripts/generate_btst_doc_bundle.py` to:

1. Call the enrichment module for selected, watch, opportunity, and early-runner rows.
2. Render the decision card.
3. Render evidence-grade stock rows.
4. Render action matrices in the checklist.
5. Write optional ledger JSON and Markdown.

### Tests

Tests should cover the decision rules directly and the generated documents as integration surfaces.

## 8. Data Flow

1. Existing report artifacts are loaded from the selected `report_dir`.
2. Rows are resolved from `brief_json`, `priority_board_json`, and early-runner artifacts.
3. Each row is passed through decision enrichment.
4. The renderer builds the document bundle from enriched rows.
5. The ledger writer stores the pre-trade decision state.
6. A later review command can join the ledger to realized next-day data and produce calibration summaries.

## 9. Accuracy Governance

The system should treat accuracy as a measured property, not a writing style.

### Daily Gates

1. If the main data source is stale, the decision card should not say `trade_allowed`.
2. If the primary candidate has `D` evidence, the decision card should choose `watch_only` or `skip`.
3. If payoff is missing, the stock row must say why it is missing or state that it is unknown.
4. If win rate is high but payoff is weak, the row must show a divergence-style warning.
5. If early-runner is `stale_fallback`, it may appear only as reference evidence.

### Weekly Calibration

The weekly report should group outcomes by:

1. Evidence grade.
2. Entry mode.
3. Data-quality label.
4. Same-ticker versus bucket prior.
5. Win-rate/payoff divergence.
6. Formal selected versus watch versus early-runner-only.

This report should answer whether `A/B/C/D` labels are predictive enough to keep, retune, or remove.

## 10. Error Handling

1. Missing optional artifacts should degrade the affected section, not stop the whole bundle.
2. Missing required `brief_json` should remain a hard error.
3. Unknown numeric fields should render as `n/a` plus an explicit quality note.
4. Any stale fallback should be visible in both the decision card and detailed section.
5. Ledger writing failures should fail the command only when ledger output is explicitly requested.

## 11. Rollout Plan

### Phase 1: Decision Pack MVP

1. Add enrichment module.
2. Add evidence grade and data-quality label.
3. Render decision card in `BTST-LLM` and `EXEC-CHECKLIST`.
4. Render action matrices for formal candidates.
5. Add unit and integration tests.

### Phase 2: Review Ledger

1. Emit pre-trade ledger JSON.
2. Add post-close fill script for realized fields.
3. Add weekly calibration Markdown.
4. Add tests for ledger schema and grouping.

### Phase 3: Calibration-Governed Refinement

1. Compare evidence grades against realized outcomes.
2. Retune grade thresholds only after enough closed samples exist.
3. Promote useful early-runner overlap logic only if calibration supports it.
4. Document any threshold change with before/after evidence.

## 12. Acceptance Criteria

The first implementation is complete when:

1. `BTST-LLM` starts with a decision card.
2. `EXEC-CHECKLIST` can be used without reading the full report.
3. Every formal stock row has evidence grade, data-quality label, trade bias, win-rate/payoff explanation, and invalidation guidance.
4. `stale_fallback` cannot be rendered as an execution upgrade.
5. Small samples and missing payoff fields are visible and downgrade the wording.
6. Tests cover grade computation, stale fallback behavior, missing payoff behavior, and document rendering.
7. Existing BTST generation commands still work for the 2026-05-29 bundle.

## 13. Self-Review

This design intentionally keeps the first implementation away from model-selection changes. The highest-value first step is to make existing evidence harder to misread and easier to review. That gives the team a cleaner foundation for later accuracy work.

The document has no unresolved blanks. The implementation is scoped to one shared enrichment module, existing document renderers, tests, and an optional ledger path. The main ambiguity is threshold tuning for `A/B/C/D`; the first version should choose conservative defaults and treat calibration as the source of future threshold changes.
