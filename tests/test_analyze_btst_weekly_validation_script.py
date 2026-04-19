from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

import scripts.analyze_btst_weekly_validation as weekly_validation


def _write_snapshot(day_dir: Path, *, trade_date: str, ticker: str, decision: str, score_target: float, candidate_source: str = "short_trade_boundary") -> None:
    day_dir.mkdir(parents=True)
    payload = {
        "trade_date": trade_date,
        "target_mode": "short_trade_only",
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
                    "blockers": [],
                    "gate_status": {
                        "data": "pass",
                        "execution": "pass",
                        "structural": "pass",
                        "score": "pass" if decision == "selected" else "near_miss",
                    },
                    "explainability_payload": {
                        "candidate_source": candidate_source,
                    },
                },
            }
        },
    }
    (day_dir / "selection_snapshot.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_complete_report(report_dir: Path, *, trade_date: str, ticker: str, decision: str, score_target: float) -> None:
    normalized_trade_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
    _write_snapshot(
        report_dir / "selection_artifacts" / normalized_trade_date,
        trade_date=trade_date,
        ticker=ticker,
        decision=decision,
        score_target=score_target,
    )
    (report_dir / "session_summary.json").write_text(json.dumps({"plan_generation": {"selection_target": "short_trade_only"}}, ensure_ascii=False) + "\n", encoding="utf-8")


def test_analyze_btst_weekly_validation_picks_latest_complete_reports_and_summarizes_week(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    older_day_one = reports_root / "paper_trading_20260413_20260413_live_short_trade_only_zz_older_complete"
    newer_day_one = reports_root / "paper_trading_20260413_20260413_live_short_trade_only_20260414_predict_v2"
    day_two = reports_root / "paper_trading_20260414_20260414_live_short_trade_only_20260415"
    incomplete_day_three = reports_root / "paper_trading_20260415_20260415_live_m2_7_short_trade_only_20260416"
    complete_day_three = reports_root / "paper_trading_20260415_20260415_live_m2_7_short_trade_only_20260416_llm_full"

    _write_complete_report(older_day_one, trade_date="20260413", ticker="300110", decision="selected", score_target=0.59)
    _write_complete_report(newer_day_one, trade_date="20260413", ticker="300111", decision="selected", score_target=0.61)
    _write_snapshot(
        newer_day_one / "selection_artifacts" / "2026-04-12",
        trade_date="20260412",
        ticker="399999",
        decision="selected",
        score_target=0.99,
    )
    _write_complete_report(day_two, trade_date="20260414", ticker="300222", decision="near_miss", score_target=0.49)
    _write_complete_report(complete_day_three, trade_date="20260415", ticker="300333", decision="selected", score_target=0.63)
    incomplete_day_three.mkdir(parents=True)
    os.utime(older_day_one, (1_000_000_000, 1_000_000_000))
    os.utime(newer_day_one, (1_000_000_100, 1_000_000_100))

    price_frames = {
        ("300111", "2026-04-13"): pd.DataFrame(
            [
                {"date": "2026-04-13", "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0},
                {"date": "2026-04-14", "open": 10.1, "high": 10.5, "low": 10.0, "close": 10.3},
                {"date": "2026-04-15", "open": 10.4, "high": 10.6, "low": 10.2, "close": 10.5},
            ]
        ),
        ("300222", "2026-04-14"): pd.DataFrame(
            [
                {"date": "2026-04-14", "open": 20.0, "high": 20.1, "low": 19.8, "close": 20.0},
                {"date": "2026-04-15", "open": 19.9, "high": 20.5, "low": 19.7, "close": 19.8},
                {"date": "2026-04-16", "open": 19.8, "high": 20.0, "low": 19.4, "close": 19.5},
            ]
        ),
        ("300333", "2026-04-15"): pd.DataFrame(
            [
                {"date": "2026-04-15", "open": 30.0, "high": 30.3, "low": 29.9, "close": 30.0},
                {"date": "2026-04-16", "open": 30.1, "high": 31.0, "low": 30.0, "close": 30.6},
                {"date": "2026-04-17", "open": 30.7, "high": 31.1, "low": 30.5, "close": 30.8},
            ]
        ),
    }

    def fake_get_price_data(ticker: str, start_date: str, end_date: str):
        frame = price_frames.get((ticker, start_date))
        if frame is None:
            raise AssertionError(f"Unexpected request: {(ticker, start_date, end_date)}")
        return frame.assign(date=lambda data: pd.to_datetime(data["date"]).dt.normalize()).set_index("date")

    monkeypatch.setattr("scripts.btst_analysis_utils.get_price_data", fake_get_price_data)

    analysis = weekly_validation.analyze_btst_weekly_validation(
        reports_root,
        start_date="2026-04-13",
        end_date="2026-04-15",
        next_high_hit_threshold=0.02,
    )

    assert analysis["trade_dates"] == ["2026-04-13", "2026-04-14", "2026-04-15"]
    assert analysis["missing_trade_dates"] == []
    assert [row["report_dir_name"] for row in analysis["daily_summaries"]] == [
        newer_day_one.name,
        day_two.name,
        complete_day_three.name,
    ]
    assert analysis["daily_summaries"][0]["decision_counts"] == {"selected": 1}
    assert analysis["daily_summaries"][0]["tradeable_surface"]["total_count"] == 1
    assert analysis["weekly_surface_summaries"]["tradeable"]["total_count"] == 3
    assert analysis["weekly_surface_summaries"]["tradeable"]["closed_cycle_count"] == 3
    assert analysis["weekly_surface_summaries"]["tradeable"]["next_close_positive_rate"] == 0.6667
    assert analysis["weekly_surface_summaries"]["tradeable"]["next_high_hit_rate_at_threshold"] == 1.0
    assert analysis["daily_summaries"][1]["tradeable_surface"]["next_close_positive_rate"] == 0.0

    markdown = weekly_validation.render_btst_weekly_validation_markdown(analysis)
    assert "# BTST Weekly Validation" in markdown
    assert newer_day_one.name in markdown
    assert complete_day_three.name in markdown


def test_analyze_btst_weekly_validation_ignores_weekends_and_requires_session_summary(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    friday_report = reports_root / "paper_trading_20260417_20260417_live_short_trade_only_20260418"
    monday_report = reports_root / "paper_trading_20260420_20260420_live_short_trade_only_20260421"
    incomplete_tuesday_report = reports_root / "paper_trading_20260421_20260421_live_short_trade_only_20260422_partial"

    _write_complete_report(friday_report, trade_date="20260417", ticker="300555", decision="selected", score_target=0.62)
    _write_complete_report(monday_report, trade_date="20260420", ticker="300666", decision="near_miss", score_target=0.48)
    _write_snapshot(
        incomplete_tuesday_report / "selection_artifacts" / "2026-04-21",
        trade_date="20260421",
        ticker="300777",
        decision="selected",
        score_target=0.64,
    )

    price_frames = {
        ("300555", "2026-04-17"): pd.DataFrame(
            [
                {"date": "2026-04-17", "open": 10.0, "high": 10.1, "low": 9.9, "close": 10.0},
                {"date": "2026-04-20", "open": 10.2, "high": 10.5, "low": 10.0, "close": 10.3},
                {"date": "2026-04-21", "open": 10.3, "high": 10.6, "low": 10.1, "close": 10.4},
            ]
        ),
        ("300666", "2026-04-20"): pd.DataFrame(
            [
                {"date": "2026-04-20", "open": 20.0, "high": 20.1, "low": 19.9, "close": 20.0},
                {"date": "2026-04-21", "open": 20.1, "high": 20.6, "low": 19.8, "close": 20.2},
                {"date": "2026-04-22", "open": 20.2, "high": 20.4, "low": 20.0, "close": 20.1},
            ]
        ),
    }

    def fake_get_price_data(ticker: str, start_date: str, end_date: str):
        frame = price_frames.get((ticker, start_date))
        if frame is None:
            raise AssertionError(f"Unexpected request: {(ticker, start_date, end_date)}")
        return frame.assign(date=lambda data: pd.to_datetime(data["date"]).dt.normalize()).set_index("date")

    monkeypatch.setattr("scripts.btst_analysis_utils.get_price_data", fake_get_price_data)

    analysis = weekly_validation.analyze_btst_weekly_validation(
        reports_root,
        start_date="2026-04-17",
        end_date="2026-04-21",
        next_high_hit_threshold=0.02,
    )

    assert analysis["trade_dates"] == ["2026-04-17", "2026-04-20", "2026-04-21"]
    assert [row["trade_date"] for row in analysis["daily_summaries"]] == ["2026-04-17", "2026-04-20"]
    assert analysis["missing_trade_dates"] == ["2026-04-21"]
