from types import SimpleNamespace

from src.agents.warren_buffett import analyze_book_value_growth, calculate_intrinsic_value


def test_calculate_intrinsic_value_handles_missing_outstanding_shares_field():
    financial_line_items = [
        SimpleNamespace(net_income=100.0, depreciation_and_amortization=20.0, capital_expenditure=-10.0, revenue=500.0),
        SimpleNamespace(net_income=90.0, depreciation_and_amortization=18.0, capital_expenditure=-9.0, revenue=450.0, outstanding_shares=10.0),
        SimpleNamespace(net_income=80.0, depreciation_and_amortization=16.0, capital_expenditure=-8.0, revenue=400.0),
    ]

    result = calculate_intrinsic_value(financial_line_items, currency_symbol="$")

    assert result["intrinsic_value"] is not None
    assert result["intrinsic_value"] > 0


def test_analyze_book_value_growth_skips_items_without_share_count():
    financial_line_items = [
        SimpleNamespace(shareholders_equity=300.0),
        SimpleNamespace(shareholders_equity=240.0, outstanding_shares=10.0),
        SimpleNamespace(shareholders_equity=200.0, outstanding_shares=10.0),
        SimpleNamespace(shareholders_equity=150.0, outstanding_shares=10.0),
    ]

    result = analyze_book_value_growth(financial_line_items)

    assert result["score"] >= 0
    assert "Insufficient" not in result["details"]
