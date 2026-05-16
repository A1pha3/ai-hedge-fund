# BTST Structural Promotion Guardrail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dual-layer structural promotion guardrail so BTST candidates that repeatedly widen `selected` / `near_miss` without T+1 support are explained in admission artifacts and blocked by the strict gate.

**Architecture:** Keep the current governance split: `btst_admission_replay_validator.py` becomes the explanatory layer, while `btst_strict_objective_gate.py` becomes the hard blocker layer. `scripts/optimize_profile.py` then consumes the enriched strict-gate result so rollout recommendations and downstream BTST reporting inherit the new blocker automatically.

**Tech Stack:** Python 3.12, pytest, existing BTST replay/rollout scripts, JSON/Markdown report artifacts

---

## File Map

- **Modify:** `scripts/btst_admission_replay_validator.py` — summarize absolute + ratio structure expansion and count excessive replay windows
- **Modify:** `tests/test_btst_admission_replay_validator.py` — cover structural summary logic and emitted payloads
- **Modify:** `scripts/btst_strict_objective_gate.py` — merge structural guardrail summaries into hold/promote blockers
- **Modify:** `tests/test_btst_strict_objective_gate.py` — cover structural blockers and artifact writing
- **Modify:** `scripts/optimize_profile.py` — load the enriched strict gate with structural blockers when rollout payloads are built
- **Modify:** `tests/test_optimize_profile_script.py` — prove rollout recommendation payloads surface the new structural blockers

### Task 1: Add the admission-layer structural summary

**Files:**
- Modify: `tests/test_btst_admission_replay_validator.py`
- Modify: `scripts/btst_admission_replay_validator.py`
- Test: `tests/test_btst_admission_replay_validator.py`

- [ ] **Step 1: Write the failing structural-summary test**

```python
def test_build_admission_replay_summary_reports_structural_expansion_pressure() -> None:
    summary = build_admission_replay_summary(
        baseline_payload={"selected": [{"ticker": "A"}], "near_miss": [{"ticker": "B"}]},
        candidate_payload={"selected": [{"ticker": "A"}, {"ticker": "C"}], "near_miss": [{"ticker": "B"}, {"ticker": "D"}]},
        regime_rows=[{"gate": "normal_trade", "execution_eligible": True, "decision": "selected"}],
        baseline_metrics={"selected_close_win_rate": 47.27, "selected_payoff_ratio": 1.282, "post_fee_expectation_low": -0.16},
        prior_audit={"downgrade_reasons": {}},
        multi_window_validation={
            "report_dir_count": 3,
            "rows": [
                {
                    "report_label": "window-a",
                    "window_recommendation": "mixed",
                    "baseline_tradeable": {"total_count": 10},
                    "variant_tradeable": {"total_count": 11},
                    "baseline_selected": {"total_count": 4},
                    "variant_selected": {"total_count": 5},
                    "baseline_near_miss": {"total_count": 5},
                    "variant_near_miss": {"total_count": 7},
                },
                {
                    "report_label": "window-b",
                    "window_recommendation": "keep_baseline_default",
                    "baseline_tradeable": {"total_count": 9},
                    "variant_tradeable": {"total_count": 9},
                    "baseline_selected": {"total_count": 4},
                    "variant_selected": {"total_count": 5},
                    "baseline_near_miss": {"total_count": 4},
                    "variant_near_miss": {"total_count": 5},
                },
            ],
        },
    )

    structural = summary["structural_guardrail"]
    assert structural["selected_ratio_threshold"] == 0.15
    assert structural["near_miss_ratio_threshold"] == 0.20
    assert structural["excessive_window_count"] == 2
    assert structural["blocker_candidate"] is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/test_btst_admission_replay_validator.py::test_build_admission_replay_summary_reports_structural_expansion_pressure -q
```

Expected: FAIL because `structural_guardrail` is not yet part of the summary payload.

- [ ] **Step 3: Add the minimal structural summary helper**

