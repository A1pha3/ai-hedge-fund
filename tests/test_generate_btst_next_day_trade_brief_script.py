from __future__ import annotations

import json

import pandas as pd

from scripts.generate_btst_next_day_trade_brief import analyze_btst_next_day_trade_brief, render_btst_next_day_trade_brief_markdown
from src.paper_trading.btst_reporting import infer_next_trade_date


def test_generate_btst_next_day_trade_brief_separates_short_trade_from_research(tmp_path):
    report_dir = tmp_path / "report"
    trade_dir = report_dir / "selection_artifacts" / "2026-03-27"
    trade_dir.mkdir(parents=True)

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
                                "candidate_source": "short_trade_boundary",
                            },
                        },
                    },
                    "002001": {
                        "ticker": "002001",
                        "research": {
                            "decision": "selected",
                            "score_target": 0.2912,
                        },
                        "short_trade": {
                            "decision": "rejected",
                            "score_target": 0.3130,
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

    analysis = analyze_btst_next_day_trade_brief(report_dir, trade_date="2026-03-27", next_trade_date="2026-03-30")

    assert analysis["primary_entry"]["ticker"] == "300757"
    assert [entry["ticker"] for entry in analysis["selected_entries"]] == ["300757"]
    assert [entry["ticker"] for entry in analysis["near_miss_entries"]] == ["601869"]
    assert [entry["ticker"] for entry in analysis["excluded_research_entries"]] == ["002001"]
    assert "300757" in analysis["recommendation"]
    assert "002001" in analysis["recommendation"]


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
                        "research": {"decision": "selected", "score_target": 0.2912},
                        "short_trade": {"decision": "rejected", "score_target": 0.3130, "preferred_entry_mode": "next_day_breakout_confirmation"},
                        "delta_summary": ["research target selected while short trade target stays rejected"],
                    },
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_btst_next_day_trade_brief(report_dir, trade_date="2026-03-27", next_trade_date="2026-03-30")
    markdown = render_btst_next_day_trade_brief_markdown(analysis)

    assert "# BTST Next-Day Trade Brief" in markdown
    assert "### 300757" in markdown
    assert "### 002001" in markdown
    assert "Research Picks Excluded From Short-Trade Brief" in markdown


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