from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scripts import run_btst_march_backtest_refresh as march_refresh


def _write_complete_report(report_dir: Path, *, day: str = "2026-03-26") -> None:
    selection_dir = report_dir / "selection_artifacts" / day
    selection_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "session_summary.json").write_text(json.dumps({"ok": True}, ensure_ascii=False) + "\n", encoding="utf-8")
    (report_dir / "daily_events.jsonl").write_text("{}\n", encoding="utf-8")
    (report_dir / "pipeline_timings.jsonl").write_text("{}\n", encoding="utf-8")
    (selection_dir / "selection_snapshot.json").write_text(json.dumps({"trade_date": day}, ensure_ascii=False) + "\n", encoding="utf-8")


def test_validate_report_artifacts_requires_selection_snapshot(tmp_path):
    report_dir = tmp_path / "report"
    (report_dir / "selection_artifacts").mkdir(parents=True)
    (report_dir / "session_summary.json").write_text("{}\n", encoding="utf-8")
    (report_dir / "daily_events.jsonl").write_text("{}\n", encoding="utf-8")
    (report_dir / "pipeline_timings.jsonl").write_text("{}\n", encoding="utf-8")

    validation = march_refresh._validate_report_artifacts(report_dir)

    assert validation["is_complete"] is False
    assert validation["selection_snapshot_count"] == 0
    assert validation["missing_paths"] == [str((report_dir / "selection_artifacts" / "*/selection_snapshot.json").resolve())]


def test_main_stops_before_micro_analysis_when_any_report_is_incomplete(tmp_path, monkeypatch):
    dev_dir = tmp_path / "dev"
    baseline_dir = tmp_path / "baseline"
    variant_dir = tmp_path / "variant"
    forward_dir = tmp_path / "forward"
    micro_json = tmp_path / "micro.json"
    micro_md = tmp_path / "micro.md"
    summary_json = tmp_path / "summary.json"
    summary_md = tmp_path / "summary.md"

    _write_complete_report(dev_dir)
    _write_complete_report(baseline_dir)
    _write_complete_report(variant_dir)
    forward_dir.mkdir(parents=True, exist_ok=True)
    (forward_dir / "session_summary.json").write_text("{}\n", encoding="utf-8")
    (forward_dir / "daily_events.jsonl").write_text("{}\n", encoding="utf-8")
    (forward_dir / "pipeline_timings.jsonl").write_text("{}\n", encoding="utf-8")

    original_argv = sys.argv[:]
    sys.argv = [
        "run_btst_march_backtest_refresh.py",
        "--skip-dev-replay",
        "--skip-baseline",
        "--skip-variant",
        "--skip-forward",
        "--dev-output-dir",
        str(dev_dir),
        "--baseline-output-dir",
        str(baseline_dir),
        "--variant-output-dir",
        str(variant_dir),
        "--forward-output-dir",
        str(forward_dir),
        "--micro-output-json",
        str(micro_json),
        "--micro-output-md",
        str(micro_md),
        "--summary-json",
        str(summary_json),
        "--summary-md",
        str(summary_md),
    ]

    def fail_if_run(*args, **kwargs):
        raise AssertionError("_run should not be called when report validation fails first")

    monkeypatch.setattr(march_refresh, "_run", fail_if_run)

    try:
        with pytest.raises(SystemExit) as exc_info:
            march_refresh.main()
    finally:
        sys.argv = original_argv

    assert exc_info.value.code == 2
    assert not micro_json.exists()
    assert not summary_json.exists()