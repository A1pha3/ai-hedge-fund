import os
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any
from collections.abc import Callable

from langchain_anthropic import ChatAnthropic
from langchain_deepseek import ChatDeepSeek
from langchain_gigachat import GigaChat
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama
from langchain_openai import AzureChatOpenAI, ChatOpenAI
from langchain_xai import ChatXAI
from pydantic import BaseModel

from src.llm.model_catalog_helpers import (
    build_fallback_model_info,
    build_llm_models,
    build_model_list_payload,
    find_model_in_catalog,
    load_model_records_from_json,
)
from src.llm.model_builder_helpers import build_openai_family_model_impl, build_registered_route_model_impl
from src.llm.provider_registry_defaults import build_default_provider_profile_specs
from src.llm.provider_route_helpers import (
    collect_provider_routes,
    get_provider_route_allowlist,
    resolve_api_key,
    resolve_provider_route_impl,
)
from src.llm.zhipu_model_helpers import resolve_zhipu_route_inputs, should_route_zhipu_to_coding_plan


class ModelProvider(StrEnum):
    """Enum for supported LLM providers"""

    ALIBABA = "Alibaba"
    ANTHROPIC = "Anthropic"
    DEEPSEEK = "DeepSeek"
    GOOGLE = "Google"
    GROQ = "Groq"
    META = "Meta"
    MISTRAL = "Mistral"
    OPENAI = "OpenAI"
    OLLAMA = "Ollama"
    OPENROUTER = "OpenRouter"
    GIGACHAT = "GigaChat"
    AZURE_OPENAI = "Azure OpenAI"
    XAI = "xAI"
    ZHIPU = "Zhipu"
    MINIMAX = "MiniMax"
    VOLCENGINE = "Volcengine"


class LLMModel(BaseModel):
    """Represents an LLM model configuration"""

    display_name: str
    model_name: str
    provider: ModelProvider

    def to_choice_tuple(self) -> tuple[str, str, str]:
        """Convert to format needed for questionary choices"""
        return (self.display_name, self.model_name, self.provider.value)

    def is_custom(self) -> bool:
        """Check if the model is a Gemini model"""
        return self.model_name == "-"

    def has_json_mode(self) -> bool:
        """Check if the model supports JSON mode"""
        if self.is_deepseek() or self.is_gemini() or self.is_minimax() or self.is_volcengine_non_json_mode():
            return False
        # Only certain Ollama models support JSON mode
        if self.is_ollama():
            return "llama3" in self.model_name or "neural-chat" in self.model_name
        # OpenRouter models generally support JSON mode
        if self.provider == ModelProvider.OPENROUTER:
            return True
        return True

    def is_deepseek(self) -> bool:
        """Check if the model is a DeepSeek model"""
        return self.model_name.startswith("deepseek")

    def is_gemini(self) -> bool:
        """Check if the model is a Gemini model"""
        return self.model_name.startswith("gemini")

    def is_ollama(self) -> bool:
        """Check if the model is an Ollama model"""
        return self.provider == ModelProvider.OLLAMA

    def is_minimax(self) -> bool:
        """Check if the model is a MiniMax model"""
        return self.provider == ModelProvider.MINIMAX or self.model_name.lower().startswith("minimax")

    def is_volcengine_non_json_mode(self) -> bool:
        """Doubao coding models on Ark Coding Plan do not support response_format=json_object."""
        lowered = self.model_name.lower()
        return self.provider == ModelProvider.VOLCENGINE and lowered in {"doubao-seed-2.0-code", "doubao-seed-2.0-pro", "ark-code-latest"}


# Load models from JSON file
def load_models_from_json(json_path: str) -> list[LLMModel]:
    """Load models from a JSON file"""
    return build_llm_models(load_model_records_from_json(json_path), LLMModel, ModelProvider)


# Get the path to the JSON files
current_dir = Path(__file__).parent
models_json_path = current_dir / "api_models.json"
ollama_models_json_path = current_dir / "ollama_models.json"

# Load available models from JSON
AVAILABLE_MODELS = load_models_from_json(str(models_json_path))

