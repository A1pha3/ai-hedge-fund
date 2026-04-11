from datetime import datetime, timedelta

import pandas as pd


def fallback_trade_date_dataframe(fetch_dataframe, pro, trade_fmt: str, fields: str):
    try:
        end_dt = datetime.strptime(trade_fmt, "%Y%m%d")
        start_dt = end_dt - timedelta(days=30)
        df_cal = fetch_dataframe(pro, "trade_cal", exchange="", start_date=start_dt.strftime("%Y%m%d"), end_date=trade_fmt, is_open=1, fields="cal_date,is_open")
        if df_cal is not None and not df_cal.empty:
            last_open = str(df_cal.iloc[-1]["cal_date"])
            return fetch_dataframe(pro, "daily", trade_date=last_open, fields=fields)
    except Exception:
        return None
    return None


def fill_missing_pct_change(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    missing_pct = pd.isna(result["pct_chg"])
    valid_pre_close = pd.notna(result["pre_close"]) & (result["pre_close"] != 0)
    result.loc[missing_pct & valid_pre_close, "pct_chg"] = (result.loc[missing_pct & valid_pre_close, "close"] - result.loc[missing_pct & valid_pre_close, "pre_close"]) / result.loc[missing_pct & valid_pre_close, "pre_close"] * 100
    return result


def build_stock_basic_maps(df_basic: pd.DataFrame | None) -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, str], dict[str, str], set[str]]:
    if df_basic is None or df_basic.empty:
        return {}, {}, {}, {}, {}, set()
    name_map = {str(row["ts_code"]): str(row["name"]) for _, row in df_basic.iterrows()}
    st_codes = {str(row["ts_code"]) for _, row in df_basic.iterrows() if "ST" in str(row["name"]).upper()}
    area_map = {str(row["ts_code"]): str(row["area"]) for _, row in df_basic.iterrows() if pd.notna(row["area"])}
    industry_map = {str(row["ts_code"]): str(row["industry"]) for _, row in df_basic.iterrows() if pd.notna(row["industry"])}
    market_map = {str(row["ts_code"]): str(row["market"]) for _, row in df_basic.iterrows() if pd.notna(row["market"])}
    list_date_map = {str(row["ts_code"]): str(row["list_date"]) for _, row in df_basic.iterrows() if pd.notna(row["list_date"])}
    return name_map, area_map, industry_map, market_map, list_date_map, st_codes


def build_daily_gainer_item(row, include_name: bool, name_map: dict[str, str], area_map: dict[str, str], industry_map: dict[str, str], market_map: dict[str, str], list_date_map: dict[str, str]) -> dict:
    date_str = str(row["trade_date"])
    item = {
        "ts_code": str(row["ts_code"]),
        "trade_date": f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}",
        "pct_chg": float(row["pct_chg"]),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "pre_close": float(row["pre_close"]) if "pre_close" in row and pd.notna(row["pre_close"]) else None,
        "vol": int(row["vol"]),
    }
    if "amount" in row and pd.notna(row["amount"]):
        item["amount"] = float(row["amount"])
    if include_name:
        ts_code = item["ts_code"]
        item["name"] = name_map.get(ts_code, ts_code)
        item["area"] = area_map.get(ts_code)
        item["industry"] = industry_map.get(ts_code)
        item["market"] = market_map.get(ts_code)
        item["list_date"] = list_date_map.get(ts_code)
    return item


def build_daily_gainers_with_tushare_data(
    *,
    pro,
    trade_fmt: str,
    pct_threshold: float,
    include_name: bool,
    fetch_dataframe,
    fallback_trade_date_dataframe_fn,
    fill_missing_pct_change_fn,
    build_stock_basic_maps_fn,
    build_daily_gainer_item_fn,
) -> list[dict]:
    fields = "ts_code,trade_date,open,high,low,close,pre_close,vol,amount,pct_chg"
    df = fetch_dataframe(pro, "daily", trade_date=trade_fmt, fields=fields)
    if df is None or df.empty:
        df = fallback_trade_date_dataframe_fn(fetch_dataframe, pro, trade_fmt, fields)
    if df is None or df.empty:
        return []

    df = fill_missing_pct_change_fn(df)
    df = df[pd.notna(df["pct_chg"])]
    df = df[df["pct_chg"] > pct_threshold]
    if df.empty:
        return []

    name_map: dict[str, str] = {}
    area_map: dict[str, str] = {}
    industry_map: dict[str, str] = {}
    market_map: dict[str, str] = {}
    list_date_map: dict[str, str] = {}
    st_codes: set[str] = set()
    if include_name:
        df_basic = fetch_dataframe(
            pro,
            "stock_basic",
            exchange="",
            list_status="L",
            fields="ts_code,name,area,industry,market,list_date",
        )
        name_map, area_map, industry_map, market_map, list_date_map, st_codes = build_stock_basic_maps_fn(df_basic)

    results = []
    df_sorted = df.sort_values("pct_chg", ascending=False)
    for _, row in df_sorted.iterrows():
        ts_code = str(row["ts_code"])
        if ts_code in st_codes:
            continue
        results.append(
            build_daily_gainer_item_fn(
                row,
                include_name,
                name_map,
                area_map,
                industry_map,
                market_map,
                list_date_map,
            )
        )
    return results
