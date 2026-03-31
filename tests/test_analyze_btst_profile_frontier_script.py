from __future__ import annotations

import json

import pandas as pd

from scripts.analyze_btst_profile_frontier import analyze_btst_profile_frontier
from src.execution.models import LayerCResult
from src.screening.models import StrategySignal
from src.targets.router import build_selection_targets


def _make_signal(direction: int, confidence: float, completeness: float = 1.0, sub_factors: dict | None = None) -> StrategySignal:
    return StrategySignal(
        direction=direction,
        confidence=confidence,
        completeness=completeness,
        sub_factors=sub_factors or {},
    )


def _write_profile_replay_input(tmp_path):
    watch_item = LayerCResult(
        ticker="300620",
        score_b=0.60,
        score_c=0.60,
        score_final=0.40,
        quality_score=0.63,
        decision="watch",
        strategy_signals={
            "trend": _make_signal(
                1,
                60.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 28.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 34.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 44.0, "completeness": 1.0},
                    "volatility": {"direction": 1, "confidence": 42.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 0, "confidence": 10.0, "completeness": 1.0},
                },
            ),
            "event_sentiment": _make_signal(
                1,
                60.0,
                sub_factors={
                    "event_freshness": {"direction": 1, "confidence": 30.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 1, "confidence": 80.0, "completeness": 1.0},
                },
            ),
            "mean_reversion": _make_signal(0, 0.0),
        },
        agent_contribution_summary={"cohort_contributions": {"analyst": 0.40, "investor": 0.20}},
    )
    selection_targets, summary = build_selection_targets(
        trade_date="20260322",
        watchlist=[watch_item],
        rejected_entries=[],
        supplemental_short_trade_entries=[],
        buy_order_tickers=set(),
        target_mode="dual_target",
    )
    replay_input = {
        "artifact_version": "v1",
        "run_id": "test_btst_profile_frontier",
        "trade_date": "2026-03-22",
        "market": "CN",
        "target_mode": "dual_target",
        "pipeline_config_snapshot": {},
        "source_summary": {
            "watchlist_count": 1,
            "rejected_entry_count": 0,
            "supplemental_short_trade_entry_count": 0,
            "buy_order_ticker_count": 0,
        },
        "watchlist": [watch_item.model_dump(mode="json")],
        "rejected_entries": [],
        "supplemental_short_trade_entries": [],
        "buy_order_tickers": [],
        "selection_targets": {ticker: evaluation.model_dump(mode="json") for ticker, evaluation in selection_targets.items()},
        "target_summary": summary.model_dump(mode="json"),
    }
    replay_input_path = tmp_path / "selection_target_replay_input.json"
    replay_input_path.write_text(json.dumps(replay_input, ensure_ascii=False, indent=2), encoding="utf-8")
    return replay_input_path


def _make_profitability_hard_cliff_signal() -> StrategySignal:
    return _make_signal(
        -1,
        68.0,
        sub_factors={
            "profitability": {
                "direction": -1,
                "confidence": 72.0,
                "completeness": 1.0,
                "metrics": {"positive_count": 0},
            },
            "financial_health": {"direction": 0, "confidence": 34.0, "completeness": 1.0},
            "growth": {"direction": 1, "confidence": 48.0, "completeness": 1.0},
        },
    )


