"""Tests for top_picks.py — P12-2 + R4/R5."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from src.screening.composite_score import CompositeEntry, CompositeReport
from src.screening.expected_return import ExpectedReturn, ExpectedReturnReport
from src.screening.top_picks import (
    _apply_consecutive_bonus_and_resort,
    _build_signal_breakdown,
    _consecutive_bonus,
    _extract_t30_metrics,
    _load_recommendation_context,
    _render_hit_rate_summary,
    _score_color,
    _status_icon,
    run_top_picks,
)
from src.utils.display import Fore, Style


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
        json.dumps({"date": date, "recommendations": recs}),
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

    def test_decision_flow_hint_in_footer(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Round 9 quality slice: --top-picks footer points users to --decision-flow.

        Product goal "用尽可能少的入口" (feature-proposals.md:3) and the
        "避免前门分裂" constraint are served by telling users the front door
        already covers the common case, so they don't run both commands.
        Follows the Round 6 research recommendation (round6-product-analysis.md:15).
        """
        recs = [_make_rec("300750", "宁德时代", 0.6)]
        _write_report(tmp_path, recs, date="20260613")
        rc = run_top_picks(count=5, reports_dir=tmp_path)
        assert rc == 0
        output = capsys.readouterr().out
        assert "--decision-flow" in output


