# Auto Feature Store Zero Network I/O Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `uv run python src/main.py --auto` scoring consume local optional-feature snapshots instead of calling live AKShare Eastmoney endpoints during Step 2.

**Architecture:** Add a small local `OptionalFeatureStore` read layer under `src/screening/`, then inject it into `score_batch()` and the auto report builder. Online provider calls stay in existing AKShare wrappers and the refresh boundary, but scoring treats missing snapshots as missing optional factors rather than falling back to network.

**Tech Stack:** Python 3.12, pandas CSV/JSON local files, pytest, existing `CandidateStock` and `StrategySignal` models.

## Global Constraints

- `score_batch()` and helpers called from Step 2 must not call `get_intraday_bars()` or `get_money_flow()`.
- Feature snapshots live under `data/feature_cache/`.
- Use CSV for first implementation to avoid adding parquet dependencies.
- Missing optional snapshots must not block `--auto`.
- Report JSON must include `data_quality.optional_features`.
- Existing AKShare proxy isolation and endpoint breaker behavior remain in provider code.
- Do not change core factor weights or introduce new stock-selection setups.

---

## File Structure

- Create `src/screening/optional_feature_store.py`
  - Owns local snapshot paths, CSV/JSON parsing, stale checks, per-ticker feature lookup, and data-quality summaries.
- Modify `src/screening/strategy_scorer.py`
  - Adds optional feature-store dependency to `score_batch()` and intraday metric population.
  - Removes network fallback from scoring hot path.
- Modify `src/main.py`
  - Constructs one `OptionalFeatureStore` for the auto run.
  - Passes it into `score_batch()`.
  - Adds `optional_feature_quality` into `_build_auto_screening_payload()`.
- Create `src/screening/optional_feature_refresh.py`
  - Adds a bounded, best-effort refresh entry point for future provider-backed snapshots.
  - Phase 1 implementation may write only a manifest when provider refresh is skipped or unavailable.
- Create `tests/screening/test_optional_feature_store.py`
  - Covers read API, stale handling, missing snapshots, and quality summary.
- Modify `tests/screening/test_strategy_scorer.py`
  - Covers scoring helpers consuming feature store and not calling live providers.
- Modify `tests/test_main_auto_feature_quality.py`
  - New focused tests for report payload quality fields.

---

### Task 1: Local Optional Feature Store Read API

**Files:**
- Create: `src/screening/optional_feature_store.py`
- Create: `tests/screening/test_optional_feature_store.py`

**Interfaces:**
- Produces: `OptionalFeatureStore(base_dir: Path | str = "data/feature_cache", max_stale_days: int = 0, allow_stale: bool = False)`
- Produces: `OptionalFeatureStore.load_intraday_metrics(trade_date: str, tickers: list[str]) -> dict[str, dict[str, Any]]`
- Produces: `OptionalFeatureStore.load_fund_flow_metrics(trade_date: str, tickers: list[str]) -> dict[str, dict[str, Any]]`
- Produces: `OptionalFeatureStore.build_quality_summary(trade_date: str, tickers: list[str]) -> dict[str, Any]`
- Produces: CSV file names `intraday_short_trade_metrics_YYYYMMDD.csv` and `daily_fund_flow_metrics_YYYYMMDD.csv`
- Produces: JSON file name `feature_manifest_YYYYMMDD.json`

- [ ] **Step 1: Write failing tests for successful local reads**

