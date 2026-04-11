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


def test_analyze_btst_carryover_aligned_peer_proof_board_threads_summary_payload(monkeypatch) -> None:
    monkeypatch.setattr("scripts.analyze_btst_carryover_aligned_peer_proof_board._load_json", lambda path: {"entries": []})
    monkeypatch.setattr(
        "scripts.analyze_btst_carryover_aligned_peer_proof_board._build_proof_entries",
        lambda harvest, peer_expansion: [
            {"ticker": "301396", "proof_verdict": "supportive_closed_cycle", "promotion_review_verdict": "ready_for_promotion_review"},
            {"ticker": "688498", "proof_verdict": "supportive_with_history_risk", "promotion_review_verdict": "requires_history_risk_review"},
        ],
    )

    analysis = analyze_btst_carryover_aligned_peer_proof_board("harvest.json", "expansion.json", "selected_refresh.json")

    assert analysis["peer_count"] == 2
    assert analysis["proof_verdict_counts"] == {"supportive_closed_cycle": 1, "supportive_with_history_risk": 1}
    assert analysis["promotion_review_verdict_counts"] == {"ready_for_promotion_review": 1, "requires_history_risk_review": 1}
    assert analysis["ready_for_promotion_review_tickers"] == ["301396"]
    assert analysis["risk_review_tickers"] == ["688498"]
    assert analysis["focus_ticker"] == "301396"


def test_analyze_btst_carryover_aligned_peer_proof_board_prefers_violated_selected_focus(tmp_path: Path) -> None:
    harvest_path = tmp_path / "harvest.json"
    expansion_path = tmp_path / "expansion.json"
    selected_refresh_path = tmp_path / "selected_refresh.json"

    _write_json(
        harvest_path,
        {
            "ticker": "002001",
            "harvest_entries": [
                {
                    "ticker": "300620",
                    "harvest_status": "promotion_review_ready",
                    "latest_trade_date": "2026-04-10",
                    "latest_scope": "same_family_source_score_catalyst",
                    "latest_score_target": 0.42,
                    "closed_cycle_count": 1,
                    "next_day_available_count": 1,
                    "rows": [
                        {
                            "trade_date": "2026-04-10",
                            "scope": "same_family_source_score_catalyst",
                            "next_high_return": 0.03,
                            "next_close_return": 0.015,
                        }
                    ],
                }
            ],
        },
    )
    _write_json(
        expansion_path,
        {
            "selected_ticker": "600111",
            "entries": [
                {
                    "ticker": "300620",
                    "harvest_status": "promotion_review_ready",
                    "expansion_status": "promotion_review_ready",
                    "latest_trade_date": "2026-04-10",
                    "latest_scope": "same_family_source_score_catalyst",
                    "latest_score_target": 0.42,
                    "concern_tags": [],
                }
            ],
        },
    )
    _write_json(
        selected_refresh_path,
        {
            "entries": [
                {
                    "ticker": "600111",
                    "trade_date": "2026-04-09",
                    "current_cycle_status": "t_plus_2_closed",
                    "overall_contract_verdict": "t_plus_2_confirmed",
                    "score_target": 0.51,
                },
                {
                    "ticker": "002001",
                    "trade_date": "2026-04-09",
                    "current_cycle_status": "t1_only",
                    "overall_contract_verdict": "next_close_violated",
                    "score_target": 0.4493,
                },
            ]
        },
    )

    analysis = analyze_btst_carryover_aligned_peer_proof_board(harvest_path, expansion_path, selected_refresh_path)

    assert analysis["selected_ticker"] == "002001"
    assert analysis["selected_contract_verdict"] == "next_close_violated"
    assert "应先收紧 carryover 主叙事" in analysis["recommendation"]
    assert "不再把它维持为 T+2 bias 锚点" in analysis["recommendation"]


def test_analyze_btst_carryover_aligned_peer_proof_board_keeps_intraday_only_selected_out_of_t2_bias_language(tmp_path: Path) -> None:
    harvest_path = tmp_path / "harvest.json"
    expansion_path = tmp_path / "expansion.json"
    selected_refresh_path = tmp_path / "selected_refresh.json"

    _write_json(
        harvest_path,
        {
            "ticker": "300720",
            "harvest_entries": [
                {
                    "ticker": "300620",
                    "harvest_status": "promotion_review_ready",
                    "latest_trade_date": "2026-04-10",
                    "latest_scope": "same_family_source_score_catalyst",
                    "latest_score_target": 0.42,
                    "closed_cycle_count": 1,
                    "next_day_available_count": 1,
                    "rows": [
                        {
                            "trade_date": "2026-04-10",
                            "scope": "same_family_source_score_catalyst",
                            "next_high_return": 0.03,
                            "next_close_return": 0.015,
                        }
                    ],
                }
            ],
        },
    )
    _write_json(
        expansion_path,
        {
            "selected_ticker": "300720",
            "entries": [
                {
                    "ticker": "300620",
                    "harvest_status": "promotion_review_ready",
                    "expansion_status": "promotion_review_ready",
                    "latest_trade_date": "2026-04-10",
                    "latest_scope": "same_family_source_score_catalyst",
                    "latest_score_target": 0.42,
                    "concern_tags": [],
                }
            ],
        },
    )
    _write_json(
        selected_refresh_path,
        {
            "entries": [
                {
                    "ticker": "300720",
                    "trade_date": "2026-04-06",
                    "current_cycle_status": "t_plus_4_closed",
                    "overall_contract_verdict": "t_plus_2_observed_without_positive_expectation",
                    "preferred_entry_mode": "intraday_confirmation_only",
                    "score_target": 0.452,
                }
            ]
        },
    )

    analysis = analyze_btst_carryover_aligned_peer_proof_board(harvest_path, expansion_path, selected_refresh_path)

    assert analysis["selected_ticker"] == "300720"
    assert "intraday confirmation-only / execution-quality" in analysis["recommendation"]
    assert "不要把它外推成 T+2 bias 锚点" in analysis["recommendation"]
