"""Tests for src/data/providers/akshare_provider.py — _run_sync kwargs handling.

R162 system bug: _run_sync passed **kwargs to loop.run_in_executor(), which does
NOT accept keyword arguments → every async akshare fetch (get_prices etc.) failed
with "run_in_executor() got an unexpected keyword argument 'symbol'" → data=[].
Broke the entire akshare live-price path silently (caught by outer except).
"""

from __future__ import annotations

import asyncio

from src.data.providers.akshare_provider import AKShareProvider


def test_run_sync_passes_kwargs() -> None:
    """A sync function taking kwargs must work through _run_sync.

    Before fix: run_in_executor(None, func, symbol=x) → TypeError.
    After fix: kwargs forwarded correctly → returns ('sh688766', 'daily').
    """
    prov = AKShareProvider()

    async def _run():
        def _sync_fn(positional, *, keyword):
            return (positional, keyword)

        return await prov._run_sync(_sync_fn, "sh688766", keyword="daily")

    assert asyncio.run(_run()) == ("sh688766", "daily")


def test_run_sync_positional_only() -> None:
    """Positional-only call still works (regression guard)."""
    prov = AKShareProvider()

    async def _run():
        def _fn(a, b):
            return a + b

        return await prov._run_sync(_fn, 2, 3)

    assert asyncio.run(_run()) == 5


def test_run_sync_returns_value_not_none() -> None:
    """Result of the wrapped function is returned (not swallowed)."""
    prov = AKShareProvider()

    async def _run():
        return await prov._run_sync(lambda: 42)

    assert asyncio.run(_run()) == 42


# ---------------------------------------------------------------------------
# same-class drain: tushare provider has the identical _run_sync kwargs bug
# ---------------------------------------------------------------------------


def test_tushare_run_sync_passes_kwargs() -> None:
    """R162 same-class: tushare provider's _run_sync must also forward kwargs.

    Both providers shared the run_in_executor(**kwargs) bug; fixing akshare
    without tushare would leave the tushare live path broken.
    """
    from src.data.providers.tushare_provider import TushareProvider

    prov = TushareProvider()

    async def _run():
        def _sync_fn(positional, *, keyword):
            return (positional, keyword)

        return await prov._run_sync(_sync_fn, "000001.SZ", keyword="daily")

    assert asyncio.run(_run()) == ("000001.SZ", "daily")
