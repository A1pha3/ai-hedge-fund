from scripts.btst_trend_continuation_activation_delta_diagnostics import (
    build_trend_continuation_activation_delta_diagnostics,
)


def _analysis_with_rows(*rows: dict) -> dict:
    return {
        "baseline_profile": "trend_continuation_strength_v2",
        "variant_profile": "trend_continuation_strength_v3",
        "report_dir_count": len(rows),
        "rows": list(rows),
    }


def test_build_activation_delta_diagnostics_summarizes_zero_delta_reasons() -> None:
    payload = build_trend_continuation_activation_delta_diagnostics(
        _analysis_with_rows(
            {
                "report_label": "window_a",
                "runtime_activation_attribution": {
                    "selected_count_delta": 0,
                    "near_miss_count_delta": 0,
                    "execution_eligible_count_delta": 0,
                    "zero_delta_reason": "profile_variant_without_runtime_activation_delta",
                    "watchlist_shrink_guard_applied_count": 0,
                    "watchlist_shrink_selected_boundary_overlap_count": 0,
                },
            },
            {
                "report_label": "window_b",
                "runtime_activation_attribution": {
                    "selected_count_delta": 0,
                    "near_miss_count_delta": 0,
                    "execution_eligible_count_delta": 0,
                    "zero_delta_reason": "watchlist_shrink_guard_without_selected_boundary_overlap",
                    "watchlist_shrink_guard_applied_count": 1,
                    "watchlist_shrink_selected_boundary_overlap_count": 0,
                },
            },
        )
    )

    assert payload["report_dir_count"] == 2
    assert payload["zero_delta_reason_counts"] == {
        "profile_variant_without_runtime_activation_delta": 1,
        "watchlist_shrink_guard_without_selected_boundary_overlap": 1,
    }
    assert payload["execution_eligible_positive_window_count"] == 0
    assert payload["dominant_zero_delta_reason"] in payload["zero_delta_reason_counts"]


def test_cli_main_creates_expected_outputs(tmp_path):
    import sys
    import json
    from pathlib import Path
    from scripts import btst_trend_continuation_activation_delta_diagnostics as mod

    # Prepare minimal input
    input_data = {
        "baseline_profile": "trend_continuation_strength_v2",
        "variant_profile": "trend_continuation_strength_v3",
        "report_dir_count": 1,
        "rows": [
            {
                "report_label": "window_x",
                "runtime_activation_attribution": {
                    "selected_count_delta": 0,
                    "near_miss_count_delta": 0,
                    "execution_eligible_count_delta": 0,
                    "zero_delta_reason": "profile_variant_without_runtime_activation_delta",
                    "watchlist_shrink_guard_applied_count": 0,
                    "watchlist_shrink_selected_boundary_overlap_count": 0,
                },
            }
        ],
    }
    input_path = tmp_path / "input.json"
    json.dump(input_data, input_path.open("w"))
    json_out = tmp_path / "out.json"
    md_out = tmp_path / "out.md"

    # Run CLI main
    sys_argv = sys.argv
    sys.argv = [
        "btst_trend_continuation_activation_delta_diagnostics.py",
        "--input-json", str(input_path),
        "--output-json", str(json_out),
        "--output-md", str(md_out),
    ]
    try:
        mod.main()
    finally:
        sys.argv = sys_argv

    # Assert output files exist
    assert json_out.exists(), f"JSON output {json_out} does not exist"
    assert md_out.exists(), f"Markdown output {md_out} does not exist"

    # Assert markdown contains dominant reason and activation summary
    md = md_out.read_text()
    assert "profile_variant_without_runtime_activation_delta" in md
    assert "Dominant zero-delta reason" in md
    assert "Activation summary" in md

def test_build_activation_delta_diagnostics_flags_execution_eligible_surface_when_present() -> None:
    payload = build_trend_continuation_activation_delta_diagnostics(
        _analysis_with_rows(
            {
                "report_label": "window_a",
                "runtime_activation_attribution": {
                    "selected_count_delta": 0,
                    "near_miss_count_delta": 1,
                    "execution_eligible_count_delta": 1,
                    "activation_change_labels": ["near_miss_surface", "execution_eligible_surface"],
                    "zero_delta_reason": None,
                    "watchlist_shrink_guard_applied_count": 1,
                    "watchlist_shrink_selected_boundary_overlap_count": 1,
                },
            }
        )
    )

    assert payload["execution_eligible_positive_window_count"] == 1
    assert payload["windows_with_activation_change"] == ["window_a"]
    assert payload["all_windows_zero_delta"] is False
