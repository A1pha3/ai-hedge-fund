from __future__ import annotations

import scripts.analyze_btst_selected_outcome_proof as proof_module
from scripts.analyze_btst_selected_outcome_proof import (
    _build_recommendation,
    _resolve_selected_entry,
    _summarize_evidence_rows,
    analyze_btst_selected_outcome_proof,
)


def test_resolve_selected_entry_accepts_legacy_target_context_selected() -> None:
    ticker, short_trade = _resolve_selected_entry(
        {
            "target_context": [
                {
                    "ticker": "688313",
                    "short_trade": {"decision": "selected"},
                    "replay_context": {
                        "historical_prior": {
                            "evaluable_count": 3,
                            "next_close_positive_rate": 0.46,
                        }
                    },
                }
            ]
        },
        ticker="688313",
    )

    assert ticker == "688313"
    assert short_trade["decision"] == "selected"
    assert short_trade["explainability_payload"]["historical_prior"]["next_close_positive_rate"] == 0.46


def test_summarize_evidence_rows_builds_confirm_then_hold_recommendation() -> None:
    summary = _summarize_evidence_rows(
        [
            {
                "next_high_return": 0.041,
                "next_close_return": 0.026,
                "next_open_to_close_return": 0.012,
                "t_plus_2_close_return": 0.018,
                "t_plus_3_close_return": 0.011,
                "t_plus_4_close_return": 0.006,
            },
            {
                "next_high_return": 0.033,
                "next_close_return": 0.017,
                "next_open_to_close_return": 0.008,
                "t_plus_2_close_return": 0.014,
                "t_plus_3_close_return": -0.003,
                "t_plus_4_close_return": 0.004,
            },
        ],
        next_high_hit_threshold=0.02,
    )

    recommendation = _build_recommendation(summary)

    assert summary["evidence_case_count"] == 2
    assert summary["next_close_positive_rate"] == 1.0
    assert summary["t_plus_2_close_positive_rate"] == 1.0
    assert summary["t_plus_3_close_positive_rate"] == 0.5
    assert recommendation == "当前 selected 路径已有足够的 historical_prior follow-through 支持，可继续保留 confirm_then_hold 语义。"


def test_analyze_btst_selected_outcome_proof_summarizes_legacy_selected_history(monkeypatch) -> None:
    monkeypatch.setattr(
        proof_module,
        "_extract_holding_outcome",
        lambda ticker, trade_date, price_cache: {
            "data_status": "ok",
            "cycle_status": "t_plus_3_closed",
            "next_trade_date": "2026-04-22",
            "next_high_return": 0.041,
            "next_close_return": 0.026,
            "next_open_to_close_return": 0.012,
            "t_plus_2_close_return": 0.018,
            "t_plus_3_close_return": 0.011,
            "t_plus_4_close_return": 0.006,
        },
    )

    analysis = analyze_btst_selected_outcome_proof(
        {
            "trade_date": "2026-04-21",
            "target_context": [
                {
                    "ticker": "688313",
                    "short_trade": {
                        "decision": "selected",
                        "candidate_source": "legacy_selected",
                        "preferred_entry_mode": "confirm_then_hold",
                        "score_target": 0.34,
                        "effective_select_threshold": 0.35,
                        "selected_score_tolerance": 0.02,
                    },
                    "replay_context": {
                        "historical_prior": {
                            "next_high_hit_threshold": 0.02,
                            "recent_examples": [
                                {"trade_date": "2026-04-18", "ticker": "688313", "candidate_source": "legacy_selected"},
                                {"trade_date": "2026-04-18", "ticker": "688313", "candidate_source": "legacy_selected"},
                            ],
                        }
                    },
                }
            ],
        },
        ticker="688313",
    )

    assert analysis["ticker"] == "688313"
    assert analysis["current_contract_status"] == "formal_selected"
    assert analysis["is_formal_selected"] is True
    assert analysis["raw_recent_example_count"] == 2
    assert analysis["deduplicated_recent_example_count"] == 1
    assert analysis["selected_within_tolerance"] is True
    assert analysis["summary"]["evidence_case_count"] == 1
    assert analysis["summary"]["next_close_positive_rate"] == 1.0
    assert analysis["summary"]["t_plus_2_close_positive_rate"] == 1.0
    assert analysis["recommendation"] == "当前 selected 路径已有足够的 historical_prior follow-through 支持，可继续保留 confirm_then_hold 语义。"
