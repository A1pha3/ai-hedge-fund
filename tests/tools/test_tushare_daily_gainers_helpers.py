"""NS-17/BH-017 family sibling drain: tushare_daily_gainers_helpers observability.

Context: ``fallback_trade_date_dataframe`` 的 ``except Exception: return None``
静默吞掉所有失败 — operators 无法区分 "无交易日" (合法空) 与 "tushare API 抖动 /
trade_fmt 格式错误" (运维需要知道)。

c273 drain: best-effort 契约保留 (return None), 但 failure path 必须发
``logger.warning`` 让 daily gainers pipeline 的数据源失败可观测。
"""

from __future__ import annotations

import logging

import pandas as pd

from src.tools import tushare_daily_gainers_helpers


class TestFallbackTradeDateDataframeModuleLogger:
    def test_module_logger_exists(self) -> None:
        assert hasattr(tushare_daily_gainers_helpers, "logger")
        assert isinstance(tushare_daily_gainers_helpers.logger, logging.Logger)
        assert tushare_daily_gainers_helpers.logger.name == "src.tools.tushare_daily_gainers_helpers"


class TestFallbackTradeDateDataframeFailureObservability:
    """fallback_trade_date_dataframe 失败路径必须可观测 (NS-17 c273)."""

    def test_trade_cal_fetch_failure_emits_warning(self, caplog) -> None:
        """fetch_dataframe(trade_cal) 抛异常必须发 warning + 返回 None."""

        def _boom_fetch(pro, api_name, **kwargs):
            raise RuntimeError("tushare trade_cal API down")

        with caplog.at_level(logging.WARNING, logger="src.tools.tushare_daily_gainers_helpers"):
            result = tushare_daily_gainers_helpers.fallback_trade_date_dataframe(
                fetch_dataframe=_boom_fetch,
                pro=None,
                trade_fmt="20260701",
                fields="ts_code,close",
            )

        assert result is None
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        msg = warnings[0].getMessage()
        assert "fallback_trade_date_dataframe failed" in msg
        assert "20260701" in msg
        assert "tushare trade_cal API down" in msg

    def test_invalid_trade_fmt_emits_warning(self, caplog) -> None:
        """trade_fmt 格式异常 (strptime 失败) 必须发 warning + 返回 None."""

        def _never_called(pro, api_name, **kwargs):
            raise AssertionError("fetch_dataframe 不应被调用 — strptime 应先抛 ValueError")

        with caplog.at_level(logging.WARNING, logger="src.tools.tushare_daily_gainers_helpers"):
            result = tushare_daily_gainers_helpers.fallback_trade_date_dataframe(
                fetch_dataframe=_never_called,
                pro=None,
                trade_fmt="not-a-date",
                fields="ts_code,close",
            )

        assert result is None
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        msg = warnings[0].getMessage()
        assert "fallback_trade_date_dataframe failed" in msg
        assert "not-a-date" in msg

    def test_second_fetch_failure_emits_warning(self, caplog) -> None:
        """trade_cal 成功但 daily 第二次 fetch 抛异常必须发 warning."""

        call_count = {"n": 0}

        def _fetch_with_second_boom(pro, api_name, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # trade_cal 调用 — 返回一个交易日
                return pd.DataFrame({"cal_date": ["20260630"], "is_open": [1]})
            # 第二次 (daily) — 抛异常
            raise RuntimeError("daily fetch failure after trade_cal success")

        with caplog.at_level(logging.WARNING, logger="src.tools.tushare_daily_gainers_helpers"):
            result = tushare_daily_gainers_helpers.fallback_trade_date_dataframe(
                fetch_dataframe=_fetch_with_second_boom,
                pro=None,
                trade_fmt="20260701",
                fields="ts_code,close",
            )

        assert result is None
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        msg = warnings[0].getMessage()
        assert "fallback_trade_date_dataframe failed" in msg
        assert "daily fetch failure after trade_cal success" in msg

    def test_empty_trade_cal_returns_none_without_warning(self, caplog) -> None:
        """trade_cal 返回空 df (无交易日) 是合法情况, 不应发 warning."""

        def _fetch_empty_cal(pro, api_name, **kwargs):
            return pd.DataFrame()

        with caplog.at_level(logging.WARNING, logger="src.tools.tushare_daily_gainers_helpers"):
            result = tushare_daily_gainers_helpers.fallback_trade_date_dataframe(
                fetch_dataframe=_fetch_empty_cal,
                pro=None,
                trade_fmt="20260701",
                fields="ts_code,close",
            )

        assert result is None
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 0, "空 trade_cal 是合法 'no trading day' 信号, 不应发 warning"

    def test_none_trade_cal_returns_none_without_warning(self, caplog) -> None:
        """trade_cal 返回 None 是合法情况 (无数据), 不应发 warning."""

        def _fetch_none_cal(pro, api_name, **kwargs):
            return None

        with caplog.at_level(logging.WARNING, logger="src.tools.tushare_daily_gainers_helpers"):
            result = tushare_daily_gainers_helpers.fallback_trade_date_dataframe(
                fetch_dataframe=_fetch_none_cal,
                pro=None,
                trade_fmt="20260701",
                fields="ts_code,close",
            )

        assert result is None
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 0, "None trade_cal 是合法 'no data' 信号, 不应发 warning"
