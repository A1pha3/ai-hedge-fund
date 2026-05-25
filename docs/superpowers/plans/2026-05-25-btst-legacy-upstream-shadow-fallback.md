# BTST Legacy Upstream Shadow Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let legacy BTST report directories that have no `selection_artifacts/` still regenerate upstream-shadow historical priors from existing `btst_next_day_trade_brief_latest.json`.

**Architecture:** Keep the normal `selection_artifacts` path unchanged. Add a narrow fallback that activates only when a report directory has no `selection_artifacts` but does have a legacy brief JSON with `upstream_shadow_entries`; load those entries, re-run `_enrich_upstream_shadow_entries_with_history(...)`, and build a minimal brief payload that downstream followup artifact generators can reuse.

**Tech Stack:** Python 3.11+, pytest, existing BTST reporting helpers under `src/paper_trading/_btst_reporting/`

---

## File structure

- Modify: `src/paper_trading/_btst_reporting/entry_builders.py`
  - Add a legacy-brief resolver/helper for report dirs without `selection_artifacts`.
- Modify: `src/paper_trading/_btst_reporting/brief_builder.py`
  - Route missing-`selection_artifacts` report dirs through the new fallback and enrich the recovered upstream-shadow entries with history.
- Modify: `src/paper_trading/btst_reporting.py`
  - Preserve the existing public generation flow while allowing the fallback-backed brief payload to flow into artifact generation.
- Modify: `tests/test_generate_btst_next_day_trade_brief_script.py`
  - Add focused regression tests for the legacy fallback.
- Modify: `tests/test_generate_btst_premarket_execution_card_script.py`
  - Add a narrow downstream test proving the fallback-backed brief still feeds card generation.

### Task 1: Lock the fallback contract with failing tests

**Files:**
- Modify: `tests/test_generate_btst_next_day_trade_brief_script.py`
- Test: `tests/test_generate_btst_next_day_trade_brief_script.py`

- [ ] **Step 1: Write the failing legacy-brief fallback test**

```python
def test_analyze_btst_next_day_trade_brief_recovers_upstream_shadow_from_legacy_brief(monkeypatch, tmp_path):
    report_dir = tmp_path / "legacy-report"
    report_dir.mkdir()
    (report_dir / "session_summary.json").write_text("{}", encoding="utf-8")
    (report_dir / "btst_next_day_trade_brief_latest.json").write_text(
        json.dumps(
            {
                "trade_date": "20260421",
                "next_trade_date": "20260422",
                "selected": [],
                "near_miss": [],
                "opportunity_pool": [],
                "research_upside_radar": [],
                "catalyst_theme_frontier": [],
                "upstream_shadow_entries": [
                    {
                        "ticker": "000546",
                        "decision": "rejected",
                        "score_target": 0.4333,
                        "confidence": 0.4394,
                        "preferred_entry_mode": "next_day_breakout_confirmation",
                        "candidate_source": "upstream_liquidity_corridor_shadow",
                        "candidate_pool_lane": "layer_a_liquidity_corridor",
                        "candidate_pool_lane_display": "layer_a_liquidity_corridor",
                        "candidate_pool_rank": 1611,
                        "candidate_reason_codes": [
                            "upstream_base_liquidity_uplift_shadow",
                            "candidate_pool_truncated_after_filters",
                        ],
                        "top_reasons": ["trend_acceleration_supportive"],
                        "rejection_reasons": ["selected_rank_cap_exceeded"],
                        "positive_tags": ["trend_acceleration_confirmed"],
                        "gate_status": {"data": "pass", "structural": "pass", "score": "fail"},
                        "promotion_trigger": "影子召回样本尚未进入可执行层，只有盘中新强度确认后才允许升级。",
                        "metrics": {
                            "breakout_freshness": 0.3952,
                            "trend_acceleration": 0.7244,
                            "volume_expansion_quality": 0.247,
                            "close_strength": 0.8804,
                            "catalyst_freshness": 0.0,
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        brief_builder,
        "_enrich_upstream_shadow_entries_with_history",
        lambda **kwargs: [{**kwargs["upstream_shadow_entries"][0], "historical_prior": {"sample_count": 9, "applied_scope": "candidate_source"}}],
    )

    analysis = brief_builder.analyze_btst_next_day_trade_brief(report_dir)

    assert [entry["ticker"] for entry in analysis["upstream_shadow_entries"]] == ["000546"]
    assert analysis["upstream_shadow_entries"][0]["historical_prior"]["sample_count"] == 9
```

