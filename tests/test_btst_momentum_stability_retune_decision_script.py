from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.btst_momentum_stability_retune_decision as decision


def test_build_retune_decision_requests_rollout_recheck_when_stability_blockers_drop() -> None:
    payload = decision.build_momentum_stability_retune_decision(
        shortlist={"best_candidate": {"trial_index": 11, "cross_window_blocker_count": 2, "risk_blocker_count": 0}, "candidate_count": 3},
        triage={"dominant_family": "cross_window_stability", "blocker_count": 27, "missing_theme_exposure_window_count": 2},
    )

    assert payload["action"] == "rerun_rollout_check"
    assert payload["release_posture"] == "hold"


def test_build_retune_decision_falls_back_to_measurement_repair_when_observability_dominates_again() -> None:
    payload = decision.build_momentum_stability_retune_decision(
        shortlist={"best_candidate": {"trial_index": 11, "cross_window_blocker_count": 1, "risk_blocker_count": 0}, "candidate_count": 2},
        triage={"dominant_family": "missing_observability", "blocker_count": 8, "missing_theme_exposure_window_count": 4},
    )

    assert payload["action"] == "fallback_measurement_repair"


def test_main_writes_retune_decision_outputs(tmp_path: Path) -> None:
    shortlist_json = tmp_path / "shortlist.json"
    triage_json = tmp_path / "triage.json"
    output_json = tmp_path / "decision.json"
    output_md = tmp_path / "decision.md"
    shortlist_json.write_text(json.dumps({"best_candidate": {"trial_index": 11, "cross_window_blocker_count": 4, "risk_blocker_count": 1}, "candidate_count": 2}), encoding="utf-8")
    triage_json.write_text(json.dumps({"dominant_family": "cross_window_stability", "blocker_count": 27, "missing_theme_exposure_window_count": 2}), encoding="utf-8")

    result = decision.main(
        [
            "--shortlist-json",
            str(shortlist_json),
            "--triage-json",
            str(triage_json),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ]
    )

    assert result == 0
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["action"] == "retain_hold"
    assert output_md.exists()


def test_build_retune_decision_fails_closed_when_best_candidate_trial_index_missing() -> None:
    with pytest.raises(SystemExit, match="trial_index"):
        decision.build_momentum_stability_retune_decision(
            shortlist={"best_candidate": {"cross_window_blocker_count": 1, "risk_blocker_count": 0}, "candidate_count": 2},
            triage={"dominant_family": "cross_window_stability", "blocker_count": 8, "missing_theme_exposure_window_count": 1},
        )
