import json
from pathlib import Path

import pytest

from src.backtesting.evaluation_bundle import build_canonical_btst_evaluation_bundle
from src.backtesting.param_search import (
    ParamSpace,
    SearchObjective,
    TrialResult,
    check_guardrails,
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
        "t_plus_3_close_positive_rate": 0.53,
        "t_plus_3_close_expectancy": 0.012,
        "downside_p10": -0.02,
        "sample_weight": 0.80,
    }
    score = compute_objective_score(metrics, SearchObjective.BTST)
    assert score == pytest.approx(0.475049, abs=1e-6)


def test_compute_objective_score_returns_none_for_missing():
    assert compute_objective_score({}, SearchObjective.COMPOSITE) is None


def test_compute_objective_score_edge_returns_none_for_missing():
    metrics = {"next_close_positive_rate": 0.6}
    assert compute_objective_score(metrics, SearchObjective.EDGE) is None


def test_compute_objective_score_btst_returns_none_for_missing():
    metrics = {"next_close_positive_rate": 0.6}
    assert compute_objective_score(metrics, SearchObjective.BTST) is None


def test_build_canonical_btst_evaluation_bundle_separates_metric_roles():
    bundle = build_canonical_btst_evaluation_bundle(
        {
            "next_close_positive_rate": 0.58,
            "next_close_payoff_ratio": 1.9,
            "next_close_expectancy": 0.012,
            "next_high_hit_rate": 0.61,
            "t_plus_2_close_positive_rate": 0.55,
            "t_plus_3_close_positive_rate": 0.52,
            "t_plus_3_close_expectancy": 0.011,
            "downside_p10": -0.031,
            "sample_weight": 0.74,
            "projected_theme_exposure": 0.18,
        }
    )

    assert bundle.objective_metrics["next_close_positive_rate"] == pytest.approx(0.58)
    assert bundle.guardrail_metrics["downside_p10"] == pytest.approx(-0.031)
    assert bundle.context_metrics["projected_theme_exposure"] == pytest.approx(0.18)


def test_build_canonical_btst_evaluation_bundle_lookup_returns_values_across_metric_groups():
    bundle = build_canonical_btst_evaluation_bundle(
        {
            "next_close_positive_rate": 0.58,
            "downside_p10": -0.031,
            "projected_theme_exposure": 0.18,
        }
    )

    assert bundle.lookup("next_close_positive_rate") == pytest.approx(0.58)
    assert bundle.lookup("downside_p10") == pytest.approx(-0.031)
    assert bundle.lookup("projected_theme_exposure") == pytest.approx(0.18)
    assert bundle.lookup("nonexistent_metric") is None


def test_build_canonical_btst_evaluation_bundle_to_payload_coerces_numeric_values_and_preserves_missing_keys():
    bundle = build_canonical_btst_evaluation_bundle(
        {
            "next_close_positive_rate": "0.58",
            "next_close_payoff_ratio": 2,
            "downside_p10": "-0.031",
        }
    )

    payload = bundle.to_payload()

    assert payload["objective_metrics"]["next_close_positive_rate"] == pytest.approx(0.58)
    assert isinstance(payload["objective_metrics"]["next_close_positive_rate"], float)
    assert payload["objective_metrics"]["next_close_payoff_ratio"] == pytest.approx(2.0)
    assert isinstance(payload["objective_metrics"]["next_close_payoff_ratio"], float)
    assert payload["guardrail_metrics"]["downside_p10"] == pytest.approx(-0.031)
    assert isinstance(payload["guardrail_metrics"]["downside_p10"], float)
    assert payload["objective_metrics"]["next_close_expectancy"] is None
    assert payload["guardrail_metrics"]["incremental_theme_exposure"] is None
    assert payload["context_metrics"]["projected_theme_exposure"] is None


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


# ---------------------------------------------------------------------------
# Guardrail tests
# ---------------------------------------------------------------------------


def test_check_guardrails_passes_when_all_met():
    metrics = {"next_close_positive_rate": 0.60, "downside_p10": -0.02}
    violations = check_guardrails(metrics, {"next_close_positive_rate": 0.54, "downside_p10": -0.06})
    assert violations == []


def test_check_guardrails_detects_value_below_floor():
    metrics = {"next_close_positive_rate": 0.50, "downside_p10": -0.02}
    violations = check_guardrails(metrics, {"next_close_positive_rate": 0.54, "downside_p10": -0.06})
    assert "next_close_positive_rate" in violations
    assert "downside_p10" not in violations


def test_check_guardrails_treats_none_as_violation():
    metrics = {"next_close_positive_rate": None}
    violations = check_guardrails(metrics, {"next_close_positive_rate": 0.54})
    assert "next_close_positive_rate" in violations


def test_check_guardrails_treats_absent_key_as_violation():
    violations = check_guardrails({}, {"next_close_positive_rate": 0.54})
    assert "next_close_positive_rate" in violations


