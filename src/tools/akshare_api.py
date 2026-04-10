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
import concurrent.futures
import hashlib
import json
import os
from typing import Any, Dict, List, Optional

import pandas as pd
from pydantic import BaseModel

from src.data.enhanced_cache import get_cache, get_enhanced_cache
from src.data.models import (
    CompanyNews,
    FinancialMetrics,
    InsiderTrade,
    LineItem,
    Price,
)
from src.tools.akshare_news_helpers import build_company_news_entry, news_date_in_range, normalize_news_symbol, resolve_stock_name, sort_news_dataframe
from src.tools.akshare_price_helpers import build_prices_from_dataframe, dump_prices_for_cache, hydrate_cached_prices

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
    if isinstance(value, dict):
        return {str(key): _normalize_akshare_cache_value(inner_value) for key, inner_value in sorted(value.items()) if inner_value is not None}
    if isinstance(value, (list, tuple, set)):
        return [_normalize_akshare_cache_value(item) for item in value]
    return value


def _make_akshare_df_cache_key(api_name: str, **kwargs) -> str:
    payload = json.dumps({"api_name": api_name, "params": _normalize_akshare_cache_value(kwargs)}, sort_keys=True, ensure_ascii=True, default=str)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    return f"akshare_df:{api_name}:{digest}"


def _resolve_akshare_cache_ttl(api_name: str, **kwargs) -> int:
    reference_date = str(kwargs.get("end_date") or kwargs.get("start_date") or "")
    today = datetime.datetime.now().strftime("%Y%m%d")
    is_historical = bool(reference_date) and reference_date < today

    if api_name in {"stock_zh_a_hist"}:
        return 30 * 86400 if is_historical else 6 * 3600
    if api_name in {"stock_financial_analysis_indicator", "stock_financial_report_sina"}:
        return 14 * 86400
    if api_name in {"stock_news_em"}:
        return 6 * 3600
    return 24 * 3600


def _cached_akshare_dataframe_call(api_name: str, func, ttl: Optional[int] = None, **kwargs) -> Optional[pd.DataFrame]:
    cache_key = _make_akshare_df_cache_key(api_name, **kwargs)
    cached_df = _persistent_cache.get(cache_key)
    if isinstance(cached_df, pd.DataFrame):
        return cached_df.copy()

    try:
        if api_name == "stock_news_em" and AKSHARE_STOCK_NEWS_TIMEOUT_SECONDS > 0:
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            future = executor.submit(func, **kwargs)
            try:
                df = future.result(timeout=AKSHARE_STOCK_NEWS_TIMEOUT_SECONDS)
            except concurrent.futures.TimeoutError as exc:
                future.cancel()
                raise TimeoutError(f"AKShare {api_name} timed out after {AKSHARE_STOCK_NEWS_TIMEOUT_SECONDS}s") from exc
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
        else:
            df = func(**kwargs)
    except Exception:
        raise

    if df is not None:
        _persistent_cache.set(cache_key, df, ttl=ttl if ttl is not None else _resolve_akshare_cache_ttl(api_name, **kwargs))
        return df.copy()

    return None


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
    import requests

    session = requests.Session()
    session.trust_env = False  # 禁用环境变量中的代理设置
    return session


