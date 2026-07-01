"""NS-17 sibling: trade_cal failure must use logger, not print().

Characterization test locking in the fix at engine_market_data.py:161 —
previously a ``print()`` residual violated the structured-logging convention
(project rule: 生产级代码使用日志库替代 print/console.log). When the
backtest engine is invoked by cron / long-running process, print() output
is lost to stdout instead of entering structured logs, so operators cannot
diagnose trade_cal fetch failures.

Sibling of NS-17 (which fixed print() in app/backend services). This test
ensures the fallback path emits via ``logger.warning`` so the event is
captured by the logging infrastructure.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import pandas as pd

from src.backtesting.engine_market_data import MarketDataLoader


def _make_minimal_loader() -> MarketDataLoader:
    """Build a MarketDataLoader with just enough state to call trading_days()."""
    return MarketDataLoader(
        tickers=["000001.SZ"],
        start_date="2024-01-01",
        end_date="2024-01-31",
        portfolio=object(),  # trading_days() never touches portfolio
        exit_reentry_cooldowns={},
    )


def test_trade_cal_failure_uses_logger_not_print(caplog):
    """trade_cal fetch failure must emit via logger.warning, not print().

    Regression guard for the NS-17 sibling fix at engine_market_data.py:161.
    Injects a failure in get_open_trade_dates and asserts a WARNING record
    is emitted (not printed to stdout).
    """
    loader = _make_minimal_loader()

    with patch(
        "src.tools.tushare_api.get_open_trade_dates",
        side_effect=RuntimeError("simulated tushare timeout"),
    ):
        with caplog.at_level(logging.WARNING, logger="src.backtesting.engine_market_data"):
            result = loader.iter_backtest_dates()

    # Fallback path must return a business-day calendar
    assert isinstance(result, pd.DatetimeIndex)
    assert len(result) > 0

    # The failure must be logged at WARNING level (not printed)
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) == 1, f"expected 1 WARNING, got {len(warning_records)}"
    assert "trade_cal" in warning_records[0].message
    assert "freq=B" in warning_records[0].message
    assert "simulated tushare timeout" in warning_records[0].message
