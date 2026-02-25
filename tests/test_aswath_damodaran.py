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
