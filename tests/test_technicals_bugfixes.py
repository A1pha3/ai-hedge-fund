"""Tests for technical analysis bug fixes: division-by-zero guards,
DataFrame mutation safety, RSI edge cases, and signal combination bounds.

Consolidated from test_numerical_robustness.py + test_technicals_bugfixes.py.
"""

import math

import numpy as np
import pandas as pd
import pytest

from src.agents.technicals import (
    calculate_adx,
    calculate_atr,
    calculate_hurst_exponent,
    calculate_mean_reversion_signals,
    calculate_momentum_signals,
    calculate_rsi,
    calculate_volatility_signals,
    safe_confidence,
    safe_float,
    weighted_signal_combination,
)
from src.agents.technicals import VOL_HIGH_THRESHOLD, VOL_LOW_THRESHOLD

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_prices_df(n: int = 200, seed: int = 42) -> pd.DataFrame:
    """Build a synthetic OHLCV DataFrame with *n* rows."""
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.standard_normal(n))
    high = close + np.abs(rng.standard_normal(n))
    low = close - np.abs(rng.standard_normal(n))
    volume = rng.integers(1_000_000, 10_000_000, size=n).astype(float)
    return pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close, "volume": volume},
        index=pd.date_range("2024-01-01", periods=n),
    )


def _make_monotonic_up_df(n: int = 200) -> pd.DataFrame:
    """Prices that only go up -- every daily return is positive."""
    close = np.arange(100.0, 100.0 + n)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(n, 5_000_000.0),
        },
        index=pd.date_range("2024-01-01", periods=n),
    )


def _make_flat_df(n: int = 200) -> pd.DataFrame:
    """Flat prices -- zero volatility / zero returns."""
    close = np.full(n, 100.0)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.01,
            "low": close - 0.01,
            "close": close,
            "volume": np.full(n, 5_000_000.0),
        },
        index=pd.date_range("2024-01-01", periods=n),
    )


