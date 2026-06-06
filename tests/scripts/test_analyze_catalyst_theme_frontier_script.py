from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.analyze_catalyst_theme_frontier import analyze_catalyst_theme_frontier, render_catalyst_theme_frontier_markdown


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_analyze_catalyst_theme_frontier_promotes_shadow_candidates(tmp_path: Path, monkeypatch) -> None:
    report_dir = tmp_path / "paper_trading_20260331_20260331_live_m2_7_short_trade_only"
    _write_json(
        report_dir / "selection_artifacts" / "2026-03-31" / "selection_snapshot.json",
        {
            "trade_date": "20260331",
            "catalyst_theme_candidates": [
                {
                    "ticker": "300999",
                    "decision": "catalyst_theme",
                    "score_target": 0.4126,
                    "candidate_source": "catalyst_theme",
                    "gate_status": {"data": "pass", "structural": "fail", "score": "proxy_only"},
                    "metrics": {
                        "breakout_freshness": 0.31,
                        "trend_acceleration": 0.26,
                        "close_strength": 0.57,
                        "sector_resonance": 0.25,
                        "catalyst_freshness": 0.84,
                    },
                }
            ],
            "catalyst_theme_shadow_candidates": [
                {
                    "ticker": "301001",
                    "decision": "catalyst_theme_shadow",
                    "score_target": 0.32,
                    "candidate_source": "catalyst_theme_shadow",
                    "filter_reason": "sector_resonance_below_catalyst_theme_floor",
                    "threshold_shortfalls": {"candidate_score": 0.02, "sector_resonance": 0.03},
                    "failed_threshold_count": 2,
                    "total_shortfall": 0.05,
                    "gate_status": {"data": "pass", "structural": "fail", "score": "shadow"},
                    "metrics": {
                        "breakout_freshness": 0.14,
                        "trend_acceleration": 0.21,
                        "close_strength": 0.41,
                        "sector_resonance": 0.22,
                        "catalyst_freshness": 0.82,
                    },
                },
                {
                    "ticker": "301002",
                    "decision": "catalyst_theme_shadow",
                    "score_target": 0.29,
                    "candidate_source": "catalyst_theme_shadow",
                    "filter_reason": "close_strength_below_catalyst_theme_floor",
                    "threshold_shortfalls": {"candidate_score": 0.05, "close_strength": 0.05, "catalyst_freshness": 0.04},
                    "failed_threshold_count": 3,
                    "total_shortfall": 0.14,
                    "gate_status": {"data": "pass", "structural": "fail", "score": "shadow"},
                    "metrics": {
                        "breakout_freshness": 0.12,
                        "trend_acceleration": 0.19,
                        "close_strength": 0.15,
                        "sector_resonance": 0.21,
                        "catalyst_freshness": 0.41,
                    },
                },
            ],
        },
    )

    monkeypatch.setattr("scripts.analyze_catalyst_theme_frontier.get_price_data", lambda *args, **kwargs: pd.DataFrame())

    analysis = analyze_catalyst_theme_frontier(
        report_dir,
        candidate_score_min_grid=[0.34, 0.32],
        breakout_min_grid=[0.10],
        close_min_grid=[0.20],
        sector_min_grid=[0.25, 0.22],
        catalyst_min_grid=[0.45],
        max_candidates_per_trade_date=8,
    )

    assert analysis["baseline_selected_count"] == 1
    assert analysis["shadow_candidate_count"] == 2
    assert analysis["baseline_variant"]["promoted_shadow_count"] == 0
    assert analysis["recommended_variant"]["promoted_shadow_count"] == 1
    assert analysis["recommended_variant"]["top_promoted_rows"][0]["ticker"] == "301001"
    assert "sector_resonance_below_catalyst_theme_floor" in analysis["recommended_variant"]["promoted_filter_reason_counts"]

    markdown = render_catalyst_theme_frontier_markdown(analysis)
    assert "# Catalyst Theme Frontier Review" in markdown
    assert "## Recommended Variant" in markdown
    assert "301001" in markdown
    assert "## Promoted Shadow Examples" in markdown


