# Auto Scoring Feature Store Zero Network I/O Design

**Date:** 2026-07-09
**Status:** Ready for owner review

## Goal

Make `score_batch()` a deterministic, local-only scoring stage. All public data acquisition must happen before scoring in a bounded refresh layer that writes local Feature Store snapshots. Scoring only consumes those snapshots and local caches. It never calls AKShare, Tushare, Eastmoney, or any other public provider directly or indirectly.

The immediate production objective is to stop the `--auto` Step 2 failure mode where hundreds of concurrent scoring candidates can trigger flaky provider calls, proxy leakage, endpoint throttling, or remote disconnects.

## First Principles

1. Scoring is computation, not acquisition. Given the same candidate pool, trade date, and feature snapshot, `score_batch()` should produce the same signals without depending on network state.
2. Public providers are unreliable inputs. Their failures should affect data quality metadata and snapshot coverage, not the control flow of scoring.
3. Missing data is a first-class state. If a snapshot family is absent, scoring degrades to empty or incomplete sub-factors instead of trying a live fallback.
4. The hot path must be auditable. A test should be able to monkeypatch every provider function to raise and still run `score_batch()` successfully.
5. Refresh and scoring need different failure semantics. Refresh can retry, time out, skip, and record failures. Scoring should be fast, bounded, and local.

## Current Network-Capable Scoring Inputs

The previous optional feature work removed direct score-time calls for intraday bars and daily fund-flow proxy reads, but `score_batch()` still has other network-capable paths:

- Price history: `_load_price_frame()` calls `src.tools.api.get_prices()`, which may hit providers on cache miss.
- Fundamental metrics: `score_fundamental_strategy()` calls `get_financial_metrics()`.
- Event sentiment: `score_event_sentiment_strategy()` calls `get_company_news()` and `get_insider_trades()`.
- Industry PE medians: `_build_industry_pe_medians()` calls `get_daily_basic_batch()`, `get_all_stock_basic()`, and `get_sw_industry_classification()`.
- Dragon tiger bonus: `_build_dragon_tiger_bonus_map()` calls `get_lhb_detail()` and `get_lhb_institutional_stats()`.
- Optional short-trade metrics: existing snapshot reads cover intraday and daily fund-flow metrics, but the refresh implementation is still a manifest-only stub.

The root cause is not one provider endpoint. The root cause is an unclear data boundary: scoring functions can still decide to fetch public data when local inputs are missing.

## Design Decision

Extend the existing optional feature snapshot idea into a full `ScoringFeatureStore`.

The store is the only data dependency passed into `score_batch()`. It exposes local read methods for every scoring input family and hides where each local snapshot came from. Provider calls are only allowed in refresh code that writes store snapshots.

This is intentionally an adapter-first design. It does not require rewriting all factor math. Existing trend, mean-reversion, fundamental, and event scoring logic should be preserved, but their orchestrators must accept already-loaded local inputs.

## Feature Families

The store should support these families:

1. `price_history`
   - Consumer: trend and mean-reversion scoring.
   - Initial source: existing `data/price_cache/{ticker}.csv`.
   - Contract: return a normalized `DataFrame` ending at or before `trade_date`; never call `get_prices()`.

2. `financial_metrics`
   - Consumer: fundamental scoring.
   - Initial source: local financial snapshots under `data/snapshots/{ticker}/{date}/financials.json` where available, plus future Feature Store CSV or JSONL snapshots.
   - Contract: return `list[FinancialMetrics]`; empty list means incomplete fundamental signal.

3. `event_inputs`
   - Consumer: event sentiment scoring.
   - Initial source: future Feature Store snapshots for company news and insider trades.
   - Contract: return `(list[CompanyNews], list[InsiderTrade])`; empty lists mean incomplete event signal.

4. `industry_pe_medians`
   - Consumer: fundamental industry PE sub-factor.
   - Initial source: precomputed snapshot written by refresh from daily basic, stock basic, and SW industry classification.
   - Contract: return `dict[industry_name, median_pe]`; empty dict disables only the industry PE sub-factor.

