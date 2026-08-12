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
    # 生产 capture 路径经 _cached_tushare_dataframe_call 读取成员帧 (2026-08-12 修复:
    # 实时失败回退缓存帧) — 缓存入口同样返回 provider 数据, 否则会读真实磁盘缓存.
    monkeypatch.setattr(
        tushare_api,
        "_cached_tushare_dataframe_call",
        lambda _pro, api_name, **_kwargs: (
            provider(_pro, api_name, **_kwargs)
            if api_name in {"index_classify", "index_member"}
            else tushare_api._cached_tushare_dataframe_call(_pro, api_name, **_kwargs)
        ),
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


def test_end_capture_self_completes_missing_observations(monkeypatch) -> None:
    """Regression: a same-day candidate-pool cache hit never calls the reference
    fetchers, so the capture used to end empty and the readiness manifest could
    never publish on repeat --auto runs. ``end_daily_readiness_reference_capture``
    must acquire missing observations itself while the token is active.
    """
    monkeypatch.setattr(tushare_api, "_get_pro", lambda: object())

    def provider(_pro, api_name: str, **_kwargs):
        if api_name == "stock_basic":
            return pd.DataFrame(
                [
                    {"ts_code": "000001.SZ", "name": "平安银行", "list_status": "L"},
                ]
            )
        if api_name == "index_classify":
            return pd.DataFrame([{"index_code": "801780.SI", "industry_name": "银行"}])
        if api_name == "index_member":
            return pd.DataFrame(
                [{"con_code": "000001.SZ", "in_date": "20000101", "out_date": None}]
            )
        raise AssertionError(api_name)

    monkeypatch.setattr(tushare_api, "_call_tushare_dataframe_api", provider)
    # 生产 capture 路径经 _cached_tushare_dataframe_call 读取成员帧 — 让缓存入口
    # 也返回 provider 数据, 否则会回退到真实磁盘缓存 (as-of 语义不同, 断言失真).
    monkeypatch.setattr(
        tushare_api,
        "_cached_tushare_dataframe_call",
        lambda _pro, api_name, **_kwargs: (
            provider(_pro, api_name, **_kwargs)
            if api_name == "index_member"
            else tushare_api._cached_tushare_dataframe_call(_pro, api_name, **_kwargs)
        ),
    )

    token = tushare_api.begin_daily_readiness_reference_capture("20260717")
    # No get_all_stock_basic()/get_sw_industry_classification() calls inside the
    # window (the pool-cache-hit scenario): end must self-complete.
    snapshot = tushare_api.end_daily_readiness_reference_capture(token)

    assert snapshot is not None
    assert snapshot.effective_as_of.isoformat() == "2026-07-17"
    assert snapshot.sw_industry_by_ticker == {"000001.SZ": "银行"}


def test_end_capture_self_completion_stays_fail_closed_without_provider(
    monkeypatch,
) -> None:
    """Self-completion must not manufacture evidence: with no tushare provider
    the observations stay missing and the capture ends with ``None``, exactly
    the pre-fix fail-closed behaviour."""
    monkeypatch.setattr(tushare_api, "_get_pro", lambda: None)

    token = tushare_api.begin_daily_readiness_reference_capture("20260717")
    snapshot = tushare_api.end_daily_readiness_reference_capture(token)

    assert snapshot is None


def test_capture_sw_mapping_survives_industry_member_fetch_failure(
    monkeypatch,
) -> None:
    """Regression: the capture-path SW projection must not silently drop an
    industry whose live ``index_member`` call fails.

    ``_capture_sw_industry_mapping_as_of`` used ``_call_tushare_dataframe_api``
    (uncached) per industry, and on a None result simply ``continue``d — no
    log, no fallback. One transient industry failure therefore produced a
    SW mapping that did not exactly cover the frozen universe, and the strict
    ``FrozenSharedReadinessSource`` check fail-closed the whole --auto
    readiness publication (``shared_source_capture_failed: SW mapping must
    exactly cover frozen universe``; observed 2026-08-11 21:33). The fix must
    read members through ``_cached_tushare_dataframe_call`` so a healthy
    persisted frame (same contract the slow path uses) backfills the industry
    when the live call fails.
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
            return pd.DataFrame(
                [
                    {"index_code": "801010.SI", "industry_name": "农林牧渔"},
                    {"index_code": "801780.SI", "industry_name": "银行"},
                ]
            )
        if api_name == "index_member":
            # 801010.SI 的实时调用失败 (瞬时网络/限速) — 正是 2026-08-11 的故障模式.
            return None
        raise AssertionError(api_name)

    # 健康缓存帧 (走 _cached_tushare_dataframe_call, 与修复后的生产路径一致):
    # as-of 20260716 在期: 农林牧渔 含 000001.SZ; 银行 含 000002.SZ.
    cached_frames = {
        "801010.SI": pd.DataFrame(
            [
                {"index_code": "801010.SI", "con_code": "000001.SZ", "in_date": "20000101", "out_date": None},
            ]
        ),
        "801780.SI": pd.DataFrame(
            [
                {"index_code": "801780.SI", "con_code": "000002.SZ", "in_date": "20000101", "out_date": None},
            ]
        ),
    }

    real_cached_call = tushare_api._cached_tushare_dataframe_call

    def wrapped_cached_call(_pro, api_name: str, **_kwargs):
        if api_name == "index_member":
            index_code = _kwargs.get("index_code")
            if index_code in cached_frames:
                return cached_frames[index_code].copy()
        return real_cached_call(_pro, api_name, **_kwargs)

    monkeypatch.setattr(tushare_api, "_call_tushare_dataframe_api", provider)
    monkeypatch.setattr(tushare_api, "_cached_tushare_dataframe_call", wrapped_cached_call)

    token = tushare_api.begin_daily_readiness_reference_capture("20260716")
    # self-completion at end triggers get_sw_industry_classification → capture path
    snapshot = tushare_api.end_daily_readiness_reference_capture(token)

    assert snapshot is not None
    # 实时失败行业由缓存帧补齐 — 映射完整覆盖两个行业
    assert snapshot.sw_industry_by_ticker == {
        "000001.SZ": "农林牧渔",
        "000002.SZ": "银行",
    }
