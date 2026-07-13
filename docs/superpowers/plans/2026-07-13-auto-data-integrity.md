# Auto Data Integrity and Strict As-Of Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `--auto` publish one auditable healthy report or a separate degraded attempt, while every historical feature uses only information available before the requested trade date.

**Architecture:** `auto_pipeline.py` owns IO orchestration and immutable input snapshots; `compute_auto_screening_results()` becomes report-publication-free. Tracking consumes the in-memory payload after canonical publication, and daily-action validates a run-bound per-ticker manifest instead of trusting a global latest date.

**Tech Stack:** Python 3.13, pandas, pathlib/tempfile/fsync/os.replace, pytest, existing screening modules.

## Global Constraints

- Execute only after the ledger/execution plan is complete and in an isolated worktree.
- A degraded attempt never overwrites a healthy same-date canonical report.
- Optional feature degradation does not stop management of existing positions.
- Default CLI status 0 covers completed healthy/degraded runs; `--strict-quality` makes degraded nonzero.
- No current-date feature may read a report dated on or after the requested trade date.
- Different `model_version` or strategy fingerprints do not pool by default.
- Full-pool investability remains shadow until every dimension supports explicit full-pool inputs.

---

## File Structure

- Create `src/screening/auto_pipeline.py`: run id, attempt status, prepare/compute/publish orchestration.
- Create `src/screening/data_quality_manifest.py`: per-ticker trade-readiness schema and validator.
- Create `src/utils/atomic_files.py`: durable same-directory JSON/CSV replacement.
- Modify `src/main.py`: thin CLI wrapper; close lock fd in finally.
- Modify `src/screening/recommendation_tracker.py`: payload-driven tracking API.
- Modify `src/screening/expected_return.py`, `confidence_calibration.py`, `composite_score.py`: explicit as-of/history/model version.
- Modify cache writers in `cache_refresh.py` and `fund_flow_store.py` to use atomic CSV replacement.
- Add focused tests under `tests/screening/`, `tests/offensive/`, and `tests/test_main_auto_cache_refresh.py`.

### Task 1: Durable atomic JSON and CSV primitives

**Files:**
- Create: `src/utils/atomic_files.py`
- Create: `tests/utils/test_atomic_files.py`
- Modify: `src/screening/offensive/cache_refresh.py`
- Modify: `src/screening/offensive/data/fund_flow_store.py`

**Interfaces:**
- Produces: `atomic_write_json(path, payload)`, `atomic_write_csv(path, frame)`.

- [ ] **Step 1: Write failing atomicity tests**

```python
import json
from pathlib import Path

import pandas as pd
import pytest

from src.utils.atomic_files import atomic_write_csv, atomic_write_json


def test_json_failure_preserves_previous_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "report.json"
    target.write_text('{"version": 1}', encoding="utf-8")
    monkeypatch.setattr(json, "dump", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        atomic_write_json(target, {"version": 2})
    assert json.loads(target.read_text(encoding="utf-8")) == {"version": 1}
    assert list(tmp_path.glob(".*.tmp")) == []


def test_csv_round_trip_replaces_complete_file(tmp_path: Path) -> None:
    target = tmp_path / "prices.csv"
    atomic_write_csv(target, pd.DataFrame([{"date": "20260710", "close": 10.0}]))
    assert pd.read_csv(target, dtype={"date": str}).to_dict("records") == [{"date": "20260710", "close": 10.0}]
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/utils/test_atomic_files.py -v`

Expected: module import fails.

- [ ] **Step 3: Implement durable replacement**

Both functions must create a temp file in `path.parent`, write, flush, `os.fsync(file.fileno())`, then `os.replace(temp, path)`. On every exception unlink the temp and preserve the prior target. `atomic_write_json()` must sanitize non-finite floats and use `allow_nan=False`; `atomic_write_csv()` must call `frame.to_csv(file, index=False)`.

- [ ] **Step 4: Route cache writers through the helper**

