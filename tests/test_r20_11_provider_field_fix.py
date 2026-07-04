"""R20.11 BETA: Provider D/A vs D/E 字段错位 bug 回归测试。

GAMMA-017 修复了 adapter 路径 (akshare_adapter/tushare_adapter) 的 debt_to_equity
写入问题, 但 AKShareProvider / TushareProvider 这两个 provider 直连的
get_financial_metrics 路径仍然把 D/A (资产负债率 / debt_to_assets) 当作 D/E
(debt_to_equity) 写入, 复刻同样的 45% 杠杆低估 bug。

这些测试隔离 provider 自身逻辑, 验证 D/A 走 debt_to_assets 字段,
debt_to_equity 留 None (下游 adapter 会从 D/A 推导)。

实现策略: patch provider._run_sync (使用 run_in_executor 的 async helper), 让
测试同步返回数据 DataFrame, 避免被 run_in_executor 的 kwargs 限制阻塞。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pandas as pd
import pytest

from src.data.providers.akshare_provider import AKShareProvider
from src.data.providers.tushare_provider import TushareProvider


def _new_akshare_provider_with_mock() -> AKShareProvider:
    """构造 AKShareProvider, _ak 指向 mock akshare, _akshare_available=True。"""
    provider = object.__new__(AKShareProvider)
    provider.name = "akshare"
    provider.priority = 10
    provider.health_status = "healthy"
    provider._ak = SimpleNamespace()  # 真实调用走 _run_sync, 会被 patch
    provider._akshare_available = True
    return provider


def _new_tushare_provider_with_mock() -> TushareProvider:
    """构造 TushareProvider, _pro 指向 mock pro, _token 设为非空。"""
    provider = object.__new__(TushareProvider)
    provider.name = "tushare"
    provider.priority = 5
    provider.health_status = "healthy"
    provider._pro = SimpleNamespace()  # 真实调用走 _run_sync, 会被 patch
    provider._token = "fake_token_for_test"
    return provider


def test_akshare_provider_da_goes_to_debt_to_assets_not_debt_to_equity():
    """R20.11 BETA: 资产负债率 (D/A) 必须写入 debt_to_assets 字段, 不是 debt_to_equity。

    复刻 GAMMA-017 bug: 之前 line 181 把资产负债率直接写到 debt_to_equity, 导致
    下游 agents (michael_burry, warren_buffett) 杠杆被低估约 45%。
    """
    df = pd.DataFrame(
        [
            {
                "报告期": "2024-09-30",
                "营业收入": 100.0,
                "净利润": 10.0,
                "市盈率": 15.0,
                "市净率": 3.0,
                "净资产收益率": 12.0,
                "资产负债率": 60.0,  # D/A = 60%
            }
        ]
    )
    provider = _new_akshare_provider_with_mock()

    async def _fake_run_sync(func, *args, **kwargs):
        return df

    async def _run() -> list:
        # 挂 mock 方法到 provider._ak (与 tushare 路径一致, 因为 get_financial_metrics
        # 内部是 self._ak.stock_financial_analysis_indicator 拿方法引用)
        provider._ak.stock_financial_analysis_indicator = lambda **kwargs: df  # type: ignore[attr-defined]
        provider._run_sync = _fake_run_sync  # type: ignore[assignment]
        response = await provider.get_financial_metrics("600519", "2024-09-30")
        return response.data

    metrics_list = asyncio.run(_run())
    assert len(metrics_list) == 1
    metric = metrics_list[0]
    # R20.11 修复: D/A 写 debt_to_assets
    assert metric.debt_to_assets == 0.60
    # R20.11 修复: debt_to_equity 不再被错误填充, 留 None (adapter 会从 D/A 推导)
    assert metric.debt_to_equity is None


def test_tushare_provider_da_goes_to_debt_to_assets_not_debt_to_equity():
    """R20.11 BETA: Tushare fina_indicator 的 debt_to_assets 字段必须写到
    debt_to_assets, 不是 debt_to_equity。
    """
    df_basic = pd.DataFrame(
        [
            {
                "ts_code": "600519.SH",
                "trade_date": "20240930",
                "pe_ttm": 25.0,
                "pb": 8.0,
                "total_mv": 100000.0,  # 亿元
            }
        ]
    )
    df_fin = pd.DataFrame(
        [
            {
                "ts_code": "600519.SH",
                "end_date": "20240930",
                "roe": 20.0,  # 20%
                "debt_to_assets": 45.0,  # D/A = 45%
                "q_sales_yoy": 15.0,  # 营收增长 15%
            }
        ]
    )
    provider = _new_tushare_provider_with_mock()

    async def _fake_run_sync(func, *args, **kwargs):
        # 用 provider._pro 上挂载的 attribute 名作为 marker (因为 lambda 没有 __name__ 区分)
        df_basic_attr = getattr(provider._pro, "_df_basic", None)
        df_fin_attr = getattr(provider._pro, "_df_fin", None)
        if df_basic_attr is not None and df_fin_attr is not None and func is getattr(provider._pro, "fina_indicator", None):
            return df_fin_attr
        return df_basic_attr if df_basic_attr is not None else df_fin_attr

    async def _run() -> list:
        # 将 mock 方法挂到 provider._pro (provider.get_financial_metrics 内部通过
        # self._pro.daily_basic / self._pro.fina_indicator 获取方法引用, 再传给 _run_sync)
        provider._pro._df_basic = df_basic  # type: ignore[attr-defined]
        provider._pro._df_fin = df_fin  # type: ignore[attr-defined]

        def _daily_basic(**_kwargs):
            return df_basic

        def _fina_indicator(**_kwargs):
            return df_fin

        provider._pro.daily_basic = _daily_basic  # type: ignore[attr-defined]
        provider._pro.fina_indicator = _fina_indicator  # type: ignore[attr-defined]
        provider._run_sync = _fake_run_sync  # type: ignore[assignment]
        response = await provider.get_financial_metrics("600519", "2024-09-30")
        return response.data

    metrics_list = asyncio.run(_run())
    assert len(metrics_list) == 1
    metric = metrics_list[0]
    # R20.11 修复: debt_to_assets 字段正确填充
    assert metric.debt_to_assets == 0.45
    # R20.11 修复: debt_to_equity 不再被错误填充
    assert metric.debt_to_equity is None
    # 其他字段保持正常
    assert metric.return_on_equity == 0.20
    assert metric.revenue_growth == 0.15
    # market_cap: total_mv 100000 亿 * 10000 = 1e9 元
    assert metric.market_cap == 100000.0 * 10000


def test_cache_benchmark_subprocess_has_timeout():
    """R20.11 BETA: cache_benchmark.run_validation_subprocess 必须传递 timeout。

    旧实现缺 timeout, validation 脚本挂起会无限阻塞整条 pipeline。
    """
    import inspect

    from src.data.cache_benchmark import run_validation_subprocess

    sig = inspect.signature(run_validation_subprocess)
    assert "timeout_seconds" in sig.parameters
    # 默认值应该是合理的（>= 60s, <= 1800s）
    default = sig.parameters["timeout_seconds"].default
    assert 60.0 <= default <= 1800.0