5. `dragon_tiger_bonus`
   - Consumer: trend momentum enrichment.
   - Initial source: existing `data/lhb_cache/YYYYMMDD.csv` if present, plus future refresh snapshots.
   - Contract: return `dict[ticker, bonus]`; empty dict means no bonus.

6. `intraday_short_trade_metrics`
   - Consumer: trend momentum enrichment.
   - Initial source: existing `data/feature_cache/intraday_short_trade_metrics_YYYYMMDD.csv`.
   - Contract: return per-ticker optional metrics.

7. `daily_fund_flow_metrics`
   - Consumer: fallback flow proxy for short-trade metrics.
   - Initial source: existing `data/fund_flow_cache/{ticker}.csv` and `data/feature_cache/daily_fund_flow_metrics_YYYYMMDD.csv`.
   - Contract: return normalized per-ticker flow metrics.

## Public Interfaces

Add or evolve a local read object with methods shaped for scoring:

```python
class ScoringFeatureStore:
    def load_price_frame(self, ticker: str, trade_date: str, lookback_days: int = 400) -> pd.DataFrame: ...
    def load_financial_metrics(self, ticker: str, trade_date: str) -> list[FinancialMetrics]: ...
    def load_event_inputs(self, ticker: str, trade_date: str) -> tuple[list[CompanyNews], list[InsiderTrade]]: ...
    def load_industry_pe_medians(self, trade_date: str) -> dict[str, float]: ...
    def load_dragon_tiger_bonus_map(self, tickers: list[str], trade_date: str) -> dict[str, float]: ...
    def load_intraday_metrics(self, trade_date: str, tickers: list[str]) -> dict[str, dict[str, Any]]: ...
    def load_fund_flow_metrics(self, trade_date: str, tickers: list[str]) -> dict[str, dict[str, Any]]: ...
    def build_quality_summary(self, trade_date: str, tickers: list[str]) -> dict[str, Any]: ...
```

`OptionalFeatureStore` can either be renamed or wrapped by `ScoringFeatureStore`. The low-risk path is to add `ScoringFeatureStore` and keep `OptionalFeatureStore` as a compatibility alias or delegate for current tests.

## Scoring Changes

`score_batch(candidates, trade_date, feature_store=None)` should construct a default `ScoringFeatureStore` when no store is supplied.

Required changes:

- `_build_industry_pe_medians(trade_date)` becomes a store read.
- `_compute_light_signals()` loads prices from the store.
- `score_candidate()` loads prices, financial metrics, event inputs, and enrichment maps through the store.
- Fundamental orchestration splits into:
  - pure input scorer: score from `list[FinancialMetrics]`
  - provider-backed wrapper retained outside the `score_batch()` path if still needed elsewhere
- Event sentiment orchestration splits into:
  - pure input scorer: score from `news_items` and `trades`
  - provider-backed wrapper retained outside the `score_batch()` path if still needed elsewhere
- `_build_dragon_tiger_bonus_map()` becomes a store read in score-time code.
- Provider aliases in `strategy_scorer.py` should not be needed for scoring once tests move to provider-forbidden guards.

The behavior of factor math should not change. Only data acquisition boundaries change.

## Refresh Layer

Add or evolve `refresh_scoring_features(trade_date, tickers, timeout_seconds=...)`.

This is the only `--auto` boundary that may perform public network I/O after the candidate pool is built. It should:

- write a manifest for every attempted refresh run;
- materialize snapshots for all supported feature families when data is available;
- reuse existing local caches where they already contain the needed data;
- record provider failures, rows written, missing tickers, and source labels;
- return quickly under a hard budget;
- never make `score_batch()` depend on refresh success.

Initial implementation can prioritize hard isolation over complete provider coverage:

- Use existing `data/price_cache` for price history.
- Use existing `data/fund_flow_cache` for fund-flow snapshots where possible.
- Use existing `data/lhb_cache` for dragon tiger snapshots where possible.
- Read existing `data/snapshots/{ticker}/{date}/financials.json` for financial metrics where possible.
- Write manifest entries for event inputs and industry PE even when snapshots are missing or not yet refreshed.

This preserves the key invariant immediately: score-time provider calls are forbidden.

## Data Flow

