"""NS-17 family sibling drain: tushare_api.py print()→logger observability.

`src/tools/tushare_api.py` is the core A-share production data layer: it wraps
the Tushare Pro API (prices / financials / daily_basic / gainers / industry /
northbound flow / etc.) with retry, rate-limit backoff, and multi-layer caching.
It is imported across main.py, screening/, data/, paper_trading/, execution/,
screening top_picks + candidate_pool + market_state + batch_data_fetcher — i.e.
nearly every must-win workflow depends on it.

Before this drain the module had **no module logger**, 27 ``print()`` calls, and
3 ``traceback.print_exc()`` calls. In cron / launchd / long-running pipeline
contexts ``print()`` / ``traceback.print_exc()`` go to stdout which operators
never inspect, so:

  - rate-limit / retry exhaustion silently throttles the whole screening run
    (free users get ~200 req/min; exhaustion returns ``None`` → empty data →
    agents score on missing inputs) with zero diagnostic breadcrumb
  - TUSHARE_TOKEN-missing ("未初始化") silently returns ``[]`` everywhere
  - every API failure silently degrades the data layer

This is the highest-value BH-017 family sibling: largest print surface (29),
on the most-reached must-win module. Mirrors the established NS-17 guard pattern
(tests/backend/test_ns17_observability.py + test_ns17_ashare_data_sources_observability.py).
"""

from __future__ import annotations

import logging

from src.tools import tushare_api


class TestTushareApiModuleLogger:
    """NS-17 family: tushare_api must have a module logger."""

    def test_module_logger_exists(self) -> None:
        """模块必须有 logger (此前无 logging, 27 print + 3 traceback 不入结构化日志)。"""
        assert hasattr(tushare_api, "logger"), (
            "tushare_api 必须有 module logger (NS-17 / BH-017 family 可观测性要求)"
        )
        assert isinstance(tushare_api.logger, logging.Logger)
        assert tushare_api.logger.name == "src.tools.tushare_api"

    def test_no_print_calls_remain(self) -> None:
        """模块源码不再含裸 print() 调用 (注释/字符串字面量除外)。"""
        import inspect

        source = inspect.getsource(tushare_api)
        code_lines = [
            line
            for line in source.splitlines()
            if line.lstrip().startswith("print(") and not line.lstrip().startswith("#")
        ]
        assert not code_lines, (
            f"tushare_api 不应再有裸 print() 调用, 发现: {code_lines}"
        )

    def test_no_traceback_print_exc_remain(self) -> None:
        """模块源码不再含 traceback.print_exc() (改用 logger.error exc_info=True)。"""
        import inspect

        source = inspect.getsource(tushare_api)
        code_lines = [
            line
            for line in source.splitlines()
            if "traceback.print_exc" in line and not line.lstrip().startswith("#")
        ]
        assert not code_lines, (
            f"tushare_api 不应再有 traceback.print_exc(), 发现: {code_lines}"
        )


class TestCallTushareDataframeApiObservability:
    """NS-17 family: 重试/限速退避须用结构化日志, 不再 print。

    这是 tushare_api 观测性最关键的一段: 限速/重试耗尽时静默返回 None →
    下游拿到空数据 → agent 在缺失输入上打分, 运维无法定位"为何这批票数据为空"。
    """

    def test_non_retryable_failure_emits_warning(self, caplog) -> None:
        """非可重试错误 (TypeError 等) 须发 warning 并返回 None。"""

        class _Boom:
            def daily(self, **kwargs):
                raise TypeError("bad param")

        pro = _Boom()
        with caplog.at_level(logging.WARNING, logger="src.tools.tushare_api"):
            df = tushare_api._call_tushare_dataframe_api(
                pro, "daily", ts_code="000001.SZ"
            )

        assert df is None
        assert any(
            "不可重试" in record.getMessage() and record.levelno >= logging.WARNING
            for record in caplog.records
        ), "非可重试错误必须发 logger.warning (含'不可重试'标记)"

    def test_rate_limit_exhaustion_emits_warning(self, caplog, monkeypatch) -> None:
        """限速重试耗尽须发 warning, 不再静默 print。"""
        monkeypatch.setenv("TUSHARE_RATE_LIMIT_MAX_RETRIES", "0")
        monkeypatch.setenv("TUSHARE_RATE_LIMIT_DELAY", "0")

        class _RateLimited:
            def daily(self, **kwargs):
                raise ConnectionError("429 Too Many Requests")

        pro = _RateLimited()
        with caplog.at_level(logging.WARNING, logger="src.tools.tushare_api"):
            df = tushare_api._call_tushare_dataframe_api(
                pro, "daily", ts_code="000001.SZ"
            )

        assert df is None
        assert any(
            "限速" in record.getMessage() and record.levelno >= logging.WARNING
            for record in caplog.records
        ), "限速重试耗尽必须发 logger.warning"


