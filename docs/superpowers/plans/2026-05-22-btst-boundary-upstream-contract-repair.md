# BTST Boundary Upstream Contract Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the upstream short-trade boundary contract so the core explainability keys needed by boundary inspection and round1 research are emitted consistently before rows fall into the `boundary_without_explainability` cohort.

**Architecture:** Add a small target-side helper that defines the canonical boundary-contract core payload and merge semantics, then wire it into both the short-trade target emitter and the daily pipeline boundary contract normalizer. Verify the repair by reusing the existing inspection, quarantine, and round1 scripts rather than inventing new analysis surfaces.

**Tech Stack:** Python 3.12, Pydantic models, existing BTST target/pipeline helpers, pytest, CLI analysis scripts.

---

## File structure

- Create: `src/targets/short_trade_boundary_contract_helpers.py`
  - canonical list of boundary-contract core keys
  - source-payload builder with precedence rules
  - explainability merge helper
- Modify: `src/targets/short_trade_target_evaluation_helpers.py`
  - emit canonical core payload at the short-trade source
- Modify: `src/execution/daily_pipeline_candidate_helpers.py`
  - reuse the same canonical payload when building `short_trade_boundary_metrics`
- Create: `tests/targets/test_short_trade_boundary_contract_helpers.py`
  - narrow helper-level precedence tests
- Modify: `tests/execution/test_daily_pipeline_candidate_helpers.py`
  - verify downstream contract backfill and precedence
- Modify: `tests/test_analyze_btst_5d_15pct_boundary_contract_inspection_script.py`
  - verify repaired rows no longer classify into the current boundary bucket
- Modify: `tests/test_analyze_btst_5d_15pct_boundary_quarantine_script.py`
  - verify the repair shrinks the quarantine surface
- Modify: `tests/test_analyze_btst_5d_15pct_factor_research_round1_script.py`
  - verify repaired custom-`reports_root` rows are no longer excluded by implicit quarantine discovery
- Create: `docs/prompt/find_actor_methord/btst-boundary-upstream-contract-repair-2026-05-22.md`
  - diagnosis-only note for this repair cycle

### Task 1: Create the canonical boundary-contract helper

**Files:**
- Create: `src/targets/short_trade_boundary_contract_helpers.py`
- Test: `tests/targets/test_short_trade_boundary_contract_helpers.py`

- [ ] **Step 1: Write the failing helper tests**

Create `tests/targets/test_short_trade_boundary_contract_helpers.py`:

```python
from src.targets.short_trade_boundary_contract_helpers import (
    BOUNDARY_CONTRACT_CORE_KEYS,
    build_boundary_contract_core_payload,
    merge_boundary_contract_core_payload,
)


def test_build_boundary_contract_core_payload_prefers_explicit_values() -> None:
    payload = build_boundary_contract_core_payload(
        explicit_values={
            "breakout_freshness": 0.71,
            "trend_acceleration": 0.66,
            "volume_expansion_quality": 0.63,
            "close_strength": 0.68,
        },
        metrics_payload={
            "breakout_freshness": 0.11,
            "trend_acceleration": 0.22,
            "volume_expansion_quality": 0.33,
            "close_strength": 0.44,
            "trend_continuation": 0.57,
        },
    )

    assert payload == {
        "breakout_freshness": 0.71,
        "trend_acceleration": 0.66,
        "volume_expansion_quality": 0.63,
        "close_strength": 0.68,
        "trend_continuation": 0.57,
    }


def test_build_boundary_contract_core_payload_backfills_from_metrics_when_explicit_missing() -> None:
    payload = build_boundary_contract_core_payload(
        explicit_values={"breakout_freshness": 0.71},
        metrics_payload={
            "trend_acceleration": 0.66,
            "volume_expansion_quality": 0.63,
            "close_strength": 0.68,
            "short_term_reversal": 0.21,
        },
    )

    assert payload == {
        "breakout_freshness": 0.71,
        "trend_acceleration": 0.66,
        "volume_expansion_quality": 0.63,
        "close_strength": 0.68,
        "short_term_reversal": 0.21,
    }


def test_merge_boundary_contract_core_payload_preserves_existing_explainability_values() -> None:
    merged = merge_boundary_contract_core_payload(
        explainability_payload={
            "breakout_freshness": 0.81,
            "committee": {"enabled": True},
        },
        core_payload={
            "breakout_freshness": 0.71,
            "trend_acceleration": 0.66,
        },
    )

    assert merged["breakout_freshness"] == 0.81
    assert merged["trend_acceleration"] == 0.66
    assert merged["committee"] == {"enabled": True}


def test_boundary_contract_core_keys_are_the_expected_boundary_surface() -> None:
    assert BOUNDARY_CONTRACT_CORE_KEYS == (
        "breakout_freshness",
        "close_strength",
        "short_term_reversal",
        "trend_acceleration",
        "trend_continuation",
        "volume_expansion_quality",
    )
```

