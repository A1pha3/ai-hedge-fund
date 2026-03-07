from src.llm import models as llm_models


def test_get_zhipu_model_uses_standard_key_by_default(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, model, api_key, base_url):
            captured["model"] = model
            captured["api_key"] = api_key
            captured["base_url"] = base_url

    monkeypatch.setattr(llm_models, "ChatOpenAI", FakeChatOpenAI)

    llm_models.get_zhipu_model("glm-4.7", {"ZHIPU_API_KEY": "standard-key"})

    assert captured == {
        "model": "glm-4.7",
        "api_key": "standard-key",
        "base_url": llm_models.ZHIPU_STANDARD_BASE_URL,
    }


def test_get_zhipu_model_prefers_standard_key_when_both_keys_present(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, model, api_key, base_url):
            captured["model"] = model
            captured["api_key"] = api_key
            captured["base_url"] = base_url

    monkeypatch.setattr(llm_models, "ChatOpenAI", FakeChatOpenAI)

    llm_models.get_zhipu_model("glm-4.7", {"ZHIPU_API_KEY": "standard-key", "ZHIPU_CODE_API_KEY": "coding-key"})

    assert captured == {
        "model": "glm-4.7",
        "api_key": "standard-key",
        "base_url": llm_models.ZHIPU_STANDARD_BASE_URL,
    }


def test_get_zhipu_model_uses_coding_plan_when_code_key_present(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, model, api_key, base_url):
            captured["model"] = model
            captured["api_key"] = api_key
            captured["base_url"] = base_url

    monkeypatch.setattr(llm_models, "ChatOpenAI", FakeChatOpenAI)
    monkeypatch.delenv("ZHIPU_API_KEY", raising=False)

    llm_models.get_zhipu_model("glm-4.7", {"ZHIPU_CODE_API_KEY": "coding-key"})

    assert captured == {
        "model": "GLM-4.7",
        "api_key": "coding-key",
        "base_url": llm_models.ZHIPU_CODING_PLAN_BASE_URL,
    }


def test_get_zhipu_model_uses_coding_plan_when_explicitly_requested(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, model, api_key, base_url):
            captured["model"] = model
            captured["api_key"] = api_key
            captured["base_url"] = base_url

    monkeypatch.setattr(llm_models, "ChatOpenAI", FakeChatOpenAI)

    llm_models.get_zhipu_model("glm-4.7", {"ZHIPU_API_KEY": "standard-key", "ZHIPU_CODE_API_KEY": "coding-key", "ZHIPU_USE_CODING_PLAN": True})

    assert captured == {
        "model": "GLM-4.7",
        "api_key": "coding-key",
        "base_url": llm_models.ZHIPU_CODING_PLAN_BASE_URL,
    }


def test_get_zhipu_coding_plan_model_keeps_glm5_lowercase(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, model, api_key, base_url):
            captured["model"] = model
            captured["api_key"] = api_key
            captured["base_url"] = base_url

    monkeypatch.setattr(llm_models, "ChatOpenAI", FakeChatOpenAI)

    llm_models.get_zhipu_coding_plan_model("glm-5", {"ZHIPU_CODE_API_KEY": "coding-key"})

    assert captured == {
        "model": "glm-5",
        "api_key": "coding-key",
        "base_url": llm_models.ZHIPU_CODING_PLAN_BASE_URL,
    }
