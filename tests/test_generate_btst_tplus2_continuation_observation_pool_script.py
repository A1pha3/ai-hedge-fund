from __future__ import annotations

from pathlib import Path

import scripts.generate_btst_tplus2_continuation_observation_pool as observation_pool


def test_generate_btst_tplus2_continuation_observation_pool_prioritizes_anchor_cluster(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()

    monkeypatch.setattr(
        observation_pool,
        "analyze_btst_tplus2_continuation_clusters",
        lambda *_args, **_kwargs: {
            "continuation_row_count": 4,
            "ticker_count": 1,
            "recurring_cluster_count": 1,
            "ticker_summaries": [
                {
                    "ticker": "600988",
                    "distinct_report_count": 2,
                    "observation_count": 4,
                    "pattern_label": "recurring_tplus2_continuation_cluster",
                    "recommendation": "600988 recurring cluster",
                    "surface_summary": {
                        "next_close_positive_rate": 0.5,
                        "t_plus_2_close_positive_rate": 1.0,
                        "t_plus_2_close_return_distribution": {"mean": 0.0355},
                    },
                }
            ],
        },
    )
    monkeypatch.setattr(
        observation_pool,
        "analyze_btst_tplus2_continuation_peer_scan",
        lambda *_args, **_kwargs: {
            "peer_count": 0,
            "near_cluster_count": 1,
            "peer_summaries": [],
            "near_peer_summaries": [
                {
                    "ticker": "600989",
                    "distinct_report_count": 7,
                    "observation_count": 7,
                    "mean_similarity_score": 1.6517,
                    "surface_summary": {
                        "next_close_positive_rate": 1.0,
                        "t_plus_2_close_positive_rate": 1.0,
                        "t_plus_2_close_return_distribution": {"mean": 0.0117},
                    },
                }
            ],
            "recommendation": "single ticker only",
        },
    )

    analysis = observation_pool.generate_btst_tplus2_continuation_observation_pool(
        reports_root,
        upstream_handoff_board_path=tmp_path / "missing_upstream_handoff_board.json",
    )

    assert analysis["entry_count"] == 2
    assert analysis["entries"][0]["ticker"] == "600988"
    assert analysis["entries"][0]["entry_type"] == "anchor_cluster"
    assert analysis["entries"][0]["lane_stage"] == "observation_only"
    assert analysis["entries"][1]["ticker"] == "600989"
    assert analysis["entries"][1]["entry_type"] == "near_cluster_watch"
    assert analysis["entries"][1]["lane_stage"] == "validation_watch"
    assert analysis["recommendation"].startswith("Observation pool ready")

    markdown = observation_pool.render_btst_tplus2_continuation_observation_pool_markdown(analysis)
    assert "# BTST T+2 Continuation Observation Pool" in markdown
    assert "600988" in markdown


def test_generate_btst_tplus2_continuation_observation_pool_includes_governance_followup(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()
    upstream_handoff_board_path = tmp_path / "btst_candidate_pool_upstream_handoff_board_latest.json"
    upstream_handoff_board_path.write_text(
        """
        {
          "board_rows": [
            {
              "ticker": "300720",
              "board_rank": 2,
              "downstream_followup_lane": "t_plus_2_continuation_review",
              "downstream_followup_status": "continuation_confirm_then_review",
              "downstream_followup_blocker": "no_selected_persistence_or_independent_edge",
              "downstream_followup_summary": "300720 should enter continuation validation watch."
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        observation_pool,
        "analyze_btst_tplus2_continuation_clusters",
        lambda *_args, **_kwargs: {
            "continuation_row_count": 0,
            "ticker_count": 0,
            "recurring_cluster_count": 0,
            "ticker_summaries": [],
        },
    )
    monkeypatch.setattr(
        observation_pool,
        "analyze_btst_tplus2_continuation_peer_scan",
        lambda *_args, **_kwargs: {
            "peer_count": 0,
            "near_cluster_count": 0,
            "peer_summaries": [],
            "near_peer_summaries": [],
            "recommendation": "none",
        },
    )

    analysis = observation_pool.generate_btst_tplus2_continuation_observation_pool(
        reports_root,
        upstream_handoff_board_path=upstream_handoff_board_path,
    )

    assert analysis["governance_followup_count"] == 1
    assert analysis["entries"][0]["ticker"] == "300720"
    assert analysis["entries"][0]["entry_type"] == "governance_followup"
    assert analysis["entries"][0]["governance_status"] == "continuation_confirm_then_review"