Add this to `tests/screening/test_optional_feature_store.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.screening.optional_feature_store import OptionalFeatureStore


def test_load_intraday_metrics_reads_snapshot_for_requested_tickers(tmp_path: Path) -> None:
    cache_dir = tmp_path / "feature_cache"
    cache_dir.mkdir()
    pd.DataFrame(
        [
            {
                "ticker": "000001",
                "trade_date": "20260708",
                "flow_60": 0.12,
                "flow_60_source": "bar_proxy",
                "close_support_30": 0.08,
                "close_support_30_source": "bar_proxy",
                "persist_120": 0.55,
                "persist_120_source": "bar_proxy",
            },
            {
                "ticker": "000002",
                "trade_date": "20260708",
                "flow_60": -0.03,
                "flow_60_source": "daily_flow_proxy",
            },
        ]
    ).to_csv(cache_dir / "intraday_short_trade_metrics_20260708.csv", index=False)

    store = OptionalFeatureStore(base_dir=cache_dir)

    result = store.load_intraday_metrics("20260708", ["000001", "000003"])

    assert result == {
        "000001": {
            "flow_60": 0.12,
            "flow_60_source": "bar_proxy",
            "close_support_30": 0.08,
            "close_support_30_source": "bar_proxy",
            "persist_120": 0.55,
            "persist_120_source": "bar_proxy",
        }
    }


def test_load_fund_flow_metrics_maps_main_flow_ratio(tmp_path: Path) -> None:
    cache_dir = tmp_path / "feature_cache"
    cache_dir.mkdir()
    pd.DataFrame(
        [
            {
                "ticker": "000001",
                "trade_date": "20260708",
                "main_flow_ratio": 0.15,
                "main_flow_ratio_source": "tushare_snapshot",
            }
        ]
    ).to_csv(cache_dir / "daily_fund_flow_metrics_20260708.csv", index=False)

    store = OptionalFeatureStore(base_dir=cache_dir)

    result = store.load_fund_flow_metrics("20260708", ["000001", "000002"])

    assert result == {
        "000001": {
            "main_flow_ratio": 0.15,
            "main_flow_ratio_source": "tushare_snapshot",
        }
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/screening/test_optional_feature_store.py::test_load_intraday_metrics_reads_snapshot_for_requested_tickers tests/screening/test_optional_feature_store.py::test_load_fund_flow_metrics_maps_main_flow_ratio -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.screening.optional_feature_store'`.

- [ ] **Step 3: Implement minimal read API**

Create `src/screening/optional_feature_store.py`:

```python
"""Local optional feature snapshots for auto screening.

This module is intentionally read-only from the scorer's point of view.  Provider
network calls belong in refresh code, not in score_batch().
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


_INTRADAY_PREFIX = "intraday_short_trade_metrics"
_FUND_FLOW_PREFIX = "daily_fund_flow_metrics"
_MANIFEST_PREFIX = "feature_manifest"
_METRIC_COLUMNS = {
    "flow_60",
    "flow_60_source",
    "close_support_30",
    "close_support_30_source",
    "persist_120",
    "persist_120_source",
    "main_flow_ratio",
    "main_flow_ratio_source",
}


@dataclass(frozen=True)
class OptionalFeatureStore:
    base_dir: Path | str = Path("data/feature_cache")
    max_stale_days: int = 0
    allow_stale: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_dir", Path(self.base_dir))

    def load_intraday_metrics(self, trade_date: str, tickers: list[str]) -> dict[str, dict[str, Any]]:
        return self._load_metrics(_INTRADAY_PREFIX, trade_date, tickers)

    def load_fund_flow_metrics(self, trade_date: str, tickers: list[str]) -> dict[str, dict[str, Any]]:
        return self._load_metrics(_FUND_FLOW_PREFIX, trade_date, tickers)

    def load_manifest(self, trade_date: str) -> dict[str, Any]:
        path = self.base_dir / f"{_MANIFEST_PREFIX}_{trade_date}.json"
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        return payload if isinstance(payload, dict) else {}

    def build_quality_summary(self, trade_date: str, tickers: list[str]) -> dict[str, Any]:
        unique_tickers = sorted({str(ticker).zfill(6) for ticker in tickers})
        manifest = self.load_manifest(trade_date)
        return {
            "optional_features": {
                "intraday_short_trade_metrics": self._quality_for_family(
                    family="intraday_short_trade_metrics",
                    prefix=_INTRADAY_PREFIX,
                    trade_date=trade_date,
                    tickers=unique_tickers,
                    manifest=manifest,
                ),
                "daily_fund_flow_metrics": self._quality_for_family(
                    family="daily_fund_flow_metrics",
                    prefix=_FUND_FLOW_PREFIX,
                    trade_date=trade_date,
                    tickers=unique_tickers,
                    manifest=manifest,
                ),
            }
        }

    def _load_metrics(self, prefix: str, trade_date: str, tickers: list[str]) -> dict[str, dict[str, Any]]:
        path = self.base_dir / f"{prefix}_{trade_date}.csv"
        if not path.exists():
            return {}
        df = pd.read_csv(path, dtype={"ticker": str, "trade_date": str})
        if df.empty or "ticker" not in df.columns:
            return {}
        df = df.copy()
        df["ticker"] = df["ticker"].astype(str).str.zfill(6)
        if "trade_date" in df.columns:
            df = df[df["trade_date"].astype(str) == str(trade_date)]
        wanted = {str(ticker).zfill(6) for ticker in tickers}
        df = df[df["ticker"].isin(wanted)]
        result: dict[str, dict[str, Any]] = {}
        for _, row in df.iterrows():
            metrics: dict[str, Any] = {}
            for column in _METRIC_COLUMNS:
                if column not in row.index:
                    continue
                value = row[column]
                if pd.isna(value):
                    continue
                metrics[column] = value.item() if hasattr(value, "item") else value
            if metrics:
                result[str(row["ticker"]).zfill(6)] = metrics
        return result

    def _quality_for_family(
        self,
        *,
        family: str,
        prefix: str,
        trade_date: str,
        tickers: list[str],
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        rows = self._load_metrics(prefix, trade_date, tickers)
        total = len(tickers)
        feature_manifest = (manifest.get("features") or {}).get(family, {})
        provider_failures = int(feature_manifest.get("provider_failures", 0) or 0)
        missing = total - len(rows)
        return {
            "coverage": round((len(rows) / total), 4) if total else 0.0,
            "source": "snapshot" if rows else "missing",
            "trade_date": trade_date,
            "stale": False,
            "provider_failures": provider_failures,
            "missing_tickers": missing,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/screening/test_optional_feature_store.py::test_load_intraday_metrics_reads_snapshot_for_requested_tickers tests/screening/test_optional_feature_store.py::test_load_fund_flow_metrics_maps_main_flow_ratio -q
```

