from __future__ import annotations

from pathlib import Path

import scripts.analyze_btst_tplus2_near_cluster_dossier as dossier


def test_analyze_btst_tplus2_near_cluster_dossier_summarizes_candidate(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()

    monkeypatch.setattr(
        dossier,
        "_collect_rows",
        lambda *_args, **_kwargs: [
            {
                "report_label": "window_a",
                "ticker": "600988",
                "candidate_source": "layer_c_watchlist",
                "metrics_payload": {
                    "breakout_freshness": 0.35,
                    "trend_acceleration": 0.48,
                    "catalyst_freshness": 0.01,
                    "layer_c_alignment": 0.49,
                    "sector_resonance": 0.13,
                    "close_strength": 0.64,
                    "t_plus_2_continuation_candidate": {"applied": True},
                },
                "next_high_return": 0.05,
                "next_close_return": -0.01,
                "t_plus_2_close_return": 0.03,
            },
            {
                "report_label": "window_a",
                "ticker": "600989",
                "candidate_source": "layer_c_watchlist",
                "metrics_payload": {
                    "breakout_freshness": 0.41,
                    "trend_acceleration": 0.56,
                    "catalyst_freshness": 0.02,
                    "layer_c_alignment": 0.52,
                    "sector_resonance": 0.14,
                    "close_strength": 0.78,
                },
                "next_high_return": 0.03,
                "next_close_return": 0.01,
                "t_plus_2_close_return": 0.012,
            },
        ],
    )

    analysis = dossier.analyze_btst_tplus2_near_cluster_dossier(reports_root)

    assert analysis["candidate_ticker"] == "600989"
    assert analysis["candidate_row_count"] == 1
    assert analysis["verdict"] == "near_cluster_candidate"
    assert analysis["candidate_tier_focus"] == "near_cluster_peer"
    assert analysis["tier_counts"]["near_cluster_peer"] == 1
    assert analysis["recent_window_count"] == 1
    assert analysis["recent_supporting_window_count"] == 1
    assert analysis["recent_validation_verdict"] == "recent_support_confirmed"
    assert analysis["recent_tier_verdict"] == "recent_tier_confirmed"
    assert analysis["promotion_readiness_verdict"] == "watchlist_ready"

    markdown = dossier.render_btst_tplus2_near_cluster_dossier_markdown(analysis)
    assert "# BTST T+2 Near-Cluster Dossier" in markdown
    assert "600989" in markdown
    assert "recent_validation_verdict" in markdown


def test_analyze_btst_tplus2_near_cluster_dossier_supports_observation_queue(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()

    monkeypatch.setattr(
        dossier,
        "_collect_rows",
        lambda *_args, **_kwargs: [
            {
                "report_label": "window_a",
                "ticker": "600988",
                "candidate_source": "layer_c_watchlist",
                "metrics_payload": {
                    "breakout_freshness": 0.35,
                    "trend_acceleration": 0.48,
                    "catalyst_freshness": 0.01,
                    "layer_c_alignment": 0.49,
                    "sector_resonance": 0.13,
                    "close_strength": 0.64,
                    "t_plus_2_continuation_candidate": {"applied": True},
                },
                "next_high_return": 0.05,
                "next_close_return": -0.01,
                "t_plus_2_close_return": 0.03,
            },
            {
                "report_label": "window_a",
                "ticker": "300505",
                "candidate_source": "layer_c_watchlist",
                "metrics_payload": {
                    "breakout_freshness": 0.58,
                    "trend_acceleration": 0.75,
                    "catalyst_freshness": 0.04,
                    "layer_c_alignment": 0.62,
                    "sector_resonance": 0.22,
                    "close_strength": 0.95,
                },
                "next_high_return": 0.04,
                "next_close_return": 0.01,
                "t_plus_2_close_return": 0.02,
            },
        ],
    )

    analysis = dossier.analyze_btst_tplus2_near_cluster_dossier(reports_root, candidate_ticker="300505")

    assert analysis["candidate_ticker"] == "300505"
    assert analysis["verdict"] == "observation_only_candidate"
    assert analysis["candidate_tier_focus"] == "observation_candidate"
    assert analysis["recent_tier_verdict"] == "recent_tier_confirmed"
    assert analysis["promotion_readiness_verdict"] == "validation_queue_ready"
