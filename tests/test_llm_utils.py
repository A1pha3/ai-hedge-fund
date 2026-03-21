from pydantic import BaseModel

from src.monitoring.llm_metrics import get_llm_metrics_paths, reset_llm_metrics_for_testing
from src.utils import llm as llm_utils
from src.utils.llm import call_llm, extract_json_from_response


class _FallbackSignal(BaseModel):
    signal: str


def setup_function():
    reset_llm_metrics_for_testing()
    llm_utils._reset_provider_rate_limit_cooldowns_for_testing()


def test_extract_json_from_response_strips_think_tags():
    content = '''
<think>
Need to reason first.
</think>
{
  "signal": "bearish",
  "confidence": 72,
  "reasoning": "Margins are weakening.",
  "reasoning_cn": "利润率正在走弱。"
}
'''

    parsed = extract_json_from_response(content)

    assert parsed is not None
    assert parsed["signal"] == "bearish"
    assert parsed["confidence"] == 72


def test_extract_json_from_response_handles_braces_inside_string():
    content = '''
Analysis summary before JSON.
{
  "signal": "neutral",
  "confidence": 55,
  "reasoning": "Management mentioned {temporary demand pressure} but guidance stayed stable.",
  "reasoning_cn": "管理层提到短期需求压力，但指引保持稳定。"
}
Trailing notes.
'''

    parsed = extract_json_from_response(content)

    assert parsed is not None
    assert parsed["signal"] == "neutral"
    assert "temporary demand pressure" in parsed["reasoning"]


def test_extract_json_from_response_handles_json_code_block_after_thinking():
    content = '''
<thinking>
internal chain of thought
</thinking>

```json
{
  "signal": "bullish",
  "confidence": 88,
  "reasoning": "Revenue acceleration and strong order visibility.",
  "reasoning_cn": "收入加速且订单可见性较强。"
}
```
'''

    parsed = extract_json_from_response(content)

    assert parsed is not None
    assert parsed["signal"] == "bullish"
    assert parsed["confidence"] == 88


def test_extract_json_from_response_handles_trailing_comma_in_code_block():
        content = '''
```json
{
    "signal": "neutral",
    "confidence": 55,
    "reasoning": "Inventory is stabilizing.",
    "reasoning_cn": "库存正在企稳。",
}
```
'''

        parsed = extract_json_from_response(content)

        assert parsed is not None
        assert parsed["signal"] == "neutral"
        assert parsed["confidence"] == 55


def test_extract_json_from_response_recovers_common_signal_schema_with_unescaped_quotes():
        content = '''
```json
{
    "signal": "neutral",
    "confidence": 55,
    "reasoning": "This is a "GARP dream" setup with strong growth.",
    "reasoning_cn": "这是一个"GARP 梦想"式的成长组合。"
}
```
'''

        parsed = extract_json_from_response(content)

        assert parsed is not None
        assert parsed["signal"] == "neutral"
        assert parsed["confidence"] == 55
        assert 'GARP dream' in parsed["reasoning"]
        assert 'GARP 梦想' in parsed["reasoning_cn"]


