# Momentum Threshold Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a governed `momentum_tuned`-style threshold-release candidate, validate it against the current `momentum_optimized` runtime, publish a manifest only if rollout evidence passes, and wire validated evidence into the BTST skill/docs path.

**Architecture:** Reuse the existing BTST profile registry, multi-window validation script, and optimized manifest publisher instead of inventing a parallel workflow. Add one new governed candidate profile, one new rollout-assessment layer, and one orchestration script that runs the historical backtest + multi-window validation + rollout decision as a single repeatable pipeline.

**Tech Stack:** Python 3.11/3.12, pytest, repository BTST replay/validation scripts, JSON/Markdown report artifacts, repository skill docs under `skills/ai-hedge-fund-btst/`

---

## File structure and responsibilities

- `src/targets/short_trade_target_profile_data.py`
  - Owns runtime BTST profile definitions.
  - Add the new governed release candidate here so replay/backtest scripts can resolve it by name.

- `tests/targets/test_momentum_threshold_governed_profile.py`
  - New focused unit tests for the governed profile definition and its inheritance from `momentum_optimized`.

- `scripts/btst_momentum_threshold_rollout_assessment.py`
  - New rollout gate that consumes a backtest summary plus multi-window validation summary and emits a single `promote` / `hold` decision with explicit blockers.

- `tests/test_btst_momentum_threshold_rollout_assessment.py`
  - New tests for promote/hold decisions and blocker rendering.

- `scripts/run_btst_momentum_threshold_governance.py`
  - New orchestration entrypoint that runs the candidate through 20-day backtest, multi-window validation, rollout assessment, and conditional manifest publication.

- `tests/test_run_btst_momentum_threshold_governance_script.py`
  - New orchestration tests that monkeypatch the heavy BTST scripts and verify the publish-vs-skip behavior.

- `scripts/btst_optimized_profile_manifest_helpers.py`
  - Reuse the existing publish helper; extend only if the new rollout metadata needs to be carried through the manifest payload or publish reason.

- `tests/test_optimize_profile_script.py`
  - Extend existing manifest-publisher coverage instead of creating a second manifest-helper test file.

- `docs/prompt/generate_file/momentum-threshold-governance-2026-05-21.md`
  - Write only when the rollout assessment returns `promote`; this is the user-facing Chinese validation note for the new factor/runtime improvement.

- `skills/ai-hedge-fund-btst/SKILL.md`
  - Update only after promotion so the skill explicitly reads the new rollout artifact/doc before describing the optimized path.

---

### Task 1: Add the governed runtime candidate profile

**Files:**
- Modify: `src/targets/short_trade_target_profile_data.py:269-320,1153-1163`
- Create: `tests/targets/test_momentum_threshold_governed_profile.py`
- Test: `tests/targets/test_momentum_threshold_governed_profile.py`

- [ ] **Step 1: Write the failing profile-registry test**

```python
from src.targets import get_short_trade_target_profile


def test_momentum_threshold_governed_profile_inherits_momentum_optimized_shape() -> None:
    baseline = get_short_trade_target_profile("momentum_optimized")
    candidate = get_short_trade_target_profile("momentum_tuned_governed_v1")

    assert candidate.name == "momentum_tuned_governed_v1"
    assert candidate.select_threshold == 0.38
    assert candidate.near_miss_threshold == 0.24
    assert candidate.selected_rank_cap_ratio == 0.50
    assert candidate.breakout_freshness_weight == baseline.breakout_freshness_weight
    assert candidate.trend_acceleration_weight == baseline.trend_acceleration_weight
    assert candidate.catalyst_freshness_weight == baseline.catalyst_freshness_weight
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/targets/test_momentum_threshold_governed_profile.py -v
```

Expected: FAIL with a missing profile error such as `Unknown short trade target profile: momentum_tuned_governed_v1`.

- [ ] **Step 3: Add the minimal governed profile definition**

```python
SHORT_TRADE_TARGET_PROFILES["momentum_tuned_governed_v1"] = replace(
    SHORT_TRADE_TARGET_PROFILES["momentum_optimized"],
    name="momentum_tuned_governed_v1",
    select_threshold=0.38,
    near_miss_threshold=0.24,
    selected_rank_cap_ratio=0.50,
)
```

Place it immediately after the existing `momentum_tuned` block so the historical relationship is obvious.

- [ ] **Step 4: Add the minimal regression test file**