def test_run_param_search_guardrail_failing_trials_ranked_last():
    """Trials that violate guardrails must appear after all passing trials."""
    space = ParamSpace(grid={"x": [1, 2, 3]})

    # x=3 has the best score but violates the win-rate guardrail
    def evaluator(params):
        return {
            "sharpe_ratio": float(params["x"]),
            "sortino_ratio": float(params["x"]),
            "max_drawdown": -0.1,
            "next_close_positive_rate": 0.40 if params["x"] == 3 else 0.60,
        }

    report = run_param_search(
        space=space,
        objective=SearchObjective.COMPOSITE,
        evaluator=evaluator,
        guardrails={"next_close_positive_rate": 0.54},
    )

    passing = [r for r in report.results if not r.failed_guardrails]
    failing = [r for r in report.results if r.failed_guardrails]

    # All passing trials must come before failing ones in ranked list
    for p in passing:
        for f in failing:
            assert report.results.index(p) < report.results.index(f)

    # Best params must be from a passing trial, not x=3 (the highest scorer)
    assert report.best_params != {"x": 3}
    assert report.best_params in [{"x": 1}, {"x": 2}]

    # x=3 trial must have the win-rate guardrail in its failed_guardrails
    x3_trial = next(r for r in report.results if r.params["x"] == 3)
    assert "next_close_positive_rate" in x3_trial.failed_guardrails


def test_run_param_search_guardrail_all_failing_falls_back_to_best_overall():
    """When every trial violates guardrails best_params is still populated."""
    space = ParamSpace(grid={"x": [1, 2]})

    def evaluator(params):
        return {
            "sharpe_ratio": float(params["x"]),
            "sortino_ratio": 1.0,
            "max_drawdown": -0.1,
            "next_close_positive_rate": 0.40,  # always below floor
        }

    report = run_param_search(
        space=space,
        objective=SearchObjective.SHARPE,
        evaluator=evaluator,
        guardrails={"next_close_positive_rate": 0.54},
    )

    assert all(r.failed_guardrails for r in report.results), "all should fail"
    # Fallback: best_params reflects the overall top trial (x=2 has sharpe=2.0)
    assert report.best_params == {"x": 2}


def test_run_param_search_guardrail_checkpoint_roundtrip(tmp_path):
    """failed_guardrails must survive a checkpoint save/reload cycle."""
    cp_path = tmp_path / "checkpoint.json"
    space = ParamSpace(grid={"x": [1]})

    def evaluator(params):
        return {
            "sharpe_ratio": 1.0,
            "sortino_ratio": 1.0,
            "max_drawdown": -0.1,
            "next_close_positive_rate": 0.40,
        }

    run_param_search(
        space=space,
        objective=SearchObjective.SHARPE,
        evaluator=evaluator,
        checkpoint_path=cp_path,
        guardrails={"next_close_positive_rate": 0.54},
    )

    call_count = 0

    def evaluator2(params):
        nonlocal call_count
        call_count += 1
        return {"sharpe_ratio": 1.0, "sortino_ratio": 1.0, "max_drawdown": -0.1, "next_close_positive_rate": 0.40}

    report2 = run_param_search(
        space=space,
        objective=SearchObjective.SHARPE,
        evaluator=evaluator2,
        checkpoint_path=cp_path,
        guardrails={"next_close_positive_rate": 0.54},
    )

    assert call_count == 0, "should not re-evaluate; completed trial loaded from checkpoint"
    assert "next_close_positive_rate" in report2.results[0].failed_guardrails


def test_run_param_search_without_guardrails_unchanged_behavior():
    """Omitting guardrails must preserve the original ranking logic."""
    space = ParamSpace(grid={"x": [1, 2, 3]})

    def evaluator(params):
        return {"sharpe_ratio": float(params["x"]), "sortino_ratio": 1.0, "max_drawdown": -0.1}

    report = run_param_search(space=space, objective=SearchObjective.SHARPE, evaluator=evaluator)

    assert report.best_params == {"x": 3}
    assert all(not r.failed_guardrails for r in report.results)


def test_format_search_report_surfaces_guardrail_violations():
    """Markdown report must mention guardrail violations when any trial failed."""
    space = ParamSpace(grid={"x": [1, 2]})

    def evaluator(params):
        return {
            "sharpe_ratio": float(params["x"]),
            "sortino_ratio": 1.0,
            "max_drawdown": -0.1,
            "next_close_positive_rate": 0.40 if params["x"] == 2 else 0.60,
        }

    report = run_param_search(
        space=space,
        objective=SearchObjective.SHARPE,
        evaluator=evaluator,
        guardrails={"next_close_positive_rate": 0.54},
    )
    md = format_search_report(report)
    assert "guardrail" in md.lower()


def test_save_search_payload_includes_failed_guardrails(tmp_path):
    space = ParamSpace(grid={"x": [1]})

    def evaluator(params):
        return {
            "sharpe_ratio": 0.5,
            "sortino_ratio": 1.0,
            "max_drawdown": -0.1,
            "next_close_positive_rate": 0.40,
        }

    report = run_param_search(
        space=space,
        objective=SearchObjective.SHARPE,
        evaluator=evaluator,
        guardrails={"next_close_positive_rate": 0.54},
    )
    json_path = save_search_payload(report, tmp_path / "out.json")
    data = json.loads(json_path.read_text())
    assert "failed_guardrails" in data["results"][0]
    assert "next_close_positive_rate" in data["results"][0]["failed_guardrails"]
