"""Backtest benchmark calculator tests.

Covers BH-017 family residual: ``BenchmarkCalculator.get_return_pct`` used to
``except Exception: return None`` with no logger, silently degrading the
backtest's benchmark/excess-return comparison (R50 same-family — backtest data
correctness path). These tests lock in the observable-degradation contract.
"""

from __future__ import annotations

import logging

import pandas as pd
import pytest

from src.backtesting.benchmarks import BenchmarkCalculator


@pytest.fixture
def calculator() -> BenchmarkCalculator:
    return BenchmarkCalculator()


def _make_price_df(close_values: list[float]) -> pd.DataFrame:
    """Build a minimal price frame matching ``prices_to_df`` schema."""
    rows = [{"time": f"2024-01-0{i+1}", "open": c, "close": c, "high": c, "low": c, "volume": 1000} for i, c in enumerate(close_values)]
    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["time"])
    df.set_index("Date", inplace=True)
    for col in ["open", "close", "high", "low", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.sort_index(inplace=True)
    return df


def test_get_return_pct_basic_buy_and_hold(calculator: BenchmarkCalculator, monkeypatch):
    """(last/first - 1) * 100 simple return."""
    df = _make_price_df([100.0, 110.0])
    monkeypatch.setattr("src.backtesting.benchmarks.get_price_data", lambda *a, **k: df)
    assert calculator.get_return_pct("SH000300", "2024-01-01", "2024-01-02") == pytest.approx(10.0)


def test_get_return_pct_empty_df_returns_none(calculator: BenchmarkCalculator, monkeypatch):
    monkeypatch.setattr("src.backtesting.benchmarks.get_price_data", lambda *a, **k: pd.DataFrame())
    assert calculator.get_return_pct("SH000300", "2024-01-01", "2024-01-02") is None


def test_get_return_pct_first_close_nan_returns_none(calculator: BenchmarkCalculator, monkeypatch):
    """NaN first close is unrecoverable for a return calc."""
    df = _make_price_df([float("nan"), 110.0])
    monkeypatch.setattr("src.backtesting.benchmarks.get_price_data", lambda *a, **k: df)
    assert calculator.get_return_pct("SH000300", "2024-01-01", "2024-01-02") is None


def test_get_return_pct_last_close_nan_recovers_last_valid(calculator: BenchmarkCalculator, monkeypatch):
    """NaN last close falls back to the last valid close in the series."""
    df = _make_price_df([100.0, 120.0, float("nan")])
    monkeypatch.setattr("src.backtesting.benchmarks.get_price_data", lambda *a, **k: df)
    assert calculator.get_return_pct("SH000300", "2024-01-01", "2024-01-03") == pytest.approx(20.0)


def test_get_return_pct_data_fetch_failure_logs_degradation(calculator: BenchmarkCalculator, monkeypatch, caplog):
    """BH-017 family: data-fetch failure must not be silent (R50 same-family).

    Regression guard: benchmark failure degrades the backtest excess-return
    comparison silently; it must emit a debug log so operators can diagnose why
    the benchmark/excess columns went missing.
    """
    monkeypatch.setattr(
        "src.backtesting.benchmarks.get_price_data",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("upstream API down")),
    )
    with caplog.at_level(logging.DEBUG, logger="src.backtesting.benchmarks"):
        result = calculator.get_return_pct("SH000300", "2024-01-01", "2024-01-02")
    assert result is None
    assert any("benchmark" in rec.message.lower() and "sh000300" in rec.message.lower() for rec in caplog.records), "benchmark fetch failure must emit a diagnosable debug log (BH-017 family)"


def test_get_daily_turnovers_per_ticker_failure_logs_degradation(monkeypatch, caplog):
    """BH-017 family (R50 same-family): per-ticker turnover fetch failure in
    ``MarketDataLoader.get_daily_turnovers`` was a silent ``continue``. A
    systematic upstream failure would silently drop turnover data recorded
    into the backtest day state. It must emit a debug log for diagnosability.
    """
    from src.backtesting.engine_market_data import MarketDataLoader
    from src.backtesting.portfolio import Portfolio

    loader = MarketDataLoader(
        tickers=["000001"],
        start_date="2024-01-01",
        end_date="2024-01-31",
        portfolio=Portfolio(tickers=["000001"], initial_cash=100_000.0, margin_requirement=0.5),
        exit_reentry_cooldowns={},
    )

    def _boom(*args, **kwargs):
        raise RuntimeError("upstream API down")

    monkeypatch.setattr("src.backtesting.engine_market_data.get_price_data", _boom)
    with caplog.at_level(logging.DEBUG, logger="src.backtesting.engine_market_data"):
        result = loader.get_daily_turnovers(["000001"], "2024-01-01", "2024-01-02")
    assert result == {}
    assert any("000001" in rec.message and "turnover" in rec.message.lower() for rec in caplog.records), "per-ticker turnover fetch failure must emit a diagnosable debug log (BH-017 family)"
