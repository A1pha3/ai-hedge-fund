from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

if TYPE_CHECKING:
    from src.paper_trading.runtime import SessionRuntimeContext


def reset_output_artifacts_for_fresh_run(
    *,
    checkpoint_path: Path,
    daily_events_path: Path,
    timing_log_path: Path,
    selection_artifact_root: Path,
) -> None:
    if checkpoint_path.exists():
        return

    output_dir = checkpoint_path.parent
    checkpoint_timing_log_path = checkpoint_path.with_name(f"{checkpoint_path.stem}.timings.jsonl")
    stale_output_patterns = (
        "session_summary.json",
        "btst_next_day_trade_brief*.json",
        "btst_next_day_trade_brief*.md",
        "btst_premarket_execution_card*.json",
        "btst_premarket_execution_card*.md",
        "btst_next_day_priority_board*.json",
        "btst_next_day_priority_board*.md",
        "btst_opening_watch_card*.json",
        "btst_opening_watch_card*.md",
        "catalyst_theme_frontier*.json",
        "catalyst_theme_frontier*.md",
    )
    stale_files = [daily_events_path, timing_log_path, checkpoint_timing_log_path]
    for pattern in stale_output_patterns:
        stale_files.extend(path for path in output_dir.glob(pattern) if path.is_file())
    for stale_file in stale_files:
        if stale_file.exists():
            stale_file.unlink()

    if selection_artifact_root.exists():
        shutil.rmtree(selection_artifact_root)


def write_research_feedback_summary(
    selection_artifact_root: Path,
    *,
    summarize_research_feedback_directory_fn: Callable[..., Any],
) -> tuple[dict, Path]:
    feedback_summary_path = selection_artifact_root / "research_feedback_summary.json"
    summary = summarize_research_feedback_directory_fn(artifact_root=selection_artifact_root)
    payload = summary.model_dump(mode="json")
    feedback_summary_path.parent.mkdir(parents=True, exist_ok=True)
    feedback_summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload, feedback_summary_path


def write_runtime_summary(summary_path: Path, summary: dict) -> None:
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def promote_runtime_timing_log(context: SessionRuntimeContext) -> None:
    engine_timing_log_path = context.engine._timing_log_path
    session_timing_log_path = context.session_paths.timing_log_path
    if engine_timing_log_path is None:
        return
    if engine_timing_log_path == session_timing_log_path:
        return
    if not engine_timing_log_path.exists():
        return
    engine_timing_log_path.replace(session_timing_log_path)
