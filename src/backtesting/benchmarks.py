from __future__ import annotations

import logging

import pandas as pd

from src.tools.api import get_price_data

logger = logging.getLogger(__name__)


class BenchmarkCalculator:
    def get_return_pct(self, ticker: str, start_date: str, end_date: str) -> float | None:
        """Compute simple buy-and-hold return % for ticker from start_date to end_date.

        Return is (last_close / first_close - 1) * 100, or None if unavailable.
        """
        try:
            df = get_price_data(ticker, start_date, end_date)
            if df.empty:
                return None
            first_close = df.iloc[0]["close"]
            last_close = df.iloc[-1]["close"]
            if first_close is None or pd.isna(first_close):
                return None
            if last_close is None or pd.isna(last_close):
                # Try last valid close
                last_valid = df["close"].dropna()
                if last_valid.empty:
                    return None
                last_close = float(last_valid.iloc[-1])
            return (float(last_close) / float(first_close) - 1.0) * 100.0
        except Exception as exc:
            # BH-017 family (R50 same-family): benchmark failure degrades the
            # backtest excess-return comparison to None silently. Emit a debug
            # log so operators can diagnose why the benchmark column went missing
            # instead of a silent empty column. Behavior unchanged (still None).
            logger.debug(
                "benchmark return calc failed for %s (%s -> %s): %s — " "excess/benchmark columns will be unavailable",
                ticker,
                start_date,
                end_date,
                exc,
            )
            return None
