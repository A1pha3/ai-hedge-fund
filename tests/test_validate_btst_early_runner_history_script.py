from __future__ import annotations

import json
from pathlib import Path

import pytest
import scripts.validate_btst_early_runner_history as history_script


def test_build_summary_tracks_rates_and_recent_exact_streak() -> None:
    """Aggregate strategy-health metrics from replay rows."""
    rows = [
        {
            "signal_date": "20260501",
            "early_runner_status": "stale_fallback",
            "intersection_count": 0,
            "only_early_runner_count": 1,
            "second_entry_count": 0,
            "outcome_attribution": {
                "intersection": {"candidate_count": 0, "next_close_available_count": 0, "next_close_positive_count": 0, "next_close_mean_return": None, "t_plus_2_available_count": 0, "t_plus_2_positive_count": 0, "t_plus_2_mean_return": None, "next_close_expectation_count": 0, "next_close_matched_count": 0, "next_close_violated_count": 0, "next_close_observed_without_positive_expectation_count": 0},
                "only_early_runner": {"candidate_count": 1, "next_close_available_count": 1, "next_close_positive_count": 0, "next_close_mean_return": -0.02, "t_plus_2_available_count": 1, "t_plus_2_positive_count": 0, "t_plus_2_mean_return": -0.03, "next_close_expectation_count": 1, "next_close_matched_count": 0, "next_close_violated_count": 1, "next_close_observed_without_positive_expectation_count": 0},
                "second_entry": {"candidate_count": 0, "next_close_available_count": 0, "next_close_positive_count": 0, "next_close_mean_return": None, "t_plus_2_available_count": 0, "t_plus_2_positive_count": 0, "t_plus_2_mean_return": None, "next_close_expectation_count": 0, "next_close_matched_count": 0, "next_close_violated_count": 0, "next_close_observed_without_positive_expectation_count": 0},
            },
        },
        {
            "signal_date": "20260502",
            "early_runner_status": "exact",
            "intersection_count": 1,
            "only_early_runner_count": 0,
            "second_entry_count": 1,
            "outcome_attribution": {
                "intersection": {"candidate_count": 1, "next_close_available_count": 1, "next_close_positive_count": 1, "next_close_mean_return": 0.03, "t_plus_2_available_count": 1, "t_plus_2_positive_count": 1, "t_plus_2_mean_return": 0.04, "next_close_expectation_count": 1, "next_close_matched_count": 1, "next_close_violated_count": 0, "next_close_observed_without_positive_expectation_count": 0},
                "only_early_runner": {"candidate_count": 0, "next_close_available_count": 0, "next_close_positive_count": 0, "next_close_mean_return": None, "t_plus_2_available_count": 0, "t_plus_2_positive_count": 0, "t_plus_2_mean_return": None, "next_close_expectation_count": 0, "next_close_matched_count": 0, "next_close_violated_count": 0, "next_close_observed_without_positive_expectation_count": 0},
                "second_entry": {"candidate_count": 1, "next_close_available_count": 1, "next_close_positive_count": 1, "next_close_mean_return": 0.01, "t_plus_2_available_count": 1, "t_plus_2_positive_count": 1, "t_plus_2_mean_return": 0.02, "next_close_expectation_count": 1, "next_close_matched_count": 1, "next_close_violated_count": 0, "next_close_observed_without_positive_expectation_count": 0},
            },
        },
        {
            "signal_date": "20260503",
            "early_runner_status": "exact",
            "intersection_count": 2,
            "only_early_runner_count": 1,
            "second_entry_count": 1,
            "outcome_attribution": {
                "intersection": {"candidate_count": 2, "next_close_available_count": 2, "next_close_positive_count": 1, "next_close_mean_return": 0.01, "t_plus_2_available_count": 1, "t_plus_2_positive_count": 0, "t_plus_2_mean_return": -0.01, "next_close_expectation_count": 2, "next_close_matched_count": 1, "next_close_violated_count": 1, "next_close_observed_without_positive_expectation_count": 0},
                "only_early_runner": {"candidate_count": 1, "next_close_available_count": 1, "next_close_positive_count": 1, "next_close_mean_return": 0.05, "t_plus_2_available_count": 0, "t_plus_2_positive_count": 0, "t_plus_2_mean_return": None, "next_close_expectation_count": 0, "next_close_matched_count": 0, "next_close_violated_count": 0, "next_close_observed_without_positive_expectation_count": 1},
                "second_entry": {"candidate_count": 1, "next_close_available_count": 1, "next_close_positive_count": 0, "next_close_mean_return": -0.02, "t_plus_2_available_count": 0, "t_plus_2_positive_count": 0, "t_plus_2_mean_return": None, "next_close_expectation_count": 1, "next_close_matched_count": 0, "next_close_violated_count": 1, "next_close_observed_without_positive_expectation_count": 0},
            },
        },
        {
            "signal_date": "20260504",
            "early_runner_status": "exact",
            "intersection_count": 0,
            "only_early_runner_count": 0,
            "second_entry_count": 1,
            "outcome_attribution": {
                "intersection": {"candidate_count": 0, "next_close_available_count": 0, "next_close_positive_count": 0, "next_close_mean_return": None, "t_plus_2_available_count": 0, "t_plus_2_positive_count": 0, "t_plus_2_mean_return": None, "next_close_expectation_count": 0, "next_close_matched_count": 0, "next_close_violated_count": 0, "next_close_observed_without_positive_expectation_count": 0},
                "only_early_runner": {"candidate_count": 0, "next_close_available_count": 0, "next_close_positive_count": 0, "next_close_mean_return": None, "t_plus_2_available_count": 0, "t_plus_2_positive_count": 0, "t_plus_2_mean_return": None, "next_close_expectation_count": 0, "next_close_matched_count": 0, "next_close_violated_count": 0, "next_close_observed_without_positive_expectation_count": 0},
                "second_entry": {"candidate_count": 1, "next_close_available_count": 0, "next_close_positive_count": 0, "next_close_mean_return": None, "t_plus_2_available_count": 0, "t_plus_2_positive_count": 0, "t_plus_2_mean_return": None, "next_close_expectation_count": 0, "next_close_matched_count": 0, "next_close_violated_count": 0, "next_close_observed_without_positive_expectation_count": 0},
            },
        },
    ]

    summary = history_script._build_summary(rows)

    assert summary["total_runs"] == 4
    assert summary["exact_count"] == 3
    assert summary["exact_rate"] == 0.75
    assert summary["intersection_positive_count"] == 2
    assert summary["only_early_runner_positive_count"] == 2
    assert summary["second_entry_positive_count"] == 3
    assert summary["total_intersection_count"] == 3
    assert summary["total_only_early_runner_count"] == 2
    assert summary["total_second_entry_count"] == 3
    assert summary["recent_exact_streak"] == 3
    assert summary["meets_recent_exact_gate"] is True
    assert summary["meets_minimum_directory_switch_gate"] is True
    assert summary["intersection_outcome_summary"]["candidate_count"] == 3
    assert summary["intersection_outcome_summary"]["next_close_positive_rate"] == 2 / 3
    assert summary["only_early_runner_outcome_summary"]["next_close_positive_rate"] == 0.5
    assert summary["second_entry_outcome_summary"]["next_close_violated_count"] == 1


