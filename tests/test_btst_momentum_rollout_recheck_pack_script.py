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
