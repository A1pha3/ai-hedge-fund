"""TDD red test: load_current_prices must skip NaN-close rows (R83 same-class
drain — the backtest price-dict path reads the DataFrame via ``iloc[-1]``
directly, bypassing the R83/R132-R137 NaN-skip guards that protect the
df→Price converters).

R83 drained the df→Price converters (AKShareProvider / build_prices_from_dataframe
/ TushareDataSource / tushare daily / Tencent / BaoStock / daily_gainers) by
adding ``if any(not pd.notna(v) for v in ohlc): continue`` — skip NaN rows.
But ``MarketDataLoader.load_current_prices`` (engine_market_data.py:259) reads
the price DataFrame DIRECTLY via ``row = price_data.iloc[-1]`` and stores
``float(row["close"])`` without a ``pd.notna`` check. A NaN close on the last
row (partial / incomplete live feed where the most recent bar is not yet
filled, or a corrupt cache row with volume>0 but close=NaN that passes the
``_is_suspended_row`` volume-only guard) propagates into ``current_prices``,
then into ``calculate_portfolio_value`` → the ENTIRE backtest NAV becomes NaN
silently, poisoning sharpe/sortino/drawdown/max_drawdown_date.

The ``_is_suspended_row`` guard (BETA-007) only checks ``volume <= 0`` — it
does NOT catch a volume>0 / NaN-close row. Fix: skip NaN-close rows the same
way suspended rows are skipped (R83 canonical "skip bad row"). This is the
R83 NaN-row-skip family sibling in the backtest price-dict path.
"""

from __future__ import annotations

import math

import pandas as pd

from src.backtesting.engine_market_data import MarketDataLoader
from src.backtesting.portfolio import Portfolio


def _make_loader(tickers: list[str]) -> MarketDataLoader:
    portfolio = Portfolio(tickers=tickers, initial_cash=100_000.0, margin_requirement=0.5)
    return MarketDataLoader(
        tickers=tickers,
        start_date="2024-01-01",
        end_date="2024-01-31",
        portfolio=portfolio,
        exit_reentry_cooldowns={},
    )


def _make_price_frame(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"])
    frame.set_index("date", inplace=True)
    return frame


class TestLoadCurrentPricesNaNCloseSkip:
    def test_nan_close_last_row_skipped_not_stored(self, monkeypatch) -> None:
        """A NaN close on the last row (partial live feed / corrupt cache with
        volume>0) must be skipped — NOT stored as NaN in current_prices, which
        would silently corrupt the entire backtest NAV via
        calculate_portfolio_value (R83 same-class drain)."""
        loader = _make_loader(["000001", "000002"])

        # 000001: last row NaN close (volume>0, passes _is_suspended_row, but
        # close is NaN — partial feed). 000002: clean.
        def fake_get_price_data(ticker, start, end, api_key=None):
            if ticker == "000001":
                return _make_price_frame(
                    [
                        {"date": "2024-01-14", "close": 10.0, "volume": 1_000_000},
                        {"date": "2024-01-15", "close": float("nan"), "volume": 1_000_000},
                    ]
                )
            return _make_price_frame(
                [
                    {"date": "2024-01-15", "close": 20.0, "volume": 1_000_000},
                ]
            )

        monkeypatch.setattr("src.backtesting.engine_market_data.get_price_data", fake_get_price_data)
        prices = loader.load_current_prices(["000001", "000002"], "2024-01-01", "2024-01-15")

        # 000002 must be present and clean
        assert prices is not None
        assert prices["000002"] == 20.0
        # 000001 must NOT be present (NaN-close row skipped), NOT stored as NaN
        assert "000001" not in prices, "NaN-close row must be skipped (R83 canonical); currently " "load_current_prices stores float(nan) in current_prices, silently " "corrupting the entire backtest NAV via calculate_portfolio_value"

    def test_nan_close_on_earlier_row_uses_last_valid(self, monkeypatch) -> None:
        """If an earlier row has NaN close but the last row is valid, the last
        valid close is used (iloc[-1] is the last row; this confirms the guard
        only skips when the LAST row is NaN, not historical NaN which pandas
        indexing already handles)."""
        loader = _make_loader(["000001"])

        def fake_get_price_data(ticker, start, end, api_key=None):
            return _make_price_frame(
                [
                    {"date": "2024-01-14", "close": float("nan"), "volume": 1_000_000},
                    {"date": "2024-01-15", "close": 11.0, "volume": 1_000_000},
                ]
            )

        monkeypatch.setattr("src.backtesting.engine_market_data.get_price_data", fake_get_price_data)
        prices = loader.load_current_prices(["000001"], "2024-01-01", "2024-01-15")
        assert prices is not None
        assert prices["000001"] == 11.0
