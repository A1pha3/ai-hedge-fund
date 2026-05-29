# BTST Decision System Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the BTST document bundle into a pre-trade decision pack with evidence grades, data-quality gates, opening action guidance, and a machine-readable review ledger.

**Architecture:** Add one shared decision-enrichment module under `src/paper_trading/` that computes row-level decision metadata from existing BTST artifacts. Keep `scripts/generate_btst_doc_bundle.py` as the renderer/orchestrator: it enriches resolved rows, renders decision cards and action sections, and optionally writes a review ledger. Keep the first implementation behavior-preserving for selection logic; all new labels govern how evidence is presented and how execution is constrained.

**Tech Stack:** Python 3.12, `uv`, pytest, existing BTST JSON/Markdown generation, standard library JSON/path handling

---

## File Structure

- Create: `src/paper_trading/btst_decision_enrichment.py`
  - Owns metric normalization, data-quality labels, evidence grades, trade bias, action matrix text, decision-card construction, and review-ledger rows.
- Create: `tests/test_btst_decision_enrichment.py`
  - Unit tests for the new enrichment rules.
- Modify: `scripts/generate_btst_doc_bundle.py`
  - Imports enrichment helpers, renders decision cards, renders evidence-grade stock rows, renders formal action matrices, and writes optional review-ledger artifacts.
- Modify: `tests/test_generate_btst_doc_bundle_script.py`
  - Integration tests that generated Markdown includes decision cards, evidence grades, stale-fallback downgrades, action matrices, and optional ledger output.
- Create: `scripts/fill_btst_decision_review_ledger.py`
  - Follow-up utility that fills realized next-day outcome fields in a pre-trade ledger when a daily price lookup is available.
- Create: `tests/test_fill_btst_decision_review_ledger_script.py`
  - Unit tests for filling realized outcome fields without network calls.
- Create: `scripts/generate_btst_decision_weekly_calibration.py`
  - Groups completed ledger rows by evidence grade, data quality, role, entry mode, and payoff divergence.
- Create: `tests/test_generate_btst_decision_weekly_calibration_script.py`
  - Unit tests for weekly grouping and Markdown output.

## Task 1: Add Decision Enrichment Unit Tests

**Files:**
- Create: `tests/test_btst_decision_enrichment.py`
- Task 2 creates: `src/paper_trading/btst_decision_enrichment.py`

- [ ] **Step 1: Write failing tests for metric normalization and evidence labels**

Create `tests/test_btst_decision_enrichment.py` with:

```python
from __future__ import annotations

from src.paper_trading.btst_decision_enrichment import (
    build_decision_card,
    enrich_btst_row,
    normalize_historical_metric,
)


def test_normalize_historical_metric_prefers_nested_prior() -> None:
    row = {
        "next_close_positive_rate": 0.25,
        "historical_prior": {
            "next_close_positive_rate": 0.72,
        },
    }

    assert normalize_historical_metric(row, "next_close_positive_rate") == 0.72


def test_enrich_btst_row_assigns_b_grade_for_confirmable_positive_payoff() -> None:
    row = {
        "ticker": "002222",
        "name": "物产金轮",
        "preferred_entry_mode": "confirm_then_hold_breakout",
        "score_target": 0.5433,
        "historical_prior": {
            "applied_scope": "same_ticker",
            "evaluable_count": 44,
            "next_close_positive_rate": 0.7273,
            "next_close_payoff_ratio": 1.0792,
            "next_close_expectancy": 0.0272,
            "next_close_profit_factor": 2.8793,
            "win_rate_payoff_divergence": False,
        },
    }

    enriched = enrich_btst_row(row, role="formal_selected", early_runner_status="exact")

    assert enriched["ticker"] == "002222"
    assert enriched["evidence_grade"] == "B"
    assert enriched["data_quality"] == "fresh"
    assert enriched["trade_bias"] == "confirmation_only"
    assert enriched["risk_posture"] == "reduced"
    assert enriched["must_confirm"] == "等待盘中延续确认后再执行，不做开盘无确认追价。"
    assert enriched["invalidate_if"] == "若开盘后无法形成延续确认，或快速冲高回落，则取消正式执行。"
    assert enriched["action_matrix"][0]["scenario"] == "开盘强且延续确认"
    assert enriched["metrics"]["win_rate"] == 0.7273


def test_enrich_btst_row_caps_grade_when_payoff_diverges() -> None:
    row = {
        "ticker": "002916",
        "preferred_entry_mode": "payoff_reconfirmation_only",
        "historical_prior": {
            "applied_scope": "same_ticker",
            "evaluable_count": 8,
            "next_close_positive_rate": 0.75,
            "next_close_payoff_ratio": 0.9217,
            "next_close_expectancy": 0.0248,
            "next_close_profit_factor": 2.7633,
            "win_rate_payoff_divergence": True,
        },
    }

    enriched = enrich_btst_row(row, role="formal_selected", early_runner_status="exact")

    assert enriched["evidence_grade"] == "C"
    assert enriched["data_quality"] == "usable_with_warning"
    assert enriched["trade_bias"] == "confirmation_only"
    assert "胜率和盈亏比/期望背离" in enriched["quality_notes"]
    assert "样本不足 10" in enriched["quality_notes"]


def test_enrich_btst_row_downgrades_stale_early_runner_reference() -> None:
    row = {
        "ticker": "300476",
        "preferred_entry_mode": "confirm_then_hold_breakout",
        "historical_prior": {
            "applied_scope": "same_ticker",
            "evaluable_count": 31,
            "next_close_positive_rate": 0.9355,
            "next_close_payoff_ratio": None,
        },
    }

    enriched = enrich_btst_row(
        row,
        role="early_runner_research",
        early_runner_status="stale_fallback",
    )

    assert enriched["evidence_grade"] == "D"
    assert enriched["data_quality"] == "stale_reference"
    assert enriched["trade_bias"] == "watch_only"
    assert enriched["risk_posture"] == "no_trade"
    assert "early-runner 非当日板" in enriched["quality_notes"]


def test_build_decision_card_selects_first_confirmable_candidate() -> None:
    rows = [
        enrich_btst_row(
            {
                "ticker": "002222",
                "preferred_entry_mode": "confirm_then_hold_breakout",
                "historical_prior": {
                    "applied_scope": "same_ticker",
                    "evaluable_count": 44,
                    "next_close_positive_rate": 0.7273,
                    "next_close_payoff_ratio": 1.0792,
                    "next_close_expectancy": 0.0272,
                    "win_rate_payoff_divergence": False,
                },
            },
            role="formal_selected",
            early_runner_status="exact",
        )
    ]

    card = build_decision_card(
        selected_rows=rows,
        early_runner_status="exact",
        signal_date="2026-05-28",
        next_trade_date="2026-05-29",
    )

    assert card["trade_bias"] == "confirmation_only"
    assert card["primary_ticker"] == "002222"
    assert card["evidence_grade"] == "B"
    assert card["data_quality"] == "fresh"
    assert card["risk_posture"] == "reduced"
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_btst_decision_enrichment.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.paper_trading.btst_decision_enrichment'`.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/test_btst_decision_enrichment.py
git commit -m "test(btst): define decision enrichment contract"
```

## Task 2: Implement Decision Enrichment Module

**Files:**
- Create: `src/paper_trading/btst_decision_enrichment.py`
- Test: `tests/test_btst_decision_enrichment.py`

- [ ] **Step 1: Create the enrichment module**

Create `src/paper_trading/btst_decision_enrichment.py`:

```python
from __future__ import annotations