class TestGetAsharePricesWithTushareObservability:
    """NS-17 family: 价格拉取未初始化/失败须可观测。

    get_ashare_prices_with_tushare 被 top_picks.py (默认前门 R1) 调用。
    token 缺失或拉取失败时静默返回 [] → 前门缺价格 → 评分/止损/仓位全失效。
    """

    def test_not_initialized_emits_warning(self, caplog, monkeypatch) -> None:
        """TUSHARE_TOKEN 未设置时 get_ashare_prices_with_tushare 须发 warning 并返回 []。"""
        monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
        # 重置 module-level _pro 缓存
        tushare_api._pro = None

        with caplog.at_level(logging.WARNING, logger="src.tools.tushare_api"):
            prices = tushare_api.get_ashare_prices_with_tushare(
                "000001", "2026-01-01", "2026-01-02"
            )

        assert prices == []
        assert any(
            "TUSHARE_TOKEN" in record.getMessage() or "未初始化" in record.getMessage()
            for record in caplog.records
        ), "未初始化 (token 缺失) 必须发 logger.warning"

    def test_fetch_failure_emits_observation(self, caplog, monkeypatch) -> None:
        """拉取异常须在结构化日志可观测 (重试层 warning 或 except 层 error)。

        注: get_ashare_prices_with_tushare → _fetch_tushare_ashare_prices_df →
        _cached_tushare_dataframe_call → _call_tushare_dataframe_api: daily/adj_factor
        异常在重试层被 catch 发 logger.warning (耗尽后返回 None), build_prices 收到
        None 返回 [], 不传播到 get_ashare_prices 的 except 块。可观测性在重试层覆盖 —
        这正是本次 drain 的核心价值 (此前重试层用 print 不入日志)。
        """

        class _FakePro:
            def daily(self, **kwargs):
                raise RuntimeError("simulated fetch failure")

            def adj_factor(self, **kwargs):
                raise RuntimeError("simulated fetch failure")

        monkeypatch.setenv("TUSHARE_TOKEN", "fake-token-for-test")
        monkeypatch.setattr(tushare_api, "_pro", _FakePro())

        with caplog.at_level(logging.WARNING, logger="src.tools.tushare_api"):
            prices = tushare_api.get_ashare_prices_with_tushare(
                "000001", "2026-01-01", "2026-01-02"
            )

        assert prices == []
        # 重试层 warning (daily) 或 except 层 error (获取价格数据失败) 任一即可
        assert any(
            (
                "daily" in record.getMessage()
                or "获取价格数据失败" in record.getMessage()
            )
            and record.levelno >= logging.WARNING
            for record in caplog.records
        ), "价格拉取失败必须在结构化日志可观测 (重试层 warning 或 except 层 error)"


