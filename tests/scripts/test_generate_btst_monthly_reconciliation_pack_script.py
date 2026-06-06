from __future__ import annotations

from pathlib import Path

import scripts.generate_btst_monthly_reconciliation_pack as pack


def test_generate_btst_monthly_reconciliation_pack_writes_expected_files(tmp_path: Path, monkeypatch) -> None:
    def _fake_audit_btst_outputs_month(*args, **kwargs):  # noqa: ANN001,ANN002,ARG001
        return {"month": "202605", "folder_count": 1, "missing_paths": [], "mismatched_folders": []}

    def _fake_rule_scorecard(*args, **kwargs):  # noqa: ANN001,ANN002,ARG001
        return {"month": "202605", "overall": {"pick_count": 1}}

    def _fake_rule_md(*args, **kwargs):  # noqa: ANN001,ANN002,ARG001
        return "# RULE\n"

    def _fake_exec_scorecard(*args, **kwargs):  # noqa: ANN001,ANN002,ARG001
        return {"month": "202605", "overall": {"pick_count": 0}}

    def _fake_exec_md(*args, **kwargs):  # noqa: ANN001,ANN002,ARG001
        return "# EXEC\n"

    def _fake_health(*args, **kwargs):  # noqa: ANN001,ANN002,ARG001
        return {"month": "202605", "overall": {"day_count": 1}}

    def _fake_health_md(*args, **kwargs):  # noqa: ANN001,ANN002,ARG001
        return "# HEALTH\n"

    def _fake_near_miss(*args, **kwargs):  # noqa: ANN001,ANN002,ARG001
        return {"month": "202605", "overall": {"near_miss_row_count": 2}}

    def _fake_near_miss_md(*args, **kwargs):  # noqa: ANN001,ANN002,ARG001
        return "# NEAR_MISS\n"

    def _fake_counterfactual(*args, **kwargs):  # noqa: ANN001,ANN002,ARG001
        return {"month": "202605", "overall": {"zero_pick_day_count": 1}}

    def _fake_counterfactual_md(*args, **kwargs):  # noqa: ANN001,ANN002,ARG001
        return "# COUNTERFACTUAL\n"

    def _fake_blockers(*args, **kwargs):  # noqa: ANN001,ANN002,ARG001
        return {"month": "202605", "overall": {"blocked_row_count": 2}}

    def _fake_blockers_md(*args, **kwargs):  # noqa: ANN001,ANN002,ARG001
        return "# BLOCKERS\n"

    monkeypatch.setattr(pack, "audit_btst_outputs_month", _fake_audit_btst_outputs_month)
    monkeypatch.setattr(pack, "analyze_btst_monthly_scorecard", _fake_rule_scorecard)
    monkeypatch.setattr(pack, "render_btst_monthly_scorecard_markdown", _fake_rule_md)
    monkeypatch.setattr(pack, "analyze_btst_monthly_execution_scorecard", _fake_exec_scorecard)
    monkeypatch.setattr(pack, "render_btst_monthly_execution_scorecard_markdown", _fake_exec_md)
    monkeypatch.setattr(pack, "analyze_btst_monthly_execution_health", _fake_health)
    monkeypatch.setattr(pack, "render_btst_monthly_execution_health_markdown", _fake_health_md)
    monkeypatch.setattr(pack, "analyze_btst_monthly_near_miss_gate_breakdown", _fake_near_miss)
    monkeypatch.setattr(pack, "render_btst_monthly_near_miss_gate_breakdown_markdown", _fake_near_miss_md)
    monkeypatch.setattr(pack, "analyze_btst_monthly_zero_pick_promotion_counterfactual", _fake_counterfactual)
    monkeypatch.setattr(pack, "render_btst_monthly_zero_pick_promotion_counterfactual_markdown", _fake_counterfactual_md)
    monkeypatch.setattr(pack, "analyze_btst_monthly_execution_blockers", _fake_blockers)
    monkeypatch.setattr(pack, "render_btst_monthly_execution_blockers_markdown", _fake_blockers_md)

    out_dir = tmp_path / "out"
    outputs = pack.generate_btst_monthly_reconciliation_pack(month="202605", out_dir=out_dir)

    assert Path(outputs["outputs_audit_json"]).is_file()
    assert Path(outputs["rule_scorecard_json"]).is_file()
    assert Path(outputs["rule_scorecard_md"]).is_file()
    assert Path(outputs["execution_scorecard_json"]).is_file()
    assert Path(outputs["execution_scorecard_md"]).is_file()
    assert Path(outputs["execution_health_json"]).is_file()
    assert Path(outputs["execution_health_md"]).is_file()
    assert Path(outputs["near_miss_gate_breakdown_json"]).is_file()
    assert Path(outputs["near_miss_gate_breakdown_md"]).is_file()
    assert Path(outputs["zero_pick_promotion_counterfactual_json"]).is_file()
    assert Path(outputs["zero_pick_promotion_counterfactual_md"]).is_file()
    assert Path(outputs["execution_blockers_json"]).is_file()
    assert Path(outputs["execution_blockers_md"]).is_file()

    assert (out_dir / "btst_monthly_scorecard_202605_top5.md").read_text(encoding="utf-8").startswith("# RULE")
    assert (out_dir / "btst_monthly_execution_scorecard_202605.md").read_text(encoding="utf-8").startswith("# EXEC")
    assert (out_dir / "btst_monthly_execution_health_202605.md").read_text(encoding="utf-8").startswith("# HEALTH")
    assert (out_dir / "btst_monthly_near_miss_gate_breakdown_202605.md").read_text(encoding="utf-8").startswith("# NEAR_MISS")
    assert (out_dir / "btst_monthly_zero_pick_promotion_counterfactual_202605.md").read_text(encoding="utf-8").startswith("# COUNTERFACTUAL")
    assert (out_dir / "btst_monthly_execution_blockers_202605.md").read_text(encoding="utf-8").startswith("# BLOCKERS")
