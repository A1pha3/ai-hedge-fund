from __future__ import annotations

import sys
import types

import pandas as pd
import pytest


def test_resolve_next_trade_date_strict_handles_weekend(monkeypatch):
    # Friday -> Monday
    from src.paper_trading import btst_trade_calendar as cal

    monkeypatch.setattr(cal, "_load_open_trade_dates_cn_sse", lambda *_args, **_kwargs: (["20260605", "20260608"], "tushare_trade_cal"))

    resolved = cal.resolve_next_trade_date_cn_sse_strict("2026-06-05")
    assert resolved.next_trade_date_iso == "2026-06-08"
    assert resolved.calendar_source == "tushare_trade_cal"


def test_resolve_next_trade_date_strict_rejects_non_trading_day(monkeypatch):
    from src.paper_trading import btst_trade_calendar as cal

    monkeypatch.setattr(cal, "_load_open_trade_dates_cn_sse", lambda *_args, **_kwargs: (["20260605", "20260608"], "tushare_trade_cal"))

    with pytest.raises(ValueError, match="not an SSE open trading day"):
        cal.resolve_next_trade_date_cn_sse_strict("2026-06-07")


def test_load_open_trade_dates_falls_back_to_akshare(monkeypatch):
    from src.paper_trading import btst_trade_calendar as cal

    # Force tushare path to return empty
    monkeypatch.setattr(cal, "_get_pro", lambda: object())
    monkeypatch.setattr(cal, "_cached_tushare_dataframe_call", lambda *_args, **_kwargs: None)

    stub_ak = types.SimpleNamespace(
        tool_trade_date_hist_sina=lambda: pd.DataFrame({"trade_date": pd.to_datetime(["2026-06-05", "2026-06-08"])})
    )
    monkeypatch.setitem(sys.modules, "akshare", stub_ak)

    dates, source = cal._load_open_trade_dates_cn_sse("20260605", "20260608")
    assert dates == ["20260605", "20260608"]
    assert source == "akshare_sina"
