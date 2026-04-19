import json

import pandas as pd
import pytest

from src.backtesting.engine import BacktestEngine, PipelineModeDayState
from src.execution.models import ExecutionPlan, LayerCResult, PendingOrder
from src.portfolio.models import ExitSignal
from src.portfolio.models import PositionPlan
from src.research.artifacts import FileSelectionArtifactWriter


class StubPipeline:
    def __init__(self, post_market_plans, intraday_responses):
        self.post_market_plans = list(post_market_plans)
        self.intraday_responses = list(intraday_responses)
        self.post_market_calls = []
        self.pre_market_calls = []
        self.intraday_calls = []

    def run_post_market(self, trade_date: str, portfolio_snapshot: dict | None = None, blocked_buy_tickers: dict | None = None) -> ExecutionPlan:
        self.post_market_calls.append((trade_date, portfolio_snapshot or {}, blocked_buy_tickers or {}))
        if self.post_market_plans:
            return self.post_market_plans.pop(0)
        return ExecutionPlan(date=trade_date, portfolio_snapshot=portfolio_snapshot or {})

    def run_pre_market(self, plan: ExecutionPlan, trade_date_t1: str, **kwargs) -> ExecutionPlan:
        self.pre_market_calls.append((trade_date_t1, plan))
        return plan

    def run_intraday(self, plan: ExecutionPlan, trade_date_t1: str, **kwargs):
        self.intraday_calls.append((trade_date_t1, kwargs))
        if self.intraday_responses:
            return self.intraday_responses.pop(0)
        return [], [], {"pause_new_buys": False, "forced_reduce_ratio": 0.0}


def _patch_market_data(monkeypatch, closes_by_ticker: dict[str, dict[str, float]]) -> None:
    monkeypatch.setattr("src.backtesting.engine.get_prices", lambda *a, **k: None)
    monkeypatch.setattr("src.backtesting.engine.get_financial_metrics", lambda *a, **k: [])
    monkeypatch.setattr("src.backtesting.engine.get_insider_trades", lambda *a, **k: [])
    monkeypatch.setattr("src.backtesting.engine.get_company_news", lambda *a, **k: [])
    monkeypatch.setattr("src.backtesting.output.print_backtest_results", lambda *a, **k: None)
    monkeypatch.setattr("src.backtesting.engine.get_limit_list", lambda *a, **k: None)

    def fake_get_price_data(ticker: str, start_date: str, end_date: str, api_key=None):
        closes = closes_by_ticker[ticker]
        rows = [
            {"date": date_str, "close": close, "open": close, "high": close, "low": close, "volume": 1_000_000}
            for date_str, close in closes.items()
            if start_date <= date_str <= end_date
        ]
        frame = pd.DataFrame(rows)
        if frame.empty:
            return frame
        frame["date"] = pd.to_datetime(frame["date"])
        frame.set_index("date", inplace=True)
        return frame[["open", "close", "high", "low", "volume"]]

    monkeypatch.setattr("src.backtesting.engine.get_price_data", fake_get_price_data)
    monkeypatch.setattr("src.backtesting.benchmarks.get_price_data", fake_get_price_data)


def test_pipeline_mode_executes_buy_on_t_plus_one(monkeypatch):
    _patch_market_data(
        monkeypatch,
        {
            "AAPL": {
                "2024-03-01": 10.0,
                "2024-03-04": 11.0,
                "2024-03-05": 12.0,
            },
            "SPY": {
                "2024-03-01": 100.0,
                "2024-03-04": 101.0,
                "2024-03-05": 102.0,
            },
        },
    )
    plan = ExecutionPlan(
        date="20240301",
        buy_orders=[PositionPlan(ticker="AAPL", shares=100, amount=1000.0, score_final=0.8, execution_ratio=1.0)],
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
    )
    pipeline = StubPipeline(
        post_market_plans=[plan, ExecutionPlan(date="20240304", portfolio_snapshot={})],
        intraday_responses=[(plan.buy_orders, [], {"pause_new_buys": False, "forced_reduce_ratio": 0.0})],
    )

    engine = BacktestEngine(
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
        tickers=["AAPL"],
        start_date="2024-03-01",
        end_date="2024-03-05",
        initial_capital=100000.0,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=0.0,
        backtest_mode="pipeline",
        pipeline=pipeline,
    )

    engine.run_backtest()

    snapshot = engine._portfolio.get_snapshot()
    assert snapshot["positions"]["AAPL"]["long"] == 100
    assert snapshot["positions"]["AAPL"]["entry_date"] == "20240304"
    assert snapshot["positions"]["AAPL"]["holding_days"] == 1
    assert snapshot["positions"]["AAPL"]["max_unrealized_pnl_pct"] == pytest.approx(0.0876, abs=1e-4)
    assert pipeline.post_market_calls[0][0] == "20240301"
    assert pipeline.pre_market_calls[0][0] == "20240304"
    assert pipeline.intraday_calls[0][0] == "20240304"