Expected: PASS.

- [ ] **Step 5: Add and run quality summary test**

Append to `tests/screening/test_optional_feature_store.py`:

```python
def test_build_quality_summary_reports_coverage_and_manifest_failures(tmp_path: Path) -> None:
    cache_dir = tmp_path / "feature_cache"
    cache_dir.mkdir()
    pd.DataFrame([{"ticker": "000001", "trade_date": "20260708", "flow_60": 0.2}]).to_csv(
        cache_dir / "intraday_short_trade_metrics_20260708.csv",
        index=False,
    )
    pd.DataFrame([{"ticker": "000002", "trade_date": "20260708", "main_flow_ratio": -0.1}]).to_csv(
        cache_dir / "daily_fund_flow_metrics_20260708.csv",
        index=False,
    )
    (cache_dir / "feature_manifest_20260708.json").write_text(
        json.dumps(
            {
                "features": {
                    "intraday_short_trade_metrics": {"provider_failures": 3},
                    "daily_fund_flow_metrics": {"provider_failures": 1},
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    summary = OptionalFeatureStore(base_dir=cache_dir).build_quality_summary(
        "20260708",
        ["000001", "000002", "000003"],
    )

    assert summary["optional_features"]["intraday_short_trade_metrics"] == {
        "coverage": 0.3333,
        "source": "snapshot",
        "trade_date": "20260708",
        "stale": False,
        "provider_failures": 3,
        "missing_tickers": 2,
    }
    assert summary["optional_features"]["daily_fund_flow_metrics"]["provider_failures"] == 1
    assert summary["optional_features"]["daily_fund_flow_metrics"]["missing_tickers"] == 2
```

Run:

```bash
uv run pytest tests/screening/test_optional_feature_store.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```bash
git add src/screening/optional_feature_store.py tests/screening/test_optional_feature_store.py
git commit -m "feat: add optional feature store snapshots"
```

---

### Task 2: Make Intraday/Fund-Flow Scoring Use Local Store Only

**Files:**
- Modify: `src/screening/strategy_scorer.py`
- Modify: `tests/screening/test_strategy_scorer.py`

**Interfaces:**
- Consumes: `OptionalFeatureStore.load_intraday_metrics(trade_date, tickers)`
- Consumes: `OptionalFeatureStore.load_fund_flow_metrics(trade_date, tickers)`
- Produces: `score_batch(candidates: list[CandidateStock], trade_date: str, feature_store: OptionalFeatureStore | None = None) -> dict[str, dict[str, StrategySignal]]`
- Produces: `_build_intraday_short_trade_metrics(ticker: str, trade_date: str, feature_store: OptionalFeatureStore | None = None) -> dict[str, Any]`
- Produces: `_load_daily_flow_proxy_ratio(ticker: str, trade_date: str | None = None, feature_store: OptionalFeatureStore | None = None) -> float | None`

- [ ] **Step 1: Write failing tests that feature store is used and providers are not called**

Append to `tests/screening/test_strategy_scorer.py`:

```python
class _FakeOptionalFeatureStore:
    def __init__(self) -> None:
        self.intraday_calls: list[tuple[str, list[str]]] = []
        self.fund_flow_calls: list[tuple[str, list[str]]] = []

    def load_intraday_metrics(self, trade_date: str, tickers: list[str]) -> dict[str, dict[str, object]]:
        self.intraday_calls.append((trade_date, tickers))
        return {
            "000001": {
                "flow_60": 0.21,
                "flow_60_source": "snapshot",
                "close_support_30": 0.11,
                "close_support_30_source": "snapshot",
            }
        }

    def load_fund_flow_metrics(self, trade_date: str, tickers: list[str]) -> dict[str, dict[str, object]]:
        self.fund_flow_calls.append((trade_date, tickers))
        return {"000001": {"main_flow_ratio": 0.13, "main_flow_ratio_source": "snapshot"}}


def test_build_intraday_short_trade_metrics_reads_feature_store_without_network(monkeypatch):
    store = _FakeOptionalFeatureStore()
    monkeypatch.setattr(
        strategy_scorer_module,
        "get_intraday_bars",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network call forbidden")),
    )

    metrics = strategy_scorer_module._build_intraday_short_trade_metrics(
        "000001",
        "20260708",
        feature_store=store,
    )

    assert metrics == {
        "flow_60": 0.21,
        "flow_60_source": "snapshot",
        "close_support_30": 0.11,
        "close_support_30_source": "snapshot",
    }
    assert store.intraday_calls == [("20260708", ["000001"])]


def test_daily_flow_proxy_reads_feature_store_without_money_flow_network(monkeypatch):
    store = _FakeOptionalFeatureStore()
    monkeypatch.setattr(
        strategy_scorer_module,
        "get_money_flow",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network call forbidden")),
    )

    result = strategy_scorer_module._load_daily_flow_proxy_ratio(
        "000001",
        trade_date="20260708",
        feature_store=store,
    )

    assert result == 0.13
    assert store.fund_flow_calls == [("20260708", ["000001"])]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/screening/test_strategy_scorer.py::test_build_intraday_short_trade_metrics_reads_feature_store_without_network tests/screening/test_strategy_scorer.py::test_daily_flow_proxy_reads_feature_store_without_money_flow_network -q
```

Expected: FAIL with unexpected keyword argument `feature_store`.

- [ ] **Step 3: Update scorer signatures and store-backed helpers**

In `src/screening/strategy_scorer.py`, add import:

```python
from src.screening.optional_feature_store import OptionalFeatureStore
```

Change `_populate_intraday_short_trade_metrics()` signature and calls:

```python
def _populate_intraday_short_trade_metrics(
    results: dict[str, dict[str, StrategySignal]],
    candidates: list[CandidateStock],
    trade_date: str,
    feature_store: OptionalFeatureStore,
) -> None:
```

Inside `_populate_intraday_short_trade_metrics()`, replace calls to `_build_intraday_short_trade_metrics(candidate.ticker, trade_date)` with:

```python
intraday_metrics = _build_intraday_short_trade_metrics(
    candidate.ticker,
    trade_date,
    feature_store=feature_store,
)
```

Replace `_build_intraday_short_trade_metrics()` with:

```python
def _build_intraday_short_trade_metrics(
    ticker: str,
    trade_date: str,
    feature_store: OptionalFeatureStore | None = None,
) -> dict[str, Any]:
    store = feature_store or OptionalFeatureStore()
    metrics = store.load_intraday_metrics(trade_date, [ticker]).get(str(ticker).zfill(6), {})
    if metrics:
        return dict(metrics)
    fallback_flow = _load_daily_flow_proxy_ratio(ticker, trade_date=trade_date, feature_store=store)
    return {"flow_60": fallback_flow, "flow_60_source": "daily_flow_proxy"} if fallback_flow is not None else {}