- [ ] **Step 2: Run the helper tests and verify they fail**

Run:

```bash
uv run pytest tests/targets/test_short_trade_boundary_contract_helpers.py -q
```

Expected: `FAIL` with import error because `src/targets/short_trade_boundary_contract_helpers.py` does not exist yet.

- [ ] **Step 3: Write the minimal helper implementation**

Create `src/targets/short_trade_boundary_contract_helpers.py`:

```python
from __future__ import annotations

from typing import Any, Mapping

BOUNDARY_CONTRACT_CORE_KEYS = (
    "breakout_freshness",
    "close_strength",
    "short_term_reversal",
    "trend_acceleration",
    "trend_continuation",
    "volume_expansion_quality",
)


def build_boundary_contract_core_payload(
    *,
    explicit_values: Mapping[str, Any] | None = None,
    metrics_payload: Mapping[str, Any] | None = None,
) -> dict[str, float]:
    payload: dict[str, float] = {}
    explicit = dict(explicit_values or {})
    metrics = dict(metrics_payload or {})
    for key in BOUNDARY_CONTRACT_CORE_KEYS:
        value = explicit.get(key)
        if value is None:
            value = metrics.get(key)
        if value is not None:
            payload[key] = round(float(value), 4)
    return payload


def merge_boundary_contract_core_payload(
    *,
    explainability_payload: Mapping[str, Any] | None = None,
    core_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    merged = dict(explainability_payload or {})
    for key, value in dict(core_payload or {}).items():
        merged.setdefault(str(key), value)
    return merged
```

- [ ] **Step 4: Run the helper tests and verify they pass**

Run:

```bash
uv run pytest tests/targets/test_short_trade_boundary_contract_helpers.py -q
```

Expected: `4 passed`.

- [ ] **Step 5: Commit the helper**

Run:

```bash
git add src/targets/short_trade_boundary_contract_helpers.py tests/targets/test_short_trade_boundary_contract_helpers.py
git commit -m "feat: add short-trade boundary contract helper"
```

### Task 2: Emit canonical boundary-contract keys from the short-trade source

**Files:**
- Modify: `src/targets/short_trade_target_evaluation_helpers.py:759-822`
- Modify: `src/targets/short_trade_target_evaluation_helpers.py:1221-1290`
- Test: `tests/targets/test_short_trade_boundary_contract_helpers.py`

- [ ] **Step 1: Add a failing source-emission regression**

Append this test to `tests/targets/test_short_trade_boundary_contract_helpers.py`:

```python
from src.targets.short_trade_boundary_contract_helpers import build_boundary_contract_core_payload, merge_boundary_contract_core_payload


def test_source_style_boundary_contract_payload_can_be_merged_into_explainability() -> None:
    metrics_payload = {
        "trend_continuation": 0.57,
        "short_term_reversal": 0.21,
    }
    explicit_values = {
        "breakout_freshness": 0.71,
        "trend_acceleration": 0.66,
        "volume_expansion_quality": 0.63,
        "close_strength": 0.68,
    }

    core_payload = build_boundary_contract_core_payload(
        explicit_values=explicit_values,
        metrics_payload=metrics_payload,
    )
    explainability_payload = merge_boundary_contract_core_payload(
        explainability_payload={"committee": {"enabled": True}},
        core_payload=core_payload,
    )

    assert explainability_payload["breakout_freshness"] == 0.71
    assert explainability_payload["trend_continuation"] == 0.57
    assert explainability_payload["short_term_reversal"] == 0.21
```

- [ ] **Step 2: Run the helper suite and verify the new regression passes red/green through implementation**