- [ ] **Step 2: Run the test to verify the current code fails**

Run:

```bash
uv run pytest tests/test_generate_btst_next_day_trade_brief_script.py::test_analyze_btst_next_day_trade_brief_recovers_upstream_shadow_from_legacy_brief -v
```

Expected: FAIL with `FileNotFoundError: selection_artifacts directory not found under ...`

- [ ] **Step 3: Add a downstream card-generation regression**

```python
def test_generate_btst_premarket_execution_card_works_with_legacy_brief_fallback(monkeypatch, tmp_path):
    report_dir = tmp_path / "legacy-report"
    report_dir.mkdir()
    (report_dir / "session_summary.json").write_text("{}", encoding="utf-8")
    legacy_brief = {
        "trade_date": "20260421",
        "next_trade_date": "20260422",
        "selected": [],
        "near_miss": [],
        "opportunity_pool": [],
        "research_upside_radar": [],
        "catalyst_theme_frontier": [],
        "upstream_shadow_entries": [
            {
                "ticker": "000546",
                "decision": "rejected",
                "candidate_source": "upstream_liquidity_corridor_shadow",
                "top_reasons": ["trend_acceleration_supportive"],
                "rejection_reasons": ["selected_rank_cap_exceeded"],
                "positive_tags": ["trend_acceleration_confirmed"],
                "gate_status": {"data": "pass", "structural": "pass", "score": "fail"},
                "historical_prior": {"sample_count": 9, "execution_quality_label": "balanced_confirmation"},
            }
        ],
    }
    (report_dir / "btst_next_day_trade_brief_latest.json").write_text(json.dumps(legacy_brief, ensure_ascii=False), encoding="utf-8")

    payload = btst_reporting.analyze_btst_premarket_execution_card(report_dir)

    assert [entry["ticker"] for entry in payload["upstream_shadow_entries"]] == ["000546"]
    assert payload["upstream_shadow_entries"][0]["historical_prior"]["sample_count"] == 9
```

- [ ] **Step 4: Run the downstream regression to verify the gap is real**

Run:

```bash
uv run pytest tests/test_generate_btst_premarket_execution_card_script.py::test_generate_btst_premarket_execution_card_works_with_legacy_brief_fallback -v
```

Expected: FAIL because the brief-analysis path still requires `selection_artifacts`.

- [ ] **Step 5: Commit the red tests**

```bash
git add tests/test_generate_btst_next_day_trade_brief_script.py tests/test_generate_btst_premarket_execution_card_script.py
git commit -m "test: lock btst legacy upstream-shadow fallback"
```

### Task 2: Implement the legacy upstream-shadow fallback

**Files:**
- Modify: `src/paper_trading/_btst_reporting/entry_builders.py`
- Modify: `src/paper_trading/_btst_reporting/brief_builder.py`
- Modify: `src/paper_trading/btst_reporting.py`
- Test: `tests/test_generate_btst_next_day_trade_brief_script.py`
- Test: `tests/test_generate_btst_premarket_execution_card_script.py`

- [ ] **Step 1: Add a focused legacy-brief loader in `entry_builders.py`**

```python
def _load_legacy_brief_upstream_shadow_entries(report_dir: Path) -> dict[str, Any] | None:
    legacy_brief_path = report_dir / "btst_next_day_trade_brief_latest.json"
    if not legacy_brief_path.exists():
        return None
    payload = json.loads(legacy_brief_path.read_text(encoding="utf-8"))
    upstream_shadow_entries = [
        dict(entry)
        for entry in list(payload.get("upstream_shadow_entries") or [])
        if str(entry.get("ticker") or "").strip()
        and str(entry.get("candidate_source") or "").strip()
    ]
    if not upstream_shadow_entries:
        return None
    return {
        "trade_date": payload.get("trade_date"),
        "next_trade_date": payload.get("next_trade_date"),
        "upstream_shadow_entries": upstream_shadow_entries,
    }
```

