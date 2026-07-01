from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd

# NS-17 / BH-017 family sibling drain: 本模块在 daily_basic (PE/PB/PS) 路径上,
# PE/PB 喂给 valuation + composite_score; 此前无 logger, 1 处 print() 在批量拉取
# 失败时静默回退空 df → 所有 PE/PB 查询 miss → valuation 退化, 运维无面包屑。
logger = logging.getLogger(__name__)


def load_daily_basic_batch(
    *,
    pro,
    ts_code: str,
    anchor_date: str,
    cache_key: str,
    get_cached_df,
    store_cached_df,
) -> pd.DataFrame | None:
    date_fmt = anchor_date.replace("-", "")
    df_batch = get_cached_df(cache_key)
    if df_batch is not None:
        return df_batch

    today_fmt = datetime.now().strftime("%Y%m%d")
    try:
        actual_end = max(date_fmt, today_fmt)
        date_obj = datetime.strptime(actual_end, "%Y%m%d")
    except Exception:
        return None

    # 2-year lookback window is intentional: daily_basic fields (PE, PB, PS, etc.)
    # change slowly and most are only updated quarterly. A 2-year window ensures
    # we always have enough history for single-query cache hits without needing
    # incremental fetches.  The `lookback_days` parameter is NOT used here because
    # the fixed 730-day window is the deliberate design choice.
    start_fmt = (date_obj - timedelta(days=730)).strftime("%Y%m%d")
    try:
        df_batch = pro.query("daily_basic", ts_code=ts_code, start_date=start_fmt, end_date=actual_end)
        if df_batch is not None and not df_batch.empty and "trade_date" in df_batch.columns:
            df_batch = df_batch.sort_values("trade_date", ascending=False).reset_index(drop=True)
    except Exception as exc:
        logger.warning("[Tushare] daily_basic 批量获取(%s, %s~%s) 失败: %s", ts_code, start_fmt, actual_end, exc, exc_info=True)
        df_batch = pd.DataFrame()

    store_cached_df(cache_key, df_batch)
    return df_batch


def select_latest_daily_basic_row(df_batch: pd.DataFrame | None, anchor_date: str) -> dict | None:
    if df_batch is None or df_batch.empty:
        return None

    date_fmt = anchor_date.replace("-", "")
    filtered = df_batch[df_batch["trade_date"] <= date_fmt]
    if filtered.empty:
        return None
    return filtered.iloc[0].to_dict()