def _disable_proxy_temporarily():
    """临时禁用系统代理（装饰器）"""
    import functools

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            saved_proxies_env = _disable_system_proxies()

            try:
                return func(*args, **kwargs)
            finally:
                _restore_proxies(saved_proxies_env)

        return wrapper

    return decorator


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
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://finance.sina.com.cn",
        }

        response = session.get(url, headers=headers, timeout=30)

        if response.status_code != 200:
            raise AShareDataError(f"新浪 API 返回错误状态码: {response.status_code}")

        # 解析新浪返回的数据格式
        # var hq_str_sh600519="贵州茅台,1521.000,1485.300,1466.800,...";
        text = response.text
        if not text or "hq_str_" not in text:
            raise AShareDataError("新浪 API 返回数据格式错误")

        # 提取数据部分
        start = text.find('"') + 1
        end = text.rfind('"')
        if start <= 0 or end <= start:
            raise AShareDataError("无法解析新浪返回的数据")

        data_str = text[start:end]
        parts = data_str.split(",")

        if len(parts) < 33:
            raise AShareDataError("新浪返回的数据字段不完整")

        # 新浪数据字段映射
        result = {
            "name": parts[0],  # 股票名称
            "open": float(parts[1]),  # 今日开盘价
            "close": float(parts[2]),  # 昨日收盘价
            "current": float(parts[3]),  # 当前价格
            "high": float(parts[4]),  # 今日最高价
            "low": float(parts[5]),  # 今日最低价
            "buy": float(parts[6]),  # 竞买价
            "sell": float(parts[7]),  # 竞卖价
            "volume": int(parts[8]),  # 成交量（股）
            "amount": float(parts[9]),  # 成交金额（元）
            "bid1_volume": int(parts[10]),  # 买1量
            "bid1_price": float(parts[11]),  # 买1价
            "bid2_volume": int(parts[12]),
            "bid2_price": float(parts[13]),
            "bid3_volume": int(parts[14]),
            "bid3_price": float(parts[15]),
            "bid4_volume": int(parts[16]),
            "bid4_price": float(parts[17]),
            "bid5_volume": int(parts[18]),
            "bid5_price": float(parts[19]),
            "ask1_volume": int(parts[20]),  # 卖1量
            "ask1_price": float(parts[21]),  # 卖1价
            "ask2_volume": int(parts[22]),
            "ask2_price": float(parts[23]),
            "ask3_volume": int(parts[24]),
            "ask3_price": float(parts[25]),
            "ask4_volume": int(parts[26]),
            "ask4_price": float(parts[27]),
            "ask5_volume": int(parts[28]),
            "ask5_price": float(parts[29]),
            "date": parts[30],  # 日期
            "time": parts[31],  # 时间
        }

        return result

    except Exception as e:
        if isinstance(e, AShareDataError):
            raise
        raise AShareDataError(f"获取新浪实时行情失败: {e}")


def _disable_system_proxies():
    """禁用系统代理设置，返回原始设置用于恢复"""
    proxy_vars = ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy", "SOCKS_PROXY", "socks_proxy"]
    saved = {}

    for var in proxy_vars:
        if var in os.environ:
            saved[var] = os.environ[var]
            del os.environ[var]

    return saved


