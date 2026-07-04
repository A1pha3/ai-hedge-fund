"""NS-17/BH-017 同族 — batch_data_fetcher.py silent except observability.

AutoDev C11/Loop 12 (c281): drains 2 silent except patterns in
batch_data_fetcher.py + fixes cache miss counter bug.

Drain pattern:
- _cached_batch_call (L234, batch fetch failure) → WARNING
  (罕见且关键 — 触发数千次单 ticker fallback 风暴)
- _fetch_single_ticker_prices_sync (L308, per-ticker fetch failure) → DEBUG
  (热路径 — 批量失败时可能并发触发数千 ticker, WARNING 会刷屏)

Counter bug fix (c281):
- 旧: tushare API 异常 → `_single_ticker_cache_misses += 1` (语义错误 —
  cache miss 是确定性无数据, fetch error 是异常)
- 新: tushare API 异常 → `_single_ticker_fetch_errors += 1` (严格区分)
- `df is None or df.empty` 路径仍记 cache_miss (确定性无数据, 行为不变)

Tests verify:
1. batch fetch failure → WARNING with cache_key + exc context + batch_failures counter
2. per-ticker fetch failure → DEBUG with ticker + start/end + exc context
3. per-ticker fetch failure → _single_ticker_fetch_errors counter (NOT cache_misses)
4. per-ticker empty df → _single_ticker_cache_misses counter (NOT fetch_errors)
5. success paths: no WARNING / DEBUG emitted
6. stats() includes new single_ticker_fetch_errors field
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pandas as pd

from src.screening.batch_data_fetcher import BatchDataFetcher


def _make_daily_prices_df(rows: list[dict]) -> pd.DataFrame:
    """构造 daily prices DataFrame (与现有测试一致的 helper)."""
    if not rows:
        return pd.DataFrame()
    defaults = {
        "open": 10.0,
        "high": 10.5,
        "low": 9.5,
        "close": 10.0,
        "pre_close": 9.9,
        "vol": 1000.0,
        "amount": 10000.0,
        "pct_chg": 0.1,
    }
    return pd.DataFrame([{**defaults, **r} for r in rows])


# ---------------------------------------------------------------------------
# Position 1: _cached_batch_call (L234) — batch fetch failure → WARNING
# ---------------------------------------------------------------------------


class TestBatchFetchFailureObservability:
    """batch fetch 失败应发 WARNING (罕见且关键, 触发 fallback 风暴)."""

    def test_batch_failure_emits_warning_with_cache_key(self, caplog) -> None:
        """batch fetch raise → WARNING 含 cache_key + exc 上下文."""
        fetcher = BatchDataFetcher(use_batch=True, max_concurrency=4)
        with caplog.at_level(logging.WARNING, logger="src.screening.batch_data_fetcher"):
            with patch(
                "src.screening.batch_data_fetcher.get_daily_price_batch",
                side_effect=RuntimeError("tushare upstream down"),
            ):
                result = fetcher.fetch_daily_prices_batch("20260305")
        # best-effort: 返回 None (调用方决定是否降级)
        assert result is None
        # WARNING 发出, 含 cache_key + exc
        warn_records = [r for r in caplog.records if r.levelno == logging.WARNING and "batch fetch failed" in r.getMessage() and "daily_price_batch:20260305" in r.getMessage()]
        assert len(warn_records) == 1, f"expected 1 WARNING for batch fetch failure, got {warn_records}"

    def test_batch_failure_increments_batch_failures_counter(self, caplog) -> None:
        """batch fetch raise → stats().batch_failures 累加 (向后兼容)."""
        fetcher = BatchDataFetcher(use_batch=True, max_concurrency=4)
        with caplog.at_level(logging.WARNING, logger="src.screening.batch_data_fetcher"):
            with patch(
                "src.screening.batch_data_fetcher.get_daily_price_batch",
                side_effect=ConnectionError("network timeout"),
            ):
                fetcher.fetch_daily_prices_batch("20260305")
        stats = fetcher.stats()
        assert stats["batch_failures"] >= 1

    def test_batch_success_no_warning(self, caplog) -> None:
        """batch fetch 成功路径不应发 WARNING."""
        fetcher = BatchDataFetcher(use_batch=True, max_concurrency=4)
        expected = _make_daily_prices_df([{"ts_code": "000001.SZ", "close": 10.0}])
        with caplog.at_level(logging.WARNING, logger="src.screening.batch_data_fetcher"):
            with patch(
                "src.screening.batch_data_fetcher.get_daily_price_batch",
                return_value=expected,
            ):
                result = fetcher.fetch_daily_prices_batch("20260305")
        assert result is not None
        warn_records = [r for r in caplog.records if r.levelno == logging.WARNING and "batch fetch failed" in r.getMessage()]
        assert len(warn_records) == 0, f"success path should not emit WARNING, got {warn_records}"


# ---------------------------------------------------------------------------
# Position 2: _fetch_single_ticker_prices_sync (L308) — per-ticker fetch failure → DEBUG
# ---------------------------------------------------------------------------


class TestSingleTickerFetchFailureObservability:
    """per-ticker fetch 失败应发 DEBUG (热路径, 避免 WARNING 刷屏)."""

    def test_single_ticker_failure_emits_debug_with_ticker(self, caplog) -> None:
        """tushare API raise → DEBUG 含 ticker + start/end + exc 上下文."""
        fetcher = BatchDataFetcher(use_batch=True, max_concurrency=2)
        import src.tools.tushare_api as tushare_api_module

        with patch.object(tushare_api_module, "_get_pro", return_value=MagicMock()):
            with patch.object(
                tushare_api_module,
                "_cached_tushare_dataframe_call",
                side_effect=RuntimeError("tushare rate limit"),
            ):
                with caplog.at_level(logging.DEBUG, logger="src.screening.batch_data_fetcher"):
                    result = fetcher._fetch_single_ticker_prices_sync("000001", "20260601", "20260601")
        # best-effort: 返回 []
        assert result == []
        # DEBUG 发出, 含 ticker + start + end + exc
        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG and "single-ticker fetch failed" in r.getMessage() and "ticker=000001" in r.getMessage() and "start=20260601" in r.getMessage() and "end=20260601" in r.getMessage()]
        assert len(debug_records) == 1, f"expected 1 DEBUG for single-ticker fetch failure, got {debug_records}"

    def test_single_ticker_failure_increments_fetch_errors_not_cache_miss(self, caplog) -> None:
        """c281 修复: tushare API 异常应记 fetch_errors, 不应记 cache_misses.

        旧 bug: except Exception: self._single_ticker_cache_misses += 1
        (语义错误 — cache miss 是确定性无数据, fetch error 是异常)
        新行为: except Exception: self._single_ticker_fetch_errors += 1
        """
        fetcher = BatchDataFetcher(use_batch=True, max_concurrency=2)
        import src.tools.tushare_api as tushare_api_module

        with patch.object(tushare_api_module, "_get_pro", return_value=MagicMock()):
            with patch.object(
                tushare_api_module,
                "_cached_tushare_dataframe_call",
                side_effect=ConnectionError("network down"),
            ):
                fetcher._fetch_single_ticker_prices_sync("000001", "20260601", "20260601")

        stats = fetcher.stats()
        # fetch error 应记 fetch_errors
        assert stats["single_ticker_fetch_errors"] >= 1, f"fetch error should increment single_ticker_fetch_errors; " f"got stats={stats}"
        # 不应记 cache_misses (这是 c281 修复的核心 — 旧行为错误累加 cache_misses)
        assert stats["single_ticker_cache_misses"] == 0, f"fetch error should NOT increment single_ticker_cache_misses (c281 fix); " f"got stats={stats}"

    def test_single_ticker_empty_df_increments_cache_misses_not_fetch_errors(self, caplog) -> None:
        """c281 行为不变: tushare 返回空 DataFrame 仍记 cache_misses (确定性无数据).

        这与 fetch error 严格区分 — 空 df 是 tushare 明确返回无数据 (停牌/退市),
        而 fetch error 是网络/限频/鉴权异常.
        """
        fetcher = BatchDataFetcher(use_batch=True, max_concurrency=2)
        import src.tools.tushare_api as tushare_api_module

        with patch.object(tushare_api_module, "_get_pro", return_value=MagicMock()):
            with patch.object(
                tushare_api_module,
                "_cached_tushare_dataframe_call",
                return_value=pd.DataFrame(),  # 空 df = 确定性无数据
            ):
                with caplog.at_level(logging.DEBUG, logger="src.screening.batch_data_fetcher"):
                    result = fetcher._fetch_single_ticker_prices_sync("000001", "20260601", "20260601")

        assert result == []
        stats = fetcher.stats()
        # 空 df 应记 cache_misses (行为不变)
        assert stats["single_ticker_cache_misses"] >= 1, f"empty df should increment single_ticker_cache_misses; got stats={stats}"
        # 不应记 fetch_errors (没有异常)
        assert stats["single_ticker_fetch_errors"] == 0, f"empty df should NOT increment single_ticker_fetch_errors; got stats={stats}"
        # 不应发 DEBUG (没有异常)
        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG and "single-ticker fetch failed" in r.getMessage()]
        assert len(debug_records) == 0

    def test_single_ticker_success_no_debug(self, caplog) -> None:
        """per-ticker 成功路径不应发 DEBUG."""
        fetcher = BatchDataFetcher(use_batch=True, max_concurrency=2)
        import src.tools.tushare_api as tushare_api_module

        mock_df = _make_daily_prices_df([{"ts_code": "000001.SZ", "close": 10.5, "trade_date": "20260601"}])
        with patch.object(tushare_api_module, "_get_pro", return_value=MagicMock()):
            with patch.object(
                tushare_api_module,
                "_cached_tushare_dataframe_call",
                return_value=mock_df,
            ):
                with caplog.at_level(logging.DEBUG, logger="src.screening.batch_data_fetcher"):
                    result = fetcher._fetch_single_ticker_prices_sync("000001", "20260601", "20260601")

        assert len(result) == 1
        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG and "single-ticker fetch failed" in r.getMessage()]
        assert len(debug_records) == 0, f"success path should not emit DEBUG, got {debug_records}"


# ---------------------------------------------------------------------------
# stats() schema — new field single_ticker_fetch_errors
# ---------------------------------------------------------------------------


class TestStatsSchemaIncludesFetchErrors:
    """stats() 应包含新字段 single_ticker_fetch_errors (c281)."""

    def test_stats_includes_single_ticker_fetch_errors_field(self) -> None:
        """stats() dict 应包含 single_ticker_fetch_errors key."""
        fetcher = BatchDataFetcher(use_batch=True, max_concurrency=2)
        stats = fetcher.stats()
        assert "single_ticker_fetch_errors" in stats, f"stats() should include single_ticker_fetch_errors (c281); got keys={list(stats.keys())}"
        assert stats["single_ticker_fetch_errors"] == 0  # 初始值

    def test_reset_stats_resets_fetch_errors(self) -> None:
        """reset_stats() 应重置 _single_ticker_fetch_errors."""
        fetcher = BatchDataFetcher(use_batch=True, max_concurrency=2)
        import src.tools.tushare_api as tushare_api_module

        # 触发一次 fetch error
        with patch.object(tushare_api_module, "_get_pro", return_value=MagicMock()):
            with patch.object(
                tushare_api_module,
                "_cached_tushare_dataframe_call",
                side_effect=RuntimeError("boom"),
            ):
                fetcher._fetch_single_ticker_prices_sync("000001", "20260601", "20260601")

        assert fetcher.stats()["single_ticker_fetch_errors"] >= 1

        # reset 后应归零
        fetcher.reset_stats()
        assert fetcher.stats()["single_ticker_fetch_errors"] == 0
