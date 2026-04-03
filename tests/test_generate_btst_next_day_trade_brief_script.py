from __future__ import annotations

import json

import pandas as pd

from scripts.generate_btst_next_day_trade_brief import analyze_btst_next_day_trade_brief, render_btst_next_day_trade_brief_markdown
from src.paper_trading.btst_reporting import infer_next_trade_date


def _write_catalyst_theme_frontier(report_dir, promoted_tickers=None):
    tickers = list(promoted_tickers or ["301001"])
    (report_dir / "catalyst_theme_frontier_latest.json").write_text(
        json.dumps(
            {
                "shadow_candidate_count": len(tickers),
                "baseline_selected_count": 0,
                "recommendation": "优先跟踪 frontier promoted shadow。",
                "recommended_variant": {
                    "variant_name": "catalyst_theme_relaxed_sector_frontier",
                    "promoted_shadow_count": len(tickers),
                    "threshold_relaxation_cost": 0.09,
                    "thresholds": {"candidate_score": 0.30, "sector_resonance": 0.20},
                    "top_promoted_rows": [{"ticker": ticker} for ticker in tickers],
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (report_dir / "catalyst_theme_frontier_latest.md").write_text("# Catalyst Theme Frontier\n", encoding="utf-8")


def test_generate_btst_next_day_trade_brief_separates_short_trade_from_research(tmp_path, monkeypatch):
    report_dir = tmp_path / "report"
    trade_dir = report_dir / "selection_artifacts" / "2026-03-27"
    trade_dir.mkdir(parents=True)

    historical_report_dir = tmp_path / "paper_trading_2026-03-26_2026-03-26_dummy"
    historical_trade_dir = historical_report_dir / "selection_artifacts" / "2026-03-26"
    historical_trade_dir.mkdir(parents=True)
    (historical_report_dir / "session_summary.json").write_text("{}\n", encoding="utf-8")
    (historical_trade_dir / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "20260326",
                "target_mode": "short_trade_only",
                "selection_targets": {
                    "601000": {
                        "ticker": "601000",
                        "short_trade": {
                            "decision": "near_miss",
                            "score_target": 0.5521,
                            "confidence": 0.811,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "positive_tags": ["fresh_catalyst_support"],
                            "top_reasons": ["trend_acceleration=0.75"],
                            "gate_status": {"score": "near_miss", "structural": "pass"},
                            "metrics_payload": {
                                "breakout_freshness": 0.801,
                                "trend_acceleration": 0.751,
                                "volume_expansion_quality": 0.332,
                                "close_strength": 0.844,
                                "catalyst_freshness": 0.734,
                            },
                            "explainability_payload": {"candidate_source": "short_trade_boundary"},
                        },
                    },
                    "300999": {
                        "ticker": "300999",
                        "short_trade": {
                            "decision": "rejected",
                            "score_target": 0.3341,
                            "confidence": 0.6911,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "positive_tags": ["fresh_catalyst_support"],
                            "top_reasons": ["catalyst_freshness=0.83"],
                            "rejection_reasons": ["score_short_below_threshold"],
                            "gate_status": {"data": "pass", "structural": "pass", "score": "fail"},
                            "metrics_payload": {
                                "breakout_freshness": 0.411,
                                "trend_acceleration": 0.392,
                                "volume_expansion_quality": 0.301,
                                "close_strength": 0.465,
                                "catalyst_freshness": 0.834,
                                "thresholds": {"near_miss_threshold": 0.52}
                            },
                            "explainability_payload": {"candidate_source": "short_trade_boundary"},
                        },
                    }
                },
                "catalyst_theme_candidates": [
                    {
                        "ticker": "300999",
                        "decision": "catalyst_theme",
                        "score_target": 0.4011,
                        "confidence": 0.4011,
                        "preferred_entry_mode": "theme_research_followup",
                        "positive_tags": ["strong_catalyst_freshness"],
                        "top_reasons": ["catalyst_freshness=0.81", "sector_resonance=0.25"],
                        "candidate_source": "catalyst_theme",
                        "gate_status": {"data": "pass", "structural": "fail", "score": "proxy_only"},
                        "blockers": ["stale_trend_repair_penalty"],
                        "promotion_trigger": "若催化继续扩散并形成量价确认，可升级到 short-trade shadow 观察。",
                        "metrics": {
                            "breakout_freshness": 0.301,
                            "trend_acceleration": 0.251,
                            "close_strength": 0.571,
                            "sector_resonance": 0.250,
                            "catalyst_freshness": 0.812,
                        },
                    }
                ],
                "catalyst_theme_shadow_candidates": [
                    {
                        "ticker": "301001",
                        "decision": "catalyst_theme_shadow",
                        "score_target": 0.3874,
                        "confidence": 0.3874,
                        "preferred_entry_mode": "theme_research_followup",
                        "positive_tags": ["strong_catalyst_freshness"],
                        "top_reasons": ["candidate_score=0.39", "total_shortfall=0.06"],
                        "candidate_source": "catalyst_theme_shadow",
                        "gate_status": {"data": "pass", "structural": "fail", "score": "shadow"},
                        "blockers": ["candidate_score_below_catalyst_theme_floor"],
                        "filter_reason": "candidate_score_below_catalyst_theme_floor",
                        "threshold_shortfalls": {"candidate_score": 0.06},
                        "failed_threshold_count": 1,
                        "total_shortfall": 0.06,
                        "promotion_trigger": "若催化继续发酵，可升级到正式题材研究池。",
                        "metrics": {
                            "breakout_freshness": 0.301,
                            "trend_acceleration": 0.241,
                            "close_strength": 0.541,
                            "sector_resonance": 0.182,
                            "catalyst_freshness": 0.812,
                        },
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "src.paper_trading.btst_reporting._extract_next_day_outcome",
        lambda ticker, trade_date, price_cache: {
            "data_status": "ok",
            "next_trade_date": "2026-03-27",
            "next_open_return": 0.008,
            "next_high_return": 0.031,
            "next_close_return": 0.014,
            "next_open_to_close_return": 0.006,
        },
    )

    (report_dir / "session_summary.json").write_text(
        json.dumps(
            {
                "plan_generation": {
                    "selection_target": "short_trade_only",
                }
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_catalyst_theme_frontier(report_dir)

    (trade_dir / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "20260327",
                "target_mode": "short_trade_only",
                "dual_target_summary": {
                    "short_trade_selected_count": 1,
                    "short_trade_near_miss_count": 1,
                    "short_trade_blocked_count": 2,
                    "short_trade_rejected_count": 6,
                    "research_selected_count": 2,
                },
                "selection_targets": {
                    "300757": {
                        "ticker": "300757",
                        "short_trade": {
                            "decision": "selected",
                            "score_target": 0.5907,
                            "confidence": 0.935,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "positive_tags": ["fresh_breakout_candidate"],
                            "top_reasons": ["breakout_freshness=0.94", "catalyst_freshness=0.88"],
                            "gate_status": {"score": "pass", "structural": "pass"},
                            "metrics_payload": {
                                "breakout_freshness": 0.935,
                                "trend_acceleration": 0.7275,
                                "volume_expansion_quality": 0.398,
                                "close_strength": 0.9019,
                                "catalyst_freshness": 0.8793,
                            },
                            "explainability_payload": {
                                "candidate_source": "short_trade_boundary",
                            },
                        },
                    },
                    "601869": {
                        "ticker": "601869",
                        "short_trade": {
                            "decision": "near_miss",
                            "score_target": 0.5540,
                            "confidence": 0.8667,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "positive_tags": ["fresh_catalyst_support"],
                            "top_reasons": ["trend_acceleration=0.76"],
                            "gate_status": {"score": "near_miss", "structural": "pass"},
                            "metrics_payload": {
                                "breakout_freshness": 0.8667,
                                "trend_acceleration": 0.7637,
                                "volume_expansion_quality": 0.3434,
                                "close_strength": 0.8895,
                                "catalyst_freshness": 0.7456,
                            },
                            "explainability_payload": {
                                "candidate_source": "upstream_liquidity_corridor_shadow",
                                "replay_context": {
                                    "candidate_pool_lane": "layer_a_liquidity_corridor",
                                    "candidate_pool_rank": 301,
                                    "candidate_pool_avg_amount_share_of_cutoff": 0.97,
                                    "candidate_pool_avg_amount_share_of_min_gate": 1.12,
                                },
                            },
                        },
                    },
                    "300442": {
                        "ticker": "300442",
                        "short_trade": {
                            "decision": "rejected",
                            "score_target": 0.3126,
                            "confidence": 0.7073,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "positive_tags": ["fresh_catalyst_support"],
                            "top_reasons": ["catalyst_freshness=0.71", "score_short=0.31"],
                            "rejection_reasons": ["score_short_below_threshold"],
                            "gate_status": {"data": "pass", "execution": "proxy_only", "structural": "pass", "score": "fail"},
                            "metrics_payload": {
                                "breakout_freshness": 0.421,
                                "trend_acceleration": 0.384,
                                "volume_expansion_quality": 0.318,
                                "close_strength": 0.447,
                                "catalyst_freshness": 0.712,
                                "thresholds": {"near_miss_threshold": 0.52},
                            },
                            "explainability_payload": {
                                "candidate_source": "post_gate_liquidity_competition_shadow",
                                "replay_context": {
                                    "candidate_pool_lane": "post_gate_liquidity_competition",
                                    "candidate_pool_rank": 304,
                                    "candidate_pool_avg_amount_share_of_cutoff": 0.91,
                                    "candidate_pool_avg_amount_share_of_min_gate": 1.05,
                                },
                            },
                        },
                    },
                    "002001": {
                        "ticker": "002001",
                        "research": {
                            "decision": "selected",
                            "score_target": 0.3912,
                        },
                        "short_trade": {
                            "decision": "rejected",
                            "score_target": 0.3130,
                            "confidence": 0.7012,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "positive_tags": ["fresh_catalyst_support"],
                            "top_reasons": ["catalyst_freshness=0.74", "breakout_freshness=0.68"],
                            "rejection_reasons": ["score_short_below_threshold"],
                            "gate_status": {"data": "pass", "structural": "pass", "score": "fail"},
                            "metrics_payload": {
                                "breakout_freshness": 0.681,
                                "trend_acceleration": 0.553,
                                "volume_expansion_quality": 0.287,
                                "close_strength": 0.621,
                                "catalyst_freshness": 0.744,
                            },
                            "explainability_payload": {"candidate_source": "short_trade_boundary"},
                        },
                        "delta_summary": ["research target selected while short trade target stays rejected"],
                    },
                    "002002": {
                        "ticker": "002002",
                        "research": {
                            "decision": "selected",
                            "score_target": 0.2812,
                        },
                        "short_trade": {
                            "decision": "rejected",
                            "score_target": 0.1130,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                        },
                        "delta_summary": ["research target selected while short trade target stays rejected"],
                    },
                },
                "catalyst_theme_candidates": [
                    {
                        "ticker": "300999",
                        "decision": "catalyst_theme",
                        "score_target": 0.4126,
                        "confidence": 0.4126,
                        "preferred_entry_mode": "theme_research_followup",
                        "positive_tags": ["strong_catalyst_freshness"],
                        "top_reasons": ["catalyst_freshness=0.84", "sector_resonance=0.25"],
                        "candidate_source": "catalyst_theme",
                        "gate_status": {"data": "pass", "structural": "fail", "score": "proxy_only"},
                        "blockers": ["stale_trend_repair_penalty"],
                        "promotion_trigger": "若催化继续扩散并形成量价确认，可升级到 short-trade shadow 观察。",
                        "metrics": {
                            "breakout_freshness": 0.321,
                            "trend_acceleration": 0.264,
                            "close_strength": 0.582,
                            "sector_resonance": 0.250,
                            "catalyst_freshness": 0.844,
                        },
                    }
                ],
                "catalyst_theme_shadow_candidates": [
                    {
                        "ticker": "301001",
                        "decision": "catalyst_theme_shadow",
                        "score_target": 0.3874,
                        "confidence": 0.3874,
                        "preferred_entry_mode": "theme_research_followup",
                        "positive_tags": ["strong_catalyst_freshness"],
                        "top_reasons": ["candidate_score=0.39", "total_shortfall=0.06"],
                        "candidate_source": "catalyst_theme_shadow",
                        "gate_status": {"data": "pass", "structural": "fail", "score": "shadow"},
                        "blockers": ["candidate_score_below_catalyst_theme_floor"],
                        "filter_reason": "candidate_score_below_catalyst_theme_floor",
                        "threshold_shortfalls": {"candidate_score": 0.06},
                        "failed_threshold_count": 1,
                        "total_shortfall": 0.06,
                        "promotion_trigger": "若催化继续发酵，可升级到正式题材研究池。",
                        "metrics": {
                            "breakout_freshness": 0.301,
                            "trend_acceleration": 0.241,
                            "close_strength": 0.541,
                            "sector_resonance": 0.182,
                            "catalyst_freshness": 0.812,
                        },
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_btst_next_day_trade_brief(report_dir, trade_date="2026-03-27", next_trade_date="2026-03-30")

    assert analysis["primary_entry"]["ticker"] == "300757"
    assert [entry["ticker"] for entry in analysis["selected_entries"]] == ["300757"]
    assert analysis["selected_entries"][0]["historical_prior"]["summary"] is not None
    assert [entry["ticker"] for entry in analysis["near_miss_entries"]] == ["601869"]
    assert analysis["near_miss_entries"][0]["candidate_source"] == "upstream_liquidity_corridor_shadow"
    assert [entry["ticker"] for entry in analysis["opportunity_pool_entries"]] == ["300442"]
    assert analysis["opportunity_pool_entries"][0]["candidate_source"] == "post_gate_liquidity_competition_shadow"
    assert [entry["ticker"] for entry in analysis["research_upside_radar_entries"]] == ["002001"]
    assert analysis["research_upside_radar_entries"][0]["historical_prior"]["summary"] is not None
    assert [entry["ticker"] for entry in analysis["catalyst_theme_entries"]] == ["300999"]
    assert analysis["catalyst_theme_entries"][0]["historical_prior"]["summary"] is not None
    assert [entry["ticker"] for entry in analysis["catalyst_theme_shadow_entries"]] == ["301001"]
    assert analysis["summary"]["catalyst_theme_frontier_promoted_count"] == 1
    assert analysis["summary"]["upstream_shadow_candidate_count"] == 2
    assert analysis["summary"]["upstream_shadow_promotable_count"] == 1
    assert [entry["ticker"] for entry in analysis["upstream_shadow_entries"]] == ["601869", "300442"]
    assert analysis["upstream_shadow_summary"]["lane_counts"] == {
        "layer_a_liquidity_corridor": 1,
        "post_gate_liquidity_competition": 1,
    }
    assert analysis["catalyst_theme_frontier_priority"]["promoted_tickers"] == ["301001"]
    assert [entry["ticker"] for entry in analysis["excluded_research_entries"]] == ["002002"]
    assert "300757" in analysis["recommendation"]
    assert "601869" in analysis["recommendation"]
    assert "300442" in analysis["recommendation"]
    assert "002001" in analysis["recommendation"]
    assert "300999" in analysis["recommendation"]
    assert "301001" in analysis["recommendation"]
    assert analysis["selected_entries"][0]["historical_prior"]["execution_quality_label"] == "balanced_confirmation"


def test_generate_btst_next_day_trade_brief_includes_replay_only_upstream_shadow_observation_entries(tmp_path):
    report_dir = tmp_path / "report"
    trade_dir = report_dir / "selection_artifacts" / "2026-04-01"
    trade_dir.mkdir(parents=True)

    (report_dir / "session_summary.json").write_text(
        json.dumps({"plan_generation": {"selection_target": "short_trade_only"}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (trade_dir / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "20260401",
                "target_mode": "short_trade_only",
                "selection_targets": {},
                "dual_target_summary": {},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (trade_dir / "selection_target_replay_input.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-04-01",
                "target_mode": "short_trade_only",
                "source_summary": {
                    "watchlist_count": 0,
                    "rejected_entry_count": 0,
                    "supplemental_short_trade_entry_count": 0,
                    "upstream_shadow_observation_entry_count": 1,
                    "supplemental_catalyst_theme_entry_count": 0,
                    "buy_order_ticker_count": 0,
                },
                "selection_targets": {},
                "upstream_shadow_observation_entries": [
                    {
                        "ticker": "301292",
                        "decision": "observation",
                        "candidate_source": "post_gate_liquidity_competition_shadow",
                        "upstream_candidate_source": "candidate_pool_truncated_after_filters",
                        "candidate_reason_codes": ["post_gate_liquidity_competition_shadow"],
                        "candidate_pool_lane": "post_gate_liquidity_competition",
                        "candidate_pool_rank": 575,
                        "candidate_pool_avg_amount_share_of_cutoff": 0.6032,
                        "candidate_pool_avg_amount_share_of_min_gate": 18.5767,
                        "score_target": 0.318,
                        "confidence": 0.318,
                        "filter_reason": "breakout_freshness_below_short_trade_boundary_floor",
                        "top_reasons": ["candidate_score=0.32"],
                        "promotion_trigger": "仅作上游影子补票观察。",
                        "gate_status": {"data": "pass", "structural": "pass", "score": "shadow_observation"},
                        "metrics": {
                            "breakout_freshness": 0.11,
                            "trend_acceleration": 0.33,
                            "volume_expansion_quality": 0.28,
                            "close_strength": 0.44,
                            "catalyst_freshness": 0.21,
                            "candidate_score": 0.318,
                        },
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_btst_next_day_trade_brief(report_dir, trade_date="2026-04-01", next_trade_date="2026-04-02")

    assert analysis["summary"]["upstream_shadow_candidate_count"] == 1
    assert analysis["summary"]["upstream_shadow_promotable_count"] == 0
    assert [entry["ticker"] for entry in analysis["upstream_shadow_entries"]] == ["301292"]
    assert analysis["upstream_shadow_entries"][0]["decision"] == "observation"
    assert analysis["upstream_shadow_entries"][0]["candidate_source"] == "post_gate_liquidity_competition_shadow"
    assert "301292" in analysis["recommendation"]


def test_render_btst_next_day_trade_brief_markdown_mentions_selected_and_excluded_research(tmp_path):
    report_dir = tmp_path / "report"
    trade_dir = report_dir / "selection_artifacts" / "2026-03-27"
    trade_dir.mkdir(parents=True)
    (trade_dir / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "20260327",
                "target_mode": "short_trade_only",
                "selection_targets": {
                    "300757": {
                        "ticker": "300757",
                        "short_trade": {
                            "decision": "selected",
                            "score_target": 0.5907,
                            "confidence": 0.935,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "positive_tags": [],
                            "top_reasons": [],
                            "gate_status": {},
                            "metrics_payload": {},
                            "explainability_payload": {"candidate_source": "short_trade_boundary"},
                        },
                    },
                    "002001": {
                        "ticker": "002001",
                        "research": {"decision": "selected", "score_target": 0.3912},
                        "short_trade": {
                            "decision": "rejected",
                            "score_target": 0.3130,
                            "confidence": 0.7012,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "positive_tags": ["fresh_catalyst_support"],
                            "top_reasons": ["catalyst_freshness=0.74"],
                            "rejection_reasons": ["score_short_below_threshold"],
                            "gate_status": {"data": "pass", "structural": "pass", "score": "fail"},
                            "metrics_payload": {
                                "breakout_freshness": 0.681,
                                "trend_acceleration": 0.553,
                                "volume_expansion_quality": 0.287,
                                "close_strength": 0.621,
                                "catalyst_freshness": 0.744,
                            },
                            "explainability_payload": {"candidate_source": "short_trade_boundary"},
                        },
                        "delta_summary": ["research target selected while short trade target stays rejected"],
                    },
                    "601869": {
                        "ticker": "601869",
                        "short_trade": {
                            "decision": "near_miss",
                            "score_target": 0.5540,
                            "confidence": 0.8667,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "positive_tags": ["fresh_catalyst_support"],
                            "top_reasons": ["trend_acceleration=0.76"],
                            "gate_status": {"score": "near_miss", "structural": "pass"},
                            "metrics_payload": {
                                "breakout_freshness": 0.8667,
                                "trend_acceleration": 0.7637,
                                "volume_expansion_quality": 0.3434,
                                "close_strength": 0.8895,
                                "catalyst_freshness": 0.7456,
                            },
                            "explainability_payload": {
                                "candidate_source": "upstream_liquidity_corridor_shadow",
                                "replay_context": {"candidate_pool_lane": "layer_a_liquidity_corridor", "candidate_pool_rank": 301},
                            },
                        },
                    },
                    "002002": {
                        "ticker": "002002",
                        "research": {"decision": "selected", "score_target": 0.2812},
                        "short_trade": {"decision": "rejected", "score_target": 0.1130, "preferred_entry_mode": "next_day_breakout_confirmation"},
                        "delta_summary": ["research target selected while short trade target stays rejected"],
                    },
                    "300442": {
                        "ticker": "300442",
                        "short_trade": {
                            "decision": "rejected",
                            "score_target": 0.3126,
                            "confidence": 0.7073,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "positive_tags": ["fresh_catalyst_support"],
                            "top_reasons": ["catalyst_freshness=0.71", "score_short=0.31"],
                            "rejection_reasons": ["score_short_below_threshold"],
                            "gate_status": {"data": "pass", "execution": "proxy_only", "structural": "pass", "score": "fail"},
                            "metrics_payload": {
                                "breakout_freshness": 0.421,
                                "trend_acceleration": 0.384,
                                "volume_expansion_quality": 0.318,
                                "close_strength": 0.447,
                                "catalyst_freshness": 0.712,
                                "thresholds": {"near_miss_threshold": 0.52},
                            },
                            "explainability_payload": {"candidate_source": "short_trade_boundary"},
                        },
                    },
                },
                "catalyst_theme_candidates": [
                    {
                        "ticker": "300999",
                        "decision": "catalyst_theme",
                        "score_target": 0.4126,
                        "confidence": 0.4126,
                        "preferred_entry_mode": "theme_research_followup",
                        "positive_tags": ["strong_catalyst_freshness"],
                        "top_reasons": ["catalyst_freshness=0.84", "sector_resonance=0.25"],
                        "candidate_source": "catalyst_theme",
                        "gate_status": {"data": "pass", "structural": "fail", "score": "proxy_only"},
                        "blockers": ["stale_trend_repair_penalty"],
                        "promotion_trigger": "若催化继续扩散并形成量价确认，可升级到 short-trade shadow 观察。",
                        "metrics": {
                            "breakout_freshness": 0.321,
                            "trend_acceleration": 0.264,
                            "close_strength": 0.582,
                            "sector_resonance": 0.250,
                            "catalyst_freshness": 0.844,
                        },
                    }
                ],
                "catalyst_theme_shadow_candidates": [
                    {
                        "ticker": "301001",
                        "decision": "catalyst_theme_shadow",
                        "score_target": 0.3874,
                        "confidence": 0.3874,
                        "preferred_entry_mode": "theme_research_followup",
                        "positive_tags": ["strong_catalyst_freshness"],
                        "top_reasons": ["candidate_score=0.39", "total_shortfall=0.06"],
                        "candidate_source": "catalyst_theme_shadow",
                        "gate_status": {"data": "pass", "structural": "fail", "score": "shadow"},
                        "blockers": ["candidate_score_below_catalyst_theme_floor"],
                        "filter_reason": "candidate_score_below_catalyst_theme_floor",
                        "threshold_shortfalls": {"candidate_score": 0.06},
                        "failed_threshold_count": 1,
                        "total_shortfall": 0.06,
                        "promotion_trigger": "若催化继续发酵，可升级到正式题材研究池。",
                        "metrics": {
                            "breakout_freshness": 0.301,
                            "trend_acceleration": 0.241,
                            "close_strength": 0.541,
                            "sector_resonance": 0.182,
                            "catalyst_freshness": 0.812,
                        },
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_catalyst_theme_frontier(report_dir)

    analysis = analyze_btst_next_day_trade_brief(report_dir, trade_date="2026-03-27", next_trade_date="2026-03-30")
    markdown = render_btst_next_day_trade_brief_markdown(analysis)

    assert "# BTST Next-Day Trade Brief" in markdown
    assert "### 300757" in markdown
    assert "historical_summary" in markdown
    assert "### 300442" in markdown
    assert "historical_summary" in markdown
    assert "Research Upside Radar" in markdown
    assert "Catalyst Theme Research Lane" in markdown
    assert "Catalyst Theme Frontier Priority" in markdown
    assert "Catalyst Theme Shadow Watch" in markdown
    assert "Upstream Shadow Recall" in markdown
    assert "### 300999" in markdown
    assert "### 301001" in markdown
    assert "### 601869" in markdown
    assert "frontier_role: promoted_shadow_priority" in markdown
    assert "### 002001" in markdown
    assert "### 002002" in markdown
    assert "Opportunity Expansion Pool" in markdown
    assert "Research Picks Excluded From Short-Trade Brief" in markdown
    assert "candidate_pool_lane: layer_a_liquidity_corridor" in markdown


def test_infer_next_trade_date_uses_earliest_open_calendar_date(monkeypatch):
    monkeypatch.setattr("src.paper_trading.btst_reporting._get_pro", lambda: object())
    monkeypatch.setattr(
        "src.paper_trading.btst_reporting._cached_tushare_dataframe_call",
        lambda *args, **kwargs: pd.DataFrame(
            [
                {"cal_date": "20260409", "is_open": 1},
                {"cal_date": "20260327", "is_open": 1},
                {"cal_date": "20260408", "is_open": 1},
            ]
        ),
    )

    assert infer_next_trade_date("2026-03-26") == "2026-03-27"