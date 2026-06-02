# BTST Regime Gate + Gap Overlay v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (1) Make `BTST-YYYYMMDD-EXEC-CHECKLIST.md` surface the same *global guardrails* (including BTST 0422 P7 gap overlay policy) that the premarket card already shows; (2) persist a minimal `market_state` + `btst_regime_gate` payload into `data/reports/btst_full_report_YYYYMMDD.json` so monthly audits can stratify by regime even when only the rule report is present.

**Architecture:**
- Checklist docs already load `session_summary.json` + optional `priority_board_json`. We will pass `session_summary` into `_render_checklist_doc()` and render a dedicated `## 全局 Guardrails` section using (a) `priority_board.global_guardrails` when present, and (b) `session_summary.btst_0422_flags` for the P7 gap overlay policy string (replayable because flags are persisted).
- Rule-based `btst_full_report.py` will add a strictly-labeled `market_state_proxy`-style payload computed from its existing `results` dataframe (breadth, mean return, limit up/down counts). It is **report-only** and **not used for enforcement**.

**Tech Stack:** Python 3.11+, pytest, existing BTST doc-bundle generator (`scripts/generate_btst_doc_bundle.py`).

---

## File / Responsibility Map (locked)

- **Modify:** `scripts/generate_btst_doc_bundle.py`
  - Pass `session_summary` into `_render_checklist_doc(...)`.
  - Add `_render_global_guardrails_lines(priority_board, session_summary)` and insert it into checklist doc rendering.
  - Add `_btst_0422_p7_gap_overlay_guardrail_from_flags(flags)` to format the same gap-overlay string as premarket card, but sourced from persisted flags.

- **Modify tests:** `tests/test_generate_btst_doc_bundle_script.py`
  - Extend the existing `_generate_btst_doc_bundle_gate_outputs(...)` fixture payloads to include:
    - `session_summary.btst_0422_flags.p7_gap_overlay_*`
    - `priority_board.global_guardrails`
  - Assert the checklist doc contains `## 全局 Guardrails` and the expected guardrail lines.

- **Modify:** `scripts/btst_full_report.py`
  - Add pure helper functions to compute a minimal `market_state` proxy and a derived `btst_regime_gate` proxy.
  - Persist these into the emitted `btst_full_report_<trade_date>.json`.

- **Create tests:** `tests/test_btst_full_report_market_state_proxy.py`
  - Unit test the proxy computation without any Tushare calls.

---

### Task 1: Surface Global Guardrails (incl. P7 Gap Overlay) in EXEC-CHECKLIST

**Files:**
- Modify: `scripts/generate_btst_doc_bundle.py`
- Modify: `tests/test_generate_btst_doc_bundle_script.py`

- [ ] **Step 1: Write a failing test that expects guardrails in the checklist doc**

In `tests/test_generate_btst_doc_bundle_script.py`, update the helper fixture `_generate_btst_doc_bundle_gate_outputs(...)` to persist P7 flags and priority-board guardrails.

1) Update `session_summary.json` payload (add `btst_0422_flags`):

```python
_write_json(
    report_dir / "session_summary.json",
    {
        "trade_date": "2026-05-29",
        "selection_target": "short_trade_only",
        "btst_0422_flags": {
            "p7_gap_overlay_mode": "report",
            "p7_gap_warn_threshold": 0.005,
            "p7_gap_halt_threshold": 0.01,
        },
        "btst_followup": {
            "brief_json": brief_path.as_posix(),
            "priority_board_json": priority_board_path.as_posix(),
        },
    },
)
```

2) Update `priority_board_path` payload (add `global_guardrails`):

```python
_write_json(
    priority_board_path,
    {
        "trade_date": "2026-05-29",
        "next_trade_date": "2026-06-01",
        "selection_target": "short_trade_only",
        "source_paths": {"snapshot_path": snapshot_path.as_posix()},
        "priority_rows": [selected_row],
        "global_guardrails": [
            "priority board 只负责排序和分层，不改变 short-trade admission 默认语义。",
        ],
    },
)
```

3) In the test that calls `_generate_btst_doc_bundle_gate_outputs(...)` and reads `checklist_doc`, add assertions:

```python
assert "## 全局 Guardrails" in checklist_doc
assert "priority board 只负责排序和分层" in checklist_doc
assert "Gap overlay (BTST 0422 P7/report):" in checklist_doc
assert "≤ -0.5%" in checklist_doc
assert "≤ -1.0%" in checklist_doc
```

- [ ] **Step 2: Run the test to confirm it fails (guardrails not rendered yet)**

Run:

