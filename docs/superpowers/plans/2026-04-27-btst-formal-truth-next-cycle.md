# BTST Formal Truth Next-Cycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make BTST execution-facing reports obey formal executable truth, then extend that safer surface into a strict corridor release lane and a gated T+2/T+3 continuation lane.

**Architecture:** Keep one mainline and two gated follow-ons. The mainline threads formal execution eligibility from `selection_targets` into every BTST report surface; the follow-ons reuse that truth path for corridor release and carryover continuation without broadening default formal admission.

**Tech Stack:** Python 3.12, pytest, existing BTST paper-trading/reporting pipeline, JSON artifact replay helpers

---

## File Map

- Modify: `src/paper_trading/_btst_reporting/entry_builders.py`
  - Add helpers that classify whether a BTST row is formally executable or only research/shadow-visible.
- Modify: `src/paper_trading/_btst_reporting/brief_builder.py`
  - Ensure selected/near-miss/opportunity buckets are built from execution truth instead of raw selected rows.
- Modify: `src/paper_trading/_btst_reporting/premarket_card.py`
  - Render zero-state primary actions when a day has no formal executable BTST names.
- Modify: `src/paper_trading/_btst_reporting/priority_board.py`
  - Filter priority rows to the same executable truth path used by the brief.
- Modify: `scripts/btst_latest_followup_utils.py`
  - Preserve the latest followup candidate without letting older selected-style rows outrank newer blocked/rejected truth.
- Modify: `scripts/run_btst_nightly_control_tower.py`
  - Reflect zero-executable BTST states in nightly summaries and recommended actions.
- Modify: `src/screening/candidate_pool_shadow_helpers.py`
  - Thread strict-release metadata for corridor names.
- Modify: `src/screening/candidate_pool_shadow_payload_helpers.py`
  - Convert the deepest-corridor retained probe into a governed release lane instead of a visibility-only lane.
- Modify: `scripts/run_btst_candidate_pool_corridor_validation_pack.py`
  - Output the strict-release focus rows and keep non-qualified rows in validation-only mode.
- Modify: `scripts/analyze_btst_carryover_peer_promotion_gate.py`
  - Keep default carryover expansion disabled unless a peer set is actually ready.
- Modify: `scripts/generate_btst_tplus2_continuation_promotion_gate.py`
  - Surface the same readiness gate into promotion artifacts.
- Test: `tests/test_generate_btst_next_day_trade_brief_script.py`
- Test: `tests/test_btst_control_tower_scripts.py`
- Test: `tests/screening/test_candidate_pool.py`
- Test: `tests/test_btst_candidate_pool_validation_bundles.py`
- Test: `tests/test_analyze_btst_carryover_peer_promotion_gate_script.py`

### Task 1: Enforce formal executable truth across BTST reports

**Files:**
- Modify: `tests/test_generate_btst_next_day_trade_brief_script.py`
- Modify: `tests/test_btst_control_tower_scripts.py`
- Modify: `src/paper_trading/_btst_reporting/entry_builders.py`
- Modify: `src/paper_trading/_btst_reporting/brief_builder.py`
- Modify: `src/paper_trading/_btst_reporting/premarket_card.py`
- Modify: `src/paper_trading/_btst_reporting/priority_board.py`
- Modify: `scripts/btst_latest_followup_utils.py`
- Modify: `scripts/run_btst_nightly_control_tower.py`

- [ ] **Step 1: Write the failing brief/control-tower tests**

```python
def test_analyze_btst_next_day_trade_brief_halt_day_has_no_formal_primary_entry(tmp_path):
    report_dir = tmp_path / "halt_day"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "session_summary.json").write_text(
        json.dumps(
            {
                "plan_generation": {"selection_target": "short_trade_only"},
                "btst_followup": {"trade_date": "2026-04-24"},
                "artifacts": {},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    target_dir = report_dir / "selection_artifacts" / "2026-04-24"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "selection_snapshot.json").write_text(json.dumps({"selected": [], "near_miss": []}) + "\n", encoding="utf-8")
    (target_dir / "selection_target_replay_input.json").write_text(
        json.dumps(
            {
                "selection_targets": {
                    "600176": {
                        "ticker": "600176",
                        "p2_execution_blocked": True,
                        "p2_execution_block_reason": "p2_regime_gate_enforce:halt",
                        "short_trade": {
                            "decision": "selected",
                            "score_target": 0.60,
                            "preferred_entry_mode": "confirm_then_hold_breakout",
                        },
                    }
                }
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_btst_next_day_trade_brief(report_dir)

    assert analysis["primary_entry"] is None
    assert analysis["selected_entries"] == []
    assert analysis["opportunity_pool_entries"] == []


def test_build_btst_nightly_control_tower_payload_surfaces_zero_formal_executable_btst():
    payload = build_btst_nightly_control_tower_payload(
        manifest={"reports_root": "/tmp/reports", "entries": []},
        report_payloads={
            "latest_btst_followup": {
                "trade_date": "2026-04-24",
                "selected_count": 0,
                "blocked_count": 2,
                "entries": [],
                "brief_recommendation": "halt day",
            }
        },
    )

    assert payload["control_tower_snapshot"]["latest_btst_followup"]["selected_count"] == 0
    assert "0 formal executable" in payload["control_tower_snapshot"]["latest_btst_followup"]["brief_recommendation"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_generate_btst_next_day_trade_brief_script.py tests/test_btst_control_tower_scripts.py -k 'halt_day or zero_formal_executable' -q`