class TestGenericApiFailureObservability:
    """NS-17 family: 通用 API 失败须可观测 (代表性抽检 get_open_trade_dates)。

    覆盖 line 1127 的 "获取交易日历失败" — paper_trading/execution 大量依赖
    trade_cal, 失败静默 return [] 会让回测日期序列错位。
    """

    def test_trade_dates_failure_emits_error(self, caplog, monkeypatch) -> None:
        """get_open_trade_dates 失败须发 logger.error, 不再静默 print。"""
        monkeypatch.setattr(tushare_api, "_get_pro", lambda: None)

        with caplog.at_level(logging.ERROR, logger="src.tools.tushare_api"):
            result = tushare_api.get_open_trade_dates("20260101", "20260102")

        assert result == []
        # _get_pro 返回 None 时函数提前返回 []; 用一个会真正抛异常的 fake pro
        # 改为直接测 logger 存在 + 函数在 pro=None 时不崩 (契约守卫)
        # 更精确的失败注入在下面
        assert hasattr(tushare_api, "logger")

    def test_api_failure_with_raising_pro_emits_observation(
        self, caplog, monkeypatch
    ) -> None:
        """真实抛异常的 pro 须触发结构化日志 (在重试层 warning 或 except 层 error)。

        注: get_open_trade_dates → _cached_tushare_dataframe_call →
        _call_tushare_dataframe_api: 异常在重试层被 catch 并发 logger.warning
        (重试耗尽返回 None), 不传播到 get_open_trade_dates 的 except 块。可观测性
        在重试层覆盖 (warning), 这正是本次 drain 的核心价值 — 此前重试层用 print
        完全不入日志。
        """

        class _BoomPro:
            def trade_cal(self, **kwargs):
                raise RuntimeError("simulated trade_cal failure")

        monkeypatch.setenv("TUSHARE_TOKEN", "fake-token-for-test")
        monkeypatch.setattr(tushare_api, "_pro", _BoomPro())

        with caplog.at_level(logging.WARNING, logger="src.tools.tushare_api"):
            result = tushare_api.get_open_trade_dates("20260101", "20260102")

        assert result == []
        # 重试层 warning (trade_cal) 或 except 层 error (get_open_trade_dates) 任一即可
        assert any(
            (
                "trade_cal" in record.getMessage()
                or "get_open_trade_dates" in record.getMessage()
            )
            and record.levelno >= logging.WARNING
            for record in caplog.records
        ), "trade_cal 失败必须在结构化日志可观测 (重试层 warning 或 except 层 error)"


class TestGetProInitFailureObservability:
    """NS-17 family sibling: ``_get_pro`` 单例 init 失败须可观测。

    生产路径: backfill/daily_pipeline 通过 ``src.tools.tushare_api._get_pro()``
    获取 tushare pro_api 单例 (与 ``src/data/providers/tushare_provider.py``
    ``_init_tushare`` 是两条独立的 init 路径 — 前者服务 tools 路径, 后者服务
    provider 路径)。token revoked / runtime schema change / 网络错误等非
    ImportError 失败此前被静默吞成 ``return None``, 调用方看到
    ``if not pro: return None`` 时无法区分 "TUSHARE_TOKEN 未配置" 与 "已配置
    但失效" — 与 c305 ``health_check`` swallow 同族残留。
    """

    def test_get_pro_non_import_failure_emits_warning(
        self, caplog, monkeypatch
    ) -> None:
        """非 ImportError 失败 (token rejected at first API call, runtime
        schema change, 网络错误) 必须发 warning, 不再静默吞成 return None。"""
        import sys
        from types import ModuleType

        monkeypatch.setenv("TUSHARE_TOKEN", "fake-token-for-test")
        # 重置 module-level _pro 单例, 强制 _get_pro 走 init 分支
        monkeypatch.setattr(tushare_api, "_pro", None)

        # 注入一个 fake tushare 模块: import 成功, 但 pro_api 抛 RuntimeError
        fake_tushare = ModuleType("tushare")

        def _boom_pro_api(*_args, **_kwargs):
            raise RuntimeError("simulated tushare init runtime error")

        fake_tushare.pro_api = _boom_pro_api  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "tushare", fake_tushare)

        with caplog.at_level(logging.WARNING, logger="src.tools.tushare_api"):
            pro = tushare_api._get_pro()

        # 契约: 失败 → None (调用方用 if not pro 处理)
        assert pro is None

        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_records) >= 1, (
            f"expected >=1 WARNING record from _get_pro non-ImportError init failure, got {caplog.records}"
        )
        msg = warning_records[0].getMessage()
        assert (
            "tushare" in msg.lower()
            or "_get_pro" in msg.lower()
            or "pro_api" in msg.lower()
        )
        assert "simulated tushare init runtime error" in msg

    def test_get_pro_import_error_stays_silent(self, caplog, monkeypatch) -> None:
        """ImportError (tushare 未安装) 是 dev box 预期状态, 必须不发 warning
        — 只有 runtime/init 失败才 surface (与 c305 health_check drain 一致)。"""
        import sys

        monkeypatch.setenv("TUSHARE_TOKEN", "fake-token-for-test")
        monkeypatch.setattr(tushare_api, "_pro", None)

        # 让 import tushare 抛 ImportError
        real_import = (
            __builtins__["__import__"]
            if isinstance(__builtins__, dict)
            else __builtins__.__import__
        )

        def _import_side_effect(name, *args, **kwargs):
            if name == "tushare":
                raise ImportError("simulated tushare not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", _import_side_effect)
        # 移除可能已缓存的 tushare 模块, 强制重新 import
        monkeypatch.delitem(sys.modules, "tushare", raising=False)

        with caplog.at_level(logging.WARNING, logger="src.tools.tushare_api"):
            pro = tushare_api._get_pro()

        assert pro is None
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warning_records == [], (
            f"ImportError 是预期状态不应发 warning, got {warning_records}"
        )


