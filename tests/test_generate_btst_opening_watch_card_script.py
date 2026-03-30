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
                },
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
    assert [item["ticker"] for item in payload["focus_items"]] == ["300757", "601869", "300442"]
    assert payload["focus_items"][0]["historical_summary"] is not None
    assert payload["focus_items"][0]["execution_note"] is not None
    assert payload["focus_items"][1]["historical_summary"] is not None
    assert payload["focus_items"][2]["historical_summary"] is not None
    assert "# BTST Opening Watch Card" in markdown
    assert "### 1. 300757" in markdown
    assert "### 2. 601869" in markdown
    assert "### 3. 300442" in markdown
    assert "execution_note" in markdown
    assert "historical_summary" in markdown