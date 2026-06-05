import asyncio
from types import SimpleNamespace

from app.backend.routes import hedge_fund_streaming


class _PendingRequest:
    def __init__(self) -> None:
        self._disconnect_event = asyncio.Event()

    async def receive(self) -> dict[str, str]:
        await self._disconnect_event.wait()
        return {"type": "http.disconnect"}


class _DummyProgress:
    def __init__(self) -> None:
        self.handlers = []

    def register_handler(self, handler) -> None:
        self.handlers.append(handler)

    def unregister_handler(self, handler) -> None:
        self.handlers.remove(handler)


def _collect(async_iterable) -> list[str]:
    async def _runner() -> list[str]:
        return [event async for event in async_iterable]

    return asyncio.run(_runner())


def test_hydrate_api_keys_only_fetches_when_missing(monkeypatch):
    calls = []

    class DummyApiKeyService:
        def __init__(self, db) -> None:
            calls.append(db)

        def get_api_keys_dict(self) -> dict[str, str]:
            return {"OPENAI_API_KEY": "secret"}

    monkeypatch.setattr(hedge_fund_streaming, "ApiKeyService", DummyApiKeyService)

    request_data = SimpleNamespace(api_keys=None)
    hedge_fund_streaming.hydrate_api_keys(request_data, db="db-session")
    assert request_data.api_keys == {"OPENAI_API_KEY": "secret"}
    assert calls == ["db-session"]

    request_data = SimpleNamespace(api_keys={"EXISTING": "value"})
    hedge_fund_streaming.hydrate_api_keys(request_data, db="unused-session")
    assert request_data.api_keys == {"EXISTING": "value"}
    assert calls == ["db-session"]


def test_create_backtest_progress_event_formats_backtest_results():
    event = hedge_fund_streaming.create_backtest_progress_event(
        {
            "type": "backtest_result",
            "data": {
                "date": "2026-01-03",
                "portfolio_value": 101000.0,
                "cash": 5000.0,
                "decisions": {"AAPL": {"action": "buy", "quantity": 1}},
                "executed_trades": {"AAPL": 1},
                "analyst_signals": {"technical": {"AAPL": {"signal": "bullish"}}},
                "current_prices": {"AAPL": 101.0},
                "long_exposure": 1000.0,
                "short_exposure": 0.0,
                "gross_exposure": 1000.0,
                "net_exposure": 1000.0,
                "long_short_ratio": None,
            },
        }
    )

    assert event is not None
    assert event.status == "Completed 2026-01-03 - Portfolio: $101,000.00"
    assert '"portfolio_value": 101000.0' in event.analysis


def test_stream_hedge_fund_run_emits_progress_and_completion(monkeypatch):
    dummy_progress = _DummyProgress()
    monkeypatch.setattr(hedge_fund_streaming, "progress", dummy_progress)
    monkeypatch.setattr(hedge_fund_streaming, "parse_hedge_fund_response", lambda _content: {"AAPL": {"action": "buy", "quantity": 5}})

    async def fake_run_graph_async(**_kwargs):
        for handler in list(dummy_progress.handlers):
            handler("risk_manager", "AAPL", "Finished analysis", "bullish", "2026-01-01T00:00:00Z")
        return {
            "messages": [SimpleNamespace(content="ignored")],
            "data": {"analyst_signals": {"risk_manager": {"AAPL": {"signal": "bullish"}}}, "current_prices": {"AAPL": 123.45}},
        }

    monkeypatch.setattr(hedge_fund_streaming, "run_graph_async", fake_run_graph_async)

    request_data = SimpleNamespace(
        tickers=["AAPL"],
        start_date="2026-01-01",
        end_date="2026-01-02",
        model_name="demo-model",
    )

    events = _collect(
        hedge_fund_streaming.stream_hedge_fund_run(
            request=_PendingRequest(),
            request_data=request_data,
            graph=object(),
            portfolio={"cash": 1000.0},
            model_provider="demo-provider",
        )
    )

    assert events[0].startswith("event: start")
    assert any("event: progress" in event and "Finished analysis" in event for event in events)
    assert events[-1].startswith("event: complete")
    assert '"current_prices":{"AAPL":123.45}' in events[-1]
    assert dummy_progress.handlers == []


def test_stream_backtest_emits_progress_and_completion(monkeypatch):
    dummy_progress = _DummyProgress()
    monkeypatch.setattr(hedge_fund_streaming, "progress", dummy_progress)

    class DummyBacktestService:
        async def run_backtest_async(self, progress_callback):
            for handler in list(dummy_progress.handlers):
                handler("analyst", "AAPL", "screened", None, "2026-01-01T00:00:00Z")
            progress_callback(
                {
                    "type": "progress",
                    "current_date": "2026-01-02",
                    "current_step": 1,
                    "total_dates": 2,
                }
            )
            progress_callback(
                {
                    "type": "backtest_result",
                    "data": {
                        "date": "2026-01-02",
                        "portfolio_value": 102500.0,
                        "cash": 1500.0,
                        "decisions": {"AAPL": {"action": "hold", "quantity": 0}},
                        "executed_trades": {"AAPL": 0},
                        "analyst_signals": {},
                        "current_prices": {"AAPL": 125.0},
                        "long_exposure": 2000.0,
                        "short_exposure": 0.0,
                        "gross_exposure": 2000.0,
                        "net_exposure": 2000.0,
                        "long_short_ratio": None,
                    },
                }
            )
            await asyncio.sleep(0)
            return {
                "results": [{"date": "2026-01-02"}],
                "performance_metrics": {
                    "sharpe_ratio": 1.5,
                    "sortino_ratio": 2.0,
                    "max_drawdown": -3.2,
                    "max_drawdown_date": "2026-01-02",
                    "long_short_ratio": None,
                    "gross_exposure": 2000.0,
                    "net_exposure": 2000.0,
                },
                "final_portfolio": {"cash": 1500.0},
            }

    events = _collect(hedge_fund_streaming.stream_backtest(request=_PendingRequest(), backtest_service=DummyBacktestService()))

    assert events[0].startswith("event: start")
    assert any("Processing 2026-01-02 (1/2)" in event for event in events)
    assert any("Completed 2026-01-02 - Portfolio: $102,500.00" in event for event in events)
    assert events[-1].startswith("event: complete")
    assert '"total_days":1' in events[-1]
    assert dummy_progress.handlers == []


