# BTST Win-Rate-First Runtime Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make implicit `short_trade_only` BTST runs automatically adopt the ready optimized manifest plus the governed P5 win-rate-first precision gate, while preserving explicit profile/override bypasses and exposing trustworthy runtime provenance to downstream BTST reporting.

**Architecture:** Keep the adoption decision in `scripts/run_paper_trading.py`, because that file already resolves the ready manifest and prepares runtime inputs. Instead of threading a brand-new top-level runtime argument across the paper-trading stack, attach a nested governed-adoption payload onto `optimization_profile_resolution`, which already flows into `session_summary.json` and printing surfaces.

**Tech Stack:** Python 3.11+, pytest, existing BTST paper-trading CLI/runtime, Markdown skill docs

---

## File Structure

- Modify: `scripts/run_paper_trading.py`
  - resolve the governed precision adoption decision
  - auto-set `BTST_0422_P5_WIN_RATE_FIRST_PRECISION_MODE` only for the implicit governed BTST path
  - enrich `optimization_profile_resolution` with governed-adoption provenance
  - print the governed-adoption state in the run summary
- Modify: `tests/test_run_paper_trading_script.py`
  - cover auto-enable, bypass, fallback, and summary/provenance behavior
- Reuse: `tests/test_task1_win_rate_first_precision.py`
  - no functional rewrite planned; rerun to ensure the existing P5 contract still behaves correctly
- Modify: `skills/ai-hedge-fund-btst/SKILL.md`
  - document that the default BTST multi-agent path may auto-apply the governed precision gate when artifacts confirm it
- Create: `docs/prompt/generate_file/btst-win-rate-first-governed-runtime-adoption-2026-05-18.md`
  - explain principle, uplift target, validation method, trade-offs, and usage in Chinese after replay evidence is collected

### Task 1: Resolve governed BTST precision adoption in `run_paper_trading.py`

**Files:**
- Modify: `scripts/run_paper_trading.py`
- Test: `tests/test_run_paper_trading_script.py`

- [ ] **Step 1: Write the failing tests for governed auto-enable and explicit bypass**

```python
def test_resolve_runtime_inputs_auto_enables_governed_precision_for_implicit_ready_btst_run(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("BTST_0422_P5_WIN_RATE_FIRST_PRECISION_MODE", raising=False)
    monkeypatch.setattr(
        run_paper_trading_script,
        "_derive_shadow_focus_tickers_from_reports",
        lambda _reports_root: {
            "all": [],
            "layer_a_liquidity_corridor": [],
            "post_gate_liquidity_competition": [],
            "release_priority_layer_a_liquidity_corridor": [],
            "release_priority_post_gate_liquidity_competition": [],
            "visibility_gap_all": [],
            "visibility_gap_layer_a_liquidity_corridor": [],
            "visibility_gap_post_gate_liquity_competition": [],
        },
    )
    monkeypatch.setattr(
        run_paper_trading_script,
        "resolve_btst_optimized_profile_manifest",
        lambda _path: {
            "mode": "optimized",
            "status": "ready",
            "profile_name": "momentum_optimized",
            "profile_overrides": {"select_threshold": 0.5},
            "manifest_path": str(tmp_path / "btst_latest_optimized_profile.json"),
        },
    )
    args = SimpleNamespace(
        start_date="2026-05-12",
        end_date="2026-05-12",
        tickers="",
        analysts=None,
        analysts_all=False,
        fast_analysts=None,
        short_trade_target_profile=None,
        short_trade_target_overrides=None,
        selection_target="short_trade_only",
        optimized_profile_manifest=str(tmp_path / "btst_latest_optimized_profile.json"),
        output_dir=str(tmp_path / "paper"),
    )

    runtime_inputs = run_paper_trading_script._resolve_paper_trading_runtime_inputs(args)

    adoption = runtime_inputs["optimization_profile_resolution"]["governed_precision_runtime_adoption"]
    assert adoption["auto_enabled"] is True
    assert adoption["reason"] == "implicit_short_trade_only_ready_manifest"
    assert os.environ["BTST_0422_P5_WIN_RATE_FIRST_PRECISION_MODE"] == "true"


def test_resolve_runtime_inputs_does_not_auto_enable_governed_precision_when_profile_is_explicit(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("BTST_0422_P5_WIN_RATE_FIRST_PRECISION_MODE", raising=False)
    monkeypatch.setattr(
        run_paper_trading_script,
        "_derive_shadow_focus_tickers_from_reports",
        lambda _reports_root: {
            "all": [],
            "layer_a_liquidity_corridor": [],
            "post_gate_liquidity_competition": [],
            "release_priority_layer_a_liquidity_corridor": [],
            "release_priority_post_gate_liquidity_competition": [],
            "visibility_gap_all": [],
            "visibility_gap_layer_a_liquidity_corridor": [],
            "visibility_gap_post_gate_liquidity_competition": [],
        },
    )
    args = SimpleNamespace(
        start_date="2026-05-12",
        end_date="2026-05-12",
        tickers="",
        analysts=None,
        analysts_all=False,
        fast_analysts=None,
        short_trade_target_profile="trend_corrected_v1",
        short_trade_target_overrides=None,
        selection_target="short_trade_only",
        optimized_profile_manifest=str(tmp_path / "btst_latest_optimized_profile.json"),
        output_dir=str(tmp_path / "paper"),
    )

    runtime_inputs = run_paper_trading_script._resolve_paper_trading_runtime_inputs(args)

    assert runtime_inputs["optimization_profile_resolution"] == {}
    assert "BTST_0422_P5_WIN_RATE_FIRST_PRECISION_MODE" not in os.environ
```

