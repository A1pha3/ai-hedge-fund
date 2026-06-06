from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_btst_latest_close_validation import generate_btst_latest_close_validation_artifacts


def test_generate_btst_latest_close_validation_artifact(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_20260401_20260401_live_m2_7_short_trade_only_20260401"
    report_dir.mkdir(parents=True, exist_ok=True)
    session_summary_path = report_dir / "session_summary.json"
    priority_board_path = report_dir / "btst_next_day_priority_board_20260402.json"
    brief_path = report_dir / "btst_next_day_trade_brief_latest.json"
    session_summary_path.write_text(json.dumps({"ok": True}, ensure_ascii=False, indent=2), encoding="utf-8")
    priority_board_path.write_text(json.dumps({"ok": True}, ensure_ascii=False, indent=2), encoding="utf-8")
    brief_path.write_text(
        json.dumps(
            {
                "upstream_shadow_summary": {
                    "shadow_candidate_count": 2,
                    "promotable_count": 1,
                    "lane_counts": {
                        "layer_a_liquidity_corridor": 1,
                        "post_gate_liquidity_competition": 1,
                    },
                    "top_focus_tickers": ["601869", "300166"],
                },
                "upstream_shadow_entries": [
                    {
                        "ticker": "601869",
                        "decision": "near_miss",
                        "candidate_source": "upstream_liquidity_corridor_shadow",
                        "candidate_pool_lane_display": "layer_a_liquidity_corridor",
                        "score_target": 0.5647,
                        "promotion_trigger": "影子召回样本已进入 near-miss 观察层，只能做盘中跟踪，不可预设交易。",
                    },
                    {
                        "ticker": "300166",
                        "decision": "rejected",
                        "candidate_source": "post_gate_liquidity_competition_shadow",
                        "candidate_pool_lane_display": "post_gate_liquidity_competition",
                        "score_target": 0.4211,
                        "promotion_trigger": "影子召回样本尚未进入可执行层，只有盘中新强度确认后才允许升级。",
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    nightly_payload = {
        "latest_btst_run": {
            "report_dir": "data/reports/paper_trading_20260401_20260401_live_m2_7_short_trade_only_20260401",
            "report_dir_abs": str(report_dir.resolve()),
            "trade_date": "2026-04-01",
            "next_trade_date": "2026-04-02",
            "selection_target": "short_trade_only",
        },
        "control_tower_snapshot": {
            "synthesis": {
                "latest_btst_followup": {
                    "priority_board_headline": "当前没有主票，优先看 near-miss，其次看机会池和 research 漏票雷达。",
                    "selected_count": 0,
                    "near_miss_count": 2,
                    "blocked_count": 2,
                    "rejected_count": 5,
                    "opportunity_pool_count": 2,
                    "brief_recommendation": "当前没有主票，只保留观察层。",
                },
                "waiting_lane_count": 5,
                "ready_lane_count": 0,
                "lane_matrix": [
                    {
                        "lane_id": "primary_roll_forward",
                        "ticker": "001309",
                        "lane_status": "continue_controlled_roll_forward",
                        "validation_verdict": "await_new_independent_window_data",
                        "missing_window_count": 1,
                        "next_step": "collect second window",
                    },
                    {
                        "lane_id": "recurring_shadow_close_candidate",
                        "ticker": "300113",
                        "lane_status": "await_new_close_candidate_window",
                        "validation_verdict": "await_new_independent_window_data",
                        "missing_window_count": 1,
                        "next_step": "rerun close bundle",
                    },
                    {
                        "lane_id": "recurring_intraday_control",
                        "ticker": "600821",
                        "lane_status": "await_new_intraday_control_window",
                        "validation_verdict": "await_new_independent_window_data",
                        "missing_window_count": 1,
                        "next_step": "hold intraday control",
                    },
                ],
            },
            "validation": {
                "overall_verdict": "pass",
                "pass_count": 6,
                "warn_count": 0,
                "fail_count": 0,
            },
        },
        "latest_priority_board_snapshot": {
            "headline": "当前没有主票，优先看 near-miss，其次看机会池和 research 漏票雷达。",
            "brief_recommendation": "当前没有主票，只保留观察层。",
            "priority_rows": [
                {
                    "ticker": "601869",
                    "lane": "near_miss_watch",
                    "actionability": "watch_only",
                    "score_target": 0.5647,
                    "execution_quality_label": "close_continuation",
                    "suggested_action": "仅做盘中跟踪。",
                },
                {
                    "ticker": "300166",
                    "lane": "near_miss_watch",
                    "actionability": "watch_only",
                    "score_target": 0.5562,
                    "execution_quality_label": "balanced_confirmation",
                    "suggested_action": "仅做盘中跟踪。",
                },
            ],
        },
        "latest_btst_snapshot": {
            "priority_board_json_path": str(priority_board_path.resolve()),
            "brief_json_path": str(brief_path.resolve()),
        },
    }
    delta_payload = {
        "comparison_basis": "nightly_history",
        "comparison_scope": "same_report_rerun",
        "overall_delta_verdict": "stable",
        "material_change_anchor": {
            "reference_generated_at": "2026-04-01T22:20:01",
            "reference_report_dir": "data/reports/paper_trading_20260331_20260331_live_m2_7_short_trade_only_20260401_catalyst_shadow_llm_digest",
            "comparison_scope": "report_rollforward",
            "overall_delta_verdict": "changed",
            "priority_delta": {
                "previous_headline": "旧 headline",
                "current_headline": "当前没有主票，优先看 near-miss，其次看机会池和 research 漏票雷达。",
                "headline_changed": True,
                "summary_delta": {"near_miss_count": -1, "opportunity_pool_count": 1},
                "added_tickers": [{"ticker": "300166", "lane": "near_miss_watch", "actionability": "watch_only"}],
                "removed_tickers": [{"ticker": "002460", "lane": "near_miss_watch", "actionability": "watch_only"}],
            },
        },
    }

    result = generate_btst_latest_close_validation_artifacts(
        nightly_payload=nightly_payload,
        delta_payload=delta_payload,
        nightly_json_path=reports_root / "btst_nightly_control_tower_latest.json",
        delta_json_path=reports_root / "btst_open_ready_delta_latest.json",
        output_json=reports_root / "btst_latest_close_validation_latest.json",
        output_md=reports_root / "btst_latest_close_validation_latest.md",
    )

    payload = result["payload"]
    assert payload["current_followup"]["summary"]["selected_count"] == 0
    assert payload["current_followup"]["summary"]["upstream_shadow_candidate_count"] == 2
    assert payload["current_followup"]["summary"]["upstream_shadow_promotable_count"] == 1
    assert payload["governance_check"]["overall_verdict"] == "pass"
    assert payload["rollforward_delta"]["added_tickers"][0]["ticker"] == "300166"
    assert any("仍无正式主票" in item for item in payload["key_conclusions"])
    assert any("上游影子召回已捕获 2 支补票样本" in item for item in payload["key_conclusions"])

    markdown = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "# BTST Latest Close Validation" in markdown
    assert "## Tonight Verdict" in markdown
    assert "## Upstream Shadow Recall" in markdown
    assert "601869" in markdown
    assert "300166" in markdown
    assert "lane_counts: layer_a_liquidity_corridor=1, post_gate_liquidity_competition=1" in markdown
    assert "overall_verdict: pass" in markdown