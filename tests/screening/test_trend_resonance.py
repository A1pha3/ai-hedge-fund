"""Tests for src/screening/trend_resonance.py — P14-1 Multi-Timeframe Trend Resonance."""

from __future__ import annotations

import pytest

from src.screening.trend_resonance import (
    _classify_direction,
    _classify_resonance,
    _direction_icon,
    _extract_score_history,
    _resonance_colored,
    _simple_slope,
    render_trend_resonance,
    TrendResonanceEntry,
    TrendResonanceReport,
)
from src.utils.display import Fore, Style

# ---------------------------------------------------------------------------
# _simple_slope
# ---------------------------------------------------------------------------


class TestSimpleSlope:
    def test_empty(self) -> None:
        assert _simple_slope([]) == 0.0

    def test_single(self) -> None:
        assert _simple_slope([1.0]) == 0.0

    def test_ascending(self) -> None:
        assert _simple_slope([0.0, 0.1, 0.2, 0.3]) == pytest.approx(0.1)

    def test_descending(self) -> None:
        assert _simple_slope([0.3, 0.2, 0.1, 0.0]) == pytest.approx(-0.1)

    def test_flat(self) -> None:
        assert _simple_slope([0.5, 0.5, 0.5]) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _classify_direction
# ---------------------------------------------------------------------------


class TestClassifyDirection:
    def test_up(self) -> None:
        assert _classify_direction(0.01) == "up"

    def test_down(self) -> None:
        assert _classify_direction(-0.01) == "down"

    def test_flat_zero(self) -> None:
        assert _classify_direction(0.0) == "flat"

    def test_flat_near_zero(self) -> None:
        assert _classify_direction(0.002) == "flat"

    def test_flat_negative_near_zero(self) -> None:
        assert _classify_direction(-0.002) == "flat"

    def test_exactly_threshold_up(self) -> None:
        """Exactly 0.003 is NOT up (must be > threshold)."""
        assert _classify_direction(0.003) == "flat"

    def test_above_threshold(self) -> None:
        assert _classify_direction(0.004) == "up"


# ---------------------------------------------------------------------------
# _classify_resonance
# ---------------------------------------------------------------------------


class TestClassifyResonance:
    def test_all_up(self) -> None:
        label, factor = _classify_resonance(("up", "up", "up"))
        assert label == "resonance_up"
        assert factor == 0.05

    def test_all_down(self) -> None:
        label, factor = _classify_resonance(("down", "down", "down"))
        assert label == "resonance_down"
        assert factor == -0.05

    def test_two_up_one_flat(self) -> None:
        label, factor = _classify_resonance(("up", "up", "flat"))
        assert label == "partial_up"
        assert factor == 0.02

    def test_two_down_one_flat(self) -> None:
        label, factor = _classify_resonance(("down", "down", "flat"))
        assert label == "partial_down"
        assert factor == -0.02

    def test_mixed_up_and_down(self) -> None:
        label, factor = _classify_resonance(("up", "down", "flat"))
        assert label == "mixed"
        assert factor == -0.05

    def test_all_flat(self) -> None:
        label, factor = _classify_resonance(("flat", "flat", "flat"))
        assert label == "neutral"
        assert factor == 0.0

    def test_one_up_two_flat(self) -> None:
        """Only 1 up and 0 downs → ups >= 2 is False, so neutral."""
        label, factor = _classify_resonance(("up", "flat", "flat"))
        assert label == "neutral"
        assert factor == 0.0

    def test_up_up_down_conflict(self) -> None:
        label, factor = _classify_resonance(("up", "up", "down"))
        assert label == "mixed"
        assert factor == -0.05


# ---------------------------------------------------------------------------
# _extract_score_history
# ---------------------------------------------------------------------------


class TestExtractScoreHistory:
    def test_empty_history(self) -> None:
        assert _extract_score_history("000001", []) == []

    def test_single_report_with_ticker(self) -> None:
        history = [
            {"payload": {"recommendations": [{"ticker": "000001", "score_b": 0.5}]}},
        ]
        scores = _extract_score_history("000001", history)
        assert scores == [0.5]

    def test_multiple_reports_chronological(self) -> None:
        history = [
            {"payload": {"recommendations": [{"ticker": "000001", "score_b": 0.7}]}},
            {"payload": {"recommendations": [{"ticker": "000001", "score_b": 0.5}]}},
        ]
        scores = _extract_score_history("000001", history)
        # reversed: oldest first → [0.5, 0.7]
        assert scores == [0.5, 0.7]

    def test_ticker_not_found(self) -> None:
        history = [
            {"payload": {"recommendations": [{"ticker": "000002", "score_b": 0.5}]}},
        ]
        assert _extract_score_history("000001", history) == []

    def test_max_days_truncation(self) -> None:
        # score_b ∈ [-1.0, 1.0]; use i/10 so dummy values are in range
        # (coerce_score_b clamps out-of-range, which would mask ordering).
        history = [
            {"payload": {"recommendations": [{"ticker": "A", "score_b": float(i) / 10.0}]}}
            for i in range(10)
        ]
        scores = _extract_score_history("A", history, max_days=5)
        assert len(scores) == 5
        # reversed(history) iterates oldest first. history[0]=0.0 (newest),
        # history[9]=0.9 (oldest). reversed → [0.9,0.8,...,0.0]; [-5:] → newest 5.
        assert scores == [0.4, 0.3, 0.2, 0.1, 0.0]

    def test_none_score_b_treated_as_zero(self) -> None:
        history = [
            {"payload": {"recommendations": [{"ticker": "A", "score_b": None}]}},
        ]
        scores = _extract_score_history("A", history)
        assert scores == [0.0]

    def test_nan_score_b_coerced_not_poisoned(self) -> None:
        """R141: a corrupt NaN score_b must not poison the slope series.

        NaN is truthy, so ``float(nan or 0.0)`` evaluates to ``nan`` (not
        0.0), silently corrupting _simple_slope into producing NaN slopes
        and a "flat" direction misclassification. The sibling
        signal_momentum._extract_score_history uses coerce_score_b for this
        exact reason (BH-012-drain comment); trend_resonance missed it.
        """
        import math
        history = [
            {"payload": {"recommendations": [{"ticker": "A", "score_b": float("nan")}]}},
        ]
        scores = _extract_score_history("A", history)
        assert scores == [0.0]
        assert not any(math.isnan(s) for s in scores)


