from __future__ import annotations

from collections.abc import Callable

import pandas as pd


def load_optional_market_dataframe(
    *,
    is_available: bool,
    unavailable_message: str,
    fetch_dataframe_fn: Callable[[], pd.DataFrame | None],
    error_message: str,
    transform_fn: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
) -> pd.DataFrame | None:
    if not is_available:
        print(unavailable_message)
        return None

    try:
        df = fetch_dataframe_fn()
        if df is None or df.empty:
            return None
        if transform_fn is not None:
            df = transform_fn(df)
            if df is None or df.empty:
                return None
        return df
    except Exception as error:
        print(f"{error_message}: {error}")
        return None
