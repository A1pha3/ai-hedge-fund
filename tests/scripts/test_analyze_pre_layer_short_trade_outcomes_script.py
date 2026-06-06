from __future__ import annotations

import json

import pandas as pd
import pytest

from scripts.analyze_pre_layer_short_trade_outcomes import _compute_walk_forward_validation, analyze_pre_layer_short_trade_outcomes, render_pre_layer_short_trade_outcomes_markdown


def test_analyze_pre_layer_short_trade_outcomes_summarizes_next_day_returns(tmp_path, monkeypatch):
    report_dir = tmp_path / "report"
    day1 = report_dir / "selection_artifacts" / "2026-03-25"
    day2 = report_dir / "selection_artifacts" / "2026-03-26"
    day1.mkdir(parents=True)
    day2.mkdir(parents=True)

    (day1 / "selection_target_replay_input.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-25",
                "supplemental_short_trade_entries": [
                    {
                        "ticker": "300724",
                        "candidate_source": "short_trade_boundary",
                        "short_trade_boundary_metrics": {
                            "candidate_score": 0.31,
                            "breakout_freshness": 0.42,
                            "trend_acceleration": 0.51,
                            "volume_expansion_quality": 0.22,
                            "catalyst_freshness": 0.19,
                        },
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (day2 / "selection_target_replay_input.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-26",
                "supplemental_short_trade_entries": [
                    {
                        "ticker": "300111",
                        "candidate_source": "short_trade_boundary",
                        "short_trade_boundary_metrics": {
                            "candidate_score": 0.26,
                            "breakout_freshness": 0.25,
                            "trend_acceleration": 0.24,
                            "volume_expansion_quality": 0.15,
                            "catalyst_freshness": 0.12,
                        },
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    def fake_get_price_data(ticker: str, start_date: str, end_date: str):
        if ticker == "300724":
            return pd.DataFrame(
                [
                    {"date": "2026-03-25", "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000},
                    {"date": "2026-03-26", "open": 10.1, "high": 10.6, "low": 10.0, "close": 10.3, "volume": 1200},
                ]
            ).assign(date=lambda frame: pd.to_datetime(frame["date"]).dt.normalize()).set_index("date")
        if ticker == "300111":
            return pd.DataFrame(
                [
                    {"date": "2026-03-26", "open": 8.0, "high": 8.1, "low": 7.8, "close": 8.0, "volume": 900},
                    {"date": "2026-03-27", "open": 7.9, "high": 8.0, "low": 7.5, "close": 7.7, "volume": 950},
                ]
            ).assign(date=lambda frame: pd.to_datetime(frame["date"]).dt.normalize()).set_index("date")
        raise AssertionError(f"Unexpected ticker: {ticker}")

    monkeypatch.setattr("scripts.analyze_pre_layer_short_trade_outcomes.get_price_data", fake_get_price_data)

    analysis = analyze_pre_layer_short_trade_outcomes(report_dir, candidate_sources={"short_trade_boundary"}, next_high_hit_threshold=0.02)

    assert analysis["candidate_count"] == 2
    assert analysis["data_status_counts"] == {"ok": 2}
    assert analysis["candidate_source_counts"] == {"short_trade_boundary": 2}
    assert analysis["next_high_hit_rate_at_threshold"] == 0.5
    assert analysis["next_close_positive_rate"] == 0.5
    assert analysis["source_breakdown"]["short_trade_boundary"]["count"] == 2
    assert analysis["top_cases"][0]["ticker"] == "300724"


def test_analyze_pre_layer_short_trade_outcomes_tracks_missing_price_data(tmp_path, monkeypatch):
    report_dir = tmp_path / "report"
    day1 = report_dir / "selection_artifacts" / "2026-03-25"
    day1.mkdir(parents=True)
    (day1 / "selection_target_replay_input.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-25",
                "supplemental_short_trade_entries": [
                    {
                        "ticker": "300724",
                        "candidate_source": "layer_b_boundary",
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("scripts.analyze_pre_layer_short_trade_outcomes.get_price_data", lambda *args, **kwargs: pd.DataFrame())

    analysis = analyze_pre_layer_short_trade_outcomes(report_dir, candidate_sources={"layer_b_boundary"})

    assert analysis["candidate_count"] == 1
    assert analysis["data_status_counts"] == {"missing_price_frame": 1}
    assert analysis["next_high_hit_rate_at_threshold"] is None
    assert analysis["next_close_positive_rate"] is None


def test_analyze_pre_layer_short_trade_outcomes_treats_nan_price_bars_as_incomplete(tmp_path, monkeypatch):
    report_dir = tmp_path / "report"
    day1 = report_dir / "selection_artifacts" / "2026-03-25"
    day1.mkdir(parents=True)
    (day1 / "selection_target_replay_input.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-25",
                "supplemental_short_trade_entries": [
                    {
                        "ticker": "300724",
                        "candidate_source": "short_trade_boundary",
                        "short_trade_boundary_metrics": {"candidate_score": 0.31},
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    def fake_get_price_data(ticker: str, start_date: str, end_date: str):
        if ticker != "300724":
            raise AssertionError(f"Unexpected ticker: {ticker}")
        return pd.DataFrame(
            [
                {"date": "2026-03-25", "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000},
                {"date": "2026-03-26", "open": 10.1, "high": float("nan"), "low": 10.0, "close": 10.3, "volume": 1200},
            ]
        ).assign(date=lambda frame: pd.to_datetime(frame["date"]).dt.normalize()).set_index("date")

    monkeypatch.setattr("scripts.analyze_pre_layer_short_trade_outcomes.get_price_data", fake_get_price_data)

    analysis = analyze_pre_layer_short_trade_outcomes(report_dir, candidate_sources={"short_trade_boundary"})

    assert analysis["data_status_counts"] == {"incomplete_price_bar": 1}
    assert analysis["rows"][0]["data_status"] == "incomplete_price_bar"


def test_render_pre_layer_short_trade_outcomes_markdown_handles_missing_return_fields() -> None:
    markdown = render_pre_layer_short_trade_outcomes_markdown(
        {
            "report_dir": "demo",
            "candidate_sources_filter": ["catalyst_theme"],
            "tickers_filter": [],
            "candidate_count": 1,
            "data_status_counts": {"missing_next_trade_day_bar": 1},
            "candidate_source_counts": {"catalyst_theme": 1},
            "next_open_return_distribution": {"count": 0, "min": None, "max": None, "mean": None},
            "next_high_return_distribution": {"count": 0, "min": None, "max": None, "mean": None},
            "next_close_return_distribution": {"count": 0, "min": None, "max": None, "mean": None},
            "next_high_hit_rate_at_threshold": None,
            "next_close_positive_rate": None,
            "source_breakdown": {},
            "top_cases": [
                {
                    "trade_date": "2026-04-08",
                    "ticker": "001309",
                    "candidate_source": "catalyst_theme",
                    "candidate_score": 0.4646,
                    "data_status": "missing_next_trade_day_bar",
                }
            ],
            "recommendation": "wait",
        }
    )

    assert "data_status=missing_next_trade_day_bar" in markdown
    assert "next_high_return=None" in markdown


def test_analyze_pre_layer_short_trade_outcomes_filters_tickers(tmp_path, monkeypatch):
    report_dir = tmp_path / "report"
    day1 = report_dir / "selection_artifacts" / "2026-03-26"
    day1.mkdir(parents=True)
    (day1 / "selection_target_replay_input.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-26",
                "supplemental_short_trade_entries": [
                    {
                        "ticker": "300383",
                        "candidate_source": "short_trade_boundary",
                        "short_trade_boundary_metrics": {
                            "candidate_score": 0.25,
                        },
                    },
                    {
                        "ticker": "600821",
                        "candidate_source": "short_trade_boundary",
                        "short_trade_boundary_metrics": {
                            "candidate_score": 0.27,
                        },
                    },
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    def fake_get_price_data(ticker: str, start_date: str, end_date: str):
        if ticker != "300383":
            raise AssertionError(f"Unexpected ticker: {ticker}")
        return pd.DataFrame(
            [
                {"date": "2026-03-26", "open": 12.0, "high": 12.3, "low": 11.9, "close": 12.0, "volume": 1000},
                {"date": "2026-03-27", "open": 12.1, "high": 12.7, "low": 12.0, "close": 12.5, "volume": 1300},
            ]
        ).assign(date=lambda frame: pd.to_datetime(frame["date"]).dt.normalize()).set_index("date")

    monkeypatch.setattr("scripts.analyze_pre_layer_short_trade_outcomes.get_price_data", fake_get_price_data)

    analysis = analyze_pre_layer_short_trade_outcomes(
        report_dir,
        candidate_sources={"short_trade_boundary"},
        tickers={"300383"},
        next_high_hit_threshold=0.02,
    )

    assert analysis["tickers_filter"] == ["300383"]
    assert analysis["candidate_count"] == 1
    assert analysis["candidate_source_counts"] == {"short_trade_boundary": 1}
    assert analysis["rows"][0]["ticker"] == "300383"
    assert analysis["top_cases"][0]["ticker"] == "300383"


def test_analyze_pre_layer_short_trade_outcomes_reads_catalyst_theme_metrics(tmp_path, monkeypatch):
    report_dir = tmp_path / "report"
    day1 = report_dir / "selection_artifacts" / "2026-04-08"
    day1.mkdir(parents=True)
    (day1 / "selection_target_replay_input.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-04-08",
                "supplemental_short_trade_entries": [
                    {
                        "ticker": "001309",
                        "candidate_source": "catalyst_theme",
                        "catalyst_theme_metrics": {
                            "candidate_score": 0.46,
                            "breakout_freshness": 0.44,
                            "trend_acceleration": 0.79,
                            "volume_expansion_quality": 0.28,
                            "catalyst_freshness": 0.10,
                        },
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("scripts.analyze_pre_layer_short_trade_outcomes.get_price_data", lambda *args, **kwargs: pd.DataFrame())

    analysis = analyze_pre_layer_short_trade_outcomes(report_dir, candidate_sources={"catalyst_theme"})

    assert analysis["candidate_count"] == 1
    assert analysis["rows"][0]["candidate_score"] == 0.46
    assert analysis["rows"][0]["breakout_freshness"] == 0.44
    assert analysis["rows"][0]["trend_acceleration"] == 0.79
    assert analysis["rows"][0]["catalyst_freshness"] == 0.1


def test_analyze_pre_layer_short_trade_outcomes_surfaces_forward_labels(tmp_path, monkeypatch):
    report_dir = tmp_path / "report"
    day1 = report_dir / "selection_artifacts" / "2026-03-25"
    day1.mkdir(parents=True)
    (day1 / "selection_target_replay_input.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-25",
                "supplemental_short_trade_entries": [
                    {
                        "ticker": "300724",
                        "candidate_source": "short_trade_boundary",
                        "short_trade_boundary_metrics": {"candidate_score": 0.31},
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    def fake_get_price_data(ticker: str, start_date: str, end_date: str):
        if ticker != "300724":
            raise AssertionError(f"Unexpected ticker: {ticker}")
        rows = [
            {"date": "2026-03-25", "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000},
            {"date": "2026-03-26", "open": 10.1, "high": 10.45, "low": 10.0, "close": 10.02, "volume": 1200},
            {"date": "2026-03-27", "open": 10.2, "high": 10.70, "low": 10.1, "close": 10.24, "volume": 1300},
            {"date": "2026-03-28", "open": 10.3, "high": 10.92, "low": 10.2, "close": 10.22, "volume": 1400},
            {"date": "2026-03-29", "open": 10.4, "high": 11.05, "low": 10.2, "close": 10.30, "volume": 1400},
            {"date": "2026-03-30", "open": 10.5, "high": 11.40, "low": 10.3, "close": 10.28, "volume": 1500},
            {"date": "2026-03-31", "open": 10.7, "high": 11.85, "low": 10.5, "close": 10.44, "volume": 1600},
            {"date": "2026-04-01", "open": 10.8, "high": 12.05, "low": 10.6, "close": 10.62, "volume": 1700},
            {"date": "2026-04-02", "open": 10.9, "high": 12.25, "low": 10.8, "close": 10.80, "volume": 1800},
            {"date": "2026-04-03", "open": 10.8, "high": 12.10, "low": 10.6, "close": 10.68, "volume": 1700},
        ]
        return pd.DataFrame(rows).assign(date=lambda frame: pd.to_datetime(frame["date"]).dt.normalize()).set_index("date")

    monkeypatch.setattr("scripts.analyze_pre_layer_short_trade_outcomes.get_price_data", fake_get_price_data)

    analysis = analyze_pre_layer_short_trade_outcomes(report_dir, candidate_sources={"short_trade_boundary"})

    assert analysis["fast_confirm_rate"] == 1.0
    assert analysis["retention_rate"] == 1.0
    assert analysis["tail_20_rate"] == 1.0
    assert analysis["rows"][0]["label_fast_confirm"] is True
    assert analysis["rows"][0]["label_retention"] is True
    assert analysis["rows"][0]["label_tail_20"] is True
    assert analysis["rows"][0]["max_high_return_t2_t9"] == pytest.approx((12.25 / 10.1) - 1.0)


def test_analyze_pre_layer_short_trade_outcomes_breaks_down_results_by_regime_gate(tmp_path, monkeypatch):
    report_dir = tmp_path / "report"
    day1 = report_dir / "selection_artifacts" / "2026-03-25"
    day1.mkdir(parents=True)
    (day1 / "selection_target_replay_input.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-25",
                "supplemental_short_trade_entries": [
                    {
                        "ticker": "300724",
                        "candidate_source": "short_trade_boundary",
                        "historical_prior": {"btst_regime_gate": "aggressive_trade"},
                        "short_trade_boundary_metrics": {"candidate_score": 0.31},
                    },
                    {
                        "ticker": "300111",
                        "candidate_source": "short_trade_boundary",
                        "historical_prior": {"btst_regime_gate": "normal_trade"},
                        "short_trade_boundary_metrics": {"candidate_score": 0.26},
                    },
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    def fake_get_price_data(ticker: str, start_date: str, end_date: str):
        if ticker == "300724":
            rows = [
                {"date": "2026-03-25", "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000},
                {"date": "2026-03-26", "open": 10.1, "high": 10.6, "low": 10.0, "close": 10.3, "volume": 1200},
                {"date": "2026-03-27", "open": 10.2, "high": 10.8, "low": 10.1, "close": 10.4, "volume": 1300},
            ]
            return pd.DataFrame(rows).assign(date=lambda frame: pd.to_datetime(frame["date"]).dt.normalize()).set_index("date")
        if ticker == "300111":
            rows = [
                {"date": "2026-03-25", "open": 8.0, "high": 8.1, "low": 7.9, "close": 8.0, "volume": 900},
                {"date": "2026-03-26", "open": 7.9, "high": 8.0, "low": 7.6, "close": 7.7, "volume": 950},
                {"date": "2026-03-27", "open": 7.8, "high": 7.9, "low": 7.5, "close": 7.6, "volume": 980},
            ]
            return pd.DataFrame(rows).assign(date=lambda frame: pd.to_datetime(frame["date"]).dt.normalize()).set_index("date")
        raise AssertionError(f"Unexpected ticker: {ticker}")

    monkeypatch.setattr("scripts.analyze_pre_layer_short_trade_outcomes.get_price_data", fake_get_price_data)

    analysis = analyze_pre_layer_short_trade_outcomes(report_dir, candidate_sources={"short_trade_boundary"})

    assert analysis["gate_breakdown"]["aggressive_trade"]["count"] == 1
    assert analysis["gate_breakdown"]["aggressive_trade"]["next_close_positive_rate"] == 1.0
    assert analysis["gate_breakdown"]["aggressive_trade"]["fast_confirm_rate"] == 1.0
    assert analysis["gate_breakdown"]["normal_trade"]["count"] == 1
    assert analysis["gate_breakdown"]["normal_trade"]["next_close_positive_rate"] == 0.0
    assert analysis["gate_breakdown"]["normal_trade"]["fast_confirm_rate"] == 0.0


def test_analyze_pre_layer_short_trade_outcomes_breaks_down_results_by_board(tmp_path, monkeypatch):
    report_dir = tmp_path / "report"
    day1 = report_dir / "selection_artifacts" / "2026-03-25"
    day1.mkdir(parents=True)
    (day1 / "selection_target_replay_input.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-25",
                "supplemental_short_trade_entries": [
                    {
                        "ticker": "688001",
                        "candidate_source": "short_trade_boundary",
                        "short_trade_boundary_metrics": {"candidate_score": 0.31},
                    },
                    {
                        "ticker": "300724",
                        "candidate_source": "short_trade_boundary",
                        "short_trade_boundary_metrics": {"candidate_score": 0.26},
                    },
                    {
                        "ticker": "600821",
                        "candidate_source": "short_trade_boundary",
                        "short_trade_boundary_metrics": {"candidate_score": 0.28},
                    },
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    def fake_get_price_data(ticker: str, start_date: str, end_date: str):
        if ticker == "688001":
            rows = [
                {"date": "2026-03-25", "open": 15.0, "high": 15.2, "low": 14.9, "close": 15.0, "volume": 1000},
                {"date": "2026-03-26", "open": 15.1, "high": 15.6, "low": 15.0, "close": 15.4, "volume": 1200},
                {"date": "2026-03-27", "open": 15.2, "high": 15.8, "low": 15.1, "close": 15.5, "volume": 1300},
            ]
            return pd.DataFrame(rows).assign(date=lambda frame: pd.to_datetime(frame["date"]).dt.normalize()).set_index("date")
        if ticker == "300724":
            rows = [
                {"date": "2026-03-25", "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000},
                {"date": "2026-03-26", "open": 10.1, "high": 10.6, "low": 10.0, "close": 10.3, "volume": 1200},
                {"date": "2026-03-27", "open": 10.2, "high": 10.8, "low": 10.1, "close": 10.4, "volume": 1300},
            ]
            return pd.DataFrame(rows).assign(date=lambda frame: pd.to_datetime(frame["date"]).dt.normalize()).set_index("date")
        if ticker == "600821":
            rows = [
                {"date": "2026-03-25", "open": 8.0, "high": 8.1, "low": 7.9, "close": 8.0, "volume": 900},
                {"date": "2026-03-26", "open": 7.9, "high": 8.0, "low": 7.6, "close": 7.7, "volume": 950},
                {"date": "2026-03-27", "open": 7.8, "high": 7.9, "low": 7.5, "close": 7.6, "volume": 980},
            ]
            return pd.DataFrame(rows).assign(date=lambda frame: pd.to_datetime(frame["date"]).dt.normalize()).set_index("date")
        raise AssertionError(f"Unexpected ticker: {ticker}")

    monkeypatch.setattr("scripts.analyze_pre_layer_short_trade_outcomes.get_price_data", fake_get_price_data)

    analysis = analyze_pre_layer_short_trade_outcomes(report_dir, candidate_sources={"short_trade_boundary"})

    assert "board_breakdown" in analysis
    assert "star_market" in analysis["board_breakdown"]
    assert "chinext" in analysis["board_breakdown"]
    assert "main_board" in analysis["board_breakdown"]
    assert analysis["board_breakdown"]["star_market"]["count"] == 1
    assert analysis["board_breakdown"]["chinext"]["count"] == 1
    assert analysis["board_breakdown"]["main_board"]["count"] == 1
    assert analysis["board_breakdown"]["star_market"]["next_close_positive_rate"] == 1.0
    assert analysis["board_breakdown"]["chinext"]["next_close_positive_rate"] == 1.0
    assert analysis["board_breakdown"]["main_board"]["next_close_positive_rate"] == 0.0


def test_analyze_pre_layer_short_trade_outcomes_computes_walk_forward_windows(tmp_path, monkeypatch):
    report_dir = tmp_path / "report"
    
    # Create 4 months of data for walk-forward
    for month_offset in range(4):
        for day_offset in range(3):
            trade_date = pd.Timestamp("2026-01-01") + pd.DateOffset(months=month_offset) + pd.Timedelta(days=day_offset * 7)
            trade_date_str = trade_date.strftime("%Y-%m-%d")
            day_dir = report_dir / "selection_artifacts" / trade_date_str
            day_dir.mkdir(parents=True)
            (day_dir / "selection_target_replay_input.json").write_text(
                json.dumps(
                    {
                        "trade_date": trade_date_str,
                        "supplemental_short_trade_entries": [
                            {
                                "ticker": "300724",
                                "candidate_source": "short_trade_boundary",
                                "short_trade_boundary_metrics": {"candidate_score": 0.3},
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

    def fake_get_price_data(ticker: str, start_date: str, end_date: str):
        if ticker != "300724":
            raise AssertionError(f"Unexpected ticker: {ticker}")
        trade_ts = pd.Timestamp(start_date)
        next_ts = trade_ts + pd.Timedelta(days=1)
        rows = [
            {"date": trade_ts.strftime("%Y-%m-%d"), "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000},
            {"date": next_ts.strftime("%Y-%m-%d"), "open": 10.1, "high": 10.5, "low": 10.0, "close": 10.3, "volume": 1200},
        ]
        return pd.DataFrame(rows).assign(date=lambda frame: pd.to_datetime(frame["date"]).dt.normalize()).set_index("date")

    monkeypatch.setattr("scripts.analyze_pre_layer_short_trade_outcomes.get_price_data", fake_get_price_data)

    analysis = analyze_pre_layer_short_trade_outcomes(
        report_dir, 
        candidate_sources={"short_trade_boundary"},
        walk_forward_preset="standard",
        walk_forward_window_mode="rolling",
    )

    assert "walk_forward" in analysis
    assert analysis["walk_forward"]["preset"] == "standard"
    assert analysis["walk_forward"]["window_mode"] == "rolling"
    assert "summary" in analysis["walk_forward"]
    assert "windows" in analysis["walk_forward"]
    assert isinstance(analysis["walk_forward"]["windows"], list)
    
    if len(analysis["walk_forward"]["windows"]) > 0:
        first_window = analysis["walk_forward"]["windows"][0]
        assert "train_start" in first_window
        assert "train_end" in first_window
        assert "test_start" in first_window
        assert "test_end" in first_window
        assert "count" in first_window
        assert "next_high_return_mean" in first_window
        assert "next_close_return_mean" in first_window
        assert "next_high_hit_rate_at_threshold" in first_window
        assert "next_close_positive_rate" in first_window
        assert "fast_confirm_rate" in first_window
        assert "retention_rate" in first_window
        assert "tail_20_rate" in first_window
    
    summary = analysis["walk_forward"]["summary"]
    assert "window_count" in summary
    assert "candidate_count" in summary
    assert "next_high_return_mean" in summary
    assert "next_close_return_mean" in summary


def test_compute_walk_forward_validation_dedupes_same_theme_same_day_event_rows() -> None:
    walk_forward = _compute_walk_forward_validation(
        candidate_rows=[
            {
                "trade_date": "2026-01-10",
                "ticker": "300001",
                "theme_name": "old_theme",
                "candidate_score": 0.21,
                "data_status": "ok",
                "next_high_return": 0.01,
                "next_close_return": 0.0,
                "label_fast_confirm": False,
                "label_retention": False,
                "label_tail_20": False,
            },
            {
                "trade_date": "2026-03-12",
                "ticker": "300111",
                "theme_name": "storage",
                "candidate_score": 0.42,
                "data_status": "ok",
                "next_high_return": 0.08,
                "next_close_return": 0.04,
                "label_fast_confirm": True,
                "label_retention": True,
                "label_tail_20": False,
            },
            {
                "trade_date": "2026-03-12",
                "ticker": "300222",
                "theme_name": "storage",
                "candidate_score": 0.31,
                "data_status": "ok",
                "next_high_return": 0.02,
                "next_close_return": -0.01,
                "label_fast_confirm": False,
                "label_retention": False,
                "label_tail_20": False,
            },
            {
                "trade_date": "2026-03-13",
                "ticker": "300333",
                "theme_name": "ai_terminal",
                "candidate_score": 0.37,
                "data_status": "ok",
                "next_high_return": 0.06,
                "next_close_return": 0.03,
                "label_fast_confirm": True,
                "label_retention": False,
                "label_tail_20": False,
            },
            {
                "trade_date": "2026-04-10",
                "ticker": "300444",
                "theme_name": "extender",
                "candidate_score": 0.20,
                "data_status": "ok",
                "next_high_return": 0.01,
                "next_close_return": 0.0,
                "label_fast_confirm": False,
                "label_retention": False,
                "label_tail_20": False,
            },
        ],
        preset="standard",
        window_mode="rolling",
        next_high_hit_threshold=0.02,
    )

    assert walk_forward["summary"]["candidate_count"] == 2
    assert walk_forward["summary"]["next_high_return_mean"] == 0.07
    assert walk_forward["summary"]["next_close_return_mean"] == 0.035
    assert walk_forward["windows"][0]["count"] == 2


def test_render_pre_layer_short_trade_outcomes_markdown_includes_board_and_walk_forward_sections():
    markdown = render_pre_layer_short_trade_outcomes_markdown(
        {
            "report_dir": "demo",
            "candidate_sources_filter": ["short_trade_boundary"],
            "tickers_filter": [],
            "candidate_count": 3,
            "data_status_counts": {"ok": 3},
            "candidate_source_counts": {"short_trade_boundary": 3},
            "next_open_return_distribution": {"count": 3, "min": 0.01, "max": 0.05, "mean": 0.03},
            "next_high_return_distribution": {"count": 3, "min": 0.02, "max": 0.06, "mean": 0.04},
            "next_close_return_distribution": {"count": 3, "min": 0.01, "max": 0.03, "mean": 0.02},
            "next_high_hit_rate_at_threshold": 0.67,
            "next_close_positive_rate": 0.67,
            "source_breakdown": {},
            "gate_breakdown": {},
            "board_breakdown": {
                "star_market": {
                    "count": 1,
                    "next_high_return_mean": 0.04,
                    "next_close_return_mean": 0.03,
                    "next_high_hit_rate_at_threshold": 1.0,
                    "next_close_positive_rate": 1.0,
                    "fast_confirm_rate": 0.5,
                    "retention_rate": 0.5,
                    "tail_20_rate": 0.0,
                },
                "chinext": {
                    "count": 1,
                    "next_high_return_mean": 0.05,
                    "next_close_return_mean": 0.03,
                    "next_high_hit_rate_at_threshold": 1.0,
                    "next_close_positive_rate": 1.0,
                    "fast_confirm_rate": 1.0,
                    "retention_rate": 1.0,
                    "tail_20_rate": 1.0,
                },
                "main_board": {
                    "count": 1,
                    "next_high_return_mean": 0.03,
                    "next_close_return_mean": 0.01,
                    "next_high_hit_rate_at_threshold": 0.0,
                    "next_close_positive_rate": 0.0,
                    "fast_confirm_rate": 0.0,
                    "retention_rate": 0.0,
                    "tail_20_rate": 0.0,
                },
            },
            "walk_forward": {
                "preset": "standard",
                "window_mode": "rolling",
                "summary": {
                    "window_count": 2,
                    "candidate_count": 4,
                    "next_high_return_mean": 0.04,
                    "next_close_return_mean": 0.02,
                    "next_high_hit_rate_at_threshold": 0.75,
                    "next_close_positive_rate": 0.75,
                    "fast_confirm_rate": 0.5,
                    "retention_rate": 0.5,
                    "tail_20_rate": 0.25,
                },
                "windows": [
                    {
                        "train_start": "2026-01-01",
                        "train_end": "2026-02-28",
                        "test_start": "2026-03-01",
                        "test_end": "2026-03-31",
                        "count": 2,
                        "next_high_return_mean": 0.05,
                        "next_close_return_mean": 0.03,
                        "next_high_hit_rate_at_threshold": 1.0,
                        "next_close_positive_rate": 1.0,
                        "fast_confirm_rate": 0.5,
                        "retention_rate": 0.5,
                        "tail_20_rate": 0.0,
                    }
                ],
            },
            "top_cases": [],
            "recommendation": "test",
        }
    )

    assert "## Board Breakdown" in markdown
    assert "star_market" in markdown
    assert "chinext" in markdown
    assert "main_board" in markdown
    assert "## Walk-Forward Validation" in markdown
    assert "preset=standard" in markdown
    assert "window_mode=rolling" in markdown
    assert "window_count=2" in markdown
    window_line = next(line for line in markdown.splitlines() if line.startswith("- window:"))
    assert "fast_confirm_rate=0.5" in window_line
    assert "retention_rate=0.5" in window_line
    assert "tail_20_rate=0.0" in window_line


def test_analyze_pre_layer_short_trade_outcomes_raises_on_invalid_walk_forward_preset(tmp_path, monkeypatch):
    """Test that invalid walk-forward preset raises clear ValueError instead of silent fallback."""
    report_dir = tmp_path / "report"
    day1 = report_dir / "selection_artifacts" / "2026-03-25"
    day1.mkdir(parents=True)

    (day1 / "selection_target_replay_input.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-25",
                "supplemental_short_trade_entries": [
                    {
                        "ticker": "300724",
                        "candidate_source": "short_trade_boundary",
                        "short_trade_boundary_metrics": {"candidate_score": 0.31},
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    def mock_get_price_data(ticker, start, end):
        return pd.DataFrame(
            {
                "date": ["2026-03-25", "2026-03-26"],
                "open": [10.0, 10.5],
                "high": [11.0, 11.5],
                "close": [10.5, 11.0],
            }
        )

    monkeypatch.setattr("scripts.analyze_pre_layer_short_trade_outcomes.get_price_data", mock_get_price_data)

    with pytest.raises(ValueError, match="Unknown walk-forward preset: invalid_preset"):
        analyze_pre_layer_short_trade_outcomes(str(report_dir), walk_forward_preset="invalid_preset")


def test_analyze_pre_layer_short_trade_outcomes_raises_on_invalid_walk_forward_window_mode(tmp_path, monkeypatch):
    """Test that invalid window mode raises clear ValueError instead of silent fallback."""
    report_dir = tmp_path / "report"
    day1 = report_dir / "selection_artifacts" / "2026-03-25"
    day1.mkdir(parents=True)

    (day1 / "selection_target_replay_input.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-03-25",
                "supplemental_short_trade_entries": [
                    {
                        "ticker": "300724",
                        "candidate_source": "short_trade_boundary",
                        "short_trade_boundary_metrics": {"candidate_score": 0.31},
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    def mock_get_price_data(ticker, start, end):
        return pd.DataFrame(
            {
                "date": ["2026-03-25", "2026-03-26"],
                "open": [10.0, 10.5],
                "high": [11.0, 11.5],
                "close": [10.5, 11.0],
            }
        )

    monkeypatch.setattr("scripts.analyze_pre_layer_short_trade_outcomes.get_price_data", mock_get_price_data)

    with pytest.raises(ValueError, match="Invalid walk-forward window mode: invalid_mode"):
        analyze_pre_layer_short_trade_outcomes(str(report_dir), walk_forward_window_mode="invalid_mode")


def test_render_pre_layer_short_trade_outcomes_markdown_shows_empty_state_for_gate_breakdown():
    """Test that empty gate_breakdown section shows clear message instead of blank section."""
    analysis = {
        "report_dir": "/test",
        "candidate_sources_filter": set(),
        "tickers_filter": set(),
        "candidate_count": 5,
        "data_status_counts": {"ok": 5},
        "candidate_source_counts": {"short_trade_boundary": 5},
        "next_open_return_distribution": {"count": 5, "mean": 0.01},
        "next_high_return_distribution": {"count": 5, "mean": 0.02},
        "next_close_return_distribution": {"count": 5, "mean": 0.015},
        "next_high_hit_rate_at_threshold": 0.6,
        "next_close_positive_rate": 0.8,
        "source_breakdown": {"short_trade_boundary": {"count": 5, "next_high_return_mean": 0.02, "next_close_return_mean": 0.015, "next_high_hit_rate_at_threshold": 0.6, "next_close_positive_rate": 0.8}},
        "gate_breakdown": {},
        "board_breakdown": {},
        "walk_forward": {},
        "top_cases": [],
        "recommendation": "Test",
    }

    markdown = render_pre_layer_short_trade_outcomes_markdown(analysis)

    # Check that empty gate_breakdown section has a clear message
    gate_section_start = markdown.find("## Regime Gate Breakdown")
    gate_section_end = markdown.find("## Board Breakdown")
    gate_section = markdown[gate_section_start:gate_section_end]
    
    assert "## Regime Gate Breakdown" in markdown
    assert "(no regime gate data available)" in gate_section


def test_render_pre_layer_short_trade_outcomes_markdown_shows_empty_state_for_board_breakdown():
    """Test that empty board_breakdown section shows clear message instead of blank section."""
    analysis = {
        "report_dir": "/test",
        "candidate_sources_filter": set(),
        "tickers_filter": set(),
        "candidate_count": 5,
        "data_status_counts": {"ok": 5},
        "candidate_source_counts": {"short_trade_boundary": 5},
        "next_open_return_distribution": {"count": 5, "mean": 0.01},
        "next_high_return_distribution": {"count": 5, "mean": 0.02},
        "next_close_return_distribution": {"count": 5, "mean": 0.015},
        "next_high_hit_rate_at_threshold": 0.6,
        "next_close_positive_rate": 0.8,
        "source_breakdown": {"short_trade_boundary": {"count": 5, "next_high_return_mean": 0.02, "next_close_return_mean": 0.015, "next_high_hit_rate_at_threshold": 0.6, "next_close_positive_rate": 0.8}},
        "gate_breakdown": {},
        "board_breakdown": {},
        "walk_forward": {},
        "top_cases": [],
        "recommendation": "Test",
    }

    markdown = render_pre_layer_short_trade_outcomes_markdown(analysis)

    # Check that empty board_breakdown section has a clear message
    board_section_start = markdown.find("## Board Breakdown")
    board_section_end = markdown.find("## Walk-Forward Validation")
    board_section = markdown[board_section_start:board_section_end]
    
    assert "## Board Breakdown" in markdown
    assert "(no board classification data available)" in board_section


def test_render_pre_layer_short_trade_outcomes_markdown_shows_empty_state_for_walk_forward():
    """Test that empty walk_forward section shows clear message instead of blank section."""
    analysis = {
        "report_dir": "/test",
        "candidate_sources_filter": set(),
        "tickers_filter": set(),
        "candidate_count": 5,
        "data_status_counts": {"ok": 5},
        "candidate_source_counts": {"short_trade_boundary": 5},
        "next_open_return_distribution": {"count": 5, "mean": 0.01},
        "next_high_return_distribution": {"count": 5, "mean": 0.02},
        "next_close_return_distribution": {"count": 5, "mean": 0.015},
        "next_high_hit_rate_at_threshold": 0.6,
        "next_close_positive_rate": 0.8,
        "source_breakdown": {"short_trade_boundary": {"count": 5, "next_high_return_mean": 0.02, "next_close_return_mean": 0.015, "next_high_hit_rate_at_threshold": 0.6, "next_close_positive_rate": 0.8}},
        "gate_breakdown": {},
        "board_breakdown": {},
        "walk_forward": {"preset": "standard", "window_mode": "rolling", "summary": {"window_count": 0, "candidate_count": 0}, "windows": []},
        "top_cases": [],
        "recommendation": "Test",
    }

    markdown = render_pre_layer_short_trade_outcomes_markdown(analysis)

    # Check that walk_forward section with zero windows has a clear message
    wf_section_start = markdown.find("## Walk-Forward Validation")
    wf_section_end = markdown.find("## Top Cases")
    wf_section = markdown[wf_section_start:wf_section_end]
    
    assert "## Walk-Forward Validation" in markdown
    assert "(no walk-forward windows generated" in wf_section
