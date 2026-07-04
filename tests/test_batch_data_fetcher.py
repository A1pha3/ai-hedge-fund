"""BatchDataFetcher 单元测试 — P0-1 全市场筛选速度优化。

覆盖：
  - BatchDataCache: TTL 过期、key 命中、clear
  - BatchDataFetcher.fetch_daily_prices_batch: 批量接口数据格式校验
  - BatchDataFetcher.fetch_daily_basic_batch: 批量接口数据格式校验
  - 批量失败 → 降级到单 ticker
  - 缓存命中减少底层调用
  - 并发受 semaphore 限制
  - USE_BATCH_FETCHER=false 走单 ticker
  - stats() 跟踪调用统计
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.screening.batch_data_fetcher import (
    BatchDataCache,
    BatchDataFetcher,
    get_global_batch_data_fetcher,
    is_batch_fetcher_enabled,
    reset_global_batch_data_fetcher,
)

# ============================================================================
# BatchDataCache 单元测试
# ============================================================================


class TestBatchDataCache:
    def test_get_returns_none_for_missing_key(self):
        cache = BatchDataCache(ttl_seconds=60)
        assert cache.get("missing") is None

    def test_set_then_get_returns_value(self):
        cache = BatchDataCache(ttl_seconds=60)
        cache.set("k1", {"hello": "world"})
        assert cache.get("k1") == {"hello": "world"}

    def test_ttl_expiry(self):
        cache = BatchDataCache(ttl_seconds=0)  # 0 TTL = 立即过期
        cache.set("k1", "value")
        # sleep 1ms to ensure time.time() advances
        time.sleep(0.01)
        assert cache.get("k1") is None

    def test_clear_removes_all_entries(self):
        cache = BatchDataCache(ttl_seconds=60)
        cache.set("k1", "v1")
        cache.set("k2", "v2")
        cache.clear()
        assert cache.get("k1") is None
        assert cache.get("k2") is None

    def test_overwrite_key_replaces_value(self):
        cache = BatchDataCache(ttl_seconds=60)
        cache.set("k1", "old")
        cache.set("k1", "new")
        assert cache.get("k1") == "new"

    def test_cache_stats_track_hits_and_misses(self):
        cache = BatchDataCache(ttl_seconds=60)
        cache.set("k1", "v1")
        cache.get("k1")  # hit
        cache.get("missing")  # miss
        cache.get("missing2")  # miss
        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 2
        assert stats["size"] == 1

    def test_cache_stats_resets_on_clear(self):
        cache = BatchDataCache(ttl_seconds=60)
        cache.set("k1", "v1")
        cache.get("k1")
        cache.clear()
        stats = cache.stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["size"] == 0


# ============================================================================
# BatchDataFetcher 批量接口测试
# ============================================================================


def _make_daily_prices_df(rows: list[dict]) -> pd.DataFrame:
    defaults = {"ts_code": "", "trade_date": "20260305", "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.2, "pre_close": 10.0, "vol": 1.0, "amount": 1000.0, "pct_chg": 2.0}
    return pd.DataFrame([{**defaults, **r} for r in rows])


def _make_daily_basic_df(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "ts_code": "",
        "trade_date": "20260305",
        "close": 10.0,
        "turnover_rate": 1.0,
        "pe": 15.0,
        "pe_ttm": 14.0,
        "pb": 1.5,
        "ps": 2.0,
        "ps_ttm": 1.8,
        "dv_ratio": 2.0,
        "dv_ttm": 2.0,
        "total_share": 100000,
        "float_share": 80000,
        "free_share": 60000,
        "total_mv": 1000000,
        "circ_mv": 800000,
    }
    return pd.DataFrame([{**defaults, **r} for r in rows])


class TestBatchDataFetcherBatchPaths:
    def test_fetch_daily_prices_batch_returns_dataframe(self):
        """批量 daily 拉取 — 返回 DataFrame 且含 ts_code 列。"""
        fetcher = BatchDataFetcher(use_batch=True, max_concurrency=4)
        expected = _make_daily_prices_df(
            [
                {"ts_code": "000001.SZ", "close": 10.0},
                {"ts_code": "000002.SZ", "close": 20.0},
            ]
        )
        with patch("src.screening.batch_data_fetcher.get_daily_price_batch", return_value=expected) as mock_batch:
            result = fetcher.fetch_daily_prices_batch("20260305")
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 2
        assert "ts_code" in result.columns
        mock_batch.assert_called_once_with("20260305")

    def test_fetch_daily_basic_batch_returns_dataframe(self):
        """批量 daily_basic 拉取 — 返回 DataFrame 且含 ts_code 列。"""
        fetcher = BatchDataFetcher(use_batch=True, max_concurrency=4)
        expected = _make_daily_basic_df(
            [
                {"ts_code": "000001.SZ", "turnover_rate": 1.5},
                {"ts_code": "000002.SZ", "turnover_rate": 2.5},
            ]
        )
        with patch("src.screening.batch_data_fetcher.get_daily_basic_batch", return_value=expected) as mock_batch:
            result = fetcher.fetch_daily_basic_batch("20260305")
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 2
        assert "ts_code" in result.columns
        mock_batch.assert_called_once_with("20260305")

    def test_batch_result_is_cached(self):
        """批量结果在 TTL 内重复请求应命中缓存，不重复调用底层。"""
        fetcher = BatchDataFetcher(use_batch=True, max_concurrency=4, cache_ttl_seconds=60)
        expected = _make_daily_prices_df([{"ts_code": "000001.SZ"}])
        with patch("src.screening.batch_data_fetcher.get_daily_price_batch", return_value=expected) as mock_batch:
            r1 = fetcher.fetch_daily_prices_batch("20260305")
            r2 = fetcher.fetch_daily_prices_batch("20260305")
        # 同 key 重复 → 底层只调用 1 次
        mock_batch.assert_called_once()
        # 两次返回 DataFrame 内容一致
        pd.testing.assert_frame_equal(r1, r2)

    def test_batch_failure_falls_back_to_singleton(self):
        """批量接口抛异常时返回 None（不抛给上游），并记录失败统计。"""
        fetcher = BatchDataFetcher(use_batch=True, max_concurrency=4)
        with patch("src.screening.batch_data_fetcher.get_daily_price_batch", side_effect=RuntimeError("upstream down")):
            result = fetcher.fetch_daily_prices_batch("20260305")
        assert result is None
        stats = fetcher.stats()
        assert stats["batch_failures"] >= 1


# ============================================================================
# USE_BATCH_FETCHER 环境变量 / 单 ticker 路径
# ============================================================================


class TestBatchDataFetcherEnvSwitch:
    def setup_method(self):
        reset_global_batch_data_fetcher()

    def teardown_method(self):
        reset_global_batch_data_fetcher()

    def test_is_batch_fetcher_enabled_default_true(self, monkeypatch):
        """默认开启（环境变量未设置时）。"""
        monkeypatch.delenv("USE_BATCH_FETCHER", raising=False)
        assert is_batch_fetcher_enabled() is True

    def test_is_batch_fetcher_disabled_by_env(self, monkeypatch):
        """环境变量 USE_BATCH_FETCHER=false → 关闭。"""
        monkeypatch.setenv("USE_BATCH_FETCHER", "false")
        assert is_batch_fetcher_enabled() is False

    def test_is_batch_fetcher_disabled_by_env_zero(self, monkeypatch):
        """环境变量 USE_BATCH_FETCHER=0 → 关闭。"""
        monkeypatch.setenv("USE_BATCH_FETCHER", "0")
        assert is_batch_fetcher_enabled() is False

    def test_is_batch_fetcher_enabled_by_env_true(self, monkeypatch):
        """环境变量 USE_BATCH_FETCHER=true → 开启。"""
        monkeypatch.setenv("USE_BATCH_FETCHER", "true")
        assert is_batch_fetcher_enabled() is True

    def test_fetcher_with_use_batch_false_skips_batch_call(self, monkeypatch):
        """use_batch=False 时不调用批量接口。"""
        fetcher = BatchDataFetcher(use_batch=False, max_concurrency=2)
        with patch("src.screening.batch_data_fetcher.get_daily_price_batch") as mock_batch:
            # 应当走单 ticker 路径
            with patch.object(fetcher, "_fetch_single_ticker_prices_sync", return_value=[]) as mock_single:
                asyncio.run(fetcher.fetch_prices_for_tickers(["000001.SZ", "000002.SZ"], "20260101", "20260305"))
        mock_batch.assert_not_called()
        assert mock_single.call_count == 2


# ============================================================================
# 并发 / Semaphore 行为
# ============================================================================


class TestBatchDataFetcherConcurrency:
    def test_semaphore_limits_concurrent_single_ticker_calls(self):
        """semaphore 应限制并发数不超过 max_concurrency。"""
        fetcher = BatchDataFetcher(use_batch=False, max_concurrency=2)
        active = 0
        peak = 0

        def slow_fetch(ticker: str, start_date: str, end_date: str) -> list:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            time.sleep(0.05)
            active -= 1
            return []

        with patch.object(fetcher, "_fetch_single_ticker_prices_sync", side_effect=slow_fetch):
            tickers = [f"{i:06d}.SZ" for i in range(10)]
            asyncio.run(fetcher.fetch_prices_for_tickers(tickers, "20260101", "20260305"))
        # peak should be at most 2
        assert peak <= 2

    def test_fetch_prices_for_tickers_returns_dict_by_ticker(self):
        """批量 ticker 接口返回 {ticker: data} 字典。"""
        fetcher = BatchDataFetcher(use_batch=False, max_concurrency=4)
        with patch.object(fetcher, "_fetch_single_ticker_prices_sync", return_value=[{"close": 10.0}]):
            result = asyncio.run(fetcher.fetch_prices_for_tickers(["000001.SZ", "000002.SZ"], "20260101", "20260305"))
        assert isinstance(result, dict)
        assert set(result.keys()) == {"000001.SZ", "000002.SZ"}
        assert result["000001.SZ"] == [{"close": 10.0}]


# ============================================================================
# Stats / 健康度
# ============================================================================


class TestBatchDataFetcherStats:
    def test_stats_tracks_batch_calls_and_fallbacks(self):
        """stats 应记录 batch_calls, batch_failures, single_ticker_calls, cache_hits。"""
        fetcher = BatchDataFetcher(use_batch=True, max_concurrency=4)
        expected = _make_daily_prices_df([{"ts_code": "000001.SZ"}])
        with patch("src.screening.batch_data_fetcher.get_daily_price_batch", return_value=expected):
            fetcher.fetch_daily_prices_batch("20260305")  # 1 batch
            fetcher.fetch_daily_prices_batch("20260305")  # 1 cache hit
        stats = fetcher.stats()
        assert stats["batch_calls"] == 1
        assert stats["cache_hits"] == 1


# ============================================================================
# reset_stats() — 全局单例多次调用间状态重置
# ============================================================================


class TestBatchDataFetcherResetStats:
    def test_reset_stats_clears_counters(self):
        """reset_stats() should zero all counters and clear cache."""
        fetcher = BatchDataFetcher(use_batch=True, max_concurrency=4)
        expected = _make_daily_prices_df([{"ts_code": "000001.SZ"}])
        with patch("src.screening.batch_data_fetcher.get_daily_price_batch", return_value=expected):
            fetcher.fetch_daily_prices_batch("20260305")
            fetcher.fetch_daily_prices_batch("20260305")
        stats_before = fetcher.stats()
        assert stats_before["batch_calls"] == 1
        assert stats_before["cache_hits"] == 1
        assert stats_before["cache_size"] == 1

        fetcher.reset_stats()
        stats_after = fetcher.stats()
        assert stats_after["batch_calls"] == 0
        assert stats_after["batch_failures"] == 0
        assert stats_after["single_ticker_calls"] == 0
        assert stats_after["cache_hits"] == 0
        assert stats_after["cache_size"] == 0

    def test_reset_stats_then_fresh_call_works(self):
        """After reset_stats(), the fetcher should work again from scratch."""
        fetcher = BatchDataFetcher(use_batch=True, max_concurrency=4)
        expected = _make_daily_prices_df([{"ts_code": "000001.SZ"}])
        with patch("src.screening.batch_data_fetcher.get_daily_price_batch", return_value=expected):
            fetcher.fetch_daily_prices_batch("20260305")
        fetcher.reset_stats()

        with patch("src.screening.batch_data_fetcher.get_daily_price_batch", return_value=expected):
            result = fetcher.fetch_daily_prices_batch("20260305")
        assert isinstance(result, pd.DataFrame)
        stats = fetcher.stats()
        assert stats["batch_calls"] == 1
        assert stats["cache_hits"] == 0

    def test_global_fetcher_stats_reset_between_runs(self):
        """Global singleton: reset_stats() gives per-run stats isolation."""
        reset_global_batch_data_fetcher()
        try:
            fetcher1 = get_global_batch_data_fetcher()
            expected = _make_daily_prices_df([{"ts_code": "000001.SZ"}])
            with patch("src.screening.batch_data_fetcher.get_daily_price_batch", return_value=expected):
                fetcher1.fetch_daily_prices_batch("20260305")
            assert fetcher1.stats()["batch_calls"] == 1

            fetcher1.reset_stats()
            assert fetcher1.stats()["batch_calls"] == 0

            with patch("src.screening.batch_data_fetcher.get_daily_price_batch", return_value=expected):
                fetcher1.fetch_daily_prices_batch("20260306")
            assert fetcher1.stats()["batch_calls"] == 1
        finally:
            reset_global_batch_data_fetcher()


# ============================================================================
# Integration gap test: batch_fetcher is NOT passed to downstream scoring
# ============================================================================


class TestBatchFetcherIntegrationGap:
    def test_score_batch_signature_has_no_batch_fetcher_param(self):
        """GAMMA-008: score_batch() does not accept a batch_fetcher parameter.

        This test documents the current integration gap:
        run_auto_screening() creates BatchDataFetcher but score_batch(),
        build_candidate_pool(), and fuse_batch() have no batch_fetcher parameter,
        so the fetcher is decorative-only and does not accelerate anything.
        When the gap is fixed, this test should be updated/removed.
        """
        import inspect

        from src.screening.strategy_scorer import score_batch

        sig = inspect.signature(score_batch)
        assert "batch_fetcher" not in sig.parameters, "score_batch now accepts batch_fetcher — update this test and remove the integration gap note"

    def test_build_candidate_pool_signature_has_no_batch_fetcher_param(self):
        """GAMMA-008: build_candidate_pool() does not accept batch_fetcher."""
        import inspect

        from src.screening.candidate_pool import build_candidate_pool

        sig = inspect.signature(build_candidate_pool)
        assert "batch_fetcher" not in sig.parameters, "build_candidate_pool now accepts batch_fetcher — update this test and remove the integration gap note"

    def test_fuse_batch_signature_has_no_batch_fetcher_param(self):
        """GAMMA-008: fuse_batch() does not accept batch_fetcher."""
        import inspect

        from src.screening.signal_fusion import fuse_batch

        sig = inspect.signature(fuse_batch)
        assert "batch_fetcher" not in sig.parameters, "fuse_batch now accepts batch_fetcher — update this test and remove the integration gap note"


# ============================================================================
# R20: BatchDataFetcher 公开缓存方法 (has_cached / get_cached)
# ============================================================================


class TestBatchDataFetcherPublicCacheAccessors:
    """R20: 公开 has_cached() / get_cached() 方法替代直接访问 _cache。"""

    def test_has_cached_returns_false_for_missing_key(self):
        """未缓存的 key 返回 False。"""
        fetcher = BatchDataFetcher(use_batch=True)
        assert fetcher.has_cached("nonexistent_key") is False

    def test_has_cached_returns_true_after_set(self):
        """set 之后 has_cached 返回 True。"""
        fetcher = BatchDataFetcher(use_batch=True)
        fetcher._cache.set("test_key", {"foo": "bar"})
        assert fetcher.has_cached("test_key") is True

    def test_get_cached_returns_value(self):
        """get_cached 返回缓存值。"""
        fetcher = BatchDataFetcher(use_batch=True)
        fetcher._cache.set("test_key", [1, 2, 3])
        assert fetcher.get_cached("test_key") == [1, 2, 3]

    def test_get_cached_returns_none_for_missing_key(self):
        """未缓存的 key 返回 None (与 BatchDataCache.get 一致)。"""
        fetcher = BatchDataFetcher(use_batch=True)
        assert fetcher.get_cached("nonexistent_key") is None


# ============================================================================
# R20: 单 ticker 路径共享批量缓存
# ============================================================================


class TestSingleTickerBatchCacheSharing:
    """R20: _fetch_single_ticker_prices_sync 应优先命中批量缓存, 避免重复拉 tushare。"""

    def test_single_ticker_hits_batch_cache(self):
        """批量缓存命中时, 单 ticker 路径直接 filter, 不调 tushare。"""
        fetcher = BatchDataFetcher(use_batch=True, max_concurrency=2)
        # 预先填充批量缓存
        batch_df = _make_daily_prices_df(
            [
                {"ts_code": "000001.SZ", "close": 10.5, "trade_date": "20260601"},
                {"ts_code": "000002.SZ", "close": 20.5, "trade_date": "20260601"},
            ]
        )
        fetcher._cache.set("daily_price_batch:20260601", batch_df)

        # 不 patch 底层 tushare, 走原同步方法
        result = fetcher._fetch_single_ticker_prices_sync("000001", "20260601", "20260601")

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["ts_code"] == "000001.SZ"
        assert result[0]["close"] == 10.5
        assert result[0]["trade_date"] == "20260601"

    def test_single_ticker_not_in_batch_returns_empty(self):
        """批量缓存命中但 ticker 不在批量结果中 -> 返回空列表 (视为停牌/未上市)。"""
        fetcher = BatchDataFetcher(use_batch=True, max_concurrency=2)
        batch_df = _make_daily_prices_df(
            [
                {"ts_code": "000001.SZ", "close": 10.5, "trade_date": "20260601"},
            ]
        )
        fetcher._cache.set("daily_price_batch:20260601", batch_df)

        result = fetcher._fetch_single_ticker_prices_sync("000999", "20260601", "20260601")
        assert result == []

    def test_single_ticker_cache_miss_falls_back_to_tushare(self):
        """批量缓存未命中时, 走原 tushare 路径。"""
        fetcher = BatchDataFetcher(use_batch=True, max_concurrency=2)
        # 模拟底层 tushare 调用 (从 tushare_api 源模块 patch, 因为 _fetch_single_ticker_prices_sync
        # 内部使用的是函数体内 import 的本地引用)
        import src.tools.tushare_api as tushare_api_module

        mock_df = _make_daily_prices_df(
            [
                {"ts_code": "000001.SZ", "close": 10.5, "trade_date": "20260601"},
            ]
        )

        with patch.object(tushare_api_module, "_get_pro", return_value=MagicMock()):
            with patch.object(tushare_api_module, "_cached_tushare_dataframe_call", return_value=mock_df) as mock_call:
                result = fetcher._fetch_single_ticker_prices_sync("000001", "20260601", "20260601")

        mock_call.assert_called_once()
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["ts_code"] == "000001.SZ"

        # 命中走 tushare 成功路径, 不应记 cache_miss
        stats = fetcher.stats()
        assert stats["single_ticker_cache_misses"] == 0

    def test_single_ticker_tushare_exception_records_fetch_error(self):
        """c281: tushare 异常时, 记 fetch_errors (NOT cache_misses).

        旧 bug: except Exception: self._single_ticker_cache_misses += 1
        (语义错误 — cache miss 是确定性无数据, fetch error 是异常)
        新行为: except Exception: self._single_ticker_fetch_errors += 1
        """
        fetcher = BatchDataFetcher(use_batch=True, max_concurrency=2)
        import src.tools.tushare_api as tushare_api_module

        with patch.object(tushare_api_module, "_get_pro", return_value=MagicMock()):
            with patch.object(tushare_api_module, "_cached_tushare_dataframe_call", side_effect=RuntimeError("tushare down")):
                result = fetcher._fetch_single_ticker_prices_sync("000001", "20260601", "20260601")

        assert result == []
        stats = fetcher.stats()
        # c281: fetch error 应记 fetch_errors (NOT cache_misses)
        assert stats["single_ticker_fetch_errors"] >= 1
        assert stats["single_ticker_cache_misses"] == 0

    def test_single_ticker_tushare_empty_records_miss(self):
        """tushare 返回空 DataFrame 时, 记 cache_miss。"""
        fetcher = BatchDataFetcher(use_batch=True, max_concurrency=2)
        import src.tools.tushare_api as tushare_api_module

        with patch.object(tushare_api_module, "_get_pro", return_value=MagicMock()):
            with patch.object(tushare_api_module, "_cached_tushare_dataframe_call", return_value=pd.DataFrame()):
                result = fetcher._fetch_single_ticker_prices_sync("000001", "20260601", "20260601")

        assert result == []
        stats = fetcher.stats()
        assert stats["single_ticker_cache_misses"] >= 1

    def test_single_ticker_cache_hit_increments_stats(self):
        """缓存命中时, single_ticker_cache_hits 计数 +1, cache_hits 也 +1。"""
        fetcher = BatchDataFetcher(use_batch=True, max_concurrency=2)
        batch_df = _make_daily_prices_df([{"ts_code": "000001.SZ", "close": 10.5, "trade_date": "20260601"}])
        fetcher._cache.set("daily_price_batch:20260601", batch_df)

        before_hits = fetcher.stats()["single_ticker_cache_hits"]
        before_cache_hits = fetcher.stats()["cache_hits"]
        result = fetcher._fetch_single_ticker_prices_sync("000001", "20260601", "20260601")
        assert len(result) == 1

        stats = fetcher.stats()
        assert stats["single_ticker_cache_hits"] == before_hits + 1
        assert stats["cache_hits"] == before_cache_hits + 1

    def test_batch_df_missing_ts_code_column_falls_back(self):
        """批量缓存存在但缺少 ts_code 列 -> 回退到 tushare, 记 cache_miss。"""
        fetcher = BatchDataFetcher(use_batch=True, max_concurrency=2)
        # 故意构造缺少 ts_code 的 DataFrame
        bad_df = pd.DataFrame({"trade_date": ["20260601"], "close": [10.0]})
        fetcher._cache.set("daily_price_batch:20260601", bad_df)

        import src.tools.tushare_api as tushare_api_module

        mock_df = _make_daily_prices_df([{"ts_code": "000001.SZ", "close": 10.5}])
        with patch.object(tushare_api_module, "_get_pro", return_value=MagicMock()):
            with patch.object(tushare_api_module, "_cached_tushare_dataframe_call", return_value=mock_df):
                result = fetcher._fetch_single_ticker_prices_sync("000001", "20260601", "20260601")

        assert len(result) == 1
        assert fetcher.stats()["single_ticker_cache_misses"] >= 1


# ============================================================================
# R20: 集成 — preheater 预热后, 单 ticker 自动命中
# ============================================================================


class TestPreheatSingleTickerIntegration:
    """R20 集成验证: preheater 预热 daily_price_batch 后,
    单 ticker 路径自动命中, 不再调 tushare。"""

    def test_preheat_then_single_ticker_auto_hits(self):
        """preheater 写入批量缓存后, _fetch_single_ticker_prices_sync 不调 tushare。"""
        from src.screening import batch_data_fetcher
        from src.screening.batch_data_fetcher import (
            get_global_batch_data_fetcher,
            reset_global_batch_data_fetcher,
        )

        reset_global_batch_data_fetcher()
        try:
            from src.data.cache_preheater import _fetch_daily_prices

            sample = _make_daily_prices_df(
                [
                    {"ts_code": "000001.SZ", "close": 10.5, "trade_date": "20260601"},
                    {"ts_code": "000002.SZ", "close": 20.5, "trade_date": "20260601"},
                ]
            )
            with patch.object(batch_data_fetcher, "get_daily_price_batch", return_value=sample):
                preheat_result = _fetch_daily_prices("20260601", force=True)
            assert preheat_result is not None

            # 模拟下游: 单 ticker 价格拉取。函数内 import 引用 src.tools.tushare_api,
            # patch 源模块 (而非 batch_data_fetcher)。
            import src.tools.tushare_api as tushare_api_module

            fetcher = get_global_batch_data_fetcher()
            with patch.object(tushare_api_module, "_get_pro") as mock_pro, patch.object(tushare_api_module, "_cached_tushare_dataframe_call") as mock_tushare_call:
                mock_pro.return_value = MagicMock()
                result = fetcher._fetch_single_ticker_prices_sync("000001", "20260601", "20260601")

            # 单 ticker 应从批量缓存读取, 底层 _cached_tushare_dataframe_call 不应被调
            mock_tushare_call.assert_not_called()
            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0]["ts_code"] == "000001.SZ"
            assert result[0]["close"] == 10.5

            # 命中统计应反映
            stats = fetcher.stats()
            assert stats["single_ticker_cache_hits"] >= 1
        finally:
            reset_global_batch_data_fetcher()
