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
import logging
import os
import threading
import time
from typing import Any, Callable, TypeVar

import pandas as pd

from src.tools.tushare_api import (
    _to_ts_code,
    get_daily_basic_batch,
    get_daily_price_batch,
)

T = TypeVar("T")

# NS-17/BH-017 同族 (c281): 此前文件无 logger, batch 失败 / per-ticker 失败
# 均静默吞异常, 运维只能通过 stats() 计数器间接感知, 无法定位根因.
# batch 失败 → WARNING (罕见且关键, 触发数千次 fallback);
# per-ticker 失败 → DEBUG (热路径避免刷屏, 排查时打开).
logger = logging.getLogger(__name__)

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

    Thread-safe: 所有读写都通过 ``self._lock`` 保护。``BatchDataFetcher``
    内部使用 ``asyncio.to_thread`` 并发触发多个 ticker 的网络请求，
    多个线程可能同时进入 ``get`` / ``set``。不在 GIL 假设下裸用 dict。
    """

    def __init__(self, ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}
        self._hits = 0
        self._misses = 0
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
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
        with self._lock:
            self._store[key] = (time.time(), value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> dict[str, int]:
        with self._lock:
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
        self._single_ticker_cache_hits = 0
        self._single_ticker_cache_misses = 0
        # c281: 单 ticker fetch 异常计数 (与 cache miss 严格区分 —
        # cache miss 是确定性无数据, fetch error 是网络/限频/鉴权异常).
        # 此前 except Exception 错误累加到 _single_ticker_cache_misses,
        # 让 stats() 报告失真, 误导运维把 fetch error 当 cache miss 处理.
        self._single_ticker_fetch_errors = 0
        self._cache_hits = 0
        # R20.10 BETA: 防缓存击穿 — 同一 cache_key 的并发调用只触发一次实际 fetch。
        # 后续调用等待第一个调用完成后直接读缓存。
        self._inflight_lock = threading.Lock()
        self._inflight_events: dict[str, threading.Event] = {}

    # ---- 公开缓存访问方法 (供 R20+ 集成方使用, 避免直接访问 _cache) ----

    def has_cached(self, key: str) -> bool:
        """检查 BatchDataCache 是否已缓存 key (在 TTL 内)。

        替代直接访问 ``fetcher._cache`` 私有属性的方式。
        """
        return self._cache.get(key) is not None

    def get_cached(self, key: str) -> Any:
        """读取 BatchDataCache 中 key 的值 (未命中/过期返回 None)。

        同样替代直接访问 ``fetcher._cache`` 私有属性。
        """
        return self._cache.get(key)

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

        # R20.10 BETA: 防缓存击穿 — 同一 key 并发调用去重。
        # 第一个调用者设 in-flight flag 并执行 fetch；
        # 后续调用者等待第一个完成后从缓存读取。
        with self._inflight_lock:
            event = self._inflight_events.get(cache_key)
            if event is not None:
                # 另一个线程正在 fetch 同一个 key，等待它完成
                is_first = False
            else:
                # 我们是第一个
                event = threading.Event()
                self._inflight_events[cache_key] = event
                is_first = True

        if not is_first:
            event.wait(timeout=120)  # 等待 fetch 完成（最多 2 分钟）
            # fetch 完成后从缓存读取结果
            cached = self._cache.get(cache_key)
            if cached is not None:
                self._cache_hits += 1
                return cached
            # fetch 失败（返回 None 或抛异常）
            return None

        # 我们是第一个调用者，执行实际 fetch
        self._batch_calls += 1
        try:
            df = fetch()
        except Exception as exc:  # noqa: BLE001 — best-effort batch, fallback to single-ticker  (c281: was silent → observable)
            # NS-17/BH-017 同族 (c281): 静默 return None 会让批量失败不可观测 —
            # 调用方回退到数千次单 ticker 并发 API 调用, 运维只看到 stats().batch_failures
            # 计数器增加, 无法定位根因 (网络/限频/鉴权/接口字段变更).
            # warning 级别 (罕见且关键 — 每批次每 trade_date 最多一次, 但触发 fallback 风暴).
            logger.warning(
                "batch_data_fetcher: batch fetch failed (cache_key=%s, "
                "falling back to single-ticker path): %s",
                cache_key,
                exc,
                exc_info=True,
            )
            self._batch_failures += 1
            return None
        finally:
            # 无论成功失败，标记完成并清理 in-flight 标记
            with self._inflight_lock:
                self._inflight_events.pop(cache_key, None)
            event.set()
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
        """单 ticker 价格拉取的同步实现 (可被 mock 覆盖)。

        优化 (R20 + R20.8 BETA):
        1. 如果 ``daily_price_batch:{trade_date}`` 已在 BatchDataCache 中,
           直接 filter 该 ticker 的 row 返回, 避免重复拉 tushare。
        2. R20.8: 多日范围 (start_date < end_date) 时, 按 end_date 单日截取;
           不再错误地视为缓存命中失败而回退到 tushare 区间拉取 (会浪费一次完整 daily API 调用)。
        3. R20.8: ticker 不在批量结果中 (停牌/退市) 时, **不增加** _single_ticker_cache_misses
           计数 (这不算 cache miss, 而是数据集确定性结果)。
        """
        # 延迟导入避免循环引用
        from src.tools.tushare_api import _cached_tushare_dataframe_call, _get_pro

        # R20 + R20.8: 尝试命中批量缓存 (单 ticker 共享)
        # 约定: end_date 形如 "20260601" -> 批量 key = "daily_price_batch:20260601"
        # 注: start_date 可能 < end_date, 但批量缓存按 trade_date 拉取。
        # R20.8: 即使是区间 [start_date, end_date] 也尝试用 end_date 那天批量数据兜底,
        # 至少能保证 1 个交易日的数据可复用, 避免在批量已成功时仍走 tushare daily 区间。
        batch_df: pd.DataFrame | None = None
        batch_cache_key = f"daily_price_batch:{end_date}"
        cached = self._cache.get(batch_cache_key)
        if isinstance(cached, pd.DataFrame) and not cached.empty:
            batch_df = cached
            self._single_ticker_cache_hits += 1
            self._cache_hits += 1

        if batch_df is not None:
            ts_code = _to_ts_code(ticker)
            if "ts_code" in batch_df.columns:
                rows = batch_df[batch_df["ts_code"] == ts_code]
                if not rows.empty:
                    # 批量行已是单日数据, 直接 dict 化
                    return rows.to_dict(orient="records")
                # R20.8: ticker 不在批量结果中 (可能停牌 / 退市), 视为确定性空数据
                # 不再累加 _single_ticker_cache_misses (这不属于 cache miss)。
                return []
            # 批量 DF 缺少 ts_code 列, 视为缓存格式不匹配, 回退到 tushare
            self._single_ticker_cache_misses += 1

        # 走原 tushare 路径
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
        except Exception as exc:  # noqa: BLE001 — best-effort per-ticker, return []  (c281: was silent → observable)
            # NS-17/BH-017 同族 (c281): 静默 return [] 会让 tushare API 异常 (网络/限频/
            # 鉴权) 与 "停牌/退市/合法无数据" 在下游完全无法区分 — 下游 Layer B 评分会把
            # "拉数失败" 误判为 "无数据 ticker" 静默剔除, 直接污染选股结果.
            # debug 级别 (热路径 — 批量失败时可能并发触发数千 ticker, WARNING 会刷屏;
            # 排查时通过 logger level=DEBUG 打开).
            # c281 同时修复计数 bug: 此前 _single_ticker_cache_misses += 1 把 fetch error
            # 误标为 cache miss (语义错误 — cache miss 是确定性无数据, fetch error 是异常),
            # 让 stats() 报告失真. 新增 _single_ticker_fetch_errors 计数器严格区分.
            logger.debug(
                "batch_data_fetcher: single-ticker fetch failed (ticker=%s, "
                "start=%s, end=%s, returning []): %s",
                ticker,
                start_date,
                end_date,
                exc,
            )
            self._single_ticker_fetch_errors += 1
            return []
        if df is None or df.empty:
            self._single_ticker_cache_misses += 1
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

    def reset_stats(self) -> None:
        """重置调用统计计数器（不清理缓存）。

        适用于全局单例在多次 ``run_auto_screening`` 调用间重置计数，
        使 ``stats()`` 反映当次运行的真实数据。
        """
        self._batch_calls = 0
        self._batch_failures = 0
        self._single_ticker_calls = 0
        self._single_ticker_cache_hits = 0
        self._single_ticker_cache_misses = 0
        self._single_ticker_fetch_errors = 0
        self._cache_hits = 0
        self._cache.clear()

    def stats(self) -> dict[str, int]:
        cache_stats = self._cache.stats()
        return {
            "batch_calls": self._batch_calls,
            "batch_failures": self._batch_failures,
            "single_ticker_calls": self._single_ticker_calls,
            "single_ticker_cache_hits": self._single_ticker_cache_hits,
            "single_ticker_cache_misses": self._single_ticker_cache_misses,
            "single_ticker_fetch_errors": self._single_ticker_fetch_errors,
            "cache_hits": self._cache_hits,
            "cache_hits_internal": cache_stats["hits"],
            "cache_misses_internal": cache_stats["misses"],
            "cache_size": cache_stats["size"],
        }

    @property
    def use_batch(self) -> bool:
        return self._use_batch
