"""R83 same-class drain: provider ``get_prices`` must not silently drop the entire
ticker's price series when a single OHLC/volume cell is ``NaN`` (halted / illiquid /
partial feed).

Background — sibling ``get_financial_metrics`` already guards every numeric field
with ``pd.notna()`` (R20.11 BETA fix), but ``get_prices`` builds the ``Price`` with
bare ``float(row[...])`` / ``int(row["vol"])``. A single bad row raises
``TypeError``/``ValueError``, which the broad ``except Exception`` at the bottom
catches and returns ``DataResponse(data=[], error=str(e))`` — silently dropping the
entire ticker's price series. This is the same class of bug as R83
(``conditional_order_advisor`` bare ``float(history[-1])``) and the same family as
BH-017 silent-degradation.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import numpy as np
import pandas as pd

from src.data.providers.akshare_provider import AKShareProvider
from src.data.providers.tushare_provider import TushareProvider


def _new_akshare_provider() -> AKShareProvider:
    provider = object.__new__(AKShareProvider)
    provider.name = "akshare"
    provider.priority = 10
    provider.health_status = "healthy"
    # _is_available 检查 _akshare_available and _ak is not None
    provider._ak = SimpleNamespace()  # type: ignore[assignment]
    provider._akshare_available = True
    return provider


def _new_tushare_provider() -> TushareProvider:
    provider = object.__new__(TushareProvider)
    provider.name = "tushare"
    provider.priority = 5
    provider.health_status = "healthy"
    # _is_available 检查 _token and _pro is not None
    provider._pro = SimpleNamespace()  # type: ignore[assignment]
    provider._token = "fake_token_for_test"
    return provider


def test_tushare_provider_get_prices_skips_nan_volume_row() -> None:
    """R83 drain: tushare daily vol 含 NaN 的行不应让整个 ticker 价格序列消失。

    Before fix: ``int(row["vol"])`` on NaN → TypeError → except → DataResponse(data=[])
    After fix: 该行被跳过 (或 NaN 容错), 其余正常行仍返回。
    """
    df = pd.DataFrame(
        [
            {"trade_date": "20240101", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2, "vol": 1000},
            {"trade_date": "20240102", "open": 10.2, "high": 10.6, "low": 10.0, "close": 10.4, "vol": np.nan},  # 停牌/无成交
            {"trade_date": "20240103", "open": 10.4, "high": 10.8, "low": 10.3, "close": 10.7, "vol": 1200},
        ]
    )
    provider = _new_tushare_provider()
    # get_prices 访问 self._pro.daily (先求值再传给 _run_sync), 需挂一个 stub 属性
    provider._pro.daily = lambda **kw: df  # type: ignore[attr-defined]

    async def _fake_run_sync(func, *args, **kwargs):
        return df

    provider._run_sync = _fake_run_sync  # type: ignore[assignment]

    async def _run():
        return await provider.get_prices("600519", "2024-01-01", "2024-01-03")

    response = asyncio.run(_run())
    # Before fix: data=[] (全部被 TypeError 吞掉). After fix: 应保留非 NaN 行 (>=1).
    assert len(response.data) >= 1, f"NaN vol 行不应吞掉整个 ticker 价格序列; got data=[] error={response.error!r}"
    # 没有一行的 close 是 NaN
    for price in response.data:
        assert price.close == price.close  # NaN != NaN


def test_akshare_provider_get_prices_skips_nan_volume_row() -> None:
    """R83 drain: akshare 成交量含 NaN 的行不应让整个 ticker 价格序列消失。"""
    df = pd.DataFrame(
        [
            {"日期": "2024-01-01", "开盘": 10.0, "最高": 10.5, "最低": 9.8, "收盘": 10.2, "成交量": 1000},
            {"日期": "2024-01-02", "开盘": 10.2, "最高": 10.6, "最低": 10.0, "收盘": 10.4, "成交量": np.nan},
            {"日期": "2024-01-03", "开盘": 10.4, "最高": 10.8, "最低": 10.3, "收盘": 10.7, "成交量": 1200},
        ]
    )
    provider = _new_akshare_provider()
    provider._ak.stock_zh_a_hist = lambda **kw: df  # type: ignore[attr-defined]

    async def _fake_run_sync(func, *args, **kwargs):
        return df

    provider._run_sync = _fake_run_sync  # type: ignore[assignment]

    async def _run():
        return await provider.get_prices("600519", "2024-01-01", "2024-01-03")

    response = asyncio.run(_run())
    assert len(response.data) >= 1, f"NaN 成交量行不应吞掉整个 ticker 价格序列; got data=[] error={response.error!r}"
    for price in response.data:
        assert price.close == price.close