```python
from src.targets import get_short_trade_target_profile


def test_momentum_threshold_governed_profile_inherits_momentum_optimized_shape() -> None:
    baseline = get_short_trade_target_profile("momentum_optimized")
    candidate = get_short_trade_target_profile("momentum_tuned_governed_v1")

    assert candidate.name == "momentum_tuned_governed_v1"
    assert candidate.select_threshold == 0.38
    assert candidate.near_miss_threshold == 0.24
    assert candidate.selected_rank_cap_ratio == 0.50
    assert candidate.breakout_freshness_weight == baseline.breakout_freshness_weight
    assert candidate.trend_acceleration_weight == baseline.trend_acceleration_weight
    assert candidate.catalyst_freshness_weight == baseline.catalyst_freshness_weight
```

- [ ] **Step 5: Run the test to verify it passes**

Run:

```bash
uv run pytest tests/targets/test_momentum_threshold_governed_profile.py -v
```

Expected: PASS with `1 passed`.

- [ ] **Step 6: Commit**

```bash
git add src/targets/short_trade_target_profile_data.py tests/targets/test_momentum_threshold_governed_profile.py
git commit -m "feat: add governed momentum threshold profile"
```

---

### Task 2: Add the rollout-assessment layer for the governed candidate

**Files:**
- Create: `scripts/btst_momentum_threshold_rollout_assessment.py`
- Create: `tests/test_btst_momentum_threshold_rollout_assessment.py`
- Test: `tests/test_btst_momentum_threshold_rollout_assessment.py`

- [ ] **Step 1: Write the failing rollout promote/hold tests**

```python
from scripts.btst_momentum_threshold_rollout_assessment import build_momentum_threshold_rollout_assessment


def test_momentum_threshold_rollout_promotes_when_backtest_and_windows_clear_guardrails() -> None:
    backtest_summary = {
        "profile_name": "momentum_tuned_governed_v1",
        "daily_return_mean": 0.0020,
        "win_rate": 0.48,
        "payoff_ratio": 1.39,
        "positive_days": 11,
        "trading_days": 18,
    }
    multi_window_validation = {
        "baseline_profile": "momentum_optimized",
        "variant_profile": "momentum_tuned_governed_v1",
        "keep_baseline_count": 0,
        "variant_supports_t1_count": 3,
        "mixed_count": 0,
        "recommendation": "Variant is promising across the observed windows and may be ready for a deeper rollout review.",
        "rows": [],
    }

    assessment = build_momentum_threshold_rollout_assessment(
        backtest_summary=backtest_summary,
        multi_window_validation=multi_window_validation,
    )

    assert assessment["action"] == "promote"
    assert assessment["blockers"] == []


def test_momentum_threshold_rollout_holds_when_window_validation_keeps_baseline() -> None:
    backtest_summary = {
        "profile_name": "momentum_tuned_governed_v1",
        "daily_return_mean": 0.0020,
        "win_rate": 0.48,
        "payoff_ratio": 1.39,
        "positive_days": 11,
        "trading_days": 18,
    }
    multi_window_validation = {
        "baseline_profile": "momentum_optimized",
        "variant_profile": "momentum_tuned_governed_v1",
        "keep_baseline_count": 1,
        "variant_supports_t1_count": 0,
        "mixed_count": 2,
        "recommendation": "Baseline should remain the default: the variant loses T+1 edge in at least one window without offsetting T+1 improvement elsewhere.",
        "rows": [],
    }

    assessment = build_momentum_threshold_rollout_assessment(
        backtest_summary=backtest_summary,
        multi_window_validation=multi_window_validation,
    )

    assert assessment["action"] == "hold"
    assert "window_validation_keeps_baseline" in assessment["blockers"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
uv run pytest tests/test_btst_momentum_threshold_rollout_assessment.py -v
```

Expected: FAIL with `ModuleNotFoundError` or missing symbol `build_momentum_threshold_rollout_assessment`.

- [ ] **Step 3: Write the minimal rollout assessment implementation**

