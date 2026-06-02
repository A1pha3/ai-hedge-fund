# BTST Payoff-first Review Lane v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a **report-only** “Payoff-first review lane” to BTST outputs so operators can review a small, auditable shortlist aimed at improving `5D/+15%` outcomes without changing formal execution behavior.

**Architecture:** Compute `payoff_review_entries` as a **pure function** from the already-enriched `selected_entries` + `near_miss_entries` (uses existing `historical_prior` fields), gate the feature behind `BTST_PAYOFF_REVIEW_LANE_MODE=off|report`, then render a dedicated markdown section in the next-day trade brief and surface a compact section in the multi-agent doc bundle.

**Tech Stack:** Python 3.11–3.12, `uv`, BTST reporting modules under `src/paper_trading/_btst_reporting/`, JSON + Markdown artifact generation, pytest.

---

## Scope / assumptions
- Primary objective definition remains **offline truth** (already implemented): `hit_5d_15 := (max_high_t1_t5_from_open >= 0.15)` from `scripts/generate_btst_realized_prices.py`.
- v1 scoring uses **existing priors** (next-day hit-rate threshold 2%) as proxies; we will validate offline with realized tooling before any promotion to execution.
- Default runtime behavior remains unchanged because the lane is **review-only** and **env-gated** (default `off`).

## File structure

- Create: `src/paper_trading/_btst_reporting/payoff_review_lane.py`
  - Env-gated lane toggle + deterministic payoff scoring + entry selection.
- Modify: `src/paper_trading/_btst_reporting/brief_builder.py`
  - Attach `payoff_review_entries` into the brief payload sections.
- Create: `src/paper_trading/btst_trade_brief_payoff_markdown_helpers.py`
  - Pure markdown renderer for the lane.
- Modify: `src/paper_trading/_btst_reporting/brief_rendering.py`
  - Render payoff lane section only when entries exist.
- Modify: `scripts/generate_btst_doc_bundle.py`
  - Surface a compact payoff lane section in the multi-agent doc (`_render_llm_doc`) using the brief payload.

**Tests:**
- Create: `tests/test_btst_payoff_review_lane.py`
- Modify: `tests/test_generate_btst_next_day_trade_brief_script.py`
- Modify: `tests/test_generate_btst_doc_bundle_script.py`

---

### Task 1: Implement payoff review lane builder (pure function + env gate)

**Files:**
- Create: `src/paper_trading/_btst_reporting/payoff_review_lane.py`
- Test: `tests/test_btst_payoff_review_lane.py`

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations

from src.paper_trading._btst_reporting.payoff_review_lane import (
    build_payoff_review_entries,
)


def test_build_payoff_review_entries_ranks_by_proxy_prior_and_reliability(monkeypatch):
    monkeypatch.setenv("BTST_PAYOFF_REVIEW_LANE_MODE", "report")
    entries = [
        {
            "ticker": "300001",
            "decision": "near_miss",
            "candidate_source": "short_trade_boundary",
            "historical_prior": {
                "next_high_hit_rate_at_threshold": 0.20,
                "evaluable_count": 8,
                "execution_quality_label": "close_continuation",
            },
        },
        {
            "ticker": "300002",
            "decision": "selected",
            "candidate_source": "short_trade_boundary",
            "historical_prior": {
                "next_high_hit_rate_at_threshold": 0.40,
                "evaluable_count": 1,
                "execution_quality_label": "close_continuation",
            },
        },
    ]

    lane = build_payoff_review_entries(selected_entries=[entries[1]], near_miss_entries=[entries[0]])

    assert [row["ticker"] for row in lane] == ["300001", "300002"]
    assert lane[0]["review_semantics"] == "review_only"
    assert lane[0]["payoff_review_lane_rank"] == 1
    assert 0.0 <= lane[0]["payoff_review_lane_score"] <= 1.0


def test_build_payoff_review_entries_dedupes_by_ticker_preferring_selected(monkeypatch):
    monkeypatch.setenv("BTST_PAYOFF_REVIEW_LANE_MODE", "report")
    selected = {
        "ticker": "300003",
        "decision": "selected",
        "candidate_source": "short_trade_boundary",
        "historical_prior": {"next_high_hit_rate_at_threshold": 0.10, "evaluable_count": 3},
    }
    near_miss = {
        "ticker": "300003",
        "decision": "near_miss",
        "candidate_source": "short_trade_boundary",
        "historical_prior": {"next_high_hit_rate_at_threshold": 0.90, "evaluable_count": 12},
    }

    lane = build_payoff_review_entries(selected_entries=[selected], near_miss_entries=[near_miss])

    assert len(lane) == 1
    assert lane[0]["ticker"] == "300003"
    assert lane[0]["decision"] == "selected"


