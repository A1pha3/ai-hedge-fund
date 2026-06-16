"""Shared fixtures for src/screening tests.

R45 / R46 made streak and freshness helpers prefer the real A-share
``trade_cal`` (via ``get_open_trade_dates``) over the weekday
approximation. When a real ``TUSHARE_TOKEN`` is present in the environment
(e.g. loaded from ``.env`` during a broad ``pytest tests/`` run), the real
calendar leaks into tests that were written assuming weekday-only behavior,
making them non-deterministic across local/CI runs.

This autouse fixture neutralises that leak by defaulting
``get_open_trade_dates`` to return an empty list (→ weekday fallback, the
pre-R45/R46 deterministic behaviour). Tests that exercise the real-calendar
path explicitly monkeypatch ``get_open_trade_dates`` themselves, which
overrides this default since their monkeypatch runs after the autouse setup.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_trade_calendar(monkeypatch: pytest.MonkeyPatch):
    """Default ``get_open_trade_dates`` to empty so weekday-only tests stay
    deterministic even when a real ``TUSHARE_TOKEN`` is in the environment."""
    import src.tools.tushare_api as tushare_api

    monkeypatch.setattr(tushare_api, "get_open_trade_dates", lambda *_args, **_kwargs: [])
    yield