def test_analyze_catalyst_theme_frontier_summarizes_t1_t2_outcomes(tmp_path: Path, monkeypatch) -> None:
    report_dir = tmp_path / "paper_trading_20260331_20260331_live_m2_7_short_trade_only"
    _write_json(
        report_dir / "selection_artifacts" / "2026-03-31" / "selection_snapshot.json",
        {
            "trade_date": "20260331",
            "catalyst_theme_candidates": [
                {
                    "ticker": "300999",
                    "decision": "catalyst_theme",
                    "score_target": 0.4126,
                    "candidate_source": "catalyst_theme",
                    "gate_status": {"data": "pass"},
                    "metrics": {
                        "breakout_freshness": 0.31,
                        "trend_acceleration": 0.26,
                        "close_strength": 0.57,
                        "sector_resonance": 0.25,
                        "catalyst_freshness": 0.84,
                    },
                }
            ],
            "catalyst_theme_shadow_candidates": [
                {
                    "ticker": "301001",
                    "decision": "catalyst_theme_shadow",
                    "score_target": 0.32,
                    "candidate_source": "catalyst_theme_shadow",
                    "filter_reason": "sector_resonance_below_catalyst_theme_floor",
                    "threshold_shortfalls": {"candidate_score": 0.02, "sector_resonance": 0.03},
                    "failed_threshold_count": 2,
                    "total_shortfall": 0.05,
                    "gate_status": {"data": "pass"},
                    "metrics": {
                        "breakout_freshness": 0.14,
                        "trend_acceleration": 0.21,
                        "close_strength": 0.41,
                        "sector_resonance": 0.22,
                        "catalyst_freshness": 0.82,
                    },
                }
            ],
        },
    )

    def fake_get_price_data(ticker: str, start_date: str, end_date: str):
        if ticker == "300999":
            return pd.DataFrame(
                [
                    {"date": "2026-03-31", "open": 10.0, "high": 10.0, "low": 9.8, "close": 10.0},
                    {"date": "2026-04-01", "open": 10.1, "high": 10.5, "low": 10.0, "close": 10.4},
                    {"date": "2026-04-02", "open": 10.3, "high": 10.8, "low": 10.2, "close": 10.6},
                ]
            ).assign(date=lambda frame: pd.to_datetime(frame["date"]).dt.normalize()).set_index("date")
        if ticker == "301001":
            return pd.DataFrame(
                [
                    {"date": "2026-03-31", "open": 8.0, "high": 8.0, "low": 7.9, "close": 8.0},
                    {"date": "2026-04-01", "open": 8.1, "high": 8.3, "low": 7.9, "close": 7.95},
                    {"date": "2026-04-02", "open": 7.9, "high": 8.0, "low": 7.7, "close": 7.8},
                ]
            ).assign(date=lambda frame: pd.to_datetime(frame["date"]).dt.normalize()).set_index("date")
        raise AssertionError(f"Unexpected ticker: {ticker}")

    monkeypatch.setattr("scripts.analyze_catalyst_theme_frontier.get_price_data", fake_get_price_data)

    analysis = analyze_catalyst_theme_frontier(
        report_dir,
        candidate_score_min_grid=[0.34, 0.32],
        breakout_min_grid=[0.10],
        close_min_grid=[0.20],
        sector_min_grid=[0.25, 0.22],
        catalyst_min_grid=[0.45],
        max_candidates_per_trade_date=8,
    )

    assert analysis["overall_outcome_summary"]["ok_count"] == 2
    assert analysis["overall_outcome_summary"]["next_high_hit_rate_at_threshold"] == 1.0
    assert analysis["overall_outcome_summary"]["second_close_positive_rate"] == 0.5
    assert analysis["recommended_variant"]["promoted_outcome_summary"]["ok_count"] == 1
    assert analysis["recommended_variant"]["promoted_outcome_summary"]["second_close_positive_rate"] == 0.0

    markdown = render_catalyst_theme_frontier_markdown(analysis)
    assert "## Realized Outcomes" in markdown
    assert "second_close_positive_rate" in markdown


def test_analyze_catalyst_theme_frontier_surfaces_multi_metric_shadow_blockers_when_no_variant_promotes(tmp_path: Path, monkeypatch) -> None:
    report_dir = tmp_path / "paper_trading_20260409_20260409_live_m2_7_short_trade_only"
    _write_json(
        report_dir / "selection_artifacts" / "2026-04-09" / "selection_snapshot.json",
        {
            "trade_date": "20260409",
            "catalyst_theme_candidates": [],
            "catalyst_theme_shadow_candidates": [
                {
                    "ticker": "603778",
                    "decision": "catalyst_theme_shadow",
                    "score_target": 0.3041,
                    "candidate_source": "catalyst_theme_shadow",
                    "filter_reason": "catalyst_freshness_below_catalyst_theme_floor",
                    "threshold_shortfalls": {"candidate_score": 0.0359, "sector_resonance": 0.1219, "catalyst_freshness": 0.3333},
                    "failed_threshold_count": 3,
                    "total_shortfall": 0.4911,
                    "gate_status": {"data": "pass"},
                    "metrics": {
                        "breakout_freshness": 0.4469,
                        "trend_acceleration": 0.18,
                        "close_strength": 0.8,
                        "sector_resonance": 0.1281,
                        "catalyst_freshness": 0.1167,
                    },
                },
                {
                    "ticker": "300394",
                    "decision": "catalyst_theme_shadow",
                    "score_target": 0.2966,
                    "candidate_source": "catalyst_theme_shadow",
                    "filter_reason": "catalyst_freshness_below_catalyst_theme_floor",
                    "threshold_shortfalls": {"candidate_score": 0.0434, "sector_resonance": 0.1214, "catalyst_freshness": 0.3545},
                    "failed_threshold_count": 3,
                    "total_shortfall": 0.5193,
                    "gate_status": {"data": "pass"},
                    "metrics": {
                        "breakout_freshness": 0.4477,
                        "trend_acceleration": 0.19,
                        "close_strength": 0.9411,
                        "sector_resonance": 0.1286,
                        "catalyst_freshness": 0.0955,
                    },
                },
            ],
        },
    )

    monkeypatch.setattr("scripts.analyze_catalyst_theme_frontier.get_price_data", lambda *args, **kwargs: pd.DataFrame())

    analysis = analyze_catalyst_theme_frontier(report_dir)

    assert analysis["recommended_variant"]["promoted_shadow_count"] == 0
    assert analysis["shadow_threshold_blocker_summary"]["multi_metric_row_count"] == 2
    assert analysis["shadow_threshold_blocker_summary"]["threshold_metric_counts"] == {
        "candidate_score": 2,
        "sector_resonance": 2,
        "catalyst_freshness": 2,
    }
    assert "多重弱结构共振" in analysis["recommendation"]
    assert "catalyst-theme 默认阈值" in analysis["recommendation"]

    markdown = render_catalyst_theme_frontier_markdown(analysis)
    assert "shadow_threshold_blocker_summary" in markdown
