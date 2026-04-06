from __future__ import annotations

from pathlib import Path

import scripts.analyze_btst_tplus2_continuation_peer_rollup as peer_rollup


def test_analyze_btst_tplus2_continuation_peer_rollup_detects_near_cluster_breakthrough(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()

    monkeypatch.setattr(
        peer_rollup,
        "generate_btst_tplus2_continuation_expansion_board",
        lambda *_args, **_kwargs: {
            "strict_peer_count": 0,
            "near_cluster_count": 1,
            "observation_candidate_count": 2,
            "board_rows": [
                {
                    "ticker": "600989",
                    "tier": "near_cluster_peer",
                    "distinct_report_count": 7,
                    "observation_count": 7,
                    "mean_similarity_score": 1.6517,
                    "recent_window_count": 5,
                    "recent_tier_window_count": 4,
                    "recent_tier_ratio": 0.8,
                    "recent_tier_verdict": "recent_tier_confirmed",
                    "next_close_positive_rate": 1.0,
                    "t_plus_2_close_positive_rate": 1.0,
                    "t_plus_2_close_return_mean": 0.0117,
                },
                {
                    "ticker": "300724",
                    "tier": "observation_candidate",
                    "distinct_report_count": 3,
                    "observation_count": 5,
                    "mean_similarity_score": 1.3421,
                    "recent_window_count": 5,
                    "recent_tier_window_count": 1,
                    "recent_tier_ratio": 0.2,
                    "recent_tier_verdict": "recent_tier_thin",
                    "next_close_positive_rate": 0.0,
                    "t_plus_2_close_positive_rate": 0.2,
                    "t_plus_2_close_return_mean": -0.0182,
                },
            ],
            "next_validation_candidates": [
                {
                    "ticker": "000792",
                    "tier": "observation_candidate",
                    "priority_rank": 2,
                    "recent_tier_verdict": "recent_tier_confirmed",
                    "recent_tier_window_count": 3,
                    "recent_window_count": 4,
                    "recent_tier_ratio": 0.75,
                }
            ],
        },
    )

    analysis = peer_rollup.analyze_btst_tplus2_continuation_peer_rollup(reports_root)

    assert analysis["rollup_verdict"] == "first_near_cluster_breakthrough"
    assert analysis["top_candidate"]["ticker"] == "600989"
    assert analysis["next_validation_candidates"][0]["ticker"] == "000792"
    assert analysis["risk_flags"][0]["ticker"] == "300724"
    assert "recent_tier_verdict=recent_tier_confirmed" in analysis["recommendation"]

    markdown = peer_rollup.render_btst_tplus2_continuation_peer_rollup_markdown(analysis)
    assert "# BTST T+2 Continuation Peer Rollup" in markdown
    assert "600989" in markdown
    assert "000792" in markdown
