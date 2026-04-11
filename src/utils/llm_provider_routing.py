"""Provider routing and cooldown helpers for LLM execution."""

from __future__ import annotations

import os
import threading
import time

from src.llm.models import (
    ProviderRoute,
    get_provider_concurrency_limit_env_var,
    get_provider_profile,
    get_provider_routes,
)


DEFAULT_ZHIPU_FALLBACK_MODEL = "glm-4.7"
DEFAULT_ZHIPU_CODING_PLAN_FALLBACK_MODEL = "glm-4.7"
DEFAULT_MINIMAX_FALLBACK_MODEL = "MiniMax-M2.5"


_PROVIDER_RATE_LIMIT_LOCK = threading.Lock()
_PROVIDER_RATE_LIMIT_UNTIL: dict[str, float] = {}


def _describe_provider_route(route: ProviderRoute) -> str:
    """Returns a human-readable provider route label for status updates."""
    return f"{route.display_name}:{route.model_name}"


def _get_transport_family(provider_name: str, route_id: str | None, api_keys: dict | None) -> str:
    """Returns the transport family label used by metrics aggregation."""
    if route_id:
        route = next((item for item in get_provider_routes(api_keys) if item.route_id == route_id), None)
        if route:
            return route.transport_family

    profile = get_provider_profile(provider_name)
    if profile and profile.capabilities.openai_compatible:
        return "openai-compatible"
    return "native"


