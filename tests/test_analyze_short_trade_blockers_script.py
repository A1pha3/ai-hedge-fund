from __future__ import annotations

import json

import scripts.analyze_short_trade_blockers as blockers_module
from scripts.analyze_short_trade_blockers import analyze_short_trade_blockers


def test_analyze_short_trade_blockers_aggregates_decisions_and_sources(tmp_path):
    report_dir = tmp_path / "report"
    selection_root = report_dir / "selection_artifacts"
    (selection_root / "2026-03-10").mkdir(parents=True)
    (selection_root / "2026-03-11").mkdir(parents=True)

    (report_dir / "session_summary.json").write_text(
        json.dumps({"plan_generation": {"selection_target": "dual_target"}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (selection_root / "2026-03-10" / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-10",
                "selection_targets": {
                    "000001": {
                        "candidate_source": "layer_b_boundary",
                        "candidate_reason_codes": ["near_fast_score_threshold"],
                        "delta_classification": "research_reject_short_pass",
                        "short_trade": {
                            "decision": "selected",
                            "score_target": 0.61,
                            "blockers": [],
                            "negative_tags": [],
                            "top_reasons": ["score_short=0.61"],
                            "gate_status": {"score": "pass", "structural": "pass"},
                            "metrics_payload": {"score_b": 0.49, "score_c": 0.0, "score_final": 0.49},
                            "explainability_payload": {"available_strategy_signals": ["trend", "event_sentiment"]},
                        },
                    },
                    "000002": {
                        "candidate_source": "watchlist_filter_diagnostics",
                        "candidate_reason_codes": ["decision_avoid"],
                        "delta_classification": "both_reject_but_reason_diverge",
                        "short_trade": {
                            "decision": "blocked",
                            "score_target": 0.22,
                            "blockers": ["layer_c_bearish_conflict"],
                            "negative_tags": ["layer_c_avoid_signal"],
                            "top_reasons": ["score_short=0.22"],
                            "gate_status": {"score": "fail", "structural": "fail"},
                            "metrics_payload": {"score_b": 0.40, "score_c": -0.05, "score_final": 0.19},
                            "explainability_payload": {"available_strategy_signals": []},
                        },
                    },
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (selection_root / "2026-03-11" / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-11",
                "selection_targets": {
                    "000003": {
                        "candidate_source": "layer_c_watchlist",
                        "candidate_reason_codes": [],
                        "short_trade": {
                            "decision": "rejected",
                            "score_target": 0.31,
                            "blockers": [],
                            "negative_tags": ["event_signal_incomplete"],
                            "top_reasons": ["score_short=0.31"],
                            "gate_status": {"score": "fail", "structural": "pass"},
                            "metrics_payload": {"score_b": 0.58, "score_c": 0.12, "score_final": 0.34},
                            "explainability_payload": {"available_strategy_signals": ["trend"]},
                        },
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_short_trade_blockers(report_dir)

    assert analysis["target_mode"] == "dual_target"
    assert analysis["short_trade_target_count"] == 3
    assert analysis["short_trade_decision_counts"] == {"selected": 1, "blocked": 1, "rejected": 1}
    assert analysis["candidate_source_counts"] == {
        "layer_b_boundary": 1,
        "watchlist_filter_diagnostics": 1,
        "layer_c_watchlist": 1,
    }
    assert analysis["failure_mechanism_counts"] == {
        "selected": 1,
        "blocked_structural_bearish_conflict": 1,
        "rejected_layer_c_watchlist_score_fail": 1,
    }
    assert analysis["candidate_source_breakdown"]["watchlist_filter_diagnostics"]["decision_counts"] == {"blocked": 1}
    assert analysis["candidate_source_breakdown"]["watchlist_filter_diagnostics"]["blocker_counts"] == {"layer_c_bearish_conflict": 1}
    assert analysis["blocker_counts"] == {"layer_c_bearish_conflict": 1}
    assert analysis["negative_tag_counts"] == {"layer_c_avoid_signal": 1, "event_signal_incomplete": 1}
    assert analysis["signal_availability"] == {"has_any": 2, "missing_all": 1}
    assert analysis["available_strategy_signal_counts"] == {"trend": 2, "event_sentiment": 1}
    assert analysis["top_blocked_examples"][0]["available_strategy_signals"] == []
    assert analysis["top_blocked_examples"][0]["ticker"] == "000002"
    assert analysis["recommended_focus_areas"][0]["focus_area"] == "layer_c_bearish_conflict_review"


def test_analyze_short_trade_blockers_can_filter_trade_dates(tmp_path):
    report_dir = tmp_path / "report"
    selection_root = report_dir / "selection_artifacts"
    (selection_root / "2026-03-10").mkdir(parents=True)
    (selection_root / "2026-03-11").mkdir(parents=True)

    (selection_root / "2026-03-10" / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-10",
                "selection_targets": {
                    "000001": {
                        "candidate_source": "short_trade_boundary",
                        "candidate_reason_codes": ["short_trade_prequalified"],
                        "short_trade": {
                            "decision": "near_miss",
                            "score_target": 0.5,
                            "blockers": [],
                            "negative_tags": [],
                            "top_reasons": ["score_short=0.50"],
                            "gate_status": {"score": "near_miss", "structural": "pass"},
                            "metrics_payload": {"score_b": 0.45, "score_c": 0.0, "score_final": 0.45},
                            "explainability_payload": {"available_strategy_signals": ["trend"]},
                        },
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (selection_root / "2026-03-11" / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-11",
                "selection_targets": {
                    "000002": {
                        "candidate_source": "watchlist_filter_diagnostics",
                        "candidate_reason_codes": ["decision_avoid"],
                        "short_trade": {
                            "decision": "blocked",
                            "score_target": 0.2,
                            "blockers": ["layer_c_bearish_conflict"],
                            "negative_tags": [],
                            "top_reasons": ["score_short=0.20"],
                            "gate_status": {"score": "fail", "structural": "fail"},
                            "metrics_payload": {"score_b": 0.3, "score_c": -0.1, "score_final": 0.1},
                            "explainability_payload": {"available_strategy_signals": ["trend"]},
                        },
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_short_trade_blockers(report_dir, trade_dates={"2026-03-11"})

    assert analysis["trade_dates_filter"] == ["2026-03-11"]
    assert analysis["trade_day_count"] == 1
    assert analysis["short_trade_target_count"] == 1
    assert analysis["short_trade_decision_counts"] == {"blocked": 1}
    assert analysis["candidate_source_counts"] == {"watchlist_filter_diagnostics": 1}


def test_analyze_short_trade_blockers_includes_upstream_shadow_observation_entries(tmp_path):
    report_dir = tmp_path / "report"
    selection_root = report_dir / "selection_artifacts" / "2026-03-30"
    selection_root.mkdir(parents=True)

    (selection_root / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-30",
                "selection_targets": {},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (selection_root / "selection_target_replay_input.json").write_text(
        json.dumps(
            {
                "upstream_shadow_observation_entries": [
                    {
                        "ticker": "301188",
                        "decision": "observation",
                        "score_target": 0.18,
                        "candidate_source": "upstream_liquidity_corridor_shadow",
                        "candidate_reason_codes": [
                            "upstream_base_liquidity_uplift_shadow",
                            "candidate_pool_truncated_after_filters",
                            "layer_a_liquidity_corridor",
                        ],
                        "blockers": ["trend_not_constructive"],
                        "top_reasons": [
                            "candidate_score=0.18",
                            "filter_reason=structural_prefilter_fail",
                        ],
                        "gate_status": {"data": "pass", "structural": "fail", "score": "shadow_observation"},
                        "strategy_signals": {
                            "trend": {},
                            "mean_reversion": {},
                        },
                        "short_trade_boundary_metrics": {
                            "candidate_score": 0.18,
                            "breakout_freshness": 0.1,
                            "trend_acceleration": 0.0,
                            "close_strength": 0.4,
                            "gate_status": {"data": "pass", "structural": "fail", "score": "shadow_observation"},
                            "blockers": ["trend_not_constructive"],
                        },
                    }
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_short_trade_blockers(report_dir)

    assert analysis["short_trade_target_count"] == 1
    assert analysis["short_trade_decision_counts"] == {"observation": 1}
    assert analysis["candidate_source_counts"] == {"upstream_liquidity_corridor_shadow": 1}
    assert analysis["failure_mechanism_counts"] == {"blocked_trend_not_constructive": 1}
    assert analysis["blocker_counts"] == {"trend_not_constructive": 1}
    assert analysis["candidate_source_breakdown"]["upstream_liquidity_corridor_shadow"]["decision_counts"] == {"observation": 1}
    assert analysis["candidate_source_breakdown"]["upstream_liquidity_corridor_shadow"]["blocker_counts"] == {"trend_not_constructive": 1}
    assert analysis["top_near_threshold_examples"][0]["ticker"] == "301188"
    assert analysis["recommended_focus_areas"][0]["focus_area"] == "trend_not_constructive_shadow_review"


def test_analyze_short_trade_blockers_recomputes_missing_observation_blockers(tmp_path):
    report_dir = tmp_path / "report"
    selection_root = report_dir / "selection_artifacts" / "2026-03-30"
    selection_root.mkdir(parents=True)

    (selection_root / "selection_snapshot.json").write_text(
        json.dumps({"trade_date": "2026-03-30", "selection_targets": {}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (selection_root / "selection_target_replay_input.json").write_text(
        json.dumps(
            {
                "upstream_shadow_observation_entries": [
                    {
                        "ticker": "301188",
                        "decision": "observation",
                        "score_target": 0.0068,
                        "candidate_source": "upstream_liquidity_corridor_shadow",
                        "candidate_reason_codes": [
                            "upstream_base_liquidity_uplift_shadow",
                            "candidate_pool_truncated_after_filters",
                            "layer_a_liquidity_corridor",
                        ],
                        "blockers": [],
                        "gate_status": {"score": "shadow_observation"},
                        "top_reasons": [
                            "candidate_score=0.01",
                            "filter_reason=structural_prefilter_fail",
                            "breakout_freshness=0.00",
                        ],
                        "strategy_signals": {
                            "trend": {
                                "direction": -1,
                                "confidence": 45.0,
                                "completeness": 1.0,
                                "sub_factors": {
                                    "momentum": {"direction": 0, "confidence": 50.0, "completeness": 1.0},
                                    "adx_strength": {"direction": -1, "confidence": 21.7, "completeness": 1.0},
                                    "ema_alignment": {"direction": -1, "confidence": 100.0, "completeness": 1.0},
                                    "volatility": {"direction": -1, "confidence": 61.1, "completeness": 1.0},
                                    "long_trend_alignment": {"direction": -1, "confidence": 32.5, "completeness": 1.0},
                                },
                            },
                            "mean_reversion": {"direction": 0, "confidence": 49.0, "completeness": 1.0, "sub_factors": {}},
                            "fundamental": {"direction": 0, "confidence": 0.0, "completeness": 0.0, "sub_factors": {}},
                            "event_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 0.0, "sub_factors": {}},
                        },
                    }
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_short_trade_blockers(report_dir)

    assert analysis["failure_mechanism_counts"] == {"blocked_trend_not_constructive": 1}
    assert analysis["blocker_counts"] == {"trend_not_constructive": 1}
    assert analysis["candidate_source_breakdown"]["upstream_liquidity_corridor_shadow"]["blocker_counts"] == {"trend_not_constructive": 1}


def test_analyze_short_trade_blockers_attaches_missing_historical_prior_for_observation_entries(tmp_path, monkeypatch):
    report_dir = tmp_path / "report"
    selection_root = report_dir / "selection_artifacts" / "2026-03-30"
    selection_root.mkdir(parents=True)

    (selection_root / "selection_snapshot.json").write_text(
        json.dumps({"trade_date": "2026-03-30", "selection_targets": {}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (selection_root / "selection_target_replay_input.json").write_text(
        json.dumps(
            {
                "upstream_shadow_observation_entries": [
                    {
                        "ticker": "300720",
                        "decision": "observation",
                        "score_target": 0.4794,
                        "candidate_source": "post_gate_liquidity_competition_shadow",
                        "candidate_reason_codes": [
                            "post_gate_liquidity_competition_shadow",
                            "candidate_pool_truncated_after_filters",
                            "post_gate_liquidity_competition",
                        ],
                        "blockers": [],
                        "gate_status": {"score": "shadow_observation"},
                        "top_reasons": [
                            "candidate_score=0.48",
                            "filter_reason=catalyst_freshness_below_short_trade_boundary_floor",
                        ],
                        "strategy_signals": {
                            "trend": {},
                            "event_sentiment": {},
                        },
                        "short_trade_boundary_metrics": {
                            "candidate_score": 0.4794,
                            "breakout_freshness": 0.4,
                            "trend_acceleration": 0.8814,
                            "volume_expansion_quality": 0.25,
                            "catalyst_freshness": 0.0,
                            "close_strength": 0.8902,
                        },
                    }
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        blockers_module,
        "_load_historical_prior_by_ticker",
        lambda report_path: {
            "300720": {
                "execution_quality_label": "intraday_only",
                "evaluable_count": 4,
                "next_close_positive_rate": 0.0,
            }
        },
    )

    analysis = analyze_short_trade_blockers(report_dir)

    example = analysis["top_near_threshold_examples"][0]
    assert example["ticker"] == "300720"
    assert example["historical_execution_quality_label"] == "intraday_only"
    assert example["historical_evaluable_count"] == 4
    assert example["historical_next_close_positive_rate"] == 0.0


def test_analyze_short_trade_blockers_summarizes_supportive_catalyst_shadows(tmp_path):
    report_dir = tmp_path / "report"
    selection_root = report_dir / "selection_artifacts" / "2026-03-30"
    selection_root.mkdir(parents=True)

    (selection_root / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-30",
                "selection_targets": {
                    "003036": {
                        "candidate_source": "upstream_liquidity_corridor_shadow",
                        "candidate_reason_codes": [
                            "upstream_base_liquidity_uplift_shadow",
                            "candidate_pool_truncated_after_filters",
                            "layer_a_liquidity_corridor",
                        ],
                        "short_trade": {
                            "decision": "observation",
                            "score_target": 0.4725,
                            "blockers": [],
                            "negative_tags": [],
                            "top_reasons": [
                                "candidate_score=0.47",
                                "filter_reason=catalyst_freshness_below_short_trade_boundary_floor",
                            ],
                            "gate_status": {"score": "shadow_observation", "data": "pass", "structural": "pass"},
                            "metrics_payload": {
                                "candidate_score": 0.4725,
                                "breakout_freshness": 0.4,
                                "trend_acceleration": 0.86,
                                "volume_expansion_quality": 0.25,
                                "catalyst_freshness": 0.0,
                                "close_strength": 0.89,
                            },
                            "historical_prior": {
                                "execution_quality_label": "close_continuation",
                                "evaluable_count": 2,
                                "next_close_positive_rate": 1.0,
                                "next_open_to_close_return_mean": 0.12,
                            },
                            "explainability_payload": {"available_strategy_signals": ["trend", "event_sentiment"]},
                        },
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_short_trade_blockers(report_dir)

    assert analysis["supportive_catalyst_shadow_summary"]["count"] == 1
    assert analysis["supportive_catalyst_shadow_summary"]["support_bucket_counts"] == {"supportive_close_continuation": 1}
    assert analysis["supportive_catalyst_shadow_summary"]["execution_quality_label_counts"] == {"close_continuation": 1}
    assert analysis["supportive_catalyst_shadow_summary"]["supportive_examples"][0]["ticker"] == "003036"
    assert analysis["recommended_focus_areas"][0]["focus_area"] == "supportive_catalyst_shadow_release_probe"
