"""Unit tests for src/screening/candidate_pool_compute_pipeline_helpers.py

Covers the filter-stage helpers, context initialization, core/preliminary
filters (ST / Beijing exchange / listing-days / suspend / limit-up /
cooldown), liquidity filter wiring, and output building. All collaborators
are injected, so tests use plain stubs.
"""

from __future__ import annotations

import os
from typing import Any

import pandas as pd
import pytest

from src.screening.candidate_pool_compute_pipeline_helpers import (
    CandidatePoolComputationContext,
    CandidatePoolComputeInputs,
    CandidatePoolLiquidityState,
    CandidatePoolPreparedUniverse,
    _apply_candidate_pool_liquidity_filters,
    _apply_core_candidate_filters,
    _apply_optional_ts_code_filter,
    _apply_preliminary_candidate_filters,
    _apply_stock_dataframe_filter,
    _build_candidate_pool_computation_context,
    _build_candidate_pool_outputs,
    _initialize_candidate_pool_context,
    _record_candidate_filter_stage,
    _record_cooldown_filter_stage,
    compute_candidate_pool_candidates,
)
from src.screening.models import CandidateStock


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _stock_df(rows: list[dict] | None = None) -> pd.DataFrame:
    if rows is None:
        rows = [
            {"symbol": "000001", "ts_code": "000001.SZ", "name": "平安银行", "list_date": "19910403"},
            {"symbol": "000002", "ts_code": "000002.SZ", "name": "ST万科", "list_date": "19910129"},
            {"symbol": "000003", "ts_code": "000003.SZ", "name": "C新发", "list_date": "20260601"},
        ]
    return pd.DataFrame(rows)


def _recorder(calls: list) -> Any:
    def _fn(diag, **kwargs):
        calls.append(kwargs.get("stage"))
    return _fn


# ---------------------------------------------------------------------------
# dataclasses
# ---------------------------------------------------------------------------


def test_dataclasses_are_frozen() -> None:
    ctx = CandidatePoolComputationContext(pro="p", stock_df=_stock_df(), focus_filter_diagnostics={})
    universe = CandidatePoolPreparedUniverse(stock_df=_stock_df(), cooldown_review_df=pd.DataFrame())
    state = CandidatePoolLiquidityState(
        stock_df=_stock_df(), cooldown_review_df=pd.DataFrame(), amount_map={}, mv_map={}
    )
    for obj in (ctx, universe, state):
        with pytest.raises((AttributeError, Exception)):
            obj.pro = "x"  # type: ignore[misc]  # frozen dataclass


def test_compute_inputs_holds_all_callables() -> None:
    inputs = CandidatePoolComputeInputs(
        trade_date="20260613",
        cooldown_tickers=None,
        min_listing_days=60,
        min_estimated_amount_1d=1000.0,
        min_avg_amount_20d=5000.0,
        tushare_daily_batch_size=100,
        get_pro_fn=lambda: None,
        get_all_stock_basic_fn=lambda: None,
        resolve_cooldown_shadow_review_tickers_fn=lambda: set(),
        init_focus_filter_diagnostics_fn=lambda *a, **k: {},
        record_focus_filter_stage_fn=lambda *a, **k: None,
        build_beijing_exchange_mask_fn=lambda df: pd.Series([False] * len(df)),
        estimate_trading_days_fn=lambda a, b: 100,
        get_suspend_list_fn=lambda d: None,
        get_limit_list_fn=lambda d: None,
        resolve_cooldown_tickers_fn=lambda **k: set(),
        get_cooled_tickers_fn=lambda d: set(),
        apply_cooldown_filter_fn=lambda **k: (pd.DataFrame(), pd.DataFrame(), 0),
        get_daily_basic_batch_fn=lambda d: None,
        build_daily_basic_maps_fn=lambda **k: ({}, {}),
        estimate_amount_from_daily_basic_fn=lambda **k: 0.0,
        apply_estimated_liquidity_filter_with_logging_fn=lambda **k: (pd.DataFrame(), pd.DataFrame()),
        load_amount_map_and_low_liquidity_codes_fn=lambda **k: ({}, set(), True),
        get_avg_amount_20d_map_fn=lambda **k: {},
        get_avg_amount_20d_fn=lambda **k: 0.0,
        enforce_tushare_daily_rate_limit_fn=lambda: None,
        filter_low_liquidity_candidates_fn=lambda **k: (pd.DataFrame(), pd.DataFrame(), 0),
        normalize_sw_map_fn=lambda x: {},
        get_sw_industry_classification_fn=lambda: {},
        is_disclosure_window_fn=lambda d: False,
        build_candidate_stocks_fn=lambda **k: [],
        finalize_focus_filter_diagnostics_fn=lambda *a, **k: [],
    )
    assert inputs.trade_date == "20260613"
    assert inputs.min_listing_days == 60
    assert callable(inputs.get_pro_fn)


