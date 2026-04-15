import datetime
import os
import time

import pandas as pd
import requests

from src.data.enhanced_cache import get_cache
from src.data.models import (
    CompanyFactsResponse,
    CompanyNews,
    FinancialMetrics,
    FinancialMetricsResponse,
    InsiderTrade,
    LineItem,
    LineItemResponse,
    Price,
    PriceResponse,
)
from src.data.snapshot import get_snapshot_exporter

# Import A-share data module
from src.tools.akshare_api import get_ashare_company_news, is_ashare
from src.tools.api_company_news_helpers import build_company_news_cache_key, cache_company_news, fetch_remote_company_news, load_cached_company_news
from src.tools.api_insider_trade_helpers import build_financial_datasets_headers, build_insider_trade_cache_key, cache_insider_trades, fetch_remote_insider_trades, load_cached_insider_trades
from src.tools.tushare_api import (
    get_ashare_financial_metrics_with_tushare,
    get_ashare_insider_trades_with_tushare,
    get_ashare_line_items_with_tushare,
    get_ashare_market_cap_with_tushare,
    get_ashare_prices_with_tushare,
)

# Global cache instance
_cache = get_cache()


def _completeness_score(model_obj) -> int:
    """Estimate record completeness by counting non-null fields."""
    if not hasattr(model_obj, "model_dump"):
        return 0
    data = model_obj.model_dump()
    return sum(1 for value in data.values() if value is not None)


def _dedupe_by_report_period(records: list) -> list:
    """Deduplicate model records by report_period, keeping the more complete one."""
    if not records:
        return records

    deduped: dict[str, object] = {}
    passthrough: list = []

    for record in records:
        period = getattr(record, "report_period", None)
        if not period:
            passthrough.append(record)
            continue

        existing = deduped.get(period)
        if existing is None or _completeness_score(record) > _completeness_score(existing):
            deduped[period] = record

    unique_records = list(deduped.values())
    unique_records.sort(key=lambda item: getattr(item, "report_period", ""), reverse=True)
    return unique_records + passthrough


def _get_snapshot():
    """延迟获取快照导出器，确保 .env 已加载"""
    return get_snapshot_exporter()


def _make_api_request(url: str, headers: dict, method: str = "GET", json_data: dict | None = None, max_retries: int = 3) -> requests.Response:
    """
    Make an API request with rate limiting handling and moderate backoff.

    Args:
        url: The URL to request
        headers: Headers to include in the request
        method: HTTP method (GET or POST)
        json_data: JSON data for POST requests
        max_retries: Maximum number of retries (default: 3)

    Returns:
        requests.Response: The response object

    Raises:
        Exception: If the request fails with a non-429 error
    """
    for attempt in range(max_retries + 1):  # +1 for initial attempt
        if method.upper() == "POST":
            response = requests.post(url, headers=headers, json=json_data)
        else:
            response = requests.get(url, headers=headers)

        if response.status_code == 429 and attempt < max_retries:
            # Linear backoff: 60s, 90s, 120s, 150s...
            delay = 60 + (30 * attempt)
            print(f"Rate limited (429). Attempt {attempt + 1}/{max_retries + 1}. Waiting {delay}s before retrying...")
            time.sleep(delay)
            continue

        # Return the response (whether success, other errors, or final 429)
        return response


def get_prices(ticker: str, start_date: str, end_date: str, api_key: str | None = None) -> list[Price]:
    """
    Fetch price data from cache or API.
    Supports both US stocks and A-shares (Chinese stocks).
    """
    # Create a cache key that includes all parameters to ensure exact matches
    cache_key = f"{ticker}_{start_date}_{end_date}"

    # Check cache first - simple exact match
    if cached_data := _cache.get_prices(cache_key):
        prices = [Price(**price) for price in cached_data]
        _get_snapshot().export_prices(ticker, end_date, prices, "cache")
        return prices

    # Check if it's an A-share (Chinese stock)
    if is_ashare(ticker):
        prices = get_ashare_prices_with_tushare(ticker, start_date, end_date)
        if prices:
            # Cache the results
            _cache.set_prices(cache_key, [p.model_dump() for p in prices])
            _get_snapshot().export_prices(ticker, end_date, prices, "tushare")
        return prices

    # For US stocks, use Financial Datasets API
    headers = {}
    financial_api_key = api_key or os.environ.get("FINANCIAL_DATASETS_API_KEY")
    if financial_api_key:
        headers["X-API-KEY"] = financial_api_key

    url = f"https://api.financialdatasets.ai/prices/?ticker={ticker}&interval=day&interval_multiplier=1&start_date={start_date}&end_date={end_date}"
    response = _make_api_request(url, headers)
    if response.status_code != 200:
        return []

    # Parse response with Pydantic model
    try:
        price_response = PriceResponse(**response.json())
        prices = price_response.prices
    except Exception:
        return []

    if not prices:
        return []

    # Cache the results using the comprehensive cache key
    _cache.set_prices(cache_key, [p.model_dump() for p in prices])
    _get_snapshot().export_prices(ticker, end_date, prices, "financial_datasets")
    return prices


