"""Tests for src/screening/regime_calibration.py — P-5 市场状态条件胜率."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.screening.regime_calibration import (
    compute_regime_calibration,
    RegimeCalibrationReport,
    RegimeWinRate,
    render_regime_calibration_line,
)


def _seed_report_with_regime(dir_path: Path, date_str: str, regime: str, tickers: list[str]) -> None:
    """Write an auto_screening report embedding a market_state with the given regime."""
    payload = {
        "date": date_str,
        "market_state": {"state_type": "normal", "regime_gate_level": regime, "position_scale": 1.0},
        "recommendations": [{"ticker": t, "score_b": 0.7} for t in tickers],
    }
    (dir_path / f"auto_screening_{date_str}.json").write_text(json.dumps(payload), encoding="utf-8")


def _seed_tracking(dir_path: Path, records: list[dict]) -> None:
    (dir_path / "tracking_history.json").write_text(json.dumps(records), encoding="utf-8")


# ---------------------------------------------------------------------------
# compute_regime_calibration
# ---------------------------------------------------------------------------


class TestComputeRegimeCalibration:
    def test_per_regime_win_rate(self, tmp_path: Path) -> None:
        """normal regime: 2 winners / 4 recs; cautious: 1 winner / 2 recs."""
        _seed_report_with_regime(tmp_path, "20260101", "normal", ["000001", "000002", "000003", "000004"])
        _seed_report_with_regime(tmp_path, "20260102", "cautious", ["000005", "000006"])
        _seed_tracking(
            tmp_path,
            [
                {"ticker": "000001", "recommended_date": "20260101", "recommendation_score": 0.7, "next_30day_return": 5.0},  # win
                {"ticker": "000002", "recommended_date": "20260101", "recommendation_score": 0.7, "next_30day_return": -3.0},  # loss
                {"ticker": "000003", "recommended_date": "20260101", "recommendation_score": 0.7, "next_30day_return": 2.0},  # win
                {"ticker": "000004", "recommended_date": "20260101", "recommendation_score": 0.7, "next_30day_return": -1.0},  # loss
                {"ticker": "000005", "recommended_date": "20260102", "recommendation_score": 0.7, "next_30day_return": 4.0},  # win
                {"ticker": "000006", "recommended_date": "20260102", "recommendation_score": 0.7, "next_30day_return": -2.0},  # loss
            ],
        )
        report = compute_regime_calibration(reports_dir=tmp_path, lookback_days=30)
        by_regime = {r.regime: r for r in report.rows}
        assert "normal" in by_regime
        assert "cautious" in by_regime
        # normal: 2 wins / 4 = 0.5
        assert by_regime["normal"].t30_win_rate == pytest.approx(0.5, abs=1e-3)
        assert by_regime["normal"].mature_t30_count == 4
        # cautious: 1 win / 2 = 0.5
        assert by_regime["cautious"].t30_win_rate == pytest.approx(0.5, abs=1e-3)

    def test_record_without_report_date_counts_unknown(self, tmp_path: Path) -> None:
        """A tracking record whose date has no report → unknown regime bucket."""
        _seed_report_with_regime(tmp_path, "20260101", "normal", ["000001"])
        _seed_tracking(
            tmp_path,
            [
                {"ticker": "000001", "recommended_date": "20260101", "recommendation_score": 0.7, "next_30day_return": 3.0},
                {"ticker": "000099", "recommended_date": "20260109", "recommendation_score": 0.7, "next_30day_return": 5.0},  # no report on 20260109
            ],
        )
        report = compute_regime_calibration(reports_dir=tmp_path, lookback_days=30)
        assert report.unknown_regime_count >= 1

    def test_no_t30_data_win_rate_none(self, tmp_path: Path) -> None:
        """Regime with no matured T+30 returns → win_rate None (honest, not 0)."""
        _seed_report_with_regime(tmp_path, "20260101", "normal", ["000001"])
        _seed_tracking(
            tmp_path,
            [
                {"ticker": "000001", "recommended_date": "20260101", "recommendation_score": 0.7},  # no next_30day_return
            ],
        )
        report = compute_regime_calibration(reports_dir=tmp_path, lookback_days=30)
        normal = next(r for r in report.rows if r.regime == "normal")
        assert normal.t30_win_rate is None
        assert normal.mature_t30_count == 0

    def test_empty_inputs(self, tmp_path: Path) -> None:
        """No reports, no tracking → empty report."""
        report = compute_regime_calibration(reports_dir=tmp_path, lookback_days=30)
        assert report.rows == []
        assert report.unknown_regime_count == 0

    def test_bear_regime_lower_win_rate_signals_caution(self, tmp_path: Path) -> None:
        """The product question: does win-rate differ by regime? This characterizes the computation."""
        _seed_report_with_regime(tmp_path, "20260101", "normal", [f"{i:06d}" for i in range(1, 5)])
        _seed_report_with_regime(tmp_path, "20260102", "risk_off", [f"{i:06d}" for i in range(5, 9)])
        _seed_tracking(tmp_path, [{"ticker": f"{i:06d}", "recommended_date": "20260101", "recommendation_score": 0.7, "next_30day_return": 3.0} for i in range(1, 5)] + [{"ticker": f"{i:06d}", "recommended_date": "20260102", "recommendation_score": 0.7, "next_30day_return": -4.0} for i in range(5, 9)])  # 4/4 win in normal  # 0/4 win in risk_off
        report = compute_regime_calibration(reports_dir=tmp_path, lookback_days=30)
        by_regime = {r.regime: r for r in report.rows}
        assert by_regime["normal"].t30_win_rate == 1.0
        assert by_regime["risk_off"].t30_win_rate == 0.0
        # This is exactly the insight P-5 surfaces: regime conditions matter for confidence.


# ---------------------------------------------------------------------------
# render_regime_calibration_line
# ---------------------------------------------------------------------------


class TestRenderRegimeLine:
    def test_renders_per_regime_summary(self) -> None:
        report = RegimeCalibrationReport(
            rows=[
                RegimeWinRate(regime="normal", t30_win_rate=0.58, t30_avg_return=2.1, sample_count=80, mature_t30_count=60),
                RegimeWinRate(regime="cautious", t30_win_rate=0.42, t30_avg_return=-0.5, sample_count=20, mature_t30_count=15),
            ],
            unknown_regime_count=0,
        )
        result = render_regime_calibration_line(report)
        assert "normal" in result
        assert "58%" in result
        assert "cautious" in result
        assert "42%" in result

    def test_empty_report_returns_empty(self) -> None:
        report = RegimeCalibrationReport(rows=[], unknown_regime_count=0)
        assert render_regime_calibration_line(report) == ""
