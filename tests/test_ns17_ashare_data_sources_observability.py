"""NS-17 family sibling drain: ashare_data_sources.py print()→logger observability.

`src/tools/ashare_data_sources.py` is the A-share multi-source price infrastructure
(Tushare / BaoStock / Sina / Mock fallback chain). It is reached from production:

- `recommendation_tracker._default_price_fetcher` (R164 fallback) imports
  ``TushareDataSource`` to backfill realized returns when akshare returns empty.
  This backfill feeds the **north-star P&L measurement closed loop** (NS-3 / NS-4 /
  north_star_pnl / rank_monotonicity — autodev's stated core value, see
  docs/cn/product/feature-proposals.md §三·6).
- `akshare_api.get_prices` imports ``get_prices_multi_source`` for the multi-source
  price path.

Before this drain the module had **no module logger** and 7 ``print()`` surfaces:

  - Tushare init: token-missing / import-missing / init-exception (3 prints)
  - BaoStock init: import-missing (1 print)
  - multi-source fallback: "尝试 / ✓ 成功 / ✗ 失败" per source (3 prints)

In cron / launchd / long-running pipeline contexts ``print()`` goes to stdout which
operators never inspect; a silent Tushare init failure (token missing, module
missing) degrades the north-star measurement closed loop with **zero diagnostic
breadcrumb** in structured logs — exactly the BH-017 silent-degradation family
pattern drained across R48-R50/R63/R67/R88/R103/R106 and NS-17 siblings.

This module mirrors the `tests/backend/test_ns17_observability.py` guard pattern:
module logger must exist, no bare ``print()`` remains, and init failures emit
``logger.warning`` with the source name so operators can locate the root cause.
"""

from __future__ import annotations

import logging

from src.tools import ashare_data_sources


class TestAshareDataSourcesModuleLogger:
    """NS-17 family: ashare_data_sources must have a module logger."""

    def test_module_logger_exists(self) -> None:
        """模块必须有 logger (此前无 logging, 7 处 print 不入结构化日志)。"""
        assert hasattr(ashare_data_sources, "logger"), "ashare_data_sources 必须有 module logger (NS-17 / BH-017 family 可观测性要求)"
        assert isinstance(ashare_data_sources.logger, logging.Logger)
        assert ashare_data_sources.logger.name == "src.tools.ashare_data_sources"

    def test_no_print_calls_remain(self) -> None:
        """模块源码不再含裸 print() 调用 (注释/字符串字面量除外)。"""
        import inspect

        source = inspect.getsource(ashare_data_sources)
        code_lines = [line for line in source.splitlines() if line.lstrip().startswith("print(") and not line.lstrip().startswith("#")]
        assert not code_lines, f"ashare_data_sources 不应再有裸 print() 调用, 发现: {code_lines}"


class TestTushareInitFailureObservability:
    """NS-17 family: TushareDataSource._init_tushare 失败须发 logger.warning。

    生产路径 (recommendation_tracker._default_price_fetcher R164 fallback) 在
    akshare 返回空时回退 TushareDataSource。若 Tushare 初始化静默失败 (token 缺失 /
    模块缺失 / 初始化异常), 回退链静默退化且 north-star P&L backfill 拿不到任何
    诊断面包屑。
    """

    def test_missing_token_emits_warning(self, caplog, monkeypatch) -> None:
        """TUSHARE_TOKEN 未设置时必须发 warning, 不再 print。"""
        monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
        # 重置 class state — 避免先前测试 / import 缓存的 _pro 污染
        ashare_data_sources.TushareDataSource._pro = None
        ashare_data_sources.TushareDataSource.available = False

        with caplog.at_level(logging.WARNING, logger="src.tools.ashare_data_sources"):
            result = ashare_data_sources.TushareDataSource._init_tushare()

        assert result is False
        assert any("TUSHARE_TOKEN" in record.getMessage() for record in caplog.records), "TUSHARE_TOKEN 缺失必须发 logger.warning"

    def test_tushare_init_exception_emits_warning(self, caplog, monkeypatch) -> None:
        """tushare.set_token / pro_api 抛异常时必须发 warning (含异常信息)。"""
        monkeypatch.setenv("TUSHARE_TOKEN", "fake-token-for-test")
        ashare_data_sources.TushareDataSource._pro = None
        ashare_data_sources.TushareDataSource.available = False

        # 让 tushare 模块导入成功但 ts.pro_api 抛异常
        import sys
        from types import ModuleType

        fake_tushare = ModuleType("tushare")

        def _boom(*args, **kwargs):  # pragma: no cover - executed via monkeypatch
            raise RuntimeError("simulated init failure")

        fake_tushare.set_token = lambda token: None
        fake_tushare.pro_api = _boom  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "tushare", fake_tushare)

        with caplog.at_level(logging.WARNING, logger="src.tools.ashare_data_sources"):
            result = ashare_data_sources.TushareDataSource._init_tushare()

        assert result is False
        assert any("Tushare" in record.getMessage() and record.levelno == logging.WARNING for record in caplog.records), "Tushare 初始化异常必须发 logger.warning"


