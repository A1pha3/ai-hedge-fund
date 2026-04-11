from __future__ import annotations

from typing import Any

import pandas as pd

from src.data.models import Price


def build_default_stock_details(ticker: str) -> dict[str, Any]:
    return {
        "name": ticker,
        "area": "N/A",
        "industry": "N/A",
        "market": "N/A",
        "list_date": "N/A",
        "pct_chg": "N/A",
        "pre_close": "N/A",
        "close": "N/A",
    }


def build_stock_basic_details(ticker: str, df_basic: pd.DataFrame | None) -> dict[str, Any]:
    basic_info = {
        "name": ticker,
        "area": "N/A",
        "industry": "N/A",
        "market": "N/A",
        "list_date": "N/A",
    }
    if df_basic is None or df_basic.empty:
        return basic_info

    row = df_basic.iloc[0]
    basic_info["name"] = str(row["name"]) if pd.notna(row["name"]) else ticker
    basic_info["area"] = str(row["area"]) if pd.notna(row["area"]) else "N/A"
    basic_info["industry"] = str(row["industry"]) if pd.notna(row["industry"]) else "N/A"
    basic_info["market"] = str(row["market"]) if pd.notna(row["market"]) else "N/A"
    basic_info["list_date"] = str(row["list_date"]) if pd.notna(row["list_date"]) else "N/A"
    return basic_info


def build_stock_price_details(df_daily: pd.DataFrame | None) -> dict[str, Any]:
    price_info = {
        "pct_chg": "N/A",
        "pre_close": "N/A",
        "close": "N/A",
    }
    if df_daily is None or df_daily.empty:
        return price_info

    row = df_daily.iloc[0]
    price_info["pct_chg"] = f"{float(row['pct_chg']):.2f}%" if pd.notna(row["pct_chg"]) else "N/A"
    price_info["pre_close"] = f"{float(row['pre_close']):.2f}" if pd.notna(row["pre_close"]) else "N/A"
    price_info["close"] = f"{float(row['close']):.2f}" if pd.notna(row["close"]) else "N/A"
    return price_info


def build_prices_from_tushare_daily_df(df: pd.DataFrame | None) -> list[Price]:
    if df is None or df.empty:
        return []

    prices: list[Price] = []
    for _, row in df.iterrows():
        date_str = str(row["trade_date"])
        prices.append(
            Price(
                time=f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}",
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row["vol"]),
            )
        )
    prices.reverse()
    return prices
