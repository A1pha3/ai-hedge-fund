from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.analyze_btst_candidate_pool_corridor_proof_gate_outcomes import (
    analyze_btst_candidate_pool_corridor_proof_gate_outcomes,
    render_btst_candidate_pool_corridor_proof_gate_outcomes_markdown,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_analyze_btst_candidate_pool_corridor_proof_gate_outcomes_keeps_gate_when_fresh_probes_fail(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    command_board_path = reports_root / "btst_candidate_pool_corridor_window_command_board_latest.json"
    report_dir = reports_root / "paper_window"

    _write_json(
        command_board_path,
        {
            "focus_ticker": "300683",
            "exploratory_trade_dates": [
                "2026-03-27",
                "2026-03-30",
                "2026-03-31",
                "2026-04-06",
                "2026-04-07",
                "2026-04-08",
            ],
            "next_target_trade_dates": ["2026-04-06", "2026-04-07", "2026-04-08"],
            "action_rows": [
                {
                    "trade_date": "2026-04-06",
                    "decision": "near_miss",
                    "candidate_source": "upstream_liquidity_corridor_shadow",
                    "score_target": 0.4111,
                    "report_dir": str(report_dir),
                    "action_tier": "upgrade_near_miss_window",
                },
                {
                    "trade_date": "2026-04-07",
                    "decision": "near_miss",
                    "candidate_source": "upstream_liquidity_corridor_shadow",
                    "score_target": 0.4054,
                    "report_dir": str(report_dir),
                    "action_tier": "upgrade_near_miss_window",
                },
                {
                    "trade_date": "2026-04-08",
                    "decision": "near_miss",
                    "candidate_source": "upstream_liquidity_corridor_shadow",
                    "score_target": 0.4047,
                    "report_dir": str(report_dir),
                    "action_tier": "upgrade_near_miss_window",
                },
                {
                    "trade_date": "2026-03-30",
                    "decision": "near_miss",
                    "candidate_source": "upstream_liquidity_corridor_shadow",
                    "score_target": 0.3965,
                    "report_dir": str(report_dir),
                    "action_tier": "upgrade_near_miss_window",
                },
                {
                    "trade_date": "2026-03-31",
                    "decision": "near_miss",
                    "candidate_source": "upstream_liquidity_corridor_shadow",
                    "score_target": 0.391,
                    "report_dir": str(report_dir),
                    "action_tier": "upgrade_near_miss_window",
                },
                {
                    "trade_date": "2026-03-27",
                    "decision": "near_miss",
                    "candidate_source": "upstream_liquidity_corridor_shadow",
                    "score_target": 0.3883,
                    "report_dir": str(report_dir),
                    "action_tier": "upgrade_near_miss_window",
                },
            ],
        },
    )

    for trade_date, score_target in {
        "2026-03-27": 0.3883,
        "2026-03-30": 0.3965,
        "2026-03-31": 0.391,
        "2026-04-06": 0.4111,
        "2026-04-07": 0.4054,
        "2026-04-08": 0.4047,
    }.items():
        _write_json(
            report_dir / "selection_artifacts" / trade_date / "selection_target_replay_input.json",
            {
                "selection_targets": {
                    "300683": {
                        "short_trade": {
                            "decision": "near_miss",
                            "score_target": score_target,
                            "candidate_source": "upstream_liquidity_corridor_shadow",
                            "negative_tags": ["selected_historical_proof_missing"],
                            "top_reasons": ["trend_acceleration_supportive"],
                            "effective_select_threshold": 0.37,
                            "effective_near_miss_threshold": 0.34,
                            "metrics_payload": {
                                "selected_historical_proof_deficiency": {
                                    "enabled": True,
                                    "proof_missing": True,
                                    "evaluable_count": 0,
                                }
                            },
                        }
                    }
                }
            },
        )

    frame = pd.DataFrame(
        [
            {"Date": "2026-03-27", "open": 38.0, "high": 39.2, "close": 38.81, "low": 37.8, "volume": 1000},
            {"Date": "2026-03-30", "open": 39.35, "high": 45.2, "close": 42.14, "low": 39.0, "volume": 1000},
            {"Date": "2026-03-31", "open": 42.12, "high": 45.95, "close": 43.36, "low": 41.8, "volume": 1000},
            {"Date": "2026-04-01", "open": 43.87, "high": 49.88, "close": 48.78, "low": 43.5, "volume": 1000},
            {"Date": "2026-04-07", "open": 42.0, "high": 42.95, "close": 41.71, "low": 41.5, "volume": 1000},
            {"Date": "2026-04-08", "open": 41.63, "high": 42.95, "close": 38.60, "low": 38.4, "volume": 1000},
            {"Date": "2026-04-09", "open": 37.91, "high": 38.79, "close": 37.44, "low": 37.1, "volume": 1000},
            {"Date": "2026-04-10", "open": 37.2, "high": 37.5, "close": 36.19, "low": 36.0, "volume": 1000},
        ]
    )
    frame["Date"] = pd.to_datetime(frame["Date"])
    frame.set_index("Date", inplace=True)

    def _mock_get_price_data(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        start_ts = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date)
        return frame.loc[(frame.index >= start_ts) & (frame.index <= end_ts)]

    monkeypatch.setattr("scripts.analyze_btst_candidate_pool_corridor_proof_gate_outcomes.get_price_data", _mock_get_price_data)

    analysis = analyze_btst_candidate_pool_corridor_proof_gate_outcomes(command_board_path)

    assert analysis["focus_ticker"] == "300683"
    assert analysis["verdict"] == "keep_proof_gate"
    assert analysis["summary"]["evaluable_count"] == 5
    assert analysis["summary"]["missing_trade_day_count"] == 1
    assert analysis["summary"]["next_close_positive_rate"] == 0.6
    assert analysis["fresh_probe_summary"]["evaluable_count"] == 2
    assert analysis["fresh_probe_summary"]["next_close_positive_rate"] == 0.0
    assert analysis["rows"][0]["trade_date"] == "2026-04-06"
    assert analysis["rows"][0]["outcome"]["data_status"] == "missing_trade_day_bar"
    assert analysis["rows"][1]["outcome"]["next_close_return"] < 0
    assert next(row for row in analysis["rows"] if row["trade_date"] == "2026-03-30")["outcome"]["data_status"] == "ok"

    markdown = render_btst_candidate_pool_corridor_proof_gate_outcomes_markdown(analysis)
    assert "# BTST Candidate Pool Corridor Proof Gate Outcomes: 300683" in markdown
    assert "keep_proof_gate" in markdown
