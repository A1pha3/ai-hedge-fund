from __future__ import annotations

from contextvars import Context
from datetime import date, datetime as _real_datetime

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


class _FrozenDateTime(_real_datetime):
    """Real datetime subclass with a frozen ``now()``; inherits strptime/etc."""

    _fixed: _real_datetime | None = None

    @classmethod
    def now(cls, tz=None):  # noqa: A003 - mirrors datetime.now signature
        assert cls._fixed is not None, "_fixed must be set before use"
        return cls._fixed


def test_capture_observation_date_binds_to_signal_across_midnight(monkeypatch) -> None:
    """Regression: a capture whose wall-clock rolls past midnight must still
    stamp ``observed_on == signal_date``. Pre-fix, ``_reference_observation_date``
    returned ``datetime.now().date()`` (the next calendar day), so the strict
    v2 evidence capture raised ``ManifestValidationError`` and ``--auto``
    fail-closed into a degraded attempt — leaving ``--daily-action`` with no
    readiness manifest for the signal session.
    """
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
            return pd.DataFrame([{"index_code": "801780.SI", "industry_name": "银行"}])
        if api_name == "index_member":
            return pd.DataFrame(
                [
                    {"con_code": "000001.SZ", "in_date": "20000101", "out_date": None},
                    {"con_code": "000002.SZ", "in_date": "20000101", "out_date": None},
                ]
            )
        raise AssertionError(api_name)

    monkeypatch.setattr(tushare_api, "_call_tushare_dataframe_api", provider)
    # Wall-clock already past midnight: signal is 2026-07-16, "now" is 2026-07-17.
    _FrozenDateTime._fixed = _real_datetime(2026, 7, 17, 0, 30)
    monkeypatch.setattr(tushare_api, "datetime", _FrozenDateTime)

    context = Context()
    token = context.run(tushare_api.begin_daily_readiness_reference_capture, "20260716")
    context.run(tushare_api.get_all_stock_basic)
    context.run(tushare_api.get_sw_industry_classification)
    snapshot = context.run(tushare_api.end_daily_readiness_reference_capture, token)

    # The signal date is 2026-07-16; observed_on must NOT have leaked the
    # 2026-07-17 wall-clock date.
    assert snapshot.security_reference.observed_on == date(2026, 7, 16)
    assert snapshot.sw_reference.observed_on == date(2026, 7, 16)
