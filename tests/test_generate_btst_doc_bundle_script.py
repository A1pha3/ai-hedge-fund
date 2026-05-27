from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_btst_doc_bundle import generate_btst_doc_bundle


def _write_json(path: Path, payload: object) -> None:
    """Write one JSON fixture file for the document-bundle test."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_generate_btst_doc_bundle_writes_early_runner_sections(tmp_path: Path) -> None:
    """Generate a compact BTST bundle and verify early-runner sections are included."""
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_20260526_20260526_live_m2_7_short_trade_only_20260527_plan"
    brief_path = report_dir / "btst_next_day_trade_brief_latest.json"
    _write_json(
        report_dir / "session_summary.json",
        {
            "trade_date": "2026-05-26",
            "selection_target": "short_trade_only",
            "btst_followup": {
                "brief_json": brief_path.as_posix(),
            },
            "optimization_profile_resolution": {
                "profile_name": "momentum_optimized",
            },
        },
    )
    _write_json(
        brief_path,
        {
            "trade_date": "2026-05-26",
            "next_trade_date": "2026-05-27",
            "selection_target": "short_trade_only",
            "primary_action": {
                "ticker": "300054",
                "name": "鼎龙股份",
                "preferred_entry_mode": "confirm_then_hold_breakout",
            },
            "selected_actions": [
                {
                    "ticker": "300054",
                    "name": "鼎龙股份",
                    "action_tier": "primary_entry",
                    "preferred_entry_mode": "confirm_then_hold_breakout",
                    "score_target": 0.5588,
                    "historical_prior": {
                        "next_close_positive_rate": 0.6667,
                        "next_close_payoff_ratio": 1.42,
                    },
                }
            ],
            "watch_actions": [
                {
                    "ticker": "300476",
                    "name": "胜宏科技",
                    "action_tier": "watch_only",
                    "preferred_entry_mode": "confirm_then_hold_breakout",
                    "score_target": 0.4308,
                    "historical_prior": {
                        "next_close_positive_rate": 0.9355,
                        "next_close_payoff_ratio": 2.31,
                    },
                }
            ],
            "opportunity_actions": [],
        },
    )
    _write_json(
        reports_root / "btst_full_report_20260526.json",
        {
            "trade_date": "20260526",
            "next_date": "20260527",
            "pool_size": 3200,
            "selected_count": 780,
            "near_miss_count": 760,
            "high_confidence": [
                {
                    "ticker": "603725",
                    "name": "天安新材",
                    "score": 0.8269,
                    "pct_chg": 5.56,
                }
            ],
        },
    )
    _write_json(
        reports_root / "btst_early_runner_v1_latest.json",
        {
            "daily_boards": [
                {
                    "trade_date": "2026-05-26",
                    "gate_action": "tradeable",
                    "deployment_mode": "shadow_only",
                    "early_runner_watchlist": [
                        {
                            "ticker": "300054",
                            "name": "鼎龙股份",
                            "entry_status": "filled",
                            "pre_score": 0.71,
                            "confirm_score": 0.82,
                            "preferred_entry_mode": "confirm_then_hold_breakout",
                            "historical_prior": {
                                "next_close_positive_rate": 0.6667,
                                "next_close_payoff_ratio": 1.42,
                            },
                        }
                    ],
                    "early_runner_priority": [
                        {
                            "ticker": "300054",
                            "name": "鼎龙股份",
                            "entry_status": "filled",
                            "pre_score": 0.71,
                            "confirm_score": 0.82,
                            "preferred_entry_mode": "confirm_then_hold_breakout",
                            "historical_prior": {
                                "next_close_positive_rate": 0.6667,
                                "next_close_payoff_ratio": 1.42,
                            },
                        },
                        {
                            "ticker": "603725",
                            "name": "天安新材",
                            "entry_status": "not_confirmed",
                            "pre_score": 0.66,
                            "confirm_score": 0.41,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "historical_prior": {
                                "next_close_positive_rate": 0.58,
                                "next_close_payoff_ratio": 1.1,
                            },
                        },
                    ],
                    "second_entry_reentry": [
                        {
                            "ticker": "605500",
                            "name": "森林包装",
                            "entry_status": "watch_only",
                            "pre_score": 0.55,
                            "confirm_score": 0.33,
                            "preferred_entry_mode": "second_entry_reentry",
                            "historical_prior": {
                                "next_close_positive_rate": 0.54,
                                "next_close_payoff_ratio": 1.08,
                            },
                        }
                    ],
                }
            ]
        },
    )

    output_dir = tmp_path / "outputs"
    result = generate_btst_doc_bundle(
        "20260526",
        reports_root=reports_root,
        output_dir=output_dir,
        refresh_early_runner=False,
    )

    assert result["status"] == "generated"
    assert result["early_runner_status"] == "exact"
    assert result["early_runner_intersection_count"] == 1
    assert result["early_runner_only_count"] == 1
    assert result["early_runner_second_entry_count"] == 1
    assert len(result["written_files"]) == 7
    llm_doc = (output_dir / "BTST-LLM-20260526.md").read_text(encoding="utf-8")
    assert "## Early Runner 章节" in llm_doc
    assert "## 交集票高亮" in llm_doc
    assert "交集优先复审" in llm_doc
    assert "### 补充复审层" in llm_doc
    assert "### 回补机会层" in llm_doc
    assert "与正式 BTST 的重合票" in llm_doc
    assert "603725" in llm_doc
    checklist_doc = (output_dir / "BTST-20260526-EXEC-CHECKLIST.md").read_text(encoding="utf-8")
    assert "## 交集优先复审" in checklist_doc
    assert "## 回补机会层" in checklist_doc
    assert "交集优先：`300054 鼎龙股份`" in checklist_doc
    assert "Early Runner 补充复审：`603725 天安新材`" in checklist_doc
    assert "Second Entry / Reentry：`605500 森林包装`" in checklist_doc
    early_warning_doc = (output_dir / "BTST-20260526-EARLY-WARNING.md").read_text(encoding="utf-8")
    assert "## 交集票高亮" in early_warning_doc
    assert "## Priority" in early_warning_doc
    assert "605500" in early_warning_doc


def test_generate_btst_doc_bundle_marks_stale_overlap_as_reference_only(tmp_path: Path) -> None:
    """Mark overlaps as reference-only when early-runner falls back to an older board."""
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_20260526_20260526_live_m2_7_short_trade_only_20260527_plan"
    brief_path = report_dir / "btst_next_day_trade_brief_latest.json"
    _write_json(
        report_dir / "session_summary.json",
        {
            "trade_date": "2026-05-26",
            "selection_target": "short_trade_only",
            "btst_followup": {
                "brief_json": brief_path.as_posix(),
            },
        },
    )
    _write_json(
        brief_path,
        {
            "trade_date": "2026-05-26",
            "next_trade_date": "2026-05-27",
            "selection_target": "short_trade_only",
            "primary_entry": {
                "ticker": "300054",
                "name": "鼎龙股份",
                "preferred_entry_mode": "confirm_then_hold_breakout",
            },
            "selected_entries": [
                {
                    "ticker": "300054",
                    "name": "鼎龙股份",
                    "preferred_entry_mode": "confirm_then_hold_breakout",
                    "historical_prior": {
                        "next_close_positive_rate": 0.6667,
                    },
                }
            ],
        },
    )
    _write_json(
        reports_root / "btst_full_report_20260526.json",
        {
            "trade_date": "20260526",
            "next_date": "20260527",
            "pool_size": 3200,
            "selected_count": 780,
            "near_miss_count": 760,
            "high_confidence": [],
        },
    )
    _write_json(
        reports_root / "btst_early_runner_v1_latest.json",
        {
            "daily_boards": [
                {
                    "trade_date": "2026-05-20",
                    "gate_action": "research_only",
                    "deployment_mode": "research_only",
                    "early_runner_watchlist": [
                        {
                            "ticker": "300054",
                            "name": "鼎龙股份",
                            "entry_status": "filled",
                            "pre_score": 0.71,
                            "confirm_score": 0.82,
                        }
                    ],
                    "early_runner_priority": [],
                    "second_entry_reentry": [],
                }
            ]
        },
    )

    output_dir = tmp_path / "outputs"
    result = generate_btst_doc_bundle(
        "20260526",
        reports_root=reports_root,
        output_dir=output_dir,
        refresh_early_runner=False,
    )

    assert result["early_runner_status"] == "stale_fallback"
    checklist_doc = (output_dir / "BTST-20260526-EXEC-CHECKLIST.md").read_text(encoding="utf-8")
    assert "历史交集参考：`300054 鼎龙股份`" in checklist_doc
    llm_doc = (output_dir / "BTST-LLM-20260526.md").read_text(encoding="utf-8")
    assert "只能作为参考高亮" in llm_doc


def test_generate_btst_doc_bundle_keeps_second_entry_out_of_only_early_runner_layer(tmp_path: Path) -> None:
    """Keep second-entry rows separate from only-early-runner rows in the four-layer output."""
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_20260526_20260526_live_m2_7_short_trade_only_20260527_plan"
    brief_path = report_dir / "btst_next_day_trade_brief_latest.json"
    _write_json(
        report_dir / "session_summary.json",
        {
            "trade_date": "2026-05-26",
            "selection_target": "short_trade_only",
            "btst_followup": {
                "brief_json": brief_path.as_posix(),
            },
        },
    )
    _write_json(
        brief_path,
        {
            "trade_date": "2026-05-26",
            "next_trade_date": "2026-05-27",
            "selection_target": "short_trade_only",
            "selected_actions": [],
            "watch_actions": [],
            "opportunity_actions": [],
        },
    )
    _write_json(
        reports_root / "btst_full_report_20260526.json",
        {
            "trade_date": "20260526",
            "next_date": "20260527",
            "pool_size": 3200,
            "selected_count": 0,
            "near_miss_count": 0,
            "high_confidence": [],
        },
    )
    _write_json(
        reports_root / "btst_early_runner_v1_latest.json",
        {
            "daily_boards": [
                {
                    "trade_date": "2026-05-26",
                    "gate_action": "tradeable",
                    "deployment_mode": "shadow_only",
                    "early_runner_watchlist": [],
                    "early_runner_priority": [
                        {
                            "ticker": "300001",
                            "name": "特锐德",
                            "entry_status": "not_confirmed",
                            "pre_score": 0.67,
                            "confirm_score": 0.42,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                        }
                    ],
                    "second_entry_reentry": [
                        {
                            "ticker": "300002",
                            "name": "神州泰岳",
                            "entry_status": "watch_only",
                            "pre_score": 0.51,
                            "confirm_score": 0.36,
                            "preferred_entry_mode": "second_entry_reentry",
                        }
                    ],
                }
            ]
        },
    )

    output_dir = tmp_path / "outputs"
    result = generate_btst_doc_bundle(
        "20260526",
        reports_root=reports_root,
        output_dir=output_dir,
        refresh_early_runner=False,
    )

    assert result["early_runner_intersection_count"] == 0
    assert result["early_runner_only_count"] == 1
    assert result["early_runner_second_entry_count"] == 1
    checklist_doc = (output_dir / "BTST-20260526-EXEC-CHECKLIST.md").read_text(encoding="utf-8")
    assert "Early Runner 补充复审：`300001 特锐德`" in checklist_doc
    assert "Second Entry / Reentry：`300002 神州泰岳`" in checklist_doc
    assert "Early Runner 补充复审：`300002 神州泰岳`" not in checklist_doc
