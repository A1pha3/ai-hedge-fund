from __future__ import annotations

import logging
from collections.abc import Callable

import pandas as pd

# NS-17 / BH-017 family sibling drain: 可选市场帧 (index/northbound) 拉取失败此前用
# print, 在 cron 上下文不可见, 运维无法定位"为何市场数据缺失"。
logger = logging.getLogger(__name__)


def load_optional_market_dataframe(
    *,
    is_available: bool,
    unavailable_message: str,
    fetch_dataframe_fn: Callable[[], pd.DataFrame | None],
    error_message: str,
    transform_fn: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
) -> pd.DataFrame | None:
    if not is_available:
        logger.warning("%s", unavailable_message)
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
        logger.warning("%s: %s", error_message, error, exc_info=True)
        return None
