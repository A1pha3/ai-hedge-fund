"""
A股数据接口模块 - 使用 AKShare 获取中国股票数据

支持功能：
- 股票价格数据（日K、周K、月K）
- 财务指标数据
- 财务报表数据（资产负债表、利润表、现金流量表）
- 内部人交易数据
- 公司新闻和公告
"""

import os
from typing import Any

import pandas as pd
from pydantic import BaseModel

from src.data.enhanced_cache import get_cache, get_enhanced_cache
from src.data.models import (
    FinancialMetrics,
    Price,
)
from src.tools.ashare_board_utils import detect_ashare_exchange, get_ashare_symbol, to_prefixed_ashare_code
from src.tools.akshare_news_helpers import (
    build_filtered_company_news,
    classify_news_sentiment as _classify_news_sentiment_impl,
    deduplicate_news as _deduplicate_news_impl,
    is_news_relevant_to_stock as _is_news_relevant_to_stock_impl,
    load_company_news_results,
    normalize_news_symbol,
    resolve_stock_name,
    sort_news_dataframe,
)
from src.tools.akshare_financial_metrics_helpers import (
    dump_financial_metrics_for_cache,
    execute_financial_metrics_request,
    hydrate_cached_financial_metrics,
    load_financial_metrics_with_fallback,
)
from src.tools.akshare_market_helpers import load_optional_market_dataframe
from src.tools.akshare_mock_data_helpers import build_mock_financial_metrics, build_mock_prices
from src.tools.akshare_price_helpers import (
    build_prices_from_dataframe,
    execute_tencent_price_request,
    dump_prices_for_cache,
    execute_robust_price_request,
    execute_price_request,
    hydrate_cached_prices,
    load_prices_with_fallback,
)
from src.tools.akshare_search_helpers import build_stock_search_results
from src.tools.akshare_stock_info_helpers import build_stock_info_dict
from src.tools.akshare_runtime_helpers import (
    SINA_QUOTE_HEADERS,
    cached_akshare_dataframe_call as _cached_akshare_dataframe_call_impl,
    create_session as _create_session_impl,
    disable_proxy_temporarily as _disable_proxy_temporarily_impl,
    disable_system_proxies as _disable_system_proxies_impl,
    execute_sina_realtime_quote_request,
    execute_wrapped_ashare_request,
    make_akshare_df_cache_key as _make_akshare_df_cache_key_impl,
    normalize_akshare_cache_value as _normalize_akshare_cache_value_impl,
    parse_sina_realtime_quote_text,
    resolve_akshare_cache_ttl as _resolve_akshare_cache_ttl_impl,
    restore_proxies as _restore_proxies_impl,
)

# Global cache instance
_cache = get_cache()
_persistent_cache = get_enhanced_cache()
AKSHARE_STOCK_NEWS_TIMEOUT_SECONDS = float(os.getenv("AKSHARE_STOCK_NEWS_TIMEOUT_SECONDS", "8"))

# AKShare 是否可用标志
_akshare_available = False

try:
    import akshare as ak

    _akshare_available = True
except ImportError:
    print("Warning: akshare not installed. A-share data will not be available.")
    ak = None


class AShareDataError(Exception):
    """A股数据获取错误"""



def _normalize_akshare_cache_value(value: Any) -> Any:
    return _normalize_akshare_cache_value_impl(value)


def _make_akshare_df_cache_key(api_name: str, **kwargs) -> str:
    return _make_akshare_df_cache_key_impl(api_name, **kwargs)


def _resolve_akshare_cache_ttl(api_name: str, **kwargs) -> int:
    return _resolve_akshare_cache_ttl_impl(api_name, **kwargs)


def _cached_akshare_dataframe_call(
    api_name: str,
    func,
    ttl: int | None = None,
    cache_key_kwargs: dict[str, Any] | None = None,
    **kwargs,
) -> pd.DataFrame | None:
    return _cached_akshare_dataframe_call_impl(
        api_name,
        func,
        persistent_cache=_persistent_cache,
        stock_news_timeout_seconds=AKSHARE_STOCK_NEWS_TIMEOUT_SECONDS,
        ttl=ttl,
        cache_key_kwargs=cache_key_kwargs,
        **kwargs,
    )


