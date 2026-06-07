"""筛选流水线性能回归测试 — P0-1。

对比 ``USE_BATCH_FETCHER=true`` (批量模式) 与 ``=false`` (串行模式) 的
调用次数和耗时差异。所有数据均 mock，不实际访问网络。
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pandas as pd
import pytest

from src.screening.batch_data_fetcher import BatchDataFetcher


def _make_daily_prices_df(tickers: list[str]) -> pd.DataFrame:
    rows = [
        {
            "ts_code": ts_code,
            "trade_date": "20260305",
            "open": 10.0,
            "high": 10.5,
            "low": 9.5,
            "close": 10.2,
            "pre_close": 10.0,
            "vol": 1.0,
            "amount": 1000.0,
            "pct_chg": 2.0,
        }
        for ts_code in tickers
    ]
    return pd.DataFrame(rows)


class TestBatchVsSerial:
    """对比批量与串行模式下的「调用次数」差异。"""

    def test_batch_mode_makes_one_call_for_all_tickers(self):
        """批量模式：5000 只 ticker 只需 1 次 daily 调用（mock 验证）。"""
        tickers = [f"{i:06d}.SZ" for i in range(5000)]
        fetcher = BatchDataFetcher(use_batch=True, max_concurrency=8)
        expected_df = _make_daily_prices_df(tickers[:100])  # 返回子集即可

        with patch("src.screening.batch_data_fetcher.get_daily_price_batch", return_value=expected_df) as mock_batch:
            result = fetcher.fetch_daily_prices_batch("20260305")

        assert mock_batch.call_count == 1
        assert isinstance(result, pd.DataFrame)
        # 即使 ticker 5000 只，底层调用只 1 次
        assert mock_batch.call_count == 1

    def test_serial_mode_makes_one_call_per_ticker(self):
        """串行模式：5000 只 ticker 需要 5000 次单 ticker daily 调用。"""
        import asyncio

        tickers = [f"{i:06d}.SZ" for i in range(50)]  # 用 50 加速测试
        fetcher = BatchDataFetcher(use_batch=False, max_concurrency=8)

        # 直接通过同步单 ticker 接口 mock
        with patch.object(
            fetcher,
            "_fetch_single_ticker_prices_sync",
            return_value=[{"close": 10.0}],
        ) as mock_single:
            asyncio.run(fetcher.fetch_prices_for_tickers(tickers, "20260101", "20260305"))

        assert mock_single.call_count == len(tickers)

    def test_batch_mode_reduces_calls_dramatically(self):
        """核心断言：批量模式调用次数应 < 串行模式调用次数 / N (N=批次大小)。"""
        import asyncio

        ticker_count = 100
        tickers = [f"{i:06d}.SZ" for i in range(ticker_count)]

        # 批量模式
        fetcher_batch = BatchDataFetcher(use_batch=True, max_concurrency=8)
        expected_df = _make_daily_prices_df(tickers[:10])
        with patch("src.screening.batch_data_fetcher.get_daily_price_batch", return_value=expected_df) as mock_batch:
            fetcher_batch.fetch_daily_prices_batch("20260305")
        batch_call_count = mock_batch.call_count

        # 串行模式
        fetcher_serial = BatchDataFetcher(use_batch=False, max_concurrency=8)
        with patch.object(fetcher_serial, "_fetch_single_ticker_prices_sync", return_value=[{"close": 10.0}]) as mock_single:
            asyncio.run(fetcher_serial.fetch_prices_for_tickers(tickers, "20260101", "20260305"))
        serial_call_count = mock_single.call_count

        # 批量应远少于串行
        assert batch_call_count == 1
        assert serial_call_count == ticker_count
        assert batch_call_count * 10 < serial_call_count  # 至少 10x 减少

    def test_batch_mode_wallclock_faster_than_serial_in_mock(self):
        """mock 环境下批量模式 wallclock 应 < 串行模式 (通过 sleep 模拟 IO 延迟)。"""
        import asyncio

        ticker_count = 20
        tickers = [f"{i:06d}.SZ" for i in range(ticker_count)]
        io_delay = 0.01  # 每次 mock 调用 10ms

        # 串行模式：每 ticker 10ms → 总 ~200ms
        fetcher_serial = BatchDataFetcher(use_batch=False, max_concurrency=8)

        def slow_single(ticker: str, start_date: str, end_date: str) -> list:
            time.sleep(io_delay)
            return [{"close": 10.0}]

        t0 = time.perf_counter()
        with patch.object(fetcher_serial, "_fetch_single_ticker_prices_sync", side_effect=slow_single):
            asyncio.run(fetcher_serial.fetch_prices_for_tickers(tickers, "20260101", "20260305"))
        serial_elapsed = time.perf_counter() - t0

        # 批量模式：1 次 10ms 调用
        fetcher_batch = BatchDataFetcher(use_batch=True, max_concurrency=8)
        expected_df = _make_daily_prices_df(tickers[:5])

        def slow_batch() -> pd.DataFrame:
            time.sleep(io_delay)
            return expected_df

        t0 = time.perf_counter()
        with patch("src.screening.batch_data_fetcher.get_daily_price_batch", side_effect=slow_batch):
            fetcher_batch.fetch_daily_prices_batch("20260305")
        batch_elapsed = time.perf_counter() - t0

        # 批量应显著快于串行 (至少 5x)
        assert batch_elapsed * 5 < serial_elapsed, (
            f"batch={batch_elapsed:.3f}s should be much less than serial={serial_elapsed:.3f}s"
        )
