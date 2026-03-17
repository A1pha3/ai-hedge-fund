from __future__ import annotations

import os

from dotenv import load_dotenv

from src.llm.models import get_provider_routes


load_dotenv(override=True)


def resolve_model_selection(model_name: str | None, model_provider: str | None) -> tuple[str, str]:
    if bool(model_name) != bool(model_provider):
        raise ValueError("--model-name 和 --model-provider 需要同时提供，或者都不提供")

    if model_name and model_provider:
        return model_name, model_provider

    env_model_name = os.getenv("BACKTEST_MODEL_NAME")
    env_model_provider = os.getenv("BACKTEST_MODEL_PROVIDER")
    if bool(env_model_name) != bool(env_model_provider):
        raise ValueError(".env 中的 BACKTEST_MODEL_NAME 和 BACKTEST_MODEL_PROVIDER 需要同时提供，或者都不提供")
    if env_model_name and env_model_provider:
        return env_model_name, env_model_provider

    routes = get_provider_routes(None)
    if not routes:
        raise ValueError("未从 .env 检测到可用的 provider 路由，请显式传入 --model-name 和 --model-provider")

    primary_route = routes[0]
    return primary_route.model_name, primary_route.provider_name