```python
def build_momentum_threshold_rollout_assessment(
    *,
    backtest_summary: dict[str, object],
    multi_window_validation: dict[str, object],
) -> dict[str, object]:
    blockers: list[str] = []

    if int(multi_window_validation.get("keep_baseline_count") or 0) > 0:
        blockers.append("window_validation_keeps_baseline")
    if float(backtest_summary.get("payoff_ratio") or 0.0) < 1.39:
        blockers.append("backtest_payoff_below_round82_reference")
    if float(backtest_summary.get("win_rate") or 0.0) < 0.48:
        blockers.append("backtest_win_rate_below_round82_reference")

    action = "promote" if not blockers else "hold"
    return {
        "candidate_profile": str(backtest_summary.get("profile_name") or "momentum_tuned_governed_v1"),
        "baseline_profile": str(multi_window_validation.get("baseline_profile") or "momentum_optimized"),
        "action": action,
        "blockers": blockers,
        "backtest_summary": backtest_summary,
        "multi_window_validation": multi_window_validation,
    }
```

- [ ] **Step 4: Add a minimal CLI wrapper and Markdown renderer**

```python
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assess whether the governed momentum threshold candidate is ready for rollout.")
    parser.add_argument("--backtest-json", required=True)
    parser.add_argument("--multi-window-json", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args(argv)

    backtest_summary = json.loads(Path(args.backtest_json).read_text(encoding="utf-8"))
    multi_window_validation = json.loads(Path(args.multi_window_json).read_text(encoding="utf-8"))
    assessment = build_momentum_threshold_rollout_assessment(
        backtest_summary=backtest_summary,
        multi_window_validation=multi_window_validation,
    )

    Path(args.output_json).write_text(json.dumps(assessment, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(args.output_md).write_text(render_momentum_threshold_rollout_markdown(assessment), encoding="utf-8")
    return 0
```

- [ ] **Step 5: Run the tests to verify they pass**

Run:

```bash
uv run pytest tests/test_btst_momentum_threshold_rollout_assessment.py -v
```

Expected: PASS with `2 passed`.

- [ ] **Step 6: Commit**

```bash
git add scripts/btst_momentum_threshold_rollout_assessment.py tests/test_btst_momentum_threshold_rollout_assessment.py
git commit -m "feat: add momentum threshold rollout assessment"
```

---

### Task 3: Add a single command that runs backtest → validation → rollout → conditional manifest publish

**Files:**
- Create: `scripts/run_btst_momentum_threshold_governance.py`
- Modify: `tests/test_optimize_profile_script.py:3245-3367`
- Create: `tests/test_run_btst_momentum_threshold_governance_script.py`
- Test: `tests/test_run_btst_momentum_threshold_governance_script.py`, `tests/test_optimize_profile_script.py`

- [ ] **Step 1: Write the failing orchestration test**

```python
from pathlib import Path

from scripts.run_btst_momentum_threshold_governance import run_pipeline


def test_run_pipeline_publishes_manifest_only_when_assessment_promotes(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "scripts.run_btst_momentum_threshold_governance.run_20day_backtest",
        lambda **_: {"profile_name": "momentum_tuned_governed_v1", "win_rate": 0.48, "payoff_ratio": 1.39},
    )
    monkeypatch.setattr(
        "scripts.run_btst_momentum_threshold_governance.run_multi_window_validation",
        lambda **_: {"baseline_profile": "momentum_optimized", "variant_profile": "momentum_tuned_governed_v1", "keep_baseline_count": 0, "variant_supports_t1_count": 2, "mixed_count": 0},
    )
    monkeypatch.setattr(
        "scripts.run_btst_momentum_threshold_governance.build_momentum_threshold_rollout_assessment",
        lambda **_: {"action": "promote", "blockers": [], "candidate_profile": "momentum_tuned_governed_v1"},
    )

    published = {}

    def fake_publish(**kwargs):
        published.update(kwargs)
        return {"status": "published", "manifest_path": str(tmp_path / "btst_latest_optimized_profile.json")}

    monkeypatch.setattr("scripts.run_btst_momentum_threshold_governance.publish_btst_optimized_profile_manifest", fake_publish)

    result = run_pipeline(output_root=tmp_path)

    assert result["assessment"]["action"] == "promote"
    assert published["profile_name"] == "momentum_tuned_governed_v1"
```

- [ ] **Step 2: Run the orchestration test to verify it fails**

Run:

```bash
uv run pytest tests/test_run_btst_momentum_threshold_governance_script.py -v
```

Expected: FAIL with missing module or missing `run_pipeline`.

- [ ] **Step 3: Write the minimal orchestration implementation**

