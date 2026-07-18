"""Tests for src/screening/market_state.py — market state detector helpers."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from src.screening.market_state import (
    _market_breadth_ratio,
    _normalize_weights,
    _northbound_streak,
    detect_market_state,
)

# ---------------------------------------------------------------------------
# detect_market_state — macro regime integration observability (R90 BH-017)
# ---------------------------------------------------------------------------


class TestDetectMarketStateMacro:
    """R90 BH-017 silent-crash residue: the optional macro regime integration
    in ``detect_market_state`` swallows all exceptions with a bare ``except: pass``.
    When macro data fetch fails (no macro provider, network, parse error) the
    GO/CAUTION/WAIT signal silently drops macro context with zero diagnostics.
    The fix must emit a warning so operators can diagnose why macro context is
    missing from the market state signal (R6 signal-light reliability)."""

    def test_macro_failure_logs_warning(self, monkeypatch, caplog) -> None:
        import logging

        import pandas as pd

        from src.screening import market_state as ms_mod

        # Minimal non-empty index frame so detect_market_state does not early-return.
        idx_df = pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "vol": [1.0]})
        monkeypatch.setattr(ms_mod, "get_index_daily", lambda *a, **k: idx_df)
        monkeypatch.setattr(ms_mod, "get_daily_price_batch", lambda *a, **k: None)
        monkeypatch.setattr(ms_mod, "get_limit_list", lambda *a, **k: None)
        monkeypatch.setattr(ms_mod, "get_daily_basic_batch", lambda *a, **k: None)
        monkeypatch.setattr(ms_mod, "get_northbound_flow", lambda *a, **k: None)
        # Short-circuit the metric builders so we reach the macro block.
        monkeypatch.setattr(ms_mod, "calculate_market_state_metrics", lambda **k: None)
        monkeypatch.setattr(ms_mod, "build_market_state_from_metrics", lambda **k: ms_mod.MarketState())

        # Macro import path raises (simulating missing macro_data module / fetch failure).
        import builtins

        real_import = builtins.__import__

        def _import_macro(name, *args, **kwargs):
            if name == "src.data.macro_data":
                raise ImportError("simulated macro_data unavailability")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _import_macro)

        with caplog.at_level(logging.WARNING, logger="src.screening.market_state"):
            state = ms_mod.detect_market_state("20260102")

        # Behavior preserved: returns a valid MarketState (macro is best-effort)
        assert state is not None
        # Diagnostic: macro failure must be logged, not silent
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) >= 1, "macro integration failure must be logged, not silent"


class TestNormalizeWeights:
    def test_normal(self) -> None:
        w = {"trend": 0.4, "mean_reversion": 0.3, "fundamental": 0.2, "event_sentiment": 0.1}
        result = _normalize_weights(w)
        assert sum(result.values()) == pytest.approx(1.0)
        assert result["trend"] == pytest.approx(0.4)

    def test_zero_total_uses_default(self) -> None:
        w = {"trend": 0.0, "mean_reversion": 0.0}
        result = _normalize_weights(w)
        # Falls back to DEFAULT_STRATEGY_WEIGHTS (88ce357e: trend 0.40)
        assert result["trend"] == 0.40

    def test_negative_clamped(self) -> None:
        w = {"trend": 0.6, "mean_reversion": -0.1, "fundamental": 0.3, "event_sentiment": 0.2}
        result = _normalize_weights(w)
        assert result["mean_reversion"] == 0.0
        # total: 0.6 + 0 + 0.3 + 0.2 = 1.1 → trend = 0.6/1.1
        assert result["trend"] == pytest.approx(0.6 / 1.1)

    def test_all_zero_uses_default(self) -> None:
        result = _normalize_weights({"trend": 0.0, "mean_reversion": 0.0, "fundamental": 0.0, "event_sentiment": 0.0})
        # 相对权重 (88ce357e 调权, sum=0.8; 消费方使用前自行归一)
        assert result == {"trend": 0.40, "mean_reversion": 0.20, "fundamental": 0.15, "event_sentiment": 0.05}


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