def test_call_llm_prefers_coding_plan_before_other_supported_providers(monkeypatch):
    calls = []

    class FakeModelInfo:
        def __init__(self, has_json_mode: bool):
            self._has_json_mode = has_json_mode

        def has_json_mode(self):
            return self._has_json_mode

    class FakeStructuredLLM:
        def __init__(self, provider, model_name, api_key):
            self.provider = provider
            self.model_name = model_name
            self.api_key = api_key

        def invoke(self, prompt):
            calls.append((self.provider, self.model_name, self.api_key, "invoke", prompt))
            return _FallbackSignal(signal="ok")

    class FakeLLM:
        def __init__(self, provider, model_name, api_key):
            self.provider = provider
            self.model_name = model_name
            self.api_key = api_key

        def with_structured_output(self, pydantic_model, method="json_mode"):
            calls.append((self.provider, self.model_name, self.api_key, "with_structured_output", method, pydantic_model.__name__))
            return FakeStructuredLLM(self.provider, self.model_name, self.api_key)

        def invoke(self, prompt):
            calls.append((self.provider, self.model_name, self.api_key, "invoke", prompt))
            return type("Response", (), {"content": '{"signal": "ok"}'})()

    monkeypatch.setenv("ZHIPU_API_KEY", "test-key")
    monkeypatch.setenv("ZHIPU_CODE_API_KEY", "coding-key")
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.delenv("ZHIPU_FALLBACK_MODEL", raising=False)
    monkeypatch.delenv("ZHIPU_CODING_FALLBACK_MODEL", raising=False)
    monkeypatch.setattr(llm_utils, "get_agent_model_config", lambda state, agent_name: ("MiniMax-M2.5", "MiniMax"))
    monkeypatch.setattr(
        llm_utils,
        "get_model_info",
        lambda model_name, model_provider: FakeModelInfo(has_json_mode=str(model_provider) == "Zhipu"),
    )

    def fake_get_model(model_name, model_provider, api_keys=None):
        api_key = None
        if api_keys:
            api_key = api_keys.get("ZHIPU_CODE_API_KEY") or api_keys.get("MINIMAX_API_KEY") or api_keys.get("ZHIPU_API_KEY")
        return FakeLLM(str(model_provider), model_name, api_key)

    monkeypatch.setattr(llm_utils, "get_model", fake_get_model)

    result = call_llm(
        prompt="hello",
        pydantic_model=_FallbackSignal,
        agent_name="test_agent",
        state={"metadata": {}},
        max_retries=3,
    )

    assert result.signal == "ok"
    assert ("Zhipu", "glm-4.7", "coding-key", "with_structured_output", "json_mode", "_FallbackSignal") in calls
    assert ("Zhipu", "glm-4.7", "coding-key", "invoke", "hello") in calls


def test_call_llm_falls_back_from_coding_plan_to_minimax_to_standard_zhipu(monkeypatch):
    calls = []
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    class FakeModelInfo:
        def __init__(self, has_json_mode: bool):
            self._has_json_mode = has_json_mode

        def has_json_mode(self):
            return self._has_json_mode

    class FakeStructuredLLM:
        def __init__(self, provider, model_name, api_key):
            self.provider = provider
            self.model_name = model_name
            self.api_key = api_key

        def invoke(self, prompt):
            calls.append((self.provider, self.model_name, self.api_key, "invoke", prompt))
            if self.api_key in {"coding-key", "minimax-key"}:
                raise RuntimeError("429 too many requests")
            return _FallbackSignal(signal="ok")

    class FakeLLM:
        def __init__(self, provider, model_name, api_key):
            self.provider = provider
            self.model_name = model_name
            self.api_key = api_key

        def with_structured_output(self, pydantic_model, method="json_mode"):
            calls.append((self.provider, self.model_name, self.api_key, "with_structured_output", method, pydantic_model.__name__))
            return FakeStructuredLLM(self.provider, self.model_name, self.api_key)

        def invoke(self, prompt):
            calls.append((self.provider, self.model_name, self.api_key, "invoke", prompt))
            raise RuntimeError("429 too many requests")

    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-key")
    monkeypatch.setenv("ZHIPU_CODE_API_KEY", "coding-key")
    monkeypatch.setenv("ZHIPU_API_KEY", "standard-key")
    monkeypatch.setattr(llm_utils, "get_agent_model_config", lambda state, agent_name: ("MiniMax-M2.5", "MiniMax"))
    monkeypatch.setattr(
        llm_utils,
        "get_model_info",
        lambda model_name, model_provider: FakeModelInfo(has_json_mode=str(model_provider) == "Zhipu"),
    )

    def fake_get_model(model_name, model_provider, api_keys=None):
        api_key = None
        if api_keys:
            api_key = api_keys.get("ZHIPU_CODE_API_KEY") or api_keys.get("MINIMAX_API_KEY") or api_keys.get("ZHIPU_API_KEY")
        return FakeLLM(str(model_provider), model_name, api_key)

    monkeypatch.setattr(llm_utils, "get_model", fake_get_model)

    result = call_llm(
        prompt="hello",
        pydantic_model=_FallbackSignal,
        agent_name="test_agent",
        state={"metadata": {}},
        max_retries=3,
    )

    assert result.signal == "ok"
    assert ("Zhipu", "glm-4.7", "coding-key", "invoke", "hello") in calls
    assert ("MiniMax", "MiniMax-M2.5", "minimax-key", "invoke", "hello") in calls
    assert ("Zhipu", "glm-4.7", "standard-key", "invoke", "hello") in calls