Expected: FAIL because the current brief/control-tower flow still derives rows from raw selected-style entries.

- [ ] **Step 3: Write the minimal execution-truth helpers and thread them through report builders**

```python
# src/paper_trading/_btst_reporting/entry_builders.py
def _is_formal_btst_execution_entry(selection_entry: dict[str, Any]) -> bool:
    short_trade = dict(selection_entry.get("short_trade") or {})
    if str(short_trade.get("decision") or "") != "selected":
        return False
    if selection_entry.get("p2_execution_blocked"):
        return False
    if selection_entry.get("p3_execution_blocked"):
        return False
    if selection_entry.get("p5_execution_blocked"):
        return False
    if selection_entry.get("p6_execution_blocked"):
        return False
    return True


def _is_formal_btst_watch_entry(selection_entry: dict[str, Any]) -> bool:
    short_trade = dict(selection_entry.get("short_trade") or {})
    return str(short_trade.get("decision") or "") == "near_miss"
```

```python
# src/paper_trading/_btst_reporting/brief_builder.py
def _build_btst_brief_candidate_groups(*, snapshot: dict[str, Any], selection_targets: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    formal_selected = []
    formal_near_miss = []
    blocked_selected = []
    for ticker, selection_entry in selection_targets.items():
        normalized = dict(selection_entry or {})
        normalized.setdefault("ticker", ticker)
        if _is_formal_btst_execution_entry(normalized):
            formal_selected.append(normalized)
        elif _is_formal_btst_watch_entry(normalized):
            formal_near_miss.append(normalized)
        elif str(dict(normalized.get("short_trade") or {}).get("decision") or "") == "selected":
            blocked_selected.append(normalized)
    return {
        "selected_entries": formal_selected,
        "near_miss_entries": formal_near_miss,
        "blocked_selected_entries": blocked_selected,
    }
```

```python
# src/paper_trading/_btst_reporting/premarket_card.py
def _build_premarket_action_context(brief: dict[str, Any]) -> dict[str, Any]:
    primary_entry = brief.get("primary_entry")
    zero_formal_executable = primary_entry is None and not list(brief.get("selected_entries") or [])
    return {
        "primary_entry": primary_entry,
        "zero_formal_executable": zero_formal_executable,
        "primary_action": _build_premarket_primary_action(primary_entry) if primary_entry else None,
        "watch_actions": _build_watch_actions(list(brief.get("near_miss_entries") or [])),
    }
```

```python
# scripts/run_btst_nightly_control_tower.py
def _summarize_latest_btst_followup(latest_followup: dict[str, Any]) -> dict[str, Any]:
    selected_count = int(latest_followup.get("selected_count") or 0)
    blocked_count = int(latest_followup.get("blocked_count") or 0)
    recommendation = str(latest_followup.get("brief_recommendation") or "")
    if selected_count == 0 and blocked_count > 0:
        recommendation = f"0 formal executable BTST names. {recommendation}".strip()
    return {**latest_followup, "brief_recommendation": recommendation}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_generate_btst_next_day_trade_brief_script.py tests/test_btst_control_tower_scripts.py -k 'halt_day or zero_formal_executable' -q`

Expected: PASS

- [ ] **Step 5: Run the full reporting regression bundle**

Run: `uv run pytest tests/test_generate_btst_next_day_trade_brief_script.py tests/test_btst_control_tower_scripts.py tests/test_run_paper_trading_script.py tests/test_btst_regime_gate_shadow.py tests/backtesting/test_paper_trading_runtime.py -k 'not writes_cache_benchmark_artifacts' -q`

