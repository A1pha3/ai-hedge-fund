"""P0-1 全市场筛选速度优化 — 批量数据获取层。

封装 tushare/akshare 的批量接口，提供：
  - 短期内存缓存 (BatchDataCache, 默认 60s TTL)
  - 批量接口优先，失败时降级到单 ticker + asyncio 并发
  - ``USE_BATCH_FETCHER`` 环境变量 kill switch (默认开启)
  - 调用统计 (stats())

典型用法 (在 ``--auto`` 入口)::

    fetcher = BatchDataFetcher()  # 自动读取 USE_BATCH_FETCHER
    prices = fetcher.fetch_daily_prices_batch(trade_date)
    if prices is not None:
        # 用批量数据驱动 Layer B 评分
        ...
    else:
        # 降级：走原来的单 ticker 路径
        ...

设计原则：
  1. 不引入新网络依赖 (沿用 tushare / akshare)
  2. 批量失败 → 返回 None，调用方决定是否回退（不静默重试）
  3. 完全向后兼容：原 ``get_prices`` / ``get_financial_metrics`` 单 ticker 调用保留
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Callable, TypeVar

import pandas as pd

from src.tools.tushare_api import (
    _to_ts_code,
    get_daily_basic_batch,
    get_daily_price_batch,
)

T = TypeVar("T")

# 默认缓存 TTL (秒)
DEFAULT_CACHE_TTL_SECONDS = 60

# 默认并发度
DEFAULT_MAX_CONCURRENCY = 8

# 环境变量 kill switch
_BATCH_FETCHER_ENV_KEY = "USE_BATCH_FETCHER"

# 模块级全局 fetcher (lazy 单例) — 避免在同一进程内多次创建
_global_fetcher: "BatchDataFetcher | None" = None


def is_batch_fetcher_enabled() -> bool:
    """读取 ``USE_BATCH_FETCHER`` 环境变量，默认开启。"""
    raw = os.getenv(_BATCH_FETCHER_ENV_KEY)
    if raw is None or raw == "":
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def reset_global_batch_data_fetcher() -> None:
    """重置全局 fetcher 单例（测试用）。"""
    global _global_fetcher
    _global_fetcher = None


def get_global_batch_data_fetcher() -> "BatchDataFetcher":
    """获取（必要时创建）全局 BatchDataFetcher 单例。"""
    global _global_fetcher
    if _global_fetcher is None:
        _global_fetcher = BatchDataFetcher()
    return _global_fetcher


class BatchDataCache:
    """短期内存缓存，TTL 过期。

    简单的 dict + 时间戳实现；不为高频热点优化，定位：
    "同一进程 / 同一分钟内" 对同一批量的重复请求去重。
    """

    def __init__(self, ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            self._misses += 1
            return None
        ts, value = entry
        if (time.time() - ts) > self._ttl:
            # 过期 → 视为未命中并清理
            self._store.pop(key, None)
            self._misses += 1
            return None
        self._hits += 1
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (time.time(), value)

    def clear(self) -> None:
        self._store.clear()
        self._hits = 0
        self._misses = 0

    def stats(self) -> dict[str, int]:
        return {
            "hits": self._hits,
            "misses": self._misses,
            "size": len(self._store),
        }


class BatchDataFetcher:
    """批量数据获取器 — 全市场批量接口 + 单 ticker 并发 fallback。"""

    def __init__(
        self,
        *,
        use_batch: bool | None = None,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        if use_batch is None:
            use_batch = is_batch_fetcher_enabled()
        self._use_batch = use_batch
        self._max_concurrency = max(1, int(max_concurrency))
        self._cache = BatchDataCache(ttl_seconds=cache_ttl_seconds)
        # 调用统计
        self._batch_calls = 0
        self._batch_failures = 0
        self._single_ticker_calls = 0
        self._cache_hits = 0

    # ---- 批量接口 (tushare) ----

    def fetch_daily_prices_batch(self, trade_date: str) -> pd.DataFrame | None:
        """批量拉取全市场当日 daily 行情 (open/high/low/close/vol/amount/pct_chg)。

        失败时返回 ``None``，调用方决定是否降级。
        """
        return self._cached_batch_call(
            cache_key=f"daily_price_batch:{trade_date}",
            fetch=lambda: get_daily_price_batch(trade_date),
        )

    def fetch_daily_basic_batch(self, trade_date: str) -> pd.DataFrame | None:
        """批量拉取全市场当日 daily_basic (pe/pb/turnover_rate/total_mv/circ_mv/...)。"""
        return self._cached_batch_call(
            cache_key=f"daily_basic_batch:{trade_date}",
            fetch=lambda: get_daily_basic_batch(trade_date),
        )

    def _cached_batch_call(
        self,
        *,
        cache_key: str,
        fetch: Callable[[], pd.DataFrame | None],
    ) -> pd.DataFrame | None:
        if not self._use_batch:
            return None
        cached = self._cache.get(cache_key)
        if cached is not None:
            self._cache_hits += 1
            return cached
        self._batch_calls += 1
        try:
            df = fetch()
        except Exception:
            self._batch_failures += 1
            return None
        if df is None:
            self._batch_failures += 1
            return None
        self._cache.set(cache_key, df)
        return df

    # ---- 单 ticker 接口 (fallback) ----

    def _fetch_single_ticker_prices_sync(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        """单 ticker 价格拉取的同步实现 (可被 mock 覆盖)。"""
        # 延迟导入避免循环引用
        from src.tools.tushare_api import _get_pro, _cached_tushare_dataframe_call

        pro = _get_pro()
        if pro is None:
            return []
        try:
            df = _cached_tushare_dataframe_call(
                pro,
                "daily",
                ts_code=_to_ts_code(ticker),
                start_date=start_date,
                end_date=end_date,
                fields="ts_code,trade_date,open,high,low,close,pre_close,vol,amount,pct_chg",
            )
        except Exception:
            return []
        if df is None or df.empty:
            return []
        return df.to_dict(orient="records")

    async def fetch_prices_for_tickers(
        self,
        tickers: list[str],
        start_date: str,
        end_date: str,
    ) -> dict[str, list[dict[str, Any]]]:
        """并发拉取多个 ticker 的价格数据。"""
        if not tickers:
            return {}

        sem = asyncio.Semaphore(self._max_concurrency)

        async def _one(ticker: str) -> tuple[str, list[dict[str, Any]]]:
            async with sem:
                result = await asyncio.to_thread(
                    self._fetch_single_ticker_prices_sync,
                    ticker,
                    start_date,
                    end_date,
                )
                self._single_ticker_calls += 1
                return ticker, result

        tasks = [asyncio.create_task(_one(t)) for t in tickers]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return {ticker: payload for ticker, payload in results}

    # ---- 统计 ----

    def stats(self) -> dict[str, int]:
        cache_stats = self._cache.stats()
        return {
            "batch_calls": self._batch_calls,
            "batch_failures": self._batch_failures,
            "single_ticker_calls": self._single_ticker_calls,
            "cache_hits": self._cache_hits,
            "cache_hits_internal": cache_stats["hits"],
            "cache_misses_internal": cache_stats["misses"],
            "cache_size": cache_stats["size"],
        }

    @property
    def use_batch(self) -> bool:
        return self._use_batch