# ---------------------------------------------------------------------------
# _record_candidate_filter_stage / _record_cooldown_filter_stage
# ---------------------------------------------------------------------------


def test_record_candidate_filter_stage_passes_active_symbols() -> None:
    calls: list[dict] = []

    def _rec(diag, **kwargs):
        calls.append(kwargs)

    df = _stock_df()
    _record_candidate_filter_stage(stock_df=df, focus_filter_diagnostics={}, stage="st_filter", record_focus_filter_stage_fn=_rec)
    assert calls[0]["stage"] == "st_filter"
    assert calls[0]["active_symbols"] == {"000001", "000002", "000003"}


def test_record_cooldown_filter_stage_unions_stock_and_review_symbols() -> None:
    calls: list[dict] = []

    def _rec(diag, **kwargs):
        calls.append(kwargs)

    stock_df = _stock_df([{"symbol": "000001", "ts_code": "000001.SZ"}])
    review_df = _stock_df([{"symbol": "000099", "ts_code": "000099.SZ"}])
    _record_cooldown_filter_stage(
        stock_df=stock_df, cooldown_review_df=review_df, focus_filter_diagnostics={}, record_focus_filter_stage_fn=_rec
    )
    assert calls[0]["stage"] == "cooldown_filter"
    assert calls[0]["active_symbols"] == {"000001", "000099"}


# ---------------------------------------------------------------------------
# _apply_stock_dataframe_filter
# ---------------------------------------------------------------------------


def test_apply_stock_dataframe_filter_removes_masked_rows(capfd: pytest.CaptureFixture) -> None:
    df = _stock_df()
    mask = pd.Series([False, True, False])  # remove row 1 (ST万科)
    calls: list = []
    out = _apply_stock_dataframe_filter(
        stock_df=df, mask=mask, label="排除 ST 后", focus_filter_diagnostics={}, stage="st_filter", record_focus_filter_stage_fn=_recorder(calls)
    )
    assert list(out["symbol"]) == ["000001", "000003"]
    assert calls == ["st_filter"]
    assert "排除 ST 后" in capfd.readouterr().out


def test_apply_stock_dataframe_filter_no_removal_records_stage() -> None:
    df = _stock_df()
    mask = pd.Series([False, False, False])
    calls: list = []
    out = _apply_stock_dataframe_filter(
        stock_df=df, mask=mask, label="X", focus_filter_diagnostics={}, stage="s", record_focus_filter_stage_fn=_recorder(calls)
    )
    assert len(out) == 3
    assert calls == ["s"]


# ---------------------------------------------------------------------------
# _apply_optional_ts_code_filter
# ---------------------------------------------------------------------------


def test_apply_optional_ts_code_filter_none_passthrough() -> None:
    df = _stock_df()
    calls: list = []
    out = _apply_optional_ts_code_filter(
        stock_df=df, filter_df=None, code_column="ts_code", label="X", focus_filter_diagnostics={}, stage="s", record_focus_filter_stage_fn=_recorder(calls)
    )
    assert len(out) == 3
    assert calls == ["s"]


