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
    # Clear LLM_PROVIDER_ROUTE_ALLOWLIST so the operator's real .env value does not leak in via
    # load_project_dotenv() on import and silently filter the expected 4-route ordering.
    monkeypatch.delenv("LLM_PROVIDER_ROUTE_ALLOWLIST", raising=False)
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


def test_get_provider_routes_respects_global_provider_route_allowlist(monkeypatch):
    monkeypatch.setenv("ZHIPU_CODE_API_KEY", "coding-key")
    monkeypatch.setenv("ZHIPU_API_KEY", "standard-key")
    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-key")
    monkeypatch.setenv("ARK_API_KEY", "ark-key")
    monkeypatch.setenv("LLM_PROVIDER_ROUTE_ALLOWLIST", "MiniMax")

    routes = llm_models.get_provider_routes(api_keys=None, enabled_only_for="priority")

    assert routes
    assert {route.provider_name for route in routes} == {"MiniMax"}
    assert llm_models.get_provider_primary_route("Zhipu", api_keys=None, enabled_only_for="priority") is None
    assert llm_models.get_provider_primary_route("MiniMax", api_keys=None, enabled_only_for="priority") is not None


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

    monkeypatch.setattr(llm_models, "ChatOpenAI", FakeChatOpenAI, raising=False)
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
        "timeout": 60.0,
    }


def test_get_registered_provider_model_applies_openai_compatible_timeout_env(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm_models, "ChatOpenAI", FakeChatOpenAI, raising=False)
    monkeypatch.setenv("LLM_OPENAI_COMPATIBLE_TIMEOUT_SECONDS", "42.5")
    monkeypatch.setattr(llm_models, "_PROVIDER_REGISTRY", llm_models.get_provider_registry())

    llm_models.register_provider_profile(
        llm_models.ProviderProfile(
            name="Alpha Router Timeout",
            variants=(
                llm_models.ProviderVariantProfile(
                    variant_name="default",
                    display_name="Alpha Router Timeout",
                    api_key_names=("ALPHA_ROUTER_TIMEOUT_API_KEY",),
                    default_model_name="alpha-router-timeout-v1",
                    openai_compatible_transport=llm_models.OpenAICompatibleTransportConfig(
                        api_key_name="ALPHA_ROUTER_TIMEOUT_API_KEY",
                        base_url="https://alpha-timeout.example/v1",
                    ),
                    route_order=41,
                ),
            ),
            capabilities=llm_models.ProviderCapabilities(openai_compatible=True),
        )
    )

    llm_models.get_registered_provider_model("alpha-router-timeout-v2", "Alpha Router Timeout", {"ALPHA_ROUTER_TIMEOUT_API_KEY": "alpha-timeout-key"})

    assert captured == {
        "model": "alpha-router-timeout-v2",
        "api_key": "alpha-timeout-key",
        "base_url": "https://alpha-timeout.example/v1",
        "timeout": 42.5,
    }


