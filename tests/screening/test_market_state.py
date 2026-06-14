"""Tests for src/screening/market_state.py — market state detector helpers."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from src.screening.market_state import (
    _market_breadth_ratio,
    _normalize_weights,
    _northbound_streak,
)

# ---------------------------------------------------------------------------
# _normalize_weights
# ---------------------------------------------------------------------------


class TestNormalizeWeights:
    def test_normal(self) -> None:
        w = {"trend": 0.4, "mean_reversion": 0.3, "fundamental": 0.2, "event_sentiment": 0.1}
        result = _normalize_weights(w)
        assert sum(result.values()) == pytest.approx(1.0)
        assert result["trend"] == pytest.approx(0.4)

    def test_zero_total_uses_default(self) -> None:
        w = {"trend": 0.0, "mean_reversion": 0.0}
        result = _normalize_weights(w)
        # Falls back to DEFAULT_STRATEGY_WEIGHTS
        assert result["trend"] == 0.30

    def test_negative_clamped(self) -> None:
        w = {"trend": 0.6, "mean_reversion": -0.1, "fundamental": 0.3, "event_sentiment": 0.2}
        result = _normalize_weights(w)
        assert result["mean_reversion"] == 0.0
        # total: 0.6 + 0 + 0.3 + 0.2 = 1.1 → trend = 0.6/1.1
        assert result["trend"] == pytest.approx(0.6 / 1.1)

    def test_all_zero_uses_default(self) -> None:
        result = _normalize_weights({"trend": 0.0, "mean_reversion": 0.0, "fundamental": 0.0, "event_sentiment": 0.0})
        assert result == {"trend": 0.30, "mean_reversion": 0.20, "fundamental": 0.30, "event_sentiment": 0.20}


# ---------------------------------------------------------------------------
# _northbound_streak
# ---------------------------------------------------------------------------


class TestNorthboundStreak:
    def test_empty(self) -> None:
        assert _northbound_streak(pd.DataFrame()) == 0

    def test_none(self) -> None:
        assert _northbound_streak(None) == 0  # type: ignore[arg-type]

    def test_positive_streak(self) -> None:
        df = pd.DataFrame({"north_money": [10, 20, 30]})
        # reversed: [30, 20, 10] → all positive, streak=3
        assert _northbound_streak(df) == 3

    def test_negative_streak(self) -> None:
        df = pd.DataFrame({"north_money": [-10, -20, -30]})
        assert _northbound_streak(df) == -3

    def test_streak_breaks_on_zero(self) -> None:
        """[10, 20, 0] → reversed: [0, 20, 10] → 0 breaks immediately, streak=0."""
        df = pd.DataFrame({"north_money": [10, 20, 0]})
        assert _northbound_streak(df) == 0

    def test_streak_breaks_on_direction_change(self) -> None:
        df = pd.DataFrame({"north_money": [10, -5, 20]})
        # reversed: [20, -5, 10] → 20 positive, -5 breaks streak
        assert _northbound_streak(df) == 1

    def test_nan_breaks(self) -> None:
        """NaN breaks streak."""
        df = pd.DataFrame({"north_money": [10.0, float("nan")]})
        # reversed: [NaN, 10.0] → NaN breaks immediately
        assert _northbound_streak(df) == 0

    def test_nan_at_end(self) -> None:
        """NaN at end (oldest) — streak from newest intact."""
        df = pd.DataFrame({"north_money": [float("nan"), 10.0, 20.0]})
        # reversed: [20, 10, NaN] → 20+ → 1, then 10+ → 2, then NaN breaks
        assert _northbound_streak(df) == 2

    def test_missing_column(self) -> None:
        df = pd.DataFrame({"other_col": [1, 2, 3]})
        assert _northbound_streak(df) == 0


# ---------------------------------------------------------------------------
# _market_breadth_ratio
# ---------------------------------------------------------------------------


class TestMarketBreadthRatio:
    def test_none(self) -> None:
        assert _market_breadth_ratio(None) == 0.5

    def test_empty(self) -> None:
        assert _market_breadth_ratio(pd.DataFrame()) == 0.5

    def test_no_pct_chg_column(self) -> None:
        """No pct_chg column → all pct_chg values are NaN → returns 0.5."""
        df = pd.DataFrame({"other": [1, 2, 3]})
        assert _market_breadth_ratio(df) == 0.5

    def test_all_advancing(self) -> None:
        df = pd.DataFrame({"pct_chg": [1.0, 2.0, 3.0]})
        assert _market_breadth_ratio(df) == 1.0

    def test_all_declining(self) -> None:
        df = pd.DataFrame({"pct_chg": [-1.0, -2.0, -3.0]})
        assert _market_breadth_ratio(df) == 0.0

    def test_mixed(self) -> None:
        df = pd.DataFrame({"pct_chg": [1.0, -1.0, 2.0, -2.0]})
        # 2 advancers, 2 decliners → 0.5
        assert _market_breadth_ratio(df) == 0.5

    def test_includes_zero_excluded(self) -> None:
        df = pd.DataFrame({"pct_chg": [1.0, 0.0, -1.0]})
        # 1 advancer, 1 decliner → 0.5
        assert _market_breadth_ratio(df) == 0.5

    def test_nan_dropped(self) -> None:
        df = pd.DataFrame({"pct_chg": [1.0, float("nan"), -1.0, -1.0]})
        # 1 advancer, 2 decliners → 1/3
        assert _market_breadth_ratio(df) == pytest.approx(1 / 3)

    def test_string_values_coerced(self) -> None:
        df = pd.DataFrame({"pct_chg": ["1.0", "-1.0", "2.0"]})
        # 2 advancers, 1 decliner → 2/3
        assert _market_breadth_ratio(df) == pytest.approx(2 / 3)
