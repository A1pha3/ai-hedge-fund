from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.btst_momentum_rollout_recheck_pack as recheck_pack


def test_build_rollout_recheck_pack_preserves_winner_and_resolved_baseline() -> None:
    payload = recheck_pack.build_momentum_rollout_recheck_pack(
        rerun_pack={
            "winner": {"trial_index": 602, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
            "challengers": [
                {"trial_index": 1226, "cross_window_blocker_count": 1, "risk_blocker_count": 0},
            ],
            "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
            "release_posture": "hold",
            "dominant_family": "cross_window_stability",
            "missing_theme_exposure_window_count": 2,
            "fail_closed": True,
        },
        rerun_recommendation={
            "action": "advance_rollout_recheck",
            "release_posture": "hold",
            "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
            "dominant_family": "cross_window_stability",
            "missing_theme_exposure_window_count": 2,
            "fail_closed": True,
        },
        baseline_resolution={
            "mode": "optimized",
            "profile_name": "momentum_optimized",
            "profile_overrides": {"select_threshold": 0.54},
            "source_type": "json",
            "source_path": "data/reports/btst_latest_optimized_profile.json",
            "validated_by": "unit-test",
            "trade_date": "2026-05-21",
            "status": "ready",
            "fallback_reason": None,
            "manifest_path": "data/reports/btst_latest_optimized_profile.json",
        },
    )

    assert payload["winner"]["trial_index"] == 602
    assert payload["challengers"][0]["trial_index"] == 1226
    assert payload["active_baseline"]["profile_name"] == "momentum_optimized"
    assert payload["guardrails"] == ["no_manifest_publication", "no_btst_skill_promotion"]
    assert payload["release_posture"] == "hold"
    assert payload["fail_closed"] is True


def test_build_rollout_recheck_pack_fails_closed_when_rerun_action_is_not_advance_rollout_recheck() -> None:
    with pytest.raises(SystemExit, match="rerun_recommendation.action must be advance_rollout_recheck"):
        recheck_pack.build_momentum_rollout_recheck_pack(
            rerun_pack={
                "winner": {"trial_index": 602, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
                "challengers": [],
                "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
                "release_posture": "hold",
                "dominant_family": "cross_window_stability",
                "missing_theme_exposure_window_count": 2,
                "fail_closed": True,
            },
            rerun_recommendation={
                "action": "retain_hold",
                "release_posture": "hold",
                "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
                "dominant_family": "cross_window_stability",
                "missing_theme_exposure_window_count": 2,
                "fail_closed": True,
            },
            baseline_resolution={"mode": "optimized", "profile_name": "momentum_optimized", "profile_overrides": {}, "status": "ready", "manifest_path": "data/reports/btst_latest_optimized_profile.json"},
        )


def test_build_rollout_recheck_pack_rejects_unresolved_baseline_fallback() -> None:
    with pytest.raises(SystemExit, match="baseline_resolution must be resolved"):
        recheck_pack.build_momentum_rollout_recheck_pack(
            rerun_pack={
                "winner": {"trial_index": 602, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
                "challengers": [],
                "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
                "release_posture": "hold",
                "dominant_family": "cross_window_stability",
                "missing_theme_exposure_window_count": 2,
                "fail_closed": True,
            },
            rerun_recommendation={
                "action": "advance_rollout_recheck",
                "release_posture": "hold",
                "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
                "dominant_family": "cross_window_stability",
                "missing_theme_exposure_window_count": 2,
                "fail_closed": True,
            },
            baseline_resolution={
                "mode": "default_fallback",
                "profile_name": "default",
                "profile_overrides": {},
                "source_type": None,
                "source_path": None,
                "validated_by": None,
                "trade_date": None,
                "status": "missing",
                "fallback_reason": "optimized_profile_manifest_missing",
                "manifest_path": "data/reports/btst_latest_optimized_profile.json",
            },
        )


def test_build_rollout_recheck_pack_rejects_non_hold_release_posture_and_guardrail_mismatch() -> None:
    with pytest.raises(SystemExit, match="rerun_recommendation.release_posture must be hold"):
        recheck_pack.build_momentum_rollout_recheck_pack(
            rerun_pack={
                "winner": {"trial_index": 602, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
                "challengers": [],
                "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
                "release_posture": "hold",
                "dominant_family": "cross_window_stability",
                "missing_theme_exposure_window_count": 2,
                "fail_closed": True,
            },
            rerun_recommendation={
                "action": "advance_rollout_recheck",
                "release_posture": "release",
                "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
                "dominant_family": "cross_window_stability",
                "missing_theme_exposure_window_count": 2,
                "fail_closed": True,
            },
            baseline_resolution={"mode": "optimized", "profile_name": "momentum_optimized", "profile_overrides": {}, "status": "ready", "manifest_path": "data/reports/btst_latest_optimized_profile.json"},
        )

    with pytest.raises(SystemExit, match="rerun_recommendation.guardrails must preserve rerun_pack.guardrails exactly"):
        recheck_pack.build_momentum_rollout_recheck_pack(
            rerun_pack={
                "winner": {"trial_index": 602, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
                "challengers": [],
                "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
                "release_posture": "hold",
                "dominant_family": "cross_window_stability",
                "missing_theme_exposure_window_count": 2,
                "fail_closed": True,
            },
            rerun_recommendation={
                "action": "advance_rollout_recheck",
                "release_posture": "hold",
                "guardrails": ["no_manifest_publication", "different_guardrail"],
                "dominant_family": "cross_window_stability",
                "missing_theme_exposure_window_count": 2,
                "fail_closed": True,
            },
            baseline_resolution={"mode": "optimized", "profile_name": "momentum_optimized", "profile_overrides": {}, "status": "ready", "manifest_path": "data/reports/btst_latest_optimized_profile.json"},
        )


def test_build_rollout_recheck_pack_rejects_wrong_shared_guardrails_and_pack_release_posture() -> None:
    with pytest.raises(SystemExit, match="rerun_pack.guardrails must preserve no_manifest_publication and no_btst_skill_promotion exactly"):
        recheck_pack.build_momentum_rollout_recheck_pack(
            rerun_pack={
                "winner": {"trial_index": 602, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
                "challengers": [],
                "guardrails": ["no_manifest_publication", "different_guardrail"],
                "release_posture": "hold",
                "dominant_family": "cross_window_stability",
                "missing_theme_exposure_window_count": 2,
                "fail_closed": True,
            },
            rerun_recommendation={
                "action": "advance_rollout_recheck",
                "release_posture": "hold",
                "guardrails": ["no_manifest_publication", "different_guardrail"],
                "dominant_family": "cross_window_stability",
                "missing_theme_exposure_window_count": 2,
                "fail_closed": True,
            },
            baseline_resolution={"mode": "optimized", "profile_name": "momentum_optimized", "profile_overrides": {}, "status": "ready", "manifest_path": "data/reports/btst_latest_optimized_profile.json"},
        )


@pytest.mark.parametrize(
    ("field_name", "rerun_pack_value", "rerun_recommendation_value", "expected_message"),
    [
        (
            "dominant_family",
            "cross_window_stability",
            "risk_payoff_regression",
            "rerun_recommendation.dominant_family must match rerun_pack.dominant_family exactly",
        ),
        (
            "missing_theme_exposure_window_count",
            2,
            3,
            "rerun_recommendation.missing_theme_exposure_window_count must match rerun_pack.missing_theme_exposure_window_count exactly",
        ),
    ],
)
def test_build_rollout_recheck_pack_rejects_mismatched_shared_context_fields(
    field_name: str, rerun_pack_value: object, rerun_recommendation_value: object, expected_message: str
) -> None:
    rerun_pack = {
        "winner": {"trial_index": 602, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
        "challengers": [],
        "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
        "release_posture": "hold",
        "dominant_family": "cross_window_stability",
        "missing_theme_exposure_window_count": 2,
        "fail_closed": True,
    }
    rerun_pack[field_name] = rerun_pack_value

    rerun_recommendation = {
        "action": "advance_rollout_recheck",
        "release_posture": "hold",
        "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
        "dominant_family": "cross_window_stability",
        "missing_theme_exposure_window_count": 2,
        "fail_closed": True,
    }
    rerun_recommendation[field_name] = rerun_recommendation_value

    with pytest.raises(SystemExit, match=expected_message):
        recheck_pack.build_momentum_rollout_recheck_pack(
            rerun_pack=rerun_pack,
            rerun_recommendation=rerun_recommendation,
            baseline_resolution={"mode": "optimized", "profile_name": "momentum_optimized", "profile_overrides": {}, "status": "ready", "manifest_path": "data/reports/btst_latest_optimized_profile.json"},
        )


@pytest.mark.parametrize(
    ("artifact_name", "rerun_pack_fail_closed", "rerun_recommendation_fail_closed"),
    [
        (
            "rerun_pack",
            False,
            True,
        ),
        (
            "rerun_recommendation",
            True,
            False,
        ),
    ],
)
def test_build_rollout_recheck_pack_requires_both_inputs_to_be_fail_closed(
    artifact_name: str, rerun_pack_fail_closed: bool, rerun_recommendation_fail_closed: bool
) -> None:
    expected = f"{artifact_name}.fail_closed must be true"
    rerun_pack = {
        "winner": {"trial_index": 602, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
        "challengers": [],
        "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
        "release_posture": "hold",
        "dominant_family": "cross_window_stability",
        "missing_theme_exposure_window_count": 2,
        "fail_closed": rerun_pack_fail_closed,
    }
    rerun_recommendation = {
        "action": "advance_rollout_recheck",
        "release_posture": "hold",
        "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
        "dominant_family": "cross_window_stability",
        "missing_theme_exposure_window_count": 2,
        "fail_closed": rerun_recommendation_fail_closed,
    }

    with pytest.raises(SystemExit, match=expected):
        recheck_pack.build_momentum_rollout_recheck_pack(
            rerun_pack=rerun_pack,
            rerun_recommendation=rerun_recommendation,
            baseline_resolution={"mode": "optimized", "profile_name": "momentum_optimized", "profile_overrides": {}, "status": "ready", "manifest_path": "data/reports/btst_latest_optimized_profile.json"},
        )

    with pytest.raises(SystemExit, match="rerun_pack.release_posture must be hold"):
        recheck_pack.build_momentum_rollout_recheck_pack(
            rerun_pack={
                "winner": {"trial_index": 602, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
                "challengers": [],
                "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
                "release_posture": "release",
                "dominant_family": "cross_window_stability",
                "missing_theme_exposure_window_count": 2,
                "fail_closed": True,
            },
            rerun_recommendation={
                "action": "advance_rollout_recheck",
                "release_posture": "hold",
                "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
                "dominant_family": "cross_window_stability",
                "missing_theme_exposure_window_count": 2,
                "fail_closed": True,
            },
            baseline_resolution={"mode": "optimized", "profile_name": "momentum_optimized", "profile_overrides": {}, "status": "ready", "manifest_path": "data/reports/btst_latest_optimized_profile.json"},
        )


@pytest.mark.parametrize(
    ("guardrail_field", "rerun_pack_guardrails", "rerun_recommendation_guardrails"),
    [
        ("rerun_pack.guardrails", 1, ["no_manifest_publication", "no_btst_skill_promotion"]),
        ("rerun_recommendation.guardrails", ["no_manifest_publication", "no_btst_skill_promotion"], 1),
    ],
)
def test_build_rollout_recheck_pack_rejects_non_list_guardrails(guardrail_field: str, rerun_pack_guardrails: object, rerun_recommendation_guardrails: object) -> None:
    import re

    expected = re.escape(guardrail_field) + r" must be a list\."
    with pytest.raises(SystemExit, match=expected):
        recheck_pack.build_momentum_rollout_recheck_pack(
            rerun_pack={
                "winner": {"trial_index": 602, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
                "challengers": [],
                "guardrails": rerun_pack_guardrails,
                "release_posture": "hold",
                "dominant_family": "cross_window_stability",
                "missing_theme_exposure_window_count": 2,
                "fail_closed": True,
            },
            rerun_recommendation={
                "action": "advance_rollout_recheck",
                "release_posture": "hold",
                "guardrails": rerun_recommendation_guardrails,
                "dominant_family": "cross_window_stability",
                "missing_theme_exposure_window_count": 2,
                "fail_closed": True,
            },
            baseline_resolution={"mode": "optimized", "profile_name": "momentum_optimized", "profile_overrides": {}, "status": "ready", "manifest_path": "data/reports/btst_latest_optimized_profile.json"},
        )


@pytest.mark.parametrize(
    ("candidate_key", "candidate"),
    [
        ("winner", {"trial_index": 602, "cross_window_blocker_count": "0", "risk_blocker_count": 0}),
        ("challengers[0]", {"trial_index": 1226, "cross_window_blocker_count": 1.5, "risk_blocker_count": 0}),
    ],
)
def test_build_rollout_recheck_pack_rejects_malformed_blocker_count_fields(candidate_key: str, candidate: dict[str, object]) -> None:
    import re

    expected = re.escape(candidate_key) + r" .* must be a non-negative integer"
    with pytest.raises(SystemExit, match=expected):
        recheck_pack.build_momentum_rollout_recheck_pack(
            rerun_pack={
                "winner": candidate if candidate_key == "winner" else {"trial_index": 602, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
                "challengers": [candidate] if candidate_key.startswith("challengers[") else [],
                "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
                "release_posture": "hold",
                "dominant_family": "cross_window_stability",
                "missing_theme_exposure_window_count": 2,
                "fail_closed": True,
            },
            rerun_recommendation={
                "action": "advance_rollout_recheck",
                "release_posture": "hold",
                "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
                "dominant_family": "cross_window_stability",
                "missing_theme_exposure_window_count": 2,
                "fail_closed": True,
            },
            baseline_resolution={"mode": "optimized", "profile_name": "momentum_optimized", "profile_overrides": {}, "status": "ready", "manifest_path": "data/reports/btst_latest_optimized_profile.json"},
        )


def test_main_writes_rollout_recheck_pack_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rerun_pack_json = tmp_path / "btst_momentum_rerun_rollout_pack.json"
    rerun_recommendation_json = tmp_path / "btst_momentum_rerun_rollout_recommendation.json"
    manifest_json = tmp_path / "btst_latest_optimized_profile.json"
    output_json = tmp_path / "btst_momentum_rollout_recheck_pack.json"
    output_md = tmp_path / "btst_momentum_rollout_recheck_pack.md"

    rerun_pack_json.write_text(
        json.dumps(
            {
                "winner": {"trial_index": 602, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
                "challengers": [{"trial_index": 1226, "cross_window_blocker_count": 1, "risk_blocker_count": 0}],
                "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
                "release_posture": "hold",
                "dominant_family": "cross_window_stability",
                "missing_theme_exposure_window_count": 2,
                "fail_closed": True,
            }
        ),
        encoding="utf-8",
    )
    rerun_recommendation_json.write_text(
        json.dumps(
            {
                "action": "advance_rollout_recheck",
                "release_posture": "hold",
                "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
                "dominant_family": "cross_window_stability",
                "missing_theme_exposure_window_count": 2,
                "fail_closed": True,
            }
        ),
        encoding="utf-8",
    )
    manifest_json.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        recheck_pack,
        "resolve_btst_optimized_profile_manifest",
        lambda path: {
            "mode": "optimized",
            "profile_name": "momentum_optimized",
            "profile_overrides": {"select_threshold": 0.54},
            "source_type": "json",
            "source_path": str(path),
            "validated_by": "unit-test",
            "trade_date": "2026-05-21",
            "status": "ready",
            "fallback_reason": None,
            "manifest_path": str(path),
        },
    )

    result = recheck_pack.main(
        [
            "--rerun-pack-json",
            str(rerun_pack_json),
            "--rerun-recommendation-json",
            str(rerun_recommendation_json),
            "--manifest-json",
            str(manifest_json),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ]
    )

    assert result == 0
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["winner"]["trial_index"] == 602
    assert data["active_baseline"]["profile_name"] == "momentum_optimized"
    assert data["release_posture"] == "hold"
    markdown = output_md.read_text(encoding="utf-8")
    assert "# Momentum Rollout Recheck Pack" in markdown
    assert "momentum_optimized" in markdown
