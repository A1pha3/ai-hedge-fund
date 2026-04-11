"""Helper functions for LLM."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from time import perf_counter

from pydantic import BaseModel

from src.graph.state import AgentState
from src.llm.defaults import get_default_model_config
from src.llm.models import get_model, get_model_info, get_provider_concurrency_limit_env_var, get_provider_profile, get_provider_routes
from src.monitoring.llm_metrics import record_llm_attempt
from src.utils.llm_call_helpers import handle_llm_failure, resolve_llm_call_context, return_success_result
from src.utils.llm_json_helpers import extract_balanced_json_candidates, extract_json_payload_from_content
from src.utils import llm_provider_routing
from src.utils.progress import progress


logger = logging.getLogger(__name__)


DEFAULT_ZHIPU_FALLBACK_MODEL = llm_provider_routing.DEFAULT_ZHIPU_FALLBACK_MODEL
DEFAULT_ZHIPU_CODING_PLAN_FALLBACK_MODEL = llm_provider_routing.DEFAULT_ZHIPU_CODING_PLAN_FALLBACK_MODEL
DEFAULT_MINIMAX_FALLBACK_MODEL = llm_provider_routing.DEFAULT_MINIMAX_FALLBACK_MODEL


def _sync_provider_routing_dependencies() -> None:
    """Keeps extracted routing helpers monkeypatch-compatible through src.utils.llm."""
    llm_provider_routing.get_provider_routes = get_provider_routes
    llm_provider_routing.get_provider_profile = get_provider_profile
    llm_provider_routing.get_provider_concurrency_limit_env_var = get_provider_concurrency_limit_env_var


def _get_transport_family(provider_name: str, route_id: str | None, api_keys: dict | None) -> str:
    _sync_provider_routing_dependencies()
    return llm_provider_routing._get_transport_family(provider_name, route_id, api_keys)


def _apply_priority_strategy(model_name: str, model_provider: str, api_keys: dict | None) -> tuple[str, str, dict | None, list[dict[str, object]], str | None, str]:
    _sync_provider_routing_dependencies()
    return llm_provider_routing._apply_priority_strategy(model_name, model_provider, api_keys)


def build_parallel_provider_execution_plan(
    agent_names: list[str],
    base_model_name: str,
    base_model_provider: str,
    api_keys: dict | None,
    per_provider_limit: int,
) -> dict[str, object]:
    _sync_provider_routing_dependencies()
    return llm_provider_routing.build_parallel_provider_execution_plan(agent_names, base_model_name, base_model_provider, api_keys, per_provider_limit)


def _register_provider_rate_limit_cooldown(model_provider: str, route_id: str | None, delay_seconds: float) -> None:
    llm_provider_routing._register_provider_rate_limit_cooldown(model_provider, route_id, delay_seconds)


def _wait_for_provider_rate_limit_cooldown(model_provider: str, route_id: str | None) -> float:
    return llm_provider_routing._wait_for_provider_rate_limit_cooldown(model_provider, route_id)


def _reset_provider_rate_limit_cooldowns_for_testing() -> None:
    llm_provider_routing._reset_provider_rate_limit_cooldowns_for_testing()


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


def _compute_retry_delay(attempt: int, error: Exception) -> float:
    """Returns a bounded backoff delay for transient provider failures."""
    if _is_rate_limit_error(error):
        return min(2.0 * (attempt + 1), 10.0)
    return min(1.0 * (attempt + 1), 3.0)


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
    prompt,
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
    llm, model_info = _build_llm(
        context.active_model_name,
        context.active_model_provider,
        context.active_api_keys,
        pydantic_model,
    )

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
        except Exception as error:
            outcome = handle_llm_failure(
                error=error,
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

        content = _strip_reasoning_blocks(content)
        content = content.strip()
        return extract_json_payload_from_content(
            content=content,
            try_json_loads=_try_json_loads,
            extract_common_signal_payload=_extract_common_signal_payload,
        )
    except Exception as error:
        print(f"Error extracting JSON from response: {error}")
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
        model_name, model_provider = request.get_agent_model_config(agent_name)
        if model_name and model_provider:
            return model_name, model_provider.value if hasattr(model_provider, "value") else str(model_provider)

    default_model_name, default_model_provider = get_default_model_config()
    model_name = state.get("metadata", {}).get("model_name") or default_model_name
    model_provider = state.get("metadata", {}).get("model_provider") or default_model_provider
    if hasattr(model_provider, "value"):
        model_provider = model_provider.value

    return model_name, model_provider
