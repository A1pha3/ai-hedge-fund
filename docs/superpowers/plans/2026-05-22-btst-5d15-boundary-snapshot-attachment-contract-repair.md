# BTST 5D15 Boundary Snapshot Attachment Contract Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `breakout_freshness`, `trend_acceleration`, `volume_expansion_quality`, and `close_strength` survive onto serialized `selection_targets[*].short_trade` surfaces in both selection artifact families, then prove the unchanged boundary trace narrows the remaining diagnosis to the already-known tail-two attachment gap.

**Architecture:** Keep evaluator math and the boundary trace unchanged. Repair the contract at artifact serialization time inside `src/research/artifacts.py` with a tiny shared normalizer that lifts already-computed values from `short_trade.metrics_payload` onto the serialized `short_trade` surface only when the explicit top-level field is absent. Verify it twice: directly in artifact-writer tests and indirectly by reconstructing live-style boundary rows from written artifacts.

**Tech Stack:** Python 3.11+, Pydantic models, pytest, JSON artifact writing, BTST boundary trace scripts.

---

### Task 1: Repair selection-target artifact serialization and lock it with failing-first regressions

**Files:**
- Modify: `src/research/artifacts.py:51-80`
- Modify: `src/research/artifacts.py:611-767`
- Modify: `tests/research/test_selection_artifact_writer.py:1267-1360`
- Modify: `tests/test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_script.py:1-26`
- Modify: `tests/test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_script.py:585-705`

- [ ] **Step 1: Add a focused failing artifact-writer regression for both artifact families**

Add this test near the existing `test_file_selection_artifact_writer_surfaces_p5_contract_metadata_and_review_explanations` fixture block so it reuses the same `DualTargetEvaluation` / `TargetEvaluationResult` pattern:

```python
def test_file_selection_artifact_writer_lifts_short_trade_attachment_keys_onto_surface(tmp_path):
    writer = FileSelectionArtifactWriter(artifact_root=tmp_path, run_id="session_surface_attachment")
    evaluation = DualTargetEvaluation(
        ticker="300724",
        trade_date="20260422",
        short_trade=TargetEvaluationResult(
            target_type="short_trade",
            decision="near_miss",
            score_target=0.73,
            metrics_payload={
                "breakout_freshness": 0.81,
                "trend_acceleration": 0.67,
                "volume_expansion_quality": 0.74,
                "close_strength": 0.64,
                "trend_continuation": 0.55,
                "short_term_reversal": 0.18,
            },
        ),
    )
    plan = ExecutionPlan(
        date="20260422",
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        risk_metrics={"counts": {"layer_a_count": 10, "layer_b_count": 1, "watchlist_count": 1, "buy_order_count": 0}},
        watchlist=[
            LayerCResult(
                ticker="300724",
                score_b=0.8,
                score_c=0.71,
                score_final=0.76,
                quality_score=0.65,
                decision="watch",
            )
        ],
        selection_targets={"300724": evaluation},
        target_mode="short_trade_only",
        dual_target_summary=DualTargetSummary(target_mode="short_trade_only", selection_target_count=1, short_trade_near_miss_count=1),
        buy_orders=[],
    )

    result = writer.write_for_plan(plan=plan, trade_date="20260422", pipeline=None, selected_analysts=None)

    assert result.write_status == "success"
    snapshot = json.loads((tmp_path / "2026-04-22" / "selection_snapshot.json").read_text(encoding="utf-8"))
    replay_input = json.loads((tmp_path / "2026-04-22" / "selection_target_replay_input.json").read_text(encoding="utf-8"))

    snapshot_short_trade = snapshot["selection_targets"]["300724"]["short_trade"]
    replay_short_trade = replay_input["selection_targets"]["300724"]["short_trade"]

    for payload in (snapshot_short_trade, replay_short_trade):
        assert payload["breakout_freshness"] == 0.81
        assert payload["trend_acceleration"] == 0.67
        assert payload["volume_expansion_quality"] == 0.74
        assert payload["close_strength"] == 0.64
        assert payload["metrics_payload"]["trend_continuation"] == 0.55
        assert payload["metrics_payload"]["short_term_reversal"] == 0.18
```

- [ ] **Step 2: Run the focused artifact-writer regression and verify it fails**

Run:

```bash
uv run pytest tests/research/test_selection_artifact_writer.py::test_file_selection_artifact_writer_lifts_short_trade_attachment_keys_onto_surface -v
```

Expected: `FAIL` because the serialized `selection_targets[*].short_trade` payload still lacks one or more of `breakout_freshness`, `trend_acceleration`, `volume_expansion_quality`, or `close_strength` at top level.

- [ ] **Step 3: Add a failing cross-cutting boundary regression that reconstructs live-style rows from written artifacts**

First extend the imports at the top of `tests/test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_script.py`:

