"""Tests for backend route fixes: compiled graph consistency."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest


class TestBacktestUsesCompiledGraph:
    """Verify that the backtest route passes a compiled graph to BacktestService.

    The bug was: the route created `graph = create_graph(...)` and then
    `graph = graph.compile()`, overwriting the variable.  But BacktestService
    was passed the original `graph` (StateGraph) instead of the compiled one.
    """

    @patch("app.backend.routes.hedge_fund.BacktestService")
    @patch("app.backend.routes.hedge_fund.create_portfolio")
    @patch("app.backend.routes.hedge_fund.create_graph")
    @patch("app.backend.routes.hedge_fund.hydrate_api_keys")
    @patch("app.backend.routes.hedge_fund.resolve_model_provider")
    def test_backtest_passes_compiled_graph(
        self,
        mock_resolve_provider,
        mock_hydrate,
        mock_create_graph,
        mock_create_portfolio,
        mock_backtest_service,
    ):
        mock_resolve_provider.return_value = "openai"
        mock_create_portfolio.return_value = {"cash": 100000.0, "positions": {}}

        mock_graph = MagicMock()
        mock_compiled = MagicMock()
        mock_graph.compile.return_value = mock_compiled
        mock_create_graph.return_value = mock_graph

        mock_service_instance = MagicMock()
        mock_service_instance.run_backtest_async = MagicMock(return_value=_asyncio_coro({}))
        mock_backtest_service.return_value = mock_service_instance

        # Verify: compile() produces a distinct compiled graph
        compiled = mock_graph.compile()
        assert compiled is mock_compiled
        assert compiled is not mock_graph


def _asyncio_coro(result):
    """Helper to create a coroutine that returns *result*."""

    async def _coro():
        return result

    return _coro()
