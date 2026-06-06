from __future__ import annotations

import json

import pandas as pd

from scripts.analyze_btst_micro_window_regression import analyze_btst_micro_window_regression


def _write_snapshot(day_dir, *, trade_date: str, ticker: str, decision: str, score_target: float, candidate_source: str) -> None:
    day_dir.mkdir(parents=True)
    (day_dir / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": trade_date,
                "target_mode": "dual_target",
                "selection_targets": {
                    ticker: {
                        "ticker": ticker,
                        "trade_date": trade_date,
                        "candidate_source": candidate_source,
                        "candidate_reason_codes": ["short_trade_candidate_score_ranked"],
                        "short_trade": {
                            "decision": decision,
                            "score_target": score_target,
                            "preferred_entry_mode": "next_day_breakout_confirmation",
                            "blockers": ["layer_c_bearish_conflict"] if decision == "blocked" else [],
                            "gate_status": {
                                "data": "pass",
                                "execution": "proxy_only",
                                "structural": "fail" if decision == "blocked" else "pass",
                                "score": "pass" if decision == "selected" else "near_miss" if decision == "near_miss" else "fail",
                            },
                            "explainability_payload": {
                                "candidate_source": candidate_source,
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


def test_analyze_btst_micro_window_regression_summarizes_closed_and_forward_windows(tmp_path, monkeypatch):
    baseline_dir = tmp_path / "baseline"
    variant_dir = tmp_path / "variant"
    forward_dir = tmp_path / "forward"

    _write_snapshot(
        baseline_dir / "selection_artifacts" / "2026-03-25",
        trade_date="20260325",
        ticker="300111",
        decision="rejected",
        score_target=0.35,
        candidate_source="short_trade_boundary",
    )
    _write_snapshot(
        baseline_dir / "selection_artifacts" / "2026-03-26",
        trade_date="20260326",
        ticker="300222",
        decision="blocked",
        score_target=0.38,
        candidate_source="short_trade_boundary",
    )

    _write_snapshot(
        variant_dir / "selection_artifacts" / "2026-03-25",
        trade_date="20260325",
        ticker="300111",
        decision="near_miss",
        score_target=0.47,
        candidate_source="short_trade_boundary",
    )
    _write_snapshot(
        variant_dir / "selection_artifacts" / "2026-03-26",
        trade_date="20260326",
        ticker="300222",
        decision="near_miss",
        score_target=0.49,
        candidate_source="short_trade_boundary",
    )

    _write_snapshot(
        forward_dir / "selection_artifacts" / "2026-03-27",
        trade_date="20260327",
        ticker="300333",
        decision="selected",
        score_target=0.61,
        candidate_source="short_trade_boundary",
    )

    price_frames = {
        ("300111", "2026-03-25"): pd.DataFrame(
            [
                {"date": "2026-03-25", "open": 10.0, "high": 10.1, "low": 9.9, "close": 10.0},
                {"date": "2026-03-26", "open": 10.1, "high": 10.5, "low": 10.0, "close": 10.2},
                {"date": "2026-03-27", "open": 10.3, "high": 10.6, "low": 10.1, "close": 10.4},
            ]
        ),
        ("300222", "2026-03-26"): pd.DataFrame(
            [
                {"date": "2026-03-26", "open": 20.0, "high": 20.2, "low": 19.8, "close": 20.0},
                {"date": "2026-03-27", "open": 20.1, "high": 20.8, "low": 20.0, "close": 20.1},
                {"date": "2026-03-30", "open": 20.2, "high": 20.4, "low": 19.9, "close": 20.2},
            ]
        ),
        ("300333", "2026-03-27"): pd.DataFrame(
            [
                {"date": "2026-03-27", "open": 30.0, "high": 30.2, "low": 29.8, "close": 30.0},
                {"date": "2026-03-30", "open": 30.3, "high": 31.0, "low": 30.0, "close": 30.5},
            ]
        ),
    }

    def fake_get_price_data(ticker: str, start_date: str, end_date: str):
        frame = price_frames.get((ticker, start_date))
        if frame is None:
            raise AssertionError(f"Unexpected request: {(ticker, start_date, end_date)}")
        return frame.assign(date=lambda data: pd.to_datetime(data["date"]).dt.normalize()).set_index("date")

    monkeypatch.setattr("scripts.btst_analysis_utils.get_price_data", fake_get_price_data)

    analysis = analyze_btst_micro_window_regression(
        baseline_dir,
        variant_reports={"catalyst_floor_zero": str(variant_dir)},
        forward_reports={"forward_20260327": str(forward_dir)},
        next_high_hit_threshold=0.02,
    )

    baseline = analysis["baseline"]
    variant = analysis["variants"][0]
    forward = analysis["forward_reports"][0]
    comparison = analysis["comparisons"][0]

    assert baseline["decision_counts"] == {"rejected": 1, "blocked": 1}
    assert baseline["false_negative_proxy_summary"]["count"] == 2
    assert baseline["surface_summaries"]["tradeable"]["total_count"] == 0
    assert variant["decision_counts"] == {"near_miss": 2}
    assert variant["surface_summaries"]["tradeable"]["total_count"] == 2
    assert variant["surface_summaries"]["tradeable"]["closed_cycle_count"] == 2
    assert variant["surface_summaries"]["tradeable"]["next_high_hit_rate_at_threshold"] == 1.0
    assert comparison["tradeable_surface_delta"]["total_count"] == 2
    assert comparison["guardrail_status"] == "passes_closed_tradeable_guardrails"
    assert "从 0 提升到 2" in comparison["comparison_note"]
    assert forward["cycle_status_counts"] == {"t1_only": 1}
    assert forward["surface_summaries"]["tradeable"]["closed_cycle_count"] == 0


def test_analyze_btst_micro_window_regression_tracks_missing_next_day_data(tmp_path, monkeypatch):
    baseline_dir = tmp_path / "baseline"
    _write_snapshot(
        baseline_dir / "selection_artifacts" / "2026-03-28",
        trade_date="20260328",
        ticker="300555",
        decision="rejected",
        score_target=0.32,
        candidate_source="short_trade_boundary",
    )

    monkeypatch.setattr("scripts.btst_analysis_utils.get_price_data", lambda *args, **kwargs: pd.DataFrame())

    analysis = analyze_btst_micro_window_regression(baseline_dir)
    baseline = analysis["baseline"]

    assert baseline["cycle_status_counts"] == {"missing_next_day": 1}
    assert baseline["data_status_counts"] == {"missing_price_frame": 1}
    assert baseline["false_negative_proxy_summary"]["count"] == 0
    assert baseline["surface_summaries"]["all"]["next_day_available_count"] == 0