def _write_profitability_relief_replay_input(tmp_path):
    report_dir = tmp_path / "profitability_relief"
    report_dir.mkdir()
    rejected_entry = {
        "ticker": "300987",
        "score_b": 0.30,
        "score_c": 0.05,
        "score_final": 0.18,
        "quality_score": 0.60,
        "decision": "avoid",
        "reason": "decision_avoid",
        "reasons": ["decision_avoid"],
        "strategy_signals": {
            "trend": _make_signal(
                1,
                55.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 55.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 52.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 52.0, "completeness": 1.0},
                    "volatility": {"direction": 1, "confidence": 45.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 1, "confidence": 8.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "event_sentiment": _make_signal(
                1,
                52.0,
                sub_factors={
                    "event_freshness": {"direction": 1, "confidence": 50.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 1, "confidence": 52.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "mean_reversion": _make_signal(0, 0.0).model_dump(mode="json"),
            "fundamental": _make_profitability_hard_cliff_signal().model_dump(mode="json"),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.48, "investor": 0.28}},
    }
    selection_targets, summary = build_selection_targets(
        trade_date="20260322",
        watchlist=[],
        rejected_entries=[rejected_entry],
        supplemental_short_trade_entries=[],
        buy_order_tickers=set(),
        target_mode="dual_target",
    )
    replay_input = {
        "artifact_version": "v1",
        "run_id": "test_btst_profitability_relief_frontier",
        "trade_date": "2026-03-22",
        "market": "CN",
        "target_mode": "dual_target",
        "pipeline_config_snapshot": {},
        "source_summary": {
            "watchlist_count": 0,
            "rejected_entry_count": 1,
            "supplemental_short_trade_entry_count": 0,
            "buy_order_ticker_count": 0,
        },
        "watchlist": [],
        "rejected_entries": [rejected_entry],
        "supplemental_short_trade_entries": [],
        "buy_order_tickers": [],
        "selection_targets": {ticker: evaluation.model_dump(mode="json") for ticker, evaluation in selection_targets.items()},
        "target_summary": summary.model_dump(mode="json"),
    }
    replay_input_path = report_dir / "selection_target_replay_input.json"
    replay_input_path.write_text(json.dumps(replay_input, ensure_ascii=False, indent=2), encoding="utf-8")
    return replay_input_path


def test_analyze_btst_profile_frontier_finds_staged_breakout_surface(tmp_path, monkeypatch):
    replay_input_path = _write_profile_replay_input(tmp_path)

    def fake_get_price_data(ticker: str, start_date: str, end_date: str):
        assert ticker == "300620"
        assert start_date == "2026-03-22"
        return pd.DataFrame(
            [
                {"date": "2026-03-22", "open": 10.0, "high": 10.1, "low": 9.9, "close": 10.0},
                {"date": "2026-03-23", "open": 10.1, "high": 10.4, "low": 10.0, "close": 10.2},
                {"date": "2026-03-24", "open": 10.2, "high": 10.5, "low": 10.1, "close": 10.3},
            ]
        ).assign(date=lambda data: pd.to_datetime(data["date"]).dt.normalize()).set_index("date")

    monkeypatch.setattr("scripts.analyze_btst_micro_window_regression.get_price_data", fake_get_price_data)

    analysis = analyze_btst_profile_frontier(
        replay_input_path,
        baseline_profile="default",
        variant_profiles=["staged_breakout"],
        next_high_hit_threshold=0.02,
    )

    baseline = analysis["baseline"]
    variant = analysis["variants"][0]
    comparison = analysis["comparisons"][0]

    assert baseline["profile_name"] == "default"
    assert baseline["surface_summaries"]["tradeable"]["total_count"] == 0
    assert baseline["false_negative_proxy_summary"]["count"] == 1
    assert variant["profile_name"] == "staged_breakout"
    assert variant["surface_summaries"]["tradeable"]["total_count"] == 1
    assert variant["surface_summaries"]["tradeable"]["closed_cycle_count"] == 1
    assert variant["top_tradeable_rows"][0]["decision"] == "near_miss"
    assert comparison["guardrail_status"] == "passes_closed_tradeable_guardrails"
    assert "从 0 提升到 1" in comparison["comparison_note"]
    assert analysis["best_variant"]["profile_name"] == "staged_breakout"


def test_analyze_btst_profile_frontier_finds_profitability_relief_surface(tmp_path, monkeypatch):
    replay_input_path = _write_profitability_relief_replay_input(tmp_path)

    def fake_get_price_data(ticker: str, start_date: str, end_date: str):
        assert ticker == "300987"
        assert start_date == "2026-03-22"
        return pd.DataFrame(
            [
                {"date": "2026-03-22", "open": 10.0, "high": 10.1, "low": 9.9, "close": 10.0},
                {"date": "2026-03-23", "open": 10.0, "high": 10.4, "low": 9.95, "close": 10.2},
                {"date": "2026-03-24", "open": 10.2, "high": 10.3, "low": 10.05, "close": 10.18},
            ]
        ).assign(date=lambda data: pd.to_datetime(data["date"]).dt.normalize()).set_index("date")

    monkeypatch.setattr("scripts.analyze_btst_micro_window_regression.get_price_data", fake_get_price_data)

    analysis = analyze_btst_profile_frontier(
        replay_input_path,
        baseline_profile="default",
        variant_profiles=["staged_breakout_profitability_relief"],
        next_high_hit_threshold=0.02,
    )

    baseline = analysis["baseline"]
    variant = analysis["variants"][0]
    comparison = analysis["comparisons"][0]

    assert baseline["profile_name"] == "default"
    assert baseline["surface_summaries"]["tradeable"]["total_count"] == 0
    assert variant["profile_name"] == "staged_breakout_profitability_relief"
    assert variant["surface_summaries"]["tradeable"]["total_count"] == 1
    assert variant["top_tradeable_rows"][0]["decision"] == "near_miss"
    assert comparison["guardrail_status"] == "passes_closed_tradeable_guardrails"
    assert "从 0 提升到 1" in comparison["comparison_note"]
    assert analysis["best_variant"]["profile_name"] == "staged_breakout_profitability_relief"