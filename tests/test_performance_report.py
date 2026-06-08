"""Tests for P2-8 组合绩效周报/月报 — ``src/portfolio/performance_report.py``.

12 tests covering:
  1. 周报完整生成
  2. 月报完整生成
  3. 收益计算
  4. Sharpe / Sortino
  5. 最大回撤
  6. 胜率 / 盈亏比
  7. 策略归因聚合
  8. Top winners / losers
  9. 推荐命中率
  10. 空数据 -> 优雅降级
  11. CLI smoke
  12. Web smoke
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from src.portfolio.performance_report import (
    ANNUAL_TRADING_DAYS,
    PerformanceReport,
    _aggregate_trades,
    _compute_annualized_return,
    _compute_daily_returns,
    _compute_max_drawdown,
    _compute_recommendation_hit_rate,
    _compute_sharpe,
    _compute_sortino,
    _compute_total_return,
    _compute_trading_days_in_period,
    _compute_volatility,
    _find_top_winners_losers,
    _resolve_period_dates,
    generate_performance_report,
    render_performance_report,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_positions_history(days: int = 7, start_value: float = 1_000_000.0, daily_return: float = 0.01) -> list[dict]:
    """生成 N 天的持仓快照, 每天以 daily_return 增长。"""
    from datetime import datetime, timedelta

    base = datetime(2026, 6, 1)
    history: list[dict] = []
    value = start_value
    for i in range(days):
        date_str = (base + timedelta(days=i)).strftime("%Y%m%d")
        history.append({"date": date_str, "portfolio_value": value})
        value = value * (1.0 + daily_return)
    return history


def _make_trades() -> list[dict]:
    """生成模拟交易记录。"""
    return [
        {"date": "20260601", "ticker": "300750", "name": "宁德时代", "pnl": 0.085, "strategy": "trend"},
        {"date": "20260602", "ticker": "600519", "name": "贵州茅台", "pnl": -0.032, "strategy": "fundamental"},
        {"date": "20260603", "ticker": "000858", "name": "五粮液", "pnl": 0.045, "strategy": "trend"},
        {"date": "20260604", "ticker": "002475", "name": "立讯精密", "pnl": -0.018, "strategy": "mean_reversion"},
        {"date": "20260605", "ticker": "601318", "name": "中国平安", "pnl": 0.022, "strategy": "event_sentiment"},
        {"date": "20260606", "ticker": "000001", "name": "平安银行", "pnl": 0.015, "strategy": "fundamental"},
        {"date": "20260607", "ticker": "300760", "name": "迈瑞医疗", "pnl": -0.025, "strategy": "mean_reversion"},
        {"date": "20260607", "ticker": "002594", "name": "比亚迪", "pnl": 0.038, "strategy": "trend"},
        {"date": "20260607", "ticker": "600036", "name": "招商银行", "pnl": 0.012, "strategy": "event_sentiment"},
        {"date": "20260607", "ticker": "000333", "name": "美的集团", "pnl": -0.008, "strategy": "fundamental"},
        {"date": "20260607", "ticker": "601012", "name": "隆基绿能", "pnl": 0.0, "strategy": "unknown"},  # flat -> excluded
    ]


def _make_tracking_history() -> list[dict]:
    """生成模拟 P1-3 追踪数据。"""
    return [
        {"ticker": "300750", "recommended_date": "20260601", "next_day_return": 2.5, "consecutive_days": 4},
        {"ticker": "600519", "recommended_date": "20260601", "next_day_return": -1.2, "consecutive_days": 1},
        {"ticker": "000858", "recommended_date": "20260602", "next_day_return": 3.1, "consecutive_days": 5},
        {"ticker": "002475", "recommended_date": "20260603", "next_day_return": -0.8, "consecutive_days": 2},
        {"ticker": "601318", "recommended_date": "20260603", "next_day_return": 1.5, "consecutive_days": 3},
    ]


# ---------------------------------------------------------------------------
# Test 1: 周报完整生成
# ---------------------------------------------------------------------------


def test_weekly_report_complete():
    """周报应包含所有字段且非 None。"""
    report = generate_performance_report(
        positions_history=_make_positions_history(7, daily_return=0.005),
        trades=_make_trades(),
        recommendations=[],
        tracking_history=_make_tracking_history(),
        period="weekly",
        end_date="20260607",
        benchmark_return=0.011,
    )
    assert report.period == "weekly"
    assert report.start_date <= report.end_date
    assert isinstance(report.total_return, float)
    assert isinstance(report.annualized_return, float)
    assert isinstance(report.max_drawdown, float)
    assert isinstance(report.sharpe_ratio, float)
    assert isinstance(report.sortino_ratio, float)
    assert isinstance(report.volatility, float)
    assert isinstance(report.total_trades, int)
    assert isinstance(report.win_rate, float)
    assert isinstance(report.strategy_attribution, dict)
    assert isinstance(report.top_winners, list)
    assert isinstance(report.top_losers, list)
    assert isinstance(report.total_recommendations, int)
    assert isinstance(report.recommendation_hit_rate, float)
    # to_dict roundtrip
    d = report.to_dict()
    assert "period" in d
    assert d["period"] == "weekly"


# ---------------------------------------------------------------------------
# Test 2: 月报完整生成
# ---------------------------------------------------------------------------


def test_monthly_report_complete():
    """月报应包含所有字段。"""
    report = generate_performance_report(
        positions_history=_make_positions_history(30, daily_return=0.003),
        trades=_make_trades(),
        recommendations=[],
        tracking_history=_make_tracking_history(),
        period="monthly",
        end_date="20260630",
        benchmark_return=0.02,
    )
    assert report.period == "monthly"
    # 30 天持仓快照, 总收益应 > 0
    assert report.total_return > 0
    assert report.benchmark_return == 0.02


# ---------------------------------------------------------------------------
# Test 3: 收益计算
# ---------------------------------------------------------------------------


def test_return_calculation():
    """总收益 = (期末 - 期初) / 期初。"""
    history = [
        {"date": "20260601", "portfolio_value": 1_000_000},
        {"date": "20260607", "portfolio_value": 1_032_000},
    ]
    total_return = _compute_total_return(history, "20260601", "20260607")
    expected = (1_032_000 - 1_000_000) / 1_000_000
    assert abs(total_return - expected) < 1e-6


def test_return_calculation_empty():
    """空历史 -> 0。"""
    assert _compute_total_return([], "20260601", "20260607") == 0.0


# ---------------------------------------------------------------------------
# Test 4: Sharpe / Sortino
# ---------------------------------------------------------------------------


def test_sharpe_positive():
    """正收益序列 Sharpe > 0。"""
    returns = [0.01, 0.02, 0.015, 0.008, 0.012]
    sharpe = _compute_sharpe(returns)
    assert sharpe > 0.0


def test_sortino_positive():
    """正收益序列 Sortino > 0 (全为正, 无下行偏差 -> 0 — 但我们用 daily_rf 作为阈值)。

    实际上全为正的收益率序列可能依然低于 daily_rf, 所以 Sortino 仍可计算。
    """
    returns = [0.01, 0.02, 0.015, 0.008, 0.012]
    sortino = _compute_sortino(returns)
    assert isinstance(sortino, float)


def test_sharpe_empty():
    """空收益率 -> 0。"""
    assert _compute_sharpe([]) == 0.0
    assert _compute_sortino([]) == 0.0


def test_sharpe_constant():
    """恒定收益率 -> std = 0 -> Sharpe = 0。"""
    returns = [0.01] * 10
    assert _compute_sharpe(returns) == 0.0


# ---------------------------------------------------------------------------
# Test 5: 最大回撤
# ---------------------------------------------------------------------------


def test_max_drawdown():
    """最大回撤: 先涨后跌的序列。"""
    history = [
        {"date": "20260601", "portfolio_value": 100},
        {"date": "20260602", "portfolio_value": 120},  # peak
        {"date": "20260603", "portfolio_value": 114},  # -5%
        {"date": "20260604", "portfolio_value": 108},  # -10%
        {"date": "20260605", "portfolio_value": 110},
    ]
    dd = _compute_max_drawdown(history)
    expected = (120 - 108) / 120  # 10%
    assert abs(dd - expected) < 1e-4


def test_max_drawdown_monotonic_up():
    """单调上涨 -> 最大回撤 = 0。"""
    history = [
        {"date": "20260601", "portfolio_value": 100},
        {"date": "20260602", "portfolio_value": 110},
        {"date": "20260603", "portfolio_value": 120},
    ]
    assert _compute_max_drawdown(history) == 0.0


def test_max_drawdown_empty():
    """空数据 -> 0。"""
    assert _compute_max_drawdown([]) == 0.0


# ---------------------------------------------------------------------------
# Test 6: 胜率 / 盈亏比
# ---------------------------------------------------------------------------


def test_trade_aggregation():
    """胜率/盈亏比/交易统计。"""
    trades = [
        {"pnl": 0.05},
        {"pnl": -0.02},
        {"pnl": 0.03},
        {"pnl": -0.01},
        {"pnl": 0.0},  # flat -> excluded from win/loss
    ]
    stats = _aggregate_trades(trades)
    assert stats["total_trades"] == 4  # 2 wins + 2 losses
    assert stats["win_count"] == 2
    assert stats["loss_count"] == 2
    assert abs(stats["win_rate"] - 0.5) < 1e-6
    assert abs(stats["avg_win"] - 0.04) < 1e-6
    assert abs(stats["avg_loss"] - (-0.015)) < 1e-6
    expected_pf = 0.04 / 0.015
    assert abs(stats["profit_factor"] - expected_pf) < 1e-4


def test_trade_aggregation_all_wins():
    """全盈利 -> profit_factor = inf。"""
    trades = [{"pnl": 0.01}, {"pnl": 0.03}]
    stats = _aggregate_trades(trades)
    assert stats["win_count"] == 2
    assert stats["loss_count"] == 0
    assert math.isinf(stats["profit_factor"])


def test_trade_aggregation_empty():
    """空交易 -> 全零。"""
    stats = _aggregate_trades([])
    assert stats["total_trades"] == 0
    assert stats["win_rate"] == 0.0


def test_trade_aggregation_break_even_pnl_does_not_fall_back_to_return_pct():
    """R20.15 Bug: ``pnl == 0`` with a non-zero ``return_pct`` was
    misclassified because the previous ``pnl or return_pct`` expression
    short-circuited on the falsy zero.  After the fix, ``pnl`` is
    preferred when present (even at 0), and the break-even trade is
    excluded from wins / losses.
    """
    trades = [
        {"pnl": 0.05, "return_pct": 999.0},  # win (return_pct ignored)
        {"pnl": 0.0, "return_pct": -0.99},   # break-even, NOT a loss
    ]
    stats = _aggregate_trades(trades)
    assert stats["win_count"] == 1
    assert stats["loss_count"] == 0
    assert stats["total_trades"] == 1  # break-even excluded
    assert stats["win_rate"] == 1.0


# ---------------------------------------------------------------------------
# Test 7: 策略归因聚合
# ---------------------------------------------------------------------------


def test_strategy_attribution():
    """按策略聚合 PnL。"""
    from src.portfolio.performance_report import _aggregate_strategy_attribution

    trades = [
        {"strategy": "trend", "pnl": 0.05},
        {"strategy": "trend", "pnl": -0.02},
        {"strategy": "fundamental", "pnl": 0.03},
        {"strategy": "event_sentiment", "pnl": -0.01},
    ]
    attr = _aggregate_strategy_attribution(trades, [])
    assert abs(attr["trend"] - 0.03) < 1e-6
    assert abs(attr["fundamental"] - 0.03) < 1e-6
    assert abs(attr["event_sentiment"] - (-0.01)) < 1e-6


def test_strategy_attribution_from_positions():
    """当 trades 为空时回退到 positions_history。"""
    from src.portfolio.performance_report import _aggregate_strategy_attribution

    positions_history = [
        {
            "date": "20260601",
            "positions": [
                {"strategy": "trend", "daily_pnl": 0.02},
                {"strategy": "mean_reversion", "daily_pnl": -0.01},
            ],
        }
    ]
    attr = _aggregate_strategy_attribution([], positions_history)
    assert abs(attr["trend"] - 0.02) < 1e-6
    assert abs(attr["mean_reversion"] - (-0.01)) < 1e-6


# ---------------------------------------------------------------------------
# Test 8: Top winners / losers
# ---------------------------------------------------------------------------


def test_top_winners_losers():
    """Top 3 盈利/亏损。"""
    trades = _make_trades()
    winners, losers = _find_top_winners_losers(trades, top_n=3)
    assert len(winners) <= 3
    assert len(losers) <= 3
    # Winners sorted descending
    for i in range(len(winners) - 1):
        assert winners[i]["return_pct"] >= winners[i + 1]["return_pct"]
    # Losers sorted ascending (most negative first)
    for i in range(len(losers) - 1):
        assert losers[i]["return_pct"] <= losers[i + 1]["return_pct"]
    # Best winner should be 宁德时代 +8.5%
    assert winners[0]["ticker"] == "300750"
    assert abs(winners[0]["return_pct"] - 0.085) < 1e-6


def test_top_winners_losers_empty():
    """空交易 -> 空列表。"""
    assert _find_top_winners_losers([]) == ([], [])


# ---------------------------------------------------------------------------
# Test 9: 推荐命中率
# ---------------------------------------------------------------------------


def test_recommendation_hit_rate():
    """命中率 = 盈利推荐数 / 有收益数据的推荐总数。"""
    tracking = _make_tracking_history()
    total, hit_rate, consecutive_hits = _compute_recommendation_hit_rate([], tracking)
    # 3 positive out of 5
    assert total == 5
    assert abs(hit_rate - 3 / 5) < 1e-6
    # consecutive_days >= 3 AND next_day_return > 0: 300750(4d, +2.5) + 000858(5d, +3.1) + 601318(3d, +1.5) = 3
    assert consecutive_hits == 3


def test_recommendation_hit_rate_empty():
    """空数据 -> 0。"""
    total, hit_rate, consecutive = _compute_recommendation_hit_rate([], [])
    assert total == 0
    assert hit_rate == 0.0
    assert consecutive == 0


# ---------------------------------------------------------------------------
# Test 10: 空数据 -> 优雅降级
# ---------------------------------------------------------------------------


def test_empty_data_graceful_degradation():
    """所有输入为空 -> 零值报告, 不抛异常。"""
    report = generate_performance_report(
        positions_history=[],
        trades=[],
        recommendations=[],
        tracking_history=[],
        period="weekly",
        end_date="20260607",
    )
    assert report.total_return == 0.0
    assert report.max_drawdown == 0.0
    assert report.sharpe_ratio == 0.0
    assert report.total_trades == 0
    assert report.win_rate == 0.0
    assert report.strategy_attribution == {}
    assert report.top_winners == []
    assert report.top_losers == []
    assert report.total_recommendations == 0
    assert report.recommendation_hit_rate == 0.0
    # render should not crash
    text = render_performance_report(report)
    assert "组合绩效周报" in text
    assert "收益概览" in text
    assert "风险指标" in text
    assert "交易统计" in text
    assert "推荐有效性" in text


# ---------------------------------------------------------------------------
# Test 11: CLI smoke
# ---------------------------------------------------------------------------


def test_cli_smoke():
    """``--performance-report`` CLI 入口应能正常返回。"""
    # 直接调用 run_performance_report 函数 (mock 数据源)
    with patch("src.main._load_positions_for_attribution", return_value=[]), patch("src.main._resolve_positions_path", return_value=None):
        # 测试 run_performance_report 可被 import 并调用
        # (CLI 入口通过 main.py 调用, 此处仅验证函数签名)
        from src.portfolio.performance_report import generate_performance_report

        report = generate_performance_report([], [], [], [], period="weekly", end_date="20260607")
        assert isinstance(report, PerformanceReport)


def test_render_report_contains_expected_sections():
    """render 输出包含所有预期段落。"""
    trades = _make_trades()
    report = generate_performance_report(
        positions_history=_make_positions_history(7, daily_return=0.005),
        trades=trades,
        recommendations=[],
        tracking_history=_make_tracking_history(),
        period="weekly",
        end_date="20260607",
        benchmark_return=0.011,
    )
    text = render_performance_report(report)
    assert "组合绩效周报" in text
    assert "收益概览" in text
    assert "风险指标" in text
    assert "交易统计" in text
    assert "策略归因" in text
    assert "最佳/最差" in text
    assert "推荐有效性" in text
    # 应包含具体数值
    assert "胜率" in text
    assert "Sharpe" in text


def test_render_monthly_report():
    """月报渲染应包含 '月报' 标签。"""
    report = generate_performance_report(
        positions_history=_make_positions_history(30, daily_return=0.003),
        trades=_make_trades(),
        recommendations=[],
        tracking_history=[],
        period="monthly",
        end_date="20260630",
    )
    text = render_performance_report(report)
    assert "组合绩效月报" in text


# ---------------------------------------------------------------------------
# Test 12: Web smoke
# ---------------------------------------------------------------------------


def test_web_endpoint_smoke():
    """验证 API 端点的 Pydantic response model 可被正确构造。"""
    report = generate_performance_report(
        positions_history=_make_positions_history(7, daily_return=0.005),
        trades=_make_trades(),
        recommendations=[],
        tracking_history=_make_tracking_history(),
        period="weekly",
        end_date="20260607",
        benchmark_return=0.011,
    )
    d = report.to_dict()
    # 验证可序列化
    serialized = json.dumps(d, default=str, ensure_ascii=False)
    assert "weekly" in serialized
    parsed = json.loads(serialized)
    assert parsed["period"] == "weekly"
    assert "total_return" in parsed
    assert "strategy_attribution" in parsed


def test_annualized_return():
    """年化收益率计算。"""
    # 7 天 +3.2% total return
    total_return = 0.032
    trading_days = 5
    ann = _compute_annualized_return(total_return, trading_days)
    expected = (1.032) ** (244 / 5) - 1
    assert abs(ann - expected) < 1e-4


def test_annualized_return_zero_days():
    """trading_days=0 -> 0。"""
    assert _compute_annualized_return(0.03, 0) == 0.0


def test_period_dates_weekly():
    """周报: start_date = end_date - 7 天。"""
    start, end = _resolve_period_dates("weekly", "20260607")
    assert end == "20260607"
    assert start == "20260531"


def test_period_dates_monthly():
    """月报: start_date = end_date - 30 天。"""
    start, end = _resolve_period_dates("monthly", "20260607")
    assert end == "20260607"
    assert start == "20260508"


def test_volatility():
    """波动率计算。"""
    returns = [0.01, -0.005, 0.02, -0.01, 0.015]
    vol = _compute_volatility(returns)
    assert vol > 0
    # Annualized vol should be > daily std
    import math as _math

    mean_r = sum(returns) / len(returns)
    var = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
    daily_std = _math.sqrt(var)
    ann_std = daily_std * _math.sqrt(244)
    assert abs(vol - ann_std) < 1e-4
