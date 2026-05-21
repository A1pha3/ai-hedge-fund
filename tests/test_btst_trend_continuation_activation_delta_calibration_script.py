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


def test_run_calibration_calls_analysis_and_diagnostics(monkeypatch):
    calls = {"analyze": 0, "diagnostics": 0}
    def fake_analyze(*a, **k):
        calls["analyze"] += 1
        return {"rows": [], "variant_supports_t1_count": 1, "mixed_count": 0}
    def fake_diagnostics(analysis):
        calls["diagnostics"] += 1
        return {"execution_eligible_positive_window_count": 1}
    monkeypatch.setattr("scripts.btst_trend_continuation_activation_delta_calibration.analyze_btst_multi_window_profile_validation", fake_analyze)
    monkeypatch.setattr("scripts.btst_trend_continuation_activation_delta_calibration.build_trend_continuation_activation_delta_diagnostics", fake_diagnostics)
    result = calibration.run_calibration(reports_root="irrelevant")
    assert calls["analyze"] == len(calibration.CALIBRATION_CANDIDATES)
    assert calls["diagnostics"] == len(calibration.CALIBRATION_CANDIDATES)
    assert "ranked_candidates" in result


import subprocess
import tempfile
import json
from pathlib import Path

def test_cli_accepts_and_writes_outputs_inprocess(tmp_path):
    import scripts.btst_trend_continuation_activation_delta_calibration as calibration
    import shutil
    output_json = tmp_path / "out.json"
    output_md = tmp_path / "out.md"
    reports_root = tmp_path / "paper_trading_window_20240101_dummy_report"
    shutil.copytree("tests/fixtures/dummy_report", reports_root)
    # Call main([...]) directly
    rc = calibration.main([
        "--reports-root", str(reports_root),
        "--output-json", str(output_json),
        "--output-md", str(output_md),
    ])
    assert rc == 0
    assert output_json.exists()
    assert output_md.exists()
    with output_json.open(encoding="utf-8") as f:
        data = json.load(f)
    assert "best_candidate" in data
    assert data["best_candidate"] is not None
    best_name = data["best_candidate"].get("candidate_name")
    with output_md.open(encoding="utf-8") as f:
        md = f.read()
    assert "# Trend Continuation Activation Delta Calibration" in md
    assert f"- best_candidate: {best_name}" in md
