from __future__ import annotations

import json

from src.paper_trading.btst_reporting import generate_btst_next_day_priority_board_artifacts


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
    assert "### 1. 301001" in markdown
    assert "lane: catalyst_theme_frontier_priority" in markdown
    assert "filter_reason: candidate_score_below_catalyst_theme_floor" in markdown
    assert "non_trade_learning_only" in markdown