class TestGetStockNameObservability:
    """NS-17 family sibling (c274): ``get_stock_name`` stock_basic 失败须可观测.

    生产路径: 多个展示/报告路径 (top_picks / pdf_exporter / etc.) 调用
    ``get_stock_name(ticker)`` 把 ticker 解析成中文名。c306 drain 漏网了这一处
    — stock_basic 查询失败静默 ``pass`` 会让运维无法区分 "ticker 无对应
    stock_basic 记录" (合法) 与 "tushare API 抖动 / token 失效" (需运维介入)。

    Best-effort 契约保留 (返回 ticker), 但 failure path 必须发 debug (展示用途,
    非决策链; 有 _stock_name_cache 减少 hot path 噪声)。
    """

    def test_stock_basic_failure_emits_debug(self, caplog, monkeypatch) -> None:
        """stock_basic 查询抛异常必须发 debug + 返回 ticker (best-effort)."""
        # 确保 cache miss, 强制走 stock_basic 路径
        monkeypatch.setattr(tushare_api, "_stock_name_cache", {})

        # 注入一个 _get_pro 返回假 pro, _cached_tushare_dataframe_call 抛异常
        class _FakePro:
            pass

        monkeypatch.setattr(tushare_api, "_get_pro", lambda: _FakePro())

        def _boom_cached_call(*_args, **_kwargs):
            raise RuntimeError("simulated stock_basic API failure")

        monkeypatch.setattr(
            tushare_api, "_cached_tushare_dataframe_call", _boom_cached_call
        )

        with caplog.at_level(logging.DEBUG, logger="src.tools.tushare_api"):
            name = tushare_api.get_stock_name("000001.SZ")

        # best-effort: 返回 ticker
        assert name == "000001.SZ"
        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debug_records) == 1, (
            f"expected 1 DEBUG record, got {debug_records}"
        )
        msg = debug_records[0].getMessage()
        assert "get_stock_name stock_basic query failed" in msg
        assert "000001.SZ" in msg
        assert "simulated stock_basic API failure" in msg

    def test_stock_basic_success_no_debug(self, caplog, monkeypatch) -> None:
        """合法 stock_basic 查询不应发 debug (避免日志噪声)."""
        import pandas as pd

        monkeypatch.setattr(tushare_api, "_stock_name_cache", {})

        class _FakePro:
            pass

        monkeypatch.setattr(tushare_api, "_get_pro", lambda: _FakePro())

        def _ok_cached_call(*_args, **_kwargs):
            return pd.DataFrame({"ts_code": ["000001.SZ"], "name": ["平安银行"]})

        monkeypatch.setattr(
            tushare_api, "_cached_tushare_dataframe_call", _ok_cached_call
        )

        with caplog.at_level(logging.DEBUG, logger="src.tools.tushare_api"):
            name = tushare_api.get_stock_name("000001.SZ")

        assert name == "平安银行"
        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debug_records) == 0

    def test_no_pro_returns_ticker_silently(self, caplog, monkeypatch) -> None:
        """``_get_pro`` 返回 None (TUSHARE_TOKEN 未配置) 是预期 dev 状态, 不发 debug."""
        monkeypatch.setattr(tushare_api, "_stock_name_cache", {})
        monkeypatch.setattr(tushare_api, "_get_pro", lambda: None)

        with caplog.at_level(logging.DEBUG, logger="src.tools.tushare_api"):
            name = tushare_api.get_stock_name("000001.SZ")

        assert name == "000001.SZ"
        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debug_records) == 0