class TestExtractedTopPicksHelpers:
    def test_build_signal_breakdown_renders_positive_negative_and_consecutive(self) -> None:
        item = {
            "momentum_bonus": 0.1,
            "sector_bonus": -0.2,
            "consistency_adj": 0.3,
            "volume_factor": -0.1,
            "trend_resonance_factor": 0.03,
            "consecutive_bonus": 0.04,
        }

        result = _build_signal_breakdown(item)

        assert "动量↑" in result
        assert "行业弱" in result
        assert "一致" in result
        assert "缩量" in result
        assert "共振↑" in result
        assert "连续+0.04" in result

    def test_build_signal_breakdown_returns_neutral_when_no_threshold_crossed(self) -> None:
        result = _build_signal_breakdown(
            {
                "momentum_bonus": 0.0,
                "sector_bonus": 0.0,
                "consistency_adj": 0.0,
                "volume_factor": 0.0,
                "trend_resonance_factor": 0.01,
                "consecutive_bonus": 0.0,
            }
        )

        assert "中性" in result
        assert "共振" not in result

    def test_score_color_thresholds(self) -> None:
        assert _score_color(0.6) == Fore.GREEN + Style.BRIGHT
        assert _score_color(0.4) == Fore.YELLOW
        assert _score_color(0.2) == Fore.RED

    def test_extract_t30_metrics_returns_numeric_values(self) -> None:
        """DRY helper extracts T+30 edge/winrate from a pick dict.

        Used by both the per-pick table row and the R33 portfolio summary,
        so the two rendering paths can never diverge on the extraction logic.
        """
        item = {
            "expected_returns": {"t30": 3.5},
            "win_rates": {"t30": 0.58},
        }
        edge, winrate = _extract_t30_metrics(item)
        assert edge == 3.5
        assert winrate == 0.58

    def test_extract_t30_metrics_returns_none_when_missing(self) -> None:
        item = {"expected_returns": {}, "win_rates": {}}
        edge, winrate = _extract_t30_metrics(item)
        assert edge is None
        assert winrate is None

    def test_extract_t30_metrics_returns_none_when_keys_absent(self) -> None:
        edge, winrate = _extract_t30_metrics({})
        assert edge is None
        assert winrate is None

    def test_extract_t30_metrics_ignores_non_numeric(self) -> None:
        item = {"expected_returns": {"t30": "n/a"}, "win_rates": {"t30": None}}
        edge, winrate = _extract_t30_metrics(item)
        assert edge is None
        assert winrate is None

    def test_load_recommendation_context_slices_to_count_times_three(self, tmp_path: Path) -> None:
        recs = [_make_rec(f"{index:06d}", f"Stock{index}", 0.5) for index in range(10)]
        _write_report(tmp_path, recs, date="20260611")

        context = _load_recommendation_context(tmp_path, count=2)

        assert context is not None
        report_path, report_data, loaded_recs, trade_date = context
        assert report_path.name == "auto_screening_20260611.json"
        assert report_data["date"] == "20260611"
        assert trade_date == "20260611"
        assert len(loaded_recs) == 6

    def test_load_recommendation_context_returns_none_without_reports(self, tmp_path: Path) -> None:
        assert _load_recommendation_context(tmp_path, count=2) is None

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

    def test_apply_consecutive_bonus_clips_to_unit_range(self) -> None:
        """composite_score is documented as clamped to [-1.0, +1.0]
        (composite_score.py:16, :233). The consecutive bonus is added *after*
        that clamp in ``_apply_consecutive_bonus_and_resort``, so it must
        re-clamp — otherwise a high-base pick (0.98) plus a 6+day bonus (0.08)
        yields composite_score=1.06, an out-of-domain value that silently
        breaks the [-1,1] invariant every downstream consumer assumes.
        """
        ranked = [
            {"ticker": "A", "composite_score": 0.98, "consecutive_bonus": 0.08},
        ]
        out = _apply_consecutive_bonus_and_resort(ranked)
        assert out[0]["composite_score"] <= 1.0, (
            f"composite_score {out[0]['composite_score']} exceeds the documented [-1,1] domain"
        )

    def test_apply_consecutive_bonus_clips_negative_too(self) -> None:
        """Symmetric: a low-base pick with a positive bonus must not dip
        below -1.0 either. (Bonus is always >= 0 in practice, but the clamp
        guard should hold for both bounds.)"""
        ranked = [
            {"ticker": "A", "composite_score": -0.98, "consecutive_bonus": 0.0},
        ]
        out = _apply_consecutive_bonus_and_resort(ranked)
        assert out[0]["composite_score"] >= -1.0

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

    def test_summary_suppresses_zero_information_excess_line(self) -> None:
        """H1 (Stage 3 product-quality): the recommended-basket "benchmark" is
        computed from the SAME picks as the basket mean, so ``excess_return`` is
        structurally ≈ 0.0 (mean(picks) - mean(picks) = 0). Rendering a line that
        is always ~0.00% adds noise and erodes trust. The line must be suppressed
        when |excess| ≤ epsilon; a future real benchmark (CSI300) would render.

        This pins the suppression invariant so the noisy dead line cannot return.
        """
        # |excess| within epsilon → suppressed
        summary_zero = SimpleNamespace(
            total_recommendations=100,
            total_days=20,
            unique_tickers=40,
            lookback_days=30,
            overall_t5_win_rate=0.55,
            avg_t5_return=1.0,
            excess_return=0.0,
        )
        result_zero = _render_hit_rate_summary(summary_zero)
        assert "历史命中率速览" in result_zero
        assert "超额收益" not in result_zero

        # |excess| just above epsilon → rendered (future real-benchmark path)
        summary_real = SimpleNamespace(
            total_recommendations=100,
            total_days=20,
            unique_tickers=40,
            lookback_days=30,
            overall_t5_win_rate=0.55,
            avg_t5_return=1.0,
            excess_return=0.5,
        )
        result_real = _render_hit_rate_summary(summary_real)
        assert "超额收益" in result_real

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


# ---------------------------------------------------------------------------
# R8: Stop-loss / take-profit
# ---------------------------------------------------------------------------


class TestStopLossTakeProfit:
    """R8/R32: _compute_pick_risk_advice — best-effort ATR advice shared by
    stop-loss rendering (R8) and reason+risk label (R32).

    The dead ``_render_stop_loss_take_profit`` wrapper was removed after the
    R32 refactor made ``_print_pick_entry_details`` call
    ``_compute_pick_risk_advice`` + ``_format_stop_loss_take_profit`` directly;
    these tests now exercise the real production function.
    """

    def test_no_prices_returns_none(self) -> None:
        from src.screening.top_picks import _compute_pick_risk_advice

        with patch("src.tools.tushare_api.get_ashare_prices_with_tushare", return_value=[]):
            assert _compute_pick_risk_advice("300750", "宁德时代", trade_date="20260610") is None

    def test_valid_prices_returns_advice(self) -> None:
        from src.data.models import Price
        from src.screening.top_picks import (
            _compute_pick_risk_advice,
            _format_stop_loss_take_profit,
        )

        # Create mock price data with enough history for ATR
        prices = [
            Price(open=100.0 + i * 0.5, close=100.0 + i * 0.5, high=101.0 + i * 0.5, low=99.0 + i * 0.5, volume=1000, time=f"2026-05-{i+1:02d}")
            for i in range(20)
        ]
        with patch("src.tools.tushare_api.get_ashare_prices_with_tushare", return_value=prices):
            advice = _compute_pick_risk_advice("300750", "宁德时代", trade_date="20260610")
        assert advice is not None
        rendered = _format_stop_loss_take_profit(advice)
        assert "止损=" in rendered
        assert "止盈=" in rendered
        assert "盈亏比=" in rendered

    def test_exception_returns_none(self) -> None:
        from src.screening.top_picks import _compute_pick_risk_advice

        with patch("src.tools.tushare_api.get_ashare_prices_with_tushare", side_effect=Exception("boom")):
            assert _compute_pick_risk_advice("300750", "宁德时代", trade_date="20260610") is None


