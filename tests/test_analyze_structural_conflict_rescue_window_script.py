from __future__ import annotations

import json

from scripts.analyze_structural_conflict_rescue_window import analyze_structural_conflict_rescue_window


def _write_case(day_dir, *, trade_date: str, ticker: str, candidate_source: str, watchlist_entry: dict, score_target: float) -> None:
    (day_dir / "selection_target_replay_input.json").write_text(
        json.dumps(
            {
                "trade_date": trade_date,
                "buy_order_tickers": [ticker],
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
                "trade_date": trade_date,
                "selection_targets": {
                    ticker: {
                        "candidate_source": candidate_source,
                        "short_trade": {
                            "decision": "blocked",
                            "score_target": score_target,
                            "blockers": ["layer_c_bearish_conflict"],
                        },
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def test_analyze_structural_conflict_rescue_window_ranks_rescuable_cases(tmp_path):
    report_dir = tmp_path / "report"
    day1 = report_dir / "selection_artifacts" / "2026-03-25"
    day2 = report_dir / "selection_artifacts" / "2026-03-26"
    day1.mkdir(parents=True)
    day2.mkdir(parents=True)

    strong_entry = {
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
            "mean_reversion": {"direction": 0, "confidence": 49.0, "completeness": 1.0, "sub_factors": {}},
        },
        "agent_contribution_summary": {"cohort_contributions": {"investor": 0.0218, "analyst": -0.0096, "other": 0.0}},
    }
    weak_entry = {
        "ticker": "300111",
        "score_b": 0.28,
        "score_c": -0.05,
        "score_final": 0.10,
        "quality_score": 0.40,
        "decision": "watch",
        "bc_conflict": "b_strong_buy_c_negative",
        "candidate_source": "watchlist_filter_diagnostics",
        "strategy_signals": {
            "trend": {
                "direction": 1,
                "confidence": 36.0,
                "completeness": 1.0,
                "sub_factors": {
                    "momentum": {"direction": 1, "confidence": 28.0, "completeness": 1.0},
                    "adx_strength": {"direction": 0, "confidence": 20.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 0, "confidence": 18.0, "completeness": 1.0},
                    "volatility": {"direction": 0, "confidence": 22.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 1, "confidence": 78.0, "completeness": 1.0},
                },
            },
            "event_sentiment": {
                "direction": 0,
                "confidence": 18.0,
                "completeness": 1.0,
                "sub_factors": {
                    "event_freshness": {"direction": 0, "confidence": 15.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 0, "confidence": 12.0, "completeness": 1.0},
                },
            },
            "mean_reversion": {"direction": 1, "confidence": 72.0, "completeness": 1.0, "sub_factors": {}},
        },
        "agent_contribution_summary": {"cohort_contributions": {"investor": -0.10, "analyst": -0.14, "other": 0.0}},
    }

    _write_case(day1, trade_date="2026-03-25", ticker="300724", candidate_source="layer_c_watchlist", watchlist_entry=strong_entry, score_target=0.3785)
    _write_case(day2, trade_date="2026-03-26", ticker="300111", candidate_source="watchlist_filter_diagnostics", watchlist_entry=weak_entry, score_target=0.05)

    analysis = analyze_structural_conflict_rescue_window(
        report_dir,
        stale_score_penalty_grid=[0.12, 0.02],
        extension_score_penalty_grid=[0.08, 0.02],
        select_threshold_grid=[0.58, 0.54],
        near_miss_threshold_grid=[0.46, 0.42],
    )

    assert analysis["blocked_case_count"] == 2
    assert analysis["near_miss_rescuable_count"] == 1
    assert analysis["selected_rescuable_count"] == 1
    assert analysis["priority_queue"][0]["ticker"] == "300724"
    assert analysis["priority_queue"][0]["minimal_near_miss_adjustment_cost"] is not None
    assert analysis["priority_queue"][0]["minimal_near_miss_adjustment_cost"] >= 0.0
    assert analysis["unrescued_cases"][0]["ticker"] == "300111"


def test_analyze_structural_conflict_rescue_window_can_filter_trade_dates(tmp_path):
    report_dir = tmp_path / "report"
    day1 = report_dir / "selection_artifacts" / "2026-03-25"
    day2 = report_dir / "selection_artifacts" / "2026-03-26"
    day1.mkdir(parents=True)
    day2.mkdir(parents=True)

    entry = {
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
            "mean_reversion": {"direction": 0, "confidence": 49.0, "completeness": 1.0, "sub_factors": {}},
        },
        "agent_contribution_summary": {"cohort_contributions": {"investor": 0.0218, "analyst": -0.0096, "other": 0.0}},
    }
    _write_case(day1, trade_date="2026-03-25", ticker="300724", candidate_source="layer_c_watchlist", watchlist_entry=entry, score_target=0.3785)
    _write_case(day2, trade_date="2026-03-26", ticker="300724", candidate_source="layer_c_watchlist", watchlist_entry=entry, score_target=0.3785)

    analysis = analyze_structural_conflict_rescue_window(
        report_dir,
        trade_dates={"2026-03-26"},
        stale_score_penalty_grid=[0.12],
        extension_score_penalty_grid=[0.08],
        select_threshold_grid=[0.58],
        near_miss_threshold_grid=[0.46, 0.42],
    )

    assert analysis["trade_dates_filter"] == ["2026-03-26"]
    assert analysis["blocked_case_count"] == 1
    assert analysis["priority_queue"][0]["trade_date"] == "2026-03-26"