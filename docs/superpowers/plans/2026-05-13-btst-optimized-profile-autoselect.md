# BTST Optimized-Profile Auto-Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the BTST document workflow default to the latest approved optimized short-trade profile instead of blindly running `default`, while preserving an explicit fallback path and provenance.

**Architecture:** Introduce a single optimized-profile resolution module that reads a canonical manifest artifact and returns either an optimized profile selection or an explicit default fallback. Thread that resolution into `scripts/run_paper_trading.py`, persist it into `session_summary.json`, then update the local `ai-hedge-fund-btst` skill instructions so the document workflow relies on this resolver-driven path and writes the chosen profile provenance into final docs.

**Tech Stack:** Python 3.12, pytest, existing BTST paper-trading runtime/session summary code, local Copilot skill files under `~/.copilot/skills/ai-hedge-fund-btst`

---

## File Structure

- Create: `src/paper_trading/optimized_profile_resolution.py`
  - Own the canonical manifest parsing, validation, and fallback result payload.
- Modify: `scripts/run_paper_trading.py`
  - Add a manifest-path option and resolve the effective short-trade profile before pipeline construction.
- Modify: `src/paper_trading/runtime.py`
  - Thread optimization resolution into runtime summary creation.
- Modify: `src/paper_trading/runtime_session_helpers.py`
  - Persist optimization provenance into `session_summary.json`.
- Modify: `tests/test_run_paper_trading_script.py`
  - Lock CLI-side manifest resolution and fallback behavior.
- Modify: `tests/backtesting/test_paper_trading_runtime.py`
  - Lock `session_summary` provenance output.
- Modify: `/Users/matrix/.copilot/skills/ai-hedge-fund-btst/SKILL.md`
  - Update workflow text so the skill uses the optimized-profile manifest driven path by default.
- Modify: `/Users/matrix/.copilot/skills/ai-hedge-fund-btst/references/artifact-reading.md`
  - Add provenance-reading guidance.
- Modify: `/Users/matrix/.copilot/skills/ai-hedge-fund-btst/references/final-doc-spec.md`
  - Require the optimized/default-fallback profile provenance in the LLM-side outputs.

## Task 1: Add the canonical optimized-profile resolver

**Files:**
- Create: `src/paper_trading/optimized_profile_resolution.py`
- Modify: `tests/test_run_paper_trading_script.py`

- [ ] **Step 1: Write the failing resolver success test**

```python
def test_resolve_btst_optimized_profile_manifest_returns_ready_profile(tmp_path: Path) -> None:
    manifest_path = tmp_path / "btst_latest_optimized_profile.json"
    manifest_path.write_text(
        json.dumps(
            {
                "profile_name": "momentum_optimized",
                "profile_overrides": {"select_threshold": 0.48, "near_miss_threshold": 0.34},
                "source_type": "optimize_profile",
                "source_path": str(tmp_path / "param_search_latest.json"),
                "validated_by": "walk_forward_and_rollout",
                "trade_date": "2026-05-12",
                "status": "ready",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "param_search_latest.json").write_text("{}", encoding="utf-8")

    result = resolve_btst_optimized_profile_manifest(manifest_path)

    assert result["mode"] == "optimized"
    assert result["profile_name"] == "momentum_optimized"
    assert result["profile_overrides"] == {"select_threshold": 0.48, "near_miss_threshold": 0.34}
    assert result["fallback_reason"] is None
```

- [ ] **Step 2: Run the success test to verify RED**

Run: `uv run pytest tests/test_run_paper_trading_script.py::test_resolve_btst_optimized_profile_manifest_returns_ready_profile -q`
Expected: FAIL with `ImportError` or `NameError` because the resolver does not exist yet.

- [ ] **Step 3: Write the failing fallback test**

```python
def test_resolve_btst_optimized_profile_manifest_returns_default_fallback_when_manifest_missing(tmp_path: Path) -> None:
    result = resolve_btst_optimized_profile_manifest(tmp_path / "missing.json")

    assert result["mode"] == "default_fallback"
    assert result["profile_name"] == "default"
    assert result["profile_overrides"] == {}
    assert result["fallback_reason"] == "optimized_profile_manifest_missing"
```

- [ ] **Step 4: Run the fallback test to verify RED**

Run: `uv run pytest tests/test_run_paper_trading_script.py::test_resolve_btst_optimized_profile_manifest_returns_default_fallback_when_manifest_missing -q`
Expected: FAIL because the resolver does not exist yet.

- [ ] **Step 5: Implement the resolver module**

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypedDict


class OptimizedProfileResolution(TypedDict):
    mode: str
    profile_name: str
    profile_overrides: dict[str, object]
    source_type: str | None
    source_path: str | None
    validated_by: str | None
    trade_date: str | None
    status: str
    fallback_reason: str | None
    manifest_path: str