Replace direct `df.to_csv(cache, index=False)` calls in price and fund-flow cache writers. Preserve existing column order and dtype behavior.

- [ ] **Step 5: Verify GREEN**

Run:

```bash
uv run pytest tests/utils/test_atomic_files.py -v
uv run pytest tests/offensive/test_daily_action_cache_refresh.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/utils/atomic_files.py src/screening/offensive/cache_refresh.py src/screening/offensive/data/fund_flow_store.py tests/utils/test_atomic_files.py
git commit -m "fix: publish market caches atomically"
```

### Task 2: Per-ticker trade-readiness manifest

**Files:**
- Create: `src/screening/data_quality_manifest.py`
- Create: `tests/screening/test_data_quality_manifest.py`

**Interfaces:**
- Produces: `TickerReadiness`, `RunManifest`, `validate_ticker_readiness()`.

- [ ] **Step 1: Write failing manifest tests**

```python
from datetime import date

from src.screening.data_quality_manifest import validate_ticker_readiness


def test_complete_btst_ticker_is_trade_ready() -> None:
    result = validate_ticker_readiness(
        ticker="000001",
        trade_date=date(2026, 7, 10),
        ohlcv_date=date(2026, 7, 10),
        ohlcv_finite=True,
        fund_flow_date=date(2026, 7, 10),
        fund_flow_history_days=20,
        industry_date=date(2026, 7, 10),
        security_status="listed",
        st_status=False,
        board_rule_version="sse-szse-202607",
        cache_fingerprint="sha256:abc",
    )
    assert result.trade_ready is True
    assert result.block_reasons == ()


def test_short_fund_flow_history_blocks_trade() -> None:
    result = validate_ticker_readiness(
        ticker="000001",
        trade_date=date(2026, 7, 10),
        ohlcv_date=date(2026, 7, 10),
        ohlcv_finite=True,
        fund_flow_date=date(2026, 7, 10),
        fund_flow_history_days=4,
        industry_date=date(2026, 7, 10),
        security_status="listed",
        st_status=False,
        board_rule_version="sse-szse-202607",
        cache_fingerprint="sha256:abc",
    )
    assert result.trade_ready is False
    assert result.block_reasons == ("fund_flow_history:4<20",)


def test_unknown_st_status_fails_closed() -> None:
    result = validate_ticker_readiness(
        ticker="000001",
        trade_date=date(2026, 7, 10),
        ohlcv_date=date(2026, 7, 10),
        ohlcv_finite=True,
        fund_flow_date=date(2026, 7, 10),
        fund_flow_history_days=20,
        industry_date=date(2026, 7, 10),
        security_status="listed",
        st_status=None,
        board_rule_version="sse-szse-202607",
        cache_fingerprint="sha256:abc",
    )
    assert "st_status:unknown" in result.block_reasons
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/screening/test_data_quality_manifest.py -v`

Expected: module import fails.

- [ ] **Step 3: Implement frozen dataclasses and validator**

`TickerReadiness` contains every test input plus `trade_ready` and tuple `block_reasons`. `RunManifest` contains `run_id`, `trade_date`, `status`, `created_at`, and a ticker-keyed mapping. The validator adds deterministic reasons in field order and never converts unknown to a passing default.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest tests/screening/test_data_quality_manifest.py -v`

Expected: all manifest tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/screening/data_quality_manifest.py tests/screening/test_data_quality_manifest.py
git commit -m "feat: record per-ticker trade readiness"
```

### Task 3: Payload-driven tracking without current-report disk reads

**Files:**
- Modify: `src/screening/recommendation_tracker.py`
- Modify: `tests/test_recommendation_tracker_extended_horizons.py`
- Create: `tests/screening/test_tracking_from_payload.py`

**Interfaces:**
- Produces: `update_tracking_history_from_payload(reports_dir, trade_date, report_payload, *, use_data_fetcher=None)`.
- Existing `update_tracking_history()` remains a compatibility wrapper that loads a report then delegates.

