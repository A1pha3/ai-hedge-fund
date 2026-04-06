from __future__ import annotations

from pathlib import Path

import scripts.generate_btst_tplus2_continuation_lane_rulepack as lane_rulepack


def test_generate_btst_tplus2_continuation_lane_rulepack_builds_single_ticker_lane(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()

    monkeypatch.setattr(
        lane_rulepack,
        "generate_btst_tplus2_continuation_observation_pool",
        lambda *_args, **_kwargs: {
            "entry_count": 1,
            "entries": [
                {
                    "ticker": "600988",
                    "entry_type": "anchor_cluster",
                    "lane_stage": "observation_only",
                    "priority_score": 28.55,
                    "t_plus_2_close_positive_rate": 1.0,
                    "t_plus_2_close_return_mean": 0.0355,
                }
            ],
        },
    )

    analysis = lane_rulepack.generate_btst_tplus2_continuation_lane_rulepack(reports_root)

    assert analysis["lane_status"] == "single_ticker_observation_lane"
    assert analysis["eligible_tickers"] == ["600988"]
    assert analysis["lane_rules"]["capital_mode"] == "paper_only"
    assert analysis["lane_rules"]["block_from_default_btst_tradeable_surface"] is True
    assert analysis["recommendation"].startswith("Use this lane as paper-only")

    markdown = lane_rulepack.render_btst_tplus2_continuation_lane_rulepack_markdown(analysis)
    assert "# BTST T+2 Continuation Lane Rulepack" in markdown
    assert "600988" in markdown


def test_generate_btst_tplus2_continuation_lane_rulepack_adds_watchlist_tickers(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()

    monkeypatch.setattr(
        lane_rulepack,
        "generate_btst_tplus2_continuation_observation_pool",
        lambda *_args, **_kwargs: {
            "entry_count": 2,
            "entries": [
                {
                    "ticker": "600988",
                    "entry_type": "anchor_cluster",
                    "lane_stage": "observation_only",
                    "priority_score": 28.55,
                    "t_plus_2_close_positive_rate": 1.0,
                    "t_plus_2_close_return_mean": 0.0355,
                },
                {
                    "ticker": "600989",
                    "entry_type": "near_cluster_watch",
                    "lane_stage": "validation_watch",
                    "priority_score": 18.94,
                    "t_plus_2_close_positive_rate": 1.0,
                    "t_plus_2_close_return_mean": 0.0117,
                },
            ],
        },
    )

    analysis = lane_rulepack.generate_btst_tplus2_continuation_lane_rulepack(reports_root)

    assert analysis["lane_status"] == "anchor_plus_validation_watch"
    assert analysis["eligible_tickers"] == ["600988"]
    assert analysis["watchlist_tickers"] == ["600989"]
    assert analysis["lane_rules"]["watchlist_entry_types"] == ["near_cluster_watch"]
