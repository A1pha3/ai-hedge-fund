"""Shared fixtures for tests/offensive.

The production default for the daily-action universe delisting filter
(``cache_refresh._load_listed_ticker_symbols``) is tushare-backed. Tests must
stay hermetic and must never depend on the repository's runtime caches, so the
default loader is neutralized to fail-open (``None`` = do not filter). Tests
for the filter itself pass ``listed_universe_loader=`` explicitly; tests for
the real loader can request this fixture and use the returned original.
"""

from __future__ import annotations

import pytest

from src.screening.offensive import cache_refresh


@pytest.fixture(autouse=True)
def _disable_listed_universe_default_loader(monkeypatch: pytest.MonkeyPatch):
    original = cache_refresh._load_listed_ticker_symbols
    monkeypatch.setattr(cache_refresh, "_load_listed_ticker_symbols", lambda: None)
    return original


@pytest.fixture(autouse=True)
def _isolate_tushare_persistent_cache(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Tests must never read or write the repository's runtime caches.

    ``_cached_tushare_dataframe_call`` reads a process-local LRU first
    (``_tushare_df_cache``) and the global persistent cache second, and
    ``_persist_tushare_dataframe_result`` writes whatever frame it receives —
    including test mock frames — into that persistent cache. A mock
    ``index_member`` frame persisted this way once overwrote the real
    bank-industry frame with 2 rows of fake membership (000002.SZ in/out
    dates), which made the daily-action readiness SW capture hit a
    cross-industry conflict and fail-closed the whole --auto publication
    (2026-08-11, ``SW mapping must exactly cover frozen universe``). Both
    layers must be isolated so no test can pollute or depend on runtime state.
    """
    from src.data.enhanced_cache import EnhancedCache
    from src.tools import tushare_api

    isolated = EnhancedCache(disk_path=str(tmp_path / "cache.sqlite"))
    monkeypatch.setattr(tushare_api, "_persistent_cache", isolated)
    monkeypatch.setattr(tushare_api, "_tushare_df_cache", {})
