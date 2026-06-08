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


def test_extract_open_dates_drops_nan_cal_date_rows():
    """NaN cal_date values must not pollute the open_dates list as the
    literal string "nan" — otherwise downstream callers silently fail
    to find the signal date inside the sorted set.
    """
    from src.paper_trading import btst_trade_calendar as cal

    df = pd.DataFrame({"cal_date": ["2026-06-05", None, "2026-06-08", float("nan")]})

    dates = cal._extract_open_dates_from_frame(df, "20260605", "20260608")

    assert "nan" not in dates
    assert "NaT" not in dates
    assert dates == ["20260605", "20260608"]


def test_extract_open_dates_drops_nan_trade_date_rows():
    """The trade_date branch must also tolerate NaN / None rows without
    raising or returning the literal "nan" string.
    """
    from src.paper_trading import btst_trade_calendar as cal

    df = pd.DataFrame(
        {
            "trade_date": [
                pd.Timestamp("2026-06-05"),
                None,
                float("nan"),
                pd.Timestamp("2026-06-08"),
            ]
        }
    )

    dates = cal._extract_open_dates_from_frame(df, "20260605", "20260608")

    assert dates == ["20260605", "20260608"]


def test_extract_open_dates_drops_out_of_range_rows():
    """Rows outside the requested compact window must be filtered out
    so the caller cannot accidentally index into an out-of-range date.
    """
    from src.paper_trading import btst_trade_calendar as cal

    df = pd.DataFrame({"cal_date": ["2026-06-01", "2026-06-05", "2026-06-08", "2026-06-30"]})

    dates = cal._extract_open_dates_from_frame(df, "20260605", "20260610")

    assert dates == ["20260605", "20260608"]
