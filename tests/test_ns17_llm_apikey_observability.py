"""NS-17 family sibling drain: src/llm/ API-key error print()→logger.

src/llm/models.py + model_builder_helpers.py build the LLM clients (OpenAI /
Zhipu / GigaChat / Azure). 7 print() calls fire on missing API key / endpoint /
deployment, each IMMEDIATELY followed by ``raise ValueError`` — so the print is
redundant double-output (exception is raised right after), AND in cron / launchd
contexts the print goes to stdout which operators never inspect.

A missing API key is the #1 LLM-init failure mode: the whole system stops
working. Before this drain the diagnostic went only to stdout (invisible in
cron) + the raised exception; structured logging gives operators a breadcrumb
to locate "为何 LLM 初始化失败" in logs.

This extends the BH-017 family drain beyond src/tools/ into the LLM init path.
"""

from __future__ import annotations

import logging

import pytest

from src.llm import models, model_builder_helpers


class TestLlmModelsModuleLogger:
    def test_module_logger_exists(self) -> None:
        assert hasattr(models, "logger")
        assert isinstance(models.logger, logging.Logger)
        assert models.logger.name == "src.llm.models"

    def test_no_print_calls_remain(self) -> None:
        import inspect

        source = inspect.getsource(models)
        assert not [ln for ln in source.splitlines() if ln.lstrip().startswith("print(") and not ln.lstrip().startswith("#")]


class TestModelBuilderHelpersModuleLogger:
    def test_module_logger_exists(self) -> None:
        assert hasattr(model_builder_helpers, "logger")
        assert isinstance(model_builder_helpers.logger, logging.Logger)
        assert model_builder_helpers.logger.name == "src.llm.model_builder_helpers"

    def test_no_print_calls_remain(self) -> None:
        import inspect

        source = inspect.getsource(model_builder_helpers)
        assert not [ln for ln in source.splitlines() if ln.lstrip().startswith("print(") and not ln.lstrip().startswith("#")]


class TestZhipuApiKeyMissingObservability:
    """Zhipu API key 缺失须发 logger.error 然后 raise。"""

    def test_missing_zhipu_key_emits_error(self, monkeypatch, caplog) -> None:
        monkeypatch.delenv("ZHIPU_API_KEY", raising=False)
        monkeypatch.delenv("ZHIPU_CODING_API_KEY", raising=False)
        monkeypatch.delenv("ZHIPU_PREFER_CODING_PLAN", raising=False)

        with caplog.at_level(logging.ERROR, logger="src.llm.models"):
            with pytest.raises(ValueError):
                models.get_zhipu_model("glm-4")

        assert any("ZHIPU_API_KEY" in r.getMessage() and r.levelno >= logging.ERROR for r in caplog.records), "Zhipu API key 缺失必须发 logger.error"


class TestRequiredApiKeyHelperObservability:
    """_get_required_api_key 缺失须发 logger.error 然后 raise。"""

    def test_missing_key_emits_error(self, monkeypatch, caplog) -> None:
        monkeypatch.delenv("SOME_TEST_KEY", raising=False)

        with caplog.at_level(logging.ERROR, logger="src.llm.models"):
            with pytest.raises(ValueError):
                models._get_required_api_key(None, "SOME_TEST_KEY", "TestProvider")

        assert any("SOME_TEST_KEY" in r.getMessage() and r.levelno >= logging.ERROR for r in caplog.records), "_get_required_api_key 缺失必须发 logger.error"


class TestAzureConfigMissingObservability:
    """Azure 缺失配置须发 logger.error 然后 raise (经 build_openai_family_model_impl)。"""

    def test_missing_azure_api_key_emits_error(self, monkeypatch, caplog) -> None:
        monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)

        with caplog.at_level(logging.ERROR, logger="src.llm.model_builder_helpers"):
            with pytest.raises(ValueError):
                model_builder_helpers.build_openai_family_model_impl(
                    model_name="gpt-4",
                    provider_name="Azure OpenAI",
                    api_keys=None,
                    build_openai_compatible_model_fn=lambda *a, **k: None,
                    openai_transport_config_cls=None,
                    get_required_api_key_fn=lambda *a, **k: "",
                    azure_chat_openai_cls=None,
                )

        assert any("AZURE_OPENAI_API_KEY" in r.getMessage() and r.levelno >= logging.ERROR for r in caplog.records), "Azure API key 缺失必须发 logger.error"
