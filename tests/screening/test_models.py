"""Tests for src/screening/models.py — screening data models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.screening.models import (
    ArbitrationAction,
    CandidateStock,
    DEFAULT_STRATEGY_WEIGHTS,
    FusedScore,
    MarketState,
    MarketStateType,
    StrategySignal,
    SubFactor,
)

# ---------------------------------------------------------------------------
# SubFactor
# ---------------------------------------------------------------------------


class TestSubFactor:
    def test_valid(self) -> None:
        sf = SubFactor(name="test", direction=1, confidence=80.0)
        assert sf.direction == 1
        assert sf.confidence == 80.0
        assert sf.completeness == 1.0
        assert sf.weight == 0.2

    def test_direction_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            SubFactor(name="test", direction=2, confidence=80.0)
        with pytest.raises(ValidationError):
            SubFactor(name="test", direction=-2, confidence=80.0)

    def test_confidence_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            SubFactor(name="test", direction=1, confidence=101.0)
        with pytest.raises(ValidationError):
            SubFactor(name="test", direction=1, confidence=-1.0)

    def test_completeness_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            SubFactor(name="test", direction=1, confidence=80.0, completeness=1.5)
        with pytest.raises(ValidationError):
            SubFactor(name="test", direction=1, confidence=80.0, completeness=-0.1)

    def test_weight_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            SubFactor(name="test", direction=1, confidence=80.0, weight=1.5)
        with pytest.raises(ValidationError):
            SubFactor(name="test", direction=1, confidence=80.0, weight=-0.1)

    def test_metrics_default_empty(self) -> None:
        sf = SubFactor(name="test", direction=1, confidence=80.0)
        assert sf.metrics == {}


# ---------------------------------------------------------------------------
# StrategySignal
# ---------------------------------------------------------------------------


class TestStrategySignal:
    def test_valid(self) -> None:
        sig = StrategySignal(direction=1, confidence=80.0, completeness=1.0)
        assert sig.direction == 1
        assert sig.sub_factors == {}

    def test_required_completeness(self) -> None:
        with pytest.raises(ValidationError):
            StrategySignal(direction=1, confidence=80.0)  # completeness is required

    def test_sub_factors_dict(self) -> None:
        sig = StrategySignal(
            direction=1,
            confidence=80.0,
            completeness=1.0,
            sub_factors={"a": {"name": "a", "direction": 1}},
        )
        assert sig.sub_factors["a"]["name"] == "a"


# ---------------------------------------------------------------------------
# MarketState
# ---------------------------------------------------------------------------


class TestMarketState:
    def test_defaults(self) -> None:
        state = MarketState()
        assert state.state_type == MarketStateType.MIXED
        assert state.breadth_ratio == 0.5
        assert state.position_scale == 1.0
        assert state.adjusted_weights["trend"] == 0.30

    def test_default_adjusted_weights(self) -> None:
        state = MarketState()
        expected = {"trend": 0.30, "mean_reversion": 0.20, "fundamental": 0.30, "event_sentiment": 0.20}
        assert state.adjusted_weights == expected

    def test_position_scale_validation(self) -> None:
        with pytest.raises(ValidationError):
            MarketState(position_scale=1.5)
        with pytest.raises(ValidationError):
            MarketState(position_scale=-0.1)


# ---------------------------------------------------------------------------
# MarketStateType
# ---------------------------------------------------------------------------


class TestMarketStateType:
    def test_values(self) -> None:
        assert MarketStateType.TREND.value == "trend"
        assert MarketStateType.RANGE.value == "range"
        assert MarketStateType.MIXED.value == "mixed"
        assert MarketStateType.CRISIS.value == "crisis"


# ---------------------------------------------------------------------------
# FusedScore
# ---------------------------------------------------------------------------


class TestFusedScore:
    def test_classify_decision_strong_buy(self) -> None:
        assert FusedScore.classify_decision(0.6) == "strong_buy"
        assert FusedScore.classify_decision(1.0) == "strong_buy"

    def test_classify_decision_watch(self) -> None:
        assert FusedScore.classify_decision(0.5) == "watch"
        assert FusedScore.classify_decision(0.35) == "watch"

    def test_classify_decision_neutral(self) -> None:
        assert FusedScore.classify_decision(0.0) == "neutral"
        assert FusedScore.classify_decision(0.2) == "neutral"
        assert FusedScore.classify_decision(-0.1) == "neutral"

    def test_classify_decision_sell(self) -> None:
        assert FusedScore.classify_decision(-0.3) == "sell"
        assert FusedScore.classify_decision(-0.5) == "sell"

    def test_classify_decision_strong_sell(self) -> None:
        assert FusedScore.classify_decision(-0.6) == "strong_sell"
        assert FusedScore.classify_decision(-1.0) == "strong_sell"

    def test_classify_decision_boundaries(self) -> None:
        """Test exact boundary values."""
        # > 0.50 = strong_buy
        assert FusedScore.classify_decision(0.51) == "strong_buy"
        # >= 0.35 = watch
        assert FusedScore.classify_decision(0.35) == "watch"
        # 0.34 < 0.35 = neutral
        assert FusedScore.classify_decision(0.34) == "neutral"
        # >= -0.20 = neutral
        assert FusedScore.classify_decision(-0.20) == "neutral"
        # -0.21 < -0.20 = sell
        assert FusedScore.classify_decision(-0.21) == "sell"
        # >= -0.50 = sell
        assert FusedScore.classify_decision(-0.50) == "sell"
        # < -0.50 = strong_sell
        assert FusedScore.classify_decision(-0.51) == "strong_sell"

    def test_score_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            FusedScore(ticker="A", score_b=1.5)
        with pytest.raises(ValidationError):
            FusedScore(ticker="A", score_b=-1.5)

    def test_default_decision_neutral(self) -> None:
        f = FusedScore(ticker="A", score_b=0.0)
        assert f.decision == "neutral"

    def test_theme_fields(self) -> None:
        f = FusedScore(ticker="A", score_b=0.5, theme_name="AI", theme_category="科技", is_new_theme=True)
        assert f.theme_name == "AI"
        assert f.theme_category == "科技"
        assert f.is_new_theme is True


# ---------------------------------------------------------------------------
# ArbitrationAction
# ---------------------------------------------------------------------------


class TestArbitrationAction:
    def test_values(self) -> None:
        assert ArbitrationAction.AVOID.value == "avoid"
        assert ArbitrationAction.CONSENSUS_BONUS.value == "consensus_bonus"
        assert ArbitrationAction.RISK_OFF.value == "risk_off"


# ---------------------------------------------------------------------------
# CandidateStock
# ---------------------------------------------------------------------------


class TestCandidateStock:
    def test_minimal(self) -> None:
        c = CandidateStock(ticker="000001", name="平安")
        assert c.ticker == "000001"
        assert c.name == "平安"
        assert c.industry_sw == ""
        assert c.market_cap == 0.0
        assert c.avg_volume_20d == 0.0

    def test_full(self) -> None:
        c = CandidateStock(
            ticker="000001",
            name="平安",
            industry_sw="银行",
            market_cap=1e12,
            avg_volume_20d=1e7,
            listing_date="2020-01-01",
            disclosure_risk=True,
        )
        assert c.industry_sw == "银行"
        assert c.disclosure_risk is True

    def test_nan_market_cap_rejected(self) -> None:
        """R117 / NaN 防御: market_cap 与 avg_volume_20d 必须拒绝 NaN。

        背景: 两字段历史上是无约束 ``float = 0.0`` (unlike StrategySignal 的 ge/le)。
        Pydantic v2 对无约束 float 接受 NaN (已验证)。build_candidate_stocks 用
        ``mv_map.get(ts_code, 0.0) / 10000.0`` 与 ``amount_map.get(ts_code, 0.0)``
        填充, .get 只挡 missing key, 不挡已有 key 的 NaN 值 —— tushare/pandas 数据含
        NaN 时直接流入 model, 再进 _candidate_liquidity_sort_key /
        _technical_stage_ranking_key 的 sort tuple, NaN 让 sorted() 比较非确定性,
        候选池排序 (Layer A 入池 + scoring) 在受影响 cohort 上跨 run 不可复现。

        加 ``ge=0`` 约束 (与 StrategySignal 一致) 让 Pydantic 在模型层拒绝 NaN/负值,
        把数据脏值挡在排序前。服务"稳定找到" (候选池排序确定性 + 不被脏 NaN 值污染)。
        """
        import math

        with pytest.raises(ValidationError):
            CandidateStock(ticker="000001", name="平安", market_cap=float("nan"))
        with pytest.raises(ValidationError):
            CandidateStock(ticker="000001", name="平安", avg_volume_20d=float("nan"))

    def test_negative_market_cap_rejected(self) -> None:
        """R117: ge=0 同时拒绝负值 (market_cap/avg_volume_20d 物理上非负)。"""
        with pytest.raises(ValidationError):
            CandidateStock(ticker="000001", name="平安", market_cap=-1.0)
        with pytest.raises(ValidationError):
            CandidateStock(ticker="000001", name="平安", avg_volume_20d=-1.0)


# ---------------------------------------------------------------------------
# DEFAULT_STRATEGY_WEIGHTS
# ---------------------------------------------------------------------------


class TestDefaultStrategyWeights:
    def test_sums_to_one(self) -> None:
        # 相对权重 (88ce357e 调权): sum=0.8, 消费方 (signal_fusion/market_state)
        # 使用前统一按 total 归一.
        total = sum(DEFAULT_STRATEGY_WEIGHTS.values())
        assert abs(total - 0.8) < 1e-9

    def test_keys(self) -> None:
        assert set(DEFAULT_STRATEGY_WEIGHTS.keys()) == {"trend", "mean_reversion", "fundamental", "event_sentiment"}
