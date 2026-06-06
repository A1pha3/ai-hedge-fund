from __future__ import annotations

import json

from scripts.analyze_short_trade_ticker_role_history import analyze_short_trade_ticker_role_history, discover_report_dirs


def test_analyze_short_trade_ticker_role_history_detects_window_local_short_trade_baseline(tmp_path):
    old_report = tmp_path / "old_report"
    new_report = tmp_path / "new_report"
    (old_report / "selection_artifacts" / "2026-03-23").mkdir(parents=True)
    (new_report / "selection_artifacts" / "2026-03-23").mkdir(parents=True)
    (new_report / "selection_artifacts" / "2026-03-25").mkdir(parents=True)

    (old_report / "selection_artifacts" / "2026-03-23" / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-23",
                "layer_b": {
                    "tickers": [
                        {
                            "ticker": "600821",
                            "reason": "below_fast_score_threshold",
                            "score_b": 0.146,
                            "decision": "neutral",
                            "rank": 28,
                        }
                    ]
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    for trade_date in ["2026-03-23", "2026-03-25"]:
        (new_report / "selection_artifacts" / trade_date / "selection_snapshot.json").write_text(
            json.dumps(
                {
                    "trade_date": trade_date,
                    "targets": {
                        "600821": {
                            "ticker": "600821",
                            "trade_date": trade_date,
                            "candidate_source": "short_trade_boundary",
                            "short_trade": {
                                "decision": "rejected",
                                "score_target": 0.36,
                                "rank_hint": 2,
                                "gate_status": {"score": "fail"},
                                "metrics_payload": {
                                    "candidate_score": 0.47,
                                    "breakout_freshness": 0.4,
                                    "trend_acceleration": 0.84,
                                    "volume_expansion_quality": 0.25,
                                    "catalyst_freshness": 0.0,
                                    "close_strength": 0.91,
                                },
                            },
                        }
                    },
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    analysis = analyze_short_trade_ticker_role_history([old_report, new_report], tickers=["600821"])

    summary = analysis["ticker_summaries"][0]
    assert summary["role_counts"]["layer_b_pool_below_fast_score_threshold"] == 1
    assert summary["role_counts"]["short_trade_boundary_rejected"] == 2
    assert summary["recurring_short_trade_trade_date_count"] == 2
    assert summary["first_short_trade_report_dir"] == "new_report"
    assert "窗口内成立的局部 baseline" in summary["recommendation"]


def test_discover_report_dirs_finds_reports_from_root_with_optional_name_filter(tmp_path):
    matching_report = tmp_path / "paper_trading_window_foo"
    ignored_report = tmp_path / "other_report"
    (matching_report / "selection_artifacts" / "2026-03-23").mkdir(parents=True)
    (ignored_report / "selection_artifacts" / "2026-03-23").mkdir(parents=True)
    (matching_report / "selection_artifacts" / "2026-03-23" / "selection_snapshot.json").write_text("{}\n", encoding="utf-8")
    (ignored_report / "selection_artifacts" / "2026-03-23" / "selection_snapshot.json").write_text("{}\n", encoding="utf-8")

    discovered = discover_report_dirs([tmp_path], report_name_contains="paper_trading_window_")

    assert discovered == [matching_report.resolve()]