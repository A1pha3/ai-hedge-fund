import json

import pytest

from scripts.btst_momentum_threshold_rollout_assessment import (
    build_momentum_threshold_rollout_assessment,
    main,
)

_PROMOTE_BACKTEST_SUMMARY = {
    "profile_name": "momentum_tuned_governed_v1",
    "daily_return_mean": 0.0020,
    "win_rate": 0.48,
    "payoff_ratio": 1.39,
    "positive_days": 11,
    "trading_days": 18,
}
_PROMOTE_MULTI_WINDOW = {
    "baseline_profile": "momentum_optimized",
    "variant_profile": "momentum_tuned_governed_v1",
    "report_dir_count": 3,
    "keep_baseline_count": 0,
    "variant_supports_t1_count": 3,
    "mixed_count": 0,
    "recommendation": "Variant is promising across the observed windows and may be ready for a deeper rollout review.",
    "rows": [{"report_dir": "paper_trading_window_1"}],
}


def test_momentum_threshold_rollout_promotes_when_backtest_and_windows_clear_guardrails() -> None:
    assessment = build_momentum_threshold_rollout_assessment(
        backtest_summary=_PROMOTE_BACKTEST_SUMMARY,
        multi_window_validation=_PROMOTE_MULTI_WINDOW,
    )

    assert assessment["action"] == "promote"
    assert assessment["blockers"] == []

    # Full payload contract
    assert set(assessment.keys()) == {"candidate_profile", "baseline_profile", "action", "blockers", "backtest_summary", "multi_window_validation"}
    assert assessment["candidate_profile"] == "momentum_tuned_governed_v1"
    assert assessment["baseline_profile"] == "momentum_optimized"
    assert assessment["backtest_summary"]["win_rate"] == pytest.approx(0.48)
    assert assessment["backtest_summary"]["payoff_ratio"] == pytest.approx(1.39)
    assert assessment["multi_window_validation"]["keep_baseline_count"] == 0
    assert assessment["multi_window_validation"]["variant_supports_t1_count"] == 3


def test_momentum_threshold_rollout_holds_when_zero_validation_windows() -> None:
    # Strong backtest, but no validation windows
    backtest_summary = {
        "profile_name": "momentum_tuned_governed_v1",
        "daily_return_mean": 0.0020,
        "win_rate": 0.50,
        "payoff_ratio": 1.50,
        "positive_days": 12,
        "trading_days": 18,
    }
    multi_window_validation = {
        "baseline_profile": "momentum_optimized",
        "variant_profile": "momentum_tuned_governed_v1",
        "report_dir_count": 0,
        "keep_baseline_count": 0,
        "variant_supports_t1_count": 0,
        "mixed_count": 0,
        "recommendation": "No matching report windows were found.",
        "rows": [],
    }
    assessment = build_momentum_threshold_rollout_assessment(
        backtest_summary=backtest_summary,
        multi_window_validation=multi_window_validation,
    )
    assert assessment["action"] == "hold"
    assert "multi_window_validation_missing" in assessment["blockers"]
    # Blockers should be precise
    assert len([b for b in assessment["blockers"] if b == "multi_window_validation_missing"]) == 1


def test_momentum_threshold_rollout_holds_when_window_validation_keeps_baseline() -> None:
    backtest_summary = {
        "profile_name": "momentum_tuned_governed_v1",
        "daily_return_mean": 0.0020,
        "win_rate": 0.48,
        "payoff_ratio": 1.39,
        "positive_days": 11,
        "trading_days": 18,
    }
    multi_window_validation = {
        "baseline_profile": "momentum_optimized",
        "variant_profile": "momentum_tuned_governed_v1",
        "report_dir_count": 3,
        "keep_baseline_count": 1,
        "variant_supports_t1_count": 0,
        "mixed_count": 2,
        "recommendation": "Baseline should remain the default: the variant loses T+1 edge in at least one window without offsetting T+1 improvement elsewhere.",
        "rows": [{"report_dir": "paper_trading_window_1"}],
    }

    assessment = build_momentum_threshold_rollout_assessment(
        backtest_summary=backtest_summary,
        multi_window_validation=multi_window_validation,
    )

    assert assessment["action"] == "hold"
    assert "window_validation_keeps_baseline" in assessment["blockers"]