- [ ] **Step 1: Write the failing payload test**

```python
import json
from pathlib import Path

from src.screening.recommendation_tracker import update_tracking_history_from_payload


def test_tracking_accepts_payload_without_report_file(tmp_path: Path) -> None:
    payload = {
        "date": "20260710",
        "model_version": "model-v2",
        "recommendations": [
            {"ticker": "000001", "name": "平安银行", "score_b": 0.5, "recommended_price": 10.0}
        ],
    }
    updated = update_tracking_history_from_payload(tmp_path, "20260710", payload, use_data_fetcher=lambda *args: [])
    assert updated == 1
    history = json.loads((tmp_path / "tracking_history.json").read_text(encoding="utf-8"))
    assert history["records"][0]["model_version"] == "model-v2"
    assert list(tmp_path.glob("auto_screening_*.json")) == []
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/screening/test_tracking_from_payload.py -v`

Expected: function import fails.

- [ ] **Step 3: Extract the shared locked implementation**

Pass pending recommendations and model version into `_update_tracking_history_locked()` instead of loading them there. The compatibility wrapper calls `load_pending_recommendations_with_version()` and then the shared function; the new API validates `payload["date"] == trade_date` and passes the payload recommendations directly.

- [ ] **Step 4: Verify GREEN and old horizons**

Run:

```bash
uv run pytest tests/screening/test_tracking_from_payload.py -v
uv run pytest tests/test_recommendation_tracker_extended_horizons.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/screening/recommendation_tracker.py tests/screening/test_tracking_from_payload.py tests/test_recommendation_tracker_extended_horizons.py
git commit -m "refactor: update tracking from report payload"
```

### Task 4: Strict as-of calibration and composite inputs

**Files:**
- Modify: `src/screening/confidence_calibration.py`
- Modify: `src/screening/expected_return.py`
- Modify: `src/screening/composite_score.py`
- Create: `tests/screening/test_strict_asof_features.py`

**Interfaces:**
- `compute_expected_returns(*, recommendations: list[dict[str, Any]], as_of: str, model_version: str, history_records: Sequence[Mapping[str, Any]], lookback_days: int = 60) -> ExpectedReturnReport`.
- `compute_composite_scores_for_recommendations(*, recommendations: list[dict[str, Any]], trade_date: str, as_of: str, history_reports: Sequence[Mapping[str, Any]], lookback_days: int = 5) -> CompositeReport`.

- [ ] **Step 1: Write failing future-mutation tests**

```python
from copy import deepcopy

from src.screening.expected_return import compute_expected_returns


def test_future_tracking_record_does_not_change_past_expected_return() -> None:
    records = [
        {"ticker": "A", "recommended_date": "20260601", "model_version": "v2", "recommendation_score": 0.5, "next_10day_return": 5.0},
        {"ticker": "B", "recommended_date": "20260720", "model_version": "v2", "recommendation_score": 0.5, "next_10day_return": -99.0},
    ]
    kwargs = dict(
        recommendations=[{"ticker": "X", "score_b": 0.5}],
        as_of="20260710",
        model_version="v2",
        history_records=records,
    )
    before = compute_expected_returns(**kwargs).to_dict()
    mutated = deepcopy(records)
    mutated[1]["next_10day_return"] = 999.0
    after = compute_expected_returns(**{**kwargs, "history_records": mutated}).to_dict()
    assert before == after


def test_other_model_version_is_not_pooled() -> None:
    records = [
        {"ticker": "A", "recommended_date": "20260601", "model_version": "old", "recommendation_score": 0.5, "next_10day_return": 100.0}
    ]
    report = compute_expected_returns(
        recommendations=[{"ticker": "X", "score_b": 0.5}],
        as_of="20260710",
        model_version="new",
        history_records=records,
    )
    assert report.total_samples == 0
```