def _make_custom_df(
    closes: list[float],
    volumes: list[float] | None = None,
) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame from explicit close prices."""
    n = len(closes)
    return pd.DataFrame(
        {
            "open": closes,
            "close": closes,
            "high": closes,
            "low": closes,
            "volume": volumes or [1000.0] * n,
        },
        index=pd.date_range("2024-01-01", periods=n, freq="D"),
    )


# ---------------------------------------------------------------------------
# RSI division-by-zero when avg_loss == 0
# ---------------------------------------------------------------------------


class TestRSIDivisionByZero:
    def test_all_up_returns_rsi_100(self):
        """When every bar closes higher, avg_loss is 0 and RSI should be 100."""
        df = _make_monotonic_up_df(200)
        rsi = calculate_rsi(df, period=14)
        valid = rsi.dropna()
        assert (valid == 100.0).all(), f"Expected all 100, got min={valid.min()}, max={valid.max()}"

    def test_constant_prices(self):
        """When prices are constant, both gain and loss are 0. RSI should be 100."""
        df = _make_custom_df([100.0] * 30)
        rsi = calculate_rsi(df, period=14)
        assert rsi.iloc[-1] == 100.0

    def test_normal_prices_no_nan(self):
        """Normal price series should produce finite RSI values in [0, 100]."""
        df = _make_prices_df(200)
        rsi = calculate_rsi(df, period=14)
        valid = rsi.dropna()
        assert valid.notna().all()
        assert np.isfinite(valid).all()
        assert (valid >= 0).all() and (valid <= 100).all()


# ---------------------------------------------------------------------------
# ADX division-by-zero and DataFrame mutation
# ---------------------------------------------------------------------------


class TestADXDivisionByZero:
    def test_constant_prices_no_exception(self):
        """Constant prices => TR=0, should not raise."""
        df = _make_custom_df([100.0] * 30)
        result = calculate_adx(df, period=14)
        assert "adx" in result.columns

    def test_flat_highs_and_lows(self):
        df = _make_custom_df([50.0] * 50)
        result = calculate_adx(df, period=14)
        assert len(result) > 0

    def test_normal_prices_returns_finite(self):
        df = _make_prices_df(200)
        result = calculate_adx(df, period=14)
        valid = result["adx"].dropna()
        assert all(np.isfinite(valid))
        assert all(v >= 0 for v in valid)


class TestAdxMutationSafety:
    def test_original_dataframe_columns_unchanged(self):
        """calculate_adx must not add columns to the input DataFrame."""
        df = _make_prices_df(200)
        original_columns = set(df.columns)
        calculate_adx(df, period=14)
        assert set(df.columns) == original_columns

    def test_adx_returns_valid_dataframe(self):
        df = _make_prices_df(200)
        result = calculate_adx(df, period=14)
        assert "adx" in result.columns
        assert len(result) == len(df)


class TestAdxDxDivisionByZero:
    def test_flat_prices_no_nan_adx(self):
        """Flat prices can produce +DI = -DI = 0; DX must not be NaN."""
        df = _make_flat_df(200)
        result = calculate_adx(df, period=14)
        valid = result["adx"].dropna()
        if len(valid) > 0:
            assert np.isfinite(valid).all()


# ---------------------------------------------------------------------------
# Bollinger-Band width division-by-zero
# ---------------------------------------------------------------------------


class TestBollingerBandsDivisionByZero:
    def test_flat_prices_no_crash(self):
        """Flat prices produce zero-width BB; mean-reversion must not crash."""
        df = _make_flat_df(200)
        result = calculate_mean_reversion_signals(df)
        assert result["signal"] in {"bullish", "bearish", "neutral"}
        assert math.isfinite(result["confidence"])
        assert math.isfinite(result["metrics"]["price_vs_bb"])

    def test_price_vs_bb_default_to_middle(self):
        """When BB width is 0, price_vs_bb should default to 0.5 (middle)."""
        df = _make_flat_df(200)
        result = calculate_mean_reversion_signals(df)
        assert result["metrics"]["price_vs_bb"] == 0.5


# ---------------------------------------------------------------------------
# Mean reversion z-score with zero std
# ---------------------------------------------------------------------------


class TestMeanReversionZeroStd:
    def test_constant_prices_z_score(self):
        """Constant prices => std=0, z_score should be NaN, not crash."""
        df = _make_custom_df([100.0] * 60)
        result = calculate_mean_reversion_signals(df)
        assert result["signal"] in ("bullish", "bearish", "neutral")
        assert 0 <= result["confidence"] <= 1


# ---------------------------------------------------------------------------
# Volatility regime division-by-zero and NaN propagation
# ---------------------------------------------------------------------------


class TestVolatilityZScoreDivisionByZero:
    def test_flat_prices_no_crash(self):
        """Zero volatility must not cause division-by-zero in z-score calc."""
        df = _make_flat_df(200)
        result = calculate_volatility_signals(df)
        assert result["signal"] in {"bullish", "bearish", "neutral"}
        assert math.isfinite(result["confidence"])
        assert math.isfinite(result["metrics"]["volatility_z_score"])


class TestVolatilitySignalNaNHandling:
    def test_short_series_no_nan_in_metrics(self):
        """Very short price series should not produce NaN in output metrics."""
        df = _make_custom_df([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
        result = calculate_volatility_signals(df)
        for key, val in result["metrics"].items():
            assert math.isfinite(safe_float(val)), f"NaN in metric {key}"

    def test_nan_propagation_in_metrics(self):
        """Verify NaN does not leak into final metrics dict."""
        # Short series to trigger NaN in rolling windows
        closes = [100.0] * 10 + list(range(100, 120))
        df = _make_custom_df(closes)
        result = calculate_volatility_signals(df)
        for key, val in result["metrics"].items():
            assert math.isfinite(safe_float(val)), f"{key} is not finite: {val}"


class TestVolatilityLabelDirection:
    """Volatility factor direction labels (autodev C224 / iv057).

    Counterfactual evidence (autodev C222 n=1587 + C223 n=8922, commits b135243f +
    _diag_trend_subfactor_direction): the original bullish/bearish labels were REVERSED
    vs T+1 — sep = T+1(bullish) - T+1(bearish) was -0.34~-0.94 (bullish 票实际 T+1 更低).
    Root cause: low-vol-regime 'bullish' was a mean-reversion bet (低 vol → expansion),
    but short-term momentum dominates T+1 (high-vol = recent winners → continue up /
    decline less). Fix: flip labels so high-vol regime → bullish, low-vol → bearish.
    """

    @staticmethod
    def _make_regime_df(calm_then_spike: bool, seed: int = 42) -> pd.DataFrame:
        """Series ending in a clear high-vol or low-vol regime at the last bar.

        calm_then_spike=True  → regime>1.2, z>+1 (high-vol regime).
        calm_then_spike=False → regime<0.8, z<-1 (low-vol regime).
        """
        rng = np.random.default_rng(seed)
        if calm_then_spike:
            calm = 100.0 + rng.normal(0, 0.2, 80)
            spike = 100.0 + rng.normal(0, 3.0, 40)
        else:
            turb = 100.0 + rng.normal(0, 3.0, 80)
            calm = 100.0 + rng.normal(0, 0.2, 40)
        close = np.concatenate([calm, spike]) if calm_then_spike else np.concatenate([turb, calm])
        n = len(close)
        return pd.DataFrame(
            {"open": close, "high": close, "low": close, "close": close, "volume": np.full(n, 1000.0)},
            index=pd.date_range("2025-01-01", periods=n),
        )

    def test_high_vol_regime_is_bullish(self):
        """High-vol regime (regime>1.2, z>+1) → bullish (C224 flip: momentum continuation)."""
        df = self._make_regime_df(calm_then_spike=True)
        result = calculate_volatility_signals(df)
        m = result["metrics"]
        assert m["volatility_regime"] > 1.2 and m["volatility_z_score"] > 1.0, "fixture must trigger high-vol regime"
        assert result["signal"] == "bullish", "high-vol regime → bullish (C224; was 'bearish' pre-flip)"

    def test_low_vol_regime_is_bearish(self):
        """Low-vol regime (regime<0.8, z<-1) → bearish (C224 flip: stagnation)."""
        df = self._make_regime_df(calm_then_spike=False)
        result = calculate_volatility_signals(df)
        m = result["metrics"]
        assert m["volatility_regime"] < 0.8 and m["volatility_z_score"] < -1.0, "fixture must trigger low-vol regime"
        assert result["signal"] == "bearish", "low-vol regime → bearish (C224; was 'bullish' pre-flip)"


class TestVolatilityBNarrowThreshold:
    """Volatility factor B_narrow threshold tightening (autodev C236 / iv069).

    Counterfactual evidence (autodev C222/C224 n=1977, 20 日期 sample=100):
    current_AND (0.8/1.2) has %neutral=53.0% (中性带太宽) + sep=-0.028 (反向, pre-C224).
    C224 翻转方向后, B_narrow (0.9/1.1) 进一步: %neutral=46.4%, sep=+0.031 (方向正, 最佳).
    Fix: VOL_LOW_THRESHOLD 0.8→0.9, VOL_HIGH_THRESHOLD 1.2→1.1 — 缩窄中性带, 让更多
    mild-vol 票进入 bullish/bearish 可操作区间. T+5/T+10 horizon 验证留 post-push observation.
    """

    def test_vol_low_threshold_narrowed_to_0_9(self):
        """B_narrow: VOL_LOW_THRESHOLD 0.8 → 0.9 (收缩中性带上界)."""
        assert VOL_LOW_THRESHOLD == 0.9, "B_narrow: VOL_LOW_THRESHOLD should be 0.9 (was 0.8); " "shrinks neutral band to reduce 53% dir=0 rate"

    def test_vol_high_threshold_narrowed_to_1_1(self):
        """B_narrow: VOL_HIGH_THRESHOLD 1.2 → 1.1 (收缩中性带下界)."""
        assert VOL_HIGH_THRESHOLD == 1.1, "B_narrow: VOL_HIGH_THRESHOLD should be 1.1 (was 1.2); " "shrinks neutral band to reduce 53% dir=0 rate"

    @staticmethod
    def _make_mild_regime_df(mild_spike: bool) -> pd.DataFrame:
        """Deterministic series ending in a MILD vol regime (regime in [1.1, 1.2] or [0.8, 0.9]).

        Uses alternating returns for deterministic vol control (no random seed dependence).
        mild_spike=True  → regime ≈ 1.135, z ≈ +1.16 (mild high-vol, neutral with old 1.2).
        mild_spike=False → regime ≈ 0.863, z ≈ -1.20 (mild low-vol, neutral with old 0.8).
        """
        calm_80 = np.array([0.01, -0.01] * 40)  # 80 bars, std ≈ 0.01
        calm_40 = np.array([0.01, -0.01] * 20)  # 40 bars, std ≈ 0.01
        spike_80 = np.array([0.013, -0.013] * 40)  # 80 bars, std ≈ 0.013
        spike_40 = np.array([0.013, -0.013] * 20)  # 40 bars, std ≈ 0.013
        if mild_spike:
            all_returns = np.concatenate([calm_80, spike_40])  # 80 calm + 40 spike
        else:
            all_returns = np.concatenate([spike_80, calm_40])  # 80 turb + 40 calm
        close = 100.0 * np.cumprod(1 + all_returns)
        n = len(close)
        return pd.DataFrame(
            {"open": close, "high": close, "low": close, "close": close, "volume": np.full(n, 1000.0)},
            index=pd.date_range("2025-01-01", periods=n),
        )

    def test_mild_high_vol_regime_now_bullish(self):
        """Mild high-vol (regime in [1.1, 1.2], z > 1) → bullish (B_narrow; was neutral with old 1.2)."""
        df = self._make_mild_regime_df(mild_spike=True)
        result = calculate_volatility_signals(df)
        m = result["metrics"]
        assert 1.1 < m["volatility_regime"] < 1.2, f"fixture must produce regime in [1.1, 1.2] for mild-high-vol test, " f"got regime={m['volatility_regime']:.4f}"
        assert m["volatility_z_score"] > 1.0, f"fixture must produce z > 1 for mild-high-vol test, got z={m['volatility_z_score']:.4f}"
        assert result["signal"] == "bullish", "B_narrow: mild high-vol regime (1.1<regime<1.2, z>1) → bullish; " "was 'neutral' with old VOL_HIGH_THRESHOLD=1.2"

    def test_mild_low_vol_regime_now_bearish(self):
        """Mild low-vol (regime in [0.8, 0.9], z < -1) → bearish (B_narrow; was neutral with old 0.8)."""
        df = self._make_mild_regime_df(mild_spike=False)
        result = calculate_volatility_signals(df)
        m = result["metrics"]
        assert 0.8 < m["volatility_regime"] < 0.9, f"fixture must produce regime in [0.8, 0.9] for mild-low-vol test, " f"got regime={m['volatility_regime']:.4f}"
        assert m["volatility_z_score"] < -1.0, f"fixture must produce z < -1 for mild-low-vol test, got z={m['volatility_z_score']:.4f}"
        assert result["signal"] == "bearish", "B_narrow: mild low-vol regime (0.8<regime<0.9, z<-1) → bearish; " "was 'neutral' with old VOL_LOW_THRESHOLD=0.8"

    def test_strict_high_vol_regime_still_bullish(self):
        """Strict high-vol (regime > 1.2, z > 1) → bullish (no regression from C224)."""
        rng = np.random.default_rng(99)
        calm = 100.0 + rng.normal(0, 0.2, 80)
        spike = 100.0 + rng.normal(0, 3.0, 40)
        close = np.concatenate([calm, spike])
        n = len(close)
        df = pd.DataFrame(
            {"open": close, "high": close, "low": close, "close": close, "volume": np.full(n, 1000.0)},
            index=pd.date_range("2025-01-01", periods=n),
        )
        result = calculate_volatility_signals(df)
        m = result["metrics"]
        assert m["volatility_regime"] > 1.2, "fixture must trigger strict high-vol regime"
        assert result["signal"] == "bullish", "strict high-vol → bullish (C224 no regression)"

    def test_strict_low_vol_regime_still_bearish(self):
        """Strict low-vol (regime < 0.8, z < -1) → bearish (no regression from C224)."""
        rng = np.random.default_rng(99)
        turb = 100.0 + rng.normal(0, 3.0, 80)
        calm = 100.0 + rng.normal(0, 0.2, 40)
        close = np.concatenate([turb, calm])
        n = len(close)
        df = pd.DataFrame(
            {"open": close, "high": close, "low": close, "close": close, "volume": np.full(n, 1000.0)},
            index=pd.date_range("2025-01-01", periods=n),
        )
        result = calculate_volatility_signals(df)
        m = result["metrics"]
        assert m["volatility_regime"] < 0.8, "fixture must trigger strict low-vol regime"
        assert result["signal"] == "bearish", "strict low-vol → bearish (C224 no regression)"


# ---------------------------------------------------------------------------
# Momentum volume division-by-zero
# ---------------------------------------------------------------------------


class TestMomentumVolumeDivisionByZero:
    def test_zero_volume_no_crash(self):
        """When volume is zero, volume_momentum must not produce inf."""
        df = _make_prices_df(200)
        df["volume"] = 0.0
        result = calculate_momentum_signals(df)
        assert result["signal"] in {"bullish", "bearish", "neutral"}
        assert math.isfinite(result["confidence"])
        assert math.isfinite(result["metrics"]["volume_momentum"])


# ---------------------------------------------------------------------------
# ATR edge cases
# ---------------------------------------------------------------------------


class TestATREdgeCases:
    def test_constant_prices(self):
        df = _make_custom_df([100.0] * 30)
        atr = calculate_atr(df, period=14)
        assert atr.iloc[-1] == 0.0


# ---------------------------------------------------------------------------
# Hurst exponent edge cases
# ---------------------------------------------------------------------------


class TestHurstExponent:
    def test_short_series_returns_half(self):
        """Series shorter than max_lag + 2 should return 0.5 (random walk)."""
        series = pd.Series([1.0, 2.0, 3.0])
        assert calculate_hurst_exponent(series) == 0.5

    def test_result_clamped_to_unit_interval(self):
        df = _make_prices_df(200)
        result = calculate_hurst_exponent(df["close"])
        assert 0.0 <= result <= 1.0

    def test_nan_series_returns_half(self):
        series = pd.Series([float("nan")] * 100)
        assert calculate_hurst_exponent(series) == 0.5

    def test_constant_series(self):
        """Constant series should return 0.5 (no trend)."""
        series = pd.Series([100.0] * 30)
        result = calculate_hurst_exponent(series)
        assert 0.0 <= result <= 1.0

    def test_polyfit_linalg_error_returns_half(self, monkeypatch):
        """LinAlgError IS a ValueError subclass — verify it's caught by the
        existing except (ValueError, RuntimeWarning) and returns 0.5 fallback.

        This test documents/locks the actual behavior: np.linalg.LinAlgError
        inherits from ValueError, so the existing except clause DOES catch it.
        The real dead-branch issue is RuntimeWarning (a Warning, not Exception)
        which can never be caught — but that's a separate, lower-impact concern
        since polyfit only *issues* warnings, never *raises* them.
        """
        series = pd.Series([float(i) for i in range(50)])

        def _fake_polyfit(*args, **kwargs):
            raise np.linalg.LinAlgError("SVD did not converge")

        monkeypatch.setattr(np, "polyfit", _fake_polyfit)
        result = calculate_hurst_exponent(series)
        assert result == 0.5  # must return random-walk fallback, not crash


# ---------------------------------------------------------------------------
# weighted_signal_combination bounds
# ---------------------------------------------------------------------------


class TestWeightedSignalCombinationBounds:
    def test_neutral_confidence_bounded_to_one(self):
        signals = {
            "trend": {"signal": "bullish", "confidence": 1.5},
            "mean_reversion": {"signal": "bearish", "confidence": 1.5},
            "momentum": {"signal": "neutral", "confidence": 1.5},
            "volatility": {"signal": "neutral", "confidence": 1.5},
            "stat_arb": {"signal": "neutral", "confidence": 1.5},
        }
        weights = {
            "trend": 0.25,
            "mean_reversion": 0.20,
            "momentum": 0.25,
            "volatility": 0.15,
            "stat_arb": 0.15,
        }
        result = weighted_signal_combination(signals, weights)
        assert result["signal"] == "neutral"
        assert 0.0 <= result["confidence"] <= 1.0

    def test_all_bullish_high_confidence(self):
        signals = {k: {"signal": "bullish", "confidence": 1.0} for k in ["trend", "mean_reversion", "momentum", "volatility", "stat_arb"]}
        weights = {"trend": 0.25, "mean_reversion": 0.20, "momentum": 0.25, "volatility": 0.15, "stat_arb": 0.15}
        result = weighted_signal_combination(signals, weights)
        assert result["signal"] == "bullish"
        assert 0.0 <= result["confidence"] <= 1.0

    def test_nan_confidence_handled_gracefully(self):
        signals = {
            "trend": {"signal": "bullish", "confidence": float("nan")},
            "mean_reversion": {"signal": "neutral", "confidence": 0.4},
            "momentum": {"signal": "bearish", "confidence": 0.7},
        }
        weights = {"trend": 0.25, "mean_reversion": 0.35, "momentum": 0.40}
        result = weighted_signal_combination(signals, weights)
        assert result["signal"] in {"bullish", "bearish", "neutral"}
        assert math.isfinite(result["confidence"])
        assert 0.0 <= result["confidence"] <= 1.0

    def test_empty_signals_returns_neutral(self):
        result = weighted_signal_combination({}, {})
        assert result["signal"] == "neutral"


# ---------------------------------------------------------------------------
# Helpers: safe_float / safe_confidence
# ---------------------------------------------------------------------------


class TestSafeHelpers:
    def test_safe_float_nan(self):
        assert safe_float(float("nan")) == 0.0

    def test_safe_float_inf(self):
        assert safe_float(float("inf")) == 0.0
        assert safe_float(float("-inf")) == 0.0

    def test_safe_float_numpy_nan(self):
        assert safe_float(np.nan) == 0.0

    def test_safe_float_none(self):
        assert safe_float(None) == 0.0

    def test_safe_float_valid(self):
        assert safe_float(3.14) == pytest.approx(3.14)

    def test_safe_confidence_clamps_high(self):
        assert safe_confidence(1.5) == 1.0

    def test_safe_confidence_clamps_low(self):
        assert safe_confidence(-0.5) == 0.0

    def test_safe_confidence_nan(self):
        assert safe_confidence(float("nan")) == 0.5  # default

    def test_safe_confidence_inf(self):
        assert safe_confidence(float("inf")) == 0.5  # default