def test_call_llm_agent_override_bypasses_priority_strategy(monkeypatch):
    calls = []

    class FakeModelInfo:
        def __init__(self, has_json_mode: bool):
            self._has_json_mode = has_json_mode

        def has_json_mode(self):
            return self._has_json_mode

    class FakeLLM:
        def __init__(self, provider, model_name, api_key):
            self.provider = provider
            self.model_name = model_name
            self.api_key = api_key

        def with_structured_output(self, pydantic_model, method="json_mode"):
            calls.append((self.provider, self.model_name, self.api_key, "with_structured_output", method, pydantic_model.__name__))
            return self

        def invoke(self, prompt):
            calls.append((self.provider, self.model_name, self.api_key, "invoke", prompt))
            return _FallbackSignal(signal="ok")

    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-key")
    monkeypatch.setenv("ZHIPU_CODE_API_KEY", "coding-key")
    monkeypatch.setattr(llm_utils, "get_agent_model_config", lambda state, agent_name: ("MiniMax-M2.5", "MiniMax"))
    monkeypatch.setattr(llm_utils, "get_model_info", lambda model_name, model_provider: FakeModelInfo(has_json_mode=True))

    def fake_get_model(model_name, model_provider, api_keys=None):
        api_key = None
        if api_keys:
            api_key = api_keys.get("MINIMAX_API_KEY") or api_keys.get("ZHIPU_CODE_API_KEY") or api_keys.get("ZHIPU_API_KEY")
        return FakeLLM(str(model_provider), model_name, api_key)

    monkeypatch.setattr(llm_utils, "get_model", fake_get_model)

    result = call_llm(
        prompt="hello",
        pydantic_model=_FallbackSignal,
        agent_name="test_agent",
        state={
            "metadata": {
                "agent_llm_overrides": {
                    "test_agent": {
                        "model_name": "MiniMax-M2.5",
                        "model_provider": "MiniMax",
                        "api_keys": {"MINIMAX_API_KEY": "minimax-key"},
                        "fallback_chain": [],
                    }
                }
            }
        },
        max_retries=3,
    )

    assert result.signal == "ok"
    assert calls[0] == ("MiniMax", "MiniMax-M2.5", "minimax-key", "with_structured_output", "json_mode", "_FallbackSignal")
    assert calls[1] == ("MiniMax", "MiniMax-M2.5", "minimax-key", "invoke", "hello")


