from __future__ import annotations

from typing import Any

import pandas as pd

from scripts.generate_btst_realized_prices import generate_realized_prices


def test_generate_realized_prices_computes_next_day_returns(monkeypatch) -> None:
    # Build a deterministic 6-bar window: T + next 5 trading days
    idx = pd.to_datetime(
        [
            "2026-05-28",
            "2026-05-29",
            "2026-06-01",
            "2026-06-02",
            "2026-06-03",
            "2026-06-04",
        ]
    )

    frame = pd.DataFrame(
        {
            "open": [10.0, 10.2, 10.5, 10.4, 10.6, 10.7],
            "high": [10.3, 11.0, 10.9, 12.0, 10.8, 11.5],
            "low": [9.8, 10.0, 10.2, 10.1, 10.4, 10.5],
            "close": [10.0, 10.4, 10.3, 10.2, 10.7, 10.6],
        },
        index=idx,
    )

    def fake_get_price_data(ticker: str, start: str, end: str) -> pd.DataFrame:  # noqa: ARG001
        return frame

    def fake_get_prices_robust(*args: Any, **kwargs: Any):  # noqa: ANN401
        raise AssertionError("fallback path should not be used in this test")

    monkeypatch.setattr("scripts.generate_btst_realized_prices.get_price_data", fake_get_price_data)
    monkeypatch.setattr("scripts.generate_btst_realized_prices.get_prices_robust", fake_get_prices_robust)

    payload = generate_realized_prices(signal_date="2026-05-28", tickers=["002222"])
    row = payload["002222"]

    # trade_close = 10.0, next_open = 10.2, next_high = 11.0, next_close = 10.4
    assert row["data_status"] == "ok"
    assert row["next_trade_date"] == "2026-05-29"
    assert row["next_open_return"] == 0.02
    assert row["next_high_return"] == 0.1
    assert row["next_close_return"] == 0.04
    assert row["next_open_to_close_return"] == round((10.4 / 10.2) - 1.0, 6)

    # max high from open over T+1..T+5 = 12.0 / 10.2 - 1
    assert row["max_high_t1_t5_from_open"] == round((12.0 / 10.2) - 1.0, 6)
    assert row["max_high_t1_t5_trade_date"] == "2026-06-02"
