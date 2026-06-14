"""Characterization tests for src/utils/llm_call_helpers.py.

resolve_llm_call_context and return_success_result are dependency-injected
orchestrators extracted from the LLM call path. They had zero direct test
coverage. Tests use mock Callables to verify the routing + JSON-extraction
contracts without touching real LLM providers.
"""
from __future__ import annotations

from typing import Any

import pytest

from src.utils.llm_call_helpers import (
    LlmCallContext,
    resolve_llm_call_context,
    return_success_result,
)


def _noop(*_args: Any, **_kwargs: Any) -> Any:
    return None


class _ModelInfo:
    def __init__(self, json_mode: bool) -> None:
        self._json_mode = json_mode

    def has_json_mode(self) -> bool:
        return self._json_mode


class TestResolveLlmCallContext:
    def _build(
        self,
        *,
        get_agent_override: Any = _noop,
        get_agent_model_config: Any = _noop,
        get_default_model_config: Any = lambda: ("default-model", "default-provider"),
        extract_state_api_keys: Any = lambda state: None,
        get_observability: Any = lambda state: {},
        merge_api_keys: Any = lambda base, extra: base,
        apply_priority_strategy: Any = lambda name, prov, keys: (name, prov, keys, [], None, "native"),
        get_transport_family: Any = lambda prov, route_id, keys: "native",
        state: Any = None,
        agent_name: str | None = None,
    ) -> LlmCallContext:
        return resolve_llm_call_context(
            state=state,
            agent_name=agent_name,
            get_agent_model_config=get_agent_model_config,
            get_default_model_config=get_default_model_config,
            extract_state_api_keys=extract_state_api_keys,
            get_agent_llm_override=get_agent_override,
            get_llm_observability_context=get_observability,
            merge_api_keys=merge_api_keys,
            apply_priority_strategy=apply_priority_strategy,
            get_transport_family=get_transport_family,
        )

    def test_default_config_when_no_state_no_agent(self) -> None:
        ctx = self._build()
        assert ctx.active_model_name == "default-model"
        assert ctx.active_model_provider == "default-provider"

    def test_agent_model_config_when_state_and_agent(self) -> None:
        ctx = self._build(
            state={"some": "state"},
            agent_name="warren_buffett",
            get_agent_model_config=lambda state, name: ("agent-model", "agent-provider"),
        )
        assert ctx.active_model_name == "agent-model"
        assert ctx.active_model_provider == "agent-provider"

    def test_agent_override_takes_precedence(self) -> None:
        """An explicit agent override wins over agent model config."""
        ctx = self._build(
            state={"s": 1},
            agent_name="agent",
            get_agent_override=lambda state, name: {
                "model_name": "override-model",
                "model_provider": "override-provider",
                "api_keys": {"K": "v"},
                "fallback_chain": [{"model_name": "fb"}],
                "route_id": "route-1",
                "transport_family": "openai-compatible",
            },
        )
        assert ctx.active_model_name == "override-model"
        assert ctx.active_model_provider == "override-provider"
        assert ctx.active_route_id == "route-1"
        assert ctx.active_transport_family == "openai-compatible"
        assert ctx.fallback_chain == [{"model_name": "fb"}]

    def test_override_merges_api_keys(self) -> None:
        merged = {"base": "1", "extra": "2"}

        def merge(base, extra):
            return merged

        ctx = self._build(
            get_agent_override=lambda s, n: {"model_name": "m", "model_provider": "p", "api_keys": {"extra": "2"}},
            merge_api_keys=merge,
        )
        assert ctx.active_api_keys == merged

    def test_priority_strategy_applied_without_override(self) -> None:
        """Without override, apply_priority_strategy transforms the config."""
        ctx = self._build(
            apply_priority_strategy=lambda name, prov, keys: ("prio-model", "prio-prov", keys, [{"fb": 1}], "route-x", "openai-compatible"),
        )
        assert ctx.active_model_name == "prio-model"
        assert ctx.active_model_provider == "prio-prov"
        assert ctx.fallback_chain == [{"fb": 1}]
        assert ctx.active_route_id == "route-x"

    def test_observability_extracted_from_state(self) -> None:
        ctx = self._build(
            state={"x": 1},
            get_observability=lambda state: {"trade_date": "20260615"},
        )
        assert ctx.llm_observability == {"trade_date": "20260615"}


class TestReturnSuccessResult:
    def test_json_mode_returns_raw_result(self) -> None:
        """When model has JSON mode, return llm_result directly (no extraction)."""
        llm_result = {"content": "raw"}
        recorded = []

        result = return_success_result(
            llm_result=llm_result,
            model_info=_ModelInfo(json_mode=True),
            pydantic_model=None,
            prompt="p",
            attempt_number=1,
            duration_ms=10.0,
            agent_name="a",
            context=LlmCallContext(
                active_model_name="m",
                active_model_provider="p",
                active_api_keys=None,
                fallback_chain=[],
                active_route_id=None,
                active_transport_family="native",
                llm_observability={},
            ),
            extract_json_from_response=lambda c: None,
            record_llm_attempt_safely=lambda **kw: recorded.append(kw),
        )
        assert result is llm_result
        assert len(recorded) == 1
        assert recorded[0]["success"] is True

    def test_no_json_mode_extracts_and_constructs_pydantic(self) -> None:
        """Without JSON mode, extract JSON and construct pydantic_model."""

        class _Pyd:
            def __init__(self, **kw):
                self.data = kw

        result = return_success_result(
            llm_result=type("R", (), {"content": '{"key": "val"}'})(),
            model_info=_ModelInfo(json_mode=False),
            pydantic_model=_Pyd,
            prompt="p",
            attempt_number=1,
            duration_ms=5.0,
            agent_name="a",
            context=LlmCallContext(
                active_model_name="m",
                active_model_provider="p",
                active_api_keys=None,
                fallback_chain=[],
                active_route_id=None,
                active_transport_family="native",
                llm_observability={},
            ),
            extract_json_from_response=lambda c: {"key": "val"},
            record_llm_attempt_safely=lambda **kw: None,
        )
        assert result.data == {"key": "val"}

    def test_no_json_mode_invalid_json_raises(self) -> None:
        """Invalid JSON extraction → ValueError."""
        with pytest.raises(ValueError, match="Could not extract"):
            return_success_result(
                llm_result=type("R", (), {"content": "not json"})(),
                model_info=_ModelInfo(json_mode=False),
                pydantic_model=None,
                prompt="p",
                attempt_number=1,
                duration_ms=5.0,
                agent_name="a",
                context=LlmCallContext(
                    active_model_name="m",
                    active_model_provider="p",
                    active_api_keys=None,
                    fallback_chain=[],
                    active_route_id=None,
                    active_transport_family="native",
                    llm_observability={},
                ),
                extract_json_from_response=lambda c: None,
                record_llm_attempt_safely=lambda **kw: None,
            )