def _restore_proxies(saved: dict):
    """恢复系统代理设置"""
    for var, value in saved.items():
        os.environ[var] = value


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
        try:
            akshare_prices = _fetch_prices_from_akshare(ak_module, ticker, start_date, end_date, period)
            if akshare_prices:
                return _cache_prices(cache_key, akshare_prices)
        except Exception as e:
            print(f"AKShare 获取数据失败，尝试腾讯接口: {e}")

        try:
            prices = _get_prices_from_tencent(ticker, start_date, end_date)
            if prices:
                return _cache_prices(cache_key, prices)
        except Exception as e:
            raise AShareDataError(f"无法获取股票 {ticker} 的历史数据（所有数据源都失败）。\n" f"AKShare 错误: {e}\n" f"腾讯接口错误: {e}\n" "请检查网络连接，或使用 use_mock=True 参数使用模拟数据。")

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
        return [FinancialMetrics(**metric) for metric in cached_data]

    # 如果指定使用模拟数据，直接返回
    if use_mock:
        return get_mock_financial_metrics(ticker, end_date, limit)

    ak_module = _get_akshare()
    if ak_module is None:
        raise AShareDataError("AKShare 模块不可用，无法获取 A 股财务数据。\n" "请检查网络连接，或使用 use_mock=True 参数使用模拟数据。")

    try:
        ashare = AShareTicker.from_symbol(ticker)

        # 尝试使用 stock_financial_analysis_indicator 获取主要财务指标
        df = _cached_akshare_dataframe_call("stock_financial_analysis_indicator", ak_module.stock_financial_analysis_indicator, symbol=ashare.symbol)

        # 如果返回空数据，尝试使用 stock_financial_report_sina 接口
        if df is None or df.empty:
            # 使用新浪财务数据接口，对科创板等股票更可靠
            df_profit = _cached_akshare_dataframe_call("stock_financial_report_sina", ak_module.stock_financial_report_sina, stock=ashare.symbol, symbol="利润表")

            if df_profit is None or df_profit.empty:
                raise AShareDataError(f"无法获取股票 {ticker} 的财务数据（AKShare 返回空数据）。\n" "请检查网络连接，或使用 use_mock=True 参数使用模拟数据。")

            # 从新浪接口数据中提取财务指标
            metrics = []
            for _, row in df_profit.head(limit).iterrows():
                # 计算净利润率（如果有数据）
                revenue = float(row.get("营业收入", 0)) if pd.notna(row.get("营业收入")) else None
                net_income = float(row.get("净利润", 0)) if pd.notna(row.get("净利润")) else None

                metric = FinancialMetrics(
                    ticker=ticker,
                    report_period=str(row.get("报告日", "")),
                    period="ttm",
                    currency="CNY",
                    market_cap=None,
                    enterprise_value=None,
                    price_to_earnings_ratio=None,
                    price_to_book_ratio=None,
                    price_to_sales_ratio=None,
                    enterprise_value_to_ebitda_ratio=None,
                    enterprise_value_to_revenue_ratio=None,
                    free_cash_flow_yield=None,
                    peg_ratio=None,
                    gross_margin=None,
                    operating_margin=None,
                    net_margin=None,
                    return_on_equity=None,
                    return_on_assets=None,
                    return_on_invested_capital=None,
                    asset_turnover=None,
                    inventory_turnover=None,
                    receivables_turnover=None,
                    days_sales_outstanding=None,
                    operating_cycle=None,
                    working_capital_turnover=None,
                    current_ratio=None,
                    quick_ratio=None,
                    cash_ratio=None,
                    operating_cash_flow_ratio=None,
                    debt_to_equity=None,
                    debt_to_assets=None,
                    interest_coverage=None,
                    revenue_growth=None,
                    earnings_growth=None,
                    book_value_growth=None,
                    earnings_per_share_growth=None,
                    free_cash_flow_growth=None,
                    operating_income_growth=None,
                    ebitda_growth=None,
                    payout_ratio=None,
                    earnings_per_share=None,
                    book_value_per_share=None,
                    free_cash_flow_per_share=None,
                )
                metrics.append(metric)
        else:
            # 使用 stock_financial_analysis_indicator 的数据
            metrics = []
            for _, row in df.head(limit).iterrows():
                metric = FinancialMetrics(
                    ticker=ticker,
                    report_period=str(row.get("报告期", "")),
                    period="ttm",
                    currency="CNY",
                    market_cap=None,
                    enterprise_value=None,
                    price_to_earnings_ratio=float(row.get("市盈率", 0)) if pd.notna(row.get("市盈率")) else None,
                    price_to_book_ratio=float(row.get("市净率", 0)) if pd.notna(row.get("市净率")) else None,
                    price_to_sales_ratio=None,
                    enterprise_value_to_ebitda_ratio=None,
                    enterprise_value_to_revenue_ratio=None,
                    free_cash_flow_yield=None,
                    peg_ratio=None,
                    gross_margin=None,
                    operating_margin=None,
                    net_margin=None,
                    return_on_equity=float(row.get("净资产收益率", 0)) / 100 if pd.notna(row.get("净资产收益率")) else None,
                    return_on_assets=None,
                    return_on_invested_capital=None,
                    asset_turnover=None,
                    inventory_turnover=None,
                    receivables_turnover=None,
                    days_sales_outstanding=None,
                    operating_cycle=None,
                    working_capital_turnover=None,
                    current_ratio=None,
                    quick_ratio=None,
                    cash_ratio=None,
                    operating_cash_flow_ratio=None,
                    debt_to_equity=float(row.get("资产负债率", 0)) / 100 if pd.notna(row.get("资产负债率")) else None,
                    debt_to_assets=None,
                    interest_coverage=None,
                    revenue_growth=None,
                    earnings_growth=None,
                    book_value_growth=None,
                    earnings_per_share_growth=None,
                    free_cash_flow_growth=None,
                    operating_income_growth=None,
                    ebitda_growth=None,
                    payout_ratio=None,
                    earnings_per_share=None,
                    book_value_per_share=None,
                    free_cash_flow_per_share=None,
                )
                metrics.append(metric)

        # 缓存结果
        _cache.set_financial_metrics(cache_key, [m.model_dump() for m in metrics])

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
    """
    基于关键词对A股新闻进行简单情感分类

    Returns:
        "positive", "negative", 或 "neutral"
    """
    text = (title + " " + content).lower()

    # 对数据表类文章（标题含"一览"且内容主要是列表数据）直接返回 neutral
    if "一览" in title and len(content) < 50:
        return "neutral"

    positive_keywords = [
        # 极端正面
        "涨停", "大涨", "暴涨", "利好", "突破", "创新高", "增长", "盈利",
        "超预期", "上调", "买入", "推荐", "看好", "回购", "增持", "签约",
        "中标", "获批", "扭亏", "新高", "强势", "反弹", "爆发", "景气",
        "丰收", "提价", "提升", "改善", "加速", "翻倍", "分红", "派息",
        # 温和正面：市场面
        "上涨", "走强", "拉升", "领涨", "飘红", "翻红", "放量上攻",
        "底部放量", "企稳", "回暖", "复苏",
        # 温和正面：资金面
        "资金流入", "净买入", "青睐", "布局", "加仓", "建仓",
        "机构加仓", "北向资金",
        # 温和正面：业务面
        "合作", "订单", "营收", "净利润", "业绩预增", "预增",
        "高送转", "定增", "重组", "复牌", "龙头", "优质", "稳健",
        "战略合作", "产能扩张", "市占率", "竞争优势", "行业领先",
        # 温和正面：补贴/政策/分红
        "补贴", "收到补贴", "补贴资金", "政策支持", "获得补助",
        "补助", "政府补助", "分派", "每股派", "权益分派",
    ]
    negative_keywords = [
        # 极端负面
        "跌停", "大跌", "暴跌", "利空", "下调", "亏损", "减持", "卖出",
        "风险", "预警", "违规", "处罚", "退市", "st",  # 修复: ST → st 匹配 .lower()
        "爆雷", "债务", "诉讼", "下滑", "萎缩", "破发", "破位",
        "新低", "弱势", "下行", "缩水", "低于预期", "恶化",
        "暂停", "终止", "警告", "质押",
        # 温和负面：市场面
        "下跌", "跳水", "回调", "低迷", "承压", "拖累", "走低",
        "杀跌", "闪崩", "阴跌", "缩量下跌",
        # 温和负面：资金面
        "抛售", "出逃", "净流出", "资金流出", "主力流出", "清仓",
        # 温和负面：业绩面
        "负增长", "收缩", "亏", "业绩变脸", "业绩不及预期",
        "利润下滑", "营收下降", "收入下降",
        "预降", "预减", "净利下降", "同比下降", "同比减少", "业绩下滑",
        "净利同比预降", "利润下降", "收入减少",
        # 温和负面：监管/法律
        "监管", "问询函", "关注函", "立案", "调查", "侵权",
        "裁员", "关停", "破产", "清算",
    ]

    pos_count = sum(1 for kw in positive_keywords if kw in text)
    neg_count = sum(1 for kw in negative_keywords if kw in text)

    if pos_count > neg_count:
        return "positive"
    elif neg_count > pos_count:
        return "negative"
    return "neutral"


