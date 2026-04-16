from __future__ import annotations

import os
from typing import Any
from collections.abc import Callable


def _build_openrouter_model_kwargs() -> dict[str, Any]:
    return {
        "extra_headers": {
            "HTTP-Referer": os.getenv("YOUR_SITE_URL", "https://github.com/virattt/ai-hedge-fund"),
            "X-Title": os.getenv("YOUR_SITE_NAME", "AI Hedge Fund"),
        }
    }


def build_default_provider_profile_specs(
    *,
    zhipu_standard_base_url: str,
    zhipu_coding_plan_base_url: str,
    volcengine_ark_coding_base_url: str,
    normalize_zhipu_coding_plan_model_name: Callable[[str], str],
) -> list[dict[str, Any]]:
    return [
        {
            "name": "Zhipu",
            "variants": [
                {
                    "variant_name": "coding_plan",
                    "display_name": "Coding Plan Zhipu",
                    "api_key_names": ("ZHIPU_CODE_API_KEY",),
                    "default_model_name": "glm-4.7",
                    "model_env_var": "ZHIPU_MODEL",
                    "extra_api_keys": {"ZHIPU_USE_CODING_PLAN": True},
                    "openai_compatible_transport": {
                        "api_key_name": "ZHIPU_CODE_API_KEY",
                        "base_url": zhipu_coding_plan_base_url,
                        "base_url_env_var": "ZHIPU_CODING_API_BASE",
                        "model_name_transform": normalize_zhipu_coding_plan_model_name,
                    },
                    "route_order": 30,
                },
                {
                    "variant_name": "standard",
                    "display_name": "standard Zhipu",
                    "api_key_names": ("ZHIPU_API_KEY",),
                    "default_model_name": "glm-4.7",
                    "model_env_var": "ZHIPU_MODEL",
                    "openai_compatible_transport": {
                        "api_key_name": "ZHIPU_API_KEY",
                        "base_url": zhipu_standard_base_url,
                        "base_url_env_var": "ZHIPU_API_BASE",
                    },
                    "route_order": 40,
                },
            ],
            "capabilities": {
                "supports_json_mode": True,
                "supports_coding_plan": True,
                "openai_compatible": True,
            },
            "concurrency_limit_env_var": "ZHIPU_PROVIDER_CONCURRENCY_LIMIT",
            "default_parallel_limit": 1,
            "enable_priority_routing": True,
            "enable_parallel_scheduler": True,
        },
        {
            "name": "MiniMax",
            "variants": [
                {
                    "variant_name": "default",
                    "display_name": "MiniMax",
                    "api_key_names": ("MINIMAX_API_KEY",),
                    "default_model_name": "MiniMax-M2.5",
                    "model_env_var": "MINIMAX_MODEL",
                    "openai_compatible_transport": {
                        "api_key_name": "MINIMAX_API_KEY",
                        "base_url": "https://api.minimaxi.com/v1",
                    },
                    "route_order": 10,
                }
            ],
            "capabilities": {
                "supports_json_mode": False,
                "openai_compatible": True,
            },
            "concurrency_limit_env_var": "MINIMAX_PROVIDER_CONCURRENCY_LIMIT",
            "default_parallel_limit": 1,
            "enable_priority_routing": True,
            "enable_parallel_scheduler": True,
        },
        {
            "name": "Volcengine",
            "variants": [
                {
                    "variant_name": "coding_plan",
                    "display_name": "Volcengine Ark",
                    "api_key_names": ("ARK_API_KEY",),
                    "default_model_name": "doubao-seed-2.0-code",
                    "model_env_var": "ARK_MODEL",
                    "openai_compatible_transport": {
                        "api_key_name": "ARK_API_KEY",
                        "base_url": volcengine_ark_coding_base_url,
                        "base_url_env_var": "ARK_API_BASE",
                    },
                    "route_order": 20,
                }
            ],
            "capabilities": {
                "supports_json_mode": True,
                "supports_coding_plan": True,
                "openai_compatible": True,
            },
            "concurrency_limit_env_var": "VOLCENGINE_PROVIDER_CONCURRENCY_LIMIT",
            "default_parallel_limit": 1,
            "enable_priority_routing": True,
            "enable_parallel_scheduler": True,
        },
        {
            "name": "OpenRouter",
            "variants": [
                {
                    "variant_name": "default",
                    "display_name": "OpenRouter",
                    "api_key_names": ("OPENROUTER_API_KEY",),
                    "default_model_name": "openai/gpt-4.1-mini",
                    "model_env_var": "OPENROUTER_MODEL",
                    "openai_compatible_transport": {
                        "api_key_name": "OPENROUTER_API_KEY",
                        "base_url": "https://openrouter.ai/api/v1",
                        "base_url_kwarg": "openai_api_base",
                        "api_key_kwarg": "openai_api_key",
                        "dynamic_model_kwargs_factory": _build_openrouter_model_kwargs,
                    },
                    "route_order": 40,
                }
            ],
            "capabilities": {
                "supports_json_mode": True,
                "openai_compatible": True,
            },
            "enable_priority_routing": False,
            "enable_parallel_scheduler": False,
        },
    ]
