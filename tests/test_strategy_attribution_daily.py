"""Tests for P1-11 strategy daily attribution (``src/screening/strategy_attribution_daily``).

13+ test cases covering:
    1.  Single strategy 100% winning
    2.  Single strategy 100% losing
    3.  Mixed multi-strategy
    4.  Attribution percentages sum to ~100%
    5.  Hit-rate computation (winners / total)
    6.  Top winner = max PnL
    7.  Top loser = min PnL
    8.  Status = winning (high attr% + high hit rate)
    9.  Status = failing (negative attr% OR low hit rate)
    10. Status = neutral (in between)
    11. Diagnosis template generation (covers all 4 known strategies × 3 statuses)
    12. Empty positions → empty result
    13. render_attribution_report format validation (header, lines, summary)

Extra coverage:
    14. NaN / Inf / None inputs handled safely
    15. Unknown strategy bucket → ``unknown``
    16. daily_pnl explicit field takes precedence over current/prev value
"""

from __future__ import annotations

import math

import pytest

from src.screening.strategy_attribution_daily import (
    DIAGNOSIS_TEMPLATES,
    KNOWN_STRATEGIES,
    STRATEGY_DISPLAY_NAMES,
    StrategyDailyAttribution,
    compute_strategy_daily_attribution,
    render_attribution_report,
)


# ---------------------------------------------------------------------------
# Test 1: single strategy 100% winning
# ---------------------------------------------------------------------------


def test_single_strategy_100pct_winning() -> None:
    positions = [
        {"ticker": "000001", "strategy": "trend", "current_value": 11000, "prev_value": 10000, "cost_basis": 9500},
        {"ticker": "300750", "strategy": "trend", "current_value": 22500, "prev_value": 20000, "cost_basis": 18000},
    ]
    result = compute_strategy_daily_attribution(positions, today_date="2026-06-07")

    assert set(result.keys()) == {"trend"}
    trend = result["trend"]
    assert trend.daily_pnl == pytest.approx(3500.0)
    assert trend.attribution_pct == pytest.approx(100.0)
    assert trend.hit_rate == pytest.approx(1.0)
    assert trend.n_positions == 2
    assert trend.top_winner == "300750"
    assert trend.top_winner_pnl == pytest.approx(2500.0)
    assert trend.top_loser is None
    assert trend.top_loser_pnl == pytest.approx(0.0)
    assert trend.status == "winning"
    # diagnosis should match the trend/winning template
    assert trend.diagnosis == DIAGNOSIS_TEMPLATES[("trend", "winning")]


# ---------------------------------------------------------------------------
# Test 2: single strategy 100% losing
# ---------------------------------------------------------------------------


def test_single_strategy_100pct_losing() -> None:
    positions = [
        {"ticker": "600519", "strategy": "fundamental", "current_value": 9500, "prev_value": 10000, "cost_basis": 9800},
        {"ticker": "601318", "strategy": "fundamental", "current_value": 8400, "prev_value": 9000, "cost_basis": 8700},
    ]
    result = compute_strategy_daily_attribution(positions, today_date="2026-06-07")

    fundamental = result["fundamental"]
    assert fundamental.daily_pnl == pytest.approx(-1100.0)
    # 100% of total PnL (which is also -1100)
    assert fundamental.attribution_pct == pytest.approx(100.0)
    assert fundamental.hit_rate == pytest.approx(0.0)
    assert fundamental.top_winner is None
    assert fundamental.top_loser == "601318"
    assert fundamental.top_loser_pnl == pytest.approx(-600.0)
    # status = failing because hit_rate (0.0) < 0.30
    assert fundamental.status == "failing"
    assert fundamental.diagnosis == DIAGNOSIS_TEMPLATES[("fundamental", "failing")]


# ---------------------------------------------------------------------------
# Test 3: mixed multi-strategy
# ---------------------------------------------------------------------------


