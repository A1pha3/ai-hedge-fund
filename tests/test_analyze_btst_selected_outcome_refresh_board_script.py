from __future__ import annotations

import json

from scripts.analyze_btst_selected_outcome_refresh_board import (
    analyze_btst_selected_outcome_refresh_board,
    render_btst_selected_outcome_refresh_board_markdown,
)


def test_analyze_btst_selected_outcome_refresh_board_tracks_current_cycle(monkeypatch, tmp_path):
    report_dir = tmp_path / "report"
    trade_dir = report_dir / "selection_artifacts" / "2026-04-09"
    trade_dir.mkdir(parents=True)
    snapshot = {
        "trade_date": "2026-04-09",
        "selection_targets": {
            "002001": {"short_trade": {"decision": "selected", "score_target": 0.4493}},
            "300001": {"short_trade": {"decision": "rejected", "score_target": 0.31}},
        },
    }
    (trade_dir / "selection_snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False) + "\n", encoding="utf-8")

    monkeypatch.setattr(
        "scripts.analyze_btst_selected_outcome_refresh_board.analyze_btst_selected_outcome_proof",
        lambda report_dir, ticker=None: {
            "ticker": ticker,
            "decision": "selected",
            "candidate_source": "catalyst_theme",
            "preferred_entry_mode": "confirm_then_hold_breakout",
            "score_target": 0.4493,
            "effective_select_threshold": 0.45,
            "selected_score_tolerance": 0.001,
            "selected_within_tolerance": True,
            "summary": {
                "evidence_case_count": 1,
                "next_close_positive_rate": 1.0,
                "t_plus_2_close_positive_rate": 1.0,
                "t_plus_3_close_positive_rate": 0.0,
                "t_plus_4_close_positive_rate": 0.0,
            },
            "recommendation": "historical proof ok",
        },
    )
    monkeypatch.setattr(
        "scripts.analyze_btst_selected_outcome_refresh_board._extract_holding_outcome",
        lambda ticker, trade_date, price_cache: {
            "data_status": "ok",
            "cycle_status": "t1_only",
            "next_trade_date": "2026-04-10",
            "next_open_return": 0.01,
            "next_high_return": 0.05,
            "next_close_return": 0.04,
            "t_plus_2_close_return": None,
            "t_plus_3_close_return": None,
            "t_plus_4_close_return": None,
        },
    )

    analysis = analyze_btst_selected_outcome_refresh_board(tmp_path)
    markdown = render_btst_selected_outcome_refresh_board_markdown(analysis)

    assert analysis["selected_count"] == 1
    assert analysis["entries"][0]["ticker"] == "002001"
    assert analysis["entries"][0]["current_cycle_status"] == "t1_only"
    assert analysis["entries"][0]["next_day_contract_verdict"] == "matched_positive_expectation"
    assert analysis["entries"][0]["overall_contract_verdict"] == "next_close_confirmed_wait_t_plus_2"
    assert analysis["current_cycle_status_counts"] == {"t1_only": 1}
    assert "next-day 可评估阶段" in analysis["recommendation"]
    assert "002001" in markdown