```

Replace `_load_daily_flow_proxy_ratio()` with:

```python
def _load_daily_flow_proxy_ratio(
    ticker: str,
    trade_date: str | None = None,
    feature_store: OptionalFeatureStore | None = None,
) -> float | None:
    if trade_date is None:
        return None
    store = feature_store or OptionalFeatureStore()
    metrics = store.load_fund_flow_metrics(trade_date, [ticker]).get(str(ticker).zfill(6), {})
    ratio = metrics.get("main_flow_ratio")
    if ratio is None:
        return None
    try:
        value = float(ratio)
    except (TypeError, ValueError):
        return None
    if abs(value) > 1.0:
        value /= 100.0
    return round(value, 4)
```

Change `score_batch()` signature and body:

```python
def score_batch(
    candidates: list[CandidateStock],
    trade_date: str,
    feature_store: OptionalFeatureStore | None = None,
) -> dict[str, dict[str, StrategySignal]]:
    started_at = perf_counter()
    optional_feature_store = feature_store or OptionalFeatureStore()
    industry_pe_medians = _build_industry_pe_medians(trade_date)
    results = _initialize_score_batch_results(candidates)
    fundamental_candidates = _prepare_heavy_score_candidates(candidates, trade_date, results)
    _populate_heavy_signals(results, fundamental_candidates, trade_date, industry_pe_medians, optional_feature_store)
    elapsed = perf_counter() - started_at
    logger.info(
        "score_batch completed: %d candidates, %d heavy-scored, concurrency=%d, %.2fs",
        len(candidates),
        len(fundamental_candidates),
        SCORE_BATCH_CONCURRENCY,
        elapsed,
    )
    return results
```

Change `_populate_heavy_signals()` signature to accept `feature_store: OptionalFeatureStore`, and change its intraday call to:

```python
_populate_intraday_short_trade_metrics(results, fundamental_candidates, trade_date, feature_store)
```

- [ ] **Step 4: Preserve old low-level bar/tick helper tests**

Do not delete `_build_intraday_short_trade_metrics_from_bars()`, `_build_intraday_short_trade_metrics_from_frames()`, `_extract_intraday_turnover_windows()`, or `_extract_intraday_tick_net_flows()`. Existing unit tests for those pure transforms must still pass because refresh code can reuse them inside the provider boundary.

- [ ] **Step 5: Run focused scorer tests**

Run:

```bash
uv run pytest tests/screening/test_strategy_scorer.py::test_build_intraday_short_trade_metrics_reads_feature_store_without_network tests/screening/test_strategy_scorer.py::test_daily_flow_proxy_reads_feature_store_without_money_flow_network tests/screening/test_strategy_scorer.py::test_build_intraday_short_trade_metrics_uses_bar_proxy_without_fetching_ticks -q
```

Expected: the two new tests PASS. If the old bar-proxy test fails because it expected `_build_intraday_short_trade_metrics()` to fetch bars, update that old test to call `_build_intraday_short_trade_metrics_from_bars()` directly; the pure transform is still supported, but scoring no longer performs network fetches.

- [ ] **Step 6: Commit Task 2**

```bash
git add src/screening/strategy_scorer.py tests/screening/test_strategy_scorer.py
git commit -m "feat: read optional scoring features from snapshots"
```

---

### Task 3: Add Optional Feature Data Quality to Auto Report

**Files:**
- Modify: `src/main.py`
- Create: `tests/test_main_auto_feature_quality.py`

**Interfaces:**
- Consumes: `OptionalFeatureStore.build_quality_summary(trade_date, tickers)`
- Produces: `_build_auto_screening_payload(..., optional_feature_quality: dict | None = None) -> dict`
- Produces: payload key `data_quality.optional_features`

- [ ] **Step 1: Write failing payload test**

Create `tests/test_main_auto_feature_quality.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