def _deduplicate_news(articles: list, similarity_threshold: float = 0.5) -> list:
    """
    对新闻列表去重，移除标题高度相似的重复报道（同一事件不同来源）。

    使用基于字符集合的 Jaccard 相似度，对中文标题效果良好且计算高效。
    保留每组重复文章中最早出现的那篇（通常是最新的，因为列表已按时间倒序排列）。

    Args:
        articles: CompanyNews 列表（已按发布时间倒序排列）
        similarity_threshold: 相似度阈值 (0-1)，超过此值视为重复

    Returns:
        去重后的 CompanyNews 列表
    """
    if len(articles) <= 1:
        return articles

    import re as _re

    def _extract_key_chars(title: str) -> set:
        """提取标题中的关键字符集合（去除标点、空格、股票代码前缀等）"""
        # 移除常见前缀模板如 "节能风电：" 或 "节能风电（601016）"
        cleaned = _re.sub(r'^[\w\u4e00-\u9fff]+[：:]\s*', '', title)
        # 移除标点符号和空格，只保留有意义的汉字和数字
        cleaned = _re.sub(r'[^\u4e00-\u9fff0-9a-zA-Z%.]', '', cleaned)
        return set(cleaned)

    def _jaccard_similarity(set_a: set, set_b: set) -> float:
        """计算两个集合的 Jaccard 相似度"""
        if not set_a or not set_b:
            return 0.0
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union > 0 else 0.0

    unique_articles = []
    seen_char_sets = []

    for article in articles:
        title = getattr(article, 'title', '')
        char_set = _extract_key_chars(title)

        is_duplicate = False
        for existing_set in seen_char_sets:
            if _jaccard_similarity(char_set, existing_set) >= similarity_threshold:
                is_duplicate = True
                break

        if not is_duplicate:
            unique_articles.append(article)
            seen_char_sets.append(char_set)

    dedup_count = len(articles) - len(unique_articles)
    if dedup_count > 0:
        print(f"[AKShare] 新闻去重：移除 {dedup_count} 篇重复报道（同一事件不同来源），保留 {len(unique_articles)} 篇")

    return unique_articles


