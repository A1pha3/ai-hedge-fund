# BTST Rollout Report Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the new `layer_c` governed rollout artifact consistently in BTST brief, premarket execution card, followup manifest, and generated doc bundles without changing trading behavior.

**Architecture:** Add one shared rollout-artifact resolver in `src/paper_trading/btst_reporting_utils.py`, then thread its normalized payload into the brief and premarket builders. Keep bundle generation read-only by consuming the already-normalized brief payload instead of re-parsing artifact files in multiple places. Missing or malformed artifacts degrade to `status=unavailable` instead of breaking report generation.

**Tech Stack:** Python 3.12, `uv`, existing BTST reporting modules under `src/paper_trading/_btst_reporting/`, JSON/Markdown artifact generation, pytest

---

## File structure

- Modify: `src/paper_trading/btst_reporting_utils.py`
  - Add one shared rollout artifact path resolver + normalized payload loader.
- Modify: `tests/test_btst_report_utils.py`
  - Add focused coverage for latest-artifact resolution and unavailable fallback.
- Modify: `src/paper_trading/_btst_reporting/brief_builder.py`
  - Attach `rollout_validation` to the brief payload.
- Modify: `src/paper_trading/_btst_reporting/brief_rendering.py`
  - Render one compact governed-rollout section in the brief markdown.
- Modify: `tests/test_generate_btst_next_day_trade_brief_script.py`
  - Cover brief JSON + markdown when rollout artifact exists and when it is missing.
- Modify: `src/paper_trading/_btst_reporting/premarket_card.py`
  - Carry the same normalized `rollout_validation` payload into the premarket card.
- Modify: `src/paper_trading/btst_reporting.py`
  - Render one compact rollout guardrail section in the premarket markdown and extend followup artifact registration.
- Modify: `tests/test_generate_btst_premarket_execution_card_script.py`
  - Cover the new premarket rollout section and unavailable fallback.
- Modify: `src/paper_trading/btst_report_artifact_helpers.py`
  - Store rollout artifact source paths in `session_summary["btst_followup"]`.
- Modify: `scripts/generate_btst_doc_bundle.py`
  - Reuse `brief["rollout_validation"]` and add one rollout section to bundle documents.
- Modify: `tests/test_generate_btst_doc_bundle_script.py`
  - Verify bundle docs surface rollout status, summary, and source path without re-parsing artifacts.

## Task 1: Add one shared rollout artifact resolver

**Files:**
- Modify: `src/paper_trading/btst_reporting_utils.py`
- Test: `tests/test_btst_report_utils.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path
import json

from src.paper_trading.btst_reporting_utils import (
    _load_btst_rollout_validation_context,
)


def test_load_btst_rollout_validation_context_prefers_latest_report(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    reports_root.mkdir(parents=True)
    older = reports_root / "btst_layer_c_rollout_validation_20260518_20260522.json"
    newer = reports_root / "btst_layer_c_rollout_validation_20260506_20260522.json"
    older.write_text(
        json.dumps({"recommendation": {"status": "hold_for_more_validation"}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    newer.write_text(
        json.dumps(
            {
                "payoff_summary": {
                    "selected_hit_rate_15pct": 0.3077,
                    "shadow_hit_rate_15pct": 0.3333,
                },
                "replay_summary": {
                    "selected_count_delta": -5,
                    "execution_eligible_delta": -3,
                    "buy_order_delta": -3,
                },
                "recommendation": {
                    "status": "governed_shadow_ready",
                    "primary_lane": "layer_c_formal_precision_tightening",
                    "summary": "先收 formal buy。",
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    context = _load_btst_rollout_validation_context(report_dir=reports_root / "paper_trading_20260522_foo")

    assert context["status"] == "governed_shadow_ready"
    assert context["source_json_path"] == newer.resolve().as_posix()
    assert context["shadow_hit_rate_15pct"] == 0.3333
    assert context["execution_eligible_delta"] == -3
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_btst_report_utils.py -k rollout_validation_context -q
```

