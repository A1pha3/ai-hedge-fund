from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_btst_carryover_aligned_peer_proof_board import analyze_btst_carryover_aligned_peer_proof_board


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_analyze_btst_carryover_aligned_peer_proof_board_promotes_supportive_peer(tmp_path: Path) -> None:
    harvest_path = tmp_path / "harvest.json"
    expansion_path = tmp_path / "expansion.json"
    selected_refresh_path = tmp_path / "selected_refresh.json"

    _write_json(
        harvest_path,
        {
            "ticker": "002001",
            "harvest_entries": [
                {
                    "ticker": "301396",
                    "harvest_status": "promotion_review_ready",
                    "latest_trade_date": "2026-04-10",
                    "latest_scope": "same_family_source_score_catalyst",
                    "latest_score_target": 0.4395,
                    "closed_cycle_count": 1,
                    "next_day_available_count": 1,
                    "rows": [
                        {
                            "trade_date": "2026-04-10",
                            "scope": "same_family_source_score_catalyst",
                            "next_high_return": 0.041,
                            "next_close_return": 0.032,
                            "t_plus_2_close_return": 0.027,
                        }
                    ],
                },
                {
                    "ticker": "688498",
                    "harvest_status": "promotion_review_ready",
                    "latest_trade_date": "2026-04-10",
                    "latest_scope": "same_family_source_score_catalyst",
                    "latest_score_target": 0.435,
                    "closed_cycle_count": 1,
                    "next_day_available_count": 1,
                    "rows": [
                        {
                            "trade_date": "2026-04-10",
                            "scope": "same_family_source_score_catalyst",
                            "next_high_return": 0.031,
                            "next_close_return": 0.018,
                            "t_plus_2_close_return": 0.011,
                        }
                    ],
                },
                {
                    "ticker": "300408",
                    "harvest_status": "closed_cycle_weak",
                    "latest_trade_date": "2026-04-10",
                    "latest_scope": "same_family_source",
                    "latest_score_target": 0.3088,
                    "closed_cycle_count": 1,
                    "next_day_available_count": 1,
                    "rows": [
                        {
                            "trade_date": "2026-04-10",
                            "scope": "same_family_source",
                            "next_high_return": 0.019,
                            "next_close_return": 0.006,
                            "t_plus_2_close_return": -0.012,
                        }
                    ],
                },
            ],
        },
    )
    _write_json(
        expansion_path,
        {
            "selected_ticker": "002001",
            "entries": [
                {
                    "ticker": "301396",
                    "harvest_status": "promotion_review_ready",
                    "expansion_status": "promotion_review_ready",
                    "latest_trade_date": "2026-04-10",
                    "latest_scope": "same_family_source_score_catalyst",
                    "latest_score_target": 0.4395,
                    "concern_tags": [],
                },
                {
                    "ticker": "688498",
                    "harvest_status": "promotion_review_ready",
                    "expansion_status": "promotion_review_ready",
                    "latest_trade_date": "2026-04-10",
                    "latest_scope": "same_family_source_score_catalyst",
                    "latest_score_target": 0.435,
                    "concern_tags": ["broad_family_only_history"],
                },
                {
                    "ticker": "300408",
                    "harvest_status": "closed_cycle_weak",
                    "expansion_status": "closed_cycle_reject",
                    "latest_trade_date": "2026-04-10",
                    "latest_scope": "same_family_source",
                    "latest_score_target": 0.3088,
                    "concern_tags": [],
                },
            ],
        },
    )
    _write_json(
        selected_refresh_path,
        {
            "trade_date": "2026-04-09",
            "entries": [
                {
                    "ticker": "002001",
                    "trade_date": "2026-04-09",
                    "current_cycle_status": "missing_next_day",
                    "overall_contract_verdict": "pending_next_day",
                }
            ],
        },
    )

    analysis = analyze_btst_carryover_aligned_peer_proof_board(harvest_path, expansion_path, selected_refresh_path)

    assert analysis["focus_ticker"] == "301396"
    assert analysis["focus_promotion_review_verdict"] == "ready_for_promotion_review"
    assert analysis["ready_for_promotion_review_tickers"] == ["301396"]
    assert analysis["risk_review_tickers"] == ["688498"]
    assert analysis["entries"][2]["ticker"] == "300408"
    assert analysis["entries"][2]["proof_verdict"] == "rejected_negative_t_plus_2"
