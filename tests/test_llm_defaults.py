import pytest

from src.llm import defaults as llm_defaults


def _clear_default_model_env(monkeypatch):
    for env_name in (
        "LLM_DEFAULT_MODEL_PROVIDER",
        "LLM_DEFAULT_MODEL_NAME",
        "BACKTEST_MODEL_PROVIDER",
        "BACKTEST_MODEL_NAME",
        "MINIMAX_MODEL",
        "MINIMAX_FALLBACK_MODEL",
        "ZHIPU_MODEL",
        "ZHIPU_FALLBACK_MODEL",
        "ZHIPU_CODING_FALLBACK_MODEL",
        "ARK_MODEL",
        "ARK_FALLBACK_MODEL",
        "OPENROUTER_MODEL",
        "OPENROUTER_FALLBACK_MODEL",
    ):
        monkeypatch.delenv(env_name, raising=False)


def test_get_default_model_config_requires_explicit_pair(monkeypatch):
    _clear_default_model_env(monkeypatch)
    monkeypatch.setattr(llm_defaults, "load_dotenv", lambda *args, **kwargs: None)

    with pytest.raises(llm_defaults.DefaultModelConfigurationError, match="默认模型必须显式配置"):
        llm_defaults.get_default_model_config()


def test_get_default_model_config_rejects_partial_pair(monkeypatch):
    _clear_default_model_env(monkeypatch)
    monkeypatch.setattr(llm_defaults, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("LLM_DEFAULT_MODEL_PROVIDER", "MiniMax")

    with pytest.raises(llm_defaults.DefaultModelConfigurationError, match="默认模型配置不完整"):
        llm_defaults.get_default_model_config()


def test_get_default_model_config_ignores_provider_specific_model_fallbacks(monkeypatch):
    _clear_default_model_env(monkeypatch)
    monkeypatch.setattr(llm_defaults, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("MINIMAX_MODEL", "MiniMax-M2.7")
    monkeypatch.setenv("MINIMAX_FALLBACK_MODEL", "MiniMax-M2.5")

    with pytest.raises(llm_defaults.DefaultModelConfigurationError, match="默认模型必须显式配置"):
        llm_defaults.get_default_model_config()


def test_get_default_model_config_accepts_explicit_backtest_pair(monkeypatch):
    _clear_default_model_env(monkeypatch)
    monkeypatch.setattr(llm_defaults, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("BACKTEST_MODEL_PROVIDER", "MiniMax")
    monkeypatch.setenv("BACKTEST_MODEL_NAME", "MiniMax-M2.7")

    assert llm_defaults.get_default_model_config() == ("MiniMax-M2.7", "MiniMax")