Expected: FAIL because `_load_btst_rollout_validation_context()` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
def _resolve_btst_rollout_validation_json_path(
    *,
    report_dir: str | Path,
    explicit_path: str | Path | None = None,
) -> Path | None:
    if explicit_path:
        resolved = Path(explicit_path).expanduser().resolve()
        return resolved if resolved.exists() else None

    reports_root = Path(report_dir).expanduser().resolve().parent
    candidates = sorted(
        reports_root.glob("btst_layer_c_rollout_validation_*.json"),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
    return candidates[0] if candidates else None


def _load_btst_rollout_validation_context(
    *,
    report_dir: str | Path,
    explicit_path: str | Path | None = None,
) -> dict[str, Any]:
    json_path = _resolve_btst_rollout_validation_json_path(
        report_dir=report_dir,
        explicit_path=explicit_path,
    )
    if json_path is None:
        return {
            "status": "unavailable",
            "primary_lane": None,
            "summary": "rollout artifact missing",
            "selected_hit_rate_15pct": None,
            "shadow_hit_rate_15pct": None,
            "selected_count_delta": None,
            "execution_eligible_delta": None,
            "buy_order_delta": None,
            "source_json_path": None,
            "source_markdown_path": None,
        }

    payload = _load_json(json_path)
    recommendation = dict(payload.get("recommendation") or {})
    payoff_summary = dict(payload.get("payoff_summary") or {})
    replay_summary = dict(payload.get("replay_summary") or {})
    markdown_path = json_path.with_suffix(".md")
    return {
        "status": recommendation.get("status") or "unavailable",
        "primary_lane": recommendation.get("primary_lane"),
        "summary": recommendation.get("summary") or "invalid rollout artifact",
        "selected_hit_rate_15pct": payoff_summary.get("selected_hit_rate_15pct"),
        "shadow_hit_rate_15pct": payoff_summary.get("shadow_hit_rate_15pct"),
        "selected_count_delta": replay_summary.get("selected_count_delta"),
        "execution_eligible_delta": replay_summary.get("execution_eligible_delta"),
        "buy_order_delta": replay_summary.get("buy_order_delta"),
        "source_json_path": json_path.as_posix(),
        "source_markdown_path": markdown_path.as_posix() if markdown_path.exists() else None,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_btst_report_utils.py -k rollout_validation_context -q
```

Expected: PASS and the newer `btst_layer_c_rollout_validation_*.json` file is selected.

- [ ] **Step 5: Commit**

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && git add src/paper_trading/btst_reporting_utils.py tests/test_btst_report_utils.py && git commit -m "feat: add btst rollout artifact resolver"
```

## Task 2: Attach rollout_validation to the brief payload and markdown

**Files:**
- Modify: `src/paper_trading/_btst_reporting/brief_builder.py`
- Modify: `src/paper_trading/_btst_reporting/brief_rendering.py`
- Test: `tests/test_generate_btst_next_day_trade_brief_script.py`

- [ ] **Step 1: Write the failing test**

```python
def test_generate_btst_next_day_trade_brief_surfaces_rollout_validation(tmp_path):
    report_dir = tmp_path / "report"
    trade_dir = report_dir / "selection_artifacts" / "2026-03-27"
    trade_dir.mkdir(parents=True)
    (report_dir / "session_summary.json").write_text(
        json.dumps({"trade_date": "2026-03-27", "selection_target": "short_trade_only"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (trade_dir / "selection_snapshot.json").write_text(
        json.dumps({"trade_date": "2026-03-27", "selection_targets": {}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (report_dir.parent / "btst_layer_c_rollout_validation_20260506_20260522.json").write_text(
        json.dumps(
            {
                "payoff_summary": {"selected_hit_rate_15pct": 0.3077, "shadow_hit_rate_15pct": 0.3333},
                "replay_summary": {"execution_eligible_delta": -3, "buy_order_delta": -3},
                "recommendation": {
                    "status": "governed_shadow_ready",
                    "primary_lane": "layer_c_formal_precision_tightening",
                    "summary": "先收 formal buy。",
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    brief = analyze_btst_next_day_trade_brief(report_dir, trade_date="2026-03-27", next_trade_date="2026-03-28")
    markdown = render_btst_next_day_trade_brief_markdown(brief)

    assert brief["rollout_validation"]["status"] == "governed_shadow_ready"
    assert brief["rollout_validation"]["execution_eligible_delta"] == -3
    assert "## Governed Rollout 观察" in markdown
    assert "layer_c_formal_precision_tightening" in markdown
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_generate_btst_next_day_trade_brief_script.py -k rollout_validation -q
```

Expected: FAIL because the brief payload and markdown do not expose `rollout_validation`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/paper_trading/_btst_reporting/brief_builder.py
from src.paper_trading.btst_reporting_utils import _load_btst_rollout_validation_context


def analyze_btst_next_day_trade_brief(
    input_path: str | Path,
    trade_date: str | None = None,
    next_trade_date: str | None = None,
) -> dict[str, Any]:
    rollout_validation = _load_btst_rollout_validation_context(report_dir=report_dir)
    brief = _build_btst_next_day_trade_brief_payload(
        report_dir=report_dir,
        snapshot_path=snapshot_path,
        session_summary_path=session_summary_path,
        actual_trade_date=actual_trade_date,
        next_trade_date=next_trade_date,
        snapshot=snapshot,
        session_summary=session_summary,
        selection_targets=selection_targets,
        selected_entries=selected_entries,
        near_miss_entries=near_miss_entries,
        opportunity_pool_entries=opportunity_pool_entries,
        no_history_observer_entries=no_history_observer_entries,
        risky_observer_entries=risky_observer_entries,
        weak_history_pruned_entries=weak_history_pruned_entries,
        research_upside_radar_entries=research_upside_radar_entries,
        catalyst_theme_entries=catalyst_theme_entries,
        catalyst_theme_shadow_entries=catalyst_theme_shadow_entries,
        excluded_research_entries=excluded_research_entries,
        runner_recall_review_entries=runner_recall_review_entries,
        brief_frontier_context=brief_frontier_context,
        btst_candidate_historical_context=btst_candidate_historical_context,
        recommendation_lines=recommendation_lines,
    )
    brief["rollout_validation"] = rollout_validation
    return brief
```

```python
# src/paper_trading/_btst_reporting/brief_rendering.py
def _append_rollout_validation_section(lines: list[str], rollout_validation: dict[str, Any]) -> None:
    lines.append("## Governed Rollout 观察")
    lines.append(f"- status: {rollout_validation.get('status')}")
    lines.append(f"- primary_lane: {rollout_validation.get('primary_lane') or 'n/a'}")
    lines.append(f"- summary: {rollout_validation.get('summary') or 'n/a'}")
    lines.append(
        f"- selected_hit_rate_15pct: {rollout_validation.get('selected_hit_rate_15pct')} -> {rollout_validation.get('shadow_hit_rate_15pct')}"
    )
    lines.append(f"- execution_eligible_delta: {rollout_validation.get('execution_eligible_delta')}")
    lines.append(f"- buy_order_delta: {rollout_validation.get('buy_order_delta')}")
    if rollout_validation.get("source_json_path"):
        lines.append(f"- rollout_source_json: {rollout_validation['source_json_path']}")
    lines.append("")
```

```python
# src/paper_trading/_btst_reporting/brief_rendering.py
def render_btst_next_day_trade_brief_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    _append_rollout_validation_section(lines, dict(analysis.get("rollout_validation") or {}))
    _append_brief_recommendation_summary(lines, analysis)
    _append_brief_scored_entries_markdown(lines, list(analysis.get("selected_entries") or []))
    _append_brief_observer_lane_markdown(lines, "Near-Miss Entries", list(analysis.get("near_miss_entries") or []))
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_generate_btst_next_day_trade_brief_script.py -k rollout_validation -q
```

Expected: PASS and both JSON + markdown contain the rollout summary.

- [ ] **Step 5: Commit**

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && git add src/paper_trading/_btst_reporting/brief_builder.py src/paper_trading/_btst_reporting/brief_rendering.py tests/test_generate_btst_next_day_trade_brief_script.py && git commit -m "feat: surface rollout status in btst brief"
```

## Task 3: Attach rollout_validation to the premarket execution card

**Files:**
- Modify: `src/paper_trading/_btst_reporting/premarket_card.py`
- Modify: `src/paper_trading/btst_reporting.py`
- Test: `tests/test_generate_btst_premarket_execution_card_script.py`

- [ ] **Step 1: Write the failing test**

```python
def test_render_btst_premarket_execution_card_markdown_emits_rollout_guardrail():
    markdown = btst_reporting.render_btst_premarket_execution_card_markdown(
        {
            "trade_date": "2026-03-27",
            "next_trade_date": "2026-03-30",
            "selection_target": "short_trade_only",
            "recommendation": "主票优先，其他仅观察。",
            "summary": {"primary_count": 1, "watch_count": 1, "opportunity_pool_count": 0},
            "primary_action": {"ticker": "300757", "action_tier": "primary_trade", "execution_posture": "breakout_confirmation", "watch_priority": "highest", "execution_quality_label": "balanced_confirmation", "preferred_entry_mode": "next_day_breakout_confirmation", "historical_prior": {}, "evidence": [], "trigger_rules": [], "avoid_rules": []},
            "watch_actions": [],
            "opportunity_actions": [],
            "runner_recall_review_actions": [],
            "risky_observer_actions": [],
            "no_history_observer_actions": [],
            "catalyst_theme_frontier_priority": {},
            "catalyst_theme_shadow_watch": [],
            "excluded_research_entries": [],
            "upstream_shadow_summary": {},
            "upstream_shadow_entries": [],
            "global_guardrails": [],
            "source_paths": {},
            "rollout_validation": {
                "status": "governed_shadow_ready",
                "primary_lane": "layer_c_formal_precision_tightening",
                "summary": "先收 formal buy。",
                "execution_eligible_delta": -3,
                "buy_order_delta": -3,
            },
        }
    )

    assert "## Governed Rollout Guardrail" in markdown
    assert "layer_c_formal_precision_tightening" in markdown
    assert "execution_eligible_delta: -3" in markdown
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_generate_btst_premarket_execution_card_script.py -k rollout_guardrail -q
```

Expected: FAIL because premarket markdown does not render the rollout section yet.

- [ ] **Step 3: Write minimal implementation**

```python
# src/paper_trading/_btst_reporting/premarket_card.py
from src.paper_trading.btst_reporting_utils import _load_btst_rollout_validation_context


def analyze_btst_premarket_execution_card(
    input_path: str | Path | dict[str, Any],
    trade_date: str | None = None,
    next_trade_date: str | None = None,
) -> dict[str, Any]:
    brief = _resolve_brief_analysis(input_path, trade_date, next_trade_date)
    action_context = _build_premarket_action_context(brief)
    card = _build_premarket_execution_card_payload(
        brief=brief,
        action_context=action_context,
        trade_date=trade_date,
        next_trade_date=next_trade_date,
    )
    card["rollout_validation"] = dict(brief.get("rollout_validation") or {}) or _load_btst_rollout_validation_context(
        report_dir=dict(brief.get("source_paths") or {}).get("report_dir") or input_path,
    )
    return card
```

```python
# src/paper_trading/btst_reporting.py
def _append_premarket_rollout_validation_markdown(lines: list[str], rollout_validation: dict[str, Any]) -> None:
    lines.append("## Governed Rollout Guardrail")
    lines.append(f"- status: {rollout_validation.get('status')}")
    lines.append(f"- primary_lane: {rollout_validation.get('primary_lane') or 'n/a'}")
    lines.append(f"- summary: {rollout_validation.get('summary') or 'n/a'}")
    lines.append(f"- execution_eligible_delta: {rollout_validation.get('execution_eligible_delta')}")
    lines.append(f"- buy_order_delta: {rollout_validation.get('buy_order_delta')}")
    lines.append("")


def render_btst_premarket_execution_card_markdown(card: dict[str, Any]) -> str:
    lines: list[str] = []
    _append_premarket_overview_markdown(lines, card)
    _append_premarket_rollout_validation_markdown(lines, dict(card.get("rollout_validation") or {}))
   _append_premarket_primary_action_markdown(lines, card.get("primary_action"))
   _append_premarket_action_section(lines, "Watchlist Actions", list(card.get("watch_actions") or []))
   _append_premarket_guardrails_markdown(lines, list(card.get("global_guardrails") or []))
   return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_generate_btst_premarket_execution_card_script.py -k rollout_guardrail -q
```

Expected: PASS and the guardrail section appears before action sections.

- [ ] **Step 5: Commit**

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && git add src/paper_trading/_btst_reporting/premarket_card.py src/paper_trading/btst_reporting.py tests/test_generate_btst_premarket_execution_card_script.py && git commit -m "feat: add rollout guardrail to premarket card"
```

## Task 4: Persist rollout source paths and surface them in the doc bundle

**Files:**
- Modify: `src/paper_trading/btst_report_artifact_helpers.py`
- Modify: `scripts/generate_btst_doc_bundle.py`
- Test: `tests/test_generate_btst_doc_bundle_script.py`

- [ ] **Step 1: Write the failing test**

```python
def test_generate_btst_doc_bundle_surfaces_rollout_validation(tmp_path: Path) -> None:
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
            "selected_actions": [],
            "watch_actions": [],
            "opportunity_actions": [],
            "rollout_validation": {
                "status": "governed_shadow_ready",
                "primary_lane": "layer_c_formal_precision_tightening",
                "summary": "先收 formal buy。",
                "source_json_path": str((reports_root / "btst_layer_c_rollout_validation_20260506_20260522.json").resolve()),
            },
        },
    )
    _write_json(reports_root / "btst_full_report_20260526.json", {"trade_date": "20260526", "next_date": "20260527", "pool_size": 1, "selected_count": 0, "near_miss_count": 0, "high_confidence": []})

    result = generate_btst_doc_bundle("20260526", reports_root=reports_root, output_dir=tmp_path / "outputs", refresh_early_runner=False)

    llm_doc = Path(result["written_files"][0]).read_text(encoding="utf-8")
    assert "## Governed Rollout" in llm_doc
    assert "governed_shadow_ready" in llm_doc
    assert "layer_c_formal_precision_tightening" in llm_doc
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_generate_btst_doc_bundle_script.py -k rollout_validation -q
```

Expected: FAIL because the bundle does not render a rollout section yet.

- [ ] **Step 3: Write minimal implementation**

```python
# src/paper_trading/btst_report_artifact_helpers.py
brief_payload = load_json(brief_json_path)
rollout_validation = dict(brief_payload.get("rollout_validation") or {})
followup_manifest = _build_followup_manifest_paths(
    resolved_report_dir=resolved_report_dir,
    resolved_trade_date=resolved_trade_date,
    resolved_next_trade_date=resolved_next_trade_date,
    brief_json_path=brief_json_path,
    brief_markdown_path=brief_markdown_path,
    card_json_path=card_json_path,
    card_markdown_path=card_markdown_path,
    opening_card_json_path=opening_card_json_path,
    opening_card_markdown_path=opening_card_markdown_path,
    priority_board_json_path=priority_board_json_path,
    priority_board_markdown_path=priority_board_markdown_path,
    sync_text_artifact_alias=sync_text_artifact_alias,
)
followup_manifest["rollout_validation_json"] = rollout_validation.get("source_json_path")
followup_manifest["rollout_validation_markdown"] = rollout_validation.get("source_markdown_path")
```

```python
# scripts/generate_btst_doc_bundle.py
def _render_rollout_validation_lines(rollout_validation: dict[str, Any]) -> list[str]:
    return [
        "## Governed Rollout",
        "",
        f"- status: `{rollout_validation.get('status') or 'unavailable'}`",
        f"- primary_lane: `{rollout_validation.get('primary_lane') or 'n/a'}`",
        f"- summary: {rollout_validation.get('summary') or 'n/a'}",
        f"- source_json: `{rollout_validation.get('source_json_path') or 'n/a'}`",
    ]