def test_pipeline_mode_crisis_reduce_trims_existing_position(monkeypatch):
    _patch_market_data(
        monkeypatch,
        {
            "AAPL": {
                "2024-03-01": 10.0,
                "2024-03-04": 11.0,
                "2024-03-05": 12.0,
            },
            "SPY": {
                "2024-03-01": 100.0,
                "2024-03-04": 101.0,
                "2024-03-05": 102.0,
            },
        },
    )
    empty_plan = ExecutionPlan(date="20240301", portfolio_snapshot={"cash": 98000.0, "positions": {}})
    pipeline = StubPipeline(
        post_market_plans=[empty_plan, ExecutionPlan(date="20240304", portfolio_snapshot={})],
        intraday_responses=[([], [], {"pause_new_buys": True, "forced_reduce_ratio": 0.5})],
    )

    engine = BacktestEngine(
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
        tickers=["AAPL"],
        start_date="2024-03-01",
        end_date="2024-03-05",
        initial_capital=100000.0,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=0.0,
        backtest_mode="pipeline",
        pipeline=pipeline,
    )
    engine._portfolio.apply_long_buy("AAPL", 200, 10.0)

    engine.run_backtest()

    snapshot = engine._portfolio.get_snapshot()
    assert snapshot["positions"]["AAPL"]["long"] == 100


def test_pipeline_mode_blocks_limit_up_buy(monkeypatch):
    _patch_market_data(
        monkeypatch,
        {
            "000001": {
                "2024-03-01": 10.0,
                "2024-03-04": 11.0,
                "2024-03-05": 12.0,
            },
            "SPY": {
                "2024-03-01": 100.0,
                "2024-03-04": 101.0,
                "2024-03-05": 102.0,
            },
        },
    )
    monkeypatch.setattr(
        "src.backtesting.engine.get_limit_list",
        lambda trade_date: pd.DataFrame([{"ts_code": "000001.SZ", "limit": "U"}]) if trade_date == "20240304" else None,
    )
    plan = ExecutionPlan(
        date="20240301",
        buy_orders=[PositionPlan(ticker="000001", shares=100, amount=1000.0, score_final=0.8, execution_ratio=1.0)],
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
    )
    pipeline = StubPipeline(
        post_market_plans=[plan, ExecutionPlan(date="20240304", portfolio_snapshot={})],
        intraday_responses=[(plan.buy_orders, [], {"pause_new_buys": False, "forced_reduce_ratio": 0.0})],
    )

    engine = BacktestEngine(
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
        tickers=["000001"],
        start_date="2024-03-01",
        end_date="2024-03-04",
        initial_capital=100000.0,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=0.0,
        backtest_mode="pipeline",
        pipeline=pipeline,
    )

    engine.run_backtest()

    snapshot = engine._portfolio.get_snapshot()
    assert snapshot["positions"]["000001"]["long"] == 0
    assert len(engine._pending_buy_queue) == 1


def test_pipeline_mode_pending_buy_executes_after_board_opens(monkeypatch):
    _patch_market_data(
        monkeypatch,
        {
            "000001": {
                "2024-03-01": 10.0,
                "2024-03-04": 11.0,
                "2024-03-05": 10.8,
                "2024-03-06": 11.2,
            },
            "SPY": {
                "2024-03-01": 100.0,
                "2024-03-04": 101.0,
                "2024-03-05": 102.0,
                "2024-03-06": 103.0,
            },
        },
    )
    monkeypatch.setattr(
        "src.backtesting.engine.get_limit_list",
        lambda trade_date: pd.DataFrame([{"ts_code": "000001.SZ", "limit": "U"}]) if trade_date == "20240304" else None,
    )
    plan = ExecutionPlan(
        date="20240301",
        buy_orders=[PositionPlan(ticker="000001", shares=100, amount=1000.0, score_final=0.8, execution_ratio=1.0)],
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
    )
    pipeline = StubPipeline(
        post_market_plans=[plan, ExecutionPlan(date="20240304", portfolio_snapshot={}), ExecutionPlan(date="20240305", portfolio_snapshot={})],
        intraday_responses=[(plan.buy_orders, [], {"pause_new_buys": False, "forced_reduce_ratio": 0.0}), ([], [], {"pause_new_buys": False, "forced_reduce_ratio": 0.0})],
    )

    engine = BacktestEngine(
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
        tickers=["000001"],
        start_date="2024-03-01",
        end_date="2024-03-06",
        initial_capital=100000.0,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=0.0,
        backtest_mode="pipeline",
        pipeline=pipeline,
    )

    engine.run_backtest()

    snapshot = engine._portfolio.get_snapshot()
    assert snapshot["positions"]["000001"]["long"] == 100
    assert engine._pending_buy_queue == []


