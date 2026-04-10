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
