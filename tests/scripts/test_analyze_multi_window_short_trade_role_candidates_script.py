from __future__ import annotations

import json

from scripts.analyze_multi_window_short_trade_role_candidates import analyze_multi_window_short_trade_role_candidates


def test_analyze_multi_window_short_trade_role_candidates_marks_emergent_local_baseline(tmp_path):
    old_report = tmp_path / "paper_trading_window_20260316_20260323_live"
    current_report = tmp_path / "paper_trading_window_20260323_20260326_live"
    (old_report / "selection_artifacts" / "2026-03-23").mkdir(parents=True)
    (current_report / "selection_artifacts" / "2026-03-24").mkdir(parents=True)
    (current_report / "selection_artifacts" / "2026-03-25").mkdir(parents=True)

    (old_report / "selection_artifacts" / "2026-03-23" / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-23",
                "layer_b": {
                    "tickers": [
                        {"ticker": "600821", "reason": "below_fast_score_threshold", "score_b": 0.1, "decision": "neutral", "rank": 1}
                    ]
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    for trade_date in ["2026-03-24", "2026-03-25"]:
        (current_report / "selection_artifacts" / trade_date / "selection_snapshot.json").write_text(
            json.dumps(
                {
                    "trade_date": trade_date,
                    "targets": {
                        "600821": {
                            "ticker": "600821",
                            "trade_date": trade_date,
                            "candidate_source": "short_trade_boundary",
                            "short_trade": {"decision": "rejected", "score_target": 0.36, "metrics_payload": {}},
                        }
                    },
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    analysis = analyze_multi_window_short_trade_role_candidates([old_report, current_report])

    assert analysis["stable_candidate_count"] == 0
    assert analysis["candidates"][0]["ticker"] == "600821"
    assert analysis["candidates"][0]["transition_locality"] == "emergent_local_baseline"
    assert analysis["candidates"][0]["distinct_window_count"] == 1


def test_analyze_multi_window_short_trade_role_candidates_marks_multi_window_stable(tmp_path):
    report_a = tmp_path / "paper_trading_window_20260316_20260323_live"
    report_b = tmp_path / "paper_trading_window_20260323_20260326_live"
    (report_a / "selection_artifacts" / "2026-03-20").mkdir(parents=True)
    (report_b / "selection_artifacts" / "2026-03-24").mkdir(parents=True)

    (report_a / "selection_artifacts" / "2026-03-20" / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-20",
                "targets": {
                    "000001": {
                        "ticker": "000001",
                        "trade_date": "2026-03-20",
                        "candidate_source": "short_trade_boundary",
                        "short_trade": {"decision": "near_miss", "score_target": 0.47, "metrics_payload": {}},
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (report_b / "selection_artifacts" / "2026-03-24" / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-24",
                "targets": {
                    "000001": {
                        "ticker": "000001",
                        "trade_date": "2026-03-24",
                        "candidate_source": "short_trade_boundary",
                        "short_trade": {"decision": "rejected", "score_target": 0.41, "metrics_payload": {}},
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_multi_window_short_trade_role_candidates([report_a, report_b])

    assert analysis["stable_candidate_count"] == 1
    assert analysis["candidates"][0]["ticker"] == "000001"
    assert analysis["candidates"][0]["transition_locality"] == "multi_window_stable"
    assert analysis["candidates"][0]["distinct_window_count"] == 2