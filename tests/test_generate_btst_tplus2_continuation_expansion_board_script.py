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

    analysis = expansion_board.generate_btst_tplus2_continuation_expansion_board(reports_root)

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
