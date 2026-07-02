"""NS-17/c289: runtime_observability_helpers must not silently skip corrupt jsonl rows.

Dogfood (AST scan of src/paper_trading silent-skip except blocks) found
``_iter_paper_trading_day_payloads`` skips corrupt ``daily_events.jsonl``
rows with ``except json.JSONDecodeError: continue`` and NO warning — while
the SAME file is parsed by ``frozen_replay`` (line 217) which DOES log a
warning + count skipped lines. Inconsistent: a corrupt row in
daily_events.jsonl is diagnosable from frozen_replay but invisible from
the observability/session-summary path. Operator debugging a degraded
session summary can't tell corrupt-rows-skipped from genuinely-empty.

Same NS-17/BH-017 silent-skip family as c288 (which fixed the experiment
harness). This fixes the observability path's inconsistency with
frozen_replay.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.paper_trading.runtime_observability_helpers import (
    build_dual_target_session_summary,
    _iter_paper_trading_day_payloads,
)


def _write_daily_events(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_iter_paper_trading_day_payloads_warns_on_corrupt_rows(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """c289: corrupt jsonl rows must emit a warning, not silently skip.

    frozen_replay:217 logs a warning per corrupt daily_events row;
    _iter_paper_trading_day_payloads (same file, different parser) must
    do the same so the observability path is consistent. Without the
    warning, a session summary built from a file with corrupt rows is
    indistinguishable from one built from a clean file with fewer rows.
    """
    good_row = json.dumps({"event": "paper_trading_day", "trade_date": "20260629", "current_plan": {"date": "20260629"}})
    bad_row = "{not valid json"
    lines = [good_row, bad_row, good_row]

    with caplog.at_level("WARNING"):
        payloads = list(_iter_paper_trading_day_payloads(lines))

    # 2 good rows parsed, 1 corrupt skipped
    assert len(payloads) == 2, f"expected 2 good payloads, got {len(payloads)}"
    # the corrupt row must produce a WARNING (not silent skip)
    assert any("损坏" in r.message or "corrupt" in r.message.lower() or "JSONDecodeError" in r.message for r in caplog.records), (
        f"corrupt jsonl row must emit a warning; got records={[r.message for r in caplog.records]}"
    )


def test_dual_target_session_summary_surfaces_corrupt_row_count(tmp_path: Path) -> None:
    """c289: session summary must report corrupt-skipped rows so the operator
    can distinguish 'corrupt rows dropped' from 'genuinely fewer days'.

    A summary built from [good, corrupt, good] must carry a corrupt_rows
    count > 0 in its output — otherwise a degraded summary looks identical
    to a clean 2-day summary.
    """
    good = json.dumps({"event": "paper_trading_day", "trade_date": "20260629", "current_plan": {"date": "20260629", "dual_target_summary": {}}})
    bad = "{not valid json"
    p = tmp_path / "daily_events.jsonl"
    _write_daily_events(p, [good, bad, good])

    summary = build_dual_target_session_summary(p)
    # the summary must surface the corrupt-row count (implementation-flexible key)
    corrupt_count = summary.get("corrupt_rows") or summary.get("skipped_corrupt_rows") or summary.get("corrupt_lines")
    assert corrupt_count is not None and corrupt_count >= 1, (
        f"session summary must report corrupt-skipped row count; got keys={list(summary.keys())}"
    )