def test_process_pending_queues_passes_watch_scores_and_dedupes_results(monkeypatch):
    engine = BacktestEngine(
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
        tickers=["000001"],
        start_date="2024-03-01",
        end_date="2024-03-05",
        initial_capital=100000.0,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=0.0,
        backtest_mode="pipeline",
        pipeline=StubPipeline(post_market_plans=[], intraday_responses=[]),
    )
    engine._pending_buy_queue = [PendingOrder(ticker="000001", order_type="buy", shares=100)]
    engine._pending_sell_queue = [PendingOrder(ticker="000002", order_type="sell", shares=50, reason="limit_down")]
    prepared_plan = ExecutionPlan(
        date="20240301",
        watchlist=[LayerCResult(ticker="000001", score_c=0.0, score_final=0.82)],
    )
    captured: dict[str, object] = {}

    def fake_process_buy(**kwargs):
        captured["watch_scores"] = kwargs["watch_scores"]
        kwargs["next_pending_buy"].extend(
            [
                PendingOrder(ticker="000001", order_type="buy", shares=100, queue_days=1),
                PendingOrder(ticker="000001", order_type="buy", shares=100, queue_days=2),
            ]
        )
        kwargs["alerts"].append("buy-alert")

    def fake_process_sell(**kwargs):
        kwargs["next_pending_sell"].extend(
            [
                PendingOrder(ticker="000002", order_type="sell", shares=50, queue_days=1, reason="limit_down"),
                PendingOrder(ticker="000002", order_type="sell", shares=50, queue_days=2, reason="limit_down"),
            ]
        )
        kwargs["alerts"].append("sell-alert")

    monkeypatch.setattr(engine, "_process_single_pending_buy", fake_process_buy)
    monkeypatch.setattr(engine, "_process_single_pending_sell", fake_process_sell)

    next_buy, next_sell, alerts = engine._process_pending_queues(
        prepared_plan=prepared_plan,
        trade_date_compact="20240304",
        current_prices={},
        limit_up=set(),
        limit_down=set(),
        decisions={},
    )

    assert captured["watch_scores"] == {"000001": 0.82}
    assert len(next_buy) == 1
    assert next_buy[0].queue_days == 2
    assert len(next_sell) == 1
    assert next_sell[0].queue_days == 2
    assert alerts == ["buy-alert", "sell-alert"]


def test_record_pipeline_mode_day_builds_and_emits_timing_and_event_payloads(monkeypatch):
    engine = BacktestEngine(
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
        tickers=["AAPL"],
        start_date="2024-03-01",
        end_date="2024-03-05",
        initial_capital=100000.0,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=0.0,
        backtest_mode="pipeline",
        pipeline=StubPipeline(post_market_plans=[], intraday_responses=[]),
    )
    engine._pending_buy_queue = [PendingOrder(ticker="AAPL", order_type="buy", shares=10)]
    engine._pending_sell_queue = [PendingOrder(ticker="AAPL", order_type="sell", shares=5)]
    engine._exit_reentry_cooldowns = {"AAPL": {"blocked_until": "20240311"}}
    engine._portfolio.apply_long_buy("AAPL", 10, 10.0)
    day_context = type("DayContext", (), {"trade_date_compact": "20240304", "active_tickers": ["AAPL"], "load_market_data_seconds": 0.4})()
    prepared_plan = ExecutionPlan(date="20240301", risk_metrics={"counts": {"watchlist_count": 1}})
    pending_plan = ExecutionPlan(date="20240304")
    day_state = PipelineModeDayState(
        decisions={"AAPL": {"action": "buy", "quantity": 10}},
        executed_trades={"AAPL": 10},
        pre_market_seconds=0.1,
        intraday_seconds=0.2,
        append_daily_state_seconds=0.3,
        post_market_seconds=0.4,
        previous_plan_counts={"watchlist_count": 1},
        previous_plan_timing={"post_market_seconds": 0.9},
        previous_plan_funnel_diagnostics={"layer_b": {"kept": 1}},
        prepared_plan=prepared_plan,
    )
    captured: dict[str, object] = {}
    timing_events: list[dict] = []
    event_payloads: list[dict] = []

    monkeypatch.setattr("src.backtesting.engine.collect_execution_plan_observations", lambda pipeline, trade_date: [{"trade_date": trade_date, "status": "ok"}])

    def fake_timing_payload(**kwargs):
        captured["timing_kwargs"] = kwargs
        return {"event": "pipeline_day_timing", "timing_seconds": {"total_day_seconds": 1.5}}

    def fake_event_payload(**kwargs):
        captured["event_kwargs"] = kwargs
        return {"event": "paper_trading_day", "timing_seconds": kwargs["timing_seconds"]}

    monkeypatch.setattr("src.backtesting.engine.build_pipeline_timing_payload", fake_timing_payload)
    monkeypatch.setattr("src.backtesting.engine.build_pipeline_event_payload", fake_event_payload)
    monkeypatch.setattr(engine, "_append_timing_log", lambda payload: timing_events.append(payload))
    monkeypatch.setattr(engine, "_append_pipeline_event", lambda payload: event_payloads.append(payload))

    engine._record_pipeline_mode_day(
        day_context=day_context,
        day_state=day_state,
        pending_plan=pending_plan,
        current_prices={"AAPL": 11.0},
        day_started_at=0.0,
    )

    assert captured["timing_kwargs"]["execution_plan_observations"] == [{"trade_date": "20240304", "status": "ok"}]
    assert captured["timing_kwargs"]["pending_buy_queue_count"] == 1
    assert captured["timing_kwargs"]["pending_sell_queue_count"] == 1
    assert captured["event_kwargs"]["timing_seconds"] == {"total_day_seconds": 1.5}
    assert captured["event_kwargs"]["portfolio_snapshot"]["positions"]["AAPL"]["long"] == 10
    assert captured["event_kwargs"]["exit_reentry_cooldowns"] == {"AAPL": {"blocked_until": "20240311"}}
    assert timing_events == [{"event": "pipeline_day_timing", "timing_seconds": {"total_day_seconds": 1.5}}]
    assert event_payloads == [{"event": "paper_trading_day", "timing_seconds": {"total_day_seconds": 1.5}}]


