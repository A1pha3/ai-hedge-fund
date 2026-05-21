from __future__ import annotations

import json
from pathlib import Path

import scripts.btst_momentum_rollout_triage_recommendation as recommendation


def test_build_triage_recommendation_prefers_measurement_fix_when_missing_observability_dominates() -> None:
    payload = recommendation.build_momentum_rollout_triage_recommendation(
        dossier={"dominant_family": "missing_observability", "blocker_count": 4},
        attribution={"windows_missing_theme_exposure": ["window_a", "window_b"], "window_count": 2},
    )

    assert payload["action"] == "measurement_fix_next"
    assert payload["release_posture"] == "hold"


def test_build_triage_recommendation_retains_hold_when_risk_regression_dominates() -> None:
    payload = recommendation.build_momentum_rollout_triage_recommendation(
        dossier={"dominant_family": "risk_payoff_regression", "blocker_count": 5},
        attribution={"windows_missing_theme_exposure": [], "window_count": 4},
    )

    assert payload["action"] == "retain_hold"
    assert "no_manifest_publication" in payload["guardrails"]


def test_main_writes_recommendation_outputs(tmp_path: Path) -> None:
    dossier_json = tmp_path / "dossier.json"
    attribution_json = tmp_path / "attribution.json"
    output_json = tmp_path / "recommendation.json"
    output_md = tmp_path / "recommendation.md"
    dossier_json.write_text(json.dumps({"dominant_family": "cross_window_stability", "blocker_count": 3}), encoding="utf-8")
    attribution_json.write_text(json.dumps({"windows_missing_theme_exposure": [], "window_count": 3}), encoding="utf-8")

    result = recommendation.main(
        [
            "--dossier-json",
            str(dossier_json),
            "--attribution-json",
            str(attribution_json),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ]
    )

    assert result == 0
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["action"] == "parameter_retune_next"
    assert output_md.exists()