# ---------------------------------------------------------------------------
# TrendResonanceEntry / TrendResonanceReport
# ---------------------------------------------------------------------------


class TestTrendResonanceEntry:
    def test_defaults(self) -> None:
        entry = TrendResonanceEntry(ticker="000001")
        assert entry.direction_5d == "flat"
        assert entry.resonance_label == "neutral"
        assert entry.resonance_factor == 0.0


class TestTrendResonanceReport:
    def test_empty(self) -> None:
        report = TrendResonanceReport()
        assert report.items == []

    def test_to_dict(self) -> None:
        report = TrendResonanceReport(
            trade_date="2026-01-01",
            items=[
                TrendResonanceEntry(
                    ticker="000001",
                    name="平安",
                    slope_5d=0.01,
                    direction_5d="up",
                    resonance_label="resonance_up",
                    resonance_factor=0.05,
                ),
            ],
        )
        d = report.to_dict()
        assert d["trade_date"] == "2026-01-01"
        assert d["items"][0]["resonance_label"] == "resonance_up"


# ---------------------------------------------------------------------------
# render_trend_resonance
# ---------------------------------------------------------------------------


class TestRenderTrendResonance:
    def test_empty(self) -> None:
        result = render_trend_resonance(TrendResonanceReport())
        assert "无推荐数据" in result

    def test_with_items(self) -> None:
        report = TrendResonanceReport(
            trade_date="2026-01-01",
            items=[
                TrendResonanceEntry(
                    ticker="000001",
                    name="平安",
                    direction_5d="up",
                    direction_20d="up",
                    direction_60d="up",
                    resonance_label="resonance_up",
                    resonance_factor=0.05,
                ),
            ],
        )
        result = render_trend_resonance(report)
        assert "000001" in result
        assert "趋势共振" in result


# ---------------------------------------------------------------------------
# compute_trend_resonance (end-to-end, no report files → empty)
# ---------------------------------------------------------------------------


class TestComputeTrendResonance:
    def test_no_reports_returns_empty(self, tmp_path) -> None:
        from src.screening.trend_resonance import compute_trend_resonance

        report = compute_trend_resonance(reports_dir=tmp_path)
        assert report.items == []


# ---------------------------------------------------------------------------
# _direction_icon / _resonance_colored (was 0 direct coverage)
# ---------------------------------------------------------------------------


class TestDirectionIcon:
    """_direction_icon — direction string → colored arrow."""

    def test_up_green_arrow(self) -> None:
        result = _direction_icon("up")
        assert Fore.GREEN in result
        assert "↑" in result

    def test_down_red_arrow(self) -> None:
        result = _direction_icon("down")
        assert Fore.RED in result
        assert "↓" in result

    def test_unknown_white_dash(self) -> None:
        result = _direction_icon("flat")
        assert Fore.WHITE in result
        assert "→" in result

    def test_empty_string_white_dash(self) -> None:
        result = _direction_icon("")
        assert Fore.WHITE in result
        assert "→" in result

    def test_all_end_with_reset(self) -> None:
        assert _direction_icon("up").endswith(Style.RESET_ALL)
        assert _direction_icon("down").endswith(Style.RESET_ALL)
        assert _direction_icon("other").endswith(Style.RESET_ALL)


class TestResonanceColored:
    """_resonance_colored — label + factor → colored resonance text."""

    def test_resonance_positive_green(self) -> None:
        result = _resonance_colored("strong_resonance", 0.8)
        assert Fore.GREEN in result
        assert "共振↑" in result

    def test_resonance_negative_red(self) -> None:
        result = _resonance_colored("weak_resonance", -0.5)
        assert Fore.RED in result
        assert "共振↓" in result

    def test_resonance_zero_factor_red(self) -> None:
        # factor == 0 → not > 0 → RED branch
        result = _resonance_colored("resonance", 0.0)
        assert Fore.RED in result
        assert "共振↓" in result

    def test_partial_positive_green(self) -> None:
        result = _resonance_colored("partial_up", 0.3)
        assert Fore.GREEN in result
        assert "偏多" in result

    def test_partial_negative_red(self) -> None:
        result = _resonance_colored("partial", -0.2)
        assert Fore.RED in result
        assert "偏空" in result

    def test_mixed_yellow_conflict(self) -> None:
        result = _resonance_colored("mixed", 0.5)
        assert Fore.YELLOW in result
        assert "冲突" in result

    def test_unknown_label_white_neutral(self) -> None:
        result = _resonance_colored("something_else", 0.5)
        assert Fore.WHITE in result
        assert "中性" in result

    def test_resonance_takes_precedence_over_partial(self) -> None:
        # label containing both "resonance" and "partial" → resonance branch wins
        result = _resonance_colored("resonance_partial", 0.5)
        assert "共振" in result

    def test_all_end_with_reset(self) -> None:
        assert _resonance_colored("resonance", 0.5).endswith(Style.RESET_ALL)
        assert _resonance_colored("mixed", 0.0).endswith(Style.RESET_ALL)
        assert _resonance_colored("other", 0.0).endswith(Style.RESET_ALL)
