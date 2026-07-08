"""Tests for NS-17 silent-except fix in PaperTracker._load_state()."""
from __future__ import annotations

import json
import logging

import pytest

from src.screening.offensive.paper_tracker import PaperTracker, PortfolioState


class TestPaperTrackerNS17Regression:
    """Regression guards for autodev-32 NS-17 fix in paper_tracker.py:79.

    _load_state() had `except Exception: pass` — a corrupted state file
    silently fell back to empty PortfolioState with zero operator visibility.
    Fix: adds logger.warning(exc_info=True) before fallback.
    """

    def test_state_file_corrupted_logs_warning(self, tmp_path, caplog):
        """Corrupted portfolio_state.json logs warning and returns empty state.

        Uses a temporary directory as the journal_dir so the corrupted
        state file is read, then __init__ reconciles open_positions from
        the (empty) journal.
        """
        state_file = tmp_path / "portfolio_state.json"
        state_file.write_text("{corrupted json!!}", encoding="utf-8")

        caplog.set_level(logging.WARNING)
        tracker = PaperTracker(journal_dir=tmp_path)
        state = tracker._state

        assert isinstance(state, PortfolioState)
        assert state.nav == 1.0  # default empty state
        assert any(
            "paper_tracker" in r.name and "failed to load portfolio state" in r.message
            for r in caplog.records
        ), f"Expected warning log, got: {[r.message for r in caplog.records]}"

    def test_state_file_valid_parses_correctly(self, tmp_path):
        """Valid state file should be parsed (non-self-healed fields intact)."""
        state_file = tmp_path / "portfolio_state.json"
        state_file.write_text(
            json.dumps({
                "nav": 1.05,
                "peak": 1.1,
                "drawdown_pct": -0.05,
                "open_positions": 3,
                "total_trades": 20,
                "realized_pnl_pct": 0.12,
                "last_30d_pnl": [0.01, -0.005, 0.02],
            }),
            encoding="utf-8",
        )
        tracker = PaperTracker(journal_dir=tmp_path)
        state = tracker._state
        # open_positions is self-healed by _reconcile_open_positions()
        # so check non-healed fields
        assert state.nav == 1.05
        assert state.total_trades == 20
        assert state.realized_pnl_pct == 0.12
        assert state.peak == 1.1
        assert state.drawdown_pct == -0.05

    def test_state_file_missing_returns_default(self, tmp_path):
        """Missing state file should return empty PortfolioState."""
        tracker = PaperTracker(journal_dir=tmp_path)
        state = tracker._state
        assert isinstance(state, PortfolioState)
        assert state.nav == 1.0

    def test_state_file_partial_data_defaults_remainder(self, tmp_path):
        """Partial JSON data fills missing fields from dataclass defaults."""
        state_file = tmp_path / "portfolio_state.json"
        state_file.write_text(json.dumps({"nav": 0.95}), encoding="utf-8")
        tracker = PaperTracker(journal_dir=tmp_path)
        state = tracker._state
        assert state.nav == 0.95
        assert state.peak == 1.0  # default
