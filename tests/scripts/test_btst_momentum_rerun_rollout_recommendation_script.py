from __future__ import annotations

import json
from pathlib import Path

import scripts.btst_momentum_rerun_rollout_recommendation as recommendation


def test_build_rerun_recommendation_advances_rollout_recheck_when_winner_stays_clear() -> None:
    payload = recommendation.build_momentum_rerun_rollout_recommendation(
        pack={
            "winner": {"trial_index": 602, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
            "challengers": [{"trial_index": 1226, "cross_window_blocker_count": 1, "risk_blocker_count": 1}],
            "release_posture": "hold",
            "dominant_family": "cross_window_stability",
            "missing_theme_exposure_window_count": 2,
        }
    )

    assert payload["action"] == "advance_rollout_recheck"
    assert payload["release_posture"] == "hold"


def test_build_rerun_recommendation_falls_back_to_measurement_repair_when_observability_dominates() -> None:
    payload = recommendation.build_momentum_rerun_rollout_recommendation(
        pack={
            "winner": {"trial_index": 602, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
            "challengers": [],
            "release_posture": "hold",
            "dominant_family": "missing_observability",
            "missing_theme_exposure_window_count": 4,
        }
    )

    assert payload["action"] == "fallback_measurement_repair"


def test_main_writes_rerun_recommendation_outputs(tmp_path: Path) -> None:
    pack_json = tmp_path / "pack.json"
    output_json = tmp_path / "recommendation.json"
    output_md = tmp_path / "recommendation.md"
    pack_json.write_text(
        json.dumps(
            {
                "winner": {"trial_index": 602, "cross_window_blocker_count": 1, "risk_blocker_count": 1},
                "challengers": [{"trial_index": 1226, "cross_window_blocker_count": 1, "risk_blocker_count": 1}],
                "release_posture": "hold",
                "dominant_family": "cross_window_stability",
                "missing_theme_exposure_window_count": 2,
            }
        ),
        encoding="utf-8",
    )

    result = recommendation.main(
        [
            "--pack-json",
            str(pack_json),
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