def test_call_llm_records_structured_metrics(monkeypatch):
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("ZHIPU_API_KEY", raising=False)
    monkeypatch.delenv("ZHIPU_CODE_API_KEY", raising=False)

    class FakeModelInfo:
        def has_json_mode(self):
            return True

    class FakeLLM:
        def with_structured_output(self, pydantic_model, method="json_mode"):
            return self

        def invoke(self, prompt):
            return _FallbackSignal(signal="ok")

    monkeypatch.setattr(llm_utils, "get_agent_model_config", lambda state, agent_name: ("MiniMax-M2.5", "MiniMax"))
    monkeypatch.setattr(llm_utils, "get_model_info", lambda model_name, model_provider: FakeModelInfo())
    monkeypatch.setattr(llm_utils, "get_model", lambda model_name, model_provider, api_keys=None: FakeLLM())

    result = call_llm(
        prompt="hello metrics",
        pydantic_model=_FallbackSignal,
        agent_name="metrics_agent",
        state={
            "metadata": {
                "llm_observability": {
                    "trade_date": "20260320",
                    "pipeline_stage": "daily_pipeline_post_market",
                    "model_tier": "fast",
                }
            }
        },
    )

    paths = get_llm_metrics_paths()
    summary_path = paths["summary_path"]
    jsonl_path = paths["jsonl_path"]

    assert result.signal == "ok"
    with open(summary_path, "r", encoding="utf-8") as handle:
        summary = __import__("json").load(handle)
    with open(jsonl_path, "r", encoding="utf-8") as handle:
        lines = [line for line in handle.readlines() if line.strip()]

    assert len(lines) == 1
    assert summary["totals"]["attempts"] == 1
    assert summary["totals"]["successes"] == 1
    assert summary["totals"]["fallback_attempts"] == 0
    assert summary["totals"]["prompt_chars"] > 0
    assert summary["agents"]["metrics_agent"]["attempts"] == 1
    assert len(summary["providers"]) == 1
    assert "transport_families" in summary
    assert "routes" in summary
    assert summary["trade_dates"]["20260320"]["attempts"] == 1
    assert summary["pipeline_stages"]["daily_pipeline_post_market"]["attempts"] == 1
    assert summary["model_tiers"]["fast"]["attempts"] == 1

    entry = __import__("json").loads(lines[0])
    assert entry["trade_date"] == "20260320"
    assert entry["pipeline_stage"] == "daily_pipeline_post_market"
    assert entry["model_tier"] == "fast"


def test_call_llm_records_fallback_attempt_metrics(monkeypatch):
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("ZHIPU_API_KEY", raising=False)
    monkeypatch.delenv("ZHIPU_CODE_API_KEY", raising=False)

    class FakeModelInfo:
        def has_json_mode(self):
            return True

    class FakeLLM:
        def __init__(self, provider):
            self.provider = provider

        def with_structured_output(self, pydantic_model, method="json_mode"):
            return self

        def invoke(self, prompt):
            if self.provider == "MiniMax":
                raise RuntimeError("429 rate limit")
            return _FallbackSignal(signal="fallback-ok")

    monkeypatch.setattr(llm_utils, "get_agent_model_config", lambda state, agent_name: ("MiniMax-M2.7", "MiniMax"))
    monkeypatch.setattr(llm_utils, "get_model_info", lambda model_name, model_provider: FakeModelInfo())
    monkeypatch.setattr(llm_utils, "get_model", lambda model_name, model_provider, api_keys=None: FakeLLM(str(model_provider)))

    result = call_llm(
        prompt="hello fallback metrics",
        pydantic_model=_FallbackSignal,
        agent_name="fallback_metrics_agent",
        state={
            "metadata": {
                "agent_llm_overrides": {
                    "fallback_metrics_agent": {
                        "model_name": "MiniMax-M2.7",
                        "model_provider": "MiniMax",
                        "api_keys": {},
                        "fallback_chain": [
                            {
                                "model_name": "doubao-seed-2.0-pro",
                                "model_provider": "Volcengine Ark",
                                "api_keys": {},
                                "status_message": "MiniMax limited, switching to Volcengine Ark:doubao-seed-2.0-pro",
                                "route_id": "Volcengine Ark:default",
                                "transport_family": "openai-compatible",
                            }
                        ],
                        "route_id": "MiniMax:default",
                        "transport_family": "openai-compatible",
                    }
                }
            }
        },
        max_retries=3,
    )

    paths = get_llm_metrics_paths()
    with open(paths["summary_path"], "r", encoding="utf-8") as handle:
        summary = __import__("json").load(handle)

    assert result.signal == "fallback-ok"
    assert summary["totals"]["attempts"] == 2
    assert summary["totals"]["rate_limit_errors"] == 1
    assert summary["totals"]["fallback_attempts"] == 1
    assert summary["providers"]["Volcengine Ark"]["fallback_attempts"] == 1