```python
def _summarize_structural_guardrail(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload:
        return None
    rows = list(payload.get("rows") or [])
    excessive_windows: list[str] = []
    for row in rows:
        if str(row.get("window_recommendation") or "") == "variant_supports_t1_edge":
            continue
        baseline_selected = int((row.get("baseline_selected") or {}).get("total_count") or 0)
        variant_selected = int((row.get("variant_selected") or {}).get("total_count") or 0)
        baseline_near_miss = int((row.get("baseline_near_miss") or {}).get("total_count") or 0)
        variant_near_miss = int((row.get("variant_near_miss") or {}).get("total_count") or 0)
        selected_ratio = (variant_selected - baseline_selected) / max(1, baseline_selected)
        near_miss_ratio = (variant_near_miss - baseline_near_miss) / max(1, baseline_near_miss)
        if selected_ratio > 0.15 or near_miss_ratio > 0.20:
            excessive_windows.append(str(row.get("report_label") or "unknown"))
    return {
        "selected_ratio_threshold": 0.15,
        "near_miss_ratio_threshold": 0.20,
        "excessive_window_count": len(excessive_windows),
        "excessive_window_labels": excessive_windows,
        "blocker_candidate": len(excessive_windows) >= 2,
    }
```

- [ ] **Step 4: Attach the structural summary to the admission payload**

```python
return {
    "approximate_surface_changed": approximate_surface_changed,
    "requires_runtime_replay": requires_runtime_replay,
    "runtime_recommendation": runtime_recommendation,
    "blind_spot_reasons": blind_spot_reasons,
    "baseline_metrics": dict(baseline_metrics),
    "prior_audit": dict(prior_audit),
    "regime_counts": regime_counts,
    "multi_window_validation": multi_window_summary,
    "structural_guardrail": _summarize_structural_guardrail(multi_window_validation),
    "baseline_selected_count": len(list(baseline_payload.get("selected") or [])),
    "candidate_selected_count": len(list(candidate_payload.get("selected") or [])),
    "baseline_near_miss_count": len(list(baseline_payload.get("near_miss") or [])),
    "candidate_near_miss_count": len(list(candidate_payload.get("near_miss") or [])),
}
```

- [ ] **Step 5: Run the focused validator tests**

Run:

```bash
uv run pytest tests/test_btst_admission_replay_validator.py -q
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/btst_admission_replay_validator.py tests/test_btst_admission_replay_validator.py
git commit -m "feat: summarize BTST structural expansion pressure"
```

### Task 2: Turn structural pressure into strict-gate blockers

**Files:**
- Modify: `tests/test_btst_strict_objective_gate.py`
- Modify: `scripts/btst_strict_objective_gate.py`
- Test: `tests/test_btst_strict_objective_gate.py`

- [ ] **Step 1: Write the failing structural-blocker test**

```python
def test_build_strict_btst_objective_gate_adds_structural_blockers() -> None:
    gate = build_strict_btst_objective_gate(
        {
            "Surface Summary": {
                "tradeable_surface": {"positive_rate": 0.4706, "mean_t_plus_2_return": -0.0057},
            },
            "Decision Leaderboard": {
                "rejected": {"positive_rate": 0.4600, "mean_t_plus_2_return": -0.0060},
            },
            "False Negative Strict Goal Cases": [],
        },
        structural_guardrail={
            "selected_ratio_threshold": 0.15,
            "near_miss_ratio_threshold": 0.20,
            "excessive_window_count": 2,
            "excessive_window_labels": ["window-a", "window-b"],
            "blocker_candidate": True,
        },
    )

    assert gate["action"] == "hold"
    assert "structural_expansion_repeated_across_windows" in gate["blockers"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/test_btst_strict_objective_gate.py::test_build_strict_btst_objective_gate_adds_structural_blockers -q
```

Expected: FAIL because `build_strict_btst_objective_gate()` does not yet accept structural inputs.

- [ ] **Step 3: Extend the gate builder and loader**

```python
def build_strict_btst_objective_gate(
    objective_monitor: dict[str, Any],
    *,
    structural_guardrail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blockers: list[str] = []
    ...
    structural_guardrail = dict(structural_guardrail or {})
    if bool(structural_guardrail.get("blocker_candidate")):
        blockers.append("structural_expansion_repeated_across_windows")
    return {
        "action": "hold" if blockers else "promote",
        "blockers": blockers,
        "false_negative_count": len(false_negatives),
        "tradeable_surface": tradeable,
        "rejected_surface": rejected,
        "structural_guardrail": structural_guardrail,
    }
```

```python
def load_strict_btst_objective_gate_from_markdown(
    path: str | Path,
    *,
    structural_guardrail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_strict_btst_objective_gate(
        parse_objective_monitor_markdown(path),
        structural_guardrail=structural_guardrail,
    )
```

