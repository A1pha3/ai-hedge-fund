"""Unit tests for src/screening/candidate_pool_compute_helpers.py

These helpers are pure functions using dependency injection, so they can be
exercised directly with synthetic DataFrames and stub callables.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.screening.candidate_pool_compute_helpers import (
    apply_cooldown_filter,
    apply_estimated_liquidity_filter_with_logging,
    build_candidate_stocks,
    build_daily_basic_maps,
    filter_low_estimated_liquidity,
    filter_low_liquidity_candidates,
    load_amount_map_and_low_liquidity_codes,
    normalize_sw_map,
    resolve_cooldown_tickers,
)

# ---------------------------------------------------------------------------
# apply_cooldown_filter
# ---------------------------------------------------------------------------


def _stock_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_apply_cooldown_filter_empty_cooldown_returns_unchanged() -> None:
    df = _stock_df([{"symbol": "000001", "ts_code": "000001.SZ"}])
    out, review, count = apply_cooldown_filter(
        stock_df=df,
        cooldown_tickers=set(),
        cooldown_review_tickers=set(),
    )
    assert len(out) == 1
    assert len(review) == 0
    assert count == 0


def test_apply_cooldown_filter_removes_cooled_tickers() -> None:
    df = _stock_df(
        [
            {"symbol": "000001", "ts_code": "000001.SZ"},
            {"symbol": "000002", "ts_code": "000002.SZ"},
            {"symbol": "000003", "ts_code": "000003.SZ"},
        ]
    )
    out, review, count = apply_cooldown_filter(
        stock_df=df,
        cooldown_tickers={"000001", "000002"},
        cooldown_review_tickers=set(),
    )
    assert list(out["symbol"]) == ["000003"]
    assert len(review) == 0
    assert count == 2


def test_apply_cooldown_filter_separates_review_subset() -> None:
    df = _stock_df(
        [
            {"symbol": "000001", "ts_code": "000001.SZ"},
            {"symbol": "000002", "ts_code": "000002.SZ"},
        ]
    )
    out, review, count = apply_cooldown_filter(
        stock_df=df,
        cooldown_tickers={"000001", "000002"},
        cooldown_review_tickers={"000002"},
    )
    assert list(out["symbol"]) == []
    # Only the review-intersecting ticker lands in review df
    assert list(review["symbol"]) == ["000002"]
    assert count == 2  # count is total cooled in df, not just review


def test_apply_cooldown_filter_review_subset_with_no_overlap() -> None:
    df = _stock_df([{"symbol": "000001", "ts_code": "000001.SZ"}])
    out, review, count = apply_cooldown_filter(
        stock_df=df,
        cooldown_tickers={"000001"},
        cooldown_review_tickers={"999999"},  # not in cooled set
    )
    assert len(out) == 0
    assert len(review) == 0
    assert count == 1


# ---------------------------------------------------------------------------
# resolve_cooldown_tickers
# ---------------------------------------------------------------------------


def test_resolve_cooldown_tickers_explicit_set_wins() -> None:
    calls: list[str] = []

    def _get(date: str) -> set[str]:
        calls.append(date)
        return {"SHOULD_NOT_BE_USED"}

    result = resolve_cooldown_tickers(
        cooldown_tickers={"000001"},
        trade_date="20260613",
        get_cooled_tickers_fn=_get,
    )
    assert result == {"000001"}
    assert calls == []  # fn not invoked when explicit set provided


def test_resolve_cooldown_tickers_none_uses_fn() -> None:
    def _get(date: str) -> set[str]:
        assert date == "20260613"
        return {"000001", "000002"}

    result = resolve_cooldown_tickers(
        cooldown_tickers=None,
        trade_date="20260613",
        get_cooled_tickers_fn=_get,
    )
    assert result == {"000001", "000002"}


def test_resolve_cooldown_tickers_explicit_empty_set_wins() -> None:
    """An explicit empty set (not None) means 'no cooldown' — fn not called."""
    calls: list[str] = []

    def _get(date: str) -> set[str]:
        calls.append(date)
        return {"X"}

    result = resolve_cooldown_tickers(
        cooldown_tickers=set(),
        trade_date="20260613",
        get_cooled_tickers_fn=_get,
    )
    assert result == set()
    assert calls == []


# ---------------------------------------------------------------------------
# build_daily_basic_maps
# ---------------------------------------------------------------------------


def _estimate(row: pd.Series) -> float:
    return float(row.get("amount", 0.0)) * 1.5


def test_build_daily_basic_maps_none_df_returns_empty() -> None:
    amount_map, mv_map = build_daily_basic_maps(None, _estimate)
    assert amount_map == {}
    assert mv_map == {}


def test_build_daily_basic_maps_empty_df_returns_empty() -> None:
    amount_map, mv_map = build_daily_basic_maps(pd.DataFrame(), _estimate)
    assert amount_map == {}
    assert mv_map == {}


def test_build_daily_basic_maps_populates_both_maps() -> None:
    df = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "total_mv": 10000.0, "amount": 100.0},
            {"ts_code": "000002.SZ", "total_mv": 20000.0, "amount": 200.0},
        ]
    )
    amount_map, mv_map = build_daily_basic_maps(df, _estimate)
    assert amount_map == {"000001.SZ": 150.0, "000002.SZ": 300.0}
    assert mv_map == {"000001.SZ": 10000.0, "000002.SZ": 20000.0}


def test_build_daily_basic_maps_missing_total_mv_skipped_in_mv_map() -> None:
    """Rows without total_mv still contribute to amount_map but not mv_map."""
    df = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "total_mv": 10000.0, "amount": 100.0},
            {"ts_code": "000002.SZ", "total_mv": None, "amount": 200.0},
        ]
    )
    amount_map, mv_map = build_daily_basic_maps(df, _estimate)
    assert amount_map == {"000001.SZ": 150.0, "000002.SZ": 300.0}
    assert mv_map == {"000001.SZ": 10000.0}  # 000002 excluded (NaN)


# ---------------------------------------------------------------------------
# filter_low_estimated_liquidity
# ---------------------------------------------------------------------------


def test_filter_low_estimated_liquidity_no_low_codes_passthrough() -> None:
    df = _stock_df([{"ts_code": "000001.SZ"}, {"ts_code": "000002.SZ"}])
    review = _stock_df([{"ts_code": "000001.SZ"}])
    out, out_review, count = filter_low_estimated_liquidity(
        stock_df=df,
        cooldown_review_df=review,
        estimated_amount_map={"000001.SZ": 500.0, "000002.SZ": 800.0},
        min_estimated_amount_1d=300.0,
    )
    assert len(out) == 2
    assert len(out_review) == 1
    assert count == 0


def test_filter_low_estimated_liquidity_filters_below_min() -> None:
    df = _stock_df([{"ts_code": "000001.SZ"}, {"ts_code": "000002.SZ"}, {"ts_code": "000003.SZ"}])
    # review contains one low-liquidity ticker (000001) and one healthy one (000002)
    review = _stock_df([{"ts_code": "000001.SZ"}, {"ts_code": "000002.SZ"}])
    out, out_review, count = filter_low_estimated_liquidity(
        stock_df=df,
        cooldown_review_df=review,
        estimated_amount_map={"000001.SZ": 100.0, "000002.SZ": 800.0, "000003.SZ": 50.0},
        min_estimated_amount_1d=300.0,
    )
    assert list(out["ts_code"]) == ["000002.SZ"]  # 000001 + 000003 removed
    assert list(out_review["ts_code"]) == ["000002.SZ"]  # 000001 removed, 000002 kept
    assert count == 2


def test_filter_low_estimated_liquidity_zero_amount_kept() -> None:
    """Zero/negative amounts are NOT treated as low liquidity (only 0 < x < min)."""
    df = _stock_df([{"ts_code": "000001.SZ"}, {"ts_code": "000002.SZ"}])
    out, _, count = filter_low_estimated_liquidity(
        stock_df=df,
        cooldown_review_df=pd.DataFrame(),
        estimated_amount_map={"000001.SZ": 0.0, "000002.SZ": 0.0},
        min_estimated_amount_1d=300.0,
    )
    assert len(out) == 2
    assert count == 0


def test_filter_low_estimated_liquidity_missing_in_map_defaults_zero_kept() -> None:
    df = _stock_df([{"ts_code": "000001.SZ"}])
    out, _, count = filter_low_estimated_liquidity(
        stock_df=df,
        cooldown_review_df=pd.DataFrame(),
        estimated_amount_map={},
        min_estimated_amount_1d=300.0,
    )
    assert len(out) == 1
    assert count == 0


def test_filter_low_estimated_liquidity_empty_review_df_stays_empty() -> None:
    df = _stock_df([{"ts_code": "000001.SZ"}, {"ts_code": "000002.SZ"}])
    out, out_review, _ = filter_low_estimated_liquidity(
        stock_df=df,
        cooldown_review_df=pd.DataFrame(),
        estimated_amount_map={"000001.SZ": 100.0},
        min_estimated_amount_1d=300.0,
    )
    assert list(out["ts_code"]) == ["000002.SZ"]
    assert len(out_review) == 0


# ---------------------------------------------------------------------------
# apply_estimated_liquidity_filter_with_logging
# ---------------------------------------------------------------------------


def test_apply_estimated_liquidity_filter_empty_map_passthrough() -> None:
    df = _stock_df([{"ts_code": "000001.SZ"}])
    out, out_review = apply_estimated_liquidity_filter_with_logging(
        stock_df=df,
        cooldown_review_df=pd.DataFrame(),
        estimated_amount_map={},
        min_estimated_amount_1d=300.0,
    )
    assert len(out) == 1
    assert len(out_review) == 0


def test_apply_estimated_liquidity_filter_with_map_filters(capfd: pytest.CaptureFixture) -> None:
    df = _stock_df([{"ts_code": "000001.SZ"}, {"ts_code": "000002.SZ"}])
    out, _ = apply_estimated_liquidity_filter_with_logging(
        stock_df=df,
        cooldown_review_df=pd.DataFrame(),
        estimated_amount_map={"000001.SZ": 100.0, "000002.SZ": 800.0},
        min_estimated_amount_1d=300.0,
    )
    assert list(out["ts_code"]) == ["000002.SZ"]
    captured = capfd.readouterr()
    assert "排除低当日估算流动性" in captured.out


# ---------------------------------------------------------------------------
# load_amount_map_and_low_liquidity_codes
# ---------------------------------------------------------------------------


def test_load_amount_map_batch_hit_returns_true() -> None:
    """When the batch fn returns a populated map, short-circuit (True)."""
    def _batch_map(pro, codes, date):
        return {"000001.SZ": 500.0, "000002.SZ": 50.0}

    def _single(pro, code, date):
        raise AssertionError("should not fall back to single when batch populated")

    def _rate_limit(**kwargs):
        return 0.0

    amount_map, low_codes, used_batch = load_amount_map_and_low_liquidity_codes(
        pro=object(),
        remaining_codes=["000001.SZ", "000002.SZ"],
        trade_date="20260613",
        min_avg_amount_20d=200.0,
        batch_size=100,
        get_avg_amount_map_fn=_batch_map,
        get_avg_amount_fn=_single,
        enforce_rate_limit_fn=_rate_limit,
    )
    assert used_batch is True
    assert amount_map == {"000001.SZ": 500.0, "000002.SZ": 50.0}
    assert low_codes == {"000002.SZ"}


def test_load_amount_map_fallback_per_ticker_returns_false() -> None:
    """When batch fn returns empty map, fall back to per-ticker (False)."""
    def _batch_map(pro, codes, date):
        return {}

    single_calls: list[str] = []

    def _single(pro, code, date):
        single_calls.append(code)
        return 600.0 if code == "000001.SZ" else 10.0

    def _rate_limit(**kwargs):
        return 0.0

    amount_map, low_codes, used_batch = load_amount_map_and_low_liquidity_codes(
        pro=object(),
        remaining_codes=["000001.SZ", "000002.SZ"],
        trade_date="20260613",
        min_avg_amount_20d=200.0,
        batch_size=100,
        get_avg_amount_map_fn=_batch_map,
        get_avg_amount_fn=_single,
        enforce_rate_limit_fn=_rate_limit,
    )
    assert used_batch is False
    assert amount_map == {"000001.SZ": 600.0, "000002.SZ": 10.0}
    assert low_codes == {"000002.SZ"}
    assert single_calls == ["000001.SZ", "000002.SZ"]


def test_load_amount_map_fallback_batches_with_rate_limit() -> None:
    """Batched fallback invokes rate-limit per batch with has_more_batches flag."""
    rate_calls: list[bool] = []

    def _batch_map(pro, codes, date):
        return {}

    def _single(pro, code, date):
        return 500.0

    def _rate_limit(**kwargs):
        rate_calls.append(kwargs.get("has_more_batches"))
        return 0.0

    load_amount_map_and_low_liquidity_codes(
        pro=object(),
        remaining_codes=["A", "B", "C", "D"],
        trade_date="20260613",
        min_avg_amount_20d=1000.0,
        batch_size=2,
        get_avg_amount_map_fn=_batch_map,
        get_avg_amount_fn=_single,
        enforce_rate_limit_fn=_rate_limit,
    )
    assert rate_calls == [True, False]


def test_load_amount_map_empty_codes_returns_empty_false() -> None:
    amount_map, low_codes, used_batch = load_amount_map_and_low_liquidity_codes(
        pro=object(),
        remaining_codes=[],
        trade_date="20260613",
        min_avg_amount_20d=200.0,
        batch_size=10,
        get_avg_amount_map_fn=lambda *a: {},
        get_avg_amount_fn=lambda *a: 0.0,
        enforce_rate_limit_fn=lambda **k: 0.0,
    )
    assert amount_map == {}
    assert low_codes == set()
    assert used_batch is False


# ---------------------------------------------------------------------------
# filter_low_liquidity_candidates
# ---------------------------------------------------------------------------


def test_filter_low_liquidity_candidates_filters_both_dfs() -> None:
    df = _stock_df([{"ts_code": "000001.SZ"}, {"ts_code": "000002.SZ"}])
    review = _stock_df([{"ts_code": "000001.SZ"}])
    out, out_review, count = filter_low_liquidity_candidates(
        stock_df=df,
        cooldown_review_df=review,
        low_liq_codes={"000001.SZ"},
    )
    assert list(out["ts_code"]) == ["000002.SZ"]
    assert len(out_review) == 0
    assert count == 1


def test_filter_low_liquidity_candidates_empty_codes_passthrough() -> None:
    df = _stock_df([{"ts_code": "000001.SZ"}])
    out, out_review, count = filter_low_liquidity_candidates(
        stock_df=df,
        cooldown_review_df=pd.DataFrame(),
        low_liq_codes=set(),
    )
    assert len(out) == 1
    assert len(out_review) == 0
    assert count == 0


# ---------------------------------------------------------------------------
# build_candidate_stocks
# ---------------------------------------------------------------------------


def _stock_rows() -> list[dict]:
    return [
        {"symbol": "000001", "ts_code": "000001.SZ", "name": "平安银行", "industry": "银行", "list_date": "19910403"},
        {"symbol": "000002", "ts_code": "000002.SZ", "name": "万科A", "industry": "地产", "list_date": "19910129"},
    ]


def test_build_candidate_stocks_basic() -> None:
    df = pd.DataFrame(_stock_rows())
    candidates = build_candidate_stocks(
        stock_df=df,
        sw_map={"000001.SZ": "银行"},
        mv_map={"000001.SZ": 50000.0, "000002.SZ": 30000.0},
        amount_map={"000001.SZ": 800.0, "000002.SZ": 600.0},
        is_disclosure=True,
    )
    assert len(candidates) == 2
    c0 = candidates[0]
    assert c0.ticker == "000001"
    assert c0.name == "平安银行"
    assert c0.industry_sw == "银行"  # from sw_map
    assert c0.market_cap == 5.0  # 50000 / 10000
    assert c0.avg_volume_20d == 800.0
    assert c0.disclosure_risk is True


def test_build_candidate_stocks_missing_maps_default_to_zero() -> None:
    df = pd.DataFrame(_stock_rows())
    candidates = build_candidate_stocks(
        stock_df=df,
        sw_map={},
        mv_map={},
        amount_map={},
        is_disclosure=False,
    )
    c0 = candidates[0]
    assert c0.market_cap == 0.0
    assert c0.avg_volume_20d == 0.0
    assert c0.industry_sw == "银行"  # falls back to df industry column
    assert c0.disclosure_risk is False


def test_build_candidate_stocks_missing_list_date_empty_string() -> None:
    df = pd.DataFrame([{"symbol": "000001", "ts_code": "000001.SZ", "name": "X", "industry": "Y", "list_date": None}])
    candidates = build_candidate_stocks(
        stock_df=df,
        sw_map={},
        mv_map={},
        amount_map={},
        is_disclosure=False,
    )
    assert candidates[0].listing_date == ""


def test_build_candidate_stocks_cooldown_review_lane() -> None:
    df = pd.DataFrame(_stock_rows())
    candidates = build_candidate_stocks(
        stock_df=df,
        sw_map={},
        mv_map={},
        amount_map={},
        is_disclosure=False,
        cooldown_review=True,
    )
    for c in candidates:
        assert c.candidate_pool_lane == "cooldown_review"
        assert c.candidate_pool_shadow_reason == "cooldown_review_shadow"


# ---------------------------------------------------------------------------
# normalize_sw_map
# ---------------------------------------------------------------------------


def test_normalize_sw_map_none_returns_empty() -> None:
    assert normalize_sw_map(None) == {}


def test_normalize_sw_map_populated_passthrough() -> None:
    sw = {"000001.SZ": "银行"}
    assert normalize_sw_map(sw) == sw


def test_normalize_sw_map_empty_dict_passthrough() -> None:
    assert normalize_sw_map({}) == {}
