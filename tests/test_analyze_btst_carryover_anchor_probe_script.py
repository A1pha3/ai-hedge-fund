from __future__ import annotations

import json

from scripts.analyze_btst_carryover_anchor_probe import analyze_btst_carryover_anchor_probe, render_btst_carryover_anchor_probe_markdown


def test_analyze_btst_carryover_anchor_probe_recovers_exact_anchor(monkeypatch, tmp_path):
    report_dir = tmp_path / "paper_trading_demo"
    report_dir.mkdir()

    monkeypatch.setattr(
        "scripts.analyze_btst_carryover_anchor_probe.load_btst_followup_by_ticker_for_report",
        lambda _: {
            "002001": {
                "ticker": "002001",
                "decision": "selected",
                "candidate_source": "catalyst_theme",
                "preferred_entry_mode": "confirm_then_hold_breakout",
                "historical_execution_quality_label": "close_continuation",
                "historical_entry_timing_bias": "confirm_then_hold",
                "trade_date": "2026-04-09",
                "historical_prior": {
                    "same_ticker_sample_count": 2,
                    "same_family_sample_count": 4,
                    "same_family_source_sample_count": 4,
                    "same_family_source_score_catalyst_sample_count": 2,
                    "same_source_score_sample_count": 2,
                },
            }
        },
    )
    monkeypatch.setattr(
        "scripts.analyze_btst_carryover_anchor_probe._collect_historical_watch_candidate_rows",
        lambda _, __: {
            "rows": [
                {
                    "trade_date": "2026-03-27",
                    "ticker": "002001",
                    "watch_candidate_family": "research_upside_radar",
                    "candidate_source": "layer_c_watchlist",
                    "score_bucket": "0.30-0.35",
                    "catalyst_bucket": "none",
                    "decision": "rejected",
                    "score_target": 0.3131,
                    "report_dir": "r1",
                },
                {
                    "trade_date": "2026-03-28",
                    "ticker": "002001",
                    "watch_candidate_family": "research_upside_radar",
                    "candidate_source": "layer_c_watchlist",
                    "score_bucket": "0.30-0.35",
                    "catalyst_bucket": "none",
                    "decision": "rejected",
                    "score_target": 0.3140,
                    "report_dir": "r2",
                },
                {
                    "trade_date": "2026-03-27",
                    "ticker": "300001",
                    "watch_candidate_family": "research_upside_radar",
                    "candidate_source": "layer_c_watchlist",
                    "score_bucket": "0.35-0.40",
                    "catalyst_bucket": "none",
                    "decision": "rejected",
                    "score_target": 0.3200,
                    "report_dir": "r3",
                },
                {
                    "trade_date": "2026-03-28",
                    "ticker": "300002",
                    "watch_candidate_family": "research_upside_radar",
                    "candidate_source": "layer_c_watchlist",
                    "score_bucket": "0.35-0.40",
                    "catalyst_bucket": "none",
                    "decision": "rejected",
                    "score_target": 0.3180,
                    "report_dir": "r4",
                },
            ]
        },
    )
    monkeypatch.setattr(
        "scripts.analyze_btst_carryover_anchor_probe.extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: {
            "next_high_return": 0.05 if ticker == "002001" else 0.03,
            "next_close_return": 0.04 if ticker == "002001" else 0.01,
            "t_plus_2_close_return": 0.01 if ticker == "002001" else 0.005,
        },
    )

    analysis = analyze_btst_carryover_anchor_probe(tmp_path, ticker="002001", report_dir=report_dir)
    markdown = render_btst_carryover_anchor_probe_markdown(analysis)

    assert analysis["probes"][0]["exact_match"] is True
    assert analysis["probes"][0]["fingerprint_distance"] == 0
    assert analysis["probes"][0]["same_family_source_score_catalyst_surface_summary"]["total_count"] == 2
    assert "完全一致的 anchor" in analysis["recommendation"]
    assert "fingerprint_distance=0" in markdown


