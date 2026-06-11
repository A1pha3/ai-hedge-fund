"""Tests for src.cli.dispatcher — 统一 CLI 分发器。

覆盖:
- 辅助函数: ``_has_flag``, ``_get_kv``, ``_next_arg``, ``_parse_int``,
  ``_parse_float``, ``_normalize_date``
- ``COMMAND_REGISTRY`` 包含所有预期的 early-dispatch flag
- ``dispatch()`` 行为: argv 中不含任何早期 flag 时返回 ``None``; 异常被捕获并返回 1
- ``SystemExit`` 被正确转换为 int 退出码
- 多个早期 flag 同时出现时, 按注册表顺序匹配 (pipeline/--screen-only 共用 handler)
- watchlist 多个子命令共享同一个 handler

注: 我们不调用真实的 ``run_*`` 业务函数 (那些有副作用且需要外部数据),
而是用 ``argv`` 替换 + 异常注入的方式验证 dispatch 行为。
"""

from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from src.cli import dispatcher
from src.cli.dispatcher import (
    COMMAND_REGISTRY,
    _get_kv,
    _has_flag,
    _next_arg,
    _normalize_date,
    _parse_float,
    _parse_int,
    dispatch,
)


class TestDispatcherHelpers(unittest.TestCase):
    """辅助函数测试。"""

    def test_has_flag_plain(self) -> None:
        self.assertTrue(_has_flag(["--preheat", "--force"], "--preheat"))
        self.assertFalse(_has_flag(["--force"], "--preheat"))

    def test_has_flag_equals_form(self) -> None:
        self.assertTrue(_has_flag(["--pdf-date=20260101"], "--pdf-date"))
        self.assertTrue(_has_flag(["--pdf-date=20260101", "--force"], "--pdf-date"))

    def test_has_flag_does_not_match_substring(self) -> None:
        # ``--preheat`` 不应匹配 ``--preheat-date``
        self.assertFalse(_has_flag(["--preheat-date=20260101"], "--preheat"))
        self.assertFalse(_has_flag(["--preheat-extra"], "--preheat"))

    def test_get_kv_returns_value(self) -> None:
        self.assertEqual(_get_kv(["--pdf-date=20260101"], "--pdf-date"), "20260101")
        self.assertEqual(
            _get_kv(["--ir-top=10", "--ir-bottom=3"], "--ir-top"),
            "10",
        )

    def test_get_kv_missing(self) -> None:
        self.assertIsNone(_get_kv(["--force"], "--pdf-date"))
        self.assertIsNone(_get_kv(["--pdf-date"], "--pdf-date"))  # 无 = 时不匹配

    def test_next_arg_returns_value(self) -> None:
        self.assertEqual(_next_arg(["--channel", "feishu"], "--channel"), "feishu")
        # 下一个 argv 以 ``-`` 开头视为 flag, 不返回值
        self.assertIsNone(_next_arg(["--channel", "--force"], "--channel"))
        # 下一个 argv 不存在
        self.assertIsNone(_next_arg(["--channel"], "--channel"))

    def test_parse_int_valid_and_default(self) -> None:
        self.assertEqual(_parse_int("10", 5), 10)
        self.assertEqual(_parse_int(None, 5), 5)
        self.assertEqual(_parse_int("not-a-number", 5), 5)  # 错误时回退到 default

    def test_parse_float_valid_and_default(self) -> None:
        self.assertEqual(_parse_float("0.05", 0.1), 0.05)
        self.assertEqual(_parse_float(None, 0.1), 0.1)
        self.assertEqual(_parse_float("xyz", 0.1), 0.1)

    def test_normalize_date_strips_dashes(self) -> None:
        self.assertEqual(_normalize_date("2026-01-01"), "20260101")
        self.assertEqual(_normalize_date("20260101"), "20260101")

    def test_normalize_date_empty_today(self) -> None:
        # empty value + default_today=True -> 今日
        result = _normalize_date(None, default_today=True)
        self.assertEqual(len(result), 8)  # YYYYMMDD
        self.assertTrue(result.isdigit())

    def test_normalize_date_empty_no_default(self) -> None:
        self.assertEqual(_normalize_date(None, default_today=False), "")


