from __future__ import annotations

from pathlib import Path

import scripts.generate_btst_tplus2_continuation_expansion_board as expansion_board


def test_generate_btst_tplus2_continuation_expansion_board_ranks_near_cluster_first(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()

    monkeypatch.setattr(
        expansion_board,
        "analyze_btst_tplus2_continuation_peer_scan",
        lambda *_args, **_kwargs: {
            "peer_count": 0,
            "near_cluster_count": 1,
            "observation_candidate_count": 1,
            "peer_summaries": [],
            "near_peer_summaries": [
                {
                    "ticker": "600989",
                    "distinct_report_count": 7,
                    "observation_count": 7,
                    "mean_similarity_score": 1.6517,
                    "recent_window_count": 5,
                    "recent_tier_window_count": 4,
                    "recent_tier_ratio": 0.8,
                    "recent_tier_verdict": "recent_tier_confirmed",
                    "surface_summary": {
                        "next_close_positive_rate": 1.0,
                        "t_plus_2_close_positive_rate": 1.0,
                        "t_plus_2_close_return_distribution": {"mean": 0.0117},
                    },
                }
            ],
            "observation_candidate_summaries": [
                {
                    "ticker": "002001",
                    "distinct_report_count": 2,
                    "observation_count": 2,
                    "mean_similarity_score": 2.301,
                    "recent_window_count": 5,
                    "recent_tier_window_count": 3,
                    "recent_tier_ratio": 0.6,
                    "recent_tier_verdict": "recent_tier_mixed",
                    "surface_summary": {
                        "next_close_positive_rate": 0.5,
                        "t_plus_2_close_positive_rate": 0.5,
                        "t_plus_2_close_return_distribution": {"mean": 0.01},
                    },
                },
                {
                    "ticker": "300502",
                    "distinct_report_count": 4,
                    "observation_count": 4,
                    "mean_similarity_score": 2.0,
                    "recent_window_count": 4,
                    "recent_tier_window_count": 4,
                    "recent_tier_ratio": 1.0,
                    "recent_tier_verdict": "recent_tier_confirmed",
                    "surface_summary": {
                        "next_close_positive_rate": 0.0,
                        "t_plus_2_close_positive_rate": 1.0,
                        "t_plus_2_close_return_distribution": {"mean": 0.003},
                    },
                },
            ],
        },
    )

    analysis = expansion_board.generate_btst_tplus2_continuation_expansion_board(
        reports_root,
        upstream_handoff_board_path=tmp_path / "missing_upstream_handoff_board.json",
    )

    assert analysis["near_cluster_count"] == 1
    assert analysis["observation_candidate_count"] == 1
    assert analysis["board_rows"][0]["ticker"] == "600989"
    assert analysis["board_rows"][0]["tier"] == "near_cluster_peer"
    assert analysis["board_rows"][1]["ticker"] == "300502"
    assert analysis["next_validation_candidates"][0]["ticker"] == "002001"
    assert all(item["ticker"] != "300502" for item in analysis["next_validation_candidates"])
    assert analysis["recommendation"].startswith("Current top continuation expansion candidate is 600989")

    markdown = expansion_board.render_btst_tplus2_continuation_expansion_board_markdown(analysis)
    assert "# BTST T+2 Continuation Expansion Board" in markdown
    assert "600989" in markdown
    assert "Next Validation Candidates" in markdown


def test_generate_btst_tplus2_continuation_expansion_board_prioritizes_governance_followup(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()
    upstream_handoff_board_path = tmp_path / "btst_candidate_pool_upstream_handoff_board_latest.json"
    upstream_handoff_board_path.write_text(
        """
        {
          "board_rows": [
            {
              "ticker": "300720",
              "downstream_followup_lane": "t_plus_2_continuation_review",
              "downstream_followup_status": "continuation_confirm_then_review",
              "downstream_followup_blocker": "no_selected_persistence_or_independent_edge",
              "board_rank": 2
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        expansion_board,
        "analyze_btst_tplus2_continuation_peer_scan",
        lambda *_args, **_kwargs: {
            "peer_count": 0,
            "near_cluster_count": 1,
            "observation_candidate_count": 0,
            "peer_summaries": [],
            "near_peer_summaries": [
                {
                    "ticker": "600989",
                    "distinct_report_count": 7,
                    "observation_count": 7,
                    "mean_similarity_score": 1.6517,
                    "recent_window_count": 5,
                    "recent_tier_window_count": 4,
                    "recent_tier_ratio": 0.8,
                    "recent_tier_verdict": "recent_tier_confirmed",
                    "surface_summary": {
                        "next_close_positive_rate": 1.0,
                        "t_plus_2_close_positive_rate": 1.0,
                        "t_plus_2_close_return_distribution": {"mean": 0.0117},
                    },
                }
            ],
            "observation_candidate_summaries": [],
        },
    )

    analysis = expansion_board.generate_btst_tplus2_continuation_expansion_board(
        reports_root,
        upstream_handoff_board_path=upstream_handoff_board_path,
    )

    assert analysis["governance_followup_count"] == 1
    assert analysis["focus_candidate"]["ticker"] == "300720"
    assert analysis["board_rows"][0]["ticker"] == "300720"
    assert analysis["board_rows"][0]["tier"] == "governance_followup"
    assert analysis["next_validation_candidates"][0]["ticker"] == "600989"


def test_generate_btst_tplus2_continuation_expansion_board_reserves_slot_for_strong_thin_near_cluster_candidate(
    monkeypatch, tmp_path: Path
) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()

    monkeypatch.setattr(
        expansion_board,
        "analyze_btst_tplus2_continuation_peer_scan",
        lambda *_args, **_kwargs: {
            "peer_count": 1,
            "near_cluster_count": 4,
            "observation_candidate_count": 0,
            "peer_summaries": [
                {
                    "ticker": "300408",
                    "distinct_report_count": 4,
                    "observation_count": 4,
                    "mean_similarity_score": 1.1,
                    "recent_window_count": 5,
                    "recent_tier_window_count": 4,
                    "recent_tier_ratio": 0.8,
                    "recent_tier_verdict": "recent_tier_confirmed",
                    "surface_summary": {
                        "next_close_positive_rate": 1.0,
                        "t_plus_2_close_positive_rate": 1.0,
                        "t_plus_2_close_return_distribution": {"mean": 0.02},
                    },
                }
            ],
            "near_peer_summaries": [
                {
                    "ticker": "300720",
                    "distinct_report_count": 4,
                    "observation_count": 4,
                    "mean_similarity_score": 1.2,
                    "recent_window_count": 5,
                    "recent_tier_window_count": 4,
                    "recent_tier_ratio": 0.8,
                    "recent_tier_verdict": "recent_tier_confirmed",
                    "surface_summary": {
                        "next_close_positive_rate": 1.0,
                        "t_plus_2_close_positive_rate": 1.0,
                        "t_plus_2_close_return_distribution": {"mean": 0.03},
                    },
                },
                {
                    "ticker": "600989",
                    "distinct_report_count": 4,
                    "observation_count": 4,
                    "mean_similarity_score": 1.25,
                    "recent_window_count": 5,
                    "recent_tier_window_count": 4,
                    "recent_tier_ratio": 0.8,
                    "recent_tier_verdict": "recent_tier_confirmed",
                    "surface_summary": {
                        "next_close_positive_rate": 1.0,
                        "t_plus_2_close_positive_rate": 1.0,
                        "t_plus_2_close_return_distribution": {"mean": 0.025},
                    },
                },
                {
                    "ticker": "600844",
                    "distinct_report_count": 4,
                    "observation_count": 4,
                    "mean_similarity_score": 1.3,
                    "recent_window_count": 5,
                    "recent_tier_window_count": 4,
                    "recent_tier_ratio": 0.8,
                    "recent_tier_verdict": "recent_tier_confirmed",
                    "surface_summary": {
                        "next_close_positive_rate": 0.8,
                        "t_plus_2_close_positive_rate": 1.0,
                        "t_plus_2_close_return_distribution": {"mean": 0.02},
                    },
                },
                {
                    "ticker": "300683",
                    "distinct_report_count": 1,
                    "observation_count": 2,
                    "mean_similarity_score": 1.1,
                    "recent_window_count": 5,
                    "recent_tier_window_count": 1,
                    "recent_tier_ratio": 0.2,
                    "recent_tier_verdict": "recent_tier_thin",
                    "surface_summary": {
                        "next_close_positive_rate": 1.0,
                        "t_plus_2_close_positive_rate": 1.0,
                        "t_plus_2_close_return_distribution": {"mean": 0.1374},
                    },
                },
            ],
            "observation_candidate_summaries": [],
        },
    )

    analysis = expansion_board.generate_btst_tplus2_continuation_expansion_board(
        reports_root,
        upstream_handoff_board_path=tmp_path / "missing_upstream_handoff_board.json",
    )

    assert [item["ticker"] for item in analysis["next_validation_candidates"]] == ["300720", "600989", "300683"]