class TestBaostockInitObservability:
    """NS-17 family: BaoStockDataSource._init_baostock 失败须发 logger.warning。"""

    def test_missing_module_emits_warning(self, caplog, monkeypatch) -> None:
        """baostock 模块不可用 (find_spec 返回 None) 时必须发 warning。

        注: ``_init_baostock`` 的契约是返回 True + 设置 ``cls.available`` 标志
        (caller 检查 available, 不检查返回值)。先前 find_spec 返回 None 时 available
        默默保持 False 且**无任何面包屑** —— 本次 drain 让该静默退化可观测。
        """
        import importlib.util

        ashare_data_sources.BaoStockDataSource.available = False

        original_find_spec = importlib.util.find_spec

        def _fake_find_spec(name, *args, **kwargs):
            if name == "baostock":
                return None
            return original_find_spec(name, *args, **kwargs)

        monkeypatch.setattr(importlib.util, "find_spec", _fake_find_spec)

        with caplog.at_level(logging.WARNING, logger="src.tools.ashare_data_sources"):
            result = ashare_data_sources.BaoStockDataSource._init_baostock()

        assert result is True  # 契约: 始终返回 True, caller 看 available
        assert ashare_data_sources.BaoStockDataSource.available is False
        assert any("baostock" in record.getMessage() and record.levelno == logging.WARNING for record in caplog.records), "baostock 模块缺失必须发 logger.warning (此前完全静默)"


class TestMultiSourceFallbackObservability:
    """NS-17 family: get_prices_multi_source 每个 source 尝试/成功/失败须发 logger。

    生产路径: akshare_api.get_prices → get_prices_multi_source。print() 在 cron /
    长跑 pipeline 不入日志, source 失败 + 回退链退化时运维失去根因定位能力。
    """

    def test_source_failure_emits_warning(self, caplog, monkeypatch) -> None:
        """每个失败的 source 必须发 logger.warning (含 source 名 + 异常信息)。"""
        from src.data.models import Price

        class _BoomSource:
            name = "boom-test"
            available = True

            @classmethod
            def get_prices(cls, ticker, start_date, end_date, period="daily"):
                raise RuntimeError("simulated source failure")

        class _OkSource:
            name = "ok-test"
            available = True

            @classmethod
            def get_prices(cls, ticker, start_date, end_date, period="daily"):
                return [Price(time="2026-01-01", open=1.0, high=1.0, low=1.0, close=1.0, volume=100)]

        monkeypatch.setattr(ashare_data_sources, "DATA_SOURCES", [_BoomSource, _OkSource])

        with caplog.at_level(logging.WARNING, logger="src.tools.ashare_data_sources"):
            prices = ashare_data_sources.get_prices_multi_source("000001", "2026-01-01", "2026-01-02")

        # 回退到第二个 source 成功
        assert len(prices) == 1
        assert any("boom-test" in record.getMessage() and record.levelno == logging.WARNING for record in caplog.records), "失败 source 必须发 logger.warning 含 source 名"

    def test_source_attempt_emits_debug(self, caplog, monkeypatch) -> None:
        """每个 source 的尝试 (debug) 与成功 (info) 用结构化日志, 不再 print。"""
        from src.data.models import Price

        class _OkSource:
            name = "ok-debug-test"
            available = True

            @classmethod
            def get_prices(cls, ticker, start_date, end_date, period="daily"):
                return [Price(time="2026-01-01", open=1.0, high=1.0, low=1.0, close=1.0, volume=100)]

        monkeypatch.setattr(ashare_data_sources, "DATA_SOURCES", [_OkSource])

        with caplog.at_level(logging.DEBUG, logger="src.tools.ashare_data_sources"):
            prices = ashare_data_sources.get_prices_multi_source("000001", "2026-01-01", "2026-01-02")

        assert len(prices) == 1
        # 至少有一条 debug (尝试) 或 info (成功) 记录, 证明不再静默
        messages = [record.getMessage() for record in caplog.records]
        assert any("ok-debug-test" in m for m in messages), "source 尝试/成功必须发结构化日志 (debug/info), 不再 print"
