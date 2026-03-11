"""Helper functions for LLM"""

import json
import logging
import os
import re
import time
from time import perf_counter

from pydantic import BaseModel

from src.graph.state import AgentState
from src.llm.models import ProviderRoute, get_model, get_model_info, get_provider_concurrency_limit_env_var, get_provider_primary_route, get_provider_profile, get_provider_routes
from src.monitoring.llm_metrics import record_llm_attempt
from src.utils.progress import progress


logger = logging.getLogger(__name__)


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


def _get_parallel_provider_allowlist() -> set[str] | None:
    """Returns an optional allowlist for providers participating in parallel waves."""
    raw_value = os.getenv("LLM_PARALLEL_PROVIDER_ALLOWLIST", "").strip()
    if not raw_value:
        return None
    providers = {item.strip() for item in raw_value.split(",") if item.strip()}
    return providers or None


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
        return {
            "effective_concurrency_limit": per_provider_limit,
            "agent_llm_overrides": {},
            "parallel_provider_count": 1,
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
    return primary["model_name"], primary["model_provider"], primary.get("api_keys"), fallback_chain[1:], primary.get("route_id"), str(primary.get("transport_family") or _get_transport_family(str(primary["model_provider"]), primary.get("route_id"), api_keys))


def _compute_retry_delay(attempt: int, error: Exception) -> float:
    """Returns a bounded backoff delay for transient provider failures."""
    if _is_rate_limit_error(error):
        return min(2.0 * (attempt + 1), 10.0)
    return min(1.0 * (attempt + 1), 3.0)


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

    # Extract model configuration if state is provided and agent_name is available
    if state and agent_name:
        model_name, model_provider = get_agent_model_config(state, agent_name)
    else:
        # Use system defaults when no state or agent_name is provided
        model_name = "gpt-4.1"
        model_provider = "OPENAI"

    # Extract API keys from state if available
    api_keys = _extract_state_api_keys(state)
    agent_override = _get_agent_llm_override(state, agent_name)

    if agent_override:
        model_name = str(agent_override.get("model_name") or model_name)
        model_provider = str(agent_override.get("model_provider") or model_provider)
        api_keys = _merge_api_keys(api_keys, agent_override.get("api_keys"))
        fallback_chain = list(agent_override.get("fallback_chain") or [])
        active_route_id = str(agent_override.get("route_id") or "") or None
        active_transport_family = str(agent_override.get("transport_family") or _get_transport_family(model_provider, active_route_id, api_keys))
    else:
        model_name, model_provider, api_keys, fallback_chain, active_route_id, active_transport_family = _apply_priority_strategy(model_name, model_provider, api_keys)

    llm, model_info = _build_llm(model_name, model_provider, api_keys, pydantic_model)
    active_model_name = model_name
    active_model_provider = model_provider
    active_api_keys = api_keys
    fallback_index = 0

    # Call the LLM with retries
    for attempt in range(max_retries):
        attempt_started_at = perf_counter()
        try:
            # Call the LLM
            result = llm.invoke(prompt)

            # For non-JSON support models, we need to extract and parse the JSON manually
            if model_info and not model_info.has_json_mode():
                parsed_result = extract_json_from_response(result.content)
                if parsed_result:
                    _record_llm_attempt_safely(
                        agent_name=agent_name,
                        model_provider=active_model_provider,
                        model_name=active_model_name,
                        attempt_number=attempt + 1,
                        success=True,
                        duration_ms=(perf_counter() - attempt_started_at) * 1000,
                        prompt=prompt,
                        response=result.content,
                        used_fallback=fallback_index > 0,
                        route_id=active_route_id,
                        transport_family=active_transport_family,
                    )
                    return pydantic_model(**parsed_result)
                else:
                    raise ValueError(f"Could not extract valid JSON from response: {result.content[:200]}...")
            else:
                _record_llm_attempt_safely(
                    agent_name=agent_name,
                    model_provider=active_model_provider,
                    model_name=active_model_name,
                    attempt_number=attempt + 1,
                    success=True,
                    duration_ms=(perf_counter() - attempt_started_at) * 1000,
                    prompt=prompt,
                    response=getattr(result, "content", result),
                    used_fallback=fallback_index > 0,
                    route_id=active_route_id,
                    transport_family=active_transport_family,
                )
                return result

        except Exception as e:
            _record_llm_attempt_safely(
                agent_name=agent_name,
                model_provider=active_model_provider,
                model_name=active_model_name,
                attempt_number=attempt + 1,
                success=False,
                duration_ms=(perf_counter() - attempt_started_at) * 1000,
                prompt=prompt,
                error=e,
                is_rate_limit=_is_rate_limit_error(e),
                used_fallback=fallback_index > 0,
                route_id=active_route_id,
                transport_family=active_transport_family,
            )
            if fallback_index < len(fallback_chain) and _is_rate_limit_error(e):
                fallback_config = fallback_chain[fallback_index]
                fallback_index += 1
                active_model_name = fallback_config["model_name"]
                active_model_provider = fallback_config["model_provider"]
                active_api_keys = fallback_config.get("api_keys")
                active_route_id = str(fallback_config.get("route_id") or "") or None
                active_transport_family = str(fallback_config.get("transport_family") or _get_transport_family(active_model_provider, active_route_id, active_api_keys))
                llm, model_info = _build_llm(active_model_name, active_model_provider, active_api_keys, pydantic_model)
                if agent_name:
                    progress.update_status(agent_name, None, str(fallback_config["status_message"]))
                    continue

            if agent_name:
                progress.update_status(agent_name, None, f"Error - retry {attempt + 1}/{max_retries}")

            if attempt == max_retries - 1:
                print(f"Error in LLM call after {max_retries} attempts: {e}")
                # Use default_factory if provided, otherwise create a basic default
                if default_factory:
                    return default_factory()
                return create_default_response(pydantic_model)

            time.sleep(_compute_retry_delay(attempt, e))

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
    """Finds balanced JSON object candidates while ignoring braces inside strings."""
    candidates: list[str] = []
    brace_count = 0
    start_idx = -1
    in_string = False
    escape_next = False

    for index, char in enumerate(content):
        if in_string:
            if escape_next:
                escape_next = False
                continue
            if char == "\\":
                escape_next = True
                continue
            if char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue

        if char == "{":
            if brace_count == 0:
                start_idx = index
            brace_count += 1
            continue

        if char == "}" and brace_count > 0:
            brace_count -= 1
            if brace_count == 0 and start_idx != -1:
                candidates.append(content[start_idx : index + 1])
                start_idx = -1

    return candidates


def extract_json_from_response(content: str) -> dict | None:
    """Extracts JSON from markdown-formatted response, handling various response formats."""
    try:
        if not content:
            return None

        # Remove model reasoning wrappers before attempting to parse JSON.
        content = _strip_reasoning_blocks(content)
        content = content.strip()

        # Try direct JSON first after cleaning.
        if content.startswith("{") or content.startswith("["):
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                pass

        # Try to find JSON in markdown code block with 'json' marker
        json_start = content.find("```json")
        if json_start != -1:
            json_text = content[json_start + 7 :]  # Skip past ```json
            json_end = json_text.find("```")
            if json_end != -1:
                json_text = json_text[:json_end].strip()
                return json.loads(json_text)

        # Try to find JSON in markdown code block without 'json' marker
        json_start = content.find("```")
        if json_start != -1:
            json_text = content[json_start + 3 :]  # Skip past ```
            json_end = json_text.find("```")
            if json_end != -1:
                json_text = json_text[:json_end].strip()
                if json_text.startswith("{") or json_text.startswith("["):
                    return json.loads(json_text)

        # Try to find raw JSON object with balanced braces.
        for json_str in _extract_balanced_json_candidates(content):
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                continue

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
    model_name = state.get("metadata", {}).get("model_name") or "gpt-4.1"
    model_provider = state.get("metadata", {}).get("model_provider") or "OPENAI"

    # Convert enum to string if necessary
    if hasattr(model_provider, "value"):
        model_provider = model_provider.value

    return model_name, model_provider