def test_apply_optional_ts_code_filter_empty_df_passthrough() -> None:
    df = _stock_df()
    calls: list = []
    out = _apply_optional_ts_code_filter(
        stock_df=df, filter_df=pd.DataFrame(), code_column="ts_code", label="X", focus_filter_diagnostics={}, stage="s", record_focus_filter_stage_fn=_recorder(calls)
    )
    assert len(out) == 3


def test_apply_optional_ts_code_filter_removes_matching() -> None:
    df = _stock_df()
    suspend_df = pd.DataFrame({"ts_code": ["000001.SZ"]})
    out = _apply_optional_ts_code_filter(
        stock_df=df, filter_df=suspend_df, code_column="ts_code", label="排除停牌后", focus_filter_diagnostics={}, stage="suspend", record_focus_filter_stage_fn=_recorder([])
    )
    assert list(out["symbol"]) == ["000002", "000003"]


# ---------------------------------------------------------------------------
# _apply_core_candidate_filters
# ---------------------------------------------------------------------------


def _core_kwargs(df: pd.DataFrame, **overrides: Any) -> dict:
    base: dict[str, Any] = dict(
        trade_date="20260613",
        stock_df=df,
        focus_filter_diagnostics={},
        min_listing_days=60,
        record_focus_filter_stage_fn=_recorder([]),
        build_beijing_exchange_mask_fn=lambda d: d["ts_code"].str.startswith("BJ"),
        estimate_trading_days_fn=lambda listing_date, trade_date: 100 if listing_date and listing_date < "2020" else 5,
    )
    base.update(overrides)
    return base


def test_apply_core_candidate_filters_removes_st_and_new() -> None:
    df = _stock_df()
    out = _apply_core_candidate_filters(**_core_kwargs(df))
    # 000002 (ST万科) removed by ST filter; 000003 (C新发, list_date 2026) removed by listing-days
    assert list(out["symbol"]) == ["000001"]


def test_apply_core_candidate_filters_removes_beijing_exchange() -> None:
    df = _stock_df(
        [
            {"symbol": "000001", "ts_code": "000001.SZ", "name": "X", "list_date": "20100101"},
            {"symbol": "830001", "ts_code": "BJ830001", "name": "Y", "list_date": "20100101"},
        ]
    )
    out = _apply_core_candidate_filters(**_core_kwargs(df))
    assert list(out["symbol"]) == ["000001"]


def test_apply_core_candidate_filters_keeps_all_when_clean() -> None:
    df = _stock_df([{"symbol": "000001", "ts_code": "000001.SZ", "name": "平安银行", "list_date": "20100101"}])
    out = _apply_core_candidate_filters(**_core_kwargs(df))
    assert len(out) == 1


# ---------------------------------------------------------------------------
# _initialize_candidate_pool_context / _build_candidate_pool_computation_context
# ---------------------------------------------------------------------------


def test_initialize_context_pro_none_returns_none_triple(capfd: pytest.CaptureFixture) -> None:
    pro, stock_df, diag = _initialize_candidate_pool_context(
        get_pro_fn=lambda: None,
        get_all_stock_basic_fn=lambda: _stock_df(),
        resolve_cooldown_shadow_review_tickers_fn=lambda: set(),
        init_focus_filter_diagnostics_fn=lambda *a, **k: {},
    )
    assert (pro, stock_df, diag) == (None, None, None)
    assert "Tushare 未初始化" in capfd.readouterr().out


def test_initialize_context_stock_df_none_returns_none_triple(capfd: pytest.CaptureFixture) -> None:
    pro, stock_df, diag = _initialize_candidate_pool_context(
        get_pro_fn=lambda: "pro_obj",
        get_all_stock_basic_fn=lambda: None,
        resolve_cooldown_shadow_review_tickers_fn=lambda: set(),
        init_focus_filter_diagnostics_fn=lambda *a, **k: {},
    )
    assert (pro, stock_df, diag) == (None, None, None)
    assert "无法获取全 A 股基本信息" in capfd.readouterr().out


