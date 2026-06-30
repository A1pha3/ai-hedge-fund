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

NS-5 wiring (2026-06-30): ``_isolate_regime_recompute`` defaults
``load_latest_regime_recompute`` to return ``None`` so existing tests that
assert hardcoded :data:`REGIME_HISTORICAL_WINRATES` /
:data:`REGIME_MULTIHORIZON_MEDIANS` values stay deterministic even when
``data/reports/regime_winrates_recomputed_*.json`` exists in the repo. Tests
that exercise the JSON override path explicitly restore the real loader (see
``tests/screening/test_regime_winrate_wiring.py::_restore_real_loader``).
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


@pytest.fixture(autouse=True)
def _isolate_regime_recompute(monkeypatch: pytest.MonkeyPatch):
    """NS-5 wiring: default ``load_latest_regime_recompute`` to ``None``.

    Without this, tests that assert hardcoded regime winrate values (e.g.
    crisis ``0.468``) would non-deterministically pick up
    ``data/reports/regime_winrates_recomputed_*.json`` if present in the
    repo, breaking each time the daily job writes a fresh artifact.

    Tests that need real loader behavior (e.g. JSON override path in
    ``test_regime_winrate_wiring.py``) restore it explicitly via
    ``_restore_real_loader(monkeypatch)`` which reads
    ``_real_load_latest_regime_recompute`` saved below.
    """
    import src.screening.regime_winrate as rw

    real = getattr(rw, "load_latest_regime_recompute", None)
    if real is not None:
        # Save real loader so tests can restore it via monkeypatch
        monkeypatch.setattr(rw, "_real_load_latest_regime_recompute", real, raising=False)
        monkeypatch.setattr(rw, "load_latest_regime_recompute", lambda *_, **__: None)
    yield


@pytest.fixture(autouse=True)
def _clean_tempfile_mkdtemp(monkeypatch: pytest.MonkeyPatch):
    """Track and remove ``tempfile.mkdtemp()`` dirs so tests don't leak.

    Several screening tests call ``tempfile.mkdtemp()`` (some via
    ``from tempfile import mkdtemp``) without ever cleaning up, which has
    leaked 17k+ dirs into the system temp dir over time. This wraps
    ``mkdtemp`` to record created dirs and removes them after each test.

    New tests should still prefer the pytest ``tmp_path`` fixture.
    """
    import shutil
    import sys
    import tempfile

    created: list[str] = []
    real_mkdtemp = tempfile.mkdtemp

    def _tracked_mkdtemp(*args: object, **kwargs: object) -> str:
        path = real_mkdtemp(*args, **kwargs)
        created.append(path)
        return path

    # Patch the canonical ``tempfile.mkdtemp`` plus any module that bound it
    # by name (``from tempfile import mkdtemp``), which a plain attribute
    # patch on ``tempfile`` alone would otherwise miss.
    for module in list(sys.modules.values()):
        if module is not None and getattr(module, "mkdtemp", None) is real_mkdtemp:
            monkeypatch.setattr(module, "mkdtemp", _tracked_mkdtemp, raising=False)

    yield

    for path in created:
        shutil.rmtree(path, ignore_errors=True)
