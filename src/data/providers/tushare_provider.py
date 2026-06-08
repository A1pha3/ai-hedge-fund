"""
Tushare 数据提供商

异步化的 Tushare 数据源实现
"""

import asyncio
import os
from datetime import datetime
from typing import Any

import pandas as pd

from src.data.base_provider import (
    APIError,
    BaseDataProvider,
    DataResponse,
)
from src.data.models import FinancialMetrics, Price
from src.tools.ashare_board_utils import to_tushare_code


class TushareProvider(BaseDataProvider):
    """
    Tushare 数据提供商

    使用 Tushare Pro API 获取 A 股数据。
    需要设置 TUSHARE_TOKEN 环境变量。

    Attributes:
        _pro: Tushare Pro API 实例
        _token: API Token
    """

    def __init__(self, token: str | None = None, priority: int = 5):
        """
        初始化 Tushare 提供商

        Args:
            token: Tushare API Token（默认从环境变量获取）
            priority: 优先级（默认 5，高优先级）
        """
        super().__init__("tushare", priority)
        self._token = token or os.environ.get("TUSHARE_TOKEN")
        self._pro = None
        # R6-BETA-003: avoid asyncio.get_event_loop() which raises RuntimeError
        # on Python 3.12+ when no loop is running. Use lazy lookup instead.
        self._init_tushare()

    def _init_tushare(self):
        """初始化 Tushare"""
        if not self._token:
            self.health_status = "unhealthy"
            return

        try:
            import tushare as ts

            # 直接使用 token 创建 pro_api，避免写入文件
            self._pro = ts.pro_api(token=self._token)
            self.health_status = "healthy"
        except ImportError:
            self.health_status = "unhealthy"
        except Exception:
            self.health_status = "unhealthy"

    def _is_available(self) -> bool:
        """检查 Tushare 是否可用"""
        if not self._token:
            raise APIError("TUSHARE_TOKEN 未设置。请设置环境变量或在初始化时传入 token。")
        if self._pro is None:
            raise APIError("Tushare 初始化失败。请检查 token 是否有效。")
        return True

    def _to_ts_code(self, ticker: str) -> str:
        """
        转换为 Tushare 代码格式

        Args:
            ticker: 股票代码（如 600519, sh600519）

        Returns:
            Tushare 格式代码（如 600519.SH）
        """
        return to_tushare_code(ticker)

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
        return await asyncio.get_running_loop().run_in_executor(None, func, *args, **kwargs)

    async def get_prices(self, ticker: str, start_date: str, end_date: str) -> DataResponse:
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

            ts_code = self._to_ts_code(ticker)
            start_fmt = start_date.replace("-", "")
            end_fmt = end_date.replace("-", "")

            # 在线程池中执行同步 Tushare 调用
            df = await self._run_sync(self._pro.daily, ts_code=ts_code, start_date=start_fmt, end_date=end_fmt)

            if df is None or df.empty:
                return DataResponse(data=[], source=self.name, error="返回空数据")

            # 转换为 Price 对象列表
            prices = []
            for _, row in df.iterrows():
                date_str = str(row["trade_date"])
                date_formatted = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

                price = Price(time=date_formatted, open=float(row["open"]), high=float(row["high"]), low=float(row["low"]), close=float(row["close"]), volume=int(row["vol"]))
                prices.append(price)

            # 按日期正序排列
            prices.reverse()

            latency = (datetime.now() - start_time).total_seconds() * 1000

            return DataResponse(data=prices, source=self.name, latency_ms=latency)

        except Exception as e:
            return DataResponse(data=[], source=self.name, error=str(e))

    async def get_financial_metrics(self, ticker: str, end_date: str) -> DataResponse:
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

            ts_code = self._to_ts_code(ticker)
            end_fmt = end_date.replace("-", "")

            # 获取日线行情数据（包含市值等指标）
            # R6-BETA-002: capture daily_basic result for P/E, P/B, market_cap
            df_basic = await self._run_sync(self._pro.daily_basic, ts_code=ts_code, trade_date=end_fmt)
            basic_row = None
            if df_basic is not None and not df_basic.empty:
                basic_row = df_basic.iloc[0]

            # 获取财务指标数据
            df_fin = await self._run_sync(self._pro.fina_indicator, ts_code=ts_code, end_date=end_fmt, limit=10)

            metrics = []

            if df_fin is not None and not df_fin.empty:
                for _, row in df_fin.iterrows():
                    # R6-BETA-001: price_to_earnings_ratio was mapped to q_sales_yoy
                    # (revenue growth), not pe_ttm. Use daily_basic pe_ttm when available.
                    pe_ratio = None
                    if basic_row is not None and pd.notna(basic_row.get("pe_ttm")):
                        pe_ratio = float(basic_row["pe_ttm"])
                    pb_ratio = None
                    if basic_row is not None and pd.notna(basic_row.get("pb")):
                        pb_ratio = float(basic_row["pb"])
                    market_cap_val = None
                    if basic_row is not None and pd.notna(basic_row.get("total_mv")):
                        market_cap_val = float(basic_row["total_mv"]) * 10000

                    metric_kwargs = {
                        "ticker": ticker,
                        "report_period": str(row.get("end_date", "")),
                        "period": "ttm",
                        "currency": "CNY",
                        "market_cap": market_cap_val,
                        "price_to_earnings_ratio": pe_ratio,
                        "price_to_book_ratio": pb_ratio,
                        "return_on_equity": float(row.get("roe", 0)) / 100 if pd.notna(row.get("roe")) else None,
                        # R20.11 BETA: Tushare fina_indicator 的 debt_to_assets 是 D/A,
                        # 之前错误地直接写入 debt_to_equity (D/E) 字段, 复刻 GAMMA-017 bug。
                        # 改为 D/A → debt_to_assets, D/E 留 None 由 adapter 推导。
                        "debt_to_assets": float(row.get("debt_to_assets", 0)) / 100 if pd.notna(row.get("debt_to_assets")) else None,
                        "debt_to_equity": None,
                        "revenue_growth": float(row.get("q_sales_yoy", 0)) / 100 if pd.notna(row.get("q_sales_yoy")) else None,
                    }
                    # R20.11 BETA: 补全 Pydantic v2 strict 必需字段。原实现只填 9 个,
                    # 缺 30+ 字段会 ValidationError → 走 except → 返回空 data。
                    for _field_name in (
                        "enterprise_value", "price_to_sales_ratio",
                        "enterprise_value_to_ebitda_ratio", "enterprise_value_to_revenue_ratio",
                        "free_cash_flow_yield", "peg_ratio", "gross_margin",
                        "operating_margin", "net_margin", "return_on_assets",
                        "return_on_invested_capital", "asset_turnover",
                        "inventory_turnover", "receivables_turnover",
                        "days_sales_outstanding", "operating_cycle",
                        "working_capital_turnover", "current_ratio", "quick_ratio",
                        "cash_ratio", "operating_cash_flow_ratio", "interest_coverage",
                        "earnings_growth", "book_value_growth",
                        "earnings_per_share_growth", "free_cash_flow_growth",
                        "operating_income_growth", "ebitda_growth", "payout_ratio",
                        "earnings_per_share", "book_value_per_share",
                        "free_cash_flow_per_share",
                    ):
                        metric_kwargs.setdefault(_field_name, None)
                    metric = FinancialMetrics(**metric_kwargs)
                    metrics.append(metric)

            latency = (datetime.now() - start_time).total_seconds() * 1000

            return DataResponse(data=metrics, source=self.name, latency_ms=latency)

        except Exception as e:
            return DataResponse(data=[], source=self.name, error=str(e))

    async def get_company_news(self, ticker: str, start_date: str, end_date: str) -> DataResponse:
        """
        获取公司新闻

        Tushare 的 major_news 接口需要单独权限

        Args:
            ticker: 股票代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            DataResponse 包含新闻列表
        """
        # Tushare 新闻接口需要额外权限
        # 返回空列表，由其他提供商补充
        return DataResponse(data=[], source=self.name, error="Tushare 新闻接口需要额外权限")

    async def health_check(self) -> bool:
        """
        健康检查

        尝试获取股票列表验证 API 可用性

        Returns:
            True 表示健康
        """
        try:
            if not self._token or self._pro is None:
                return False

            # 尝试获取股票列表
            df = await self._run_sync(self._pro.stock_basic, exchange="", list_status="L", limit=5)

            if df is not None and not df.empty:
                self.health_status = "healthy"
                return True

            self.health_status = "unhealthy"
            return False

        except Exception:
            self.health_status = "unhealthy"
            return False

    def rate_limit_info(self) -> dict[str, Any]:
        """
        速率限制信息

        Tushare Pro API 有积分限制

        Returns:
            速率限制信息字典
        """
        return {"requests_per_minute": 500, "requests_per_day": float("inf"), "backoff_strategy": "fixed", "current_remaining": None, "note": "Tushare uses a point-based system. Higher points = higher limits."}  # 根据积分等级不同