def test_apply_pipeline_decisions_builds_lookup_maps_and_dedupes_queues(monkeypatch):
    engine = BacktestEngine(
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
        tickers=["AAPL"],
        start_date="2024-03-01",
        end_date="2024-03-05",
        initial_capital=100000.0,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=0.0,
        backtest_mode="pipeline",
        pipeline=StubPipeline(post_market_plans=[], intraday_responses=[]),
    )
    prepared_plan = ExecutionPlan(
        date="20240304",
        buy_orders=[PositionPlan(ticker="AAPL", shares=100, amount=1000.0, score_final=0.8, execution_ratio=1.0)],
        watchlist=[LayerCResult(ticker="MSFT", score_c=0.2, score_final=0.6, action="watch")],
    )
    engine._pending_buy_queue = [PendingOrder(ticker="AAPL", order_type="buy", shares=10)]
    engine._pending_sell_queue = [PendingOrder(ticker="AAPL", order_type="sell", shares=5)]
    captured: dict[str, object] = {}

    def fake_apply_single(**kwargs):
        captured["apply_kwargs"] = kwargs

    monkeypatch.setattr(engine._decision_executor, "_apply_single", fake_apply_single)
    monkeypatch.setattr(engine._decision_executor, "_dedupe_queues", lambda buy_q, sell_q: (
        buy_q.append(PendingOrder(ticker="DONE", order_type="buy", shares=1)) or
        sell_q.append(PendingOrder(ticker="DONE", order_type="sell", shares=1))
    ))

    engine._pending_plan_runner._apply_pipeline_decisions(
        prepared_plan=prepared_plan,
        current_prices={"AAPL": 11.0},
        daily_turnovers={"AAPL": 1000000.0},
        limit_up=set(),
        limit_down=set(),
        trade_date_compact="20240304",
        decisions={"AAPL": {"action": "buy", "quantity": 10}},
        executed_trades={"AAPL": 0},
        pending_buy_queue=engine._pending_buy_queue,
        pending_sell_queue=engine._pending_sell_queue,
    )

    assert captured["apply_kwargs"]["buy_order_by_ticker"] == {"AAPL": prepared_plan.buy_orders[0]}
    assert captured["apply_kwargs"]["watchlist_by_ticker"] == {"MSFT": prepared_plan.watchlist[0]}
    assert engine._pending_buy_queue[-1].ticker == "DONE"
    assert engine._pending_sell_queue[-1].ticker == "DONE"


