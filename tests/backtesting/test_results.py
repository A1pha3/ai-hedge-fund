from src.backtesting.output import OutputBuilder


def test_results_builder_builds_rows_and_summary(monkeypatch, portfolio):
    rows_captured = []

    def fake_format_backtest_row(**kwargs):
        # Keep a compact tuple to validate ordering and key fields
        rows_captured.append(
            (
                kwargs.get("date"),
                kwargs.get("ticker"),
                kwargs.get("action"),
                kwargs.get("quantity"),
                kwargs.get("price"),
                kwargs.get("is_summary", False),
                kwargs.get("total_value"),
            )
        )
        return [kwargs.get("date"), kwargs.get("ticker"), kwargs.get("action"), kwargs.get("quantity")]  # minimal row shape

    printed = {"called": False, "rows": None}

    def fake_print_backtest_results(rows):
        printed["called"] = True
        printed["rows"] = rows

    # OutputBuilder imports these directly, so patch in its module
    monkeypatch.setattr("src.backtesting.output.format_backtest_row", fake_format_backtest_row)
    monkeypatch.setattr("src.backtesting.output.print_backtest_results", fake_print_backtest_results)

    rb = OutputBuilder(initial_capital=100_000.0)

    # Prepare state: own 10 AAPL @100, no shorts
    portfolio.apply_long_buy("AAPL", 10, 100.0)
    current_prices = {"AAPL": 100.0}

    agent_output = {
        "decisions": {"AAPL": {"action": "buy", "quantity": 10}},
        "analyst_signals": {"agentA": {"AAPL": {"signal": "bullish"}}},
    }

    rows = rb.build_day_rows(
        date_str="2024-01-02",
        tickers=["AAPL"],
        agent_output=agent_output,
        executed_trades={"AAPL": 10},
        current_prices=current_prices,
        portfolio=portfolio,
        performance_metrics={"sharpe_ratio": None, "sortino_ratio": None, "max_drawdown": None},
        total_value=100_000.0,
    )
    rb.print_rows(rows)

    # We should have 2 rows produced: 1 per-ticker + 1 summary
    assert len(printed["rows"]) == 2
    # The captured tuples include a summary row with total_value
    assert any(r[5] and r[6] == 100_000.0 for r in rows_captured)


def test_results_builder_handles_active_ticker_without_existing_position(monkeypatch, portfolio):
    row_payloads = []

    def fake_format_backtest_row(**kwargs):
        row_payloads.append(kwargs)
        return [kwargs.get("ticker"), kwargs.get("long_shares"), kwargs.get("short_shares"), kwargs.get("position_value")]

    monkeypatch.setattr("src.backtesting.output.format_backtest_row", fake_format_backtest_row)

    rb = OutputBuilder(initial_capital=100_000.0)
    portfolio.apply_long_buy("AAPL", 10, 100.0)

    rows = rb.build_day_rows(
        date_str="2024-01-03",
        tickers=["AAPL", "NVDA"],
        agent_output={
            "decisions": {
                "AAPL": {"action": "hold", "quantity": 0},
                "NVDA": {"action": "buy", "quantity": 100},
            },
            "analyst_signals": {},
        },
        executed_trades={"AAPL": 0, "NVDA": 0},
        current_prices={"AAPL": 100.0, "NVDA": 50.0},
        portfolio=portfolio,
        performance_metrics={"sharpe_ratio": None, "sortino_ratio": None, "max_drawdown": None},
        total_value=100_000.0,
    )

    assert rows[1] == ["NVDA", 0, 0, 0.0]
    nvda_row = next(payload for payload in row_payloads if payload.get("ticker") == "NVDA")
    assert nvda_row["long_shares"] == 0
    assert nvda_row["short_shares"] == 0
    assert nvda_row["position_value"] == 0.0