def resolve_btst_optimized_profile_manifest(manifest_path: str | Path) -> OptimizedProfileResolution:
    resolved_path = Path(manifest_path).expanduser().resolve()
    if not resolved_path.exists():
        return {
            "mode": "default_fallback",
            "profile_name": "default",
            "profile_overrides": {},
            "source_type": None,
            "source_path": None,
            "validated_by": None,
            "trade_date": None,
            "status": "missing",
            "fallback_reason": "optimized_profile_manifest_missing",
            "manifest_path": str(resolved_path),
        }

    payload = json.loads(resolved_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("optimized profile manifest must be a JSON object")

    profile_name = str(payload.get("profile_name") or "").strip()
    profile_overrides = payload.get("profile_overrides") or {}
    status = str(payload.get("status") or "").strip()
    source_path = str(payload.get("source_path") or "").strip() or None

    if not profile_name or status != "ready" or not isinstance(profile_overrides, dict):
        return {
            "mode": "default_fallback",
            "profile_name": "default",
            "profile_overrides": {},
            "source_type": str(payload.get("source_type") or "").strip() or None,
            "source_path": source_path,
            "validated_by": str(payload.get("validated_by") or "").strip() or None,
            "trade_date": str(payload.get("trade_date") or "").strip() or None,
            "status": status or "invalid",
            "fallback_reason": "optimized_profile_manifest_invalid",
            "manifest_path": str(resolved_path),
        }

    if source_path is not None and not Path(source_path).expanduser().exists():
        return {
            "mode": "default_fallback",
            "profile_name": "default",
            "profile_overrides": {},
            "source_type": str(payload.get("source_type") or "").strip() or None,
            "source_path": source_path,
            "validated_by": str(payload.get("validated_by") or "").strip() or None,
            "trade_date": str(payload.get("trade_date") or "").strip() or None,
            "status": status,
            "fallback_reason": "optimized_profile_source_missing",
            "manifest_path": str(resolved_path),
        }

    return {
        "mode": "optimized",
        "profile_name": profile_name,
        "profile_overrides": dict(profile_overrides),
        "source_type": str(payload.get("source_type") or "").strip() or None,
        "source_path": source_path,
        "validated_by": str(payload.get("validated_by") or "").strip() or None,
        "trade_date": str(payload.get("trade_date") or "").strip() or None,
        "status": status,
        "fallback_reason": None,
        "manifest_path": str(resolved_path),
    }
```

- [ ] **Step 6: Run the two resolver tests to verify GREEN**

Run: `uv run pytest tests/test_run_paper_trading_script.py::test_resolve_btst_optimized_profile_manifest_returns_ready_profile tests/test_run_paper_trading_script.py::test_resolve_btst_optimized_profile_manifest_returns_default_fallback_when_manifest_missing -q`
Expected: `2 passed`

- [ ] **Step 7: Commit the resolver task**

```bash
git add src/paper_trading/optimized_profile_resolution.py tests/test_run_paper_trading_script.py
git commit -m "feat: add BTST optimized profile resolver"
```

## Task 2: Thread optimized-profile provenance through `run_paper_trading`

**Files:**
- Modify: `scripts/run_paper_trading.py`
- Modify: `src/paper_trading/runtime.py`
- Modify: `src/paper_trading/runtime_session_helpers.py`
- Modify: `tests/test_run_paper_trading_script.py`
- Modify: `tests/backtesting/test_paper_trading_runtime.py`

- [ ] **Step 1: Write the failing CLI resolution test**

```python
def test_run_paper_trading_resolves_optimized_manifest_before_pipeline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manifest_path = tmp_path / "btst_latest_optimized_profile.json"
    manifest_path.write_text(
        json.dumps(
            {
                "profile_name": "momentum_optimized",
                "profile_overrides": {"select_threshold": 0.48},
                "source_type": "optimize_profile",
                "source_path": str(tmp_path / "source.json"),
                "validated_by": "walk_forward_and_rollout",
                "trade_date": "2026-05-12",
                "status": "ready",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "source.json").write_text("{}", encoding="utf-8")

    captured: dict[str, object] = {}

    def fake_run_session(**kwargs: object) -> tuple[dict[str, object], Path]:
        captured.update(kwargs)
        return {}, tmp_path

    monkeypatch.setattr(run_paper_trading_module, "_run_paper_trading_session", fake_run_session)

    run_paper_trading_module.main(
        [
            "--start-date",
            "2026-05-12",
            "--end-date",
            "2026-05-12",
            "--selection-target",
            "short_trade_only",
            "--optimized-profile-manifest",
            str(manifest_path),
        ]
    )

    assert captured["short_trade_target_profile_name"] == "momentum_optimized"
    assert captured["short_trade_target_profile_overrides"] == {"select_threshold": 0.48}
```

- [ ] **Step 2: Run the CLI test to verify RED**

Run: `uv run pytest tests/test_run_paper_trading_script.py::test_run_paper_trading_resolves_optimized_manifest_before_pipeline -q`
Expected: FAIL because the CLI does not resolve optimized manifests yet.

- [ ] **Step 3: Write the failing session summary provenance test**

```python
def test_build_session_summary_includes_optimization_profile_resolution() -> None:
    summary = build_session_summary(
        start_date="2026-05-12",
        end_date="2026-05-12",
        tickers=[],
        initial_capital=100000.0,
        resolved_model_name="MiniMax-M2.7",
        resolved_model_provider="MiniMax",
        selected_analysts=None,
        fast_selected_analysts=None,
        short_trade_target_profile_name="momentum_optimized",
        short_trade_target_profile_overrides={"select_threshold": 0.48},
        frozen_plan_source_path=None,
        selection_target="short_trade_only",
        metrics={},
        portfolio_values=[],
        final_portfolio_snapshot={},
        llm_route_provenance={},
        execution_plan_provenance={},
        dual_target_summary={},
        reporting_target_summary={},
        llm_observability_summary={},
        llm_error_digest={},
        data_cache_summary={},
        cache_benchmark_summary=None,
        cache_benchmark_status={},
        research_feedback_summary={},
        recorder_day_count=1,
        recorder_executed_trade_days=0,
        recorder_total_executed_orders=0,
        daily_events_path=Path("daily_events.jsonl"),
        timing_log_path=Path("pipeline_timings.jsonl"),
        summary_path=Path("session_summary.json"),
        selection_artifact_root=Path("selection_artifacts"),
        feedback_summary_path=Path("research_feedback_summary.json"),
        cache_benchmark_artifacts={},
        llm_metrics_artifacts={},
        optimization_profile_resolution={
            "mode": "optimized",
            "profile_name": "momentum_optimized",
            "profile_overrides": {"select_threshold": 0.48},
            "source_type": "optimize_profile",
            "source_path": "data/reports/param_search_latest.json",
            "validated_by": "walk_forward_and_rollout",
            "trade_date": "2026-05-12",
            "status": "ready",
            "fallback_reason": None,
            "manifest_path": "data/reports/btst_latest_optimized_profile.json",
        },
    )

    assert summary["optimization_profile_resolution"]["mode"] == "optimized"
    assert summary["optimization_profile_resolution"]["profile_name"] == "momentum_optimized"
```

- [ ] **Step 4: Run the provenance test to verify RED**

Run: `uv run pytest tests/backtesting/test_paper_trading_runtime.py::test_build_session_summary_includes_optimization_profile_resolution -q`
Expected: FAIL because `build_session_summary()` does not expose the optimization resolution payload yet.

- [ ] **Step 5: Add the manifest CLI option and resolve the effective profile**

```python
parser.add_argument(
    "--optimized-profile-manifest",
    default="data/reports/btst_latest_optimized_profile.json",
    help="Canonical manifest describing the latest approved BTST optimized profile",
)
```

```python
resolution = resolve_btst_optimized_profile_manifest(args.optimized_profile_manifest)
explicit_profile = str(args.short_trade_target_profile or "").strip()
explicit_overrides = _resolve_short_trade_target_overrides(args.short_trade_target_overrides)

effective_profile_name = explicit_profile or resolution["profile_name"]
effective_profile_overrides = explicit_overrides if explicit_overrides is not None else resolution["profile_overrides"]
```

- [ ] **Step 6: Thread optimization resolution into runtime summary inputs**

```python
summary = build_session_summary(
    **_build_runtime_session_summary_inputs(
        context=context,
        metrics=metrics,
        start_date=start_date,
        end_date=end_date,
        tickers=tickers,
        initial_capital=initial_capital,
        selected_analysts=selected_analysts,
        fast_selected_analysts=fast_selected_analysts,
        short_trade_target_profile_name=short_trade_target_profile_name,
        short_trade_target_profile_overrides=short_trade_target_profile_overrides,
        selection_target=selection_target,
        research_feedback_summary=research_feedback_summary,
        feedback_summary_path=feedback_summary_path,
        monitoring_summary=monitoring_summary,
        data_cache_summary=data_cache_summary,
        cache_benchmark_summary=cache_benchmark_summary,
        cache_benchmark_artifacts=cache_benchmark_artifacts,
        cache_benchmark_status=cache_benchmark_status,
        optimization_profile_resolution=optimization_profile_resolution,
    )
)
```

```python
summary["optimization_profile_resolution"] = dict(optimization_profile_resolution or {})
```

- [ ] **Step 7: Run the focused tests to verify GREEN**

Run: `uv run pytest tests/test_run_paper_trading_script.py::test_run_paper_trading_resolves_optimized_manifest_before_pipeline tests/backtesting/test_paper_trading_runtime.py::test_build_session_summary_includes_optimization_profile_resolution -q`
Expected: `2 passed`

- [ ] **Step 8: Commit the runtime/provenance task**

```bash
git add scripts/run_paper_trading.py src/paper_trading/runtime.py src/paper_trading/runtime_session_helpers.py tests/test_run_paper_trading_script.py tests/backtesting/test_paper_trading_runtime.py
git commit -m "feat: wire BTST optimized profile resolution into paper trading"
```

## Task 3: Update the BTST skill and final-doc rules to consume optimized provenance

**Files:**
- Modify: `/Users/matrix/.copilot/skills/ai-hedge-fund-btst/SKILL.md`
- Modify: `/Users/matrix/.copilot/skills/ai-hedge-fund-btst/references/artifact-reading.md`
- Modify: `/Users/matrix/.copilot/skills/ai-hedge-fund-btst/references/final-doc-spec.md`
- Modify: `tests/test_run_paper_trading_script.py`

- [ ] **Step 1: Write the failing document-provenance test**

```python
def test_btst_session_summary_records_default_fallback_reason_when_manifest_missing(tmp_path: Path) -> None:
    resolution = resolve_btst_optimized_profile_manifest(tmp_path / "missing.json")

    assert resolution["mode"] == "default_fallback"
    assert resolution["fallback_reason"] == "optimized_profile_manifest_missing"
```

- [ ] **Step 2: Run the provenance fallback test to verify GREEN boundary**

Run: `uv run pytest tests/test_run_paper_trading_script.py::test_btst_session_summary_records_default_fallback_reason_when_manifest_missing -q`
Expected: PASS after Tasks 1-2, proving the fallback payload is stable enough for the skill to read.

- [ ] **Step 3: Update the skill workflow to rely on the resolver-driven runtime**

```markdown
3. Run the multi-agent BTST pipeline.
  - Use short_trade_only for this skill.
  - Default to the canonical optimized-profile manifest at `data/reports/btst_latest_optimized_profile.json`.
  - If the manifest resolves to an optimized profile, the run must use it.
  - If the manifest falls back to default, the final documents must say so explicitly.
```

```bash
.venv/bin/python scripts/run_paper_trading.py \
  --start-date YYYY-MM-DD \
  --end-date YYYY-MM-DD \
  --selection-target short_trade_only \
  --optimized-profile-manifest data/reports/btst_latest_optimized_profile.json \
  --model-provider MiniMax \
  --model-name MiniMax-M2.7 \
  --output-dir data/reports/paper_trading_YYYYMMDD_YYYYMMDD_live_m2_7_short_trade_only_YYYYMMDD_plan
```

- [ ] **Step 4: Update artifact-reading and final-doc rules**

```markdown
- Read `session_summary.json["optimization_profile_resolution"]` before drafting the LLM-side outputs.
- If `mode == "optimized"`, state the selected profile and override provenance.
- If `mode == "default_fallback"`, state that the run fell back to default and include `fallback_reason`.
```

- [ ] **Step 5: Run the regression surface**

Run: `uv run pytest tests/test_run_paper_trading_script.py tests/backtesting/test_paper_trading_runtime.py -q`
Expected: PASS

- [ ] **Step 6: Manual smoke-check the updated skill files**

Run:

```bash
rg -n "optimized-profile-manifest|optimization_profile_resolution|default_fallback" \
  /Users/matrix/.copilot/skills/ai-hedge-fund-btst/SKILL.md \
  /Users/matrix/.copilot/skills/ai-hedge-fund-btst/references/artifact-reading.md \
  /Users/matrix/.copilot/skills/ai-hedge-fund-btst/references/final-doc-spec.md
```

Expected: each file contains the new optimized/default-fallback provenance rules.

- [ ] **Step 7: Commit the repo-side regression anchor**

```bash
git add tests/test_run_paper_trading_script.py tests/backtesting/test_paper_trading_runtime.py
git commit -m "test: cover BTST optimized profile provenance"
```

## Self-Review Notes

- Spec coverage:
  - canonical optimized artifact: Task 1
  - resolver-driven runtime selection: Task 2
  - session summary provenance: Task 2
  - final-doc provenance and explicit fallback: Task 3
- Placeholder scan:
  - no placeholder markers remain
  - all tasks point at exact file paths and commands
- Type consistency:
  - use `optimization_profile_resolution` consistently in resolver output, runtime threading, and session summary payload
