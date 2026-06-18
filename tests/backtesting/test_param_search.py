import json
from pathlib import Path

import pytest

from src.backtesting.evaluation_bundle import build_canonical_btst_evaluation_bundle
from src.backtesting.param_search import (
    check_guardrails,
    compute_objective_score,
    format_search_report,
    ParamSpace,
    run_param_search,
    save_search_payload,
    save_search_report,
    SearchObjective,
    TrialResult,
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


def test_build_canonical_btst_evaluation_bundle_treats_malformed_metric_values_as_missing():
    bundle = build_canonical_btst_evaluation_bundle(
        {
            "next_close_positive_rate": "",
            "downside_p10": "N/A",
            "projected_theme_exposure": "bad-value",
        }
    )

    payload = bundle.to_payload()

    assert payload["objective_metrics"]["next_close_positive_rate"] is None
    assert payload["guardrail_metrics"]["downside_p10"] is None
    assert payload["context_metrics"]["projected_theme_exposure"] is None


def test_build_canonical_btst_evaluation_bundle_treats_non_finite_metric_values_as_missing():
    bundle = build_canonical_btst_evaluation_bundle(
        {
            "next_close_positive_rate": float("nan"),
            "downside_p10": float("inf"),
            "projected_theme_exposure": float("-inf"),
        }
    )

    payload = bundle.to_payload()

    assert payload["objective_metrics"]["next_close_positive_rate"] is None
    assert payload["guardrail_metrics"]["downside_p10"] is None
    assert payload["context_metrics"]["projected_theme_exposure"] is None


def test_compute_objective_score_btst_returns_none_for_non_finite_metrics_even_with_bonus_inputs() -> None:
    metrics = {
        "next_close_positive_rate": 0.62,
        "next_close_payoff_ratio": 1.8,
        "next_close_expectancy": 0.012,
        "next_high_hit_rate": float("nan"),
        "t_plus_2_close_positive_rate": 0.56,
        "t_plus_3_close_positive_rate": 0.54,
        "t_plus_3_close_expectancy": 0.011,
        "downside_p10": -0.02,
        "sample_weight": 0.8,
        "promotion_guardrail_pass": True,
        "baseline_next_close_positive_rate_delta": 0.03,
        "baseline_next_close_expectancy_delta": 0.004,
    }
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


def test_load_checkpoint_corrupt_falls_back_to_empty(tmp_path, caplog):
    """R88 drain: 损坏的 checkpoint.json (运行中断 / 磁盘错误 / 部分写入) 不应让
    整个 --param-search JSONDecodeError 崩溃丢失已完成 trials, 而应回退空 checkpoint
    并发 warning 诊断 (用户可决定是否重新搜索)。

    bug 复现: _load_checkpoint 裸 json.load(f), checkpoint 损坏时整个 param search
    中断, 数小时已完成 trials 全部需要重跑。
    """
    import logging as _logging

    from src.backtesting.param_search import _load_checkpoint

    cp_path = tmp_path / "checkpoint.json"
    cp_path.write_text("{partial write, not valid json", encoding="utf-8")

    with caplog.at_level(_logging.WARNING, logger="src.backtesting.param_search"):
        result = _load_checkpoint(cp_path)
    # 应回退空 checkpoint (空 completed_trials), 而非抛 JSONDecodeError
    assert result == {"completed_trials": []}, (
        f"损坏 checkpoint 应回退空结构而非崩溃; got result={result!r}"
    )
    warn_msgs = [r.message for r in caplog.records if r.levelno >= _logging.WARNING]
    assert any("checkpoint" in m.lower() or "损坏" in m for m in warn_msgs), (
        f"损坏 checkpoint 应触发 warning 诊断; got warnings={warn_msgs!r}"
    )


def test_save_checkpoint_is_atomic_no_partial_file_on_crash(tmp_path, monkeypatch):
    """R93 family drain (write-side): _save_checkpoint must use atomic write
    (temp-file + os.replace) so a crash mid-write never leaves a truncated
    checkpoint at the canonical path. A partial write would force the next
    run into the R88 corrupt-fallback path, silently losing all completed
    trials even though the data was successfully computed.

    bug 复现: _save_checkpoint 用裸 open(path, "w") + json.dump; 进程在
    json.dump 中途被 SIGKILL/OOM 留下截断文件, 下次启动 _load_checkpoint
    触发 R88 fallback 回退空 checkpoint, 数小时已完成 trials 全部丢失。

    verification strategy: monkeypatch os.replace to simulate a crash before
    the atomic rename — the canonical path must remain in its prior valid
    state (or absent if first write), never a partial file.
    """
    import os
    import json

    from src.backtesting.param_search import _save_checkpoint, _load_checkpoint

    cp_path = tmp_path / "checkpoint.json"

    # 1. Successful initial write establishes a valid baseline.
    baseline_data = {"completed_trials": [{"params": {"a": 1}, "score": 0.5}]}
    _save_checkpoint(cp_path, baseline_data)
    assert cp_path.exists()
    # Canonical path holds complete valid JSON, not a partial write.
    assert _load_checkpoint(cp_path) == baseline_data

    # 2. Simulate a crash during the SECOND write by breaking os.replace:
    #    the temp file is written but never renamed onto the canonical path.
    real_replace = os.replace
    replace_calls: list = []

    def _failing_replace(src, dst):
        replace_calls.append((src, dst))
        raise OSError("simulated crash before atomic rename")

    monkeypatch.setattr("src.backtesting.param_search.os.replace", _failing_replace)

    new_data = {"completed_trials": [{"params": {"a": 2}, "score": 0.9}]}
    try:
        _save_checkpoint(cp_path, new_data)
    except OSError:
        pass  # caller is informed the checkpoint was not persisted

    # 3. Canonical path still holds the BASELINE (prior valid) data,
    #    never a truncated/partial file. This is the atomic-write guarantee.
    assert cp_path.exists(), "canonical checkpoint must remain after failed rename"
    recovered = _load_checkpoint(cp_path)
    assert recovered == baseline_data, (
        f"atomic write must preserve prior valid checkpoint on crash; "
        f"got {recovered!r}, expected baseline {baseline_data!r}"
    )

    # 4. No stray temp files left in the directory (cleanup-on-failure).
    stray_tmps = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert not stray_tmps, f"failed atomic write must clean up temp file; got {stray_tmps}"

    # 5. Once os.replace works again, a fresh write succeeds normally.
    monkeypatch.setattr("src.backtesting.param_search.os.replace", real_replace)
    _save_checkpoint(cp_path, new_data)
    assert _load_checkpoint(cp_path) == new_data


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


def test_compute_objective_score_btst_returns_none_when_candidate_fails_guardrails() -> None:
    metrics = {
        "next_close_positive_rate": 0.62,
        "next_close_payoff_ratio": 1.8,
        "next_close_expectancy": 0.012,
        "next_high_hit_rate": 0.58,
        "t_plus_2_close_positive_rate": 0.56,
        "t_plus_3_close_positive_rate": 0.54,
        "t_plus_3_close_expectancy": 0.011,
        "downside_p10": -0.02,
        "sample_weight": 0.8,
        "promotion_guardrail_pass": False,
    }
    assert compute_objective_score(metrics, SearchObjective.BTST) is None


def test_compute_objective_score_btst_rewards_baseline_delta_when_guardrails_pass() -> None:
    metrics = {
        "next_close_positive_rate": 0.62,
        "next_close_payoff_ratio": 1.8,
        "next_close_expectancy": 0.012,
        "next_high_hit_rate": 0.58,
        "t_plus_2_close_positive_rate": 0.56,
        "t_plus_3_close_positive_rate": 0.54,
        "t_plus_3_close_expectancy": 0.011,
        "downside_p10": -0.02,
        "sample_weight": 0.8,
        "promotion_guardrail_pass": True,
        "baseline_next_close_positive_rate_delta": 0.03,
        "baseline_next_close_expectancy_delta": 0.004,
    }
    score = compute_objective_score(metrics, SearchObjective.BTST)
    assert score is not None
    assert score > 0.47


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


def test_check_guardrails_treats_partial_horizon_canonical_metric_absence_as_violation_even_with_fallback_fields():
    metrics = {
        "next_close_positive_rate": 0.60,
        "next_close_payoff_ratio": 2.0,
        "next_close_expectancy": 0.01,
        "next_high_hit_rate": 0.50,
        "t_plus_3_close_positive_rate": 0.58,
        "t_plus_3_close_expectancy": 0.012,
        "downside_p10": -0.02,
        "sample_weight": 0.80,
    }

    violations = check_guardrails(
        metrics,
        {
            "next_close_positive_rate": 0.54,
            "t_plus_2_close_positive_rate": 0.54,
        },
    )

    assert violations == ["t_plus_2_close_positive_rate"]


def test_check_guardrails_treats_malformed_partial_horizon_canonical_metric_as_violation():
    metrics = {
        "next_close_positive_rate": 0.60,
        "t_plus_2_close_positive_rate": "N/A",
        "t_plus_3_close_positive_rate": 0.53,
    }

    violations = check_guardrails(
        metrics,
        {
            "next_close_positive_rate": 0.54,
            "t_plus_2_close_positive_rate": 0.54,
        },
    )

    assert violations == ["t_plus_2_close_positive_rate"]


def test_check_guardrails_treats_raw_only_guardrail_metric_as_violation_when_canonical_key_is_absent():
    metrics = {
        "next_close_positive_rate": 0.60,
        "t_plus_2_close_positive_rate_raw_100": 72.0,
    }

    violations = check_guardrails(
        metrics,
        {
            "next_close_positive_rate": 0.54,
            "t_plus_2_close_positive_rate": 0.54,
        },
    )

    assert violations == ["t_plus_2_close_positive_rate"]


def test_check_guardrails_treats_custom_malformed_string_as_violation():
    violations = check_guardrails({"custom_metric": "N/A"}, {"custom_metric": 0.54})
    assert violations == ["custom_metric"]


def test_check_guardrails_treats_custom_non_finite_value_as_violation():
    violations = check_guardrails({"custom_metric": float("inf")}, {"custom_metric": 0.54})
    assert violations == ["custom_metric"]


def test_check_guardrails_supports_explicit_max_bounds():
    metrics = {
        "projected_theme_exposure": 0.18,
        "crowding_risk_raw_100": 68.0,
    }

    violations = check_guardrails(
        metrics,
        {
            "projected_theme_exposure": {"max": 0.20},
            "crowding_risk_raw_100": {"max": 70.0},
        },
    )

    assert violations == []


def test_check_guardrails_detects_mixed_min_and_max_bound_violations():
    metrics = {
        "next_close_positive_rate": 0.53,
        "projected_theme_exposure": 0.21,
    }

    violations = check_guardrails(
        metrics,
        {
            "next_close_positive_rate": {"min": 0.54},
            "projected_theme_exposure": {"max": 0.20},
        },
    )

    assert violations == ["next_close_positive_rate", "projected_theme_exposure"]


def test_check_guardrails_skip_if_null_suppresses_none_violation():
    """skip_if_null=True on a dict spec must not count a None metric as a violation."""
    violations = check_guardrails(
        {"projected_theme_exposure": None},
        {"projected_theme_exposure": {"max": 0.35, "skip_if_null": True}},
    )
    assert violations == []


def test_check_guardrails_skip_if_null_still_catches_bound_breach_when_value_present():
    """skip_if_null=True must not suppress a violation when a real value breaches the bound."""
    violations = check_guardrails(
        {"projected_theme_exposure": 0.40},
        {"projected_theme_exposure": {"max": 0.35, "skip_if_null": True}},
    )
    assert "projected_theme_exposure" in violations


def test_check_guardrails_skip_if_null_false_still_treats_none_as_violation():
    """Explicit skip_if_null=False must preserve the original violation-on-null behaviour."""
    violations = check_guardrails(
        {"projected_theme_exposure": None},
        {"projected_theme_exposure": {"max": 0.35, "skip_if_null": False}},
    )
    assert "projected_theme_exposure" in violations


def test_check_guardrails_default_btst_replay_guardrails_skip_theme_exposure_when_null():
    """DEFAULT_BTST_REPLAY_GUARDRAILS theme-exposure entries must not violate when None.

    This validates the fix for the 4-day sparse-window scenario where
    projected_theme_exposure and incremental_theme_exposure cannot be computed.
    """
    from scripts.optimize_profile import DEFAULT_BTST_REPLAY_GUARDRAILS

    metrics = {
        "next_close_positive_rate": 0.56,
        "next_high_hit_rate": 0.58,
        "downside_p10": -0.04,
        "window_coverage": 0.80,
        "projected_theme_exposure": None,
        "incremental_theme_exposure": None,
        "liquidity_capacity_raw_100": 50.0,
        "crowding_risk_raw_100": 30.0,
        "gap_risk_raw_100": 20.0,
    }

    violations = check_guardrails(metrics, DEFAULT_BTST_REPLAY_GUARDRAILS)
    assert "projected_theme_exposure" not in violations
    assert "incremental_theme_exposure" not in violations


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


def test_run_param_search_ranks_trials_last_when_explicit_max_guardrail_is_breached():
    space = ParamSpace(grid={"x": [1, 2]})

    def evaluator(params):
        return {
            "sharpe_ratio": float(params["x"]),
            "sortino_ratio": 1.0,
            "max_drawdown": -0.1,
            "projected_theme_exposure": 0.18 if params["x"] == 1 else 0.24,
        }

    report = run_param_search(
        space=space,
        objective=SearchObjective.SHARPE,
        evaluator=evaluator,
        guardrails={"projected_theme_exposure": {"max": 0.20}},
    )

    assert report.best_params == {"x": 1}
    assert report.results[-1].params == {"x": 2}
    assert report.results[-1].failed_guardrails == ("projected_theme_exposure",)


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


def test_run_param_search_persists_failed_guardrails_for_every_trial_in_checkpoint(tmp_path):
    cp_path = tmp_path / "checkpoint.json"
    space = ParamSpace(grid={"x": [1, 2]})

    def evaluator(params):
        if params["x"] == 1:
            return {
                "sharpe_ratio": 0.5,
                "sortino_ratio": 1.0,
                "max_drawdown": -0.1,
                "next_close_positive_rate": 0.60,
            }
        return {
            "sharpe_ratio": 0.4,
            "sortino_ratio": 1.0,
            "max_drawdown": -0.1,
            "next_close_positive_rate": 0.40,
        }

    report = run_param_search(
        space=space,
        objective=SearchObjective.SHARPE,
        evaluator=evaluator,
        checkpoint_path=cp_path,
        guardrails={"next_close_positive_rate": 0.54},
    )

    payload = json.loads(cp_path.read_text())
    completed_by_x = {item["params"]["x"]: item["failed_guardrails"] for item in payload["completed_trials"]}

    assert report.completed_trials == 2
    assert len(payload["completed_trials"]) == 2
    assert completed_by_x[1] == []
    assert completed_by_x[2] == ["next_close_positive_rate"]


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


# ---------------------------------------------------------------------------
# Tests for BTST runner objective (Task 2)
# ---------------------------------------------------------------------------


def test_compute_objective_score_btst_runner_prioritizes_tail_hits_without_ignoring_t1() -> None:
    metrics = {
        "promotion_guardrail_pass": True,
        "max_future_high_return_2_5d_hit_rate_at_15pct": 0.48,
        "max_future_high_return_2_5d_hit_rate_at_20pct": 0.32,
        "runner_capture_count": 14,
        "median_max_future_high_return_2_5d": 0.18,
        "time_to_hit_15pct_median": 2.0,
        "time_to_hit_20pct_median": 3.0,
        "next_open_return": 0.01,
        "next_open_to_close_return": 0.02,
        "next_close_positive_rate": 0.58,
        "downside_p10": -0.025,
        "sample_weight": 0.8,
    }

    score = compute_objective_score(metrics, SearchObjective.BTST_RUNNER)

    assert score is not None
    assert score > 0.0


def test_compute_objective_score_btst_runner_rewards_15pct_hit_improvement() -> None:
    metrics = {
        "promotion_guardrail_pass": True,
        "max_future_high_return_2_5d_hit_rate_at_15pct": 0.35,
        "max_future_high_return_2_5d_hit_rate_at_20pct": 0.18,
        "runner_capture_count": 10,
        "median_max_future_high_return_2_5d": 0.17,
        "time_to_hit_15pct_median": 2.0,
        "time_to_hit_20pct_median": 3.0,
        "next_open_return": 0.01,
        "next_open_to_close_return": 0.02,
        "next_close_positive_rate": 0.58,
        "downside_p10": -0.025,
        "sample_weight": 0.8,
    }

    stronger_objective_metrics = {**metrics, "max_future_high_return_2_5d_hit_rate_at_15pct": 0.65}

    base_score = compute_objective_score(metrics, SearchObjective.BTST_RUNNER)
    stronger_score = compute_objective_score(stronger_objective_metrics, SearchObjective.BTST_RUNNER)

    assert base_score is not None
    assert stronger_score is not None
    assert stronger_score > base_score
