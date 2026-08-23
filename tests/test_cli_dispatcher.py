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
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from src.cli import dispatcher
from src.cli.dispatcher import (
    _get_kv,
    _has_flag,
    _next_arg,
    _normalize_date,
    _parse_float,
    _parse_int,
    COMMAND_REGISTRY,
    dispatch,
)


def run_daily_action_cli_fixture(*, reports_dir: Path) -> int | None:
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    signal_date = date(2026, 7, 13)
    with (
        patch("src.screening.consecutive_recommendation.resolve_report_dir", return_value=reports_dir),
        patch("src.screening.offensive.daily_action.resolve_daily_action_signal", return_value=(signal_date, "normal")),
        patch("builtins.print"),
    ):
        return dispatcher._resolve_daily_action(
            ["--daily-action"],
            open_sessions=(signal_date, signal_date + timedelta(days=1)),
            ledger_path=reports_dir.parent / "ledger.sqlite3",
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

    def test_registry_flags_are_unique(self) -> None:
        flags = [flag for flag, _ in COMMAND_REGISTRY]
        duplicates = sorted({flag for flag in flags if flags.count(flag) > 1})
        self.assertEqual(duplicates, [], f"Duplicate flags in registry: {duplicates}")

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
        watchlist_handlers = {h for flag, h in COMMAND_REGISTRY if flag.startswith("--watchlist-")}
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

    def test_daily_action_renders_actual_scan_trade_date(self) -> None:
        """--daily-action resolves the signal date via the lightweight resolver."""
        from datetime import date, datetime

        from src.screening.offensive.daily_action import _CN_TZ

        # R90: 硬编码历史日期必须同时冻结时钟, 否则入场窗口护栏随日历漂移
        # 把"当前"钉在信号日当晚 (已过收盘、未到 T+1 09:30), 窗口保持开放.
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch(
                    "src.screening.offensive.daily_action.resolve_daily_action_signal",
                    return_value=(date(2026, 7, 10), "normal"),
                ),
                patch(
                    "src.screening.offensive.daily_action.scan_daily_action_candidates"
                ) as legacy_scan,
                patch(
                    "src.screening.offensive.daily_action._current_cn_datetime",
                    return_value=datetime(2026, 7, 10, 21, 0, tzinfo=_CN_TZ),
                ),
                patch("builtins.print") as output,
            ):
                rc = dispatcher._resolve_daily_action(
                    ["--daily-action"],
                    open_sessions=(date(2026, 7, 10), date(2026, 7, 13)),
                    ledger_path=Path(tmp) / "v2.sqlite3",
                )

        # 时钟冻结在信号日当晚 → 入场窗口开放; tmp 目录无就绪清单 → 数据护栏阻断 rc=13
        self.assertEqual(rc, 13)
        self.assertIn("每日动作 · 信号日 2026-07-10", output.call_args.args[0])
        # Task 8: the production path must NOT run the legacy full-market scan
        # that reopens cache files just to derive the signal date.
        legacy_scan.assert_not_called()

    def test_daily_action_v2_path_runs_signal_coverage_sentinel(self) -> None:
        """--daily-action v2 生产路径必须跑信号覆盖哨点 (2026-08-18 审查项 2).

        哨点原先只挂在 legacy generate_daily_action — 生产路径走
        scan_from_verified_snapshot + DailyActionService, 从不经过它,
        19/30 交易日断跑在本路径零检测 (华正新材型漏信号重演风险)."""
        from datetime import date, datetime

        from src.screening.offensive.daily_action import _CN_TZ

        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch(
                    "src.screening.offensive.daily_action.resolve_daily_action_signal",
                    return_value=(date(2026, 7, 10), "normal"),
                ),
                patch(
                    "src.screening.offensive.daily_action._current_cn_datetime",
                    return_value=datetime(2026, 7, 10, 21, 0, tzinfo=_CN_TZ),
                ),
                patch(
                    "src.screening.offensive.setup_output_log.warn_missing_signal_log_sessions",
                    return_value=[],
                ) as warn_sentinel,
                patch("builtins.print"),
            ):
                rc = dispatcher._resolve_daily_action(
                    ["--daily-action"],
                    open_sessions=(date(2026, 7, 10), date(2026, 7, 13)),
                    ledger_path=Path(tmp) / "v2.sqlite3",
                )

        # 哨点以信号日为界审计 (before=YYYYMMDD), 无论就绪是否阻断都要跑.
        warn_sentinel.assert_called_once_with(before="20260710")
        # tmp 目录无就绪清单 → 数据护栏阻断 rc=13 (与既有契约一致).
        self.assertEqual(rc, 13)

    def test_daily_action_passes_end_date_override(self) -> None:
        """--daily-action --end-date=YYYY-MM-DD 应规范化成 YYYYMMDD 传给 signal 解析."""

        from datetime import date
        with tempfile.TemporaryDirectory() as tmp, patch(
            "src.screening.offensive.daily_action.resolve_daily_action_signal",
            return_value=(date(2026, 7, 6), "normal"),
        ) as resolver, patch("builtins.print"):
            rc = dispatcher._resolve_daily_action(
                ["--daily-action", "--end-date=2026-07-06"],
                open_sessions=(date(2026, 7, 6), date(2026, 7, 7)),
                ledger_path=Path(tmp) / "v2.sqlite3",
            )

        # 历史日期 + 真实时钟 → 已过入场日 09:30, 入场窗口守卫触发 (策略性停手 rc=14)
        self.assertEqual(rc, 14)
        # 带横线的 YYYY-MM-DD 应规范化成 YYYYMMDD
        self.assertEqual(resolver.call_args.kwargs.get("end_date"), "20260706")

    def test_daily_action_passes_end_date_space_form(self) -> None:
        """--daily-action --end-date YYYY-MM-DD (空格分隔) 也应解析."""

        from datetime import date
        with tempfile.TemporaryDirectory() as tmp, patch(
            "src.screening.offensive.daily_action.resolve_daily_action_signal",
            return_value=(date(2026, 7, 6), "normal"),
        ) as resolver, patch("builtins.print"):
            rc = dispatcher._resolve_daily_action(
                ["--daily-action", "--end-date", "20260706"],
                open_sessions=(date(2026, 7, 6), date(2026, 7, 7)),
                ledger_path=Path(tmp) / "v2.sqlite3",
            )

        self.assertEqual(rc, 14)  # 入场窗口守卫 (历史日期 + 真实时钟)
        # YYYYMMDD (无横线) 保持不变
        self.assertEqual(resolver.call_args.kwargs.get("end_date"), "20260706")

    def test_daily_action_no_end_date_passes_none(self) -> None:
        """不带 --end-date 时 end_date 应为 None (走 17:00 规则)."""

        from datetime import date
        with tempfile.TemporaryDirectory() as tmp, patch(
            "src.screening.offensive.daily_action.resolve_daily_action_signal",
            return_value=(date(2026, 7, 6), "normal"),
        ) as resolver, patch("builtins.print"):
            rc = dispatcher._resolve_daily_action(
                ["--daily-action"],
                open_sessions=(date(2026, 7, 6), date(2026, 7, 7)),
                ledger_path=Path(tmp) / "v2.sqlite3",
            )

        self.assertEqual(rc, 14)  # 入场窗口守卫 (历史日期 + 真实时钟)
        self.assertIsNone(resolver.call_args.kwargs.get("end_date"))
        self.assertEqual(
            resolver.call_args.kwargs.get("open_sessions"),
            (date(2026, 7, 6), date(2026, 7, 7)),
        )

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