Run:

```bash
uv run pytest tests/targets/test_short_trade_boundary_contract_helpers.py -q
```

Expected before wiring into production code: helper suite still passes, proving the helper contract is stable and ready to wire.

- [ ] **Step 3: Wire the helper into the source emitter**

Modify `src/targets/short_trade_target_evaluation_helpers.py`:

```python
from src.targets.short_trade_boundary_contract_helpers import (
    build_boundary_contract_core_payload,
    merge_boundary_contract_core_payload,
)
```

In `build_short_trade_target_result(...)`, replace the inline payload construction with locals:

```python
    metrics_payload = _build_short_trade_metrics_payload(
        input_data=input_data,
        profile=snapshot["profile"],
        snapshot=snapshot,
        breakout_stage=thresholds.breakout_stage,
        selected_breakout_gate_pass=thresholds.selected_breakout_gate_pass,
        near_miss_breakout_gate_pass=thresholds.near_miss_breakout_gate_pass,
        carryover_evidence_deficiency=context.carryover_evidence_deficiency,
        selected_historical_proof_deficiency=context.selected_historical_proof_deficiency,
    )
    explainability_payload = _build_short_trade_explainability_payload(
        input_data=input_data,
        snapshot=snapshot,
        breakout_stage=thresholds.breakout_stage,
        state=_build_short_trade_explainability_state(snapshot),
        carryover_evidence_deficiency=context.carryover_evidence_deficiency,
        selected_historical_proof_deficiency=context.selected_historical_proof_deficiency,
    )
    boundary_contract_core_payload = build_boundary_contract_core_payload(
        explicit_values={
            "breakout_freshness": round(thresholds.breakout_freshness, 4),
            "trend_acceleration": round(thresholds.trend_acceleration, 4),
            "volume_expansion_quality": round(float(snapshot["volume_expansion_quality"]), 4),
            "close_strength": round(float(snapshot["close_strength"]), 4),
            "trend_continuation": round(float(snapshot.get("trend_continuation", 0.0)), 4),
            "short_term_reversal": round(float(snapshot.get("short_term_reversal", 0.0)), 4),
        },
        metrics_payload=metrics_payload,
    )
    explainability_payload = merge_boundary_contract_core_payload(
        explainability_payload=explainability_payload,
        core_payload=boundary_contract_core_payload,
    )
```

Then return:

```python
        metrics_payload=metrics_payload,
        explainability_payload=explainability_payload,
```

- [ ] **Step 4: Run the helper suite and a focused target regression**

Run:

```bash
uv run pytest tests/targets/test_short_trade_boundary_contract_helpers.py tests/targets/test_short_trade_target_snapshot_payload_helpers.py -q
```

Expected: all listed tests `PASS`.

- [ ] **Step 5: Commit the source-emitter wiring**

Run:

```bash
git add src/targets/short_trade_target_evaluation_helpers.py tests/targets/test_short_trade_boundary_contract_helpers.py
git commit -m "feat: emit canonical short-trade boundary contract keys"
```

### Task 3: Normalize boundary-lane propagation in the daily pipeline

**Files:**
- Modify: `src/execution/daily_pipeline_candidate_helpers.py:33-57`
- Test: `tests/execution/test_daily_pipeline_candidate_helpers.py`

- [ ] **Step 1: Write the failing pipeline regressions**

Append these tests to `tests/execution/test_daily_pipeline_candidate_helpers.py`:

```python
from src.execution.daily_pipeline_candidate_helpers import build_short_trade_boundary_metrics_payload


def test_build_short_trade_boundary_metrics_payload_backfills_boundary_contract_core_keys_from_raw_candidate_metrics() -> None:
    payload = build_short_trade_boundary_metrics_payload(
        snapshot={
            "breakout_freshness": 0.71,
            "trend_acceleration": 0.66,
            "volume_expansion_quality": 0.63,
            "close_strength": 0.68,
            "catalyst_freshness": 0.55,
            "sector_resonance": 0.44,
            "gate_status": {"data": "pass"},
            "blockers": [],
        },
        compute_candidate_score_fn=lambda snapshot: 0.77,
        raw_candidate_metrics={
            "trend_continuation": 0.57,
            "short_term_reversal": 0.21,
        },
    )

    assert payload["trend_continuation"] == 0.57
    assert payload["short_term_reversal"] == 0.21


def test_build_short_trade_boundary_metrics_payload_keeps_explicit_snapshot_values_authoritative() -> None:
    payload = build_short_trade_boundary_metrics_payload(
        snapshot={
            "breakout_freshness": 0.71,
            "trend_acceleration": 0.66,
            "volume_expansion_quality": 0.63,
            "close_strength": 0.68,
            "trend_continuation": 0.61,
            "short_term_reversal": 0.19,
            "catalyst_freshness": 0.55,
            "sector_resonance": 0.44,
            "gate_status": {"data": "pass"},
            "blockers": [],
        },
        compute_candidate_score_fn=lambda snapshot: 0.77,
        raw_candidate_metrics={
            "trend_continuation": 0.57,
            "short_term_reversal": 0.21,
        },
    )

    assert payload["trend_continuation"] == 0.61
    assert payload["short_term_reversal"] == 0.19
```

- [ ] **Step 2: Run the pipeline tests and verify they fail**

Run:

```bash
uv run pytest tests/execution/test_daily_pipeline_candidate_helpers.py -q
```

Expected: `FAIL` because the current function only hand-carries the old subset and does not normalize the full boundary-contract core payload.

- [ ] **Step 3: Reuse the canonical helper in the pipeline normalizer**

Modify `src/execution/daily_pipeline_candidate_helpers.py`:

```python
from src.targets.short_trade_boundary_contract_helpers import build_boundary_contract_core_payload
```

Replace the manual per-key propagation block with:

```python
    boundary_contract_core_payload = build_boundary_contract_core_payload(
        explicit_values=snapshot,
        metrics_payload=raw_candidate_metrics,
    )
    payload.update(
        {
            key: value
            for key, value in boundary_contract_core_payload.items()
            if key not in payload or payload.get(key) is None
        }
    )
```

Keep the existing base payload and `raw_candidate_metrics.setdefault(...)` behavior intact for non-core keys.

- [ ] **Step 4: Run the pipeline suite**

Run:

```bash
uv run pytest tests/execution/test_daily_pipeline_candidate_helpers.py tests/targets/test_short_trade_boundary_contract_helpers.py -q
```

Expected: all listed tests `PASS`.

- [ ] **Step 5: Commit the pipeline normalization**

Run:

```bash
git add src/execution/daily_pipeline_candidate_helpers.py tests/execution/test_daily_pipeline_candidate_helpers.py
git commit -m "feat: normalize boundary contract propagation in pipeline"
```

### Task 4: Prove the repair shrinks the boundary / quarantine / round1 surfaces

**Files:**
- Modify: `tests/test_analyze_btst_5d_15pct_boundary_contract_inspection_script.py`
- Modify: `tests/test_analyze_btst_5d_15pct_boundary_quarantine_script.py`
- Modify: `tests/test_analyze_btst_5d_15pct_factor_research_round1_script.py`

- [ ] **Step 1: Write the failing end-to-end regressions**

Append a repaired-contract style test to `tests/test_analyze_btst_5d_15pct_boundary_contract_inspection_script.py`:

```python
def test_analyze_btst_5d_15pct_boundary_contract_inspection_excludes_rows_when_core_explainability_is_present(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_window_20260323_20260326_boundary_contract"
    snapshot_dir = report_dir / "selection_artifacts" / "2026-03-24"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.joinpath("selection_snapshot.json").write_text(
        '''
        {
          "trade_date": "20260324",
          "selection_targets": {
            "001309": {
              "candidate_source": "short_trade_boundary",
              "short_trade": {
                "decision": "selected",
                "explainability_payload": {
                  "breakout_freshness": 0.71,
                  "trend_acceleration": 0.66,
                  "volume_expansion_quality": 0.63,
                  "close_strength": 0.68,
                  "trend_continuation": 0.57,
                  "short_term_reversal": 0.21
                }
              }
            }
          }
        }
        '''.strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        boundary_script,
        "_extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: {
            "cycle_status": "closed_cycle",
            "future_high_hit_15pct_2_5d": False,
            "max_future_high_return_2_5d": 0.04,
            "next_open_return": 0.01,
        },
    )

    analysis = boundary_script.analyze_btst_5d_15pct_boundary_contract_inspection(reports_root)

    assert analysis["boundary_row_count"] == 0
```

