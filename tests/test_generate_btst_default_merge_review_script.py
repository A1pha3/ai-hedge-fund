from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_btst_default_merge_review import (
    generate_btst_default_merge_review,
    render_btst_default_merge_review_markdown,
)


def test_generate_btst_default_merge_review_marks_ready_focus(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    promotion_review_path = tmp_path / "promotion_review.json"
    governance_board_path = tmp_path / "governance_board.json"
    focus_dossier_path = tmp_path / "focus_dossier.json"

    manifest_path.write_text(
        json.dumps(
            {
                "continuation_promotion_ready_summary": {
                    "focus_ticker": "300720",
                    "promotion_path_status": "merge_review_ready",
                    "promotion_merge_review_verdict": "ready_for_default_btst_merge_review",
                    "qualifying_window_buckets": ["near_miss_entries", "selected_entries"],
                    "observed_independent_window_count": 2,
                    "weighted_observed_window_credit": 2.0,
                    "candidate_dossier_current_plan_visible_trade_dates": ["2026-03-31"],
                    "candidate_dossier_current_plan_visibility_gap_trade_dates": ["2026-03-23", "2026-03-27"],
                    "required_positive_rate_delta_vs_default_btst": 0.1,
                    "required_mean_return_delta_vs_default_btst": 0.02,
                    "focus_t_plus_2_positive_rate": 0.75,
                    "default_btst_t_plus_2_positive_rate": 0.3539,
                    "t_plus_2_positive_rate_delta_vs_default_btst": 0.3961,
                    "focus_t_plus_2_mean_return": 0.0912,
                    "default_btst_t_plus_2_mean_return": 0.0068,
                    "t_plus_2_mean_return_delta_vs_default_btst": 0.0844,
                    "edge_threshold_verdict": "edge_threshold_satisfied",
                    "persistence_verdict": "independent_window_requirement_satisfied",
                }
            }
        ),
        encoding="utf-8",
    )
    promotion_review_path.write_text(
        json.dumps({"focus_ticker": "300720", "promotion_review_verdict": "ready_for_default_btst_merge_review", "promotion_blockers": []}),
        encoding="utf-8",
    )
    governance_board_path.write_text(
        json.dumps({"focus_ticker": "300720", "governance_status": "ready_for_default_btst_merge_review", "promotion_blocker": "default_btst_merge_review_pending"}),
        encoding="utf-8",
    )
    focus_dossier_path.write_text(
        json.dumps({"latest_followup_decision": "selected", "downstream_followup_status": "continuation_only_confirm_then_review"}),
        encoding="utf-8",
    )

    analysis = generate_btst_default_merge_review(
        manifest_path=manifest_path,
        promotion_review_path=promotion_review_path,
        governance_board_path=governance_board_path,
        focus_dossier_path=focus_dossier_path,
    )

    assert analysis["focus_ticker"] == "300720"
    assert analysis["merge_review_verdict"] == "ready_for_default_btst_merge_review"
    assert analysis["operator_action"] == "review_default_btst_merge"
    assert analysis["blockers"] == []
    assert analysis["latest_followup_decision"] == "selected"
    assert analysis["counterfactual_validation"]["t_plus_2_positive_rate_delta_vs_default_btst"] == 0.3961
    assert analysis["counterfactual_validation"]["t_plus_2_mean_return_delta_vs_default_btst"] == 0.0844
    assert analysis["counterfactual_validation"]["counterfactual_verdict"] == "supports_default_btst_merge"
    assert analysis["counterfactual_validation"]["t_plus_2_positive_rate_margin_vs_threshold"] == 0.2961
    assert analysis["counterfactual_validation"]["t_plus_2_mean_return_margin_vs_threshold"] == 0.0644
    markdown = render_btst_default_merge_review_markdown(analysis)
    assert "# BTST Default Merge Review" in markdown
    assert "ready_for_default_btst_merge_review" in markdown
    assert "counterfactual_validation" in markdown


def test_generate_btst_default_merge_review_holds_when_not_ready(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    promotion_review_path = tmp_path / "promotion_review.json"
    governance_board_path = tmp_path / "governance_board.json"

    manifest_path.write_text(
        json.dumps(
            {
                "continuation_promotion_ready_summary": {
                    "focus_ticker": "300720",
                    "promotion_path_status": "one_qualifying_window_away",
                    "promotion_merge_review_verdict": "await_additional_independent_window_persistence",
                    "unresolved_requirements": ["new_independent_trade_date"],
                }
            }
        ),
        encoding="utf-8",
    )
    promotion_review_path.write_text(
        json.dumps({"focus_ticker": "300720", "promotion_review_verdict": "hold_validation_queue", "promotion_blockers": ["recent_tier_not_confirmed"]}),
        encoding="utf-8",
    )
    governance_board_path.write_text(
        json.dumps({"focus_ticker": "300720", "governance_status": "single_ticker_with_validation_watch", "promotion_blocker": "recent_validation_pending"}),
        encoding="utf-8",
    )

    analysis = generate_btst_default_merge_review(
        manifest_path=manifest_path,
        promotion_review_path=promotion_review_path,
        governance_board_path=governance_board_path,
    )

    assert analysis["merge_review_verdict"] == "hold_continuation_lane"
    assert "new_independent_trade_date" in analysis["blockers"]
    assert "recent_tier_not_confirmed" in analysis["blockers"]


def test_generate_btst_default_merge_review_threads_payload(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    promotion_review_path = tmp_path / "promotion_review.json"
    governance_board_path = tmp_path / "governance_board.json"
    focus_dossier_path = tmp_path / "focus_dossier.json"

    manifest_path.write_text(
        json.dumps(
            {
                "continuation_promotion_ready_summary": {
                    "focus_ticker": "300720",
                    "promotion_path_status": "merge_review_ready",
                    "promotion_merge_review_verdict": "ready_for_default_btst_merge_review",
                    "qualifying_window_buckets": ["near_miss_entries", "selected_entries"],
                    "observed_independent_window_count": 2,
                    "weighted_observed_window_credit": 2.0,
                    "required_positive_rate_delta_vs_default_btst": 0.1,
                    "required_mean_return_delta_vs_default_btst": 0.02,
                    "focus_t_plus_2_positive_rate": 0.75,
                    "default_btst_t_plus_2_positive_rate": 0.3539,
                    "t_plus_2_positive_rate_delta_vs_default_btst": 0.3961,
                    "focus_t_plus_2_mean_return": 0.0912,
                    "default_btst_t_plus_2_mean_return": 0.0068,
                    "t_plus_2_mean_return_delta_vs_default_btst": 0.0844,
                }
            }
        ),
        encoding="utf-8",
    )
    promotion_review_path.write_text(
        json.dumps({"focus_ticker": "300720", "promotion_review_verdict": "ready_for_default_btst_merge_review", "promotion_blockers": []}),
        encoding="utf-8",
    )
    governance_board_path.write_text(
        json.dumps({"focus_ticker": "300720", "governance_status": "ready_for_default_btst_merge_review", "promotion_blocker": "default_btst_merge_review_pending"}),
        encoding="utf-8",
    )
    focus_dossier_path.write_text(
        json.dumps(
            {
                "latest_followup_decision": "selected",
                "downstream_followup_status": "continuation_only_confirm_then_review",
                "governance_objective_support": {"closed_cycle_count": 2, "support_verdict": "supports_default_btst_merge"},
            }
        ),
        encoding="utf-8",
    )

    analysis = generate_btst_default_merge_review(
        manifest_path=manifest_path,
        promotion_review_path=promotion_review_path,
        governance_board_path=governance_board_path,
        focus_dossier_path=focus_dossier_path,
    )

    assert analysis["focus_ticker"] == "300720"
    assert analysis["merge_review_verdict"] == "ready_for_default_btst_merge_review"
    assert analysis["operator_action"] == "review_default_btst_merge"
    assert analysis["counterfactual_validation"]["counterfactual_verdict"] == "supports_default_btst_merge"
    assert analysis["focus_closed_cycle_count"] == 2
    assert analysis["focus_support_verdict"] == "supports_default_btst_merge"
    assert analysis["source_reports"] == {
        "manifest": str(manifest_path.expanduser().resolve()),
        "promotion_review": str(promotion_review_path.expanduser().resolve()),
        "governance_board": str(governance_board_path.expanduser().resolve()),
        "focus_dossier": str(focus_dossier_path.expanduser().resolve()),
    }
