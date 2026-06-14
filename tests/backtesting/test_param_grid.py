"""Unit + integration tests for the parameter-grid comparison module.

Coverage breakdown:
  * Grid spec parsing (correct, malformed, edge cases)
  * Cartesian-product expansion
  * Single-trial execution & error capture
  * Worker-pool execution with a mock evaluator
  * Best-trial selection under failures / missing metrics
  * Console / Markdown / CSV / JSON rendering
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

import pytest

from src.backtesting.param_grid import (
    COMPARISON_METRICS,
    DEFAULT_GRID_MAX_WORKERS,
    grid_combinations,
    GRID_ENV_VAR,
    ParamGridError,
    ParamGridReport,
    ParamGridTrial,
    parse_param_grid,
    render_console_table,
    render_markdown_table,
    run_param_grid,
    save_csv_report,
    save_json_report,
    save_markdown_report,
)

# ---------------------------------------------------------------------------
# parse_param_grid
# ---------------------------------------------------------------------------


def test_parse_param_grid_basic_comma_separated_values():
    grid = parse_param_grid("top_n=10,15,20;min_score=0.5,0.6")
    assert grid == {"top_n": [10, 15, 20], "min_score": [0.5, 0.6]}


def test_parse_param_grid_coerces_int_float_bool_and_string():
    grid = parse_param_grid("a=1,2; b=0.1,0.2; c=true,false; d=hello,world")
    assert grid["a"] == [1, 2]
    assert grid["b"] == [0.1, 0.2]
    assert grid["c"] == [True, False]
    assert grid["d"] == ["hello", "world"]


def test_parse_param_grid_strips_whitespace():
    grid = parse_param_grid("  top_n = 10 , 15 ; min_score = 0.5 ")
    assert grid["top_n"] == [10, 15]
    assert grid["min_score"] == [0.5]


def test_parse_param_grid_keeps_int_value_with_decimal_colon_unaffected():
    # "10" should stay int (matches CLI --baseline-top-n=10 behaviour).
    grid = parse_param_grid("top_n=10,20")
    assert all(isinstance(v, int) for v in grid["top_n"])


def test_parse_param_grid_single_dimension():
    grid = parse_param_grid("only=1")
    assert grid == {"only": [1]}


def test_parse_param_grid_rejects_empty_spec():
    with pytest.raises(ParamGridError, match="empty"):
        parse_param_grid("")


def test_parse_param_grid_rejects_whitespace_only_spec():
    with pytest.raises(ParamGridError, match="empty"):
        parse_param_grid("   ")


def test_parse_param_grid_rejects_missing_equals_sign():
    with pytest.raises(ParamGridError, match="invalid --param-grid dimension"):
        parse_param_grid("top_n10,15")


def test_parse_param_grid_rejects_empty_dimension_name():
    with pytest.raises(ParamGridError, match="empty dimension name"):
        parse_param_grid("=10,15")


def test_parse_param_grid_rejects_duplicate_keys():
    with pytest.raises(ParamGridError, match="duplicate dimension"):
        parse_param_grid("top_n=10;top_n=20")


def test_parse_param_grid_rejects_empty_value_cell():
    with pytest.raises(ParamGridError, match="empty value cell"):
        parse_param_grid("top_n=10,,20")


def test_parse_param_grid_rejects_only_delimiter():
    with pytest.raises(ParamGridError, match="no dimensions"):
        parse_param_grid(";;;")


def test_parse_param_grid_ignores_blank_segments_between_semicolons():
    # `top_n=10; ;min_score=0.5` should be tolerated: the empty segment is skipped.
    grid = parse_param_grid("top_n=10; ;min_score=0.5")
    assert grid == {"top_n": [10], "min_score": [0.5]}


# ---------------------------------------------------------------------------
# grid_combinations
# ---------------------------------------------------------------------------


def test_grid_combinations_returns_cartesian_product():
    grid = {"a": [1, 2], "b": [3, 4]}
    combos = grid_combinations(grid)
    assert len(combos) == 4
    assert {"a": 1, "b": 3} in combos
    assert {"a": 1, "b": 4} in combos
    assert {"a": 2, "b": 3} in combos
    assert {"a": 2, "b": 4} in combos


def test_grid_combinations_sort_keys_for_determinism():
    grid = {"z": [1], "a": [2], "m": [3]}
    combos = grid_combinations(grid)
    assert list(combos[0].keys()) == ["a", "m", "z"]


def test_grid_combinations_empty_grid_returns_empty_list():
    assert grid_combinations({}) == []


# ---------------------------------------------------------------------------
# _run_single_trial / run_param_grid
# ---------------------------------------------------------------------------


def test_run_param_grid_invokes_evaluator_for_each_combination():
    grid = {"x": [1, 2, 3]}
    calls: list[dict] = []

    def evaluator(params):
        calls.append(dict(params))
        return {"sharpe_ratio": float(params["x"]), "win_rate": 0.5}

    report = run_param_grid(grid=grid, evaluator=evaluator)
    assert report.total_combinations == 3
    assert report.completed == 3
    assert report.failed == 0
    assert sorted(call["x"] for call in calls) == [1, 2, 3]


def test_run_param_grid_captures_evaluator_exceptions():
    grid = {"x": [1, 2]}

    def evaluator(params):
        if params["x"] == 2:
            raise ValueError("boom")
        return {"sharpe_ratio": 1.0}

    report = run_param_grid(grid=grid, evaluator=evaluator)
    assert report.completed == 1
    assert report.failed == 1
    failed = next(t for t in report.trials if t.is_failed())
    assert failed.params == {"x": 2}
    assert "ValueError" in (failed.error or "")
    assert failed.metrics.get("status") == "failed"


def test_run_param_grid_preserves_completed_trial_metric_keys():
    grid = {"x": [1]}

    def evaluator(_params):
        return {
            "sharpe_ratio": 1.5,
            "sortino_ratio": 2.0,
            "max_drawdown": -0.05,
            "win_rate": 0.6,
            "total_return": 0.12,
            "window_count": 3,
            "extra_metric": "should be in JSON",
        }

    report = run_param_grid(grid=grid, evaluator=evaluator)
    trial = report.trials[0]
    for key in COMPARISON_METRICS:
        assert key in trial.metrics
    assert trial.metrics["extra_metric"] == "should be in JSON"


def test_run_param_grid_trial_order_is_canonical():
    """Trials must come back in cartesian-product order, not completion order."""
    grid = {"x": [1, 2, 3]}

    def evaluator(params):
        if params["x"] == 2:
            time.sleep(0.05)  # let x=3 finish first
        return {"sharpe_ratio": 0.0}

    report = run_param_grid(grid=grid, evaluator=evaluator, max_workers=3)
    assert [t.params["x"] for t in report.trials] == [1, 2, 3]


def test_run_param_grid_thread_safety_with_shared_evaluator():
    """The evaluator may be invoked from multiple threads simultaneously."""
    grid = {"x": list(range(8))}
    seen: list[int] = []
    seen_lock = threading.Lock()
    counter_lock = threading.Lock()
    active = 0
    max_active = 0

    def evaluator(params):
        nonlocal active, max_active
        with counter_lock:
            active += 1
            max_active = max(max_active, active)
        # Yield so other threads can interleave.  This is what makes the
        # "ran in parallel" claim meaningful: if the pool ran serially,
        # active would never exceed 1.
        time.sleep(0.01)
        with counter_lock:
            active -= 1
        with seen_lock:
            seen.append(params["x"])
        return {"sharpe_ratio": 1.0}

    report = run_param_grid(grid=grid, evaluator=evaluator, max_workers=4)
    assert report.completed == 8
    assert sorted(seen) == list(range(8))
    # The pool actually ran trials in parallel (not serialized).
    assert max_active > 1, f"expected concurrent execution, max_active={max_active}"


def test_run_param_grid_respects_max_workers_override(monkeypatch):
    monkeypatch.delenv(GRID_ENV_VAR, raising=False)
    grid = {"x": [1, 2]}
    report = run_param_grid(grid=grid, evaluator=lambda p: {"sharpe_ratio": 1.0}, max_workers=1)
    assert report.max_workers == 1


def test_run_param_grid_reads_default_workers_from_env(monkeypatch):
    monkeypatch.setenv(GRID_ENV_VAR, "5")
    grid = {"x": [1]}
    report = run_param_grid(grid=grid, evaluator=lambda p: {"sharpe_ratio": 1.0})
    assert report.max_workers == 5


def test_run_param_grid_falls_back_when_env_var_is_garbage(monkeypatch):
    monkeypatch.setenv(GRID_ENV_VAR, "not-a-number")
    grid = {"x": [1]}
    report = run_param_grid(grid=grid, evaluator=lambda p: {"sharpe_ratio": 1.0})
    assert report.max_workers == DEFAULT_GRID_MAX_WORKERS


def test_run_param_grid_clamps_zero_or_negative_max_workers():
    grid = {"x": [1]}
    report = run_param_grid(grid=grid, evaluator=lambda p: {"sharpe_ratio": 1.0}, max_workers=0)
    assert report.max_workers == 1
    report = run_param_grid(grid=grid, evaluator=lambda p: {"sharpe_ratio": 1.0}, max_workers=-3)
    assert report.max_workers == 1


def test_run_param_grid_empty_grid_yields_empty_report():
    report = run_param_grid(grid={}, evaluator=lambda p: {})
    assert report.total_combinations == 0
    assert report.completed == 0
    assert report.failed == 0
    assert report.trials == []


# ---------------------------------------------------------------------------
# best_trial / trials_sorted_by
# ---------------------------------------------------------------------------


def _make_trial(
    index: int,
    params: dict,
    metrics: dict,
    *,
    error: str | None = None,
    duration: float = 0.01,
) -> ParamGridTrial:
    return ParamGridTrial(
        trial_index=index,
        params=params,
        metrics=metrics,
        duration_seconds=duration,
        error=error,
    )


def test_best_trial_picks_highest_sharpe():
    report = ParamGridReport(
        trials=[
            _make_trial(0, {"x": 1}, {"sharpe_ratio": 0.5}),
            _make_trial(1, {"x": 2}, {"sharpe_ratio": 2.5}),
            _make_trial(2, {"x": 3}, {"sharpe_ratio": 1.0}),
        ],
    )
    best = report.best_trial("sharpe_ratio")
    assert best is not None
    assert best.params == {"x": 2}


def test_best_trial_skips_failed_trials():
    report = ParamGridReport(
        trials=[
            _make_trial(0, {"x": 1}, {"sharpe_ratio": 100.0}, error="boom"),
            _make_trial(1, {"x": 2}, {"sharpe_ratio": 1.0}),
        ],
    )
    best = report.best_trial("sharpe_ratio")
    assert best is not None
    assert best.params == {"x": 2}


def test_best_trial_returns_none_when_all_failed():
    report = ParamGridReport(
        trials=[
            _make_trial(0, {"x": 1}, {}, error="boom"),
            _make_trial(1, {"x": 2}, {}, error="boom"),
        ],
    )
    assert report.best_trial("sharpe_ratio") is None


def test_best_trial_returns_none_when_no_trials():
    assert ParamGridReport().best_trial("sharpe_ratio") is None


def test_trials_sorted_by_treats_missing_metric_as_worst():
    report = ParamGridReport(
        trials=[
            _make_trial(0, {"x": 1}, {"sharpe_ratio": None}),
            _make_trial(1, {"x": 2}, {"sharpe_ratio": 0.5}),
            _make_trial(2, {"x": 3}, {"sharpe_ratio": 1.0}),
        ],
    )
    sorted_trials = report.trials_sorted_by("sharpe_ratio")
    # The two real-sharpe trials come first, with 1.0 ranked above 0.5;
    # the missing-sharpe trial is pushed to the end.
    assert [t.params["x"] for t in sorted_trials] == [3, 2, 1]


def test_trials_sorted_by_ascending():
    report = ParamGridReport(
        trials=[
            _make_trial(0, {"x": 1}, {"sharpe_ratio": 0.5}),
            _make_trial(1, {"x": 2}, {"sharpe_ratio": 2.5}),
        ],
    )
    sorted_trials = report.trials_sorted_by("sharpe_ratio", descending=False)
    assert [t.params["x"] for t in sorted_trials] == [1, 2]


# ---------------------------------------------------------------------------
# ParamGridTrial.to_row
# ---------------------------------------------------------------------------


def test_trial_to_row_includes_param_columns_and_metrics():
    trial = _make_trial(0, {"x": 1, "y": 2}, {"sharpe_ratio": 1.5, "win_rate": 0.6})
    row = trial.to_row()
    assert row["param.x"] == 1
    assert row["param.y"] == 2
    assert row["sharpe_ratio"] == 1.5
    assert row["win_rate"] == 0.6
    assert row["status"] == "ok"
    assert row["duration_s"] == pytest.approx(round(trial.duration_seconds, 3))
    assert "error" not in row


def test_trial_to_row_marks_failure_and_includes_error():
    trial = _make_trial(0, {"x": 1}, {"status": "failed"}, error="boom")
    row = trial.to_row()
    assert row["status"] == "failed"
    assert row["error"] == "boom"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_render_console_table_includes_headers_and_separator():
    report = ParamGridReport(
        trials=[
            _make_trial(0, {"x": 1}, {"sharpe_ratio": 0.5, "win_rate": 0.4}),
        ],
        total_combinations=1,
    )
    table = render_console_table(report)
    assert "x" in table
    assert "sharpe_ratio" in table
    assert "-+-" in table
    assert "0.5000" in table


def test_render_console_table_empty_report():
    assert render_console_table(ParamGridReport()) == "(no trials)"


def test_render_markdown_table_shows_best_trial_and_results():
    report = ParamGridReport(
        trials=[
            _make_trial(0, {"x": 1}, {"sharpe_ratio": 0.5, "win_rate": 0.4}),
            _make_trial(1, {"x": 2}, {"sharpe_ratio": 1.5, "win_rate": 0.6}),
        ],
        total_combinations=2,
    )
    md = render_markdown_table(report, sort_by="sharpe_ratio")
    assert "Best Trial" in md
    assert "sharpe_ratio" in md
    # The Best Trial block should list the highest-sharpe trial (x=2).
    best_block = md.split("## Results")[0]
    assert "`x`: 2" in best_block
    # The Results table should sort x=2 above x=1 (descending sharpe).
    results_block = md.split("## Results")[1]
    # Look for the row position of each trial's cell value.
    pos_x2 = results_block.index(" 2 ")  # the " 2 " cell of the x column
    pos_x1 = results_block.index(" 1 ")
    assert pos_x2 < pos_x1, f"x=2 (sharpe 1.5) should appear above x=1 (sharpe 0.5): {results_block!r}"


def test_render_markdown_table_handles_empty_report():
    md = render_markdown_table(ParamGridReport())
    assert "No trials to display" in md


def test_render_markdown_table_handles_all_failed_report():
    report = ParamGridReport(
        trials=[
            _make_trial(0, {"x": 1}, {"status": "failed"}, error="boom"),
        ],
        total_combinations=1,
    )
    md = render_markdown_table(report)
    assert "FAILED" in md or "failed" in md.lower()


# ---------------------------------------------------------------------------
# File output
# ---------------------------------------------------------------------------


def test_save_csv_report_creates_file_with_header_and_rows(tmp_path: Path):
    report = ParamGridReport(
        trials=[
            _make_trial(0, {"x": 1, "y": 2}, {"sharpe_ratio": 0.5, "win_rate": 0.6}),
            _make_trial(1, {"x": 3, "y": 4}, {"sharpe_ratio": 1.5, "win_rate": 0.7}),
        ],
        total_combinations=2,
    )
    path = save_csv_report(report, tmp_path / "grid.csv")
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    lines = [line for line in content.strip().splitlines() if line]
    # 1 header + 2 data rows
    assert len(lines) == 3
    # First line contains every header
    assert "sharpe_ratio" in lines[0]
    assert "param.x" in lines[0]


def test_save_csv_report_empty_report_writes_empty_file(tmp_path: Path):
    path = save_csv_report(ParamGridReport(), tmp_path / "grid.csv")
    assert path.exists()
    assert path.read_text(encoding="utf-8") == ""


def test_save_json_report_contains_summary_and_trials(tmp_path: Path):
    report = ParamGridReport(
        trials=[
            _make_trial(0, {"x": 1}, {"sharpe_ratio": 1.0, "win_rate": 0.5}),
            _make_trial(1, {"x": 2}, {"sharpe_ratio": 2.0, "win_rate": 0.6}, error="boom"),
        ],
        total_combinations=2,
    )
    path = save_json_report(report, tmp_path / "grid.json", sort_by="sharpe_ratio")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["summary"]["total_combinations"] == 2
    assert data["summary"]["completed"] == 1
    assert data["summary"]["failed"] == 1
    assert data["summary"]["sort_by"] == "sharpe_ratio"
    # best_params must come from the only passing trial (x=1)
    assert data["summary"]["best_params"] == {"x": 1}
    # 2 trials in the payload
    assert len(data["trials"]) == 2
    statuses = sorted(t["status"] for t in data["trials"])
    assert statuses == ["failed", "ok"]


def test_save_markdown_report_writes_to_disk(tmp_path: Path):
    report = ParamGridReport(
        trials=[_make_trial(0, {"x": 1}, {"sharpe_ratio": 1.0})],
        total_combinations=1,
    )
    path = save_markdown_report(report, tmp_path / "grid.md", sort_by="sharpe_ratio")
    assert path.exists()
    assert "Parameter Grid Comparison" in path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Integration: end-to-end with mock evaluator
# ---------------------------------------------------------------------------


def test_end_to_end_grid_run_writes_three_reports(tmp_path: Path, caplog):
    """Smoke-test the full path: parse -> run -> render -> save."""
    spec = "top_n=5,10;threshold=0.3,0.4"
    grid = parse_param_grid(spec)
    assert grid_combinations(grid).__len__() == 4

    def evaluator(params):
        # Deterministic mock: sharpe = top_n * threshold * 10
        return {
            "sharpe_ratio": float(params["top_n"]) * float(params["threshold"]) * 10.0,
            "win_rate": 0.4 + 0.1 * params["threshold"],
            "sortino_ratio": 1.0,
            "max_drawdown": -0.05,
            "total_return": 0.10,
        }

    caplog.set_level(logging.INFO, logger="src.backtesting.param_grid")
    report = run_param_grid(grid=grid, evaluator=evaluator, max_workers=2)

    # 4 trials, all completed, best is top_n=10, threshold=0.4 (sharpe 40)
    assert report.completed == 4
    assert report.failed == 0
    best = report.best_trial("sharpe_ratio")
    assert best is not None
    assert best.params == {"top_n": 10, "threshold": 0.4}
    assert best.metrics["sharpe_ratio"] == pytest.approx(40.0)

    # Write all three reports
    csv_path = save_csv_report(report, tmp_path / "g.csv")
    md_path = save_markdown_report(report, tmp_path / "g.md", sort_by="sharpe_ratio")
    json_path = save_json_report(report, tmp_path / "g.json", sort_by="sharpe_ratio")

    assert csv_path.exists() and csv_path.stat().st_size > 0
    assert md_path.exists() and "Parameter Grid Comparison" in md_path.read_text(encoding="utf-8")
    json_payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert json_payload["summary"]["best_params"] == {"top_n": 10, "threshold": 0.4}

    # Make sure the completion log line was emitted
    assert any("Param grid complete" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# NaN / Inf metric guards (regression for v0 audit)
# ---------------------------------------------------------------------------
class TestNonFiniteMetricGuards:
    """best_trial / trials_sorted_by must drop NaN/Inf metrics instead of
    surfacing a corrupt value as the "best" via IEEE-754 sort quirks."""

    def test_best_trial_skips_nan_metric(self) -> None:
        from src.backtesting.param_grid import ParamGridReport, ParamGridTrial

        finite_trial = ParamGridTrial(
            trial_index=0,
            params={"x": 1},
            metrics={"sharpe_ratio": 1.5, "status": "ok"},
            duration_seconds=0.1,
        )
        nan_trial = ParamGridTrial(
            trial_index=1,
            params={"x": 2},
            metrics={"sharpe_ratio": float("nan"), "status": "ok"},
            duration_seconds=0.1,
        )
        report = ParamGridReport(trials=[nan_trial, finite_trial], total_combinations=2, max_workers=1)
        best = report.best_trial("sharpe_ratio")
        assert best is not None
        assert best.trial_index == 0  # the NaN trial must NOT win

    def test_best_trial_skips_inf_metric(self) -> None:
        from src.backtesting.param_grid import ParamGridReport, ParamGridTrial

        finite_trial = ParamGridTrial(
            trial_index=0,
            params={"x": 1},
            metrics={"sharpe_ratio": 1.5, "status": "ok"},
            duration_seconds=0.1,
        )
        inf_trial = ParamGridTrial(
            trial_index=1,
            params={"x": 2},
            metrics={"sharpe_ratio": float("inf"), "status": "ok"},
            duration_seconds=0.1,
        )
        report = ParamGridReport(trials=[inf_trial, finite_trial], total_combinations=2, max_workers=1)
        best = report.best_trial("sharpe_ratio")
        assert best is not None
        assert best.trial_index == 0

    def test_best_trial_returns_none_when_all_non_finite(self) -> None:
        from src.backtesting.param_grid import ParamGridReport, ParamGridTrial

        nan_trial = ParamGridTrial(
            trial_index=0,
            params={"x": 1},
            metrics={"sharpe_ratio": float("nan"), "status": "ok"},
            duration_seconds=0.1,
        )
        report = ParamGridReport(trials=[nan_trial], total_combinations=1, max_workers=1)
        assert report.best_trial("sharpe_ratio") is None

    def test_trials_sorted_by_pushed_nan_to_bottom(self) -> None:
        from src.backtesting.param_grid import ParamGridReport, ParamGridTrial

        a = ParamGridTrial(trial_index=0, params={"x": 1}, metrics={"sharpe_ratio": 2.0, "status": "ok"}, duration_seconds=0.1)
        b = ParamGridTrial(trial_index=1, params={"x": 2}, metrics={"sharpe_ratio": float("nan"), "status": "ok"}, duration_seconds=0.1)
        c = ParamGridTrial(trial_index=2, params={"x": 3}, metrics={"sharpe_ratio": 1.0, "status": "ok"}, duration_seconds=0.1)
        report = ParamGridReport(trials=[b, a, c], total_combinations=3, max_workers=1)
        sorted_trials = report.trials_sorted_by("sharpe_ratio", descending=True)
        # NaN trial pushed to the end; finite values sorted normally
        assert sorted_trials[-1].trial_index == 1
        assert sorted_trials[0].trial_index == 0
        assert sorted_trials[1].trial_index == 2