- [ ] **Step 2: Keep the normal snapshot path unchanged, but expose a legacy fallback probe**

```python
def _resolve_snapshot_or_legacy_brief(input_path: str | Path, trade_date: str | None) -> dict[str, Any]:
    resolved_input = Path(input_path).expanduser().resolve()
    if resolved_input.is_dir() and not (resolved_input / "selection_artifacts").exists():
        legacy_payload = _load_legacy_brief_upstream_shadow_entries(resolved_input)
        if legacy_payload is not None:
            return {
                "mode": "legacy_brief",
                "report_dir": resolved_input,
                "snapshot_path": None,
                **legacy_payload,
            }
    snapshot_path, report_dir = _resolve_snapshot_path(resolved_input, trade_date)
    return {
        "mode": "selection_snapshot",
        "report_dir": report_dir,
        "snapshot_path": snapshot_path,
        "trade_date": trade_date,
        "next_trade_date": None,
        "upstream_shadow_entries": [],
    }
```

- [ ] **Step 3: Teach `brief_builder.py` to build a minimal legacy brief**

```python
resolved_input = _resolve_snapshot_or_legacy_brief(input_path, trade_date)
report_dir = resolved_input["report_dir"]
if resolved_input["mode"] == "legacy_brief":
    upstream_shadow_entries = _enrich_upstream_shadow_entries_with_history(
        report_dir=report_dir,
        actual_trade_date=_normalize_trade_date(resolved_input.get("trade_date")),
        upstream_shadow_entries=list(resolved_input["upstream_shadow_entries"]),
    )
    return {
        "trade_date": _normalize_trade_date(resolved_input.get("trade_date")),
        "next_trade_date": _normalize_trade_date(resolved_input.get("next_trade_date")),
        "selected": [],
        "near_miss": [],
        "opportunity_pool": [],
        "research_upside_radar": [],
        "catalyst_theme_frontier": [],
        "upstream_shadow_entries": upstream_shadow_entries,
        "upstream_shadow_summary": _build_upstream_shadow_summary(upstream_shadow_entries),
        "btst_candidate_historical_context": _build_empty_btst_candidate_historical_context(),
        "watch_candidate_historical_context": _build_empty_btst_candidate_historical_context(),
        "opportunity_pool_historical_context": _build_empty_btst_candidate_historical_context(),
        "excluded_research_entries": [],
        "recommendation": "",
    }
```

- [ ] **Step 4: Keep public artifact generation unchanged**

```python
def generate_btst_next_day_trade_brief_artifacts(...):
    return _generate_btst_next_day_trade_brief_artifacts_impl(
        input_path=input_path,
        output_dir=output_dir,
        trade_date=trade_date,
        next_trade_date=next_trade_date,
        file_stem=file_stem,
        analyze_btst_next_day_trade_brief=analyze_btst_next_day_trade_brief,
        render_btst_next_day_trade_brief_markdown=render_btst_next_day_trade_brief_markdown,
        build_output_file_stem=_build_output_file_stem,
        write_analysis_artifacts=_write_analysis_artifacts,
    )
```

The implementation goal here is *not* to change `btst_reporting.py` semantics, only to verify the new fallback stays behind the existing public APIs.

- [ ] **Step 5: Run the focused tests and make them pass**

Run:

```bash
uv run pytest \
  tests/test_generate_btst_next_day_trade_brief_script.py::test_analyze_btst_next_day_trade_brief_recovers_upstream_shadow_from_legacy_brief \
  tests/test_generate_btst_premarket_execution_card_script.py::test_generate_btst_premarket_execution_card_works_with_legacy_brief_fallback \
  -v
```