Append a repaired-row round1 regression to `tests/test_analyze_btst_5d_15pct_factor_research_round1_script.py`:

```python
def test_analyze_btst_5d_15pct_factor_research_round1_keeps_repaired_rows_visible_under_custom_reports_root(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "custom_reports_root"
    reports_root.mkdir(parents=True, exist_ok=True)
    report_dir = reports_root / "paper_trading_window_20260323_20260326_round1_a"
    snapshot_dir = report_dir / "selection_artifacts" / "2026-03-24"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.joinpath("selection_snapshot.json").write_text(
        '''
        {
          "trade_date": "20260324",
          "selection_targets": {
            "001309": {
              "candidate_source": "short_trade_boundary",
              "short_trade": {
                "decision": "selected",
                "explainability_payload": {
                  "breakout_freshness": 0.71,
                  "trend_acceleration": 0.66,
                  "volume_expansion_quality": 0.63,
                  "close_strength": 0.68,
                  "trend_continuation": 0.57,
                  "short_term_reversal": 0.21
                }
              }
            }
          }
        }
        '''.strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        round1_script,
        "_extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: {
            "cycle_status": "closed_cycle",
            "future_high_hit_15pct_2_5d": True,
            "max_future_high_return_2_5d": 0.18,
            "time_to_hit_15pct": 2,
            "next_open_return": 0.01,
        },
    )

    analysis = round1_script.analyze_btst_5d_15pct_factor_research_round1(
        reports_root,
        min_closed_cycle_count=1,
    )

    assert analysis["row_count"] == 1
```

- [ ] **Step 2: Run the boundary/round1 regressions and verify they fail**

Run:

```bash
uv run pytest tests/test_analyze_btst_5d_15pct_boundary_contract_inspection_script.py tests/test_analyze_btst_5d_15pct_factor_research_round1_script.py -q
```

Expected: `FAIL` because the repaired-contract rows are not yet emitted consistently enough to escape the old boundary bucket.

- [ ] **Step 3: Adjust the verification surfaces only as required by the repaired contract**

Keep production logic changes minimal here. If the repaired rows are already visible to inspection / round1 after Tasks 2-3, only update the tests. If a tiny compatibility adjustment is still needed in an existing verifier, keep it narrow and inside one of these files:

```python
tests/test_analyze_btst_5d_15pct_boundary_contract_inspection_script.py
tests/test_analyze_btst_5d_15pct_boundary_quarantine_script.py
tests/test_analyze_btst_5d_15pct_factor_research_round1_script.py
```

The target behavior is:

```python
assert inspection_analysis["boundary_row_count"] == 0
assert round1_analysis["row_count"] == 1
```

- [ ] **Step 4: Run the full focused regression bundle**

Run:

```bash
uv run pytest \
  tests/targets/test_short_trade_boundary_contract_helpers.py \
  tests/execution/test_daily_pipeline_candidate_helpers.py \
  tests/test_analyze_btst_5d_15pct_boundary_contract_inspection_script.py \
  tests/test_analyze_btst_5d_15pct_boundary_quarantine_script.py \
  tests/test_analyze_btst_5d_15pct_factor_research_round1_script.py \
  -q
```

Expected: all listed tests `PASS`.

- [ ] **Step 5: Commit the verification surface updates**

Run:

```bash
git add \
  tests/targets/test_short_trade_boundary_contract_helpers.py \
  tests/execution/test_daily_pipeline_candidate_helpers.py \
  tests/test_analyze_btst_5d_15pct_boundary_contract_inspection_script.py \
  tests/test_analyze_btst_5d_15pct_boundary_quarantine_script.py \
  tests/test_analyze_btst_5d_15pct_factor_research_round1_script.py
git commit -m "test: verify repaired boundary rows stay off quarantine path"
```

### Task 5: Refresh the diagnosis note and final verification artifacts

