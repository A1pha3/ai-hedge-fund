from types import SimpleNamespace

import pytest

import src.agents.cathie_wood as cathie_wood


def test_analyze_disruptive_potential_scores_accelerating_high_margin_and_high_rnd(monkeypatch):
    def _fake_cagr(financial_line_items, field):
        return {"revenue": 1.2, "operating_expense": 0.1}[field]

    monkeypatch.setattr(cathie_wood, "calculate_cagr_from_line_items", _fake_cagr)
    financial_line_items = [
        SimpleNamespace(
            revenue=300.0,
            report_period="20241231",
            gross_margin=0.60,
            operating_expense=80.0,
            research_and_development=60.0,
        ),
        SimpleNamespace(
            revenue=100.0,
            report_period="20231231",
            gross_margin=0.55,
            operating_expense=75.0,
            research_and_development=20.0,
        ),
        SimpleNamespace(
            revenue=50.0,
            report_period="20221231",
            gross_margin=0.45,
            operating_expense=70.0,
            research_and_development=10.0,
        ),
    ]

    result = cathie_wood.analyze_disruptive_potential(metrics=[SimpleNamespace()], financial_line_items=financial_line_items)

    assert result["score"] == pytest.approx((14 / 12) * 5)
    assert result["raw_score"] == 14
    assert result["max_score"] == 12
    assert "Revenue growth is accelerating: 200.0% vs 100.0%" in result["details"]
    assert "Exceptional revenue CAGR: 120.0%" in result["details"]
    assert "Expanding gross margins: +15.0%" in result["details"]
    assert "High gross margin: 60.0%" in result["details"]
    assert "Positive operating leverage: Revenue growing faster than expenses" in result["details"]
    assert "High R&D investment: 20.0% of revenue" in result["details"]


def test_analyze_disruptive_potential_reports_missing_inputs_without_scoring(monkeypatch):
    monkeypatch.setattr(cathie_wood, "calculate_cagr_from_line_items", lambda financial_line_items, field: None)
    financial_line_items = [
        SimpleNamespace(revenue=100.0, gross_margin=None, operating_expense=None, research_and_development=None),
        SimpleNamespace(revenue=90.0, gross_margin=None, operating_expense=None, research_and_development=None),
    ]

    result = cathie_wood.analyze_disruptive_potential(metrics=[SimpleNamespace()], financial_line_items=financial_line_items)

    assert result["score"] == 0
    assert result["raw_score"] == 0
    assert result["details"] == "Insufficient revenue data for growth analysis; Insufficient gross margin data; Insufficient data for operating leverage analysis; No R&D data available"


def test_analyze_innovation_growth_scores_strong_reinvestment_and_efficiency():
    financial_line_items = [
        SimpleNamespace(
            revenue=100.0,
            research_and_development=45.0,
            free_cash_flow=20.0,
            operating_margin=0.20,
            capital_expenditure=-20.0,
            dividends_and_other_cash_distributions=-1.0,
        ),
        SimpleNamespace(
            revenue=80.0,
            research_and_development=20.0,
            free_cash_flow=10.0,
            operating_margin=0.10,
            capital_expenditure=-10.0,
            dividends_and_other_cash_distributions=-1.0,
        ),
    ]

    result = cathie_wood.analyze_innovation_growth(metrics=[SimpleNamespace()], financial_line_items=financial_line_items)

    assert result["score"] == 5
    assert result["raw_score"] == 15
    assert result["max_score"] == 15
    assert "Strong R&D investment growth: +125.0%" in result["details"]
    assert "Increasing R&D intensity: 45.0% vs 25.0%" in result["details"]
    assert "Strong and consistent FCF growth, excellent innovation funding capacity" in result["details"]
    assert "Strong and improving operating margin: 20.0%" in result["details"]
    assert "Strong investment in growth infrastructure" in result["details"]
    assert "Strong focus on reinvestment over dividends" in result["details"]


def test_analyze_innovation_growth_reports_missing_inputs_without_scoring():
    financial_line_items = [
        SimpleNamespace(
            revenue=100.0,
            research_and_development=None,
            free_cash_flow=None,
            operating_margin=None,
            capital_expenditure=None,
            dividends_and_other_cash_distributions=None,
        ),
        SimpleNamespace(
            revenue=90.0,
            research_and_development=None,
            free_cash_flow=None,
            operating_margin=None,
            capital_expenditure=None,
            dividends_and_other_cash_distributions=None,
        ),
    ]

    result = cathie_wood.analyze_innovation_growth(metrics=[SimpleNamespace()], financial_line_items=financial_line_items)

    assert result["score"] == 0
    assert result["raw_score"] == 0
    assert result["details"] == "Insufficient R&D data for trend analysis; Insufficient FCF data for analysis; Insufficient operating margin data; Insufficient CAPEX data; Insufficient dividend data"
