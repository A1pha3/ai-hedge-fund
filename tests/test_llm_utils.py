from pydantic import BaseModel

from src.utils import llm as llm_utils
from src.utils.llm import call_llm, extract_json_from_response


class _FallbackSignal(BaseModel):
    signal: str


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
            return _FallbackSignal(signal="ok")

    monkeypatch.setenv("ZHIPU_API_KEY", "test-key")
    monkeypatch.setenv("ZHIPU_CODE_API_KEY", "coding-key")
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
