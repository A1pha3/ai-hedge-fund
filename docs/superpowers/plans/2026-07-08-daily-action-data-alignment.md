# Daily Action Data Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align `--auto` cache refresh, `--daily-action` scanning, and Phase 0 setup research so next-open BTST T+10 and Oversold T+5 signals use the same fresh, executable data universe.

**Architecture:** Add small cache-refresh helpers that resolve the daily-action ticker universe from current cache plus candidate-pool snapshots, backfill bounded history for new tickers, and use the same target list for fund-flow refresh. Add a reusable SW industry-index helper for real one-day industry pct lookup, then inject that real value into BTST runtime and Phase 0 research.

**Tech Stack:** Python 3.11, pandas, pytest, Tushare/AkShare wrappers already present in the repo.

## Global Constraints

- Preserve the approved objective: next-open entry and setup natural horizons, BTST T+10 and Oversold Bounce T+5.
- Do not add new setup families.
- Do not update `KNOWN_DISTRIBUTIONS` without a fresh Phase 0 report.
- `--auto` cache refresh remains best-effort and must not abort the main report.
- Do not modify unrelated data-cache files or paper-trading journal state.

---

### Task 1: Candidate-Pool Tickers Enter Daily-Action Cache Refresh

**Files:**
- Modify: `src/screening/offensive/cache_refresh.py`
- Modify: `tests/offensive/test_daily_action_cache_refresh.py`

**Interfaces:**
- Produces: `resolve_daily_action_refresh_tickers(trade_date: str, *, price_cache_dir: Path | str = _DEFAULT_PRICE_CACHE_DIR, snapshot_dir: Path | str = Path("data/snapshots"), include_shadow: bool = False) -> list[str]`
- Produces: `refresh_price_cache_from_daily_batch(..., target_tickers: list[str] | None = None, backfill_price_history_fn: Callable[[str, str, str], pd.DataFrame | None] | None = None, min_history_rows: int = 31) -> DailyActionCacheRefreshStats`
- Consumes: candidate-pool snapshot JSON shaped either as a list of candidate dicts or a shadow payload with `selected_candidates` and `shadow_candidates`.

- [ ] **Step 1: Write failing tests**

Add tests:

```python
def test_resolve_daily_action_refresh_tickers_includes_candidate_pool_new_tickers(tmp_path):
    from src.screening.offensive.cache_refresh import resolve_daily_action_refresh_tickers

    price_cache = tmp_path / "price_cache"
    snapshots = tmp_path / "snapshots"
    price_cache.mkdir()
    snapshots.mkdir()
    (price_cache / "000001.csv").write_text("date,close\n2026-07-08,10\n", encoding="utf-8")
    (snapshots / "candidate_pool_20260708.json").write_text(
        '[{"ticker":"000002"},{"ticker":"000003"}]', encoding="utf-8"
    )

    assert resolve_daily_action_refresh_tickers(
        "20260708", price_cache_dir=price_cache, snapshot_dir=snapshots
    ) == ["000001", "000002", "000003"]
```

```python
def test_refresh_price_cache_backfills_new_candidate_ticker(tmp_path):
    from src.screening.offensive.cache_refresh import refresh_price_cache_from_daily_batch

    price_cache = tmp_path / "price_cache"
    price_cache.mkdir()
    rows = [{"date": f"2026-06-{day:02d}", "close": 10.0, "open": 10.0, "high": 10.0, "low": 10.0, "pct_change": 0.0, "volume": 1000.0} for day in range(1, 32)]
    history = pd.DataFrame(rows)

    stats = refresh_price_cache_from_daily_batch(
        "20260708",
        price_cache_dir=price_cache,
        daily_prices_df=_daily_prices([{"ts_code": "000002.SZ", "close": 12.0}]),
        target_tickers=["000002"],
        backfill_price_history_fn=lambda ticker, start, end: history,
        min_history_rows=31,
    )

    assert (price_cache / "000002.csv").exists()
    assert stats.price_backfilled == 1
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/offensive/test_daily_action_cache_refresh.py::test_resolve_daily_action_refresh_tickers_includes_candidate_pool_new_tickers tests/offensive/test_daily_action_cache_refresh.py::test_refresh_price_cache_backfills_new_candidate_ticker -q`

