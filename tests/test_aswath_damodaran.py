from pydantic import BaseModel

from src.agents.aswath_damodaran import (
    analyze_growth_and_reinvestment,
    calculate_intrinsic_value_dcf,
)
from src.data.models import LineItem


class DummyMetric(BaseModel):
    revenue: float | None = None
    return_on_invested_capital: float | None = None
    free_cash_flow_per_share: float | None = None


def test_growth_and_reinvestment_does_not_crash_when_some_line_items_lack_fcf():
    metrics = [
        DummyMetric(revenue=120.0, return_on_invested_capital=0.12),
        DummyMetric(revenue=100.0, return_on_invested_capital=0.11),
        DummyMetric(revenue=80.0, return_on_invested_capital=0.10),
    ]
    line_items = [
        LineItem(ticker="600158", report_period="2024-12-31", period="ttm", currency="CNY", free_cash_flow=70.0),
        LineItem(ticker="600158", report_period="2023-12-31", period="ttm", currency="CNY"),
        LineItem(ticker="600158", report_period="2022-12-31", period="ttm", currency="CNY", free_cash_flow=50.0),
    ]

    result = analyze_growth_and_reinvestment(metrics, line_items)

    assert "score" in result
    assert "details" in result


def test_intrinsic_value_dcf_falls_back_to_latest_available_fcf():
    metrics = [
        DummyMetric(revenue=120.0, return_on_invested_capital=0.12, free_cash_flow_per_share=1.5),
        DummyMetric(revenue=100.0, return_on_invested_capital=0.11, free_cash_flow_per_share=1.2),
    ]
    line_items = [
        LineItem(ticker="600158", report_period="2024-12-31", period="ttm", currency="CNY", outstanding_shares=100.0),
        LineItem(ticker="600158", report_period="2023-12-31", period="ttm", currency="CNY", free_cash_flow=150.0),
    ]

    result = calculate_intrinsic_value_dcf(metrics, line_items, risk_analysis={"cost_of_equity": 0.09})

    assert result["intrinsic_value"] is not None


def test_growth_score_revenue_zero_base_not_dropped_into_inflated_cagr():
    """R135 (R123 deferred falsy-zero residue): ``analyze_growth_and_reinvestment``
    filtered revenue with truthiness ``if hasattr(m, "revenue") and m.revenue``,
    which drops a legitimate ``revenue == 0`` base period (pre-revenue startup or a
    data-glitch zero). Dropping the zero base shrinks ``n_periods`` and makes
    ``revs[0]`` the next period, computing a misleadingly huge CAGR (e.g.
    (200/100)^(1/0.25)-1 = 1500%) and awarding a false +2 high-growth score.
    CAGR from a zero base is mathematically undefined; the sibling DCF path
    (``calculate_intrinsic_value_dcf`` line 357/362) already uses ``is not None``
    correctly — this is a file-internal semantic split (same R123 cathie_wood
    pattern). revenue=0 base must yield "Revenue data incomplete" (cagr None),
    not an inflated CAGR score.
    """
    # Chronological order (latest first): latest=200, mid=100, oldest=0 (base)
    metrics = [
        DummyMetric(revenue=200.0, return_on_invested_capital=0.12),
        DummyMetric(revenue=100.0, return_on_invested_capital=0.11),
        DummyMetric(revenue=0.0, return_on_invested_capital=0.10),
    ]
    line_items = [
        LineItem(ticker="600158", report_period="2024-12-31", period="ttm", currency="CNY", free_cash_flow=70.0),
        LineItem(ticker="600158", report_period="2023-12-31", period="ttm", currency="CNY", free_cash_flow=60.0),
        LineItem(ticker="600158", report_period="2022-12-31", period="ttm", currency="CNY", free_cash_flow=50.0),
    ]

    result = analyze_growth_and_reinvestment(metrics, line_items)

    details_str = result["details"] if isinstance(result["details"], str) else " ".join(result["details"])
    # The zero-revenue base must NOT produce an inflated CAGR score: cagr must be
    # None (undefined from zero base), so no "Revenue CAGR" detail is appended.
    assert "Revenue CAGR" not in details_str
    assert "Revenue data incomplete" in details_str