def test_initialize_context_success_returns_tuple() -> None:
    pro, stock_df, diag = _initialize_candidate_pool_context(
        get_pro_fn=lambda: "pro_obj",
        get_all_stock_basic_fn=lambda: _stock_df(),
        resolve_cooldown_shadow_review_tickers_fn=lambda: {"000001"},
        init_focus_filter_diagnostics_fn=lambda df, focus_tickers: {"focus": focus_tickers},
    )
    assert pro == "pro_obj"
    assert len(stock_df) == 3
    assert diag == {"focus": {"000001"}}


def test_build_computation_context_returns_none_when_pro_none() -> None:
    ctx = _build_candidate_pool_computation_context(
        get_pro_fn=lambda: None,
        get_all_stock_basic_fn=lambda: _stock_df(),
        resolve_cooldown_shadow_review_tickers_fn=lambda: set(),
        init_focus_filter_diagnostics_fn=lambda *a, **k: {},
    )
    assert ctx is None


def test_build_computation_context_returns_dataclass_on_success() -> None:
    ctx = _build_candidate_pool_computation_context(
        get_pro_fn=lambda: "pro",
        get_all_stock_basic_fn=lambda: _stock_df(),
        resolve_cooldown_shadow_review_tickers_fn=lambda: set(),
        init_focus_filter_diagnostics_fn=lambda df, focus_tickers: {"x": 1},
    )
    assert isinstance(ctx, CandidatePoolComputationContext)
    assert ctx.pro == "pro"
    assert ctx.focus_filter_diagnostics == {"x": 1}


# ---------------------------------------------------------------------------
# _apply_preliminary_candidate_filters
# ---------------------------------------------------------------------------


def _prelim_kwargs(df: pd.DataFrame, **overrides: Any) -> dict:
    base: dict[str, Any] = dict(
        trade_date="20260613",
        stock_df=df,
        focus_filter_diagnostics={},
        cooldown_tickers=None,
        min_listing_days=60,
        record_focus_filter_stage_fn=_recorder([]),
        build_beijing_exchange_mask_fn=lambda d: pd.Series([False] * len(d)),
        estimate_trading_days_fn=lambda listing_date, trade_date: 100,
        get_suspend_list_fn=lambda d: None,
        get_limit_list_fn=lambda d: None,
        resolve_cooldown_tickers_fn=lambda **k: set(),
        get_cooled_tickers_fn=lambda d: set(),
        apply_cooldown_filter_fn=lambda **k: (k["stock_df"], k["stock_df"].iloc[0:0].copy(), 0),
        resolve_cooldown_shadow_review_tickers_fn=lambda: set(),
    )
    base.update(overrides)
    return base


def test_apply_preliminary_filters_limit_up_included_by_default() -> None:
    df = _stock_df([{"symbol": "000001", "ts_code": "000001.SZ", "name": "X", "list_date": "20100101"}])
    limit_df = pd.DataFrame({"ts_code": ["000001.SZ"], "limit": ["U"]})
    out, review = _apply_preliminary_candidate_filters(**_prelim_kwargs(df, get_limit_list_fn=lambda d: limit_df))
    assert len(out) == 1  # limit-up NOT excluded by default


def test_apply_preliminary_filters_limit_up_excluded_when_env_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BTST_EXCLUDE_LIMIT_UP", "1")
    df = _stock_df(
        [
            {"symbol": "000001", "ts_code": "000001.SZ", "name": "X", "list_date": "20100101"},
            {"symbol": "000002", "ts_code": "000002.SZ", "name": "Y", "list_date": "20100101"},
        ]
    )
    limit_df = pd.DataFrame({"ts_code": ["000001.SZ"], "limit": ["U"]})
    out, _ = _apply_preliminary_candidate_filters(**_prelim_kwargs(df, get_limit_list_fn=lambda d: limit_df))
    assert list(out["symbol"]) == ["000002"]


