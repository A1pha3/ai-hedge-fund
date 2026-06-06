from __future__ import annotations

import json

from scripts.analyze_targeted_structural_conflict_release import analyze_targeted_structural_conflict_release


def _write_case(day_dir, *, trade_date: str, ticker: str, candidate_source: str, entry: dict, score_target: float, blockers: list[str] | None = None) -> None:
    (day_dir / "selection_target_replay_input.json").write_text(
        json.dumps(
            {
                "trade_date": trade_date,
                "buy_order_tickers": [ticker],
                "watchlist": [entry],
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
                            "blockers": blockers or ["layer_c_bearish_conflict"],
                        },
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _build_entry(ticker: str, *, strong: bool) -> dict:
    if strong:
        trend_confidence = 86.0
        event_confidence = 76.0
        momentum_confidence = 90.0
        adx_confidence = 82.0
        ema_confidence = 84.0
        volatility_confidence = 72.0
        long_trend_confidence = 70.0
        event_freshness = 74.0
        news_sentiment = 68.0
        investor_contribution = 0.0218
        analyst_contribution = -0.0096
        score_b = 0.5406
        score_c = 0.0122
        score_final = 0.3028
        quality_score = 0.81
    else:
        trend_confidence = 38.0
        event_confidence = 20.0
        momentum_confidence = 30.0
        adx_confidence = 24.0
        ema_confidence = 26.0
        volatility_confidence = 20.0
        long_trend_confidence = 76.0
        event_freshness = 16.0
        news_sentiment = 14.0
        investor_contribution = -0.08
        analyst_contribution = -0.12
        score_b = 0.31
        score_c = -0.05
        score_final = 0.11
        quality_score = 0.42
    return {
        "ticker": ticker,
        "score_b": score_b,
        "score_c": score_c,
        "score_final": score_final,
        "quality_score": quality_score,
        "decision": "watch",
        "bc_conflict": "b_strong_buy_c_negative",
        "candidate_source": "layer_c_watchlist",
        "strategy_signals": {
            "trend": {
                "direction": 1,
                "confidence": trend_confidence,
                "completeness": 1.0,
                "sub_factors": {
                    "momentum": {"direction": 1, "confidence": momentum_confidence, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": adx_confidence, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": ema_confidence, "completeness": 1.0},
                    "volatility": {"direction": 1, "confidence": volatility_confidence, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 1, "confidence": long_trend_confidence, "completeness": 1.0},
                },
            },
            "event_sentiment": {
                "direction": 1,
                "confidence": event_confidence,
                "completeness": 1.0,
                "sub_factors": {
                    "event_freshness": {"direction": 1, "confidence": event_freshness, "completeness": 1.0},
                    "news_sentiment": {"direction": 1, "confidence": news_sentiment, "completeness": 1.0},
                },
            },
            "mean_reversion": {"direction": 0, "confidence": 49.0, "completeness": 1.0, "sub_factors": {}},
        },
        "agent_contribution_summary": {"cohort_contributions": {"investor": investor_contribution, "analyst": analyst_contribution, "other": 0.0}},
    }


def test_targeted_structural_conflict_release_only_changes_target_case(tmp_path):
    report_dir = tmp_path / "report"
    day1 = report_dir / "selection_artifacts" / "2026-03-25"
    day2 = report_dir / "selection_artifacts" / "2026-03-26"
    day1.mkdir(parents=True)
    day2.mkdir(parents=True)

    _write_case(
        day1,
        trade_date="2026-03-25",
        ticker="300724",
        candidate_source="layer_c_watchlist",
        entry=_build_entry("300724", strong=True),
        score_target=0.3785,
    )
    _write_case(
        day2,
        trade_date="2026-03-26",
        ticker="300111",
        candidate_source="layer_c_watchlist",
        entry=_build_entry("300111", strong=False),
        score_target=0.05,
    )

    analysis = analyze_targeted_structural_conflict_release(
        report_dir,
        targets={("2026-03-25", "300724")},
        profile_overrides={
            "hard_block_bearish_conflicts": [],
            "overhead_conflict_penalty_conflicts": [],
            "near_miss_threshold": 0.42,
        },
    )

    assert analysis["matched_target_case_count"] == 1
    assert analysis["changed_case_count"] == 1
    assert analysis["before_decision_counts"]["blocked"] == 2
    assert analysis["after_decision_counts"]["blocked"] == 1
    promoted_count = analysis["after_decision_counts"].get("near_miss", 0) + analysis["after_decision_counts"].get("selected", 0)
    assert promoted_count == 1
    transition_count = analysis["decision_transition_counts"].get("blocked->near_miss", 0) + analysis["decision_transition_counts"].get("blocked->selected", 0)
    assert transition_count == 1
    assert analysis["changed_cases"][0]["ticker"] == "300724"
    assert analysis["changed_cases"][0]["after_decision"] in {"near_miss", "selected"}
    assert analysis["non_target_changed_cases"] == []


def test_targeted_structural_conflict_release_requires_existing_target(tmp_path):
    report_dir = tmp_path / "report"
    day1 = report_dir / "selection_artifacts" / "2026-03-25"
    day1.mkdir(parents=True)

    _write_case(
        day1,
        trade_date="2026-03-25",
        ticker="300724",
        candidate_source="layer_c_watchlist",
        entry=_build_entry("300724", strong=True),
        score_target=0.3785,
    )

    try:
        analyze_targeted_structural_conflict_release(
            report_dir,
            targets={("2026-03-25", "999999")},
            profile_overrides={"hard_block_bearish_conflicts": []},
        )
    except ValueError as exc:
        assert "Targets not found" in str(exc)
    else:
        raise AssertionError("Expected ValueError for missing target case")