"""
模拟数据提供商

用于测试和演示的数据源
"""

import random
from typing import Dict, Any, List
from datetime import datetime, timedelta

from src.data.base_provider import BaseDataProvider, DataResponse
from src.data.models import Price, FinancialMetrics, CompanyNews


class MockProvider(BaseDataProvider):
    """
    模拟数据提供商
    
    生成模拟的股票数据，用于：
    - 测试数据架构
    - 演示功能
    - 作为最终降级方案
    """

    def __init__(self, priority: int = 100):
        """
        初始化模拟提供商
        
        Args:
            priority: 优先级（默认 100，最低优先级）
        """
        super().__init__("mock", priority)
        self.health_status = "healthy"

    async def get_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str
    ) -> DataResponse:
        """
        获取模拟价格数据
        
        Args:
            ticker: 股票代码
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            DataResponse 包含模拟价格数据
        """
        start_time = datetime.now()
        
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
            
            prices = []
            current = start
            base_price = 100.0
            
            while current <= end:
                if current.weekday() < 5:  # 只生成工作日数据
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
        获取模拟财务指标
        
        Args:
            ticker: 股票代码
            end_date: 截止日期
        
        Returns:
            DataResponse 包含模拟财务指标
        """
        start_time = datetime.now()
        
        try:
            end = datetime.strptime(end_date, "%Y-%m-%d")
            
            metrics = []
            for i in range(10):
                quarter = (end.month - 1) // 3
                year = end.year
                
                # 生成模拟的财务指标
                metric = FinancialMetrics(
                    ticker=ticker,
                    report_period=f"{year}Q{quarter + 1}",
                    period="ttm",
                    currency="CNY",
                    market_cap=random.uniform(100000000000, 1000000000000),
                    enterprise_value=random.uniform(100000000000, 1000000000000),
                    price_to_earnings_ratio=random.uniform(10.0, 30.0),
                    price_to_book_ratio=random.uniform(1.0, 5.0),
                    price_to_sales_ratio=random.uniform(1.0, 10.0),
                    enterprise_value_to_ebitda_ratio=random.uniform(5.0, 20.0),
                    enterprise_value_to_revenue_ratio=random.uniform(1.0, 5.0),
                    free_cash_flow_yield=random.uniform(0.02, 0.08),
                    peg_ratio=random.uniform(0.5, 2.0),
                    gross_margin=random.uniform(0.3, 0.7),
                    operating_margin=random.uniform(0.1, 0.3),
                    net_margin=random.uniform(0.05, 0.2),
                    return_on_equity=random.uniform(0.1, 0.25),
                    return_on_assets=random.uniform(0.05, 0.15),
                    return_on_invested_capital=random.uniform(0.08, 0.2),
                    asset_turnover=random.uniform(0.5, 1.5),
                    inventory_turnover=random.uniform(2.0, 10.0),
                    receivables_turnover=random.uniform(4.0, 12.0),
                    days_sales_outstanding=random.uniform(30.0, 90.0),
                    operating_cycle=random.uniform(60.0, 180.0),
                    working_capital_turnover=random.uniform(1.0, 5.0),
                    current_ratio=random.uniform(1.0, 3.0),
                    quick_ratio=random.uniform(0.8, 2.5),
                    cash_ratio=random.uniform(0.2, 1.0),
                    operating_cash_flow_ratio=random.uniform(0.1, 0.5),
                    debt_to_equity=random.uniform(0.3, 0.8),
                    debt_to_assets=random.uniform(0.2, 0.6),
                    interest_coverage=random.uniform(3.0, 15.0),
                    revenue_growth=random.uniform(-0.1, 0.3),
                    earnings_growth=random.uniform(-0.15, 0.4),
                    book_value_growth=random.uniform(0.05, 0.2),
                    earnings_per_share_growth=random.uniform(-0.1, 0.3),
                    free_cash_flow_growth=random.uniform(-0.2, 0.5),
                    operating_income_growth=random.uniform(-0.1, 0.25),
                    ebitda_growth=random.uniform(-0.05, 0.3),
                    payout_ratio=random.uniform(0.2, 0.6),
                    earnings_per_share=random.uniform(1.0, 10.0),
                    book_value_per_share=random.uniform(10.0, 50.0),
                    free_cash_flow_per_share=random.uniform(2.0, 15.0),
                )
                metrics.append(metric)
                
                # 上一个季度（使用 timedelta 避免日期越界）
                end = end - timedelta(days=90)
            
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
        获取模拟公司新闻
        
        Args:
            ticker: 股票代码
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            DataResponse 包含模拟新闻
        """
        start_time = datetime.now()
        
        news_templates = [
            "{company}发布季度财报，营收同比增长{percent}%",
            "{company}宣布新的投资计划，预计投资{amount}亿元",
            "{company}与{partner}达成战略合作协议",
            "{company}股价今日上涨{percent}%，市场表现强劲",
            "{company}获得{amount}亿元融资，估值创新高",
            "{company}推出新产品，预计带来{percent}%增长",
            "分析师上调{company}目标价至{amount}元",
            "{company}宣布分红方案，每10股派{amount}元",
        ]
        
        companies = {
            "600519": "贵州茅台",
            "000001": "平安银行",
            "000858": "五粮液",
            "002415": "海康威视",
        }
        
        company_name = companies.get(ticker, f"公司{ticker}")
        
        news_list = []
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        current = start
        
        while current <= end:
            if random.random() > 0.7:  # 30% 概率生成新闻
                template = random.choice(news_templates)
                news = CompanyNews(
                    ticker=ticker,
                    title=template.format(
                        company=company_name,
                        percent=round(random.uniform(5, 30), 1),
                        amount=round(random.uniform(1, 100), 1),
                        partner=f"合作伙伴{random.randint(1, 10)}"
                    ),
                    author=f"记者{random.randint(1, 20)}",
                    source=random.choice(["财经网", "证券时报", "上海证券报", "每日经济新闻"]),
                    date=current.strftime("%Y-%m-%d"),
                    url=f"https://example.com/news/{ticker}/{current.strftime('%Y%m%d')}",
                    sentiment=random.choice(["positive", "neutral", "negative", None])
                )
                news_list.append(news)
            
            current += timedelta(days=1)
        
        latency = (datetime.now() - start_time).total_seconds() * 1000
        
        return DataResponse(
            data=news_list,
            source=self.name,
            latency_ms=latency
        )

    async def health_check(self) -> bool:
        """
        健康检查
        
        模拟提供商永远健康
        
        Returns:
            True
        """
        return True

    def rate_limit_info(self) -> Dict[str, Any]:
        """
        速率限制信息
        
        模拟提供商没有速率限制
        
        Returns:
            速率限制信息字典
        """
        return {
            "requests_per_minute": float('inf'),
            "requests_per_day": float('inf'),
            "backoff_strategy": "none",
            "current_remaining": float('inf'),
            "note": "Mock provider has no rate limits"
        }
