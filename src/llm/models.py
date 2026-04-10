import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, List, Tuple

from langchain_anthropic import ChatAnthropic
from langchain_deepseek import ChatDeepSeek
from langchain_gigachat import GigaChat
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama
from langchain_openai import AzureChatOpenAI, ChatOpenAI
from langchain_xai import ChatXAI
from pydantic import BaseModel


class ModelProvider(str, Enum):
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

    def to_choice_tuple(self) -> Tuple[str, str, str]:
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
def load_models_from_json(json_path: str) -> List[LLMModel]:
    """Load models from a JSON file"""
    with open(json_path, "r") as f:
        models_data = json.load(f)

    models = []
    for model_data in models_data:
        # Convert string provider to ModelProvider enum
        provider_enum = ModelProvider(model_data["provider"])
        models.append(LLMModel(display_name=model_data["display_name"], model_name=model_data["model_name"], provider=provider_enum))
    return models


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
    return (api_keys or {}).get(key_name) or os.getenv(key_name)


def _resolve_provider_route(profile: ProviderProfile, variant: ProviderVariantProfile, api_keys: dict | None) -> ProviderRoute | None:
    resolved_api_keys: dict[str, Any] = {}
    for api_key_name in variant.api_key_names:
        api_key_value = _resolve_api_key(api_keys, api_key_name)
        if not api_key_value:
            return None
        resolved_api_keys[api_key_name] = api_key_value

    resolved_api_keys.update(variant.extra_api_keys)
    model_name = os.getenv(variant.model_env_var, variant.default_model_name) if variant.model_env_var else variant.default_model_name

    return ProviderRoute(
        provider_name=profile.name,
        variant_name=variant.variant_name,
        display_name=variant.display_name,
        model_name=model_name,
        api_keys=resolved_api_keys,
        route_order=variant.route_order,
        capabilities=profile.capabilities,
        openai_compatible_transport=variant.openai_compatible_transport,
    )


def _default_concurrency_env_var(provider_name: str) -> str:
    normalized = provider_name.upper().replace(" ", "_")
    return f"{normalized}_PROVIDER_CONCURRENCY_LIMIT"


def _get_provider_route_allowlist() -> set[str] | None:
    """Returns an optional global allowlist for routable providers."""
    raw_value = os.getenv("LLM_PROVIDER_ROUTE_ALLOWLIST", "").strip()
    if not raw_value:
        return None

    providers = {item.strip().lower() for item in raw_value.split(",") if item.strip()}
    return providers or None


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
    routes: list[ProviderRoute] = []
    provider_allowlist = _get_provider_route_allowlist()

    for profile in _PROVIDER_REGISTRY.values():
        if provider_allowlist and profile.name.lower() not in provider_allowlist:
            continue
        if enabled_only_for == "parallel" and not profile.enable_parallel_scheduler:
            continue
        if enabled_only_for == "priority" and not profile.enable_priority_routing:
            continue

        for variant in profile.variants:
            route = _resolve_provider_route(profile, variant, api_keys)
            if route:
                routes.append(route)

    return sorted(routes, key=lambda route: (route.route_order, route.provider_name, route.variant_name))


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


