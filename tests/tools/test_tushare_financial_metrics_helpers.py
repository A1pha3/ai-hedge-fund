"""C2-BH2: _build_prior_period_keys robustness against malformed end_date.

Tushare ``fina_indicator`` may return a row with a null/missing/short
``end_date`` (observed for newly-listed companies or partial-year restatements).
``_build_prior_period_keys`` previously did ``int(end_date_str[:4])``
unconditionally — a 0-length or non-digit prefix raises ``ValueError``, which
propagates through TTM synthesis and is swallowed by the outer ``except`` in
``get_ashare_financial_metrics_with_tushare``, silently dropping ALL financial
metrics for the ticker. One bad row poisons the whole batch.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.tools.tushare_financial_metrics_helpers import (
    _build_prior_period_keys,
    _extend_ttm_synthesis_dates,
    _should_include_financial_period,
    build_financial_metrics_from_frames,
)


class TestBuildPriorPeriodKeysRobustness:
    def test_valid_quarterly_date(self) -> None:
        assert _build_prior_period_keys("20240331") == ("20231231", "20230331")

    def test_valid_annual_date(self) -> None:
        assert _build_prior_period_keys("20231231") == ("20221231", "20221231")

    @pytest.mark.parametrize(
        "bad",
        ["", "20", "abcd", "2024", None, "2024033"],
    )
    def test_malformed_does_not_raise(self, bad) -> None:
        """A malformed end_date must NOT raise — it returns a sentinel that
        downstream .get() misses, instead of poisoning the whole batch."""
        result = _build_prior_period_keys(bad)
        # Must return a tuple (not raise); sentinel keys that won't match real data
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_extend_synthesis_dates_skips_malformed(self) -> None:
        """A malformed end_date in period_dates must not crash synthesis-date
        extension; it is skipped so valid dates still synthesize."""
        dates = ["20240331", "", "20230630", "abc"]
        # Must not raise
        result = _extend_ttm_synthesis_dates(dates)
        # Valid dates still produce their prior-period keys
        assert "20240331" in result
        assert "20230630" in result


class TestR41AnnDatePointInTimeFilter:
    """R41: fundamental 财报 ann_date point-in-time 过滤.

    ``_should_include_financial_period`` previously filtered only by report
    period type (annual/quarterly) and never checked ``ann_date`` (公告日) ≤
    trade date. In a backtest/replay a 2 月 simulated trade could read a 2023
    annual report that was not *announced* until 4 月, systematically inflating
    fundamental-driven agents (Warren Buffett / Michael Burry / Cathie Wood 等)
    with look-ahead data. R37-R40 hardened macro/prices/calendar; fundamental
    was the remaining sibling. This test class locks the PIT contract: when an
    ``as_of`` trade date is supplied, rows whose ``ann_date`` is strictly after
    that date are excluded; live mode (``as_of=None``) is unchanged.
    """

    def test_live_mode_unchanged_when_as_of_none(self) -> None:
        """as_of=None (live mode) must keep the historical behavior — no PIT
        filtering is applied. This guards against accidentally filtering live
        runs."""
        assert _should_include_financial_period("20231231", "annual", ann_date_str="20240415", as_of_date=None) is True
        assert _should_include_financial_period("20240331", "quarterly", ann_date_str="20240415", as_of_date=None) is True

    def test_announced_on_or_before_trade_date_is_included(self) -> None:
        """A report announced on or before the trade date is point-in-time
        valid and must be included (period type still applies)."""
        # annual report end_date 20231231, announced 20240130, backtest trade 20240201
        assert _should_include_financial_period("20231231", "annual", ann_date_str="20240130", as_of_date="20240201") is True
        # exactly equal (announced == trade date) is allowed
        assert _should_include_financial_period("20231231", "annual", ann_date_str="20240201", as_of_date="20240201") is True

    def test_announced_after_trade_date_is_excluded(self) -> None:
        """A report announced strictly after the trade date is look-ahead data
        and must be excluded, even if its report period (end_date) is old."""
        # 2023 annual report, end_date 20231231, but not announced until 20240415;
        # a 20240201 backtest must NOT see it.
        assert _should_include_financial_period("20231231", "annual", ann_date_str="20240415", as_of_date="20240201") is False
        # quarterly variant
        assert _should_include_financial_period("20231231", "quarterly", ann_date_str="20240415", as_of_date="20240201") is False

    def test_dashed_trade_date_normalized(self) -> None:
        """The trade date may arrive as 'YYYY-MM-DD' (agents/backtest mix
        formats); it must be normalized to compact form before comparison."""
        assert _should_include_financial_period("20231231", "annual", ann_date_str="20240130", as_of_date="2024-02-01") is True
        assert _should_include_financial_period("20231231", "annual", ann_date_str="20240415", as_of_date="2024-02-01") is False

    def test_dashed_ann_date_normalized(self) -> None:
        """ann_date may also arrive dashed; both sides normalize."""
        assert _should_include_financial_period("20231231", "annual", ann_date_str="2024-04-15", as_of_date="20240201") is False
        assert _should_include_financial_period("20231231", "annual", ann_date_str="2024-01-30", as_of_date="20240201") is True

    def test_missing_or_malformed_ann_date_does_not_filter(self) -> None:
        """If ann_date is missing/malformed (newly-listed, partial restatement),
        the filter must NOT raise and must NOT over-filter — fall back to the
        period-type behavior so one bad row cannot silently drop good metrics
        (mirrors the C2-BH2 robustness contract for _build_prior_period_keys)."""
        for bad_ann in ["", None, "20", "abcd"]:
            # period-type verdict still applies; no exception
            assert _should_include_financial_period("20231231", "annual", ann_date_str=bad_ann, as_of_date="20240201") is True
            assert _should_include_financial_period("20240331", "quarterly", ann_date_str=bad_ann, as_of_date="20240201") is True

    def test_missing_or_malformed_as_of_does_not_filter(self) -> None:
        """If as_of is malformed, treat as live (no PIT filtering) rather than
        risking an over-filter that drops legitimate data."""
        assert _should_include_financial_period("20231231", "annual", ann_date_str="20240415", as_of_date="") is True
        assert _should_include_financial_period("20231231", "annual", ann_date_str="20240415", as_of_date="bad") is True

    def test_backtest_excludes_future_announced_report(self) -> None:
        """Integration: build_financial_metrics_from_frames must drop a row
        whose ann_date is after the trade date, while keeping an announced
        row. This is the end-to-end R41 look-ahead elimination."""
        # Two annual rows: one announced before, one after the trade date 20240201.
        df_fin = pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "end_date": "20231231", "ann_date": "20240415", "netprofit_yoy": 20.0},
                {"ts_code": "000001.SZ", "end_date": "20221231", "ann_date": "20230130", "netprofit_yoy": 15.0},
            ]
        )
        metrics = build_financial_metrics_from_frames(
            ticker="000001",
            end_date="20240201",
            limit=10,
            period="annual",
            pro=None,
            ts_code="000001.SZ",
            df_fin=df_fin,
            df_cash=None,
            df_bal=None,
            df_income=None,
            fcf_values=[None, None],
            raw_income_map={},
            ttm_income_map={},
            get_latest_daily_basic=lambda pro, code, anchor: None,
            validate_margin=lambda v: v,
            validate_roe=lambda v: v,
        )
        report_periods = [m.report_period for m in metrics]
        # The 2023 annual report (announced 20240415) is look-ahead for a
        # 20240201 trade and must be gone; the 2022 report stays.
        assert "20231231" not in report_periods
        assert "20221231" in report_periods