# ---------------------------------------------------------------------------
# P0 1.1 — 30D Edge card data derivation
# ---------------------------------------------------------------------------


def test_compute_edge_data_bullish_ticker_has_positive_edge():
    signals = {
        "warren_buffett_abc": {"AAPL": {"signal": "bullish", "confidence": 80}},
        "charlie_munger_def": {"AAPL": {"signal": "bullish", "confidence": 70}},
        "risk_management_ghi": {
            "AAPL": {
                "signal": "neutral",
                "confidence": 50,
                "remaining_position_limit": 5000.0,
                "current_price": 100.0,
            }
        },
    }
    decisions = {"AAPL": {"action": "buy", "quantity": 50, "confidence": 80}}
    result = hedge_fund_streaming._compute_edge_data_for_completion(signals, decisions)
    assert "AAPL" in result
    assert result["AAPL"]["expected_30d_edge"] > 0
    assert result["AAPL"]["risk_budget_ratio"] is not None
    assert "可重点关注" in result["AAPL"]["edge_summary"]


def test_compute_edge_data_bearish_ticker_has_negative_edge():
    signals = {
        "warren_buffett_abc": {"TSLA": {"signal": "bearish", "confidence": 60}},
        "charlie_munger_def": {"TSLA": {"signal": "bearish", "confidence": 90}},
        "risk_management_ghi": {
            "TSLA": {
                "signal": "neutral",
                "confidence": 50,
                "remaining_position_limit": 1000.0,
                "current_price": 200.0,
            }
        },
    }
    decisions = {"TSLA": {"action": "short", "quantity": 5, "confidence": 70}}
    result = hedge_fund_streaming._compute_edge_data_for_completion(signals, decisions)
    assert result["TSLA"]["expected_30d_edge"] < 0
    assert "建议避免开仓" in result["TSLA"]["edge_summary"]


def test_compute_edge_data_empty_inputs_returns_empty():
    assert hedge_fund_streaming._compute_edge_data_for_completion({}, {}) == {}
    assert hedge_fund_streaming._compute_edge_data_for_completion(None, None) == {}


def test_compute_edge_data_hold_with_risk_manager():
    signals = {
        "risk_management_ghi": {
            "GOOG": {
                "signal": "neutral",
                "confidence": 50,
                "remaining_position_limit": 0.0,
                "current_price": 100.0,
            }
        }
    }
    decisions = {"GOOG": {"action": "hold", "quantity": 0, "confidence": 0}}
    result = hedge_fund_streaming._compute_edge_data_for_completion(signals, decisions)
    assert "GOOG" in result
    assert result["GOOG"]["expected_30d_edge"] == 0.0
    assert result["GOOG"]["risk_budget_ratio"] == 0.0


def test_compute_edge_data_disagreement_raises_cvar():
    """Mixed bullish+bearish signals should produce a wider tail (higher CVaR)."""
    signals = {
        "warren_buffett_abc": {"NVDA": {"signal": "bullish", "confidence": 60}},
        "charlie_munger_def": {"NVDA": {"signal": "bearish", "confidence": 60}},
    }
    decisions = {"NVDA": {"action": "hold", "quantity": 0, "confidence": 0}}
    result = hedge_fund_streaming._compute_edge_data_for_completion(signals, decisions)
    # Disagreement should add the 0.10 bump to baseline 0.05.
    assert result["NVDA"]["cvar_95"] >= 0.15


def test_compute_edge_data_create_run_completion_includes_edge():
    """``create_run_completion_event`` must include ``edge_data`` in its payload."""
    result = {
        "messages": [SimpleNamespace(content='{"AAPL": {"action": "buy", "quantity": 5, "confidence": 70}}')],
        "data": {
            "analyst_signals": {
                "warren_buffett_abc": {"AAPL": {"signal": "bullish", "confidence": 80}},
                "risk_management_ghi": {
                    "AAPL": {
                        "signal": "neutral",
                        "confidence": 50,
                        "remaining_position_limit": 5000.0,
                        "current_price": 100.0,
                    }
                },
            },
            "current_prices": {"AAPL": 100.0},
        },
    }
    event = hedge_fund_streaming.create_run_completion_event(result)
    assert hasattr(event, "data")
    assert "edge_data" in event.data
    assert "AAPL" in event.data["edge_data"]