def _register_default_provider_profiles() -> None:
    register_provider_profile(
        ProviderProfile(
            name="Zhipu",
            variants=(
                ProviderVariantProfile(
                    variant_name="coding_plan",
                    display_name="Coding Plan Zhipu",
                    api_key_names=("ZHIPU_CODE_API_KEY",),
                    default_model_name="glm-4.7",
                    model_env_var="ZHIPU_MODEL",
                    extra_api_keys={"ZHIPU_USE_CODING_PLAN": True},
                    openai_compatible_transport=OpenAICompatibleTransportConfig(
                        api_key_name="ZHIPU_CODE_API_KEY",
                        base_url=ZHIPU_CODING_PLAN_BASE_URL,
                        base_url_env_var="ZHIPU_CODING_API_BASE",
                        model_name_transform=_normalize_zhipu_coding_plan_model_name,
                    ),
                    route_order=30,
                ),
                ProviderVariantProfile(
                    variant_name="standard",
                    display_name="standard Zhipu",
                    api_key_names=("ZHIPU_API_KEY",),
                    default_model_name="glm-4.7",
                    model_env_var="ZHIPU_MODEL",
                    openai_compatible_transport=OpenAICompatibleTransportConfig(
                        api_key_name="ZHIPU_API_KEY",
                        base_url=ZHIPU_STANDARD_BASE_URL,
                        base_url_env_var="ZHIPU_API_BASE",
                    ),
                    route_order=40,
                ),
            ),
            capabilities=ProviderCapabilities(supports_json_mode=True, supports_coding_plan=True, openai_compatible=True),
            concurrency_limit_env_var="ZHIPU_PROVIDER_CONCURRENCY_LIMIT",
            default_parallel_limit=1,
            enable_priority_routing=True,
            enable_parallel_scheduler=True,
        )
    )
    register_provider_profile(
        ProviderProfile(
            name="MiniMax",
            variants=(
                ProviderVariantProfile(
                    variant_name="default",
                    display_name="MiniMax",
                    api_key_names=("MINIMAX_API_KEY",),
                    default_model_name="MiniMax-M2.5",
                    model_env_var="MINIMAX_MODEL",
                    openai_compatible_transport=OpenAICompatibleTransportConfig(
                        api_key_name="MINIMAX_API_KEY",
                        base_url="https://api.minimaxi.com/v1",
                    ),
                    route_order=10,
                ),
            ),
            capabilities=ProviderCapabilities(supports_json_mode=False, openai_compatible=True),
            concurrency_limit_env_var="MINIMAX_PROVIDER_CONCURRENCY_LIMIT",
            default_parallel_limit=1,
            enable_priority_routing=True,
            enable_parallel_scheduler=True,
        )
    )
    register_provider_profile(
        ProviderProfile(
            name="Volcengine",
            variants=(
                ProviderVariantProfile(
                    variant_name="coding_plan",
                    display_name="Volcengine Ark",
                    api_key_names=("ARK_API_KEY",),
                    default_model_name="doubao-seed-2.0-code",
                    model_env_var="ARK_MODEL",
                    openai_compatible_transport=OpenAICompatibleTransportConfig(
                        api_key_name="ARK_API_KEY",
                        base_url=VOLCENGINE_ARK_CODING_BASE_URL,
                        base_url_env_var="ARK_API_BASE",
                    ),
                    route_order=20,
                ),
            ),
            capabilities=ProviderCapabilities(supports_json_mode=True, supports_coding_plan=True, openai_compatible=True),
            concurrency_limit_env_var="VOLCENGINE_PROVIDER_CONCURRENCY_LIMIT",
            default_parallel_limit=1,
            enable_priority_routing=True,
            enable_parallel_scheduler=True,
        )
    )
    register_provider_profile(
        ProviderProfile(
            name="OpenRouter",
            variants=(
                ProviderVariantProfile(
                    variant_name="default",
                    display_name="OpenRouter",
                    api_key_names=("OPENROUTER_API_KEY",),
                    default_model_name="openai/gpt-4.1-mini",
                    model_env_var="OPENROUTER_MODEL",
                    openai_compatible_transport=OpenAICompatibleTransportConfig(
                        api_key_name="OPENROUTER_API_KEY",
                        base_url="https://openrouter.ai/api/v1",
                        base_url_kwarg="openai_api_base",
                        api_key_kwarg="openai_api_key",
                        dynamic_model_kwargs_factory=lambda: {
                            "extra_headers": {
                                "HTTP-Referer": os.getenv("YOUR_SITE_URL", "https://github.com/virattt/ai-hedge-fund"),
                                "X-Title": os.getenv("YOUR_SITE_NAME", "AI Hedge Fund"),
                            }
                        },
                    ),
                    route_order=40,
                ),
            ),
            capabilities=ProviderCapabilities(supports_json_mode=True, openai_compatible=True),
            enable_priority_routing=False,
            enable_parallel_scheduler=False,
        )
    )


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
    if api_keys is None:
        standard_api_key = os.getenv("ZHIPU_API_KEY")
        coding_api_key = os.getenv("ZHIPU_CODE_API_KEY")
        prefer_coding_plan = os.getenv("ZHIPU_USE_CODING_PLAN", "").lower() in {"1", "true", "yes"}
    else:
        standard_api_key = api_keys.get("ZHIPU_API_KEY")
        coding_api_key = api_keys.get("ZHIPU_CODE_API_KEY")
        prefer_coding_plan = bool(api_keys.get("ZHIPU_USE_CODING_PLAN"))

    if coding_api_key:
        prefer_coding_plan = True

    if prefer_coding_plan:
        return get_zhipu_coding_plan_model(model_name, api_keys)

    api_key = standard_api_key
    if not api_key:
        print("API Key Error: Please make sure ZHIPU_API_KEY is set in your .env file or provided via API keys.")
        raise ValueError("Zhipu API key not found. Please make sure ZHIPU_API_KEY is set in your .env file or provided via API keys.")

    return build_openai_compatible_model(
        model_name,
        OpenAICompatibleTransportConfig(api_key_name="ZHIPU_API_KEY", base_url=ZHIPU_STANDARD_BASE_URL, base_url_env_var="ZHIPU_API_BASE"),
        {"ZHIPU_API_KEY": api_key},
    )


