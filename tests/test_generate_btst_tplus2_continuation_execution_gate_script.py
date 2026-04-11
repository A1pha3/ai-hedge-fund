from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_btst_tplus2_continuation_execution_gate import (
    generate_btst_tplus2_continuation_execution_gate,
    render_btst_tplus2_continuation_execution_gate_markdown,
)


def test_generate_btst_tplus2_continuation_execution_gate_approves_candidate(tmp_path: Path) -> None:
    lane_rulepack_path = tmp_path / "lane_rulepack.json"
    lane_validation_path = tmp_path / "lane_validation.json"
    eligible_execution_path = tmp_path / "eligible_execution.json"
    promotion_review_path = tmp_path / "promotion_review.json"

    lane_rulepack_path.write_text(json.dumps({"lane_rules": {"capital_mode": "paper_only"}}), encoding="utf-8")
    lane_validation_path.write_text(
        json.dumps(
            {
                "aggregate_surface_summary": {"t_plus_2_close_return_distribution": {"mean": 0.0313}},
                "per_window_summaries": [{"window_verdict": "supports_tplus2_lane"}] * 7 + [{"window_verdict": "mixed_or_weak"}],
            }
        ),
        encoding="utf-8",
    )
    eligible_execution_path.write_text(
        json.dumps(
            {
                "focus_ticker": "300505",
                "execution_verdict": "eligible_extension_applied",
                "adopted_eligible_row": {
                    "recent_support_ratio": 1.0,
                    "recent_supporting_window_count": 4,
                    "next_close_positive_rate": 1.0,
                    "t_plus_2_close_positive_rate": 1.0,
                    "t_plus_2_close_return_mean": 0.0361,
                },
            }
        ),
        encoding="utf-8",
    )
    promotion_review_path.write_text(
        json.dumps({"focus_ticker": "300505", "comparison_summary": {"t_plus_2_mean_gap_vs_watch": 0.0244, "governance_payoff_ready": True}}),
        encoding="utf-8",
    )

    analysis = generate_btst_tplus2_continuation_execution_gate(
        lane_rulepack_path=lane_rulepack_path,
        lane_validation_path=lane_validation_path,
        eligible_execution_path=eligible_execution_path,
        promotion_review_path=promotion_review_path,
    )

    assert analysis["gate_verdict"] == "approve_execution_candidate"
    assert analysis["gate_blockers"] == []
    markdown = render_btst_tplus2_continuation_execution_gate_markdown(analysis)
    assert "approve_execution_candidate" in markdown


def test_generate_btst_tplus2_continuation_execution_gate_holds_on_imperfect_focus(tmp_path: Path) -> None:
    lane_rulepack_path = tmp_path / "lane_rulepack.json"
    lane_validation_path = tmp_path / "lane_validation.json"
    eligible_execution_path = tmp_path / "eligible_execution.json"
    promotion_review_path = tmp_path / "promotion_review.json"

    lane_rulepack_path.write_text(json.dumps({"lane_rules": {"capital_mode": "paper_only"}}), encoding="utf-8")
    lane_validation_path.write_text(
        json.dumps(
            {
                "aggregate_surface_summary": {"t_plus_2_close_return_distribution": {"mean": 0.0313}},
                "per_window_summaries": [{"window_verdict": "supports_tplus2_lane"}] * 6 + [{"window_verdict": "mixed_or_weak"}] * 2,
            }
        ),
        encoding="utf-8",
    )
    eligible_execution_path.write_text(
        json.dumps(
            {
                "focus_ticker": "300505",
                "execution_verdict": "eligible_extension_applied",
                "adopted_eligible_row": {
                    "recent_support_ratio": 0.75,
                    "recent_supporting_window_count": 4,
                    "next_close_positive_rate": 1.0,
                    "t_plus_2_close_positive_rate": 1.0,
                    "t_plus_2_close_return_mean": 0.0361,
                },
            }
        ),
        encoding="utf-8",
    )
    promotion_review_path.write_text(
        json.dumps({"focus_ticker": "300505", "comparison_summary": {"t_plus_2_mean_gap_vs_watch": 0.0244, "governance_payoff_ready": True}}),
        encoding="utf-8",
    )

    analysis = generate_btst_tplus2_continuation_execution_gate(
        lane_rulepack_path=lane_rulepack_path,
        lane_validation_path=lane_validation_path,
        eligible_execution_path=eligible_execution_path,
        promotion_review_path=promotion_review_path,
    )

    assert analysis["gate_verdict"] == "hold_execution_candidate"
    assert "focus_recent_support_not_perfect" in analysis["gate_blockers"]


