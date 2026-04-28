from __future__ import annotations

import json

import src.paper_trading.btst_reporting as btst_reporting
from src.paper_trading.btst_reporting import generate_btst_next_day_priority_board_artifacts


def test_render_btst_next_day_priority_board_markdown_emits_sections_and_catalyst_rows():
    markdown = btst_reporting.render_btst_next_day_priority_board_markdown(
        {
            "trade_date": "2026-03-27",
            "next_trade_date": "2026-03-30",
            "selection_target": "short_trade_only",
            "headline": "先执行主票确认，再按 near-miss 递减关注；题材催化前沿 research priority 为 301001。",
            "summary": {
                "primary_count": 1,
                "near_miss_count": 1,
                "opportunity_pool_count": 0,
                "no_history_observer_count": 0,
                "risky_observer_count": 0,
                "research_upside_radar_count": 1,
                "catalyst_theme_count": 1,
                "catalyst_theme_frontier_promoted_count": 1,
                "catalyst_theme_shadow_count": 1,
            },
            "priority_rows": [
                {
                    "ticker": "300757",
                    "lane": "primary_entry",
                    "actionability": "trade_candidate",
                    "monitor_priority": "highest",
                    "execution_priority": "high",
                    "execution_quality_label": "balanced_confirmation",
                    "score_target": 0.5907,
                    "preferred_entry_mode": "next_day_breakout_confirmation",
                    "why_now": "breakout_freshness=0.94",
                    "suggested_action": "盘中确认后再执行。",
                    "historical_summary": "close continuation supportive",
                    "execution_note": "avoid weak open",
                }
            ],
            "catalyst_theme_frontier_priority": {
                "status": "watch",
                "recommended_variant_name": "catalyst_theme_relaxed_sector_frontier",
                "promoted_shadow_count": 1,
                "promoted_tickers": ["301001"],
                "recommended_relaxation_cost": 0.09,
                "recommendation": "优先跟踪 frontier promoted shadow。",
                "markdown_path": "/tmp/frontier.md",
                "promoted_shadow_watch": [
                    {
                        "ticker": "301001",
                        "candidate_score": 0.3874,
                        "filter_reason": "candidate_score_below_catalyst_theme_floor",
                        "total_shortfall": 0.06,
                        "failed_threshold_count": 1,
                        "preferred_entry_mode": "theme_research_followup",
                        "promotion_trigger": "若催化继续发酵，可升级到正式题材研究池。",
                        "top_reasons": ["candidate_score=0.39"],
                        "positive_tags": ["strong_catalyst_freshness"],
                        "threshold_shortfalls": {"candidate_score": 0.06},
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
            "catalyst_theme_shadow_watch": [
                {
                    "ticker": "301002",
                    "candidate_score": 0.32,
                    "filter_reason": "sector_resonance_below_catalyst_theme_floor",
                    "total_shortfall": 0.05,
                    "failed_threshold_count": 2,
                    "preferred_entry_mode": "theme_research_followup",
                    "promotion_trigger": "只做研究跟踪，不进入当日 BTST 交易名单。",
                    "top_reasons": ["candidate_score=0.32"],
                    "positive_tags": ["strong_catalyst_freshness"],
                    "threshold_shortfalls": {"candidate_score": 0.02, "sector_resonance": 0.03},
                    "metrics": {
                        "breakout_freshness": 0.14,
                        "trend_acceleration": 0.21,
                        "close_strength": 0.41,
                        "sector_resonance": 0.22,
                        "catalyst_freshness": 0.82,
                    },
                }
            ],
            "global_guardrails": ["priority board 只负责排序和分层，不改变 short-trade admission 默认语义。"],
            "source_paths": {
                "report_dir": "/tmp/report",
                "snapshot_path": "/tmp/snapshot.json",
                "session_summary_path": "/tmp/session_summary.json",
            },
        }
    )

    assert "# BTST Next-Day Priority Board" in markdown
    assert "## Overview" in markdown
    assert "### 1. 300757" in markdown
    assert "- execution_quality_label: balanced_confirmation" in markdown
    assert "## Catalyst Theme Frontier Priority" in markdown
    assert "- threshold_shortfalls: candidate_score=0.0600" in markdown
    assert "## Catalyst Theme Shadow Watch" in markdown
    assert "- key_metrics: breakout=0.1400, trend=0.2100, close=0.4100, sector=0.2200, catalyst=0.8200" in markdown
    assert "## Source Paths" in markdown


def test_generate_btst_next_day_priority_board_orders_trade_watch_opportunity_and_radar(tmp_path, monkeypatch):
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
                            "metrics_payload": {
                                "breakout_freshness": 0.935,
                                "trend_acceleration": 0.7275,
                                "volume_expansion_quality": 0.398,
                                "close_strength": 0.9019,
                                "catalyst_freshness": 0.8793,
                            },
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
                            "metrics_payload": {
                                "breakout_freshness": 0.8667,
                                "trend_acceleration": 0.7637,
                                "volume_expansion_quality": 0.3434,
                                "close_strength": 0.8895,
                                "catalyst_freshness": 0.7456,
                            },
                            "explainability_payload": {"candidate_source": "short_trade_boundary"},
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
                    },
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "src.paper_trading._btst_reporting.historical_prior._extract_next_day_outcome",
        lambda ticker, trade_date, price_cache: {
            "data_status": "ok",
            "next_trade_date": "2026-03-27",
            "next_open_return": 0.008,
            "next_high_return": 0.031,
            "next_close_return": 0.014,
            "next_open_to_close_return": 0.006,
        },
    )

    result = generate_btst_next_day_priority_board_artifacts(
        input_path=report_dir,
        output_dir=tmp_path,
        trade_date="2026-03-27",
        next_trade_date="2026-03-30",
    )

    payload = json.loads((tmp_path / "btst_next_day_priority_board_20260330.json").read_text(encoding="utf-8"))
    markdown = (tmp_path / "btst_next_day_priority_board_20260330.md").read_text(encoding="utf-8")

    assert result["analysis"]["headline"]
    assert "301001" in result["analysis"]["headline"]
    assert [row["ticker"] for row in payload["priority_rows"]] == ["300757", "601869", "300442", "002001"]
    assert payload["priority_rows"][0]["lane"] == "primary_entry"
    assert payload["priority_rows"][3]["lane"] == "research_upside_radar"
    assert payload["summary"]["catalyst_theme_frontier_promoted_count"] == 1
    assert payload["summary"]["catalyst_theme_shadow_count"] == 1
    assert payload["catalyst_theme_frontier_priority"]["promoted_tickers"] == ["301001"]
    assert payload["catalyst_theme_shadow_watch"][0]["ticker"] == "301001"
    assert payload["priority_rows"][0]["execution_quality_label"] == "balanced_confirmation"
    assert payload["priority_rows"][3]["actionability"] == "non_trade_learning_only"
    assert "# BTST Next-Day Priority Board" in markdown
    assert "### 1. 300757" in markdown
    assert "### 4. 002001" in markdown
    assert "## Catalyst Theme Frontier Priority" in markdown
    assert "## Catalyst Theme Shadow Watch" in markdown


def test_generate_btst_next_day_priority_board_places_demoted_weak_near_miss_in_opportunity_pool_lane(tmp_path):
    board = generate_btst_next_day_priority_board_artifacts(
        input_path={
            "trade_date": "2026-04-06",
            "next_trade_date": "2026-04-07",
            "selected_entries": [],
            "near_miss_entries": [],
            "opportunity_pool_entries": [
                {
                    "ticker": "603778",
                    "score_target": 0.4512,
                    "decision": "near_miss",
                    "reporting_decision": "opportunity_pool",
                    "preferred_entry_mode": "next_day_breakout_confirmation",
                    "top_reasons": ["trend_acceleration=0.79", "historical_zero_follow_through_demoted"],
                    "promotion_trigger": "历史同层兑现极弱，先降为机会池；只有盘中新强度确认时再考虑回到观察层。",
                    "historical_prior": {
                        "monitor_priority": "low",
                        "execution_priority": "low",
                        "execution_quality_label": "zero_follow_through",
                        "summary": "同层同源历史 3 例，next_high>=2.0% 命中率=0.0，next_close 正收益率=0.0。 历史同层兑现为 0，降级到机会池等待新增强度。",
                        "execution_note": "历史同层样本几乎不给盘中空间，也没有收盘正收益，除非出现新的强确认，否则不应进入高优先级执行面。",
                        "demoted_from_near_miss": True,
                    },
                }
            ],
            "research_upside_radar_entries": [],
            "catalyst_theme_shadow_entries": [],
            "catalyst_theme_frontier_priority": {},
        },
        output_dir=tmp_path,
    )

    payload = json.loads((tmp_path / "btst_next_day_priority_board_20260407.json").read_text(encoding="utf-8"))
    markdown = (tmp_path / "btst_next_day_priority_board_20260407.md").read_text(encoding="utf-8")

    assert [row["ticker"] for row in payload["priority_rows"]] == ["603778"]
    assert payload["priority_rows"][0]["lane"] == "opportunity_pool"
    assert payload["priority_rows"][0]["actionability"] == "upgrade_only"
    assert payload["priority_rows"][0]["execution_quality_label"] == "zero_follow_through"
    assert "### 1. 603778" in markdown
    assert "lane: opportunity_pool" in markdown
    assert "historical_zero_follow_through_demoted" in markdown


def test_generate_btst_next_day_priority_board_surfaces_no_history_observer_lane(tmp_path):
    board = generate_btst_next_day_priority_board_artifacts(
        input_path={
            "trade_date": "2026-03-23",
            "next_trade_date": "2026-03-24",
            "selected_entries": [],
            "near_miss_entries": [],
            "opportunity_pool_entries": [],
            "no_history_observer_entries": [
                {
                    "ticker": "003036",
                    "preferred_entry_mode": "next_day_breakout_confirmation",
                    "promotion_trigger": "暂无可评估历史先验；只有盘中新证据显著增强时，才允许从 no-history observer 升级。",
                    "top_reasons": ["no_history_observer_rebucket"],
                    "historical_prior": {
                        "monitor_priority": "medium",
                        "execution_priority": "unscored",
                        "execution_quality_label": "unknown",
                        "summary": "暂无同层可评估历史样本。 暂无可评估历史先验，已移入 no-history observer。",
                        "execution_note": "先看盘中新证据，再决定是否重新评估。",
                    },
                }
            ],
            "risky_observer_entries": [],
            "research_upside_radar_entries": [],
            "catalyst_theme_shadow_entries": [],
            "catalyst_theme_frontier_priority": {},
        },
        output_dir=tmp_path,
    )

    payload = json.loads((tmp_path / "btst_next_day_priority_board_20260324.json").read_text(encoding="utf-8"))
    markdown = (tmp_path / "btst_next_day_priority_board_20260324.md").read_text(encoding="utf-8")

    assert board["analysis"]["summary"]["no_history_observer_count"] == 1
    assert [row["ticker"] for row in payload["priority_rows"]] == ["003036"]
    assert payload["priority_rows"][0]["lane"] == "no_history_observer"
    assert payload["priority_rows"][0]["actionability"] == "observe_only_no_history"
    assert "### 1. 003036" in markdown
    assert "lane: no_history_observer" in markdown


def test_generate_btst_next_day_priority_board_filters_execution_blocked_formal_entries(tmp_path):
    board = generate_btst_next_day_priority_board_artifacts(
        input_path={
            "trade_date": "2026-04-22",
            "next_trade_date": "2026-04-23",
            "selected_entries": [
                {
                    "ticker": "300724",
                    "decision": "selected",
                    "reporting_decision": "blocked",
                    "execution_blocked": True,
                    "score_target": 0.61,
                    "preferred_entry_mode": "next_day_breakout_confirmation",
                    "historical_prior": {},
                }
            ],
            "near_miss_entries": [
                {
                    "ticker": "688313",
                    "decision": "near_miss",
                    "reporting_decision": "blocked",
                    "execution_blocked": True,
                    "score_target": 0.55,
                    "preferred_entry_mode": "next_day_breakout_confirmation",
                    "historical_prior": {},
                }
            ],
            "opportunity_pool_entries": [],
            "research_upside_radar_entries": [],
            "catalyst_theme_shadow_entries": [],
            "catalyst_theme_frontier_priority": {},
        },
        output_dir=tmp_path,
    )

    payload = json.loads((tmp_path / "btst_next_day_priority_board_20260423.json").read_text(encoding="utf-8"))
    markdown = (tmp_path / "btst_next_day_priority_board_20260423.md").read_text(encoding="utf-8")

    assert board["analysis"]["summary"]["primary_count"] == 0
    assert payload["summary"]["near_miss_count"] == 0
    assert payload["priority_rows"] == []
    assert "300724" not in markdown
    assert "688313" not in markdown


def test_generate_btst_next_day_priority_board_uses_execution_quality_specific_suggested_actions(tmp_path):
    generate_btst_next_day_priority_board_artifacts(
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
                        "execution_quality_label": "intraday_only",
                        "summary": "同票历史 4 例，next_close 正收益率=0.0000。",
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
                    "historical_prior": {
                        "execution_quality_label": "gap_chase_risk",
                        "summary": "同票历史 6 例，next_close 正收益率=0.6667。",
                        "execution_note": "历史上更像高开后回落，避免开盘直接追价。",
                    },
                }
            ],
            "research_upside_radar_entries": [],
            "catalyst_theme_shadow_entries": [],
            "catalyst_theme_frontier_summary": {},
            "catalyst_theme_frontier_priority": {},
        },
        output_dir=tmp_path,
    )

    payload = json.loads((tmp_path / "btst_next_day_priority_board_20260407.json").read_text(encoding="utf-8"))

    assert [row["ticker"] for row in payload["priority_rows"]] == ["300720", "300757"]
    assert payload["priority_rows"][0]["lane"] == "near_miss_watch"
    assert "intraday" in payload["priority_rows"][0]["suggested_action"]
    assert payload["priority_rows"][1]["lane"] == "opportunity_pool"
    assert "避免开盘直接追价" in payload["priority_rows"][1]["suggested_action"]