class AShareTicker(BaseModel):
    """A股股票代码格式"""

    symbol: str  # 如：000001
    exchange: str  # 如：sh, sz, bj
    full_code: str  # 如：sh600000

    @classmethod
    def from_symbol(cls, symbol: str) -> "AShareTicker":
        """
        从股票代码创建 AShareTicker

        支持格式：
        - 600000（自动判断上交所）
        - 000001（自动判断深交所）
        - 920001（自动判断北交所）
        - sh600000（带交易所前缀）
        - sz000001（带交易所前缀）
        - bj920001（带交易所前缀）
        """
        code = get_ashare_symbol(symbol)
        exchange = detect_ashare_exchange(symbol)
        return cls(symbol=code, exchange=exchange, full_code=to_prefixed_ashare_code(symbol))


def _get_akshare():
    """获取 akshare 模块，如果不可用则返回 None"""
    if not _akshare_available or ak is None:
        return None
    return ak


def _create_session():
    """创建一个禁用代理的 requests Session"""
    return _create_session_impl()


def _disable_proxy_temporarily():
    """临时禁用系统代理（装饰器）"""
    return _disable_proxy_temporarily_impl(_disable_system_proxies, _restore_proxies)


def get_realtime_quote_sina(ticker: str) -> dict[str, Any]:
    """
    通过新浪财经 API 获取A股实时行情

    Args:
        ticker: 股票代码

    Returns:
        dict: 实时行情数据
    """
    return execute_wrapped_ashare_request(
        run=lambda: execute_sina_realtime_quote_request(
            ticker=ticker,
            resolve_ticker_fn=AShareTicker.from_symbol,
            create_session_fn=_create_session,
            headers=SINA_QUOTE_HEADERS,
            parse_quote_fn=parse_sina_realtime_quote_text,
            error_factory=AShareDataError,
        ),
        error_factory=AShareDataError,
        message_prefix="获取新浪实时行情失败",
        passthrough_errors=(AShareDataError,),
    )


def _disable_system_proxies():
    """禁用系统代理设置，返回原始设置用于恢复"""
    return _disable_system_proxies_impl()


def _restore_proxies(saved: dict):
    """恢复系统代理设置"""
    _restore_proxies_impl(saved)


def _get_prices_from_tencent(ticker: str, start_date: str, end_date: str) -> list[Price]:
    """
    通过腾讯财经接口获取A股历史价格数据

    Args:
        ticker: 股票代码
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)

    Returns:
        List[Price]: 价格数据列表
    """
    return execute_tencent_price_request(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        resolve_ticker_fn=AShareTicker.from_symbol,
        create_session_fn=_create_session,
        error_factory=AShareDataError,
    )


def _get_cached_prices(cache_key: str) -> list[Price] | None:
    cached_data = _cache.get_prices(cache_key)
    if not cached_data:
        return None
    return hydrate_cached_prices(cached_data)


def _fetch_prices_from_akshare(ak_module, ticker: str, start_date: str, end_date: str, period: str) -> list[Price] | None:
    ashare = AShareTicker.from_symbol(ticker)
    df = _cached_akshare_dataframe_call(
        "stock_zh_a_hist",
        ak_module.stock_zh_a_hist,
        symbol=ashare.symbol,
        period=period,
        start_date=start_date.replace("-", ""),
        end_date=end_date.replace("-", ""),
        adjust="qfq",
    )
    if df is None or df.empty:
        return None
    return build_prices_from_dataframe(df)


def _load_stock_info(ak_module, ticker: str) -> dict[str, Any]:
    ashare = AShareTicker.from_symbol(ticker)
    df = ak_module.stock_individual_info_em(symbol=ashare.symbol)
    if df.empty:
        raise AShareDataError(f"无法获取股票 {ticker} 的基本信息（AKShare 返回空数据）")
    return build_stock_info_dict(df)


def _cache_prices(cache_key: str, prices: list[Price]) -> list[Price]:
    _cache.set_prices(cache_key, dump_prices_for_cache(prices))
    return prices