Add a composite test that passes a future `history_reports` item, mutates it, and asserts identical past output.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/screening/test_strict_asof_features.py -v`

Expected: current functions reject the new arguments or include future records.

- [ ] **Step 3: Implement explicit snapshots**

Filter tracking records by `recommended_date < as_of`, matching model version, and label maturity date strictly before as-of. Remove internal latest-report reads from the explicit composite path; each dimension receives the supplied prior report snapshot. Keep CLI compatibility wrappers that resolve snapshots once at the boundary.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest tests/screening/test_strict_asof_features.py -v`

Expected: all as-of tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/screening/confidence_calibration.py src/screening/expected_return.py src/screening/composite_score.py tests/screening/test_strict_asof_features.py
git commit -m "fix: enforce strict as-of screening features"
```

### Task 5: Auto pipeline, canonical/attempt publication, and lock semantics

**Files:**
- Create: `src/screening/auto_pipeline.py`
- Modify: `src/main.py`
- Create: `tests/screening/test_auto_pipeline_publication.py`
- Modify: `tests/test_main_auto_cache_refresh.py`

**Interfaces:**
- Produces: `AutoRunStatus`, `AutoRunResult`, `run_auto_pipeline(trade_date, top_n, strict_quality=False)`.

- [ ] **Step 1: Write failing publication tests**

```python
import json
from pathlib import Path

from src.screening.auto_pipeline import AutoRunStatus, run_auto_pipeline


def test_healthy_run_publishes_one_canonical(tmp_path: Path, fake_auto_dependencies) -> None:
    result = run_auto_pipeline("20260710", 10, reports_dir=tmp_path, dependencies=fake_auto_dependencies.healthy())
    assert result.status is AutoRunStatus.HEALTHY
    assert result.exit_code == 0
    assert len(list(tmp_path.glob("auto_screening_20260710.json"))) == 1
    assert list(tmp_path.glob("auto_attempt_20260710_*.json")) == []


def test_degraded_attempt_does_not_overwrite_healthy_canonical(tmp_path: Path, fake_auto_dependencies) -> None:
    canonical = tmp_path / "auto_screening_20260710.json"
    canonical.write_text('{"status":"healthy","run_id":"old"}', encoding="utf-8")
    result = run_auto_pipeline("20260710", 10, reports_dir=tmp_path, dependencies=fake_auto_dependencies.degraded())
    assert result.status is AutoRunStatus.DEGRADED
    assert result.exit_code == 0
    assert json.loads(canonical.read_text(encoding="utf-8"))["run_id"] == "old"
    assert len(list(tmp_path.glob("auto_attempt_20260710_*.json"))) == 1


def test_strict_quality_maps_degraded_to_nonzero(tmp_path: Path, fake_auto_dependencies) -> None:
    result = run_auto_pipeline("20260710", 10, reports_dir=tmp_path, dependencies=fake_auto_dependencies.degraded(), strict_quality=True)
    assert result.exit_code != 0
```

The fixture is a concrete dataclass of callables returning a fixed payload, manifest, and tracking result; it performs no network IO.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/screening/test_auto_pipeline_publication.py -v`

Expected: auto pipeline module is missing.

- [ ] **Step 3: Implement orchestration and thin main wrapper**

Implement `run_auto_pipeline()` in this fixed order:

```python
inputs = dependencies.prepare_inputs(trade_date)
payload = dependencies.compute_report(inputs, top_n)
manifest = dependencies.build_manifest(inputs, payload)
if manifest.is_healthy:
    canonical = dependencies.publish_canonical(payload, manifest)
    dependencies.update_tracking(payload)
    return AutoRunResult(AutoRunStatus.HEALTHY, 0, canonical)
attempt = dependencies.publish_attempt(payload, manifest)
code = 3 if strict_quality else 0
return AutoRunResult(AutoRunStatus.DEGRADED, code, attempt)
```