def test_call_llm_disables_provider_fallback_when_requested(monkeypatch):
    monkeypatch.setenv("LLM_DISABLE_FALLBACK", "true")

    class FakeModelInfo:
        def has_json_mode(self):
            return True

    class FakeLLM:
        def with_structured_output(self, pydantic_model, method="json_mode"):
            return self

        def invoke(self, prompt):
            raise RuntimeError("429 rate limit")

    monkeypatch.setattr(llm_utils, "get_agent_model_config", lambda state, agent_name: ("MiniMax-M2.7", "MiniMax"))
    monkeypatch.setattr(llm_utils, "get_model_info", lambda model_name, model_provider: FakeModelInfo())
    monkeypatch.setattr(llm_utils, "get_model", lambda model_name, model_provider, api_keys=None: FakeLLM())

    result = call_llm(
        prompt="hello no fallback",
        pydantic_model=_FallbackSignal,
        agent_name="fallback_disabled_agent",
        state={
            "metadata": {
                "agent_llm_overrides": {
                    "fallback_disabled_agent": {
                        "model_name": "MiniMax-M2.7",
                        "model_provider": "MiniMax",
                        "api_keys": {},
                        "fallback_chain": [
                            {
                                "model_name": "doubao-seed-2.0-pro",
                                "model_provider": "Volcengine Ark",
                                "api_keys": {},
                                "status_message": "MiniMax limited, switching to Volcengine Ark:doubao-seed-2.0-pro",
                                "route_id": "Volcengine Ark:default",
                                "transport_family": "openai-compatible",
                            }
                        ],
                        "route_id": "MiniMax:default",
                        "transport_family": "openai-compatible",
                    }
                }
            }
        },
        max_retries=2,
    )

    paths = get_llm_metrics_paths()
    with open(paths["summary_path"], "r", encoding="utf-8") as handle:
        summary = __import__("json").load(handle)

    assert result.signal == "Error in analysis, using default"
    assert summary["totals"]["attempts"] == 2
    assert summary["totals"]["rate_limit_errors"] == 2
    assert summary["totals"]["fallback_attempts"] == 0
    assert "Volcengine Ark" not in summary["providers"]


def test_call_llm_ignores_metrics_recording_failures(monkeypatch):
    class FakeModelInfo:
        def has_json_mode(self):
            return True

    class FakeLLM:
        def with_structured_output(self, pydantic_model, method="json_mode"):
            return self

        def invoke(self, prompt):
            return _FallbackSignal(signal="ok")

    monkeypatch.setattr(llm_utils, "get_agent_model_config", lambda state, agent_name: ("MiniMax-M2.5", "MiniMax"))
    monkeypatch.setattr(llm_utils, "get_model_info", lambda model_name, model_provider: FakeModelInfo())
    monkeypatch.setattr(llm_utils, "get_model", lambda model_name, model_provider, api_keys=None: FakeLLM())
    monkeypatch.setattr(llm_utils, "record_llm_attempt", lambda **kwargs: (_ for _ in ()).throw(OSError("disk full")))

    result = call_llm(
        prompt="hello resilient metrics",
        pydantic_model=_FallbackSignal,
        agent_name="resilient_agent",
        state={"metadata": {}},
    )

    assert result.signal == "ok"