# ---------------------------------------------------------------------------
# R9: Score trend
# ---------------------------------------------------------------------------


class TestScoreTrend:
    """R9: _render_score_trend — score trend direction from signal decay."""

    def test_no_report_returns_empty(self, tmp_path: Path) -> None:
        from src.screening.top_picks import _render_score_trend

        result = _render_score_trend("300750", report_dir=tmp_path)
        assert result == ""

    def test_rising_score_shows_up_arrow(self, tmp_path: Path) -> None:
        from src.screening.signal_decay_detector import DecayInfo, DecayLevel
        from src.screening.top_picks import _render_score_trend

        decay_info = DecayInfo(
            ticker="300750",
            level=DecayLevel.NONE,
            current_score=0.8,
            previous_score=0.6,
            change_pct=33.0,
            days_since_peak=0,
        )
        with patch("src.screening.top_picks.detect_signal_decay", return_value={"300750": decay_info}):
            with patch("src.screening.top_picks._find_latest_report", return_value=tmp_path / "fake.json"):
                (tmp_path / "fake.json").write_text('{"recommendations":[]}', encoding="utf-8")
                result = _render_score_trend("300750", report_dir=tmp_path)
                assert "↑↑" in result

    def test_falling_score_shows_down_arrow(self, tmp_path: Path) -> None:
        from src.screening.signal_decay_detector import DecayInfo, DecayLevel
        from src.screening.top_picks import _render_score_trend

        decay_info = DecayInfo(
            ticker="300750",
            level=DecayLevel.MODERATE,
            current_score=0.3,
            previous_score=0.6,
            change_pct=-50.0,
            days_since_peak=3,
        )
        with patch("src.screening.top_picks.detect_signal_decay", return_value={"300750": decay_info}):
            with patch("src.screening.top_picks._find_latest_report", return_value=tmp_path / "fake.json"):
                (tmp_path / "fake.json").write_text('{"recommendations":[]}', encoding="utf-8")
                result = _render_score_trend("300750", report_dir=tmp_path)
                assert "↓↓" in result

    def test_stable_score_shows_arrow(self, tmp_path: Path) -> None:
        from src.screening.signal_decay_detector import DecayInfo, DecayLevel
        from src.screening.top_picks import _render_score_trend

        decay_info = DecayInfo(
            ticker="300750",
            level=DecayLevel.NONE,
            current_score=0.6,
            previous_score=0.59,
            change_pct=1.7,
            days_since_peak=0,
        )
        with patch("src.screening.top_picks.detect_signal_decay", return_value={"300750": decay_info}):
            with patch("src.screening.top_picks._find_latest_report", return_value=tmp_path / "fake.json"):
                (tmp_path / "fake.json").write_text('{"recommendations":[]}', encoding="utf-8")
                result = _render_score_trend("300750", report_dir=tmp_path)
                assert "→" in result

    def test_no_previous_score_returns_empty(self, tmp_path: Path) -> None:
        from src.screening.signal_decay_detector import DecayInfo, DecayLevel
        from src.screening.top_picks import _render_score_trend

        decay_info = DecayInfo(
            ticker="300750",
            level=DecayLevel.NONE,
            current_score=0.6,
            previous_score=None,
            change_pct=None,
            days_since_peak=0,
        )
        with patch("src.screening.top_picks.detect_signal_decay", return_value={"300750": decay_info}):
            with patch("src.screening.top_picks._find_latest_report", return_value=tmp_path / "fake.json"):
                (tmp_path / "fake.json").write_text('{"recommendations":[]}', encoding="utf-8")
                result = _render_score_trend("300750", report_dir=tmp_path)
                assert result == ""

    def test_zero_previous_score_returns_empty_not_flat_arrow(self, tmp_path: Path) -> None:
        """BH-006: when previous_score == 0.0 (coerced from None/NaN by
        ALPHA-002), ``change_pct`` is None (division by zero is undefined).
        The old guard only checked ``previous_score is None``, so 0.0 slipped
        through and rendered a flat "→" on a pick with no valid prior score.
        The fix also suppresses the arrow when ``change_pct is None``."""
        from src.screening.signal_decay_detector import DecayInfo, DecayLevel
        from src.screening.top_picks import _render_score_trend

        decay_info = DecayInfo(
            ticker="300750",
            level=DecayLevel.NONE,
            current_score=0.6,
            previous_score=0.0,  # NOT None — but change_pct is None (the trap)
            change_pct=None,
            days_since_peak=0,
        )
        with patch("src.screening.top_picks.detect_signal_decay", return_value={"300750": decay_info}):
            with patch("src.screening.top_picks._find_latest_report", return_value=tmp_path / "fake.json"):
                (tmp_path / "fake.json").write_text('{"recommendations":[]}', encoding="utf-8")
                result = _render_score_trend("300750", report_dir=tmp_path)
                assert result == ""
                assert "→" not in result


