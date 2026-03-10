from src.llm import models as llm_models


def test_provider_registry_exposes_default_profiles():
    registry = llm_models.get_provider_registry()

    assert "Zhipu" in registry
    assert "MiniMax" in registry
    assert "OpenRouter" in registry
    assert registry["Zhipu"].capabilities.supports_coding_plan is True
    assert registry["MiniMax"].capabilities.openai_compatible is True


def test_get_provider_routes_orders_registered_routes_by_priority(monkeypatch):
    monkeypatch.setenv("ZHIPU_CODE_API_KEY", "coding-key")
    monkeypatch.setenv("ZHIPU_API_KEY", "standard-key")
    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-key")

    routes = llm_models.get_provider_routes(api_keys=None, enabled_only_for="priority")

    assert [(route.provider_name, route.variant_name) for route in routes[:3]] == [
        ("Zhipu", "coding_plan"),
        ("MiniMax", "default"),
        ("Zhipu", "standard"),
    ]


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
