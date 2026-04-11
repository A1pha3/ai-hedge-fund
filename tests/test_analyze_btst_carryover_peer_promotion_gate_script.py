from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_btst_carryover_peer_promotion_gate import analyze_btst_carryover_peer_promotion_gate


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_analyze_btst_carryover_peer_promotion_gate_blocks_until_selected_contract_confirms(tmp_path: Path) -> None:
    proof_board_path = tmp_path / "proof_board.json"
    selected_refresh_path = tmp_path / "selected_refresh.json"

    _write_json(
        proof_board_path,
        {
            "selected_ticker": "002001",
            "selected_trade_date": "2026-04-09",
            "selected_contract_verdict": "pending_next_day",
            "entries": [
                {
                    "ticker": "301396",
                    "proof_verdict": "supportive_closed_cycle",
                    "promotion_review_verdict": "ready_for_promotion_review",
                    "latest_trade_date": "2026-04-10",
                    "concern_tags": [],
                    "blockers": [],
                },
                {
                    "ticker": "300408",
                    "proof_verdict": "pending_t_plus_2_close",
                    "promotion_review_verdict": "await_t_plus_2_close",
                    "latest_trade_date": "2026-04-10",
                    "concern_tags": [],
                    "blockers": ["await_t_plus_2_bar"],
                },
            ],
        },
    )
    _write_json(
        selected_refresh_path,
        {
            "entries": [
                {
                    "ticker": "002001",
                    "trade_date": "2026-04-09",
                    "overall_contract_verdict": "pending_next_day",
                }
            ]
        },
    )

    analysis = analyze_btst_carryover_peer_promotion_gate(proof_board_path, selected_refresh_path)

    assert analysis["focus_ticker"] == "301396"
    assert analysis["focus_gate_verdict"] == "blocked_selected_contract_open"
    assert analysis["blocked_open_tickers"] == ["301396"]
    assert analysis["pending_t_plus_2_tickers"] == ["300408"]


def test_analyze_btst_carryover_peer_promotion_gate_threads_summary_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.analyze_btst_carryover_peer_promotion_gate._load_json",
        lambda path: {"entries": []} if "selected" not in str(path) else {"entries": [{"ticker": "002001", "trade_date": "2026-04-09", "overall_contract_verdict": "pending_next_day"}]},
    )
    monkeypatch.setattr(
        "scripts.analyze_btst_carryover_peer_promotion_gate._build_gate_entries",
        lambda proof_board, selected_contract_verdict: [
            {"ticker": "301396", "gate_verdict": "blocked_selected_contract_open"},
            {"ticker": "688498", "gate_verdict": "requires_history_risk_review"},
        ],
    )

    analysis = analyze_btst_carryover_peer_promotion_gate("proof_board.json", "selected_refresh.json")

    assert analysis["selected_ticker"] == "002001"
    assert analysis["selected_contract_verdict"] == "pending_next_day"
    assert analysis["gate_verdict_counts"] == {"blocked_selected_contract_open": 1, "requires_history_risk_review": 1}
    assert analysis["blocked_open_tickers"] == ["301396"]
    assert analysis["risk_review_tickers"] == ["688498"]
    assert analysis["focus_ticker"] == "301396"


def test_analyze_btst_carryover_peer_promotion_gate_prefers_violated_selected_focus(tmp_path: Path) -> None:
    proof_board_path = tmp_path / "proof_board.json"
    selected_refresh_path = tmp_path / "selected_refresh.json"

    _write_json(
        proof_board_path,
        {
            "selected_ticker": "600111",
            "selected_trade_date": "2026-04-09",
            "selected_contract_verdict": "t_plus_2_confirmed",
            "entries": [
                {
                    "ticker": "301396",
                    "proof_verdict": "supportive_closed_cycle",
                    "promotion_review_verdict": "ready_for_promotion_review",
                    "latest_trade_date": "2026-04-10",
                    "concern_tags": [],
                    "blockers": [],
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
                    "overall_contract_verdict": "t_plus_2_confirmed",
                    "current_cycle_status": "t_plus_2_closed",
                },
                {
                    "ticker": "002001",
                    "trade_date": "2026-04-09",
                    "overall_contract_verdict": "next_close_violated",
                    "current_cycle_status": "t1_only",
                },
            ]
        },
    )

    analysis = analyze_btst_carryover_peer_promotion_gate(proof_board_path, selected_refresh_path)

    assert analysis["selected_ticker"] == "002001"
    assert analysis["selected_contract_verdict"] == "next_close_violated"
    assert analysis["focus_gate_verdict"] == "blocked_selected_contract_violated"


