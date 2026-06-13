"""Tests for src/screening/signal_decay_detector.py — P0-3 信号衰减检测."""

from __future__ import annotations

import pytest

from src.screening.signal_decay_detector import (
    DecayInfo,
    DecayLevel,
    _classify_decay,
    _compute_change_pct,
    _parse_date,
    build_decay_summary,
    detect_signal_decay,
)


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------


class TestParseDate:
    def test_yyyymmdd(self) -> None:
        from datetime import datetime
        dt = _parse_date("20260101")
        assert dt == datetime(2026, 1, 1)

    def test_yyyy_mm_dd(self) -> None:
        from datetime import datetime
        dt = _parse_date("2026-01-01")
        assert dt == datetime(2026, 1, 1)

    def test_invalid_format(self) -> None:
        with pytest.raises(ValueError):
            _parse_date("invalid")

    def test_too_short(self) -> None:
        with pytest.raises(ValueError):
            _parse_date("20261")


# ---------------------------------------------------------------------------
# _classify_decay
# ---------------------------------------------------------------------------


class TestClassifyDecay:
    def test_none_returns_none(self) -> None:
        assert _classify_decay(None) == DecayLevel.NONE

    def test_positive_change_returns_none(self) -> None:
        assert _classify_decay(5.0) == DecayLevel.NONE

    def test_zero_change_returns_none(self) -> None:
        assert _classify_decay(0.0) == DecayLevel.NONE

    def test_small_drop_returns_none(self) -> None:
        assert _classify_decay(-5.0) == DecayLevel.NONE

    def test_mild_decay(self) -> None:
        assert _classify_decay(-15.0) == DecayLevel.MILD

    def test_moderate_decay(self) -> None:
        assert _classify_decay(-25.0) == DecayLevel.MODERATE

    def test_severe_decay(self) -> None:
        assert _classify_decay(-50.0) == DecayLevel.SEVERE

    def test_boundary_mild(self) -> None:
        """Exactly 10% → MILD."""
        assert _classify_decay(-10.0) == DecayLevel.MILD

    def test_boundary_moderate(self) -> None:
        """Exactly 20% → MODERATE."""
        assert _classify_decay(-20.0) == DecayLevel.MODERATE

    def test_boundary_severe(self) -> None:
        """Exactly 40% → SEVERE."""
        assert _classify_decay(-40.0) == DecayLevel.SEVERE


# ---------------------------------------------------------------------------
# _compute_change_pct
# ---------------------------------------------------------------------------


class TestComputeChangePct:
    def test_increase(self) -> None:
        assert _compute_change_pct(0.6, 0.5) == pytest.approx(20.0)

    def test_decrease(self) -> None:
        assert _compute_change_pct(0.4, 0.5) == pytest.approx(-20.0)

    def test_no_change(self) -> None:
        assert _compute_change_pct(0.5, 0.5) == pytest.approx(0.0)

    def test_zero_previous_returns_none(self) -> None:
        assert _compute_change_pct(0.5, 0.0) is None

    def test_near_zero_previous(self) -> None:
        """Very small previous → uses max(abs(prev), 0.01) as denominator."""
        result = _compute_change_pct(0.5, 0.001)
        assert result is not None
        # (0.5 - 0.001) / max(0.001, 0.01) * 100 = 0.499 / 0.01 * 100 = 4990
        assert result > 100.0


# ---------------------------------------------------------------------------
# DecayLevel / DecayInfo
# ---------------------------------------------------------------------------


class TestDecayLevel:
    def test_enum_values(self) -> None:
        assert DecayLevel.NONE.value == "none"
        assert DecayLevel.MILD.value == "mild"
        assert DecayLevel.MODERATE.value == "moderate"
        assert DecayLevel.SEVERE.value == "severe"


