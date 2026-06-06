from __future__ import annotations

from pathlib import Path

import scripts.analyze_btst_tplus2_continuation_clusters as continuation_clusters


def test_analyze_btst_tplus2_continuation_clusters_identifies_recurring_cluster(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "reports"
    window_a = reports_root / "paper_trading_window_a_btst"
    window_b = reports_root / "paper_trading_window_b_btst"
    for report_dir in (window_a, window_b):
        report_dir.mkdir(parents=True)

    monkeypatch.setattr(continuation_clusters, "discover_report_dirs", lambda *_args, **_kwargs: [window_a, window_b])

    def _fake_replay_window(input_path, *, profile_name, label, next_high_hit_threshold):
        report_name = Path(input_path).name
        if report_name == "paper_trading_window_a_btst":
            rows = [
                {
                    "report_label": label,
                    "trade_date": "2026-03-24",
                    "ticker": "600988",
                    "decision": "rejected",
                    "candidate_source": "layer_c_watchlist",
                    "metrics_payload": {
                        "breakout_freshness": 0.35,
                        "trend_acceleration": 0.56,
                        "catalyst_freshness": 0.04,
                        "layer_c_alignment": 0.49,
                        "sector_resonance": 0.13,
                        "close_strength": 0.88,
                        "t_plus_2_continuation_candidate": {"applied": True},
                    },
                    "next_open_return": 0.01,
                    "next_high_return": 0.04,
                    "next_close_return": -0.02,
                    "next_open_to_close_return": -0.01,
                    "t_plus_2_close_return": 0.03,
                },
                {
                    "report_label": label,
                    "trade_date": "2026-03-24",
                    "ticker": "300724",
                    "decision": "rejected",
                    "candidate_source": "layer_c_watchlist",
                    "metrics_payload": {"t_plus_2_continuation_candidate": {"applied": False}},
                    "next_open_return": 0.0,
                    "next_high_return": 0.01,
                    "next_close_return": -0.03,
                    "next_open_to_close_return": -0.03,
                    "t_plus_2_close_return": -0.04,
                },
            ]
        else:
            rows = [
                {
                    "report_label": label,
                    "trade_date": "2026-03-25",
                    "ticker": "600988",
                    "decision": "near_miss",
                    "candidate_source": "layer_c_watchlist",
                    "metrics_payload": {
                        "breakout_freshness": 0.31,
                        "trend_acceleration": 0.41,
                        "catalyst_freshness": 0.03,
                        "layer_c_alignment": 0.52,
                        "sector_resonance": 0.18,
                        "close_strength": 0.39,
                        "t_plus_2_continuation_candidate": {"applied": True},
                    },
                    "next_open_return": 0.0,
                    "next_high_return": 0.02,
                    "next_close_return": 0.01,
                    "next_open_to_close_return": 0.01,
                    "t_plus_2_close_return": 0.04,
                }
            ]
        return {"rows": rows}

    monkeypatch.setattr(continuation_clusters, "analyze_btst_profile_replay_window", _fake_replay_window)

    analysis = continuation_clusters.analyze_btst_tplus2_continuation_clusters(
        reports_root,
        profile_name="watchlist_zero_catalyst_guard_relief",
        report_name_contains="btst",
    )

    assert analysis["continuation_row_count"] == 2
    assert analysis["ticker_count"] == 1
    assert analysis["recurring_cluster_count"] == 1
    assert analysis["strong_t_plus_2_edge_count"] == 1
    assert analysis["recommendation"].startswith("Detected recurring T+2 continuation clusters")
    assert analysis["ticker_summaries"][0]["ticker"] == "600988"
    assert analysis["ticker_summaries"][0]["pattern_label"] == "recurring_tplus2_continuation_cluster"

    markdown = continuation_clusters.render_btst_tplus2_continuation_clusters_markdown(analysis)
    assert "# BTST T+2 Continuation Clusters" in markdown
    assert "600988" in markdown
    assert "recurring_tplus2_continuation_cluster" in markdown