import src.main as main_module


def test_build_auto_screening_payload_includes_optional_feature_quality(monkeypatch):
    monkeypatch.setattr(main_module, "_compute_model_version", lambda: "test-sha")
    market_state = SimpleNamespace(model_dump=lambda: {"regime": "mixed"})
    fused = [SimpleNamespace(score_b=0.4)]
    optional_feature_quality = {
        "optional_features": {
            "intraday_short_trade_metrics": {
                "coverage": 0.5,
                "source": "snapshot",
                "trade_date": "20260708",
                "stale": False,
                "provider_failures": 1,
                "missing_tickers": 1,
            }
        }
    }

    payload = main_module._build_auto_screening_payload(
        trade_date="20260708",
        top_n=10,
        market_state=market_state,
        candidates=[object(), object()],
        fused=fused,
        top_results_serializable=[],
        sector_warnings=[],
        consecutive_highlight=0,
        decay_summary={},
        industry_rotation_payload=[],
        batch_fetcher_use_batch=True,
        batch_fetcher_stats={"batch_calls": 1},
        optional_feature_quality=optional_feature_quality,
    )

    assert payload["data_quality"]["optional_features"]["intraday_short_trade_metrics"]["coverage"] == 0.5
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/test_main_auto_feature_quality.py::test_build_auto_screening_payload_includes_optional_feature_quality -q
```

Expected: FAIL with unexpected keyword argument `optional_feature_quality`.

- [ ] **Step 3: Modify payload builder**

In `src/main.py`, change `_build_auto_screening_payload()` signature:

```python
def _build_auto_screening_payload(
    *,
    trade_date: str,
    top_n: int,
    market_state,
    candidates,
    fused,
    top_results_serializable: list[dict],
    sector_warnings: list,
    consecutive_highlight: int,
    decay_summary: dict,
    industry_rotation_payload: list[dict],
    batch_fetcher_use_batch: bool,
    batch_fetcher_stats: dict,
    optional_feature_quality: dict | None = None,
) -> dict:
```

At the start of the function body, before `return`, add:

```python
    data_quality = dict(optional_feature_quality or {})
```

In the returned dict, add:

```python
        "data_quality": data_quality,
```

- [ ] **Step 4: Wire store into `compute_auto_screening_results()`**

In `src/main.py`, import locally inside `compute_auto_screening_results()` before Step 2:

```python
    from src.screening.optional_feature_store import OptionalFeatureStore

    optional_feature_store = OptionalFeatureStore()
```

Change:

```python
    scored = score_batch(candidates, trade_date)
```

to:

```python
    scored = score_batch(candidates, trade_date, feature_store=optional_feature_store)
    optional_feature_quality = optional_feature_store.build_quality_summary(
        trade_date,
        [candidate.ticker for candidate in candidates],
    )
```

Pass `optional_feature_quality=optional_feature_quality` into both `_build_auto_screening_payload()` calls in `compute_auto_screening_results()`.

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/test_main_auto_feature_quality.py -q
```

Expected: PASS.

- [ ] **Step 6: Run main auto payload regression tests**

Run:

```bash
uv run pytest tests/test_main_auto_cache_refresh.py tests/test_main_auto_feature_quality.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 3**

```bash
git add src/main.py tests/test_main_auto_feature_quality.py
git commit -m "feat: report optional feature data quality"
```

---

### Task 4: Add Bounded Optional Feature Refresh Entry Point

**Files:**
- Create: `src/screening/optional_feature_refresh.py`
- Create: `tests/screening/test_optional_feature_refresh.py`
- Modify: `src/main.py`

**Interfaces:**
- Produces: `refresh_optional_features(trade_date: str, tickers: list[str], *, timeout_seconds: float = 20.0, cache_dir: Path | str = "data/feature_cache") -> dict[str, Any]`
- Produces: manifest file `feature_manifest_YYYYMMDD.json`
- Consumes: provider functions only inside refresh code, never inside scoring.

- [ ] **Step 1: Write failing test for bounded refresh manifest**

Create `tests/screening/test_optional_feature_refresh.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from src.screening.optional_feature_refresh import refresh_optional_features


