"""Infrastructure helpers for AKShare adapters."""

from __future__ import annotations

import concurrent.futures
import datetime
import functools
import hashlib
import json
import os
from typing import Any

import pandas as pd


SINA_QUOTE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://finance.sina.com.cn",
}
PROXY_ENV_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy", "SOCKS_PROXY", "socks_proxy")


def normalize_akshare_cache_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): normalize_akshare_cache_value(inner_value) for key, inner_value in sorted(value.items()) if inner_value is not None}
    if isinstance(value, (list, tuple, set)):
        return [normalize_akshare_cache_value(item) for item in value]
    return value


def make_akshare_df_cache_key(api_name: str, **kwargs) -> str:
    payload = json.dumps(
        {"api_name": api_name, "params": normalize_akshare_cache_value(kwargs)},
        sort_keys=True,
        ensure_ascii=True,
        default=str,
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    return f"akshare_df:{api_name}:{digest}"


def resolve_akshare_cache_ttl(api_name: str, **kwargs) -> int:
    reference_date = str(kwargs.get("end_date") or kwargs.get("start_date") or "")
    today = datetime.datetime.now().strftime("%Y%m%d")
    is_historical = bool(reference_date) and reference_date < today

    if api_name in {"stock_zh_a_hist"}:
        return 30 * 86400 if is_historical else 6 * 3600
    if api_name in {"stock_financial_analysis_indicator", "stock_financial_report_sina"}:
        return 14 * 86400
    if api_name in {"stock_news_em"}:
        return 30 * 86400 if is_historical else 6 * 3600
    return 24 * 3600


def cached_akshare_dataframe_call(
    api_name: str,
    func,
    *,
    persistent_cache,
    stock_news_timeout_seconds: float,
    ttl: int | None = None,
    cache_key_kwargs: dict[str, Any] | None = None,
    **kwargs,
) -> pd.DataFrame | None:
    cache_identity = dict(cache_key_kwargs or kwargs)
    cache_key = make_akshare_df_cache_key(api_name, **cache_identity)
    cached_df = persistent_cache.get(cache_key)
    if isinstance(cached_df, pd.DataFrame):
        return cached_df.copy()

    if api_name == "stock_news_em" and stock_news_timeout_seconds > 0:
        df = _call_with_timeout(
            func=func,
            timeout_seconds=stock_news_timeout_seconds,
            timeout_label=f"AKShare {api_name} timed out after {stock_news_timeout_seconds}s",
            **kwargs,
        )
    else:
        df = func(**kwargs)

    if df is not None:
        persistent_cache.set(
            cache_key,
            df,
            ttl=ttl if ttl is not None else resolve_akshare_cache_ttl(api_name, **cache_identity),
        )
        return df.copy()
    return None


def create_session():
    import requests

    session = requests.Session()
    session.trust_env = False
    return session


def disable_system_proxies() -> dict[str, str]:
    saved: dict[str, str] = {}
    for var in PROXY_ENV_VARS:
        if var in os.environ:
            saved[var] = os.environ[var]
            del os.environ[var]
    return saved


def restore_proxies(saved: dict[str, str]) -> None:
    for var, value in saved.items():
        os.environ[var] = value


def disable_proxy_temporarily(disable_proxies, restore_saved_proxies):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            saved_proxies_env = disable_proxies()
            try:
                return func(*args, **kwargs)
            finally:
                restore_saved_proxies(saved_proxies_env)

        return wrapper

    return decorator


def parse_sina_realtime_quote_text(text: str, error_cls: type[Exception]) -> dict[str, Any]:
    if not text or "hq_str_" not in text:
        raise error_cls("新浪 API 返回数据格式错误")

    start = text.find('"') + 1
    end = text.rfind('"')
    if start <= 0 or end <= start:
        raise error_cls("无法解析新浪返回的数据")

    data_str = text[start:end]
    parts = data_str.split(",")
    if len(parts) < 33:
        raise error_cls("新浪返回的数据字段不完整")

    return {
        "name": parts[0],
        "open": float(parts[1]),
        "close": float(parts[2]),
        "current": float(parts[3]),
        "high": float(parts[4]),
        "low": float(parts[5]),
        "buy": float(parts[6]),
        "sell": float(parts[7]),
        "volume": int(parts[8]),
        "amount": float(parts[9]),
        "bid1_volume": int(parts[10]),
        "bid1_price": float(parts[11]),
        "bid2_volume": int(parts[12]),
        "bid2_price": float(parts[13]),
        "bid3_volume": int(parts[14]),
        "bid3_price": float(parts[15]),
        "bid4_volume": int(parts[16]),
        "bid4_price": float(parts[17]),
        "bid5_volume": int(parts[18]),
        "bid5_price": float(parts[19]),
        "ask1_volume": int(parts[20]),
        "ask1_price": float(parts[21]),
        "ask2_volume": int(parts[22]),
        "ask2_price": float(parts[23]),
        "ask3_volume": int(parts[24]),
        "ask3_price": float(parts[25]),
        "ask4_volume": int(parts[26]),
        "ask4_price": float(parts[27]),
        "ask5_volume": int(parts[28]),
        "ask5_price": float(parts[29]),
        "date": parts[30],
        "time": parts[31],
    }


def execute_sina_realtime_quote_request(
    *,
    ticker: str,
    resolve_ticker_fn,
    create_session_fn,
    headers: dict[str, str],
    parse_quote_fn,
    error_factory,
) -> dict[str, Any]:
    session = create_session_fn()
    ashare = resolve_ticker_fn(ticker)
    response = session.get(f"https://hq.sinajs.cn/list={ashare.full_code}", headers=headers, timeout=30)
    if response.status_code != 200:
        raise error_factory(f"新浪 API 返回错误状态码: {response.status_code}")
    return parse_quote_fn(response.text, error_factory)


def execute_wrapped_ashare_request(
    *,
    run,
    error_factory,
    message_prefix: str,
    passthrough_errors: tuple[type[Exception], ...] = (),
    message_suffix: str = "",
):
    try:
        return run()
    except passthrough_errors:
        raise
    except Exception as error:
        message = f"{message_prefix}: {error}"
        if message_suffix:
            message = f"{message}\n{message_suffix}"
        raise error_factory(message) from error


def _call_with_timeout(*, func, timeout_seconds: float, timeout_label: str, **kwargs):
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(func, **kwargs)
    try:
        return future.result(timeout=timeout_seconds)
    except concurrent.futures.TimeoutError as exc:
        future.cancel()
        raise TimeoutError(timeout_label) from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
