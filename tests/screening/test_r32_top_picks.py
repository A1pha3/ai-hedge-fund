"""Tests for R32 (one-line reason + risk label) in top_picks.

R32 adds a compact ``理由: ... | 风险: 低/中/高(ATR X%)`` line to each pick,
reusing R15 factor attribution (top-2 factors) and R8 ATR data (risk level).
"""
from __future__ import annotations

from types import SimpleNamespace

from src.screening.top_picks import (
    _RISK_HIGH_THRESHOLD,
    _RISK_LOW_THRESHOLD,
    _format_stop_loss_take_profit,
    _render_reason_and_risk,
    _risk_label_from_advice,
)
from src.utils.display import Fore, Style


def _make_advice(*, atr: float, price: float = 10.0, rr: float = 1.5) -> SimpleNamespace:
    """Build a minimal stand-in for ConditionalOrderAdvice."""
    return SimpleNamespace(
        ticker="000001",
        name="测试",
        current_price=price,
        atr=atr,
        suggested_buy_zone=(price * 0.99, price * 1.01),
        suggested_stop_loss=price * 0.95,
        suggested_take_profit=price * 1.06,
        confidence=80.0,
        reasoning="test",
        historical_hit_rate=0.6,
        risk_reward_ratio=rr,
        n_sessions=14,
        degraded=False,
        atr_period=14,
    )


class TestRiskLabelFromAdvice:
    def test_low_risk(self) -> None:
        """ATR/price < 3% → 低."""
        advice = _make_advice(atr=0.2, price=10.0)  # 2%
        label, ratio = _risk_label_from_advice(advice)
        assert label == "低"
        assert abs(ratio - 0.02) < 1e-9

    def test_medium_risk(self) -> None:
        """ATR/price 3-5% → 中."""
        advice = _make_advice(atr=0.4, price=10.0)  # 4%
        label, ratio = _risk_label_from_advice(advice)
        assert label == "中"
        assert abs(ratio - 0.04) < 1e-9

    def test_high_risk(self) -> None:
        """ATR/price >= 5% → 高."""
        advice = _make_advice(atr=0.6, price=10.0)  # 6%
        label, ratio = _risk_label_from_advice(advice)
        assert label == "高"
        assert abs(ratio - 0.06) < 1e-9

    def test_boundary_low_medium(self) -> None:
        """Exactly at 3% boundary → 中 (>= threshold is not low)."""
        advice = _make_advice(atr=_RISK_LOW_THRESHOLD * 10.0, price=10.0)
        label, _ = _risk_label_from_advice(advice)
        assert label == "中"

    def test_none_advice(self) -> None:
        """None advice → ('—', 0.0)."""
        label, ratio = _risk_label_from_advice(None)
        assert label == "—"
        assert ratio == 0.0

    def test_zero_price(self) -> None:
        """Zero price → no risk label."""
        advice = _make_advice(atr=0.5, price=0.0)
        label, _ = _risk_label_from_advice(advice)
        assert label == "—"

    def test_zero_atr(self) -> None:
        """Zero ATR → no risk label."""
        advice = _make_advice(atr=0.0, price=10.0)
        label, _ = _risk_label_from_advice(advice)
        assert label == "—"


class TestRenderReasonAndRisk:
    def test_with_reason_and_risk(self) -> None:
        """Both reason (from strategy_signals) and risk → combined line."""
        item = {
            "strategy_signals": {
                "trend": {"direction": 1, "confidence": 80},
                "fundamental": {"direction": 1, "confidence": 60},
            }
        }
        advice = _make_advice(atr=0.4, price=10.0)  # 中 risk
        result = _render_reason_and_risk(item, advice)
        assert "理由" in result
        assert "趋势" in result
        assert "风险" in result
        assert "中" in result
        assert Fore.YELLOW in result  # medium risk color

    def test_no_reason_no_risk_returns_empty(self) -> None:
        """No strategy_signals and no advice → empty string."""
        result = _render_reason_and_risk({}, None)
        assert result == ""

    def test_reason_only_data_insufficient_risk(self) -> None:
        """Reason present but advice None → reason + '风险: 数据不足'."""
        item = {
            "strategy_signals": {
                "trend": {"direction": 1, "confidence": 80},
            }
        }
        result = _render_reason_and_risk(item, None)
        assert "理由" in result
        assert "趋势" in result
        assert "数据不足" in result

    def test_high_risk_uses_red_color(self) -> None:
        """High risk label uses Fore.RED."""
        item = {"strategy_signals": {"trend": {"direction": 1, "confidence": 80}}}
        advice = _make_advice(atr=0.7, price=10.0)  # 7% → 高
        result = _render_reason_and_risk(item, advice)
        assert "高" in result
        assert Fore.RED in result

    def test_low_risk_uses_green_color(self) -> None:
        """Low risk label uses Fore.GREEN."""
        item = {"strategy_signals": {"trend": {"direction": 1, "confidence": 80}}}
        advice = _make_advice(atr=0.1, price=10.0)  # 1% → 低
        result = _render_reason_and_risk(item, advice)
        assert "低" in result
        assert Fore.GREEN in result


class TestFormatStopLossTakeProfit:
    """R8 regression: ensure refactored _format_stop_loss_take_profit still works."""

    def test_formats_correctly(self) -> None:
        advice = _make_advice(atr=0.4, price=10.0, rr=2.0)
        result = _format_stop_loss_take_profit(advice)
        assert "止损" in result
        assert "止盈" in result
        assert "盈亏比" in result
        assert "买入" in result

    def test_low_rr_uses_yellow(self) -> None:
        advice = _make_advice(atr=0.4, price=10.0, rr=1.0)
        result = _format_stop_loss_take_profit(advice)
        assert Fore.YELLOW in result  # rr < 1.5 → yellow