def test_refresh_optional_features_writes_manifest_without_blocking_on_disabled_providers(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUTO_OPTIONAL_FEATURE_REFRESH", "0")

    summary = refresh_optional_features(
        "20260708",
        ["000001", "000002"],
        timeout_seconds=0.1,
        cache_dir=tmp_path,
    )

    manifest_path = tmp_path / "feature_manifest_20260708.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert summary["status"] == "skipped"
    assert manifest["trade_date"] == "20260708"
    assert manifest["candidate_count"] == 2
    assert manifest["features"]["intraday_short_trade_metrics"]["provider_failures"] == 0
    assert manifest["features"]["daily_fund_flow_metrics"]["provider_failures"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/screening/test_optional_feature_refresh.py::test_refresh_optional_features_writes_manifest_without_blocking_on_disabled_providers -q
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement minimal refresh entry point**

Create `src/screening/optional_feature_refresh.py`:

```python
"""Best-effort optional feature refresh for auto screening.

The first implementation writes a manifest and establishes the refresh boundary.
Provider-specific snapshot writers can be added behind this boundary without
changing score_batch().
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


def _refresh_enabled() -> bool:
    raw = os.environ.get("AUTO_OPTIONAL_FEATURE_REFRESH", "1")
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def refresh_optional_features(
    trade_date: str,
    tickers: list[str],
    *,
    timeout_seconds: float = 20.0,
    cache_dir: Path | str = "data/feature_cache",
) -> dict[str, Any]:
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)
    unique_tickers = sorted({str(ticker).zfill(6) for ticker in tickers})
    enabled = _refresh_enabled()
    status = "ok" if enabled else "skipped"
    manifest = {
        "trade_date": str(trade_date),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "candidate_count": len(unique_tickers),
        "timeout_seconds": float(timeout_seconds),
        "status": status,
        "features": {
            "intraday_short_trade_metrics": {
                "provider_failures": 0,
                "rows_written": 0,
                "source": "not_refreshed" if not enabled else "pending_provider_implementation",
            },
            "daily_fund_flow_metrics": {
                "provider_failures": 0,
                "rows_written": 0,
                "source": "not_refreshed" if not enabled else "pending_provider_implementation",
            },
        },
    }
    manifest_path = cache_path / f"feature_manifest_{trade_date}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "status": status,
        "trade_date": str(trade_date),
        "candidate_count": len(unique_tickers),
        "manifest_path": str(manifest_path),
    }
```

- [ ] **Step 4: Run refresh test**

Run:

```bash
uv run pytest tests/screening/test_optional_feature_refresh.py -q
```

Expected: PASS.

- [ ] **Step 5: Wire refresh before scoring in `compute_auto_screening_results()`**

In `src/main.py`, after candidate pool is built and before Step 2, add:

```python
    from src.screening.optional_feature_refresh import refresh_optional_features
    from src.screening.optional_feature_store import OptionalFeatureStore

    refresh_optional_features(
        trade_date,
        [candidate.ticker for candidate in candidates],
        timeout_seconds=float(os.environ.get("AUTO_OPTIONAL_FEATURE_REFRESH_TIMEOUT_SECONDS", "20")),
    )
    optional_feature_store = OptionalFeatureStore()
```

If Task 3 already added the `OptionalFeatureStore` import and construction, merge these imports so each symbol is imported once.

- [ ] **Step 6: Run auto-related tests**

Run:

```bash
uv run pytest tests/screening/test_optional_feature_refresh.py tests/test_main_auto_feature_quality.py tests/test_main_auto_cache_refresh.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 4**

```bash
git add src/screening/optional_feature_refresh.py tests/screening/test_optional_feature_refresh.py src/main.py
git commit -m "feat: add bounded optional feature refresh boundary"
```

---

### Task 5: Full Verification and Network-I/O Guard

**Files:**
- Modify: `tests/screening/test_strategy_scorer.py`
- No production file changes unless this task exposes a missed call path.

**Interfaces:**
- Verifies: Step 2 helpers do not call `get_intraday_bars()` or `get_money_flow()`.

- [ ] **Step 1: Add integration-style guard around `score_batch()`**

Add this test to `tests/screening/test_strategy_scorer.py`. Reuse existing local helper factories in the file if equivalent helpers already exist; otherwise include these minimal objects:

```python
def test_score_batch_does_not_call_live_intraday_or_money_flow(monkeypatch):
    candidate = CandidateStock(
        ticker="000001",
        name="平安银行",
        industry_sw="银行",
        market_cap=100.0,
        avg_volume_20d=100.0,
    )

    trend_signal = StrategySignal(
        direction=1,
        confidence=80.0,
        completeness=1.0,
        sub_factors={"momentum": {"metrics": {}}},
    )
    neutral_signal = StrategySignal(direction=0, confidence=0.0, completeness=0.0, sub_factors={})

    monkeypatch.setattr(strategy_scorer_module, "_build_industry_pe_medians", lambda trade_date: {})
    monkeypatch.setattr(strategy_scorer_module, "_initialize_score_batch_results", lambda candidates: {candidate.ticker: {"trend": trend_signal}})
    monkeypatch.setattr(strategy_scorer_module, "_prepare_heavy_score_candidates", lambda candidates, trade_date, results: candidates)
    monkeypatch.setattr(strategy_scorer_module, "score_fundamental_strategy", lambda *_args, **_kwargs: neutral_signal)
    monkeypatch.setattr(strategy_scorer_module, "score_event_sentiment_strategy", lambda *_args, **_kwargs: neutral_signal)
    monkeypatch.setattr(strategy_scorer_module, "_populate_dragon_tiger_bonus_metrics", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(strategy_scorer_module, "get_intraday_bars", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("intraday network forbidden")))
    monkeypatch.setattr(strategy_scorer_module, "get_money_flow", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("money flow network forbidden")))

    class _Store:
        def load_intraday_metrics(self, trade_date, tickers):
            return {"000001": {"flow_60": 0.1, "flow_60_source": "snapshot"}}

        def load_fund_flow_metrics(self, trade_date, tickers):
            return {}

    result = strategy_scorer_module.score_batch([candidate], "20260708", feature_store=_Store())

    assert result["000001"]["trend"].sub_factors["momentum"]["metrics"]["flow_60"] == 0.1
```

- [ ] **Step 2: Run guard test**

Run:

```bash
uv run pytest tests/screening/test_strategy_scorer.py::test_score_batch_does_not_call_live_intraday_or_money_flow -q
```

Expected: PASS. If it fails with `AssertionError("intraday network forbidden")` or `AssertionError("money flow network forbidden")`, fix the remaining hot-path call before continuing.

- [ ] **Step 3: Run focused suites**

Run:

```bash
uv run pytest tests/screening/test_optional_feature_store.py tests/screening/test_optional_feature_refresh.py tests/screening/test_strategy_scorer.py tests/test_main_auto_feature_quality.py tests/test_main_auto_cache_refresh.py -q
```

Expected: PASS.

- [ ] **Step 4: Run real auto smoke with refresh disabled**

Run:

```bash
AUTO_OPTIONAL_FEATURE_REFRESH=0 uv run python src/main.py --auto
```

Expected:

- Process exits with code 0.
- Console reaches Top 10 recommendation output.
- Step 2 does not log `get_intraday_bars` or `get_money_flow` provider warnings.
- `data/reports/auto_screening_YYYYMMDD.json` includes `data_quality.optional_features`.

- [ ] **Step 5: Commit verification test or final fixes**

If Step 1 added the only remaining changes:

```bash
git add tests/screening/test_strategy_scorer.py
git commit -m "test: guard auto scoring against live optional providers"
```

If Step 2 exposed production fixes, include those exact files in the same commit with the same message.

---

## Self-Review

- Spec coverage: The plan covers local snapshots, scoring zero network I/O, report data quality, bounded refresh boundary, missing snapshot behavior, and provider-layer isolation.
- Placeholder scan: No unfinished marker or vague task remains.
- Type consistency: `OptionalFeatureStore`, `load_intraday_metrics`, `load_fund_flow_metrics`, `build_quality_summary`, and `refresh_optional_features` signatures are consistent across tasks.
- Scope control: Provider-specific snapshot population is deliberately deferred behind `optional_feature_refresh.py`; this keeps Phase 1 focused on the architectural boundary and scoring reliability.