- [ ] **Step 2: Run the targeted tests to verify they fail first**

Run:

```bash
uv run pytest tests/test_run_paper_trading_script.py -q -k "governed_precision"
```

Expected: FAIL because the governed adoption payload and auto-enable behavior do not exist yet.

- [ ] **Step 3: Add a helper that resolves the governed adoption decision and mutates the manifest resolution payload**

```python
BTST_P5_PRECISION_ENV = "BTST_0422_P5_WIN_RATE_FIRST_PRECISION_MODE"


def _resolve_governed_btst_precision_runtime_adoption(
    *,
    selection_target: str,
    has_explicit_short_trade_target_inputs: bool,
    optimization_profile_resolution: dict[str, Any],
) -> dict[str, Any]:
    if selection_target != "short_trade_only":
        return {"auto_enabled": False, "reason": "selection_target_not_short_trade_only"}
    if has_explicit_short_trade_target_inputs:
        return {"auto_enabled": False, "reason": "explicit_short_trade_inputs"}
    if str(optimization_profile_resolution.get("mode") or "") != "optimized":
        return {"auto_enabled": False, "reason": "manifest_not_optimized"}
    if str(optimization_profile_resolution.get("status") or "") != "ready":
        return {"auto_enabled": False, "reason": "manifest_not_ready"}
    return {
        "auto_enabled": True,
        "reason": "implicit_short_trade_only_ready_manifest",
        "env_name": BTST_P5_PRECISION_ENV,
        "resolved_value": "true",
    }
```

- [ ] **Step 4: Apply the helper inside `_resolve_paper_trading_runtime_inputs()` and preserve explicit operator env when auto-enable is false**

```python
adoption = _resolve_governed_btst_precision_runtime_adoption(
    selection_target=str(getattr(args, "selection_target", "") or ""),
    has_explicit_short_trade_target_inputs=has_explicit_short_trade_target_inputs,
    optimization_profile_resolution=optimization_profile_resolution,
)
if optimization_profile_resolution:
    optimization_profile_resolution = dict(optimization_profile_resolution)
    optimization_profile_resolution["governed_precision_runtime_adoption"] = adoption
if adoption.get("auto_enabled"):
    os.environ[BTST_P5_PRECISION_ENV] = "true"
```

- [ ] **Step 5: Re-run the targeted tests and confirm they pass**

Run:

```bash
uv run pytest tests/test_run_paper_trading_script.py -q -k "governed_precision"
```

Expected: PASS.

- [ ] **Step 6: Commit the runtime adoption decision slice**

```bash
git add scripts/run_paper_trading.py tests/test_run_paper_trading_script.py
git commit -m "feat: auto-enable governed BTST precision for ready manifests"
```

### Task 2: Expose governed adoption provenance in CLI and session outputs

**Files:**
- Modify: `scripts/run_paper_trading.py`
- Test: `tests/test_run_paper_trading_script.py`

- [ ] **Step 1: Write the failing summary/provenance test**

