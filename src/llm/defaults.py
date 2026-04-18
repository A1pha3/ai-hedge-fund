from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from src.llm.models import ModelProvider


DEFAULT_MODEL_NAME = "gpt-4.1"
DEFAULT_MODEL_PROVIDER = ModelProvider.OPENAI.value

_MODEL_NAME_ENV_VARS = ("LLM_DEFAULT_MODEL_NAME", "BACKTEST_MODEL_NAME")
_MODEL_PROVIDER_ENV_VARS = ("LLM_DEFAULT_MODEL_PROVIDER", "BACKTEST_MODEL_PROVIDER")
_API_KEY_ENV_VARS = (
    "MINIMAX_API_KEY",
    "ZHIPU_API_KEY",
    "ZHIPU_CODE_API_KEY",
    "ARK_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
)
_PROVIDER_ALIASES = {provider.value.lower(): provider.value for provider in ModelProvider}
_PROVIDER_ALIASES.update(
    {
        "azure": ModelProvider.AZURE_OPENAI.value,
        "azure-openai": ModelProvider.AZURE_OPENAI.value,
        "azure_openai": ModelProvider.AZURE_OPENAI.value,
        "openai": ModelProvider.OPENAI.value,
    }
)


class DefaultModelConfigurationError(ValueError):
    """Raised when the default LLM model configuration is missing or ambiguous."""


def _build_missing_default_model_message() -> str:
    return (
        "默认模型必须显式配置。请同时设置 LLM_DEFAULT_MODEL_PROVIDER 与 LLM_DEFAULT_MODEL_NAME，"
        "或同时设置 BACKTEST_MODEL_PROVIDER 与 BACKTEST_MODEL_NAME。为避免静默降级，"
        "系统不再从 MINIMAX_MODEL、MINIMAX_FALLBACK_MODEL 等 provider 变量推断默认模型。"
    )


def _read_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value is not None:
            normalized = value.strip()
            if normalized:
                return normalized
    return None


def _ensure_default_env_loaded() -> None:
    sentinel_names = set(_MODEL_NAME_ENV_VARS + _MODEL_PROVIDER_ENV_VARS)

    if os.getenv("PYTEST_CURRENT_TEST"):
        sentinel_names.update(_API_KEY_ENV_VARS)

    if any(os.getenv(name) for name in sentinel_names):
        return

    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)


def normalize_provider_name(provider_name: str | None) -> str:
    if provider_name is None:
        return DEFAULT_MODEL_PROVIDER
    normalized = str(provider_name).strip()
    if not normalized:
        return DEFAULT_MODEL_PROVIDER
    return _PROVIDER_ALIASES.get(normalized.lower(), normalized)


def get_default_model_config() -> tuple[str, str]:
    _ensure_default_env_loaded()
    env_model_name = _read_env(*_MODEL_NAME_ENV_VARS)
    env_provider = _read_env(*_MODEL_PROVIDER_ENV_VARS)

    if not env_model_name and not env_provider:
        raise DefaultModelConfigurationError(_build_missing_default_model_message())

    if bool(env_model_name) != bool(env_provider):
        raise DefaultModelConfigurationError(
            "默认模型配置不完整。LLM_DEFAULT_MODEL_PROVIDER 与 LLM_DEFAULT_MODEL_NAME "
            "或 BACKTEST_MODEL_PROVIDER 与 BACKTEST_MODEL_NAME 必须成对出现。"
        )

    return env_model_name or DEFAULT_MODEL_NAME, normalize_provider_name(env_provider or DEFAULT_MODEL_PROVIDER)


def resolve_model_selection(model_name: str | None, model_provider: str | None) -> tuple[str, str]:
    if bool(model_name) != bool(model_provider):
        raise ValueError("model_name 和 model_provider 需要同时提供，或者都不提供")

    if model_name and model_provider:
        return str(model_name), normalize_provider_name(model_provider)

    return get_default_model_config()