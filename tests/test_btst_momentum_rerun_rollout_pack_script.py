import json
from pathlib import Path

import pytest

import scripts.btst_momentum_rerun_rollout_pack as pack


def test_build_rerun_pack_carries_winner_challengers_and_guardrails() -> None:
    payload = pack.build_momentum_rerun_rollout_pack(
        cohort={
            "winner": {"trial_index": 602, "params": {"select_threshold": 0.46}},
            "challengers": [{"trial_index": 1226, "params": {"select_threshold": 0.46}}],
            "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
        },
        decision={"action": "rerun_rollout_check", "release_posture": "hold", "dominant_family": "cross_window_stability", "missing_theme_exposure_window_count": 2},
    )

    assert payload["winner"]["trial_index"] == 602
    assert [row["trial_index"] for row in payload["challengers"]] == [1226]
    assert payload["release_posture"] == "hold"
    assert payload["guardrails"] == ["no_manifest_publication", "no_btst_skill_promotion"]
    assert payload["dominant_family"] == "cross_window_stability"
    assert payload["missing_theme_exposure_window_count"] == 2
    assert payload["fail_closed"] is True


def test_build_rerun_pack_fails_closed_when_release_posture_is_not_hold() -> None:
    with pytest.raises(SystemExit, match="release_posture"):
        pack.build_momentum_rerun_rollout_pack(
            cohort={"winner": {"trial_index": 602}, "challengers": [], "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"]},
            decision={"action": "rerun_rollout_check", "release_posture": "ready", "dominant_family": "cross_window_stability", "missing_theme_exposure_window_count": 2},
        )


def test_main_writes_rerun_pack_outputs(tmp_path: Path) -> None:
    cohort_json = tmp_path / "cohort.json"
    decision_json = tmp_path / "decision.json"
    output_json = tmp_path / "pack.json"
    output_md = tmp_path / "pack.md"
    cohort_json.write_text(json.dumps({"winner": {"trial_index": 602}, "challengers": [], "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"]}), encoding="utf-8")
    decision_json.write_text(json.dumps({"action": "rerun_rollout_check", "release_posture": "hold", "dominant_family": "cross_window_stability", "missing_theme_exposure_window_count": 2}), encoding="utf-8")

    result = pack.main(
        [
            "--cohort-json",
            str(cohort_json),
            "--decision-json",
            str(decision_json),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ]
    )

    assert result == 0
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["release_posture"] == "hold"
    assert data["dominant_family"] == "cross_window_stability"
    assert data["missing_theme_exposure_window_count"] == 2
    assert data["fail_closed"] is True
    assert output_md.exists()


def test_build_rerun_pack_fails_closed_when_dominant_family_contains_newlines() -> None:
    with pytest.raises(SystemExit, match="dominant_family"):
        pack.build_momentum_rerun_rollout_pack(
            cohort={"winner": {"trial_index": 602}, "challengers": [], "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"]},
            decision={
                "action": "rerun_rollout_check",
                "release_posture": "hold",
                "dominant_family": "cross_window_stability\n\n## injected",
                "missing_theme_exposure_window_count": 2,
            },
        )
