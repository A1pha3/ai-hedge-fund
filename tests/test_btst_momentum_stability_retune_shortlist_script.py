import json
from pathlib import Path

import pytest

import scripts.btst_momentum_stability_retune_shortlist as shortlist


def test_build_retune_shortlist_prefers_lower_stability_pressure_without_worsening_risk() -> None:
    payload = shortlist.build_momentum_stability_retune_shortlist(
        results=[
            {
                "trial_index": 10,
                "params": {"select_threshold": 0.46},
                "comparison_summary": {
                    "momentum_optimized": {"win_rate_window_trend_delta": -0.02, "gate_above_threshold_cv_delta": 0.0, "max_drawdown_simulated_delta": 0.0},
                    "default": {"win_rate_cv_delta": -0.01, "t_plus_3_close_payoff_ratio_delta": 0.0},
                },
            },
            {
                "trial_index": 11,
                "params": {"select_threshold": 0.46},
                "comparison_summary": {
                    "momentum_optimized": {"win_rate_window_trend_delta": 0.01, "gate_above_threshold_cv_delta": 0.0, "max_drawdown_simulated_delta": 0.0},
                    "default": {"win_rate_cv_delta": 0.0, "t_plus_3_close_payoff_ratio_delta": 0.0},
                },
            },
        ],
        surface={"grid": {"select_threshold": [0.42, 0.46, 0.5]}, "fixed_params": {"momentum_strength_weight": 0.0, "short_term_reversal_weight": 0.0}},
    )

    assert payload["candidate_count"] == 2
    assert payload["best_candidate"]["trial_index"] == 11
    assert payload["best_candidate"]["cross_window_blocker_count"] == 0


def test_build_retune_shortlist_fails_closed_when_no_local_candidates_match_surface() -> None:
    with pytest.raises(SystemExit, match="local retune candidates"):
        shortlist.build_momentum_stability_retune_shortlist(
            results=[{"trial_index": 1, "params": {"select_threshold": 0.6}, "comparison_summary": {}}],
            surface={"grid": {"select_threshold": [0.42, 0.46, 0.5]}, "fixed_params": {"momentum_strength_weight": 0.0, "short_term_reversal_weight": 0.0}},
        )


def test_main_writes_shortlist_outputs(tmp_path: Path) -> None:
    source_json = tmp_path / "source.json"
    surface_json = tmp_path / "surface.json"
    output_json = tmp_path / "shortlist.json"
    output_md = tmp_path / "shortlist.md"
    source_json.write_text(json.dumps({"results": [{"trial_index": 11, "params": {"select_threshold": 0.46, "momentum_strength_weight": 0.0, "short_term_reversal_weight": 0.0}, "comparison_summary": {"momentum_optimized": {"win_rate_window_trend_delta": 0.01}, "default": {"win_rate_cv_delta": 0.0}}}]}), encoding="utf-8")
    surface_json.write_text(json.dumps({"grid": {"select_threshold": [0.42, 0.46, 0.5]}, "fixed_params": {"momentum_strength_weight": 0.0, "short_term_reversal_weight": 0.0}}), encoding="utf-8")

    result = shortlist.main(
        [
            "--source-json",
            str(source_json),
            "--surface-json",
            str(surface_json),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ]
    )

    assert result == 0
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["candidate_count"] == 1
    assert output_md.exists()
