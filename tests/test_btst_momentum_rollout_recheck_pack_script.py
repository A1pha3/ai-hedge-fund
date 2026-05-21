import json
from pathlib import Path
import pytest

from scripts.btst_momentum_rollout_recheck_pack import (
    build_momentum_rollout_recheck_pack,
    main as rollout_main,
)


def make_valid_snapshot():
    return {
        "profile_name": "p1",
        "profile_overrides": {},
        "source_type": "session_summary",
        "source_path": "data/.../session_summary.json",
        "validated_by": "tester",
        "trade_date": "20260521",
        "manifest_path": "manifests/p1.json",
        "release_posture": "hold",
        "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
        "fail_closed": True,
    }


def make_rerun_pack():
    return {
        "action": "advance_rollout_recheck",
        "winner": {"trial_index": 602, "params": {}, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
        "challengers": [{"trial_index": 1226, "params": {}, "cross_window_blocker_count": 1, "risk_blocker_count": 1}],
        "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
        "release_posture": "hold",
        "dominant_family": "cross_window_stability",
        "missing_theme_exposure_window_count": 2,
        "fail_closed": True,
    }


def make_rerun_recommendation():
    return {
        "action": "advance_rollout_recheck",
        "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
        "release_posture": "hold",
        "dominant_family": "cross_window_stability",
        "missing_theme_exposure_window_count": 2,
        "fail_closed": True,
    }


def test_active_baseline_snapshot_success():
    snap = make_valid_snapshot()
    pack = build_momentum_rollout_recheck_pack(active_baseline_snapshot=snap)
    assert "active_baseline" in pack
    assert pack["active_baseline"] == snap


def test_active_baseline_snapshot_guardrails_drift_fail_closed():
    snap = make_valid_snapshot()
    # mutate guardrails
    snap["guardrails"] = ["no_manifest_publication"]
    with pytest.raises(SystemExit):
        build_momentum_rollout_recheck_pack(active_baseline_snapshot=snap)


def test_main_prefers_active_baseline_json_over_manifest(tmp_path: Path):
    # create baseline_resolution JSON
    baseline = {"manifest_path": "manifests/old.json"}
    baseline_file = tmp_path / "baseline.json"
    baseline_file.write_text(json.dumps(baseline), encoding="utf-8")

    # create active baseline snapshot JSON
    snap = make_valid_snapshot()
    snap_file = tmp_path / "active.json"
    snap_file.write_text(json.dumps(snap), encoding="utf-8")

    pack = rollout_main(["--baseline-resolution-json", str(baseline_file), "--active-baseline-json", str(snap_file)], return_pack=True)
    assert isinstance(pack, dict)
    assert pack["active_baseline"]["release_posture"] == "hold"
    assert pack["active_baseline"]["guardrails"] == ["no_manifest_publication", "no_btst_skill_promotion"]


def test_baseline_resolution_manifest_path_preserved():
    baseline = {"manifest_path": "manifests/p1.json"}
    pack = build_momentum_rollout_recheck_pack(baseline_resolution=baseline)
    assert pack["active_baseline"]["manifest_path"] == "manifests/p1.json"
    assert pack["active_baseline"]["source"] == "manifest_resolution"


def test_main_writes_rollout_pack_outputs_from_rerun_inputs_and_active_baseline(tmp_path: Path):
    rerun_pack_file = tmp_path / "rerun_pack.json"
    rerun_recommendation_file = tmp_path / "rerun_recommendation.json"
    active_baseline_file = tmp_path / "active_baseline.json"
    output_json = tmp_path / "rollout_pack.json"
    output_md = tmp_path / "rollout_pack.md"

    rerun_pack_file.write_text(json.dumps(make_rerun_pack()), encoding="utf-8")
    rerun_recommendation_file.write_text(json.dumps(make_rerun_recommendation()), encoding="utf-8")
    active_baseline_file.write_text(json.dumps(make_valid_snapshot()), encoding="utf-8")

    result = rollout_main(
        [
            "--rerun-pack-json",
            str(rerun_pack_file),
            "--rerun-recommendation-json",
            str(rerun_recommendation_file),
            "--active-baseline-json",
            str(active_baseline_file),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ]
    )

    assert result == 0
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["winner"]["trial_index"] == 602
    assert data["challengers"][0]["trial_index"] == 1226
    assert data["active_baseline"]["profile_name"] == "p1"
    assert data["guardrails"] == ["no_manifest_publication", "no_btst_skill_promotion"]
    assert data["release_posture"] == "hold"
    assert data["fail_closed"] is True
    assert output_md.exists()
