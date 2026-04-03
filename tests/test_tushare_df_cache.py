import pandas as pd

from src.tools import tushare_api


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