```python
from src.execution.models import ExecutionPlan, LayerCResult
from src.research.artifacts import FileSelectionArtifactWriter
from src.targets.models import DualTargetEvaluation, DualTargetSummary, TargetEvaluationResult
```

Then add a helper next to `_write_live_boundary_artifacts()` that uses the real writer instead of a hand-built JSON payload:

```python
def _write_surface_repaired_boundary_artifacts(reports_root: Path) -> dict[str, object]:
    report_dir = reports_root / "paper_trading_window_20260324_boundary_surface_repaired"
    selection_root = report_dir / "selection_artifacts"
    writer = FileSelectionArtifactWriter(artifact_root=selection_root, run_id="boundary_surface_repaired")
    nested_metrics = {
        "breakout_freshness": 0.91,
        "trend_acceleration": 0.82,
        "volume_expansion_quality": 0.73,
        "close_strength": 0.64,
        "trend_continuation": 0.55,
        "short_term_reversal": 0.18,
    }
    evaluation = DualTargetEvaluation(
        ticker="001309",
        trade_date="20260324",
        candidate_source="short_trade_boundary",
        short_trade=TargetEvaluationResult(
            target_type="short_trade",
            decision="near_miss",
            candidate_source="short_trade_boundary",
            metrics_payload=nested_metrics,
        ),
    )
    plan = ExecutionPlan(
        date="20260324",
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        risk_metrics={"counts": {"layer_a_count": 10, "layer_b_count": 1, "watchlist_count": 1, "buy_order_count": 0}},
        watchlist=[
            LayerCResult(
                ticker="001309",
                score_b=0.71,
                score_c=0.66,
                score_final=0.69,
                quality_score=0.65,
                decision="watch",
            )
        ],
        selection_targets={"001309": evaluation},
        target_mode="short_trade_only",
        dual_target_summary=DualTargetSummary(target_mode="short_trade_only", selection_target_count=1, short_trade_near_miss_count=1),
        buy_orders=[],
    )

    writer.write_for_plan(plan=plan, trade_date="20260324", pipeline=None, selected_analysts=None)
    return {
        "report_dir_name": report_dir.name,
        "trade_date": "20260324",
        "ticker": "001309",
        "candidate_source": "short_trade_boundary",
    }
```

Add the regression immediately after `test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_reconstructs_live_rows_from_artifacts`:

```python
def test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_reconstructs_surface_repaired_rows(tmp_path: Path, monkeypatch) -> None:
    script = _load_script_module()
    reports_root = tmp_path / "data" / "reports"
    boundary_row = _write_surface_repaired_boundary_artifacts(reports_root)

    monkeypatch.setattr(
        script,
        "analyze_btst_5d_15pct_boundary_contract_inspection",
        lambda reports_root: {
            "generated_at": "2026-03-25T00:00:00Z",
            "reports_root": str(Path(reports_root).resolve()),
            "boundary_row_count": 1,
            "boundary_rows": [boundary_row],
        },
    )

    analysis = script.analyze_btst_5d_15pct_boundary_missing_six_core_keys(reports_root)

    assert analysis["trace_status_board"][0]["nested_only_missing_six_keys"] == [
        "trend_continuation",
        "short_term_reversal",
    ]
    assert analysis["trace_status_board"][0]["missing_everywhere_missing_six_keys"] == []
    assert analysis["trace_status_board"][0]["surface_visible_keys"] == [
        "breakout_freshness",
        "trend_acceleration",
        "volume_expansion_quality",
        "close_strength",
        "t0_tail_strength",
    ]
    assert analysis["governance_diagnosis_board"] == [
        {
            "action": "fix_snapshot_attachment_contract",
            "row_count": 1,
            "tickers": ["001309"],
            "affected_keys": ["trend_continuation", "short_term_reversal"],
        }
    ]
```

- [ ] **Step 4: Run the cross-cutting regression and verify it fails**

Run:

```bash
uv run pytest tests/test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_script.py::test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_reconstructs_surface_repaired_rows -v
```

Expected: `FAIL` because the real artifact writer still emits the four attachment keys only inside `metrics_payload`, so the trace still reports all six keys as attachment-side losses.

- [ ] **Step 5: Implement the minimal shared serializer in `src/research/artifacts.py`**

Add the key list and helper near the existing low-level serialization helpers:

```python
_SHORT_TRADE_SURFACE_ATTACHMENT_KEYS = (
    "breakout_freshness",
    "trend_acceleration",
    "volume_expansion_quality",
    "close_strength",
)


def _normalize_short_trade_surface_payload(short_trade_payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(short_trade_payload or {})
    metrics_payload = dict(payload.get("metrics_payload") or {})
    for key in _SHORT_TRADE_SURFACE_ATTACHMENT_KEYS:
        if payload.get(key) is None and metrics_payload.get(key) is not None:
            payload[key] = metrics_payload[key]
    return payload


def _serialize_selection_targets_for_artifacts(selection_targets: dict[str, DualTargetEvaluation] | None) -> dict[str, Any]:
    serialized: dict[str, Any] = {}
    for ticker, evaluation in dict(selection_targets or {}).items():
        payload = evaluation.model_dump(mode="json") if isinstance(evaluation, DualTargetEvaluation) else dict(evaluation or {})
        short_trade_payload = dict(payload.get("short_trade") or {})
        if short_trade_payload:
            payload["short_trade"] = _normalize_short_trade_surface_payload(short_trade_payload)
        serialized[str(ticker)] = payload
    return serialized
```

Then replace the direct `dict(plan.selection_targets or {})` calls in both builders with one shared normalized payload:

```python
selection_targets_payload = _serialize_selection_targets_for_artifacts(plan.selection_targets)
```

Use that variable in all three places below:

```python
selection_targets=selection_targets_payload,
```

```python
selection_targets=selection_targets_payload,
```

```python
reporting_target_summary=build_reporting_target_summary(
    selection_targets=selection_targets_payload,
    target_mode=str(getattr(plan, "target_mode", "research_only") or "research_only"),
).model_dump(mode="json"),
```

This keeps `selection_snapshot.json`, `selection_target_replay_input.json`, and `reporting_target_summary` aligned to the same normalized surface contract.

- [ ] **Step 6: Add a precedence regression so explicit top-level values win over nested fallback**

Append this test below the new artifact-writer regression:

```python
def test_file_selection_artifact_writer_preserves_explicit_short_trade_surface_values(tmp_path):
    writer = FileSelectionArtifactWriter(artifact_root=tmp_path, run_id="session_surface_precedence")
    evaluation = DualTargetEvaluation(
        ticker="300724",
        trade_date="20260422",
        short_trade=TargetEvaluationResult(
            target_type="short_trade",
            decision="near_miss",
            breakout_freshness=0.44,
            trend_acceleration=0.45,
            volume_expansion_quality=0.46,
            close_strength=0.47,
            metrics_payload={
                "breakout_freshness": 0.81,
                "trend_acceleration": 0.67,
                "volume_expansion_quality": 0.74,
                "close_strength": 0.64,
            },
        ),
    )
    plan = ExecutionPlan(
        date="20260422",
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        risk_metrics={"counts": {"layer_a_count": 10, "layer_b_count": 1, "watchlist_count": 1, "buy_order_count": 0}},
        watchlist=[
            LayerCResult(
                ticker="300724",
                score_b=0.8,
                score_c=0.71,
                score_final=0.76,
                quality_score=0.65,
                decision="watch",
            )
        ],
        selection_targets={"300724": evaluation},
        target_mode="short_trade_only",
        dual_target_summary=DualTargetSummary(target_mode="short_trade_only", selection_target_count=1, short_trade_near_miss_count=1),
        buy_orders=[],
    )

    writer.write_for_plan(plan=plan, trade_date="20260422", pipeline=None, selected_analysts=None)
    snapshot = json.loads((tmp_path / "2026-04-22" / "selection_snapshot.json").read_text(encoding="utf-8"))
    short_trade = snapshot["selection_targets"]["300724"]["short_trade"]

    assert short_trade["breakout_freshness"] == 0.44
    assert short_trade["trend_acceleration"] == 0.45
    assert short_trade["volume_expansion_quality"] == 0.46
    assert short_trade["close_strength"] == 0.47
```

Do not change the serializer after this point unless this regression fails. The implementation rule is: **top-level value wins; nested `metrics_payload` only backfills absent top-level fields**.

- [ ] **Step 7: Run the direct and cross-cutting tests and verify they pass**

Run:

```bash
uv run pytest \
  tests/research/test_selection_artifact_writer.py::test_file_selection_artifact_writer_lifts_short_trade_attachment_keys_onto_surface \
  tests/research/test_selection_artifact_writer.py::test_file_selection_artifact_writer_preserves_explicit_short_trade_surface_values \
  tests/test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_script.py::test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_reconstructs_surface_repaired_rows \
  -v
```

Expected: all three tests `PASS`.

- [ ] **Step 8: Run the focused artifact/boundary regression bundle**

Run:

```bash
uv run pytest \
  tests/research/test_selection_artifact_writer.py \
  tests/research/test_selection_artifact_engine.py \
  tests/test_btst_boundary_missing_core_key_trace_helpers.py \
  tests/test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_script.py \
  tests/test_analyze_btst_5d_15pct_boundary_contract_inspection_script.py \
  -q
```

Expected: all listed tests `PASS`.

- [ ] **Step 9: Commit the serialization repair**

Run:

```bash
git add \
  src/research/artifacts.py \
  tests/research/test_selection_artifact_writer.py \
  tests/test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_script.py
git commit -m "fix: surface short trade attachment keys in selection artifacts"
```

### Task 2: Refresh diagnostics, regenerate local reports, and document the fail-closed outcome

**Files:**
- Create: `docs/prompt/find_actor_methord/btst-5d15-boundary-snapshot-attachment-contract-repair-2026-05-22.md`
- Refresh local ignored artifacts: `data/reports/btst_5d_15pct_boundary_missing_six_core_keys_latest.json`
- Refresh local ignored artifacts: `data/reports/btst_5d_15pct_boundary_missing_six_core_keys_latest.md`

- [ ] **Step 1: Re-run the boundary trace script against local reports**

Run:

```bash
uv run python scripts/analyze_btst_5d_15pct_boundary_missing_six_core_keys.py
```

Expected: the script rewrites `data/reports/btst_5d_15pct_boundary_missing_six_core_keys_latest.json` and `.md`. If the current local sample root still yields `boundary_row_count=0`, keep that fact in the note instead of inventing a live success claim.

- [ ] **Step 2: Write the diagnosis-only Chinese note for this repair cycle**

Create `docs/prompt/find_actor_methord/btst-5d15-boundary-snapshot-attachment-contract-repair-2026-05-22.md` with this content:

```markdown
# btst-5d15-boundary-snapshot-attachment-contract-repair-2026-05-22

## 结论

- 本轮修复的是 `selection_snapshot.json` / `selection_target_replay_input.json` 的序列化表面契约，不是新的 alpha 因子。
- `breakout_freshness`、`trend_acceleration`、`volume_expansion_quality`、`close_strength` 现在会在 `selection_targets[*].short_trade` 顶层显式暴露。
- `trend_continuation`、`short_term_reversal` 仍然保持 fail-closed：若仅存在于嵌套层，边界追踪仍会继续报 `fix_snapshot_attachment_contract`。

## 这轮修复解决了什么

1. 保持短线评估器不变，不修改因子计算逻辑。
2. 仅在 artifact 写出前把已存在的四个字段抬升到 `short_trade` 表层。
3. 让 `selection_snapshot.json` 与 `selection_target_replay_input.json` 使用同一份序列化契约。

## 如何验证

1. 直接回归：`uv run pytest tests/research/test_selection_artifact_writer.py -q`
2. 边界回归：`uv run pytest tests/test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_script.py -q`
3. 本地诊断：`uv run python scripts/analyze_btst_5d_15pct_boundary_missing_six_core_keys.py`

## fail-closed 说明

- 如果本地样本仍然是 `boundary_row_count=0`，这只说明当前样本窗口没有可追踪边界行，不代表可以跳过回归测试。
- 本文档不能进入 `docs/prompt/find_actor/`。
- 本轮修复不能直接进入 `ai-hedge-fund-btst` 作为因子/策略提升。
```

- [ ] **Step 3: Run the final verification bundle after the note is written**

Run:

```bash
uv run pytest \
  tests/research/test_selection_artifact_writer.py \
  tests/research/test_selection_artifact_engine.py \
  tests/test_btst_boundary_missing_core_key_trace_helpers.py \
  tests/test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_script.py \
  tests/test_analyze_btst_5d_15pct_boundary_contract_inspection_script.py \
  -q && \
uv run python scripts/analyze_btst_5d_15pct_boundary_missing_six_core_keys.py
```

Expected: the pytest bundle `PASS`es; the script refreshes the local ignored reports without widening scope beyond diagnostics.

- [ ] **Step 4: Commit the note and refreshed diagnostics metadata**

Run:

```bash
git add docs/prompt/find_actor_methord/btst-5d15-boundary-snapshot-attachment-contract-repair-2026-05-22.md
git commit -m "docs: record boundary snapshot attachment repair"
```

## Spec coverage check

- Serialized short-trade surface contract repaired in **Task 1, Steps 5-7**.
- Same serializer used in both `selection_snapshot.json` and `selection_target_replay_input.json` in **Task 1, Step 5**.
- Boundary trace left unchanged and used as the verifier in **Task 1, Steps 3-4 and 7-8**.
- Fail-closed posture and diagnosis-only documentation covered in **Task 2, Steps 1-3**.

## Placeholder scan

- No unresolved placeholders or vague “add tests later” instructions remain.
- Every code-changing step includes concrete code or exact commands.

## Type consistency check

- Serializer helpers operate on `dict[str, DualTargetEvaluation] | None`, matching `SelectionSnapshot.selection_targets` and `SelectionTargetReplayInput.selection_targets`.
- Surface keys match the existing `TargetEvaluationResult` fields exactly: `breakout_freshness`, `trend_acceleration`, `volume_expansion_quality`, `close_strength`.
