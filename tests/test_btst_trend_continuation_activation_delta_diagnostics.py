import json
from pathlib import Path

from scripts.btst_trend_continuation_activation_delta_diagnostics import (
    build_trend_continuation_activation_delta_diagnostics,
    main,
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


def test_cli_main_creates_expected_outputs(tmp_path: Path) -> None:
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
    input_path.write_text(json.dumps(input_data), encoding="utf-8")
    json_out = tmp_path / "out.json"
    md_out = tmp_path / "out.md"

    result = main(
        [
            "--input-json", str(input_path),
            "--output-json", str(json_out),
            "--output-md", str(md_out),
        ]
    )

    assert result == 0
    assert json_out.exists()
    assert md_out.exists()

    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["dominant_zero_delta_reason"] == "profile_variant_without_runtime_activation_delta"
    markdown = md_out.read_text(encoding="utf-8")
    assert "# Trend Continuation Activation Delta Diagnostics" in markdown
    assert "profile_variant_without_runtime_activation_delta: 1" in markdown

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