rollout_validation = dict(brief.get("rollout_validation") or {})
lines.extend(_render_rollout_validation_lines(rollout_validation))
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_generate_btst_doc_bundle_script.py -k rollout_validation -q
```

Expected: PASS and the bundle docs reuse the brief payload instead of re-discovering artifact files.

- [ ] **Step 5: Commit**

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && git add src/paper_trading/btst_report_artifact_helpers.py scripts/generate_btst_doc_bundle.py tests/test_generate_btst_doc_bundle_script.py && git commit -m "feat: surface rollout status in btst bundle"
```

## Task 5: Run the focused integration suite

**Files:**
- Modify: none
- Test: `tests/test_btst_report_utils.py`
- Test: `tests/test_generate_btst_next_day_trade_brief_script.py`
- Test: `tests/test_generate_btst_premarket_execution_card_script.py`
- Test: `tests/test_generate_btst_doc_bundle_script.py`

- [ ] **Step 1: Run the focused suite**

Run:

```bash
cd /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork && uv run pytest tests/test_btst_report_utils.py tests/test_generate_btst_next_day_trade_brief_script.py tests/test_generate_btst_premarket_execution_card_script.py tests/test_generate_btst_doc_bundle_script.py -q
```

Expected: PASS with the new rollout resolver, brief, premarket, and bundle coverage all green.
