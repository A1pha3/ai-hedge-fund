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


# ---------------------------------------------------------------------------
# c311 graph_nodes bound — the second request multiplier.
#
# Commit 6f113912 claimed to add this guard (test docstring documents default
# 50 + env HEDGE_FUND_MAX_GRAPH_NODES) but the schemas.py validator was never
# implemented — graph_nodes stayed unbounded at every layer (model, route,
# create_graph). Total agent executions per run ≈ len(tickers) × len(graph_nodes);
# bounding tickers but not graph_nodes leaves the cost-DoS vector open via the
# other multiplier. These tests pin the documented spec.
# ---------------------------------------------------------------------------


def _hf_with_nodes(n_nodes: int, tickers: list[str] | None = None) -> HedgeFundRequest:
    return HedgeFundRequest(
        tickers=tickers or ["000001"],
        graph_nodes=_nodes(n_nodes),
        graph_edges=[],
    )


def test_graph_nodes_within_default_bound_ok():
    # default 50 (per docstring: 20 canonical agents + headroom) → OK
    assert len(_hf_with_nodes(50).graph_nodes) == 50


def test_graph_nodes_exceeding_default_bound_raises():
    # 51 > default 50 → ValidationError
    with pytest.raises(ValidationError) as ei:
        _hf_with_nodes(51)
    assert "graph_nodes" in str(ei.value).lower() or "nodes" in str(ei.value).lower()


def test_graph_nodes_at_default_bound_boundary_ok():
    # exactly 50 → OK (off-by-one guard)
    assert len(_hf_with_nodes(50).graph_nodes) == 50


def test_graph_nodes_bound_configurable_via_env(monkeypatch):
    monkeypatch.setenv("HEDGE_FUND_MAX_GRAPH_NODES", "5")
    assert len(_hf_with_nodes(5).graph_nodes) == 5
    with pytest.raises(ValidationError):
        _hf_with_nodes(6)


def test_graph_nodes_bound_reads_env_at_validation_time(monkeypatch):
    # not import-time: changing env between two constructions takes effect
    monkeypatch.setenv("HEDGE_FUND_MAX_GRAPH_NODES", "100")
    assert len(_hf_with_nodes(60).graph_nodes) == 60  # under 100 → OK
    monkeypatch.setenv("HEDGE_FUND_MAX_GRAPH_NODES", "40")
    with pytest.raises(ValidationError):  # now 60 > 40
        _hf_with_nodes(60)


def test_graph_nodes_nonpositive_env_falls_back_to_default(monkeypatch):
    # non-positive / unparseable → default (don't reject everything)
    monkeypatch.setenv("HEDGE_FUND_MAX_GRAPH_NODES", "0")
    assert len(_hf_with_nodes(50).graph_nodes) == 50  # default still applies
    monkeypatch.setenv("HEDGE_FUND_MAX_GRAPH_NODES", "not-a-number")
    assert len(_hf_with_nodes(50).graph_nodes) == 50


def test_backtest_inherits_graph_nodes_bound():
    # BacktestRequest subclasses BaseHedgeFundRequest → graph_nodes also bounded
    with pytest.raises(ValidationError):
        BacktestRequest(
            tickers=["000001"],
            graph_nodes=_nodes(51),
            graph_edges=[],
            start_date="2024-01-02",
            end_date="2024-02-01",
        )


def test_graph_nodes_error_message_discloses_limit_and_env_knob(monkeypatch):
    monkeypatch.setenv("HEDGE_FUND_MAX_GRAPH_NODES", "3")
    with pytest.raises(ValidationError) as ei:
        _hf_with_nodes(4)
    msg = str(ei.value)
    assert "3" in msg and "HEDGE_FUND_MAX_GRAPH_NODES" in msg


def test_both_multipliers_bounded_simultaneously(monkeypatch):
    # the core DoS math: len(tickers) × len(graph_nodes). Both must be bounded
    # or the vector stays open via the unbounded one. Tight caps on both → raise.
    monkeypatch.setenv("HEDGE_FUND_MAX_TICKERS", "3")
    monkeypatch.setenv("HEDGE_FUND_MAX_GRAPH_NODES", "3")
    with pytest.raises(ValidationError):
        HedgeFundRequest(
            tickers=["000001"] * 4,  # exceeds tickers cap
            graph_nodes=_nodes(4),  # also exceeds graph_nodes cap
            graph_edges=[],
        )