```bash
uv run pytest tests/test_generate_btst_doc_bundle_script.py -q
```

Expected: FAIL because checklist doc does not include `## 全局 Guardrails`.

- [ ] **Step 3: Implement the P7 gap overlay guardrail formatter sourced from persisted flags**

In `scripts/generate_btst_doc_bundle.py`, add:

```python
def _btst_0422_p7_gap_overlay_guardrail_from_flags(flags: dict[str, Any]) -> str | None:
    mode = str(flags.get("p7_gap_overlay_mode") or "off").strip().lower() or "off"
    if mode not in {"off", "report", "enforce"}:
        mode = "off"
    if mode == "off":
        return None

    def _num(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    warn = abs(_num(flags.get("p7_gap_warn_threshold"), 0.005))
    halt = abs(_num(flags.get("p7_gap_halt_threshold"), 0.01))
    if warn <= 0:
        warn = 0.005
    if halt <= 0:
        halt = 0.01
    if halt < warn:
        halt = warn

    warn_pct = f"{warn * 100:.1f}%"
    halt_pct = f"{halt * 100:.1f}%"
    return (
        f"Gap overlay (BTST 0422 P7/{mode}): 若 T+1 开盘相对 T 收盘跳空低开 ≤ -{warn_pct}，只允许确认后减仓入场；"
        f"若 ≤ -{halt_pct}，当日禁入。"
    )
```

- [ ] **Step 4: Implement checklist global-guardrails rendering**

In `scripts/generate_btst_doc_bundle.py`, add:

```python
def _render_global_guardrails_lines(
    *,
    priority_board: dict[str, Any],
    session_summary: dict[str, Any],
) -> list[str]:
    lines = ["## 全局 Guardrails", ""]

    guardrails = list(priority_board.get("global_guardrails") or [])
    if guardrails:
        for item in guardrails:
            text = str(item or "").strip()
            if text:
                lines.append(f"- {text}")

    flags = dict(session_summary.get("btst_0422_flags") or {})
    gap_guardrail = _btst_0422_p7_gap_overlay_guardrail_from_flags(flags)
    if gap_guardrail:
        lines.append(f"- {gap_guardrail}")

    if len(lines) == 2:
        lines.append("- （无）")

    return lines
```

- [ ] **Step 5: Pass `session_summary` into `_render_checklist_doc` and insert the new section**

1) Update `_render_checklist_doc` signature to accept `session_summary: dict[str, Any]`:

```python
def _render_checklist_doc(
    signal_date_compact: str,
    brief: dict[str, Any],
    priority_board: dict[str, Any],
    session_summary: dict[str, Any],
    semantic_selected: list[dict[str, Any]],
    ...
) -> str:
    ...
```

2) Insert the section after `## 盘前控制塔`:

```python
lines.extend(_render_premarket_control_tower(control_tower))
lines.extend([""])
lines.extend(_render_global_guardrails_lines(priority_board=priority_board, session_summary=session_summary))
lines.extend([""])
lines.extend(_render_opening_timeline_lines(...))
```

3) Update the callsite in `generate_btst_doc_bundle()`:

```python
f"BTST-{signal_date_compact}-EXEC-CHECKLIST.md": _render_checklist_doc(
    signal_date_compact,
    brief,
    priority_board,
    session_summary,
    semantic_selected,
    semantic_watch,
    early_runner,
    selection_snapshot,
    control_tower,
    report_mode,
    veto_owner,
    section_labels,
    resolved_strategy_thresholds,
    resolved_strategy_thresholds_config_path,
    strategy_thresholds_profile,
),
```

- [ ] **Step 6: Run tests to verify they now pass**

Run:

```bash
uv run pytest tests/test_generate_btst_doc_bundle_script.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/generate_btst_doc_bundle.py tests/test_generate_btst_doc_bundle_script.py
git commit -m "feat: render global guardrails in checklist"
```

---

### Task 2: Persist `market_state` + `btst_regime_gate` into `btst_full_report_YYYYMMDD.json` (proxy, audit-only)

**Files:**
- Modify: `scripts/btst_full_report.py`
- Create: `tests/test_btst_full_report_market_state_proxy.py`

- [ ] **Step 1: Add a failing unit test for the market-state proxy computation**

Create `tests/test_btst_full_report_market_state_proxy.py`:

```python
from __future__ import annotations

import pandas as pd


def test_btst_full_report_builds_market_state_proxy_and_gate():
    import scripts.btst_full_report as report

    results = pd.DataFrame(
        {
            "pct_chg": [1.0, 0.5, -0.2, -1.5, 3.0],
        }
    )

    market_state = report._build_market_state_proxy_from_results(results)
    assert market_state["source"] == "universe_proxy_v1"
    assert 0 <= market_state["breadth_ratio"] <= 1

    gate = report._derive_btst_regime_gate_proxy(market_state)
    assert gate["source"] == "universe_proxy_v1"
    assert gate["gate"] in {"aggressive_trade", "normal_trade", "shadow_only", "halt"}
    assert gate["enforced"] is False
```

- [ ] **Step 2: Run the test to confirm it fails (helpers not implemented)**

Run:

```bash
uv run pytest tests/test_btst_full_report_market_state_proxy.py -q
```

Expected: FAIL with `AttributeError` (missing helper functions).

- [ ] **Step 3: Implement the proxy helpers in `scripts/btst_full_report.py`**

Add near the bottom of `scripts/btst_full_report.py` (top-level helpers; pure, no Tushare calls):

```python
def _build_market_state_proxy_from_results(results: pd.DataFrame) -> dict:
    pct = pd.to_numeric(results.get("pct_chg"), errors="coerce")
    pct = pct.dropna()
    if pct.empty:
        return {
            "source": "universe_proxy_v1",
            "breadth_ratio": None,
            "daily_return": None,
            "limit_up_count": None,
            "limit_down_count": None,
            "position_scale": 1.0,
            "regime_gate_level": "n/a",
            "regime_gate_reasons": ["missing_universe"],
        }

    breadth_ratio = float((pct > 0).mean())
    daily_return = float(pct.mean() / 100.0)
    limit_up_count = int((pct >= 9.8).sum())
    limit_down_count = int((pct <= -9.8).sum())

    regime_gate_level = "balanced"
    reasons: list[str] = []
    position_scale = 1.0
    if daily_return <= -0.005 and breadth_ratio <= 0.35:
        regime_gate_level = "crisis"
        reasons = ["breadth_weak", "daily_return_negative"]
        position_scale = 0.75
    elif daily_return <= -0.002 or breadth_ratio <= 0.45:
        regime_gate_level = "risk_off"
        reasons = ["breadth_soft", "daily_return_soft"]
        position_scale = 0.9

    return {
        "source": "universe_proxy_v1",
        "breadth_ratio": breadth_ratio,
        "daily_return": daily_return,
        "limit_up_count": limit_up_count,
        "limit_down_count": limit_down_count,
        "position_scale": position_scale,
        "regime_gate_level": regime_gate_level,
        "regime_gate_reasons": reasons,
    }


def _derive_btst_regime_gate_proxy(market_state: dict) -> dict:
    level = str(market_state.get("regime_gate_level") or "n/a")
    gate = "normal_trade"
    if level == "crisis":
        gate = "halt"
    elif level == "risk_off":
        gate = "shadow_only"
    elif level == "balanced":
        gate = "normal_trade"

    return {
        "source": "universe_proxy_v1",
        "gate": gate,
        "mode": "report_only",
        "enforced": False,
        "buy_orders_cleared": None,
        "buy_orders_cleared_count": None,
        "shadow_promotion_tickers": [],
    }
```

- [ ] **Step 4: Persist the proxy payloads into the JSON report output**

In the `json_data = { ... }` block (near the end of `main()`), insert:

```python
market_state = _build_market_state_proxy_from_results(results)
json_data["market_state"] = market_state
json_data["btst_regime_gate_enforcement"] = _derive_btst_regime_gate_proxy(market_state)
```

(Keep naming explicit: this is a proxy report surface; it should not be confused with paper-trading `selection_snapshot.market_state`.)

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/test_btst_full_report_market_state_proxy.py -q
```

Expected: PASS.

- [ ] **Step 6: Run the focused BTST bundle suite to ensure no regressions**

Run:

```bash
uv run pytest tests/test_generate_btst_doc_bundle_script.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/btst_full_report.py tests/test_btst_full_report_market_state_proxy.py
git commit -m "feat: persist market_state proxy in btst_full_report"
```

---

## Self-Review (run now)

- **Spec coverage:**
  - EXEC-CHECKLIST renders global guardrails + P7 gap overlay → Task 1.
  - Rule report persists structured market_state/gate for audit stratification → Task 2.

- **Placeholder scan:** No “TBD/TODO/implement later” language.

- **Type consistency:** New helpers return dict payloads; checklist renderer consumes `session_summary.btst_0422_flags`.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-02-btst-regime-gate-gap-overlay-v1.md`.

Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks.
2. **Inline Execution** — Execute tasks in this session using executing-plans, with checkpoints.

Which approach?
