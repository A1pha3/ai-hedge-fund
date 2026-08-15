"""--auto 表格级展示契约测试 (F1 池胜率列 / F2 numparse / F8 日期与市场状态)
+ --daily-action 成交价缺失守卫 (F10).

行级契约见 test_score_decomposition.py::TestAutoScreeningTableCompositeColumn;
本文件钉住整张表的端到端渲染.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.main import (
    _format_trade_date_display,
    _market_state_display,
    _print_auto_screening_table,
)
from src.screening.models import FusedScore, StrategySignal


def _item(ticker: str = "000001", score_b: float = 0.357) -> FusedScore:
    return FusedScore(
        ticker=ticker,
        name="测试股",
        industry_sw="电子",
        score_b=score_b,
        strategy_signals={
            "trend": StrategySignal(direction=1, confidence=50.0, completeness=1.0, sub_factors={}),
            "mean_reversion": StrategySignal(direction=0, confidence=59.8, completeness=1.0, sub_factors={}),
        },
        weights_used={"trend": 0.4, "mean_reversion": 0.2, "fundamental": 0.3, "event_sentiment": 0.1},
        decision="watch",
    )


def _render_table(capsys: pytest.CaptureFixture[str]) -> str:
    _print_auto_screening_table(
        "20260814",
        [_item()],
        SimpleNamespace(state_type="mixed", position_scale=1.0),
        300,
        10,
        Path("data/reports/auto_screening_20260814.json"),
        consecutive_recommendations=[],
        composite_by_ticker={"000001": 0.457},
        bucket_stats={"000001": (0.4825, 428)},
    )
    return capsys.readouterr().out


def test_table_shows_bucket_winrate_as_primary_sort_key(capsys: pytest.CaptureFixture[str]) -> None:
    """F1: 排序主键 (池胜率) 必须入表, 图例必须指向它 — 否则综合分非单调像 bug."""
    output = _render_table(capsys)
    assert "池胜率" in output
    assert "48%·428" in output
    assert "排序看「池胜率」" in output


def test_table_preserves_explicit_number_formatting(capsys: pytest.CaptureFixture[str]) -> None:
    """F2: tabulate numparse 不得吃掉显式格式 — "+0.3570" 的符号与尾零保留."""
    output = _render_table(capsys)
    assert "+0.3570" in output
    assert "0.357 " not in output  # 尾零被 %g 吃掉的旧形态


def test_table_neutral_signal_has_no_confidence_number(capsys: pytest.CaptureFixture[str]) -> None:
    """F3: 无信号策略在表格信号列只显示裸 "—", 不带信心数."""
    output = _render_table(capsys)
    assert "↑50" in output
    assert "—60" not in output


def test_table_header_date_and_market_state_are_chinese(capsys: pytest.CaptureFixture[str]) -> None:
    """F8: 日期带星期, 市场状态中文 + 原始枚举随附."""
    output = _render_table(capsys)
    assert "2026-08-14（周五）" in output
    assert "混合市（mixed）" in output


def test_format_trade_date_display_fallback() -> None:
    assert _format_trade_date_display("20260814") == "2026-08-14（周五）"
    assert _format_trade_date_display("2026-08-14") == "2026-08-14（周五）"
    assert _format_trade_date_display("garbage") == "garbage"
    assert _format_trade_date_display("") == ""


def test_market_state_display_unknown_passthrough() -> None:
    assert _market_state_display("crisis") == "危机市（crisis）"
    assert _market_state_display("unknown_state") == "unknown_state"


def test_daily_action_fill_row_survives_missing_price(monkeypatch) -> None:
    """F10: raw_entry_price=None 的坏成交行渲染为「成交价缺失」, 不崩整个视图."""
    from src.screening.offensive.daily_action import DailyActionV2Run, render_daily_action_v2
    from src.screening.offensive.ledger_repository import DailyValuation
    from src.screening.offensive.trade_lifecycle import FillSource

    monkeypatch.setattr("src.tools.tushare_api.get_stock_name", lambda ticker: ticker)

    signal_date = date(2026, 8, 14)
    trade = SimpleNamespace(
        ticker="600487",
        fill_source=FillSource.SYNTHETIC_OPEN,
        entry_date=signal_date,
        raw_entry_price=None,
        shadow_would_exit_next_open=False,
        shadow_exit_line=None,
        shadow_reason="hold",
    )
    service_run = SimpleNamespace(
        trade_date=signal_date,
        block_reason=None,
        block_reasons=(),
        blocked_tickers=(),
        ticker_gate_blocks=(),
        exit_plans=(),
        completed_exits=(),
        skipped_plans=(),
        deferred_exits=(),
        valuation=DailyValuation(signal_date, 1_000_000, 0, 1_000_000, 1_000_000, 0.0, ()),
    )
    run = DailyActionV2Run(service_run, (), (trade,), (), ())
    rendered = render_daily_action_v2(run)
    assert "成交价缺失" in rendered
    assert "模拟成交：1 笔" in rendered


def test_daily_action_blocked_candidate_nan_price_shows_missing(monkeypatch) -> None:
    """G4: reference_price=NaN 的不可计划候选渲染「参考价缺失」, 不出现 ~nan."""
    from src.screening.offensive.daily_action import (
        BlockedCandidate,
        DailyActionV2Run,
        render_daily_action_v2,
    )
    from src.screening.offensive.ledger_repository import DailyValuation

    monkeypatch.setattr("src.tools.tushare_api.get_stock_name", lambda ticker: ticker)

    signal_date = date(2026, 8, 14)
    candidate = BlockedCandidate("002594", "stale_price_cache", float("nan"))
    service_run = SimpleNamespace(
        trade_date=signal_date,
        block_reason=None,
        block_reasons=(),
        blocked_tickers=(),
        ticker_gate_blocks=(),
        exit_plans=(),
        completed_exits=(),
        skipped_plans=(),
        deferred_exits=(),
        valuation=DailyValuation(signal_date, 1_000_000, 0, 1_000_000, 1_000_000, 0.0, ()),
    )
    run = DailyActionV2Run(service_run, (), (), (candidate,), ())
    rendered = render_daily_action_v2(run)
    blocked_line = next(line for line in rendered.splitlines() if "002594" in line)
    assert "参考价缺失" in blocked_line
    assert "nan" not in blocked_line.lower()


def test_daily_action_contract_rejects_folded_not_flooded(monkeypatch) -> None:
    """G11: candidate_not_plan_eligible (detect 前契约拒票, 未触发; 数据事故日
    可达数百只) 折叠为一行计数 — 不淹没可操作拦截, 且漏斗算术一致
    (命中 = 可计划 + 不可计划)."""
    from src.screening.offensive.daily_action import (
        BlockedCandidate,
        DailyActionV2Run,
        ScanFunnel,
        render_daily_action_v2,
    )
    from src.screening.offensive.ledger_repository import DailyValuation

    monkeypatch.setattr("src.tools.tushare_api.get_stock_name", lambda ticker: ticker)

    signal_date = date(2026, 8, 14)
    actionable = BlockedCandidate("002594", "stale_price_cache", 105.3)
    rejects = tuple(
        BlockedCandidate(f"6000{i:02d}", "candidate_not_plan_eligible", 10.0)
        for i in range(74)
    )
    service_run = SimpleNamespace(
        trade_date=signal_date,
        block_reason=None,
        block_reasons=(),
        blocked_tickers=(),
        ticker_gate_blocks=(),
        exit_plans=(),
        completed_exits=(),
        skipped_plans=(),
        deferred_exits=(),
        valuation=DailyValuation(signal_date, 1_000_000, 0, 1_000_000, 1_000_000, 0.0, ()),
    )
    funnel = ScanFunnel(scannable=1523, prefilter_passed=5, hits=1)
    run = DailyActionV2Run(service_run, (), (), (actionable,) + rejects, (), funnel=funnel)
    rendered = render_daily_action_v2(run)
    # 只有可操作拦截入区, 74 只契约拒票折叠为一行
    assert "不可计划候选（1 只）" in rendered
    assert "另：74 只不具备计划资格" in rendered
    assert "600010" not in rendered
    # 漏斗算术: 命中 1 = 可计划 0 + 不可计划 1
    assert "命中 1 只 → 可计划 0 只 · 不可计划 1 只" in rendered
    assert "不可计划 75" not in rendered


def test_daily_action_empty_fills_keep_channel_lines(monkeypatch) -> None:
    """两渠道皆空时仍各显示一行"无" — 渠道标签恒在是回归测试钉住的契约
    (渠道空也显示 = "两通道都结算过且皆无", 与整节静默区分)."""
    from src.screening.offensive.daily_action import DailyActionV2Run, render_daily_action_v2
    from src.screening.offensive.ledger_repository import DailyValuation

    monkeypatch.setattr("src.tools.tushare_api.get_stock_name", lambda ticker: ticker)

    signal_date = date(2026, 8, 14)
    service_run = SimpleNamespace(
        trade_date=signal_date,
        block_reason=None,
        block_reasons=(),
        blocked_tickers=(),
        ticker_gate_blocks=(),
        exit_plans=(),
        completed_exits=(),
        skipped_plans=(),
        deferred_exits=(),
        valuation=DailyValuation(signal_date, 1_000_000, 0, 1_000_000, 1_000_000, 0.0, ()),
    )
    run = DailyActionV2Run(service_run, (), (), (), ())
    rendered = render_daily_action_v2(run)
    assert "模拟成交：无" in rendered
    assert "确认成交：无" in rendered