def test_build_payoff_review_entries_returns_empty_when_mode_off(monkeypatch):
    monkeypatch.delenv("BTST_PAYOFF_REVIEW_LANE_MODE", raising=False)
    lane = build_payoff_review_entries(selected_entries=[{"ticker": "300004"}], near_miss_entries=[])
    assert lane == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_btst_payoff_review_lane.py -q
```

Expected: FAIL because `payoff_review_lane.py` does not exist.

- [ ] **Step 3: Add minimal implementation**

Create `src/paper_trading/_btst_reporting/payoff_review_lane.py`:

```python
from __future__ import annotations

from typing import Any

from src.utils.env_helpers import get_env_mode, get_env_int
from src.paper_trading.btst_reporting_utils import RISKY_OBSERVER_EXECUTION_QUALITY_LABELS

_BTST_PAYOFF_REVIEW_LANE_MODE_ENV = "BTST_PAYOFF_REVIEW_LANE_MODE"
_BTST_PAYOFF_REVIEW_LANE_MODES = frozenset({"off", "report"})
_BTST_PAYOFF_REVIEW_MAX_ENTRIES_ENV = "BTST_PAYOFF_REVIEW_MAX_ENTRIES"


def _lane_mode() -> str:
    mode = get_env_mode(_BTST_PAYOFF_REVIEW_LANE_MODE_ENV, "off")
    if mode not in _BTST_PAYOFF_REVIEW_LANE_MODES:
        return "off"
    return mode


