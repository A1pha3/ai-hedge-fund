import pytest

from src.llm import defaults as llm_defaults
from src.llm import models as llm_models


def test_provider_registry_exposes_default_profiles():
    registry = llm_models.get_provider_registry()

    assert "Zhipu" in registry
    assert "MiniMax" in registry
    assert "Volcengine" in registry
    assert "OpenRouter" in registry
    assert registry["Zhipu"].capabilities.supports_coding_plan is True
    assert registry["MiniMax"].capabilities.openai_compatible is True
    assert registry["Volcengine"].capabilities.openai_compatible is True


def test_get_provider_routes_orders_registered_routes_by_priority(monkeypatch):
    monkeypatch.setenv("ZHIPU_CODE_API_KEY", "coding-key")
    monkeypatch.setenv("ZHIPU_API_KEY", "standard-key")
    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-key")
    monkeypatch.setenv("ARK_API_KEY", "ark-key")

    routes = llm_models.get_provider_routes(api_keys=None, enabled_only_for="priority")

    assert [(route.provider_name, route.variant_name) for route in routes[:4]] == [
        ("MiniMax", "default"),
        ("Volcengine", "coding_plan"),
        ("Zhipu", "coding_plan"),
        ("Zhipu", "standard"),
    ]


def test_provider_primary_routes_use_primary_model_env_vars(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-key")
    monkeypatch.setenv("MINIMAX_MODEL", "MiniMax-M2.7")
    monkeypatch.setenv("ARK_API_KEY", "ark-key")
    monkeypatch.setenv("ARK_MODEL", "doubao-seed-2.0-pro")
    monkeypatch.setenv("ZHIPU_API_KEY", "standard-key")
    monkeypatch.setenv("ZHIPU_CODE_API_KEY", "coding-key")
    monkeypatch.setenv("ZHIPU_MODEL", "glm-4.7")
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "openai/gpt-4.1")

    minimax_route = llm_models.get_provider_primary_route("MiniMax", api_keys=None, enabled_only_for="priority")
    ark_route = llm_models.get_provider_primary_route("Volcengine", api_keys=None, enabled_only_for="priority")
    zhipu_coding_route = llm_models.get_provider_primary_route("Zhipu", api_keys={"ZHIPU_CODE_API_KEY": "coding-key"}, enabled_only_for="priority")
    openrouter_route = llm_models.get_provider_primary_route("OpenRouter", api_keys=None)

    assert minimax_route is not None
    assert minimax_route.model_name == "MiniMax-M2.7"
    assert ark_route is not None
    assert ark_route.model_name == "doubao-seed-2.0-pro"
    assert zhipu_coding_route is not None
    assert zhipu_coding_route.variant_name == "coding_plan"
    assert zhipu_coding_route.model_name == "glm-4.7"
    monkeypatch.delenv("ZHIPU_CODE_API_KEY")
    zhipu_standard_route = llm_models.get_provider_primary_route("Zhipu", api_keys={"ZHIPU_API_KEY": "standard-key"})
    assert zhipu_standard_route is not None
    assert zhipu_standard_route.variant_name == "standard"
    assert zhipu_standard_route.model_name == "glm-4.7"
    assert openrouter_route is not None
    assert openrouter_route.model_name == "openai/gpt-4.1"


def test_register_provider_profile_supports_new_registry_entries(monkeypatch):
    monkeypatch.setattr(llm_models, "_PROVIDER_REGISTRY", llm_models.get_provider_registry())

    llm_models.register_provider_profile(
        llm_models.ProviderProfile(
            name="Alpha Router",
            variants=(
                llm_models.ProviderVariantProfile(
                    variant_name="default",
                    display_name="Alpha Router",
                    api_key_names=("ALPHA_ROUTER_API_KEY",),
                    default_model_name="alpha-router-v1",
                    route_order=40,
                ),
            ),
            capabilities=llm_models.ProviderCapabilities(openai_compatible=True),
            enable_parallel_scheduler=True,
        )
    )

    route = llm_models.get_provider_primary_route("Alpha Router", {"ALPHA_ROUTER_API_KEY": "alpha-key"}, enabled_only_for="parallel")

    assert route is not None
    assert route.provider_name == "Alpha Router"
    assert route.model_name == "alpha-router-v1"
    assert llm_models.get_provider_concurrency_limit_env_var("Alpha Router") == "ALPHA_ROUTER_PROVIDER_CONCURRENCY_LIMIT"


