import logging
from collections.abc import Callable

import pandas as pd

from src.data.models import Price

# NS-17 / BH-017 family sibling drain: 本模块持有 A 股多级价格回退链
# (execute_robust_price_request: AKShare→新浪→Tushare/BaoStock→mock;
# load_prices_with_fallback: AKShare→腾讯→Tushare 三层), 是 get_prices_robust /
# akshare_api.get_prices 的核心价格获取路径。此前无 logger, 8 处 print() 在
# cron/launchd 上下文里不入结构化日志: 某级 tier 静默失败时运维无法定位"为何
# 最终拿到 mock/空数据"。
logger = logging.getLogger(__name__)


def hydrate_cached_prices(cached_data: list[dict]) -> list[Price]:
    return [Price(**price) for price in cached_data]


def build_prices_from_dataframe(df: pd.DataFrame) -> list[Price]:
    prices: list[Price] = []
    for _, row in df.iterrows():
        # R132 (R83 same-class drain): skip rows with NaN/None in any OHLC/volume
        # cell. Halted/illiquid/delisted days produce NaN cells (akshare
        # stock_zh_a_hist); bare ``int(row["成交量"])`` on NaN raises ValueError
        # and crashes the whole ticker's price series on the production
        # ``akshare_api.get_prices`` path. Aligns with the sibling
        # AKShareProvider.get_prices ``pd.notna`` guard (R83).
        ohlc = (row["开盘"], row["最高"], row["最低"], row["收盘"], row["成交量"])
        if any(not pd.notna(v) for v in ohlc):
            continue
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

    prices: list[Price] = []
    for item in kline_data:
        # R134 (R83/R132/R133 same-class drain residue): Tencent kline rows are
        # ``[date, open, close, high, low, volume]`` STRING lists; halted/illiquid
        # days yield empty-string cells. Bare ``int(float(item[5]))`` on ``""``
        # raises ValueError, crashing the WHOLE ticker's price series on the
        # fallback path. Skip rows whose OHLC/volume cells are empty/missing,
        # aligning with the sibling df→Price converters' NaN/empty-row skip guard.
        ohlc = item[1:6]
        if len(ohlc) < 5 or any(cell in ("", None) for cell in ohlc):
            continue
        prices.append(
            Price(
                time=item[0],
                open=float(item[1]),
                close=float(item[2]),
                high=float(item[3]),
                low=float(item[4]),
                volume=int(float(item[5])),
            )
        )
    return prices


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
        logger.debug("[1/4] 尝试 AKShare...")
        return get_prices_fn(ticker, start_date, end_date, period, False)
    except Exception as error:
        errors.append(f"AKShare: {error}")
        logger.warning("  ✗ AKShare 失败: %s", error)

    try:
        logger.debug("[2/4] 尝试新浪财经历史数据...")
        return get_sina_historical_data_fn(ticker, start_date, end_date, period)
    except Exception as error:
        errors.append(f"新浪财经: {error}")
        logger.warning("  ✗ 新浪财经失败: %s", error)

    try:
        logger.debug("[3/4] 尝试 Tushare/BaoStock...")
        return get_prices_multi_source_fn(ticker, start_date, end_date, period)
    except Exception as error:
        errors.append(f"多数据源: {error}")
        logger.warning("  ✗ 多数据源失败: %s", error)

    if use_mock_on_fail:
        logger.warning("[4/4] 所有真实数据源失败, 回退模拟数据")
        return get_mock_prices_fn(ticker, start_date, end_date)

    raise error_factory(f"所有数据源都失败: {'; '.join(errors)}")


def _is_network_error(error: Exception) -> bool:
    """Classify whether an exception is a network/proxy class error.

    Network errors (ProxyError/Timeout/ConnectionError/SSLError) carry very long
    URLs in their message; for log readability we dedupe them across a batch
    rather than printing the full message per ticker.
    """
    error_name = type(error).__name__
    return (
        "proxy" in str(error).lower()
        or "timeout" in str(error).lower()
        or error_name in (
            "ProxyError", "RemoteDisconnected", "ConnectionError", "MaxRetryError", "SSLError",
        )
    )


