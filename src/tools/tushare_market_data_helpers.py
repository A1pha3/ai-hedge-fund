from __future__ import annotations

from collections.abc import Callable

import pandas as pd


def build_index_daily_query_kwargs(index_code: str, start_date: str, end_date: str, limit: int) -> dict[str, str | int]:
    kwargs: dict[str, str | int] = {"ts_code": index_code}
    if start_date:
        kwargs["start_date"] = start_date
    if end_date:
        kwargs["end_date"] = end_date
    if not start_date and not end_date:
        kwargs["limit"] = limit
    return kwargs


def build_northbound_flow_query_kwargs(trade_date: str, start_date: str, end_date: str, limit: int) -> dict[str, str | int]:
    kwargs: dict[str, str | int] = {}
    if trade_date:
        kwargs["trade_date"] = trade_date
    if start_date:
        kwargs["start_date"] = start_date
    if end_date:
        kwargs["end_date"] = end_date
    if not trade_date and not start_date:
        kwargs["limit"] = limit
    return kwargs


def fetch_sorted_cached_market_frame(
    *,
    cache_key: str,
    get_cached_df: Callable[[str], pd.DataFrame | None],
    store_cached_df: Callable[[str, pd.DataFrame], None],
    fetch_frame: Callable[[], pd.DataFrame | None],
    sort_column: str = "trade_date",
) -> pd.DataFrame | None:
    cached_df = get_cached_df(cache_key)
    if cached_df is not None:
        return cached_df

    df = fetch_frame()
    if df is None or df.empty:
        return None

    sorted_df = df.sort_values(sort_column).reset_index(drop=True)
    store_cached_df(cache_key, sorted_df)
    return sorted_df.copy()
