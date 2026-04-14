from __future__ import annotations

import json

import pandas as pd

from scripts.analyze_short_trade_boundary_filtered_candidates import analyze_short_trade_boundary_filtered_candidates


def test_analyze_short_trade_boundary_filtered_candidates_ranks_closest_rows(tmp_path, monkeypatch):
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
                            "candidate_score": 0.22,
                            "breakout_freshness": 0.17,
                            "trend_acceleration": 0.24,
                            "volume_expansion_quality": 0.14,
                            "catalyst_freshness": 0.12,
                            "close_strength": 0.24,
                        },
                    },
                    {
                        "ticker": "300003",
                        "candidate_source": "layer_b_boundary",
                        "short_trade_boundary_metrics": {
                            "candidate_score": 0.20,
                            "breakout_freshness": 0.10,
                            "trend_acceleration": 0.18,
                            "volume_expansion_quality": 0.09,
                            "catalyst_freshness": 0.08,
                            "close_strength": 0.20,
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
                    {"date": "2026-03-26", "open": 8.05, "high": 8.4, "low": 8.0, "close": 8.22, "volume": 980},
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

    analysis = analyze_short_trade_boundary_filtered_candidates(report_dir, candidate_sources={"layer_b_boundary"}, top_n=2)

    assert analysis["total_candidate_count"] == 3
    assert analysis["qualified_candidate_count"] == 2
    assert analysis["filtered_candidate_count"] == 1
    assert analysis["closest_to_pass_rows"][0]["ticker"] == "300003"
    assert analysis["closest_to_pass_rows"][0]["primary_reason"] == "breakout_freshness_below_short_trade_boundary_floor"