```python
def run_pipeline(*, output_root: str | Path) -> dict[str, object]:
    output_root = Path(output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    backtest_summary = run_20day_backtest(output_root=output_root)
    multi_window_validation = run_multi_window_validation(output_root=output_root)
    assessment = build_momentum_threshold_rollout_assessment(
        backtest_summary=backtest_summary,
        multi_window_validation=multi_window_validation,
    )

    manifest_result = publish_btst_optimized_profile_manifest(
        manifest_path=Path("data/reports/btst_latest_optimized_profile.json"),
        rollout_recommendation=str(assessment["action"]),
        profile_name="momentum_tuned_governed_v1",
        profile_overrides={
            "select_threshold": 0.38,
            "near_miss_threshold": 0.24,
            "selected_rank_cap_ratio": 0.50,
        },
        source_path=output_root / "btst_momentum_threshold_rollout_assessment.json",
        replay_input_paths=[],
    )
    return {
        "backtest_summary": backtest_summary,
        "multi_window_validation": multi_window_validation,
        "assessment": assessment,
        "manifest_result": manifest_result,
    }
```

- [ ] **Step 4: Extend manifest tests for the new candidate profile**

```python
def test_publish_btst_optimized_profile_manifest_accepts_governed_threshold_candidate(tmp_path: Path) -> None:
    manifest_path = tmp_path / "btst_latest_optimized_profile.json"
    source_path = tmp_path / "assessment.json"
    source_path.write_text("{}", encoding="utf-8")

    result = publish_btst_optimized_profile_manifest(
        manifest_path=manifest_path,
        rollout_recommendation="promote",
        profile_name="momentum_tuned_governed_v1",
        profile_overrides={
            "select_threshold": 0.38,
            "near_miss_threshold": 0.24,
            "selected_rank_cap_ratio": 0.50,
        },
        source_path=source_path,
        replay_input_paths=[],
    )

    assert result["status"] == "published"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["profile_name"] == "momentum_tuned_governed_v1"
```

- [ ] **Step 5: Run the focused tests to verify they pass**

Run:

```bash
uv run pytest tests/test_run_btst_momentum_threshold_governance_script.py tests/test_optimize_profile_script.py -k "momentum_threshold_governance or governed_threshold_candidate" -v
```

Expected: PASS for the new orchestration and manifest cases.

- [ ] **Step 6: Commit**

```bash
git add scripts/run_btst_momentum_threshold_governance.py tests/test_run_btst_momentum_threshold_governance_script.py tests/test_optimize_profile_script.py
git commit -m "feat: add momentum threshold governance runner"
```

---

### Task 4: Run the governed validation workflow and capture the evidence artifacts

**Files:**
- Modify: `docs/prompt/generate_file/momentum-threshold-governance-2026-05-21.md` (create only if rollout promotes)
- Modify: `skills/ai-hedge-fund-btst/SKILL.md` (only if rollout promotes)
- Test: generated artifacts under `data/reports/`

- [ ] **Step 1: Run the full governance pipeline**

Run:

```bash
uv run python scripts/run_btst_momentum_threshold_governance.py \
  --output-root data/reports/momentum_threshold_governance_20260521
```

Expected: JSON/Markdown artifacts for backtest summary, multi-window validation, rollout assessment, and a manifest publish result.

- [ ] **Step 2: Verify the rollout result before touching docs or skill wiring**

Run:

```bash
python - <<'PY'
import json
from pathlib import Path
assessment = json.loads(Path("data/reports/momentum_threshold_governance_20260521/btst_momentum_threshold_rollout_assessment.json").read_text())
print(assessment["action"])
print(assessment["blockers"])
PY
```

Expected:

- `promote` with `[]` blockers if the candidate is validated
- otherwise `hold` with explicit blocker names

- [ ] **Step 3: If the result is `promote`, write the dated Chinese validation note**

```markdown
# momentum-threshold-governance-2026-05-21

## 因子 / 运行时改动名称
- `momentum_tuned_governed_v1`

## 原理
- 在 `momentum_optimized` 的权重体系不变前提下，只释放阈值与 selected rank cap。
- 目标不是盲目扩大覆盖，而是在不破坏 drift / downside / rollout guardrail 的前提下，验证更宽阈值是否能带来更高的 BTST 胜率和赔率。

## 提升效果
- 记录 20 天回测、multi-window validation、rollout assessment 的最终数值。
- 明确对比 `momentum_optimized` 的 win rate、payoff ratio、downside、drawdown、window verdict。

## 如何验证
- 写出 `scripts/run_btst_momentum_threshold_governance.py` 的完整命令。
- 写出 assessment JSON/Markdown 的路径。

## 如何让 ai-hedge-fund-btst skill 使用
- 说明 skill 只能在 manifest 已发布且 assessment 为 `promote` 时，把这条路径描述成 active optimized profile。
```

