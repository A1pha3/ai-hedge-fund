"""NS-9: Tushare provider/data-source qfq drain.

R37 fixed ``_fetch_tushare_ashare_prices_df`` to fetch ``pro.daily`` +
``pro.adj_factor`` and apply forward-adjustment (前复权). But two sibling
sites still use raw ``pro.daily`` without ``adj_factor``:

1. ``TushareProvider.get_prices`` (src/data/providers/tushare_provider.py:123)
2. ``TushareDataSource.get_prices`` (src/tools/ashare_data_sources.py:91)

Across any ex-dividend day (送股/分红/配股) the raw close gaps down, fabricating
a phantom loss that corrupts return/ATR/stop-loss/drawdown computations
downstream. This test suite verifies both siblings now apply qfq adjustment
mirroring R37.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from src.data.providers.tushare_provider import TushareProvider
from src.tools.ashare_data_sources import TushareDataSource


# ---------------------------------------------------------------------------
# Fixtures: raw daily + adj_factor with a known ex-dividend gap
# ---------------------------------------------------------------------------

#: Raw prices across an ex-dividend day. day1 close=10, day2 (ex-div) close=9.5
#: looks like a -5% drop, but it's just the dividend payment.
#: NOTE: Tushare ``pro.daily`` returns rows in trade_date DESC order (newest
#: first). The provider/data-source call ``prices.reverse()`` to give callers
#: ascending order; fixtures must mirror that API contract so ``prices[0]``
#: is the oldest day after reverse.
_RAW_DAILY_DF = pd.DataFrame(
    [
        {"trade_date": "20260112", "open": 9.6, "high": 9.7, "low": 9.4, "close": 9.5, "vol": 1100},
        {"trade_date": "20260109", "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "vol": 1000},
    ]
)

#: adj_factor: day1=1.2 (pre-div), day2=1.0 (post-div, latest).
#: qfq: day1 = 10 * 1.2/1.0 = 12.0, day2 = 9.5 * 1.0/1.0 = 9.5.
#: The qfq return reflects the true economic effect without the artificial
#: price-level jump from the dividend. Order mirrors _RAW_DAILY_DF (DESC).
_ADJ_FACTOR_DF = pd.DataFrame(
    [
        {"trade_date": "20260112", "adj_factor": 1.0},
        {"trade_date": "20260109", "adj_factor": 1.2},
    ]
)


def _expected_qfq_day1_close() -> float:
    """qfq close for day1 = raw_close * adj_factor / latest_adj_factor."""
    return 10.0 * 1.2 / 1.0  # = 12.0


# ---------------------------------------------------------------------------
# TushareProvider (async) — src/data/providers/tushare_provider.py
# ---------------------------------------------------------------------------


def _new_tushare_provider_with_qfq_mock(
    raw_df: pd.DataFrame | None = _RAW_DAILY_DF,
    adj_df: pd.DataFrame | None = _ADJ_FACTOR_DF,
) -> TushareProvider:
    """Build a TushareProvider with mocked _pro.daily + _pro.adj_factor.

    The provider's ``get_prices`` calls ``self._run_sync(self._pro.daily, ...)``.
    To add qfq, the fix must also call ``self._run_sync(self._pro.adj_factor, ...)``
    and apply the adjustment. This mock returns the configured dfs based on
    which attribute is accessed.
    """
    provider = object.__new__(TushareProvider)
    provider.name = "tushare"
    provider.priority = 5
    provider.health_status = "healthy"
    provider._token = "fake_token_for_test"

    # Mock _pro with daily/adj_factor methods returning the configured dfs
    pro = SimpleNamespace()

    def _daily(**_kwargs: Any) -> pd.DataFrame | None:
        return raw_df

    def _adj_factor(**_kwargs: Any) -> pd.DataFrame | None:
        return adj_df

    pro.daily = _daily
    pro.adj_factor = _adj_factor
    provider._pro = pro

    # _run_sync: call the sync function directly
    async def _fake_run_sync(func, *args, **kwargs):
        return func(**kwargs)

    provider._run_sync = _fake_run_sync  # type: ignore[assignment]
    return provider


def test_ns9_tushare_provider_applies_qfq_adjustment() -> None:
    """TushareProvider.get_prices must apply qfq adjustment (NS-9 drain).

    RED: current implementation calls only ``self._pro.daily`` (line 123),
    ignoring ``adj_factor``. Across an ex-dividend day, raw close gaps down
    (10.0 → 9.5) but qfq close should be 12.0 → 9.5 (scales history).
    """
    provider = _new_tushare_provider_with_qfq_mock()

    async def _run():
        return await provider.get_prices("600519", "2026-01-09", "2026-01-12")

    response = asyncio.run(_run())
    assert response.error is None or response.error == "", f"unexpected error: {response.error}"
    assert len(response.data) == 2, f"expected 2 prices, got {len(response.data)}"

    # qfq day1 close = raw * adj_factor / latest_adj = 10 * 1.2 / 1.0 = 12.0
    # RED: current returns raw close = 10.0 (no qfq adjustment)
    day1 = response.data[0]  # prices.reverse() → oldest first
    day2 = response.data[1]
    expected_day1_close = _expected_qfq_day1_close()
    assert day1.close == pytest.approx(expected_day1_close, abs=0.01), (
        f"NS-9: TushareProvider day1 close should be qfq-adjusted to {expected_day1_close}, "
        f"got {day1.close} (raw=10.0). adj_factor=1.2/1.0 not applied."
    )
    # day2 close unchanged (latest anchor)
    assert day2.close == pytest.approx(9.5, abs=0.01)


def test_ns9_tushare_provider_falls_back_to_raw_when_no_adj_factor() -> None:
    """TushareProvider.get_prices must degrade gracefully if adj_factor fetch fails.

    R37 pattern: return raw daily if adj_factor unavailable (degrade, don't block).
    """
    provider = _new_tushare_provider_with_qfq_mock(adj_df=None)

    async def _run():
        return await provider.get_prices("600519", "2026-01-09", "2026-01-12")

    response = asyncio.run(_run())
    assert len(response.data) == 2
    # Raw close unchanged (no adj_factor to scale by)
    day1 = response.data[0]
    assert day1.close == pytest.approx(10.0, abs=0.01)


# ---------------------------------------------------------------------------
# TushareDataSource (sync) — src/tools/ashare_data_sources.py
# ---------------------------------------------------------------------------


def _patch_tushare_datasource_cached_call(
    monkeypatch: pytest.MonkeyPatch,
    raw_df: pd.DataFrame | None = _RAW_DAILY_DF,
    adj_df: pd.DataFrame | None = _ADJ_FACTOR_DF,
) -> None:
    """Patch ``_cached_tushare_dataframe_call`` to return configured dfs by api_name.

    The helper is imported lazily inside ``TushareDataSource.get_prices`` via
    ``from src.tools.tushare_api import _cached_tushare_dataframe_call``, so we
    patch it on its home module (``tushare_api``) — every fresh ``from`` import
    re-binds the (now patched) attribute, which is exactly the behaviour we need.
    """
    def fake_cached_call(_pro: Any, api_name: str, **_kwargs: Any) -> pd.DataFrame | None:
        if api_name == "daily":
            return raw_df
        if api_name == "adj_factor":
            return adj_df
        return None

    monkeypatch.setattr(
        "src.tools.tushare_api._cached_tushare_dataframe_call",
        fake_cached_call,
    )


def test_ns9_tushare_datasource_applies_qfq_adjustment(monkeypatch: pytest.MonkeyPatch) -> None:
    """TushareDataSource.get_prices must apply qfq adjustment (NS-9 drain).

    RED: current implementation calls only ``_cached_tushare_dataframe_call(pro, "daily", ...)``
    (line 91), ignoring adj_factor. Across an ex-dividend day, raw close gaps
    down (10.0 → 9.5) but qfq close should be 12.0 → 9.5.
    """
    _patch_tushare_datasource_cached_call(monkeypatch)
    # Bypass _init_tushare (TUSHARE_TOKEN not set in test env)
    monkeypatch.setattr(TushareDataSource, "_init_tushare", classmethod(lambda cls: True))
    monkeypatch.setattr(TushareDataSource, "_pro", object(), raising=False)

    prices = TushareDataSource.get_prices("600519", "2026-01-09", "2026-01-12")
    assert len(prices) == 2, f"expected 2 prices, got {len(prices)}"

    # qfq day1 close = raw * adj_factor / latest_adj = 10 * 1.2 / 1.0 = 12.0
    # RED: current returns raw close = 10.0 (no qfq adjustment)
    day1 = prices[0]  # prices.reverse() → oldest first
    day2 = prices[1]
    expected_day1_close = _expected_qfq_day1_close()
    assert day1.close == pytest.approx(expected_day1_close, abs=0.01), (
        f"NS-9: TushareDataSource day1 close should be qfq-adjusted to {expected_day1_close}, "
        f"got {day1.close} (raw=10.0). adj_factor=1.2/1.0 not applied."
    )
    assert day2.close == pytest.approx(9.5, abs=0.01)


def test_ns9_tushare_datasource_falls_back_to_raw_when_no_adj_factor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TushareDataSource.get_prices must degrade gracefully if adj_factor fetch fails."""
    _patch_tushare_datasource_cached_call(monkeypatch, adj_df=None)
    monkeypatch.setattr(TushareDataSource, "_init_tushare", classmethod(lambda cls: True))
    monkeypatch.setattr(TushareDataSource, "_pro", object(), raising=False)

    prices = TushareDataSource.get_prices("600519", "2026-01-09", "2026-01-12")
    assert len(prices) == 2
    # Raw close unchanged (no adj_factor to scale by)
    day1 = prices[0]
    assert day1.close == pytest.approx(10.0, abs=0.01)
