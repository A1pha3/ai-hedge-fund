from __future__ import annotations

import json

import pandas as pd

from scripts.analyze_short_trade_boundary_coverage_variants import analyze_short_trade_boundary_coverage_variants


def test_analyze_short_trade_boundary_coverage_variants_recommends_relaxed_variant(tmp_path, monkeypatch):
    report_dir = tmp_path / "report"
    day1 = report_dir / "selection_artifacts" / "2026-03-25"
    day1.mkdir(parents=True)
    (day1 / "selection_target_replay_input.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-25",
                "supplemental_short_trade_entries": [
                    {
                        "ticker": "300001",
                        "candidate_source": "layer_b_boundary",
                        "short_trade_boundary_metrics": {
                            "candidate_score": 0.30,
                            "breakout_freshness": 0.24,
                            "trend_acceleration": 0.30,
                            "volume_expansion_quality": 0.18,
                            "catalyst_freshness": 0.14,
                            "close_strength": 0.30,
                        },
                    },
                    {
                        "ticker": "300002",
                        "candidate_source": "layer_b_boundary",
                        "short_trade_boundary_metrics": {
                            "candidate_score": 0.26,
                            "breakout_freshness": 0.22,
                            "trend_acceleration": 0.24,
                            "volume_expansion_quality": 0.13,
                            "catalyst_freshness": 0.12,
                            "close_strength": 0.27,
                        },
                    },
                    {
                        "ticker": "300003",
                        "candidate_source": "layer_b_boundary",
                        "short_trade_boundary_metrics": {
                            "candidate_score": 0.18,
                            "breakout_freshness": 0.12,
                            "trend_acceleration": 0.18,
                            "volume_expansion_quality": 0.10,
                            "catalyst_freshness": 0.06,
                            "close_strength": 0.21,
                        },
                    },
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    def fake_get_price_data(ticker: str, start_date: str, end_date: str):
        frames = {
            "300001": pd.DataFrame(
                [
                    {"date": "2026-03-25", "open": 10.0, "high": 10.1, "low": 9.8, "close": 10.0, "volume": 1000},
                    {"date": "2026-03-26", "open": 10.2, "high": 10.7, "low": 10.0, "close": 10.4, "volume": 1100},
                ]
            ),
            "300002": pd.DataFrame(
                [
                    {"date": "2026-03-25", "open": 8.0, "high": 8.1, "low": 7.9, "close": 8.0, "volume": 900},
                    {"date": "2026-03-26", "open": 8.05, "high": 8.35, "low": 7.95, "close": 8.2, "volume": 980},
                ]
            ),
            "300003": pd.DataFrame(
                [
                    {"date": "2026-03-25", "open": 6.0, "high": 6.1, "low": 5.9, "close": 6.0, "volume": 800},
                    {"date": "2026-03-26", "open": 5.9, "high": 6.0, "low": 5.7, "close": 5.8, "volume": 780},
                ]
            ),
        }
        frame = frames[ticker].assign(date=lambda current: pd.to_datetime(current["date"]).dt.normalize()).set_index("date")
        return frame

    monkeypatch.setattr("scripts.short_trade_boundary_analysis_utils.get_price_data", fake_get_price_data)

    analysis = analyze_short_trade_boundary_coverage_variants(
        report_dir,
        candidate_sources={"layer_b_boundary"},
        candidate_score_min_grid=[0.24],
        breakout_min_grid=[0.18],
        trend_min_grid=[0.22],
        volume_min_grid=[0.15, 0.12],
        catalyst_min_grid=[0.12],
    )

    assert analysis["candidate_pool_count"] == 3
    assert analysis["baseline_variant"]["selected_candidate_count"] == 1
    assert analysis["recommended_variant"]["selected_candidate_count"] == 2
    assert analysis["recommended_variant"]["thresholds"]["volume_expansion_quality_min"] == 0.12
    assert analysis["recommended_variant"]["next_close_positive_rate"] == 1.0
