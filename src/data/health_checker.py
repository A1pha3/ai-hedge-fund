import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class HealthCheckResult:
    """健康检查结果"""

    source: str
    timestamp: str
    connectivity: bool
    response_time: float
    data_quality: dict[str, Any]
    errors: list[str]

    @property
    def is_healthy(self) -> bool:
        """是否健康"""
        return self.connectivity and len(self.errors) == 0


class DataSourceHealthChecker:
    """数据源健康度检查器

    定期评估各数据源的健康状况：
    1. 连接性检查
    2. 响应时间监控
    3. 数据质量评估
    """

    TEST_TICKERS = ["000001", "600000", "300001"]

    def __init__(self, providers: dict[str, Any] | None = None):
        """初始化健康检查器

        Args:
            providers: 数据源提供商标识字典 {name: provider_instance}
        """
        self.providers = providers or {}

    def register_provider(self, name: str, provider: Any) -> None:
        """注册数据源提供商"""
        self.providers[name] = provider

    async def check_source_health(self, source_name: str) -> HealthCheckResult:
        """检查单个数据源健康度

        Args:
            source_name: 数据源名称

        Returns:
            健康检查结果
        """
        provider = self.providers.get(source_name)

        if not provider:
            return HealthCheckResult(
                source=source_name,
                timestamp=datetime.now().isoformat(),
                connectivity=False,
                response_time=0.0,
                data_quality={},
                errors=[f"未知数据源: {source_name}"],
            )

        results: dict[str, Any] = {}
        errors: list[str] = []
        max_response_time = 0.0
        success_count = 0

        for ticker in self.TEST_TICKERS:
            try:
                start = time.time()

                if hasattr(provider, "get_financial_metrics"):
                    if asyncio.iscoroutinefunction(provider.get_financial_metrics):
                        data = await provider.get_financial_metrics(ticker)
                    else:
                        data = provider.get_financial_metrics(ticker)
                else:
                    data = []

                elapsed = time.time() - start
                max_response_time = max(max_response_time, elapsed)

                results[ticker] = {
                    "records": len(data) if data else 0,
                    "response_time": round(elapsed, 3),
                }
                success_count += 1

            except Exception as e:
                errors.append(f"{ticker}: {str(e)}")

        connectivity = success_count > 0

        return HealthCheckResult(
            source=source_name,
            timestamp=datetime.now().isoformat(),
            connectivity=connectivity,
            response_time=round(max_response_time, 3),
            data_quality=results,
            errors=errors,
        )

    async def check_all_sources(self) -> dict[str, HealthCheckResult]:
        """检查所有数据源健康度

        Returns:
            {source_name: HealthCheckResult}
        """
        results = {}

        for source_name in self.providers:
            results[source_name] = await self.check_source_health(source_name)

        return results

    def get_health_summary(self, results: dict[str, HealthCheckResult]) -> dict[str, Any]:
        """获取健康状态摘要

        Args:
            results: 健康检查结果字典

        Returns:
            摘要信息
        """
        total = len(results)
        healthy = sum(1 for r in results.values() if r.is_healthy)

        return {
            "timestamp": datetime.now().isoformat(),
            "total_sources": total,
            "healthy_sources": healthy,
            "unhealthy_sources": total - healthy,
            "health_rate": f"{healthy / total:.2%}" if total > 0 else "N/A",
            "details": {
                name: {
                    "healthy": result.is_healthy,
                    "response_time": result.response_time,
                    "errors": result.errors,
                }
                for name, result in results.items()
            },
        }


async def run_health_check(providers: dict[str, Any]) -> dict[str, Any]:
    """运行健康检查的便捷函数

    Args:
        providers: 数据源提供商标识字典

    Returns:
        健康状态摘要
    """
    checker = DataSourceHealthChecker(providers)
    results = await checker.check_all_sources()
    return checker.get_health_summary(results)
