"""
AKShare 数据提供商

异步化的 AKShare 数据源实现
"""

import asyncio
import os
from typing import Dict, Any, List
from datetime import datetime
import pandas as pd

from src.data.base_provider import (
    BaseDataProvider,
    DataResponse,
    RateLimitError,
    APIError,
)
from src.data.models import Price, FinancialMetrics, CompanyNews


class AKShareProvider(BaseDataProvider):
    """
    AKShare 数据提供商
    
    使用 AKShare 库获取 A 股数据。
    由于 AKShare 是同步库，使用线程池包装为异步接口。
    
    Attributes:
        _akshare_available: AKShare 是否可用
        _ak: AKShare 模块实例
    """

    def __init__(self, priority: int = 10):
        """
        初始化 AKShare 提供商
        
        Args:
            priority: 优先级（默认 10，较高优先级）
        """
        super().__init__("akshare", priority)
        self._akshare_available = False
        self._ak = None
        self._loop = asyncio.get_event_loop()
        self._init_akshare()

    def _init_akshare(self):
        """初始化 AKShare 模块"""
        try:
            import akshare as ak
            self._ak = ak
            self._akshare_available = True
            self.health_status = "healthy"
        except ImportError:
            self._akshare_available = False
            self.health_status = "unhealthy"

    def _is_available(self) -> bool:
        """检查 AKShare 是否可用"""
        if not self._akshare_available or self._ak is None:
            raise APIError(
                "AKShare 模块不可用。请安装：pip install akshare"
            )
        return True

    def _to_ashare_symbol(self, ticker: str) -> str:
        """
        转换为 A 股代码格式
        
        Args:
            ticker: 股票代码（如 600519, sh600519）
        
        Returns:
            纯数字代码（如 600519）
        """
        ticker = ticker.strip().lower()
        if ticker.startswith(('sh', 'sz', 'bj')):
            return ticker[2:]
        return ticker

    def _get_exchange(self, ticker: str) -> str:
        """
        根据代码判断交易所
        
        Args:
            ticker: 股票代码
        
        Returns:
            交易所代码（sh/sz/bj）
        """
        ticker = ticker.strip().lower()
        
        if ticker.startswith(('sh', 'sz', 'bj')):
            return ticker[:2]
        
        # 根据代码规则判断
        if ticker.startswith(('6', '68', '51', '56', '58', '60')):
            return 'sh'
        elif ticker.startswith(('0', '3', '15', '16', '18', '20')):
            return 'sz'
        elif ticker.startswith(('4', '8', '43', '83', '87')):
            return 'bj'
        
        return 'sz'  # 默认深交所

    async def _run_sync(self, func, *args, **kwargs):
        """
        在线程池中运行同步函数
        
        Args:
            func: 同步函数
            *args: 位置参数
            **kwargs: 关键字参数
        
        Returns:
            函数执行结果
        """
        return await self._loop.run_in_executor(
            None, func, *args, **kwargs
        )

    async def get_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str
    ) -> DataResponse:
        """
        获取价格数据
        
        Args:
            ticker: 股票代码
            start_date: 开始日期（YYYY-MM-DD）
            end_date: 结束日期（YYYY-MM-DD）
        
        Returns:
            DataResponse 包含 Price 对象列表
        """
        start_time = datetime.now()
        
        try:
            self._is_available()
            
            symbol = self._to_ashare_symbol(ticker)
            start_fmt = start_date.replace("-", "")
            end_fmt = end_date.replace("-", "")
            
            # 在线程池中执行同步 AKShare 调用
            df = await self._run_sync(
                self._ak.stock_zh_a_hist,
                symbol=symbol,
                period="daily",
                start_date=start_fmt,
                end_date=end_fmt,
                adjust="qfq"
            )
            
            if df.empty:
                return DataResponse(
                    data=[],
                    source=self.name,
                    error="返回空数据"
                )
            
            # 转换为 Price 对象列表
            prices = []
            for _, row in df.iterrows():
                price = Price(
                    time=str(row["日期"]),
                    open=float(row["开盘"]),
                    high=float(row["最高"]),
                    low=float(row["最低"]),
                    close=float(row["收盘"]),
                    volume=int(row["成交量"])
                )
                prices.append(price)
            
            latency = (datetime.now() - start_time).total_seconds() * 1000
            
            return DataResponse(
                data=prices,
                source=self.name,
                latency_ms=latency
            )
            
        except Exception as e:
            return DataResponse(
                data=[],
                source=self.name,
                error=str(e)
            )

    async def get_financial_metrics(
        self,
        ticker: str,
        end_date: str
    ) -> DataResponse:
        """
        获取财务指标
        
        Args:
            ticker: 股票代码
            end_date: 截止日期（YYYY-MM-DD）
        
        Returns:
            DataResponse 包含 FinancialMetrics 对象列表
        """
        start_time = datetime.now()
        
        try:
            self._is_available()
            
            symbol = self._to_ashare_symbol(ticker)
            
            # 获取主要财务指标
            df = await self._run_sync(
                self._ak.stock_financial_analysis_indicator,
                symbol=symbol
            )
            
            if df.empty:
                return DataResponse(
                    data=[],
                    source=self.name,
                    error="返回空数据"
                )
            
            # 转换为 FinancialMetrics 对象
            metrics = []
            for _, row in df.head(10).iterrows():
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
            
            latency = (datetime.now() - start_time).total_seconds() * 1000
            
            return DataResponse(
                data=metrics,
                source=self.name,
                latency_ms=latency
            )
            
        except Exception as e:
            return DataResponse(
                data=[],
                source=self.name,
                error=str(e)
            )

    async def get_company_news(
        self,
        ticker: str,
        start_date: str,
        end_date: str
    ) -> DataResponse:
        """
        获取公司新闻
        
        Args:
            ticker: 股票代码
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            DataResponse 包含 CompanyNews 对象列表
        """
        start_time = datetime.now()
        
        try:
            self._is_available()
            
            symbol = self._to_ashare_symbol(ticker)
            
            # 获取个股新闻
            df = await self._run_sync(
                self._ak.stock_news_em,
                symbol=symbol
            )
            
            if df.empty:
                return DataResponse(
                    data=[],
                    source=self.name
                )
            
            # 过滤日期范围
            df['datetime'] = pd.to_datetime(df['发布时间'])
            start_dt = pd.to_datetime(start_date)
            end_dt = pd.to_datetime(end_date)
            df = df[(df['datetime'] >= start_dt) & (df['datetime'] <= end_dt)]
            
            # 转换为 CompanyNews 对象
            news_list = []
            for _, row in df.head(100).iterrows():
                news = CompanyNews(
                    ticker=ticker,
                    title=str(row.get("标题", "")),
                    author=str(row.get("作者", "")),
                    source=str(row.get("来源", "东方财富")),
                    date=str(row.get("发布时间", "")),
                    url=str(row.get("链接", "")),
                    sentiment=None
                )
                news_list.append(news)
            
            latency = (datetime.now() - start_time).total_seconds() * 1000
            
            return DataResponse(
                data=news_list,
                source=self.name,
                latency_ms=latency
            )
            
        except Exception as e:
            return DataResponse(
                data=[],
                source=self.name,
                error=str(e)
            )

    async def health_check(self) -> bool:
        """
        健康检查
        
        尝试获取上证指数数据验证可用性
        
        Returns:
            True 表示健康
        """
        try:
            if not self._akshare_available:
                return False
            
            # 尝试获取上证指数数据
            df = await self._run_sync(
                self._ak.stock_zh_a_hist,
                symbol="000001",
                period="daily",
                start_date="20240101",
                end_date="20240102",
                adjust="qfq"
            )
            
            self.health_status = "healthy"
            return True
            
        except Exception:
            self.health_status = "unhealthy"
            return False

    def rate_limit_info(self) -> Dict[str, Any]:
        """
        速率限制信息
        
        AKShare 是本地库，没有严格的速率限制
        
        Returns:
            速率限制信息字典
        """
        return {
            "requests_per_minute": 1000,  # 本地调用，限制较宽松
            "requests_per_day": float('inf'),
            "backoff_strategy": "none",
            "current_remaining": 1000,
            "note": "AKShare is a local library with no strict rate limits"
        }
