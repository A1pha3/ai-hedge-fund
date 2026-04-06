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