def test_generate_btst_tplus2_continuation_execution_gate_approves_quant_confirmed_focus_without_perfect_rates(tmp_path: Path) -> None:
    lane_rulepack_path = tmp_path / "lane_rulepack.json"
    lane_validation_path = tmp_path / "lane_validation.json"
    eligible_execution_path = tmp_path / "eligible_execution.json"
    promotion_review_path = tmp_path / "promotion_review.json"

    lane_rulepack_path.write_text(json.dumps({"lane_rules": {"capital_mode": "paper_only"}}), encoding="utf-8")
    lane_validation_path.write_text(
        json.dumps(
            {
                "aggregate_surface_summary": {"t_plus_2_close_return_distribution": {"mean": 0.0313}},
                "per_window_summaries": [{"window_verdict": "supports_tplus2_lane"}] * 7 + [{"window_verdict": "mixed_or_weak"}],
            }
        ),
        encoding="utf-8",
    )
    eligible_execution_path.write_text(
        json.dumps(
            {
                "focus_ticker": "300720",
                "execution_verdict": "eligible_extension_applied",
                "adopted_eligible_row": {
                    "recent_support_ratio": 1.0,
                    "recent_supporting_window_count": 4,
                    "next_close_positive_rate": 0.8,
                    "t_plus_2_close_positive_rate": 0.8667,
                    "t_plus_2_close_return_mean": 0.0787,
                },
            }
        ),
        encoding="utf-8",
    )
    promotion_review_path.write_text(
        json.dumps({"focus_ticker": "300720", "comparison_summary": {"t_plus_2_mean_gap_vs_watch": 0.067, "governance_payoff_ready": True}}),
        encoding="utf-8",
    )

    analysis = generate_btst_tplus2_continuation_execution_gate(
        lane_rulepack_path=lane_rulepack_path,
        lane_validation_path=lane_validation_path,
        eligible_execution_path=eligible_execution_path,
        promotion_review_path=promotion_review_path,
    )

    assert analysis["gate_verdict"] == "approve_execution_candidate"
    assert analysis["gate_blockers"] == []
    assert analysis["governance_payoff_ready"] is True


def test_generate_btst_tplus2_continuation_execution_gate_threads_payload(tmp_path: Path) -> None:
    lane_rulepack_path = tmp_path / "lane_rulepack.json"
    lane_validation_path = tmp_path / "lane_validation.json"
    eligible_execution_path = tmp_path / "eligible_execution.json"
    promotion_review_path = tmp_path / "promotion_review.json"

    lane_rulepack_path.write_text(json.dumps({"lane_rules": {"capital_mode": "paper_only"}}), encoding="utf-8")
    lane_validation_path.write_text(
        json.dumps(
            {
                "aggregate_surface_summary": {"t_plus_2_close_return_distribution": {"mean": 0.0313}},
                "per_window_summaries": [{"window_verdict": "supports_tplus2_lane"}] * 7 + [{"window_verdict": "mixed_or_weak"}],
            }
        ),
        encoding="utf-8",
    )
    eligible_execution_path.write_text(
        json.dumps(
            {
                "focus_ticker": "300505",
                "execution_verdict": "eligible_extension_applied",
                "adopted_eligible_row": {
                    "recent_support_ratio": 1.0,
                    "recent_supporting_window_count": 4,
                    "next_close_positive_rate": 1.0,
                    "t_plus_2_close_positive_rate": 1.0,
                    "t_plus_2_close_return_mean": 0.0361,
                },
            }
        ),
        encoding="utf-8",
    )
    promotion_review_path.write_text(
        json.dumps({"focus_ticker": "300505", "comparison_summary": {"t_plus_2_mean_gap_vs_watch": 0.0244, "governance_payoff_ready": True}}),
        encoding="utf-8",
    )

    analysis = generate_btst_tplus2_continuation_execution_gate(
        lane_rulepack_path=lane_rulepack_path,
        lane_validation_path=lane_validation_path,
        eligible_execution_path=eligible_execution_path,
        promotion_review_path=promotion_review_path,
    )

    assert analysis["focus_ticker"] == "300505"
    assert analysis["gate_verdict"] == "approve_execution_candidate"
    assert analysis["gate_blockers"] == []
    assert analysis["lane_support_window_count"] == 7
    assert analysis["lane_window_count"] == 8
    assert analysis["lane_support_ratio"] == 0.875
    assert analysis["operator_action"] == "append_focus_to_execution_overlay"
    assert analysis["recommendation"] == "Approve 300505 as an effective paper execution candidate for the isolated continuation lane."
    assert analysis["source_reports"] == {
        "lane_rulepack": str(lane_rulepack_path.expanduser().resolve()),
        "lane_validation": str(lane_validation_path.expanduser().resolve()),
        "eligible_execution": str(eligible_execution_path.expanduser().resolve()),
        "promotion_review": str(promotion_review_path.expanduser().resolve()),
    }
