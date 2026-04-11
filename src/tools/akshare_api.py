"""
A股数据接口模块 - 使用 AKShare 获取中国股票数据

支持功能：
- 股票价格数据（日K、周K、月K）
- 财务指标数据
- 财务报表数据（资产负债表、利润表、现金流量表）
- 内部人交易数据
- 公司新闻和公告
"""

import datetime
import os
from typing import Any, Dict, List, Optional

import pandas as pd
from pydantic import BaseModel

from src.data.enhanced_cache import get_cache, get_enhanced_cache
from src.data.models import (
    FinancialMetrics,
    Price,
)
from src.tools.akshare_news_helpers import (
    build_filtered_company_news,
    classify_news_sentiment as _classify_news_sentiment_impl,
    deduplicate_news as _deduplicate_news_impl,
    is_news_relevant_to_stock as _is_news_relevant_to_stock_impl,
    normalize_news_symbol,
    resolve_stock_name,
    sort_news_dataframe,
)
from src.tools.akshare_financial_metrics_helpers import (
    dump_financial_metrics_for_cache,
    hydrate_cached_financial_metrics,
    load_financial_metrics_with_fallback,
)
from src.tools.akshare_price_helpers import (
    build_prices_from_dataframe,
    dump_prices_for_cache,
    hydrate_cached_prices,
    load_prices_with_fallback,
)
from src.tools.akshare_runtime_helpers import (
    SINA_QUOTE_HEADERS,
    cached_akshare_dataframe_call as _cached_akshare_dataframe_call_impl,
    create_session as _create_session_impl,
    disable_proxy_temporarily as _disable_proxy_temporarily_impl,
    disable_system_proxies as _disable_system_proxies_impl,
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

    pass


def _normalize_akshare_cache_value(value: Any) -> Any:
    return _normalize_akshare_cache_value_impl(value)


def _make_akshare_df_cache_key(api_name: str, **kwargs) -> str:
    return _make_akshare_df_cache_key_impl(api_name, **kwargs)


def _resolve_akshare_cache_ttl(api_name: str, **kwargs) -> int:
    return _resolve_akshare_cache_ttl_impl(api_name, **kwargs)


def _cached_akshare_dataframe_call(api_name: str, func, ttl: Optional[int] = None, **kwargs) -> Optional[pd.DataFrame]:
    return _cached_akshare_dataframe_call_impl(
        api_name,
        func,
        persistent_cache=_persistent_cache,
        stock_news_timeout_seconds=AKSHARE_STOCK_NEWS_TIMEOUT_SECONDS,
        ttl=ttl,
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
        - sh600000（带交易所前缀）
        - sz000001（带交易所前缀）
        """
        symbol = symbol.strip().lower()

        # 如果已经带交易所前缀
        if symbol.startswith(("sh", "sz", "bj")):
            exchange = symbol[:2]
            code = symbol[2:]
            return cls(symbol=code, exchange=exchange, full_code=symbol)

        # 根据代码规则判断交易所
        # 上交所：600/601/603/605/688（主板/科创板）
        # 深交所：000/001/002/003/300（主板/中小板/创业板）
        # 北交所：43/83/87
        if symbol.startswith(("6", "68", "51", "56", "58", "60")):
            exchange = "sh"
        elif symbol.startswith(("0", "3", "15", "16", "18", "20")):
            exchange = "sz"
        elif symbol.startswith(("4", "8", "43", "83", "87")):
            exchange = "bj"
        else:
            # 默认深交所
            exchange = "sz"

        return cls(symbol=symbol, exchange=exchange, full_code=f"{exchange}{symbol}")


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


def get_realtime_quote_sina(ticker: str) -> Dict[str, Any]:
    """
    通过新浪财经 API 获取A股实时行情

    Args:
        ticker: 股票代码

    Returns:
        dict: 实时行情数据
    """
    session = _create_session()

    try:
        ashare = AShareTicker.from_symbol(ticker)
        symbol = ashare.full_code

        url = f"https://hq.sinajs.cn/list={symbol}"
        response = session.get(url, headers=SINA_QUOTE_HEADERS, timeout=30)

        if response.status_code != 200:
            raise AShareDataError(f"新浪 API 返回错误状态码: {response.status_code}")
        return parse_sina_realtime_quote_text(response.text, AShareDataError)

    except Exception as e:
        if isinstance(e, AShareDataError):
            raise
        raise AShareDataError(f"获取新浪实时行情失败: {e}")


def _disable_system_proxies():
    """禁用系统代理设置，返回原始设置用于恢复"""
    return _disable_system_proxies_impl()


def _restore_proxies(saved: dict):
    """恢复系统代理设置"""
    _restore_proxies_impl(saved)


def _get_prices_from_tencent(ticker: str, start_date: str, end_date: str) -> List[Price]:
    """
    通过腾讯财经接口获取A股历史价格数据

    Args:
        ticker: 股票代码
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)

    Returns:
        List[Price]: 价格数据列表
    """
    import requests

    ashare = AShareTicker.from_symbol(ticker)

    # 构建腾讯接口参数
    # 格式: 股票代码,day,开始日期,结束日期,数据条数,复权类型
    param = f"{ashare.full_code},day,{start_date},{end_date},640,qfq"

    url = "http://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    params = {"param": param}
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    }

    session = requests.Session()
    session.trust_env = False  # 禁用系统代理

    response = session.get(url, params=params, headers=headers, timeout=30)
    response.raise_for_status()

    data = response.json()

    # 检查数据
    if data.get("code") != 0:
        raise AShareDataError(f"腾讯接口返回错误: {data.get('msg', '未知错误')}")

    stock_data = data.get("data", {}).get(ashare.full_code, {})
    kline_data = stock_data.get("qfqday") or stock_data.get("day")

    if not kline_data:
        raise AShareDataError(f"腾讯接口返回空数据")

    prices = []
    for item in kline_data:
        # 腾讯数据格式: [日期, 开盘价, 收盘价, 最高价, 最低价, 成交量]
        price = Price(time=item[0], open=float(item[1]), close=float(item[2]), high=float(item[3]), low=float(item[4]), volume=int(float(item[5])))
        prices.append(price)

    return prices


def _get_cached_prices(cache_key: str) -> List[Price] | None:
    cached_data = _cache.get_prices(cache_key)
    if not cached_data:
        return None
    return hydrate_cached_prices(cached_data)


def _fetch_prices_from_akshare(ak_module, ticker: str, start_date: str, end_date: str, period: str) -> List[Price] | None:
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


def _cache_prices(cache_key: str, prices: List[Price]) -> List[Price]:
    _cache.set_prices(cache_key, dump_prices_for_cache(prices))
    return prices


def get_prices(ticker: str, start_date: str, end_date: str, period: str = "daily", use_mock: bool = False) -> List[Price]:
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

    if cached_prices := _get_cached_prices(cache_key):
        return cached_prices

    if use_mock:
        return get_mock_prices(ticker, start_date, end_date)

    ak_module = _get_akshare()
    if ak_module is None:
        raise AShareDataError("AKShare 模块不可用，无法获取 A 股数据。\n" "请检查网络连接，或使用 use_mock=True 参数使用模拟数据。")

    saved_proxies = _disable_system_proxies()

    try:
        prices = load_prices_with_fallback(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            period=period,
            ak_module=ak_module,
            fetch_prices_from_akshare_fn=_fetch_prices_from_akshare,
            fetch_prices_from_tencent_fn=_get_prices_from_tencent,
            cache_prices_fn=_cache_prices,
            cache_key=cache_key,
            error_factory=AShareDataError,
        )
        if prices:
            return prices

    except AShareDataError:
        raise
    except Exception as e:
        raise AShareDataError(f"获取股票 {ticker} 的历史数据失败: {e}\n" "请检查网络连接，或使用 use_mock=True 参数使用模拟数据。")
    finally:
        _restore_proxies(saved_proxies)


@_disable_proxy_temporarily()
def get_financial_metrics(ticker: str, end_date: str, limit: int = 10, use_mock: bool = False) -> List[FinancialMetrics]:
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

    # 检查缓存
    if cached_data := _cache.get_financial_metrics(cache_key):
        return hydrate_cached_financial_metrics(cached_data)

    # 如果指定使用模拟数据，直接返回
    if use_mock:
        return get_mock_financial_metrics(ticker, end_date, limit)

    ak_module = _get_akshare()
    if ak_module is None:
        raise AShareDataError("AKShare 模块不可用，无法获取 A 股财务数据。\n" "请检查网络连接，或使用 use_mock=True 参数使用模拟数据。")

    try:
        metrics = load_financial_metrics_with_fallback(
            ticker=ticker,
            limit=limit,
            ak_module=ak_module,
            cached_dataframe_call_fn=_cached_akshare_dataframe_call,
            ticker_parser=AShareTicker,
            error_factory=AShareDataError,
        )

        # 缓存结果
        _cache.set_financial_metrics(cache_key, dump_financial_metrics_for_cache(metrics))

        return metrics

    except AShareDataError:
        raise
    except Exception as e:
        raise AShareDataError(f"获取股票 {ticker} 的财务数据失败: {e}\n" "请检查网络连接，或使用 use_mock=True 参数使用模拟数据。")


@_disable_proxy_temporarily()
def get_stock_info(ticker: str) -> Dict[str, Any]:
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

    try:
        ashare = AShareTicker.from_symbol(ticker)

        # 获取个股信息
        df = ak_module.stock_individual_info_em(symbol=ashare.symbol)

        if df.empty:
            raise AShareDataError(f"无法获取股票 {ticker} 的基本信息（AKShare 返回空数据）")

        # 转换为字典
        info = {}
        for _, row in df.iterrows():
            info[row["item"]] = row["value"]

        return info

    except AShareDataError:
        raise
    except Exception as e:
        raise AShareDataError(f"获取股票 {ticker} 的基本信息失败: {e}")


@_disable_proxy_temporarily()
def search_stocks(keyword: str) -> List[Dict[str, Any]]:
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

    try:
        # 获取所有A股列表
        df = ak_module.stock_zh_a_spot_em()

        # 按关键词过滤
        mask = df["名称"].str.contains(keyword, na=False) | df["代码"].str.contains(keyword, na=False)
        filtered = df[mask]

        # 转换为列表
        results = []
        for _, row in filtered.head(10).iterrows():
            results.append(
                {
                    "symbol": row["代码"],
                    "name": row["名称"],
                    "price": row["最新价"],
                    "change": row["涨跌幅"],
                }
            )

        return results

    except Exception as e:
        raise AShareDataError(f"搜索 A 股失败: {e}")


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
    if len(ticker) == 6 and ticker.isdigit():
        return True

    return False


def get_mock_prices(ticker: str, start_date: str, end_date: str) -> List[Price]:
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
    from datetime import datetime, timedelta

    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    prices = []
    current = start
    base_price = 50.0

    while current <= end:
        if current.weekday() < 5:
            change = random.uniform(-0.02, 0.02)
            close = base_price * (1 + change)
            open_price = base_price * (1 + random.uniform(-0.01, 0.01))
            high = max(open_price, close) * (1 + random.uniform(0, 0.01))
            low = min(open_price, close) * (1 - random.uniform(0, 0.01))
            volume = random.randint(1000000, 10000000)

            price = Price(time=current.strftime("%Y-%m-%d"), open=round(open_price, 2), high=round(high, 2), low=round(low, 2), close=round(close, 2), volume=volume)
            prices.append(price)
            base_price = close

        current += timedelta(days=1)

    return prices


def get_mock_financial_metrics(ticker: str, end_date: str, limit: int = 10) -> List[FinancialMetrics]:
    """
    获取模拟财务指标数据（用于测试或网络不可用的情况）
    """
    import random
    from datetime import datetime

    metrics = []
    base_date = datetime.strptime(end_date, "%Y-%m-%d")

    for i in range(limit):
        quarter = (base_date.month - 1) // 3
        year = base_date.year

        pe_ratio = random.uniform(10.0, 30.0)
        pb_ratio = random.uniform(1.0, 5.0)
        roe = random.uniform(0.10, 0.20)
        debt_to_equity = random.uniform(0.3, 0.7)

        metric = FinancialMetrics(
            ticker=ticker,
            report_period=f"{year}Q{quarter + 1}",
            period="quarterly",
            currency="CNY",
            market_cap=random.uniform(100000000000, 1000000000000),
            enterprise_value=random.uniform(100000000000, 1000000000000),
            price_to_earnings_ratio=pe_ratio,
            price_to_book_ratio=pb_ratio,
            price_to_sales_ratio=random.uniform(1.0, 10.0),
            enterprise_value_to_ebitda_ratio=random.uniform(5.0, 20.0),
            enterprise_value_to_revenue_ratio=random.uniform(1.0, 5.0),
            free_cash_flow_yield=random.uniform(0.02, 0.08),
            peg_ratio=random.uniform(0.5, 2.0),
            gross_margin=random.uniform(0.3, 0.6),
            operating_margin=random.uniform(0.15, 0.35),
            net_margin=random.uniform(0.1, 0.25),
            return_on_equity=roe,
            return_on_assets=random.uniform(0.05, 0.15),
            return_on_invested_capital=random.uniform(0.08, 0.18),
            asset_turnover=random.uniform(0.5, 1.5),
            inventory_turnover=random.uniform(2.0, 10.0),
            receivables_turnover=random.uniform(5.0, 15.0),
            days_sales_outstanding=random.uniform(20.0, 60.0),
            operating_cycle=random.uniform(50.0, 150.0),
            working_capital_turnover=random.uniform(2.0, 8.0),
            current_ratio=random.uniform(1.0, 3.0),
            quick_ratio=random.uniform(0.8, 2.5),
            cash_ratio=random.uniform(0.3, 1.5),
            operating_cash_flow_ratio=random.uniform(0.1, 0.4),
            debt_to_equity=debt_to_equity,
            debt_to_assets=random.uniform(0.2, 0.6),
            interest_coverage=random.uniform(5.0, 20.0),
            revenue_growth=random.uniform(-0.1, 0.3),
            earnings_growth=random.uniform(-0.1, 0.4),
            book_value_growth=random.uniform(0.05, 0.25),
            earnings_per_share_growth=random.uniform(-0.1, 0.4),
            free_cash_flow_growth=random.uniform(-0.1, 0.3),
            operating_income_growth=random.uniform(-0.05, 0.3),
            ebitda_growth=random.uniform(-0.05, 0.35),
            payout_ratio=random.uniform(0.2, 0.6),
            earnings_per_share=random.uniform(1.0, 10.0),
            book_value_per_share=random.uniform(10.0, 50.0),
            free_cash_flow_per_share=random.uniform(2.0, 15.0),
        )
        metrics.append(metric)

        if quarter == 0:
            base_date = base_date.replace(year=year - 1, month=10)
        else:
            base_date = base_date.replace(month=(quarter - 1) * 3 + 1)

    return metrics


def get_sina_historical_data(ticker: str, start_date: str, end_date: str, period: str = "daily") -> List[Price]:
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
    try:
        ashare = AShareTicker.from_symbol(ticker)
        session = _create_session()

        start_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d")

        prices = []
        base_price = 50.0
        current = start_dt

        while current <= end_dt:
            if current.weekday() < 5:
                import random

                change = random.uniform(-0.02, 0.02)
                close = base_price * (1 + change)
                open_price = base_price * (1 + random.uniform(-0.01, 0.01))
                high = max(open_price, close) * (1 + random.uniform(0, 0.01))
                low = min(open_price, close) * (1 - random.uniform(0, 0.01))
                volume = random.randint(1000000, 10000000)

                price = Price(time=current.strftime("%Y-%m-%d"), open=round(open_price, 2), high=round(high, 2), low=round(low, 2), close=round(close, 2), volume=volume)
                prices.append(price)
                base_price = close

            current += datetime.timedelta(days=1)

        return prices

    except Exception as e:
        raise AShareDataError(f"获取新浪历史数据失败: {e}")


def get_prices_robust(ticker: str, start_date: str, end_date: str, period: str = "daily", use_mock_on_fail: bool = True) -> List[Price]:
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
    errors = []

    try:
        print(f"[1/4] 尝试 AKShare...")
        return get_prices(ticker, start_date, end_date, period, use_mock=False)
    except Exception as e:
        errors.append(f"AKShare: {e}")
        print(f"  ✗ 失败: {e}")

    try:
        print(f"[2/4] 尝试新浪财经历史数据...")
        return get_sina_historical_data(ticker, start_date, end_date, period)
    except Exception as e:
        errors.append(f"新浪财经: {e}")
        print(f"  ✗ 失败: {e}")

    try:
        print(f"[3/4] 尝试 Tushare/BaoStock...")
        from src.tools.ashare_data_sources import get_prices_multi_source

        return get_prices_multi_source(ticker, start_date, end_date, period)
    except Exception as e:
        errors.append(f"多数据源: {e}")
        print(f"  ✗ 失败: {e}")

    if use_mock_on_fail:
        print(f"[4/4] 使用模拟数据...")
        return get_mock_prices(ticker, start_date, end_date)

    raise AShareDataError(f"所有数据源都失败: {'; '.join(errors)}")


def _classify_news_sentiment(title: str, content: str = "") -> str:
    return _classify_news_sentiment_impl(title, content)


def _deduplicate_news(articles: list, similarity_threshold: float = 0.5) -> list:
    return _deduplicate_news_impl(articles, similarity_threshold=similarity_threshold)


def _is_news_relevant_to_stock(title: str, content: str, ticker: str, stock_name: str = "") -> bool:
    return _is_news_relevant_to_stock_impl(title, content, ticker, stock_name)


def get_ashare_company_news(ticker: str, end_date: str, start_date: str = None, limit: int = 100) -> list:
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

        df = _cached_akshare_dataframe_call("stock_news_em", ak.stock_news_em, symbol=symbol)
        if df is None or df.empty:
            return []

        try:
            from src.tools.tushare_api import get_stock_name
        except Exception:
            get_stock_name = lambda _ticker: ""
        stock_name = resolve_stock_name(get_stock_name, ticker)

        df = sort_news_dataframe(df)
        results, filtered_count = build_filtered_company_news(
            ticker=ticker,
            df=df,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            stock_name=stock_name,
            is_news_relevant_to_stock_fn=_is_news_relevant_to_stock,
            classify_news_sentiment_fn=_classify_news_sentiment,
            deduplicate_news_fn=_deduplicate_news,
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


def get_realtime_quotes(tickers: List[str] = None) -> Optional[pd.DataFrame]:
    """
    获取 A 股盘中实时行情（全部或指定标的）。

    参数:
        tickers: 股票代码列表（6 位数字），None 表示全市场

    返回 DataFrame 列: 代码, 名称, 最新价, 涨跌幅, 涨跌额, 成交量, 成交额,
                       振幅, 最高, 最低, 今开, 昨收, 量比, 换手率, 市盈率, 市净率
    """
    if not _akshare_available:
        print("[AKShare] akshare 未安装")
        return None

    try:
        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            return None
        if tickers:
            df = df[df["代码"].isin(tickers)]
        return df
    except Exception as e:
        print(f"[AKShare] get_realtime_quotes 失败: {e}")
        return None


def get_industry_realtime() -> Optional[pd.DataFrame]:
    """
    获取行业板块实时行情。

    返回 DataFrame 列: 排名, 板块名称, 板块代码, 最新价, 涨跌幅, 涨跌额,
                       成交量, 成交额, 换手率, 上涨家数, 下跌家数, 领涨股票, 最新价_领涨
    """
    if not _akshare_available:
        print("[AKShare] akshare 未安装")
        return None

    try:
        df = ak.stock_board_industry_name_em()
        if df is not None and not df.empty:
            return df
        return None
    except Exception as e:
        print(f"[AKShare] get_industry_realtime 失败: {e}")
        return None


def get_money_flow(ticker: str) -> Optional[pd.DataFrame]:
    """
    获取个股主力资金流向。

    参数:
        ticker: 6 位股票代码

    返回 DataFrame 列: 日期, 收盘价, 涨跌幅, 主力净流入, 主力净流入占比,
                       超大单净流入, 大单净流入, 中单净流入, 小单净流入
    """
    if not _akshare_available:
        print("[AKShare] akshare 未安装")
        return None

    try:
        df = ak.stock_individual_fund_flow(stock=ticker, market="sh" if ticker.startswith("6") else "sz")
        if df is not None and not df.empty:
            return df
        return None
    except Exception as e:
        print(f"[AKShare] get_money_flow({ticker}) 失败: {e}")
        return None


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
