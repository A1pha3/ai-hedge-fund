"""
A股多数据源模块
支持多种数据源：Tushare、BaoStock、新浪财经、AKShare、模拟数据
"""

import datetime
import os
from typing import List, Optional, Dict, Any

from src.data.models import Price, FinancialMetrics


class DataSourceError(Exception):
    """数据源错误"""
    pass


class BaseDataSource:
    """数据源基类"""
    
    name: str = "base"
    available: bool = False
    
    @classmethod
    def get_prices(
        cls,
        ticker: str,
        start_date: str,
        end_date: str,
        period: str = "daily"
    ) -> List[Price]:
        """获取价格数据"""
        raise NotImplementedError
    
    @classmethod
    def get_financial_metrics(
        cls,
        ticker: str,
        end_date: str,
        limit: int = 10
    ) -> List[FinancialMetrics]:
        """获取财务指标"""
        raise NotImplementedError


class TushareDataSource(BaseDataSource):
    """Tushare 数据源"""
    
    name: str = "tushare"
    available: bool = False
    _pro = None
    
    @classmethod
    def _init_tushare(cls):
        """初始化 Tushare"""
        if cls._pro is not None:
            return True
        
        try:
            import tushare as ts
            token = os.environ.get("TUSHARE_TOKEN")
            if token:
                ts.set_token(token)
                cls._pro = ts.pro_api()
                cls.available = True
                return True
            else:
                print("Warning: TUSHARE_TOKEN 环境变量未设置，Tushare 不可用")
                return False
        except ImportError:
            print("Warning: tushare 模块未安装")
            return False
        except Exception as e:
            print(f"Warning: Tushare 初始化失败: {e}")
            return False
    
    @classmethod
    def get_prices(
        cls,
        ticker: str,
        start_date: str,
        end_date: str,
        period: str = "daily"
    ) -> List[Price]:
        """
        通过 Tushare 获取价格数据
        
        Args:
            ticker: 股票代码
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            period: 周期
        
        Returns:
            List[Price]: 价格数据列表
        """
        if not cls._init_tushare():
            raise DataSourceError("Tushare 不可用，请设置 TUSHARE_TOKEN 环境变量")
        
        try:
            from src.tools.akshare_api import AShareTicker
            ashare = AShareTicker.from_symbol(ticker)
            
            ts_code = f"{ashare.symbol}.SH" if ashare.exchange == "sh" else f"{ashare.symbol}.SZ"
            start_date_fmt = start_date.replace("-", "")
            end_date_fmt = end_date.replace("-", "")
            
            df = cls._pro.daily(
                ts_code=ts_code,
                start_date=start_date_fmt,
                end_date=end_date_fmt
            )
            
            if df.empty:
                raise DataSourceError(f"Tushare 返回空数据: {ticker}")
            
            prices = []
            for _, row in df.iterrows():
                date_str = row["trade_date"]
                date_formatted = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                
                price = Price(
                    time=date_formatted,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=int(row["vol"])
                )
                prices.append(price)
            
            prices.reverse()
            return prices
            
        except Exception as e:
            raise DataSourceError(f"Tushare 获取数据失败: {e}")


class BaoStockDataSource(BaseDataSource):
    """BaoStock 数据源"""
    
    name: str = "baostock"
    available: bool = False
    
    @classmethod
    def _init_baostock(cls):
        """初始化 BaoStock"""
        try:
            import baostock as bs
            cls.available = True
            return True
        except ImportError:
            print("Warning: baostock 模块未安装")
            return False
    
    @classmethod
    def get_prices(
        cls,
        ticker: str,
        start_date: str,
        end_date: str,
        period: str = "daily"
    ) -> List[Price]:
        """
        通过 BaoStock 获取价格数据
        
        Args:
            ticker: 股票代码
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            period: 周期
        
        Returns:
            List[Price]: 价格数据列表
        """
        if not cls._init_baostock():
            raise DataSourceError("BaoStock 不可用，请安装 baostock")
        
        try:
            import baostock as bs
            from src.tools.akshare_api import AShareTicker
            
            ashare = AShareTicker.from_symbol(ticker)
            bs_code = f"sh.{ashare.symbol}" if ashare.exchange == "sh" else f"sz.{ashare.symbol}"
            
            lg = bs.login()
            if lg.error_code != '0':
                raise DataSourceError(f"BaoStock 登录失败: {lg.error_msg}")
            
            try:
                rs = bs.query_history_k_data_plus(
                    bs_code,
                    "date,open,high,low,close,volume",
                    start_date=start_date,
                    end_date=end_date,
                    frequency="d",
                    adjustflag="3"
                )
                
                if rs.error_code != '0':
                    raise DataSourceError(f"BaoStock 查询失败: {rs.error_msg}")
                
                prices = []
                while (rs.error_code == '0') & rs.next():
                    row = rs.get_row_data()
                    if row[1] == '':
                        continue
                    
                    price = Price(
                        time=row[0],
                        open=float(row[1]),
                        high=float(row[2]),
                        low=float(row[3]),
                        close=float(row[4]),
                        volume=int(float(row[5]))
                    )
                    prices.append(price)
                
                return prices
                
            finally:
                bs.logout()
            
        except DataSourceError:
            raise
        except Exception as e:
            raise DataSourceError(f"BaoStock 获取数据失败: {e}")


class SinaDataSource(BaseDataSource):
    """新浪财经数据源（增强版）"""
    
    name: str = "sina"
    available: bool = True
    
    @classmethod
    def get_prices(
        cls,
        ticker: str,
        start_date: str,
        end_date: str,
        period: str = "daily"
    ) -> List[Price]:
        """
        通过新浪财经获取历史数据（使用模拟数据，因为真实接口暂时不可用）
        
        Args:
            ticker: 股票代码
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            period: 周期
        
        Returns:
            List[Price]: 价格数据列表
        """
        try:
            from src.tools.akshare_api import get_sina_historical_data
            return get_sina_historical_data(ticker, start_date, end_date, period)
        except Exception as e:
            raise DataSourceError(f"新浪财经获取数据失败: {e}")


class MockDataSource(BaseDataSource):
    """模拟数据源"""
    
    name: str = "mock"
    available: bool = True
    
    @classmethod
    def get_prices(
        cls,
        ticker: str,
        start_date: str,
        end_date: str,
        period: str = "daily"
    ) -> List[Price]:
        """
        获取模拟价格数据
        
        Args:
            ticker: 股票代码
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            period: 周期
        
        Returns:
            List[Price]: 模拟价格数据列表
        """
        from src.tools.akshare_api import get_mock_prices
        return get_mock_prices(ticker, start_date, end_date)


# 数据源列表（按优先级排序）
DATA_SOURCES = [
    TushareDataSource,
    BaoStockDataSource,
    SinaDataSource,
    MockDataSource,
]


def get_prices_multi_source(
    ticker: str,
    start_date: str,
    end_date: str,
    period: str = "daily",
    source_preference: Optional[List[str]] = None
) -> List[Price]:
    """
    多数据源获取价格数据（自动容错）
    
    Args:
        ticker: 股票代码
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
        period: 周期
        source_preference: 数据源优先级列表
    
    Returns:
        List[Price]: 价格数据列表
    """
    sources = DATA_SOURCES
    
    if source_preference:
        source_map = {s.name: s for s in DATA_SOURCES}
        sources = [source_map[name] for name in source_preference if name in source_map]
    
    last_error = None
    
    for source in sources:
        try:
            print(f"尝试使用数据源: {source.name}")
            prices = source.get_prices(ticker, start_date, end_date, period)
            print(f"✓ 数据源 {source.name} 获取成功，共 {len(prices)} 条数据")
            return prices
        except Exception as e:
            last_error = e
            print(f"✗ 数据源 {source.name} 获取失败: {e}")
            continue
    
    raise DataSourceError(f"所有数据源都失败，最后错误: {last_error}")