def test_build_bucket_outcome_stats_tracks_realized_returns(monkeypatch) -> None:
    """Aggregate realized outcomes for one bucket by ticker."""
    monkeypatch.setattr(
        history_script,
        "_extract_holding_outcome",
        lambda ticker, trade_date, price_cache: {
            "data_status": "ok",
            "cycle_status": "t_plus_2_closed",
            "next_close_return": 0.03 if ticker == "300001" else -0.02,
            "t_plus_2_close_return": 0.04 if ticker == "300001" else None,
        },
    )
    rows = [
        {"ticker": "300001", "historical_prior": {"next_close_positive_rate": 0.8}},
        {"ticker": "300002", "historical_prior": {"next_close_positive_rate": 0.7}},
    ]

    summary = history_script._build_bucket_outcome_stats(rows, "2026-05-01", {})

    assert summary["candidate_count"] == 2
    assert summary["next_close_available_count"] == 2
    assert summary["next_close_positive_count"] == 1
    assert summary["next_close_positive_rate"] == 0.5
    assert summary["next_close_mean_return"] == pytest.approx(0.005)
    assert summary["t_plus_2_available_count"] == 1
    assert summary["t_plus_2_positive_rate"] == 1.0
    assert summary["next_close_matched_count"] == 1
    assert summary["next_close_violated_count"] == 1