- [ ] **Step 4: If the result is `promote`, update the BTST skill so it reads the new artifact/doc**

```markdown
- If `data/reports/momentum_threshold_governance_20260521/btst_momentum_threshold_rollout_assessment.json`
  exists and the newest assessment says `action=promote`, read it before describing the active optimized profile.
- If `docs/prompt/generate_file/momentum-threshold-governance-2026-05-21.md` exists, use it only as supporting explanation for an already-promoted runtime path.
- If the assessment says `hold`, do not describe the threshold-release candidate as active.
```

- [ ] **Step 5: Verify the promoted-doc / skill wiring**

Run:

```bash
rg -n "momentum_threshold_rollout_assessment|momentum-threshold-governance-2026-05-21|action=promote|action=hold" \
  skills/ai-hedge-fund-btst/SKILL.md \
  docs/prompt/generate_file/momentum-threshold-governance-2026-05-21.md
```

Expected:

- If rollout promoted: matches in both files
- If rollout held: no skill update and no validation note commit

- [ ] **Step 6: Commit**

If rollout promoted:

```bash
git add skills/ai-hedge-fund-btst/SKILL.md docs/prompt/generate_file/momentum-threshold-governance-2026-05-21.md data/reports/momentum_threshold_governance_20260521
git commit -m "docs: publish momentum threshold governance rollout"
```

If rollout held, do **not** force a docs/skill commit; commit only the code and tests from Tasks 1-3.

---

### Task 5: Run the focused regression suite and the existing BTST validation suite

**Files:**
- Test: `tests/targets/test_momentum_threshold_governed_profile.py`
- Test: `tests/test_btst_momentum_threshold_rollout_assessment.py`
- Test: `tests/test_run_btst_momentum_threshold_governance_script.py`
- Test: `tests/test_analyze_btst_multi_window_profile_validation_script.py`
- Test: `tests/test_optimize_profile_script.py`

- [ ] **Step 1: Run the new focused tests**

Run:

```bash
uv run pytest \
  tests/targets/test_momentum_threshold_governed_profile.py \
  tests/test_btst_momentum_threshold_rollout_assessment.py \
  tests/test_run_btst_momentum_threshold_governance_script.py \
  -v
```

Expected: PASS for all newly added tests.

- [ ] **Step 2: Run the existing multi-window validation regression**

Run:

```bash
uv run pytest tests/test_analyze_btst_multi_window_profile_validation_script.py -v
```

Expected: PASS with no regressions in the baseline validation script.

- [ ] **Step 3: Run the existing manifest / optimize-profile regression**

Run:

```bash
uv run pytest tests/test_optimize_profile_script.py -k "publish_btst_optimized_profile_manifest or resolve_btst_optimized_profile_manifest" -v
```

Expected: PASS for the manifest helper coverage, including the new governed candidate case.

- [ ] **Step 4: Run the candidate orchestration once more after the test suite**

Run:

```bash
uv run python scripts/run_btst_momentum_threshold_governance.py \
  --output-root data/reports/momentum_threshold_governance_20260521
```

Expected: reproducible artifacts and the same rollout decision as before the regression suite.

- [ ] **Step 5: Commit the final green state**

```bash
git add src/targets/short_trade_target_profile_data.py \
  scripts/btst_momentum_threshold_rollout_assessment.py \
  scripts/run_btst_momentum_threshold_governance.py \
  tests/targets/test_momentum_threshold_governed_profile.py \
  tests/test_btst_momentum_threshold_rollout_assessment.py \
  tests/test_run_btst_momentum_threshold_governance_script.py \
  tests/test_optimize_profile_script.py
git commit -m "feat: validate governed momentum threshold release"
```

---

## Self-review checklist

- Spec coverage:
  - governed candidate profile: covered by Task 1
  - multi-window / rollout validation: covered by Tasks 2-4
  - conditional manifest publication: covered by Task 3
  - docs + BTST skill integration only after validated uplift: covered by Task 4
  - regression and verification: covered by Task 5

- Placeholder scan:
  - no `TBD`, `TODO`, or “similar to Task N” shortcuts remain

- Type consistency:
  - candidate profile name is consistently `momentum_tuned_governed_v1`
  - manifest publication and rollout assessment use the same candidate name and threshold override keys
