"""Tests for the setup-output ↔ forward-return join."""

from __future__ import annotations

import pandas as pd

from scripts.join_setup_outputs_with_returns import compute_forward_returns, join_records


def _series() -> pd.DataFrame:
    # idx0 = signal day; entry at idx1 open, exit at idx N close.
    rows = []
    dates = ["20260101"] + [f"202601{d:02d}" for d in range(2, 13)]  # 12 sessions
    for i, d in enumerate(dates):
        close = 10.0 + i * 0.5  # rises 0.5/session
        prev_close = 10.0 + (i - 1) * 0.5 if i > 0 else close
        pct = (close / prev_close - 1) * 100 if prev_close else 0.0
        rows.append({"compact": d, "open": 10.0, "high": 12.0, "low": 8.0, "close": close, "pct_change": pct})
    return pd.DataFrame(rows)


def test_compute_forward_returns_entry_next_open_exit_close():
    df = _series()
    rets = compute_forward_returns(df, "20260101")
    # T+1: entry idx1 open=10, exit idx1 close=10.5 → +5%
    assert round(rets[1], 2) == 5.0
    # T+10: exit idx10 close=15.0 → (15-10)/10 = +50%
    assert round(rets[10], 2) == 50.0


def test_compute_forward_returns_none_when_future_missing():
    df = _series().iloc[:3]  # only signal + 2 forward bars
    rets = compute_forward_returns(df, "20260101")
    assert rets[1] is not None
    assert rets[10] is None  # not enough forward bars yet


def test_compute_forward_returns_none_when_signal_absent():
    df = _series()
    rets = compute_forward_returns(df, "20259999")
    assert all(v is None for v in rets.values())


def test_join_records_attaches_returns_and_realized_flag():
    df = _series()
    records = [
        {"ticker": "000001", "signal_date": "20260101", "plan_eligible": True},
        {"ticker": "999999", "signal_date": "20260101", "plan_eligible": False},
    ]
    joined = join_records(records, {"000001": df})
    a = next(j for j in joined if j["ticker"] == "000001")
    assert a["realized"] is True
    assert round(a["return_t1"], 2) == 5.0
    b = next(j for j in joined if j["ticker"] == "999999")
    assert b["realized"] is False  # no price series for this ticker
    assert b["return_t10"] is None
