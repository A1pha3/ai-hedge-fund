"""Characterization tests for src/utils/financial_calcs.py.

CAGR / YTD-annualization / P-E calculations had zero direct test coverage
despite being finance-domain math used by analyst agents. Tests lock down
the A-share YTD-aware calculation contracts.

LineItem objects are simulated with SimpleNamespace (the functions use getattr).
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from src.utils.financial_calcs import (
    annualize_ytd_value,
    calculate_cagr_from_line_items,
    calculate_pe_from_line_items,
)


def _li(report_period: str, **fields: float) -> SimpleNamespace:
    """Build a LineItem-like object with a report_period + arbitrary fields."""
    return SimpleNamespace(report_period=report_period, **fields)


# ---------------------------------------------------------------------------
# annualize_ytd_value
# ---------------------------------------------------------------------------


class TestAnnualizeYtdValue:
    @pytest.mark.parametrize(
        "period,months",
        [("20250331", 3), ("20250630", 6), ("20250930", 9), ("20251231", 12)],
    )
    def test_standard_quarter_ends(self, period: str, months: int) -> None:
        assert annualize_ytd_value(120, period) == pytest.approx(120 * 12 / months)

    def test_q3_nine_months(self) -> None:
        """9-month YTD → annualized = value * 12/9."""
        assert annualize_ytd_value(90, "20250930") == pytest.approx(120.0)

    def test_full_year_unchanged(self) -> None:
        """Q4 (1231) is already annual → no scaling."""
        assert annualize_ytd_value(100, "20251231") == pytest.approx(100.0)

    def test_non_standard_month_inferred(self) -> None:
        """Period '20250115' → month=01 inferred → value * 12/1."""
        assert annualize_ytd_value(10, "20250115") == pytest.approx(120.0)

    def test_empty_period_returns_none(self) -> None:
        assert annualize_ytd_value(100, "") is None

    def test_short_period_returns_none(self) -> None:
        assert annualize_ytd_value(100, "short") is None

    def test_invalid_month_returns_none(self) -> None:
        """Month 13 is invalid → None."""
        assert annualize_ytd_value(100, "20251301") is None


# ---------------------------------------------------------------------------
# calculate_cagr_from_line_items
# ---------------------------------------------------------------------------


class TestCalculateCagr:
    def test_annual_strategy_two_points(self) -> None:
        """100→121 over 1 year → CAGR 21%."""
        items = [_li("20241231", revenue=121), _li("20231231", revenue=100)]
        result = calculate_cagr_from_line_items(items, field="revenue")
        assert result == pytest.approx(0.21, abs=1e-6)

    def test_annual_strategy_multi_year(self) -> None:
        """3 consecutive annual points: 100→121→146.41, n=2 intervals → CAGR ~21%."""
        items = [
            _li("20251231", revenue=146.41),
            _li("20241231", revenue=121),
            _li("20231231", revenue=100),
        ]
        result = calculate_cagr_from_line_items(items, field="revenue")
        assert result == pytest.approx(0.21, abs=0.01)

    def test_same_quarter_yoy_fallback(self) -> None:
        """No annual data → same-quarter YoY (strategy 2)."""
        items = [_li("20250930", revenue=121), _li("20240930", revenue=100)]
        result = calculate_cagr_from_line_items(items, field="revenue")
        assert result == pytest.approx(0.21, abs=1e-6)

    def test_insufficient_items_returns_none(self) -> None:
        assert calculate_cagr_from_line_items([_li("20251231", revenue=100)]) is None

    def test_empty_list_returns_none(self) -> None:
        assert calculate_cagr_from_line_items([]) is None

    def test_zero_or_negative_values_excluded(self) -> None:
        """Zero/negative revenue values are filtered out."""
        items = [_li("20251231", revenue=0), _li("20241231", revenue=100)]
        assert calculate_cagr_from_line_items(items, field="revenue") is None

    def test_years_param_limits_window(self) -> None:
        """years=1 uses only 1-year span even with more data."""
        items = [
            _li("20251231", revenue=121),
            _li("20241231", revenue=110),
            _li("20231231", revenue=100),
        ]
        result = calculate_cagr_from_line_items(items, field="revenue", years=1)
        # years=1 → latest vs 1 year back (110) → (121/110)-1
        assert result == pytest.approx((121 / 110) - 1, abs=1e-6)

    def test_custom_field_net_income(self) -> None:
        items = [_li("20241231", net_income=50), _li("20231231", net_income=40)]
        result = calculate_cagr_from_line_items(items, field="net_income")
        assert result == pytest.approx((50 / 40) - 1, abs=1e-6)


# ---------------------------------------------------------------------------
# calculate_pe_from_line_items
# ---------------------------------------------------------------------------


class TestCalculatePe:
    def test_annual_net_income(self) -> None:
        """market_cap / annual net_income."""
        items = [_li("20241231", net_income=100)]
        assert calculate_pe_from_line_items(1000, items) == pytest.approx(10.0)

    def test_zero_market_cap_returns_none(self) -> None:
        items = [_li("20241231", net_income=100)]
        assert calculate_pe_from_line_items(0, items) is None

    def test_negative_market_cap_returns_none(self) -> None:
        items = [_li("20241231", net_income=100)]
        assert calculate_pe_from_line_items(-100, items) is None

    def test_empty_line_items_returns_none(self) -> None:
        assert calculate_pe_from_line_items(1000, []) is None

    def test_quarterly_annualized_fallback(self) -> None:
        """No annual data → annualize latest quarterly net_income."""
        # Q3 net_income=75 → annualized 75*12/9=100 → PE=1000/100=10
        items = [_li("20250930", net_income=75)]
        assert calculate_pe_from_line_items(1000, items) == pytest.approx(10.0)

    def test_negative_net_income_falls_through(self) -> None:
        """Negative annual net_income → no PE (doesn't backfill older years)."""
        items = [_li("20241231", net_income=-50)]
        result = calculate_pe_from_line_items(1000, items)
        # annual is negative → strategy 2 tries quarterly annualize of -50 → negative → None
        assert result is None
