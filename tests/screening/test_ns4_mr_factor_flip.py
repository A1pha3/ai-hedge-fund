"""NS-4 mean-reversion factor direction flip (autodev / owner directive 2026-06-30).

Counterfactual evidence (autodev C225, commit 55d98538, n=1193/factor): all 4 MR
sub-factors were REVERSED vs T+1 — zscore_bbands sep=-2.58%, rsi_extreme -2.15%,
stat_arb -1.04%, hurst_regime -2.50% (ALL sep<0). Root cause (same as the volatility
factor C222-C224, commit 9059a4cf): MR uses mean-reversion logic (oversold→bullish,
overbought→bearish), but short-term momentum dominates T+1 — oversold 票 continue
falling, overbought continue rising. So the MR signals are systematically anti-correlated.

Fix (mirrors C224 volatility label flip): flip MR signal directions so oversold→bearish,
overbought→bullish (momentum-following). For the 3 pure sign-inversion factors
(zscore_bbands / rsi_extreme / stat_arb) sep negates by construction —
sep_new = T+1(dir_new=+1) − T+1(dir_new=−1) = T+1(dir_old=−1) − T+1(dir_old=+1) = −sep_old.
hurst_regime flip is surgical: only the mean-reverting-regime branch (hurst<0.45) flips;
the trending-regime branch (hurst>0.55) was already momentum-following (correct) and is
left unchanged.
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd

from src.agents.technicals import (
    calculate_mean_reversion_signals,
    calculate_stat_arb_signals,
)
from src.screening.strategy_scorer_mean_reversion import (
    _resolve_hurst_regime_signal,
    _resolve_rsi_extreme_signal,
    HurstRegimeSnapshot,
    score_mean_reversion_strategy,
)


def _make_steady_then_jump_df(jump_pct: float, seed: int = 42, n_steady: int = 79) -> pd.DataFrame:
    """Low-variance steady series, then a sharp jump on the last bar.

    jump_pct>0 → overbought (z>+2, price_vs_bb>0.8); jump_pct<0 → oversold (z<-2, price_vs_bb<0.2).
    """
    rng = np.random.default_rng(seed)
    steady = 100.0 + rng.normal(0, 0.3, n_steady)
    last = np.array([steady[-1] * (1.0 + jump_pct)])
    close = np.concatenate([steady, last])
    idx = pd.date_range("2025-01-01", periods=len(close))
    return pd.DataFrame(
        {"open": close, "high": close + 0.3, "low": close - 0.3, "close": close, "volume": np.full(len(close), 1000.0)},
        index=idx,
    )


class TestNS4zscoreBbandsDirection:
    """zscore_bbands (calculate_mean_reversion_signals): oversold→bearish, overbought→bullish (flipped)."""

    def test_oversold_is_bearish(self):
        df = _make_steady_then_jump_df(jump_pct=-0.10)  # sharp drop → oversold
        result = calculate_mean_reversion_signals(df)
        m = result["metrics"]
        assert m["z_score"] < -2.0 and m["price_vs_bb"] < 0.2, f"fixture must trigger oversold (z={m['z_score']:.2f}, pvsbb={m['price_vs_bb']:.2f})"
        assert result["signal"] == "bearish", "oversold → bearish (NS-4 flip; was 'bullish' pre-flip)"

    def test_overbought_is_bullish(self):
        df = _make_steady_then_jump_df(jump_pct=+0.10)  # sharp rise → overbought
        result = calculate_mean_reversion_signals(df)
        m = result["metrics"]
        assert m["z_score"] > 2.0 and m["price_vs_bb"] > 0.8, f"fixture must trigger overbought (z={m['z_score']:.2f}, pvsbb={m['price_vs_bb']:.2f})"
        assert result["signal"] == "bullish", "overbought → bullish (NS-4 flip; was 'bearish' pre-flip)"


class TestNS4StatArbDirection:
    """stat_arb (calculate_stat_arb_signals): low-hurst+positive-skew→bearish, negative-skew→bullish (flipped)."""

    def test_positive_skew_low_hurst_is_bearish(self):
        df = _make_steady_then_jump_df(jump_pct=+0.12)  # one large positive return → positive skew
        with patch("src.agents.technicals.calculate_hurst_exponent", return_value=0.35):  # < STAT_ARB_HURST_BULL=0.4
            result = calculate_stat_arb_signals(df)
        assert result["metrics"]["hurst_exponent"] < 0.4
        assert result["metrics"]["skewness"] > 1.0, f"fixture must trigger positive skew (skew={result['metrics']['skewness']:.2f})"
        assert result["signal"] == "bearish", "low hurst + positive skew → bearish (NS-4 flip; was 'bullish')"

    def test_negative_skew_low_hurst_is_bullish(self):
        df = _make_steady_then_jump_df(jump_pct=-0.12)  # one large negative return → negative skew
        with patch("src.agents.technicals.calculate_hurst_exponent", return_value=0.35):
            result = calculate_stat_arb_signals(df)
        assert result["metrics"]["skewness"] < -1.0, f"fixture must trigger negative skew (skew={result['metrics']['skewness']:.2f})"
        assert result["signal"] == "bullish", "low hurst + negative skew → bullish (NS-4 flip; was 'bearish')"


class TestNS4RsiExtremeDirection:
    """rsi_extreme: oversold(RSI<30)→-1, overbought(RSI>70)→+1 (flipped)."""

    def test_oversold_is_bearish(self):
        direction, _conf = _resolve_rsi_extreme_signal(last_rsi_14=25.0, last_rsi_28=35.0)
        assert direction == -1, "RSI<30 oversold → bearish (NS-4 flip; was +1)"

    def test_overbought_is_bullish(self):
        direction, _conf = _resolve_rsi_extreme_signal(last_rsi_14=75.0, last_rsi_28=65.0)
        assert direction == 1, "RSI>70 overbought → bullish (NS-4 flip; was -1)"

    def test_neutral_band_unchanged(self):
        direction, _conf = _resolve_rsi_extreme_signal(last_rsi_14=50.0, last_rsi_28=50.0)
        assert direction == 0, "mid-range RSI → neutral (unchanged)"


class TestNS4HurstRegimeDirection:
    """hurst_regime: mean-reverting regime (hurst<0.45) branch FLIPPED; trending regime (hurst>0.55) UNCHANGED."""

    def test_mean_reverting_oversold_is_bearish(self):
        snap = HurstRegimeSnapshot(hurst=0.40, z_score=-1.5, completeness=1.0)
        direction, _conf = _resolve_hurst_regime_signal(snap)
        assert direction == -1, "hurst<0.45 + z<-1 (oversold) → bearish (NS-4 flip; was +1)"

    def test_mean_reverting_overbought_is_bullish(self):
        snap = HurstRegimeSnapshot(hurst=0.40, z_score=+1.5, completeness=1.0)
        direction, _conf = _resolve_hurst_regime_signal(snap)
        assert direction == 1, "hurst<0.45 + z>+1 (overbought) → bullish (NS-4 flip; was -1)"

    def test_trending_above_ma_still_bullish(self):
        """Trending regime (hurst>0.55) was already momentum-following (correct) — NOT flipped."""
        snap = HurstRegimeSnapshot(hurst=0.62, z_score=+0.5, completeness=1.0)
        direction, _conf = _resolve_hurst_regime_signal(snap)
        assert direction == 1, "trending + above MA → bullish (UNCHANGED; already correct momentum-following)"

    def test_trending_below_ma_still_bearish(self):
        snap = HurstRegimeSnapshot(hurst=0.62, z_score=-0.5, completeness=1.0)
        direction, _conf = _resolve_hurst_regime_signal(snap)
        assert direction == -1, "trending + below MA → bearish (UNCHANGED)"


class TestNS4EndToEndFlip:
    """End-to-end: score_mean_reversion_strategy on an oversold fixture → bearish aggregate (flipped)."""

    def test_oversold_fixture_aggregates_bearish(self):
        df = _make_steady_then_jump_df(jump_pct=-0.12)
        result = score_mean_reversion_strategy(df)
        # The aggregate MR strategy signal should be bearish (or neutral if confidence thresholds unmet),
        # but NEVER bullish on an oversold-only fixture post-flip.
        assert result.direction != 1, f"oversold fixture must not aggregate bullish post-flip (got direction={result.direction})"
