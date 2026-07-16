from __future__ import annotations

from contextvars import Context

import pandas as pd

from src.tools import tushare_api


def test_interleaved_reference_captures_keep_their_requested_membership(
    monkeypatch,
) -> None:
    monkeypatch.setattr(tushare_api, "_get_pro", lambda: object())

    def provider(_pro, api_name: str, **_kwargs):
        if api_name == "stock_basic":
            return pd.DataFrame(
                [
                    {"ts_code": "000001.SZ", "name": "平安银行", "list_status": "L"},
                    {"ts_code": "000002.SZ", "name": "万科A", "list_status": "L"},
                ]
            )
        if api_name == "index_classify":
            return pd.DataFrame(
                [{"index_code": "801780.SI", "industry_name": "银行"}]
            )
        if api_name == "index_member":
            return pd.DataFrame(
                [
                    {
                        "con_code": "000001.SZ",
                        "in_date": "20000101",
                        "out_date": "20260717",
                    },
                    {
                        "con_code": "000002.SZ",
                        "in_date": "20260717",
                        "out_date": None,
                    },
                ]
            )
        raise AssertionError(api_name)

    monkeypatch.setattr(tushare_api, "_call_tushare_dataframe_api", provider)
    monkeypatch.setattr(
        tushare_api,
        "_reference_observation_date",
        lambda: tushare_api._active_daily_readiness_capture_date(),
        raising=False,
    )

    context_16 = Context()
    context_17 = Context()
    token_16 = context_16.run(
        tushare_api.begin_daily_readiness_reference_capture, "20260716"
    )
    token_17 = context_17.run(
        tushare_api.begin_daily_readiness_reference_capture, "20260717"
    )

    context_16.run(tushare_api.get_all_stock_basic)
    context_17.run(tushare_api.get_all_stock_basic)
    context_16.run(tushare_api.get_sw_industry_classification)
    context_17.run(tushare_api.get_sw_industry_classification)

    snapshot_17 = context_17.run(
        tushare_api.end_daily_readiness_reference_capture, token_17
    )
    snapshot_16 = context_16.run(
        tushare_api.end_daily_readiness_reference_capture, token_16
    )

    assert snapshot_16.effective_as_of.isoformat() == "2026-07-16"
    assert snapshot_16.sw_industry_by_ticker == {"000001.SZ": "银行"}
    assert snapshot_17.effective_as_of.isoformat() == "2026-07-17"
    assert snapshot_17.sw_industry_by_ticker == {"000002.SZ": "银行"}
    assert snapshot_16.sw_reference.effective_from.isoformat() == "2026-07-16"
    assert snapshot_17.sw_reference.effective_from.isoformat() == "2026-07-17"