def test_apply_single_pipeline_decision_skips_when_price_missing(monkeypatch):
    engine = BacktestEngine(
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
        tickers=["AAPL"],
        start_date="2024-03-01",
        end_date="2024-03-05",
        initial_capital=100000.0,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=0.0,
        backtest_mode="pipeline",
        pipeline=StubPipeline(post_market_plans=[], intraday_responses=[]),
    )
    queue_calls: list[dict] = []
    execute_calls: list[dict] = []
    side_effect_calls: list[dict] = []

    monkeypatch.setattr(engine._decision_executor, "_queue_if_blocked", lambda **kwargs: queue_calls.append(kwargs) or False)
    monkeypatch.setattr(engine._decision_executor, "_execute_decision", lambda **kwargs: execute_calls.append(kwargs) or 0)
    monkeypatch.setattr(engine._decision_executor, "_record_side_effects", lambda **kwargs: side_effect_calls.append(kwargs))

    engine._decision_executor._apply_single(
        ticker="AAPL",
        decision={"action": "buy", "quantity": 10},
        current_prices={},
        daily_turnovers={},
        limit_up=set(),
        limit_down=set(),
        trade_date_compact="20240304",
        buy_order_by_ticker={},
        watchlist_by_ticker={},
        executed_trades={},
        pending_buy_queue=engine._pending_buy_queue,
        pending_sell_queue=engine._pending_sell_queue,
    )

    assert queue_calls == []
    assert execute_calls == []
    assert side_effect_calls == []


def test_apply_single_pipeline_decision_executes_and_records_side_effects(monkeypatch):
    engine = BacktestEngine(
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
        tickers=["AAPL"],
        start_date="2024-03-01",
        end_date="2024-03-05",
        initial_capital=100000.0,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=0.0,
        backtest_mode="pipeline",
        pipeline=StubPipeline(post_market_plans=[], intraday_responses=[]),
    )
    captured: dict[str, object] = {}
    executed_trades: dict[str, int] = {}

    monkeypatch.setattr(engine._decision_executor, "_normalize_ticker", lambda ticker: "AAPL")
    def fake_queue(**kwargs):
        captured["queue_kwargs"] = kwargs
        return False

    def fake_execute(**kwargs):
        captured["execute_kwargs"] = kwargs
        return 7

    def fake_side_effects(**kwargs):
        captured["side_effect_kwargs"] = kwargs

    monkeypatch.setattr(engine._decision_executor, "_queue_if_blocked", fake_queue)
    monkeypatch.setattr(engine._decision_executor, "_execute_decision", fake_execute)
    monkeypatch.setattr(engine._decision_executor, "_record_side_effects", fake_side_effects)

    engine._decision_executor._apply_single(
        ticker="AAPL",
        decision={"action": "buy", "quantity": 10},
        current_prices={"AAPL": 11.5},
        daily_turnovers={"AAPL": 1000000.0},
        limit_up={"AAPL"},
        limit_down=set(),
        trade_date_compact="20240304",
        buy_order_by_ticker={"AAPL": object()},
        watchlist_by_ticker={"AAPL": object()},
        executed_trades=executed_trades,
        pending_buy_queue=engine._pending_buy_queue,
        pending_sell_queue=engine._pending_sell_queue,
    )

    assert captured["queue_kwargs"]["normalized_ticker"] == "AAPL"
    assert captured["execute_kwargs"]["price"] == 11.5
    assert captured["execute_kwargs"]["normalized_ticker"] == "AAPL"
    assert executed_trades == {"AAPL": 7}
    assert captured["side_effect_kwargs"]["executed_qty"] == 7


