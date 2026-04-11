from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd


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

    start_fmt = (date_obj - timedelta(days=730)).strftime("%Y%m%d")
    try:
        df_batch = pro.query("daily_basic", ts_code=ts_code, start_date=start_fmt, end_date=actual_end)
        if df_batch is not None and not df_batch.empty and "trade_date" in df_batch.columns:
            df_batch = df_batch.sort_values("trade_date", ascending=False).reset_index(drop=True)
    except Exception as exc:
        print(f"[Tushare] daily_basic 批量获取({ts_code}, {start_fmt}~{actual_end}) 失败: {exc}")
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
