"""NS-17 family sibling drain: api.py print()→logger (logger already present).

src/tools/api.py already has a module logger (line 54) but 3 print() calls
remained in _make_api_request (request-error + rate-limit-retry) and
get_company_facts (fetch-error). In cron/launchd contexts these prints go to
stdout which operators never inspect, so a request-error / rate-limit / facts-
fetch-failure degrades the US-equity data path with zero diagnostic breadcrumb.

This is the last print→logger sibling in src/tools/ (c280-c286 batch).
"""

from __future__ import annotations

import logging

from src.tools import api


class TestApiNoPrintRemains:
    """NS-17 family: api.py 不应再有裸 print()。"""

    def test_no_print_calls_remain(self) -> None:
        """模块已有 logger, 不应再用 print()。"""
        import inspect

        source = inspect.getsource(api)
        code_lines = [
            ln
            for ln in source.splitlines()
            if ln.lstrip().startswith("print(")
            and not ln.lstrip().startswith("#")
        ]
        assert not code_lines, f"api.py 不应再有裸 print() 调用, 发现: {code_lines}"

    def test_module_logger_exists(self) -> None:
        """模块已有 logger (本次只补 print→logger, logger 本就存在)。"""
        assert hasattr(api, "logger")
        assert api.logger.name == "src.tools.api"


class TestMakeApiRequestObservability:
    """NS-17 family: _make_api_request 错误须用 logger, 不再 print。"""

    def test_request_error_emits_warning(self, monkeypatch, caplog) -> None:
        """requests.RequestException 须发 logger.warning, 不再 print。"""
        import requests

        class _BoomSession:
            def __getattr__(self, name):
                def _raise(*a, **k):
                    raise requests.RequestException("simulated request error")
                return _raise

        monkeypatch.setattr(requests, "post", _BoomSession().post)
        monkeypatch.setattr(requests, "get", _BoomSession().get)

        with caplog.at_level(logging.WARNING, logger="src.tools.api"):
            result = api._make_api_request("http://example.com", headers={}, method="GET", max_retries=0)

        assert result is None
        assert any(
            "Request error" in r.getMessage() and r.levelno >= logging.WARNING
            for r in caplog.records
        ), "RequestException 必须发 logger.warning (不再 print)"

    def test_rate_limit_emits_warning(self, monkeypatch, caplog) -> None:
        """429 限速重试须发 logger.warning, 不再 print。"""
        from types import SimpleNamespace

        def _fake_get(*a, **k):
            return SimpleNamespace(status_code=429)

        import requests

        monkeypatch.setattr(requests, "get", _fake_get)
        # 避免真 sleep 60s: rate-limit 重试路径用 delay=60+(30*attempt)
        monkeypatch.setattr(api.time, "sleep", lambda *a, **k: None)

        with caplog.at_level(logging.WARNING, logger="src.tools.api"):
            # max_retries=1 让它重试一次 (触发 rate-limit 日志), 第二次仍 429 返回
            api._make_api_request("http://example.com", headers={}, method="GET", max_retries=1)

        assert any(
            "429" in r.getMessage() or "Rate limited" in r.getMessage()
            for r in caplog.records
        ), "429 限速重试必须发 logger.warning (不再 print)"