Expected: PASS with no new failures in BTST reporting/runtime regressions.

- [ ] **Step 6: Commit**

```bash
git add tests/test_generate_btst_next_day_trade_brief_script.py tests/test_btst_control_tower_scripts.py src/paper_trading/_btst_reporting/entry_builders.py src/paper_trading/_btst_reporting/brief_builder.py src/paper_trading/_btst_reporting/premarket_card.py src/paper_trading/_btst_reporting/priority_board.py scripts/btst_latest_followup_utils.py scripts/run_btst_nightly_control_tower.py
git commit -m "fix(btst): align reports with formal executable truth"
```

### Task 2: Convert corridor false negatives into a strict-release lane

**Files:**
- Modify: `tests/screening/test_candidate_pool.py`
- Modify: `tests/test_btst_candidate_pool_validation_bundles.py`
- Modify: `src/screening/candidate_pool_shadow_helpers.py`
- Modify: `src/screening/candidate_pool_shadow_payload_helpers.py`
- Modify: `scripts/run_btst_candidate_pool_corridor_validation_pack.py`

- [ ] **Step 1: Write the failing strict-release tests**

```python
def test_candidate_pool_shadow_release_only_promotes_retained_corridor_focus():
    overflow = [
        {
            "ticker": "301188",
            "candidate_pool_lane": "layer_a_liquidity_corridor",
            "candidate_pool_avg_amount_share_of_cutoff": 0.074,
            "candidate_pool_avg_amount_share_of_min_gate": 2.5,
        },
        {
            "ticker": "688796",
            "candidate_pool_lane": "layer_a_liquidity_corridor",
            "candidate_pool_avg_amount_share_of_cutoff": 0.0821,
            "candidate_pool_avg_amount_share_of_min_gate": 2.46,
        },
    ]

    payload = _resolve_shadow_overflow_payload(
        lane_name="layer_a_liquidity_corridor",
        candidates=overflow,
        max_tickers=2,
    )

    assert payload["release_focus_tickers"] == ["301188"]
    assert payload["validation_only_tickers"] == ["688796"]


def test_corridor_validation_pack_exposes_strict_release_focus(tmp_path):
    analysis = analyze_btst_candidate_pool_corridor_validation_pack(
        tmp_path / "btst_candidate_pool_recall_dossier_latest.json",
        corridor_narrow_probe_path=tmp_path / "btst_candidate_pool_corridor_narrow_probe_latest.json",
    )

    assert "strict_release_focus_tickers" in analysis
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/screening/test_candidate_pool.py tests/test_btst_candidate_pool_validation_bundles.py -k 'strict_release or release_focus' -q`

Expected: FAIL because corridor output currently distinguishes retained/excluded names for diagnostics, but not as a dedicated strict-release contract.

- [ ] **Step 3: Write the minimal strict-release implementation**

```python
# src/screening/candidate_pool_shadow_payload_helpers.py
def _split_corridor_release_candidates(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    release_rows = []
    validation_rows = []
    for row in rows:
        cutoff_share = float(row.get("candidate_pool_avg_amount_share_of_cutoff") or 999.0)
        min_gate_share = float(row.get("candidate_pool_avg_amount_share_of_min_gate") or 0.0)
        if min_gate_share >= 2.0 and cutoff_share <= SHADOW_LIQUIDITY_CORRIDOR_FOCUS_LOW_GATE_MAX_CUTOFF_SHARE:
            release_rows.append(row)
        else:
            validation_rows.append(row)
    return release_rows, validation_rows


def _resolve_shadow_overflow_payload(...):
    release_rows, validation_rows = _split_corridor_release_candidates(selected_rows)
    payload["release_focus_tickers"] = [row["ticker"] for row in release_rows]
    payload["validation_only_tickers"] = [row["ticker"] for row in validation_rows]
```

```python
# scripts/run_btst_candidate_pool_corridor_validation_pack.py
analysis["strict_release_focus_tickers"] = [str(row.get("ticker") or "") for row in corridor_ticker_rows if str(row.get("ticker") or "") in set(corridor_narrow_probe.get("deepest_corridor_focus_tickers") or [])]
analysis["validation_only_tickers"] = sorted(excluded_low_gate_tail_tickers)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/screening/test_candidate_pool.py tests/test_btst_candidate_pool_validation_bundles.py -k 'strict_release or release_focus' -q`

Expected: PASS

- [ ] **Step 5: Run the broader corridor regression suite**

