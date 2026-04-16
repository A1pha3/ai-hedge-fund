from collections.abc import Callable

import pandas as pd

from src.data.models import Price


def hydrate_cached_prices(cached_data: list[dict]) -> list[Price]:
    return [Price(**price) for price in cached_data]


def build_prices_from_dataframe(df: pd.DataFrame) -> list[Price]:
    prices: list[Price] = []
    for _, row in df.iterrows():
        prices.append(Price(time=row["日期"], open=float(row["开盘"]), high=float(row["最高"]), low=float(row["最低"]), close=float(row["收盘"]), volume=int(row["成交量"])))
    return prices


def dump_prices_for_cache(prices: list[Price]) -> list[dict]:
    return [price.model_dump() for price in prices]


def build_tencent_price_request(full_code: str, start_date: str, end_date: str) -> tuple[str, dict[str, str], dict[str, str]]:
    return (
        "http://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
        {"param": f"{full_code},day,{start_date},{end_date},640,qfq"},
        {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        },
    )


def build_prices_from_tencent_payload(data: dict, full_code: str, error_factory) -> list[Price]:
    if data.get("code") != 0:
        raise error_factory(f"腾讯接口返回错误: {data.get('msg', '未知错误')}")

    stock_data = data.get("data", {}).get(full_code, {})
    kline_data = stock_data.get("qfqday") or stock_data.get("day")
    if not kline_data:
        raise error_factory("腾讯接口返回空数据")

    return [
        Price(
            time=item[0],
            open=float(item[1]),
            close=float(item[2]),
            high=float(item[3]),
            low=float(item[4]),
            volume=int(float(item[5])),
        )
        for item in kline_data
    ]


def execute_tencent_price_request(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    resolve_ticker_fn,
    create_session_fn,
    error_factory,
) -> list[Price]:
    ashare = resolve_ticker_fn(ticker)
    url, params, headers = build_tencent_price_request(ashare.full_code, start_date, end_date)
    session = create_session_fn()
    response = session.get(url, params=params, headers=headers, timeout=30)
    response.raise_for_status()
    return build_prices_from_tencent_payload(response.json(), ashare.full_code, error_factory)


def execute_price_request(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    period: str,
    use_mock: bool,
    cache_key: str,
    cache,
    hydrate_cached_fn,
    get_mock_prices_fn,
    get_akshare_fn,
    load_prices_fn,
    error_factory,
) -> list[Price]:
    if cached_prices := cache.get_prices(cache_key):
        return hydrate_cached_fn(cached_prices)

    if use_mock:
        return get_mock_prices_fn(ticker, start_date, end_date)

    ak_module = get_akshare_fn()
    if ak_module is None:
        raise error_factory("AKShare 模块不可用，无法获取 A 股数据。\n请检查网络连接，或使用 use_mock=True 参数使用模拟数据。")

    return load_prices_fn(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        period=period,
        ak_module=ak_module,
    )


def execute_robust_price_request(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    period: str,
    use_mock_on_fail: bool,
    get_prices_fn,
    get_sina_historical_data_fn,
    get_prices_multi_source_fn,
    get_mock_prices_fn,
    error_factory,
) -> list[Price]:
    errors: list[str] = []

    try:
        print("[1/4] 尝试 AKShare...")
        return get_prices_fn(ticker, start_date, end_date, period, False)
    except Exception as error:
        errors.append(f"AKShare: {error}")
        print(f"  ✗ 失败: {error}")

    try:
        print("[2/4] 尝试新浪财经历史数据...")
        return get_sina_historical_data_fn(ticker, start_date, end_date, period)
    except Exception as error:
        errors.append(f"新浪财经: {error}")
        print(f"  ✗ 失败: {error}")

    try:
        print("[3/4] 尝试 Tushare/BaoStock...")
        return get_prices_multi_source_fn(ticker, start_date, end_date, period)
    except Exception as error:
        errors.append(f"多数据源: {error}")
        print(f"  ✗ 失败: {error}")

    if use_mock_on_fail:
        print("[4/4] 使用模拟数据...")
        return get_mock_prices_fn(ticker, start_date, end_date)

    raise error_factory(f"所有数据源都失败: {'; '.join(errors)}")


def load_prices_with_fallback(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    period: str,
    ak_module,
    fetch_prices_from_akshare_fn: Callable[..., list[Price] | None],
    fetch_prices_from_tencent_fn: Callable[..., list[Price]],
    cache_prices_fn: Callable[[str, list[Price]], list[Price]],
    cache_key: str,
    error_factory: Callable[[str], Exception],
) -> list[Price]:
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
