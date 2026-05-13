# BTST Optimized Profile Publisher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically publish the latest rollout-approved BTST optimize result to `data/reports/btst_latest_optimized_profile.json` so the BTST skill consumes the newest approved configuration by default.

**Architecture:** Keep production and consumption separated. Add a focused publisher helper for canonical manifest generation/publication, then wire `scripts/optimize_profile.py` to invoke it only for BTST replay runs whose rollout recommendation is `promote`, while preserving the last ready manifest on hold runs.

**Tech Stack:** Python 3.12, pytest, existing `scripts/optimize_profile.py` pipeline, JSON artifacts under `data/reports/`

---

## File structure

- Create: `scripts/btst_optimized_profile_manifest_helpers.py`
  - Build canonical manifest payloads
  - Parse latest replay trade date
  - Publish or skip with explicit status payload
- Modify: `scripts/optimize_profile.py`
  - Call publisher helper after search payload persistence
  - Thread publication status into JSON + Markdown outputs
- Modify: `tests/test_optimize_profile_script.py`
  - Add publisher helper and optimize main integration coverage

### Task 1: Add publisher helper with explicit publish/skip semantics

**Files:**
- Create: `scripts/btst_optimized_profile_manifest_helpers.py`
- Test: `tests/test_optimize_profile_script.py`

- [ ] **Step 1: Write the failing helper tests**

```python
def test_publish_btst_optimized_profile_manifest_writes_ready_manifest(tmp_path: Path) -> None:
    manifest_path = tmp_path / "btst_latest_optimized_profile.json"
    source_path = tmp_path / "search.json"
    source_path.write_text("{}", encoding="utf-8")

    result = publish_btst_optimized_profile_manifest(
        profile_name="momentum_optimized",
        profile_overrides={"select_threshold": 0.50},
        source_path=source_path,
        rollout_recommendation="promote",
        rollout_recommendation_details={"blockers": []},
        replay_input_paths=[
            tmp_path / "selection_artifacts" / "2026-05-09" / "selection_target_replay_input.json",
            tmp_path / "selection_artifacts" / "2026-05-12" / "selection_target_replay_input.json",
        ],
        manifest_path=manifest_path,
    )

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert result["status"] == "published"
    assert payload["profile_name"] == "momentum_optimized"
    assert payload["profile_overrides"] == {"select_threshold": 0.50}
    assert payload["status"] == "ready"
    assert payload["trade_date"] == "2026-05-12"


def test_publish_btst_optimized_profile_manifest_skips_hold_without_overwriting_existing_ready(tmp_path: Path) -> None:
    manifest_path = tmp_path / "btst_latest_optimized_profile.json"
    manifest_path.write_text(
        json.dumps({"profile_name": "momentum_optimized", "profile_overrides": {"select_threshold": 0.46}, "status": "ready"}),
        encoding="utf-8",
    )
    source_path = tmp_path / "search.json"
    source_path.write_text("{}", encoding="utf-8")

    result = publish_btst_optimized_profile_manifest(
        profile_name="momentum_optimized",
        profile_overrides={"select_threshold": 0.50},
        source_path=source_path,
        rollout_recommendation="hold",
        rollout_recommendation_details={"blockers": ["next_close_positive_rate_regressed_vs_default"]},
        replay_input_paths=[],
        manifest_path=manifest_path,
    )

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert result["status"] == "skipped"
    assert result["reason"] == "rollout_recommendation_hold"
    assert payload["profile_overrides"] == {"select_threshold": 0.46}
```

- [ ] **Step 2: Run the focused tests to verify RED**

Run: `uv run pytest tests/test_optimize_profile_script.py -k 'publish_btst_optimized_profile_manifest' -v`
Expected: FAIL because the helper does not exist yet.

- [ ] **Step 3: Add the helper implementation**

```python
def publish_btst_optimized_profile_manifest(... ) -> dict[str, Any]:
    if rollout_recommendation != "promote":
        return {
            "status": "skipped",
            "reason": "rollout_recommendation_hold",
            "manifest_path": str(Path(manifest_path).expanduser().resolve()),
        }

    payload = {
        "profile_name": profile_name,
        "profile_overrides": dict(profile_overrides),
        "source_type": "optimize_profile",
        "source_path": str(Path(source_path).expanduser().resolve()),
        "validated_by": "btst_rollout_recommendation",
        "trade_date": resolve_latest_replay_trade_date(replay_input_paths),
        "status": "ready",
    }
    resolved_manifest_path = Path(manifest_path).expanduser().resolve()
    resolved_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "published", "reason": "promoted_btst_profile", "manifest_path": str(resolved_manifest_path)}
```

- [ ] **Step 4: Run the helper tests to verify GREEN**

Run: `uv run pytest tests/test_optimize_profile_script.py -k 'publish_btst_optimized_profile_manifest' -v`
Expected: PASS

### Task 2: Wire optimize_profile main to publish canonical manifest and surface publication status

**Files:**
- Modify: `scripts/optimize_profile.py`
- Test: `tests/test_optimize_profile_script.py`

- [ ] **Step 1: Write failing integration tests for promote and hold publication**

```python
def test_main_publishes_ready_btst_manifest_when_rollout_recommendation_is_promote(...) -> None:
    ...
    assert published_manifest["status"] == "ready"
    assert payload["optimized_profile_manifest_publication"]["status"] == "published"


def test_main_skips_manifest_publish_when_rollout_recommendation_holds(...) -> None:
    ...
    assert not manifest_path.exists()
    assert payload["optimized_profile_manifest_publication"]["status"] == "skipped"
    assert payload["optimized_profile_manifest_publication"]["reason"] == "rollout_recommendation_hold"
```

- [ ] **Step 2: Run the integration tests to verify RED**

Run: `uv run pytest tests/test_optimize_profile_script.py -k 'publishes_ready_btst_manifest or skips_manifest_publish' -v`
Expected: FAIL because `optimize_profile.main()` does not publish or persist publication status yet.

- [ ] **Step 3: Add publisher wiring and payload persistence**

```python
publication = build_btst_optimized_profile_manifest_publication(...)
_persist_search_metadata(
    ...,
    optimized_profile_manifest_publication=publication,
)
```

And in `_persist_search_metadata()`:

```python
if optimized_profile_manifest_publication is not None:
    payload["optimized_profile_manifest_publication"] = optimized_profile_manifest_publication
```

Append a Markdown section such as:

```markdown
Optimized Profile Manifest Publication: **published**
- manifest_path: `.../btst_latest_optimized_profile.json`
- reason: `promoted_btst_profile`
```

- [ ] **Step 4: Run the integration tests to verify GREEN**

Run: `uv run pytest tests/test_optimize_profile_script.py -k 'publishes_ready_btst_manifest or skips_manifest_publish' -v`
Expected: PASS

### Task 3: Run the focused regression surface

**Files:**
- Modify: `tests/test_optimize_profile_script.py`
- Test: `tests/test_optimize_profile_script.py`

- [ ] **Step 1: Run the optimize-profile regression slice**

Run: `uv run pytest tests/test_optimize_profile_script.py -k 'rollout_recommendation or publish_btst_optimized_profile_manifest or publishes_ready_btst_manifest or skips_manifest_publish' -v`
Expected: PASS

- [ ] **Step 2: Run the broader optimization/paper-trading regression surface**

Run: `uv run pytest tests/test_optimize_profile_script.py tests/test_run_paper_trading_script.py tests/backtesting/test_paper_trading_runtime.py -q`
Expected: PASS
