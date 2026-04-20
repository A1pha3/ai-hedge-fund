from __future__ import annotations

from pathlib import Path

from scripts.rebuild_catalyst_theme_diagnostics_from_frozen_reports import _discover_unique_report_dirs


def test_discover_unique_report_dirs_includes_replayable_reports_without_selection_artifacts(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    report_dir = reports_root / "paper_trading_20260411_20260411_missing_artifacts"
    report_dir.mkdir(parents=True)
    (report_dir / "session_summary.json").write_text("{}\n", encoding="utf-8")
    (report_dir / "daily_events.jsonl").write_text("", encoding="utf-8")

    discovered = _discover_unique_report_dirs(
        [str(reports_root), str(report_dir)],
        report_name_contains="paper_trading",
    )

    assert discovered == [report_dir.resolve()]
