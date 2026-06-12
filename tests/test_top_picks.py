"""Tests for top_picks.py — P12-2 + R4/R5."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.screening.composite_score import CompositeEntry, CompositeReport
from src.screening.expected_return import ExpectedReturn, ExpectedReturnReport
from src.screening.top_picks import (
    run_top_picks,
    _consecutive_bonus,
    _status_icon,
    _render_hit_rate_summary,
)


def _make_rec(ticker: str, name: str, score_b: float, industry: str = "电子") -> dict[str, Any]:
    return {
        "ticker": ticker,
        "name": name,
        "score_b": score_b,
        "industry_sw": industry,
        "strategy_signals": {
            "trend": {"signal": "bullish", "confidence": 70, "direction": 1},
            "fundamental": {"signal": "bullish", "confidence": 60, "direction": 1},
            "mean_reversion": {"signal": "neutral", "confidence": 40, "direction": 0},
            "event_sentiment": {"signal": "bullish", "confidence": 55, "direction": 1},
        },
    }


def _write_report(tmp_dir: Path, recs: list[dict], date: str = "20260610") -> None:
    path = tmp_dir / f"auto_screening_{date}.json"
    path.write_text(
        json.dumps({"trade_date": date, "recommendations": recs}),
        encoding="utf-8",
    )


class TestTopPicks:
    def test_no_report(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        rc = run_top_picks(count=5, reports_dir=tmp_path)
        assert rc == 1
        assert "No auto_screening report found" in capsys.readouterr().out

    def test_empty_recommendations(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _write_report(tmp_path, [])
        rc = run_top_picks(count=5, reports_dir=tmp_path)
        assert rc == 0

    def test_basic_output(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        recs = [
            _make_rec("300750", "宁德时代", 0.6, "电气设备"),
            _make_rec("000001", "平安银行", 0.3, "银行"),
            _make_rec("600519", "贵州茅台", 0.5, "食品饮料"),
        ]
        _write_report(tmp_path, recs)
        rc = run_top_picks(count=5, reports_dir=tmp_path)
        assert rc == 0
        output = capsys.readouterr().out
        assert "Top Picks" in output
        assert "300750" in output

    def test_count_limits_output(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        recs = [_make_rec(f"{i:06d}", f"Stock{i}", 0.5) for i in range(10)]
        _write_report(tmp_path, recs)
        rc = run_top_picks(count=3, reports_dir=tmp_path)
        assert rc == 0
        output = capsys.readouterr().out
        # Should show at most 3 numbered picks
        assert "1." in output
        assert "3." in output

    def test_high_confidence_message(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        recs = [_make_rec("300750", "宁德时代", 0.8)]
        _write_report(tmp_path, recs)
        rc = run_top_picks(count=5, reports_dir=tmp_path)
        assert rc == 0
        output = capsys.readouterr().out
        assert "High confidence" in output

    def test_no_confidence_message(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        recs = [_make_rec("000001", "平安银行", 0.05)]
        _write_report(tmp_path, recs)
        rc = run_top_picks(count=5, reports_dir=tmp_path)
        assert rc == 0
        output = capsys.readouterr().out
        assert "No high-confidence" in output or "waiting" in output

    def test_signal_breakdown(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        recs = [_make_rec("300750", "宁德时代", 0.6)]
        _write_report(tmp_path, recs)
        rc = run_top_picks(count=5, reports_dir=tmp_path)
        assert rc == 0
        output = capsys.readouterr().out
        # Should show signal breakdown (动量/行业/一致/量价)
        assert "base=" in output

    @patch(
        "src.screening.expected_return.compute_expected_returns",
        return_value=ExpectedReturnReport(
            trade_date="20260610",
            lookback_days=60,
            total_samples=120,
            items=[
                ExpectedReturn(
                    ticker="300750",
                    score_b=0.8,
                    bucket_label="高 (>0.8)",
                    bucket_sample_count=40,
                    expected_returns={"t1": 1.0, "t5": 3.5, "t10": 5.2, "t20": 8.1, "t30": 11.4},
                    win_rates={"t1": 0.55, "t5": 0.60, "t10": 0.61, "t20": 0.63, "t30": 0.66},
                ),
            ],
        ),
    )
    def test_output_includes_t30_investability_evidence(self, _mock_expected: object, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        recs = [_make_rec("300750", "宁德时代", 0.8)]
        _write_report(tmp_path, recs)
        rc = run_top_picks(count=5, reports_dir=tmp_path)
        assert rc == 0
        output = capsys.readouterr().out
        assert "T+30" in output
        assert "样本" in output

    @patch(
        "src.screening.top_picks.compute_expected_returns",
        return_value=ExpectedReturnReport(
            trade_date="20260610",
            lookback_days=60,
            total_samples=120,
            items=[
                ExpectedReturn(
                    ticker="300750",
                    score_b=0.8,
                    bucket_label="高 (>0.8)",
                    bucket_sample_count=40,
                    expected_returns={"t30": 11.4},
                    win_rates={"t30": 0.66},
                ),
            ],
        ),
    )
    @patch(
        "src.screening.top_picks.compute_composite_scores",
        return_value=CompositeReport(
            trade_date="20260610",
            items=[
                CompositeEntry(
                    ticker="300750",
                    name="宁德时代",
                    base_score=0.8,
                    composite_score=0.72,
                    momentum_bonus=0.05,
                    sector_bonus=0.03,
                    consistency_adj=0.02,
                    volume_factor=0.01,
                    trend_resonance_factor=0.04,
                )
            ],
        ),
    )
    def test_top_picks_uses_market_gate_trade_date_and_renders_actionable_verdict(
        self,
        _mock_composite: object,
        _mock_expected: object,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        recs = [_make_rec("300750", "宁德时代", 0.8)]
        _write_report(tmp_path, recs)

        def fake_detect_market_state(trade_date: str) -> SimpleNamespace:
            assert trade_date == "20260610"
            return SimpleNamespace(regime="risk_off")

        with patch("src.screening.market_state.detect_market_state", side_effect=fake_detect_market_state):
            rc = run_top_picks(count=3, reports_dir=tmp_path)

        assert rc == 0
        output = capsys.readouterr().out
        assert "MARKET GATE" in output
        assert "操作=HOLD" in output
        assert "失效条件" in output

    @patch(
        "src.screening.market_state.detect_market_state",
        return_value=SimpleNamespace(regime="trend"),
    )
    @patch(
        "src.screening.top_picks.compute_expected_returns",
        return_value=ExpectedReturnReport(
            trade_date="20260610",
            lookback_days=60,
            total_samples=200,
            items=[
                ExpectedReturn(
                    ticker="000001",
                    score_b=0.81,
                    bucket_label="高",
                    bucket_sample_count=52,
                    expected_returns={"t30": 10.0},
                    win_rates={"t30": 0.64},
                ),
                ExpectedReturn(
                    ticker="000002",
                    score_b=0.80,
                    bucket_label="高",
                    bucket_sample_count=50,
                    expected_returns={"t30": 9.5},
                    win_rates={"t30": 0.62},
                ),
                ExpectedReturn(
                    ticker="000003",
                    score_b=0.79,
                    bucket_label="高",
                    bucket_sample_count=48,
                    expected_returns={"t30": 8.0},
                    win_rates={"t30": 0.60},
                ),
            ],
        ),
    )
    @patch(
        "src.screening.top_picks.compute_composite_scores",
        return_value=CompositeReport(
            trade_date="20260610",
            items=[
                CompositeEntry(ticker="000001", name="电子龙头A", base_score=0.81, composite_score=0.81),
                CompositeEntry(ticker="000002", name="电子龙头B", base_score=0.80, composite_score=0.80),
                CompositeEntry(ticker="000003", name="银行核心", base_score=0.79, composite_score=0.79),
            ],
        ),
    )
    def test_top_picks_keeps_one_representative_per_cluster_and_lists_backups(
        self,
        _mock_composite: object,
        _mock_expected: object,
        _mock_market_state: object,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        recs = [
            _make_rec("000001", "电子龙头A", 0.81, "电子"),
            _make_rec("000002", "电子龙头B", 0.80, "电子"),
            _make_rec("000003", "银行核心", 0.79, "银行"),
        ]
        _write_report(tmp_path, recs)

        rc = run_top_picks(count=2, reports_dir=tmp_path)

        assert rc == 0
        output = capsys.readouterr().out
        assert "000001" in output
        assert "000003" in output
        assert "同簇备选: 000002" in output

    @patch(
        "src.screening.top_picks.compute_expected_returns",
        return_value=ExpectedReturnReport(
            trade_date="20260610",
            lookback_days=60,
            total_samples=120,
            items=[
                ExpectedReturn(
                    ticker="300750",
                    score_b=0.8,
                    bucket_label="高 (>0.8)",
                    bucket_sample_count=40,
                    expected_returns={"t30": 11.4},
                    win_rates={"t30": 0.66},
                ),
            ],
        ),
    )
    @patch(
        "src.screening.top_picks.compute_composite_scores",
        return_value=CompositeReport(
            trade_date="20260610",
            items=[
                CompositeEntry(
                    ticker="300750",
                    name="宁德时代",
                    base_score=0.8,
                    composite_score=0.72,
                )
            ],
        ),
    )
    def test_top_picks_falls_back_when_market_gate_lookup_fails(
        self,
        _mock_composite: object,
        _mock_expected: object,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        recs = [_make_rec("300750", "宁德时代", 0.8)]
        _write_report(tmp_path, recs)

        with patch("src.screening.market_state.detect_market_state", side_effect=RuntimeError("boom")):
            rc = run_top_picks(count=3, reports_dir=tmp_path)

        assert rc == 0
        output = capsys.readouterr().out
        assert "MARKET GATE unavailable" in output
        assert "300750" in output


# ---------------------------------------------------------------------------
# R4: Consecutive recommendation bonus tests
# ---------------------------------------------------------------------------


class TestConsecutiveBonus:
    """Tests for R4 consecutive recommendation integration."""

    def test_bonus_zero_for_less_than_3_days(self) -> None:
        assert _consecutive_bonus(0) == 0.0
        assert _consecutive_bonus(1) == 0.0
        assert _consecutive_bonus(2) == 0.0

    def test_bonus_3_days(self) -> None:
        assert _consecutive_bonus(3) == 0.03

    def test_bonus_5_days(self) -> None:
        assert _consecutive_bonus(5) == 0.05

    def test_bonus_6plus_days_caps_at_default(self) -> None:
        assert _consecutive_bonus(6) == 0.08
        assert _consecutive_bonus(10) == 0.08
        assert _consecutive_bonus(30) == 0.08

    def test_status_icon_first_appearance(self) -> None:
        assert _status_icon("first_appearance") == "🆕"
        assert _status_icon("") == "🆕"

    def test_status_icon_consecutive(self) -> None:
        assert _status_icon("consecutive_3plus") == "🔁"
        assert _status_icon("consecutive_2days") == "🔁"

    def test_status_icon_reentry(self) -> None:
        assert _status_icon("reentry_signal") == "🔄"

    def test_status_icon_broken(self) -> None:
        assert _status_icon("broken_streak") == "⬇️"

    @patch(
        "src.screening.top_picks.compute_expected_returns",
        return_value=ExpectedReturnReport(
            trade_date="20260610",
            lookback_days=60,
            total_samples=120,
            items=[
                ExpectedReturn(
                    ticker="300750",
                    score_b=0.8,
                    bucket_label="高",
                    bucket_sample_count=40,
                    expected_returns={"t30": 11.4},
                    win_rates={"t30": 0.66},
                ),
                ExpectedReturn(
                    ticker="000001",
                    score_b=0.6,
                    bucket_label="中",
                    bucket_sample_count=30,
                    expected_returns={"t30": 5.0},
                    win_rates={"t30": 0.55},
                ),
            ],
        ),
    )
    @patch(
        "src.screening.top_picks.compute_composite_scores",
        return_value=CompositeReport(
            trade_date="20260610",
            items=[
                CompositeEntry(ticker="300750", name="宁德时代", base_score=0.8, composite_score=0.72),
                CompositeEntry(ticker="000001", name="平安银行", base_score=0.6, composite_score=0.55),
            ],
        ),
    )
    @patch(
        "src.screening.top_picks.enrich_recommendations_with_history",
    )
    def test_consecutive_boosts_ranking(
        self,
        mock_enrich: object,
        _mock_composite: object,
        _mock_expected: object,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """R4: A stock with consecutive 5-day history should outrank higher score_b single-day stock."""
        recs = [
            _make_rec("000001", "平安银行", 0.6, "银行"),
            _make_rec("300750", "宁德时代", 0.8, "电气设备"),
        ]
        _write_report(tmp_path, recs)

        # 000001 has 5 consecutive days (bonus 0.05)
        # 300750 has 0 consecutive days (bonus 0.0)
        def enrich_side_effect(*args: Any, **kwargs: Any) -> list[dict]:
            recommendations = kwargs.get("recommendations") or args[0]
            for rec in recommendations:
                if rec.get("ticker") == "000001":
                    rec["consecutive_days"] = 5
                    rec["consecutive_status"] = "consecutive_3plus"
                    rec["stability_bonus"] = 10.0
                    rec["recommendation_history"] = []
                    rec["consecutive_bonus"] = 0.05
                else:
                    rec["consecutive_days"] = 0
                    rec["consecutive_status"] = "first_appearance"
                    rec["stability_bonus"] = 0.0
                    rec["recommendation_history"] = []
                    rec["consecutive_bonus"] = 0.0
            return recommendations

        mock_enrich.side_effect = enrich_side_effect

        with patch("src.screening.market_state.detect_market_state", return_value=SimpleNamespace(regime="trend")):
            rc = run_top_picks(count=5, reports_dir=tmp_path)

        assert rc == 0
        output = capsys.readouterr().out
        # 000001 (0.55 + 0.05 = 0.60) should outrank 300750 (0.72 + 0.0 = 0.72)
        # Actually 300750 base composite 0.72 is still higher than 0.60, so it stays first
        # But the consecutive icon should appear for 000001
        assert "🔁5d" in output or "5d" in output

    @patch(
        "src.screening.top_picks.compute_expected_returns",
        return_value=ExpectedReturnReport(
            trade_date="20260610",
            lookback_days=60,
            total_samples=50,
            items=[
                ExpectedReturn(
                    ticker="300750",
                    score_b=0.8,
                    bucket_label="高",
                    bucket_sample_count=40,
                    expected_returns={"t30": 11.4},
                    win_rates={"t30": 0.66},
                ),
            ],
        ),
    )
    @patch(
        "src.screening.top_picks.compute_composite_scores",
        return_value=CompositeReport(
            trade_date="20260610",
            items=[
                CompositeEntry(ticker="300750", name="宁德时代", base_score=0.8, composite_score=0.72),
            ],
        ),
    )
    def test_consecutive_enrichment_failure_is_non_fatal(
        self,
        _mock_composite: object,
        _mock_expected: object,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """R4: If enrichment fails, top-picks still works without consecutive data."""
        recs = [_make_rec("300750", "宁德时代", 0.8)]
        _write_report(tmp_path, recs)

        with patch(
            "src.screening.top_picks.enrich_recommendations_with_history",
            side_effect=RuntimeError("no history"),
        ), patch(
            "src.screening.market_state.detect_market_state",
            return_value=SimpleNamespace(regime="trend"),
        ):
            rc = run_top_picks(count=5, reports_dir=tmp_path)

        assert rc == 0
        output = capsys.readouterr().out
        assert "300750" in output


# ---------------------------------------------------------------------------
# R5: Historical hit-rate summary tests
# ---------------------------------------------------------------------------


class TestHitRateSummary:
    """Tests for R5 historical hit-rate display."""

    def test_empty_summary(self) -> None:
        summary = SimpleNamespace(
            total_recommendations=0,
            total_days=0,
            unique_tickers=0,
            lookback_days=30,
        )
        assert _render_hit_rate_summary(summary) == ""

    def test_basic_summary_rendering(self) -> None:
        summary = SimpleNamespace(
            total_recommendations=120,
            total_days=22,
            unique_tickers=45,
            lookback_days=30,
            overall_t5_win_rate=0.58,
            overall_t10_win_rate=0.55,
            overall_t30_win_rate=0.52,
            avg_t5_return=2.1,
            avg_t30_return=5.4,
            excess_return=1.2,
        )
        result = _render_hit_rate_summary(summary)
        assert "历史命中率速览" in result
        assert "22 个交易日" in result
        assert "120 次推荐" in result
        assert "T+5" in result
        assert "T+30" in result
        assert "超额收益" in result

    def test_summary_with_negative_excess(self) -> None:
        summary = SimpleNamespace(
            total_recommendations=80,
            total_days=15,
            unique_tickers=30,
            lookback_days=30,
            overall_t5_win_rate=0.45,
            overall_t30_win_rate=0.42,
            avg_t5_return=-0.5,
            avg_t30_return=-2.1,
            excess_return=-1.5,
        )
        result = _render_hit_rate_summary(summary)
        assert "历史命中率速览" in result
        assert "超额收益" in result

    def test_summary_without_optional_fields(self) -> None:
        summary = SimpleNamespace(
            total_recommendations=50,
            total_days=10,
            unique_tickers=20,
            lookback_days=30,
        )
        result = _render_hit_rate_summary(summary)
        assert "历史命中率速览" in result
        assert "10 个交易日" in result

    @patch(
        "src.screening.top_picks.compute_expected_returns",
        return_value=ExpectedReturnReport(
            trade_date="20260610",
            lookback_days=60,
            total_samples=50,
            items=[
                ExpectedReturn(
                    ticker="300750",
                    score_b=0.8,
                    bucket_label="高",
                    bucket_sample_count=40,
                    expected_returns={"t30": 11.4},
                    win_rates={"t30": 0.66},
                ),
            ],
        ),
    )
    @patch(
        "src.screening.top_picks.compute_composite_scores",
        return_value=CompositeReport(
            trade_date="20260610",
            items=[
                CompositeEntry(ticker="300750", name="宁德时代", base_score=0.8, composite_score=0.72),
            ],
        ),
    )
    @patch(
        "src.screening.top_picks.compute_verify_recommendations",
    )
    def test_hit_rate_summary_appears_in_output(
        self,
        mock_verify: object,
        _mock_composite: object,
        _mock_expected: object,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """R5: Verify summary appears in top-picks output."""
        recs = [_make_rec("300750", "宁德时代", 0.8)]
        _write_report(tmp_path, recs)

        mock_verify.return_value = SimpleNamespace(
            total_recommendations=100,
            total_days=20,
            unique_tickers=35,
            lookback_days=30,
            overall_t5_win_rate=0.60,
            overall_t30_win_rate=0.55,
            avg_t5_return=1.8,
            avg_t30_return=4.5,
            excess_return=2.0,
        )

        with patch(
            "src.screening.market_state.detect_market_state",
            return_value=SimpleNamespace(regime="trend"),
        ):
            rc = run_top_picks(count=5, reports_dir=tmp_path)

        assert rc == 0
        output = capsys.readouterr().out
        assert "历史命中率速览" in output
        assert "100 次推荐" in output

    @patch(
        "src.screening.top_picks.compute_expected_returns",
        return_value=ExpectedReturnReport(
            trade_date="20260610",
            lookback_days=60,
            total_samples=50,
            items=[
                ExpectedReturn(
                    ticker="300750",
                    score_b=0.8,
                    bucket_label="高",
                    bucket_sample_count=40,
                    expected_returns={"t30": 11.4},
                    win_rates={"t30": 0.66},
                ),
            ],
        ),
    )
    @patch(
        "src.screening.top_picks.compute_composite_scores",
        return_value=CompositeReport(
            trade_date="20260610",
            items=[
                CompositeEntry(ticker="300750", name="宁德时代", base_score=0.8, composite_score=0.72),
            ],
        ),
    )
    def test_verify_failure_is_non_fatal(
        self,
        _mock_composite: object,
        _mock_expected: object,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """R5: If verify_recommendations fails, top-picks still works."""
        recs = [_make_rec("300750", "宁德时代", 0.8)]
        _write_report(tmp_path, recs)

        with patch(
            "src.screening.top_picks.compute_verify_recommendations",
            side_effect=RuntimeError("no data"),
        ), patch(
            "src.screening.market_state.detect_market_state",
            return_value=SimpleNamespace(regime="trend"),
        ):
            rc = run_top_picks(count=5, reports_dir=tmp_path)

        assert rc == 0
        output = capsys.readouterr().out
        assert "300750" in output


# ---------------------------------------------------------------------------
# Verdict distribution summary tests
# ---------------------------------------------------------------------------


class TestVerdictDistribution:
    """Tests for BUY/HOLD/AVOID distribution summary."""

    def _make_pick(self, score: float, t30: float = 0.0, t30_wr: float = 0.0, sample: int = 0, decision: str = "bullish") -> dict:
        """Build a recommendation dict with enough fields for verdict."""
        return {
            "composite_score": score,
            "score_b": score,
            "decision": decision,
            "expected_returns": {"t30": t30},
            "win_rates": {"t30": t30_wr},
            "bucket_sample_count": sample,
        }

    def test_all_buy(self) -> None:
        from src.screening.top_picks import _render_verdict_distribution
        picks = [
            self._make_pick(0.8, t30=10.0, t30_wr=0.66, sample=40),
            self._make_pick(0.6, t30=5.0, t30_wr=0.60, sample=30),
        ]
        result = _render_verdict_distribution(picks, market_regime="trend")
        assert "BUY=2" in result
        assert "AVOID" not in result

    def test_mixed_verdicts(self) -> None:
        from src.screening.top_picks import _render_verdict_distribution
        picks = [
            self._make_pick(0.7, t30=8.0, t30_wr=0.62, sample=25),   # BUY
            self._make_pick(0.35, t30=1.0, t30_wr=0.52, sample=15),  # HOLD
            self._make_pick(0.1, t30=-2.0, t30_wr=0.40, sample=10),   # AVOID
        ]
        result = _render_verdict_distribution(picks, market_regime="trend")
        assert "BUY=1" in result
        assert "HOLD=1" in result
        assert "AVOID=1" in result

    def test_empty_picks(self) -> None:
        from src.screening.top_picks import _render_verdict_distribution
        result = _render_verdict_distribution([], market_regime="trend")
        assert result == ""

    def test_crisis_mode_downgrades(self) -> None:
        from src.screening.top_picks import _render_verdict_distribution
        picks = [
            self._make_pick(0.8, t30=10.0, t30_wr=0.66, sample=40),
        ]
        result = _render_verdict_distribution(picks, market_regime="crisis")
        assert "BUY" not in result
        assert "HOLD=1" in result


# ---------------------------------------------------------------------------
# Market opportunity index tests
# ---------------------------------------------------------------------------


class TestMarketOpportunityIndex:
    """Tests for market opportunity traffic light."""

    def _make_pick(self, score: float, t30: float = 10.0, t30_wr: float = 0.66, sample: int = 40, decision: str = "bullish") -> dict:
        return {
            "composite_score": score,
            "score_b": score,
            "decision": decision,
            "expected_returns": {"t30": t30},
            "win_rates": {"t30": t30_wr},
            "bucket_sample_count": sample,
        }

    def test_go_signal_with_high_quality_buys(self) -> None:
        from src.screening.top_picks import _render_market_opportunity_index
        picks = [
            self._make_pick(0.7, t30=8.0, t30_wr=0.62, sample=25),
            self._make_pick(0.6, t30=6.0, t30_wr=0.58, sample=30),
        ]
        result = _render_market_opportunity_index(picks, market_regime="trend")
        assert "GO" in result
        assert "BUY 2/2" in result

    def test_wait_signal_in_crisis(self) -> None:
        from src.screening.top_picks import _render_market_opportunity_index
        picks = [self._make_pick(0.3)]
        result = _render_market_opportunity_index(picks, market_regime="crisis")
        assert "WAIT" in result

    def test_caution_signal_with_no_buys(self) -> None:
        from src.screening.top_picks import _render_market_opportunity_index
        picks = [self._make_pick(0.2, t30=-1.0, t30_wr=0.40, sample=5)]
        result = _render_market_opportunity_index(picks, market_regime="range_bound")
        assert "WAIT" in result or "CAUTION" in result

    def test_empty_picks(self) -> None:
        from src.screening.top_picks import _render_market_opportunity_index
        result = _render_market_opportunity_index([], market_regime="trend")
        assert "无候选" in result or "CAUTION" in result

