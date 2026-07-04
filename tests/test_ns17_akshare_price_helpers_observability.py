"""NS-17 family sibling drain: akshare_price_helpers.py print()→logger observability.

`src/tools/akshare_price_helpers.py` holds the multi-tier A-share price fallback
chain (execute_robust_price_request: AKShare → 新浪 → Tushare/BaoStock → mock)
plus load_prices_with_fallback (AKShare → Tencent). These are the core price-
acquisition paths behind get_prices_robust / akshare_api.get_prices — the most-
reached price surface in the system (main pipeline, backtest, north-star backfill).

Before this drain the module had NO module logger and 8 print() calls. In cron /
launchd contexts print() goes to stdout which operators never inspect, so a
silently-failing price tier degrades the fallback chain with zero diagnostic
breadcrumb — operators cannot tell which tier failed or why the chain bottomed
out (to mock or to empty). Mirrors the BH-017 family pattern drained across
ashare_data_sources (c280) + tushare_api (c281).
"""

from __future__ import annotations

import logging

from src.tools import akshare_price_helpers


class TestAksharePriceHelpersModuleLogger:
    """NS-17 family: akshare_price_helpers must have a module logger."""

    def test_module_logger_exists(self) -> None:
        """模块必须有 logger (此前无 logging, 8 处 print 不入结构化日志)。"""
        assert hasattr(akshare_price_helpers, "logger"), "akshare_price_helpers 必须有 module logger (NS-17 / BH-017 family 可观测性要求)"
        assert isinstance(akshare_price_helpers.logger, logging.Logger)
        assert akshare_price_helpers.logger.name == "src.tools.akshare_price_helpers"

    def test_no_print_calls_remain(self) -> None:
        """模块源码不再含裸 print() 调用 (注释/字符串字面量除外)。"""
        import inspect

        source = inspect.getsource(akshare_price_helpers)
        code_lines = [line for line in source.splitlines() if line.lstrip().startswith("print(") and not line.lstrip().startswith("#")]
        assert not code_lines, f"akshare_price_helpers 不应再有裸 print() 调用, 发现: {code_lines}"


class TestExecuteRobustPriceRequestObservability:
    """NS-17 family: 四级价格回退链须用结构化日志, 不再 print。

    execute_robust_price_request 是 get_prices_robust 的核心。每个 tier 失败静默
    回退下一级, 运维无法定位"为何最终拿到 mock/空数据"。drain 后每 tier 尝试
    用 debug, 失败用 warning。
    """

    def test_all_tiers_failure_emits_warnings(self, monkeypatch, caplog) -> None:
        """所有 tier 失败时每级须发 warning, 最终 raise。"""

        def _boom(*args, **kwargs):
            raise RuntimeError("tier failure")

        with caplog.at_level(logging.WARNING, logger="src.tools.akshare_price_helpers"):
            try:
                akshare_price_helpers.execute_robust_price_request(
                    ticker="000001",
                    start_date="2026-01-01",
                    end_date="2026-01-02",
                    period="daily",
                    use_mock_on_fail=False,
                    get_prices_fn=_boom,
                    get_sina_historical_data_fn=_boom,
                    get_prices_multi_source_fn=_boom,
                    get_mock_prices_fn=lambda *a, **k: [],
                    error_factory=RuntimeError,
                )
            except RuntimeError:
                pass

        # 三级失败 (AKShare/新浪/多源) 至少各发一条 warning
        failure_msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(failure_msgs) >= 3, f"三级 tier 失败至少须发 3 条 warning, 实际 {len(failure_msgs)}: {failure_msgs}"

    def test_first_tier_success_no_warning(self, monkeypatch, caplog) -> None:
        """第一 tier 成功时不应发 warning。"""

        def _ok(ticker, start_date, end_date, period, use_mock):
            from src.data.models import Price

            return [Price(time="2026-01-01", open=1.0, high=1.0, low=1.0, close=1.0, volume=100)]

        with caplog.at_level(logging.WARNING, logger="src.tools.akshare_price_helpers"):
            prices = akshare_price_helpers.execute_robust_price_request(
                ticker="000001",
                start_date="2026-01-01",
                end_date="2026-01-02",
                period="daily",
                use_mock_on_fail=False,
                get_prices_fn=_ok,
                get_sina_historical_data_fn=lambda *a, **k: [],
                get_prices_multi_source_fn=lambda *a, **k: [],
                get_mock_prices_fn=lambda *a, **k: [],
                error_factory=RuntimeError,
            )

        assert len(prices) == 1
        assert not any(r.levelno >= logging.WARNING for r in caplog.records), "第一 tier 成功时不应发 warning"


class TestLoadPricesWithFallbackObservability:
    """NS-17 family: AKShare→Tencent 回退的 akshare 失败须可观测。"""

    def test_akshare_failure_emits_warning(self, monkeypatch, caplog) -> None:
        """AKShare 失败回退 Tencent 时须发 warning (此前静默 print)。"""

        def _boom_akshare(ak_module, ticker, start, end, period):
            raise RuntimeError("akshare failure")

        def _ok_tencent(ticker, start, end):
            from src.data.models import Price

            return [Price(time="2026-01-01", open=1.0, high=1.0, low=1.0, close=1.0, volume=100)]

        with caplog.at_level(logging.WARNING, logger="src.tools.akshare_price_helpers"):
            prices = akshare_price_helpers.load_prices_with_fallback(
                ticker="000001",
                start_date="2026-01-01",
                end_date="2026-01-02",
                period="daily",
                ak_module=None,
                fetch_prices_from_akshare_fn=_boom_akshare,
                fetch_prices_from_tencent_fn=_ok_tencent,
                cache_prices_fn=lambda key, p: p,
                cache_key="test-key",
                error_factory=RuntimeError,
            )

        assert len(prices) == 1  # Tencent 回退成功
        assert any("AKShare" in r.getMessage() and r.levelno >= logging.WARNING for r in caplog.records), "AKShare 失败回退 Tencent 必须发 logger.warning"
