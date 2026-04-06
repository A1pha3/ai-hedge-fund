from __future__ import annotations

from pathlib import Path

import scripts.generate_btst_tplus2_continuation_validation_queue as validation_queue


def test_generate_btst_tplus2_continuation_validation_queue_builds_focus_candidate(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()

    monkeypatch.setattr(
        validation_queue,
        "generate_btst_tplus2_continuation_expansion_board",
        lambda *_args, **_kwargs: {
            "next_validation_candidates": [
                {"ticker": "300505", "tier": "observation_candidate", "priority_rank": 2},
                {"ticker": "000792", "tier": "observation_candidate", "priority_rank": 3},
            ]
        },
    )
    monkeypatch.setattr(
        validation_queue,
        "analyze_btst_tplus2_near_cluster_dossier",
        lambda *_args, **kwargs: {
            "candidate_ticker": kwargs["candidate_ticker"],
            "candidate_tier_focus": "observation_candidate",
            "recent_tier_verdict": "recent_tier_confirmed",
            "recent_tier_window_count": 4,
            "recent_window_count": 4,
            "recent_tier_ratio": 1.0,
            "promotion_readiness_verdict": "validation_queue_ready",
            "tier_focus_surface_summary": {
                "next_close_positive_rate": 1.0,
                "t_plus_2_close_positive_rate": 1.0,
                "t_plus_2_close_return_distribution": {"mean": 0.02},
            },
        },
    )

    analysis = validation_queue.generate_btst_tplus2_continuation_validation_queue(
        reports_root,
        focus_ticker="300505",
    )

    assert analysis["queue_row_count"] == 2
    assert analysis["focus_ticker"] == "300505"
    assert analysis["focus_candidate"]["ticker"] == "300505"
    assert analysis["promotion_review"]["promotion_review_verdict"] == "watch_review_ready"

    markdown = validation_queue.render_btst_tplus2_continuation_validation_queue_markdown(analysis)
    assert "# BTST T+2 Continuation Validation Queue" in markdown
    assert "300505" in markdown