def test_render_markdown_includes_second_entry_and_gate_fields() -> None:
    """Render the upgraded strategy-health markdown fields."""
    summary = {
        "total_runs": 2,
        "exact_count": 1,
        "stale_fallback_count": 1,
        "unavailable_count": 0,
        "exact_rate": 0.5,
        "intersection_positive_count": 1,
        "intersection_positive_rate": 0.5,
        "only_early_runner_positive_count": 1,
        "only_early_runner_positive_rate": 0.5,
        "second_entry_positive_count": 1,
        "second_entry_positive_rate": 0.5,
        "total_intersection_count": 1,
        "total_only_early_runner_count": 2,
        "total_second_entry_count": 1,
        "avg_intersection_count": 0.5,
        "avg_only_early_runner_count": 1.0,
        "avg_second_entry_count": 0.5,
        "recent_exact_streak": 1,
        "meets_recent_exact_gate": False,
        "meets_minimum_directory_switch_gate": False,
        "intersection_outcome_summary": {"candidate_count": 1, "next_close_available_count": 1, "next_close_positive_rate": 1.0, "next_close_mean_return": 0.03, "t_plus_2_available_count": 1, "t_plus_2_positive_rate": 1.0, "t_plus_2_mean_return": 0.04, "next_close_matched_count": 1, "next_close_expectation_count": 1, "next_close_violated_count": 0, "next_close_observed_without_positive_expectation_count": 0},
        "only_early_runner_outcome_summary": {"candidate_count": 2, "next_close_available_count": 2, "next_close_positive_rate": 0.5, "next_close_mean_return": 0.01, "t_plus_2_available_count": 1, "t_plus_2_positive_rate": 0.0, "t_plus_2_mean_return": -0.01, "next_close_matched_count": 0, "next_close_expectation_count": 1, "next_close_violated_count": 1, "next_close_observed_without_positive_expectation_count": 1},
        "second_entry_outcome_summary": {"candidate_count": 1, "next_close_available_count": 1, "next_close_positive_rate": 0.0, "next_close_mean_return": -0.02, "t_plus_2_available_count": 0, "t_plus_2_positive_rate": 0.0, "t_plus_2_mean_return": None, "next_close_matched_count": 0, "next_close_expectation_count": 1, "next_close_violated_count": 1, "next_close_observed_without_positive_expectation_count": 0},
    }
    rows = [
        {
            "signal_date": "20260501",
            "next_trade_date": "2026-05-02",
            "early_runner_status": "stale_fallback",
            "early_runner_latest_trade_date": "2026-04-30",
            "formal_count": 2,
            "intersection_count": 0,
            "only_early_runner_count": 1,
            "second_entry_count": 1,
            "intersection_tickers": [],
            "only_early_runner_tickers": ["300001"],
            "second_entry_tickers": ["300002"],
        }
    ]

    markdown = history_script._render_markdown("202605", summary, rows)

    assert "second-entry 出现占比" in markdown
    assert "最小目录切换 gate" in markdown
    assert "## 策略体检" in markdown
    assert "## 结果归因" in markdown
    assert "交集优先复审层" in markdown
    assert "next_close 正收益率 / 平均收益" in markdown
    assert "second_entry_count" in markdown
    assert "300002" in markdown