def _log_price_tier_failure(tier: str, source: str, ticker: str, next_source: str | None, error: Exception) -> None:
    """Log a price-tier failure with dedup for network-class errors.

    Network errors (proxy/timeout/SSL/connection) are common across a full-market
    batch and would flood the log if printed in full per ticker. We dedupe: the
    first 3 print the ticker + error type + truncated message, then a single
    summary line announces subsequent ones are silenced. Non-network errors are
    always printed in full (they are rare and usually actionable).
    """
    if _is_network_error(error):
        if not hasattr(_log_price_tier_failure, "_net_count"):
            _log_price_tier_failure._net_count = 0  # type: ignore[attr-defined]
        _log_price_tier_failure._net_count += 1  # type: ignore[attr-defined]
        n = _log_price_tier_failure._net_count  # type: ignore[attr-defined]
        # Truncate the error message: network errors embed very long proxy URLs.
        msg = str(error)
        if len(msg) > 120:
            msg = msg[:120] + "..."
        if n <= 3:
            suffix = f", 尝试 {next_source}" if next_source else ""
            logger.warning("%s %s %s 失败 (%s): %s%s", tier, source, ticker, type(error).__name__, msg, suffix)
        elif n == 4:
            logger.warning("%s 网络错误已累计 %d 次, 后续同类静默 (请检查代理/网络, 而非代码)", tier, n)
    else:
        suffix = f", 尝试 {next_source}" if next_source else ""
        logger.warning("%s %s %s 失败 (%s): %s%s", tier, source, ticker, type(error).__name__, error, suffix)


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
    fetch_prices_from_tushare_fn: Callable[..., list[Price]] | None = None,
) -> list[Price]:
    # Three-tier A-share price fallback chain: AKShare → Tencent → Tushare.
    # AKShare and Tencent share the eastmoney/tencent network egress and tend to
    # fail together (proxy outage), so Tushare — which has an independent egress
    # — is the third tier that rescues the chain when the first two go down.
    errors: dict[str, str] = {}

    # --- Tier 1/3: AKShare ---
    try:
        akshare_prices = fetch_prices_from_akshare_fn(ak_module, ticker, start_date, end_date, period)
        if akshare_prices:
            return cache_prices_fn(cache_key, akshare_prices)
        errors["AKShare"] = "返回空数据"
    except Exception as error:
        errors["AKShare"] = f"{type(error).__name__}: {error}"
        _log_price_tier_failure("[价格链 1/3]", "AKShare", ticker, "腾讯接口", error)

    # --- Tier 2/3: Tencent ---
    try:
        prices = fetch_prices_from_tencent_fn(ticker, start_date, end_date)
        if prices:
            return cache_prices_fn(cache_key, prices)
        errors["腾讯接口"] = "返回空数据"
        logger.warning("[价格链 2/3] 腾讯接口 %s 返回空数据", ticker)
    except Exception as error:
        errors["腾讯接口"] = f"{type(error).__name__}: {error}"
        next_src = "Tushare" if fetch_prices_from_tushare_fn is not None else None
        _log_price_tier_failure("[价格链 2/3]", "腾讯接口", ticker, next_src, error)

    # --- Tier 3/3: Tushare (optional) ---
    if fetch_prices_from_tushare_fn is not None:
        try:
            prices = fetch_prices_from_tushare_fn(ticker, start_date, end_date, period)
            if prices:
                return cache_prices_fn(cache_key, prices)
            errors["Tushare"] = "返回空数据"
            logger.warning("[价格链 3/3] Tushare %s 返回空数据", ticker)
        except Exception as error:
            errors["Tushare"] = f"{type(error).__name__}: {error}"
            _log_price_tier_failure("[价格链 3/3]", "Tushare", ticker, None, error)

    # All tiers exhausted — report each source's real failure reason.
    detail = "; ".join(f"{src}: {reason}" for src, reason in errors.items())
    raise error_factory(f"无法获取股票 {ticker} 的历史数据（所有数据源都失败）。\n{detail}\n请检查网络连接，或使用 use_mock=True 参数使用模拟数据。")