def test_run_pending_pipeline_plan_merges_applies_and_carries_queue_alerts(monkeypatch):
    engine = BacktestEngine(
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
        tickers=["AAPL"],
        start_date="2024-03-01",
        end_date="2024-03-05",
        initial_capital=100000.0,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=0.0,
        backtest_mode="pipeline",
        pipeline=StubPipeline(post_market_plans=[], intraday_responses=[]),
    )
    prepared_plan = ExecutionPlan(date="20240304", risk_alerts=["existing"])
    pending_plan = ExecutionPlan(date="20240303")
    decisions = {"AAPL": {"action": "hold", "quantity": 0}}
    executed_trades = {"AAPL": 0}
    confirmed_orders = [PositionPlan(ticker="AAPL", shares=100, amount=1000.0, score_final=0.8, execution_ratio=1.0)]
    exits = [type("ExitSignalLike", (), {"ticker": "AAPL", "sell_ratio": 1.0})()]
    crisis_response = {"pause_new_buys": False, "forced_reduce_ratio": 0.0}
    captured: dict[str, object] = {}
    runner = engine._pending_plan_runner

    monkeypatch.setattr(
        runner,
        "_prepare_pending_pipeline_plan",
        lambda **kwargs: (
            prepared_plan,
            0.1,
            {"watchlist_count": 2},
            {"post_market_seconds": 0.9},
            {"layer_b": {"kept": 1}},
        ),
    )

    def fake_build_intraday_state(**kwargs):
        from src.backtesting.engine_pending_plan_runner import PendingPipelineIntradayState
        return (
            PendingPipelineIntradayState(
                confirmed_orders=confirmed_orders,
                exits=exits,
                crisis_response=crisis_response,
                queue_alerts=["queued-buy:AAPL"],
                intraday_seconds=0.2,
            ),
            engine._pending_buy_queue,
            engine._pending_sell_queue,
        )

    monkeypatch.setattr(runner, "_build_pending_pipeline_intraday_state", fake_build_intraday_state)

    def fake_merge(**kwargs):
        captured["merge_kwargs"] = kwargs

    def fake_apply(**kwargs):
        captured["apply_kwargs"] = kwargs

    monkeypatch.setattr(runner, "_merge_pending_intraday_decisions", fake_merge)
    monkeypatch.setattr(runner, "_apply_pipeline_decisions", fake_apply)

    result = runner.run_pending_pipeline_plan(
        pending_plan=pending_plan,
        day_context=type(
            "DayContext",
            (),
            {
                "trade_date_compact": "20240304",
                "current_prices": {"AAPL": 11.0},
                "daily_turnovers": {"AAPL": 1000000.0},
                "limit_up": set(),
                "limit_down": set(),
            },
        )(),
        decisions=decisions,
        executed_trades=executed_trades,
        pending_buy_queue=engine._pending_buy_queue,
        pending_sell_queue=engine._pending_sell_queue,
        build_confirmation_inputs_fn=lambda plan, prices: {},
        process_pending_queues_fn=lambda **kw: ([], [], []),
    )

    assert captured["merge_kwargs"]["confirmed_orders"] == confirmed_orders
    assert captured["merge_kwargs"]["exits"] == exits
    assert captured["merge_kwargs"]["crisis_response"] == crisis_response
    assert captured["apply_kwargs"]["prepared_plan"] is prepared_plan
    assert captured["apply_kwargs"]["executed_trades"] is executed_trades
    assert prepared_plan.risk_alerts == ["existing", "queued-buy:AAPL"]
    assert result.prepared_plan is prepared_plan
    assert result.pre_market_seconds == 0.1
    assert result.intraday_seconds == 0.2
    assert result.previous_plan_counts == {"watchlist_count": 2}
    assert result.previous_plan_timing == {"post_market_seconds": 0.9}
    assert result.previous_plan_funnel_diagnostics == {"layer_b": {"kept": 1}}


def test_queue_limit_blocked_pipeline_decision_queues_buy_and_marks_zero_execution():
    engine = BacktestEngine(
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
        tickers=["AAPL"],
        start_date="2024-03-01",
        end_date="2024-03-05",
        initial_capital=100000.0,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=0.0,
        backtest_mode="pipeline",
        pipeline=StubPipeline(post_market_plans=[], intraday_responses=[]),
    )
    executed_trades: dict[str, int] = {}

    blocked = engine._decision_executor._queue_limit_blocked(
        ticker="AAPL",
        decision={"action": "buy", "quantity": 10},
        normalized_ticker="AAPL",
        trade_date_compact="20240304",
        limit_up={"AAPL"},
        limit_down=set(),
        buy_order_by_ticker={"AAPL": type("BuyOrderLike", (), {"score_final": 0.8, "amount": 1200.0})()},
        executed_trades=executed_trades,
        pending_buy_queue=engine._pending_buy_queue,
        pending_sell_queue=engine._pending_sell_queue,
    )

    assert blocked is True
    assert executed_trades == {"AAPL": 0}
    assert len(engine._pending_buy_queue) == 1
    assert engine._pending_buy_queue[0].ticker == "AAPL"
    assert engine._pending_buy_queue[0].amount == 1200.0


def test_queue_limit_blocked_pipeline_decision_queues_sell_with_ratio_and_reason():
    engine = BacktestEngine(
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
        tickers=["AAPL"],
        start_date="2024-03-01",
        end_date="2024-03-05",
        initial_capital=100000.0,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=0.0,
        backtest_mode="pipeline",
        pipeline=StubPipeline(post_market_plans=[], intraday_responses=[]),
    )
    engine._portfolio.apply_long_buy("AAPL", 40, 10.0)
    executed_trades: dict[str, int] = {}

    blocked = engine._decision_executor._queue_limit_blocked(
        ticker="AAPL",
        decision={"action": "sell", "quantity": 10, "reason": "limit_down_exit"},
        normalized_ticker="AAPL",
        trade_date_compact="20240304",
        limit_up=set(),
        limit_down={"AAPL"},
        buy_order_by_ticker={},
        executed_trades=executed_trades,
        pending_buy_queue=engine._pending_buy_queue,
        pending_sell_queue=engine._pending_sell_queue,
    )

    assert blocked is True
    assert executed_trades == {"AAPL": 0}
    assert len(engine._pending_sell_queue) == 1
    assert engine._pending_sell_queue[0].reason == "limit_down_exit"
    assert engine._pending_sell_queue[0].sell_ratio == pytest.approx(0.25)


