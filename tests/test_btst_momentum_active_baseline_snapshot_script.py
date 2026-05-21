import json
from pathlib import Path
import pytest

from scripts.btst_momentum_active_baseline_snapshot import (
    build_snapshot,
    load_session_summary,
    render_markdown,
    main,
    SnapshotValidationError,
)


def make_sample_session():
    return {
        "trade_date": "20260513",
        "optimization_profile_resolution": {
            "mode": "optimized",
            "status": "ready",
            "fallback_reason": None,
            "profile_name": "btst_precision_v2",
            "profile_overrides": {"param": 1},
            "source_type": "approved_btst_research_backfill",
            "source_path": "data/reports/btst_v2_objective_alignment_primary.json",
            "validated_by": "objective_alignment_primary",
            "manifest_path": "manifests/btst_precision_v2.json",
        },
    }


def test_build_snapshot_success():
    sess = make_sample_session()
    snap = build_snapshot(sess)
    assert snap["profile_name"] == "btst_precision_v2"
    assert snap["profile_overrides"] == {"param": 1}
    assert snap["source_type"] == "approved_btst_research_backfill"
    assert snap["manifest_path"] == "manifests/btst_precision_v2.json"
    assert snap["release_posture"] == "hold"
    assert snap["fail_closed"] is True


def test_build_snapshot_missing_opr_raises():
    sess = {"trade_date": "20260513"}
    with pytest.raises(SnapshotValidationError):
        build_snapshot(sess)


def test_main_writes_outputs(tmp_path, monkeypatch):
    # write a session_summary to a temp file
    sess = make_sample_session()
    input_file = tmp_path / "session_summary.json"
    input_file.write_text(json.dumps(sess))

    json_out = tmp_path / "out.json"
    md_out = tmp_path / "out.md"

    # call main with our paths
    rc = main(["--input", str(input_file), "--json-output", str(json_out), "--md-output", str(md_out)])
    assert rc == 0

    assert json_out.exists()
    assert md_out.exists()

    data = json.loads(json_out.read_text())
    assert data["profile_name"] == "btst_precision_v2"
    md_text = md_out.read_text()
    assert "BTST Momentum Active Baseline Snapshot" in md_text
    assert "profile_overrides" in md_text or "Profile overrides" in md_text