# Load Ollama models from JSON
OLLAMA_MODELS = load_models_from_json(str(ollama_models_json_path))

# Create LLM_ORDER in the format expected by the UI
LLM_ORDER = [model.to_choice_tuple() for model in AVAILABLE_MODELS]

# Create Ollama LLM_ORDER separately
OLLAMA_LLM_ORDER = [model.to_choice_tuple() for model in OLLAMA_MODELS]

ZHIPU_STANDARD_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
ZHIPU_CODING_PLAN_BASE_URL = "https://open.bigmodel.cn/api/coding/paas/v4"
VOLCENGINE_ARK_CODING_BASE_URL = "https://ark.cn-beijing.volces.com/api/coding/v3"


@dataclass(frozen=True)
class ProviderCapabilities:
    """Static capability flags that describe a provider family."""

    supports_json_mode: bool | None = None
    supports_coding_plan: bool = False
    openai_compatible: bool = False


@dataclass(frozen=True)
class ProviderVariantProfile:
    """Describes one routable variant for a provider."""

    variant_name: str
    display_name: str
    api_key_names: tuple[str, ...]
    default_model_name: str
    model_env_var: str | None = None
    extra_api_keys: dict[str, Any] = field(default_factory=dict)
    openai_compatible_transport: "OpenAICompatibleTransportConfig | None" = None
    route_order: int = 0


@dataclass(frozen=True)
class OpenAICompatibleTransportConfig:
    """Configuration for providers that expose an OpenAI-compatible API surface."""

    api_key_name: str
    base_url: str | None = None
    base_url_env_var: str | None = None
    api_key_kwarg: str = "api_key"
    base_url_kwarg: str = "base_url"
    static_model_kwargs: dict[str, Any] = field(default_factory=dict)
    dynamic_model_kwargs_factory: Callable[[], dict[str, Any]] | None = None
    model_name_transform: Callable[[str], str] | None = None


@dataclass(frozen=True)
class ProviderRoute:
    """Resolved provider route with concrete keys and model metadata."""

    provider_name: str
    variant_name: str
    display_name: str
    model_name: str
    api_keys: dict[str, Any]
    route_order: int
    capabilities: ProviderCapabilities
    openai_compatible_transport: OpenAICompatibleTransportConfig | None = None

    @property
    def route_id(self) -> str:
        return f"{self.provider_name}:{self.variant_name}"

    @property
    def transport_family(self) -> str:
        return "openai-compatible" if self.capabilities.openai_compatible else "native"

    def to_execution_config(self, *, status_message: str, model_name: str | None = None) -> dict[str, Any]:
        return {
            "model_name": model_name or self.model_name,
            "model_provider": self.provider_name,
            "api_keys": dict(self.api_keys),
            "status_message": status_message,
            "route_id": self.route_id,
            "transport_family": self.transport_family,
        }


@dataclass(frozen=True)
class ProviderProfile:
    """Registry entry used by the shared multi-provider router."""

    name: str
    variants: tuple[ProviderVariantProfile, ...]
    capabilities: ProviderCapabilities = field(default_factory=ProviderCapabilities)
    concurrency_limit_env_var: str | None = None
    default_parallel_limit: int = 1
    enable_priority_routing: bool = False
    enable_parallel_scheduler: bool = False


def _resolve_api_key(api_keys: dict | None, key_name: str) -> Any:
    return resolve_api_key(api_keys, key_name)


def _resolve_provider_route(profile: ProviderProfile, variant: ProviderVariantProfile, api_keys: dict | None) -> ProviderRoute | None:
    return resolve_provider_route_impl(
        profile=profile,
        variant=variant,
        api_keys=api_keys,
        resolve_api_key_fn=_resolve_api_key,
        provider_route_cls=ProviderRoute,
    )


def _default_concurrency_env_var(provider_name: str) -> str:
    normalized = provider_name.upper().replace(" ", "_")
    return f"{normalized}_PROVIDER_CONCURRENCY_LIMIT"


def _get_provider_route_allowlist() -> set[str] | None:
    """Returns an optional global allowlist for routable providers."""
    return get_provider_route_allowlist()


