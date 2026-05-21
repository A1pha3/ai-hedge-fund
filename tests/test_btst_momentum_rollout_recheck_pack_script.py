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