def test_momentum_threshold_rollout_holds_when_backtest_payoff_is_below_round82_reference() -> None:
    backtest_summary = {
        "profile_name": "momentum_tuned_governed_v1",
        "daily_return_mean": 0.0020,
        "win_rate": 0.48,
        "payoff_ratio": 1.38,
        "positive_days": 11,
        "trading_days": 18,
    }
    multi_window_validation = {
        "baseline_profile": "momentum_optimized",
        "variant_profile": "momentum_tuned_governed_v1",
        "report_dir_count": 3,
        "keep_baseline_count": 0,
        "variant_supports_t1_count": 3,
        "mixed_count": 0,
        "recommendation": "Variant is promising across the observed windows and may be ready for a deeper rollout review.",
        "rows": [{"report_dir": "paper_trading_window_1"}],
    }

    assessment = build_momentum_threshold_rollout_assessment(
        backtest_summary=backtest_summary,
        multi_window_validation=multi_window_validation,
    )

    assert assessment["action"] == "hold"
    assert "backtest_payoff_below_round82_reference" in assessment["blockers"]


def test_momentum_threshold_rollout_holds_when_backtest_win_rate_is_below_round82_reference() -> None:
    backtest_summary = {
        "profile_name": "momentum_tuned_governed_v1",
        "daily_return_mean": 0.0020,
        "win_rate": 0.47,
        "payoff_ratio": 1.39,
        "positive_days": 11,
        "trading_days": 18,
    }
    multi_window_validation = {
        "baseline_profile": "momentum_optimized",
        "variant_profile": "momentum_tuned_governed_v1",
        "report_dir_count": 3,
        "keep_baseline_count": 0,
        "variant_supports_t1_count": 3,
        "mixed_count": 0,
        "recommendation": "Variant is promising across the observed windows and may be ready for a deeper rollout review.",
        "rows": [{"report_dir": "paper_trading_window_1"}],
    }

    assessment = build_momentum_threshold_rollout_assessment(
        backtest_summary=backtest_summary,
        multi_window_validation=multi_window_validation,
    )

    assert assessment["action"] == "hold"
    assert "backtest_win_rate_below_round82_reference" in assessment["blockers"]


def test_cli_main_creates_output_files_and_validates_content(tmp_path: pytest.TempPathFactory) -> None:
    backtest_json = tmp_path / "backtest.json"
    multi_window_json = tmp_path / "multi_window.json"
    out_json = tmp_path / "assessment.json"
    out_md = tmp_path / "assessment.md"

    backtest_json.write_text(json.dumps(_PROMOTE_BACKTEST_SUMMARY), encoding="utf-8")
    multi_window_json.write_text(json.dumps(_PROMOTE_MULTI_WINDOW), encoding="utf-8")

    exit_code = main(
        [
            "--backtest-json",
            str(backtest_json),
            "--multi-window-json",
            str(multi_window_json),
            "--output-json",
            str(out_json),
            "--output-md",
            str(out_md),
        ]
    )

    assert exit_code == 0
    assert out_json.exists(), "JSON output not created"
    assert out_md.exists(), "Markdown output not created"

    result = json.loads(out_json.read_text(encoding="utf-8"))
    assert result["action"] == "promote"
    assert result["blockers"] == []
    assert result["candidate_profile"] == "momentum_tuned_governed_v1"
    assert result["baseline_profile"] == "momentum_optimized"
    assert "backtest_summary" in result
    assert "multi_window_validation" in result

    md = out_md.read_text(encoding="utf-8")
    assert "# Momentum Threshold Rollout Assessment" in md
    assert "**promote**" in md
    assert "momentum_tuned_governed_v1" in md
    assert "momentum_optimized" in md
    assert "- none" in md  # no blockers


def test_momentum_threshold_rollout_holds_when_multi_window_validation_has_no_report_windows() -> None:
    assessment = build_momentum_threshold_rollout_assessment(
        backtest_summary=_PROMOTE_BACKTEST_SUMMARY,
        multi_window_validation={
            "baseline_profile": "momentum_optimized",
            "variant_profile": "momentum_tuned_governed_v1",
            "report_dir_count": 0,
            "keep_baseline_count": 0,
            "variant_supports_t1_count": 0,
            "mixed_count": 0,
            "recommendation": "No matching report windows were found.",
            "rows": [],
        },
    )

    assert assessment["action"] == "hold"
    assert "multi_window_validation_missing" in assessment["blockers"]
