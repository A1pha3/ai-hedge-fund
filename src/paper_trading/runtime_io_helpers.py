from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, TYPE_CHECKING

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
    _atomic_write_json(feedback_summary_path, payload)
    return payload, feedback_summary_path


def write_runtime_summary(summary_path: Path, summary: dict) -> None:
    _atomic_write_json(summary_path, summary)


def _atomic_write_json(path: Path, payload: Any) -> None:
    """R88 corrupt-sidecar CRASH vector guard: tempfile + os.replace 原子写。
    paper_trading runtime summary 的输出格式 (ensure_ascii=False, indent=2, 无尾换行)
    与 c294 btst_reporting_utils._write_json (带 \\n) 不同, 故就地实现而非复用。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, indent=2))
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


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
