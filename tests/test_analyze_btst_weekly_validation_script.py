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


def _write_complete_report_with_targets(report_dir: Path, *, trade_date: str, targets: list[dict[str, object]]) -> None:
    normalized_trade_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
    selection_root = report_dir / "selection_artifacts" / normalized_trade_date
    selection_root.mkdir(parents=True)
    selection_targets = {}
    for target in targets:
        ticker = str(target["ticker"])
        decision = str(target["decision"])
        score_target = float(target["score_target"])
        candidate_source = str(target.get("candidate_source") or "short_trade_boundary")
        selection_targets[ticker] = {
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
    payload = {
        "trade_date": trade_date,
        "target_mode": "short_trade_only",
        "selection_targets": selection_targets,
    }
    (selection_root / "selection_snapshot.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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


def test_analyze_btst_weekly_validation_surfaces_5d_payoff_gap_and_runner_false_negative_sources(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    day_one = reports_root / "paper_trading_20260413_20260413_live_short_trade_only_20260414"
    day_two = reports_root / "paper_trading_20260414_20260414_live_short_trade_only_20260415"
    day_three = reports_root / "paper_trading_20260415_20260415_live_short_trade_only_20260416"

    _write_complete_report_with_targets(
        day_one,
        trade_date="20260413",
        targets=[
            {"ticker": "300111", "decision": "selected", "score_target": 0.63, "candidate_source": "short_trade_boundary"},
            {"ticker": "300222", "decision": "near_miss", "score_target": 0.48, "candidate_source": "catalyst_theme"},
        ],
    )
    _write_complete_report_with_targets(
        day_two,
        trade_date="20260414",
        targets=[
            {"ticker": "300333", "decision": "selected", "score_target": 0.61, "candidate_source": "layer_c_watchlist"},
            {"ticker": "300444", "decision": "blocked", "score_target": 0.29, "candidate_source": "watchlist_filter_diagnostics"},
        ],
    )
    _write_complete_report_with_targets(
        day_three,
        trade_date="20260415",
        targets=[
            {"ticker": "300555", "decision": "rejected", "score_target": 0.21, "candidate_source": "watchlist_filter_diagnostics"},
            {"ticker": "300666", "decision": "near_miss", "score_target": 0.46, "candidate_source": "catalyst_theme"},
        ],
    )

    price_frames = {
        ("300111", "2026-04-13"): pd.DataFrame(
            [
                {"date": "2026-04-13", "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0},
                {"date": "2026-04-14", "open": 10.1, "high": 10.4, "low": 10.0, "close": 10.2},
                {"date": "2026-04-15", "open": 10.2, "high": 10.8, "low": 10.1, "close": 10.4},
                {"date": "2026-04-16", "open": 10.4, "high": 11.2, "low": 10.3, "close": 10.7},
                {"date": "2026-04-17", "open": 10.7, "high": 11.3, "low": 10.6, "close": 10.9},
                {"date": "2026-04-20", "open": 10.9, "high": 11.4, "low": 10.8, "close": 11.0},
            ]
        ),
        ("300222", "2026-04-13"): pd.DataFrame(
            [
                {"date": "2026-04-13", "open": 10.0, "high": 10.1, "low": 9.9, "close": 10.0},
                {"date": "2026-04-14", "open": 10.0, "high": 10.3, "low": 9.9, "close": 10.1},
                {"date": "2026-04-15", "open": 10.2, "high": 11.8, "low": 10.1, "close": 11.1},
                {"date": "2026-04-16", "open": 11.1, "high": 11.7, "low": 10.9, "close": 11.3},
                {"date": "2026-04-17", "open": 11.3, "high": 11.6, "low": 11.1, "close": 11.4},
                {"date": "2026-04-20", "open": 11.4, "high": 11.5, "low": 11.2, "close": 11.3},
            ]
        ),
        ("300333", "2026-04-14"): pd.DataFrame(
            [
                {"date": "2026-04-14", "open": 20.0, "high": 20.2, "low": 19.9, "close": 20.0},
                {"date": "2026-04-15", "open": 20.1, "high": 20.5, "low": 20.0, "close": 20.3},
                {"date": "2026-04-16", "open": 20.3, "high": 21.1, "low": 20.2, "close": 20.7},
                {"date": "2026-04-17", "open": 20.7, "high": 22.0, "low": 20.6, "close": 21.2},
                {"date": "2026-04-20", "open": 21.2, "high": 22.4, "low": 21.0, "close": 21.5},
                {"date": "2026-04-21", "open": 21.5, "high": 23.3, "low": 21.4, "close": 22.1},
            ]
        ),
        ("300444", "2026-04-14"): pd.DataFrame(
            [
                {"date": "2026-04-14", "open": 8.0, "high": 8.1, "low": 7.9, "close": 8.0},
                {"date": "2026-04-15", "open": 8.0, "high": 8.2, "low": 7.9, "close": 8.1},
                {"date": "2026-04-16", "open": 8.2, "high": 8.4, "low": 8.0, "close": 8.3},
                {"date": "2026-04-17", "open": 8.3, "high": 9.4, "low": 8.2, "close": 9.0},
                {"date": "2026-04-20", "open": 9.0, "high": 9.6, "low": 8.9, "close": 9.3},
                {"date": "2026-04-21", "open": 9.3, "high": 9.5, "low": 9.1, "close": 9.2},
            ]
        ),
        ("300555", "2026-04-15"): pd.DataFrame(
            [
                {"date": "2026-04-15", "open": 12.0, "high": 12.1, "low": 11.9, "close": 12.0},
                {"date": "2026-04-16", "open": 12.0, "high": 12.3, "low": 11.9, "close": 12.1},
                {"date": "2026-04-17", "open": 12.1, "high": 12.4, "low": 12.0, "close": 12.2},
                {"date": "2026-04-20", "open": 12.2, "high": 13.9, "low": 12.1, "close": 13.5},
                {"date": "2026-04-21", "open": 13.5, "high": 14.2, "low": 13.4, "close": 13.9},
                {"date": "2026-04-22", "open": 13.9, "high": 14.0, "low": 13.7, "close": 13.8},
            ]
        ),
        ("300666", "2026-04-15"): pd.DataFrame(
            [
                {"date": "2026-04-15", "open": 15.0, "high": 15.1, "low": 14.9, "close": 15.0},
                {"date": "2026-04-16", "open": 15.0, "high": 15.3, "low": 14.9, "close": 15.2},
                {"date": "2026-04-17", "open": 15.2, "high": 17.5, "low": 15.1, "close": 16.6},
                {"date": "2026-04-20", "open": 16.6, "high": 17.4, "low": 16.3, "close": 16.9},
                {"date": "2026-04-21", "open": 16.9, "high": 17.3, "low": 16.7, "close": 16.8},
                {"date": "2026-04-22", "open": 16.8, "high": 17.1, "low": 16.6, "close": 16.7},
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

    assert analysis["weekly_surface_summaries"]["selected"]["max_future_high_return_2_5d_hit_rate_at_15pct"] == 0.5
    assert analysis["weekly_surface_summaries"]["near_miss"]["max_future_high_return_2_5d_hit_rate_at_15pct"] == 1.0
    assert analysis["weekly_surface_summaries"]["blocked_rejected"]["max_future_high_return_2_5d_hit_rate_at_15pct"] == 1.0
    assert analysis["runner_false_negative_summary"]["count"] == 2
    assert analysis["runner_false_negative_summary"]["candidate_source_counts"] == {"watchlist_filter_diagnostics": 2}
    assert analysis["selected_candidate_source_breakdown"][0]["candidate_source"] == "layer_c_watchlist"
    assert analysis["selected_candidate_source_breakdown"][0]["max_future_high_return_2_5d_hit_rate_at_15pct"] == 1.0
    assert "shadow" in analysis["recommendation"].lower()

    markdown = weekly_validation.render_btst_weekly_validation_markdown(analysis)
    assert "## 5D / +15% Objective Focus" in markdown
    assert "watchlist_filter_diagnostics" in markdown
    assert "shadow-only" in markdown


def test_analyze_btst_weekly_validation_builds_selected_payoff_drag_exclusion_shadow(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    day_one = reports_root / "paper_trading_20260413_20260413_live_short_trade_only_20260414"
    day_two = reports_root / "paper_trading_20260414_20260414_live_short_trade_only_20260415"
    day_three = reports_root / "paper_trading_20260415_20260415_live_short_trade_only_20260416"

    _write_complete_report_with_targets(
        day_one,
        trade_date="20260413",
        targets=[
            {"ticker": "300101", "decision": "selected", "score_target": 0.64, "candidate_source": "short_trade_boundary"},
            {"ticker": "300201", "decision": "selected", "score_target": 0.62, "candidate_source": "catalyst_theme"},
        ],
    )
    _write_complete_report_with_targets(
        day_two,
        trade_date="20260414",
        targets=[
            {"ticker": "300102", "decision": "selected", "score_target": 0.63, "candidate_source": "layer_c_watchlist"},
            {"ticker": "300202", "decision": "selected", "score_target": 0.61, "candidate_source": "catalyst_theme"},
        ],
    )
    _write_complete_report_with_targets(
        day_three,
        trade_date="20260415",
        targets=[
            {"ticker": "300103", "decision": "selected", "score_target": 0.60, "candidate_source": "short_trade_boundary"},
            {"ticker": "300104", "decision": "selected", "score_target": 0.59, "candidate_source": "layer_c_watchlist"},
        ],
    )

    price_frames = {
        ("300101", "2026-04-13"): pd.DataFrame(
            [
                {"date": "2026-04-13", "open": 10.0, "high": 10.1, "low": 9.9, "close": 10.0},
                {"date": "2026-04-14", "open": 10.0, "high": 10.4, "low": 9.9, "close": 10.2},
                {"date": "2026-04-15", "open": 10.2, "high": 10.9, "low": 10.1, "close": 10.4},
                {"date": "2026-04-16", "open": 10.4, "high": 11.2, "low": 10.2, "close": 10.5},
                {"date": "2026-04-17", "open": 10.5, "high": 11.3, "low": 10.4, "close": 10.7},
                {"date": "2026-04-20", "open": 10.7, "high": 11.4, "low": 10.6, "close": 10.8},
            ]
        ),
        ("300102", "2026-04-14"): pd.DataFrame(
            [
                {"date": "2026-04-14", "open": 12.0, "high": 12.1, "low": 11.9, "close": 12.0},
                {"date": "2026-04-15", "open": 12.0, "high": 12.4, "low": 11.9, "close": 12.2},
                {"date": "2026-04-16", "open": 12.2, "high": 12.8, "low": 12.1, "close": 12.3},
                {"date": "2026-04-17", "open": 12.3, "high": 13.1, "low": 12.2, "close": 12.4},
                {"date": "2026-04-20", "open": 12.4, "high": 13.3, "low": 12.2, "close": 12.5},
                {"date": "2026-04-21", "open": 12.5, "high": 13.4, "low": 12.4, "close": 12.6},
            ]
        ),
        ("300103", "2026-04-15"): pd.DataFrame(
            [
                {"date": "2026-04-15", "open": 14.0, "high": 14.1, "low": 13.9, "close": 14.0},
                {"date": "2026-04-16", "open": 14.0, "high": 14.3, "low": 13.8, "close": 14.1},
                {"date": "2026-04-17", "open": 14.1, "high": 14.8, "low": 14.0, "close": 14.2},
                {"date": "2026-04-20", "open": 14.2, "high": 15.1, "low": 14.1, "close": 14.3},
                {"date": "2026-04-21", "open": 14.3, "high": 15.5, "low": 14.2, "close": 14.4},
                {"date": "2026-04-22", "open": 14.4, "high": 15.8, "low": 14.3, "close": 14.5},
            ]
        ),
        ("300104", "2026-04-15"): pd.DataFrame(
            [
                {"date": "2026-04-15", "open": 16.0, "high": 16.1, "low": 15.9, "close": 16.0},
                {"date": "2026-04-16", "open": 16.0, "high": 16.2, "low": 15.8, "close": 16.0},
                {"date": "2026-04-17", "open": 16.0, "high": 16.8, "low": 15.9, "close": 16.2},
                {"date": "2026-04-20", "open": 16.2, "high": 17.4, "low": 16.1, "close": 16.4},
                {"date": "2026-04-21", "open": 16.4, "high": 18.2, "low": 16.2, "close": 16.5},
                {"date": "2026-04-22", "open": 16.5, "high": 18.3, "low": 16.4, "close": 16.6},
            ]
        ),
        ("300201", "2026-04-13"): pd.DataFrame(
            [
                {"date": "2026-04-13", "open": 20.0, "high": 20.2, "low": 19.9, "close": 20.0},
                {"date": "2026-04-14", "open": 20.1, "high": 20.8, "low": 20.0, "close": 20.5},
                {"date": "2026-04-15", "open": 20.5, "high": 22.4, "low": 20.4, "close": 21.3},
                {"date": "2026-04-16", "open": 21.3, "high": 22.9, "low": 21.1, "close": 21.8},
                {"date": "2026-04-17", "open": 21.8, "high": 23.3, "low": 21.6, "close": 22.0},
                {"date": "2026-04-20", "open": 22.0, "high": 23.5, "low": 21.8, "close": 22.2},
            ]
        ),
        ("300202", "2026-04-14"): pd.DataFrame(
            [
                {"date": "2026-04-14", "open": 18.0, "high": 18.1, "low": 17.9, "close": 18.0},
                {"date": "2026-04-15", "open": 18.0, "high": 18.5, "low": 17.9, "close": 18.3},
                {"date": "2026-04-16", "open": 18.3, "high": 20.9, "low": 18.2, "close": 19.6},
                {"date": "2026-04-17", "open": 19.6, "high": 21.2, "low": 19.4, "close": 20.0},
                {"date": "2026-04-20", "open": 20.0, "high": 21.5, "low": 19.8, "close": 20.2},
                {"date": "2026-04-21", "open": 20.2, "high": 21.7, "low": 20.0, "close": 20.4},
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

    assert analysis["selected_payoff_drag_candidate_sources"] == ["layer_c_watchlist", "short_trade_boundary"]
    scenario = analysis["selected_shadow_scenarios"][0]
    assert scenario["scenario_id"] == "exclude_payoff_drag_sources"
    assert scenario["excluded_candidate_sources"] == ["layer_c_watchlist", "short_trade_boundary"]
    assert scenario["removed_count"] == 4
    assert scenario["remaining_count"] == 2
    assert scenario["surface_summary"]["max_future_high_return_2_5d_hit_rate_at_15pct"] == 1.0

    markdown = weekly_validation.render_btst_weekly_validation_markdown(analysis)
    assert "Selected Shadow Scenarios" in markdown
    assert "exclude_payoff_drag_sources" in markdown
    assert "short_trade_boundary" in markdown
