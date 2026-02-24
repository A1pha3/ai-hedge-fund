"""
数据路由器模块

实现数据源路由、容错切换、缓存管理等功能
"""

import asyncio
import time
from typing import List, Optional, Dict, Any, Type
from datetime import datetime, timedelta
import logging

from src.data.base_provider import (
    BaseDataProvider,
    DataRequest,
    DataResponse,
    DataType,
    DataProviderError,
)
from src.data.cache import get_cache

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DataRouter:
    """
    数据路由器
    
    负责：
    - 根据数据类型和优先级选择合适的数据源
    - 实现容错机制（主数据源失败时自动切换）
    - 管理缓存
    - 记录数据血缘和性能指标
    
    Attributes:
        providers: 注册的提供商列表
        cache: 缓存实例
        health_check_interval: 健康检查间隔（秒）
        _last_health_check: 上次健康检查时间
    """

    def __init__(
        self,
        providers: Optional[List[BaseDataProvider]] = None,
        health_check_interval: int = 300
    ):
        """
        初始化数据路由器
        
        Args:
            providers: 提供商列表
            health_check_interval: 健康检查间隔（秒，默认 5 分钟）
        """
        self.providers = providers or []
        self.cache = get_cache()
        self.health_check_interval = health_check_interval
        self._last_health_check: Optional[datetime] = None
        self._health_cache: Dict[str, bool] = {}
        
        # 按优先级排序
        self._sort_providers()

    def _sort_providers(self):
        """按优先级排序提供商（数值越小优先级越高）"""
        self.providers.sort(key=lambda p: p.priority)

    def register_provider(self, provider: BaseDataProvider):
        """
        注册数据提供商
        
        Args:
            provider: 数据提供商实例
        """
        self.providers.append(provider)
        self._sort_providers()
        logger.info(f"Registered provider: {provider.name} (priority: {provider.priority})")

    def unregister_provider(self, provider_name: str):
        """
        注销数据提供商
        
        Args:
            provider_name: 提供商名称
        """
        self.providers = [p for p in self.providers if p.name != provider_name]
        logger.info(f"Unregistered provider: {provider_name}")

    def _get_cache_key(self, data_type: DataType, ticker: str, **kwargs) -> str:
        """
        生成缓存键
        
        Args:
            data_type: 数据类型
            ticker: 股票代码
            **kwargs: 其他参数
        
        Returns:
            缓存键字符串
        """
        key_parts = [data_type.value, ticker]
        
        # 添加其他参数
        for k, v in sorted(kwargs.items()):
            if v is not None:
                key_parts.append(f"{k}={v}")
        
        return "_".join(key_parts)

    def _get_from_cache(self, cache_key: str, data_type: DataType) -> Optional[DataResponse]:
        """
        从缓存获取数据
        
        Args:
            cache_key: 缓存键
            data_type: 数据类型
        
        Returns:
            DataResponse 或 None
        """
        cached_data = None
        
        if data_type == DataType.PRICE:
            cached_data = self.cache.get_prices(cache_key)
        elif data_type == DataType.FUNDAMENTAL:
            cached_data = self.cache.get_financial_metrics(cache_key)
        elif data_type == DataType.NEWS:
            cached_data = self.cache.get_company_news(cache_key)
        elif data_type == DataType.INSIDER_TRADE:
            cached_data = self.cache.get_insider_trades(cache_key)
        
        if cached_data:
            return DataResponse(
                data=cached_data,
                source="cache",
                cached=True
            )
        
        return None

    def _set_to_cache(self, cache_key: str, data_type: DataType, data: Any):
        """
        设置缓存数据
        
        Args:
            cache_key: 缓存键
            data_type: 数据类型
            data: 数据内容
        """
        try:
            if data_type == DataType.PRICE:
                self.cache.set_prices(cache_key, data)
            elif data_type == DataType.FUNDAMENTAL:
                self.cache.set_financial_metrics(cache_key, data)
            elif data_type == DataType.NEWS:
                self.cache.set_company_news(cache_key, data)
            elif data_type == DataType.INSIDER_TRADE:
                self.cache.set_insider_trades(cache_key, data)
        except Exception as e:
            logger.warning(f"Failed to cache data: {e}")

    async def _check_health(self, force: bool = False):
        """
        检查提供商健康状态
        
        Args:
            force: 是否强制检查
        """
        now = datetime.now()
        
        if not force and self._last_health_check:
            elapsed = (now - self._last_health_check).total_seconds()
            if elapsed < self.health_check_interval:
                return
        
        self._last_health_check = now
        
        for provider in self.providers:
            try:
                is_healthy = await provider.health_check()
                self._health_cache[provider.name] = is_healthy
                
                if is_healthy:
                    logger.debug(f"Provider {provider.name} is healthy")
                else:
                    logger.warning(f"Provider {provider.name} is unhealthy")
                    
            except Exception as e:
                self._health_cache[provider.name] = False
                logger.warning(f"Health check failed for {provider.name}: {e}")

    def _get_healthy_providers(self) -> List[BaseDataProvider]:
        """
        获取健康的提供商列表
        
        Returns:
            健康的提供商列表
        """
        return [
            p for p in self.providers
            if self._health_cache.get(p.name, True)
        ]

    async def get_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        use_cache: bool = True
    ) -> DataResponse:
        """
        获取价格数据（带容错和缓存）
        
        Args:
            ticker: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            use_cache: 是否使用缓存
        
        Returns:
            DataResponse 包含价格数据
        """
        cache_key = self._get_cache_key(
            DataType.PRICE,
            ticker,
            start=start_date,
            end=end_date
        )
        
        # 检查缓存
        if use_cache:
            cached = self._get_from_cache(cache_key, DataType.PRICE)
            if cached:
                logger.debug(f"Cache hit for {cache_key}")
                return cached
        
        # 检查健康状态
        await self._check_health()
        
        # 获取健康的提供商
        providers = self._get_healthy_providers()
        
        if not providers:
            return DataResponse(
                data=[],
                source="router",
                error="No healthy providers available"
            )
        
        # 依次尝试每个提供商
        last_error = None
        
        for provider in providers:
            try:
                logger.info(f"Trying provider {provider.name} for {ticker} prices")
                
                response = await provider.get_prices(ticker, start_date, end_date)
                
                if response.error:
                    logger.warning(f"Provider {provider.name} returned error: {response.error}")
                    last_error = response.error
                    continue
                
                if response.data:
                    # 缓存结果（转换为字典）
                    if use_cache:
                        try:
                            cache_data = []
                            for p in response.data:
                                if hasattr(p, 'model_dump'):
                                    cache_data.append(p.model_dump())
                                elif isinstance(p, dict):
                                    cache_data.append(p)
                                else:
                                    cache_data.append(p.__dict__)
                            self._set_to_cache(cache_key, DataType.PRICE, cache_data)
                        except Exception as e:
                            logger.warning(f"Failed to cache prices: {e}")
                    
                    logger.info(f"Successfully got prices from {provider.name}")
                    return response
                
            except Exception as e:
                logger.warning(f"Provider {provider.name} failed: {e}")
                last_error = str(e)
                continue
        
        # 所有提供商都失败
        return DataResponse(
            data=[],
            source="router",
            error=f"All providers failed. Last error: {last_error}"
        )

    async def get_financial_metrics(
        self,
        ticker: str,
        end_date: str,
        limit: int = 10,
        use_cache: bool = True
    ) -> DataResponse:
        """
        获取财务指标（带容错和缓存）
        
        Args:
            ticker: 股票代码
            end_date: 截止日期
            limit: 返回记录数
            use_cache: 是否使用缓存
        
        Returns:
            DataResponse 包含财务指标
        """
        cache_key = self._get_cache_key(
            DataType.FUNDAMENTAL,
            ticker,
            end=end_date,
            limit=limit
        )
        
        # 检查缓存
        if use_cache:
            cached = self._get_from_cache(cache_key, DataType.FUNDAMENTAL)
            if cached:
                return cached
        
        # 检查健康状态
        await self._check_health()
        
        # 获取健康的提供商
        providers = self._get_healthy_providers()
        
        if not providers:
            return DataResponse(
                data=[],
                source="router",
                error="No healthy providers available"
            )
        
        # 依次尝试每个提供商
        last_error = None
        
        for provider in providers:
            try:
                logger.info(f"Trying provider {provider.name} for {ticker} metrics")
                
                response = await provider.get_financial_metrics(ticker, end_date)
                
                if response.error:
                    last_error = response.error
                    continue
                
                if response.data:
                    # 限制返回数量
                    data = response.data[:limit]
                    
                    # 缓存结果（转换为字典）
                    if use_cache:
                        try:
                            cache_data = []
                            for m in data:
                                if hasattr(m, 'model_dump'):
                                    cache_data.append(m.model_dump())
                                elif isinstance(m, dict):
                                    cache_data.append(m)
                                else:
                                    cache_data.append(m.__dict__)
                            self._set_to_cache(cache_key, DataType.FUNDAMENTAL, cache_data)
                        except Exception as e:
                            logger.warning(f"Failed to cache metrics: {e}")
                    
                    return DataResponse(
                        data=data,
                        source=provider.name,
                        latency_ms=response.latency_ms
                    )
                
            except Exception as e:
                last_error = str(e)
                continue
        
        return DataResponse(
            data=[],
            source="router",
            error=f"All providers failed. Last error: {last_error}"
        )

    async def get_company_news(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        use_cache: bool = True
    ) -> DataResponse:
        """
        获取公司新闻（带容错和缓存）
        
        Args:
            ticker: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            use_cache: 是否使用缓存
        
        Returns:
            DataResponse 包含新闻列表
        """
        cache_key = self._get_cache_key(
            DataType.NEWS,
            ticker,
            start=start_date,
            end=end_date
        )
        
        # 检查缓存
        if use_cache:
            cached = self._get_from_cache(cache_key, DataType.NEWS)
            if cached:
                return cached
        
        # 检查健康状态
        await self._check_health()
        
        # 获取健康的提供商
        providers = self._get_healthy_providers()
        
        if not providers:
            return DataResponse(
                data=[],
                source="router",
                error="No healthy providers available"
            )
        
        # 依次尝试每个提供商
        last_error = None
        
        for provider in providers:
            try:
                response = await provider.get_company_news(ticker, start_date, end_date)
                
                if response.error:
                    last_error = response.error
                    continue
                
                if response.data:
                    # 缓存结果
                    if use_cache:
                        self._set_to_cache(
                            cache_key,
                            DataType.NEWS,
                            [n.model_dump() for n in response.data]
                        )
                    
                    return response
                
            except Exception as e:
                last_error = str(e)
                continue
        
        return DataResponse(
            data=[],
            source="router",
            error=f"All providers failed. Last error: {last_error}"
        )

    async def execute_request(self, request: DataRequest) -> DataResponse:
        """
        执行数据请求
        
        根据请求类型路由到相应方法
        
        Args:
            request: 数据请求对象
        
        Returns:
            DataResponse
        """
        if request.data_type == DataType.PRICE:
            return await self.get_prices(
                request.ticker,
                request.start_date,
                request.end_date
            )
        elif request.data_type == DataType.FUNDAMENTAL:
            return await self.get_financial_metrics(
                request.ticker,
                request.end_date,
                request.kwargs.get("limit", 10)
            )
        elif request.data_type == DataType.NEWS:
            return await self.get_company_news(
                request.ticker,
                request.start_date,
                request.end_date
            )
        else:
            return DataResponse(
                data=None,
                source="router",
                error=f"Unsupported data type: {request.data_type}"
            )

    async def close(self):
        """关闭所有提供商连接"""
        for provider in self.providers:
            try:
                await provider.close()
            except Exception as e:
                logger.warning(f"Error closing provider {provider.name}: {e}")

    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.close()


# 全局路由器实例
_router: Optional[DataRouter] = None


def get_router() -> DataRouter:
    """
    获取全局数据路由器实例
    
    Returns:
        DataRouter 实例
    """
    global _router
    
    if _router is None:
        _router = DataRouter()
        
        # 自动注册可用的提供商
        try:
            from src.data.providers.akshare_provider import AKShareProvider
            _router.register_provider(AKShareProvider())
        except Exception as e:
            logger.warning(f"Failed to register AKShareProvider: {e}")
        
        try:
            from src.data.providers.tushare_provider import TushareProvider
            _router.register_provider(TushareProvider())
        except Exception as e:
            logger.warning(f"Failed to register TushareProvider: {e}")
        
        # 始终注册 Mock 提供商作为最终降级方案
        try:
            from src.data.providers.mock_provider import MockProvider
            _router.register_provider(MockProvider())
            logger.info("Registered MockProvider as fallback")
        except Exception as e:
            logger.warning(f"Failed to register MockProvider: {e}")
    
    return _router


def reset_router():
    """重置全局路由器（用于测试）"""
    global _router
    _router = None
