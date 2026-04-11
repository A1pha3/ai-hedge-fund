from __future__ import annotations

from collections.abc import Callable

import pandas as pd


def fetch_process_cached_frame(
    *,
    cached_frame: pd.DataFrame | None,
    fetch_frame: Callable[[], pd.DataFrame | None],
    cache_frame: Callable[[pd.DataFrame], None],
) -> pd.DataFrame | None:
    if cached_frame is not None:
        return cached_frame.copy()

    df = fetch_frame()
    if df is None or df.empty:
        return None

    cache_frame(df)
    return df.copy()


def fetch_batch_cached_frame(
    *,
    cache_key: str,
    get_cached_df: Callable[[str], pd.DataFrame | None],
    store_cached_df: Callable[[str, pd.DataFrame], None],
    fetch_frame: Callable[[], pd.DataFrame | None],
) -> pd.DataFrame | None:
    cached_df = get_cached_df(cache_key)
    if cached_df is not None:
        return cached_df

    df = fetch_frame()
    if df is None or df.empty:
        return None

    store_cached_df(cache_key, df)
    return df.copy()
