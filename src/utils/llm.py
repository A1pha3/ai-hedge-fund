"""Helper functions for LLM"""

import json
import logging
import os
import re
import threading
import time
from time import perf_counter

from pydantic import BaseModel

from src.graph.state import AgentState
from src.llm.defaults import get_default_model_config
from src.llm.models import ProviderRoute, get_model, get_model_info, get_provider_concurrency_limit_env_var, get_provider_primary_route, get_provider_profile, get_provider_routes
from src.monitoring.llm_metrics import record_llm_attempt
from src.utils.llm_call_helpers import handle_llm_failure, resolve_llm_call_context, return_success_result
from src.utils.llm_json_helpers import extract_balanced_json_candidates, extract_json_payload_from_content
from src.utils.progress import progress


logger = logging.getLogger(__name__)


_PROVIDER_RATE_LIMIT_LOCK = threading.Lock()
_PROVIDER_RATE_LIMIT_UNTIL: dict[str, float] = {}


DEFAULT_ZHIPU_FALLBACK_MODEL = "glm-4.7"
DEFAULT_ZHIPU_CODING_PLAN_FALLBACK_MODEL = "glm-4.7"
DEFAULT_MINIMAX_FALLBACK_MODEL = "MiniMax-M2.5"


def _describe_provider_route(route: ProviderRoute) -> str:
    """Returns a human-readable provider route label for status updates."""
    return f"{route.display_name}:{route.model_name}"


def _group_provider_routes(api_keys: dict | None, *, enabled_only_for: str | None = None) -> dict[str, list[ProviderRoute]]:
    """Groups available provider routes by provider name."""
    grouped_routes: dict[str, list[ProviderRoute]] = {}
    for route in get_provider_routes(api_keys, enabled_only_for=enabled_only_for):
        grouped_routes.setdefault(route.provider_name, []).append(route)
    return grouped_routes


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


def _build_llm(model_name: str, model_provider: str, api_keys: dict | None, pydantic_model: type[BaseModel]):
    """Builds an LLM client and applies structured output when supported."""
    model_info = get_model_info(model_name, model_provider)
    llm = get_model(model_name, model_provider, api_keys)

    if not (model_info and not model_info.has_json_mode()):
        llm = llm.with_structured_output(
            pydantic_model,
            method="json_mode",
        )

    return llm, model_info


def _is_rate_limit_error(error: Exception) -> bool:
    """Detects provider quota/rate-limit failures that should trigger fallback."""
    message = str(error).lower()
    return any(
        marker in message
        for marker in [
            "429",
            "rate_limit",
            "rate limit",
            "too many requests",
            "usage limit exceeded",
        ]
    )


def _merge_api_keys(base_api_keys: dict | None, override_api_keys: dict | None) -> dict | None:
    """Creates a merged API key mapping for fallback providers."""
    if not base_api_keys and not override_api_keys:
        return None
    merged = dict(base_api_keys or {})
    merged.update(override_api_keys or {})
    return merged


def _extract_state_api_keys(state: AgentState | None) -> dict | None:
    """Extracts API keys from graph state metadata when available."""
    if not state:
        return None

    request = state.get("metadata", {}).get("request")
    if request and hasattr(request, "api_keys"):
        return request.api_keys
    return None


def _get_agent_llm_override(state: AgentState | None, agent_name: str | None) -> dict | None:
    """Returns an agent-specific LLM override injected into graph metadata."""
    if not state or not agent_name:
        return None

    overrides = state.get("metadata", {}).get("agent_llm_overrides") or {}
    override = overrides.get(agent_name)
    return override if isinstance(override, dict) else None


def _get_llm_observability_context(state: AgentState | None) -> dict[str, str]:
    """Extracts optional observability context injected into graph metadata."""
    if not state:
        return {}

    raw_context = state.get("metadata", {}).get("llm_observability") or {}
    if not isinstance(raw_context, dict):
        return {}

    context: dict[str, str] = {}
    for key in ("trade_date", "pipeline_stage", "model_tier"):
        value = raw_context.get(key)
        if value is not None and str(value).strip():
            context[key] = str(value)
    return context


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


def _build_explicit_provider_config(
    provider_name: str,
    api_keys: dict | None,
    status_message: str,
    *,
    model_name: str | None = None,
    enabled_only_for: str | None = None,
) -> dict[str, object] | None:
    """Builds an explicit provider config from the registry when the provider is available."""
    route = get_provider_primary_route(provider_name, api_keys, enabled_only_for=enabled_only_for)
    if not route:
        return None
    return route.to_execution_config(status_message=status_message, model_name=model_name)


def _build_parallel_fallback_chain(primary_provider: str, api_keys: dict | None, current_route_id: str | None = None) -> list[dict[str, object]]:
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


