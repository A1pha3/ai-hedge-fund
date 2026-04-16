from __future__ import annotations

import os
from typing import Any
from collections.abc import Callable


def build_openai_family_model_impl(
    *,
    model_name: str,
    provider_name: str,
    api_keys: dict[str, Any] | None,
    build_openai_compatible_model_fn: Callable,
    openai_transport_config_cls,
    get_required_api_key_fn: Callable[[dict | None, str, str], str],
    azure_chat_openai_cls,
):
    if provider_name == "OpenAI":
        return build_openai_compatible_model_fn(
            model_name,
            openai_transport_config_cls(api_key_name="OPENAI_API_KEY", base_url=os.getenv("OPENAI_API_BASE")),
            {"OPENAI_API_KEY": get_required_api_key_fn(api_keys, "OPENAI_API_KEY", "OpenAI")},
        )

    if provider_name != "Azure OpenAI":
        return None

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

    return azure_chat_openai_cls(
        azure_endpoint=azure_endpoint,
        azure_deployment=azure_deployment_name,
        api_key=api_key,
        api_version="2024-10-21",
    )


def build_registered_route_model_impl(
    *,
    model_name: str,
    provider_name: str,
    api_keys: dict[str, Any] | None,
    get_registered_provider_model_fn: Callable,
    get_zhipu_model_fn: Callable,
):
    registered_model = get_registered_provider_model_fn(model_name, provider_name, api_keys)

    if provider_name == "OpenRouter":
        if registered_model is None:
            raise ValueError("OpenRouter route is not available. Please make sure OPENROUTER_API_KEY is set.")
        return registered_model

    if provider_name == "MiniMax":
        if registered_model is None:
            raise ValueError("MiniMax route is not available. Please make sure MINIMAX_API_KEY is set.")
        return registered_model

    if provider_name == "Zhipu":
        return registered_model or get_zhipu_model_fn(model_name, api_keys)

    return registered_model