def _get_env_int(name: str, default: int) -> int:
    """Returns a positive integer from the environment or the provided default."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        parsed = int(raw_value)
    except ValueError:
        return default

    return parsed if parsed > 0 else default


def _get_parallel_provider_allowlist() -> set[str] | None:
    """Returns an optional allowlist for providers participating in parallel waves."""
    raw_value = os.getenv("LLM_PARALLEL_PROVIDER_ALLOWLIST", "").strip()
    if not raw_value:
        return None
    providers = {item.strip() for item in raw_value.split(",") if item.strip()}
    return providers or None


def _get_allowlist_summary(env_var_name: str) -> list[str] | None:
    """Returns a normalized allowlist summary for execution-plan provenance."""
    raw_value = os.getenv(env_var_name, "").strip()
    if not raw_value:
        return None
    values = [item.strip() for item in raw_value.split(",") if item.strip()]
    return values or None


def _filter_parallel_routes(routes: list[ProviderRoute]) -> list[ProviderRoute]:
    """Applies optional provider allowlist filtering to parallel-routing candidates."""
    allowlist = _get_parallel_provider_allowlist()
    if not allowlist:
        return routes
    return [route for route in routes if route.provider_name in allowlist]


def _get_available_provider_keys(api_keys: dict | None) -> dict[str, list[ProviderRoute]]:
    """Returns the available parallel-routing provider routes grouped by provider."""
    grouped_routes: dict[str, list[ProviderRoute]] = {}
    for route in _filter_parallel_routes(get_provider_routes(api_keys, enabled_only_for="parallel")):
        grouped_routes.setdefault(route.provider_name, []).append(route)
    return grouped_routes


def _build_parallel_fallback_chain(
    primary_provider: str,
    api_keys: dict | None,
    current_route_id: str | None = None,
) -> list[dict[str, object]]:
    """Builds parallel fallback order from the provider registry."""
    available_routes = _filter_parallel_routes(get_provider_routes(api_keys, enabled_only_for="parallel"))
    if not available_routes:
        return []

    current_route = next((route for route in available_routes if route.route_id == current_route_id), None)
    if not current_route:
        current_route = next((route for route in available_routes if route.provider_name == str(primary_provider)), None)
    if not current_route:
        return []

    chain: list[dict[str, object]] = []
    for route in available_routes:
        if route.route_id == current_route.route_id:
            continue
        chain.append(route.to_execution_config(status_message=f"{current_route.display_name} limited, switching to {_describe_provider_route(route)}"))
    return chain


def _build_provider_slot_sequence(provider_limits: dict[str, int], base_model_provider: str) -> list[str]:
    """Builds a weighted provider slot sequence that respects per-provider soft caps."""
    active_limits = {provider: limit for provider, limit in provider_limits.items() if limit > 0}
    if not active_limits:
        return []

    preferred_provider = os.getenv("LLM_PRIMARY_PROVIDER")
    ordered_providers = sorted(
        active_limits,
        key=lambda provider: (
            0 if preferred_provider == provider else 1,
            -active_limits[provider],
            0 if provider == str(base_model_provider) else 1,
            provider,
        ),
    )

    remaining = dict(active_limits)
    provider_slots: list[str] = []
    while any(limit > 0 for limit in remaining.values()):
        for provider in ordered_providers:
            if remaining[provider] <= 0:
                continue
            provider_slots.append(provider)
            remaining[provider] -= 1

    return provider_slots


def _get_provider_lane_limits(
    per_provider_limit: int,
    active_providers: list[str],
    base_model_provider: str,
) -> dict[str, int]:
    """Returns per-provider soft caps for one execution wave."""
    limits: dict[str, int] = {}
    for provider_name in active_providers:
        limit_env_var = get_provider_concurrency_limit_env_var(provider_name)
        limits[provider_name] = _get_env_int(limit_env_var, per_provider_limit)

    if sum(limits.values()) <= 0:
        limits[str(base_model_provider)] = per_provider_limit
    return limits


def _build_execution_plan_provenance(
    *,
    planning_mode: str,
    base_model_name: str,
    base_model_provider: str,
    per_provider_limit: int,
    effective_concurrency_limit: int,
    parallel_provider_count: int,
    provider_routes: dict[str, list[ProviderRoute]],
    provider_lane_limits: dict[str, int],
    provider_slot_sequence: list[str],
    primary_provider_name: str,
    single_provider_reason: str | None = None,
) -> dict[str, object]:
    """Builds a human-readable execution-plan summary for logging and reports."""
    return {
        "planning_mode": planning_mode,
        "base_model_name": str(base_model_name),
        "base_model_provider": str(base_model_provider),
        "per_provider_limit": int(per_provider_limit),
        "effective_concurrency_limit": int(effective_concurrency_limit),
        "parallel_provider_count": int(parallel_provider_count),
        "primary_provider_name": str(primary_provider_name),
        "active_provider_names": list(provider_routes.keys()),
        "provider_lane_limits": {provider: int(limit) for provider, limit in provider_lane_limits.items()},
        "provider_slot_sequence": list(provider_slot_sequence),
        "provider_routes": {
            provider: [
                {
                    "route_id": route.route_id,
                    "display_name": route.display_name,
                    "model_name": route.model_name,
                    "transport_family": route.transport_family,
                }
                for route in routes
            ]
            for provider, routes in provider_routes.items()
        },
        "llm_provider_route_allowlist": _get_allowlist_summary("LLM_PROVIDER_ROUTE_ALLOWLIST"),
        "llm_parallel_provider_allowlist": _get_allowlist_summary("LLM_PARALLEL_PROVIDER_ALLOWLIST"),
        "llm_primary_provider": os.getenv("LLM_PRIMARY_PROVIDER") or None,
        "single_provider_reason": single_provider_reason,
    }


def build_parallel_provider_execution_plan(
    agent_names: list[str],
    base_model_name: str,
    base_model_provider: str,
    api_keys: dict | None,
    per_provider_limit: int,
) -> dict[str, object]:
    """Builds provider-balanced agent overrides for any registered parallel providers."""
    provider_name = str(base_model_provider)
    provider_routes = _get_available_provider_keys(api_keys)
    active_provider_names = list(provider_routes.keys())

    if len(active_provider_names) < 2:
        single_provider_name = active_provider_names[0] if active_provider_names else provider_name
        single_provider_limits = _get_provider_lane_limits(per_provider_limit, [single_provider_name], single_provider_name)
        effective_concurrency_limit = single_provider_limits.get(single_provider_name, per_provider_limit)
        return {
            "effective_concurrency_limit": effective_concurrency_limit,
            "agent_llm_overrides": {},
            "parallel_provider_count": 1,
            "execution_provenance": _build_execution_plan_provenance(
                planning_mode="single-provider",
                base_model_name=base_model_name,
                base_model_provider=base_model_provider,
                per_provider_limit=per_provider_limit,
                effective_concurrency_limit=effective_concurrency_limit,
                parallel_provider_count=1,
                provider_routes=provider_routes,
                provider_lane_limits=single_provider_limits,
                provider_slot_sequence=[single_provider_name] * max(1, effective_concurrency_limit),
                primary_provider_name=single_provider_name,
                single_provider_reason="fewer than two active providers after route filtering",
            ),
        }

    preferred_provider = os.getenv("LLM_PRIMARY_PROVIDER")
    primary_provider_name = provider_name if provider_name in provider_routes else preferred_provider if preferred_provider in provider_routes else active_provider_names[0]

    provider_configs: dict[str, dict[str, object]] = {}
    primary_route = provider_routes[primary_provider_name][0]
    primary_model_name = base_model_name if primary_provider_name == provider_name else primary_route.model_name
    provider_configs[primary_provider_name] = primary_route.to_execution_config(
        status_message=f"Retrying with {primary_provider_name}:{primary_model_name}",
        model_name=primary_model_name,
    )

    for secondary_provider_name in active_provider_names:
        if secondary_provider_name == primary_provider_name:
            continue
        secondary_route = provider_routes[secondary_provider_name][0]
        provider_configs[secondary_provider_name] = secondary_route.to_execution_config(
            status_message=f"Switching to {_describe_provider_route(secondary_route)}"
        )

    provider_limits = _get_provider_lane_limits(per_provider_limit, active_provider_names, primary_provider_name)
    provider_slot_names = _build_provider_slot_sequence(provider_limits, primary_provider_name)
    provider_slots = [provider_configs[slot_name] for slot_name in provider_slot_names]

    overrides: dict[str, dict[str, object]] = {}
    wave_size = len(provider_slots)
    for batch_start in range(0, len(agent_names), wave_size):
        batch = agent_names[batch_start : batch_start + wave_size]
        for index, agent_name in enumerate(batch):
            provider_config = provider_slots[index]
            current_route_id = str(provider_config.get("route_id") or "")
            overrides[agent_name] = {
                "model_name": provider_config["model_name"],
                "model_provider": provider_config["model_provider"],
                "api_keys": dict(provider_config.get("api_keys") or {}),
                "fallback_chain": _build_parallel_fallback_chain(
                    str(provider_config["model_provider"]),
                    api_keys,
                    current_route_id=current_route_id,
                ),
            }

    return {
        "effective_concurrency_limit": wave_size,
        "agent_llm_overrides": overrides,
        "parallel_provider_count": len(active_provider_names),
        "execution_provenance": _build_execution_plan_provenance(
            planning_mode="parallel",
            base_model_name=base_model_name,
            base_model_provider=base_model_provider,
            per_provider_limit=per_provider_limit,
            effective_concurrency_limit=wave_size,
            parallel_provider_count=len(active_provider_names),
            provider_routes=provider_routes,
            provider_lane_limits=provider_limits,
            provider_slot_sequence=provider_slot_names,
            primary_provider_name=primary_provider_name,
        ),
    }


def _build_fallback_chain(primary_provider: str, api_keys: dict | None) -> list[dict[str, object]]:
    """Builds an ordered fallback chain for quota/rate-limit failures."""
    profile = get_provider_profile(str(primary_provider))
    if not profile or not profile.enable_priority_routing:
        return []

    return [
        route.to_execution_config(status_message=f"Switching to {_describe_provider_route(route)}")
        for route in get_provider_routes(api_keys, enabled_only_for="priority")
    ]


def _apply_priority_strategy(
    model_name: str,
    model_provider: str,
    api_keys: dict | None,
) -> tuple[str, str, dict | None, list[dict[str, object]], str | None, str]:
    """Applies the registry-driven priority routing strategy when configured."""
    fallback_chain = _build_fallback_chain(model_provider, api_keys)
    if not fallback_chain:
        return model_name, model_provider, api_keys, [], None, _get_transport_family(model_provider, None, api_keys)

    primary = fallback_chain[0]
    primary_provider = str(primary["model_provider"])
    primary_model_name = model_name if primary_provider == str(model_provider) and model_name else str(primary["model_name"])
    return (
        primary_model_name,
        primary_provider,
        primary.get("api_keys"),
        fallback_chain[1:],
        primary.get("route_id"),
        str(primary.get("transport_family") or _get_transport_family(primary_provider, primary.get("route_id"), api_keys)),
    )


def _provider_rate_limit_key(model_provider: str, route_id: str | None) -> str:
    """Builds a stable key for provider/route-scoped cooldown tracking."""
    return str(route_id or model_provider)


def _register_provider_rate_limit_cooldown(model_provider: str, route_id: str | None, delay_seconds: float) -> None:
    """Registers a process-local cooldown window for a provider route after a 429-style failure."""
    if delay_seconds <= 0:
        return

    cooldown_key = _provider_rate_limit_key(model_provider, route_id)
    cooldown_until = time.monotonic() + delay_seconds
    with _PROVIDER_RATE_LIMIT_LOCK:
        current_until = _PROVIDER_RATE_LIMIT_UNTIL.get(cooldown_key, 0.0)
        _PROVIDER_RATE_LIMIT_UNTIL[cooldown_key] = max(current_until, cooldown_until)


def _wait_for_provider_rate_limit_cooldown(model_provider: str, route_id: str | None) -> float:
    """Sleeps until an active provider cooldown expires and returns the waited seconds."""
    cooldown_key = _provider_rate_limit_key(model_provider, route_id)
    with _PROVIDER_RATE_LIMIT_LOCK:
        cooldown_until = _PROVIDER_RATE_LIMIT_UNTIL.get(cooldown_key, 0.0)

    remaining = cooldown_until - time.monotonic()
    if remaining <= 0:
        return 0.0

    time.sleep(remaining)
    return remaining


def _reset_provider_rate_limit_cooldowns_for_testing() -> None:
    """Clears process-local provider cooldown state for deterministic tests."""
    with _PROVIDER_RATE_LIMIT_LOCK:
        _PROVIDER_RATE_LIMIT_UNTIL.clear()
