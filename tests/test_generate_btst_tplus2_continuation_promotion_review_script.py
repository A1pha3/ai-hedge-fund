from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_btst_tplus2_continuation_promotion_review import (
    generate_btst_tplus2_continuation_promotion_review,
    render_btst_tplus2_continuation_promotion_review_markdown,
)


def test_generate_btst_tplus2_continuation_promotion_review_marks_watch_review_ready(tmp_path: Path) -> None:
    queue_path = tmp_path / "queue.json"
    focus_dossier_path = tmp_path / "focus.json"
    watch_dossier_path = tmp_path / "watch.json"

    queue_path.write_text(json.dumps({"focus_candidate": {"ticker": "300505"}}), encoding="utf-8")
    focus_dossier_path.write_text(
        json.dumps(
            {
                "candidate_ticker": "300505",
                "candidate_tier_focus": "observation_candidate",
                "recent_tier_verdict": "recent_tier_confirmed",
                "recent_tier_window_count": 4,
                "recent_window_count": 4,
                "tier_focus_surface_summary": {
                    "next_close_positive_rate": 1.0,
                    "t_plus_2_close_positive_rate": 1.0,
                    "t_plus_2_close_return_distribution": {"mean": 0.0361},
                },
            }
        ),
        encoding="utf-8",
    )
    watch_dossier_path.write_text(
        json.dumps(
            {
                "candidate_ticker": "600989",
                "recent_support_ratio": 0.8,
                "recent_supporting_surface_summary": {
                    "t_plus_2_close_return_distribution": {"mean": 0.0117},
                },
            }
        ),
        encoding="utf-8",
    )

    analysis = generate_btst_tplus2_continuation_promotion_review(
        queue_path=queue_path,
        focus_dossier_path=focus_dossier_path,
        watch_dossier_path=watch_dossier_path,
    )

    assert analysis["focus_ticker"] == "300505"
    assert analysis["benchmark_watch_ticker"] == "600989"
    assert analysis["promotion_review_verdict"] == "watch_review_ready"
    assert analysis["promotion_blockers"] == []

    markdown = render_btst_tplus2_continuation_promotion_review_markdown(analysis)
    assert "# BTST T+2 Continuation Promotion Review" in markdown
    assert "300505" in markdown


def test_generate_btst_tplus2_continuation_promotion_review_surfaces_governance_evidence_gap(tmp_path: Path) -> None:
    queue_path = tmp_path / "queue.json"
    focus_dossier_path = tmp_path / "focus.json"
    watch_dossier_path = tmp_path / "watch.json"

    queue_path.write_text(json.dumps({"focus_candidate": {"ticker": "300720"}}), encoding="utf-8")
    focus_dossier_path.write_text(
        json.dumps(
            {
                "candidate_ticker": "300720",
                "candidate_tier_focus": "governance_followup",
                "governance_objective_support": {
                    "support_verdict": "candidate_pool_false_negative_outperforms_tradeable_surface",
                    "closed_cycle_count": 15,
                },
                "recent_tier_verdict": "governance_followup_pending_evidence",
                "recent_tier_window_count": 0,
                "recent_window_count": 0,
                "tier_focus_surface_summary": {
                    "next_close_positive_rate": 0.8,
                    "t_plus_2_close_positive_rate": 0.8667,
                    "t_plus_2_close_return_distribution": {"mean": 0.0787},
                },
            }
        ),
        encoding="utf-8",
    )
    watch_dossier_path.write_text(
        json.dumps(
            {
                "candidate_ticker": "600989",
                "recent_support_ratio": 0.8,
                "recent_supporting_surface_summary": {
                    "t_plus_2_close_return_distribution": {"mean": 0.0117},
                },
            }
        ),
        encoding="utf-8",
    )

    analysis = generate_btst_tplus2_continuation_promotion_review(
        queue_path=queue_path,
        focus_dossier_path=focus_dossier_path,
        watch_dossier_path=watch_dossier_path,
    )

    assert analysis["promotion_review_verdict"] == "hold_validation_queue"
    assert "governance_followup_needs_multiwindow_payoff" in analysis["promotion_blockers"]
    assert "recent_payoff_windows_missing" in analysis["promotion_blockers"]
    assert "weak_next_close_follow_through" not in analysis["promotion_blockers"]
    assert "weak_t_plus_2_follow_through" not in analysis["promotion_blockers"]