def test_apply_preliminary_filters_cooldown_applied() -> None:
    df = _stock_df(
        [
            {"symbol": "000001", "ts_code": "000001.SZ", "name": "X", "list_date": "20100101"},
            {"symbol": "000002", "ts_code": "000002.SZ", "name": "Y", "list_date": "20100101"},
        ]
    )

    def _cooldown_filter(**k):
        stock = k["stock_df"]
        mask = stock["symbol"] == "000001"
        return stock[~mask].copy(), stock.iloc[0:0].copy(), int(mask.sum())

    out, _ = _apply_preliminary_candidate_filters(
        **_prelim_kwargs(df, resolve_cooldown_tickers_fn=lambda **k: {"000001"}, apply_cooldown_filter_fn=_cooldown_filter)
    )
    assert list(out["symbol"]) == ["000002"]


def test_apply_preliminary_filters_suspend_removed() -> None:
    df = _stock_df(
        [
            {"symbol": "000001", "ts_code": "000001.SZ", "name": "X", "list_date": "20100101"},
            {"symbol": "000002", "ts_code": "000002.SZ", "name": "Y", "list_date": "20100101"},
        ]
    )
    suspend_df = pd.DataFrame({"ts_code": ["000001.SZ"]})
    out, _ = _apply_preliminary_candidate_filters(**_prelim_kwargs(df, get_suspend_list_fn=lambda d: suspend_df))
    assert list(out["symbol"]) == ["000002"]


# ---------------------------------------------------------------------------
# _apply_candidate_pool_liquidity_filters
# ---------------------------------------------------------------------------


def test_apply_liquidity_filters_wiring() -> None:
    stock_df = _stock_df([{"symbol": "000001", "ts_code": "000001.SZ", "name": "X", "list_date": "20100101"}])
    review_df = pd.DataFrame({"symbol": ["000099"], "ts_code": ["000099.SZ"]})
    low_codes: set[str] = set()

    def _est_liq_filter(**k):
        return k["stock_df"], k["cooldown_review_df"]

    def _low_liq_filter(**k):
        return k["stock_df"], k["cooldown_review_df"], 0

    out_stock, out_review, amount_map, mv_map = _apply_candidate_pool_liquidity_filters(
        trade_date="20260613",
        pro="pro",
        stock_df=stock_df,
        cooldown_review_df=review_df,
        focus_filter_diagnostics={},
        min_estimated_amount_1d=1000.0,
        min_avg_amount_20d=5000.0,
        tushare_daily_batch_size=100,
        record_focus_filter_stage_fn=_recorder([]),
        get_daily_basic_batch_fn=lambda d: None,
        build_daily_basic_maps_fn=lambda **k: ({"000001.SZ": 5000.0}, {"000001.SZ": 100.0}),
        estimate_amount_from_daily_basic_fn=lambda **k: 0.0,
        apply_estimated_liquidity_filter_with_logging_fn=_est_liq_filter,
        load_amount_map_and_low_liquidity_codes_fn=lambda **k: ({"000001.SZ": 5000.0, "000099.SZ": 100.0}, {"000099.SZ"}, True),
        get_avg_amount_20d_map_fn=lambda **k: {},
        get_avg_amount_20d_fn=lambda **k: 0.0,
        enforce_tushare_daily_rate_limit_fn=lambda: None,
        filter_low_liquidity_candidates_fn=_low_liq_filter,
    )
    assert amount_map == {"000001.SZ": 5000.0, "000099.SZ": 100.0}
    assert mv_map == {"000001.SZ": 100.0}
    assert len(out_stock) == 1


# ---------------------------------------------------------------------------
# _build_candidate_pool_outputs
# ---------------------------------------------------------------------------