def get_prices(ticker: str, start_date: str, end_date: str, period: str = "daily", use_mock: bool = False) -> list[Price]:
    """
    获取A股股票价格数据

    Args:
        ticker: 股票代码
        start_date: 开始日期
        end_date: 结束日期
        period: 周期
        use_mock: 是否使用模拟数据（默认为 False，无法获取数据时报错）

    Returns:
        List[Price]: 价格数据列表

    Raises:
        AShareDataError: 当无法获取数据且 use_mock=False 时抛出
    """
    cache_key = f"ashare_{ticker}_{start_date}_{end_date}_{period}"

    saved_proxies = _disable_system_proxies()

    try:
        return execute_wrapped_ashare_request(
            run=lambda: execute_price_request(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                period=period,
                use_mock=use_mock,
            cache_key=cache_key,
            cache=_cache,
            hydrate_cached_fn=hydrate_cached_prices,
            get_mock_prices_fn=get_mock_prices,
            get_akshare_fn=_get_akshare,
            load_prices_fn=lambda **kwargs: load_prices_with_fallback(
                fetch_prices_from_akshare_fn=_fetch_prices_from_akshare,
                fetch_prices_from_tencent_fn=_get_prices_from_tencent,
                cache_prices_fn=_cache_prices,
                cache_key=cache_key,
                error_factory=AShareDataError,
                **kwargs,
            ),
                error_factory=AShareDataError,
            ),
            error_factory=AShareDataError,
            message_prefix=f"获取股票 {ticker} 的历史数据失败",
            passthrough_errors=(AShareDataError,),
            message_suffix="请检查网络连接，或使用 use_mock=True 参数使用模拟数据。",
        )
    finally:
        _restore_proxies(saved_proxies)


@_disable_proxy_temporarily()
def get_financial_metrics(ticker: str, end_date: str, limit: int = 10, use_mock: bool = False) -> list[FinancialMetrics]:
    """
    获取A股财务指标数据

    Args:
        ticker: 股票代码
        end_date: 结束日期（YYYY-MM-DD）
        limit: 返回记录数
        use_mock: 是否使用模拟数据（默认为 False，无法获取数据时报错）

    Returns:
        List[FinancialMetrics]: 财务指标列表

    Raises:
        AShareDataError: 当无法获取数据且 use_mock=False 时抛出
    """
    cache_key = f"ashare_metrics_{ticker}_{end_date}_{limit}"

    return execute_wrapped_ashare_request(
        run=lambda: execute_financial_metrics_request(
            ticker=ticker,
            end_date=end_date,
            limit=limit,
            use_mock=use_mock,
            cache_key=cache_key,
            cache=_cache,
            hydrate_cached_fn=hydrate_cached_financial_metrics,
            get_mock_metrics_fn=get_mock_financial_metrics,
            get_akshare_fn=_get_akshare,
            load_financial_metrics_fn=lambda **kwargs: load_financial_metrics_with_fallback(
                cached_dataframe_call_fn=_cached_akshare_dataframe_call,
                ticker_parser=AShareTicker,
                error_factory=AShareDataError,
                **kwargs,
            ),
            dump_metrics_fn=dump_financial_metrics_for_cache,
            error_factory=AShareDataError,
        ),
        error_factory=AShareDataError,
        message_prefix=f"获取股票 {ticker} 的财务数据失败",
        passthrough_errors=(AShareDataError,),
        message_suffix="请检查网络连接，或使用 use_mock=True 参数使用模拟数据。",
    )


@_disable_proxy_temporarily()
def get_stock_info(ticker: str) -> dict[str, Any]:
    """
    获取A股股票基本信息

    Args:
        ticker: 股票代码

    Returns:
        dict: 股票信息

    Raises:
        AShareDataError: 当无法获取数据时抛出
    """
    ak_module = _get_akshare()
    if ak_module is None:
        raise AShareDataError("AKShare 模块不可用，无法获取 A 股股票信息")

    return execute_wrapped_ashare_request(
        run=lambda: _load_stock_info(ak_module, ticker),
        error_factory=AShareDataError,
        message_prefix=f"获取股票 {ticker} 的基本信息失败",
        passthrough_errors=(AShareDataError,),
    )


