"""Concurrency guard: --auto pipeline must serialize across overlapping invocations.

Root cause of the R88/R104/R93 corrupt-report family: overlapping --auto runs
(from cron launchd + manual invocation + subprocess + daily_accumulate) write
the same ``auto_screening_{trade_date}.json`` (fixed-path → partial-write /
last-writer-wins) and race on ``tracking_history.json`` read-modify-write. The
codebase has extensive REACTIVE corrupt-report guards (R88 drain across
composite_score / data_quality_audit / candidate_pool_persistence_helpers /
signal_consistency) but NO PROACTIVE mutual exclusion — guards treat the
symptom; the flock treats the root cause.

``fcntl.flock`` is advisory and auto-releases when the holding process exits
(even on crash / kill -9), so there is no stale-lock cleanup. Covers ALL --auto
entry points (shell scripts, subprocess, direct invocation) because the lock
lives in the pipeline code, not the launcher.
"""

from __future__ import annotations

import os
from pathlib import Path

from src.main import _try_acquire_pipeline_lock


def test_try_acquire_pipeline_lock_serializes_concurrent_callers(tmp_path: Path) -> None:
    """First acquire succeeds; a concurrent second acquire is denied; after release, a third succeeds."""
    lock = tmp_path / ".auto_pipeline.lock"
    fd1 = _try_acquire_pipeline_lock(lock)
    assert fd1 is not None, "first acquire must succeed"
    try:
        fd2 = _try_acquire_pipeline_lock(lock)
        assert fd2 is None, "second acquire while the first holds the lock must be denied — " "concurrent --auto runs must serialize to avoid report/tracking_history corruption"
    finally:
        os.close(fd1)
    # After release, the next acquire must succeed.
    fd3 = _try_acquire_pipeline_lock(lock)
    assert fd3 is not None, "acquire must succeed after the holder releases"
    os.close(fd3)


def test_try_acquire_pipeline_lock_creates_missing_parent_dir(tmp_path: Path) -> None:
    """The lock parent (logs/) may not exist on a fresh clone — mkdir it."""
    lock = tmp_path / "nested" / "missing" / ".auto_pipeline.lock"
    fd = _try_acquire_pipeline_lock(lock)
    assert fd is not None
    assert lock.parent.exists(), "lock helper must create the parent directory"
    assert lock.exists(), "lock file must be created"
    os.close(fd)


def test_try_acquire_pipeline_lock_releases_on_close_allows_reacquire(tmp_path: Path) -> None:
    """Closing the fd releases the flock — verifies crash-safe auto-release semantics (fd close ≈ process exit)."""
    lock = tmp_path / ".cycle.lock"
    for i in range(3):
        fd = _try_acquire_pipeline_lock(lock)
        assert fd is not None, f"cycle {i}: acquire must succeed (prior fd closed → flock released)"
        os.close(fd)