def test_provider_rate_limit_cooldown_waits_until_expiry(monkeypatch):
    current_time = {"value": 100.0}
    sleep_calls = []

    def fake_monotonic():
        return current_time["value"]

    def fake_sleep(seconds):
        sleep_calls.append(seconds)
        current_time["value"] += seconds

    monkeypatch.setattr(llm_utils.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(llm_utils.time, "sleep", fake_sleep)

    llm_utils._register_provider_rate_limit_cooldown("MiniMax", "MiniMax:default", 2.5)
    waited = llm_utils._wait_for_provider_rate_limit_cooldown("MiniMax", "MiniMax:default")

    assert waited == 2.5
    assert sleep_calls == [2.5]


def test_call_llm_reuses_provider_cooldown_for_rate_limit_retry(monkeypatch):
    current_time = {"value": 100.0}
    sleep_calls = []
    invoke_attempts = []

    class FakeModelInfo:
        def has_json_mode(self):
            return True

    class FakeLLM:
        def with_structured_output(self, pydantic_model, method="json_mode"):
            return self

        def invoke(self, prompt):
            invoke_attempts.append(prompt)
            if len(invoke_attempts) == 1:
                raise RuntimeError("429 rate limit")
            return _FallbackSignal(signal="ok")

    def fake_monotonic():
        return current_time["value"]

    def fake_sleep(seconds):
        sleep_calls.append(seconds)
        current_time["value"] += seconds

    monkeypatch.setattr(llm_utils, "get_model_info", lambda model_name, model_provider: FakeModelInfo())
    monkeypatch.setattr(llm_utils, "get_model", lambda model_name, model_provider, api_keys=None: FakeLLM())
    monkeypatch.setattr(llm_utils.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(llm_utils.time, "sleep", fake_sleep)

    result = call_llm(
        prompt="hello cooldown",
        pydantic_model=_FallbackSignal,
        agent_name="cooldown_agent",
        state={
            "metadata": {
                "agent_llm_overrides": {
                    "cooldown_agent": {
                        "model_name": "MiniMax-M2.7",
                        "model_provider": "MiniMax",
                        "api_keys": {},
                        "fallback_chain": [],
                        "route_id": "MiniMax:default",
                        "transport_family": "openai-compatible",
                    }
                }
            }
        },
        max_retries=2,
    )

    assert result.signal == "ok"
    assert len(invoke_attempts) == 2
    assert sleep_calls == [2.0]


def test_apply_priority_strategy_keeps_requested_primary_model_name(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-key")
    monkeypatch.setenv("MINIMAX_FALLBACK_MODEL", "MiniMax-M2.5")

    model_name, model_provider, api_keys, fallback_chain, route_id, transport_family = llm_utils._apply_priority_strategy(
        "MiniMax-M2.7",
        "MiniMax",
        None,
    )

    assert model_provider == "MiniMax"
    assert model_name == "MiniMax-M2.7"
    assert api_keys is not None
    assert api_keys["MINIMAX_API_KEY"] == "minimax-key"
    assert route_id == "MiniMax:default"
    assert transport_family == "openai-compatible"
    assert isinstance(fallback_chain, list)


def test_apply_priority_strategy_respects_global_provider_route_allowlist(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-key")
    monkeypatch.setenv("ZHIPU_API_KEY", "zhipu-key")
    monkeypatch.setenv("ARK_API_KEY", "ark-key")
    monkeypatch.setenv("LLM_PROVIDER_ROUTE_ALLOWLIST", "MiniMax")

    model_name, model_provider, api_keys, fallback_chain, route_id, transport_family = llm_utils._apply_priority_strategy(
        "MiniMax-M2.7",
        "MiniMax",
        None,
    )

    assert model_provider == "MiniMax"
    assert model_name == "MiniMax-M2.7"
    assert api_keys is not None
    assert api_keys["MINIMAX_API_KEY"] == "minimax-key"
    assert route_id == "MiniMax:default"
    assert transport_family == "openai-compatible"
    assert fallback_chain == []


def test_build_llm_skips_structured_output_for_unlisted_minimax_model(monkeypatch):
    calls = []

    class FakeLLM:
        def with_structured_output(self, pydantic_model, method="json_mode"):
            calls.append(("with_structured_output", method, pydantic_model.__name__))
            return self

    monkeypatch.setattr(llm_utils, "get_model", lambda model_name, model_provider, api_keys=None: FakeLLM())

    llm, model_info = llm_utils._build_llm("MiniMax-M2.7", "MiniMax", None, _FallbackSignal)

    assert llm is not None
    assert model_info is not None
    assert model_info.has_json_mode() is False
    assert calls == []


def test_build_llm_skips_structured_output_for_volcengine_non_json_model(monkeypatch):
    calls = []

    class FakeLLM:
        def with_structured_output(self, pydantic_model, method="json_mode"):
            calls.append(("with_structured_output", method, pydantic_model.__name__))
            return self

    monkeypatch.setattr(llm_utils, "get_model", lambda model_name, model_provider, api_keys=None: FakeLLM())

    llm, model_info = llm_utils._build_llm("doubao-seed-2.0-pro", "Volcengine", None, _FallbackSignal)

    assert llm is not None
    assert model_info is not None
    assert model_info.has_json_mode() is False
    assert calls == []
