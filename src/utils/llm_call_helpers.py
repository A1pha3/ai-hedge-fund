from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from collections.abc import Callable


@dataclass
class LlmCallContext:
    active_model_name: str
    active_model_provider: str
    active_api_keys: dict | None
    fallback_chain: list[dict[str, object]]
    active_route_id: str | None
    active_transport_family: str
    llm_observability: dict[str, str]
    fallback_index: int = 0


@dataclass
class LlmFailureOutcome:
    should_continue: bool
    llm: Any
    model_info: Any
    response: Any = None


def resolve_llm_call_context(
    *,
    state,
    agent_name: str | None,
    get_agent_model_config: Callable,
    get_default_model_config: Callable,
    extract_state_api_keys: Callable,
    get_agent_llm_override: Callable,
    get_llm_observability_context: Callable,
    merge_api_keys: Callable,
    apply_priority_strategy: Callable,
    get_transport_family: Callable,
) -> LlmCallContext:
    agent_override = get_agent_llm_override(state, agent_name)
    if agent_override:
        model_name = str(agent_override.get("model_name") or "")
        model_provider = str(agent_override.get("model_provider") or "")
    elif state and agent_name:
        model_name, model_provider = get_agent_model_config(state, agent_name)
    else:
        model_name, model_provider = get_default_model_config()
    api_keys = extract_state_api_keys(state)
    llm_observability = get_llm_observability_context(state)
    if agent_override:
        model_name = str(agent_override.get("model_name") or model_name)
        model_provider = str(agent_override.get("model_provider") or model_provider)
        api_keys = merge_api_keys(api_keys, agent_override.get("api_keys"))
        fallback_chain = list(agent_override.get("fallback_chain") or [])
        active_route_id = str(agent_override.get("route_id") or "") or None
        active_transport_family = str(agent_override.get("transport_family") or get_transport_family(model_provider, active_route_id, api_keys))
    else:
        model_name, model_provider, api_keys, fallback_chain, active_route_id, active_transport_family = apply_priority_strategy(model_name, model_provider, api_keys)
    return LlmCallContext(
        active_model_name=model_name,
        active_model_provider=model_provider,
        active_api_keys=api_keys,
        fallback_chain=fallback_chain,
        active_route_id=active_route_id,
        active_transport_family=active_transport_family,
        llm_observability=llm_observability,
    )


def return_success_result(
    *,
    llm_result: Any,
    model_info: Any,
    pydantic_model,
    prompt: Any,
    attempt_number: int,
    duration_ms: float,
    agent_name: str | None,
    context: LlmCallContext,
    extract_json_from_response: Callable[[str], dict | None],
    record_llm_attempt_safely: Callable[..., None],
):
    if model_info and not model_info.has_json_mode():
        parsed_result = extract_json_from_response(llm_result.content)
        if not parsed_result:
            raise ValueError(f"Could not extract valid JSON from response: {llm_result.content[:200]}...")
        record_llm_attempt_safely(
            agent_name=agent_name,
            model_provider=context.active_model_provider,
            model_name=context.active_model_name,
            attempt_number=attempt_number,
            success=True,
            duration_ms=duration_ms,
            prompt=prompt,
            response=llm_result.content,
            used_fallback=context.fallback_index > 0,
            route_id=context.active_route_id,
            transport_family=context.active_transport_family,
            trade_date=context.llm_observability.get("trade_date"),
            pipeline_stage=context.llm_observability.get("pipeline_stage"),
            model_tier=context.llm_observability.get("model_tier"),
        )
        return pydantic_model(**parsed_result)
    record_llm_attempt_safely(
        agent_name=agent_name,
        model_provider=context.active_model_provider,
        model_name=context.active_model_name,
        attempt_number=attempt_number,
        success=True,
        duration_ms=duration_ms,
        prompt=prompt,
        response=getattr(llm_result, "content", llm_result),
        used_fallback=context.fallback_index > 0,
        route_id=context.active_route_id,
        transport_family=context.active_transport_family,
        trade_date=context.llm_observability.get("trade_date"),
        pipeline_stage=context.llm_observability.get("pipeline_stage"),
        model_tier=context.llm_observability.get("model_tier"),
    )
    return llm_result


def handle_llm_failure(
    *,
    error: Exception,
    attempt_number: int,
    max_retries: int,
    duration_ms: float,
    prompt: Any,
    agent_name: str | None,
    pydantic_model,
    context: LlmCallContext,
    llm: Any,
    model_info: Any,
    record_llm_attempt_safely: Callable[..., None],
    compute_retry_delay: Callable[[int, Exception], float],
    is_rate_limit_error: Callable[[Exception], bool],
    register_provider_rate_limit_cooldown: Callable[[str, str | None, float], None],
    is_provider_fallback_disabled: Callable[[], bool],
    get_transport_family: Callable[[str, str | None, dict | None], str],
    build_llm: Callable,
    progress_update_status: Callable[[str, Any, str], None],
    create_default_response: Callable,
    sleep: Callable[[float], None],
) -> LlmFailureOutcome:
    retry_delay = compute_retry_delay(attempt_number - 1, error)
    is_rate_limited = is_rate_limit_error(error)
    record_llm_attempt_safely(
        agent_name=agent_name,
        model_provider=context.active_model_provider,
        model_name=context.active_model_name,
        attempt_number=attempt_number,
        success=False,
        duration_ms=duration_ms,
        prompt=prompt,
        error=error,
        is_rate_limit=is_rate_limited,
        used_fallback=context.fallback_index > 0,
        route_id=context.active_route_id,
        transport_family=context.active_transport_family,
        trade_date=context.llm_observability.get("trade_date"),
        pipeline_stage=context.llm_observability.get("pipeline_stage"),
        model_tier=context.llm_observability.get("model_tier"),
    )
    if is_rate_limited:
        register_provider_rate_limit_cooldown(context.active_model_provider, context.active_route_id, retry_delay)

    if context.fallback_index < len(context.fallback_chain) and is_rate_limited:
        if is_provider_fallback_disabled():
            context.fallback_chain = []
        else:
            fallback_config = context.fallback_chain[context.fallback_index]
            context.fallback_index += 1
            context.active_model_name = str(fallback_config["model_name"])
            context.active_model_provider = str(fallback_config["model_provider"])
            context.active_api_keys = fallback_config.get("api_keys")
            context.active_route_id = str(fallback_config.get("route_id") or "") or None
            context.active_transport_family = str(fallback_config.get("transport_family") or get_transport_family(context.active_model_provider, context.active_route_id, context.active_api_keys))
            llm, model_info = build_llm(context.active_model_name, context.active_model_provider, context.active_api_keys, pydantic_model)
            if agent_name:
                progress_update_status(agent_name, None, str(fallback_config["status_message"]))
            return LlmFailureOutcome(should_continue=True, llm=llm, model_info=model_info)

    if agent_name:
        progress_update_status(agent_name, None, f"Error - retry {attempt_number}/{max_retries}")
    if attempt_number == max_retries:
        print(f"Error in LLM call after {max_retries} attempts: {error}")
        return LlmFailureOutcome(should_continue=False, llm=llm, model_info=model_info, response=create_default_response(pydantic_model))
    if not is_rate_limited:
        sleep(retry_delay)
    return LlmFailureOutcome(should_continue=True, llm=llm, model_info=model_info)
