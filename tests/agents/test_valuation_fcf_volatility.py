"""Tests for valuation.calculate_fcf_volatility observability.

The FCF-volatility fallback path swallowed every exception and returned a silent
0.5 "moderate volatility" — masking real data/computation failures behind a
confident-looking signal that feeds valuation confidence and the discount logic.
These tests pin the contract that the fallback still returns 0.5 *and* that the
swallow is now traceable via the module logger.
"""

from __future__ import annotations

import logging

import pytest

from src.agents import valuation


def _force_stats_failure(monkeypatch):
    """Make statistics.mean raise so the except branch is exercised."""

    def _boom(_data):
        raise RuntimeError("simulated stats failure")

    monkeypatch.setattr(valuation.statistics, "mean", _boom)


def test_calculate_fcf_volatility_default_when_history_too_short():
    # < 3 points cannot compute volatility — returns the documented default.
    assert valuation.calculate_fcf_volatility([1.0, 2.0]) == 0.5
    assert valuation.calculate_fcf_volatility([]) == 0.5


def test_calculate_fcf_volatility_high_when_mostly_negative():
    # Mostly-negative FCF means unreliable volatility — high-volatility sentinel.
    assert valuation.calculate_fcf_volatility([-1.0, -2.0, 5.0]) == 0.8


def test_calculate_fcf_volatility_normal_case():
    # Positive history of >= 3 points returns a real coefficient of variation.
    vol = valuation.calculate_fcf_volatility([10.0, 10.0, 10.0])
    assert vol == pytest.approx(0.0)
    vol2 = valuation.calculate_fcf_volatility([8.0, 10.0, 12.0])
    assert 0.0 < vol2 <= 1.0


def test_calculate_fcf_volatility_swallow_is_now_logged(caplog, monkeypatch):
    """Exception in the stats path must be traceable via the module logger.

    Previously `except Exception: return 0.5` had no log, so a real computation
    failure was indistinguishable from a genuine moderate-volatility signal. The
    fallback return value is preserved; this test only asserts observability.
    """
    _force_stats_failure(monkeypatch)

    with caplog.at_level(logging.DEBUG, logger="src.agents.valuation"):
        result = valuation.calculate_fcf_volatility([8.0, 10.0, 12.0])

    # Behavior preserved: silent fallback still returns the documented 0.5.
    assert result == 0.5
    # Observability: the swallow is now logged (at DEBUG or higher).
    assert any(
        "fcf_volatility" in rec.message.lower() or "volatility" in rec.message.lower()
        for rec in caplog.records
    ), f"expected a log record mentioning volatility, got: {[r.message for r in caplog.records]}"
