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
