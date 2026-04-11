from types import SimpleNamespace

from src.agents.rakesh_jhunjhunwala import (
    analyze_balance_sheet,
    analyze_cash_flow,
    analyze_growth,
    analyze_management_actions,
    analyze_profitability,
    assess_quality_metrics,
    calculate_intrinsic_value,
)


def test_analyze_profitability_preserves_high_score_path():
    financial_line_items = [
        SimpleNamespace(net_income=300.0, total_assets=1000.0, total_liabilities=100.0, operating_income=220.0, revenue=900.0, earnings_per_share=9.0),
        SimpleNamespace(earnings_per_share=7.0),
        SimpleNamespace(earnings_per_share=5.0),
    ]

    assert analyze_profitability(financial_line_items) == {
        "score": 8,
        "details": "Excellent ROE: 33.3%; Excellent operating margin: 24.4%; High EPS CAGR: 34.2%",
    }


def test_analyze_profitability_preserves_missing_data_messages():
    financial_line_items = [
        SimpleNamespace(net_income=None, total_assets=None, total_liabilities=None, operating_income=None, revenue=None, earnings_per_share=1.0)
    ]

    assert analyze_profitability(financial_line_items) == {
        "score": 0,
        "details": "Unable to calculate ROE - missing data; Unable to calculate operating margin; Insufficient EPS data for growth analysis",
    }


def test_analyze_growth_preserves_income_cagr_and_inconsistent_revenue_message():
    financial_line_items = [
        SimpleNamespace(revenue=180.0, net_income=72.0),
        SimpleNamespace(revenue=150.0, net_income=54.0),
        SimpleNamespace(revenue=120.0, net_income=36.0),
    ]

    assert analyze_growth(financial_line_items) == {
        "score": 3,
        "details": "Insufficient revenue data for CAGR calculation; Excellent income CAGR: 41.4%; Inconsistent growth pattern (0% of years)",
    }


def test_analyze_growth_preserves_negative_income_cagr_wording():
    financial_line_items = [
        SimpleNamespace(revenue=100.0, net_income=8.0),
        SimpleNamespace(revenue=110.0, net_income=9.0),
        SimpleNamespace(revenue=130.0, net_income=10.0),
    ]

    assert analyze_growth(financial_line_items) == {
        "score": 1,
        "details": "Insufficient revenue data for CAGR calculation; Moderate income CAGR: -10.6%; Consistent growth pattern (100% of years)",
    }


def test_analyze_balance_sheet_preserves_strength_and_missing_messages():
    strong_financials = [
        SimpleNamespace(total_assets=1000.0, total_liabilities=300.0, current_assets=420.0, current_liabilities=180.0)
    ]
    missing_financials = [SimpleNamespace(total_assets=None, total_liabilities=None, current_assets=None, current_liabilities=None)]

    assert analyze_balance_sheet(strong_financials) == {
        "score": 4,
        "details": "Low debt ratio: 0.30; Excellent liquidity with current ratio: 2.33",
    }
    assert analyze_balance_sheet(missing_financials) == {
        "score": 0,
        "details": "Insufficient data to calculate debt ratio; Insufficient data to calculate current ratio",
    }


def test_analyze_cash_flow_preserves_positive_and_missing_dividend_paths():
    shareholder_friendly = [
        SimpleNamespace(free_cash_flow=125.0, dividends_and_other_cash_distributions=-12.0)
    ]
    missing_cash_flow = [SimpleNamespace(free_cash_flow=None, dividends_and_other_cash_distributions=None)]

    assert analyze_cash_flow(shareholder_friendly) == {
        "score": 3,
        "details": "Positive free cash flow: 125.0; Company pays dividends to shareholders",
    }
    assert analyze_cash_flow(missing_cash_flow) == {
        "score": 0,
        "details": "Free cash flow data not available; No dividend payment data available",
    }


def test_analyze_management_actions_preserves_buyback_and_missing_paths():
    assert analyze_management_actions([SimpleNamespace(issuance_or_purchase_of_equity_shares=-25.0)]) == {
        "score": 2,
        "details": "Company buying back shares: 25.0",
    }
    assert analyze_management_actions([SimpleNamespace(issuance_or_purchase_of_equity_shares=None)]) == {
        "score": 0,
        "details": "No data on share issuance or buybacks",
    }


def test_assess_quality_metrics_preserves_weighted_quality_average():
    financial_line_items = [
        SimpleNamespace(net_income=120.0, total_assets=500.0, total_liabilities=120.0),
        SimpleNamespace(net_income=110.0, total_assets=470.0, total_liabilities=120.0),
        SimpleNamespace(net_income=90.0, total_assets=440.0, total_liabilities=130.0),
        SimpleNamespace(net_income=80.0, total_assets=420.0, total_liabilities=140.0),
    ]

    assert assess_quality_metrics(financial_line_items) == 0.6666666666666666


def test_assess_quality_metrics_preserves_neutral_default_for_empty_input():
    assert assess_quality_metrics([]) == 0.5


def test_calculate_intrinsic_value_preserves_growth_projection_path():
    financial_line_items = [
        SimpleNamespace(net_income=120.0, total_assets=500.0, total_liabilities=120.0),
        SimpleNamespace(net_income=100.0, total_assets=470.0, total_liabilities=120.0),
        SimpleNamespace(net_income=80.0, total_assets=440.0, total_liabilities=130.0),
        SimpleNamespace(net_income=70.0, total_assets=420.0, total_liabilities=140.0),
    ]

    assert calculate_intrinsic_value(financial_line_items, 1000.0) == 2470.8611074200207


def test_calculate_intrinsic_value_preserves_fallback_and_negative_earnings_paths():
    assert calculate_intrinsic_value([SimpleNamespace(net_income=50.0)], 1000.0) == 600.0
    assert calculate_intrinsic_value([SimpleNamespace(net_income=-5.0)], 1000.0) is None
