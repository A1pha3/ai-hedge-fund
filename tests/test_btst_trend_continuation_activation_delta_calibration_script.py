import json
from pathlib import Path

import scripts.btst_trend_continuation_activation_delta_calibration as calibration


def test_rank_calibration_candidates_prefers_execution_eligible_activation_then_t1_support() -> None:
    ranked = calibration.rank_calibration_candidates(
        [
            {
                "candidate_name": "tight",
                "diagnostics": {"execution_eligible_positive_window_count": 0, "all_windows_zero_delta": True},
                "analysis": {"variant_supports_t1_count": 0, "mixed_count": 2},
            },
            {
                "candidate_name": "balanced",
                "diagnostics": {"execution_eligible_positive_window_count": 2, "all_windows_zero_delta": False},
                "analysis": {"variant_supports_t1_count": 1, "mixed_count": 1},
            },
        ]
    )

    assert ranked[0]["candidate_name"] == "balanced"


def test_build_candidate_overrides_keeps_scope_inside_v3_shrink_parameters() -> None:
    candidate = calibration.CALIBRATION_CANDIDATES[0]

    assert set(candidate["profile_overrides"].keys()) <= {
        "watchlist_filter_diagnostics_selected_only_shrink_select_threshold_lift",
        "watchlist_filter_diagnostics_selected_only_shrink_catalyst_freshness_max",
        "watchlist_filter_diagnostics_selected_only_shrink_trend_acceleration_max",
        "watchlist_filter_diagnostics_selected_only_shrink_close_strength_max",
    }


def test_run_calibration_calls_validation_and_diagnostics_for_each_candidate(monkeypatch) -> None:
    captured_calls: list[dict[str, object]] = []

    def fake_analyze(reports_root, *, baseline_profile, variant_profile, variant_profile_overrides):
        captured_calls.append(
            {
                "reports_root": reports_root,
                "baseline_profile": baseline_profile,
                "variant_profile": variant_profile,
                "variant_profile_overrides": dict(variant_profile_overrides),
            }
        )
        return {
            "baseline_profile": baseline_profile,
            "variant_profile": variant_profile,
            "variant_supports_t1_count": 1,
            "mixed_count": 0,
            "rows": [],
        }

    def fake_diagnostics(analysis):
        return {
            "all_windows_zero_delta": False,
            "execution_eligible_positive_window_count": 1,
            "analysis_variant_profile": analysis["variant_profile"],
        }

    monkeypatch.setattr(calibration, "analyze_btst_multi_window_profile_validation", fake_analyze)
    monkeypatch.setattr(calibration, "build_trend_continuation_activation_delta_diagnostics", fake_diagnostics)

    payload = calibration.run_calibration(reports_root=Path("/tmp/reports"))

    assert len(captured_calls) == len(calibration.CALIBRATION_CANDIDATES)
    assert all(call["baseline_profile"] == "trend_continuation_strength_v2" for call in captured_calls)
    assert all(call["variant_profile"] == "trend_continuation_strength_v3" for call in captured_calls)
    assert payload["best_candidate"]["diagnostics"]["execution_eligible_positive_window_count"] == 1


def test_main_writes_json_and_markdown_outputs(tmp_path: Path, monkeypatch) -> None:
    output_json = tmp_path / "calibration.json"
    output_md = tmp_path / "calibration.md"

    monkeypatch.setattr(
        calibration,
        "run_calibration",
        lambda *, reports_root: {
            "baseline_profile": "trend_continuation_strength_v2",
            "candidate_profile": "trend_continuation_strength_v3",
            "ranked_candidates": [
                {
                    "candidate_name": "lift_0p03_relaxed_close",
                    "diagnostics": {"execution_eligible_positive_window_count": 2},
                    "analysis": {"variant_supports_t1_count": 1, "mixed_count": 0},
                }
            ],
            "best_candidate": {
                "candidate_name": "lift_0p03_relaxed_close",
                "diagnostics": {"execution_eligible_positive_window_count": 2},
                "analysis": {"variant_supports_t1_count": 1, "mixed_count": 0},
            },
        },
    )

    result = calibration.main(
        [
            "--reports-root",
            str(tmp_path / "reports"),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ]
    )

    assert result == 0
    assert output_json.exists()
    assert output_md.exists()

    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["best_candidate"]["candidate_name"] == "lift_0p03_relaxed_close"

    markdown = output_md.read_text(encoding="utf-8")
    assert "# Trend Continuation Activation Delta Calibration" in markdown
    assert "best_candidate: lift_0p03_relaxed_close" in markdown
