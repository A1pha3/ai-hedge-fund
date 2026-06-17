from __future__ import annotations

import os
from typing import Any

# Truthy string tokens that enable the Coding Plan route. Shared by the
# env-var and api_keys paths so both interpret ``ZHIPU_USE_CODING_PLAN``
# identically. Without this, the api_keys path used naive ``bool(...)``, so a
# non-empty string like ``"false"`` / ``"0"`` was coerced to ``True`` and
# silently enabled the route when a caller meant to disable it (BH-036).
_TRUTHY_FLAG_TOKENS = frozenset({"1", "true", "yes", "on"})


def _parse_truthy_flag(value: Any) -> bool:
    """Parse a boolean flag from an env string or api_keys value.

    - ``bool``: returned as-is (registry default is ``True``).
    - ``str``: case-insensitive membership in ``_TRUTHY_FLAG_TOKENS``.
    - ``None`` / anything else: ``bool(value)``.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in _TRUTHY_FLAG_TOKENS
    return bool(value)


def resolve_zhipu_route_inputs(api_keys: dict[str, Any] | None) -> tuple[str | None, str | None, bool]:
    if api_keys is None:
        standard_api_key = os.getenv("ZHIPU_API_KEY")
        coding_api_key = os.getenv("ZHIPU_CODE_API_KEY")
        prefer_coding_plan = _parse_truthy_flag(os.getenv("ZHIPU_USE_CODING_PLAN", ""))
    else:
        standard_api_key = api_keys.get("ZHIPU_API_KEY")
        coding_api_key = api_keys.get("ZHIPU_CODE_API_KEY")
        prefer_coding_plan = _parse_truthy_flag(api_keys.get("ZHIPU_USE_CODING_PLAN"))

    return standard_api_key, coding_api_key, prefer_coding_plan


def should_route_zhipu_to_coding_plan(coding_api_key: str | None, prefer_coding_plan: bool) -> bool:
    return bool(coding_api_key) or prefer_coding_plan
