"""Infrastructure helpers for AKShare adapters."""

from __future__ import annotations

import atexit
import concurrent.futures
import datetime
import functools
import hashlib
import json
import os
import threading
from collections.abc import Callable
from typing import Any

import pandas as pd

SINA_QUOTE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://finance.sina.com.cn",
}
PROXY_ENV_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "http_proxy",
    "https_proxy",
    "ALL_PROXY",
    "all_proxy",
    "SOCKS_PROXY",
    "socks_proxy",
    "NO_PROXY",
    "no_proxy",
)
BYPASS_ALL_PROXY_ENV_VARS = ("NO_PROXY", "no_proxy")


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
    timeout_seconds: float | None = None,
    ttl: int | None = None,
    cache_key_kwargs: dict[str, Any] | None = None,
    **kwargs,
) -> pd.DataFrame | None:
    cache_identity = dict(cache_key_kwargs or kwargs)
    cache_key = make_akshare_df_cache_key(api_name, **cache_identity)
    cached_df = persistent_cache.get(cache_key)
    if isinstance(cached_df, pd.DataFrame):
        return cached_df.copy()

    effective_timeout_seconds = timeout_seconds
    if effective_timeout_seconds is None and api_name == "stock_news_em":
        effective_timeout_seconds = stock_news_timeout_seconds

    if effective_timeout_seconds is not None and effective_timeout_seconds > 0:
        df = _call_with_timeout(
            func=func,
            timeout_seconds=effective_timeout_seconds,
            timeout_label=f"AKShare {api_name} timed out after {effective_timeout_seconds}s",
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


# R20.8 BETA: 模块级共享 Session 句柄（懒加载，线程安全）
_SHARED_SESSION = None
_SESSION_LOCK = threading.Lock()


def create_session():
    """获取（必要时创建）模块级共享 requests.Session (R20.8 BETA 性能优化)。

    早期实现每次都新建 ``requests.Session()``，导致每次 AKShare/Sina/Tencent
    HTTP 请求都要重新建 TCP 连接 + TLS 握手。对于批量价格拉取等场景，
    这部分开销可占端到端延迟的 20-50%。

    优化：模块级单例 ``_SHARED_SESSION`` + ``HTTPAdapter`` 配
    ``connectionpool`` 连接池，默认 10 个 keep-alive 连接，跨调用复用。
    通过 ``AKSHARE_SESSION_POOL_SIZE`` 可调。
    """
    global _SHARED_SESSION
    if _SHARED_SESSION is not None:
        return _SHARED_SESSION

    with _SESSION_LOCK:
        if _SHARED_SESSION is not None:
            return _SHARED_SESSION
        import requests
        from requests.adapters import HTTPAdapter

        session = requests.Session()
        session.trust_env = False
        # 配 HTTPAdapter：pool_connections=连接池数, pool_maxsize=每池最多 keep-alive 连接
        pool_size = int(os.environ.get("AKSHARE_SESSION_POOL_SIZE", "10"))

        # R20.10 BETA: pool_block=True 防止池耗尽时无上限新建 transient 连接。
        # 注: 原实现还传了 pool_timeout=30, 但 urllib3 2.x 移除了 pool_timeout
        # (PoolManager.__init__ 不再接受它, 请求时构造 PoolKey 会 crash:
        # "PoolKey.__new__() got an unexpected keyword argument 'key_pool_timeout'").
        # urllib3 2.x 下 pool_block=True 即阻塞等待连接释放, 无单独超时; pool_size
        # 足够大时实际不会无限阻塞。故移除 pool_timeout, 保留 pool_block 防池耗尽语义。
        class _BoundedHTTPAdapter(HTTPAdapter):
            def init_poolmanager(self, *args, **kwargs):
                # maxsize & block are already supplied positionally/keyword by
                # HTTPAdapter.__init__ (via pool_maxsize/pool_block ctor args);
                # re-adding maxsize to kwargs collides with the positional value
                # on requests>=2.32 ("got multiple values for 'maxsize'"). R20.25.
                kwargs["block"] = True
                return super().init_poolmanager(*args, **kwargs)

        adapter = _BoundedHTTPAdapter(
            pool_connections=pool_size,
            pool_maxsize=pool_size,
            pool_block=True,
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        _SHARED_SESSION = session
        return _SHARED_SESSION


# Module-level lock to serialize the whole proxy-disabled request window across
# threads.  Deleting/restoring env vars alone is not enough: requests/AKShare
# reads proxy env lazily during the HTTP call, so another thread restoring the
# vars mid-call can leak proxies back into an in-flight request.
_PROXY_LOCK = threading.RLock()


def _disable_system_proxies_unlocked() -> dict[str, str]:
    saved: dict[str, str] = {}
    for var in PROXY_ENV_VARS:
        if var in os.environ:
            saved[var] = os.environ[var]
            del os.environ[var]
    # On macOS, requests/urllib can fall back to SystemConfiguration proxies
    # when proxy env vars are absent.  NO_PROXY=* forces a real all-host bypass.
    for var in BYPASS_ALL_PROXY_ENV_VARS:
        os.environ[var] = "*"
    return saved


def _restore_proxies_unlocked(saved: dict[str, str]) -> None:
    for var in PROXY_ENV_VARS:
        if var in saved:
            os.environ[var] = saved[var]
        else:
            os.environ.pop(var, None)


def disable_system_proxies() -> dict[str, str]:
    with _PROXY_LOCK:
        return _disable_system_proxies_unlocked()


def restore_proxies(saved: dict[str, str]) -> None:
    with _PROXY_LOCK:
        _restore_proxies_unlocked(saved)


def run_without_system_proxies(run: Callable[[], Any]) -> Any:
    with _PROXY_LOCK:
        saved_proxies_env = _disable_system_proxies_unlocked()
        try:
            return run()
        finally:
            _restore_proxies_unlocked(saved_proxies_env)


def disable_proxy_temporarily(disable_proxies, restore_saved_proxies):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with _PROXY_LOCK:
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


# R20.10 BETA: 模块级共享 ThreadPoolExecutor，避免每次 _call_with_timeout 新建 executor。
# 旧实现每次调用都 ThreadPoolExecutor(max_workers=1)，超时后 shutdown(wait=False)
# 无法杀死线程，100 次连续超时会泄漏 ~100 个线程 (~800MB)。
_SHARED_TIMEOUT_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4)

# BETA-008: 注册 atexit 清理 — 非守护线程会延迟进程退出。Python 默认不会
# 在解释器关闭时调用 ThreadPoolExecutor.shutdown()。wait=False 让清理不阻塞。
atexit.register(_SHARED_TIMEOUT_EXECUTOR.shutdown, wait=False)


def _call_with_timeout(*, func, timeout_seconds: float, timeout_label: str, **kwargs):
    future = _SHARED_TIMEOUT_EXECUTOR.submit(func, **kwargs)
    try:
        return future.result(timeout=timeout_seconds)
    except concurrent.futures.TimeoutError as exc:
        future.cancel()
        raise TimeoutError(timeout_label) from exc