def get_model_info(model_name: str, model_provider: str) -> LLMModel | None:
    """Get model information by model_name"""
    all_models = AVAILABLE_MODELS + OLLAMA_MODELS
    matched_model = next((model for model in all_models if model.model_name == model_name and model.provider == model_provider), None)
    if matched_model:
        return matched_model

    try:
        provider_enum = model_provider if isinstance(model_provider, ModelProvider) else ModelProvider(str(model_provider))
    except ValueError:
        return None

    return LLMModel(display_name=str(model_name), model_name=str(model_name), provider=provider_enum)


def find_model_by_name(model_name: str) -> LLMModel | None:
    """Find a model by its name across all available models."""
    all_models = AVAILABLE_MODELS + OLLAMA_MODELS
    return next((model for model in all_models if model.model_name == model_name), None)


def get_models_list():
    """Get the list of models for API responses."""
    return [{"display_name": model.display_name, "model_name": model.model_name, "provider": model.provider.value} for model in AVAILABLE_MODELS]


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
    if model_provider == ModelProvider.OPENAI:
        return build_openai_compatible_model(
            model_name,
            OpenAICompatibleTransportConfig(api_key_name="OPENAI_API_KEY", base_url=os.getenv("OPENAI_API_BASE")),
            {"OPENAI_API_KEY": _get_required_api_key(api_keys, "OPENAI_API_KEY", "OpenAI")},
        )
    if model_provider == ModelProvider.AZURE_OPENAI:
        api_key = os.getenv("AZURE_OPENAI_API_KEY")
        if not api_key:
            print("API Key Error: Please make sure AZURE_OPENAI_API_KEY is set in your .env file.")
            raise ValueError("Azure OpenAI API key not found.  Please make sure AZURE_OPENAI_API_KEY is set in your .env file.")
        azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        if not azure_endpoint:
            print("Azure Endpoint Error: Please make sure AZURE_OPENAI_ENDPOINT is set in your .env file.")
            raise ValueError("Azure OpenAI endpoint not found.  Please make sure AZURE_OPENAI_ENDPOINT is set in your .env file.")
        azure_deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
        if not azure_deployment_name:
            print("Azure Deployment Name Error: Please make sure AZURE_OPENAI_DEPLOYMENT_NAME is set in your .env file.")
            raise ValueError("Azure OpenAI deployment name not found.  Please make sure AZURE_OPENAI_DEPLOYMENT_NAME is set in your .env file.")
        return AzureChatOpenAI(azure_endpoint=azure_endpoint, azure_deployment=azure_deployment_name, api_key=api_key, api_version="2024-10-21")
    return None


def _build_registered_route_model(model_name: str, model_provider: ModelProvider, provider_value: str, api_keys: dict | None = None):
    if model_provider == ModelProvider.OPENROUTER:
        registered_model = get_registered_provider_model(model_name, provider_value, api_keys)
        if registered_model is None:
            raise ValueError("OpenRouter route is not available. Please make sure OPENROUTER_API_KEY is set.")
        return registered_model
    if model_provider == ModelProvider.MINIMAX:
        registered_model = get_registered_provider_model(model_name, provider_value, api_keys)
        if registered_model is None:
            raise ValueError("MiniMax route is not available. Please make sure MINIMAX_API_KEY is set.")
        return registered_model
    if model_provider == ModelProvider.ZHIPU:
        registered_model = get_registered_provider_model(model_name, provider_value, api_keys)
        return registered_model or get_zhipu_model(model_name, api_keys)
    registered_model = get_registered_provider_model(model_name, provider_value, api_keys)
    if registered_model is not None:
        return registered_model
    return None


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


def get_model(model_name: str, model_provider: ModelProvider, api_keys: dict = None) -> ChatOpenAI | ChatGroq | ChatOllama | GigaChat | None:
    provider_value = model_provider.value if hasattr(model_provider, "value") else str(model_provider)
    for builder in (_build_native_provider_model, _build_openai_family_model, _build_ollama_or_gigachat_model):
        model = builder(model_name, model_provider, api_keys)
        if model is not None:
            return model
    return _build_registered_route_model(model_name, model_provider, provider_value, api_keys)
