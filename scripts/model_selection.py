from __future__ import annotations

import os

from src.project_env import load_project_dotenv
from src.llm.defaults import resolve_model_selection as resolve_default_model_selection


load_project_dotenv()


def resolve_model_selection(model_name: str | None, model_provider: str | None) -> tuple[str, str]:
    try:
        return resolve_default_model_selection(model_name, model_provider)
    except ValueError as error:
        if model_name or model_provider:
            raise ValueError("--model-name 和 --model-provider 需要同时提供，或者都不提供") from error
        env_model_name = os.getenv("BACKTEST_MODEL_NAME")
        env_model_provider = os.getenv("BACKTEST_MODEL_PROVIDER")
        if bool(env_model_name) != bool(env_model_provider):
            raise ValueError(".env 中的 BACKTEST_MODEL_NAME 和 BACKTEST_MODEL_PROVIDER 需要同时提供，或者都不提供") from error
        raise