def test_pipeline_mode_registers_defensive_exit_cooldown_for_same_day_post_market(monkeypatch):
    _patch_market_data(
        monkeypatch,
        {
            "AAPL": {
                "2024-03-01": 10.0,
                "2024-03-04": 9.0,
                "2024-03-05": 8.5,
            },
            "SPY": {
                "2024-03-01": 100.0,
                "2024-03-04": 101.0,
                "2024-03-05": 102.0,
            },
        },
    )
    pipeline = StubPipeline(
        post_market_plans=[ExecutionPlan(date="20240301", portfolio_snapshot={}), ExecutionPlan(date="20240304", portfolio_snapshot={})],
        intraday_responses=[([], [ExitSignal(ticker="AAPL", level="position", trigger_reason="hard_stop_loss", sell_ratio=1.0)], {"pause_new_buys": False, "forced_reduce_ratio": 0.0})],
    )

    engine = BacktestEngine(
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
        tickers=["AAPL"],
        start_date="2024-03-01",
        end_date="2024-03-05",
        initial_capital=100000.0,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=0.0,
        backtest_mode="pipeline",
        pipeline=pipeline,
    )
    engine._portfolio.apply_long_buy("AAPL", 100, 10.0)

    engine.run_backtest()

    assert pipeline.post_market_calls[1][0] == "20240304"
    assert pipeline.post_market_calls[1][2]["AAPL"]["trigger_reason"] == "hard_stop_loss"
    assert pipeline.post_market_calls[1][2]["AAPL"]["blocked_until"] == "20240311"