1. `uv run python src/main.py --auto`
2. Layer A builds or loads the candidate pool as today.
3. `refresh_scoring_features(trade_date, candidate_tickers)` runs with a bounded budget.
4. Refresh writes local snapshots and `feature_manifest_YYYYMMDD.json`.
5. `score_batch(candidates, trade_date, feature_store=ScoringFeatureStore(...))` runs.
6. Scoring reads only local files through the store.
7. Missing families produce incomplete sub-factors and quality metadata.
8. The auto report includes `data_quality.scoring_features`.

## Data Quality Contract

The report should disclose scoring feature coverage by family. Keep `optional_features` backward-compatible during migration, but add the broader `scoring_features` block.

Example:

```json
{
  "data_quality": {
    "scoring_features": {
      "price_history": {
        "coverage": 0.97,
        "source": "local_price_cache",
        "trade_date": "20260708",
        "stale": false,
        "missing_tickers": 9,
        "provider_failures": 0
      },
      "financial_metrics": {
        "coverage": 0.41,
        "source": "snapshot",
        "trade_date": "20260708",
        "stale": false,
        "missing_tickers": 177,
        "provider_failures": 0
      },
      "event_inputs": {
        "coverage": 0.0,
        "source": "missing",
        "trade_date": "20260708",
        "stale": false,
        "missing_tickers": 300,
        "provider_failures": 0
      }
    }
  }
}
```

Coverage should be computed against the candidate set actually submitted to scoring. Empty feature families must be visible rather than silently neutral.

## Error Handling

- Store reads catch malformed files, missing files, parse failures, and bad schema. They return empty data and mark quality degraded.
- Stale snapshots are rejected by default unless explicitly allowed through store configuration.
- Future-dated snapshots are never used as stale fallbacks.
- Refresh failures never abort scoring.
- Score-time missing data never triggers a provider fallback.
- Provider proxy isolation and endpoint breakers remain in provider and refresh code only.

## Tests

Add tests that prove the boundary:

- `score_batch()` completes when all known provider functions are monkeypatched to raise.
- Price frame loading uses `ScoringFeatureStore.load_price_frame()` and does not call `get_prices()`.
- Fundamental scoring in `score_batch()` uses local metrics and does not call `get_financial_metrics()`.
- Event sentiment scoring in `score_batch()` uses local event inputs and does not call `get_company_news()` or `get_insider_trades()`.
- Industry PE medians come from the store and do not call Tushare batch/basic/classification functions.
- Dragon tiger enrichment comes from the store and does not call AKShare LHB functions.
- Missing snapshots produce incomplete signals and quality metadata, not exceptions.
- Stale snapshots are rejected by default and accepted only when explicitly configured.
- `--auto` report includes `data_quality.scoring_features`.

Regression tests for the existing optional intraday/fund-flow snapshots should remain.

## Rollout

Phase 1: hard isolation.

- Add `ScoringFeatureStore`.
- Route every `score_batch()` data read through it.
- Split provider-backed fundamental and event wrappers from pure input scorers.
- Add provider-forbidden tests.
- Preserve existing ranking math.

Phase 2: snapshot coverage.

- Expand refresh to write or assemble price, financial, event, industry PE, dragon tiger, intraday, and fund-flow snapshots.
- Normalize manifests and quality reporting.
- Keep refresh best-effort and bounded.

Phase 3: operational polish.

- Add commands or flags to run refresh separately from scoring.
- Add coverage thresholds for selected high-value feature families if needed.
- Add provider-specific refresh diagnostics without touching score-time code.

## Non-Goals

- No change to factor weights.
- No change to `--daily-action` setup logic.
- No change to paper trading state.
- No live provider fallback inside `score_batch()`.
- No requirement to achieve full feature coverage before hard isolation is merged.

## Acceptance Criteria

- `score_batch()` has zero public network I/O by construction.
- A provider-forbidden test guards all known score-time provider functions.
- `uv run python src/main.py --auto` Step 2 no longer logs AKShare, Tushare, Eastmoney, or provider fetch messages from scoring.
- Missing feature snapshots degrade strategy completeness and are reported in `data_quality.scoring_features`.
- Existing optional feature quality output remains compatible during migration.
