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
from typing import List, Optional, Dict, Any
import pandas as pd
from pydantic import BaseModel

from src.data.cache import get_cache
from src.data.models import (
    Price,
    FinancialMetrics,
    CompanyNews,
    InsiderTrade,
    LineItem,
)

# Global cache instance
_cache = get_cache()

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
        if symbol.startswith(('sh', 'sz', 'bj')):
            exchange = symbol[:2]
            code = symbol[2:]
            return cls(symbol=code, exchange=exchange, full_code=symbol)
        
        # 根据代码规则判断交易所
        # 上交所：600/601/603/605/688（主板/科创板）
        # 深交所：000/001/002/003/300（主板/中小板/创业板）
        # 北交所：43/83/87
        if symbol.startswith(('6', '68', '51', '56', '58', '60')):
            exchange = 'sh'
        elif symbol.startswith(('0', '3', '15', '16', '18', '20')):
            exchange = 'sz'
        elif symbol.startswith(('4', '8', '43', '83', '87')):
            exchange = 'bj'
        else:
            # 默认深交所
            exchange = 'sz'
        
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
        
        url = f'https://hq.sinajs.cn/list={symbol}'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://finance.sina.com.cn',
        }
        
        response = session.get(url, headers=headers, timeout=30)
        
        if response.status_code != 200:
            raise AShareDataError(f"新浪 API 返回错误状态码: {response.status_code}")
        
        # 解析新浪返回的数据格式
        # var hq_str_sh600519="贵州茅台,1521.000,1485.300,1466.800,...";
        text = response.text
        if not text or 'hq_str_' not in text:
            raise AShareDataError("新浪 API 返回数据格式错误")
        
        # 提取数据部分
        start = text.find('"') + 1
        end = text.rfind('"')
        if start <= 0 or end <= start:
            raise AShareDataError("无法解析新浪返回的数据")
        
        data_str = text[start:end]
        parts = data_str.split(',')
        
        if len(parts) < 33:
            raise AShareDataError("新浪返回的数据字段不完整")
        
        # 新浪数据字段映射
        result = {
            'name': parts[0],  # 股票名称
            'open': float(parts[1]),  # 今日开盘价
            'close': float(parts[2]),  # 昨日收盘价
            'current': float(parts[3]),  # 当前价格
            'high': float(parts[4]),  # 今日最高价
            'low': float(parts[5]),  # 今日最低价
            'buy': float(parts[6]),  # 竞买价
            'sell': float(parts[7]),  # 竞卖价
            'volume': int(parts[8]),  # 成交量（股）
            'amount': float(parts[9]),  # 成交金额（元）
            'bid1_volume': int(parts[10]),  # 买1量
            'bid1_price': float(parts[11]),  # 买1价
            'bid2_volume': int(parts[12]),
            'bid2_price': float(parts[13]),
            'bid3_volume': int(parts[14]),
            'bid3_price': float(parts[15]),
            'bid4_volume': int(parts[16]),
            'bid4_price': float(parts[17]),
            'bid5_volume': int(parts[18]),
            'bid5_price': float(parts[19]),
            'ask1_volume': int(parts[20]),  # 卖1量
            'ask1_price': float(parts[21]),  # 卖1价
            'ask2_volume': int(parts[22]),
            'ask2_price': float(parts[23]),
            'ask3_volume': int(parts[24]),
            'ask3_price': float(parts[25]),
            'ask4_volume': int(parts[26]),
            'ask4_price': float(parts[27]),
            'ask5_volume': int(parts[28]),
            'ask5_price': float(parts[29]),
            'date': parts[30],  # 日期
            'time': parts[31],  # 时间
        }
        
        return result
    
    except Exception as e:
        if isinstance(e, AShareDataError):
            raise
        raise AShareDataError(f"获取新浪实时行情失败: {e}")


