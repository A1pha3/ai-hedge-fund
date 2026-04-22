from pathlib import Path

from src.paper_trading.runtime_io_helpers import reset_output_artifacts_for_fresh_run


def test_reset_output_artifacts_for_fresh_run_removes_stale_summary_and_followup_files(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "session.checkpoint.json"
    daily_events_path = tmp_path / "daily_events.jsonl"
    timing_log_path = tmp_path / "pipeline_timings.jsonl"
    selection_artifact_root = tmp_path / "selection_artifacts"
    checkpoint_timing_log_path = tmp_path / "session.checkpoint.timings.jsonl"
    session_summary_path = tmp_path / "session_summary.json"
    btst_brief_path = tmp_path / "btst_next_day_trade_brief_latest.json"

    daily_events_path.write_text("{}\n", encoding="utf-8")
    timing_log_path.write_text("{}\n", encoding="utf-8")
    checkpoint_timing_log_path.write_text("{}\n", encoding="utf-8")
    session_summary_path.write_text("{}\n", encoding="utf-8")
    btst_brief_path.write_text("{}\n", encoding="utf-8")
    (selection_artifact_root / "2026-04-21").mkdir(parents=True)
    (selection_artifact_root / "2026-04-21" / "selection_snapshot.json").write_text("{}\n", encoding="utf-8")

    reset_output_artifacts_for_fresh_run(
        checkpoint_path=checkpoint_path,
        daily_events_path=daily_events_path,
        timing_log_path=timing_log_path,
        selection_artifact_root=selection_artifact_root,
    )

    assert not daily_events_path.exists()
    assert not timing_log_path.exists()
    assert not checkpoint_timing_log_path.exists()
    assert not selection_artifact_root.exists()
    assert not session_summary_path.exists()
    assert not btst_brief_path.exists()
