"""R74 (R41/BH-035 lookahead family): point-in-time ``ann_date`` filtering for
the ``line_items`` fetch path (balancesheet / cashflow / income / fina_indicator).

R41 hardened the ``fina_indicator`` *metrics* path (``get_ashare_financial_metrics``)
via ``_should_include_financial_period(ann_date_str, as_of_date)`` so a backtest
on a simulated trade date does not read a report *announced* after that date.
The sibling ``line_items`` path (``get_ashare_line_items_with_tushare`` →
``build_line_items_from_frames`` → ``should_include_period``) used by the
fundamental agents (Warren Buffett / Charlie Munger / Bill Ackman / Michael
Burry / Mohnish Pabrai / Aswath Damodaran / Ben Graham / Cathie Wood …) only
filtered by report-period ``end_date`` (annual/quarterly), **not** by
``ann_date``. Backtest agent-mode calls ``search_line_items(end_date=<simulated
trade date>)`` which forwarded ``end_date`` but the fetcher ignored it for
filtering — a 2 月 backtest could read a 2023 annual report not announced
until 4 月, inflating fundamental-agent backtest results.

These guards mirror the R41 contract: when ``ann_date`` and ``as_of`` are both
present and well-formed, a report announced strictly after ``as_of`` is excluded;
missing/malformed values fall back to the historical (live-mode) behaviour.
"""

from __future__ import annotations

import pandas as pd

from src.tools.tushare_line_items_helpers import (
    build_line_items_from_frames,
    should_include_period,
)


def _make_fin_frame(rows: list[dict]) -> pd.DataFrame:
    """Minimal fina_indicator-style frame with end_date + ann_date columns."""
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Unit: should_include_period gains ann_date / as_of PIT filtering
# ---------------------------------------------------------------------------


class TestShouldIncludePeriodPIT:
    def test_live_mode_unchanged_without_as_of(self) -> None:
        """No as_of → no PIT filtering; behaves as before (live mode)."""
        assert should_include_period("20231231", "annual") is True
        assert should_include_period("20230930", "quarterly") is True

    def test_excludes_report_announced_after_as_of(self) -> None:
        """R74: a 2023 annual report announced 2024-04-30 must NOT be visible
        to a backtest whose simulated trade date is 2024-02-15."""
        result = should_include_period(
            "20231231",
            "annual",
            ann_date_str="20240430",
            as_of_date="20240215",
        )
        assert result is False, "look-ahead report (announced after as_of) must be excluded"

    def test_includes_report_announced_before_as_of(self) -> None:
        """A report announced 2024-01-15 IS visible to a 2024-02-15 backtest."""
        result = should_include_period(
            "20231231",
            "annual",
            ann_date_str="20240115",
            as_of_date="20240215",
        )
        assert result is True

    def test_malformed_ann_date_falls_back_to_live(self) -> None:
        """Malformed ann_date (non-digit / wrong length) → no PIT filter
        (C2-BH2 robustness: never over-filter on bad data)."""
        result = should_include_period(
            "20231231",
            "annual",
            ann_date_str="not-a-date",
            as_of_date="20240215",
        )
        assert result is True

    def test_missing_ann_date_falls_back_to_live(self) -> None:
        """Missing ann_date (None) → no PIT filter (live mode)."""
        result = should_include_period(
            "20231231",
            "annual",
            ann_date_str=None,
            as_of_date="20240215",
        )
        assert result is True

    def test_dashed_dates_normalized(self) -> None:
        """Dashed ISO dates (2024-04-30) normalized same as compact (20240430)."""
        result = should_include_period(
            "20231231",
            "annual",
            ann_date_str="2024-04-30",
            as_of_date="2024-02-15",
        )
        assert result is False


# ---------------------------------------------------------------------------
# Unit: build_line_items_from_frames applies PIT filter end-to-end
# ---------------------------------------------------------------------------


class TestBuildLineItemsFromFramesPIT:
    def _frames_with_ann_date(self) -> pd.DataFrame:
        """Two annual reports: 2022 (announced 2023-04, visible) and 2023
        (announced 2024-04, look-ahead for a 2024-02 backtest)."""
        return pd.DataFrame(
            [
                {"end_date": "20231231", "ann_date": "20240430", "roe": 18.0},
                {"end_date": "20221231", "ann_date": "20230430", "roe": 16.0},
            ]
        )

    def test_lookahead_report_excluded_when_as_of_supplied(self) -> None:
        """R74: a 2024-02 backtest must NOT see the 2023 annual report
        announced 2024-04-30."""
        df_fin = self._frames_with_ann_date()
        results = build_line_items_from_frames(
            ticker="000001",
            line_items=["roe"],
            period="annual",
            limit=10,
            df_fin=df_fin,
            df_bal=None,
            df_cash=None,
            df_income=None,
            as_of_date="20240215",
        )
        report_periods = [r.report_period for r in results]
        assert "20231231" not in report_periods, "look-ahead annual report must be excluded"
        assert "20221231" in report_periods, "already-announced report must remain"

    def test_live_mode_keeps_all_reports_without_as_of(self) -> None:
        """Live mode (no as_of) keeps both reports — no regression."""
        df_fin = self._frames_with_ann_date()
        results = build_line_items_from_frames(
            ticker="000001",
            line_items=["roe"],
            period="annual",
            limit=10,
            df_fin=df_fin,
            df_bal=None,
            df_cash=None,
            df_income=None,
        )
        report_periods = [r.report_period for r in results]
        assert "20231231" in report_periods
        assert "20221231" in report_periods

    def test_missing_ann_date_column_falls_back_to_live(self) -> None:
        """If the frame lacks ann_date entirely (older Tushare schema), no PIT
        filter is applied — robustness contract, never over-filter."""
        df_fin = pd.DataFrame(
            [
                {"end_date": "20231231", "roe": 18.0},
                {"end_date": "20221231", "roe": 16.0},
            ]
        )
        results = build_line_items_from_frames(
            ticker="000001",
            line_items=["roe"],
            period="annual",
            limit=10,
            df_fin=df_fin,
            df_bal=None,
            df_cash=None,
            df_income=None,
            as_of_date="20240215",
        )
        report_periods = [r.report_period for r in results]
        # Both remain because ann_date is unavailable → live fallback
        assert "20231231" in report_periods
        assert "20221231" in report_periods
