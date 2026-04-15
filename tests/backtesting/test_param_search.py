import json
from pathlib import Path

import pytest

from src.backtesting.param_search import (
    ParamSpace,
    SearchObjective,
    TrialResult,
    compute_objective_score,
    format_search_report,
    run_param_search,
    save_search_payload,
    save_search_report,
)


def test_param_space_combinations():
    space = ParamSpace(grid={"a": [1, 2], "b": [3, 4]})
    combos = space.combinations()
    assert len(combos) == 4
    assert {"a": 1, "b": 3} in combos
    assert {"a": 2, "b": 4} in combos


def test_param_space_size():
    space = ParamSpace(grid={"a": [1, 2, 3], "b": [4, 5], "c": [6]})
    assert space.size() == 6


def test_compute_objective_score_sharpe():
    metrics = {"sharpe_ratio": 1.5, "sortino_ratio": 2.0, "max_drawdown": -0.1}
    assert compute_objective_score(metrics, SearchObjective.SHARPE) == 1.5


def test_compute_objective_score_composite():
    metrics = {"sharpe_ratio": 1.0, "sortino_ratio": 2.0, "max_drawdown": -1.0}
    expected = 0.4 * 2.0 + 0.3 * 1.0 - 0.3 * 1.0
    assert abs(compute_objective_score(metrics, SearchObjective.COMPOSITE) - expected) < 1e-6


def test_compute_objective_score_edge():
    metrics = {
        "next_close_positive_rate": 0.60,
        "next_close_payoff_ratio": 2.0,
        "next_close_expectancy": 0.01,
        "next_high_hit_rate": 0.50,
        "t_plus_2_close_positive_rate": 0.55,
        "downside_p10": -0.02,
        "sample_weight": 0.80,
    }
    score = compute_objective_score(metrics, SearchObjective.EDGE)
    assert score == pytest.approx(0.4796, abs=1e-4)


def test_compute_objective_score_btst():
    metrics = {
        "next_close_positive_rate": 0.60,
        "next_close_payoff_ratio": 2.0,
        "next_close_expectancy": 0.01,
        "next_high_hit_rate": 0.50,
        "t_plus_2_close_positive_rate": 0.55,
        "downside_p10": -0.02,
        "sample_weight": 0.80,
    }
    score = compute_objective_score(metrics, SearchObjective.BTST)
    assert score == pytest.approx(0.46661, abs=1e-5)


def test_compute_objective_score_returns_none_for_missing():
    assert compute_objective_score({}, SearchObjective.COMPOSITE) is None


def test_compute_objective_score_edge_returns_none_for_missing():
    metrics = {"next_close_positive_rate": 0.6}
    assert compute_objective_score(metrics, SearchObjective.EDGE) is None


def test_compute_objective_score_btst_returns_none_for_missing():
    metrics = {"next_close_positive_rate": 0.6}
    assert compute_objective_score(metrics, SearchObjective.BTST) is None


def test_run_param_search_ranks_by_score():
    space = ParamSpace(grid={"x": [1, 2, 3]})

    def evaluator(params):
        return {"sharpe_ratio": float(params["x"]), "sortino_ratio": float(params["x"]) * 2, "max_drawdown": -0.1 * params["x"]}

    report = run_param_search(space=space, objective=SearchObjective.COMPOSITE, evaluator=evaluator)
    assert report.completed_trials == 3
    assert report.best_params == {"x": 3}
    assert report.results[0].params == {"x": 3}


def test_run_param_search_checkpoint_resume(tmp_path):
    cp_path = tmp_path / "checkpoint.json"
    space = ParamSpace(grid={"x": [1, 2]})

    call_count = 0

    def evaluator(params):
        nonlocal call_count
        call_count += 1
        return {"sharpe_ratio": float(params["x"]), "sortino_ratio": 1.0, "max_drawdown": -0.1}

    report1 = run_param_search(space=space, objective=SearchObjective.SHARPE, evaluator=evaluator, checkpoint_path=cp_path)
    assert report1.completed_trials == 2
    assert call_count == 2

    report2 = run_param_search(space=space, objective=SearchObjective.SHARPE, evaluator=evaluator, checkpoint_path=cp_path)
    assert report2.completed_trials == 2
    assert call_count == 2, "should not re-evaluate completed trials"


def test_format_search_report():
    report = run_param_search(
        space=ParamSpace(grid={"a": [1, 2]}),
        objective=SearchObjective.COMPOSITE,
        evaluator=lambda p: {"sharpe_ratio": float(p["a"]), "sortino_ratio": 1.0, "max_drawdown": -0.1},
    )
    md = format_search_report(report)
    assert "Parameter Search Report" in md
    assert "composite" in md
    assert "Best" in md


def test_save_search_report_and_payload(tmp_path):
    report = run_param_search(
        space=ParamSpace(grid={"x": [1]}),
        objective=SearchObjective.SHARPE,
        evaluator=lambda p: {"sharpe_ratio": 1.0, "sortino_ratio": 2.0, "max_drawdown": -0.5},
    )
    md_path = save_search_report(report, tmp_path / "report.md")
    json_path = save_search_payload(report, tmp_path / "report.json")

    assert md_path.exists()
    assert json_path.exists()

    data = json.loads(json_path.read_text())
    assert data["completed_trials"] == 1
    assert data["results"][0]["params"]["x"] == 1


def test_trial_result_with_none_score_excluded_from_best():
    space = ParamSpace(grid={"x": [1, 2]})

    def evaluator(params):
        if params["x"] == 1:
            return {"sharpe_ratio": None, "sortino_ratio": None, "max_drawdown": None}
        return {"sharpe_ratio": 1.0, "sortino_ratio": 2.0, "max_drawdown": -0.1}

    report = run_param_search(space=space, objective=SearchObjective.SHARPE, evaluator=evaluator)
    assert report.best_params == {"x": 2}