def get_financial_metrics(
    ticker: str,
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
    api_key: str | None = None,
) -> list[FinancialMetrics]:
    """
    Fetch financial metrics from cache or API.
    Supports both US stocks and A-shares (Chinese stocks).
    """
    # Create a cache key that includes all parameters to ensure exact matches
    cache_key = f"{ticker}_{period}_{end_date}_{limit}"

    # Check cache first - simple exact match
    if cached_data := _cache.get_financial_metrics(cache_key):
        metrics = _dedupe_by_report_period([FinancialMetrics(**metric) for metric in cached_data])
        _get_snapshot().export_financial_metrics(ticker, end_date, metrics, "cache")
        return metrics

    # Check if it's an A-share (Chinese stock)
    if is_ashare(ticker):
        metrics = _dedupe_by_report_period(get_ashare_financial_metrics_with_tushare(ticker, end_date, limit, period=period))
        if metrics:
            # Cache the results
            _cache.set_financial_metrics(cache_key, [m.model_dump() for m in metrics])
            _get_snapshot().export_financial_metrics(ticker, end_date, metrics, "tushare")
        return metrics

    # For US stocks, use Financial Datasets API
    headers = {}
    financial_api_key = api_key or os.environ.get("FINANCIAL_DATASETS_API_KEY")
    if financial_api_key:
        headers["X-API-KEY"] = financial_api_key

    url = f"https://api.financialdatasets.ai/financial-metrics/?ticker={ticker}&report_period_lte={end_date}&limit={limit}&period={period}"
    response = _make_api_request(url, headers)
    if response.status_code != 200:
        return []

    # Parse response with Pydantic model
    try:
        metrics_response = FinancialMetricsResponse(**response.json())
        financial_metrics = _dedupe_by_report_period(metrics_response.financial_metrics)
    except Exception:
        return []

    if not financial_metrics:
        return []

    # Cache the results as dicts using the comprehensive cache key
    _cache.set_financial_metrics(cache_key, [m.model_dump() for m in financial_metrics])
    _get_snapshot().export_financial_metrics(ticker, end_date, financial_metrics, "financial_datasets")
    return financial_metrics


def search_line_items(
    ticker: str,
    line_items: list[str],
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
    api_key: str | None = None,
) -> list[LineItem]:
    """Fetch line items from API."""
    # Check if it's an A-share (Chinese stock)
    if is_ashare(ticker):
        # 缓存 key: 按 ticker + 字段 + period + end_date + limit 组合
        sorted_items = "_".join(sorted(line_items))
        cache_key = f"{ticker}_{sorted_items}_{period}_{end_date}_{limit}"
        if cached_data := _cache.get_line_items(cache_key):
            results = [LineItem(**item) for item in cached_data]
            return results
        results = _dedupe_by_report_period(get_ashare_line_items_with_tushare(ticker, line_items, end_date, period, limit))
        if results:
            _cache.set_line_items(cache_key, [r.model_dump() for r in results])
        _get_snapshot().export_line_items(ticker, end_date, results, "tushare")
        return results

    # For US stocks, use Financial Datasets API
    headers = {}
    financial_api_key = api_key or os.environ.get("FINANCIAL_DATASETS_API_KEY")
    if financial_api_key:
        headers["X-API-KEY"] = financial_api_key

    url = "https://api.financialdatasets.ai/financials/search/line-items"

    body = {
        "tickers": [ticker],
        "line_items": line_items,
        "end_date": end_date,
        "period": period,
        "limit": limit,
    }
    response = _make_api_request(url, headers, method="POST", json_data=body)
    if response.status_code != 200:
        return []

    try:
        data = response.json()
        response_model = LineItemResponse(**data)
        search_results = response_model.search_results
    except Exception:
        return []
    if not search_results:
        return []

    # Snapshot and return the results
    results = _dedupe_by_report_period(search_results[:limit])
    _get_snapshot().export_line_items(ticker, end_date, results, "financial_datasets")
    return results


