"""
数据源抽象基类模块

遵循文档架构设计，提供统一的数据源接口
"""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import aiohttp


class DataType(Enum):
    """
    数据类型枚举

    定义系统支持的所有数据类型
    """

    PRICE = "price"
    FUNDAMENTAL = "fundamental"
    NEWS = "news"
    INSIDER_TRADE = "insider_trade"
    ECONOMIC = "economic"


@dataclass
class DataRequest:
    """
    数据请求对象

    Attributes:
        ticker: 股票代码
        data_type: 数据类型
        start_date: 开始日期（YYYY-MM-DD）
        end_date: 结束日期（YYYY-MM-DD）
        fields: 需要的字段列表
        kwargs: 其他参数
    """

    ticker: str
    data_type: DataType
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    fields: Optional[List[str]] = None
    kwargs: Optional[Dict[str, Any]] = field(default_factory=dict)


@dataclass
class DataResponse:
    """
    数据响应对象

    包含数据本身和元数据，用于调试和监控

    Attributes:
        data: 实际数据
        source: 数据来源
        timestamp: 获取时间
        cached: 是否来自缓存
        error: 错误信息
        latency_ms: 请求延迟（毫秒）
    """

    data: Any
    source: str
    timestamp: datetime = field(default_factory=datetime.now)
    cached: bool = False
    error: Optional[str] = None
    latency_ms: Optional[float] = None


class DataProviderError(Exception):
    """数据提供商错误基类"""

    pass


class RateLimitError(DataProviderError):
    """速率限制错误"""

    pass


class APIError(DataProviderError):
    """API 调用错误"""

    pass


class ValidationError(DataProviderError):
    """数据验证错误"""

    pass


class BaseDataProvider(ABC):
    """
    数据提供商抽象基类

    所有数据提供商必须继承此类并实现抽象方法。
    遵循依赖倒置原则，上层应用依赖此抽象接口而非具体实现。

    Attributes:
        name: 提供商名称
        priority: 优先级（数值越小优先级越高）
        health_status: 健康状态
        _session: HTTP 会话（懒加载）
    """

    def __init__(self, name: str, priority: int = 100):
        """
        初始化数据提供商

        Args:
            name: 提供商名称
            priority: 优先级（1 = 最高优先级）
        """
        self.name = name
        self.priority = priority
        self.health_status = "unknown"  # unknown/healthy/unhealthy
        self._session: Optional[aiohttp.ClientSession] = None
        self._rate_limit_remaining: Optional[int] = None
        self._rate_limit_reset: Optional[datetime] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """
        获取或创建 HTTP 会话

        使用连接池复用，提高性能

        Returns:
            aiohttp.ClientSession 实例
        """
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30), headers={"Content-Type": "application/json"})
        return self._session

    async def close(self):
        """关闭 HTTP 会话"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.close()

    @abstractmethod
    async def get_prices(self, ticker: str, start_date: str, end_date: str) -> DataResponse:
        """
        获取价格数据

        Args:
            ticker: 股票代码
            start_date: 开始日期（YYYY-MM-DD）
            end_date: 结束日期（YYYY-MM-DD）

        Returns:
            DataResponse 包含价格数据列表

        Raises:
            DataProviderError: 数据获取失败
            RateLimitError: 超过速率限制
        """
        pass

    @abstractmethod
    async def get_financial_metrics(self, ticker: str, end_date: str) -> DataResponse:
        """
        获取财务指标

        Args:
            ticker: 股票代码
            end_date: 截止日期（YYYY-MM-DD）

        Returns:
            DataResponse 包含财务指标字典
        """
        pass

    @abstractmethod
    async def get_company_news(self, ticker: str, start_date: str, end_date: str) -> DataResponse:
        """
        获取公司新闻

        Args:
            ticker: 股票代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            DataResponse 包含新闻列表
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """
        健康检查

        验证数据源是否可用

        Returns:
            True 表示健康，False 表示不健康
        """
        pass

    @abstractmethod
    def rate_limit_info(self) -> Dict[str, Any]:
        """
        速率限制信息

        Returns:
            包含以下字段的字典：
            - requests_per_minute: 每分钟请求限制
            - requests_per_day: 每天请求限制
            - backoff_strategy: 退避策略（exponential/fixed/none）
            - current_remaining: 当前剩余请求数
        """
        pass

    async def execute_with_retry(self, operation, max_retries: int = 3, backoff_strategy: str = "exponential") -> Any:
        """
        带重试机制执行操作

        Args:
            operation: 异步操作函数
            max_retries: 最大重试次数
            backoff_strategy: 退避策略

        Returns:
            操作结果

        Raises:
            DataProviderError: 所有重试失败后抛出
        """
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                return await operation()
            except RateLimitError as e:
                last_error = e
                if attempt < max_retries:
                    if backoff_strategy == "exponential":
                        delay = 2**attempt
                    elif backoff_strategy == "fixed":
                        delay = 60
                    else:
                        delay = 0

                    if delay > 0:
                        await asyncio.sleep(delay)
                continue
            except APIError as e:
                last_error = e
                if attempt < max_retries:
                    continue
                raise

        raise last_error or DataProviderError("Operation failed after retries")

    def _update_rate_limit(self, headers: Dict[str, str]):
        """
        从响应头更新速率限制信息

        Args:
            headers: HTTP 响应头
        """
        if "X-RateLimit-Remaining" in headers:
            self._rate_limit_remaining = int(headers["X-RateLimit-Remaining"])
        if "X-RateLimit-Reset" in headers:
            self._rate_limit_reset = datetime.fromtimestamp(int(headers["X-RateLimit-Reset"]))