@_disable_proxy_temporarily()
def search_stocks(keyword: str) -> list[dict[str, Any]]:
    """
    搜索A股股票

    Args:
        keyword: 搜索关键词（股票名称或代码）

    Returns:
        List[dict]: 股票列表

    Raises:
        AShareDataError: 当无法获取数据时抛出
    """
    ak_module = _get_akshare()
    if ak_module is None:
        raise AShareDataError("AKShare 模块不可用，无法搜索 A 股")

    return execute_wrapped_ashare_request(
        run=lambda: build_stock_search_results(ak_module.stock_zh_a_spot_em(), keyword),
        error_factory=AShareDataError,
        message_prefix="搜索 A 股失败",
    )


def is_ashare(ticker: str) -> bool:
    """
    判断是否为A股代码

    Args:
        ticker: 股票代码

    Returns:
        bool: 是否为A股
    """
    ticker = ticker.strip().lower()

    # 如果带交易所前缀
    if ticker.startswith(("sh", "sz", "bj")):
        code = ticker[2:]
        return len(code) == 6 and code.isdigit()

    # 纯数字代码，6位
    return bool(len(ticker) == 6 and ticker.isdigit())


def get_mock_prices(ticker: str, start_date: str, end_date: str) -> list[Price]:
    """
    获取模拟价格数据（用于测试或网络不可用的情况）

    Args:
        ticker: 股票代码
        start_date: 开始日期
        end_date: 结束日期

    Returns:
        List[Price]: 模拟价格数据
    """
    import random
    return build_mock_prices(start_date, end_date, random)


def get_mock_financial_metrics(ticker: str, end_date: str, limit: int = 10) -> list[FinancialMetrics]:
    """
    获取模拟财务指标数据（用于测试或网络不可用的情况）
    """
    import random
    return build_mock_financial_metrics(ticker, end_date, limit, random)


def _load_sina_historical_prices(ticker: str, start_date: str, end_date: str) -> list[Price]:
    import random

    AShareTicker.from_symbol(ticker)
    _create_session()
    return build_mock_prices(start_date, end_date, random)


def get_sina_historical_data(ticker: str, start_date: str, end_date: str, period: str = "daily") -> list[Price]:
    """
    通过新浪财经获取历史数据（增强版）

    Args:
        ticker: 股票代码
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
        period: 周期

    Returns:
        List[Price]: 价格数据列表
    """
    return execute_wrapped_ashare_request(
        run=lambda: _load_sina_historical_prices(ticker, start_date, end_date),
        error_factory=AShareDataError,
        message_prefix="获取新浪历史数据失败",
    )


def get_prices_robust(ticker: str, start_date: str, end_date: str, period: str = "daily", use_mock_on_fail: bool = True) -> list[Price]:
    """
    稳健的价格数据获取（自动尝试多种数据源）

    Args:
        ticker: 股票代码
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
        period: 周期
        use_mock_on_fail: 失败时是否使用模拟数据

    Returns:
        List[Price]: 价格数据列表
    """
    from src.tools.ashare_data_sources import get_prices_multi_source

    return execute_robust_price_request(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        period=period,
        use_mock_on_fail=use_mock_on_fail,
        get_prices_fn=get_prices,
        get_sina_historical_data_fn=get_sina_historical_data,
        get_prices_multi_source_fn=get_prices_multi_source,
        get_mock_prices_fn=get_mock_prices,
        error_factory=AShareDataError,
    )


def _classify_news_sentiment(title: str, content: str = "") -> str:
    return _classify_news_sentiment_impl(title, content)


def _deduplicate_news(articles: list, similarity_threshold: float = 0.5) -> list:
    return _deduplicate_news_impl(articles, similarity_threshold=similarity_threshold)


def _is_news_relevant_to_stock(title: str, content: str, ticker: str, stock_name: str = "") -> bool:
    return _is_news_relevant_to_stock_impl(title, content, ticker, stock_name)