def test_get_registered_provider_model_applies_default_openai_compatible_timeout(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm_models, "ChatOpenAI", FakeChatOpenAI, raising=False)
    monkeypatch.delenv("LLM_OPENAI_COMPATIBLE_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setattr(llm_models, "_PROVIDER_REGISTRY", llm_models.get_provider_registry())

    llm_models.register_provider_profile(
        llm_models.ProviderProfile(
            name="Alpha Router Default Timeout",
            variants=(
                llm_models.ProviderVariantProfile(
                    variant_name="default",
                    display_name="Alpha Router Default Timeout",
                    api_key_names=("ALPHA_ROUTER_DEFAULT_TIMEOUT_API_KEY",),
                    default_model_name="alpha-router-default-timeout-v1",
                    openai_compatible_transport=llm_models.OpenAICompatibleTransportConfig(
                        api_key_name="ALPHA_ROUTER_DEFAULT_TIMEOUT_API_KEY",
                        base_url="https://alpha-default-timeout.example/v1",
                    ),
                    route_order=42,
                ),
            ),
            capabilities=llm_models.ProviderCapabilities(openai_compatible=True),
        )
    )

    llm_models.get_registered_provider_model(
        "alpha-router-default-timeout-v2",
        "Alpha Router Default Timeout",
        {"ALPHA_ROUTER_DEFAULT_TIMEOUT_API_KEY": "alpha-default-timeout-key"},
    )

    assert captured == {
        "model": "alpha-router-default-timeout-v2",
        "api_key": "alpha-default-timeout-key",
        "base_url": "https://alpha-default-timeout.example/v1",
        "timeout": 60.0,
    }


def test_get_zhipu_model_uses_standard_key_when_only_standard_key_is_provided(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm_models, "ChatOpenAI", FakeChatOpenAI, raising=False)

    llm_models.get_zhipu_model("glm-4.7", {"ZHIPU_API_KEY": "standard-key"})

    assert captured == {
        "model": "glm-4.7",
        "api_key": "standard-key",
        "base_url": llm_models.ZHIPU_STANDARD_BASE_URL,
        "timeout": 60.0,
    }


def test_get_zhipu_model_prefers_standard_key_when_both_keys_present(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm_models, "ChatOpenAI", FakeChatOpenAI, raising=False)

    llm_models.get_zhipu_model("glm-4.7", {"ZHIPU_API_KEY": "standard-key", "ZHIPU_CODE_API_KEY": "coding-key"})

    assert captured == {
        "model": "GLM-4.7",
        "api_key": "coding-key",
        "base_url": llm_models.ZHIPU_CODING_PLAN_BASE_URL,
        "timeout": 60.0,
    }


def test_get_zhipu_model_uses_coding_plan_when_code_key_present(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm_models, "ChatOpenAI", FakeChatOpenAI, raising=False)
    monkeypatch.delenv("ZHIPU_API_KEY", raising=False)

    llm_models.get_zhipu_model("glm-4.7", {"ZHIPU_CODE_API_KEY": "coding-key"})

    assert captured == {
        "model": "GLM-4.7",
        "api_key": "coding-key",
        "base_url": llm_models.ZHIPU_CODING_PLAN_BASE_URL,
        "timeout": 60.0,
    }


def test_get_zhipu_model_uses_coding_plan_when_explicitly_requested(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm_models, "ChatOpenAI", FakeChatOpenAI, raising=False)

    llm_models.get_zhipu_model("glm-4.7", {"ZHIPU_API_KEY": "standard-key", "ZHIPU_CODE_API_KEY": "coding-key", "ZHIPU_USE_CODING_PLAN": True})

    assert captured == {
        "model": "GLM-4.7",
        "api_key": "coding-key",
        "base_url": llm_models.ZHIPU_CODING_PLAN_BASE_URL,
        "timeout": 60.0,
    }


def test_get_zhipu_model_explicit_api_keys_do_not_leak_env(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm_models, "ChatOpenAI", FakeChatOpenAI, raising=False)
    monkeypatch.setenv("ZHIPU_CODE_API_KEY", "env-coding-key")

    llm_models.get_zhipu_model("glm-4.7", {"ZHIPU_API_KEY": "standard-key"})

    assert captured == {
        "model": "glm-4.7",
        "api_key": "standard-key",
        "base_url": llm_models.ZHIPU_STANDARD_BASE_URL,
        "timeout": 60.0,
    }


def test_get_zhipu_coding_plan_model_keeps_glm5_lowercase(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm_models, "ChatOpenAI", FakeChatOpenAI, raising=False)

    llm_models.get_zhipu_coding_plan_model("glm-5", {"ZHIPU_CODE_API_KEY": "coding-key"})

    assert captured == {
        "model": "glm-5",
        "api_key": "coding-key",
        "base_url": llm_models.ZHIPU_CODING_PLAN_BASE_URL,
        "timeout": 60.0,
    }


def test_get_registered_provider_model_builds_volcengine_client(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm_models, "ChatOpenAI", FakeChatOpenAI, raising=False)

    llm_models.get_registered_provider_model("doubao-seed-2.0-code", "Volcengine", {"ARK_API_KEY": "ark-key"})

    assert captured == {
        "model": "doubao-seed-2.0-code",
        "api_key": "ark-key",
        "base_url": llm_models.VOLCENGINE_ARK_CODING_BASE_URL,
        "timeout": 60.0,
    }


def test_load_models_from_json_builds_typed_models(tmp_path):
    json_path = tmp_path / "models.json"
    json_path.write_text('[{"display_name":"Demo","model_name":"demo-1","provider":"OpenAI"}]')

    models = llm_models.load_models_from_json(str(json_path))

    assert len(models) == 1
    assert models[0].display_name == "Demo"
    assert models[0].provider == llm_models.ModelProvider.OPENAI


def test_get_model_info_builds_fallback_model_for_known_provider():
    result = llm_models.get_model_info("custom-model", "OpenAI")

    assert result is not None
    assert result.display_name == "custom-model"
    assert result.model_name == "custom-model"
    assert result.provider == llm_models.ModelProvider.OPENAI


def test_get_models_list_uses_available_models_contract():
    result = llm_models.get_models_list()

    assert result
    assert {"display_name", "model_name", "provider"} <= set(result[0].keys())


def test_volcengine_doubao_model_disables_json_mode():
    model = llm_models.LLMModel(display_name="Doubao", model_name="doubao-seed-2.0-code", provider=llm_models.ModelProvider.VOLCENGINE)

    assert model.has_json_mode() is False


def test_get_model_builds_openai_client_with_env_base_url(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm_models, "ChatOpenAI", FakeChatOpenAI, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("OPENAI_API_BASE", "https://openai.example/v1")

    llm_models.get_model("gpt-4.1", llm_models.ModelProvider.OPENAI)

    assert captured["model"] == "gpt-4.1"
    assert captured["api_key"] == "openai-key"
    assert captured["base_url"] == "https://openai.example/v1"


def test_get_model_returns_registered_minimax_route(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(llm_models, "get_registered_provider_model", lambda model_name, model_provider, api_keys=None: sentinel)

    model = llm_models.get_model("MiniMax-M2.5", llm_models.ModelProvider.MINIMAX, {"MINIMAX_API_KEY": "minimax-key"})

    assert model is sentinel


def test_default_model_config_requires_explicit_global_model_name(monkeypatch):
    monkeypatch.setenv("LLM_DEFAULT_MODEL_PROVIDER", "MiniMax")
    monkeypatch.delenv("LLM_DEFAULT_MODEL_NAME", raising=False)
    monkeypatch.delenv("BACKTEST_MODEL_NAME", raising=False)
    monkeypatch.setenv("MINIMAX_MODEL", "MiniMax-M2.7")
    # Prevent .env from re-populating LLM_DEFAULT_MODEL_NAME after we deleted it
    monkeypatch.setattr(llm_defaults, "_ensure_default_env_loaded", lambda: None)

    with pytest.raises(llm_defaults.DefaultModelConfigurationError, match="默认模型配置不完整"):
        llm_defaults.get_default_model_config()


def test_default_model_config_prefers_explicit_global_model_name(monkeypatch):
    monkeypatch.setenv("LLM_DEFAULT_MODEL_PROVIDER", "MiniMax")
    monkeypatch.setenv("LLM_DEFAULT_MODEL_NAME", "MiniMax-M2.5")
    monkeypatch.setenv("MINIMAX_MODEL", "MiniMax-M2.7")

    model_name, model_provider = llm_defaults.get_default_model_config()

    assert model_provider == "MiniMax"
    assert model_name == "MiniMax-M2.5"


# ---------------------------------------------------------------------------
# autodev-21 / loop 119: import-isolation — front doors must not crash when a
# single langchain provider package is absent. Previously models.py imported
# all 8 langchain_* packages at module top level, so a missing langchain_xai
# (or any one of them) crashed `from src.main import run_top` even though the
# --top / --custom-weights front doors never call an LLM. Mirror of loop 118
# (fpdf) but systemic across the LLM provider surface.
# ---------------------------------------------------------------------------


def test_models_module_importable_when_one_langchain_provider_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``src.llm.models`` 必须在任一 langchain provider 包缺失时仍可导入 —
    ``ModelProvider`` enum / ``LLMModel`` / ``load_models_from_json`` 等纯辅助
    不依赖任何 langchain 运行时类; 只有真正构建 client 的函数 (get_model /
    _build_native_provider_model 等) 才需要。顶层导入全部 8 个 provider 让
    ``--top`` / ``--custom-weights`` 前门在单个 provider 缺失/升级 break 时
    整体崩溃 (dogfood 20260706 loop 119: 模拟 langchain_xai 缺失即崩)。"""
    import builtins
    import importlib
    import sys

    real_import = builtins.__import__

    def _block_xai(name: str, *args, **kwargs):
        if name == "langchain_xai" or name.startswith("langchain_xai."):
            raise ImportError("simulated langchain_xai not installed (loop-119 isolation test)")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block_xai)
    for mod in list(sys.modules):
        if mod == "langchain_xai" or mod.startswith("langchain_xai."):
            monkeypatch.delitem(sys.modules, mod, raising=False)
    monkeypatch.delitem(sys.modules, "src.llm.models", raising=False)

    fresh = importlib.import_module("src.llm.models")
    # Pure symbols must remain available without the xai provider package.
    assert hasattr(fresh, "ModelProvider")
    assert hasattr(fresh, "LLMModel")
    assert hasattr(fresh, "load_models_from_json")
    assert fresh.ModelProvider.XAI.value == "xAI"


def test_front_door_importable_when_one_langchain_provider_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``run_top_picks`` / ``run_top`` / ``run_custom_weights`` 前门在单个
    langchain provider 缺失时必须仍可导入 — 这些前门运行时不调用任何 LLM,
    仅因 ``src.main`` 顶层 ``from src.llm.defaults import ...`` 被传递性拖垮。
    """
    import builtins
    import importlib
    import sys

    real_import = builtins.__import__

    def _block_xai(name: str, *args, **kwargs):
        if name == "langchain_xai" or name.startswith("langchain_xai."):
            raise ImportError("simulated langchain_xai not installed (loop-119 isolation test)")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block_xai)
    for mod in list(sys.modules):
        if mod == "langchain_xai" or mod.startswith("langchain_xai."):
            monkeypatch.delitem(sys.modules, mod, raising=False)
    # Force re-import of the polluted chain.
    for mod in list(sys.modules):
        if mod in ("src.main", "src.llm.models", "src.llm.defaults") or mod.startswith("src.llm."):
            monkeypatch.delitem(sys.modules, mod, raising=False)

    fresh_main = importlib.import_module("src.main")
    assert hasattr(fresh_main, "run_top")
    assert hasattr(fresh_main, "run_custom_weights")
    fresh_top_picks = importlib.import_module("src.screening.top_picks")
    assert hasattr(fresh_top_picks, "run_top_picks")


def test_front_doors_do_not_pull_agent_modules_at_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """autodev-21 / loop 120: ``--top`` / ``--custom-weights`` / ``--top-picks``
    前门运行时不调用任何 LLM agent (agents 只在 ``--pipeline`` 全流水线模式
    使用)。此前 ``src/main.py`` 顶层 ``from src.agents.portfolio_manager
    import ...`` + ``from src.graph.state import AgentState`` 把全部 41 个
    agent/graph 模块在 import 时拉入 — 前门因此被 agent 依赖的 langchain_core
    及传递性重依赖绑架 (dogfood 20260706 loop 120: 前门 import 拉入
    src.agents.* / src.graph.state 共 41 个模块)。

    修复后 (loop 120): agent/graph import 延迟到 ``create_workflow`` 内,
    前门 import 不应触达 ``src.agents`` 或 ``src.graph.state``。
    """
    import importlib
    import sys

    for mod in list(sys.modules):
        if mod.startswith("src.main") or mod.startswith("src.screening.top_picks") or mod.startswith("src.agents") or mod.startswith("src.graph"):
            monkeypatch.delitem(sys.modules, mod, raising=False)

    fresh_main = importlib.import_module("src.main")
    importlib.import_module("src.screening.top_picks")

    pulled = [m for m in sys.modules if m.startswith("src.agents") or m == "src.graph.state"]
    # Tolerate src.agents package __init__ if it's a pure namespace, but the
    # concrete agent modules (warren_buffett, risk_manager, etc.) and graph.state
    # must NOT be loaded by a front-door import.
    concrete_agents = [m for m in pulled if m not in ("src.agents",)]
    assert not concrete_agents, (
        f"front-door import pulled {len(concrete_agents)} agent/graph modules "
        f"(should be 0 for --top/--custom-weights which never call agents): "
        f"{concrete_agents[:5]}..."
    )