def test_generate_btst_next_day_priority_board_backfills_confirm_then_hold_mode_from_close_continuation(tmp_path):
    generate_btst_next_day_priority_board_artifacts(
        input_path={
            "trade_date": "2026-03-31",
            "next_trade_date": "2026-04-01",
            "summary": {},
            "selected_entries": [],
            "near_miss_entries": [
                {
                    "ticker": "601869",
                    "top_reasons": ["historical_execution_relief_applied"],
                    "historical_prior": {
                        "execution_quality_label": "close_continuation",
                        "entry_timing_bias": "confirm_then_hold",
                        "summary": "同票历史 4 例，next_close 正收益率=1.0000。",
                        "execution_note": "确认后若量价延续良好，可保留收盘 follow-through。",
                    },
                }
            ],
            "opportunity_pool_entries": [],
            "research_upside_radar_entries": [],
            "catalyst_theme_shadow_entries": [],
            "catalyst_theme_frontier_summary": {},
            "catalyst_theme_frontier_priority": {},
        },
        output_dir=tmp_path,
    )

    payload = json.loads((tmp_path / "btst_next_day_priority_board_20260401.json").read_text(encoding="utf-8"))

    assert payload["priority_rows"][0]["preferred_entry_mode"] == "confirm_then_hold_breakout"
    assert "continuation 确认" in payload["priority_rows"][0]["suggested_action"]
    assert "持有到收盘" in payload["priority_rows"][0]["suggested_action"]
    assert "T+2 bias" in payload["priority_rows"][0]["execution_note"]
