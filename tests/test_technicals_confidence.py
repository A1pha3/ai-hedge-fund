import math

from src.agents.technicals import generate_chinese_reasoning, safe_confidence, weighted_signal_combination


def test_safe_confidence_replaces_nan_and_clamps_range():
    assert safe_confidence(float("nan")) == 0.5
    assert safe_confidence(1.7) == 1.0
    assert safe_confidence(-0.2) == 0.0


def test_weighted_signal_combination_ignores_nan_confidence():
    combined = weighted_signal_combination(
        {
            "trend": {"signal": "bullish", "confidence": float("nan")},
            "mean_reversion": {"signal": "neutral", "confidence": 0.4},
            "momentum": {"signal": "bearish", "confidence": 0.7},
        },
        {
            "trend": 0.25,
            "mean_reversion": 0.35,
            "momentum": 0.40,
        },
    )

    assert combined["signal"] in {"bullish", "bearish", "neutral"}
    assert math.isfinite(combined["confidence"])
    assert 0.0 <= combined["confidence"] <= 1.0


def test_generate_chinese_reasoning_handles_nan_combined_confidence():
    reasoning = generate_chinese_reasoning(
        ticker="000001",
        combined_signal={"signal": "neutral", "confidence": float("nan")},
        strategy_signals={
            "trend": {"signal": "neutral", "confidence": float("nan"), "metrics": {}},
            "mean_reversion": {"signal": "neutral", "confidence": 0.5, "metrics": {}},
            "momentum": {"signal": "neutral", "confidence": 0.5, "metrics": {}},
            "volatility": {"signal": "neutral", "confidence": 0.5, "metrics": {}},
            "stat_arb": {"signal": "neutral", "confidence": 0.5, "metrics": {}},
        },
        weights={
            "trend": 0.25,
            "mean_reversion": 0.20,
            "momentum": 0.25,
            "volatility": 0.15,
            "stat_arb": 0.15,
        },
    )

    assert "nan" not in reasoning.lower()
    assert "50.0%" in reasoning


def test_generate_chinese_reasoning_preserves_bullish_mixed_strategy_narrative():
    reasoning = generate_chinese_reasoning(
        ticker="000001",
        combined_signal={"signal": "bullish", "confidence": 0.82},
        strategy_signals={
            "trend": {"signal": "bullish", "confidence": 0.91, "metrics": {"adx": 31.2, "trend_strength": 0.88}},
            "mean_reversion": {"signal": "neutral", "confidence": 0.42, "metrics": {"z_score": -0.4, "price_vs_bb": 0.45, "rsi_14": 51.2, "rsi_28": 49.8}},
            "momentum": {"signal": "bullish", "confidence": 0.76, "metrics": {"momentum_1m": 0.12, "momentum_3m": 0.18, "momentum_6m": 0.24, "volume_momentum": 1.35}},
            "volatility": {"signal": "neutral", "confidence": 0.55, "metrics": {"historical_volatility": 0.23, "volatility_regime": 0.96, "volatility_z_score": 0.1, "atr_ratio": 0.041}},
            "stat_arb": {"signal": "bearish", "confidence": 0.61, "metrics": {"hurst_exponent": 0.37, "skewness": -1.2, "kurtosis": 2.8}},
        },
        weights={
            "trend": 0.25,
            "mean_reversion": 0.20,
            "momentum": 0.25,
            "volatility": 0.15,
            "stat_arb": 0.15,
        },
    )

    assert "【综合信号】看涨 (置信度: 82.0%)" in reasoning
    assert "【趋势跟踪】权重25% - 看涨 (置信度: 91.0%)" in reasoning
    assert "  • 解读: EMA8>EMA21且EMA21>EMA55，短期和中期趋势均为上升" in reasoning
    assert "【动量分析】权重25% - 看涨 (置信度: 76.0%)" in reasoning
    assert "  • 1月动量: 12.00%, 3月动量: 18.00%, 6月动量: 24.00%" in reasoning
    assert "【统计套利】权重15% - 看跌 (置信度: 61.0%)" in reasoning
    assert "  • 看涨策略: 2/5, 看跌策略: 1/5, 中性策略: 2/5" in reasoning
    assert "  • 多数策略指向看涨，建议关注买入机会" in reasoning


def test_generate_chinese_reasoning_preserves_bearish_branch_explanations():
    reasoning = generate_chinese_reasoning(
        ticker="600000",
        combined_signal={"signal": "bearish", "confidence": 0.67},
        strategy_signals={
            "trend": {"signal": "bearish", "confidence": 0.72, "metrics": {"adx": 28.0, "trend_strength": -0.64}},
            "mean_reversion": {"signal": "bearish", "confidence": 0.81, "metrics": {"z_score": 2.4, "price_vs_bb": 0.92, "rsi_14": 73.0, "rsi_28": 68.0}},
            "momentum": {"signal": "neutral", "confidence": 0.48, "metrics": {"momentum_1m": -0.01, "momentum_3m": 0.02, "momentum_6m": 0.03, "volume_momentum": 0.94}},
            "volatility": {"signal": "bearish", "confidence": 0.74, "metrics": {"historical_volatility": 0.31, "volatility_regime": 1.35, "volatility_z_score": 1.7, "atr_ratio": 0.063}},
            "stat_arb": {"signal": "neutral", "confidence": 0.58, "metrics": {"hurst_exponent": 0.53, "skewness": 0.12, "kurtosis": 1.1}},
        },
        weights={
            "trend": 0.25,
            "mean_reversion": 0.20,
            "momentum": 0.25,
            "volatility": 0.15,
            "stat_arb": 0.15,
        },
    )

    assert "【综合信号】看跌 (置信度: 67.0%)" in reasoning
    assert "  • 解读: EMA8<EMA21且EMA21<EMA55，短期和中期趋势均为下降" in reasoning
    assert "  • 解读: 价格显著高于均值(Z>2)且接近布林带上轨，存在回调风险" in reasoning
    assert "  • 解读: 处于高波动区间，波动率有望收缩，可能伴随价格调整" in reasoning
    assert "  • 看涨策略: 0/5, 看跌策略: 3/5, 中性策略: 2/5" in reasoning
    assert "  • 多数策略指向看跌，建议关注卖出或规避风险" in reasoning
