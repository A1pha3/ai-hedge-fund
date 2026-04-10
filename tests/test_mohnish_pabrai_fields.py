from types import SimpleNamespace

import src.agents.mohnish_pabrai as mohnish_pabrai


def test_analyze_downside_protection_scores_net_cash_liquidity_low_leverage_and_stable_fcf(monkeypatch):
    monkeypatch.setattr(mohnish_pabrai, "get_currency_symbol", lambda ticker: "$")
    financial_line_items = [
        SimpleNamespace(
            cash_and_equivalents=120.0,
            total_debt=20.0,
            current_assets=200.0,
            current_liabilities=80.0,
            debt_to_equity=0.2,
            free_cash_flow=15.0,
        ),
        SimpleNamespace(free_cash_flow=14.0),
        SimpleNamespace(free_cash_flow=13.0),
        SimpleNamespace(free_cash_flow=10.0),
    ]

    result = mohnish_pabrai.analyze_downside_protection(financial_line_items, ticker="AAPL")

    assert result["score"] == 9
    assert "Net cash position: $100" in result["details"]
    assert "Strong liquidity (current ratio 2.50)" in result["details"]
    assert "Very low leverage (D/E 0.20)" in result["details"]
    assert "Positive and improving/stable FCF" in result["details"]


def test_analyze_downside_protection_reports_net_debt_weak_liquidity_high_leverage_and_negative_fcf(monkeypatch):
    monkeypatch.setattr(mohnish_pabrai, "get_currency_symbol", lambda ticker: "¥")
    financial_line_items = [
        SimpleNamespace(
            cash_and_equivalents=30.0,
            total_debt=80.0,
            current_assets=90.0,
            current_liabilities=100.0,
            shareholders_equity=50.0,
            free_cash_flow=-5.0,
        ),
        SimpleNamespace(free_cash_flow=-6.0),
        SimpleNamespace(free_cash_flow=-7.0),
    ]

    result = mohnish_pabrai.analyze_downside_protection(financial_line_items, ticker="000001")

    assert result["score"] == 0
    assert "Net debt position: ¥-50" in result["details"]
    assert "Weak liquidity (current ratio 0.90)" in result["details"]
    assert "High leverage (D/E 1.60)" in result["details"]
    assert "Negative FCF" in result["details"]


def test_analyze_pabrai_valuation_scores_exceptional_fcf_yield_and_asset_light_business():
    financial_line_items = [
        SimpleNamespace(free_cash_flow=20.0, capital_expenditure=-2.0, revenue=100.0),
        SimpleNamespace(free_cash_flow=18.0, capital_expenditure=-3.0, revenue=120.0),
        SimpleNamespace(free_cash_flow=16.0, capital_expenditure=-4.0, revenue=140.0),
    ]

    result = mohnish_pabrai.analyze_pabrai_valuation(financial_line_items, market_cap=150.0)

    assert result["score"] == 6
    assert round(result["normalized_fcf"], 1) == 18.0
    assert round(result["fcf_yield"], 2) == 0.12
    assert "Exceptional value: 12.0% FCF yield" in result["details"]
    assert "Asset-light: Avg capex 2.5% of revenue" in result["details"]


def test_analyze_pabrai_valuation_returns_non_positive_normalized_fcf_without_yield():
    financial_line_items = [
        SimpleNamespace(free_cash_flow=-2.0, capital_expenditure=-1.0, revenue=100.0),
        SimpleNamespace(free_cash_flow=-3.0, capital_expenditure=-1.0, revenue=110.0),
        SimpleNamespace(free_cash_flow=-4.0, capital_expenditure=-1.0, revenue=120.0),
    ]

    result = mohnish_pabrai.analyze_pabrai_valuation(financial_line_items, market_cap=150.0)

    assert result["score"] == 0
    assert result["fcf_yield"] is None
    assert result["normalized_fcf"] == -3.0
    assert result["details"] == "Non-positive normalized FCF"


def test_analyze_double_potential_scores_revenue_fcf_growth_and_high_fcf_yield(monkeypatch):
    monkeypatch.setattr(mohnish_pabrai, "calculate_cagr_from_line_items", lambda financial_line_items, field: 0.2)
    monkeypatch.setattr(mohnish_pabrai, "analyze_pabrai_valuation", lambda financial_line_items, market_cap: {"fcf_yield": 0.09})
    financial_line_items = [
        SimpleNamespace(free_cash_flow=20.0, revenue=100.0),
        SimpleNamespace(free_cash_flow=18.0, revenue=90.0),
        SimpleNamespace(free_cash_flow=10.0, revenue=80.0),
    ]

    result = mohnish_pabrai.analyze_double_potential(financial_line_items, market_cap=150.0)

    assert result["score"] == 8
    assert "Strong revenue trajectory (20.0%)" in result["details"]
    assert "Strong FCF growth (60.0%)" in result["details"]
    assert "High FCF yield can drive doubling via retained cash/Buybacks" in result["details"]


def test_analyze_double_potential_only_adds_reasonable_compounding_when_growth_is_muted(monkeypatch):
    monkeypatch.setattr(mohnish_pabrai, "calculate_cagr_from_line_items", lambda financial_line_items, field: None)
    monkeypatch.setattr(mohnish_pabrai, "analyze_pabrai_valuation", lambda financial_line_items, market_cap: {"fcf_yield": 0.06})
    financial_line_items = [
        SimpleNamespace(free_cash_flow=10.0, revenue=100.0),
        SimpleNamespace(free_cash_flow=10.0, revenue=95.0),
        SimpleNamespace(free_cash_flow=10.0, revenue=90.0),
    ]

    result = mohnish_pabrai.analyze_double_potential(financial_line_items, market_cap=150.0)

    assert result["score"] == 1
    assert result["details"] == "Reasonable FCF yield supports moderate compounding"