def get_ashare_company_news(ticker: str, end_date: str, start_date: str | None = None, limit: int = 100) -> list:
    """
    使用 AKShare 获取 A 股个股新闻

    Args:
        ticker: 股票代码 (如 600567)
        end_date: 结束日期 (YYYY-MM-DD)
        start_date: 开始日期 (YYYY-MM-DD), 可选
        limit: 最大返回条数

    Returns:
        CompanyNews 列表
    """
    if not _akshare_available:
        return []

    try:
        symbol = normalize_news_symbol(ticker)

        try:
            from src.tools.tushare_api import get_stock_name
        except Exception:
            def get_stock_name(_ticker):
                return ""

        results, filtered_count, stock_name = load_company_news_results(
            ticker=ticker,
            end_date=end_date,
            start_date=start_date,
            limit=limit,
            fetch_news_df_fn=lambda: _cached_akshare_dataframe_call(
                "stock_news_em",
                ak.stock_news_em,
                symbol=symbol,
                cache_key_kwargs={
                    "symbol": symbol,
                    "start_date": start_date,
                    "end_date": end_date,
                },
            ),
            resolve_stock_name_fn=lambda: resolve_stock_name(get_stock_name, ticker),
            sort_news_dataframe_fn=sort_news_dataframe,
            build_filtered_company_news_fn=lambda **kwargs: build_filtered_company_news(
                is_news_relevant_to_stock_fn=_is_news_relevant_to_stock,
                classify_news_sentiment_fn=_classify_news_sentiment,
                deduplicate_news_fn=_deduplicate_news,
                **kwargs,
            ),
        )

        if filtered_count > 0:
            print(f"[AKShare] 已过滤 {filtered_count} 篇与 {ticker}({stock_name}) 无直接关联的通用市场文章")

        return results
    except Exception as e:
        print(f"[AKShare] 获取 A 股新闻失败 ({ticker}): {e}")
        return []


# ============================================================================
# 以下为机构级多策略框架（Phase 0.2）新增接口
# ============================================================================


def get_realtime_quotes(tickers: list[str] | None = None) -> pd.DataFrame | None:
    """
    获取 A 股盘中实时行情（全部或指定标的）。

    参数:
        tickers: 股票代码列表（6 位数字），None 表示全市场

    返回 DataFrame 列: 代码, 名称, 最新价, 涨跌幅, 涨跌额, 成交量, 成交额,
                       振幅, 最高, 最低, 今开, 昨收, 量比, 换手率, 市盈率, 市净率
    """
    return load_optional_market_dataframe(
        is_available=_akshare_available,
        unavailable_message="[AKShare] akshare 未安装",
        fetch_dataframe_fn=ak.stock_zh_a_spot_em,
        error_message="[AKShare] get_realtime_quotes 失败",
        transform_fn=(lambda df: df[df["代码"].isin(tickers)] if tickers else df),
    )


def get_industry_realtime() -> pd.DataFrame | None:
    """
    获取行业板块实时行情。

    返回 DataFrame 列: 排名, 板块名称, 板块代码, 最新价, 涨跌幅, 涨跌额,
                       成交量, 成交额, 换手率, 上涨家数, 下跌家数, 领涨股票, 最新价_领涨
    """
    return load_optional_market_dataframe(
        is_available=_akshare_available,
        unavailable_message="[AKShare] akshare 未安装",
        fetch_dataframe_fn=ak.stock_board_industry_name_em,
        error_message="[AKShare] get_industry_realtime 失败",
    )


def get_money_flow(ticker: str) -> pd.DataFrame | None:
    """
    获取个股主力资金流向。

    参数:
        ticker: 6 位股票代码

    返回 DataFrame 列: 日期, 收盘价, 涨跌幅, 主力净流入, 主力净流入占比,
                       超大单净流入, 大单净流入, 中单净流入, 小单净流入
    """
    return load_optional_market_dataframe(
        is_available=_akshare_available,
        unavailable_message="[AKShare] akshare 未安装",
        fetch_dataframe_fn=lambda: ak.stock_individual_fund_flow(stock=ticker, market="sh" if ticker.startswith("6") else "sz"),
        error_message=f"[AKShare] get_money_flow({ticker}) 失败",
    )


# 导出函数
__all__ = [
    "get_prices",
    "get_financial_metrics",
    "get_stock_info",
    "search_stocks",
    "is_ashare",
    "AShareTicker",
    "get_mock_prices",
    "get_mock_financial_metrics",
    "get_realtime_quote_sina",
    "AShareDataError",
    "get_sina_historical_data",
    "get_prices_robust",
    "get_ashare_company_news",
    "get_realtime_quotes",
    "get_industry_realtime",
    "get_money_flow",
]
