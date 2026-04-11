from __future__ import annotations

import os
from typing import Any, Callable


def resolve_api_key(api_keys: dict[str, Any] | None, key_name: str) -> Any:
    return (api_keys or {}).get(key_name) or os.getenv(key_name)


def resolve_provider_route_impl(
    *,
    profile,
    variant,
    api_keys: dict[str, Any] | None,
    resolve_api_key_fn: Callable[[dict[str, Any] | None, str], Any],
    provider_route_cls,
):
    resolved_api_keys: dict[str, Any] = {}
    for api_key_name in variant.api_key_names:
        api_key_value = resolve_api_key_fn(api_keys, api_key_name)
        if not api_key_value:
            return None
        resolved_api_keys[api_key_name] = api_key_value

    resolved_api_keys.update(variant.extra_api_keys)
    model_name = os.getenv(variant.model_env_var, variant.default_model_name) if variant.model_env_var else variant.default_model_name

    return provider_route_cls(
        provider_name=profile.name,
        variant_name=variant.variant_name,
        display_name=variant.display_name,
        model_name=model_name,
        api_keys=resolved_api_keys,
        route_order=variant.route_order,
        capabilities=profile.capabilities,
        openai_compatible_transport=variant.openai_compatible_transport,
    )


def get_provider_route_allowlist() -> set[str] | None:
    raw_value = os.getenv("LLM_PROVIDER_ROUTE_ALLOWLIST", "").strip()
    if not raw_value:
        return None

    providers = {item.strip().lower() for item in raw_value.split(",") if item.strip()}
    return providers or None


def collect_provider_routes(
    *,
    registry: dict[str, Any],
    api_keys: dict[str, Any] | None,
    enabled_only_for: str | None,
    provider_allowlist: set[str] | None,
    resolve_provider_route_fn: Callable[[Any, Any, dict[str, Any] | None], Any],
) -> list[Any]:
    routes: list[Any] = []

    for profile in registry.values():
        if provider_allowlist and profile.name.lower() not in provider_allowlist:
            continue
        if enabled_only_for == "parallel" and not profile.enable_parallel_scheduler:
            continue
        if enabled_only_for == "priority" and not profile.enable_priority_routing:
            continue

        for variant in profile.variants:
            route = resolve_provider_route_fn(profile, variant, api_keys)
            if route:
                routes.append(route)

    return sorted(routes, key=lambda route: (route.route_order, route.provider_name, route.variant_name))
