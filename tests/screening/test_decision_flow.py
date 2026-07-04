"""Tests for decision_flow.py -- P8-1 + P9-2."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from src.screening.decision_flow import render_decision_flow_summary, run_decision_flow


def _make_report(date_str: str, recs: list[dict]) -> dict:
    return {"date": date_str, "recommendations": recs}


def _make_rec(ticker: str, name: str, score_b: float, signals: dict | None = None) -> dict:
    return {"ticker": ticker, "name": name, "score_b": score_b, "strategy_signals": signals or {}}


class TestDecisionFlow:
    def test_no_report_returns_error(self, tmp_path: Path) -> None:
        result = run_decision_flow(reports_dir=tmp_path)
        assert result.get("error") == "no_report"

    def test_full_flow_runs(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        yesterday = _make_report("20260610", [_make_rec("000001", "A", 0.7)])
        today = _make_report(
            "20260611",
            [
                _make_rec(
                    "000001",
                    "A",
                    0.8,
                    {
                        "trend": {"signal": "bullish", "confidence": 80},
                        "mean_reversion": {"signal": "bullish", "confidence": 70},
                    },
                ),
            ],
        )
        (reports_dir / "auto_screening_20260610.json").write_text(json.dumps(yesterday), encoding="utf-8")
        (reports_dir / "auto_screening_20260611.json").write_text(json.dumps(today), encoding="utf-8")

        result = run_decision_flow(top_n=10, reports_dir=reports_dir)
        assert "error" not in result
        assert result["recommendation_count"] == 1
        # Original steps
        assert "freshness" in result
        assert "consistency" in result
        assert "dynamic_threshold" in result
        assert "daily_delta" in result
        # P9-2 additions
        assert "outliers" in result
        assert "outlier_count" in result
        assert "expected_returns" in result

    def test_outlier_count_is_int(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        today = _make_report("20260611", [_make_rec("000001", "A", 0.8)])
        (reports_dir / "auto_screening_20260611.json").write_text(json.dumps(today), encoding="utf-8")

        result = run_decision_flow(top_n=10, reports_dir=reports_dir)
        assert isinstance(result.get("outlier_count"), int)

    def test_expected_returns_in_result(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        today = _make_report("20260611", [_make_rec("000001", "A", 0.8)])
        (reports_dir / "auto_screening_20260611.json").write_text(json.dumps(today), encoding="utf-8")

        result = run_decision_flow(top_n=10, reports_dir=reports_dir)
        er = result.get("expected_returns", {})
        assert "items" in er
        assert "total_samples" in er
        assert "lookback_days" in er

    def test_render_summary(self) -> None:
        flow = {
            "trade_date": "20260611",
            "recommendation_count": 5,
            "freshness": {"fresh": True},
            "high_consistency_count": 4,
            "outlier_count": 0,
        }
        output = render_decision_flow_summary(flow)
        assert "20260611" in output
        assert "5" in output
        assert "PASS" in output
        assert "Outliers: 0" in output

    def test_render_summary_with_outliers(self) -> None:
        flow = {
            "trade_date": "20260611",
            "recommendation_count": 3,
            "freshness": {"fresh": False},
            "high_consistency_count": 1,
            "outlier_count": 2,
        }
        output = render_decision_flow_summary(flow)
        assert "WARNING" in output
        assert "Outliers: 2" in output

    def test_decision_flow_prints_disclaimer(self, tmp_path: Path, capsys) -> None:
        """R77 (R71/R72/R73/R75/R76 trust-calibration family): --decision-flow
        emits a concrete Top-investable ticker with composite score + T+30 edge +
        win rate, so the footer must carry the same non-advice disclaimer as the
        other six user-facing decision surfaces."""
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        today = _make_report("20260611", [_make_rec("000001", "A", 0.8)])
        (reports_dir / "auto_screening_20260611.json").write_text(json.dumps(today), encoding="utf-8")

        run_decision_flow(top_n=10, reports_dir=reports_dir)
        captured = capsys.readouterr()
        assert "不构成任何投资建议" in captured.out
        assert "研究" in captured.out

    def test_r104_corrupt_report_degrades_gracefully(self, tmp_path: Path, capsys) -> None:
        """R104 (R88/BH-017 family): a corrupt/truncated latest report (partial
        write / interrupted run) must not crash --decision-flow with a raw
        JSONDecodeError. Degrade to a user-visible error + "corrupt_report"
        marker so the operator re-runs --auto."""
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        (reports_dir / "auto_screening_20260611.json").write_text("{corrupt not json", encoding="utf-8")

        result = run_decision_flow(top_n=10, reports_dir=reports_dir)
        captured = capsys.readouterr()
        assert result.get("error") == "corrupt_report"
        assert "损坏" in captured.out

    @patch("src.screening.investability.rank_recommendations_by_investability")
    def test_top_investable_flags_t30_low_confidence_when_mature_tiny(self, mock_rank, tmp_path: Path, capsys) -> None:
        """R141 Bug Hunt (R51/R52 family — coverage gap drain): c271 added the
        ``⚠少样本`` low-confidence marker to ``render_expected_returns_compact``
        in this SAME ``--decision-flow`` output, but the Top investable headline
        line (which reads the SAME ``win_rates.t30`` + ``bucket_t30_mature_count``
        fields) was missed. A per-bucket n=1 "100% winrate" renders
        confident-green in the Top investable line while the expected-returns
        section below it flags the same ticker yellow — inconsistent honesty
        within a single command output.
        """
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        today = _make_report("20260611", [_make_rec("000001", "A", 0.8)])
        (reports_dir / "auto_screening_20260611.json").write_text(json.dumps(today), encoding="utf-8")

        mock_rank.return_value = [
            {
                "ticker": "000001",
                "name": "A",
                "score_b": 0.8,
                "composite_score": 0.8,
                "win_rates": {"t30": 1.0, "t5": 0.6, "t10": 0.6},
                "expected_returns": {"t30": 0.03, "t5": 0.01, "t10": 0.012},
                "bucket_sample_count": 4,
                "bucket_t30_mature_count": 1,
            }
        ]

        run_decision_flow(top_n=10, reports_dir=reports_dir)
        captured = capsys.readouterr()
        # Isolate the Top investable line (not the entire output which may
        # contain ⚠少样本 from the c271-fixed compact expected-returns section).
        top_investable_lines = [line for line in captured.out.splitlines() if "Top investable" in line]
        assert top_investable_lines, "Top investable line must be present"
        assert "少样本" in top_investable_lines[0] or "⚠" in top_investable_lines[0], "--decision-flow Top investable line must flag T+30 winrate " "low-confidence when mature sample < 5 — c271 fixed the compact " "expected-returns renderer in the same output but missed the headline."

    @patch("src.screening.investability.rank_recommendations_by_investability")
    def test_top_investable_no_flag_when_mature_sufficient(self, mock_rank, tmp_path: Path, capsys) -> None:
        """R141 negative guard: sufficient mature sample → no low-confidence marker."""
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        today = _make_report("20260611", [_make_rec("000001", "A", 0.8)])
        (reports_dir / "auto_screening_20260611.json").write_text(json.dumps(today), encoding="utf-8")

        mock_rank.return_value = [
            {
                "ticker": "000001",
                "name": "A",
                "score_b": 0.8,
                "composite_score": 0.8,
                "win_rates": {"t30": 0.6, "t5": 0.6, "t10": 0.6},
                "expected_returns": {"t30": 0.03, "t5": 0.01, "t10": 0.012},
                "bucket_sample_count": 50,
                "bucket_t30_mature_count": 20,
            }
        ]

        run_decision_flow(top_n=10, reports_dir=reports_dir)
        captured = capsys.readouterr()
        # Top investable line should be present but without the low-confidence marker.
        top_investable_lines = [line for line in captured.out.splitlines() if "Top investable" in line]
        assert top_investable_lines, "Top investable line must be present"
        assert "少样本" not in top_investable_lines[0]
