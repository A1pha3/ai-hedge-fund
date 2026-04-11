from __future__ import annotations

import os
from typing import Any


def resolve_zhipu_route_inputs(api_keys: dict[str, Any] | None) -> tuple[str | None, str | None, bool]:
    if api_keys is None:
        standard_api_key = os.getenv("ZHIPU_API_KEY")
        coding_api_key = os.getenv("ZHIPU_CODE_API_KEY")
        prefer_coding_plan = os.getenv("ZHIPU_USE_CODING_PLAN", "").lower() in {"1", "true", "yes"}
    else:
        standard_api_key = api_keys.get("ZHIPU_API_KEY")
        coding_api_key = api_keys.get("ZHIPU_CODE_API_KEY")
        prefer_coding_plan = bool(api_keys.get("ZHIPU_USE_CODING_PLAN"))

    return standard_api_key, coding_api_key, prefer_coding_plan


def should_route_zhipu_to_coding_plan(coding_api_key: str | None, prefer_coding_plan: bool) -> bool:
    return bool(coding_api_key) or prefer_coding_plan
