"""NS-17 family sibling drain: small helper modules print()→logger (batch).

Batch drains three small modules, each with 1-2 print() calls and no module
logger:
- tushare_sw_industry_helpers.py: build_sw_industry_mapping fetches SW industry
  members; silent per-industry failure leaves the industry mapping partial ->
  candidate-pool industry clustering degrades with zero breadcrumb.
- akshare_news_helpers.py: deduplicate_news prints the dedup count; this is a
  diagnostic info that goes to stdout (invisible in cron).
- akshare_market_helpers.py: load_optional_market_dataframe prints unavailable +
  error messages; silent failure on optional market frames (index/northbound)
  degrades with no breadcrumb.

Mirrors the BH-017 family drained across c280-c284.
"""

from __future__ import annotations

import logging
import os
from types import SimpleNamespace

from src.tools import (
    akshare_market_helpers,
    akshare_news_helpers,
    tushare_sw_industry_helpers,
)


class TestTushareSwIndustryHelpersLogger:
    def test_module_logger_exists(self) -> None:
        assert hasattr(tushare_sw_industry_helpers, "logger")
        assert tushare_sw_industry_helpers.logger.name == "src.tools.tushare_sw_industry_helpers"

    def test_no_print_calls_remain(self) -> None:
        import inspect

        source = inspect.getsource(tushare_sw_industry_helpers)
        assert not [ln for ln in source.splitlines() if ln.lstrip().startswith("print(") and not ln.lstrip().startswith("#")]


class TestSwIndustryMemberFetchObservability:
    def test_member_fetch_failure_emits_warning(self, caplog) -> None:
        import pandas as pd

        index_df = pd.DataFrame([{"index_code": "801010", "industry_name": "农林牧渔"}])

        def _boom(*a, **k):
            raise RuntimeError("member fetch failure")

        with caplog.at_level(logging.WARNING, logger="src.tools.tushare_sw_industry_helpers"):
            result = tushare_sw_industry_helpers.build_sw_industry_mapping(_boom, None, index_df)

        assert result == {}  # 失败的行业被跳过
        assert any("农林牧渔" in r.getMessage() and r.levelno >= logging.WARNING for r in caplog.records), "行业成分拉取失败必须发 logger.warning"


class TestAkshareNewsHelpersLogger:
    def test_module_logger_exists(self) -> None:
        assert hasattr(akshare_news_helpers, "logger")
        assert akshare_news_helpers.logger.name == "src.tools.akshare_news_helpers"

    def test_no_print_calls_remain(self) -> None:
        import inspect

        source = inspect.getsource(akshare_news_helpers)
        assert not [ln for ln in source.splitlines() if ln.lstrip().startswith("print(") and not ln.lstrip().startswith("#")]


class TestNewsDedupObservability:
    def test_dedup_emits_info(self, caplog) -> None:
        # 构造 2 篇标题相同的新闻 (deduplicate_news 读 article.title 属性, 需对象非 dict)
        from types import SimpleNamespace

        a1 = SimpleNamespace(title="公司发布财报", content="营收增长", source="A")
        a2 = SimpleNamespace(title="公司发布财报", content="营收增长", source="B")

        with caplog.at_level(logging.INFO, logger="src.tools.akshare_news_helpers"):
            result = akshare_news_helpers.deduplicate_news([a1, a2])

        assert len(result) == 1
        assert any("去重" in r.getMessage() and r.levelno == logging.INFO for r in caplog.records), "去重计数必须经 logger.info 可观测"


class TestAkshareMarketHelpersLogger:
    def test_module_logger_exists(self) -> None:
        assert hasattr(akshare_market_helpers, "logger")
        assert akshare_market_helpers.logger.name == "src.tools.akshare_market_helpers"

    def test_no_print_calls_remain(self) -> None:
        import inspect

        source = inspect.getsource(akshare_market_helpers)
        assert not [ln for ln in source.splitlines() if ln.lstrip().startswith("print(") and not ln.lstrip().startswith("#")]


