from types import SimpleNamespace

import src.agents.charlie_munger as charlie_munger


def test_analyze_moat_strength_scores_excellent_roic_pricing_power_and_low_capital_needs():
    financial_line_items = [
        SimpleNamespace(
            return_on_invested_capital=0.20,
            gross_margin=0.50,
            capital_expenditure=-2.0,
            revenue=100.0,
            research_and_development=10.0,
            goodwill_and_intangible_assets=50.0,
        ),
        SimpleNamespace(
            return_on_invested_capital=0.18,
            gross_margin=0.55,
            capital_expenditure=-3.0,
            revenue=110.0,
            research_and_development=9.0,
            goodwill_and_intangible_assets=45.0,
        ),
        SimpleNamespace(
            return_on_invested_capital=0.16,
            gross_margin=0.60,
            capital_expenditure=-4.0,
            revenue=120.0,
            research_and_development=8.0,
            goodwill_and_intangible_assets=40.0,
        ),
    ]

    result = charlie_munger.analyze_moat_strength(metrics=[SimpleNamespace()], financial_line_items=financial_line_items)

    assert result["score"] == 8.88888888888889
    assert "Excellent ROIC: >15% in 3/3 periods" in result["details"]
    assert "Good pricing power: Average gross margin 55.0%" in result["details"]
    assert "Low capital requirements: Avg capex 2.7% of revenue" in result["details"]
    assert "Invests in R&D, building intellectual property" in result["details"]
    assert "Significant goodwill/intangible assets, suggesting brand value or IP" in result["details"]


def test_analyze_moat_strength_reports_missing_roic_weak_margins_and_high_capital_needs():
    financial_line_items = [
        SimpleNamespace(gross_margin=0.20, capital_expenditure=-20.0, revenue=100.0),
        SimpleNamespace(gross_margin=0.18, capital_expenditure=-18.0, revenue=90.0),
        SimpleNamespace(gross_margin=0.15, capital_expenditure=-15.0, revenue=80.0),
    ]

    result = charlie_munger.analyze_moat_strength(metrics=[SimpleNamespace()], financial_line_items=financial_line_items)

    assert result["score"] == 0
    assert "No ROIC data available" in result["details"]
    assert "Limited pricing power: Low or declining gross margins" in result["details"]
    assert "High capital requirements: Avg capex 19.6% of revenue" in result["details"]


def test_analyze_management_quality_scores_cash_conversion_prudent_debt_and_shareholder_alignment():
    financial_line_items = [
        SimpleNamespace(
            free_cash_flow=120.0,
            net_income=100.0,
            total_debt=25.0,
            shareholders_equity=100.0,
            cash_and_equivalents=15.0,
            revenue=100.0,
            outstanding_shares=90.0,
        ),
        SimpleNamespace(
            free_cash_flow=110.0,
            net_income=100.0,
            total_debt=30.0,
            shareholders_equity=100.0,
            cash_and_equivalents=14.0,
            revenue=100.0,
            outstanding_shares=95.0,
        ),
        SimpleNamespace(
            free_cash_flow=130.0,
            net_income=100.0,
            total_debt=35.0,
            shareholders_equity=100.0,
            cash_and_equivalents=13.0,
            revenue=100.0,
            outstanding_shares=100.0,
        ),
    ]
    insider_trades = [
        SimpleNamespace(transaction_type="buy"),
        SimpleNamespace(transaction_type="purchase"),
        SimpleNamespace(transaction_type="buy"),
    ]

    result = charlie_munger.analyze_management_quality(financial_line_items, insider_trades)

    assert result["score"] == 10
    assert "Excellent cash conversion: FCF/NI ratio of 1.20" in result["details"]
    assert "Conservative debt management: D/E ratio of 0.25" in result["details"]
    assert "Prudent cash management: Cash/Revenue ratio of 0.15" in result["details"]
    assert "Strong insider buying: 3/3 transactions are purchases" in result["details"]
    assert "Shareholder-friendly: Reducing share count over time" in result["details"]
    assert result["insider_buy_ratio"] == 1.0
    assert result["recent_de_ratio"] == 0.25
    assert result["cash_to_revenue"] == 0.15
    assert result["share_count_trend"] == "decreasing"


def test_analyze_management_quality_reports_high_debt_selling_and_dilution():
    financial_line_items = [
        SimpleNamespace(
            free_cash_flow=10.0,
            net_income=20.0,
            total_debt=200.0,
            shareholders_equity=100.0,
            cash_and_equivalents=2.0,
            revenue=100.0,
            outstanding_shares=130.0,
        ),
        SimpleNamespace(
            free_cash_flow=8.0,
            net_income=20.0,
            total_debt=180.0,
            shareholders_equity=100.0,
            cash_and_equivalents=2.0,
            revenue=100.0,
            outstanding_shares=110.0,
        ),
        SimpleNamespace(
            free_cash_flow=6.0,
            net_income=20.0,
            total_debt=160.0,
            shareholders_equity=100.0,
            cash_and_equivalents=2.0,
            revenue=100.0,
            outstanding_shares=100.0,
        ),
    ]
    insider_trades = [SimpleNamespace(transaction_type="sell") for _ in range(6)]

    result = charlie_munger.analyze_management_quality(financial_line_items, insider_trades)

    assert result["score"] == 0
    assert "Poor cash conversion: FCF/NI ratio of only 0.40" in result["details"]
    assert "High debt level: D/E ratio of 2.00" in result["details"]
    assert "Low cash reserves: Cash/Revenue ratio of 0.02" in result["details"]
    assert "Concerning insider selling: 6/6 transactions are sales" in result["details"]
    assert "Concerning dilution: Share count increased significantly" in result["details"]
    assert result["insider_buy_ratio"] == 0.0
    assert result["recent_de_ratio"] == 2.0
    assert result["cash_to_revenue"] == 0.02
    assert result["share_count_trend"] == "increasing"