def get_prices(
    ticker: str,
    start_date: str,
    end_date: str,
    period: str = "daily",
    use_mock: bool = False
) -> List[Price]:
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
    
    # 检查缓存
    if cached_data := _cache.get_prices(cache_key):
        return [Price(**price) for price in cached_data]
    
    # 如果指定使用模拟数据，直接返回
    if use_mock:
        return get_mock_prices(ticker, start_date, end_date)
    
    ak_module = _get_akshare()
    if ak_module is None:
        raise AShareDataError(
            "AKShare 模块不可用，无法获取 A 股数据。\n"
            "请检查网络连接，或使用 use_mock=True 参数使用模拟数据。"
        )
    
    try:
        ashare = AShareTicker.from_symbol(ticker)
        start_date_fmt = start_date.replace("-", "")
        end_date_fmt = end_date.replace("-", "")
        
        # 尝试使用 AKShare 获取数据
        df = ak_module.stock_zh_a_hist(
            symbol=ashare.symbol,
            period=period,
            start_date=start_date_fmt,
            end_date=end_date_fmt,
            adjust="qfq"
        )
        
        if df.empty:
            raise AShareDataError(
                f"无法获取股票 {ticker} 的历史数据（AKShare 返回空数据）。\n"
                "请检查网络连接，或使用 use_mock=True 参数使用模拟数据。"
            )
        
        prices = []
        for _, row in df.iterrows():
            price = Price(
                time=row["日期"],
                open=float(row["开盘"]),
                high=float(row["最高"]),
                low=float(row["最低"]),
                close=float(row["收盘"]),
                volume=int(row["成交量"])
            )
            prices.append(price)
        
        # 缓存结果
        _cache.set_prices(cache_key, [p.model_dump() for p in prices])
        
        return prices
    
    except AShareDataError:
        raise
    except Exception as e:
        raise AShareDataError(
            f"获取股票 {ticker} 的历史数据失败: {e}\n"
            "请检查网络连接，或使用 use_mock=True 参数使用模拟数据。"
        )


def get_financial_metrics(
    ticker: str,
    end_date: str,
    limit: int = 10,
    use_mock: bool = False
) -> List[FinancialMetrics]:
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
        raise AShareDataError(
            "AKShare 模块不可用，无法获取 A 股财务数据。\n"
            "请检查网络连接，或使用 use_mock=True 参数使用模拟数据。"
        )
    
    try:
        ashare = AShareTicker.from_symbol(ticker)
        
        # 获取主要财务指标
        df = ak_module.stock_financial_analysis_indicator(symbol=ashare.symbol)
        
        if df.empty:
            raise AShareDataError(
                f"无法获取股票 {ticker} 的财务数据（AKShare 返回空数据）。\n"
                "请检查网络连接，或使用 use_mock=True 参数使用模拟数据。"
            )
        
        # 转换为 FinancialMetrics 对象
        metrics = []
        for _, row in df.head(limit).iterrows():
            metric = FinancialMetrics(
                ticker=ticker,
                report_period=str(row.get("报告期", "")),
                period="ttm",
                currency="CNY",
                revenue=float(row.get("营业收入", 0)) * 10000 if pd.notna(row.get("营业收入")) else None,
                net_income=float(row.get("净利润", 0)) * 10000 if pd.notna(row.get("净利润")) else None,
                price_to_earnings_ratio=float(row.get("市盈率", 0)) if pd.notna(row.get("市盈率")) else None,
                price_to_book_ratio=float(row.get("市净率", 0)) if pd.notna(row.get("市净率")) else None,
                return_on_equity=float(row.get("净资产收益率", 0)) / 100 if pd.notna(row.get("净资产收益率")) else None,
                debt_to_equity=float(row.get("资产负债率", 0)) / 100 if pd.notna(row.get("资产负债率")) else None,
            )
            metrics.append(metric)
        
        # 缓存结果
        _cache.set_financial_metrics(cache_key, [m.model_dump() for m in metrics])
        
        return metrics
    
    except AShareDataError:
        raise
    except Exception as e:
        raise AShareDataError(
            f"获取股票 {ticker} 的财务数据失败: {e}\n"
            "请检查网络连接，或使用 use_mock=True 参数使用模拟数据。"
        )


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
        mask = (
            df["名称"].str.contains(keyword, na=False) |
            df["代码"].str.contains(keyword, na=False)
        )
        filtered = df[mask]
        
        # 转换为列表
        results = []
        for _, row in filtered.head(10).iterrows():
            results.append({
                "symbol": row["代码"],
                "name": row["名称"],
                "price": row["最新价"],
                "change": row["涨跌幅"],
            })
        
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
    if ticker.startswith(('sh', 'sz', 'bj')):
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
            
            price = Price(
                time=current.strftime("%Y-%m-%d"),
                open=round(open_price, 2),
                high=round(high, 2),
                low=round(low, 2),
                close=round(close, 2),
                volume=volume
            )
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
]