class TestCommandRegistry(unittest.TestCase):
    """注册表结构与覆盖范围。"""

    EXPECTED_FLAGS = [
        "--preheat",
        "--daily-gainers",
        "--macro",
        "--performance-report",
        "--market-status",
        "--pipeline",
        "--screen-only",
        "--industry-rotation",
        "--tracking-summary",
        "--export-pdf",
        "--attribution-daily",
        "--factor-ic",
        "--rebalance",
        "--conditional-orders",
        "--push-test",
        "--winrate-dashboard",
        "--verify-recommendations",
        "--cross-picks",
        "--build-portfolio",
        "--calibrate-weights",
        "--stock-detail",
        "--custom-weights",
        "--compare",
        "--watchlist-add",
        "--watchlist-remove",
        "--watchlist-list",
        "--watchlist-status",
        "--expected-returns",
    ]

    def test_registry_is_non_empty(self) -> None:
        self.assertGreater(len(COMMAND_REGISTRY), 10)

    def test_all_expected_flags_registered(self) -> None:
        registered = {flag for flag, _ in COMMAND_REGISTRY}
        for flag in self.EXPECTED_FLAGS:
            self.assertIn(flag, registered, f"Missing flag in registry: {flag}")

    def test_handlers_are_callables(self) -> None:
        for flag, handler in COMMAND_REGISTRY:
            self.assertTrue(callable(handler), f"Handler for {flag} is not callable")

    def test_auto_not_in_registry(self) -> None:
        # ``--auto`` 走主 parser (它本来 ``require_tickers=False``), 不应在这里
        registered = {flag for flag, _ in COMMAND_REGISTRY}
        self.assertNotIn("--auto", registered)
        # ``--explain`` R20.14 改为 dispatcher 早期分发, 以避开 ``--tickers required`` 冲突
        self.assertIn("--explain", registered)


class TestDispatchBehavior(unittest.TestCase):
    """``dispatch()`` 行为测试。"""

    def test_dispatch_empty_returns_none(self) -> None:
        # 无任何 flag -> 走主 parser
        self.assertIsNone(dispatch([]))

    def test_dispatch_random_args_returns_none(self) -> None:
        self.assertIsNone(dispatch(["--tickers", "AAPL"]))

    def test_dispatch_systemexit_converted_to_int(self) -> None:
        # 注入一个会 SystemExit(0) 的 handler
        sentinel = ("--test-sentinel", lambda argv: (_ for _ in ()).throw(SystemExit(0)))
        original = list(dispatcher.COMMAND_REGISTRY)
        try:
            dispatcher.COMMAND_REGISTRY.insert(0, sentinel)
            self.assertEqual(dispatch(["--test-sentinel"]), 0)
        finally:
            dispatcher.COMMAND_REGISTRY[:] = original

    def test_dispatch_systemexit_string_code_becomes_1(self) -> None:
        sentinel = (
            "--test-sentinel-str",
            lambda argv: (_ for _ in ()).throw(SystemExit("boom")),
        )
        original = list(dispatcher.COMMAND_REGISTRY)
        try:
            dispatcher.COMMAND_REGISTRY.insert(0, sentinel)
            self.assertEqual(dispatch(["--test-sentinel-str"]), 1)
        finally:
            dispatcher.COMMAND_REGISTRY[:] = original

    def test_dispatch_handler_exception_caught_returns_1(self) -> None:
        # 注入抛异常的 handler
        def boom(argv: list[str]) -> int | None:
            raise RuntimeError("intentional")

        sentinel = ("--test-boom", boom)
        original = list(dispatcher.COMMAND_REGISTRY)
        try:
            dispatcher.COMMAND_REGISTRY.insert(0, sentinel)
            with patch.object(sys, "stderr") as fake_stderr:
                rc = dispatch(["--test-boom"])
            self.assertEqual(rc, 1)
            self.assertTrue(fake_stderr.write.called)
        finally:
            dispatcher.COMMAND_REGISTRY[:] = original

    def test_dispatch_uses_sys_argv_when_none(self) -> None:
        # ``sys_argv=None`` 应回退到 ``sys.argv[1:]``
        with patch.object(sys, "argv", ["main.py", "--preheat"]):
            # ``--preheat`` handler 会调用 ``run_preheat`` — 真实 import 可能不存在,
            # 但我们要验证: 1) 没有 ``None`` 返回 (即 ``--preheat`` 被识别);
            # 2) 不抛 ``KeyError``。
            # 我们在 ``run_preheat`` 抛出 ``SystemExit(0)`` 模拟成功路径。
            with patch("src.main.run_preheat", return_value=0) as mock:
                rc = dispatch()
            self.assertEqual(rc, 0)
            mock.assert_called_once()

    def test_dispatch_pipeline_and_screen_only_share_handler(self) -> None:
        # ``--pipeline`` 和 ``--screen-only`` 共享 ``_resolve_pipeline`` handler
        pipeline_flag = next(flag for flag, h in COMMAND_REGISTRY if flag == "--pipeline")
        screen_flag = next(flag for flag, h in COMMAND_REGISTRY if flag == "--screen-only")
        pipeline_handler = next(h for flag, h in COMMAND_REGISTRY if flag == pipeline_flag)
        screen_handler = next(h for flag, h in COMMAND_REGISTRY if flag == screen_flag)
        self.assertIs(pipeline_handler, screen_handler)

    def test_dispatch_watchlist_subcommands_share_handler(self) -> None:
        # 4 个 watchlist 子命令共享 ``_resolve_watchlist``
        watchlist_handlers = {
            h for flag, h in COMMAND_REGISTRY if flag.startswith("--watchlist-")
        }
        self.assertEqual(len(watchlist_handlers), 1)


