from __future__ import annotations

from pathlib import Path

import scripts.analyze_btst_tplus2_continuation_peer_scan as peer_scan


def test_analyze_btst_tplus2_continuation_peer_scan_finds_same_cluster_peer(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "reports"
    window_a = reports_root / "paper_trading_window_a_btst"
    window_b = reports_root / "paper_trading_window_b_btst"
    for report_dir in (window_a, window_b):
        report_dir.mkdir(parents=True)

    monkeypatch.setattr(peer_scan, "discover_report_dirs", lambda *_args, **_kwargs: [window_a, window_b])

    def _fake_replay_window(input_path, *, profile_name, label, next_high_hit_threshold):
        report_name = Path(input_path).name
        anchor_row = {
            "report_label": label,
            "trade_date": "2026-03-24" if report_name.endswith("a_btst") else "2026-03-25",
            "ticker": "600988",
            "decision": "rejected",
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
            "next_open_return": 0.01,
            "next_high_return": 0.05,
            "next_close_return": -0.01,
            "next_open_to_close_return": -0.02,
            "t_plus_2_close_return": 0.03,
        }
        peer_row = {
            "report_label": label,
            "trade_date": "2026-03-24" if report_name.endswith("a_btst") else "2026-03-25",
            "ticker": "300620",
            "decision": "rejected",
            "candidate_source": "layer_c_watchlist",
            "metrics_payload": {
                "breakout_freshness": 0.37,
                "trend_acceleration": 0.46,
                "catalyst_freshness": 0.02,
                "layer_c_alignment": 0.5,
                "sector_resonance": 0.14,
                "close_strength": 0.66,
                "t_plus_2_continuation_candidate": {"applied": False},
            },
            "next_open_return": 0.0,
            "next_high_return": 0.03,
            "next_close_return": -0.005,
            "next_open_to_close_return": -0.005,
            "t_plus_2_close_return": 0.025,
        }
        bad_row = {
            "report_label": label,
            "trade_date": "2026-03-24" if report_name.endswith("a_btst") else "2026-03-25",
            "ticker": "300724",
            "decision": "selected",
            "candidate_source": "layer_c_watchlist",
            "metrics_payload": {
                "breakout_freshness": 0.4,
                "trend_acceleration": 0.68,
                "catalyst_freshness": 0.0,
                "layer_c_alignment": 0.47,
                "sector_resonance": 0.1,
                "close_strength": 0.95,
                "t_plus_2_continuation_candidate": {"applied": False},
            },
            "next_open_return": 0.0,
            "next_high_return": 0.01,
            "next_close_return": -0.03,
            "next_open_to_close_return": -0.03,
            "t_plus_2_close_return": -0.04,
        }
        return {"rows": [anchor_row, peer_row, bad_row]}

    monkeypatch.setattr(peer_scan, "analyze_btst_profile_replay_window", _fake_replay_window)

    analysis = peer_scan.analyze_btst_tplus2_continuation_peer_scan(
        reports_root,
        anchor_ticker="600988",
        profile_name="watchlist_zero_catalyst_guard_relief",
        report_name_contains="btst",
    )

    assert analysis["anchor_profile"]["ticker"] == "600988"
    assert analysis["peer_count"] == 1
    assert analysis["peer_summaries"][0]["ticker"] == "300620"
    assert analysis["peer_summaries"][0]["distinct_report_count"] == 2
    assert analysis["peer_summaries"][0]["recent_tier_window_count"] == 2
    assert analysis["peer_summaries"][0]["recent_window_count"] == 2
    assert analysis["peer_summaries"][0]["recent_tier_verdict"] == "recent_tier_confirmed"
    assert analysis["near_cluster_count"] == 0
    assert analysis["observation_candidate_count"] == 0
    assert len(analysis["near_peer_rejections"]) == 2
    assert analysis["near_peer_rejections"][0]["ticker"] == "300724"
    assert analysis["recommendation"].startswith("Found same-cluster continuation peers")

    markdown = peer_scan.render_btst_tplus2_continuation_peer_scan_markdown(analysis)
    assert "# BTST T+2 Continuation Peer Scan" in markdown
    assert "300620" in markdown


def test_analyze_btst_tplus2_continuation_peer_scan_surfaces_near_cluster_candidates(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "reports"
    window_a = reports_root / "paper_trading_window_a_btst"
    window_a.mkdir(parents=True)

    monkeypatch.setattr(peer_scan, "discover_report_dirs", lambda *_args, **_kwargs: [window_a])

    def _fake_replay_window(_input_path, *, profile_name, label, next_high_hit_threshold):
        return {
            "rows": [
                {
                    "report_label": label,
                    "trade_date": "2026-03-24",
                    "ticker": "600988",
                    "decision": "rejected",
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
                    "next_open_return": 0.01,
                    "next_high_return": 0.05,
                    "next_close_return": -0.01,
                    "next_open_to_close_return": -0.02,
                    "t_plus_2_close_return": 0.03,
                },
                {
                    "report_label": label,
                    "trade_date": "2026-03-24",
                    "ticker": "000988",
                    "decision": "near_miss",
                    "candidate_source": "layer_c_watchlist",
                    "metrics_payload": {
                        "breakout_freshness": 0.43,
                        "trend_acceleration": 0.58,
                        "catalyst_freshness": 0.03,
                        "layer_c_alignment": 0.54,
                        "sector_resonance": 0.15,
                        "close_strength": 0.78,
                        "t_plus_2_continuation_candidate": {"applied": False},
                    },
                    "next_open_return": 0.0,
                    "next_high_return": 0.025,
                    "next_close_return": -0.004,
                    "next_open_to_close_return": -0.004,
                    "t_plus_2_close_return": 0.006,
                },
            ]
        }

    monkeypatch.setattr(peer_scan, "analyze_btst_profile_replay_window", _fake_replay_window)

    analysis = peer_scan.analyze_btst_tplus2_continuation_peer_scan(
        reports_root,
        anchor_ticker="600988",
        profile_name="watchlist_zero_catalyst_guard_relief",
        report_name_contains="btst",
    )

    assert analysis["peer_count"] == 0
    assert analysis["near_cluster_count"] == 1
    assert analysis["near_peer_summaries"][0]["ticker"] == "000988"
    assert analysis["near_peer_summaries"][0]["recent_tier_window_count"] == 1
    assert analysis["near_peer_summaries"][0]["recent_tier_verdict"] == "recent_tier_confirmed"
    assert analysis["observation_candidate_count"] == 0
    assert analysis["recommendation"].startswith("No strict same-cluster peer passed")


def test_analyze_btst_tplus2_continuation_peer_scan_includes_corridor_shadow_candidates(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "reports"
    window_a = reports_root / "paper_trading_window_a_btst"
    window_b = reports_root / "paper_trading_window_b_btst"
    for report_dir in (window_a, window_b):
        report_dir.mkdir(parents=True)

    monkeypatch.setattr(peer_scan, "discover_report_dirs", lambda *_args, **_kwargs: [window_a, window_b])

    def _fake_replay_window(input_path, *, profile_name, label, next_high_hit_threshold):
        report_name = Path(input_path).name
        trade_date = "2026-03-24" if report_name.endswith("a_btst") else "2026-03-25"
        return {
            "rows": [
                {
                    "report_label": label,
                    "trade_date": trade_date,
                    "ticker": "600988",
                    "decision": "rejected",
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
                    "next_open_return": 0.01,
                    "next_high_return": 0.05,
                    "next_close_return": -0.01,
                    "next_open_to_close_return": -0.02,
                    "t_plus_2_close_return": 0.03,
                },
                {
                    "report_label": label,
                    "trade_date": trade_date,
                    "ticker": "300683",
                    "decision": "near_miss",
                    "candidate_source": "upstream_liquidity_corridor_shadow",
                    "metrics_payload": {
                        "breakout_freshness": 0.37,
                        "trend_acceleration": 0.5,
                        "catalyst_freshness": 0.02,
                        "layer_c_alignment": 0.5,
                        "sector_resonance": 0.14,
                        "close_strength": 0.66,
                        "t_plus_2_continuation_candidate": {"applied": False},
                    },
                    "next_open_return": 0.0,
                    "next_high_return": 0.03,
                    "next_close_return": 0.005,
                    "next_open_to_close_return": 0.005,
                    "t_plus_2_close_return": 0.025,
                },
            ]
        }

    monkeypatch.setattr(peer_scan, "analyze_btst_profile_replay_window", _fake_replay_window)

    analysis = peer_scan.analyze_btst_tplus2_continuation_peer_scan(
        reports_root,
        anchor_ticker="600988",
        profile_name="watchlist_zero_catalyst_guard_relief",
        report_name_contains="btst",
    )

    assert analysis["peer_count"] == 1
    assert analysis["peer_summaries"][0]["ticker"] == "300683"
    assert analysis["peer_summaries"][0]["distinct_report_count"] == 2


def test_analyze_btst_tplus2_continuation_peer_scan_threads_analysis_payload(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()

    monkeypatch.setattr(
        peer_scan,
        "_collect_rows",
        lambda *_args, **_kwargs: [{"ticker": "600988"}],
    )
    monkeypatch.setattr(peer_scan, "_build_anchor_profile", lambda rows, anchor_ticker: {"ticker": anchor_ticker})
    monkeypatch.setattr(
        peer_scan,
        "_classify_peer_candidate_rows",
        lambda *args, **kwargs: (
            [{"ticker": "300620", "similarity_score": 1.1}],
            [{"ticker": "000988", "similarity_score": 1.8}],
            [{"ticker": "300505", "similarity_score": 2.5}],
            [{"ticker": "300724", "similarity_score": 2.9}],
            {"300620": [{"ticker": "300620"}], "000988": [{"ticker": "000988"}], "300505": [{"ticker": "300505"}]},
        ),
    )
    monkeypatch.setattr(
        peer_scan,
        "_summarize_scan_tiers",
        lambda strict_peer_rows, near_peer_rows, observation_candidate_rows, grouped_all_candidate_rows, next_high_hit_threshold, recent_window_limit: (
            [{"ticker": "300620"}],
            [{"ticker": "000988"}],
            [{"ticker": "300505"}],
        ),
    )
    monkeypatch.setattr(peer_scan, "_build_peer_scan_recommendation", lambda **kwargs: "scan ready")

    analysis = peer_scan.analyze_btst_tplus2_continuation_peer_scan(reports_root)

    assert analysis["anchor_profile"] == {"ticker": "600988"}
    assert analysis["peer_summaries"] == [{"ticker": "300620"}]
    assert analysis["near_peer_summaries"] == [{"ticker": "000988"}]
    assert analysis["observation_candidate_summaries"] == [{"ticker": "300505"}]
    assert analysis["near_peer_rejections"] == [{"ticker": "300724", "similarity_score": 2.9}]
    assert analysis["recommendation"] == "scan ready"
