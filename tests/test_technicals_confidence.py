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
