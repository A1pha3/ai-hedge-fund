from __future__ import annotations

import json

from src.paper_trading.btst_reporting import generate_btst_opening_watch_card_artifacts


def test_generate_btst_opening_watch_card_orders_primary_watch_and_opportunity(tmp_path, monkeypatch):
    report_dir = tmp_path / "report"
    trade_dir = report_dir / "selection_artifacts" / "2026-03-27"
    trade_dir.mkdir(parents=True)

    historical_report_dir = tmp_path / "paper_trading_2026-03-26_2026-03-26_dummy"
    historical_trade_dir = historical_report_dir / "selection_artifacts" / "2026-03-26"
    historical_trade_dir.mkdir(parents=True)

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
    (historical_report_dir / "session_summary.json").write_text("{}\n", encoding="utf-8")

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
                            "positive_tags": ["fresh_breakout_candidate"],
                            "top_reasons": ["breakout_freshness=0.94"],
                            "gate_status": {"score": "pass", "structural": "pass"},
                            "metrics_payload": {"breakout_freshness": 0.935},
                            "explainability_payload": {"candidate_source": "short_trade_boundary"},
                        },
                    },
                    "601869": {
                        "ticker": "601869",
                        "short_trade": {
                            "decision": "near_miss",
                            "score_target": 0.554,
                            "confidence": 0.8667,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "positive_tags": ["fresh_catalyst_support"],
                            "top_reasons": ["trend_acceleration=0.76"],
                            "gate_status": {"score": "near_miss", "structural": "pass"},
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
                            "top_reasons": ["catalyst_freshness=0.71"],
                            "rejection_reasons": ["score_short_below_threshold"],
                            "gate_status": {"data": "pass", "structural": "pass", "score": "fail"},
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
                },
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
                            "score_target": 0.3411,
                            "confidence": 0.7021,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "positive_tags": ["fresh_catalyst_support"],
                            "top_reasons": ["catalyst_freshness=0.82"],
                            "rejection_reasons": ["score_short_below_threshold"],
                            "gate_status": {"data": "pass", "structural": "pass", "score": "fail"},
                            "metrics_payload": {
                                "breakout_freshness": 0.401,
                                "trend_acceleration": 0.388,
                                "volume_expansion_quality": 0.308,
                                "close_strength": 0.431,
                                "catalyst_freshness": 0.821,
                                "thresholds": {"near_miss_threshold": 0.52},
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
        "src.paper_trading.btst_reporting._extract_next_day_outcome",
        lambda ticker, trade_date, price_cache: {
            "data_status": "ok",
            "next_trade_date": "2026-03-27",
            "next_open_return": 0.007,
            "next_high_return": 0.025,
            "next_close_return": 0.011,
            "next_open_to_close_return": 0.004,
        },
    )

    result = generate_btst_opening_watch_card_artifacts(
        input_path=report_dir,
        output_dir=tmp_path,
        trade_date="2026-03-27",
        next_trade_date="2026-03-30",
    )

    payload = json.loads((tmp_path / "btst_opening_watch_card_20260330.json").read_text(encoding="utf-8"))
    markdown = (tmp_path / "btst_opening_watch_card_20260330.md").read_text(encoding="utf-8")

    assert result["analysis"]["headline"]
    assert "301001" in result["analysis"]["headline"]
    assert "601869" in result["analysis"]["headline"]
    assert [item["ticker"] for item in payload["focus_items"]] == ["300757", "601869", "300442"]
    assert payload["summary"]["catalyst_theme_frontier_promoted_count"] == 1
    assert payload["summary"]["catalyst_theme_shadow_count"] == 1
    assert payload["summary"]["upstream_shadow_candidate_count"] == 2
    assert payload["summary"]["upstream_shadow_promotable_count"] == 1
    assert payload["catalyst_theme_frontier_priority"]["promoted_tickers"] == ["301001"]
    assert payload["catalyst_theme_shadow_watch"][0]["ticker"] == "301001"
    assert [entry["ticker"] for entry in payload["upstream_shadow_entries"]] == ["601869", "300442"]
    assert payload["focus_items"][0]["historical_summary"] is not None
    assert payload["focus_items"][0]["execution_note"] is not None
    assert payload["upstream_shadow_entries"][0]["candidate_source"] == "upstream_liquidity_corridor_shadow"
    assert payload["upstream_shadow_entries"][1]["candidate_source"] == "post_gate_liquidity_competition_shadow"
    assert "# BTST Opening Watch Card" in markdown
    assert "### 1. 300757" in markdown
    assert "### 2. 601869" in markdown
    assert "### 3. 300442" in markdown
    assert "## Catalyst Theme Frontier Priority" in markdown
    assert "## Catalyst Theme Shadow Watch" in markdown
    assert "## Upstream Shadow Recall" in markdown
    assert "### 1. 301001" in markdown
    assert "candidate_source: upstream_liquidity_corridor_shadow" in markdown
    assert "focus_tier: catalyst_theme_frontier_priority" in markdown
    assert "execution_posture: research_followup_only" in markdown
    assert "execution_note" in markdown
    assert "historical_summary" in markdown


def test_generate_btst_opening_watch_card_surfaces_risky_observers_separately(tmp_path):
    result = generate_btst_opening_watch_card_artifacts(
        input_path={
            "trade_date": "2026-04-09",
            "next_trade_date": "2026-04-10",
            "selection_target": "short_trade_only",
            "recommendation": "只保留高风险盘中观察。",
            "selected_entries": [],
            "near_miss_entries": [],
            "opportunity_pool_entries": [],
            "risky_observer_entries": [
                {
                    "ticker": "601869",
                    "score_target": 0.41,
                    "preferred_entry_mode": "avoid_open_chase_confirmation",
                    "top_reasons": ["historical_gap_chase_risk"],
                    "historical_prior": {
                        "summary": "同票历史 12 例，next_close 正收益率=0.2500。",
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
        trade_date="2026-04-09",
        next_trade_date="2026-04-10",
    )

    payload = json.loads((tmp_path / "btst_opening_watch_card_20260410.json").read_text(encoding="utf-8"))
    markdown = (tmp_path / "btst_opening_watch_card_20260410.md").read_text(encoding="utf-8")

    assert result["analysis"]["summary"]["risky_observer_count"] == 1
    assert [item["ticker"] for item in payload["focus_items"]] == ["601869"]
    assert payload["focus_items"][0]["focus_tier"] == "risky_observer"
    assert payload["focus_items"][0]["execution_posture"] == "risk_observer_only"
    assert "risky_observer_count: 1" in markdown
    assert "focus_tier: risky_observer" in markdown


def test_generate_btst_opening_watch_card_surfaces_no_history_observers_separately(tmp_path):
    result = generate_btst_opening_watch_card_artifacts(
        input_path={
            "trade_date": "2026-03-23",
            "next_trade_date": "2026-03-24",
            "selection_target": "short_trade_only",
            "recommendation": "只保留 no-history 观察。",
            "selected_entries": [],
            "near_miss_entries": [],
            "opportunity_pool_entries": [],
            "no_history_observer_entries": [
                {
                    "ticker": "003036",
                    "score_target": 0.3857,
                    "preferred_entry_mode": "next_day_breakout_confirmation",
                    "top_reasons": ["no_history_observer_rebucket"],
                    "historical_prior": {
                        "summary": "暂无同层可评估历史样本。 暂无可评估历史先验，已移入 no-history observer。",
                        "execution_note": "先看盘中新证据，再决定是否重新评估。",
                    },
                }
            ],
            "risky_observer_entries": [],
            "research_upside_radar_entries": [],
            "catalyst_theme_shadow_entries": [],
            "catalyst_theme_frontier_summary": {},
            "catalyst_theme_frontier_priority": {},
            "upstream_shadow_entries": [],
            "upstream_shadow_summary": {"shadow_candidate_count": 0, "promotable_count": 0, "lane_counts": {}, "decision_counts": {}, "top_focus_tickers": []},
        },
        output_dir=tmp_path,
        trade_date="2026-03-23",
        next_trade_date="2026-03-24",
    )

    payload = json.loads((tmp_path / "btst_opening_watch_card_20260324.json").read_text(encoding="utf-8"))
    markdown = (tmp_path / "btst_opening_watch_card_20260324.md").read_text(encoding="utf-8")

    assert result["analysis"]["summary"]["no_history_observer_count"] == 1
    assert [item["ticker"] for item in payload["focus_items"]] == ["003036"]
    assert payload["focus_items"][0]["focus_tier"] == "no_history_observer"
    assert payload["focus_items"][0]["execution_posture"] == "observe_only_no_history"
    assert "no_history_observer_count: 1" in markdown
    assert "focus_tier: no_history_observer" in markdown