_PROVIDER_REGISTRY: dict[str, ProviderProfile] = {}


def register_provider_profile(profile: ProviderProfile) -> None:
    """Registers or replaces a provider routing profile."""
    _PROVIDER_REGISTRY[profile.name] = profile


def get_provider_profile(provider_name: str) -> ProviderProfile | None:
    """Returns a provider routing profile when registered."""
    return _PROVIDER_REGISTRY.get(str(provider_name))


def get_provider_registry() -> dict[str, ProviderProfile]:
    """Returns a shallow copy of the registered provider profiles."""
    return dict(_PROVIDER_REGISTRY)


def get_provider_routes(api_keys: dict | None, *, enabled_only_for: str | None = None) -> list[ProviderRoute]:
    """Returns all available provider routes ordered by routing priority."""
    return collect_provider_routes(
        registry=_PROVIDER_REGISTRY,
        api_keys=api_keys,
        enabled_only_for=enabled_only_for,
        provider_allowlist=_get_provider_route_allowlist(),
        resolve_provider_route_fn=_resolve_provider_route,
    )


def get_provider_primary_route(provider_name: str, api_keys: dict | None, *, enabled_only_for: str | None = None) -> ProviderRoute | None:
    """Returns the highest-priority available route for a provider."""
    candidate_routes = [route for route in get_provider_routes(api_keys, enabled_only_for=enabled_only_for) if route.provider_name == str(provider_name)]
    return candidate_routes[0] if candidate_routes else None


def get_provider_concurrency_limit_env_var(provider_name: str) -> str:
    """Returns the env var used for the provider's soft concurrency limit."""
    profile = get_provider_profile(provider_name)
    if profile and profile.concurrency_limit_env_var:
        return profile.concurrency_limit_env_var
    return _default_concurrency_env_var(str(provider_name))


def _build_openai_transport_config(spec: dict[str, Any] | None) -> OpenAICompatibleTransportConfig | None:
    if not spec:
        return None
    return OpenAICompatibleTransportConfig(**spec)


def _build_provider_variant_profile(spec: dict[str, Any]) -> ProviderVariantProfile:
    variant_spec = dict(spec)
    transport_spec = variant_spec.pop("openai_compatible_transport", None)
    return ProviderVariantProfile(
        **variant_spec,
        openai_compatible_transport=_build_openai_transport_config(transport_spec),
    )


def _build_provider_profile(spec: dict[str, Any]) -> ProviderProfile:
    profile_spec = dict(spec)
    capability_spec = profile_spec.pop("capabilities", {})
    variant_specs = profile_spec.pop("variants")
    return ProviderProfile(
        **profile_spec,
        variants=tuple(_build_provider_variant_profile(variant_spec) for variant_spec in variant_specs),
        capabilities=ProviderCapabilities(**capability_spec),
    )


def _get_default_provider_profiles() -> list[ProviderProfile]:
    specs = build_default_provider_profile_specs(
        zhipu_standard_base_url=ZHIPU_STANDARD_BASE_URL,
        zhipu_coding_plan_base_url=ZHIPU_CODING_PLAN_BASE_URL,
        volcengine_ark_coding_base_url=VOLCENGINE_ARK_CODING_BASE_URL,
        normalize_zhipu_coding_plan_model_name=_normalize_zhipu_coding_plan_model_name,
    )
    return [_build_provider_profile(spec) for spec in specs]


def _register_default_provider_profiles() -> None:
    for profile in _get_default_provider_profiles():
        register_provider_profile(profile)


def _normalize_zhipu_coding_plan_model_name(model_name: str) -> str:
    """Normalize coding-plan model ids to the names expected by Zhipu tools docs."""
    lowered = model_name.lower()
    if lowered.startswith("glm-4."):
        return model_name.upper()
    return model_name


def _resolve_openai_compatible_model_kwargs(config: OpenAICompatibleTransportConfig) -> dict[str, Any]:
    model_kwargs = dict(config.static_model_kwargs)
    if config.dynamic_model_kwargs_factory:
        model_kwargs.update(config.dynamic_model_kwargs_factory())
    return model_kwargs