Fatal exceptions return status FATAL and exit code 1 without replacing canonical. `run_auto_screening()` obtains the existing flock, delegates, and always closes the fd in finally. Busy returns a documented temporary-failure code, not 0.

- [ ] **Step 4: Verify GREEN and cache bridge**

Run:

```bash
uv run pytest tests/screening/test_auto_pipeline_publication.py -v
uv run pytest tests/test_main_auto_cache_refresh.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/screening/auto_pipeline.py src/main.py tests/screening/test_auto_pipeline_publication.py tests/test_main_auto_cache_refresh.py
git commit -m "refactor: publish auto reports from one pipeline"
```

### Task 6: Daily-action manifest gate and full-pool shadow ranking

**Files:**
- Modify: `src/screening/offensive/daily_action_service.py`
- Modify: `src/screening/investability.py`
- Modify: `src/main.py`
- Create: `tests/offensive/test_daily_action_manifest_gate.py`
- Create: `tests/screening/test_full_pool_shadow_ranking.py`

**Interfaces:**
- Daily action consumes a healthy exact-date manifest and revalidates each candidate cache row.
- Auto emits `shadow_rank` without changing canonical recommendation order.

- [ ] **Step 1: Write failing gate tests**

```python
def test_missing_healthy_manifest_blocks_new_plan_but_keeps_open_positions(service, open_trade):
    run = service.run(as_of=open_trade.entry_date, candidates=[], manifest=None)
    assert run.new_plans == ()
    assert run.open_positions[0].trade_id == open_trade.trade_id
    assert run.block_reason == "healthy_manifest_missing"


def test_ticker_fingerprint_mismatch_blocks_only_that_candidate(service, healthy_manifest, candidates):
    healthy_manifest.tickers[candidates[0].ticker].cache_fingerprint = "sha256:stale"
    run = service.run(as_of=healthy_manifest.trade_date, candidates=candidates, manifest=healthy_manifest)
    assert candidates[0].ticker in run.blocked_tickers
    assert candidates[1].ticker not in run.blocked_tickers
```

Add a ranking test with 40 candidates where candidate 35 wins the explicit full-pool shadow computation while canonical order remains unchanged.

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run pytest tests/offensive/test_daily_action_manifest_gate.py -v
uv run pytest tests/screening/test_full_pool_shadow_ranking.py -v
```

Expected: manifest and shadow-rank interfaces are missing.

- [ ] **Step 3: Implement fail-closed gate and shadow field**

Do not delete the canonical Top 30 preselection in this task. Compute a separate full-pool challenger only when every ticker has complete explicit composite dimensions; otherwise set `shadow_rank_status="insufficient"`. Never let shadow rank affect plan ordering or weights.

- [ ] **Step 4: Verify GREEN**

Run the two tests from Step 2 and expect all pass.

- [ ] **Step 5: Commit**

```bash
git add src/screening/offensive/daily_action_service.py src/screening/investability.py src/main.py tests/offensive/test_daily_action_manifest_gate.py tests/screening/test_full_pool_shadow_ranking.py
git commit -m "feat: gate trades on run-bound data quality"
```

### Task 7: Phase-two verification

**Files:**
- No planned production changes.

- [ ] **Step 1: Run focused suites**

```bash
uv run pytest tests/screening/test_auto_pipeline_publication.py tests/screening/test_strict_asof_features.py tests/screening/test_tracking_from_payload.py -v
uv run pytest tests/offensive/test_daily_action_manifest_gate.py tests/offensive/test_daily_action_cache_refresh.py -v
```

Expected: all tests pass.

- [ ] **Step 2: Run required regressions**

```bash
uv run pytest tests/offensive/ -v
uv run pytest tests/test_main_auto_cache_refresh.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Check report-write call sites**

Run: `rg -n '_save_json_report\(f?"auto_screening_' src`

Expected: canonical auto report publication exists only in `auto_pipeline.py`; compatibility readers may remain elsewhere but no writer does.