def test_analyze_predictability_scores_consistent_growth_operations_margins_and_cash(monkeypatch):
    monkeypatch.setattr(charlie_munger, "calculate_cagr_from_line_items", lambda line_items, field: 0.12)

    financial_line_items = [
        SimpleNamespace(revenue=150.0, operating_income=30.0, operating_margin=0.20, free_cash_flow=25.0),
        SimpleNamespace(revenue=130.0, operating_income=26.0, operating_margin=0.19, free_cash_flow=22.0),
        SimpleNamespace(revenue=115.0, operating_income=24.0, operating_margin=0.21, free_cash_flow=20.0),
        SimpleNamespace(revenue=100.0, operating_income=20.0, operating_margin=0.20, free_cash_flow=18.0),
        SimpleNamespace(revenue=90.0, operating_income=18.0, operating_margin=0.19, free_cash_flow=16.0),
    ]

    result = charlie_munger.analyze_predictability(financial_line_items)

    assert result["score"] == 10
    assert "Highly predictable revenue: 12.0% avg growth with low volatility" in result["details"]
    assert "Highly predictable operations: Operating income positive in all periods" in result["details"]
    assert "Highly predictable margins: 19.8% avg with minimal volatility" in result["details"]
    assert "Highly predictable cash generation: Positive FCF in all periods" in result["details"]


def test_analyze_predictability_reports_declining_revenue_volatile_margins_and_weak_cash(monkeypatch):
    monkeypatch.setattr(charlie_munger, "calculate_cagr_from_line_items", lambda line_items, field: -0.10)

    financial_line_items = [
        SimpleNamespace(revenue=80.0, operating_income=10.0, operating_margin=0.30, free_cash_flow=5.0),
        SimpleNamespace(revenue=90.0, operating_income=-5.0, operating_margin=0.10, free_cash_flow=-2.0),
        SimpleNamespace(revenue=100.0, operating_income=8.0, operating_margin=0.25, free_cash_flow=3.0),
        SimpleNamespace(revenue=110.0, operating_income=-4.0, operating_margin=0.08, free_cash_flow=-1.0),
        SimpleNamespace(revenue=120.0, operating_income=-6.0, operating_margin=0.18, free_cash_flow=-3.0),
    ]

    result = charlie_munger.analyze_predictability(financial_line_items)

    assert result["score"] == 0
    assert "Declining or highly unpredictable revenue: -10.0% avg growth" in result["details"]
    assert "Unpredictable operations: Operating income positive in only 2/5 periods" in result["details"]
    assert "Unpredictable margins: 18.2% avg with high volatility (7.4%)" in result["details"]
    assert "Unpredictable cash generation: Positive FCF in only 2/5 periods" in result["details"]


def test_calculate_munger_valuation_scores_strong_yield_margin_of_safety_and_growth():
    financial_line_items = [
        SimpleNamespace(free_cash_flow=100.0),
        SimpleNamespace(free_cash_flow=90.0),
        SimpleNamespace(free_cash_flow=80.0),
        SimpleNamespace(free_cash_flow=70.0),
        SimpleNamespace(free_cash_flow=60.0),
    ]

    result = charlie_munger.calculate_munger_valuation(financial_line_items, market_cap=800.0)

    assert result["score"] == 10
    assert "Excellent value: 10.0% FCF yield" in result["details"]
    assert "Large margin of safety: 50.0% upside to reasonable value" in result["details"]
    assert "Growing FCF trend adds to intrinsic value" in result["details"]
    assert result["intrinsic_value_range"] == {"conservative": 800.0, "reasonable": 1200.0, "optimistic": 1600.0}
    assert result["fcf_yield"] == 0.1
    assert result["normalized_fcf"] == 80.0
    assert result["margin_of_safety_vs_fair_value"] == 0.5


def test_calculate_munger_valuation_reports_expensive_declining_fcf_case():
    financial_line_items = [
        SimpleNamespace(free_cash_flow=10.0),
        SimpleNamespace(free_cash_flow=20.0),
        SimpleNamespace(free_cash_flow=30.0),
    ]

    result = charlie_munger.calculate_munger_valuation(financial_line_items, market_cap=1000.0)

    assert result["score"] == 0
    assert "Expensive: Only 2.0% FCF yield" in result["details"]
    assert "Expensive: 70.0% premium to reasonable value" in result["details"]
    assert "Declining FCF trend is concerning" in result["details"]
    assert result["intrinsic_value_range"] == {"conservative": 200.0, "reasonable": 300.0, "optimistic": 400.0}
    assert result["fcf_yield"] == 0.02
    assert result["normalized_fcf"] == 20.0
    assert result["margin_of_safety_vs_fair_value"] == -0.7
