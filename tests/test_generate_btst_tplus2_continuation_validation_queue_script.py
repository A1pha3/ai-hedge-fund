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


def test_generate_btst_tplus2_continuation_validation_queue_includes_governance_focus_candidate(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()

    monkeypatch.setattr(
        validation_queue,
        "generate_btst_tplus2_continuation_expansion_board",
        lambda *_args, **_kwargs: {
            "focus_candidate": {"ticker": "300720"},
            "board_rows": [
                {"ticker": "300720", "tier": "governance_followup", "priority_rank": 1},
                {"ticker": "000792", "tier": "observation_candidate", "priority_rank": 2},
            ],
            "next_validation_candidates": [
                {"ticker": "000792", "tier": "observation_candidate", "priority_rank": 2},
            ],
        },
    )
    monkeypatch.setattr(
        validation_queue,
        "analyze_btst_tplus2_near_cluster_dossier",
        lambda *_args, **kwargs: {
            "candidate_ticker": kwargs["candidate_ticker"],
            "candidate_tier_focus": "governance_followup" if kwargs["candidate_ticker"] == "300720" else "observation_candidate",
            "recent_tier_verdict": "governance_followup_payoff_confirmed" if kwargs["candidate_ticker"] == "300720" else "recent_tier_confirmed",
            "recent_tier_window_count": 4 if kwargs["candidate_ticker"] == "300720" else 2,
            "recent_window_count": 4 if kwargs["candidate_ticker"] == "300720" else 2,
            "recent_tier_ratio": 1.0,
            "promotion_readiness_verdict": "watch_review_ready" if kwargs["candidate_ticker"] == "300720" else "validation_queue_ready",
            "tier_focus_surface_summary": {
                "next_close_positive_rate": 0.8 if kwargs["candidate_ticker"] == "300720" else 0.5,
                "t_plus_2_close_positive_rate": 1.0,
                "t_plus_2_close_return_distribution": {"mean": 0.02},
            },
        },
    )

    analysis = validation_queue.generate_btst_tplus2_continuation_validation_queue(reports_root)

    assert analysis["focus_ticker"] == "300720"
    assert analysis["focus_candidate"]["ticker"] == "300720"
    assert analysis["queue_rows"][0]["ticker"] == "300720"
    assert analysis["queue_rows"][0]["next_step"] == "Promote into near-cluster watch review under the governance-approved continuation lane."


def test_generate_btst_tplus2_continuation_validation_queue_escalates_merge_ready_focus(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()

    monkeypatch.setattr(
        validation_queue,
        "generate_btst_tplus2_continuation_expansion_board",
        lambda *_args, **_kwargs: {
            "focus_candidate": {"ticker": "300720"},
            "board_rows": [
                {"ticker": "300720", "tier": "governance_followup", "priority_rank": 1},
            ],
            "next_validation_candidates": [],
        },
    )
    monkeypatch.setattr(
        validation_queue,
        "analyze_btst_tplus2_near_cluster_dossier",
        lambda *_args, **kwargs: {
            "candidate_ticker": kwargs["candidate_ticker"],
            "candidate_tier_focus": "governance_followup",
            "recent_tier_verdict": "governance_followup_payoff_confirmed",
            "recent_tier_window_count": 4,
            "recent_window_count": 4,
            "recent_tier_ratio": 1.0,
            "promotion_readiness_verdict": "merge_review_ready",
            "tier_focus_surface_summary": {
                "next_close_positive_rate": 0.8,
                "t_plus_2_close_positive_rate": 1.0,
                "t_plus_2_close_return_distribution": {"mean": 0.02},
            },
        },
    )

    analysis = validation_queue.generate_btst_tplus2_continuation_validation_queue(reports_root)

    assert analysis["queue_rows"][0]["next_step"] == "Escalate into default BTST merge review under explicit governance approval."


def test_generate_btst_tplus2_continuation_validation_queue_keeps_seed_order_when_board_focus_is_non_governance(
    monkeypatch, tmp_path: Path
) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()

    monkeypatch.setattr(
        validation_queue,
        "generate_btst_tplus2_continuation_expansion_board",
        lambda *_args, **_kwargs: {
            "focus_candidate": {"ticker": "300408", "tier": "strict_peer"},
            "board_rows": [
                {"ticker": "300408", "tier": "strict_peer", "priority_rank": 1},
                {"ticker": "300720", "tier": "near_cluster_peer", "priority_rank": 2},
                {"ticker": "600989", "tier": "near_cluster_peer", "priority_rank": 3},
                {"ticker": "300683", "tier": "near_cluster_peer", "priority_rank": 8},
            ],
            "next_validation_candidates": [
                {"ticker": "300720", "tier": "near_cluster_peer", "priority_rank": 2},
                {"ticker": "600989", "tier": "near_cluster_peer", "priority_rank": 3},
                {"ticker": "300683", "tier": "near_cluster_peer", "priority_rank": 8},
            ],
        },
    )
    monkeypatch.setattr(
        validation_queue,
        "analyze_btst_tplus2_near_cluster_dossier",
        lambda *_args, **kwargs: {
            "candidate_ticker": kwargs["candidate_ticker"],
            "candidate_tier_focus": "near_cluster_peer",
            "recent_tier_verdict": "recent_tier_confirmed" if kwargs["candidate_ticker"] != "300683" else "recent_tier_thin",
            "recent_tier_window_count": 4 if kwargs["candidate_ticker"] != "300683" else 1,
            "recent_window_count": 5,
            "recent_tier_ratio": 0.8 if kwargs["candidate_ticker"] != "300683" else 0.2,
            "promotion_readiness_verdict": "watchlist_ready" if kwargs["candidate_ticker"] != "300683" else "low_priority",
            "tier_focus_surface_summary": {
                "next_close_positive_rate": 1.0,
                "t_plus_2_close_positive_rate": 1.0,
                "t_plus_2_close_return_distribution": {"mean": 0.05 if kwargs["candidate_ticker"] == "300683" else 0.02},
            },
        },
    )

    analysis = validation_queue.generate_btst_tplus2_continuation_validation_queue(reports_root)

    assert analysis["focus_ticker"] == "300720"
    assert [row["ticker"] for row in analysis["queue_rows"]] == ["300720", "600989", "300683"]


def test_generate_btst_tplus2_continuation_validation_queue_threads_payload(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()

    monkeypatch.setattr(
        validation_queue,
        "generate_btst_tplus2_continuation_expansion_board",
        lambda *_args, **_kwargs: {
            "focus_candidate": {"ticker": "300505"},
            "board_rows": [{"ticker": "300505", "tier": "observation_candidate", "priority_rank": 1}],
            "next_validation_candidates": [{"ticker": "300505", "tier": "observation_candidate", "priority_rank": 1}],
        },
    )
    monkeypatch.setattr(
        validation_queue,
        "_build_validation_queue_rows",
        lambda **kwargs: [{"ticker": "300505", "next_step": "keep validating"}],
    )
    monkeypatch.setattr(
        validation_queue,
        "_resolve_focus_candidate_review",
        lambda **kwargs: (
            {"ticker": "300505", "next_step": "keep validating"},
            {"promotion_review_verdict": "watch_review_ready"},
        ),
    )

    analysis = validation_queue.generate_btst_tplus2_continuation_validation_queue(reports_root, focus_ticker="300505")

    assert analysis["queue_row_count"] == 1
    assert analysis["focus_ticker"] == "300505"
    assert analysis["focus_candidate"] == {"ticker": "300505", "next_step": "keep validating"}
    assert analysis["promotion_review"] == {"promotion_review_verdict": "watch_review_ready"}
    assert "300505" in analysis["recommendation"]