**Files:**
- Create: `docs/prompt/find_actor_methord/btst-boundary-upstream-contract-repair-2026-05-22.md`
- Refresh local ignored artifacts:
  - `data/reports/btst_5d_15pct_boundary_contract_inspection_latest.json`
  - `data/reports/btst_5d_15pct_boundary_contract_inspection_latest.md`
  - `data/reports/btst_5d_15pct_boundary_quarantine_latest.json`
  - `data/reports/btst_5d_15pct_boundary_quarantine_latest.md`

- [ ] **Step 1: Write the diagnosis-only note**

Create `docs/prompt/find_actor_methord/btst-boundary-upstream-contract-repair-2026-05-22.md`:

```markdown
# btst-boundary-upstream-contract-repair-2026-05-22

## 结论

- 本轮工作是 upstream contract repair，不是 alpha 因子优化。
- 目标是让 `short_trade_boundary` / `layer_b_boundary` 在源头就写出 inspection / round1 需要的 core explainability surface。
- quarantine 仍然保留为 fail-closed backstop，但本轮重点是减少它继续接住同一批 121 行样本。

## 这轮解决什么

1. 把 short-trade source 里的 boundary contract core keys 统一成 canonical payload。
2. 让 daily pipeline candidate helper 用同一套 precedence/backfill 规则把这些 keys 带入 downstream contract。
3. 用 inspection / quarantine / round1 三个既有 surface 验证 repair 后 cohort 是否缩小。

## 如何验证

1. `uv run pytest tests/targets/test_short_trade_boundary_contract_helpers.py tests/execution/test_daily_pipeline_candidate_helpers.py tests/test_analyze_btst_5d_15pct_boundary_contract_inspection_script.py tests/test_analyze_btst_5d_15pct_boundary_quarantine_script.py tests/test_analyze_btst_5d_15pct_factor_research_round1_script.py -q`
2. `uv run python scripts/analyze_btst_5d_15pct_boundary_contract_inspection.py`
3. `uv run python scripts/analyze_btst_5d_15pct_boundary_quarantine.py`

## fail-closed 说明

- 如果源头仍然缺 key，就保持缺失并继续让 quarantine/inspection 暴露问题，不能造默认因子值。
- 本轮不处理 round2，也不接入 `ai-hedge-fund-btst`。
- 本文档是 diagnosis-only note，不能进入 `docs/prompt/find_actor/`。
```

- [ ] **Step 2: Refresh the local ignored artifacts**

Run:

```bash
uv run python scripts/analyze_btst_5d_15pct_boundary_contract_inspection.py && \
uv run python scripts/analyze_btst_5d_15pct_boundary_quarantine.py
```

Expected: rewrites the ignored boundary inspection and quarantine reports under `data/reports/`.

- [ ] **Step 3: Run the final focused verification bundle**

Run:

```bash
uv run pytest \
  tests/targets/test_short_trade_boundary_contract_helpers.py \
  tests/execution/test_daily_pipeline_candidate_helpers.py \
  tests/test_analyze_btst_5d_15pct_boundary_contract_inspection_script.py \
  tests/test_analyze_btst_5d_15pct_boundary_quarantine_script.py \
  tests/test_analyze_btst_5d_15pct_factor_research_round1_script.py \
  -q && \
uv run python scripts/analyze_btst_5d_15pct_boundary_contract_inspection.py && \
uv run python scripts/analyze_btst_5d_15pct_boundary_quarantine.py
```

Expected: pytest bundle `PASS`es and both inspection/quarantine artifacts refresh successfully.

- [ ] **Step 4: Commit the note**

Run:

```bash
git add docs/prompt/find_actor_methord/btst-boundary-upstream-contract-repair-2026-05-22.md
git commit -m "docs: record upstream boundary contract repair"
```

## Spec coverage check

- Source-core emitter work is covered by **Tasks 1-2**.
- Boundary contract normalization is covered by **Task 3**.
- Boundary / quarantine / round1 verification is covered by **Task 4**.
- Diagnosis-only documentation and final artifact refresh are covered by **Task 5**.

## Placeholder scan

- No placeholders or vague deferred-work wording remain.
- Every code step includes concrete code and exact commands.

## Type consistency check

- The plan consistently uses `BOUNDARY_CONTRACT_CORE_KEYS`, `build_boundary_contract_core_payload`, and `merge_boundary_contract_core_payload`.
- The same canonical payload terminology is used across source emission, pipeline normalization, and downstream verification tasks.