def test_mixed_multi_strategy() -> None:
    positions = [
        # trend: +12,300 winner via 300750
        {"ticker": "300750", "strategy": "trend", "current_value": 32300, "prev_value": 20000},
        {"ticker": "000001", "strategy": "trend", "current_value": 10000, "prev_value": 10000},
        # mean_reversion: +2,100
        {"ticker": "000002", "strategy": "mean_reversion", "current_value": 12100, "prev_value": 10000},
        # fundamental: -5,200 loser via 600519
        {"ticker": "600519", "strategy": "fundamental", "current_value": 4800, "prev_value": 10000},
        # event_sentiment: +14,300
        {"ticker": "000333", "strategy": "event_sentiment", "current_value": 24300, "prev_value": 10000},
    ]
    result = compute_strategy_daily_attribution(positions, today_date="2026-06-07")

    assert set(result.keys()) == {"trend", "mean_reversion", "fundamental", "event_sentiment"}
    assert result["trend"].daily_pnl == pytest.approx(12300.0)
    assert result["mean_reversion"].daily_pnl == pytest.approx(2100.0)
    assert result["fundamental"].daily_pnl == pytest.approx(-5200.0)
    assert result["event_sentiment"].daily_pnl == pytest.approx(14300.0)

    # Total PnL = 23,500
    total = sum(a.daily_pnl for a in result.values())
    assert total == pytest.approx(23500.0)


# ---------------------------------------------------------------------------
# Test 4: attribution percentages sum approximately to 100%
# ---------------------------------------------------------------------------