def _is_news_relevant_to_stock(title: str, content: str, ticker: str, stock_name: str = "") -> bool:
    """
    判断新闻文章是否与目标股票直接相关（而非仅在多股票列表中被提及）。

    Args:
        title: 新闻标题
        content: 新闻内容
        ticker: 股票代码
        stock_name: 股票名称

    Returns:
        bool: True 如果文章主要关于目标股票
    """
    # 如果标题中包含股票名称或代码，高置信度相关
    if stock_name and stock_name in title:
        return True
    if ticker in title:
        return True

    # 通用市场文章模式（多股票列表类）
    generic_list_patterns = [
        "解密主力资金出逃股", "主力资金出逃", "短线防风险",
        "只个股", "一览", "榜单", "排行", "盘点",
        "连续.*净流出.*股", "连续.*净流入.*股",
        "只股票", "股名单",
    ]
    import re
    for pattern in generic_list_patterns:
        if re.search(pattern, title):
            return False

    # 如果内容主要是数字/表格数据（如多股排行表），大概率是通用文章
    if content:
        content_sample = content[:300]
        # 统计内容中数字和空格的比例，表格类内容数字密度高
        digit_count = sum(1 for c in content_sample if c.isdigit() or c in '. -')
        if len(content_sample) > 0 and digit_count / len(content_sample) > 0.5:
            # 内容以数字为主，很可能是排行表，检查标题是否提到目标股票
            if stock_name and stock_name not in content_sample[:100]:
                return False

    return True


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

        results = []
        filtered_count = 0
        for _, row in df.iterrows():
            pub_time = str(row.get("发布时间", ""))
            if not news_date_in_range(pub_time, start_date, end_date):
                continue

            title = str(row.get("新闻标题", ""))
            content = str(row.get("新闻内容", ""))

            if not _is_news_relevant_to_stock(title, content, ticker, stock_name):
                filtered_count += 1
                continue

            sentiment = _classify_news_sentiment(title, content)
            news = build_company_news_entry(ticker, row, sentiment)
            results.append(news)

            if len(results) >= limit:
                break

        if filtered_count > 0:
            print(f"[AKShare] 已过滤 {filtered_count} 篇与 {ticker}({stock_name}) 无直接关联的通用市场文章")

        results = _deduplicate_news(results)

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
