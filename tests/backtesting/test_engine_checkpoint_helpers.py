"""C2-BH1: checkpoint crash-safety — atomic write + corrupt-read resilience.

``write_checkpoint`` previously wrote directly to the final path via
``path.write_text`` (truncates-then-streams). A crash mid-write (SIGKILL / OOM /
disk-full) leaves a truncated/empty checkpoint file. The recovery chain then
wedges: ``reset_output_artifacts_for_fresh_run`` sees
``checkpoint_path.exists() == True`` (the truncated file exists) and skips
cleanup, while ``read_checkpoint`` → ``json.loads`` raises ``JSONDecodeError``
on the truncated file, crashing the resume with no escape short of manual ``rm``.

These tests lock in two guarantees:
1. ``write_checkpoint`` uses atomic temp-file + ``os.replace`` so a crash never
   leaves a partial file at the canonical path.
2. ``read_checkpoint`` degrades gracefully on a corrupt/truncated checkpoint
   (treats it as missing) instead of raising, so a stale corrupt file can never
   wedge the session.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.backtesting.engine_checkpoint_helpers import (
    build_checkpoint_payload,
    read_checkpoint,
    write_checkpoint,
)


def _sample_payload() -> dict:
    return build_checkpoint_payload(
        last_processed_date="2026-04-10",
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        portfolio_values=[],
        performance_metrics={"sharpe": 1.2},
        pending_buy_queue=[],
        pending_sell_queue=[],
        exit_reentry_cooldowns={},
        pending_plan=None,
    )


class TestWriteCheckpointAtomicity:
    def test_clean_write_round_trips(self, tmp_path: Path) -> None:
        ckpt = tmp_path / "ck.json"
        payload = _sample_payload()
        write_checkpoint(ckpt, payload)
        assert read_checkpoint(ckpt)["last_processed_date"] == "2026-04-10"

    def test_no_tmp_file_left_behind(self, tmp_path: Path) -> None:
        """Atomic write must not leave a stale .tmp file after success."""
        ckpt = tmp_path / "ck.json"
        write_checkpoint(ckpt, _sample_payload())
        leftover_tmps = list(tmp_path.glob("*.tmp"))
        assert leftover_tmps == [], f"stale tmp file left behind: {leftover_tmps}"

    def test_overwrite_preserves_validity(self, tmp_path: Path) -> None:
        """Rewriting an existing checkpoint must leave a valid file (no truncation window)."""
        ckpt = tmp_path / "ck.json"
        write_checkpoint(ckpt, _sample_payload())
        # Second write with different content
        payload2 = _sample_payload()
        payload2["last_processed_date"] = "2026-04-11"
        write_checkpoint(ckpt, payload2)
        # File must always be valid JSON at the canonical path
        raw = ckpt.read_text(encoding="utf-8")
        assert "NaN" not in raw and "Infinity" not in raw
        parsed = json.loads(raw)
        assert parsed["last_processed_date"] == "2026-04-11"


class TestReadCheckpointCorruptResilience:
    def test_truncated_checkpoint_does_not_raise(self, tmp_path: Path) -> None:
        """A truncated checkpoint (simulating crash mid-write) must not crash read.

        Previously ``read_checkpoint`` would raise ``JSONDecodeError`` on a
        partial file, wedging recovery. It must instead degrade as if the
        checkpoint were missing so the engine can start a fresh run.
        """
        ckpt = tmp_path / "ck.json"
        # Simulate a truncated write: opening brace + partial content, no close
        ckpt.write_text('{"last_processed_date": "2026-04-10", "portfolio_', encoding="utf-8")
        result = read_checkpoint(ckpt)
        assert result == {}, f"corrupt checkpoint must degrade to {{}}, got {result}"

    def test_empty_checkpoint_does_not_raise(self, tmp_path: Path) -> None:
        ckpt = tmp_path / "ck.json"
        ckpt.write_text("", encoding="utf-8")
        result = read_checkpoint(ckpt)
        assert result == {}

    def test_missing_checkpoint_returns_empty(self, tmp_path: Path) -> None:
        """A non-existent checkpoint path must return {} (not raise)."""
        ckpt = tmp_path / "does_not_exist.json"
        result = read_checkpoint(ckpt)
        assert result == {}

    def test_corrupt_checkpoint_file_is_quarantined(self, tmp_path: Path) -> None:
        """A corrupt checkpoint should be moved aside so a subsequent fresh run
        is not re-blocked by the same corrupt file."""
        ckpt = tmp_path / "ck.json"
        ckpt.write_text("{corrupt not json", encoding="utf-8")
        read_checkpoint(ckpt)
        # Original corrupt file must no longer block the canonical path
        assert not ckpt.exists(), "corrupt checkpoint should be quarantined/removed"
        # A quarantine marker should exist for diagnosis
        quarantined = list(tmp_path.glob("*.corrupt*")) + list(tmp_path.glob("*.bak*"))
        assert len(quarantined) >= 1, f"corrupt checkpoint should leave a quarantine marker, got {list(tmp_path.iterdir())}"