def build_openai_compatible_model(model_name: str, config: OpenAICompatibleTransportConfig, api_keys: dict | None = None) -> ChatOpenAI:
    """Builds a ChatOpenAI-compatible client from transport config."""
    api_key = (api_keys or {}).get(config.api_key_name) or os.getenv(config.api_key_name)
    if not api_key:
        print(f"API Key Error: Please make sure {config.api_key_name} is set in your .env file or provided via API keys.")
        raise ValueError(f"{config.api_key_name} not found. Please make sure it is set in your .env file or provided via API keys.")

    normalized_model_name = config.model_name_transform(model_name) if config.model_name_transform else model_name
    base_url = os.getenv(config.base_url_env_var, config.base_url) if config.base_url_env_var else config.base_url

    kwargs: dict[str, Any] = {"model": normalized_model_name, config.api_key_kwarg: api_key}
    if base_url:
        kwargs[config.base_url_kwarg] = base_url

    model_kwargs = _resolve_openai_compatible_model_kwargs(config)
    if model_kwargs:
        kwargs["model_kwargs"] = model_kwargs

    return ChatOpenAI(**kwargs)


def get_registered_provider_model(model_name: str, model_provider: str, api_keys: dict | None = None):
    """Builds a model client from the provider registry when transport config is registered."""
    route = get_provider_primary_route(str(model_provider), api_keys)
    if not route or not route.openai_compatible_transport:
        return None
    return build_openai_compatible_model(model_name, route.openai_compatible_transport, route.api_keys)


_register_default_provider_profiles()


def get_zhipu_coding_plan_model(model_name: str, api_keys: dict | None = None) -> ChatOpenAI:
    """Build a Zhipu Coding Plan client using the dedicated coding endpoint."""
    route = get_provider_primary_route("Zhipu", api_keys)
    if not route or route.variant_name != "coding_plan" or not route.openai_compatible_transport:
        raise ValueError("Zhipu Coding Plan route is not available. Please make sure ZHIPU_CODE_API_KEY is set.")
    return build_openai_compatible_model(model_name, route.openai_compatible_transport, route.api_keys)


def get_zhipu_model(model_name: str, api_keys: dict | None = None) -> ChatOpenAI:
    """Build a Zhipu client, routing to Coding Plan when a dedicated key is intended."""
    standard_api_key, coding_api_key, prefer_coding_plan = resolve_zhipu_route_inputs(api_keys)
    if should_route_zhipu_to_coding_plan(coding_api_key, prefer_coding_plan):
        return get_zhipu_coding_plan_model(model_name, api_keys)

    if not standard_api_key:
        print("API Key Error: Please make sure ZHIPU_API_KEY is set in your .env file or provided via API keys.")
        raise ValueError("Zhipu API key not found. Please make sure ZHIPU_API_KEY is set in your .env file or provided via API keys.")

    return build_openai_compatible_model(
        model_name,
        OpenAICompatibleTransportConfig(api_key_name="ZHIPU_API_KEY", base_url=ZHIPU_STANDARD_BASE_URL, base_url_env_var="ZHIPU_API_BASE"),
        {"ZHIPU_API_KEY": standard_api_key},
    )


def get_model_info(model_name: str, model_provider: str) -> LLMModel | None:
    """Get model information by model_name"""
    all_models = AVAILABLE_MODELS + OLLAMA_MODELS
    matched_model = find_model_in_catalog(all_models, model_name, model_provider)
    if matched_model:
        return matched_model
    return build_fallback_model_info(model_name, model_provider, ModelProvider, LLMModel)


def find_model_by_name(model_name: str) -> LLMModel | None:
    """Find a model by its name across all available models."""
    all_models = AVAILABLE_MODELS + OLLAMA_MODELS
    return find_model_in_catalog(all_models, model_name)


def get_models_list():
    """Get the list of models for API responses."""
    return build_model_list_payload(AVAILABLE_MODELS)