def _max_entries() -> int:
    value = int(get_env_int(_BTST_PAYOFF_REVIEW_MAX_ENTRIES_ENV, 3) or 3)
    return max(1, min(10, value))


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int:
    try:
        if value is None:
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def _compute_payoff_score(entry: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    prior = dict(entry.get("historical_prior") or {})
    prior_hit = _as_float(prior.get("next_high_hit_rate_at_threshold")) or 0.0
    evaluable = _as_int(prior.get("evaluable_count"))
    reliability = min(1.0, evaluable / 6.0) if evaluable > 0 else 0.0

    quality_label = str(prior.get("execution_quality_label") or "")
    risky = quality_label in RISKY_OBSERVER_EXECUTION_QUALITY_LABELS
    penalty = 1.0 if risky else 0.0

    score = (0.6 * prior_hit) + (0.4 * reliability) - (0.2 * penalty)
    score = max(0.0, min(1.0, score))

    components = {
        "prior_next_high_hit_rate_at_threshold": prior_hit,
        "evaluable_count": evaluable,
        "reliability_score": round(reliability, 4),
        "execution_quality_label": quality_label or None,
        "penalty_applied": risky,
    }
    return score, components


def build_payoff_review_entries(
    *,
    selected_entries: list[dict[str, Any]],
    near_miss_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if _lane_mode() != "report":
        return []

    by_ticker: dict[str, dict[str, Any]] = {}
    for entry in list(near_miss_entries or []):
        ticker = str(entry.get("ticker") or "").strip()
        if ticker:
            by_ticker.setdefault(ticker, entry)

    for entry in list(selected_entries or []):
        ticker = str(entry.get("ticker") or "").strip()
        if ticker:
            by_ticker[ticker] = entry  # prefer selected

    scored: list[dict[str, Any]] = []
    for ticker, entry in by_ticker.items():
        score, components = _compute_payoff_score(entry)
        scored.append(
            {
                **dict(entry),
                "payoff_review_lane_score": round(score, 6),
                "payoff_review_lane_components": components,
                "review_semantics": "review_only",
            }
        )

    scored.sort(
        key=lambda row: (
            -(float(row.get("payoff_review_lane_score") or 0.0)),
            0 if str(row.get("decision") or "") == "selected" else 1,
            str(row.get("ticker") or ""),
        )
    )

    out: list[dict[str, Any]] = []
    for idx, row in enumerate(scored[: _max_entries()], start=1):
        out.append({**row, "payoff_review_lane_rank": idx})
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_btst_payoff_review_lane.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/paper_trading/_btst_reporting/payoff_review_lane.py tests/test_btst_payoff_review_lane.py
git commit -m "feat(btst): add payoff-first review lane scorer" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: Attach payoff review entries into brief JSON payload

**Files:**
- Modify: `src/paper_trading/_btst_reporting/brief_builder.py`
- Test: `tests/test_generate_btst_next_day_trade_brief_script.py`

- [ ] **Step 1: Write failing test (rendering-level contract)**

Append to `tests/test_generate_btst_next_day_trade_brief_script.py`:

```python

def test_render_btst_next_day_trade_brief_markdown_renders_payoff_review_lane_when_present():
    markdown = btst_reporting.render_btst_next_day_trade_brief_markdown(
        {
            "trade_date": "2026-03-27",
            "next_trade_date": "2026-03-30",
            "target_mode": "short_trade_only",
            "selection_target": "short_trade_only",
            "recommendation": "...",
            "summary": {},
            "selected_entries": [],
            "near_miss_entries": [],
            "opportunity_pool_entries": [],
            "risky_observer_entries": [],
            "no_history_observer_entries": [],
            "weak_history_pruned_entries": [],
            "research_upside_radar_entries": [],
            "runner_recall_review_entries": [],
            "catalyst_theme_entries": [],
            "catalyst_theme_frontier_priority": {},
            "catalyst_theme_shadow_entries": [],
            "excluded_research_entries": [],
            "upstream_shadow_summary": {"shadow_candidate_count": 0, "promotable_count": 0, "lane_counts": {}},
            "upstream_shadow_entries": [],
            "rollout_validation": {},
            "payoff_review_entries": [
                {
                    "ticker": "300001",
                    "decision": "near_miss",
                    "score_target": 0.42,
                    "confidence": 0.80,
                    "preferred_entry_mode": "next_day_breakout_confirmation",
                    "candidate_source": "short_trade_boundary",
                    "top_reasons": ["breakout_freshness=0.90"],
                    "positive_tags": ["fresh_breakout_candidate"],
                    "metrics": {
                        "breakout_freshness": 0.90,
                        "trend_acceleration": 0.70,
                        "volume_expansion_quality": 0.40,
                        "close_strength": 0.80,
                        "catalyst_freshness": 0.50,
                    },
                    "gate_status": {"score": "near_miss"},
                    "historical_prior": {
                        "next_high_hit_rate_at_threshold": 0.35,
                        "evaluable_count": 7,
                        "execution_quality_label": "close_continuation",
                    },
                    "review_semantics": "review_only",
                    "payoff_review_lane_score": 0.50,
                    "payoff_review_lane_rank": 1,
                    "payoff_review_lane_components": {"prior_next_high_hit_rate_at_threshold": 0.35, "evaluable_count": 7},
                }
            ],
            "report_dir": "/tmp/report",
            "snapshot_path": "/tmp/snapshot.json",
            "replay_input_path": "/tmp/replay.json",
            "session_summary_path": "/tmp/session_summary.json",
        }
    )

    assert "## Payoff-first Review Lane" in markdown
    assert "- review_semantics: review_only" in markdown
    assert "- payoff_review_lane_score: 0.5000" in markdown
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_generate_btst_next_day_trade_brief_script.py -k payoff_review_lane -q
```

Expected: FAIL because brief markdown does not include this section yet.

- [ ] **Step 3: Wire `payoff_review_entries` into brief sections**

Modify `src/paper_trading/_btst_reporting/brief_builder.py`:

1) Import the builder:

```python
from src.paper_trading._btst_reporting.payoff_review_lane import build_payoff_review_entries
```

2) In `_build_btst_next_day_trade_brief_payload(...)`, after filtering:

```python
selected_entries = _filter_execution_ready_entries(selected_entries)
near_miss_entries = _filter_execution_ready_entries(near_miss_entries)

payoff_review_entries = build_payoff_review_entries(
    selected_entries=selected_entries,
    near_miss_entries=near_miss_entries,
)
```

3) Thread it into `_build_btst_next_day_trade_brief_content(...)` and `_build_btst_next_day_trade_brief_sections(...)`:

- Add parameter `payoff_review_entries: list[dict[str, Any]]` to both functions.
- In `_build_btst_next_day_trade_brief_sections(...)` return dict, add:

```python
"payoff_review_entries": payoff_review_entries,
```

- [ ] **Step 4: Add markdown renderer for payoff lane**

(Implemented in Task 3 below; this step only ensures JSON carries the field.)

