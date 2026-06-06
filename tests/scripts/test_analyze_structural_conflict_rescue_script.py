from __future__ import annotations

import json

from scripts.analyze_structural_conflict_rescue import analyze_structural_conflict_rescue


def test_analyze_structural_conflict_rescue_reports_variant_lift_for_watchlist_case(tmp_path):
    report_dir = tmp_path / "report"
    day_dir = report_dir / "selection_artifacts" / "2026-03-25"
    day_dir.mkdir(parents=True)

    (day_dir / "selection_target_replay_input.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-25",
                "buy_order_tickers": ["300724"],
                "watchlist": [
                    {
                        "ticker": "300724",
                        "score_b": 0.5406,
                        "score_c": 0.0122,
                        "score_final": 0.3028,
                        "quality_score": 0.81,
                        "decision": "watch",
                        "bc_conflict": "b_strong_buy_c_negative",
                        "candidate_source": "layer_c_watchlist",
                        "strategy_signals": {
                            "trend": {
                                "direction": 1,
                                "confidence": 86.0,
                                "completeness": 1.0,
                                "sub_factors": {
                                    "momentum": {"direction": 1, "confidence": 90.0, "completeness": 1.0},
                                    "adx_strength": {"direction": 1, "confidence": 82.0, "completeness": 1.0},
                                    "ema_alignment": {"direction": 1, "confidence": 84.0, "completeness": 1.0},
                                    "volatility": {"direction": 1, "confidence": 72.0, "completeness": 1.0},
                                    "long_trend_alignment": {"direction": 1, "confidence": 70.0, "completeness": 1.0},
                                },
                            },
                            "event_sentiment": {
                                "direction": 1,
                                "confidence": 76.0,
                                "completeness": 1.0,
                                "sub_factors": {
                                    "event_freshness": {"direction": 1, "confidence": 74.0, "completeness": 1.0},
                                    "news_sentiment": {"direction": 1, "confidence": 68.0, "completeness": 1.0},
                                },
                            },
                            "mean_reversion": {
                                "direction": 0,
                                "confidence": 49.0,
                                "completeness": 1.0,
                                "sub_factors": {},
                            },
                        },
                        "agent_contribution_summary": {"cohort_contributions": {"investor": 0.0218, "analyst": -0.0096, "other": 0.0}},
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (day_dir / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-25",
                "selection_targets": {
                    "300724": {
                        "short_trade": {
                            "decision": "blocked",
                        }
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_structural_conflict_rescue(report_dir, "2026-03-25", "300724")

    assert analysis["source_bucket"] == "watchlist"
    assert analysis["candidate_source"] == "layer_c_watchlist"
    assert analysis["stored_short_trade_decision"] in {"blocked", "selected", "near_miss"}
    assert analysis["variant_results"][0]["variant"] == "baseline"
    assert analysis["variant_results"][0]["decision"] in {"blocked", "selected", "near_miss"}
    assert analysis["variant_results"][1]["variant"] == "remove_conflict_hard_block_keep_penalty"
    assert analysis["variant_results"][1]["decision"] in {"rejected", "near_miss", "selected"}
    assert analysis["variant_results"][1]["score_target"] >= analysis["variant_results"][0]["score_target"]
    assert "最佳释放路径" in analysis["recommendation"]


def test_analyze_structural_conflict_rescue_can_surface_penalty_threshold_frontier(tmp_path):
    report_dir = tmp_path / "report"
    day_dir = report_dir / "selection_artifacts" / "2026-03-25"
    day_dir.mkdir(parents=True)

    watchlist_entry = {
        "ticker": "300724",
        "score_b": 0.5406,
        "score_c": 0.0122,
        "score_final": 0.3028,
        "quality_score": 0.81,
        "decision": "watch",
        "bc_conflict": "b_strong_buy_c_negative",
        "candidate_source": "layer_c_watchlist",
        "strategy_signals": {
            "trend": {
                "direction": 1,
                "confidence": 86.0,
                "completeness": 1.0,
                "sub_factors": {
                    "momentum": {"direction": 1, "confidence": 90.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 82.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 84.0, "completeness": 1.0},
                    "volatility": {"direction": 1, "confidence": 72.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 1, "confidence": 70.0, "completeness": 1.0},
                },
            },
            "event_sentiment": {
                "direction": 1,
                "confidence": 76.0,
                "completeness": 1.0,
                "sub_factors": {
                    "event_freshness": {"direction": 1, "confidence": 74.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 1, "confidence": 68.0, "completeness": 1.0},
                },
            },
            "mean_reversion": {
                "direction": 0,
                "confidence": 49.0,
                "completeness": 1.0,
                "sub_factors": {},
            },
        },
        "agent_contribution_summary": {"cohort_contributions": {"investor": 0.0218, "analyst": -0.0096, "other": 0.0}},
    }
    (day_dir / "selection_target_replay_input.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-25",
                "buy_order_tickers": ["300724"],
                "watchlist": [watchlist_entry],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (day_dir / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-25",
                "selection_targets": {
                    "300724": {
                        "short_trade": {
                            "decision": "blocked",
                        }
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_structural_conflict_rescue(
        report_dir,
        "2026-03-25",
        "300724",
        stale_score_penalty_grid=[0.09, 0.02],
        extension_score_penalty_grid=[0.06, 0.02],
        select_threshold_grid=[0.56, 0.48],
        near_miss_threshold_grid=[0.50, 0.44],
    )

    frontier = analysis["penalty_threshold_frontier"]
    assert frontier["row_count"] == 12
    assert frontier["best_score_row"] is not None
    assert frontier["best_score_row"]["score_target"] >= analysis["variant_results"][0]["score_target"]
    assert frontier["minimal_near_miss_row"] is not None
    assert frontier["minimal_near_miss_row"]["decision"] in {"near_miss", "selected"}
    assert frontier["minimal_near_miss_row"]["adjustment_cost"] is not None
    assert "最小 near_miss frontier" in analysis["recommendation"]