class TestMarketHelpersObservability:
    def test_unavailable_emits_warning(self, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger="src.tools.akshare_market_helpers"):
            result = akshare_market_helpers.load_optional_market_dataframe(
                is_available=False,
                unavailable_message="市场数据不可用",
                fetch_dataframe_fn=lambda: None,
                error_message="拉取失败",
            )

        assert result is None
        assert any("市场数据不可用" in r.getMessage() and r.levelno >= logging.WARNING for r in caplog.records)

    def test_fetch_error_emits_warning(self, caplog) -> None:
        def _boom():
            raise RuntimeError("market fetch failure")

        with caplog.at_level(logging.WARNING, logger="src.tools.akshare_market_helpers"):
            result = akshare_market_helpers.load_optional_market_dataframe(
                is_available=True,
                unavailable_message="不可用",
                fetch_dataframe_fn=_boom,
                error_message="市场数据拉取失败",
            )

        assert result is None
        assert any("市场数据拉取失败" in r.getMessage() and r.levelno >= logging.WARNING for r in caplog.records)

    def test_fetch_runs_with_system_proxies_disabled(self, monkeypatch) -> None:
        monkeypatch.setenv("HTTP_PROXY", "http://proxy.example")
        observed = {}

        def _fetch():
            observed["during_fetch"] = os.environ.get("HTTP_PROXY")
            return akshare_market_helpers.pd.DataFrame([{"value": 1}])

        result = akshare_market_helpers.load_optional_market_dataframe(
            is_available=True,
            unavailable_message="不可用",
            fetch_dataframe_fn=_fetch,
            error_message="市场数据拉取失败",
        )

        assert result is not None
        assert observed == {"during_fetch": None}
        assert os.environ["HTTP_PROXY"] == "http://proxy.example"

    def test_repeated_expected_failures_open_endpoint_circuit_breaker(self, monkeypatch) -> None:
        monkeypatch.setenv("AKSHARE_EASTMONEY_FAILURE_BREAKER_THRESHOLD", "2")
        monkeypatch.setenv("AKSHARE_EASTMONEY_FAILURE_BREAKER_COOLDOWN_SECONDS", "60")
        monkeypatch.setattr(akshare_market_helpers, "_get_eastmoney_rate_limiter", lambda: SimpleNamespace(acquire=lambda: None))
        akshare_market_helpers._network_error_counts.clear()
        akshare_market_helpers._endpoint_failure_counts.clear()
        akshare_market_helpers._endpoint_circuit_open_until.clear()

        calls = []

        def _boom():
            calls.append("fetch")
            raise ConnectionError("Remote end closed connection without response")

        for _ in range(2):
            result = akshare_market_helpers.load_optional_market_dataframe(
                is_available=True,
                unavailable_message="不可用",
                fetch_dataframe_fn=_boom,
                error_message="[AKShare] get_intraday_bars(688361, 20260708) 失败",
            )
            assert result is None

        result = akshare_market_helpers.load_optional_market_dataframe(
            is_available=True,
            unavailable_message="不可用",
            fetch_dataframe_fn=_boom,
            error_message="[AKShare] get_intraday_bars(688082, 20260708) 失败",
        )

        assert result is None
        assert calls == ["fetch", "fetch"]

    def test_empty_data_failures_do_not_open_endpoint_circuit_breaker(self, monkeypatch) -> None:
        monkeypatch.setenv("AKSHARE_EASTMONEY_FAILURE_BREAKER_THRESHOLD", "2")
        monkeypatch.setattr(akshare_market_helpers, "_get_eastmoney_rate_limiter", lambda: SimpleNamespace(acquire=lambda: None))
        akshare_market_helpers._network_error_counts.clear()
        akshare_market_helpers._endpoint_failure_counts.clear()
        akshare_market_helpers._endpoint_circuit_open_until.clear()

        calls = []

        def _empty_response():
            calls.append("fetch")
            raise TypeError("'NoneType' object is not subscriptable")

        for _ in range(3):
            result = akshare_market_helpers.load_optional_market_dataframe(
                is_available=True,
                unavailable_message="不可用",
                fetch_dataframe_fn=_empty_response,
                error_message="[AKShare] get_lhb_detail(20260708, 20260708) 失败",
            )
            assert result is None

        assert calls == ["fetch", "fetch", "fetch"]
        assert akshare_market_helpers._endpoint_circuit_open_until == {}

    def test_circuit_breaker_is_rechecked_after_rate_limit_wait(self, monkeypatch) -> None:
        key = "[AKShare] get_intraday_bars"
        akshare_market_helpers._network_error_counts.clear()
        akshare_market_helpers._endpoint_failure_counts.clear()
        akshare_market_helpers._endpoint_circuit_open_until.clear()

        class _Limiter:
            def acquire(self) -> None:
                akshare_market_helpers._endpoint_circuit_open_until[key] = akshare_market_helpers.time.monotonic() + 60

        monkeypatch.setattr(akshare_market_helpers, "_get_eastmoney_rate_limiter", lambda: _Limiter())
        calls = []

        def _fetch():
            calls.append("fetch")
            return akshare_market_helpers.pd.DataFrame([{"value": 1}])

        result = akshare_market_helpers.load_optional_market_dataframe(
            is_available=True,
            unavailable_message="不可用",
            fetch_dataframe_fn=_fetch,
            error_message="[AKShare] get_intraday_bars(688361, 20260708) 失败",
        )

        assert result is None
        assert calls == []