def _get_provider_lane_limits(per_provider_limit: int, active_providers: list[str], base_model_provider: str) -> dict[str, int]:
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
    provider_configs[primary_provider_name] = primary_route.to_execution_config(status_message=f"Retrying with {primary_provider_name}:{primary_model_name}", model_name=primary_model_name)

    for secondary_provider_name in active_provider_names:
        if secondary_provider_name == primary_provider_name:
            continue
        secondary_route = provider_routes[secondary_provider_name][0]
        provider_configs[secondary_provider_name] = secondary_route.to_execution_config(status_message=f"Switching to {_describe_provider_route(secondary_route)}")

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
                "fallback_chain": _build_parallel_fallback_chain(str(provider_config["model_provider"]), api_keys, current_route_id=current_route_id),
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

    return [route.to_execution_config(status_message=f"Switching to {_describe_provider_route(route)}") for route in get_provider_routes(api_keys, enabled_only_for="priority")]


def _apply_priority_strategy(model_name: str, model_provider: str, api_keys: dict | None) -> tuple[str, str, dict | None, list[dict[str, object]], str | None, str]:
    """Applies the registry-driven priority routing strategy when configured."""
    fallback_chain = _build_fallback_chain(model_provider, api_keys)
    if not fallback_chain:
        return model_name, model_provider, api_keys, [], None, _get_transport_family(model_provider, None, api_keys)

    primary = fallback_chain[0]
    primary_provider = str(primary["model_provider"])
    primary_model_name = model_name if primary_provider == str(model_provider) and model_name else str(primary["model_name"])
    return primary_model_name, primary_provider, primary.get("api_keys"), fallback_chain[1:], primary.get("route_id"), str(primary.get("transport_family") or _get_transport_family(primary_provider, primary.get("route_id"), api_keys))


def _compute_retry_delay(attempt: int, error: Exception) -> float:
    """Returns a bounded backoff delay for transient provider failures."""
    if _is_rate_limit_error(error):
        return min(2.0 * (attempt + 1), 10.0)
    return min(1.0 * (attempt + 1), 3.0)


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


def _is_provider_fallback_disabled() -> bool:
    """Returns whether cross-provider fallback is explicitly disabled for the current process."""
    return os.getenv("LLM_DISABLE_FALLBACK", "").strip().lower() in {"1", "true", "yes", "on"}


def _record_llm_attempt_safely(**kwargs) -> None:
    """Records metrics on a best-effort basis without affecting business logic."""
    try:
        record_llm_attempt(**kwargs)
    except Exception as metrics_error:
        logger.warning("Failed to record LLM metrics: %s", metrics_error)


def call_llm(
    prompt: any,
    pydantic_model: type[BaseModel],
    agent_name: str | None = None,
    state: AgentState | None = None,
    max_retries: int = 3,
    default_factory=None,
) -> BaseModel:
    """
    Makes an LLM call with retry logic, handling both JSON supported and non-JSON supported models.

    Args:
        prompt: The prompt to send to the LLM
        pydantic_model: The Pydantic model class to structure the output
        agent_name: Optional name of the agent for progress updates and model config extraction
        state: Optional state object to extract agent-specific model configuration
        max_retries: Maximum number of retries (default: 3)
        default_factory: Optional factory function to create default response on failure

    Returns:
        An instance of the specified Pydantic model
    """

    context = resolve_llm_call_context(
        state=state,
        agent_name=agent_name,
        get_agent_model_config=get_agent_model_config,
        get_default_model_config=get_default_model_config,
        extract_state_api_keys=_extract_state_api_keys,
        get_agent_llm_override=_get_agent_llm_override,
        get_llm_observability_context=_get_llm_observability_context,
        merge_api_keys=_merge_api_keys,
        apply_priority_strategy=_apply_priority_strategy,
        get_transport_family=_get_transport_family,
    )
    llm, model_info = _build_llm(context.active_model_name, context.active_model_provider, context.active_api_keys, pydantic_model)

    # Call the LLM with retries
    for attempt in range(max_retries):
        _wait_for_provider_rate_limit_cooldown(context.active_model_provider, context.active_route_id)
        attempt_started_at = perf_counter()
        try:
            result = llm.invoke(prompt)
            return return_success_result(
                llm_result=result,
                model_info=model_info,
                pydantic_model=pydantic_model,
                prompt=prompt,
                attempt_number=attempt + 1,
                duration_ms=(perf_counter() - attempt_started_at) * 1000,
                agent_name=agent_name,
                context=context,
                extract_json_from_response=extract_json_from_response,
                record_llm_attempt_safely=_record_llm_attempt_safely,
            )
        except Exception as e:
            outcome = handle_llm_failure(
                error=e,
                attempt_number=attempt + 1,
                max_retries=max_retries,
                duration_ms=(perf_counter() - attempt_started_at) * 1000,
                prompt=prompt,
                agent_name=agent_name,
                pydantic_model=pydantic_model,
                context=context,
                llm=llm,
                model_info=model_info,
                record_llm_attempt_safely=_record_llm_attempt_safely,
                compute_retry_delay=_compute_retry_delay,
                is_rate_limit_error=_is_rate_limit_error,
                register_provider_rate_limit_cooldown=_register_provider_rate_limit_cooldown,
                is_provider_fallback_disabled=_is_provider_fallback_disabled,
                get_transport_family=_get_transport_family,
                build_llm=_build_llm,
                progress_update_status=progress.update_status,
                create_default_response=(lambda _model: default_factory()) if default_factory else create_default_response,
                sleep=time.sleep,
            )
            llm = outcome.llm
            model_info = outcome.model_info
            if outcome.response is not None:
                return outcome.response
            if outcome.should_continue:
                continue

    # This should never be reached due to the retry logic above
    return create_default_response(pydantic_model)