def test_attribution_pct_sums_to_100() -> None:
    positions = [
        {"ticker": "A", "strategy": "trend", "current_value": 120, "prev_value": 100},
        {"ticker": "B", "strategy": "mean_reversion", "current_value": 105, "prev_value": 100},
        {"ticker": "C", "strategy": "fundamental", "current_value": 90, "prev_value": 100},
        {"ticker": "D", "strategy": "event_sentiment", "current_value": 130, "prev_value": 100},
    ]
    result = compute_strategy_daily_attribution(positions, today_date="2026-06-07")
    total_attr = sum(a.attribution_pct for a in result.values())
    assert total_attr == pytest.approx(100.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Test 5: hit rate calculation
# ---------------------------------------------------------------------------


def test_hit_rate_calculation() -> None:
    positions = [
        # trend: 2 winners / 3 total = 0.667 hit rate
        {"ticker": "A", "strategy": "trend", "current_value": 110, "prev_value": 100},
        {"ticker": "B", "strategy": "trend", "current_value": 105, "prev_value": 100},
        {"ticker": "C", "strategy": "trend", "current_value": 95, "prev_value": 100},
    ]
    result = compute_strategy_daily_attribution(positions, today_date="2026-06-07")
    assert result["trend"].hit_rate == pytest.approx(2 / 3)
    assert result["trend"].n_positions == 3


# ---------------------------------------------------------------------------
# Test 6: top winner = max PnL
# ---------------------------------------------------------------------------


def test_top_winner_is_max_pnl() -> None:
    positions = [
        {"ticker": "small", "strategy": "trend", "current_value": 105, "prev_value": 100},
        {"ticker": "big", "strategy": "trend", "current_value": 300, "prev_value": 100},
        {"ticker": "medium", "strategy": "trend", "current_value": 150, "prev_value": 100},
    ]
    result = compute_strategy_daily_attribution(positions, today_date="2026-06-07")
    assert result["trend"].top_winner == "big"
    assert result["trend"].top_winner_pnl == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# Test 7: top loser = min PnL
# ---------------------------------------------------------------------------


def test_top_loser_is_min_pnl() -> None:
    positions = [
        {"ticker": "small_loss", "strategy": "fundamental", "current_value": 95, "prev_value": 100},
        {"ticker": "big_loss", "strategy": "fundamental", "current_value": 30, "prev_value": 100},
        {"ticker": "medium_loss", "strategy": "fundamental", "current_value": 60, "prev_value": 100},
    ]
    result = compute_strategy_daily_attribution(positions, today_date="2026-06-07")
    assert result["fundamental"].top_loser == "big_loss"
    assert result["fundamental"].top_loser_pnl == pytest.approx(-70.0)


# ---------------------------------------------------------------------------
# Test 8: status = winning
# ---------------------------------------------------------------------------


def test_status_winning() -> None:
    # Build a position set where trend contributes > 5% with hit rate > 50%
    positions = [
        {"ticker": "A", "strategy": "trend", "current_value": 110, "prev_value": 100},
        {"ticker": "B", "strategy": "trend", "current_value": 120, "prev_value": 100},
        # Counter-strategy with small contribution so trend dominates
        {"ticker": "C", "strategy": "mean_reversion", "current_value": 100.5, "prev_value": 100},
    ]
    result = compute_strategy_daily_attribution(positions, today_date="2026-06-07")
    assert result["trend"].status == "winning"


# ---------------------------------------------------------------------------
# Test 9: status = failing
# ---------------------------------------------------------------------------


def test_status_failing_by_negative_attribution() -> None:
    # fundamental strategy attribution_pct < -5%
    positions = [
        {"ticker": "winner", "strategy": "trend", "current_value": 200, "prev_value": 100},
        {"ticker": "loser", "strategy": "fundamental", "current_value": 50, "prev_value": 100},
    ]
    result = compute_strategy_daily_attribution(positions, today_date="2026-06-07")
    # total = +100 - 50 = +50; fundamental = -50/+50 = -100% -> failing
    assert result["fundamental"].status == "failing"


def test_status_failing_by_low_hit_rate() -> None:
    # 0 winners / 1 total = 0% hit rate (< 30%)
    positions = [
        {"ticker": "only", "strategy": "event_sentiment", "current_value": 99.9, "prev_value": 100},
    ]
    result = compute_strategy_daily_attribution(positions, today_date="2026-06-07")
    assert result["event_sentiment"].status == "failing"


# ---------------------------------------------------------------------------
# Test 10: status = neutral
# ---------------------------------------------------------------------------


def test_status_neutral() -> None:
    # Mean reversion: small positive but attribution = 5% boundary, hit rate = 50% boundary
    positions = [
        {"ticker": "trend_big", "strategy": "trend", "current_value": 950, "prev_value": 100},
        # Mean reversion: 2 positions, 1 winner — hit rate exactly 50% (boundary; > 50% required for winning)
        {"ticker": "mr_win", "strategy": "mean_reversion", "current_value": 105, "prev_value": 100},
        {"ticker": "mr_neutral", "strategy": "mean_reversion", "current_value": 100, "prev_value": 100},
    ]
    result = compute_strategy_daily_attribution(positions, today_date="2026-06-07")
    # mean_reversion attribution_pct is tiny; hit rate = 50% (not > 50%) → neutral
    assert result["mean_reversion"].status == "neutral"


# ---------------------------------------------------------------------------
# Test 11: diagnosis template generation — all 4 strategies × 3 statuses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("strategy", list(KNOWN_STRATEGIES))
@pytest.mark.parametrize("status", ["winning", "neutral", "failing"])
def test_diagnosis_template_for_each_strategy_and_status(strategy: str, status: str) -> None:
    """每个 (strategy, status) 组合都应该映射到一条非空中文模板。"""
    template = DIAGNOSIS_TEMPLATES.get((strategy, status))
    assert template is not None, f"Missing template for ({strategy}, {status})"
    assert len(template) > 0


# ---------------------------------------------------------------------------
# Test 12: empty positions → empty result
# ---------------------------------------------------------------------------


def test_empty_positions_returns_empty_dict() -> None:
    assert compute_strategy_daily_attribution([], today_date="2026-06-07") == {}
    # None entries are skipped silently
    assert compute_strategy_daily_attribution([None, None], today_date="2026-06-07") == {}  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# Test 13: render_attribution_report output format
# ---------------------------------------------------------------------------


def test_render_attribution_report_format() -> None:
    positions = [
        {"ticker": "300750", "strategy": "trend", "current_value": 32300, "prev_value": 20000},
        {"ticker": "000001", "strategy": "trend", "current_value": 9000, "prev_value": 10000},
        {"ticker": "600519", "strategy": "fundamental", "current_value": 4800, "prev_value": 10000},
    ]
    attributions = compute_strategy_daily_attribution(positions, today_date="2026-06-07")
    total_pnl = sum(a.daily_pnl for a in attributions.values())
    report = render_attribution_report(attributions, total_pnl, "2026-06-07", portfolio_value_base=2_500_000)

    assert "策略归因日报" in report
    assert "2026-06-07" in report
    assert "组合当日 PnL" in report
    assert "各策略表现" in report
    # 应该出现策略中文名
    assert STRATEGY_DISPLAY_NAMES["trend"] in report
    assert STRATEGY_DISPLAY_NAMES["fundamental"] in report
    # 最大贡献 / 最大拖累 标签
    assert "最大贡献" in report or "最大拖累" in report
    # 总结句
    assert "总结" in report


def test_render_attribution_report_empty() -> None:
    """空 attributions 应该返回友好提示, 不抛异常。"""
    report = render_attribution_report({}, portfolio_total_pnl=0.0, date="2026-06-07")
    assert "策略归因日报" in report
    assert "2026-06-07" in report
    assert "暂无持仓" in report


# ---------------------------------------------------------------------------
# Extra coverage: NaN/Inf safety + unknown strategy bucket + daily_pnl precedence
# ---------------------------------------------------------------------------


def test_handles_nan_inf_and_none() -> None:
    """NaN / Inf / None 都应该归 0, 不污染下游计算。"""
    positions = [
        {"ticker": "good", "strategy": "trend", "current_value": 110, "prev_value": 100},
        {"ticker": "nan", "strategy": "trend", "current_value": float("nan"), "prev_value": 100},
        {"ticker": "inf", "strategy": "trend", "current_value": float("inf"), "prev_value": 100},
        {"ticker": "none", "strategy": "trend", "current_value": None, "prev_value": None},
    ]
    result = compute_strategy_daily_attribution(positions, today_date="2026-06-07")
    trend = result["trend"]
    # 只有 "good" 贡献了 +10; NaN/Inf/None 全部归 0
    assert math.isfinite(trend.daily_pnl)
    assert trend.daily_pnl == pytest.approx(10.0)


def test_unknown_strategy_bucket() -> None:
    """白名单外的策略应该被聚到 ``unknown`` 桶里。"""
    positions = [
        {"ticker": "weird", "strategy": "high_frequency_arbitrage", "current_value": 110, "prev_value": 100},
    ]
    result = compute_strategy_daily_attribution(positions, today_date="2026-06-07")
    assert "unknown" in result
    assert result["unknown"].daily_pnl == pytest.approx(10.0)


def test_explicit_daily_pnl_takes_precedence() -> None:
    """显式 daily_pnl 字段应该覆盖 current_value - prev_value 计算。"""
    positions = [
        # current/prev 暗示 +10, 但显式 daily_pnl=999 应该胜出
        {"ticker": "x", "strategy": "trend", "current_value": 110, "prev_value": 100, "daily_pnl": 999},
    ]
    result = compute_strategy_daily_attribution(positions, today_date="2026-06-07")
    assert result["trend"].daily_pnl == pytest.approx(999.0)


def test_attribution_pct_zero_when_total_zero() -> None:
    """组合总 PnL 为 0 时, 各策略 attribution_pct 应该为 0 (避免除零)。"""
    positions = [
        {"ticker": "up", "strategy": "trend", "current_value": 110, "prev_value": 100},
        {"ticker": "down", "strategy": "fundamental", "current_value": 90, "prev_value": 100},
    ]
    result = compute_strategy_daily_attribution(positions, today_date="2026-06-07")
    for attr in result.values():
        assert math.isfinite(attr.attribution_pct)
        assert attr.attribution_pct == 0.0


def test_to_dict_serializable() -> None:
    """StrategyDailyAttribution.to_dict 输出应可被 json.dumps 直接消费。"""
    import json

    positions = [{"ticker": "A", "strategy": "trend", "current_value": 110, "prev_value": 100}]
    result = compute_strategy_daily_attribution(positions, today_date="2026-06-07")
    payload = {k: v.to_dict() for k, v in result.items()}
    # round-trip 应该无异常
    encoded = json.dumps(payload, ensure_ascii=False)
    decoded = json.loads(encoded)
    assert decoded["trend"]["strategy_name"] == "trend"
    assert decoded["trend"]["daily_pnl"] == pytest.approx(10.0)


def test_dataclass_frozen() -> None:
    """StrategyDailyAttribution 应该是 frozen dataclass — 不可变。"""
    attr = StrategyDailyAttribution(
        strategy_name="trend",
        daily_pnl=10.0,
        attribution_pct=100.0,
        hit_rate=1.0,
        top_winner="A",
        top_winner_pnl=10.0,
        top_loser=None,
        top_loser_pnl=0.0,
        n_positions=1,
        status="winning",
        diagnosis="test",
    )
    with pytest.raises(Exception):
        attr.daily_pnl = 999  # type: ignore[misc]