Expected: both fail because the helper and new stats field do not exist.

- [ ] **Step 3: Implement minimal cache-refresh helpers**

Implement snapshot parsing, target union, optional history backfill for tickers without existing CSV, and stats fields `price_backfilled` and `price_insufficient_history`.

- [ ] **Step 4: Verify Task 1**

Run: `uv run pytest tests/offensive/test_daily_action_cache_refresh.py -q`

Expected: all cache-refresh tests pass.

### Task 2: Industry Index Cache Uses Requested Trade Date

**Files:**
- Modify: `scripts/backfill_industry_index.py`
- Modify: `tests/offensive/test_daily_action_cache_refresh.py`

**Interfaces:**
- Produces: `backfill(end_date: str | None = None) -> dict[str, int]`
- Produces: `_resolve_end_date(end_date: str | None = None) -> str`

- [ ] **Step 1: Write failing test**

```python
def test_industry_index_backfill_accepts_requested_end_date(monkeypatch, tmp_path):
    import scripts.backfill_industry_index as mod

    calls = []
    monkeypatch.setattr(mod, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(mod, "_fetch_industry_codes", lambda: [("801010.SI", "农林牧渔")])
    monkeypatch.setattr(
        mod,
        "_fetch_industry_daily",
        lambda index_code, end_date=None: calls.append((index_code, end_date)) or pd.DataFrame([{"trade_date": "20260708", "pct_chg": 1.0}]),
    )

    mod.backfill(end_date="20260708")

    assert calls == [("801010.SI", "20260708")]
```

- [ ] **Step 2: Run failing test**

Run: `uv run pytest tests/offensive/test_daily_action_cache_refresh.py::test_industry_index_backfill_accepts_requested_end_date -q`

Expected: fail because `backfill` and `_fetch_industry_daily` do not accept `end_date`.

- [ ] **Step 3: Implement date parameter**

Make `_fetch_industry_daily(index_code: str, end_date: str | None = None)` and `backfill(end_date: str | None = None)` use a resolved end date instead of `_END_DATE`.

- [ ] **Step 4: Verify Task 2**

Run: `uv run pytest tests/offensive/test_daily_action_cache_refresh.py::test_industry_index_backfill_accepts_requested_end_date -q`

Expected: pass.

### Task 3: Runtime BTST Uses Real Industry Day Pct

**Files:**
- Modify: `src/screening/offensive/daily_action.py`
- Modify: `tests/offensive/test_daily_action.py`

**Interfaces:**
- Produces: `_load_industry_day_pct_by_ticker(trade_date: str, tickers: list[str]) -> dict[str, float]`
- Produces: `_btst_prior_disclaimer() -> str`

- [ ] **Step 1: Write failing tests**

```python
def test_generate_daily_action_does_not_fabricate_industry_pct_for_limit_up(tmp_path, monkeypatch):
    import pandas as pd
    from src.screening.offensive import daily_action as da
    from src.screening.offensive.paper_tracker import PaperTracker
    from src.screening.offensive.setups.base import DetectionResult
    from src.screening.offensive.statistics import Distribution

    captured = {}

    class IndustryAwareSetup:
        def detect(self, ticker, trade_date, context):
            captured[ticker] = context.get("industry_day_pct")
            return DetectionResult(hit=False, ticker=ticker, trade_date=trade_date, trigger_strength=0.0, invalidation_condition="")

    dist = Distribution(100, 0.6, 0.12, -0.06, 2.0, 0.05, 0.02, 0.08, 0.1)
    prices = pd.DataFrame([{"date": pd.Timestamp("2026-07-08"), "open": 10.0, "high": 11.0, "low": 9.9, "close": 11.0, "pct_change": 10.0, "volume": 1000.0}])
    monkeypatch.setattr(da, "_VERIFIED_SETUPS", [("btst_breakout", IndustryAwareSetup, 10)])
    monkeypatch.setattr(da, "get_known_distribution", lambda name, horizon: dist)
    monkeypatch.setattr(da, "_load_industry_day_pct_by_ticker", lambda trade_date, tickers: {"000001": 1.0})

    report_path = tmp_path / "auto_screening_20260708.json"
    report_path.write_text('{"date":"20260708","recommendations":[{"ticker":"000001"}],"market_state":{"regime_gate_level":"normal"}}', encoding="utf-8")

    da.generate_daily_action(report_path=report_path, tracker=PaperTracker(journal_dir=tmp_path), scan_mode="report", price_loader=lambda ticker, date: prices)

    assert captured["000001"] == 1.0
```

