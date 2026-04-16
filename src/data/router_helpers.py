from __future__ import annotations

from typing import Any
from collections.abc import Awaitable, Callable

from src.data.base_provider import DataResponse


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
    last_error: str | None = None
    for provider in providers:
        try:
            logger.info(f"Trying provider {provider.name} for {request_label}")
            response = await fetcher(provider)
            if response.error:
                logger.warning(f"Provider {provider.name} returned error: {response.error}")
                last_error = response.error
                continue
            if response.data:
                return response, None
        except Exception as exc:
            logger.warning(f"Provider {provider.name} failed: {exc}")
            last_error = str(exc)
    return None, last_error


def build_router_failure_response(last_error: str | None) -> DataResponse:
    return DataResponse(data=[], source="router", error=f"All providers failed. Last error: {last_error}")
