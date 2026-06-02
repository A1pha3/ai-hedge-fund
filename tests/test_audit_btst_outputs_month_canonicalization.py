from __future__ import annotations

import json
from pathlib import Path

from scripts.audit_btst_outputs_month import audit_btst_outputs_month


def test_audit_btst_outputs_month_flags_next_date_folder_as_non_canonical(tmp_path: Path) -> None:
    repo_root = tmp_path

    existing_ref = repo_root / "data" / "reports" / "run1" / "session_summary.json"
    existing_ref.parent.mkdir(parents=True)
    existing_ref.write_text(json.dumps({"ok": True}) + "\n", encoding="utf-8")

    # Folder name matches NEXT trade date (canonical is signal date), while the file is signal-date stamped.
    out_dir = repo_root / "outputs" / "202605" / "20260522"
    out_dir.mkdir(parents=True)

    md = (
        "# BTST 多智能体详细计划（20260521 -> 20260522）\n\n"
        "- 会话索引：`data/reports/run1/session_summary.json`\n"
        "- 信号日：`20260521`\n"
        "- 下一交易日：`20260522`\n"
    )
    (out_dir / "BTST-LLM-20260521.md").write_text(md, encoding="utf-8")

    result = audit_btst_outputs_month(month="202605", outputs_dir="outputs", repo_root=repo_root)

    assert result["missing_paths"] == []
    assert result["mismatched_folders"] == []
    assert result["inconsistent_folders"] == []

    assert result["non_canonical_folders"] == ["20260522"]
    assert result["filename_mismatch_folders"] == ["20260522"]

    folder = result["folders"][0]
    assert folder["folder"] == "20260522"
    assert folder["folder_date_role"] == "next_date"
    assert folder["filename_date_matches_folder"] is False
    assert folder["next_date_matches_folder"] is True
