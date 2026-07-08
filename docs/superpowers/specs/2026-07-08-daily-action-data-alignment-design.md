# Daily Action Data Alignment Design

**Date:** 2026-07-08
**Status:** Approved by owner

## Goal

Improve the daily stock-selection flow for the owner-approved objective: buy at the next open and maximize execution-adjusted setup returns over each setup's natural horizon, currently BTST Breakout T+10 and Oversold Bounce T+5.

## Current Problems

The two-command workflow has four data-alignment defects that cap realized returns before strategy tuning matters:

1. `--daily-action` claims full-market scanning but only scans ticker CSVs already present in `data/price_cache`. On 2026-07-08, the latest candidate pool had 300 tickers, but `price_cache` covered only 202 of them and missed 98 current candidates.
2. BTST's industry-strength gate is bypassed in runtime. `generate_daily_action` sets `industry_day_pct = max(pct, 3.0)` for limit-up stocks, so every limit-up stock automatically passes the "industry up > 2%" condition.
3. The Phase 0 research path uses the same fake industry assumption. `scripts/setup_research.py` sets `industry_pct_by_date = {d: 3.0}`, so the known BTST distribution is not validated with real industry resonance.
4. `scripts/backfill_industry_index.py` has a fixed `_END_DATE = "20260707"`, which lets the SW industry index cache lag current trade dates.

## Scope

This design fixes data and signal-contract defects. It does not introduce new setups, change Kelly math, or change the approved holding horizons.

## Architecture

### Cache Target Universe

`--auto` should refresh daily-action caches for the tickers that can actually be selected by the next `--daily-action` run:

- Existing `data/price_cache` tickers remain eligible.
- Latest `candidate_pool_<trade_date>.json` and `candidate_pool_<trade_date>_top300.json` tickers are added.
- Shadow candidates may be included behind an environment flag, default off, to control Tushare volume.

Existing tickers get one appended or replaced daily OHLCV row from the batch daily price frame. New tickers get a bounded history backfill, default 90 calendar days or enough rows to support the current setup lookbacks and exits. If the full backfill fails, the ticker is excluded from `--daily-action` and surfaced in the cache-refresh summary.

Fund-flow refresh uses the same target ticker set. The refresh summary must distinguish existing-updated, new-backfilled, missing, and failed tickers.

### Industry Data

SW L1 industry index cache must be trade-date aware:

- Replace the hardcoded industry backfill end date with a parameter or default to today.
- Add an incremental refresh path for the current `trade_date`.
- Treat stale industry index data as unavailable for that date.

`daily_action` should resolve ticker to SW L1 industry and look up the industry's actual one-day `pct_chg` for `trade_date`. BTST should receive that real value as `industry_day_pct`.

If industry mapping or industry pct is missing, BTST must not pass the industry gate by fabricated data. The system can still run Oversold Bounce, because it does not depend on `industry_day_pct`.

### Research Parity

Phase 0 setup research must use the same real industry-day pct source as runtime. That removes the fake `{d: 3.0}` assumption and makes future BTST known distributions comparable to daily-action signals.

Until BTST distributions are recomputed under the real industry gate, the runtime output should disclose that the BTST prior was calibrated under the old industry proxy. This avoids silently mixing a stricter live signal with a looser historical prior.

## Data Flow

1. `uv run python src/main.py --auto`
2. Build candidate pool and report as today.
3. Resolve daily-action refresh ticker set from current caches plus candidate pool.
4. Refresh price history and fund-flow cache for that set.
5. Refresh SW industry index data through `trade_date`.
6. Persist refresh summary into `auto_screening_<trade_date>.json`.
7. `uv run python src/main.py --daily-action`
8. Resolve signal date from price cache, block stale or missed-entry windows as today.
9. Scan the refreshed ticker set.
10. For BTST, inject real `industry_day_pct`; for Oversold, leave unchanged.
11. Rank by expected return, trigger strength, convexity, and portfolio cap as today.

## Error Handling

- Cache refresh remains best-effort for `--auto`, but failures are explicit in the report payload.
- `--daily-action` blocks new BUY signals when price cache is behind the latest `--auto` report, as today.
- `--daily-action` should also report when industry data is stale for BTST gating.
- New ticker history backfill must be bounded and isolated, so one failing ticker does not abort the full refresh.

## Testing

Add focused tests for:

- Candidate-pool tickers are included in the daily-action cache refresh target universe.
- A new ticker with enough fetched history gets a new price cache file.
- A new ticker without enough history is reported as missing and not scanned.
- Fund-flow refresh uses the same target ticker list as price refresh.
- Industry index backfill defaults to the requested trade date rather than a hardcoded date.
- `daily_action` passes real industry pct into BTST and does not fabricate `3.0` for limit-up stocks.
- BTST misses when real industry pct is below 2%.
- Phase 0 research universe uses real industry pct mapping.

## Non-Goals

- No real-money order placement.
- No new setup families.
- No automatic update of `KNOWN_DISTRIBUTIONS` without a fresh Phase 0 report.
- No change to paper-trading journal semantics.
