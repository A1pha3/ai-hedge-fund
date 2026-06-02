from __future__ import annotations

import json
from pathlib import Path

from scripts.audit_btst_outputs_month import audit_btst_outputs_month


def test_audit_btst_outputs_month_detects_missing_refs_and_mismatch(tmp_path: Path) -> None:
    repo_root = tmp_path

    # Create one referenced report file (exists)
    existing_ref = repo_root / "data" / "reports" / "run1" / "session_summary.json"
    existing_ref.parent.mkdir(parents=True)
    existing_ref.write_text(json.dumps({"ok": True}) + "\n", encoding="utf-8")

    # Build outputs folder: name is next trade date, but we intentionally mismatch it.
    out_dir = repo_root / "outputs" / "202605" / "20260523"
    out_dir.mkdir(parents=True)

    md = (
        "# BTST 多智能体详细计划（20260521 -> 20260522）\n\n"
        "## 来源\n\n"
        "- 会话索引：`data/reports/run1/session_summary.json`\n"
        "- 主报告目录：`data/reports/run1`\n"
        "- 缺失引用：`data/reports/run1/missing.json`\n"
        "- 信号日：`20260521`\n"
        "- 下一交易日：`20260522`\n"
    )
    (out_dir / "BTST-LLM-20260521.md").write_text(md, encoding="utf-8")

    result = audit_btst_outputs_month(month="202605", outputs_dir="outputs", repo_root=repo_root)

    assert result["folder_count"] == 1
    assert result["missing_paths"] == ["data/reports/run1/missing.json"]
    assert result["mismatched_folders"] == ["20260523"]

    folder = result["folders"][0]
    assert folder["signal_dates"] == ["20260521"]
    assert folder["next_dates"] == ["20260522"]
    assert folder["missing_paths"] == ["data/reports/run1/missing.json"]
    assert folder["folder_date_role"] == "mismatch"
    assert folder["next_date_matches_folder"] is False