def test_analyze_btst_carryover_anchor_probe_falls_back_to_legacy_snapshot_when_followup_missing(monkeypatch, tmp_path):
    report_dir = tmp_path / "paper_trading_demo"
    snapshot_dir = report_dir / "selection_artifacts" / "2026-04-22"
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-04-22",
                "target_context": [
                    {
                        "ticker": "688313",
                        "short_trade": {"decision": "selected"},
                        "replay_context": {
                            "historical_prior": {
                                "same_ticker_sample_count": 1,
                                "same_family_sample_count": 2,
                                "same_family_source_sample_count": 2,
                                "same_family_source_score_catalyst_sample_count": 1,
                                "same_source_score_sample_count": 1,
                            }
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("scripts.analyze_btst_carryover_anchor_probe.load_btst_followup_by_ticker_for_report", lambda _: {})
    monkeypatch.setattr(
        "scripts.analyze_btst_carryover_anchor_probe._collect_historical_watch_candidate_rows",
        lambda _, __: {
            "rows": [
                {
                    "trade_date": "2026-03-27",
                    "ticker": "688313",
                    "watch_candidate_family": "research_upside_radar",
                    "candidate_source": "layer_c_watchlist",
                    "score_bucket": "0.30-0.35",
                    "catalyst_bucket": "none",
                    "decision": "rejected",
                    "score_target": 0.3131,
                    "report_dir": "r1",
                }
            ]
        },
    )
    monkeypatch.setattr(
        "scripts.analyze_btst_carryover_anchor_probe.extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: {
            "next_high_return": 0.05,
            "next_close_return": 0.04,
            "t_plus_2_close_return": 0.01,
        },
    )

    analysis = analyze_btst_carryover_anchor_probe(tmp_path, ticker="688313", report_dir=report_dir)

    assert analysis["target_row"]["ticker"] == "688313"
    assert analysis["target_prior_fingerprint"]["same_family_sample_count"] == 2


def test_analyze_btst_carryover_anchor_probe_returns_empty_diagnostic_when_no_ticker_anchor_candidates(monkeypatch, tmp_path):
    report_dir = tmp_path / "paper_trading_demo"
    snapshot_dir = report_dir / "selection_artifacts" / "2026-04-22"
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-04-22",
                "target_context": [
                    {
                        "ticker": "688313",
                        "short_trade": {"decision": "selected"},
                        "replay_context": {
                            "historical_prior": {
                                "same_ticker_sample_count": 1,
                                "same_family_sample_count": 2,
                                "same_family_source_sample_count": 2,
                                "same_family_source_score_catalyst_sample_count": 1,
                                "same_source_score_sample_count": 1,
                            }
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("scripts.analyze_btst_carryover_anchor_probe.load_btst_followup_by_ticker_for_report", lambda _: {})
    monkeypatch.setattr(
        "scripts.analyze_btst_carryover_anchor_probe._collect_historical_watch_candidate_rows",
        lambda _, __: {
            "rows": [
                {
                    "trade_date": "2026-03-27",
                    "ticker": "300001",
                    "watch_candidate_family": "research_upside_radar",
                    "candidate_source": "layer_c_watchlist",
                    "score_bucket": "0.30-0.35",
                    "catalyst_bucket": "none",
                    "decision": "rejected",
                    "score_target": 0.3131,
                    "report_dir": "r1",
                }
            ]
        },
    )

    analysis = analyze_btst_carryover_anchor_probe(tmp_path, ticker="688313", report_dir=report_dir)
    markdown = render_btst_carryover_anchor_probe_markdown(analysis)

    assert analysis["ticker_anchor_candidate_count"] == 0
    assert analysis["probes"] == []
    assert "没有找到同 ticker 的历史 anchor candidates" in analysis["recommendation"]
    assert "- none" in markdown