class TestDispatchEarlyFlags(unittest.TestCase):
    """每个早期 flag 应被 dispatch 识别 (不返回 None)。"""

    def test_preheat_flag_recognized(self) -> None:
        # 注入 mock 让 ``run_preheat`` 返回 0
        with patch("src.main.run_preheat", return_value=0) as mock:
            rc = dispatch(["--preheat"])
        self.assertEqual(rc, 0)
        mock.assert_called_once()

    def test_daily_gainers_flag_recognized(self) -> None:
        with patch("src.main.run_daily_gainers_cli", return_value=0) as mock:
            rc = dispatch(["--daily-gainers"])
        self.assertEqual(rc, 0)
        mock.assert_called_once()

    def test_market_status_flag_recognized(self) -> None:
        with patch("src.main.run_market_status", return_value=0) as mock:
            rc = dispatch(["--market-status"])
        self.assertEqual(rc, 0)
        # ``run_market_status`` 应被调用, 并传入今日日期 (8 位)
        args, _ = mock.call_args
        self.assertEqual(len(args[0]), 8)
        self.assertTrue(args[0].isdigit())

    def test_industry_rotation_with_kv_args(self) -> None:
        with patch("src.main.run_industry_rotation", return_value=0) as mock:
            rc = dispatch(
                [
                    "--industry-rotation",
                    "--ir-date=20260101",
                    "--ir-top=10",
                    "--ir-bottom=2",
                ]
            )
        self.assertEqual(rc, 0)
        # 检查传参: 第一个位置参数是 trade_date
        call_args = mock.call_args
        self.assertEqual(call_args.args[0], "20260101")
        self.assertEqual(call_args.kwargs["top_n"], 10)
        self.assertEqual(call_args.kwargs["bottom_n"], 2)

    def test_stock_detail_missing_ticker_returns_1(self) -> None:
        # 没有 ticker 时应打印用法并返回 1
        rc = dispatch(["--stock-detail"])
        self.assertEqual(rc, 1)

    def test_stock_detail_equals_form(self) -> None:
        with patch("src.screening.stock_detail.run_stock_detail_cli", return_value=0) as mock:
            rc = dispatch(["--stock-detail=300750"])
        self.assertEqual(rc, 0)
        mock.assert_called_once_with("300750", trade_date=None)

    def test_compare_missing_tickers_returns_1(self) -> None:
        rc = dispatch(["--compare"])
        self.assertEqual(rc, 1)

    def test_compare_equals_form(self) -> None:
        with patch("src.screening.compare_tool.run_compare_cli", return_value=0) as mock:
            rc = dispatch(["--compare=300750,600519", "--no-radar"])
        self.assertEqual(rc, 0)
        call_args = mock.call_args
        self.assertEqual(call_args.kwargs["tickers_arg"], "300750,600519")
        self.assertEqual(call_args.kwargs["show_radar"], False)

    def test_custom_weights_parses_floats(self) -> None:
        with patch("src.main.run_custom_weights", return_value=0) as mock:
            rc = dispatch(
                [
                    "--custom-weights",
                    "--trend=0.4",
                    "--mean-reversion=0.2",
                    "--fundamental=0.3",
                    "--event-sentiment=0.1",
                    "--top-n=5",
                ]
            )
        self.assertEqual(rc, 0)
        kwargs = mock.call_args.kwargs
        self.assertAlmostEqual(kwargs["trend"], 0.4)
        self.assertAlmostEqual(kwargs["mean_reversion"], 0.2)
        self.assertAlmostEqual(kwargs["fundamental"], 0.3)
        self.assertAlmostEqual(kwargs["event_sentiment"], 0.1)
        self.assertEqual(kwargs["top_n"], 5)


if __name__ == "__main__":
    unittest.main()
