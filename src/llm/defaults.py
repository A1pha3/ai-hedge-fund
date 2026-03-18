from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from src.llm.models import ModelProvider, get_provider_primary_route, get_provider_routes


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
_PROVIDER_MODEL_ENV_VARS: dict[str, tuple[str, ...]] = {
    ModelProvider.MINIMAX.value: ("MINIMAX_MODEL", "MINIMAX_FALLBACK_MODEL"),
    ModelProvider.ZHIPU.value: ("ZHIPU_MODEL", "ZHIPU_FALLBACK_MODEL", "ZHIPU_CODING_FALLBACK_MODEL"),
    ModelProvider.VOLCENGINE.value: ("ARK_MODEL", "ARK_FALLBACK_MODEL"),
    ModelProvider.OPENROUTER.value: ("OPENROUTER_MODEL", "OPENROUTER_FALLBACK_MODEL"),
    ModelProvider.OPENAI.value: ("OPENAI_MODEL",),
    ModelProvider.ANTHROPIC.value: ("ANTHROPIC_MODEL",),
    ModelProvider.DEEPSEEK.value: ("DEEPSEEK_MODEL",),
    ModelProvider.GOOGLE.value: ("GOOGLE_MODEL",),
    ModelProvider.XAI.value: ("XAI_MODEL",),
    ModelProvider.GROQ.value: ("GROQ_MODEL",),
    ModelProvider.GIGACHAT.value: ("GIGACHAT_MODEL",),
    ModelProvider.AZURE_OPENAI.value: ("AZURE_OPENAI_MODEL", "AZURE_OPENAI_DEPLOYMENT_NAME"),
    ModelProvider.OLLAMA.value: ("OLLAMA_MODEL",),
}
_BUILTIN_PROVIDER_DEFAULTS: dict[str, str] = {
    ModelProvider.OPENAI.value: "gpt-4.1",
    ModelProvider.ANTHROPIC.value: "claude-sonnet-4-5-20250929",
    ModelProvider.DEEPSEEK.value: "deepseek-chat",
    ModelProvider.GOOGLE.value: "gemini-3-pro-preview",
    ModelProvider.GROQ.value: "deepseek-chat",
    ModelProvider.GIGACHAT.value: "GigaChat-2-Max",
    ModelProvider.MINIMAX.value: "MiniMax-M2.5",
    ModelProvider.OPENROUTER.value: "openai/gpt-4.1-mini",
    ModelProvider.OLLAMA.value: "llama3",
    ModelProvider.XAI.value: "grok-4-0709",
    ModelProvider.ZHIPU.value: "glm-4.7",
    ModelProvider.VOLCENGINE.value: "doubao-seed-2.0-code",
    ModelProvider.AZURE_OPENAI.value: "",
}
_PROVIDER_ALIASES = {provider.value.lower(): provider.value for provider in ModelProvider}
_PROVIDER_ALIASES.update(
    {
        "azure": ModelProvider.AZURE_OPENAI.value,
        "azure-openai": ModelProvider.AZURE_OPENAI.value,
        "azure_openai": ModelProvider.AZURE_OPENAI.value,
        "openai": ModelProvider.OPENAI.value,
    }
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
    for names in _PROVIDER_MODEL_ENV_VARS.values():
        sentinel_names.update(names)

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


def get_default_model_provider() -> str:
    _ensure_default_env_loaded()
    env_provider = _read_env(*_MODEL_PROVIDER_ENV_VARS)
    if env_provider:
        return normalize_provider_name(env_provider)

    routes = get_provider_routes(None)
    if routes:
        return normalize_provider_name(routes[0].provider_name)

    return DEFAULT_MODEL_PROVIDER


def get_default_model_name(provider_name: str | None = None) -> str:
    _ensure_default_env_loaded()
    env_model_name = _read_env(*_MODEL_NAME_ENV_VARS)
    if env_model_name:
        return env_model_name

    resolved_provider = normalize_provider_name(provider_name or get_default_model_provider())
    provider_model_env_vars = _PROVIDER_MODEL_ENV_VARS.get(resolved_provider, ())
    provider_model_name = _read_env(*provider_model_env_vars)
    if provider_model_name:
        return provider_model_name

    route = get_provider_primary_route(resolved_provider, None)
    if route and route.model_name:
        return route.model_name

    return _BUILTIN_PROVIDER_DEFAULTS.get(resolved_provider, DEFAULT_MODEL_NAME)


def get_default_model_config() -> tuple[str, str]:
    model_provider = get_default_model_provider()
    model_name = get_default_model_name(model_provider)
    return model_name, model_provider


def resolve_model_selection(model_name: str | None, model_provider: str | None) -> tuple[str, str]:
    if bool(model_name) != bool(model_provider):
        raise ValueError("model_name 和 model_provider 需要同时提供，或者都不提供")

    if model_name and model_provider:
        return str(model_name), normalize_provider_name(model_provider)

    return get_default_model_config()