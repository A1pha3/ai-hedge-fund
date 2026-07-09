# Auto Feature Store Zero Network I/O Design

**Date:** 2026-07-09
**Status:** Ready for owner review

## Goal

Make `uv run python src/main.py --auto` deterministic and operationally stable by removing live third-party network calls from the scoring hot path. The scoring stage should consume local feature snapshots, compute rankings, and write the report. Online data acquisition remains supported, but it runs in a bounded refresh layer with explicit quality reporting.

## Current Problems

`--auto` Step 2 currently computes trend and short-trade features while reaching out to optional online providers:

1. `get_intraday_bars()` calls AKShare's Eastmoney minute-bar endpoint on `push2his.eastmoney.com`.
2. `_load_daily_flow_proxy_ratio()` calls `get_money_flow()`, which also depends on `push2his.eastmoney.com`.
3. These optional calls are executed while scoring hundreds of candidates, so one flaky endpoint can be multiplied across the candidate pool.
4. Runtime warnings are currently correct but too late: the main scoring path has already spent time waiting on a provider that is not required for the core ranking.

Recent debugging confirmed two separate failure modes:

- macOS system proxy settings can leak into `requests` unless `NO_PROXY=*` is set during proxy-disabled calls.
- After proxy bypass, Eastmoney can still close direct connections before returning a response (`RemoteDisconnected`). That is an external endpoint condition, not a local code bug.

## First Principles

Daily scoring should obey four invariants:

1. **Scoring is pure computation.** Given the same candidate pool, prices, fundamentals, and feature snapshot, it should produce the same ranking without depending on live provider state.
2. **Online providers are data preparation, not decision logic.** Provider failures should change data-quality metadata, not the control flow of scoring.
3. **Optional features are optional.** Missing minute-flow or fund-flow proxies should lower feature confidence, not block or stall the report.
4. **Every run should disclose data quality.** Coverage, staleness, provider failures, and fallback sources must be visible in the report.

## Recommended Architecture

Introduce a local feature snapshot layer between online data acquisition and scoring.

### Feature Refresh Layer

The refresh layer is responsible for best-effort online acquisition and snapshot writing. It may call AKShare, Tushare, or future providers, but it has a strict time budget and endpoint-level health tracking.

Initial feature families:

- `intraday_short_trade_metrics`: per ticker and trade date, containing `flow_60`, `close_support_30`, `persist_120`, source labels, and freshness metadata.
- `daily_fund_flow_metrics`: per ticker and trade date, containing main-flow ratio and any normalized fund-flow fields already used by scoring.

Suggested storage:

- `data/feature_cache/intraday_short_trade_metrics_YYYYMMDD.parquet`
- `data/feature_cache/daily_fund_flow_metrics_YYYYMMDD.parquet`
- `data/feature_cache/feature_manifest_YYYYMMDD.json`

If parquet dependencies are not already available in the runtime, use CSV for the first implementation and keep the API abstract so storage format is not part of the scorer contract.

### Feature Store Read Layer

Add a small read API used by scoring:

- `FeatureStore.load_intraday_metrics(trade_date, tickers) -> dict[ticker, metrics]`
- `FeatureStore.load_fund_flow_metrics(trade_date, tickers) -> dict[ticker, metrics]`
- `FeatureStore.load_manifest(trade_date) -> FeatureManifest`

This read layer must not perform network I/O. It only reads local files and returns missing-feature markers when a snapshot is absent or stale.

### Scoring Layer

`src/screening/strategy_scorer.py` should stop calling `get_intraday_bars()` and `get_money_flow()` directly during `score_batch()`.

Instead:

- `_build_intraday_short_trade_metrics()` reads precomputed metrics from the feature store.
- `_load_daily_flow_proxy_ratio()` reads precomputed fund-flow metrics from the feature store.
- Missing metrics are treated exactly as optional missing sub-factors.
- The trend signal records feature source and missing reason where possible.

The existing online AKShare wrappers can remain for refresh and tooling, but not for scoring hot-path use.

## Data Flow

1. `uv run python src/main.py --auto`
2. Build candidate pool as today.
3. Optional feature refresh runs with a hard budget, default 20 seconds.
4. Refresh writes local snapshots and a manifest. If refresh fails or times out, it preserves the last usable snapshot only if it is within a configured staleness window.
5. `score_batch()` receives or constructs a local `FeatureStore` for the selected `trade_date`.
6. Scoring consumes only candidate data, cached price/fundamental data, and feature snapshots.
7. The final `auto_screening_YYYYMMDD.json` includes `data_quality.optional_features`.

## Data Quality Contract

The report should expose enough detail to distinguish "feature genuinely absent" from "provider failed":

```json
{
  "data_quality": {
    "optional_features": {
      "intraday_short_trade_metrics": {
        "coverage": 0.84,
        "source": "snapshot",
        "trade_date": "20260708",
        "stale": false,
        "provider_failures": 2,
        "missing_tickers": 48
      },
      "daily_fund_flow_metrics": {
        "coverage": 0.91,
        "source": "snapshot",
        "trade_date": "20260708",
        "stale": false,
        "provider_failures": 0,
        "missing_tickers": 27
      }
    }
  }
}
```

Coverage should be computed against the candidate set actually submitted to scoring.

## Error Handling

- Feature refresh is best-effort and bounded. It must not prevent `--auto` from finishing.
- Scoring must not initiate provider calls when snapshots are missing. Missing snapshots produce missing optional features and data-quality warnings.
- Endpoint circuit breakers remain in the provider layer to protect refresh jobs.
- Existing proxy isolation remains in the provider layer because refresh still needs online calls.
- If a feature snapshot is stale beyond its configured window, scoring treats it as absent unless an explicit environment flag allows stale optional features.

## Rollout Plan

Phase 1 should be narrow and low-risk:

1. Add the feature store read API and manifest model.
2. Teach `score_batch()` to accept optional preloaded feature maps or a feature store.
3. Keep existing AKShare online code available, but put it behind the refresh path.
4. Default scoring to local-only mode.
5. Preserve current output when feature snapshots exist; degrade cleanly when they do not.

Phase 2 can move current refresh logic into an explicit `refresh_optional_features()` function called before scoring.

Phase 3 can optimize provider coverage and add alternative sources, but only behind the refresh layer.

## Testing

Add focused tests for:

- `score_batch()` does not call `get_intraday_bars()` or `get_money_flow()` when local feature store is enabled.
- Missing intraday snapshot results in missing optional metrics, not network calls.
- Missing fund-flow snapshot results in missing flow proxy, not retries or sleeps.
- Feature manifest coverage is written into the auto report.
- Stale snapshots are rejected by default.
- Provider refresh failures increment manifest failure counters without aborting the auto run.
- Existing AKShare proxy isolation and endpoint breaker tests remain in place for refresh/provider code.

## Non-Goals

- No change to core factor weights in this design.
- No new stock-selection setups.
- No replacement of AKShare or Tushare as provider libraries.
- No automatic recalibration of historical factor distributions.
- No change to `--daily-action` setup logic in this design.

## Acceptance Criteria

- A normal `--auto` scoring run can be executed with network disabled after required local snapshots already exist.
- With missing optional snapshots, `--auto` still finishes and reports reduced feature coverage.
- Step 2 no longer logs provider network warnings from `get_intraday_bars()` or `get_money_flow()`.
- Optional feature coverage and provider failure counts are visible in the JSON report.