class TestDecayInfo:
    def test_to_dict(self) -> None:
        info = DecayInfo(
            ticker="000001",
            level=DecayLevel.MILD,
            current_score=0.4,
            previous_score=0.5,
            change_pct=-20.0,
            days_since_peak=1,
        )
        d = info.to_dict()
        assert d["level"] == "mild"
        assert d["current_score"] == 0.4
        assert d["change_pct"] == -20.0
        assert d["days_since_peak"] == 1


# ---------------------------------------------------------------------------
# build_decay_summary
# ---------------------------------------------------------------------------


class TestBuildDecaySummary:
    def test_empty(self) -> None:
        summary = build_decay_summary({})
        assert summary == {"none": 0, "mild": 0, "moderate": 0, "severe": 0}

    def test_counts(self) -> None:
        decay_map = {
            "A": DecayInfo("A", DecayLevel.NONE, 0.5, 0.5, 0.0, 0),
            "B": DecayInfo("B", DecayLevel.MILD, 0.4, 0.5, -10.0, 1),
            "C": DecayInfo("C", DecayLevel.SEVERE, 0.1, 0.5, -50.0, 2),
        }
        summary = build_decay_summary(decay_map)
        assert summary["none"] == 1
        assert summary["mild"] == 1
        assert summary["severe"] == 1


# ---------------------------------------------------------------------------
# detect_signal_decay (end-to-end)
# ---------------------------------------------------------------------------


class TestDetectSignalDecay:
    def test_no_reports(self, tmp_path) -> None:
        """No history → all tickers get NONE with previous_score=None."""
        recs = [{"ticker": "000001", "score_b": 0.5}]
        result = detect_signal_decay(recs, report_dir=tmp_path, end_date="20260110")
        assert len(result) == 1
        assert result["000001"].level == DecayLevel.NONE
        assert result["000001"].previous_score is None

    def test_with_history_decaying(self, tmp_path) -> None:
        """Create a historical report, verify decay detection."""
        import json
        # Create a previous day's report
        prev_report = {"recommendations": [{"ticker": "000001", "score_b": 0.5}]}
        (tmp_path / "auto_screening_20260109.json").write_text(
            json.dumps(prev_report), encoding="utf-8"
        )

        recs = [{"ticker": "000001", "score_b": 0.3}]
        result = detect_signal_decay(recs, report_dir=tmp_path, end_date="20260110", lookback_days=3)
        assert result["000001"].current_score == pytest.approx(0.3)
        assert result["000001"].previous_score == pytest.approx(0.5)
        # (0.3 - 0.5) / 0.5 * 100 = -40%
        assert result["000001"].level == DecayLevel.SEVERE

    def test_with_history_improving(self, tmp_path) -> None:
        """Improving score → NONE."""
        import json
        prev_report = {"recommendations": [{"ticker": "000001", "score_b": 0.3}]}
        (tmp_path / "auto_screening_20260109.json").write_text(
            json.dumps(prev_report), encoding="utf-8"
        )

        recs = [{"ticker": "000001", "score_b": 0.5}]
        result = detect_signal_decay(recs, report_dir=tmp_path, end_date="20260110", lookback_days=3)
        assert result["000001"].level == DecayLevel.NONE

    def test_multiple_tickers(self, tmp_path) -> None:
        import json
        prev_report = {
            "recommendations": [
                {"ticker": "000001", "score_b": 0.5},
                {"ticker": "000002", "score_b": 0.4},
            ],
        }
        (tmp_path / "auto_screening_20260109.json").write_text(
            json.dumps(prev_report), encoding="utf-8"
        )

        recs = [
            {"ticker": "000001", "score_b": 0.3},  # decay
            {"ticker": "000002", "score_b": 0.6},  # improve
        ]
        result = detect_signal_decay(recs, report_dir=tmp_path, end_date="20260110", lookback_days=3)
        assert len(result) == 2
        assert result["000001"].level == DecayLevel.SEVERE
        assert result["000002"].level == DecayLevel.NONE

    def test_empty_recommendations(self, tmp_path) -> None:
        result = detect_signal_decay([], report_dir=tmp_path, end_date="20260110")
        assert result == {}