from typing import Any


def _is_missing(value: Any) -> bool:
    return value in (None, "", [], {}, ())


def _to_float(value: Any) -> float | None:
    if _is_missing(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if _is_missing(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_historical_metric(row: dict[str, Any], key: str) -> Any:
    prior = dict(row.get("historical_prior") or {})
    prior_value = prior.get(key)
    if not _is_missing(prior_value):
        return prior_value
    return row.get(key)


def _scope_label(row: dict[str, Any]) -> str:
    return str(
        normalize_historical_metric(row, "applied_scope")
        or normalize_historical_metric(row, "scope")
        or ""
    )


def _metric_bundle(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "win_rate": _to_float(normalize_historical_metric(row, "next_close_positive_rate")),
        "payoff_ratio": _to_float(normalize_historical_metric(row, "next_close_payoff_ratio")),
        "expectancy": _to_float(normalize_historical_metric(row, "next_close_expectancy")),
        "profit_factor": _to_float(normalize_historical_metric(row, "next_close_profit_factor")),
        "evaluable_count": _to_int(normalize_historical_metric(row, "evaluable_count")),
        "sample_count": _to_int(normalize_historical_metric(row, "sample_count")),
        "scope": _scope_label(row),
        "win_rate_payoff_divergence": bool(
            normalize_historical_metric(row, "win_rate_payoff_divergence")
        ),
    }


def classify_data_quality(
    row: dict[str, Any],
    *,
    role: str,
    early_runner_status: str,
) -> tuple[str, list[str]]:
    metrics = _metric_bundle(row)
    notes: list[str] = []
    if role.startswith("early_runner") and early_runner_status == "stale_fallback":
        notes.append("early-runner 非当日板，只能作历史参考")
        return "stale_reference", notes
    if metrics["win_rate"] is None and metrics["payoff_ratio"] is None:
        notes.append("胜率和盈亏比均缺失")
        return "insufficient", notes
    if metrics["evaluable_count"] is not None and metrics["evaluable_count"] < 5:
        notes.append("样本不足 5，只能作弱参考")
        return "insufficient", notes
    if metrics["evaluable_count"] is not None and metrics["evaluable_count"] < 10:
        notes.append("样本不足 10，必须配合盘中确认")
        return "usable_with_warning", notes
    if metrics["payoff_ratio"] is None:
        notes.append("盈亏比缺失，不能确认赔率质量")
        return "usable_with_warning", notes
    if metrics["scope"] and metrics["scope"] != "same_ticker":
        notes.append("历史先验来自分桶样本，不是同票样本")
        return "usable_with_warning", notes
    return "fresh", notes


def _base_grade(metrics: dict[str, Any], data_quality: str) -> str:
    win_rate = metrics["win_rate"]
    payoff_ratio = metrics["payoff_ratio"]
    expectancy = metrics["expectancy"]
    if data_quality in {"stale_reference", "insufficient"}:
        return "D"
    if win_rate is None and payoff_ratio is None:
        return "D"
    if (
        win_rate is not None
        and win_rate >= 0.70
        and payoff_ratio is not None
        and payoff_ratio >= 1.50
        and (expectancy is None or expectancy >= 0)
    ):
        return "A"
    if (
        win_rate is not None
        and win_rate >= 0.55
        and payoff_ratio is not None
        and payoff_ratio >= 1.00
        and (expectancy is None or expectancy >= 0)
    ):
        return "B"
    if win_rate is not None and win_rate >= 0.45:
        return "C"
    if payoff_ratio is not None and payoff_ratio >= 1.50 and (expectancy is None or expectancy >= 0):
        return "C"
    return "D"


def _cap_grade_for_risks(grade: str, metrics: dict[str, Any], notes: list[str]) -> str:
    if metrics["win_rate_payoff_divergence"]:
        notes.append("胜率和盈亏比/期望背离，需降级确认")
        return "C" if grade in {"A", "B"} else grade
    if metrics["payoff_ratio"] is not None and metrics["payoff_ratio"] < 1.0 and grade in {"A", "B"}:
        notes.append("盈亏比低于 1.00，不能按高赔率处理")
        return "C"
    return grade


def _trade_bias_for_grade(role: str, grade: str, data_quality: str) -> str:
    if role != "formal_selected":
        return "watch_only"
    if data_quality in {"stale_reference", "insufficient"} or grade == "D":
        return "skip"
    if grade == "A":
        return "trade_allowed"
    return "confirmation_only"


def _risk_posture_for_bias(trade_bias: str, grade: str, data_quality: str) -> str:
    if trade_bias == "skip":
        return "no_trade"
    if trade_bias == "watch_only" or grade == "C" or data_quality == "usable_with_warning":
        return "micro"
    if trade_bias == "confirmation_only":
        return "reduced"
    return "normal"


def _must_confirm(preferred_entry_mode: str) -> str:
    if preferred_entry_mode == "payoff_reconfirmation_only":
        return "必须看到新的强确认，且不能只凭历史胜率入场。"
    if preferred_entry_mode == "intraday_confirmation_only":
        return "只做盘中确认后的机会，不预设隔夜执行。"
    return "等待盘中延续确认后再执行，不做开盘无确认追价。"


def _invalidate_if(preferred_entry_mode: str) -> str:
    if preferred_entry_mode == "payoff_reconfirmation_only":
        return "若确认不足或赔率背离继续存在，则取消正式执行。"
    if preferred_entry_mode == "intraday_confirmation_only":
        return "若盘中确认失败或收盘延续预期不足，则不隔夜持有。"
    return "若开盘后无法形成延续确认，或快速冲高回落，则取消正式执行。"


def _action_matrix(preferred_entry_mode: str) -> list[dict[str, str]]:
    return [
        {
            "scenario": "开盘强且延续确认",
            "action": _must_confirm(preferred_entry_mode),
        },
        {
            "scenario": "高开但确认失败",
            "action": "不追价，降级为观察。"
        },
        {
            "scenario": "低开后修复",
            "action": "只在原始触发逻辑仍成立时复审，不因低位反弹自动升级。"
        },
        {
            "scenario": "触发失效条件",
            "action": _invalidate_if(preferred_entry_mode),
        },
    ]


def enrich_btst_row(
    row: dict[str, Any],
    *,
    role: str,
    early_runner_status: str,
) -> dict[str, Any]:
    metrics = _metric_bundle(row)
    data_quality, notes = classify_data_quality(
        row,
        role=role,
        early_runner_status=early_runner_status,
    )
    grade = _cap_grade_for_risks(_base_grade(metrics, data_quality), metrics, notes)
    preferred_entry_mode = str(row.get("preferred_entry_mode") or "next_day_breakout_confirmation")
    trade_bias = _trade_bias_for_grade(role, grade, data_quality)
    return {
        "ticker": str(row.get("ticker") or ""),
        "name": str(row.get("name") or ""),
        "role": role,
        "source_row": dict(row),
        "preferred_entry_mode": preferred_entry_mode,
        "score_target": row.get("score_target", row.get("pre_score")),
        "evidence_grade": grade,
        "data_quality": data_quality,
        "trade_bias": trade_bias,
        "risk_posture": _risk_posture_for_bias(trade_bias, grade, data_quality),
        "must_confirm": _must_confirm(preferred_entry_mode),
        "invalidate_if": _invalidate_if(preferred_entry_mode),
        "quality_notes": notes,
        "metrics": metrics,
        "action_matrix": _action_matrix(preferred_entry_mode),
    }


def build_decision_card(
    *,
    selected_rows: list[dict[str, Any]],
    early_runner_status: str,
    signal_date: str,
    next_trade_date: str,
) -> dict[str, Any]:
    primary = next(
        (row for row in selected_rows if row.get("trade_bias") in {"trade_allowed", "confirmation_only"}),
        selected_rows[0] if selected_rows else {},
    )
    if not primary:
        return {
            "signal_date": signal_date,
            "next_trade_date": next_trade_date,
            "trade_bias": "skip",
            "primary_ticker": None,
            "evidence_grade": "D",
            "data_quality": "insufficient",
            "risk_posture": "no_trade",
            "must_confirm": "没有 formal selected 票，保持空仓观察。",
            "invalidate_if": "无可执行主线。",
            "early_runner_status": early_runner_status,
        }
    return {
        "signal_date": signal_date,
        "next_trade_date": next_trade_date,
        "trade_bias": primary["trade_bias"],
        "primary_ticker": primary["ticker"],
        "evidence_grade": primary["evidence_grade"],
        "data_quality": primary["data_quality"],
        "risk_posture": primary["risk_posture"],
        "must_confirm": primary["must_confirm"],
        "invalidate_if": primary["invalidate_if"],
        "early_runner_status": early_runner_status,
    }


def build_review_ledger_rows(
    *,
    signal_date: str,
    next_trade_date: str,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ledger_rows = []
    for row in rows:
        metrics = dict(row.get("metrics") or {})
        ledger_rows.append(
            {
                "signal_date": signal_date,
                "next_trade_date": next_trade_date,
                "ticker": row.get("ticker"),
                "role": row.get("role"),
                "evidence_grade": row.get("evidence_grade"),
                "data_quality": row.get("data_quality"),
                "trade_bias": row.get("trade_bias"),
                "risk_posture": row.get("risk_posture"),
                "win_rate": metrics.get("win_rate"),
                "payoff_ratio": metrics.get("payoff_ratio"),
                "expectancy": metrics.get("expectancy"),
                "entry_mode": row.get("preferred_entry_mode"),
                "must_confirm": row.get("must_confirm"),
                "invalidate_if": row.get("invalidate_if"),
                "realized_next_open": None,
                "realized_next_high": None,
                "realized_next_close": None,
                "review_label": None,
            }
        )
    return ledger_rows
```

- [ ] **Step 2: Run unit tests**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_btst_decision_enrichment.py -q
```

Expected: PASS, with all tests in `tests/test_btst_decision_enrichment.py` passing.

- [ ] **Step 3: Commit the enrichment module**

```bash
git add src/paper_trading/btst_decision_enrichment.py tests/test_btst_decision_enrichment.py
git commit -m "feat(btst): add decision enrichment rules"
```

## Task 3: Add Decision Card Rendering to Document Bundle

**Files:**
- Modify: `tests/test_generate_btst_doc_bundle_script.py`
- Modify: `scripts/generate_btst_doc_bundle.py`
- Uses: `src/paper_trading/btst_decision_enrichment.py`

- [ ] **Step 1: Add failing integration assertions for the decision card**

In `tests/test_generate_btst_doc_bundle_script.py`, update `test_generate_btst_doc_bundle_writes_early_runner_sections` by adding richer historical priors to the existing selected and watch rows:

```python
"historical_prior": {
    "applied_scope": "same_ticker",
    "evaluable_count": 18,
    "next_close_positive_rate": 0.6667,
    "next_close_payoff_ratio": 1.42,
    "next_close_expectancy": 0.021,
    "next_close_profit_factor": 2.4,
    "win_rate_payoff_divergence": False,
},
```

Then add these assertions after `llm_doc` is read:

```python
assert "## 30 秒决策卡" in llm_doc
assert "- 交易倾向：`confirmation_only`" in llm_doc
assert "- 主票：`300054`" in llm_doc
assert "- 证据等级：`B`；数据质量：`fresh`；风险姿态：`reduced`。" in llm_doc
assert "- 必须确认：等待盘中延续确认后再执行，不做开盘无确认追价。" in llm_doc
assert "- 失效条件：若开盘后无法形成延续确认，或快速冲高回落，则取消正式执行。" in llm_doc
```

Add these assertions after `checklist_doc` is read:

```python
assert "## 30 秒决策卡" in checklist_doc
assert "- 主票：`300054`" in checklist_doc
assert "- 交易倾向：`confirmation_only`" in checklist_doc
```

- [ ] **Step 2: Run the integration test and verify it fails**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_generate_btst_doc_bundle_script.py::test_generate_btst_doc_bundle_writes_early_runner_sections -q
```

Expected: FAIL because the generated documents do not include `## 30 秒决策卡`.

- [ ] **Step 3: Add renderer helpers and imports**

In `scripts/generate_btst_doc_bundle.py`, add this import near the top:

```python
from src.paper_trading.btst_decision_enrichment import (
    build_decision_card,
    enrich_btst_row,
)
```

Add helper functions near `_stock_bullets`:

```python
def _enriched_stock_label(row: dict[str, Any]) -> str:
    ticker = str(row.get("ticker") or "").strip()
    name = str(row.get("name") or "").strip()
    return f"{ticker} {name}".strip()


def _enrich_formal_rows(rows: list[dict[str, Any]], *, role: str, early_runner_status: str) -> list[dict[str, Any]]:
    return [
        enrich_btst_row(row, role=role, early_runner_status=early_runner_status)
        for row in rows
    ]


def _render_decision_card(card: dict[str, Any]) -> list[str]:
    return [
        "## 30 秒决策卡",
        "",
        f"- 交易倾向：`{card.get('trade_bias')}`。",
        f"- 主票：`{card.get('primary_ticker') or 'n/a'}`。",
        f"- 证据等级：`{card.get('evidence_grade')}`；数据质量：`{card.get('data_quality')}`；风险姿态：`{card.get('risk_posture')}`。",
        f"- 必须确认：{card.get('must_confirm')}",
        f"- 失效条件：{card.get('invalidate_if')}",
        f"- early-runner 状态：`{card.get('early_runner_status')}`。",
    ]
```

- [ ] **Step 4: Render the decision card in `BTST-LLM`**

In `_render_llm_doc`, after `formal_rows` and `profile_name` are computed, add:

```python
early_status = str(early_runner.get("status") or "unavailable")
enriched_selected = _enrich_formal_rows(
    selected_actions,
    role="formal_selected",
    early_runner_status=early_status,
)
decision_card = build_decision_card(
    selected_rows=enriched_selected,
    early_runner_status=early_status,
    signal_date=str(brief.get("trade_date") or ""),
    next_trade_date=str(brief.get("next_trade_date") or ""),
)
```

Then insert the decision card immediately after the core conclusion block and before `_render_strategy_threshold_lines`:

```python
lines.extend(_render_decision_card(decision_card))
lines.extend([""])
```

- [ ] **Step 5: Render the decision card in `EXEC-CHECKLIST`**

In `_render_checklist_doc`, after `selected_actions` and `watch_actions` are computed, add the same card construction:

```python
early_status = str(early_runner.get("status") or "unavailable")
enriched_selected = _enrich_formal_rows(
    selected_actions,
    role="formal_selected",
    early_runner_status=early_status,
)
decision_card = build_decision_card(
    selected_rows=enriched_selected,
    early_runner_status=early_status,
    signal_date=str(brief.get("trade_date") or ""),
    next_trade_date=str(brief.get("next_trade_date") or ""),
)
```

Then insert:

```python
lines.extend(_render_decision_card(decision_card))
lines.extend([""])
```

right after the initial signal-date header block.

- [ ] **Step 6: Run the focused integration test**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_generate_btst_doc_bundle_script.py::test_generate_btst_doc_bundle_writes_early_runner_sections -q
```

Expected: PASS.

- [ ] **Step 7: Commit the decision card renderer**

```bash
git add scripts/generate_btst_doc_bundle.py tests/test_generate_btst_doc_bundle_script.py
git commit -m "feat(btst-docs): render pretrade decision card"
```

## Task 4: Render Evidence Grades and Action Matrices

**Files:**
- Modify: `tests/test_generate_btst_doc_bundle_script.py`
- Modify: `scripts/generate_btst_doc_bundle.py`

- [ ] **Step 1: Add failing assertions for grades and action matrix**

In `tests/test_generate_btst_doc_bundle_script.py`, extend `test_generate_btst_doc_bundle_writes_early_runner_sections`:

```python
assert "证据 `B`，数据 `fresh`，倾向 `confirmation_only`，风险 `reduced`" in llm_doc
assert "## 正式执行动作矩阵" in checklist_doc
assert "### 300054 鼎龙股份" in checklist_doc
assert "| 开盘强且延续确认 | 等待盘中延续确认后再执行，不做开盘无确认追价。 |" in checklist_doc
assert "| 触发失效条件 | 若开盘后无法形成延续确认，或快速冲高回落，则取消正式执行。 |" in checklist_doc
```

- [ ] **Step 2: Run the focused integration test and verify it fails**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_generate_btst_doc_bundle_script.py::test_generate_btst_doc_bundle_writes_early_runner_sections -q
```

Expected: FAIL because evidence-grade text and action matrix are not rendered yet.

- [ ] **Step 3: Add enriched stock row renderer**

In `scripts/generate_btst_doc_bundle.py`, add:

```python
def _render_enriched_stock_bullets(rows: list[dict[str, Any]], *, limit: int) -> list[str]:
    lines: list[str] = []
    for row in rows[:limit]:
        metrics = dict(row.get("metrics") or {})
        quality_notes = list(row.get("quality_notes") or [])
        note_suffix = f"，质量提示：{'；'.join(str(note) for note in quality_notes)}" if quality_notes else ""
        lines.append(
            f"- `{_enriched_stock_label(row)}`：模式 `{row.get('preferred_entry_mode')}`，"
            f"分数 `{_fmt_num(row.get('score_target'), 4)}`，"
            f"证据 `{row.get('evidence_grade')}`，数据 `{row.get('data_quality')}`，"
            f"倾向 `{row.get('trade_bias')}`，风险 `{row.get('risk_posture')}`，"
            f"收盘胜率 `{_fmt_pct(metrics.get('win_rate'))}`，"
            f"盈亏比 `{_fmt_num(metrics.get('payoff_ratio'), 2)}`{note_suffix}。"
        )
    return lines or ["- 无。"]


def _render_action_matrix_sections(rows: list[dict[str, Any]], *, limit: int = 3) -> list[str]:
    lines = ["## 正式执行动作矩阵", ""]
    if not rows:
        lines.append("- 当前没有正式执行票。")
        return lines
    for row in rows[:limit]:
        lines.extend(
            [
                f"### {_enriched_stock_label(row)}",
                "",
                "| 场景 | 动作 |",
                "| --- | --- |",
            ]
        )
        for item in list(row.get("action_matrix") or []):
            lines.append(f"| {item.get('scenario')} | {item.get('action')} |")
        lines.append("")
    return lines
```

- [ ] **Step 4: Use enriched rows in `BTST-LLM` formal sections**

In `_render_llm_doc`, replace the formal execution layer render:

```python
lines.extend(_stock_bullets(selected_actions, limit=5, include_payoff=True))
```

with:

```python
lines.extend(_render_enriched_stock_bullets(enriched_selected, limit=5))
```

Then compute enriched watch rows:

```python
enriched_watch = _enrich_formal_rows(
    watch_actions,
    role="formal_watch",
    early_runner_status=early_status,
)
```

Replace:

```python
lines.extend(_stock_bullets(watch_actions, limit=8, include_payoff=True))
```

with:

```python
lines.extend(_render_enriched_stock_bullets(enriched_watch, limit=8))
```

- [ ] **Step 5: Add action matrix to checklist**

In `_render_checklist_doc`, after formal execution rows and before `## 正式观察顺序`, insert:

```python
lines.extend([""])
lines.extend(_render_action_matrix_sections(enriched_selected, limit=3))
```

- [ ] **Step 6: Run focused integration test**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_generate_btst_doc_bundle_script.py::test_generate_btst_doc_bundle_writes_early_runner_sections -q
```

Expected: PASS.

- [ ] **Step 7: Run all document-bundle tests**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_generate_btst_doc_bundle_script.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit the evidence-grade renderer**

```bash
git add scripts/generate_btst_doc_bundle.py tests/test_generate_btst_doc_bundle_script.py
git commit -m "feat(btst-docs): render evidence grades and action matrix"
```

## Task 5: Enforce Stale and Weak-Evidence Wording in Early-Warning Docs

**Files:**
- Modify: `tests/test_generate_btst_doc_bundle_script.py`
- Modify: `scripts/generate_btst_doc_bundle.py`

- [ ] **Step 1: Add failing stale-fallback integration assertions**

In `test_generate_btst_doc_bundle_marks_stale_overlap_as_reference_only`, add:

```python
llm_doc = (output_dir / "BTST-LLM-20260526.md").read_text(encoding="utf-8")
assert "early-runner 状态：`stale_fallback`" in llm_doc
assert "stale_reference" in llm_doc
assert "不能直接当成当日交集优先" in llm_doc
```

In `test_generate_btst_doc_bundle_surfaces_research_only_confirmation_pool`, add:

```python
early_warning_doc = (output_dir / "BTST-20260527-EARLY-WARNING.md").read_text(encoding="utf-8")
assert "证据 `D`" in early_warning_doc
assert "数据 `insufficient`" in early_warning_doc
assert "倾向 `watch_only`" in early_warning_doc
```

- [ ] **Step 2: Run targeted tests and verify failure**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_generate_btst_doc_bundle_script.py -k "stale_overlap or research_only_confirmation_pool" -q
```

Expected: FAIL because early-warning rows still use `_stock_bullets()`.

- [ ] **Step 3: Enrich early-runner rows before rendering**

In `scripts/generate_btst_doc_bundle.py`, add:

```python
def _enrich_early_runner_rows(
    rows: list[dict[str, Any]],
    *,
    role: str,
    early_runner_status: str,
) -> list[dict[str, Any]]:
    return [
        enrich_btst_row(row, role=role, early_runner_status=early_runner_status)
        for row in rows
    ]
```

In `_render_early_warning_doc`, compute:

```python
early_status = str(early_runner.get("status") or "unavailable")
enriched_priority = _enrich_early_runner_rows(
    _safe_rows(early_runner.get("priority")),
    role="early_runner_priority",
    early_runner_status=early_status,
)
enriched_watchlist = _enrich_early_runner_rows(
    _safe_rows(early_runner.get("watchlist")),
    role="early_runner_watchlist",
    early_runner_status=early_status,
)
enriched_second_entry = _enrich_early_runner_rows(
    _safe_rows(early_runner.get("second_entry")),
    role="early_runner_second_entry",
    early_runner_status=early_status,
)
enriched_research = _enrich_early_runner_rows(
    research_confirmation,
    role="early_runner_research",
    early_runner_status=early_status,
)
```

Then replace these render calls:

```python
lines.extend(_stock_bullets(_safe_rows(early_runner.get("priority")), limit=6, include_payoff=True))
lines.extend(_stock_bullets(_safe_rows(early_runner.get("watchlist")), limit=8, include_payoff=True))
lines.extend(_stock_bullets(_safe_rows(early_runner.get("second_entry")), limit=8, include_payoff=True))
lines.extend(_stock_bullets(research_confirmation, limit=8, include_payoff=True))
```

with:

```python
lines.extend(_render_enriched_stock_bullets(enriched_priority, limit=6))
lines.extend(_render_enriched_stock_bullets(enriched_watchlist, limit=8))
lines.extend(_render_enriched_stock_bullets(enriched_second_entry, limit=8))
lines.extend(_render_enriched_stock_bullets(enriched_research, limit=8))
```

- [ ] **Step 4: Run targeted tests**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_generate_btst_doc_bundle_script.py -k "stale_overlap or research_only_confirmation_pool" -q
```

Expected: PASS.

- [ ] **Step 5: Commit stale and weak-evidence rendering**

```bash
git add scripts/generate_btst_doc_bundle.py tests/test_generate_btst_doc_bundle_script.py
git commit -m "feat(btst-docs): gate stale and weak evidence wording"
```

## Task 6: Add Optional Review Ledger Output

**Files:**
- Modify: `tests/test_generate_btst_doc_bundle_script.py`
- Modify: `scripts/generate_btst_doc_bundle.py`
- Uses: `src/paper_trading/btst_decision_enrichment.py`

- [ ] **Step 1: Add failing test for ledger output**

Add a test to `tests/test_generate_btst_doc_bundle_script.py`:

```python
def test_generate_btst_doc_bundle_writes_review_ledger_when_requested(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_20260526_20260526_live_m2_7_short_trade_only_20260527_plan"
    brief_path = report_dir / "btst_next_day_trade_brief_latest.json"
    _write_json(
        report_dir / "session_summary.json",
        {
            "trade_date": "2026-05-26",
            "selection_target": "short_trade_only",
            "btst_followup": {"brief_json": brief_path.as_posix()},
        },
    )
    _write_json(
        brief_path,
        {
            "trade_date": "2026-05-26",
            "next_trade_date": "2026-05-27",
            "selection_target": "short_trade_only",
            "selected_actions": [
                {
                    "ticker": "300054",
                    "preferred_entry_mode": "confirm_then_hold_breakout",
                    "historical_prior": {
                        "applied_scope": "same_ticker",
                        "evaluable_count": 18,
                        "next_close_positive_rate": 0.6667,
                        "next_close_payoff_ratio": 1.42,
                    },
                }
            ],
            "watch_actions": [],
            "opportunity_actions": [],
        },
    )
    _write_json(
        reports_root / "btst_full_report_20260526.json",
        {
            "trade_date": "20260526",
            "next_date": "20260527",
            "pool_size": 10,
            "selected_count": 1,
            "near_miss_count": 0,
            "high_confidence": [],
        },
    )
    _write_json(reports_root / "btst_early_runner_v1_latest.json", {"daily_boards": [{"trade_date": "2026-05-26"}]})

    output_dir = tmp_path / "outputs"
    result = generate_btst_doc_bundle(
        "20260526",
        reports_root=reports_root,
        output_dir=output_dir,
        refresh_early_runner=False,
        write_review_ledger=True,
    )

    ledger_path = output_dir / "20260526-btst-decision-review-ledger.json"
    assert result["review_ledger_json_path"] == ledger_path.as_posix()
    payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert payload["signal_date"] == "2026-05-26"
    assert payload["next_trade_date"] == "2026-05-27"
    assert payload["rows"][0]["ticker"] == "300054"
    assert payload["rows"][0]["evidence_grade"] == "B"
    assert payload["rows"][0]["realized_next_close"] is None
```

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_generate_btst_doc_bundle_script.py::test_generate_btst_doc_bundle_writes_review_ledger_when_requested -q
```

Expected: FAIL because `write_review_ledger` is not an accepted argument.

- [ ] **Step 3: Add review-ledger support to generator signature**

In `scripts/generate_btst_doc_bundle.py`, import:

```python
from src.paper_trading.btst_decision_enrichment import (
    build_decision_card,
    build_review_ledger_rows,
    enrich_btst_row,
)
```

Update `generate_btst_doc_bundle` signature:

```python
def generate_btst_doc_bundle(
    signal_date: str,
    *,
    reports_root: str | Path = REPORTS_DIR,
    output_dir: str | Path | None = None,
    report_dir: str | Path | None = None,
    refresh_early_runner: bool = True,
    include_extra_warning_docs: bool = True,
    strategy_thresholds_config_path: str | Path | None = None,
    strategy_thresholds_profile: str = DEFAULT_STRATEGY_THRESHOLDS_PROFILE,
    write_review_ledger: bool = False,
) -> dict[str, Any]:
```

Before `return`, build and write the ledger:

```python
review_ledger_json_path = None
if write_review_ledger:
    early_status = str(early_runner.get("status") or "unavailable")
    ledger_selected = _enrich_formal_rows(
        selected_rows,
        role="formal_selected",
        early_runner_status=early_status,
    )
    ledger_watch = _enrich_formal_rows(
        watch_rows,
        role="formal_watch",
        early_runner_status=early_status,
    )
    ledger_rows = build_review_ledger_rows(
        signal_date=str(brief.get("trade_date") or signal_date_iso),
        next_trade_date=str(brief.get("next_trade_date") or ""),
        rows=[*ledger_selected, *ledger_watch],
    )
    review_ledger_json_path = target_output_dir / f"{signal_date_compact}-btst-decision-review-ledger.json"
    _write_text(
        review_ledger_json_path,
        json.dumps(
            {
                "signal_date": str(brief.get("trade_date") or signal_date_iso),
                "next_trade_date": str(brief.get("next_trade_date") or ""),
                "rows": ledger_rows,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
```

In the returned dict, add:

```python
"review_ledger_json_path": review_ledger_json_path.as_posix() if review_ledger_json_path else None,
```

- [ ] **Step 4: Add CLI flag**

In `_build_arg_parser`, add:

```python
parser.add_argument("--write-review-ledger", action="store_true")
```

Where `generate_btst_doc_bundle()` is called from CLI, pass:

```python
write_review_ledger=args.write_review_ledger,
```

- [ ] **Step 5: Run ledger test**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_generate_btst_doc_bundle_script.py::test_generate_btst_doc_bundle_writes_review_ledger_when_requested -q
```

Expected: PASS.

- [ ] **Step 6: Commit review-ledger output**

```bash
git add scripts/generate_btst_doc_bundle.py tests/test_generate_btst_doc_bundle_script.py
git commit -m "feat(btst-docs): write optional decision review ledger"
```

## Task 7: Add Post-Close Ledger Fill Utility

**Files:**
- Create: `scripts/fill_btst_decision_review_ledger.py`
- Create: `tests/test_fill_btst_decision_review_ledger_script.py`

- [ ] **Step 1: Write failing tests for filling realized outcomes**

Create `tests/test_fill_btst_decision_review_ledger_script.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from scripts.fill_btst_decision_review_ledger import fill_review_ledger


def test_fill_review_ledger_updates_realized_fields_and_review_label(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.json"
    price_path = tmp_path / "prices.json"
    ledger_path.write_text(
        json.dumps(
            {
                "signal_date": "2026-05-28",
                "next_trade_date": "2026-05-29",
                "rows": [
                    {
                        "ticker": "002222",
                        "role": "formal_selected",
                        "evidence_grade": "B",
                        "trade_bias": "confirmation_only",
                        "realized_next_open": None,
                        "realized_next_high": None,
                        "realized_next_close": None,
                        "review_label": None,
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    price_path.write_text(
        json.dumps(
            {
                "002222": {
                    "next_open_return": -0.008,
                    "next_high_return": 0.034,
                    "next_close_return": 0.021,
                }
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = fill_review_ledger(
        ledger_path=ledger_path,
        realized_prices_path=price_path,
        output_path=tmp_path / "filled.json",
    )

    row = result["rows"][0]
    assert row["realized_next_open"] == -0.008
    assert row["realized_next_high"] == 0.034
    assert row["realized_next_close"] == 0.021
    assert row["review_label"] == "close_positive"
    assert (tmp_path / "filled.json").exists()


def test_fill_review_ledger_marks_missing_realized_price(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.json"
    price_path = tmp_path / "prices.json"
    ledger_path.write_text(
        json.dumps(
            {
                "signal_date": "2026-05-28",
                "next_trade_date": "2026-05-29",
                "rows": [{"ticker": "002222", "review_label": None}],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    price_path.write_text("{}\n", encoding="utf-8")

    result = fill_review_ledger(ledger_path=ledger_path, realized_prices_path=price_path)

    assert result["rows"][0]["review_label"] == "missing_realized_price"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_fill_btst_decision_review_ledger_script.py -q
```

Expected: FAIL because `scripts/fill_btst_decision_review_ledger.py` does not exist.

- [ ] **Step 3: Implement utility**

Create `scripts/fill_btst_decision_review_ledger.py`:

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read_json(path: str | Path) -> dict[str, Any]:
    return dict(json.loads(Path(path).read_text(encoding="utf-8")))


def _review_label(close_return: Any) -> str:
    if close_return is None:
        return "missing_realized_price"
    try:
        return "close_positive" if float(close_return) > 0 else "close_non_positive"
    except (TypeError, ValueError):
        return "missing_realized_price"


def fill_review_ledger(
    *,
    ledger_path: str | Path,
    realized_prices_path: str | Path,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    payload = _read_json(ledger_path)
    prices = _read_json(realized_prices_path)
    rows = []
    for row in list(payload.get("rows") or []):
        updated = dict(row)
        ticker = str(updated.get("ticker") or "")
        price = dict(prices.get(ticker) or {})
        if price:
            updated["realized_next_open"] = price.get("next_open_return")
            updated["realized_next_high"] = price.get("next_high_return")
            updated["realized_next_close"] = price.get("next_close_return")
            updated["review_label"] = _review_label(price.get("next_close_return"))
        else:
            updated["review_label"] = "missing_realized_price"
        rows.append(updated)
    result = dict(payload)
    result["rows"] = rows
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger-path", required=True)
    parser.add_argument("--realized-prices-path", required=True)
    parser.add_argument("--output-path")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    result = fill_review_ledger(
        ledger_path=args.ledger_path,
        realized_prices_path=args.realized_prices_path,
        output_path=args.output_path,
    )
    print(json.dumps({"status": "filled", "row_count": len(result.get("rows") or [])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run utility tests**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_fill_btst_decision_review_ledger_script.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit post-close ledger filler**

```bash
git add scripts/fill_btst_decision_review_ledger.py tests/test_fill_btst_decision_review_ledger_script.py
git commit -m "feat(btst): add decision ledger fill utility"
```

## Task 8: Add Weekly Calibration Report

**Files:**
- Create: `scripts/generate_btst_decision_weekly_calibration.py`
- Create: `tests/test_generate_btst_decision_weekly_calibration_script.py`

- [ ] **Step 1: Write failing calibration tests**

Create `tests/test_generate_btst_decision_weekly_calibration_script.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_btst_decision_weekly_calibration import (
    build_weekly_calibration,
    render_weekly_calibration_markdown,
)


def test_build_weekly_calibration_groups_by_grade_and_data_quality(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "ticker": "002222",
                        "evidence_grade": "B",
                        "data_quality": "fresh",
                        "role": "formal_selected",
                        "entry_mode": "confirm_then_hold_breakout",
                        "review_label": "close_positive",
                    },
                    {
                        "ticker": "002916",
                        "evidence_grade": "C",
                        "data_quality": "usable_with_warning",
                        "role": "formal_selected",
                        "entry_mode": "payoff_reconfirmation_only",
                        "review_label": "close_non_positive",
                    },
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = build_weekly_calibration([ledger_path])

    assert result["total_rows"] == 2
    assert result["by_evidence_grade"]["B"]["row_count"] == 1
    assert result["by_evidence_grade"]["B"]["close_positive_rate"] == 1.0
    assert result["by_data_quality"]["usable_with_warning"]["close_positive_rate"] == 0.0


def test_render_weekly_calibration_markdown() -> None:
    markdown = render_weekly_calibration_markdown(
        {
            "total_rows": 1,
            "by_evidence_grade": {"B": {"row_count": 1, "close_positive_count": 1, "close_positive_rate": 1.0}},
            "by_data_quality": {"fresh": {"row_count": 1, "close_positive_count": 1, "close_positive_rate": 1.0}},
            "by_role": {},
            "by_entry_mode": {},
        }
    )

    assert "# BTST Decision Weekly Calibration" in markdown
    assert "| B | 1 | 1 | 100.00% |" in markdown
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_generate_btst_decision_weekly_calibration_script.py -q
```

Expected: FAIL because the calibration script does not exist.

- [ ] **Step 3: Implement calibration script**

Create `scripts/generate_btst_decision_weekly_calibration.py`:

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read_rows(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [dict(row) for row in list(payload.get("rows") or [])]


def _summarize_group(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        label = str(row.get(key) or "unknown")
        grouped.setdefault(label, []).append(row)
    summary: dict[str, dict[str, Any]] = {}
    for label, label_rows in grouped.items():
        positives = sum(1 for row in label_rows if row.get("review_label") == "close_positive")
        summary[label] = {
            "row_count": len(label_rows),
            "close_positive_count": positives,
            "close_positive_rate": round(positives / len(label_rows), 4) if label_rows else None,
        }
    return summary


def build_weekly_calibration(ledger_paths: list[str | Path]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for path in ledger_paths:
        rows.extend(_read_rows(path))
    return {
        "total_rows": len(rows),
        "by_evidence_grade": _summarize_group(rows, "evidence_grade"),
        "by_data_quality": _summarize_group(rows, "data_quality"),
        "by_role": _summarize_group(rows, "role"),
        "by_entry_mode": _summarize_group(rows, "entry_mode"),
    }


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.2f}%"


def _render_group(title: str, rows: dict[str, dict[str, Any]]) -> list[str]:
    lines = [f"## {title}", "", "| 分组 | 样本 | 收盘为正 | 收盘胜率 |", "| --- | ---: | ---: | ---: |"]
    for label in sorted(rows):
        item = rows[label]
        lines.append(
            f"| {label} | {item.get('row_count')} | {item.get('close_positive_count')} | {_fmt_pct(item.get('close_positive_rate'))} |"
        )
    return lines


def render_weekly_calibration_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# BTST Decision Weekly Calibration",
        "",
        f"- total_rows: `{summary.get('total_rows')}`",
        "",
    ]
    lines.extend(_render_group("By Evidence Grade", dict(summary.get("by_evidence_grade") or {})))
    lines.extend([""])
    lines.extend(_render_group("By Data Quality", dict(summary.get("by_data_quality") or {})))
    lines.extend([""])
    lines.extend(_render_group("By Role", dict(summary.get("by_role") or {})))
    lines.extend([""])
    lines.extend(_render_group("By Entry Mode", dict(summary.get("by_entry_mode") or {})))
    return "\n".join(lines) + "\n"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("ledger_paths", nargs="+")
    parser.add_argument("--output-json")
    parser.add_argument("--output-md")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    summary = build_weekly_calibration(args.ledger_paths)
    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(render_weekly_calibration_markdown(summary), encoding="utf-8")
    print(json.dumps({"status": "generated", "total_rows": summary["total_rows"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run calibration tests**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_generate_btst_decision_weekly_calibration_script.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit weekly calibration**

```bash
git add scripts/generate_btst_decision_weekly_calibration.py tests/test_generate_btst_decision_weekly_calibration_script.py
git commit -m "feat(btst): add decision weekly calibration report"
```

## Task 9: Regenerate the 2026-05-29 Bundle and Verify End-to-End

**Files:**
- Regenerate outputs under `outputs/202605/20260529/`
- Verify code and tests from previous tasks

- [ ] **Step 1: Run the full related test set**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_btst_decision_enrichment.py tests/test_generate_btst_doc_bundle_script.py tests/test_fill_btst_decision_review_ledger_script.py tests/test_generate_btst_decision_weekly_calibration_script.py tests/test_btst_latest_followup_utils.py tests/test_generate_btst_opening_watch_card_script.py
```

Expected: PASS for all selected tests.

- [ ] **Step 2: Regenerate the target BTST bundle with review ledger**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && source .env && uv run python scripts/generate_btst_doc_bundle.py --signal-date 20260528 --output-dir outputs/202605/20260529 --strategy-thresholds-config config/btst_strategy_thresholds.json --no-refresh-early-runner --write-review-ledger
```

Expected:

```text
"status": "generated"
"output_dir": "/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/outputs/202605/20260529"
"review_ledger_json_path": "/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/outputs/202605/20260529/20260528-btst-decision-review-ledger.json"
```

- [ ] **Step 3: Spot-check generated documents**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && rg -n "30 秒决策卡|证据 `|数据 `|正式执行动作矩阵|stale_reference|review-ledger|002222|002916|600176" outputs/202605/20260529
```

Expected:

1. `BTST-LLM-20260528.md` contains `## 30 秒决策卡`.
2. `BTST-20260528-EXEC-CHECKLIST.md` contains `## 正式执行动作矩阵`.
3. `BTST-20260528-EARLY-WARNING.md` shows stale/reference wording for non-actionable early-runner content.
4. The ledger JSON exists and contains rows for `002222`, `002916`, and `600176`.

- [ ] **Step 4: Inspect ledger JSON**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run python - <<'PY'
import json
from pathlib import Path

path = Path("outputs/202605/20260529/20260528-btst-decision-review-ledger.json")
payload = json.loads(path.read_text(encoding="utf-8"))
print(payload["signal_date"], payload["next_trade_date"], len(payload["rows"]))
for row in payload["rows"][:5]:
    print(row["ticker"], row["role"], row["evidence_grade"], row["data_quality"], row["trade_bias"], row["risk_posture"])
PY
```

Expected output includes:

```text
2026-05-28 2026-05-29
002222 formal_selected B fresh confirmation_only reduced
```

- [ ] **Step 5: Commit generated-system integration**

```bash
git add \
  src/paper_trading/btst_decision_enrichment.py \
  scripts/generate_btst_doc_bundle.py \
  scripts/fill_btst_decision_review_ledger.py \
  scripts/generate_btst_decision_weekly_calibration.py \
  tests/test_btst_decision_enrichment.py \
  tests/test_generate_btst_doc_bundle_script.py \
  tests/test_fill_btst_decision_review_ledger_script.py \
  tests/test_generate_btst_decision_weekly_calibration_script.py \
  outputs/202605/20260529/BTST-20260528.md \
  outputs/202605/20260529/BTST-LLM-20260528.md \
  outputs/202605/20260529/BTST-20260528-EXEC-CHECKLIST.md \
  outputs/202605/20260529/BTST-20260528-EARLY-WARNING.md \
  outputs/202605/20260529/BTST-20260528-EARLY-WARNING-CARD.md \
  outputs/202605/20260529/20260528-两套交易计划通俗说明.md \
  outputs/202605/20260529/20260528-两套交易计划论坛短版.md \
  outputs/202605/20260529/20260528-btst-decision-review-ledger.json
git commit -m "feat(btst-docs): upgrade BTST bundle into decision pack"
```

## Self-Review

### Spec Coverage

- Decision card: Tasks 3 and 9.
- Evidence grades: Tasks 1, 2, 4, and 5.
- Data-quality gates: Tasks 1, 2, and 5.
- Action matrix: Task 4.
- Review ledger: Tasks 6 and 7.
- Weekly calibration: Task 8.
- 2026-05-29 bundle regeneration: Task 9.

### Scope Notes

This plan does not change the core BTST selection model. It changes evidence presentation, decision constraints, and review artifacts. That matches the design requirement to improve readability, practical execution, and accuracy governance before touching alpha selection logic.

### Type and Naming Consistency

The plan consistently uses:

- `evidence_grade`
- `data_quality`
- `trade_bias`
- `risk_posture`
- `must_confirm`
- `invalidate_if`
- `review_ledger_json_path`

These names are introduced in Task 2 and reused by renderers, ledger output, and calibration scripts.
