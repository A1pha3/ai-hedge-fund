from __future__ import annotations

import json

from scripts.refresh_selection_artifacts_from_daily_events import refresh_selection_artifacts_for_report
from src.execution.models import ExecutionPlan
from src.screening.models import StrategySignal


def _make_signal(direction: int, confidence: float, completeness: float = 1.0, sub_factors: dict | None = None) -> StrategySignal:
    return StrategySignal(
        direction=direction,
        confidence=confidence,
        completeness=completeness,
        sub_factors=sub_factors or {},
    )


def _make_post_gate_released_shadow_entry() -> dict:
    return {
        "ticker": "300720",
        "score_b": 0.2,
        "score_c": -0.4,
        "score_final": 0.05,
        "quality_score": 0.58,
        "decision": "watch",
        "reason": "post_gate_liquidity_competition_shadow",
        "reasons": [
            "post_gate_liquidity_competition_shadow",
            "candidate_pool_truncated_after_filters",
            "post_gate_liquidity_competition",
            "catalyst_freshness_below_short_trade_boundary_floor",
            "upstream_shadow_release_score_floor_pass",
            "upstream_shadow_release_candidate",
        ],
        "candidate_source": "post_gate_liquidity_competition_shadow",
        "upstream_candidate_source": "candidate_pool_truncated_after_filters",
        "candidate_reason_codes": [
            "post_gate_liquidity_competition_shadow",
            "candidate_pool_truncated_after_filters",
            "post_gate_liquidity_competition",
            "catalyst_freshness_below_short_trade_boundary_floor",
            "upstream_shadow_release_score_floor_pass",
            "upstream_shadow_release_candidate",
        ],
        "candidate_pool_rank": 1131,
        "candidate_pool_lane": "post_gate_liquidity_competition",
        "candidate_pool_avg_amount_share_of_cutoff": 0.3221,
        "candidate_pool_avg_amount_share_of_min_gate": 9.6762,
        "short_trade_boundary_metrics": {
            "breakout_freshness": 0.4,
            "trend_acceleration": 0.8814,
            "volume_expansion_quality": 0.25,
            "catalyst_freshness": 0.0,
            "close_strength": 0.8902,
            "candidate_score": 0.4794,
        },
        "shadow_release_filter_reason": "catalyst_freshness_below_short_trade_boundary_floor",
        "shadow_release_reason": "upstream_shadow_release_score_floor_pass",
        "shadow_release_score_floor": 0.3,
        "shadow_release_candidate_score": 0.4794,
        "promotion_trigger": "受控 upstream shadow release 样本，仅进入 short-trade supplemental replay，默认不直接进入正式买入名单。",
        "strategy_signals": {
            "trend": _make_signal(
                1,
                95.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 88.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 85.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 95.0, "completeness": 1.0},
                    "volatility": {"direction": 1, "confidence": 30.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 1, "confidence": 70.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "event_sentiment": _make_signal(
                1,
                40.0,
                sub_factors={
                    "event_freshness": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "mean_reversion": _make_signal(0, 0.0).model_dump(mode="json"),
            "fundamental": _make_signal(1, 45.0).model_dump(mode="json"),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.0, "investor": 0.0}},
    }


def test_refresh_selection_artifacts_from_daily_events_promotes_post_gate_shadow_entry(tmp_path):
    report_dir = tmp_path / "paper_trading_20260331_20260331_refresh_target"
    (report_dir / "selection_artifacts").mkdir(parents=True)
    trade_date = "20260331"

    plan = ExecutionPlan(
        date=trade_date,
        target_mode="short_trade_only",
        risk_metrics={
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {"tickers": [], "released_shadow_entries": []},
                    "short_trade_candidates": {
                        "tickers": [],
                        "released_shadow_entries": [_make_post_gate_released_shadow_entry()],
                    },
                }
            }
        },
    )
    (report_dir / "daily_events.jsonl").write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": trade_date,
                "current_plan": plan.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = refresh_selection_artifacts_for_report(report_dir, trade_date="2026-03-31")

    assert result["results"][0]["trade_date"] == "2026-03-31"
    replay_input = json.loads((report_dir / "selection_artifacts" / "2026-03-31" / "selection_target_replay_input.json").read_text(encoding="utf-8"))
    supplemental_entry = next(entry for entry in replay_input["supplemental_short_trade_entries"] if entry["ticker"] == "300720")
    assert supplemental_entry["short_trade_catalyst_relief"]["selected_threshold"] == 0.45
    assert supplemental_entry["short_trade_catalyst_relief"]["near_miss_threshold"] == 0.45

    selection_snapshot = json.loads((report_dir / "selection_artifacts" / "2026-03-31" / "selection_snapshot.json").read_text(encoding="utf-8"))
    assert selection_snapshot["short_trade_view"]["selected_symbols"] == ["300720"]
    assert selection_snapshot["selection_targets"]["300720"]["short_trade"]["decision"] == "selected"

    session_summary = json.loads((report_dir / "session_summary.json").read_text(encoding="utf-8"))
    assert session_summary["selection_artifact_refresh"]["refreshed_trade_dates"] == ["2026-03-31"]