- [ ] **Step 5: Run the test to verify it now reaches rendering (still failing until Task 3)**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_generate_btst_next_day_trade_brief_script.py -k payoff_review_lane -q
```

Expected: still FAIL because rendering is not implemented yet.

- [ ] **Step 6: Commit**

```bash
git add src/paper_trading/_btst_reporting/brief_builder.py
git commit -m "feat(btst): attach payoff review lane to brief payload" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Render payoff review lane in next-day trade brief markdown

**Files:**
- Create: `src/paper_trading/btst_trade_brief_payoff_markdown_helpers.py`
- Modify: `src/paper_trading/_btst_reporting/brief_rendering.py`
- Test: `tests/test_generate_btst_next_day_trade_brief_script.py`

- [ ] **Step 1: Implement payoff markdown helper**

Create `src/paper_trading/btst_trade_brief_payoff_markdown_helpers.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from typing import Any


def append_brief_payoff_review_lane_markdown(
    lines: list[str],
    entries: list[dict[str, Any]],
    *,
    append_brief_ticker_section: Callable[..., None],
    append_brief_historical_prior_fields: Callable[..., None],
    append_brief_short_trade_metrics: Callable[[list[str], dict[str, Any]], None],
    append_brief_historical_recent_examples: Callable[[list[str], dict[str, Any]], None],
    append_gate_status_line: Callable[[list[str], dict[str, Any]], None],
    format_float: Callable[[Any], str],
) -> None:
    if not entries:
        return

    def render_entry(inner: list[str], entry: dict[str, Any]) -> None:
        historical_prior = dict(entry.get("historical_prior") or {})
        inner.append("- review_semantics: review_only")
        inner.append(
            f"- payoff_review_lane_rank: {int(entry.get('payoff_review_lane_rank') or 0)}"
        )
        inner.append(
            f"- payoff_review_lane_score: {float(entry.get('payoff_review_lane_score') or 0.0):.4f}"
        )
        comps = dict(entry.get("payoff_review_lane_components") or {})
        inner.append(
            "- payoff_components: "
            + ", ".join(
                [
                    f"prior_hit={format_float(comps.get('prior_next_high_hit_rate_at_threshold') or comps.get('prior_next_high_hit_rate_at_threshold'))}",
                    f"evaluable={int(comps.get('evaluable_count') or historical_prior.get('evaluable_count') or 0)}",
                    f"exec_quality={comps.get('execution_quality_label') or historical_prior.get('execution_quality_label') or 'n/a'}",
                ]
            )
        )
        inner.append(f"- decision: {entry.get('decision')}")
        inner.append(f"- candidate_source: {entry.get('candidate_source')}")
        append_brief_historical_prior_fields(
            inner,
            historical_prior,
            include_monitor_priority=True,
            include_execution_quality=True,
            include_execution_note=True,
        )
        inner.append(
            f"- top_reasons: {', '.join(entry.get('top_reasons') or []) or 'n/a'}"
        )
        append_brief_short_trade_metrics(inner, dict(entry.get("metrics") or {}))
        append_brief_historical_recent_examples(inner, historical_prior)
        append_gate_status_line(inner, entry.get("gate_status") or {})

    lines.append("## Payoff-first Review Lane")
    lines.append("- 复审层（review-only）：不等于下单；用于优先盯 5D payoff 线索，需盘中确认后再决策。")
    lines.append("")
    append_brief_ticker_section(
        lines,
        title="Payoff-first Review Entries",
        entries=entries,
        render_entry=render_entry,
    )
```

- [ ] **Step 2: Wire renderer into `brief_rendering.py`**

Modify `src/paper_trading/_btst_reporting/brief_rendering.py`:

1) Add import:

```python
from src.paper_trading.btst_trade_brief_payoff_markdown_helpers import (
    append_brief_payoff_review_lane_markdown as _append_brief_payoff_review_lane_markdown_impl,
)
```

2) Add local wrapper similar to others:

```python
def _append_brief_payoff_review_lane_markdown(lines: list[str], entries: list[dict[str, Any]]) -> None:
    _append_brief_payoff_review_lane_markdown_impl(
        lines,
        entries,
        append_brief_ticker_section=_append_brief_ticker_section,
        append_brief_historical_prior_fields=_append_brief_historical_prior_fields,
        append_brief_short_trade_metrics=_append_brief_short_trade_metrics,
        append_brief_historical_recent_examples=_append_brief_historical_recent_examples,
        append_gate_status_line=_append_gate_status_line,
        format_float=_format_float,
    )
```

3) In `render_btst_next_day_trade_brief_markdown(...)`, insert after Near-Miss section:

