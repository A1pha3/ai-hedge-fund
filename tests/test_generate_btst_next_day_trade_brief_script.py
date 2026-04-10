from __future__ import annotations

import json

import pandas as pd

from scripts.generate_btst_next_day_trade_brief import analyze_btst_next_day_trade_brief, render_btst_next_day_trade_brief_markdown
import src.paper_trading.btst_reporting as btst_reporting
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


def test_build_watch_candidate_historical_prior_prefers_family_source_score_scope(monkeypatch):
    captured: dict[str, object] = {}
    entry = {"ticker": "002001", "candidate_source": "catalyst_theme"}
    historical_rows = [
        {"ticker": "002001", "watch_candidate_family": "catalyst_theme", "candidate_source": "catalyst_theme", "score_bucket": "high", "catalyst_bucket": "fresh"},
        {"ticker": "300001", "watch_candidate_family": "catalyst_theme", "candidate_source": "catalyst_theme", "score_bucket": "high", "catalyst_bucket": "fresh"},
        {"ticker": "300002", "watch_candidate_family": "catalyst_theme", "candidate_source": "catalyst_theme", "score_bucket": "high", "catalyst_bucket": "fresh"},
        {"ticker": "300003", "watch_candidate_family": "catalyst_theme", "candidate_source": "other_source", "score_bucket": "high", "catalyst_bucket": "fresh"},
    ]

    monkeypatch.setattr(
        btst_reporting,
        "_decorate_watch_candidate_history_entry",
        lambda raw_entry, family: {**raw_entry, "ticker": "002001", "candidate_source": "catalyst_theme", "score_bucket": "high", "catalyst_bucket": "fresh"},
    )

    def fake_summarize(rows, price_cache):
        captured["applied_rows"] = list(rows)
        return {"sample_count": len(rows), "evaluable_count": len(rows), "next_high_hit_rate_at_threshold": 1.0, "next_close_positive_rate": 1.0}

    monkeypatch.setattr(btst_reporting, "_classify_historical_prior", lambda *args: ("supportive", "high"))
    monkeypatch.setattr(btst_reporting, "_classify_execution_quality_prior", lambda *args: {"execution_quality_label": "close_continuation"})
    monkeypatch.setattr(btst_reporting, "_summarize_historical_opportunity_rows", fake_summarize)

    def fake_summary(**kwargs):
        captured["summary_kwargs"] = kwargs
        return "summary"

    monkeypatch.setattr(btst_reporting, "_build_historical_prior_summary", fake_summary)

    prior = btst_reporting._build_watch_candidate_historical_prior(entry, historical_rows, {}, family="catalyst_theme")

    assert prior["applied_scope"] == "family_source_score_catalyst"
    assert len(captured["applied_rows"]) == 3
    assert prior["same_ticker_sample_count"] == 1
    assert prior["same_family_sample_count"] == 4
    assert prior["same_family_source_sample_count"] == 3
    assert prior["same_family_source_score_catalyst_sample_count"] == 3


def test_build_watch_candidate_historical_prior_falls_back_to_same_ticker_when_no_broader_scope(monkeypatch):
    historical_rows = [
        {"ticker": "002001", "watch_candidate_family": "other_family", "candidate_source": "other_source", "score_bucket": "mid", "catalyst_bucket": "old"},
    ]

    monkeypatch.setattr(
        btst_reporting,
        "_decorate_watch_candidate_history_entry",
        lambda raw_entry, family: {**raw_entry, "ticker": "002001", "candidate_source": "catalyst_theme", "score_bucket": "high", "catalyst_bucket": "fresh"},
    )
    monkeypatch.setattr(
        btst_reporting,
        "_summarize_historical_opportunity_rows",
        lambda rows, price_cache: {"sample_count": len(rows), "evaluable_count": len(rows), "next_high_hit_rate_at_threshold": None, "next_close_positive_rate": None},
    )
    monkeypatch.setattr(btst_reporting, "_classify_historical_prior", lambda *args: ("unknown", "normal"))
    monkeypatch.setattr(btst_reporting, "_classify_execution_quality_prior", lambda *args: {"execution_quality_label": "unknown"})
    monkeypatch.setattr(btst_reporting, "_build_historical_prior_summary", lambda **kwargs: "fallback-summary")

    prior = btst_reporting._build_watch_candidate_historical_prior({"ticker": "002001", "candidate_source": "catalyst_theme"}, historical_rows, {}, family="catalyst_theme")

    assert prior["applied_scope"] == "same_ticker"
    assert prior["sample_count"] == 1
    assert prior["summary"] == "fallback-summary"


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
                        "candidate_reason_codes": ["short_trade_candidate_score_ranked", "short_trade_prequalified"],
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
                        "candidate_reason_codes": ["upstream_shadow_release_candidate"],
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
                                "upstream_shadow_catalyst_relief": {
                                    "enabled": True,
                                    "applied": True,
                                    "reason": "upstream_shadow_catalyst_relief",
                                },
                                "replay_context": {
                                    "candidate_pool_lane": "layer_a_liquidity_corridor",
                                    "candidate_pool_rank": 301,
                                    "candidate_pool_avg_amount_share_of_cutoff": 0.97,
                                    "candidate_pool_avg_amount_share_of_min_gate": 1.12,
                                },
                            },
                            "historical_prior": {
                                "applied_scope": "same_ticker",
                                "sample_count": 2,
                                "evaluable_count": 2,
                                "execution_quality_label": "close_continuation",
                                "next_close_positive_rate": 1.0,
                                "next_open_to_close_return_mean": 0.031,
                                "summary": "同票历史延续性强，允许保留为 close-continuation near-miss。",
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
                        "candidate_reason_codes": [
                            "catalyst_theme_candidate_score_ranked",
                            "catalyst_theme_research_candidate",
                            "catalyst_theme_short_trade_carryover_candidate",
                        ],
                        "short_trade_catalyst_relief": {
                            "enabled": True,
                            "reason": "catalyst_theme_short_trade_carryover",
                            "catalyst_freshness_floor": 1.0,
                            "near_miss_threshold": 0.44,
                        },
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
    assert analysis["near_miss_entries"][0]["candidate_reason_codes"] == ["upstream_shadow_release_candidate"]
    assert analysis["near_miss_entries"][0]["short_trade_catalyst_relief_reason"] == "upstream_shadow_catalyst_relief"
    assert analysis["near_miss_entries"][0]["historical_prior"]["execution_quality_label"] == "close_continuation"
    assert analysis["near_miss_entries"][0]["historical_prior"]["applied_scope"] == "same_ticker"
    assert analysis["opportunity_pool_entries"] == []
    assert [entry["ticker"] for entry in analysis["no_history_observer_entries"]] == ["300442"]
    assert analysis["no_history_observer_entries"][0]["candidate_source"] == "post_gate_liquidity_competition_shadow"
    assert analysis["summary"]["no_history_observer_count"] == 1
    assert [entry["ticker"] for entry in analysis["research_upside_radar_entries"]] == ["002001"]
    assert analysis["research_upside_radar_entries"][0]["historical_prior"]["summary"] is not None
    assert [entry["ticker"] for entry in analysis["catalyst_theme_entries"]] == ["300999"]
    assert analysis["catalyst_theme_entries"][0]["historical_prior"]["summary"] is not None
    assert "catalyst_theme_short_trade_carryover_candidate" in analysis["catalyst_theme_entries"][0]["candidate_reason_codes"]
    assert analysis["catalyst_theme_entries"][0]["short_trade_catalyst_relief_reason"] == "catalyst_theme_short_trade_carryover"
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


def test_generate_btst_next_day_trade_brief_demotes_weak_historical_near_miss_into_opportunity_pool(tmp_path, monkeypatch):
    report_dir = tmp_path / "report"
    trade_dir = report_dir / "selection_artifacts" / "2026-04-06"
    trade_dir.mkdir(parents=True)

    (report_dir / "session_summary.json").write_text(
        json.dumps({"plan_generation": {"selection_target": "short_trade_only"}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _write_catalyst_theme_frontier(report_dir, promoted_tickers=[])
    (trade_dir / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "20260406",
                "target_mode": "short_trade_only",
                "selection_targets": {
                    "603778": {
                        "ticker": "603778",
                        "short_trade": {
                            "decision": "near_miss",
                            "score_target": 0.4512,
                            "confidence": 0.79,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "positive_tags": ["fresh_breakout_candidate"],
                            "top_reasons": ["trend_acceleration=0.79"],
                            "gate_status": {"score": "near_miss", "structural": "pass"},
                            "metrics_payload": {
                                "breakout_freshness": 0.73,
                                "trend_acceleration": 0.79,
                                "volume_expansion_quality": 0.31,
                                "close_strength": 0.86,
                                "catalyst_freshness": 0.42,
                            },
                            "explainability_payload": {
                                "candidate_source": "post_gate_liquidity_competition_shadow",
                            },
                        },
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "src.paper_trading.btst_reporting._collect_historical_watch_candidate_rows",
        lambda report_dir, actual_trade_date: {
            "rows": [
                {
                    "ticker": "603778",
                    "trade_date": "2026-03-31",
                    "candidate_source": "post_gate_liquidity_competition_shadow",
                    "watch_candidate_family": "near_miss",
                    "score_bucket": "0.45_0.50",
                    "catalyst_bucket": "0.40_0.50",
                },
                {
                    "ticker": "603778",
                    "trade_date": "2026-04-01",
                    "candidate_source": "post_gate_liquidity_competition_shadow",
                    "watch_candidate_family": "near_miss",
                    "score_bucket": "0.45_0.50",
                    "catalyst_bucket": "0.40_0.50",
                },
                {
                    "ticker": "603778",
                    "trade_date": "2026-04-02",
                    "candidate_source": "post_gate_liquidity_competition_shadow",
                    "watch_candidate_family": "near_miss",
                    "score_bucket": "0.45_0.50",
                    "catalyst_bucket": "0.40_0.50",
                },
            ],
            "historical_report_dirs": [],
            "contributing_report_count": 3,
            "family_counts": {"near_miss": 3, "opportunity_pool": 0, "selected": 0},
        },
    )
    monkeypatch.setattr(
        "src.paper_trading.btst_reporting._extract_next_day_outcome",
        lambda ticker, trade_date, price_cache: {
            "data_status": "ok",
            "next_trade_date": "2026-04-07",
            "next_open_return": -0.01,
            "next_high_return": 0.0,
            "next_close_return": -0.02,
            "next_open_to_close_return": -0.01,
        },
    )

    analysis = analyze_btst_next_day_trade_brief(report_dir, trade_date="2026-04-06", next_trade_date="2026-04-07")

    assert analysis["summary"]["short_trade_near_miss_count"] == 0
    assert analysis["summary"]["short_trade_opportunity_pool_count"] == 0
    assert analysis["summary"]["weak_history_pruned_count"] == 1
    assert analysis["near_miss_entries"] == []
    assert analysis["opportunity_pool_entries"] == []
    assert [entry["ticker"] for entry in analysis["weak_history_pruned_entries"]] == ["603778"]
    assert analysis["weak_history_pruned_entries"][0]["decision"] == "near_miss"
    assert analysis["weak_history_pruned_entries"][0]["historical_prior"]["demoted_from_near_miss"] is True
    assert analysis["weak_history_pruned_entries"][0]["historical_prior"]["demotion_reason"] == "historical_zero_follow_through"
    assert analysis["weak_history_pruned_entries"][0]["historical_prior"]["execution_quality_label"] == "zero_follow_through"
    assert analysis["weak_history_pruned_entries"][0]["historical_prior"]["execution_priority"] == "low"


def test_generate_btst_next_day_trade_brief_rebuckets_intraday_selected_and_reorders_opportunity_pool(tmp_path, monkeypatch):
    report_dir = tmp_path / "report"
    trade_dir = report_dir / "selection_artifacts" / "2026-04-06"
    trade_dir.mkdir(parents=True)

    (report_dir / "session_summary.json").write_text(
        json.dumps({"plan_generation": {"selection_target": "short_trade_only"}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _write_catalyst_theme_frontier(report_dir, promoted_tickers=[])
    (trade_dir / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "20260406",
                "target_mode": "short_trade_only",
                "selection_targets": {
                    "300720": {
                        "ticker": "300720",
                        "short_trade": {
                            "decision": "selected",
                            "score_target": 0.4555,
                            "confidence": 0.81,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "positive_tags": ["fresh_breakout_candidate"],
                            "top_reasons": ["trend_acceleration=0.85"],
                            "gate_status": {"score": "pass", "structural": "pass"},
                            "metrics_payload": {
                                "breakout_freshness": 0.58,
                                "trend_acceleration": 0.85,
                                "volume_expansion_quality": 0.41,
                                "close_strength": 0.74,
                                "catalyst_freshness": 0.32,
                            },
                            "explainability_payload": {"candidate_source": "upstream_liquidity_corridor_shadow"},
                        },
                    },
                    "300757": {
                        "ticker": "300757",
                        "short_trade": {
                            "decision": "rejected",
                            "score_target": 0.3924,
                            "confidence": 0.72,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "positive_tags": ["fresh_breakout_candidate"],
                            "top_reasons": ["trend_acceleration=0.72"],
                            "rejection_reasons": ["score_short_below_threshold"],
                            "gate_status": {"data": "pass", "structural": "pass", "score": "fail"},
                            "metrics_payload": {
                                "breakout_freshness": 0.46,
                                "trend_acceleration": 0.72,
                                "volume_expansion_quality": 0.34,
                                "close_strength": 0.61,
                                "catalyst_freshness": 0.41,
                                "thresholds": {"near_miss_threshold": 0.52},
                            },
                            "explainability_payload": {"candidate_source": "short_trade_boundary"},
                        },
                    },
                    "600522": {
                        "ticker": "600522",
                        "short_trade": {
                            "decision": "rejected",
                            "score_target": 0.3980,
                            "confidence": 0.7,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "positive_tags": ["fresh_breakout_candidate"],
                            "top_reasons": ["trend_acceleration=0.74"],
                            "rejection_reasons": ["score_short_below_threshold"],
                            "gate_status": {"data": "pass", "structural": "pass", "score": "fail"},
                            "metrics_payload": {
                                "breakout_freshness": 0.46,
                                "trend_acceleration": 0.74,
                                "volume_expansion_quality": 0.31,
                                "close_strength": 0.58,
                                "catalyst_freshness": 0.37,
                                "thresholds": {"near_miss_threshold": 0.52},
                            },
                            "explainability_payload": {"candidate_source": "short_trade_boundary"},
                        },
                    },
                    "603778": {
                        "ticker": "603778",
                        "short_trade": {
                            "decision": "rejected",
                            "score_target": 0.4512,
                            "confidence": 0.76,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "positive_tags": ["fresh_breakout_candidate"],
                            "top_reasons": ["trend_acceleration=0.79"],
                            "rejection_reasons": ["score_short_below_threshold"],
                            "gate_status": {"data": "pass", "structural": "pass", "score": "fail"},
                            "metrics_payload": {
                                "breakout_freshness": 0.88,
                                "trend_acceleration": 0.79,
                                "volume_expansion_quality": 0.29,
                                "close_strength": 0.63,
                                "catalyst_freshness": 0.77,
                                "thresholds": {"near_miss_threshold": 0.52},
                            },
                            "explainability_payload": {"candidate_source": "short_trade_boundary"},
                        },
                    },
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    historical_rows: list[dict[str, object]] = []
    for trade_date in ("2026-03-31", "2026-04-01", "2026-04-02"):
        historical_rows.extend(
            [
                {
                    "ticker": "300720",
                    "trade_date": trade_date,
                    "candidate_source": "upstream_liquidity_corridor_shadow",
                    "watch_candidate_family": "selected",
                },
                {
                    "ticker": "300757",
                    "trade_date": trade_date,
                    "candidate_source": "short_trade_boundary",
                    "watch_candidate_family": "opportunity_pool",
                },
                {
                    "ticker": "600522",
                    "trade_date": trade_date,
                    "candidate_source": "short_trade_boundary",
                    "watch_candidate_family": "opportunity_pool",
                },
                {
                    "ticker": "603778",
                    "trade_date": trade_date,
                    "candidate_source": "short_trade_boundary",
                    "watch_candidate_family": "opportunity_pool",
                },
            ]
        )

    monkeypatch.setattr(
        "src.paper_trading.btst_reporting._collect_historical_watch_candidate_rows",
        lambda report_dir, actual_trade_date: {
            "rows": historical_rows,
            "historical_report_dirs": [],
            "contributing_report_count": 3,
            "family_counts": {"selected": 3, "near_miss": 0, "opportunity_pool": 9, "research_upside_radar": 0, "catalyst_theme": 0},
        },
    )

    def _outcome(ticker: str, trade_date: str, price_cache):
        if ticker == "300720":
            return {
                "data_status": "ok",
                "next_trade_date": "2026-04-07",
                "next_open_return": 0.01,
                "next_high_return": 0.05,
                "next_close_return": -0.01,
                "next_open_to_close_return": -0.02,
            }
        if ticker == "300757":
            return {
                "data_status": "ok",
                "next_trade_date": "2026-04-07",
                "next_open_return": 0.03,
                "next_high_return": 0.05,
                "next_close_return": 0.02,
                "next_open_to_close_return": -0.01,
            }
        if ticker == "600522":
            return {
                "data_status": "ok",
                "next_trade_date": "2026-04-07",
                "next_open_return": 0.0,
                "next_high_return": 0.04,
                "next_close_return": -0.005,
                "next_open_to_close_return": -0.005,
            }
        return {
            "data_status": "ok",
            "next_trade_date": "2026-04-07",
            "next_open_return": -0.01,
            "next_high_return": 0.0,
            "next_close_return": -0.02,
            "next_open_to_close_return": -0.01,
        }

    monkeypatch.setattr("src.paper_trading.btst_reporting._extract_next_day_outcome", _outcome)

    analysis = analyze_btst_next_day_trade_brief(report_dir, trade_date="2026-04-06", next_trade_date="2026-04-07")

    assert analysis["primary_entry"] is None
    assert analysis["summary"]["short_trade_selected_count"] == 0
    assert analysis["summary"]["short_trade_near_miss_count"] == 1
    assert analysis["summary"]["short_trade_opportunity_pool_count"] == 0
    assert analysis["summary"]["risky_observer_count"] == 2
    assert analysis["summary"]["weak_history_pruned_count"] == 1
    assert [entry["ticker"] for entry in analysis["near_miss_entries"]] == ["300720"]
    assert analysis["near_miss_entries"][0]["preferred_entry_mode"] == "intraday_confirmation_only"
    assert "historical_intraday_only_selected_demoted" in analysis["near_miss_entries"][0]["top_reasons"]
    assert analysis["opportunity_pool_entries"] == []
    assert [entry["ticker"] for entry in analysis["risky_observer_entries"]] == ["300757", "600522"]
    assert analysis["risky_observer_entries"][0]["preferred_entry_mode"] == "avoid_open_chase_confirmation"
    assert analysis["risky_observer_entries"][1]["preferred_entry_mode"] == "intraday_confirmation_only"
    assert [entry["ticker"] for entry in analysis["weak_history_pruned_entries"]] == ["603778"]
    assert all("historical_zero_follow_through" in ",".join(entry["top_reasons"]) for entry in analysis["weak_history_pruned_entries"])


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


def test_generate_btst_next_day_trade_brief_prunes_balanced_confirmation_opportunity_with_zero_follow_through(tmp_path, monkeypatch):
    report_dir = tmp_path / "report"
    trade_dir = report_dir / "selection_artifacts" / "2026-04-09"
    trade_dir.mkdir(parents=True)

    (report_dir / "session_summary.json").write_text(
        json.dumps({"plan_generation": {"selection_target": "short_trade_only"}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _write_catalyst_theme_frontier(report_dir, promoted_tickers=[])
    (trade_dir / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "20260409",
                "target_mode": "short_trade_only",
                "selection_targets": {
                    "301188": {
                        "ticker": "301188",
                        "short_trade": {
                            "decision": "rejected",
                            "score_target": 0.4011,
                            "confidence": 0.82,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "positive_tags": ["fresh_breakout_candidate"],
                            "top_reasons": ["trend_acceleration=0.71"],
                            "rejection_reasons": ["score_short_below_threshold"],
                            "gate_status": {"data": "pass", "structural": "pass", "score": "fail"},
                            "metrics_payload": {
                                "breakout_freshness": 0.44,
                                "trend_acceleration": 0.71,
                                "volume_expansion_quality": 0.32,
                                "close_strength": 0.57,
                                "catalyst_freshness": 0.21,
                                "thresholds": {"near_miss_threshold": 0.52},
                            },
                            "historical_prior": {
                                "applied_scope": "same_family_source",
                                "sample_count": 2,
                                "evaluable_count": 2,
                                "execution_quality_label": "balanced_confirmation",
                                "next_high_hit_rate_at_threshold": 0.0,
                                "next_close_positive_rate": 0.0,
                                "next_open_to_close_return_mean": -0.0426,
                                "summary": "同层同源历史 2 例，next_high>=2.0% 命中率=0.0000, next_close 正收益率=0.0000。",
                            },
                            "explainability_payload": {"candidate_source": "upstream_liquidity_corridor_shadow"},
                        },
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "src.paper_trading.btst_reporting._collect_historical_watch_candidate_rows",
        lambda report_dir, actual_trade_date: {
            "rows": [],
            "historical_report_dirs": [],
            "contributing_report_count": 0,
            "family_counts": {"selected": 0, "near_miss": 0, "opportunity_pool": 0, "research_upside_radar": 0, "catalyst_theme": 0},
        },
    )

    analysis = analyze_btst_next_day_trade_brief(report_dir, trade_date="2026-04-09", next_trade_date="2026-04-10")

    assert analysis["opportunity_pool_entries"] == []
    assert analysis["risky_observer_entries"] == []
    assert [entry["ticker"] for entry in analysis["weak_history_pruned_entries"]] == ["301188"]
    assert analysis["weak_history_pruned_entries"][0]["historical_prior"]["execution_quality_label"] == "balanced_confirmation"
    assert "historical_zero_follow_through_pruned" in analysis["weak_history_pruned_entries"][0]["top_reasons"]


def test_generate_btst_next_day_trade_brief_prunes_weak_balanced_confirmation_opportunity_pool_entry(tmp_path, monkeypatch):
    report_dir = tmp_path / "report"
    trade_dir = report_dir / "selection_artifacts" / "2026-04-06"
    trade_dir.mkdir(parents=True)

    (report_dir / "session_summary.json").write_text(
        json.dumps({"plan_generation": {"selection_target": "short_trade_only"}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _write_catalyst_theme_frontier(report_dir, promoted_tickers=[])
    (trade_dir / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "20260406",
                "target_mode": "short_trade_only",
                "selection_targets": {
                    "601872": {
                        "ticker": "601872",
                        "short_trade": {
                            "decision": "rejected",
                            "score_target": 0.3612,
                            "confidence": 0.73,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "positive_tags": ["fresh_breakout_candidate"],
                            "top_reasons": ["trend_acceleration=0.67"],
                            "rejection_reasons": ["score_short_below_threshold"],
                            "gate_status": {"data": "pass", "structural": "pass", "score": "fail"},
                            "metrics_payload": {
                                "breakout_freshness": 0.49,
                                "trend_acceleration": 0.67,
                                "volume_expansion_quality": 0.27,
                                "close_strength": 0.54,
                                "catalyst_freshness": 0.28,
                                "thresholds": {"near_miss_threshold": 0.52},
                            },
                            "historical_prior": {
                                "applied_scope": "family_source_score_catalyst",
                                "sample_count": 7,
                                "evaluable_count": 7,
                                "execution_quality_label": "balanced_confirmation",
                                "next_high_hit_rate_at_threshold": 0.4286,
                                "next_close_positive_rate": 0.1429,
                                "next_open_to_close_return_mean": -0.0271,
                                "summary": "同层历史 7 例，next_high>=2.0% 命中率=0.4286, next_close 正收益率=0.1429。",
                            },
                            "explainability_payload": {"candidate_source": "short_trade_boundary"},
                        },
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "src.paper_trading.btst_reporting._collect_historical_watch_candidate_rows",
        lambda report_dir, actual_trade_date: {
            "rows": [],
            "historical_report_dirs": [],
            "contributing_report_count": 0,
            "family_counts": {"selected": 0, "near_miss": 0, "opportunity_pool": 0, "research_upside_radar": 0, "catalyst_theme": 0},
        },
    )

    analysis = analyze_btst_next_day_trade_brief(report_dir, trade_date="2026-04-06", next_trade_date="2026-04-07")

    assert analysis["opportunity_pool_entries"] == []
    assert analysis["risky_observer_entries"] == []
    assert [entry["ticker"] for entry in analysis["weak_history_pruned_entries"]] == ["601872"]
    assert analysis["weak_history_pruned_entries"][0]["historical_prior"]["execution_quality_label"] == "balanced_confirmation"
    assert "historical_zero_follow_through_pruned" in analysis["weak_history_pruned_entries"][0]["top_reasons"]


def test_generate_btst_next_day_trade_brief_rebuckets_no_history_opportunity_pool_entry(tmp_path, monkeypatch):
    report_dir = tmp_path / "report"
    trade_dir = report_dir / "selection_artifacts" / "2026-03-23"
    trade_dir.mkdir(parents=True)

    (report_dir / "session_summary.json").write_text(
        json.dumps({"plan_generation": {"selection_target": "short_trade_only"}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _write_catalyst_theme_frontier(report_dir, promoted_tickers=[])
    (trade_dir / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "20260323",
                "target_mode": "short_trade_only",
                "selection_targets": {
                    "003036": {
                        "ticker": "003036",
                        "short_trade": {
                            "decision": "rejected",
                            "score_target": 0.3857,
                            "confidence": 0.71,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "candidate_source": "upstream_liquidity_corridor_shadow",
                            "positive_tags": ["fresh_breakout_candidate"],
                            "top_reasons": ["trend_acceleration=0.72"],
                            "rejection_reasons": ["score_short_below_threshold"],
                            "gate_status": {"data": "pass", "structural": "pass", "score": "fail"},
                            "metrics_payload": {
                                "breakout_freshness": 0.48,
                                "trend_acceleration": 0.72,
                                "volume_expansion_quality": 0.25,
                                "close_strength": 0.58,
                                "catalyst_freshness": 0.24,
                                "thresholds": {"near_miss_threshold": 0.52},
                            },
                            "historical_prior": {
                                "applied_scope": "none",
                                "sample_count": 0,
                                "evaluable_count": 0,
                                "execution_quality_label": "unknown",
                                "summary": "暂无同层可评估历史样本。",
                            },
                            "explainability_payload": {"candidate_source": "upstream_liquidity_corridor_shadow"},
                        },
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "src.paper_trading.btst_reporting._collect_historical_watch_candidate_rows",
        lambda report_dir, actual_trade_date: {
            "rows": [],
            "historical_report_dirs": [],
            "contributing_report_count": 0,
            "family_counts": {"selected": 0, "near_miss": 0, "opportunity_pool": 0, "research_upside_radar": 0, "catalyst_theme": 0},
        },
    )

    analysis = analyze_btst_next_day_trade_brief(report_dir, trade_date="2026-03-23", next_trade_date="2026-03-24")

    assert analysis["opportunity_pool_entries"] == []
    assert [entry["ticker"] for entry in analysis["no_history_observer_entries"]] == ["003036"]
    assert analysis["summary"]["no_history_observer_count"] == 1
    assert analysis["no_history_observer_entries"][0]["historical_prior"]["rebucket_reason"] == "no_evaluable_history"
    assert "no_history_observer_rebucket" in analysis["no_history_observer_entries"][0]["top_reasons"]


def test_generate_btst_next_day_trade_brief_prunes_low_score_no_history_upstream_prepared_breakout(tmp_path, monkeypatch):
    report_dir = tmp_path / "report"
    trade_dir = report_dir / "selection_artifacts" / "2026-03-23"
    trade_dir.mkdir(parents=True)

    (report_dir / "session_summary.json").write_text(
        json.dumps({"plan_generation": {"selection_target": "short_trade_only"}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _write_catalyst_theme_frontier(report_dir, promoted_tickers=[])
    (trade_dir / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "20260323",
                "target_mode": "short_trade_only",
                "selection_targets": {
                    "300641": {
                        "ticker": "300641",
                        "short_trade": {
                            "decision": "rejected",
                            "score_target": 0.3296,
                            "confidence": 0.68,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "candidate_source": "upstream_liquidity_corridor_shadow",
                            "positive_tags": ["fresh_breakout_candidate"],
                            "top_reasons": ["trend_acceleration=0.58", "prepared_breakout", "score_short=0.33"],
                            "rejection_reasons": ["score_short_below_threshold"],
                            "gate_status": {"data": "pass", "structural": "pass", "score": "fail"},
                            "metrics_payload": {
                                "breakout_freshness": 0.43,
                                "trend_acceleration": 0.58,
                                "volume_expansion_quality": 0.21,
                                "close_strength": 0.47,
                                "catalyst_freshness": 0.19,
                                "thresholds": {"near_miss_threshold": 0.52},
                            },
                            "historical_prior": {
                                "applied_scope": "none",
                                "sample_count": 0,
                                "evaluable_count": 0,
                                "execution_quality_label": "unknown",
                                "summary": "暂无同层可评估历史样本。",
                            },
                            "explainability_payload": {"candidate_source": "upstream_liquidity_corridor_shadow"},
                        },
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "src.paper_trading.btst_reporting._collect_historical_watch_candidate_rows",
        lambda report_dir, actual_trade_date: {
            "rows": [],
            "historical_report_dirs": [],
            "contributing_report_count": 0,
            "family_counts": {"selected": 0, "near_miss": 0, "opportunity_pool": 0, "research_upside_radar": 0, "catalyst_theme": 0},
        },
    )

    analysis = analyze_btst_next_day_trade_brief(report_dir, trade_date="2026-03-23", next_trade_date="2026-03-24")

    assert analysis["opportunity_pool_entries"] == []
    assert analysis["no_history_observer_entries"] == []
    assert [entry["ticker"] for entry in analysis["weak_history_pruned_entries"]] == ["300641"]
    assert analysis["weak_history_pruned_entries"][0]["historical_prior"]["prune_reason"] == "no_history_low_score_prepared_breakout"
    assert "no_history_low_score_pruned" in analysis["weak_history_pruned_entries"][0]["top_reasons"]


def test_generate_btst_next_day_trade_brief_prunes_weak_catalyst_no_history_without_profitability_support(tmp_path, monkeypatch):
    report_dir = tmp_path / "report"
    trade_dir = report_dir / "selection_artifacts" / "2026-03-30"
    trade_dir.mkdir(parents=True)

    (report_dir / "session_summary.json").write_text(
        json.dumps({"plan_generation": {"selection_target": "short_trade_only"}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _write_catalyst_theme_frontier(report_dir, promoted_tickers=[])
    (trade_dir / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "20260330",
                "target_mode": "short_trade_only",
                "selection_targets": {
                    "688072": {
                        "ticker": "688072",
                        "short_trade": {
                            "decision": "rejected",
                            "score_target": 0.3751,
                            "confidence": 0.72,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "candidate_source": "catalyst_theme",
                            "positive_tags": ["fresh_breakout_candidate"],
                            "top_reasons": ["trend_acceleration=0.73", "confirmed_breakout", "score_short=0.38"],
                            "rejection_reasons": ["score_short_below_threshold"],
                            "gate_status": {"data": "pass", "structural": "pass", "score": "fail"},
                            "metrics_payload": {
                                "breakout_freshness": 0.45,
                                "trend_acceleration": 0.73,
                                "volume_expansion_quality": 0.24,
                                "close_strength": 0.57,
                                "catalyst_freshness": 0.35,
                                "thresholds": {"near_miss_threshold": 0.52},
                            },
                            "historical_prior": {
                                "applied_scope": "none",
                                "sample_count": 0,
                                "evaluable_count": 0,
                                "execution_quality_label": "unknown",
                                "summary": "暂无同层可评估历史样本。",
                            },
                            "explainability_payload": {"candidate_source": "catalyst_theme"},
                        },
                    },
                    "002491": {
                        "ticker": "002491",
                        "short_trade": {
                            "decision": "rejected",
                            "score_target": 0.3547,
                            "confidence": 0.71,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "candidate_source": "catalyst_theme",
                            "positive_tags": ["fresh_breakout_candidate"],
                            "top_reasons": ["trend_acceleration=0.74", "profitability_hard_cliff", "confirmed_breakout"],
                            "rejection_reasons": ["score_short_below_threshold"],
                            "gate_status": {"data": "pass", "structural": "pass", "score": "fail"},
                            "metrics_payload": {
                                "breakout_freshness": 0.43,
                                "trend_acceleration": 0.74,
                                "volume_expansion_quality": 0.23,
                                "close_strength": 0.59,
                                "catalyst_freshness": 0.31,
                                "thresholds": {"near_miss_threshold": 0.52},
                            },
                            "historical_prior": {
                                "applied_scope": "none",
                                "sample_count": 0,
                                "evaluable_count": 0,
                                "execution_quality_label": "unknown",
                                "summary": "暂无同层可评估历史样本。",
                            },
                            "explainability_payload": {"candidate_source": "catalyst_theme"},
                        },
                    },
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "src.paper_trading.btst_reporting._collect_historical_watch_candidate_rows",
        lambda report_dir, actual_trade_date: {
            "rows": [],
            "historical_report_dirs": [],
            "contributing_report_count": 0,
            "family_counts": {"selected": 0, "near_miss": 0, "opportunity_pool": 0, "research_upside_radar": 0, "catalyst_theme": 0},
        },
    )

    analysis = analyze_btst_next_day_trade_brief(report_dir, trade_date="2026-03-30", next_trade_date="2026-03-31")

    assert analysis["opportunity_pool_entries"] == []
    assert [entry["ticker"] for entry in analysis["no_history_observer_entries"]] == ["002491"]
    assert [entry["ticker"] for entry in analysis["weak_history_pruned_entries"]] == ["688072"]
    assert analysis["weak_history_pruned_entries"][0]["historical_prior"]["prune_reason"] == "catalyst_no_history_without_profitability_support"
    assert "catalyst_no_history_pruned" in analysis["weak_history_pruned_entries"][0]["top_reasons"]


def test_generate_btst_next_day_trade_brief_prunes_mixed_boundary_opportunity_pool_without_clear_follow_through(tmp_path, monkeypatch):
    report_dir = tmp_path / "report"
    trade_dir = report_dir / "selection_artifacts" / "2026-04-09"
    trade_dir.mkdir(parents=True)

    (report_dir / "session_summary.json").write_text(
        json.dumps({"plan_generation": {"selection_target": "short_trade_only"}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _write_catalyst_theme_frontier(report_dir, promoted_tickers=[])
    (trade_dir / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "20260409",
                "target_mode": "short_trade_only",
                "selection_targets": {
                    "600875": {
                        "ticker": "600875",
                        "short_trade": {
                            "decision": "rejected",
                            "score_target": 0.3885,
                            "confidence": 0.65,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "candidate_source": "short_trade_boundary",
                            "positive_tags": ["trend_acceleration_confirmed", "confirmed_breakout_stage"],
                            "top_reasons": ["breakout_freshness=0.49", "trend_acceleration=0.65", "profitability_hard_cliff"],
                            "rejection_reasons": ["score_short_below_threshold"],
                            "gate_status": {"data": "pass", "structural": "pass", "score": "fail"},
                            "metrics_payload": {
                                "breakout_freshness": 0.4934,
                                "trend_acceleration": 0.65,
                                "volume_expansion_quality": 0.3247,
                                "close_strength": 0.8,
                                "catalyst_freshness": 0.2867,
                                "thresholds": {"near_miss_threshold": 0.46},
                            },
                            "historical_prior": {
                                "applied_scope": "family_source_score_catalyst",
                                "sample_count": 6,
                                "evaluable_count": 6,
                                "next_high_hit_rate_at_threshold": 0.5,
                                "next_close_positive_rate": 0.5,
                                "next_open_to_close_return_mean": 0.0192,
                                "execution_quality_label": "balanced_confirmation",
                                "summary": "同层同源同分桶历史 6 例，next_high>=2.0% 命中率=0.5000, next_close 正收益率=0.5000。",
                            },
                            "explainability_payload": {"candidate_source": "short_trade_boundary"},
                        },
                    },
                    "300757": {
                        "ticker": "300757",
                        "short_trade": {
                            "decision": "rejected",
                            "score_target": 0.3362,
                            "confidence": 0.68,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "candidate_source": "short_trade_boundary",
                            "positive_tags": ["fresh_breakout_candidate"],
                            "top_reasons": ["breakout_freshness=0.47", "catalyst_freshness=0.76", "profitability_hard_cliff"],
                            "rejection_reasons": ["score_short_below_threshold"],
                            "gate_status": {"data": "pass", "structural": "pass", "score": "fail"},
                            "metrics_payload": {
                                "breakout_freshness": 0.47,
                                "trend_acceleration": 0.7,
                                "volume_expansion_quality": 0.25,
                                "close_strength": 0.63,
                                "catalyst_freshness": 0.76,
                                "thresholds": {"near_miss_threshold": 0.46},
                            },
                            "historical_prior": {
                                "applied_scope": "same_ticker",
                                "sample_count": 4,
                                "evaluable_count": 4,
                                "next_high_hit_rate_at_threshold": 0.5,
                                "next_close_positive_rate": 0.5,
                                "next_open_to_close_return_mean": 0.0194,
                                "execution_quality_label": "balanced_confirmation",
                                "summary": "同票历史 4 例，next_high>=2.0% 命中率=0.5000, next_close 正收益率=0.5000。",
                            },
                            "explainability_payload": {"candidate_source": "short_trade_boundary"},
                        },
                    },
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "src.paper_trading.btst_reporting._collect_historical_watch_candidate_rows",
        lambda report_dir, actual_trade_date: {
            "rows": [],
            "historical_report_dirs": [],
            "contributing_report_count": 0,
            "family_counts": {"selected": 0, "near_miss": 0, "opportunity_pool": 0, "research_upside_radar": 0, "catalyst_theme": 0},
        },
    )

    analysis = analyze_btst_next_day_trade_brief(report_dir, trade_date="2026-04-09", next_trade_date="2026-04-10")

    assert [entry["ticker"] for entry in analysis["opportunity_pool_entries"]] == ["300757"]
    assert [entry["ticker"] for entry in analysis["weak_history_pruned_entries"]] == ["600875"]
    assert analysis["weak_history_pruned_entries"][0]["historical_prior"]["prune_reason"] == "mixed_boundary_follow_through"
    assert "mixed_boundary_follow_through_pruned" in analysis["weak_history_pruned_entries"][0]["top_reasons"]


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


def test_extract_next_day_outcome_prefers_robust_prices_before_tushare(monkeypatch):
    calls: list[str] = []

    def _robust(ticker: str, start_date: str, end_date: str, use_mock_on_fail: bool = False):
        calls.append(f"robust:{ticker}:{start_date}:{end_date}:{use_mock_on_fail}")
        return ["sentinel"]

    def _prices_to_df(_prices):
        frame = pd.DataFrame(
            [
                {"time": "2026-03-30", "open": 10.0, "high": 10.5, "low": 9.9, "close": 10.0},
                {"time": "2026-03-31", "open": 10.2, "high": 10.8, "low": 10.1, "close": 10.4},
            ]
        )
        frame["time"] = pd.to_datetime(frame["time"])
        return frame.set_index("time")

    monkeypatch.setattr(btst_reporting, "get_prices_robust", _robust)
    monkeypatch.setattr(btst_reporting, "prices_to_df", _prices_to_df)
    monkeypatch.setattr(
        btst_reporting,
        "get_price_data",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("get_price_data should not be called when robust prices succeed")),
    )

    outcome = btst_reporting._extract_next_day_outcome("300720", "2026-03-30", {})

    assert calls == ["robust:300720:2026-03-30:2026-04-09:False"]
    assert outcome["data_status"] == "ok"
    assert outcome["next_trade_date"] == "2026-03-31"
    assert outcome["next_open_return"] == 0.02
    assert outcome["next_high_return"] == 0.08
    assert outcome["next_close_return"] == 0.04
