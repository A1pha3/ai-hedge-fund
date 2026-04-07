from __future__ import annotations

import json

from scripts.generate_btst_premarket_execution_card import generate_btst_premarket_execution_card_artifacts


def test_generate_btst_premarket_execution_card_creates_primary_watch_and_non_trade_sections(tmp_path):
    report_dir = tmp_path / "report"
    trade_dir = report_dir / "selection_artifacts" / "2026-03-27"
    trade_dir.mkdir(parents=True)

    (report_dir / "session_summary.json").write_text(
        json.dumps({"plan_generation": {"selection_target": "short_trade_only"}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (report_dir / "catalyst_theme_frontier_latest.json").write_text(
        json.dumps(
            {
                "shadow_candidate_count": 1,
                "baseline_selected_count": 0,
                "recommendation": "优先跟踪 frontier promoted shadow。",
                "recommended_variant": {
                    "variant_name": "catalyst_theme_relaxed_sector_frontier",
                    "promoted_shadow_count": 1,
                    "threshold_relaxation_cost": 0.09,
                    "thresholds": {"candidate_score": 0.30, "sector_resonance": 0.20},
                    "top_promoted_rows": [{"ticker": "301001"}],
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (report_dir / "catalyst_theme_frontier_latest.md").write_text("# Catalyst Theme Frontier\n", encoding="utf-8")
    (trade_dir / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "20260327",
                "target_mode": "short_trade_only",
                "catalyst_theme_shadow_candidates": [
                    {
                        "ticker": "301001",
                        "decision": "catalyst_theme_shadow",
                        "score_target": 0.32,
                        "candidate_source": "catalyst_theme_shadow",
                        "filter_reason": "sector_resonance_below_catalyst_theme_floor",
                        "threshold_shortfalls": {"candidate_score": 0.02, "sector_resonance": 0.03},
                        "failed_threshold_count": 2,
                        "total_shortfall": 0.05,
                        "positive_tags": ["strong_catalyst_freshness", "breakout_watch_ready"],
                        "top_reasons": ["candidate_score=0.32", "catalyst_freshness=0.82", "total_shortfall=0.05"],
                        "metrics": {
                            "breakout_freshness": 0.14,
                            "trend_acceleration": 0.21,
                            "close_strength": 0.41,
                            "sector_resonance": 0.22,
                            "catalyst_freshness": 0.82,
                        },
                    }
                ],
                "selection_targets": {
                    "300757": {
                        "ticker": "300757",
                        "short_trade": {
                            "decision": "selected",
                            "score_target": 0.5907,
                            "confidence": 0.935,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "positive_tags": ["fresh_breakout_candidate"],
                            "top_reasons": ["breakout_freshness=0.94"],
                            "gate_status": {"score": "pass"},
                            "metrics_payload": {"breakout_freshness": 0.935},
                            "explainability_payload": {"candidate_source": "short_trade_boundary"},
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
                            "gate_status": {"score": "near_miss"},
                            "metrics_payload": {"trend_acceleration": 0.7637},
                            "explainability_payload": {
                                "candidate_source": "upstream_liquidity_corridor_shadow",
                                "replay_context": {"candidate_pool_lane": "layer_a_liquidity_corridor", "candidate_pool_rank": 301},
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
                                "replay_context": {"candidate_pool_lane": "post_gate_liquidity_competition", "candidate_pool_rank": 304},
                            },
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
                    "002002": {
                        "ticker": "002002",
                        "research": {"decision": "selected", "score_target": 0.2812},
                        "short_trade": {
                            "decision": "rejected",
                            "score_target": 0.1130,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                        },
                        "delta_summary": ["research target selected while short trade target stays rejected"],
                    },
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = generate_btst_premarket_execution_card_artifacts(
        input_path=report_dir,
        output_dir=tmp_path,
        trade_date="2026-03-27",
        next_trade_date="2026-03-30",
    )

    payload = json.loads((tmp_path / "btst_premarket_execution_card_20260327_for_20260330.json").read_text(encoding="utf-8"))
    markdown = (tmp_path / "btst_premarket_execution_card_20260327_for_20260330.md").read_text(encoding="utf-8")

    assert result["analysis"]["primary_action"]["ticker"] == "300757"
    assert payload["summary"]["catalyst_theme_frontier_promoted_count"] == 1
    assert payload["summary"]["catalyst_theme_shadow_count"] == 1
    assert payload["summary"]["upstream_shadow_candidate_count"] == 2
    assert payload["summary"]["upstream_shadow_promotable_count"] == 1
    assert [entry["ticker"] for entry in payload["watch_actions"]] == ["601869"]
    assert [entry["ticker"] for entry in payload["opportunity_actions"]] == ["300442"]
    assert [entry["ticker"] for entry in payload["upstream_shadow_entries"]] == ["601869", "300442"]
    assert payload["catalyst_theme_frontier_priority"]["promoted_tickers"] == ["301001"]
    assert [entry["ticker"] for entry in payload["catalyst_theme_shadow_watch"]] == ["301001"]
    assert payload["primary_action"]["historical_prior"]["execution_quality_label"] == "unknown"
    assert [entry["ticker"] for entry in payload["excluded_research_entries"]] == ["002002"]
    assert "# BTST Premarket Execution Card" in markdown
    assert "## Catalyst Theme Frontier Priority" in markdown
    assert "## Catalyst Theme Shadow Watch" in markdown
    assert "## Upstream Shadow Recall" in markdown
    assert "300757" in markdown
    assert "601869" in markdown
    assert "300442" in markdown
    assert "301001" in markdown
    assert "action_tier: catalyst_theme_frontier_priority" in markdown
    assert "Opportunity Pool Actions" in markdown
    assert "execution_posture: research_followup_only" in markdown
    assert "candidate_source: upstream_liquidity_corridor_shadow" in markdown
    assert "execution_quality_label" in markdown
    assert "002002" in markdown


def test_generate_btst_premarket_execution_card_uses_execution_quality_specific_watch_rules(tmp_path):
    result = generate_btst_premarket_execution_card_artifacts(
        input_path={
            "trade_date": "2026-04-06",
            "next_trade_date": "2026-04-07",
            "summary": {},
            "selected_entries": [],
            "near_miss_entries": [
                {
                    "ticker": "300720",
                    "preferred_entry_mode": "intraday_confirmation_only",
                    "top_reasons": ["historical_intraday_only_selected_demoted"],
                    "historical_prior": {
                        "summary": "同票历史 4 例，next_close 正收益率=0.0000。",
                        "execution_quality_label": "intraday_only",
                        "execution_note": "历史上更多是盘中给空间、收盘回落。",
                    },
                }
            ],
            "opportunity_pool_entries": [
                {
                    "ticker": "300757",
                    "preferred_entry_mode": "avoid_open_chase_confirmation",
                    "promotion_trigger": "若盘中回踩后重新走强可再确认。",
                    "top_reasons": ["historical_gap_chase_risk"],
                    "rejection_reasons": ["score_short_below_threshold"],
                    "historical_prior": {
                        "summary": "同票历史 6 例，next_close 正收益率=0.6667。",
                        "execution_quality_label": "gap_chase_risk",
                        "execution_note": "历史上更像高开后回落，避免开盘直接追价。",
                    },
                }
            ],
            "research_upside_radar_entries": [],
            "catalyst_theme_shadow_entries": [],
            "catalyst_theme_frontier_summary": {},
            "catalyst_theme_frontier_priority": {},
            "upstream_shadow_entries": [],
            "upstream_shadow_summary": {"shadow_candidate_count": 0, "promotable_count": 0, "lane_counts": {}, "decision_counts": {}, "top_focus_tickers": []},
        },
        output_dir=tmp_path,
        trade_date="2026-04-06",
        next_trade_date="2026-04-07",
    )

    payload = json.loads((tmp_path / "btst_premarket_execution_card_20260406_for_20260407.json").read_text(encoding="utf-8"))

    assert result["analysis"]["primary_action"] is None
    assert payload["watch_actions"][0]["execution_quality_label"] == "intraday_only"
    assert any("intraday" in rule for rule in payload["watch_actions"][0]["trigger_rules"])
    assert payload["opportunity_actions"][0]["execution_quality_label"] == "gap_chase_risk"
    assert any("避免开盘直接追价" in rule for rule in payload["opportunity_actions"][0]["trigger_rules"])


def test_generate_btst_premarket_execution_card_supports_confirm_then_hold_breakout_mode(tmp_path):
    primary_entry = {
        "ticker": "601869",
        "preferred_entry_mode": "confirm_then_hold_breakout",
        "score_target": 0.5632,
        "top_reasons": ["historical_execution_relief_applied", "close_continuation_follow_through"],
        "positive_tags": ["historical_execution_relief_applied"],
        "metrics": {"score_target": 0.5632},
        "historical_prior": {
            "summary": "同票历史 4 例，next_close 正收益率=1.0000。",
            "execution_quality_label": "close_continuation",
            "execution_note": "确认后若量价延续良好，可保留收盘 follow-through。",
        },
    }
    generate_btst_premarket_execution_card_artifacts(
        input_path={
            "trade_date": "2026-03-31",
            "next_trade_date": "2026-04-01",
            "summary": {},
            "primary_entry": primary_entry,
            "selected_entries": [primary_entry],
            "near_miss_entries": [],
            "opportunity_pool_entries": [],
            "research_upside_radar_entries": [],
            "catalyst_theme_shadow_entries": [],
            "catalyst_theme_frontier_summary": {},
            "catalyst_theme_frontier_priority": {},
            "upstream_shadow_entries": [],
            "upstream_shadow_summary": {"shadow_candidate_count": 0, "promotable_count": 0, "lane_counts": {}, "decision_counts": {}, "top_focus_tickers": []},
        },
        output_dir=tmp_path,
        trade_date="2026-03-31",
        next_trade_date="2026-04-01",
    )

    payload = json.loads((tmp_path / "btst_premarket_execution_card_20260331_for_20260401.json").read_text(encoding="utf-8"))
    markdown = (tmp_path / "btst_premarket_execution_card_20260331_for_20260401.md").read_text(encoding="utf-8")

    assert payload["primary_action"]["preferred_entry_mode"] == "confirm_then_hold_breakout"
    assert payload["primary_action"]["execution_posture"] == "confirm_then_hold"
    assert any("持有到收盘" in rule for rule in payload["primary_action"]["trigger_rules"])
    assert "confirm_then_hold" in markdown