def test_pipeline_mode_records_selection_artifacts_in_event_and_timing_logs(tmp_path, monkeypatch):
    _patch_market_data(
        monkeypatch,
        {
            "AAPL": {
                "2024-03-01": 10.0,
                "2024-03-04": 11.0,
            },
            "SPY": {
                "2024-03-01": 100.0,
                "2024-03-04": 101.0,
            },
        },
    )
    plan = ExecutionPlan(
        date="20240301",
        buy_orders=[PositionPlan(ticker="AAPL", shares=100, amount=1000.0, score_final=0.8, execution_ratio=1.0)],
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        risk_metrics={"counts": {"watchlist_count": 1}},
    )
    pipeline = StubPipeline(
        post_market_plans=[plan],
        intraday_responses=[],
    )
    event_payloads: list[dict] = []

    engine = BacktestEngine(
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
        tickers=["AAPL"],
        start_date="2024-03-01",
        end_date="2024-03-01",
        initial_capital=100000.0,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=0.0,
        backtest_mode="pipeline",
        pipeline=pipeline,
        checkpoint_path=str(tmp_path / "checkpoint.json"),
        pipeline_event_recorder=event_payloads.append,
        selection_artifact_writer=FileSelectionArtifactWriter(artifact_root=tmp_path / "selection_artifacts", run_id="integration_test"),
    )

    engine.run_backtest()

    timing_log_path = tmp_path / "checkpoint.timings.jsonl"
    assert timing_log_path.exists()
    timing_lines = [json.loads(line) for line in timing_log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    day_timing = next(line for line in timing_lines if line.get("event") == "pipeline_day_timing")
    assert day_timing["current_plan"]["selection_artifacts"]["write_status"] == "success"
    assert day_timing["current_plan"]["target_mode"] == "research_only"

    assert event_payloads
    assert event_payloads[0]["current_plan"]["selection_artifacts"]["write_status"] == "success"
    assert event_payloads[0]["current_plan"]["target_mode"] == "research_only"
    assert (tmp_path / "selection_artifacts" / "2024-03-01" / "selection_snapshot.json").exists()
    assert len(pipeline.post_market_calls) == 1
    assert pipeline.post_market_calls[0][0] == "20240301"
    assert pipeline.post_market_calls[0][2] == {}


def test_pipeline_checkpoint_persists_exit_reentry_cooldowns(tmp_path, monkeypatch):
    _patch_market_data(
        monkeypatch,
        {
            "AAPL": {
                "2024-03-01": 10.0,
                "2024-03-04": 11.0,
            },
            "SPY": {
                "2024-03-01": 100.0,
                "2024-03-04": 101.0,
            },
        },
    )
    checkpoint_path = tmp_path / "pipeline-checkpoint.json"

    engine = BacktestEngine(
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
        tickers=["AAPL"],
        start_date="2024-03-01",
        end_date="2024-03-04",
        initial_capital=100000.0,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=0.0,
        backtest_mode="pipeline",
        pipeline=StubPipeline(post_market_plans=[], intraday_responses=[]),
        checkpoint_path=str(checkpoint_path),
    )
    engine._exit_reentry_cooldowns = {
        "AAPL": {"trigger_reason": "hard_stop_loss", "exit_trade_date": "20240304", "blocked_until": "20240311", "reentry_review_until": "20240318"}
    }

    engine._save_checkpoint("2024-03-04")

    restored = BacktestEngine(
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
        tickers=["AAPL"],
        start_date="2024-03-01",
        end_date="2024-03-04",
        initial_capital=100000.0,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=0.0,
        backtest_mode="pipeline",
        pipeline=StubPipeline(post_market_plans=[], intraday_responses=[]),
        checkpoint_path=str(checkpoint_path),
    )
    last_processed_date, pending_plan = restored._load_checkpoint()

    assert last_processed_date == "2024-03-04"
    assert pending_plan is None
    assert restored._exit_reentry_cooldowns["AAPL"]["blocked_until"] == "20240311"
    assert restored._exit_reentry_cooldowns["AAPL"]["reentry_review_until"] == "20240318"


def test_pipeline_mode_pending_sell_executes_after_limit_down_releases(monkeypatch):
    _patch_market_data(
        monkeypatch,
        {
            "000001": {
                "2024-03-01": 10.0,
                "2024-03-04": 9.8,
                "2024-03-05": 10.1,
                "2024-03-06": 10.2,
            },
            "SPY": {
                "2024-03-01": 100.0,
                "2024-03-04": 101.0,
                "2024-03-05": 102.0,
                "2024-03-06": 103.0,
            },
        },
    )
    monkeypatch.setattr(
        "src.backtesting.engine.get_limit_list",
        lambda trade_date: pd.DataFrame([{"ts_code": "000001.SZ", "limit": "D"}]) if trade_date == "20240304" else None,
    )
    exit_signal = type("ExitSignalLike", (), {"ticker": "000001", "sell_ratio": 1.0})()
    pipeline = StubPipeline(
        post_market_plans=[ExecutionPlan(date="20240301", portfolio_snapshot={}), ExecutionPlan(date="20240304", portfolio_snapshot={}), ExecutionPlan(date="20240305", portfolio_snapshot={})],
        intraday_responses=[([], [exit_signal], {"pause_new_buys": False, "forced_reduce_ratio": 0.0}), ([], [], {"pause_new_buys": False, "forced_reduce_ratio": 0.0})],
    )

    engine = BacktestEngine(
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
        tickers=["000001"],
        start_date="2024-03-01",
        end_date="2024-03-06",
        initial_capital=100000.0,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=0.0,
        backtest_mode="pipeline",
        pipeline=pipeline,
    )
    engine._portfolio.apply_long_buy("000001", 100, 10.0)

    engine.run_backtest()

    snapshot = engine._portfolio.get_snapshot()
    assert snapshot["positions"]["000001"]["long"] == 0
    assert engine._pending_sell_queue == []


def test_pipeline_mode_timing_log_includes_funnel_diagnostics(monkeypatch):
    _patch_market_data(
        monkeypatch,
        {
            "AAPL": {
                "2024-03-01": 10.0,
                "2024-03-04": 11.0,
            },
            "SPY": {
                "2024-03-01": 100.0,
                "2024-03-04": 101.0,
            },
        },
    )
    plan = ExecutionPlan(
        date="20240301",
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        risk_metrics={
            "counts": {"layer_a_count": 3, "watchlist_count": 1},
            "timing_seconds": {"total_post_market": 1.23},
            "funnel_diagnostics": {
                "counts": {"layer_a_count": 3, "watchlist_count": 1},
                "filters": {"layer_b": {"filtered_count": 2, "reason_counts": {"below_fast_score_threshold": 2}, "tickers": []}},
                "sell_orders": {"count": 0, "reason_counts": {}, "tickers": []},
            },
        },
    )
    pipeline = StubPipeline(post_market_plans=[plan], intraday_responses=[])

    engine = BacktestEngine(
        agent=lambda **kwargs: {"decisions": {}, "analyst_signals": {}},
        tickers=["AAPL"],
        start_date="2024-03-01",
        end_date="2024-03-01",
        initial_capital=100000.0,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=0.0,
        backtest_mode="pipeline",
        pipeline=pipeline,
    )

    timing_events = []
    engine._append_timing_log = lambda payload: timing_events.append(payload)

    engine.run_backtest()

    pipeline_events = [event for event in timing_events if event.get("event") == "pipeline_day_timing"]
    assert pipeline_events
    assert pipeline_events[-1]["current_plan"]["funnel_diagnostics"]["counts"]["layer_a_count"] == 3
    assert pipeline_events[-1]["current_plan"]["funnel_diagnostics"]["filters"]["layer_b"]["reason_counts"] == {"below_fast_score_threshold": 2}