Expected: PASS

- [ ] **Step 6: Commit the implementation**

```bash
git add src/paper_trading/_btst_reporting/entry_builders.py src/paper_trading/_btst_reporting/brief_builder.py src/paper_trading/btst_reporting.py tests/test_generate_btst_next_day_trade_brief_script.py tests/test_generate_btst_premarket_execution_card_script.py
git commit -m "feat: support btst legacy upstream-shadow fallback"
```

### Task 3: Prove the fallback closes the real 000546 blocker

**Files:**
- Modify: `tests/test_generate_btst_next_day_trade_brief_script.py`
- Test: `tests/test_generate_btst_next_day_trade_brief_script.py`
- Test: `scripts/analyze_btst_upstream_shadow_unknown_prior_audit.py`

- [ ] **Step 1: Add a real-shape fixture test using the 000546 report layout**

```python
def test_generate_btst_next_day_trade_brief_legacy_report_shape_includes_upstream_shadow_prior(tmp_path):
    report_dir = tmp_path / "paper_trading_20260421_20260421_live_m2_7_short_trade_only_20260422_plan"
    report_dir.mkdir()
    (report_dir / "session_summary.json").write_text("{}", encoding="utf-8")
    (report_dir / "btst_next_day_trade_brief_latest.json").write_text(
        json.dumps(
            {
                "trade_date": "20260421",
                "next_trade_date": "20260422",
                "upstream_shadow_entries": [
                    {
                        "ticker": "000546",
                        "decision": "rejected",
                        "candidate_source": "upstream_liquidity_corridor_shadow",
                        "metrics": {"trend_acceleration": 0.7244, "close_strength": 0.8804},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    analysis = brief_builder.analyze_btst_next_day_trade_brief(report_dir)

    assert analysis["upstream_shadow_entries"][0]["ticker"] == "000546"
    assert "historical_prior" in analysis["upstream_shadow_entries"][0]
```

- [ ] **Step 2: Run the BTST reporting regression pack**

Run:

```bash
uv run pytest \
  tests/test_generate_btst_next_day_trade_brief_script.py \
  tests/test_generate_btst_premarket_execution_card_script.py \
  -q
```

Expected: PASS

- [ ] **Step 3: Re-run the real residual audit workflow**

Run:

```bash
uv run python scripts/analyze_btst_upstream_shadow_unknown_prior_audit.py \
  --reports-root /Users/matrix/.copilot/session-state/359fb789-0911-44b2-900a-26f7e4891fab/files/patched_reports_20260512 \
  --output-json /Users/matrix/.copilot/session-state/359fb789-0911-44b2-900a-26f7e4891fab/files/patched_unknown_prior_audit_000546_fallback.json \
  --output-md /Users/matrix/.copilot/session-state/359fb789-0911-44b2-900a-26f7e4891fab/files/patched_unknown_prior_audit_000546_fallback.md
```

Expected: `remaining_missing_upstream_prior_source_split` is empty, or `000546` leaves the `missing_upstream_prior` board.

- [ ] **Step 4: Commit the verification updates**

```bash
git add tests/test_generate_btst_next_day_trade_brief_script.py /Users/matrix/.copilot/session-state/359fb789-0911-44b2-900a-26f7e4891fab/files/patched_unknown_prior_audit_000546_fallback.json /Users/matrix/.copilot/session-state/359fb789-0911-44b2-900a-26f7e4891fab/files/patched_unknown_prior_audit_000546_fallback.md
git commit -m "test: verify btst legacy fallback closes 000546 gap"
```

## Self-review

- Spec coverage: the plan covers the only remaining blocker (`000546`) and the intended repair seam (legacy brief fallback instead of broader upstream-shadow logic changes).
- Placeholder scan: no `TODO`/`TBD`; every task has concrete files, commands, and code snippets.
- Type consistency: the plan keeps the public `analyze_*` / `generate_*` APIs intact and scopes the new behavior to a private resolver/helper plus brief-builder fallback path.

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-25-btst-legacy-upstream-shadow-fallback.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints
