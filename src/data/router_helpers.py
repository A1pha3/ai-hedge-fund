from __future__ import annotations

import time
from typing import Any
from collections.abc import Awaitable, Callable

from src.data.base_provider import DataResponse
from src.data.health import get_health_monitor


def serialize_cache_records(records: list[Any]) -> list[dict]:
    serialized: list[dict] = []
    for record in records:
        if hasattr(record, "model_dump"):
            serialized.append(record.model_dump())
        elif isinstance(record, dict):
            serialized.append(record)
        else:
            serialized.append(record.__dict__)
    return serialized


async def fetch_from_providers(
    providers: list[Any],
    *,
    request_label: str,
    logger,
    fetcher: Callable[[Any], Awaitable[DataResponse]],
) -> tuple[DataResponse | None, str | None]:
    """依次尝试每个 provider，同时记录健康状态到全局 HealthMonitor。

    对每个 provider：
      1. 记录请求开始时间
      2. 调用 fetcher
      3. 根据结果（异常 / error 字段 / 空数据）判断成功或失败
      4. 将结果记录到 HealthMonitor
    """
    monitor = get_health_monitor()
    last_error: str | None = None

    for provider in providers:
        start = time.monotonic()
        try:
            logger.info(f"Trying provider {provider.name} for {request_label}")
            response = await fetcher(provider)
            latency_ms = (time.monotonic() - start) * 1000

            if response.error:
                logger.warning(f"Provider {provider.name} returned error: {response.error}")
                last_error = response.error
                monitor.record_failure(provider.name, latency_ms, error=response.error)
                continue

            if response.data:
                monitor.record_success(provider.name, latency_ms)
                return response, None

            # R20.11 BETA: 空数据但无 error —— 视为 partial failure (provider 正常
            # 返回但无数据), 记 failure 但不抛异常, 让 router 继续试下一个 provider。
            # 旧实现 (R20.10 之前) 错误地把空响应记为 success, 污染了 HealthMonitor
            # 统计: provider 一直返回空数据时降级阈值永远不触发, 自动降级失效。
            monitor.record_failure(provider.name, latency_ms, error="empty response")
            last_error = "empty response"
            continue

        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000
            logger.warning(f"Provider {provider.name} failed: {exc}")
            last_error = str(exc)
            monitor.record_failure(provider.name, latency_ms, error=last_error)

    return None, last_error


def build_router_failure_response(last_error: str | None) -> DataResponse:
    return DataResponse(data=[], source="router", error=f"All providers failed. Last error: {last_error}")
