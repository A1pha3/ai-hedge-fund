from __future__ import annotations

import json
from pathlib import Path

import scripts.refresh_btst_5d_15pct_priors as refresh_script


def test_refresh_btst_5d_15pct_priors_writes_artifacts(monkeypatch, tmp_path: Path):
    boundary_json = tmp_path / "boundary.json"
    boundary_md = tmp_path / "boundary.md"
    trend_json = tmp_path / "trend.json"
    trend_md = tmp_path / "trend.md"

    monkeypatch.setattr(
        refresh_script,
        "analyze_btst_5d_15pct_boundary_contract_inspection",
        lambda _root: {"boundary_row_count": 2, "boundary_rows": []},
    )
    monkeypatch.setattr(
        refresh_script,
        "render_btst_5d_15pct_boundary_contract_inspection_markdown",
        lambda _analysis: "# boundary\n",
    )
    monkeypatch.setattr(
        refresh_script,
        "analyze_btst_5d_15pct_trend_gate_oos_validation",
        lambda _root: {"candidate_summary": {"closed_cycle_count": 7}, "candidate_manifest": []},
    )
    monkeypatch.setattr(
        refresh_script,
        "render_btst_5d_15pct_trend_gate_oos_validation_markdown",
        lambda _analysis: "# trend\n",
    )

    payload = refresh_script.refresh_btst_5d_15pct_priors(
        tmp_path,
        boundary_output_json=boundary_json,
        boundary_output_md=boundary_md,
        trend_output_json=trend_json,
        trend_output_md=trend_md,
    )

    assert payload["report_type"] == "refresh_btst_5d_15pct_priors"
    assert Path(payload["artifacts"]["boundary"]["json_path"]).exists()
    assert Path(payload["artifacts"]["trend_gate_oos"]["json_path"]).exists()

    assert boundary_md.read_text(encoding="utf-8").startswith("# boundary")
    assert trend_md.read_text(encoding="utf-8").startswith("# trend")

    boundary_payload = json.loads(boundary_json.read_text(encoding="utf-8"))
    assert boundary_payload["boundary_row_count"] == 2

    trend_payload = json.loads(trend_json.read_text(encoding="utf-8"))
    assert trend_payload["candidate_summary"]["closed_cycle_count"] == 7
