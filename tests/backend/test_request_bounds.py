"""c310+c311 (loops 43-44): production-readiness — bound the two web request
multipliers that determine total hedge-fund-run work.

The web money-acting endpoints (hedge-fund run, backtest, rerun) accepted
unbounded ``tickers`` AND unbounded ``graph_nodes``. Total agent executions per
request is approximately ``len(tickers) x len(graph_nodes)`` (each graph node
becomes one agent registered in the StateGraph, and each agent runs once per
ticker — see ``app/backend/services/graph.py`` ``create_graph``). Either field
unbounded => resource exhaustion / cost-DoS / timeout on the pre-production web
app. CLI/cron don't use HedgeFundRequest (they build the graph directly), so
bounding the web model is safe.

- c310: tickers default 25 (interactive use is 2-5 per CLAUDE.md), env
  ``HEDGE_FUND_MAX_TICKERS``.
- c311: graph_nodes default 50 (system has 20 canonical agents — 18 in
  ANALYST_CONFIG + risk_manager + portfolio_manager; 2.5x headroom for
  duplicates / utility / notes / group nodes), env
  ``HEDGE_FUND_MAX_GRAPH_NODES``.

Bounding one multiplier but not the other leaves the DoS vector open via the
unbounded one, so both are guarded.
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


def _nodes(n: int) -> list[GraphNode]:
    return [GraphNode(id=f"agent_{i}") for i in range(n)]


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
