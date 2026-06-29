from types import SimpleNamespace

import src.agents.bill_ackman as bill_ackman
from src.agents.bill_ackman import analyze_financial_discipline
from src.agents.bill_ackman_helpers import _score_ackman_roe


def test_analyze_financial_discipline_scores_reasonable_leverage_dividends_and_buybacks():
    financial_line_items = [
        SimpleNamespace(debt_to_equity=0.8, dividends_and_other_cash_distributions=-3.0, outstanding_shares=90.0),
        SimpleNamespace(debt_to_equity=0.7, dividends_and_other_cash_distributions=-2.0, outstanding_shares=100.0),
        SimpleNamespace(debt_to_equity=1.2, dividends_and_other_cash_distributions=0.0, outstanding_shares=110.0),
    ]

    result = analyze_financial_discipline(metrics=[SimpleNamespace()], financial_line_items=financial_line_items)

    assert result["score"] == 4
    assert "Debt-to-equity < 1.0 for the majority of periods (reasonable leverage)." in result["details"]
    assert "Company has a history of returning capital to shareholders (dividends)." in result["details"]
    assert "Outstanding shares have decreased over time (possible buybacks)." in result["details"]


def test_analyze_financial_discipline_uses_liabilities_fallback_and_reports_missing_capital_returns():
    financial_line_items = [
        SimpleNamespace(total_liabilities=70.0, total_assets=100.0, outstanding_shares=100.0),
        SimpleNamespace(total_liabilities=40.0, total_assets=100.0),
    ]

    result = analyze_financial_discipline(metrics=[SimpleNamespace()], financial_line_items=financial_line_items)

    assert result["score"] == 0
    assert "Liabilities-to-assets >= 50% in many periods." in result["details"]
    assert "No dividend data found across periods." in result["details"]
    assert "No multi-period share count data to assess buybacks." in result["details"]


def test_analyze_business_quality_scores_growth_profitability_cash_flow_and_high_roe(monkeypatch):
    monkeypatch.setattr(bill_ackman, "calculate_cagr_from_line_items", lambda financial_line_items, field: 0.2)
    financial_line_items = [
        SimpleNamespace(revenue=100.0, operating_margin=0.2, free_cash_flow=12.0),
        SimpleNamespace(revenue=90.0, operating_margin=0.18, free_cash_flow=9.0),
        SimpleNamespace(revenue=80.0, operating_margin=0.1, free_cash_flow=-1.0),
    ]
    metrics = [SimpleNamespace(return_on_equity=0.18)]

    result = bill_ackman.analyze_business_quality(metrics=metrics, financial_line_items=financial_line_items)

    assert result["score"] == 7
    assert "Revenue CAGR of 20.0% over the period (strong growth)." in result["details"]
    assert "Operating margins have often exceeded 15% (indicates good profitability)." in result["details"]
    assert "Majority of periods show positive free cash flow." in result["details"]
    assert "High ROE of 18.0%, indicating a competitive advantage." in result["details"]


def test_analyze_business_quality_reports_missing_inputs_without_scoring(monkeypatch):
    monkeypatch.setattr(bill_ackman, "calculate_cagr_from_line_items", lambda financial_line_items, field: None)
    financial_line_items = [
        SimpleNamespace(revenue=100.0, operating_margin=None, free_cash_flow=None),
        SimpleNamespace(revenue=95.0, operating_margin=None, free_cash_flow=None),
    ]
    metrics = [SimpleNamespace(return_on_equity=None)]

    result = bill_ackman.analyze_business_quality(metrics=metrics, financial_line_items=financial_line_items)

    assert result["score"] == 0
    assert "Insufficient revenue data for CAGR calculation." in result["details"]
    assert "No operating margin data across periods." in result["details"]
    assert "No free cash flow data across periods." in result["details"]
    assert "ROE data not available." in result["details"]


def test_analyze_valuation_does_not_crash_on_zero_market_cap():
    """BH-031 (same-class drain): ``analyze_valuation`` guards with
    ``market_cap is None`` (line 239), but ``get_market_cap`` can return ``0.0``
    from the company-facts API path. Zero leaks past ``is None`` and hits
    ``margin_of_safety = (iv - mc) / mc`` → ZeroDivisionError. Must treat zero
    as missing data.
    """
    financial_line_items = [
        SimpleNamespace(
            free_cash_flow=100.0,
            revenue=1000.0,
            operating_margin=0.2,
        )
    ]
    result = bill_ackman.analyze_valuation(financial_line_items, market_cap=0.0)
    assert isinstance(result, dict)
    assert result.get("score") == 0


# ---------------------------------------------------------------------------
# Falsy-zero on ROE (R68/R96 family residue) — sibling of warren_buffett
# ``_score_buffett_fundamental_roe``. The data provider emits ``None`` for a
# *missing* ROE and 0.0 for a *computed* breakeven ROE (net_income == 0).
# Truthiness ``if latest_metrics.return_on_equity:`` collapsed 0.0 into the
# 'ROE data not available.' fallthrough, mislabeling a real breakeven ROE.
# ---------------------------------------------------------------------------


def test_score_ackman_roe_zero_is_moderate_not_missing():
    """ROE == 0.0 (breakeven year) must read 'ROE of 0.0% is moderate.', not 'data not available.'"""
    score, reason = _score_ackman_roe([SimpleNamespace(return_on_equity=0.0)])
    assert score == 0
    assert reason == "ROE of 0.0% is moderate."


def test_score_ackman_roe_none_still_reports_unavailable():
    """Regression guard: None must STILL read 'ROE data not available.'."""
    score, reason = _score_ackman_roe([SimpleNamespace(return_on_equity=None)])
    assert score == 0
    assert reason == "ROE data not available."


def test_analyze_business_quality_reports_breakeven_roe_not_missing(monkeypatch):
    """End-to-end: a breakeven-ROE company must report 'ROE of 0.0% is moderate.',
    not 'ROE data not available.' (the existing None-path test stays green)."""
    monkeypatch.setattr(bill_ackman, "calculate_cagr_from_line_items", lambda financial_line_items, field: None)
    financial_line_items = [
        SimpleNamespace(revenue=100.0, operating_margin=None, free_cash_flow=None),
        SimpleNamespace(revenue=95.0, operating_margin=None, free_cash_flow=None),
    ]
    metrics = [SimpleNamespace(return_on_equity=0.0)]

    result = bill_ackman.analyze_business_quality(metrics=metrics, financial_line_items=financial_line_items)

    assert "ROE of 0.0% is moderate." in result["details"]
    assert "ROE data not available." not in result["details"]
