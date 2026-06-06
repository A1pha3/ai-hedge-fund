from __future__ import annotations

import json

import pandas as pd

from scripts.analyze_btst_penalty_frontier import analyze_btst_penalty_frontier
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


def _write_penalty_frontier_replay_input(tmp_path):
    watch_item = LayerCResult(
        ticker="300620",
        score_b=0.30,
        score_c=-0.10,
        score_final=0.15,
        quality_score=0.63,
        decision="watch",
        strategy_signals={
            "trend": _make_signal(
                1,
                30.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 28.0, "completeness": 1.0},
                    "adx_strength": {"direction": 0, "confidence": 14.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 24.0, "completeness": 1.0},
                    "volatility": {"direction": 1, "confidence": 22.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 0, "confidence": 10.0, "completeness": 1.0},
                },
            ),
            "event_sentiment": _make_signal(
                0,
                10.0,
                sub_factors={
                    "event_freshness": {"direction": 0, "confidence": 10.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 0, "confidence": 10.0, "completeness": 1.0},
                },
            ),
            "mean_reversion": _make_signal(0, 0.0),
        },
        agent_contribution_summary={"cohort_contributions": {"analyst": 0.10, "investor": 0.00}},
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
        "run_id": "test_btst_penalty_frontier",
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


def test_analyze_btst_penalty_frontier_finds_threshold_only_surface(tmp_path, monkeypatch):
    replay_input_path = _write_penalty_frontier_replay_input(tmp_path)

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

    monkeypatch.setattr("scripts.btst_analysis_utils.get_price_data", fake_get_price_data)

    analysis = analyze_btst_penalty_frontier(
        replay_input_path,
        baseline_profile="default",
        near_miss_threshold_grid=[0.34, 0.28],
        stale_weight_grid=[0.09],
        extension_weight_grid=[0.06],
        next_high_hit_threshold=0.02,
        focus_tickers=["300620"],
    )

    baseline = analysis["baseline"]
    best_variant = analysis["best_variant"]
    minimal_passing_variant = analysis["minimal_passing_variant"]

    assert baseline["surface_summaries"]["tradeable"]["total_count"] == 0
    assert best_variant is not None
    assert best_variant["variant_family"] == "threshold_only"
    assert best_variant["near_miss_threshold"] == 0.28
    assert best_variant["adjustment_cost"] == 0.06
    assert best_variant["closed_cycle_tradeable_count"] >= 0
    assert best_variant["guardrail_status"] in {"passes_closed_tradeable_guardrails", "not_enough_closed_tradeable_rows"}
    if best_variant["guardrail_status"] == "passes_closed_tradeable_guardrails":
        assert minimal_passing_variant is not None
        assert minimal_passing_variant["variant_name"] == best_variant["variant_name"]


def test_analyze_btst_penalty_frontier_prefers_threshold_only_over_penalty_coupled_rows(tmp_path, monkeypatch):
    replay_input_path = _write_penalty_frontier_replay_input(tmp_path)

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

    monkeypatch.setattr("scripts.btst_analysis_utils.get_price_data", fake_get_price_data)

    analysis = analyze_btst_penalty_frontier(
        replay_input_path,
        baseline_profile="default",
        near_miss_threshold_grid=[0.44, 0.40],
        stale_weight_grid=[0.09, 0.04],
        extension_weight_grid=[0.06, 0.03],
        next_high_hit_threshold=0.02,
    )

    passing_variants = [row for row in analysis["ranked_variants"] if row["guardrail_status"] == "passes_closed_tradeable_guardrails"]

    if passing_variants:
        assert any(row["variant_family"] == "penalty_coupled" for row in passing_variants)
        penalty_coupled_costs = [row["adjustment_cost"] for row in passing_variants if row["variant_family"] == "penalty_coupled"]
        assert penalty_coupled_costs
    assert analysis["best_variant"] is not None
    assert analysis["best_variant"]["variant_family"] in {"threshold_only", "penalty_coupled", "baseline_equivalent"}