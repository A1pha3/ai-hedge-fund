from typing import List

import pandas as pd

from src.data.models import Price


def hydrate_cached_prices(cached_data: list[dict]) -> List[Price]:
    return [Price(**price) for price in cached_data]


def build_prices_from_dataframe(df: pd.DataFrame) -> List[Price]:
    prices: list[Price] = []
    for _, row in df.iterrows():
        prices.append(Price(time=row["日期"], open=float(row["开盘"]), high=float(row["最高"]), low=float(row["最低"]), close=float(row["收盘"]), volume=int(row["成交量"])))
    return prices


def dump_prices_for_cache(prices: List[Price]) -> list[dict]:
    return [price.model_dump() for price in prices]