def _get_required_api_key(api_keys: dict | None, key_name: str, provider_label: str) -> str:
    api_key = (api_keys or {}).get(key_name) or os.getenv(key_name)
    if not api_key:
        print(f"API Key Error: Please make sure {key_name} is set in your .env file or provided via API keys.")
        raise ValueError(f"{provider_label} API key not found. Please make sure {key_name} is set in your .env file or provided via API keys.")
    return api_key


def _build_native_provider_model(model_name: str, model_provider: ModelProvider, api_keys: dict | None = None):
    if model_provider == ModelProvider.GROQ:
        return ChatGroq(model=model_name, api_key=_get_required_api_key(api_keys, "GROQ_API_KEY", "Groq"))
    if model_provider == ModelProvider.ANTHROPIC:
        return ChatAnthropic(model=model_name, api_key=_get_required_api_key(api_keys, "ANTHROPIC_API_KEY", "Anthropic"))
    if model_provider == ModelProvider.DEEPSEEK:
        return ChatDeepSeek(model=model_name, api_key=_get_required_api_key(api_keys, "DEEPSEEK_API_KEY", "DeepSeek"))
    if model_provider == ModelProvider.GOOGLE:
        return ChatGoogleGenerativeAI(model=model_name, api_key=_get_required_api_key(api_keys, "GOOGLE_API_KEY", "Google"))
    if model_provider == ModelProvider.XAI:
        return ChatXAI(model=model_name, api_key=_get_required_api_key(api_keys, "XAI_API_KEY", "xAI"))
    return None


def _build_openai_family_model(model_name: str, model_provider: ModelProvider, api_keys: dict | None = None):
    provider_name = model_provider.value if hasattr(model_provider, "value") else str(model_provider)
    return build_openai_family_model_impl(
        model_name=model_name,
        provider_name=provider_name,
        api_keys=api_keys,
        build_openai_compatible_model_fn=build_openai_compatible_model,
        openai_transport_config_cls=OpenAICompatibleTransportConfig,
        get_required_api_key_fn=_get_required_api_key,
        azure_chat_openai_cls=AzureChatOpenAI,
    )


def _build_registered_route_model(model_name: str, model_provider: ModelProvider, provider_value: str, api_keys: dict | None = None):
    return build_registered_route_model_impl(
        model_name=model_name,
        provider_name=provider_value,
        api_keys=api_keys,
        get_registered_provider_model_fn=get_registered_provider_model,
        get_zhipu_model_fn=get_zhipu_model,
    )


def _build_ollama_or_gigachat_model(model_name: str, model_provider: ModelProvider, api_keys: dict | None = None):
    if model_provider == ModelProvider.OLLAMA:
        ollama_host = os.getenv("OLLAMA_HOST", "localhost")
        return ChatOllama(model=model_name, base_url=os.getenv("OLLAMA_BASE_URL", f"http://{ollama_host}:11434"))
    if model_provider == ModelProvider.GIGACHAT:
        if os.getenv("GIGACHAT_USER") or os.getenv("GIGACHAT_PASSWORD"):
            return GigaChat(model=model_name)
        api_key = (api_keys or {}).get("GIGACHAT_API_KEY") or os.getenv("GIGACHAT_API_KEY") or os.getenv("GIGACHAT_CREDENTIALS")
        if not api_key:
            print("API Key Error: Please make sure api_keys is set in your .env file or provided via API keys.")
            raise ValueError("GigaChat API key not found. Please make sure GIGACHAT_API_KEY is set in your .env file or provided via API keys.")
        return GigaChat(credentials=api_key, model=model_name)
    return None


def get_model(model_name: str, model_provider: ModelProvider, api_keys: dict | None = None) -> ChatOpenAI | ChatGroq | ChatOllama | GigaChat | None:
    provider_value = model_provider.value if hasattr(model_provider, "value") else str(model_provider)
    for builder in (_build_native_provider_model, _build_openai_family_model, _build_ollama_or_gigachat_model):
        model = builder(model_name, model_provider, api_keys)
        if model is not None:
            return model
    return _build_registered_route_model(model_name, model_provider, provider_value, api_keys)
