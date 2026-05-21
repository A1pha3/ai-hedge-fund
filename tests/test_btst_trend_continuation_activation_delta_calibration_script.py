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
