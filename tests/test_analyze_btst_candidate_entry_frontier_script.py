from __future__ import annotations

import json

import pandas as pd

from scripts.analyze_btst_candidate_entry_frontier import analyze_btst_candidate_entry_frontier
from src.screening.models import StrategySignal
from src.targets.router import build_selection_targets


def _make_signal(direction: int, confidence: float, completeness: float = 1.0, sub_factors: dict | None = None) -> StrategySignal:
    return StrategySignal(
        direction=direction,
        confidence=confidence,
        completeness=completeness,
        sub_factors=sub_factors or {},
    )


def _write_candidate_entry_frontier_replay_input(tmp_path):
    retained_entry = {
        "ticker": "300394",
        "score_b": 0.4199,
        "score_c": -0.0961,
        "score_final": 0.1877,
        "quality_score": 0.975,
        "decision": "avoid",
        "bc_conflict": "b_positive_c_strong_bearish",
        "candidate_source": "watchlist_filter_diagnostics",
        "candidate_reason_codes": ["decision_avoid", "score_final_below_watchlist_threshold"],
        "reason": "decision_avoid",
        "strategy_signals": {
            "trend": _make_signal(
                1,
                100.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 49.24, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    "volatility": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                },
            ),
            "event_sentiment": _make_signal(
                0,
                0.0,
                sub_factors={
                    "event_freshness": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                },
            ),
            "mean_reversion": _make_signal(0, 0.0),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": -0.0305, "investor": -0.0656}},
    }
    weak_entry = {
        "ticker": "300502",
        "score_b": 0.3829,
        "score_c": -0.1194,
        "score_final": 0.1568,
        "quality_score": 0.9375,
        "decision": "avoid",
        "bc_conflict": "b_positive_c_strong_bearish",
        "candidate_source": "watchlist_filter_diagnostics",
        "candidate_reason_codes": ["decision_avoid", "score_final_below_watchlist_threshold"],
        "reason": "decision_avoid",
        "strategy_signals": {
            "trend": _make_signal(
                1,
                70.0,
                sub_factors={
                    "momentum": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 50.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    "volatility": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                },
            ),
            "event_sentiment": _make_signal(
                0,
                0.0,
                sub_factors={
                    "event_freshness": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                },
            ),
            "mean_reversion": _make_signal(0, 0.0),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": -0.0646, "investor": -0.0548}},
    }
    replay_entries = [retained_entry, weak_entry]
    replay_entries_json = [
        {
            **entry,
            "strategy_signals": {name: signal.model_dump(mode="json") for name, signal in entry["strategy_signals"].items()},
        }
        for entry in replay_entries
    ]
    selection_targets, summary = build_selection_targets(
        trade_date="20260322",
        watchlist=[],
        rejected_entries=replay_entries,
        supplemental_short_trade_entries=[],
        buy_order_tickers=set(),
        target_mode="dual_target",
    )
    replay_input = {
        "artifact_version": "v1",
        "run_id": "test_btst_candidate_entry_frontier",
        "trade_date": "2026-03-22",
        "market": "CN",
        "target_mode": "dual_target",
        "pipeline_config_snapshot": {},
        "source_summary": {
            "watchlist_count": 0,
            "rejected_entry_count": 2,
            "supplemental_short_trade_entry_count": 0,
            "buy_order_ticker_count": 0,
        },
        "watchlist": [],
        "rejected_entries": replay_entries_json,
        "supplemental_short_trade_entries": [],
        "buy_order_tickers": [],
        "selection_targets": {ticker: evaluation.model_dump(mode="json") for ticker, evaluation in selection_targets.items()},
        "target_summary": summary.model_dump(mode="json"),
    }
    replay_input_path = tmp_path / "selection_target_replay_input.json"
    replay_input_path.write_text(json.dumps(replay_input, ensure_ascii=False, indent=2), encoding="utf-8")
    return replay_input_path


def test_analyze_btst_candidate_entry_frontier_finds_weak_structure_filter(tmp_path, monkeypatch):
    replay_input_path = _write_candidate_entry_frontier_replay_input(tmp_path)

    def fake_get_price_data(ticker: str, start_date: str, end_date: str):
        assert start_date == "2026-03-22"
        price_rows = {
            "300394": [
                {"date": "2026-03-22", "open": 10.0, "high": 10.1, "low": 9.9, "close": 10.0},
                {"date": "2026-03-23", "open": 10.1, "high": 10.6, "low": 10.0, "close": 10.4},
                {"date": "2026-03-24", "open": 10.4, "high": 10.7, "low": 10.3, "close": 10.5},
            ],
            "300502": [
                {"date": "2026-03-22", "open": 8.0, "high": 8.1, "low": 7.9, "close": 8.0},
                {"date": "2026-03-23", "open": 7.9, "high": 8.0, "low": 7.7, "close": 7.8},
                {"date": "2026-03-24", "open": 7.8, "high": 7.9, "low": 7.5, "close": 7.6},
            ],
        }
        return pd.DataFrame(price_rows[ticker]).assign(date=lambda data: pd.to_datetime(data["date"]).dt.normalize()).set_index("date")

    monkeypatch.setattr("scripts.analyze_btst_micro_window_regression.get_price_data", fake_get_price_data)

    analysis = analyze_btst_candidate_entry_frontier(
        replay_input_path,
        baseline_profile="default",
        variant_names=["weak_structure_triplet", "semantic_pair_300502", "volume_only_20260326"],
        focus_tickers=["300502"],
        preserve_tickers=["300394"],
        next_high_hit_threshold=0.02,
    )

    baseline = analysis["baseline"]
    weak_structure_variant = next(variant for variant in analysis["variants"] if variant["label"] == "weak_structure_triplet")
    weak_structure_comparison = next(comparison for comparison in analysis["comparisons"] if comparison["variant_name"] == "weak_structure_triplet")
    volume_only_comparison = next(comparison for comparison in analysis["comparisons"] if comparison["variant_name"] == "volume_only_20260326")

    assert baseline["filtered_candidate_entry_summary"]["count"] == 0
    assert baseline["false_negative_proxy_summary"]["count"] == 1

    assert weak_structure_variant["filtered_candidate_entry_summary"]["count"] == 1
    assert weak_structure_variant["filtered_candidate_entry_summary"]["matched_filter_counts"] == {"watchlist_avoid_boundary_weak_structure_entry": 1}
    assert weak_structure_variant["top_filtered_candidate_entry_rows"][0]["ticker"] == "300502"
    assert weak_structure_comparison["candidate_entry_status"] == "filters_focus_and_weaker_than_false_negative_pool"
    assert weak_structure_comparison["focus_filtered_tickers"] == ["300502"]
    assert weak_structure_comparison["preserve_filtered_tickers"] == []
    assert weak_structure_comparison["filtered_candidate_entry_surface"]["next_close_positive_rate"] == 0.0

    assert volume_only_comparison["candidate_entry_status"] == "filters_focus_and_weaker_than_false_negative_pool"
    assert volume_only_comparison["focus_filtered_tickers"] == ["300502"]
    assert volume_only_comparison["preserve_filtered_tickers"] == []

    assert analysis["best_variant"]["variant_name"] == "weak_structure_triplet"
