"""Price frame normalization and next-day outcome extraction for BTST historical priors.

Extracted from historical_prior.py during R20.16 refactoring.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.paper_trading.btst_reporting_utils import _as_float
from src.tools.akshare_api import get_prices_robust
from src.tools.api import get_price_data, prices_to_df


def _normalize_price_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    normalized = frame.copy()
    if not isinstance(normalized.index, pd.DatetimeIndex):
        normalized.index = pd.to_datetime(normalized.index)
    normalized = normalized.sort_index()
    normalized.columns = [str(column).lower() for column in normalized.columns]
    return normalized


def _extract_next_day_outcome(ticker: str, trade_date: str, price_cache: dict[tuple[str, str], pd.DataFrame]) -> dict[str, Any]:
    cache_key = (ticker, trade_date)
    frame = price_cache.get(cache_key)
    if frame is None:
        end_date = (pd.Timestamp(trade_date) + pd.Timedelta(days=10)).strftime("%Y-%m-%d")
        try:
            frame = _normalize_price_frame(prices_to_df(get_prices_robust(ticker, trade_date, end_date, use_mock_on_fail=False)))
        except Exception:
            try:
                frame = _normalize_price_frame(get_price_data(ticker, trade_date, end_date))
            except Exception:
                frame = pd.DataFrame()
        price_cache[cache_key] = frame
    if frame.empty:
        return {"data_status": "missing_price_frame"}

    trade_ts = pd.Timestamp(trade_date)
    same_day = frame.loc[frame.index.normalize() == trade_ts.normalize()]
    next_day = frame.loc[frame.index.normalize() > trade_ts.normalize()]
    if same_day.empty:
        return {"data_status": "missing_trade_day_bar"}
    if next_day.empty:
        return {"data_status": "missing_next_trade_day_bar"}

    trade_row = same_day.iloc[0]
    next_row = next_day.iloc[0]
    trade_close = _as_float(trade_row.get("close"))
    next_open = _as_float(next_row.get("open"))
    next_high = _as_float(next_row.get("high"))
    next_close = _as_float(next_row.get("close"))
    # _as_float can return NaN for NaN/None numeric inputs; NaN comparisons
    # are always False, so the <= 0 guard would otherwise let NaN through and
    # silently poison next_open_return / next_close_return computations.
    if trade_close != trade_close or next_open != next_open or next_high != next_high or next_close != next_close or trade_close <= 0 or next_open <= 0 or next_high <= 0 or next_close <= 0:
        return {"data_status": "incomplete_price_bar"}

    return {
        "data_status": "ok",
        "next_trade_date": next_day.index[0].strftime("%Y-%m-%d"),
        "trade_close": round(trade_close, 4),
        "next_open": round(next_open, 4),
        "next_high": round(next_high, 4),
        "next_close": round(next_close, 4),
        "next_open_return": round((next_open / trade_close) - 1.0, 4),
        "next_high_return": round((next_high / trade_close) - 1.0, 4),
        "next_close_return": round((next_close / trade_close) - 1.0, 4),
        "next_open_to_close_return": round((next_close / next_open) - 1.0, 4),
    }