def create_default_response(model_class: type[BaseModel]) -> BaseModel:
    """Creates a safe default response based on the model's fields."""
    default_values = {}
    for field_name, field in model_class.model_fields.items():
        if field.annotation is str:
            default_values[field_name] = "Error in analysis, using default"
        elif field.annotation is float:
            default_values[field_name] = 0.0
        elif field.annotation is int:
            default_values[field_name] = 0
        elif hasattr(field.annotation, "__origin__") and field.annotation.__origin__ is dict:
            default_values[field_name] = {}
        else:
            # For other types (like Literal), try to use the first allowed value
            if hasattr(field.annotation, "__args__"):
                default_values[field_name] = field.annotation.__args__[0]
            else:
                default_values[field_name] = None

    return model_class(**default_values)


def _strip_reasoning_blocks(content: str) -> str:
    """Removes model reasoning wrappers before JSON extraction."""
    patterns = [
        r"<think\b[^>]*>.*?</think>",
        r"<thinking\b[^>]*>.*?</thinking>",
    ]

    cleaned = content
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip()


def _extract_balanced_json_candidates(content: str) -> list[str]:
    return extract_balanced_json_candidates(content)


def _try_json_loads(payload: str) -> dict | None:
    """Attempts strict JSON parsing with a couple of bounded cleanups."""
    if not payload:
        return None

    candidates = [payload]
    cleaned_payload = re.sub(r",\s*([}\]])", r"\1", payload)
    if cleaned_payload != payload:
        candidates.append(cleaned_payload)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    return None


def _extract_common_signal_payload(content: str) -> dict | None:
    """Best-effort extractor for the common agent response schema when JSON is malformed."""
    signal_match = re.search(r'"signal"\s*:\s*"(?P<value>[^"]+)"', content)
    confidence_match = re.search(r'"confidence"\s*:\s*(?P<value>-?\d+(?:\.\d+)?)', content)
    reasoning_start = re.search(r'"reasoning"\s*:\s*"', content)
    reasoning_cn_start = re.search(r'"reasoning_cn"\s*:\s*"', content)

    if not (signal_match and confidence_match and reasoning_start and reasoning_cn_start):
        return None

    reasoning_value_start = reasoning_start.end()
    reasoning_value_end = reasoning_cn_start.start()
    reasoning_segment = content[reasoning_value_start:reasoning_value_end]
    reasoning_segment = re.sub(r'",\s*$', "", reasoning_segment, flags=re.DOTALL).strip()

    reasoning_cn_value_start = reasoning_cn_start.end()
    reasoning_cn_tail = content[reasoning_cn_value_start:]
    reasoning_cn_end = reasoning_cn_tail.rfind('"')
    if reasoning_cn_end == -1:
        return None
    reasoning_cn_segment = reasoning_cn_tail[:reasoning_cn_end].strip()

    try:
        confidence_value = float(confidence_match.group("value"))
    except ValueError:
        return None

    confidence: int | float
    if confidence_value.is_integer():
        confidence = int(confidence_value)
    else:
        confidence = confidence_value

    return {
        "signal": signal_match.group("value").strip(),
        "confidence": confidence,
        "reasoning": reasoning_segment.replace('\\"', '"').strip(),
        "reasoning_cn": reasoning_cn_segment.replace('\\"', '"').strip(),
    }


def extract_json_from_response(content: str) -> dict | None:
    """Extracts JSON from markdown-formatted response, handling various response formats."""
    try:
        if not content:
            return None

        # Remove model reasoning wrappers before attempting to parse JSON.
        content = _strip_reasoning_blocks(content)
        content = content.strip()
        return extract_json_payload_from_content(
            content=content,
            try_json_loads=_try_json_loads,
            extract_common_signal_payload=_extract_common_signal_payload,
        )

    except Exception as e:
        print(f"Error extracting JSON from response: {e}")
        if content:
            print(f"Content preview: {content[:500]}...")
    return None


def get_agent_model_config(state, agent_name):
    """
    Get model configuration for a specific agent from the state.
    Falls back to global model configuration if agent-specific config is not available.
    Always returns valid model_name and model_provider values.
    """
    request = state.get("metadata", {}).get("request")

    if request and hasattr(request, "get_agent_model_config"):
        # Get agent-specific model configuration
        model_name, model_provider = request.get_agent_model_config(agent_name)
        # Ensure we have valid values
        if model_name and model_provider:
            return model_name, model_provider.value if hasattr(model_provider, "value") else str(model_provider)

    # Fall back to global configuration (system defaults)
    default_model_name, default_model_provider = get_default_model_config()
    model_name = state.get("metadata", {}).get("model_name") or default_model_name
    model_provider = state.get("metadata", {}).get("model_provider") or default_model_provider

    # Convert enum to string if necessary
    if hasattr(model_provider, "value"):
        model_provider = model_provider.value

    return model_name, model_provider
