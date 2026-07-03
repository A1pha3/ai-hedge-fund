"""c310 (loop 43): production-readiness — bound tickers on HedgeFundRequest.

The web money-acting endpoints (hedge-fund run, backtest, rerun) accepted
unbounded tickers → N tickers × 20 agents + per-ticker data fetches = resource
exhaustion / cost-DoS / timeout for a pre-production web app. No client-side
bound either. CLI/cron don't use HedgeFundRequest (they build the graph
directly), so bounding the web model is safe. Default 25 (interactive use is
typically 2-5 tickers per CLAUDE.md examples); env-configurable for owners who
batch more.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.backend.models.schemas import (
    BacktestRequest,
    GraphEdge,
    GraphNode,
    HedgeFundRequest,
)


def _hf(tickers: list[str]) -> HedgeFundRequest:
    return HedgeFundRequest(tickers=tickers, graph_nodes=[], graph_edges=[])


def test_tickers_within_default_bound_ok():
    req = _hf(["000001"] * 25)
    assert len(req.tickers) == 25


def test_tickers_exceeding_default_bound_raises():
    with pytest.raises(ValidationError) as ei:
        _hf(["000001"] * 26)
    assert "Too many tickers" in str(ei.value) or "max" in str(ei.value).lower()


def test_tickers_at_default_bound_boundary_ok():
    # exactly 25 → OK (off-by-one guard)
    assert len(_hf(["000001"] * 25).tickers) == 25


def test_bound_configurable_via_env(monkeypatch):
    # runtime-configurable (validator reads env at validation time, not import time)
    monkeypatch.setenv("HEDGE_FUND_MAX_TICKERS", "5")
    assert len(_hf(["000001"] * 5).tickers) == 5
    with pytest.raises(ValidationError):
        _hf(["000001"] * 6)


def test_backtest_inherits_bound():
    # BacktestRequest subclasses BaseHedgeFundRequest → also bounded
    with pytest.raises(ValidationError):
        BacktestRequest(
            tickers=["000001"] * 26,
            graph_nodes=[],
            graph_edges=[],
            start_date="2024-01-02",
            end_date="2024-02-01",
        )


def test_error_message_discloses_limit_and_env_knob(monkeypatch):
    monkeypatch.setenv("HEDGE_FUND_MAX_TICKERS", "3")
    with pytest.raises(ValidationError) as ei:
        _hf(["000001"] * 4)
    msg = str(ei.value)
    # operator-facing: tells them the limit + how to raise it
    assert "3" in msg and "HEDGE_FUND_MAX_TICKERS" in msg
