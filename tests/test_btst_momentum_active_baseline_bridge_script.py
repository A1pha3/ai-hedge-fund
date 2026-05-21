import json
from pathlib import Path
import pytest

from scripts.btst_momentum_active_baseline_bridge import (
    build_bridge,
    main as bridge_main,
)

def _make_active_and_source(tmp_path):
    active = {
        "profile_name": "btst_precision_v2",
        "profile_overrides": {"rank_cap": 5, "window": 3},
        "source_type": "session",
        "source_path": "session_summary.json",
        "validated_by": "ci",
        "trade_date": "20260515",
        "manifest_path": "manifests/btst.json",
        "release_posture": "hold",
        "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
        "fail_closed": True,
    }

    row = {
        "report_key": "core_btst",
        "objective": "btst",
        "best_params": {"rank_cap": 5, "window": 3},
        "best_metrics": {
            "next_close_positive_rate": 0.6,
            "next_close_payoff_ratio": 1.5,
            "next_close_expectancy": 0.2,
            "window_coverage": 0.8,
            "window_count": 120,
            "max_drawdown": 0.1,
        },
    }

    source = {"rows": [row]}

    active_path = tmp_path / "active.json"
    source_path = tmp_path / "source.json"
    active_path.write_text(json.dumps(active))
    source_path.write_text(json.dumps(source))
    return str(active_path), str(source_path)


def test_extract_metrics_success(tmp_path):
    active, source = _make_active_and_source(tmp_path)

    bridge = build_bridge(active_baseline_json=str(active), source_json=str(source))

    assert bridge["report_key"] == "core_btst"
    assert bridge["baseline_metrics"]
    for key in [
        "next_close_positive_rate",
        "next_close_payoff_ratio",
        "next_close_expectancy",
        "window_coverage",
        "window_count",
        "max_drawdown",
    ]:
        assert key in bridge["baseline_metrics"]


def test_fail_closed_missing_metrics(tmp_path):
    active, source = _make_active_and_source(tmp_path)
    # remove a required metric from source
    data = json.loads(Path(source).read_text())
    data["rows"][0]["best_metrics"].pop("next_close_positive_rate")
    Path(source).write_text(json.dumps(data))

    with pytest.raises(ValueError):
        build_bridge(active_baseline_json=str(active), source_json=str(source))


def test_main_writes_outputs(tmp_path):
    active, source = _make_active_and_source(tmp_path)
    out_json = tmp_path / "bridge.json"
    out_md = tmp_path / "bridge.md"

    # ensure not present
    if out_json.exists():
        out_json.unlink()
    if out_md.exists():
        out_md.unlink()

    bridge_main(
        active_baseline_json=str(active),
        source_json=str(source),
        output_json=str(out_json),
        output_md=str(out_md),
    )

    assert out_json.exists()
    assert out_md.exists()

    j = json.loads(out_json.read_text())
    assert j.get("report_key") == "core_btst"
