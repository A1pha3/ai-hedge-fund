"""NS-17 family sibling drain: tushare fundamental-data helpers print()→logger.

Batch covers two modules on the fundamental-data path:
- tushare_line_items_helpers.py: fetch_line_item_statement_frames (fina_indicator)
  + _fetch_optional_frame (balancesheet/cashflow/income). Fundamental agents
    (bill_ackman / phil_fisher / valuation) read line items; a silent frame-
    fetch failure returns None → agent scores on partial/missing fundamentals.
- tushare_daily_basic_helpers.py: load_daily_basic_batch (PE/PB/PS). PE/PB feed
    valuation + composite_score; silent batch fetch failure returns empty df →
    all PE/PB lookups miss → valuation degrades with zero breadcrumb.

Both modules had NO module logger and used print() for fetch failures. In cron /
launchd contexts print() goes to stdout which operators never inspect, so a
failing financial-statement / daily_basic fetch silently degrades the
fundamental + valuation path. Mirrors the BH-017 family drained across
ashare_data_sources (c280), tushare_api (c281), akshare_price_helpers (c282),
akshare_api (c283).
"""

from __future__ import annotations

import logging

from src.tools import tushare_daily_basic_helpers, tushare_line_items_helpers


class TestLineItemsHelpersModuleLogger:
    def test_module_logger_exists(self) -> None:
        assert hasattr(tushare_line_items_helpers, "logger")
        assert isinstance(tushare_line_items_helpers.logger, logging.Logger)
        assert tushare_line_items_helpers.logger.name == "src.tools.tushare_line_items_helpers"

    def test_no_print_calls_remain(self) -> None:
        import inspect

        source = inspect.getsource(tushare_line_items_helpers)
        code_lines = [ln for ln in source.splitlines() if ln.lstrip().startswith("print(") and not ln.lstrip().startswith("#")]
        assert not code_lines, f"残留 print(): {code_lines}"


class TestLineItemsFetchFailureObservability:
    """fina_indicator / 可选报表拉取失败须可观测。"""

    def test_fina_indicator_failure_emits_warning(self, caplog) -> None:
        def _boom(*a, **k):
            raise RuntimeError("fina fetch failure")

        with caplog.at_level(logging.WARNING, logger="src.tools.tushare_line_items_helpers"):
            df_fin, df_bal, df_cash, df_income = tushare_line_items_helpers.fetch_line_item_statement_frames(_boom, None, "000001.SZ", 10)

        assert df_fin is None
        assert any("财务指标" in r.getMessage() and r.levelno >= logging.WARNING for r in caplog.records), "fina_indicator 失败必须发 logger.warning"

    def test_optional_frame_failure_emits_warning(self, caplog) -> None:
        def _boom(*a, **k):
            raise RuntimeError("balancesheet fetch failure")

        with caplog.at_level(logging.WARNING, logger="src.tools.tushare_line_items_helpers"):
            df = tushare_line_items_helpers._fetch_optional_frame(_boom, None, "balancesheet", "000001.SZ", 10, "资产负债表")

        assert df is None
        assert any("资产负债表" in r.getMessage() and r.levelno >= logging.WARNING for r in caplog.records), "可选报表失败必须发 logger.warning"


class TestDailyBasicHelpersModuleLogger:
    def test_module_logger_exists(self) -> None:
        assert hasattr(tushare_daily_basic_helpers, "logger")
        assert isinstance(tushare_daily_basic_helpers.logger, logging.Logger)
        assert tushare_daily_basic_helpers.logger.name == "src.tools.tushare_daily_basic_helpers"

    def test_no_print_calls_remain(self) -> None:
        import inspect

        source = inspect.getsource(tushare_daily_basic_helpers)
        code_lines = [ln for ln in source.splitlines() if ln.lstrip().startswith("print(") and not ln.lstrip().startswith("#")]
        assert not code_lines, f"残留 print(): {code_lines}"


class TestDailyBasicBatchFailureObservability:
    """daily_basic 批量拉取失败须可观测 (PE/PB/PS 路径)。"""

    def test_batch_query_failure_emits_warning(self, caplog) -> None:
        class _BoomPro:
            def query(self, *a, **k):
                raise RuntimeError("daily_basic batch failure")

        with caplog.at_level(logging.WARNING, logger="src.tools.tushare_daily_basic_helpers"):
            df = tushare_daily_basic_helpers.load_daily_basic_batch(
                pro=_BoomPro(),
                ts_code="000001.SZ",
                anchor_date="2026-01-01",
                cache_key="test-cache-key",
                get_cached_df=lambda key: None,
                store_cached_df=lambda key, df: None,
            )

        # 失败时回退空 DataFrame (非 None)
        assert df is not None
        assert df.empty
        assert any("daily_basic" in r.getMessage() and r.levelno >= logging.WARNING for r in caplog.records), "daily_basic 批量拉取失败必须发 logger.warning"

    def test_date_parse_failure_emits_warning(self, caplog) -> None:
        """anchor_date 格式异常导致日期解析失败必须发 logger.warning (NS-17 c273).

        原先 line 32 的 ``except Exception: return None`` 静默吞掉 ValueError,
        运维无法区分 "ts_code 无 daily_basic 数据" 与 "上游传入畸形 anchor_date"。
        此测试覆盖 best-effort 契约 (返回 None) + 可观测性 (warning 发出)。
        """
        with caplog.at_level(logging.WARNING, logger="src.tools.tushare_daily_basic_helpers"):
            df = tushare_daily_basic_helpers.load_daily_basic_batch(
                pro=None,  # 不会到达 pro.query 调用
                ts_code="000001.SZ",
                anchor_date="not-a-date",  # strptime 会抛 ValueError
                cache_key="test-cache-key",
                get_cached_df=lambda key: None,
                store_cached_df=lambda key, df: None,
            )

        assert df is None
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1, "date parse 失败必须发 1 条 warning"
        msg = warnings[0].getMessage()
        assert "date parse failed" in msg
        assert "000001.SZ" in msg
        assert "not-a-date" in msg