- [ ] **Step 2: Run failing test**

Run: `uv run pytest tests/offensive/test_daily_action.py::test_generate_daily_action_does_not_fabricate_industry_pct_for_limit_up -q`

Expected: fail because runtime currently passes `3.0` for limit-up stocks.

- [ ] **Step 3: Implement real industry pct injection**

Load industry pct once per run, pass `industry_pct_by_ticker.get(ticker, 0.0)` into setup context, and keep Oversold unchanged.

- [ ] **Step 4: Verify Task 3**

Run: `uv run pytest tests/offensive/test_daily_action.py -q`

Expected: all daily-action tests pass.

### Task 4: Phase 0 Research Uses Real Industry Day Pct

**Files:**
- Modify: `scripts/setup_research.py`
- Modify: `tests/offensive/test_setup_research_cli.py`

**Interfaces:**
- Produces: `load_industry_day_pct(cache_dir: Path = _INDUSTRY_INDEX_CACHE_DIR) -> dict[tuple[str, str], float]`
- Consumes: `build_ticker_to_industry(tickers: list[str]) -> dict[str, str]`

- [ ] **Step 1: Write failing test**

```python
def test_load_backtest_universe_uses_real_industry_day_pct(tmp_path, monkeypatch):
    from scripts import setup_research as sr

    price_cache = tmp_path / "price_cache"
    fund_cache = tmp_path / "fund_flow_cache"
    reports = tmp_path / "reports"
    price_cache.mkdir()
    fund_cache.mkdir()
    reports.mkdir()
    (price_cache / "000001.csv").write_text("date,close,open,high,low,pct_change,volume\n2026-07-08,10,10,10,10,0,100\n" * 60, encoding="utf-8")
    regime_path = reports / "regime_history.json"
    regime_path.write_text('{"20260708":"normal"}', encoding="utf-8")
    monkeypatch.setattr(sr, "load_industry_day_pct", lambda: {("银行", "20260708"): 1.2})
    monkeypatch.setattr(sr, "build_ticker_to_industry", lambda tickers: {"000001": "银行"})

    universe = sr.load_backtest_universe(
        start_date="20260708",
        end_date="20260708",
        price_cache_dir=price_cache,
        fund_flow_cache_dir=fund_cache,
        regime_history_path=regime_path,
    )

    assert universe["industry_pct_by_date"]["20260708"] == 1.2
```

- [ ] **Step 2: Run failing test**

Run: `uv run pytest tests/offensive/test_setup_research_cli.py::test_load_backtest_universe_uses_real_industry_day_pct -q`

Expected: fail because `industry_pct_by_date` is currently hardcoded to `3.0`.

- [ ] **Step 3: Implement research parity**

Add `load_industry_day_pct`, resolve ticker industries, and build a date-level mapping suitable for the existing wrapper. If multiple industries appear for a date, use the ticker-level value in the wrapper when available and keep date-level fallback neutral.

- [ ] **Step 4: Verify Task 4**

Run: `uv run pytest tests/offensive/test_setup_research_cli.py -q`

Expected: setup research CLI tests pass.

### Final Verification

- [ ] Run focused suite:

```bash
uv run pytest tests/offensive/test_daily_action.py tests/offensive/test_daily_action_cache_refresh.py tests/offensive/test_setup_research_cli.py tests/test_main_auto_cache_refresh.py tests/test_cli_dispatcher.py -q
```

- [ ] Run a read-only diagnostic with a temporary paper tracker:

```bash
python - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
from src.screening.offensive import daily_action as da
from src.screening.offensive.paper_tracker import PaperTracker

with TemporaryDirectory() as td:
    tracker = PaperTracker(journal_dir=Path(td))
    actions = da.generate_daily_action(tracker=tracker, scan_mode="full_market")
    print({"trade_date": tracker.last_action_trade_date, "stale_reason": tracker.last_action_stale_reason, "n_actions": len(actions)})
    for action in actions:
        print(action.ticker, action.setup, action.kelly_pct, action.entry_price)
PY
```
