"""--auto 表格级展示契约测试 (v3 桶分组版, 2026-08-16)
+ --daily-action 成交价缺失守卫 (F10).

行级契约见 test_score_decomposition.py::TestAutoScreeningTableRowV3;
本文件钉住整张表的端到端渲染: 档头钱数、记分牌常驻、numparse、
无信号策略与 legacy header 形态.
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
from src.screening.scorecard import BucketStats


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


def _bucket_stats() -> dict[str, BucketStats]:
    # score_b=0.357 → 桶 较低 (0.3-0.4)
    return {
        "较低 (0.3-0.4)": BucketStats(
            label="较低 (0.3-0.4)",
            window_start="20260226",
            window_end="20260814",
            n_records=431,
            n_mature=398,
            win_rate=0.48,
            mean_return=0.3,
            avg_win=9.9,
            avg_loss=-8.6,
            payoff=1.1,
        )
    }


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
        bucket_display_stats=_bucket_stats(),
        scorecard_lines=[
            "排序记分牌 近60个推荐日（20260226→20260807）: Top10 切片 T+5 胜率 48% · 均值 -0.5%",
            "→ 排序近期无正向证据，本表按观察清单使用；实际 BUY 见 --daily-action",
        ],
    )
    return capsys.readouterr().out


def test_table_bucket_header_carries_money_stats(capsys: pytest.CaptureFixture[str]) -> None:
    """F1 (v3): 排序主键 (桶胜率) 上桶头 — 胜率/均值/盈亏笔均/赔率一次渲染,
    图例指向桶头; 行内不再逐行重复桶级数字."""
    output = _render_table(capsys)
    assert "信号分档 0.3-0.4" in output  # 冷读反馈: 区间+名次, 不出现定性标签
    assert "本表第 1 名" in output  # 档归属的名次区间
    assert "较低" not in output
    assert "胜率 48%" in output
    assert "赔率 1.1" in output
    assert "盈笔均 +9.9%" in output and "亏笔均 -8.6%" in output
    assert "档头" in output  # 图例指向档头语义


def test_table_scorecard_lines_when_no_briefing(capsys: pytest.CaptureFixture[str]) -> None:
    """v3: briefing 缺席 (legacy header 回退) 时记分牌仍常驻 — 它是整张表的先验."""
    output = _render_table(capsys)
    assert "排序记分牌" in output
    assert "观察清单" in output


def test_table_bucket_header_null_state(capsys: pytest.CaptureFixture[str]) -> None:
    """空态矩阵: 桶无追踪数据 → 确定性披露行, 不编造数字."""
    _print_auto_screening_table(
        "20260814",
        [_item()],
        SimpleNamespace(state_type="mixed", position_scale=1.0),
        300,
        10,
        Path("data/reports/auto_screening_20260814.json"),
        consecutive_recommendations=[],
        bucket_display_stats={},
    )
    output = capsys.readouterr().out
    assert "信号分档 0.3-0.4" in output
    assert "不提供估计" in output
    # 桶头无点估计 ("T+5 胜率" 只在有钱数的桶头出现; 图例的 "T+5 实证" 不受影响)
    assert "T+5 胜率" not in output


def test_table_preserves_explicit_number_formatting(capsys: pytest.CaptureFixture[str]) -> None:
    """F2 (v3): tabulate numparse 不得吃掉显式格式 — 综合分 "+0.46" 的符号保留;
    同档 tie-break 用 2 位小数 (4 位是假精度)."""
    output = _render_table(capsys)
    assert "+0.46" in output
    assert "0.457" not in output


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