def get_insider_trades(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
    api_key: str | None = None,
) -> list[InsiderTrade]:
    """Fetch insider trades from cache or API."""
    cache_key = build_insider_trade_cache_key(ticker, start_date, end_date, limit)

    if is_ashare(ticker):
        if cached_trades := load_cached_insider_trades(_cache, cache_key):
            return cached_trades
        trades = get_ashare_insider_trades_with_tushare(ticker, end_date, start_date, limit)
        if trades:
            cache_insider_trades(_cache, cache_key, trades)
        return trades

    if cached_trades := load_cached_insider_trades(_cache, cache_key):
        return cached_trades

    all_trades = fetch_remote_insider_trades(
        _make_api_request,
        ticker,
        end_date,
        start_date,
        limit,
        build_financial_datasets_headers(api_key),
    )

    if not all_trades:
        return []

    return cache_insider_trades(_cache, cache_key, all_trades)


def get_company_news(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
    api_key: str | None = None,
) -> list[CompanyNews]:
    """Fetch company news from cache or API."""
    if is_ashare(ticker):
        cache_key = build_company_news_cache_key(ticker, start_date, end_date, limit, ashare=True)
        if cached_news := load_cached_company_news(_cache, cache_key):
            return cached_news
        news = get_ashare_company_news(ticker, end_date, start_date, limit)
        if news:
            cache_company_news(_cache, cache_key, news)
        return news

    cache_key = build_company_news_cache_key(ticker, start_date, end_date, limit)
    if cached_news := load_cached_company_news(_cache, cache_key):
        return cached_news

    all_news = fetch_remote_company_news(
        _make_api_request,
        ticker,
        end_date,
        start_date,
        limit,
        build_financial_datasets_headers(api_key),
    )

    if not all_news:
        return []

    return cache_company_news(_cache, cache_key, all_news)


def get_market_cap(
    ticker: str,
    end_date: str,
    api_key: str | None = None,
) -> float | None:
    """Fetch market cap from the API."""
    if is_ashare(ticker):
        return get_ashare_market_cap_with_tushare(ticker, end_date)

    # Check if end_date is today
    if end_date == datetime.datetime.now().strftime("%Y-%m-%d"):
        # Get the market cap from company facts API
        headers = {}
        financial_api_key = api_key or os.environ.get("FINANCIAL_DATASETS_API_KEY")
        if financial_api_key:
            headers["X-API-KEY"] = financial_api_key

        url = f"https://api.financialdatasets.ai/company/facts/?ticker={ticker}"
        response = _make_api_request(url, headers)
        if response.status_code != 200:
            print(f"Error fetching company facts: {ticker} - {response.status_code}")
            return None

        data = response.json()
        response_model = CompanyFactsResponse(**data)
        return response_model.company_facts.market_cap

    financial_metrics = get_financial_metrics(ticker, end_date, api_key=api_key)
    if not financial_metrics:
        return None

    market_cap = financial_metrics[0].market_cap

    if not market_cap:
        return None

    return market_cap


def prices_to_df(prices: list[Price]) -> pd.DataFrame:
    """Convert prices to a DataFrame."""
    df = pd.DataFrame([p.model_dump() for p in prices])
    df["Date"] = pd.to_datetime(df["time"])
    df.set_index("Date", inplace=True)
    numeric_cols = ["open", "close", "high", "low", "volume"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.sort_index(inplace=True)
    return df


# Update the get_price_data function to use the new functions
def get_price_data(ticker: str, start_date: str, end_date: str, api_key: str | None = None) -> pd.DataFrame:
    prices = get_prices(ticker, start_date, end_date, api_key=api_key)
    return prices_to_df(prices)