- [ ] **Step 4: Teach the CLI entrypoint to accept a structural JSON artifact**

```python
parser.add_argument("--structural-json")
...
structural_guardrail = (
    json.loads(Path(args.structural_json).read_text(encoding="utf-8")).get("structural_guardrail")
    if args.structural_json
    else None
)
payload = load_strict_btst_objective_gate_from_markdown(
    args.input_md,
    structural_guardrail=structural_guardrail,
)
```

- [ ] **Step 5: Run the strict-gate tests**

Run:

```bash
uv run pytest tests/test_btst_strict_objective_gate.py -q
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/btst_strict_objective_gate.py tests/test_btst_strict_objective_gate.py
git commit -m "feat: add structural blockers to strict BTST gate"
```

### Task 3: Wire the new blockers into rollout recommendations

**Files:**
- Modify: `scripts/optimize_profile.py`
- Modify: `tests/test_optimize_profile_script.py`
- Test: `tests/test_optimize_profile_script.py`

- [ ] **Step 1: Write the failing rollout-payload test**

```python
def test_build_rollout_recommendation_payload_appends_structural_guardrail_blockers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        optimize_profile,
        "_load_strict_btst_objective_gate",
        lambda: {
            "action": "hold",
            "blockers": ["structural_expansion_repeated_across_windows"],
            "structural_guardrail": {
                "excessive_window_count": 2,
                "excessive_window_labels": ["window-a", "window-b"],
            },
        },
    )

    payload = optimize_profile._build_rollout_recommendation_payload(
        {
            "default": {
                "next_close_positive_rate_delta": 0.01,
                "next_high_hit_rate_delta": 0.01,
                "next_close_expectancy_delta": 0.002,
                "downside_p10_delta": 0.001,
                "window_coverage_delta": 0.001,
            }
        }
    )

    assert payload["action"] == "hold"
    assert "structural_expansion_repeated_across_windows" in payload["blockers"]
    assert payload["strict_btst_objective_gate"]["structural_guardrail"]["excessive_window_count"] == 2
```

- [ ] **Step 2: Run the test to verify it fails if rollout payload drops the structural guard**

Run:

```bash
uv run pytest tests/test_optimize_profile_script.py::test_build_rollout_recommendation_payload_appends_structural_guardrail_blockers -q
```

Expected: FAIL if the rollout payload does not preserve the enriched strict-gate artifact.

- [ ] **Step 3: Update the strict-gate loader inside optimize_profile**

```python
def _load_strict_btst_objective_gate() -> dict[str, Any] | None:
    objective_monitor_path = REPORTS_DIR / "btst_tplus1_tplus2_objective_monitor_latest.md"
    structural_validation_path = REPORTS_DIR / "btst_admission_edge_replay_validation.json"
    if not objective_monitor_path.exists():
        return None
    structural_guardrail = None
    if structural_validation_path.exists():
        structural_payload = json.loads(structural_validation_path.read_text(encoding="utf-8"))
        structural_guardrail = dict(structural_payload.get("structural_guardrail") or {})
    return build_strict_btst_objective_gate(
        parse_objective_monitor_markdown(objective_monitor_path),
        structural_guardrail=structural_guardrail,
    )
```

- [ ] **Step 4: Run the focused optimizer test**

Run:

```bash
uv run pytest tests/test_optimize_profile_script.py::test_build_rollout_recommendation_payload_appends_structural_guardrail_blockers -q
```

Expected: PASS

- [ ] **Step 5: Run the cross-surface regression slice**

Run:

```bash
uv run pytest tests/test_btst_admission_replay_validator.py tests/test_btst_strict_objective_gate.py tests/test_optimize_profile_script.py -k 'structural or strict_btst_objective_gate or admission_replay' -q
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/optimize_profile.py tests/test_optimize_profile_script.py
git commit -m "feat: honor BTST structural blockers in rollout payloads"
```

## Self-Review Notes

1. **Spec coverage:** Task 1 adds the admission-layer explanation, Task 2 adds the strict-gate blocker, and Task 3 ensures optimize_profile consumes the enriched gate so rollout decisions inherit the new policy.
2. **No placeholders:** every task includes exact files, commands, and code snippets for the engineer to follow.
3. **Type consistency:** the structural payload is consistently named `structural_guardrail`, and the hard blocker name is consistently `structural_expansion_repeated_across_windows`.
