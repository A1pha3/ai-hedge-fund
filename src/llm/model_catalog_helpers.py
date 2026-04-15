from __future__ import annotations

import json
from typing import Any


def load_model_records_from_json(json_path: str) -> list[dict[str, Any]]:
    with open(json_path, "r") as file_obj:
        return json.load(file_obj)


def build_llm_models(model_records: list[dict[str, Any]], model_cls, provider_enum_cls) -> list[Any]:
    return [
        model_cls(
            display_name=model_data["display_name"],
            model_name=model_data["model_name"],
            provider=provider_enum_cls(model_data["provider"]),
        )
        for model_data in model_records
    ]


def find_model_in_catalog(all_models: list[Any], model_name: str, provider: Any | None = None) -> Any | None:
    return next(
        (
            model
            for model in all_models
            if model.model_name == model_name and (provider is None or model.provider == provider)
        ),
        None,
    )


def build_fallback_model_info(model_name: str, model_provider: Any, provider_enum_cls, model_cls):
    try:
        provider_enum = model_provider if isinstance(model_provider, provider_enum_cls) else provider_enum_cls(str(model_provider))
    except ValueError:
        return None

    return model_cls(display_name=str(model_name), model_name=str(model_name), provider=provider_enum)


def build_model_list_payload(models: list[Any]) -> list[dict[str, str]]:
    return [
        {
            "display_name": model.display_name,
            "model_name": model.model_name,
            "provider": model.provider.value,
        }
        for model in models
    ]
