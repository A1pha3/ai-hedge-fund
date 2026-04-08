from __future__ import annotations

import json

import pandas as pd

from scripts.analyze_pre_layer_short_trade_outcomes import analyze_pre_layer_short_trade_outcomes, render_pre_layer_short_trade_outcomes_markdown


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