```python
def test_print_paper_trading_run_summary_includes_governed_precision_adoption(capsys, tmp_path: Path) -> None:
    run_paper_trading_script._print_paper_trading_run_summary(
        args=SimpleNamespace(
            start_date="2026-05-12",
            end_date="2026-05-12",
            selection_target="short_trade_only",
            cache_benchmark=False,
            frozen_plan_source=None,
        ),
        artifacts=SimpleNamespace(
            output_dir=tmp_path / "paper",
            daily_events_path=tmp_path / "paper" / "daily_events.jsonl",
            timing_log_path=tmp_path / "paper" / "pipeline_timings.jsonl",
            summary_path=tmp_path / "paper" / "session_summary.json",
        ),
        resolved_model_name="MiniMax-M2.7",
        resolved_model_provider="MiniMax",
        selected_analysts=None,
        fast_selected_analysts=None,
        short_trade_target_profile="momentum_optimized",
        short_trade_target_overrides={"select_threshold": 0.5},
        optimization_profile_resolution={
            "mode": "optimized",
            "manifest_path": str(tmp_path / "btst_latest_optimized_profile.json"),
            "governed_precision_runtime_adoption": {
                "auto_enabled": True,
                "reason": "implicit_short_trade_only_ready_manifest",
                "env_name": "BTST_0422_P5_WIN_RATE_FIRST_PRECISION_MODE",
                "resolved_value": "true",
            },
        },
        auto_shadow_focus={"all": [], "layer_a_liquidity_corridor": [], "post_gate_liquidity_competition": [], "release_priority_layer_a_liquidity_corridor": [], "release_priority_post_gate_liquidity_competition": [], "visibility_gap_all": [], "visibility_gap_layer_a_liquidity_corridor": [], "visibility_gap_post_gate_liquidity_competition": []},
        shadow_focus_env={},
    )

    output = capsys.readouterr().out
    assert "paper_trading_governed_precision_auto_enabled=true" in output
    assert "paper_trading_governed_precision_reason=implicit_short_trade_only_ready_manifest" in output
```

- [ ] **Step 2: Run the targeted summary test to see it fail**

Run:

```bash
uv run pytest tests/test_run_paper_trading_script.py::test_print_paper_trading_run_summary_includes_governed_precision_adoption -q
```

Expected: FAIL because the summary printer does not emit governed precision fields yet.

- [ ] **Step 3: Extend `_print_paper_trading_run_summary()` to print the governed precision payload from `optimization_profile_resolution`**

```python
governed_precision = dict(optimization_profile_resolution.get("governed_precision_runtime_adoption") or {})
if governed_precision:
    print(f"paper_trading_governed_precision_auto_enabled={str(bool(governed_precision.get('auto_enabled'))).lower()}")
    if governed_precision.get("reason"):
        print(f"paper_trading_governed_precision_reason={governed_precision['reason']}")
    if governed_precision.get("env_name"):
        print(f"paper_trading_governed_precision_env={governed_precision['env_name']}")
    if governed_precision.get("resolved_value"):
        print(f"paper_trading_governed_precision_value={governed_precision['resolved_value']}")
```

- [ ] **Step 4: Re-run the summary test and the existing manifest resolution tests**

Run:

```bash
uv run pytest \
  tests/test_run_paper_trading_script.py::test_print_paper_trading_run_summary_includes_governed_precision_adoption \
  tests/test_run_paper_trading_script.py::test_run_paper_trading_resolves_optimized_manifest_before_pipeline \
  tests/test_run_paper_trading_script.py::test_resolve_runtime_inputs_scopes_optimized_manifest_resolution_to_short_trade_only \
  -q
```

Expected: PASS.

- [ ] **Step 5: Commit the provenance-printing slice**

```bash
git add scripts/run_paper_trading.py tests/test_run_paper_trading_script.py
git commit -m "feat: expose governed BTST precision provenance"
```

### Task 3: Verify the execution contract is still correct under the adopted path

**Files:**
- Reuse: `tests/test_task1_win_rate_first_precision.py`
- Reuse: `tests/test_run_paper_trading_script.py`

- [ ] **Step 1: Run the focused P5 precision contract tests**

Run:

```bash
uv run pytest tests/test_task1_win_rate_first_precision.py -q
```

Expected: PASS, proving the auto-enable change did not alter the existing downgrade semantics.

- [ ] **Step 2: Run the focused manifest/runtime regression set**

Run:

```bash
uv run pytest \
  tests/test_run_paper_trading_script.py \
  tests/test_task1_win_rate_first_precision.py \
  -q
```

Expected: PASS.

- [ ] **Step 3: Run paired BTST replays for evidence collection**

Run baseline:

```bash
BTST_0422_P5_EXECUTION_CONTRACT_MODE=enforce \
BTST_0422_P5_WIN_RATE_FIRST_PRECISION_MODE=false \
uv run python scripts/run_paper_trading.py \
  --start-date 2026-05-12 \
  --end-date 2026-05-12 \
  --selection-target short_trade_only \
  --optimized-profile-manifest data/reports/btst_latest_optimized_profile.json \
  --output-dir data/reports/paper_trading_2026-05-12_2026-05-12_btst_runtime_baseline
```

Run governed candidate:

```bash
BTST_0422_P5_EXECUTION_CONTRACT_MODE=enforce \
uv run python scripts/run_paper_trading.py \
  --start-date 2026-05-12 \
  --end-date 2026-05-12 \
  --selection-target short_trade_only \
  --optimized-profile-manifest data/reports/btst_latest_optimized_profile.json \
  --output-dir data/reports/paper_trading_2026-05-12_2026-05-12_btst_runtime_governed
```

Expected:

1. both runs resolve the ready manifest,
2. only the governed run reports `paper_trading_governed_precision_auto_enabled=true`,
3. the governed run shows tighter execution-eligible / selected behavior in `session_summary.json`.

- [ ] **Step 4: Inspect the summary deltas before claiming uplift**

Run:

```bash
python - <<'PY'
import json
from pathlib import Path

baseline = json.loads(Path("data/reports/paper_trading_2026-05-12_2026-05-12_btst_runtime_baseline/session_summary.json").read_text())
governed = json.loads(Path("data/reports/paper_trading_2026-05-12_2026-05-12_btst_runtime_governed/session_summary.json").read_text())

print("baseline adoption:", baseline.get("optimization_profile_resolution", {}).get("governed_precision_runtime_adoption"))
print("governed adoption:", governed.get("optimization_profile_resolution", {}).get("governed_precision_runtime_adoption"))
print("baseline p5:", baseline.get("dual_target_summary", {}).get("execution_plan_provenance_summary", {}))
print("governed p5:", governed.get("dual_target_summary", {}).get("execution_plan_provenance_summary", {}))
PY
```

Expected: clear provenance difference plus a cleaner governed tradeable surface.

- [ ] **Step 5: Commit after validation evidence is captured**

```bash
git add scripts/run_paper_trading.py tests/test_run_paper_trading_script.py
git commit -m "test: validate governed BTST precision runtime adoption"
```

### Task 4: Update the BTST skill contract and record the validated Chinese note

**Files:**
- Modify: `skills/ai-hedge-fund-btst/SKILL.md`
- Create: `docs/prompt/generate_file/btst-win-rate-first-governed-runtime-adoption-2026-05-18.md`

- [ ] **Step 1: Write the skill-doc change**

```md
- Default this workflow to the latest approved optimized profile manifest when it is ready.
- For implicit `short_trade_only` BTST runs that resolve a ready optimized manifest without explicit short-trade profile inputs, the runtime may also auto-enable the governed P5 win-rate-first precision gate.
- Final documents must describe that governed precision path only when `session_summary.json` or downstream artifacts confirm it.
```

- [ ] **Step 2: Write the dated Chinese validation note**

```md
# btst-win-rate-first-governed-runtime-adoption-2026-05-18

## 原理
- 这次改动不是发布新的 BTST profile，而是把“已批准 optimized manifest + 已验证 P5 precision”合并成默认的 win-rate-first 运行面。

## 提升效果
- 目标是收紧 formal `selected` / `execution_eligible`，优先保护 T+1 胜率与赔率，而不是扩大覆盖率。

## 如何验证
- 对比 baseline 与 governed 两组同窗 paper-trading `session_summary.json`。

## 观察到的权衡
- 覆盖率可能下降，但 tradeable surface 应更干净。

## 如何使用
- 默认 `short_trade_only` + ready manifest 路径自动生效；显式 profile / override 仍为人为绕过路径。
```

- [ ] **Step 3: Run a final focused regression plus doc sanity check**

Run:

```bash
uv run pytest \
  tests/test_run_paper_trading_script.py \
  tests/test_task1_win_rate_first_precision.py \
  -q
```

Expected: PASS.

Check docs:

```bash
git --no-pager diff -- skills/ai-hedge-fund-btst/SKILL.md docs/prompt/generate_file/btst-win-rate-first-governed-runtime-adoption-2026-05-18.md | cat
```

Expected: the skill wording matches the runtime provenance rule and the dated note stays artifact-grounded.

- [ ] **Step 4: Commit the contract/doc slice**

```bash
git add skills/ai-hedge-fund-btst/SKILL.md docs/prompt/generate_file/btst-win-rate-first-governed-runtime-adoption-2026-05-18.md
git commit -m "docs: record governed BTST precision runtime adoption"
```

## Self-Review

1. **Spec coverage:** Task 1 covers governed adoption decision + bypass rules; Task 2 covers provenance surfacing; Task 3 covers replay validation; Task 4 covers skill/doc updates. No spec section is left without a task.
2. **Placeholder scan:** The plan contains exact files, exact commands, and concrete code snippets for each change. The replay window is pinned to a concrete BTST date used in existing artifacts.
3. **Type consistency:** The plan consistently uses `governed_precision_runtime_adoption` as a nested dictionary inside `optimization_profile_resolution`, and uses the helper name `_resolve_governed_btst_precision_runtime_adoption()` throughout.