def test_analyze_btst_carryover_peer_promotion_gate_aligns_focus_with_pending_proof_under_violation(tmp_path: Path) -> None:
    proof_board_path = tmp_path / "proof_board.json"
    selected_refresh_path = tmp_path / "selected_refresh.json"

    _write_json(
        proof_board_path,
        {
            "selected_ticker": "002001",
            "selected_trade_date": "2026-04-09",
            "selected_contract_verdict": "next_close_violated",
            "focus_ticker": "300620",
            "entries": [
                {
                    "ticker": "688498",
                    "proof_verdict": "pending_t_plus_2_close",
                    "promotion_review_verdict": "await_t_plus_2_close",
                    "latest_trade_date": "2026-04-10",
                    "concern_tags": [],
                    "blockers": ["await_t_plus_2_bar"],
                },
                {
                    "ticker": "300620",
                    "proof_verdict": "pending_t_plus_2_close",
                    "promotion_review_verdict": "await_t_plus_2_close",
                    "latest_trade_date": "2026-04-10",
                    "concern_tags": [],
                    "blockers": ["await_t_plus_2_bar"],
                },
            ],
        },
    )
    _write_json(
        selected_refresh_path,
        {
            "entries": [
                {
                    "ticker": "002001",
                    "trade_date": "2026-04-09",
                    "overall_contract_verdict": "next_close_violated",
                    "current_cycle_status": "t1_only",
                }
            ]
        },
    )

    analysis = analyze_btst_carryover_peer_promotion_gate(proof_board_path, selected_refresh_path)

    assert analysis["focus_ticker"] == "300620"
    assert analysis["focus_gate_verdict"] == "blocked_selected_contract_violated"


def test_analyze_btst_carryover_peer_promotion_gate_aligns_focus_with_pending_proof_without_violation(tmp_path: Path) -> None:
    proof_board_path = tmp_path / "proof_board.json"
    selected_refresh_path = tmp_path / "selected_refresh.json"

    _write_json(
        proof_board_path,
        {
            "selected_ticker": "300720",
            "selected_trade_date": "2026-04-06",
            "selected_contract_verdict": "t_plus_2_observed_without_positive_expectation",
            "focus_ticker": "300620",
            "entries": [
                {
                    "ticker": "688498",
                    "proof_verdict": "pending_t_plus_2_close",
                    "promotion_review_verdict": "await_t_plus_2_close",
                    "latest_trade_date": "2026-04-10",
                    "concern_tags": [],
                    "blockers": ["await_t_plus_2_bar"],
                },
                {
                    "ticker": "300620",
                    "proof_verdict": "pending_t_plus_2_close",
                    "promotion_review_verdict": "await_t_plus_2_close",
                    "latest_trade_date": "2026-04-10",
                    "concern_tags": [],
                    "blockers": ["await_t_plus_2_bar"],
                },
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
                    "overall_contract_verdict": "t_plus_2_observed_without_positive_expectation",
                    "current_cycle_status": "t_plus_4_closed",
                }
            ]
        },
    )

    analysis = analyze_btst_carryover_peer_promotion_gate(proof_board_path, selected_refresh_path)

    assert analysis["focus_ticker"] == "300620"
    assert analysis["focus_gate_verdict"] == "await_peer_t_plus_2_close"
    assert analysis["pending_t_plus_2_tickers"][:2] == ["300620", "688498"]
