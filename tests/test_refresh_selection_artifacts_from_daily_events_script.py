from __future__ import annotations

import json

import pytest

import scripts.refresh_selection_artifacts_from_daily_events as refresh_module
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


def _make_corridor_released_shadow_entry(*, shadow_visibility_gap_selected: bool) -> dict:
    return {
        "ticker": "300720",
        "score_b": 0.2,
        "score_c": -0.4,
        "score_final": 0.05,
        "quality_score": 0.58,
        "decision": "watch",
        "reason": "upstream_base_liquidity_uplift_shadow",
        "reasons": [
            "upstream_base_liquidity_uplift_shadow",
            "candidate_pool_truncated_after_filters",
            "layer_a_liquidity_corridor",
            "catalyst_freshness_below_short_trade_boundary_floor",
            "upstream_shadow_release_score_floor_pass",
            "upstream_shadow_release_candidate",
        ],
        "candidate_source": "upstream_liquidity_corridor_shadow",
        "upstream_candidate_source": "candidate_pool_truncated_after_filters",
        "candidate_reason_codes": [
            "upstream_base_liquidity_uplift_shadow",
            "candidate_pool_truncated_after_filters",
            "layer_a_liquidity_corridor",
            "catalyst_freshness_below_short_trade_boundary_floor",
            "upstream_shadow_release_score_floor_pass",
            "upstream_shadow_release_candidate",
        ],
        "candidate_pool_rank": 1131,
        "candidate_pool_lane": "layer_a_liquidity_corridor",
        "candidate_pool_shadow_reason": "upstream_base_liquidity_uplift_shadow_visibility_gap_relaxed_band" if shadow_visibility_gap_selected else "upstream_base_liquidity_uplift_shadow",
        "candidate_pool_avg_amount_share_of_cutoff": 0.3221,
        "candidate_pool_avg_amount_share_of_min_gate": 9.6762,
        "shadow_visibility_gap_selected": shadow_visibility_gap_selected,
        "short_trade_boundary_metrics": {
            "breakout_freshness": 0.4,
            "trend_acceleration": 0.8507,
            "volume_expansion_quality": 0.25,
            "catalyst_freshness": 0.0,
            "close_strength": 0.9092,
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


def _make_corridor_shadow_observation_entry() -> dict:
    return {
        "ticker": "301188",
        "decision": "observation",
        "reason": "upstream_base_liquidity_uplift_shadow",
        "candidate_source": "upstream_liquidity_corridor_shadow",
        "upstream_candidate_source": "candidate_pool_truncated_after_filters",
        "candidate_reason_codes": [
            "upstream_base_liquidity_uplift_shadow",
            "candidate_pool_truncated_after_filters",
            "layer_a_liquidity_corridor",
        ],
        "candidate_pool_lane": "layer_a_liquidity_corridor",
        "candidate_pool_shadow_reason": "upstream_base_liquidity_uplift_shadow_focus_relaxed_band",
        "candidate_pool_rank": 3179,
        "candidate_pool_avg_amount_share_of_cutoff": 0.0738,
        "candidate_pool_avg_amount_share_of_min_gate": 2.4069,
        "gate_status": {"score": "shadow_observation"},
        "top_reasons": [
            "candidate_score=0.01",
            "filter_reason=structural_prefilter_fail",
            "breakout_freshness=0.00",
        ],
        "short_trade_boundary_metrics": {
            "breakout_freshness": 0.0,
            "trend_acceleration": 0.0,
            "volume_expansion_quality": 0.0,
            "catalyst_freshness": 0.0,
            "close_strength": 0.068,
            "candidate_score": 0.0068,
        },
        "strategy_signals": {
            "trend": _make_signal(
                -1,
                45.0,
                sub_factors={
                    "momentum": {"direction": 0, "confidence": 50.0, "completeness": 1.0},
                    "adx_strength": {"direction": -1, "confidence": 21.7, "completeness": 1.0},
                    "ema_alignment": {"direction": -1, "confidence": 100.0, "completeness": 1.0},
                    "volatility": {"direction": -1, "confidence": 61.1, "completeness": 1.0},
                    "long_trend_alignment": {"direction": -1, "confidence": 32.5, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "mean_reversion": _make_signal(0, 49.0).model_dump(mode="json"),
            "fundamental": _make_signal(0, 0.0, completeness=0.0).model_dump(mode="json"),
            "event_sentiment": _make_signal(0, 0.0, completeness=0.0).model_dump(mode="json"),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.0, "investor": 0.0}},
    }


def test_refresh_selection_artifacts_from_daily_events_promotes_post_gate_shadow_entry(tmp_path, monkeypatch: pytest.MonkeyPatch):
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
    raw_current_plan = plan.model_dump(mode="json")
    raw_current_plan["candidate_pool_shadow"] = {
        "tickers": [
            {
                "ticker": "300720",
                "candidate_pool_rank": 1131,
                "candidate_pool_lane": "layer_a_liquidity_corridor",
                "candidate_pool_shadow_reason": "upstream_base_liquidity_uplift_shadow_visibility_gap_relaxed_band",
                "avg_amount_share_of_cutoff": 0.3221,
                "avg_amount_share_of_min_gate": 9.6762,
                "shadow_visibility_gap_selected": True,
                "shadow_visibility_gap_relaxed_band": True,
            }
        ]
    }
    (report_dir / "daily_events.jsonl").write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": trade_date,
                "current_plan": raw_current_plan,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        refresh_module,
        "_load_latest_historical_prior_by_ticker",
        lambda report_path: {
            "300720": {
                "execution_quality_label": "close_continuation",
                "evaluable_count": 4,
                "next_close_positive_rate": 0.75,
                "next_open_to_close_return_mean": 0.03,
            }
        },
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


def test_refresh_selection_artifacts_from_daily_events_promotes_visibility_gap_corridor_shadow_entry(tmp_path, monkeypatch: pytest.MonkeyPatch):
    report_dir = tmp_path / "paper_trading_20260406_20260406_refresh_target"
    (report_dir / "selection_artifacts").mkdir(parents=True)
    trade_date = "20260406"

    plan = ExecutionPlan(
        date=trade_date,
        target_mode="short_trade_only",
        risk_metrics={
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {"tickers": [], "released_shadow_entries": []},
                    "short_trade_candidates": {
                        "tickers": [],
                        "released_shadow_entries": [_make_corridor_released_shadow_entry(shadow_visibility_gap_selected=True)],
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
    monkeypatch.setattr(
        refresh_module,
        "_load_latest_historical_prior_by_ticker",
        lambda report_path: {
            "300720": {
                "execution_quality_label": "close_continuation",
                "evaluable_count": 4,
                "next_close_positive_rate": 0.75,
                "next_open_to_close_return_mean": 0.03,
            }
        },
    )

    refresh_selection_artifacts_for_report(report_dir, trade_date="2026-04-06")

    selection_snapshot = json.loads((report_dir / "selection_artifacts" / "2026-04-06" / "selection_snapshot.json").read_text(encoding="utf-8"))
    short_trade = selection_snapshot["selection_targets"]["300720"]["short_trade"]
    assert short_trade["metrics_payload"]["thresholds"]["effective_select_threshold"] == 0.45
    assert short_trade["metrics_payload"]["thresholds"]["near_miss_threshold"] == 0.45
    assert selection_snapshot["selection_targets"]["300720"]["short_trade"]["decision"] == "selected"


def test_refresh_selection_artifacts_from_daily_events_recomputes_shadow_observation_blockers(tmp_path):
    report_dir = tmp_path / "paper_trading_20260330_20260330_refresh_shadow_observation"
    (report_dir / "selection_artifacts").mkdir(parents=True)
    trade_date = "20260330"

    plan = ExecutionPlan(
        date=trade_date,
        target_mode="short_trade_only",
        risk_metrics={
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {"tickers": [], "released_shadow_entries": []},
                    "short_trade_candidates": {
                        "tickers": [],
                        "released_shadow_entries": [],
                        "shadow_observation_entries": [_make_corridor_shadow_observation_entry()],
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

    refresh_selection_artifacts_for_report(report_dir, trade_date="2026-03-30")

    replay_input = json.loads((report_dir / "selection_artifacts" / "2026-03-30" / "selection_target_replay_input.json").read_text(encoding="utf-8"))
    observation_entry = replay_input["upstream_shadow_observation_entries"][0]
    assert observation_entry["ticker"] == "301188"
    assert observation_entry["filter_reason"] == "structural_prefilter_fail"
    assert observation_entry["blockers"] == ["trend_not_constructive"]
    assert observation_entry["short_trade_boundary_metrics"]["gate_status"] == {
        "data": "pass",
        "execution": "proxy_only",
        "structural": "fail",
        "score": "fail",
    }


def test_refresh_selection_artifacts_from_daily_events_keeps_plain_corridor_shadow_below_selected(tmp_path):
    report_dir = tmp_path / "paper_trading_20260406_20260406_refresh_target_plain"
    (report_dir / "selection_artifacts").mkdir(parents=True)
    trade_date = "20260406"

    plan = ExecutionPlan(
        date=trade_date,
        target_mode="short_trade_only",
        risk_metrics={
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {"tickers": [], "released_shadow_entries": []},
                    "short_trade_candidates": {
                        "tickers": [],
                        "released_shadow_entries": [_make_corridor_released_shadow_entry(shadow_visibility_gap_selected=False)],
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

    refresh_selection_artifacts_for_report(report_dir, trade_date="2026-04-06")

    selection_snapshot = json.loads((report_dir / "selection_artifacts" / "2026-04-06" / "selection_snapshot.json").read_text(encoding="utf-8"))
    short_trade = selection_snapshot["selection_targets"]["300720"]["short_trade"]
    assert short_trade["metrics_payload"]["thresholds"]["effective_select_threshold"] == 0.58
    assert selection_snapshot["selection_targets"]["300720"]["short_trade"]["decision"] == "rejected"


def test_refresh_selection_artifacts_from_daily_events_injects_historical_prior_into_boundary_candidate(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    report_dir = tmp_path / "paper_trading_20260406_20260406_refresh_boundary"
    (report_dir / "selection_artifacts").mkdir(parents=True)
    trade_date = "20260406"

    plan = ExecutionPlan(
        date=trade_date,
        target_mode="short_trade_only",
        risk_metrics={
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {"tickers": [], "released_shadow_entries": []},
                    "short_trade_candidates": {
                        "tickers": [
                            {
                                "ticker": "300757",
                                "score_b": 0.2,
                                "score_c": -0.4,
                                "score_final": 0.05,
                                "quality_score": 0.58,
                                "decision": "watch",
                                "reason": "short_trade_candidate_score_ranked",
                                "reasons": ["short_trade_candidate_score_ranked", "short_trade_prequalified"],
                                "candidate_source": "short_trade_boundary",
                                "candidate_reason_codes": ["short_trade_candidate_score_ranked", "short_trade_prequalified"],
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
                                    "fundamental": _make_signal(
                                        -1,
                                        68.0,
                                        sub_factors={
                                            "profitability": {
                                                "direction": -1,
                                                "confidence": 72.0,
                                                "completeness": 1.0,
                                                "metrics": {"positive_count": 0},
                                            }
                                        },
                                    ).model_dump(mode="json"),
                                },
                                "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.0, "investor": 0.0}},
                            }
                        ],
                        "released_shadow_entries": [],
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
    (report_dir / "btst_next_day_trade_brief_latest.json").write_text(
        json.dumps(
            {
                "opportunity_pool_entries": [
                    {
                        "ticker": "300757",
                        "decision": "rejected",
                        "candidate_source": "short_trade_boundary",
                        "historical_prior": {
                            "execution_quality_label": "gap_chase_risk",
                            "entry_timing_bias": "avoid_open_chase",
                            "evaluable_count": 6,
                            "next_high_hit_rate_at_threshold": 0.6667,
                            "next_close_positive_rate": 0.6667,
                            "execution_note": "历史上更像高开后回落，避免开盘直接追价。",
                        },
                    }
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (report_dir / "session_summary.json").write_text(
        json.dumps(
            {
                "end_date": "2026-04-06",
                "plan_generation": {"selection_target": "short_trade_only"},
                "btst_followup": {
                    "trade_date": "2026-04-06",
                    "brief_json": str((report_dir / "btst_next_day_trade_brief_latest.json").resolve()),
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    refresh_selection_artifacts_for_report(report_dir, trade_date="2026-04-06")

    replay_input = json.loads((report_dir / "selection_artifacts" / "2026-04-06" / "selection_target_replay_input.json").read_text(encoding="utf-8"))
    supplemental_entry = next(entry for entry in replay_input["supplemental_short_trade_entries"] if entry["ticker"] == "300757")
    assert supplemental_entry["historical_prior"]["execution_quality_label"] == "gap_chase_risk"
    assert supplemental_entry["historical_prior"]["entry_timing_bias"] == "avoid_open_chase"

    selection_snapshot = json.loads((report_dir / "selection_artifacts" / "2026-04-06" / "selection_snapshot.json").read_text(encoding="utf-8"))
    short_trade = selection_snapshot["selection_targets"]["300757"]["short_trade"]
    assert short_trade["decision"] in {"selected", "near_miss"}
    assert short_trade["preferred_entry_mode"] == "avoid_open_chase_confirmation"
    assert short_trade["metrics_payload"]["historical_execution_relief"]["applied"] is True
    assert short_trade["metrics_payload"]["historical_execution_relief"]["execution_quality_label"] == "gap_chase_risk"