Run: `uv run pytest tests/screening/test_candidate_pool.py tests/test_analyze_btst_candidate_pool_corridor_window_diagnostics_script.py tests/test_analyze_btst_candidate_pool_corridor_narrow_probe_script.py tests/test_analyze_btst_candidate_pool_corridor_persistence_dossier_script.py tests/test_analyze_btst_candidate_pool_lane_objective_support_script.py tests/test_analyze_btst_candidate_pool_branch_priority_board_script.py tests/test_analyze_btst_candidate_pool_recall_dossier_script.py tests/test_run_btst_candidate_pool_rebucket_shadow_pack_script.py tests/test_btst_candidate_pool_validation_bundles.py -q`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/screening/test_candidate_pool.py tests/test_btst_candidate_pool_validation_bundles.py src/screening/candidate_pool_shadow_helpers.py src/screening/candidate_pool_shadow_payload_helpers.py scripts/run_btst_candidate_pool_corridor_validation_pack.py
git commit -m "feat(btst): add strict corridor release lane"
```

### Task 3: Keep T+2/T+3 expansion behind a ready-only carryover gate

**Files:**
- Modify: `tests/test_analyze_btst_carryover_peer_promotion_gate_script.py`
- Modify: `scripts/analyze_btst_carryover_peer_promotion_gate.py`
- Modify: `scripts/generate_btst_tplus2_continuation_promotion_gate.py`

- [ ] **Step 1: Write the failing carryover-gate tests**

```python
def test_carryover_peer_promotion_gate_does_not_mark_ready_when_peer_set_is_pending(tmp_path):
    gate_path = tmp_path / "btst_carryover_peer_promotion_gate_latest.json"
    gate_path.write_text(
        json.dumps(
            {
                "ready_tickers": [],
                "pending_t_plus_2_tickers": ["300620", "300502"],
                "focus_ticker": "300620",
                "focus_gate_verdict": "await_peer_t_plus_2_close",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_btst_carryover_peer_promotion_gate(gate_path)

    assert analysis["default_expansion_status"] == "pending_peer_proof"
    assert analysis["promotion_ready_tickers"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_analyze_btst_carryover_peer_promotion_gate_script.py -k pending_peer_proof -q`

Expected: FAIL because the current gate analysis emphasizes status reporting but does not expose an explicit default-expansion contract.

- [ ] **Step 3: Write the minimal carryover gate contract**

```python
# scripts/analyze_btst_carryover_peer_promotion_gate.py
def _resolve_default_expansion_status(payload: dict[str, Any]) -> str:
    ready_tickers = list(payload.get("ready_tickers") or [])
    if ready_tickers:
        return "ready_for_peer_promotion"
    return "pending_peer_proof"


def analyze_btst_carryover_peer_promotion_gate(...):
    analysis["default_expansion_status"] = _resolve_default_expansion_status(analysis)
    analysis["promotion_ready_tickers"] = list(analysis.get("ready_tickers") or [])
```

```python
# scripts/generate_btst_tplus2_continuation_promotion_gate.py
payload["default_expansion_status"] = analysis["default_expansion_status"]
payload["promotion_ready_tickers"] = analysis["promotion_ready_tickers"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_analyze_btst_carryover_peer_promotion_gate_script.py -k pending_peer_proof -q`

Expected: PASS

- [ ] **Step 5: Run the carryover regression suite**

Run: `uv run pytest tests/test_analyze_btst_carryover_peer_promotion_gate_script.py tests/test_run_btst_nightly_control_tower_script.py -k 'not writes_cache_benchmark_artifacts' -q`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_analyze_btst_carryover_peer_promotion_gate_script.py scripts/analyze_btst_carryover_peer_promotion_gate.py scripts/generate_btst_tplus2_continuation_promotion_gate.py
git commit -m "feat(btst): gate carryover expansion on ready peers"
```

## Self-Review

### Spec coverage

- Formal executable reporting truth -> covered by Task 1.
- Corridor strict-release lane -> covered by Task 2.
- T+2/T+3 carryover gate-first expansion -> covered by Task 3.
- Verification on weekly replay/report artifacts -> covered by Task 1 regression bundle and zero-executable assertions.

### Placeholder scan

- No `TODO`, `TBD`, or “similar to previous task” placeholders remain.
- Each task contains concrete files, tests, commands, and code snippets.

### Type consistency

- The plan consistently uses `selection_targets` as the source of truth.
- New helper names are reused consistently:
  - `_is_formal_btst_execution_entry`
  - `_is_formal_btst_watch_entry`
  - `_split_corridor_release_candidates`
  - `_resolve_default_expansion_status`
