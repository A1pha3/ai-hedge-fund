from src.llm import models as llm_models
from src.main import _build_analyst_batches, _get_analyst_concurrency_limit, _order_selected_analysts
from src.utils import llm as llm_utils
from src.utils.llm import build_parallel_provider_execution_plan


def test_build_analyst_batches_respects_limit():
    batches = _build_analyst_batches(["a", "b", "c", "d", "e"], 2)

    assert batches == [["a", "b"], ["c", "d"], ["e"]]


def test_get_analyst_concurrency_limit_defaults_to_two(monkeypatch):
    monkeypatch.delenv("ANALYST_CONCURRENCY_LIMIT", raising=False)

    assert _get_analyst_concurrency_limit() == 2


def test_order_selected_analysts_uses_config_order():
    ordered = _order_selected_analysts(["warren_buffett", "ben_graham", "aswath_damodaran"])

    assert ordered == ["aswath_damodaran", "ben_graham", "warren_buffett"]


def test_build_parallel_provider_execution_plan_uses_dual_provider_wave(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-key")
    monkeypatch.setenv("ZHIPU_API_KEY", "zhipu-key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PRIMARY_PROVIDER", raising=False)
    monkeypatch.setenv("MINIMAX_PROVIDER_CONCURRENCY_LIMIT", "3")
    monkeypatch.setenv("ZHIPU_PROVIDER_CONCURRENCY_LIMIT", "3")

    plan = build_parallel_provider_execution_plan(
        agent_names=[f"agent_{index}" for index in range(1, 7)],
        base_model_name="glm-4.7",
        base_model_provider="Zhipu",
        api_keys=None,
        per_provider_limit=3,
    )

    overrides = plan["agent_llm_overrides"]
    providers = [overrides[f"agent_{index}"]["model_provider"] for index in range(1, 7)]

    assert plan["effective_concurrency_limit"] == 6
    assert plan["parallel_provider_count"] == 2
    assert providers.count("Zhipu") == 3
    assert providers.count("MiniMax") == 3


def test_build_parallel_provider_execution_plan_supports_weighted_provider_caps(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-key")
    monkeypatch.setenv("ZHIPU_API_KEY", "zhipu-key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.setenv("MINIMAX_PROVIDER_CONCURRENCY_LIMIT", "4")
    monkeypatch.setenv("ZHIPU_PROVIDER_CONCURRENCY_LIMIT", "2")

    plan = build_parallel_provider_execution_plan(
        agent_names=[f"agent_{index}" for index in range(1, 7)],
        base_model_name="glm-4.7",
        base_model_provider="Zhipu",
        api_keys=None,
        per_provider_limit=3,
    )

    overrides = plan["agent_llm_overrides"]
    providers = [overrides[f"agent_{index}"]["model_provider"] for index in range(1, 7)]

    assert plan["effective_concurrency_limit"] == 6
    assert providers.count("MiniMax") == 4
    assert providers.count("Zhipu") == 2
    assert providers[0] == "MiniMax"


def test_build_parallel_provider_execution_plan_supports_three_provider_wave(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-key")
    monkeypatch.setenv("ZHIPU_API_KEY", "zhipu-key")
    monkeypatch.setenv("ARK_API_KEY", "ark-key")
    monkeypatch.setenv("MINIMAX_PROVIDER_CONCURRENCY_LIMIT", "5")
    monkeypatch.setenv("VOLCENGINE_PROVIDER_CONCURRENCY_LIMIT", "3")
    monkeypatch.setenv("ZHIPU_PROVIDER_CONCURRENCY_LIMIT", "1")

    plan = build_parallel_provider_execution_plan(
        agent_names=[f"agent_{index}" for index in range(1, 10)],
        base_model_name="glm-4.7",
        base_model_provider="Zhipu",
        api_keys=None,
        per_provider_limit=3,
    )

    overrides = plan["agent_llm_overrides"]
    providers = [overrides[f"agent_{index}"]["model_provider"] for index in range(1, 10)]

    assert plan["effective_concurrency_limit"] == 9
    assert plan["parallel_provider_count"] == 3
    assert providers.count("MiniMax") == 5
    assert providers.count("Volcengine") == 3
    assert providers.count("Zhipu") == 1


def test_build_parallel_provider_execution_plan_supports_provider_allowlist(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-key")
    monkeypatch.setenv("ZHIPU_API_KEY", "zhipu-key")
    monkeypatch.setenv("ARK_API_KEY", "ark-key")
    monkeypatch.setenv("MINIMAX_PROVIDER_CONCURRENCY_LIMIT", "5")
    monkeypatch.setenv("VOLCENGINE_PROVIDER_CONCURRENCY_LIMIT", "3")
    monkeypatch.setenv("ZHIPU_PROVIDER_CONCURRENCY_LIMIT", "1")
    monkeypatch.setenv("LLM_PRIMARY_PROVIDER", "MiniMax")
    monkeypatch.setenv("LLM_PARALLEL_PROVIDER_ALLOWLIST", "MiniMax,Volcengine")

    plan = build_parallel_provider_execution_plan(
        agent_names=[f"agent_{index}" for index in range(1, 9)],
        base_model_name="glm-4.7",
        base_model_provider="Zhipu",
        api_keys=None,
        per_provider_limit=3,
    )

    overrides = plan["agent_llm_overrides"]
    providers = [overrides[f"agent_{index}"]["model_provider"] for index in range(1, 9)]

    assert plan["effective_concurrency_limit"] == 8
    assert plan["parallel_provider_count"] == 2
    assert providers.count("MiniMax") == 5
    assert providers.count("Volcengine") == 3
    assert "Zhipu" not in providers


def test_build_parallel_provider_execution_plan_keeps_single_provider_when_key_missing(monkeypatch):
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.setenv("ZHIPU_API_KEY", "zhipu-key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    plan = build_parallel_provider_execution_plan(
        agent_names=["agent_1", "agent_2"],
        base_model_name="glm-4.7",
        base_model_provider="Zhipu",
        api_keys=None,
        per_provider_limit=3,
    )

    assert plan["effective_concurrency_limit"] == 3
    assert plan["parallel_provider_count"] == 1
    assert plan["agent_llm_overrides"] == {}


def test_build_parallel_provider_execution_plan_respects_global_provider_route_allowlist(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-key")
    monkeypatch.setenv("ZHIPU_API_KEY", "zhipu-key")
    monkeypatch.setenv("ARK_API_KEY", "ark-key")
    monkeypatch.setenv("LLM_PROVIDER_ROUTE_ALLOWLIST", "MiniMax")

    plan = build_parallel_provider_execution_plan(
        agent_names=[f"agent_{index}" for index in range(1, 5)],
        base_model_name="MiniMax-M2.7",
        base_model_provider="MiniMax",
        api_keys=None,
        per_provider_limit=3,
    )

    assert plan["effective_concurrency_limit"] == 3
    assert plan["parallel_provider_count"] == 1
    assert plan["agent_llm_overrides"] == {}


def test_build_parallel_provider_execution_plan_supports_generic_registered_providers(monkeypatch):
    fake_routes = [
        llm_models.ProviderRoute(
            provider_name="Alpha",
            variant_name="primary",
            display_name="Alpha",
            model_name="alpha-fallback",
            api_keys={"ALPHA_API_KEY": "alpha-key"},
            route_order=10,
            capabilities=llm_models.ProviderCapabilities(openai_compatible=True),
        ),
        llm_models.ProviderRoute(
            provider_name="Beta",
            variant_name="primary",
            display_name="Beta",
            model_name="beta-fallback",
            api_keys={"BETA_API_KEY": "beta-key"},
            route_order=20,
            capabilities=llm_models.ProviderCapabilities(openai_compatible=True),
        ),
    ]

    monkeypatch.setattr(llm_utils, "get_provider_routes", lambda api_keys, enabled_only_for=None: fake_routes)
    monkeypatch.setattr(llm_utils, "get_provider_concurrency_limit_env_var", lambda provider_name: f"{provider_name.upper()}_PROVIDER_CONCURRENCY_LIMIT")

    plan = build_parallel_provider_execution_plan(
        agent_names=[f"agent_{index}" for index in range(1, 5)],
        base_model_name="alpha-primary",
        base_model_provider="Alpha",
        api_keys=None,
        per_provider_limit=1,
    )

    overrides = plan["agent_llm_overrides"]

    assert plan["effective_concurrency_limit"] == 2
    assert plan["parallel_provider_count"] == 2
    assert [overrides[f"agent_{index}"]["model_provider"] for index in range(1, 5)] == ["Alpha", "Beta", "Alpha", "Beta"]
    assert overrides["agent_1"]["model_name"] == "alpha-primary"
    assert overrides["agent_2"]["model_name"] == "beta-fallback"