def test_validate_btst_early_runner_history_writes_upgraded_outputs(tmp_path: Path, monkeypatch) -> None:
    """Write JSON and Markdown outputs with the upgraded strategy-health summary."""
    reports_root = tmp_path / "data" / "reports"
    output_dir = tmp_path / "outputs"

    monkeypatch.setattr(history_script, "_discover_signal_dates", lambda reports_root, month_prefix: ["20260501", "20260502"])
    monkeypatch.setattr(
        history_script,
        "_build_row",
        lambda reports_root, signal_date, bundle_root: {
            "signal_date": signal_date,
            "next_trade_date": "2026-05-03",
            "report_dir": f"report-{signal_date}",
            "early_runner_status": "exact" if signal_date == "20260502" else "stale_fallback",
            "early_runner_latest_trade_date": "2026-05-02",
            "formal_count": 2,
            "intersection_count": 1 if signal_date == "20260502" else 0,
            "intersection_tickers": ["300001"] if signal_date == "20260502" else [],
            "only_early_runner_count": 1,
            "only_early_runner_tickers": ["300002"],
            "second_entry_count": 1,
            "second_entry_tickers": ["300003"],
            "outcome_attribution": {
                "intersection": {"candidate_count": 1 if signal_date == "20260502" else 0, "next_close_available_count": 1 if signal_date == "20260502" else 0, "next_close_positive_count": 1 if signal_date == "20260502" else 0, "next_close_mean_return": 0.04 if signal_date == "20260502" else None, "t_plus_2_available_count": 0, "t_plus_2_positive_count": 0, "t_plus_2_mean_return": None, "next_close_expectation_count": 1 if signal_date == "20260502" else 0, "next_close_matched_count": 1 if signal_date == "20260502" else 0, "next_close_violated_count": 0, "next_close_observed_without_positive_expectation_count": 0},
                "only_early_runner": {"candidate_count": 1, "next_close_available_count": 1, "next_close_positive_count": 0, "next_close_mean_return": -0.01, "t_plus_2_available_count": 0, "t_plus_2_positive_count": 0, "t_plus_2_mean_return": None, "next_close_expectation_count": 1, "next_close_matched_count": 0, "next_close_violated_count": 1, "next_close_observed_without_positive_expectation_count": 0},
                "second_entry": {"candidate_count": 1, "next_close_available_count": 1, "next_close_positive_count": 1, "next_close_mean_return": 0.02, "t_plus_2_available_count": 0, "t_plus_2_positive_count": 0, "t_plus_2_mean_return": None, "next_close_expectation_count": 1, "next_close_matched_count": 1, "next_close_violated_count": 0, "next_close_observed_without_positive_expectation_count": 0},
            },
            "written_files": [],
        },
    )

    result = history_script.validate_btst_early_runner_history(
        "202605",
        reports_root=reports_root,
        output_dir=output_dir,
    )

    assert result["status"] == "validated"
    assert result["summary"]["second_entry_positive_count"] == 2
    assert Path(result["json_path"]).exists()
    assert Path(result["md_path"]).exists()

    payload = json.loads(Path(result["json_path"]).read_text(encoding="utf-8"))
    assert payload["summary"]["total_second_entry_count"] == 2
    assert payload["summary"]["intersection_outcome_summary"]["next_close_positive_count"] == 1
    assert payload["summary"]["second_entry_outcome_summary"]["next_close_positive_rate"] == 1.0
    markdown = Path(result["md_path"]).read_text(encoding="utf-8")
    assert "## 策略体检" in markdown
    assert "## 结果归因" in markdown
    assert "300003" in markdown