```python
_append_brief_payoff_review_lane_markdown(
    lines, list(analysis.get("payoff_review_entries") or [])
)
```

- [ ] **Step 3: Re-run the payoff lane test and verify it passes**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_generate_btst_next_day_trade_brief_script.py -k payoff_review_lane -q
```

Expected: PASS.

- [ ] **Step 4: Run the focused BTST brief suite**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_generate_btst_next_day_trade_brief_script.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/paper_trading/_btst_reporting/brief_rendering.py src/paper_trading/btst_trade_brief_payoff_markdown_helpers.py tests/test_generate_btst_next_day_trade_brief_script.py
git commit -m "feat(btst): render payoff-first review lane in trade brief" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 4: Surface payoff review lane in the BTST doc bundle (multi-agent doc)

**Files:**
- Modify: `scripts/generate_btst_doc_bundle.py`
- Test: `tests/test_generate_btst_doc_bundle_script.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_generate_btst_doc_bundle_script.py`:

```python

def test_generate_btst_doc_bundle_surfaces_payoff_review_lane_in_llm_doc(tmp_path, monkeypatch):
    monkeypatch.setenv("BTST_PAYOFF_REVIEW_LANE_MODE", "report")

    # Reuse existing helpers in this test module to build a minimal bundle input.
    # (Pattern: the suite already constructs `brief` dicts inline for many assertions.)
    brief = {
        "trade_date": "2026-04-06",
        "next_trade_date": "2026-04-07",
        "selection_target": "short_trade_only",
        "selected_entries": [],
        "near_miss_entries": [],
        "opportunity_pool_entries": [],
        "payoff_review_entries": [
            {
                "ticker": "300001",
                "decision": "near_miss",
                "review_semantics": "review_only",
                "payoff_review_lane_score": 0.5,
                "payoff_review_lane_rank": 1,
            }
        ],
    }

    text = generate_btst_doc_bundle._render_llm_doc(
        signal_date_compact="20260406",
        brief=brief,
        priority_board={},
        session_summary={},
        semantic_selected=[],
        semantic_watch=[],
        early_runner={"status": "unavailable"},
        selection_snapshot={},
        control_tower={},
        report_mode="formal_execution",
        veto_owner="n/a",
        section_labels={"llm_execution_title": "LLM Execution"},
        report_dir=tmp_path,
        strategy_thresholds={},
        strategy_thresholds_config_path="/tmp/thresholds.json",
        strategy_thresholds_profile="default",
    )

    assert "## Payoff-first Review Lane" in text
    assert "300001" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_generate_btst_doc_bundle_script.py -k payoff_review_lane -q
```

Expected: FAIL because `_render_llm_doc()` does not render the payoff lane.

- [ ] **Step 3: Implement minimal rendering in `_render_llm_doc()`**

Modify `scripts/generate_btst_doc_bundle.py` in `_render_llm_doc(...)`:

1) Resolve rows:

```python
payoff_review_rows = _safe_rows(brief.get("payoff_review_entries"))
```

2) After the main “观察层” section (or before “机会池”), add:

```python
if payoff_review_rows:
    lines.extend(["", "## Payoff-first Review Lane", ""])
    lines.append("- 复审层（review-only）：不等于下单；用于优先盯 5D payoff 线索。")
    for row in payoff_review_rows[:5]:
        score = row.get("payoff_review_lane_score")
        score_str = f"{float(score):.4f}" if score is not None else "n/a"
        lines.append(f"- `{_stock_label(row)}` score={score_str}")
```

- [ ] **Step 4: Re-run doc bundle payoff test**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_generate_btst_doc_bundle_script.py -k payoff_review_lane -q
```

Expected: PASS.

- [ ] **Step 5: Run the existing doc bundle suite**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_generate_btst_doc_bundle_script.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/generate_btst_doc_bundle.py tests/test_generate_btst_doc_bundle_script.py
git commit -m "feat(btst): surface payoff review lane in doc bundle" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Final verification (after implementation)

Run the focused BTST report generators:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork \
  && uv run pytest tests/test_generate_btst_next_day_trade_brief_script.py tests/test_generate_btst_doc_bundle_script.py -q
```

Expected: PASS.

## Notes for rollout
- Default remains `BTST_PAYOFF_REVIEW_LANE_MODE=off`.
- To enable for shadow/operator review:

```bash
export BTST_PAYOFF_REVIEW_LANE_MODE=report
export BTST_PAYOFF_REVIEW_MAX_ENTRIES=3
```
