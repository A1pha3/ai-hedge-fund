from __future__ import annotations

from scripts._btst_p1_p2_next_actions import compute_priority_score


def test_compute_priority_score_structural_conflict_accumulates_all_relevant_boosts() -> None:
    row = {
        "score_target": 0.36,
        "short_trade_decision": "blocked",
        "false_negative_positive_close": True,
        "false_negative_recurring_pattern": True,
        "research_decision": "selected",
        "next_high_return": 0.08,
        "next_close_return": 0.03,
    }

    score = compute_priority_score(
        row,
        "structural_conflict_but_pattern_recurs",
        0.04,
    )

    assert score == 35 + 15 + 5 + 10 + 6 + 8 + 8 + 3 - 0


def test_compute_priority_score_watch_only_applies_gap_penalty_and_return_contributions() -> None:
    row = {
        "score_target": 0.22,
        "short_trade_decision": "near_miss",
        "false_negative_positive_close": False,
        "false_negative_recurring_pattern": False,
        "research_decision": "rejected",
        "next_high_return": 0.04,
        "next_close_return": -0.01,
    }

    score = compute_priority_score(
        row,
        "watch_only_but_tradable_intraday",
        0.15,
    )

    assert score == 25 + 4 - 1 - 3
