"""NS-17 family sibling drain: akshare_api.py print()→logger observability.

`src/tools/akshare_api.py` is the AKShare data interface module (prices /
financials / statements / insider trades / company news). It is the primary
A-share data path behind get_prices / get_company_news / sentiment agents.

Before this drain the module had NO module logger and 3 print() calls:
  - module-load: akshare import-failure warning (line 122)
  - news-filter: filtered-count info (line 613)
  - news-fetch: failure on the sentiment/news path (line 617)

In cron/launchd contexts print() goes to stdout which operators never inspect,
so an akshare-not-installed or news-fetch-failure degrades the sentiment path
with zero diagnostic breadcrumb. Mirrors the BH-017 family drained across
ashare_data_sources (c280), tushare_api (c281), akshare_price_helpers (c282).

Note: the module-load print runs at import time in a try/except ImportError;
we cannot easily TDD-drive it post-import, so the guard asserts the module
logger exists + the source has no print() (structural guard) + the news-fetch
failure path emits logger.warning (runtime guard).
"""

from __future__ import annotations

import logging

from src.tools import akshare_api


class TestAkshareApiModuleLogger:
    """NS-17 family: akshare_api must have a module logger."""

    def test_module_logger_exists(self) -> None:
        """模块必须有 logger (此前无 logging, 3 处 print 不入结构化日志)。"""
        assert hasattr(akshare_api, "logger"), (
            "akshare_api 必须有 module logger (NS-17 / BH-017 family 可观测性要求)"
        )
        assert isinstance(akshare_api.logger, logging.Logger)
        assert akshare_api.logger.name == "src.tools.akshare_api"

    def test_no_print_calls_remain(self) -> None:
        """模块源码不再含裸 print() 调用 (注释/字符串字面量除外)。"""
        import inspect

        source = inspect.getsource(akshare_api)
        code_lines = [
            line
            for line in source.splitlines()
            if line.lstrip().startswith("print(")
            and not line.lstrip().startswith("#")
        ]
        assert not code_lines, (
            f"akshare_api 不应再有裸 print() 调用, 发现: {code_lines}"
        )


class TestNewsFetchObservability:
    """NS-17 family: 新闻拉取失败须可观测。

    get_a_share_news 是 sentiment agent 的输入路径。拉取失败静默返回 [] →
    agent 在无新闻上做情绪分析, 运维无法定位"为何情绪信号缺失"。
    """

    def test_news_fetch_failure_emits_warning(self, monkeypatch, caplog) -> None:
        """新闻拉取异常须发 logger.warning, 返回 []。"""
        # 让 load_company_news_results 抛异常, 触发 get_ashare_company_news 的 except 块
        def _boom(**kwargs):
            raise RuntimeError("simulated news fetch failure")

        monkeypatch.setattr(akshare_api, "load_company_news_results", _boom)

        with caplog.at_level(logging.WARNING, logger="src.tools.akshare_api"):
            result = akshare_api.get_ashare_company_news("000001", end_date="2026-01-01")

        assert result == []
        assert any(
            "新闻" in r.getMessage() and r.levelno >= logging.WARNING
            for r in caplog.records
        ), "新闻拉取失败必须发 logger.warning"
