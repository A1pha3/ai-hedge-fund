from __future__ import annotations

import json
from pathlib import Path

import scripts.analyze_btst_tplus2_near_cluster_dossier as dossier


def test_analyze_btst_tplus2_near_cluster_dossier_summarizes_candidate(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()

    monkeypatch.setattr(
        dossier,
        "_collect_rows",
        lambda *_args, **_kwargs: [
            {
                "report_label": "window_a",
                "ticker": "600988",
                "candidate_source": "layer_c_watchlist",
                "metrics_payload": {
                    "breakout_freshness": 0.35,
                    "trend_acceleration": 0.48,
                    "catalyst_freshness": 0.01,
                    "layer_c_alignment": 0.49,
                    "sector_resonance": 0.13,
                    "close_strength": 0.64,
                    "t_plus_2_continuation_candidate": {"applied": True},
                },
                "next_high_return": 0.05,
                "next_close_return": -0.01,
                "t_plus_2_close_return": 0.03,
            },
            {
                "report_label": "window_a",
                "ticker": "600989",
                "candidate_source": "layer_c_watchlist",
                "metrics_payload": {
                    "breakout_freshness": 0.41,
                    "trend_acceleration": 0.56,
                    "catalyst_freshness": 0.02,
                    "layer_c_alignment": 0.52,
                    "sector_resonance": 0.14,
                    "close_strength": 0.78,
                },
                "next_high_return": 0.03,
                "next_close_return": 0.01,
                "t_plus_2_close_return": 0.012,
            },
        ],
    )

    analysis = dossier.analyze_btst_tplus2_near_cluster_dossier(reports_root)

    assert analysis["candidate_ticker"] == "600989"
    assert analysis["candidate_row_count"] == 1
    assert analysis["verdict"] == "near_cluster_candidate"
    assert analysis["candidate_tier_focus"] == "near_cluster_peer"
    assert analysis["tier_counts"]["near_cluster_peer"] == 1
    assert analysis["recent_window_count"] == 1
    assert analysis["recent_supporting_window_count"] == 1
    assert analysis["recent_validation_verdict"] == "recent_support_confirmed"
    assert analysis["recent_tier_verdict"] == "recent_tier_confirmed"
    assert analysis["promotion_readiness_verdict"] == "watchlist_ready"

    markdown = dossier.render_btst_tplus2_near_cluster_dossier_markdown(analysis)
    assert "# BTST T+2 Near-Cluster Dossier" in markdown
    assert "600989" in markdown
    assert "recent_validation_verdict" in markdown


def test_analyze_btst_tplus2_near_cluster_dossier_supports_observation_queue(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()

    monkeypatch.setattr(
        dossier,
        "_collect_rows",
        lambda *_args, **_kwargs: [
            {
                "report_label": "window_a",
                "ticker": "600988",
                "candidate_source": "layer_c_watchlist",
                "metrics_payload": {
                    "breakout_freshness": 0.35,
                    "trend_acceleration": 0.48,
                    "catalyst_freshness": 0.01,
                    "layer_c_alignment": 0.49,
                    "sector_resonance": 0.13,
                    "close_strength": 0.64,
                    "t_plus_2_continuation_candidate": {"applied": True},
                },
                "next_high_return": 0.05,
                "next_close_return": -0.01,
                "t_plus_2_close_return": 0.03,
            },
            {
                "report_label": "window_a",
                "ticker": "300505",
                "candidate_source": "layer_c_watchlist",
                "metrics_payload": {
                    "breakout_freshness": 0.58,
                    "trend_acceleration": 0.75,
                    "catalyst_freshness": 0.04,
                    "layer_c_alignment": 0.62,
                    "sector_resonance": 0.22,
                    "close_strength": 0.95,
                },
                "next_high_return": 0.04,
                "next_close_return": 0.01,
                "t_plus_2_close_return": 0.02,
            },
        ],
    )

    analysis = dossier.analyze_btst_tplus2_near_cluster_dossier(reports_root, candidate_ticker="300505")

    assert analysis["candidate_ticker"] == "300505"
    assert analysis["verdict"] == "observation_only_candidate"
    assert analysis["candidate_tier_focus"] == "observation_candidate"
    assert analysis["recent_tier_verdict"] == "recent_tier_confirmed"
    assert analysis["promotion_readiness_verdict"] == "validation_queue_ready"


def test_analyze_btst_tplus2_near_cluster_dossier_counts_recent_tier_trade_dates_within_same_report(
    monkeypatch, tmp_path: Path
) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()

    monkeypatch.setattr(
        dossier,
        "_collect_rows",
        lambda *_args, **_kwargs: [
            {
                "report_label": "window_anchor",
                "trade_date": "2026-03-24",
                "ticker": "600988",
                "candidate_source": "layer_c_watchlist",
                "metrics_payload": {
                    "breakout_freshness": 0.35,
                    "trend_acceleration": 0.48,
                    "catalyst_freshness": 0.01,
                    "layer_c_alignment": 0.49,
                    "sector_resonance": 0.13,
                    "close_strength": 0.64,
                    "t_plus_2_continuation_candidate": {"applied": True},
                },
                "next_high_return": 0.05,
                "next_close_return": -0.01,
                "t_plus_2_close_return": 0.03,
            },
            {
                "report_label": "window_bundle",
                "trade_date": "2026-03-27",
                "ticker": "300683",
                "candidate_source": "upstream_liquidity_corridor_shadow",
                "metrics_payload": {
                    "breakout_freshness": 0.37,
                    "trend_acceleration": 0.5,
                    "catalyst_freshness": 0.02,
                    "layer_c_alignment": 0.5,
                    "sector_resonance": 0.14,
                        "close_strength": 0.88,
                },
                "next_high_return": 0.09,
                "next_close_return": 0.03,
                "t_plus_2_close_return": 0.07,
            },
            {
                "report_label": "window_bundle",
                "trade_date": "2026-03-30",
                "ticker": "300683",
                "candidate_source": "upstream_liquidity_corridor_shadow",
                "metrics_payload": {
                    "breakout_freshness": 0.38,
                    "trend_acceleration": 0.49,
                    "catalyst_freshness": 0.02,
                    "layer_c_alignment": 0.5,
                    "sector_resonance": 0.14,
                        "close_strength": 0.88,
                },
                "next_high_return": 0.08,
                "next_close_return": 0.02,
                "t_plus_2_close_return": 0.06,
            },
        ],
    )

    analysis = dossier.analyze_btst_tplus2_near_cluster_dossier(reports_root, candidate_ticker="300683")

    assert analysis["candidate_tier_focus"] == "near_cluster_peer"
    assert analysis["recent_window_count"] == 1
    assert analysis["recent_tier_window_count"] == 2
    assert analysis["recent_tier_verdict"] == "recent_tier_confirmed"


def test_analyze_btst_tplus2_near_cluster_dossier_keeps_strong_positive_t_plus_2_window_in_recent_tier(
    monkeypatch, tmp_path: Path
) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()

    monkeypatch.setattr(
        dossier,
        "_collect_rows",
        lambda *_args, **_kwargs: [
            {
                "report_label": "window_anchor",
                "trade_date": "2026-03-24",
                "ticker": "600988",
                "candidate_source": "layer_c_watchlist",
                "metrics_payload": {
                    "breakout_freshness": 0.35,
                    "trend_acceleration": 0.48,
                    "catalyst_freshness": 0.01,
                    "layer_c_alignment": 0.49,
                    "sector_resonance": 0.13,
                    "close_strength": 0.64,
                    "t_plus_2_continuation_candidate": {"applied": True},
                },
                "next_high_return": 0.05,
                "next_close_return": -0.01,
                "t_plus_2_close_return": 0.03,
            },
            {
                "report_label": "window_bundle",
                "trade_date": "2026-03-27",
                "ticker": "300683",
                "candidate_source": "upstream_liquidity_corridor_shadow",
                "metrics_payload": {
                    "breakout_freshness": 0.37,
                    "trend_acceleration": 0.5,
                    "catalyst_freshness": 0.02,
                    "layer_c_alignment": 0.5,
                    "sector_resonance": 0.14,
                    "close_strength": 0.88,
                },
                "next_high_return": 0.1646,
                "next_close_return": 0.0858,
                "t_plus_2_close_return": 0.1172,
            },
            {
                "report_label": "window_bundle",
                "trade_date": "2026-03-30",
                "ticker": "300683",
                "candidate_source": "upstream_liquidity_corridor_shadow",
                "metrics_payload": {
                    "breakout_freshness": 0.38,
                    "trend_acceleration": 0.49,
                    "catalyst_freshness": 0.02,
                    "layer_c_alignment": 0.5,
                    "sector_resonance": 0.14,
                    "close_strength": 0.88,
                },
                "next_high_return": 0.0904,
                "next_close_return": 0.029,
                "t_plus_2_close_return": 0.1576,
            },
            {
                "report_label": "window_bundle",
                "trade_date": "2026-03-31",
                "ticker": "300683",
                "candidate_source": "upstream_liquidity_corridor_shadow",
                "metrics_payload": {
                    "breakout_freshness": 0.39,
                    "trend_acceleration": 0.5,
                    "catalyst_freshness": 0.02,
                    "layer_c_alignment": 0.5,
                    "sector_resonance": 0.14,
                    "close_strength": 0.88,
                },
                "next_high_return": 0.1504,
                "next_close_return": 0.125,
                "t_plus_2_close_return": 0.0936,
            },
        ],
    )

    analysis = dossier.analyze_btst_tplus2_near_cluster_dossier(reports_root, candidate_ticker="300683")

    assert analysis["candidate_tier_focus"] == "near_cluster_peer"
    assert analysis["recent_window_count"] == 1
    assert analysis["recent_tier_window_count"] == 3
    assert analysis["recent_tier_verdict"] == "recent_tier_confirmed"


def test_analyze_btst_tplus2_near_cluster_dossier_marks_governance_followup_candidate(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()
    upstream_handoff_board_path = tmp_path / "btst_candidate_pool_upstream_handoff_board_latest.json"
    lane_objective_support_path = tmp_path / "btst_candidate_pool_lane_objective_support_latest.json"
    upstream_handoff_board_path.write_text(
        json.dumps(
            {
                "board_rows": [
                    {
                        "ticker": "300720",
                        "downstream_followup_lane": "t_plus_2_continuation_review",
                        "downstream_followup_status": "continuation_confirm_then_review",
                        "downstream_followup_blocker": "no_selected_persistence_or_independent_edge",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    lane_objective_support_path.write_text(
        json.dumps(
            {
                "ticker_rows": [
                    {
                        "ticker": "300720",
                        "next_close_positive_rate": 0.8,
                        "t_plus_2_positive_rate": 0.8667,
                        "mean_t_plus_2_return": 0.0787,
                        "next_high_hit_rate_at_threshold": 0.8667,
                        "closed_cycle_count": 15,
                        "support_verdict": "candidate_pool_false_negative_outperforms_tradeable_surface",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    followup_report_dir = reports_root / "paper_trading_20260331_20260331_live_m2_7_short_trade_only_300720_followup"
    followup_report_dir.mkdir(parents=True, exist_ok=True)
    (followup_report_dir / "daily_events.jsonl").write_text('{"trade_date":"20260331","current_plan":{"date":"20260331"},"focus":"300720"}\n', encoding="utf-8")
    followup_brief_path = followup_report_dir / "btst_next_day_trade_brief_latest.json"
    followup_brief_path.write_text(
        json.dumps(
            {
                "upstream_shadow_recall_summary": {"top_focus_tickers": ["300720"]},
                "priority_rows": [
                    {
                        "ticker": "300720",
                        "decision": "near_miss",
                        "candidate_source": "post_gate_liquidity_competition_shadow",
                        "positive_tags": ["upstream_shadow_catalyst_relief_applied"],
                        "top_reasons": ["upstream_shadow_catalyst_relief"],
                        "score_target": 0.4574,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (followup_report_dir / "session_summary.json").write_text(
        json.dumps(
            {
                "plan_generation": {"selection_target": "short_trade_only"},
                "btst_followup": {
                    "trade_date": "2026-03-31",
                    "brief_json": str(followup_brief_path.resolve()),
                },
            }
        ),
        encoding="utf-8",
    )
    gap_report_dir = reports_root / "paper_trading_20260327_20260327_live_m2_7_short_trade_only_300720_gap"
    gap_report_dir.mkdir(parents=True, exist_ok=True)
    (gap_report_dir / "daily_events.jsonl").write_text('{"trade_date":"20260327","current_plan":{"date":"20260327"},"focus":"300720"}\n', encoding="utf-8")

    class _FakePlan:
        def __init__(self, payload: dict[str, object]) -> None:
            self._payload = payload

        def model_dump(self, mode: str = "json") -> dict[str, object]:
            return dict(self._payload)

    monkeypatch.setattr(
        dossier,
        "load_frozen_post_market_plans",
        lambda path: (
            {
                "20260331": _FakePlan(
                    {
                        "risk_metrics": {
                            "funnel_diagnostics": {
                                "filters": {
                                    "short_trade_candidates": {
                                        "released_shadow_entries": [{"ticker": "300720"}],
                                    }
                                }
                            }
                        }
                    }
                )
            }
            if Path(path).parent.name == followup_report_dir.name
            else {
                "20260327": _FakePlan(
                    {
                        "risk_metrics": {
                            "funnel_diagnostics": {
                                "filters": {
                                    "short_trade_candidates": {
                                        "released_shadow_entries": [],
                                    }
                                }
                            }
                        }
                    }
                )
            }
        ),
    )

    monkeypatch.setattr(
        dossier,
        "_collect_rows",
        lambda *_args, **_kwargs: [
            {
                "report_label": "window_a",
                "ticker": "600988",
                "candidate_source": "layer_c_watchlist",
                "metrics_payload": {
                    "breakout_freshness": 0.35,
                    "trend_acceleration": 0.48,
                    "catalyst_freshness": 0.01,
                    "layer_c_alignment": 0.49,
                    "sector_resonance": 0.13,
                    "close_strength": 0.64,
                    "t_plus_2_continuation_candidate": {"applied": True},
                },
                "next_high_return": 0.05,
                "next_close_return": -0.01,
                "t_plus_2_close_return": 0.03,
            }
        ],
    )

    analysis = dossier.analyze_btst_tplus2_near_cluster_dossier(
        reports_root,
        candidate_ticker="300720",
        upstream_handoff_board_path=upstream_handoff_board_path,
        lane_objective_support_path=lane_objective_support_path,
    )

    assert analysis["verdict"] == "governance_followup_candidate"
    assert analysis["candidate_tier_focus"] == "governance_followup"
    assert analysis["governance_objective_support"]["support_verdict"] == "candidate_pool_false_negative_outperforms_tradeable_surface"
    assert analysis["recent_tier_verdict"] == "governance_followup_pending_evidence"
    assert analysis["promotion_readiness_verdict"] == "governance_validation_required"
    assert analysis["recent_window_count"] == 1
    assert analysis["recent_tier_window_count"] == 1
    assert analysis["governance_recent_followup_rows"][0]["decision"] == "near_miss"
    assert analysis["recent_window_summaries"][0]["supporting_window"] is True
    assert analysis["tier_focus_surface_summary"]["t_plus_2_close_return_distribution"]["mean"] == 0.0787
    assert analysis["current_plan_visibility_summary"]["current_plan_visible_trade_dates"] == ["2026-03-31"]
    assert analysis["current_plan_visibility_summary"]["current_plan_visibility_gap_trade_dates"] == ["2026-03-27"]


def test_analyze_btst_tplus2_near_cluster_dossier_marks_strong_governance_followup_payoff_confirmed(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()
    upstream_handoff_board_path = tmp_path / "btst_candidate_pool_upstream_handoff_board_latest.json"
    lane_objective_support_path = tmp_path / "btst_candidate_pool_lane_objective_support_latest.json"
    upstream_handoff_board_path.write_text(
        json.dumps(
            {
                "board_rows": [
                    {
                        "ticker": "300720",
                        "downstream_followup_lane": "t_plus_2_continuation_review",
                        "downstream_followup_status": "continuation_confirm_then_review",
                        "downstream_followup_blocker": "no_selected_persistence_or_independent_edge",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    lane_objective_support_path.write_text(
        json.dumps(
            {
                "ticker_rows": [
                    {
                        "ticker": "300720",
                        "next_close_positive_rate": 0.8,
                        "t_plus_2_positive_rate": 0.8667,
                        "t_plus_2_return_hit_rate_at_target": 0.8,
                        "mean_t_plus_2_return": 0.0787,
                        "next_high_hit_rate_at_threshold": 0.8667,
                        "closed_cycle_count": 15,
                        "support_verdict": "candidate_pool_false_negative_outperforms_tradeable_surface",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        dossier,
        "_collect_rows",
        lambda *_args, **_kwargs: [
            {
                "report_label": "window_anchor",
                "ticker": "600988",
                "candidate_source": "layer_c_watchlist",
                "metrics_payload": {
                    "breakout_freshness": 0.35,
                    "trend_acceleration": 0.48,
                    "catalyst_freshness": 0.01,
                    "layer_c_alignment": 0.49,
                    "sector_resonance": 0.13,
                    "close_strength": 0.64,
                    "t_plus_2_continuation_candidate": {"applied": True},
                },
                "next_high_return": 0.05,
                "next_close_return": -0.01,
                "t_plus_2_close_return": 0.03,
            }
        ],
    )
    monkeypatch.setattr(
        dossier,
        "load_upstream_shadow_followup_history_by_ticker",
        lambda *_args, **_kwargs: {
            "300720": [
                {"ticker": "300720", "trade_date": "20260331", "report_dir": "report_a", "decision": "near_miss"},
                {"ticker": "300720", "trade_date": "20260328", "report_dir": "report_b", "decision": "near_miss"},
                {"ticker": "300720", "trade_date": "20260325", "report_dir": "report_c", "decision": "near_miss"},
            ]
        },
    )

    analysis = dossier.analyze_btst_tplus2_near_cluster_dossier(
        reports_root,
        candidate_ticker="300720",
        upstream_handoff_board_path=upstream_handoff_board_path,
        lane_objective_support_path=lane_objective_support_path,
    )

    assert analysis["recent_tier_verdict"] == "governance_followup_payoff_confirmed"
    assert analysis["promotion_readiness_verdict"] == "watch_review_ready"


def test_analyze_btst_tplus2_near_cluster_dossier_surfaces_manifest_merge_review_ready(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()
    upstream_handoff_board_path = tmp_path / "btst_candidate_pool_upstream_handoff_board_latest.json"
    lane_objective_support_path = tmp_path / "btst_candidate_pool_lane_objective_support_latest.json"
    upstream_handoff_board_path.write_text(
        json.dumps(
            {
                "board_rows": [
                    {
                        "ticker": "300720",
                        "latest_followup_decision": "selected",
                        "downstream_followup_lane": "t_plus_2_continuation_review",
                        "downstream_followup_status": "continuation_only_confirm_then_review",
                        "downstream_followup_blocker": "no_selected_persistence_or_independent_edge",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    lane_objective_support_path.write_text(json.dumps({"ticker_rows": [{"ticker": "300720"}]}), encoding="utf-8")
    (reports_root / "report_manifest_latest.json").write_text(
        json.dumps(
            {
                "continuation_promotion_ready_summary": {
                    "focus_ticker": "300720",
                    "promotion_path_status": "merge_review_ready",
                    "promotion_merge_review_verdict": "ready_for_default_btst_merge_review",
                    "qualifying_window_buckets": ["near_miss_entries", "selected_entries"],
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(dossier, "_collect_rows", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(dossier, "_build_anchor_profile", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(dossier, "load_upstream_shadow_followup_history_by_ticker", lambda *_args, **_kwargs: {"300720": []})
    monkeypatch.setattr(
        dossier,
        "load_frozen_post_market_plans",
        lambda *_args, **_kwargs: {},
    )

    analysis = dossier.analyze_btst_tplus2_near_cluster_dossier(
        reports_root,
        candidate_ticker="300720",
        upstream_handoff_board_path=upstream_handoff_board_path,
        lane_objective_support_path=lane_objective_support_path,
    )

    assert analysis["promotion_readiness_verdict"] == "merge_review_ready"
    assert analysis["promotion_path_status"] == "merge_review_ready"
    assert analysis["promotion_merge_review_verdict"] == "ready_for_default_btst_merge_review"
    assert analysis["latest_followup_decision"] == "selected"
    assert analysis["downstream_followup_status"] == "continuation_only_confirm_then_review"
    assert analysis["qualifying_window_buckets"] == ["near_miss_entries", "selected_entries"]


def test_analyze_btst_tplus2_near_cluster_dossier_threads_final_payload(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()

    monkeypatch.setattr(dossier, "_collect_rows", lambda *_args, **_kwargs: [{"ticker": "600988"}])
    monkeypatch.setattr(dossier, "_extract_current_plan_visibility_summary", lambda *_args, **_kwargs: {"current_plan_visible_trade_dates": ["2026-03-31"]})
    monkeypatch.setattr(dossier, "_load_continuation_promotion_ready_summary", lambda *_args, **_kwargs: {"promotion_path_status": "watch_review"})
    monkeypatch.setattr(dossier, "_collect_candidate_rows_for_dossier", lambda *args, **kwargs: [{"ticker": "300505"}])
    monkeypatch.setattr(
        dossier,
        "_summarize_candidate_windows",
        lambda *args, **kwargs: {
            "per_window_summaries": [{"report_label": "window_a"}],
            "tier_counts": {"observation_candidate": 1},
            "candidate_tier_focus": "observation_candidate",
            "supporting_rows": [],
            "tier_focus_rows": [{"ticker": "300505"}],
            "surface_summary": {"evidence_case_count": 1},
            "supporting_surface_summary": {},
            "tier_focus_surface_summary": {"next_close_positive_rate": 1.0},
            "recent_window_summaries": [{"report_label": "window_a"}],
            "recent_supporting_window_count": 0,
            "recent_support_ratio": 0.0,
            "recent_supporting_surface_summary": {},
            "recent_tier_window_count": 1,
            "recent_tier_ratio": 1.0,
            "recent_tier_surface_summary": {"next_close_positive_rate": 1.0},
        },
    )
    monkeypatch.setattr(
        dossier,
        "_load_governance_context",
        lambda *args, **kwargs: {
            "governance_followup": {},
            "governance_objective_support": {},
            "governance_recent_followup_rows": [],
        },
    )
    monkeypatch.setattr(dossier, "_resolve_dossier_verdict", lambda **kwargs: "observation_only_candidate")
    monkeypatch.setattr(dossier, "_resolve_recent_validation_verdict", lambda **kwargs: "recent_support_absent")
    monkeypatch.setattr(dossier, "governance_followup_payoff_confirmed", lambda *args, **kwargs: False)
    monkeypatch.setattr(dossier, "_classify_recent_tier_verdict", lambda *args, **kwargs: "recent_tier_confirmed")
    monkeypatch.setattr(dossier, "_resolve_promotion_readiness_verdict", lambda **kwargs: "validation_queue_ready")

    analysis = dossier.analyze_btst_tplus2_near_cluster_dossier(reports_root, candidate_ticker="300505")

    assert analysis["candidate_ticker"] == "300505"
    assert analysis["candidate_row_count"] == 1
    assert analysis["tier_counts"] == {"observation_candidate": 1}
    assert analysis["recent_window_summaries"] == [{"report_label": "window_a"}]
    assert analysis["promotion_readiness_verdict"] == "validation_queue_ready"
    assert analysis["current_plan_visible_trade_dates"] == ["2026-03-31"]