def test_cli_test_fixture_never_writes_workspace_reports(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reports_dir = tmp_path / "reports"
    # 真实时钟下历史信号日触发入场窗口守卫 → 策略性停手 rc=14
    assert run_daily_action_cli_fixture(reports_dir=reports_dir) == 14
    assert not Path("data/reports").exists()


def test_daily_action_blocked_conclusion_comes_first(tmp_path, monkeypatch):
    """阻断日的 ⛔ 结论必须在正文标题之前 (结论先行) — 此前 append 在末尾,
    操作员要翻完整屏才看到当天最重要的事实."""
    monkeypatch.chdir(tmp_path)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    signal_date = date(2026, 7, 13)
    with (
        patch("src.screening.consecutive_recommendation.resolve_report_dir", return_value=reports_dir),
        patch("src.screening.offensive.daily_action.resolve_daily_action_signal", return_value=(signal_date, "normal")),
        patch("builtins.print") as output,
    ):
        rc = dispatcher._resolve_daily_action(
            ["--daily-action"],
            open_sessions=(signal_date, signal_date + timedelta(days=1)),
            ledger_path=tmp_path / "ledger.sqlite3",
        )
    assert rc == 14  # 入场窗口守卫 (历史信号日 + 真实时钟) → 策略性停手
    rendered = output.call_args.args[0]
    assert "结论：⛔ 数据护栏阻断新计划" in rendered
    assert rendered.find("结论：⛔") < rendered.find("每日动作 · 信号日")


def test_daily_action_runlevel_block_gets_conclusion(tmp_path, monkeypatch):
    """G1: service 层阻断 (回撤熔断等) 无快照阻断时也要有结论 — 此前默认视图
    对"为何无计划"只字不提, 甚至落到"系统健康，今日无信号"的误报."""
    from datetime import datetime
    from types import SimpleNamespace

    from src.screening.offensive.daily_action import _CN_TZ

    monkeypatch.chdir(tmp_path)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    signal_date = date(2026, 7, 13)
    run = SimpleNamespace(
        plans=(),
        blocked_candidates=(),
        open_positions=(),
        service_run=SimpleNamespace(block_reasons=("drawdown_circuit_breaker",)),
    )
    with (
        patch("src.screening.consecutive_recommendation.resolve_report_dir", return_value=reports_dir),
        patch("src.screening.offensive.daily_action.resolve_daily_action_signal", return_value=(signal_date, "normal")),
        # 入场窗口护栏: 固定"当前时刻"为信号日 21:00 (次日入场窗口未过),
        # 否则真实时钟 > 入场日 09:30 会先触发 entry_window_missed 快照阻断.
        patch(
            "src.screening.offensive.daily_action._current_cn_datetime",
            return_value=datetime(2026, 7, 13, 21, 0, tzinfo=_CN_TZ),
        ),
        patch(
            "src.screening.offensive.daily_action_snapshot.load_verified_daily_action_snapshot",
            return_value=SimpleNamespace(snapshot=SimpleNamespace(regime="normal", signal_date=signal_date), global_reason=None),
        ),
        patch("src.screening.offensive.daily_action.scan_from_verified_snapshot", return_value=SimpleNamespace(signal_date=signal_date, candidates=(), blocked_candidates=(), reference_prices=())),
        patch("src.screening.offensive.daily_action.complete_daily_action_v2", return_value=run),
        patch("src.screening.offensive.daily_action.render_daily_action_v2", return_value="正文"),
        patch("builtins.print") as output,
    ):
        rc = dispatcher._resolve_daily_action(
            ["--daily-action"],
            open_sessions=(signal_date, signal_date + timedelta(days=1), signal_date + timedelta(days=7)),
            ledger_path=tmp_path / "ledger.sqlite3",
        )
    assert rc == 14  # 回撤熔断 → 策略性停手
    rendered = output.call_args.args[0]
    assert "结论：⛔ 运行护栏阻断新计划" in rendered
    assert "组合回撤熔断" in rendered
    assert "系统健康" not in rendered
    assert rendered.find("结论：⛔") < rendered.find("正文")


class _FakeStream:
    """Minimal non-TTY (or TTY) stream for color-init tests."""

    def __init__(self, *, tty: bool):
        self.buf = ""
        self._tty = tty
        self.closed = False

    def isatty(self):
        return self._tty

    def write(self, s):
        self.buf += s
        return len(s)

    def flush(self):
        pass


def test_init_color_strips_ansi_when_piped(monkeypatch):
    """非 TTY (launchd/cron 日志) 下 ANSI 色码必须被剥离 — 日志可读性."""
    import colorama

    from src.cli.dispatcher import _init_color_for_stream

    fake = _FakeStream(tty=False)
    monkeypatch.setattr(sys, "stdout", fake)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    try:
        _init_color_for_stream()
        print("\x1b[32mgreen\x1b[0m")
        assert "\x1b" not in fake.buf
        assert "green" in fake.buf
    finally:
        colorama.deinit()


def test_init_color_force_color_keeps_ansi_when_piped(monkeypatch):
    """FORCE_COLOR 在管道中强制保留色码 (如 `| less -R`)."""
    import colorama

    from src.cli.dispatcher import _init_color_for_stream

    fake = _FakeStream(tty=False)
    monkeypatch.setattr(sys, "stdout", fake)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    try:
        _init_color_for_stream()
        print("\x1b[32mgreen\x1b[0m")
        assert "\x1b[32m" in fake.buf
    finally:
        colorama.deinit()


def test_init_color_no_color_strips_even_on_tty(monkeypatch):
    """NO_COLOR 显式关色, 即使是 TTY."""
    import colorama

    from src.cli.dispatcher import _init_color_for_stream

    fake = _FakeStream(tty=True)
    monkeypatch.setattr(sys, "stdout", fake)
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    try:
        _init_color_for_stream()
        print("\x1b[32mgreen\x1b[0m")
        assert "\x1b" not in fake.buf
    finally:
        colorama.deinit()


if __name__ == "__main__":
    unittest.main()


class TestDailyActionExitCode:
    """--daily-action 退出码语义: 0 正常 / 13 数据护栏阻断 / 14 策略性停手.

    阻断夜与正常夜同为 0 曾是 launchd 监控盲区 (静默事故不可见).
    """

    def _code(self, **kw) -> int:
        from src.cli.dispatcher import _daily_action_exit_code

        defaults = dict(
            snapshot_block_reason=None,
            run_block_reasons=(),
            actionable_blocked_reasons=(),
            has_plans=False,
        )
        defaults.update(kw)
        return _daily_action_exit_code(**defaults)

    def test_normal_days_are_zero(self):
        assert self._code(has_plans=True) == 0
        # 健康无信号日
        assert self._code() == 0
        # 日常强度门禁拦截是健康过滤, 不是异常
        assert self._code(actionable_blocked_reasons=("trigger_strength_below_threshold",)) == 0
        # 混合拦截 (含 regime 闸但不全是) 不算全闸日
        assert self._code(actionable_blocked_reasons=("regime_gate_halt", "stale_price_cache")) == 0

    def test_data_guard_blocks_are_13(self):
        assert self._code(snapshot_block_reason="daily_action_readiness_missing") == 13
        assert self._code(snapshot_block_reason="readiness_scan_failed") == 13
        assert self._code(snapshot_block_reason="snapshot_fingerprint_mismatch") == 13
        assert self._code(run_block_reasons=("calendar_unavailable",)) == 13

    def test_policy_halts_are_14(self):
        # 入场窗口时机守卫
        assert self._code(snapshot_block_reason="entry_window_missed") == 14
        # 组合回撤熔断
        assert self._code(run_block_reasons=("drawdown_circuit_breaker",)) == 14
        # 危机日 regime 全闸 (无计划且全部可操作拦截都是 regime_gate_halt)
        assert self._code(actionable_blocked_reasons=("regime_gate_halt", "regime_gate_halt")) == 14

    def test_snapshot_block_takes_precedence_over_run_blocks(self):
        assert self._code(
            snapshot_block_reason="daily_action_readiness_missing",
            run_block_reasons=("drawdown_circuit_breaker",),
        ) == 13


def test_daily_action_log_write_failure_blocks_new_plans(tmp_path, monkeypatch):
    """证据写入失败 = 运行失败 (2026-08-23 Item 3): 新计划阻断, 走 run_block 结论.

    此前 `except → debug` 让证据丢失不可见, 计划在无证据行的情况下照建 —
    2026-08-20 事件的第一因. 现在写失败必须阻断 + 结论先行.
    """
    from datetime import datetime
    from types import SimpleNamespace

    from src.screening.offensive.daily_action import _CN_TZ

    monkeypatch.chdir(tmp_path)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    signal_date = date(2026, 7, 13)
    run = SimpleNamespace(
        plans=(),
        blocked_candidates=(),
        open_positions=(),
        service_run=SimpleNamespace(
            block_reasons=("setup_output_log_write_failed",)
        ),
    )
    with (
        patch("src.screening.consecutive_recommendation.resolve_report_dir", return_value=reports_dir),
        patch("src.screening.offensive.daily_action.resolve_daily_action_signal", return_value=(signal_date, "normal")),
        patch(
            "src.screening.offensive.daily_action._current_cn_datetime",
            return_value=datetime(2026, 7, 13, 21, 0, tzinfo=_CN_TZ),
        ),
        patch(
            "src.screening.offensive.daily_action_snapshot.load_verified_daily_action_snapshot",
            return_value=SimpleNamespace(snapshot=SimpleNamespace(regime="normal", signal_date=signal_date), global_reason=None),
        ),
        patch(
            "src.screening.offensive.daily_action.scan_from_verified_snapshot",
            return_value=SimpleNamespace(signal_date=signal_date, candidates=(), blocked_candidates=(), reference_prices=()),
        ),
        patch(
            "src.screening.offensive.setup_output_log.log_setup_outputs",
            side_effect=OSError("disk full"),
        ) as log_write,
        patch(
            "src.screening.offensive.daily_action.complete_daily_action_v2",
            return_value=run,
        ) as complete,
        patch("src.screening.offensive.daily_action.render_daily_action_v2", return_value="正文"),
        patch("builtins.print") as output,
    ):
        rc = dispatcher._resolve_daily_action(
            ["--daily-action"],
            open_sessions=(signal_date, signal_date + timedelta(days=1), signal_date + timedelta(days=7)),
            ledger_path=tmp_path / "ledger.sqlite3",
        )
    assert rc == 13  # 数据护栏阻断 (写失败需排查重跑), 非策略性停手
    # 写失败必须传导为 new_entry_block, 而不是静默继续建计划
    assert complete.call_args.kwargs.get("new_entry_block") == "setup_output_log_write_failed"
    rendered = output.call_args.args[0]
    assert "信号日志写入失败" in rendered
    assert rendered.find("结论：⛔") < rendered.find("正文")


def test_daily_action_log_write_passes_plan_backed_tickers(tmp_path, monkeypatch):
    """台账写守卫接线 (Item 1): 本信号日已有计划的票传给日志守卫."""
    from datetime import datetime
    from types import SimpleNamespace

    from src.screening.offensive.daily_action import _CN_TZ

    monkeypatch.chdir(tmp_path)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    signal_date = date(2026, 7, 13)
    run = SimpleNamespace(
        plans=(),
        blocked_candidates=(),
        open_positions=(),
        service_run=SimpleNamespace(block_reasons=()),
    )
    with (
        patch("src.screening.consecutive_recommendation.resolve_report_dir", return_value=reports_dir),
        patch("src.screening.offensive.daily_action.resolve_daily_action_signal", return_value=(signal_date, "normal")),
        patch(
            "src.screening.offensive.daily_action._current_cn_datetime",
            return_value=datetime(2026, 7, 13, 21, 0, tzinfo=_CN_TZ),
        ),
        patch(
            "src.screening.offensive.daily_action_snapshot.load_verified_daily_action_snapshot",
            return_value=SimpleNamespace(snapshot=SimpleNamespace(regime="normal", signal_date=signal_date), global_reason=None),
        ),
        patch(
            "src.screening.offensive.daily_action.scan_from_verified_snapshot",
            return_value=SimpleNamespace(signal_date=signal_date, candidates=(), blocked_candidates=(), reference_prices=()),
        ),
        patch(
            "src.screening.offensive.setup_output_log.log_setup_outputs",
            return_value=tmp_path / "log.jsonl",
        ) as log_write,
        patch("src.screening.offensive.daily_action.complete_daily_action_v2", return_value=run),
        patch("src.screening.offensive.daily_action.render_daily_action_v2", return_value="正文"),
        patch("builtins.print"),
    ):
        dispatcher._resolve_daily_action(
            ["--daily-action"],
            open_sessions=(signal_date, signal_date + timedelta(days=1), signal_date + timedelta(days=7)),
            ledger_path=tmp_path / "ledger.sqlite3",
        )
    # 空台账 → 守卫参数为空集 (键存在即可证接线)
    assert "plan_backed_tickers" in log_write.call_args.kwargs
    assert log_write.call_args.kwargs["plan_backed_tickers"] == set()
