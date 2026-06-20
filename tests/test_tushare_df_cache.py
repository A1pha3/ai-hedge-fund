import pandas as pd

from src.tools import tushare_api
from src.tools.tushare_stock_details_helpers import build_prices_from_tushare_daily_df


def test_tushare_df_cache_evicts_oldest_entry(monkeypatch):
    monkeypatch.setattr(tushare_api, "_TUSHARE_DF_CACHE_MAX_ENTRIES", 2)
    tushare_api._tushare_df_cache.clear()

    tushare_api._store_tushare_cached_df("first", pd.DataFrame({"value": [1]}))
    tushare_api._store_tushare_cached_df("second", pd.DataFrame({"value": [2]}))
    tushare_api._store_tushare_cached_df("third", pd.DataFrame({"value": [3]}))

    assert "first" not in tushare_api._tushare_df_cache
    assert "second" in tushare_api._tushare_df_cache
    assert "third" in tushare_api._tushare_df_cache


def test_tushare_df_cache_get_refreshes_lru_order(monkeypatch):
    monkeypatch.setattr(tushare_api, "_TUSHARE_DF_CACHE_MAX_ENTRIES", 2)
    tushare_api._tushare_df_cache.clear()

    tushare_api._store_tushare_cached_df("first", pd.DataFrame({"value": [1]}))
    tushare_api._store_tushare_cached_df("second", pd.DataFrame({"value": [2]}))

    cached = tushare_api._get_tushare_cached_df("first")

    assert cached is not None
    tushare_api._store_tushare_cached_df("third", pd.DataFrame({"value": [3]}))

    assert "first" in tushare_api._tushare_df_cache
    assert "second" not in tushare_api._tushare_df_cache


def test_build_prices_from_tushare_daily_df_skips_nan_volume_row():
    """R134 (R83/R132/R133 same-class drain residue): ``build_prices_from_tushare_daily_df``
    is a FOURTH sibling df→Price converter (besides AKShareProvider R83,
    build_prices_from_dataframe R132, TushareDataSource R133) that lacks the
    pd.notna NaN-row skip guard. It is the converter on the production
    ``tushare_api.get_prices`` path (``tushare_api.py:352``), wrapped in a
    try/except that swallows the crash into ``return []`` — so a single NaN-vol
    halted day silently drops the WHOLE ticker's price series (BH-017 silent data
    loss). ``int(row["vol"])`` on NaN raises ValueError.

    A single NaN-volume row must be skipped, not drop the whole series.
    """
    df = pd.DataFrame(
        [
            {"trade_date": "20260401", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2, "vol": 12345.0},
            {"trade_date": "20260402", "open": 10.2, "high": 10.6, "low": 10.0, "close": 10.4, "vol": float("nan")},
            {"trade_date": "20260403", "open": 10.4, "high": 10.8, "low": 10.3, "close": 10.7, "vol": 13000.0},
        ]
    )

    prices = build_prices_from_tushare_daily_df(df)

    # NaN-volume row skipped (not crash); valid rows preserved (the builder
    # reverses to chronological order, same as the sibling converters).
    times = [p.time for p in prices]
    assert "2026-04-02" not in times
    assert len(prices) == 2
    assert set(times) == {"2026-04-01", "2026-04-03"}


def test_build_prices_from_tushare_daily_df_skips_nan_ohlc_row():
    """R134 (R83 same-class drain): NaN in any OHLC cell must also skip the row,
    not propagate NaN into Price (downstream corrupts every price-based metric).
    Aligns with the sibling converters' ``any(not pd.notna(v) for v in ohlc)``
    guard.
    """
    df = pd.DataFrame(
        [
            {"trade_date": "20260401", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2, "vol": 12345.0},
            {"trade_date": "20260402", "open": float("nan"), "high": 10.6, "low": 10.0, "close": 10.4, "vol": 1100.0},
        ]
    )

    prices = build_prices_from_tushare_daily_df(df)

    assert len(prices) == 1
    assert prices[0].time == "2026-04-01"