def test_get_registered_provider_model_builds_openai_compatible_client(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm_models, "ChatOpenAI", FakeChatOpenAI)
    monkeypatch.setattr(llm_models, "_PROVIDER_REGISTRY", llm_models.get_provider_registry())

    llm_models.register_provider_profile(
        llm_models.ProviderProfile(
            name="Alpha Router",
            variants=(
                llm_models.ProviderVariantProfile(
                    variant_name="default",
                    display_name="Alpha Router",
                    api_key_names=("ALPHA_ROUTER_API_KEY",),
                    default_model_name="alpha-router-v1",
                    openai_compatible_transport=llm_models.OpenAICompatibleTransportConfig(
                        api_key_name="ALPHA_ROUTER_API_KEY",
                        base_url="https://alpha.example/v1",
                    ),
                    route_order=40,
                ),
            ),
            capabilities=llm_models.ProviderCapabilities(openai_compatible=True),
        )
    )

    llm_models.get_registered_provider_model("alpha-router-v2", "Alpha Router", {"ALPHA_ROUTER_API_KEY": "alpha-key"})

    assert captured == {
        "model": "alpha-router-v2",
        "api_key": "alpha-key",
        "base_url": "https://alpha.example/v1",
    }


def test_get_zhipu_model_uses_standard_key_when_only_standard_key_is_provided(monkeypatch):
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
        "model": "GLM-4.7",
        "api_key": "coding-key",
        "base_url": llm_models.ZHIPU_CODING_PLAN_BASE_URL,
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


def test_get_zhipu_model_explicit_api_keys_do_not_leak_env(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, model, api_key, base_url):
            captured["model"] = model
            captured["api_key"] = api_key
            captured["base_url"] = base_url

    monkeypatch.setattr(llm_models, "ChatOpenAI", FakeChatOpenAI)
    monkeypatch.setenv("ZHIPU_CODE_API_KEY", "env-coding-key")

    llm_models.get_zhipu_model("glm-4.7", {"ZHIPU_API_KEY": "standard-key"})

    assert captured == {
        "model": "glm-4.7",
        "api_key": "standard-key",
        "base_url": llm_models.ZHIPU_STANDARD_BASE_URL,
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


def test_get_registered_provider_model_builds_volcengine_client(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm_models, "ChatOpenAI", FakeChatOpenAI)

    llm_models.get_registered_provider_model("doubao-seed-2.0-code", "Volcengine", {"ARK_API_KEY": "ark-key"})

    assert captured == {
        "model": "doubao-seed-2.0-code",
        "api_key": "ark-key",
        "base_url": llm_models.VOLCENGINE_ARK_CODING_BASE_URL,
    }


def test_volcengine_doubao_model_disables_json_mode():
    model = llm_models.LLMModel(display_name="Doubao", model_name="doubao-seed-2.0-code", provider=llm_models.ModelProvider.VOLCENGINE)

    assert model.has_json_mode() is False


def test_default_model_config_requires_explicit_global_model_name(monkeypatch):
    monkeypatch.setenv("LLM_DEFAULT_MODEL_PROVIDER", "MiniMax")
    monkeypatch.delenv("LLM_DEFAULT_MODEL_NAME", raising=False)
    monkeypatch.delenv("BACKTEST_MODEL_NAME", raising=False)
    monkeypatch.setenv("MINIMAX_MODEL", "MiniMax-M2.7")

    with pytest.raises(llm_defaults.DefaultModelConfigurationError, match="默认模型配置不完整"):
        llm_defaults.get_default_model_config()


def test_default_model_config_prefers_explicit_global_model_name(monkeypatch):
    monkeypatch.setenv("LLM_DEFAULT_MODEL_PROVIDER", "MiniMax")
    monkeypatch.setenv("LLM_DEFAULT_MODEL_NAME", "MiniMax-M2.5")
    monkeypatch.setenv("MINIMAX_MODEL", "MiniMax-M2.7")

    model_name, model_provider = llm_defaults.get_default_model_config()

    assert model_provider == "MiniMax"
    assert model_name == "MiniMax-M2.5"
