from typing import Callable, List

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


def load_prices_with_fallback(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    period: str,
    ak_module,
    fetch_prices_from_akshare_fn: Callable[..., List[Price] | None],
    fetch_prices_from_tencent_fn: Callable[..., List[Price]],
    cache_prices_fn: Callable[[str, List[Price]], List[Price]],
    cache_key: str,
    error_factory: Callable[[str], Exception],
) -> List[Price]:
    try:
        akshare_prices = fetch_prices_from_akshare_fn(ak_module, ticker, start_date, end_date, period)
        if akshare_prices:
            return cache_prices_fn(cache_key, akshare_prices)
    except Exception as error:
        print(f"AKShare 获取数据失败，尝试腾讯接口: {error}")

    try:
        prices = fetch_prices_from_tencent_fn(ticker, start_date, end_date)
        if prices:
            return cache_prices_fn(cache_key, prices)
    except Exception as error:
        raise error_factory(
            f"无法获取股票 {ticker} 的历史数据（所有数据源都失败）。\n"
            f"AKShare 错误: {error}\n"
            f"腾讯接口错误: {error}\n"
            "请检查网络连接，或使用 use_mock=True 参数使用模拟数据。"
        )

    return []
