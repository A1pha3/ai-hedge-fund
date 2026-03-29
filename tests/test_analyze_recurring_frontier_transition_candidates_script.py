from __future__ import annotations

import json

from scripts.analyze_recurring_frontier_transition_candidates import analyze_recurring_frontier_transition_candidates


def test_analyze_recurring_frontier_transition_candidates_marks_emergent_local_baselines(tmp_path):
    recurring_frontier_report = tmp_path / "recurring_frontier.json"
    old_report = tmp_path / "old_report"
    current_report = tmp_path / "current_report"
    (old_report / "selection_artifacts" / "2026-03-23").mkdir(parents=True)
    (current_report / "selection_artifacts" / "2026-03-23").mkdir(parents=True)
    (current_report / "selection_artifacts" / "2026-03-25").mkdir(parents=True)

    recurring_frontier_report.write_text(
        json.dumps(
            {
                "priority_queue": [
                    {"ticker": "600821", "occurrence_count": 3, "minimal_adjustment_cost": 0.1},
                    {"ticker": "002015", "occurrence_count": 3, "minimal_adjustment_cost": 0.12},
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (old_report / "selection_artifacts" / "2026-03-23" / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-23",
                "layer_b": {
                    "tickers": [
                        {"ticker": "600821", "reason": "below_fast_score_threshold", "score_b": 0.146, "decision": "neutral", "rank": 28},
                        {"ticker": "002015", "reason": "below_fast_score_threshold", "score_b": -1.0, "decision": "strong_sell", "rank": 199},
                    ]
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    for trade_date in ["2026-03-23", "2026-03-25"]:
        (current_report / "selection_artifacts" / trade_date / "selection_snapshot.json").write_text(
            json.dumps(
                {
                    "trade_date": trade_date,
                    "targets": {
                        "600821": {"ticker": "600821", "trade_date": trade_date, "candidate_source": "short_trade_boundary", "short_trade": {"decision": "rejected", "score_target": 0.36, "rank_hint": 2, "gate_status": {"score": "fail"}, "metrics_payload": {}}},
                        "002015": {"ticker": "002015", "trade_date": trade_date, "candidate_source": "short_trade_boundary", "short_trade": {"decision": "rejected", "score_target": 0.35, "rank_hint": 5, "gate_status": {"score": "fail"}, "metrics_payload": {}}},
                    },
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    analysis = analyze_recurring_frontier_transition_candidates(
        recurring_frontier_report,
        role_history_report_dirs=[old_report, current_report],
    )

    assert analysis["candidates"][0]["transition_locality"] == "emergent_local_baseline"
    assert analysis["candidates"][1]["transition_locality"] == "emergent_local_baseline"
    assert "current-window emergent baselines" in analysis["recommendation"]


def test_analyze_recurring_frontier_transition_candidates_accepts_discovered_report_dirs(tmp_path):
    recurring_frontier_report = tmp_path / "recurring_frontier.json"
    report_root = tmp_path / "reports"
    old_report = report_root / "paper_trading_window_old"
    current_report = report_root / "paper_trading_window_current"
    (old_report / "selection_artifacts" / "2026-03-23").mkdir(parents=True)
    (current_report / "selection_artifacts" / "2026-03-24").mkdir(parents=True)
    (current_report / "selection_artifacts" / "2026-03-25").mkdir(parents=True)

    recurring_frontier_report.write_text(
        json.dumps({"priority_queue": [{"ticker": "600821", "occurrence_count": 2, "minimal_adjustment_cost": 0.1}]}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (old_report / "selection_artifacts" / "2026-03-23" / "selection_snapshot.json").write_text(
        json.dumps({"trade_date": "2026-03-23", "layer_b": {"tickers": [{"ticker": "600821", "reason": "below_fast_score_threshold", "score_b": 0.1, "decision": "neutral", "rank": 1}]}} , ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    for trade_date in ["2026-03-24", "2026-03-25"]:
        (current_report / "selection_artifacts" / trade_date / "selection_snapshot.json").write_text(
            json.dumps({"trade_date": trade_date, "targets": {"600821": {"ticker": "600821", "trade_date": trade_date, "candidate_source": "short_trade_boundary", "short_trade": {"decision": "rejected", "score_target": 0.36, "rank_hint": 2, "gate_status": {"score": "fail"}, "metrics_payload": {}}}}}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    analysis = analyze_recurring_frontier_transition_candidates(
        recurring_frontier_report,
        role_history_report_dirs=[old_report, current_report],
    )

    assert analysis["candidates"][0]["previous_window_role"] == "layer_b_pool_below_fast_score_threshold"
    assert analysis["candidates"][0]["transition_locality"] == "emergent_local_baseline"