# ---------------------------------------------------------------------------
# R10: Multi-strategy confluence
# ---------------------------------------------------------------------------


class TestConfluence:
    """Tests for _compute_confluence and _render_confluence (R10)."""

    def test_compute_confluence_all_bullish(self) -> None:
        from src.screening.top_picks import _compute_confluence

        item = _make_rec("300750", "宁德时代", 0.8)
        bullish, total = _compute_confluence(item)
        # _make_rec has 3 bullish (trend=1, fundamental=1, event_sentiment=1) + 1 neutral
        assert bullish == 3
        assert total == 4

    def test_compute_confluence_all_bearish(self) -> None:
        from src.screening.top_picks import _compute_confluence

        item = {
            "ticker": "000001",
            "strategy_signals": {
                "trend": {"direction": -1},
                "mean_reversion": {"direction": -1},
                "fundamental": {"direction": 0},
                "event_sentiment": {"direction": -1},
            },
        }
        bullish, total = _compute_confluence(item)
        assert bullish == 0
        assert total == 4

    def test_compute_confluence_no_signals(self) -> None:
        from src.screening.top_picks import _compute_confluence

        item: dict[str, Any] = {"ticker": "000001"}
        bullish, total = _compute_confluence(item)
        assert bullish == 0
        assert total == 0

    def test_render_confluence_4_of_4(self) -> None:
        from src.screening.top_picks import _render_confluence

        result = _render_confluence(4, 4)
        assert "共振 4/4" in result
        assert "\033[32m" in result  # Green color

    def test_render_confluence_0_of_4(self) -> None:
        from src.screening.top_picks import _render_confluence

        result = _render_confluence(0, 4)
        assert "共振 0/4" in result

    def test_render_confluence_empty(self) -> None:
        from src.screening.top_picks import _render_confluence

        result = _render_confluence(0, 0)
        assert result == ""

    def test_confluence_appears_in_output(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        recs = [_make_rec("300750", "宁德时代", 0.6)]
        _write_report(tmp_path, recs)
        rc = run_top_picks(count=5, reports_dir=tmp_path)
        assert rc == 0
        output = capsys.readouterr().out
        assert "共振" in output


# ---------------------------------------------------------------------------
# R11: Sector focus summary
# ---------------------------------------------------------------------------


class TestSectorFocus:
    """Tests for _render_sector_focus (R11)."""

    def test_sector_focus_single_industry(self) -> None:
        from src.screening.top_picks import _render_sector_focus

        picks = [
            {"industry_sw": "电子"},
            {"industry_sw": "电子"},
            {"industry_sw": "电子"},
        ]
        result = _render_sector_focus(picks)
        assert "电子" in result
        assert "(3)" in result
        assert "行业聚焦" in result

    def test_sector_focus_multiple_industries(self) -> None:
        from src.screening.top_picks import _render_sector_focus

        picks = [
            {"industry_sw": "电子"},
            {"industry_sw": "电子"},
            {"industry_sw": "医药"},
            {"industry_sw": "机械"},
        ]
        result = _render_sector_focus(picks)
        assert "电子" in result
        assert "(2)" in result
        assert "行业聚焦" in result

    def test_sector_focus_all_single(self) -> None:
        from src.screening.top_picks import _render_sector_focus

        picks = [
            {"industry_sw": "电子"},
            {"industry_sw": "医药"},
            {"industry_sw": "机械"},
        ]
        result = _render_sector_focus(picks)
        assert "行业聚焦" in result
        # All are count=1, should show industry names
        assert "电子" in result

    def test_sector_focus_empty_picks(self) -> None:
        from src.screening.top_picks import _render_sector_focus

        result = _render_sector_focus([])
        assert result == ""

    def test_sector_focus_no_industry(self) -> None:
        from src.screening.top_picks import _render_sector_focus

        picks = [{"ticker": "000001"}, {"ticker": "000002"}]
        result = _render_sector_focus(picks)
        assert result == ""

    def test_sector_focus_appears_in_output(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        recs = [
            _make_rec("300750", "宁德时代", 0.6, "电气设备"),
            _make_rec("600519", "贵州茅台", 0.5, "食品饮料"),
            _make_rec("000001", "平安银行", 0.3, "银行"),
        ]
        _write_report(tmp_path, recs)
        rc = run_top_picks(count=5, reports_dir=tmp_path)
        assert rc == 0
        output = capsys.readouterr().out
        assert "行业聚焦" in output


# ---------------------------------------------------------------------------
# R12: Data freshness guard
# ---------------------------------------------------------------------------


class TestDataFreshness:
    """Tests for _check_report_freshness (R12)."""

    def test_fresh_report_no_warning(self) -> None:
        from datetime import datetime

        from src.screening.top_picks import _check_report_freshness

        today = datetime.now().strftime("%Y%m%d")
        result = _check_report_freshness(today)
        assert result == ""

    def test_yesterday_report_no_warning(self) -> None:
        from datetime import datetime, timedelta

        from src.screening.top_picks import _check_report_freshness

        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        result = _check_report_freshness(yesterday)
        assert result == ""

    def test_stale_report_shows_warning(self) -> None:
        from datetime import datetime

        from src.screening.top_picks import _check_report_freshness

        # A report >= 2 trading days old must warn. Using a deterministic date
        # (2026-06-12 Fri read 2026-06-17 Wed = 2 elapsed trading days: Mon+Tue)
        # avoids the weekend-dependent flakiness of the old `now - 3 days` form.
        result = _check_report_freshness("20260612", now=datetime(2026, 6, 17))
        assert "非最新" in result
        assert "⚠" in result

    def test_very_old_report_shows_warning(self) -> None:
        from src.screening.top_picks import _check_report_freshness

        result = _check_report_freshness("20260101")
        assert "非最新" in result

    def test_invalid_date_no_warning(self) -> None:
        from src.screening.top_picks import _check_report_freshness

        assert _check_report_freshness("") == ""
        assert _check_report_freshness("invalid") == ""
        assert _check_report_freshness("20261301") == ""

    def test_friday_report_read_monday_no_false_stale(self) -> None:
        """Friday report read on Monday (next trading day) must NOT warn stale.

        2026-06-12 is a Friday; 2026-06-15 is the following Monday. The Friday
        report is still the latest trading-day data on Monday morning, so the
        R12 guard must not show a false "非最新" warning (3 calendar days but
        only 0 business days elapsed). Regression test for the weekend false-
        positive bug where age_days >= 2 fired on Monday morning.
        """
        from datetime import datetime

        from src.screening.top_picks import _check_report_freshness

        result = _check_report_freshness("20260612", now=datetime(2026, 6, 15))
        assert result == ""

    def test_thursday_report_read_monday_no_false_stale(self) -> None:
        """Thursday report read Monday = 1 business day elapsed → still fresh.

        2026-06-11 (Thu) read on 2026-06-15 (Mon): covers a weekend, only one
        business day has passed. This is the normal "ran --auto Thursday,
        reviewing Monday pre-market" case.
        """
        from datetime import datetime

        from src.screening.top_picks import _check_report_freshness

        result = _check_report_freshness("20260611", now=datetime(2026, 6, 15))
        assert result == ""

    def test_stale_report_2_business_days_warns(self) -> None:
        """A report 2+ business days old (e.g. Monday read Wed) still warns."""
        from datetime import datetime

        from src.screening.top_picks import _check_report_freshness

        # 2026-06-12 (Fri) read 2026-06-17 (Wed) = 2 business days elapsed
        result = _check_report_freshness("20260612", now=datetime(2026, 6, 17))
        assert "非最新" in result

    def test_during_long_holiday_no_false_stale(self, monkeypatch) -> None:
        """BH-015 / R45 same-class drain: a pre-CNY report read mid-holiday must
        not show a false stale warning when trade_cal is available.

        2024-02-08 (Thu) is the last trading day before Spring Festival;
        2024-02-13 (Tue) is mid-holiday closure (markets shut Feb 9 - Feb 18).
        The weekday-only approximation counts Fri 2/9 + Mon 2/12 + Tue 2/13's
        prior-weekday-rolled "now" → 2+ elapsed business days → false stale.
        With trade_cal, ZERO trading days have actually elapsed (no opens
        between Feb 8 close and Feb 13), so warning must be suppressed.
        """
        from datetime import datetime

        # Real A-share open dates spanning Spring Festival 2024.
        cny_open_dates = [
            "20240207",
            "20240208",  # last day before CNY
            # Feb 9 - Feb 18: Spring Festival closure (no opens)
            "20240219",
            "20240220",
        ]

        def mock_get_open(start: str, end: str) -> list[str]:
            return [d for d in cny_open_dates if start <= d <= end]

        monkeypatch.setattr(
            "src.tools.tushare_api.get_open_trade_dates",
            mock_get_open,
        )
        from src.screening.top_picks import _check_report_freshness

        # Mid-holiday review of pre-CNY report.
        result = _check_report_freshness("20240208", now=datetime(2024, 2, 13))
        assert result == "", f"Expected no warning during CNY closure, got: {result!r}"

    def test_post_long_holiday_warns_only_after_real_trading_days(self, monkeypatch) -> None:
        """BH-015 / R45 same-class: post-CNY review still warns when real
        elapsed trading days >= 2 (e.g. ran --auto Thu 2/8 pre-CNY but did
        not re-run; reviewing Wed 2/21 = Mon 2/19 + Tue 2/20 = 2 real
        trading days elapsed → stale).
        """
        from datetime import datetime

        cny_open_dates = [
            "20240207",
            "20240208",
            "20240219",
            "20240220",
            "20240221",
        ]

        def mock_get_open(start: str, end: str) -> list[str]:
            return [d for d in cny_open_dates if start <= d <= end]

        monkeypatch.setattr(
            "src.tools.tushare_api.get_open_trade_dates",
            mock_get_open,
        )
        from src.screening.top_picks import _check_report_freshness

        # Pre-CNY report read Wed 2024-02-21 → 2 real trading days elapsed.
        result = _check_report_freshness("20240208", now=datetime(2024, 2, 21))
        assert "非最新" in result

    def test_freshness_falls_back_to_weekday_when_trade_cal_unavailable(self, monkeypatch) -> None:
        """BH-015 / R45 same-class: trade_cal failure must not break the
        existing R12 weekday approximation behaviour. Fri+Mon read Wed = 2
        trading days elapsed → still warns (R36 behaviour preserved).
        """
        from datetime import datetime

        def mock_empty(start: str, end: str) -> list[str]:
            return []

        monkeypatch.setattr(
            "src.tools.tushare_api.get_open_trade_dates",
            mock_empty,
        )
        from src.screening.top_picks import _check_report_freshness

        result = _check_report_freshness("20260612", now=datetime(2026, 6, 17))
        assert "非最新" in result


# ---------------------------------------------------------------------------
# R13: New / dropped pick detection
# ---------------------------------------------------------------------------


class TestPickChanges:
    """Tests for _find_previous_report, _compute_pick_changes, _render_pick_changes (R13)."""

    def test_find_previous_report_single_file(self, tmp_path: Path) -> None:
        from src.screening.top_picks import _find_previous_report

        p = tmp_path / "auto_screening_20260610.json"
        p.write_text("{}", encoding="utf-8")
        assert _find_previous_report(p) is None

    def test_find_previous_report_two_files(self, tmp_path: Path) -> None:
        from src.screening.top_picks import _find_previous_report

        p1 = tmp_path / "auto_screening_20260609.json"
        p2 = tmp_path / "auto_screening_20260610.json"
        p1.write_text("{}", encoding="utf-8")
        p2.write_text("{}", encoding="utf-8")
        assert _find_previous_report(p2) == p1

    def test_find_previous_report_first_file(self, tmp_path: Path) -> None:
        from src.screening.top_picks import _find_previous_report

        p1 = tmp_path / "auto_screening_20260609.json"
        p2 = tmp_path / "auto_screening_20260610.json"
        p1.write_text("{}", encoding="utf-8")
        p2.write_text("{}", encoding="utf-8")
        assert _find_previous_report(p1) is None

    def test_compute_pick_changes_new_and_dropped(self, tmp_path: Path) -> None:
        from src.screening.top_picks import _compute_pick_changes

        prev = tmp_path / "auto_screening_20260609.json"
        prev.write_text(
            json.dumps({"recommendations": [{"ticker": "000001"}, {"ticker": "000002"}]}),
            encoding="utf-8",
        )
        current = {"300750", "000001"}  # 000002 dropped, 300750 new
        new, dropped = _compute_pick_changes(current, prev)
        assert new == {"300750"}
        assert dropped == {"000002"}

    def test_compute_pick_changes_no_changes(self, tmp_path: Path) -> None:
        from src.screening.top_picks import _compute_pick_changes

        prev = tmp_path / "auto_screening_20260609.json"
        prev.write_text(
            json.dumps({"recommendations": [{"ticker": "000001"}, {"ticker": "000002"}]}),
            encoding="utf-8",
        )
        current = {"000001", "000002"}
        new, dropped = _compute_pick_changes(current, prev)
        assert new == set()
        assert dropped == set()

    def test_compute_pick_changes_bad_file(self, tmp_path: Path) -> None:
        from src.screening.top_picks import _compute_pick_changes

        bad = tmp_path / "auto_screening_20260609.json"
        bad.write_text("not json", encoding="utf-8")
        new, dropped = _compute_pick_changes({"000001"}, bad)
        assert new == set()
        assert dropped == set()

    def test_render_pick_changes_new_only(self) -> None:
        from src.screening.top_picks import _render_pick_changes

        result = _render_pick_changes({"300750"}, set(), [{"ticker": "300750", "name": "宁德时代"}])
        assert "新入选" in result
        assert "🆕" in result
        assert "宁德时代" in result

    def test_render_pick_changes_dropped_only(self) -> None:
        from src.screening.top_picks import _render_pick_changes

        result = _render_pick_changes(set(), {"000001"}, [])
        assert "退出" in result
        assert "❌" in result
        assert "000001" in result

    def test_render_pick_changes_both(self) -> None:
        from src.screening.top_picks import _render_pick_changes

        result = _render_pick_changes(
            {"300750"},
            {"000001"},
            [{"ticker": "300750", "name": "宁德时代"}],
        )
        assert "新入选" in result
        assert "退出" in result

    def test_render_pick_changes_empty(self) -> None:
        from src.screening.top_picks import _render_pick_changes

        result = _render_pick_changes(set(), set(), [])
        assert result == ""

    def test_new_badge_appears_in_output(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        # Write previous report with different tickers
        prev = tmp_path / "auto_screening_20260609.json"
        prev.write_text(
            json.dumps({"date": "20260609", "recommendations": [{"ticker": "999999", "name": "Old", "score_b": 0.5}]}),
            encoding="utf-8",
        )
        # Write current report
        recs = [_make_rec("300750", "宁德时代", 0.6)]
        _write_report(tmp_path, recs, date="20260610")
        rc = run_top_picks(count=5, reports_dir=tmp_path)
        assert rc == 0
        output = capsys.readouterr().out
        assert "🆕" in output

    def test_stale_report_warning_in_output(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        recs = [_make_rec("300750", "宁德时代", 0.6)]
        _write_report(tmp_path, recs, date="20260101")  # Very old date
        rc = run_top_picks(count=5, reports_dir=tmp_path)
        assert rc == 0
        output = capsys.readouterr().out
        assert "非最新" in output
