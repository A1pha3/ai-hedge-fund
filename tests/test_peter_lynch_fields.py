from types import SimpleNamespace

import src.agents.peter_lynch as peter_lynch


def test_analyze_lynch_fundamentals_scores_low_debt_strong_margin_and_positive_fcf():
    financial_line_items = [
        SimpleNamespace(debt_to_equity=0.4, operating_margin=0.25, free_cash_flow=120.0),
        SimpleNamespace(debt_to_equity=0.5, operating_margin=0.2, free_cash_flow=100.0),
    ]

    result = peter_lynch.analyze_lynch_fundamentals(financial_line_items)

    assert result["score"] == 10
    assert "Low debt-to-equity: 0.40" in result["details"]
    assert "Strong operating margin: 25.0%" in result["details"]
    assert "Positive free cash flow: 120" in result["details"]


def test_analyze_lynch_fundamentals_uses_debt_fallback_and_reports_missing_margin_and_fcf():
    financial_line_items = [
        SimpleNamespace(total_debt=120.0, shareholders_equity=100.0, operating_margin=None, free_cash_flow=None),
        SimpleNamespace(total_debt=110.0, shareholders_equity=90.0),
    ]

    result = peter_lynch.analyze_lynch_fundamentals(financial_line_items)

    assert result["score"] == 0
    assert "High debt-to-equity: 1.20" in result["details"]
    assert "No operating margin data available." in result["details"]
    assert "No free cash flow data available." in result["details"]


def test_analyze_lynch_valuation_scores_low_pe_and_low_peg(monkeypatch):
    monkeypatch.setattr(peter_lynch, "calculate_pe_from_line_items", lambda market_cap, financial_line_items: 12.0)
    monkeypatch.setattr(peter_lynch, "calculate_cagr_from_line_items", lambda financial_line_items, field: 0.2)
    financial_line_items = [SimpleNamespace(net_income=100.0, earnings_per_share=2.0)]

    result = peter_lynch.analyze_lynch_valuation(financial_line_items, market_cap=1000.0)

    assert result["score"] == 10
    assert "Estimated P/E: 12.00" in result["details"]
    assert "Annualized EPS growth rate: 20.0%" in result["details"]
    assert "PEG ratio: 0.60" in result["details"]


def test_analyze_lynch_valuation_reports_missing_pe_and_growth_inputs(monkeypatch):
    monkeypatch.setattr(peter_lynch, "calculate_pe_from_line_items", lambda market_cap, financial_line_items: None)
    monkeypatch.setattr(peter_lynch, "calculate_cagr_from_line_items", lambda financial_line_items, field: None)
    financial_line_items = [SimpleNamespace(net_income=None, earnings_per_share=None)]

    result = peter_lynch.analyze_lynch_valuation(financial_line_items, market_cap=1000.0)

    assert result["score"] == 0
    assert result["details"] == "No positive net income => can't compute approximate P/E; Insufficient EPS data to compute growth rate"