def test_build_outputs_constructs_candidates_and_cooldown_review() -> None:
    stock_df = _stock_df(
        [
            {"symbol": "000001", "ts_code": "000001.SZ", "name": "X", "list_date": "20100101"},
            {"symbol": "000002", "ts_code": "000002.SZ", "name": "Y", "list_date": "20100101"},
        ]
    )
    review_df = _stock_df([{"symbol": "000099", "ts_code": "000099.SZ", "name": "R", "list_date": "20100101"}])

    def _build(stock_df, **k):
        return [CandidateStock(ticker=str(row["symbol"]), name=str(row["name"])) for _, row in stock_df.iterrows()]

    candidates, cooldown_review_candidates, diag = _build_candidate_pool_outputs(
        trade_date="20260613",
        stock_df=stock_df,
        cooldown_review_df=review_df,
        focus_filter_diagnostics={},
        amount_map={},
        mv_map={},
        normalize_sw_map_fn=lambda x: {},
        get_sw_industry_classification_fn=lambda: {},
        is_disclosure_window_fn=lambda d: True,
        build_candidate_stocks_fn=_build,
        finalize_focus_filter_diagnostics_fn=lambda diag, **k: [{"finalized": True}],
    )
    assert len(candidates) == 2
    assert len(cooldown_review_candidates) == 1
    assert cooldown_review_candidates[0].ticker == "000099"
    assert diag == [{"finalized": True}]


# ---------------------------------------------------------------------------
# compute_candidate_pool_candidates — end-to-end with stubs
# ---------------------------------------------------------------------------


def test_compute_returns_empty_when_pro_not_initialized(capfd: pytest.CaptureFixture) -> None:
    result = compute_candidate_pool_candidates(
        trade_date="20260613",
        cooldown_tickers=None,
        min_listing_days=60,
        min_estimated_amount_1d=1000.0,
        min_avg_amount_20d=5000.0,
        tushare_daily_batch_size=100,
        get_pro_fn=lambda: None,
        get_all_stock_basic_fn=lambda: _stock_df(),
        resolve_cooldown_shadow_review_tickers_fn=lambda: set(),
        init_focus_filter_diagnostics_fn=lambda *a, **k: {},
        record_focus_filter_stage_fn=lambda *a, **k: None,
        build_beijing_exchange_mask_fn=lambda df: pd.Series([False] * len(df)),
        estimate_trading_days_fn=lambda a, b: 100,
        get_suspend_list_fn=lambda d: None,
        get_limit_list_fn=lambda d: None,
        resolve_cooldown_tickers_fn=lambda **k: set(),
        get_cooled_tickers_fn=lambda d: set(),
        apply_cooldown_filter_fn=lambda **k: (k["stock_df"], pd.DataFrame(), 0),
        get_daily_basic_batch_fn=lambda d: None,
        build_daily_basic_maps_fn=lambda **k: ({}, {}),
        estimate_amount_from_daily_basic_fn=lambda **k: 0.0,
        apply_estimated_liquidity_filter_with_logging_fn=lambda **k: (k["stock_df"], k["cooldown_review_df"]),
        load_amount_map_and_low_liquidity_codes_fn=lambda **k: ({}, set(), True),
        get_avg_amount_20d_map_fn=lambda **k: {},
        get_avg_amount_20d_fn=lambda **k: 0.0,
        enforce_tushare_daily_rate_limit_fn=lambda: None,
        filter_low_liquidity_candidates_fn=lambda **k: (k["stock_df"], k["cooldown_review_df"], 0),
        normalize_sw_map_fn=lambda x: {},
        get_sw_industry_classification_fn=lambda: {},
        is_disclosure_window_fn=lambda d: False,
        build_candidate_stocks_fn=lambda **k: [],
        finalize_focus_filter_diagnostics_fn=lambda *a, **k: [],
    )
    assert result == ([], [], [])
    assert "Tushare 未初始化" in capfd.readouterr().out
