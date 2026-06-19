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


def test_analyze_cathie_wood_valuation_does_not_crash_on_zero_market_cap():
    """BH-031: ``analyze_cathie_wood_valuation`` guards with ``market_cap is
    None`` (line 253), but ``get_market_cap`` can return ``0.0`` from the US
    company-facts API path (``api.py:458`` has no ``if not market_cap`` guard,
    unlike the fallback path at ``api.py:466``). A zero market_cap leaks past
    the ``is None`` guard and hits ``margin_of_safety = (iv - mc) / mc`` →
    ZeroDivisionError, crashing the entire Cathie Wood agent.

    Regression guard: a zero market_cap must be treated as missing data and
    return a safe neutral result, not crash.
    """
    financial_line_items = [
        SimpleNamespace(
            free_cash_flow=100.0,
            revenue=1000.0,
            operating_margin=0.2,
            research_and_development=50.0,
            capital_expenditure=20.0,
        )
    ]
    # market_cap=0.0 simulates the company-facts API returning a zero field
    result = cathie_wood.analyze_cathie_wood_valuation(financial_line_items, market_cap=0.0)
    # Must not raise; must return a neutral/zero-score dict, not crash
    assert isinstance(result, dict)
    assert result.get("score") == 0
    assert "market cap" in result.get("details", "").lower() or "insufficient" in result.get("details", "").lower()


def test_reinvestment_focus_treats_zero_dividends_as_strong_reinvestment():
    """dividends_and_other_cash_distributions == 0 (company paid nothing) is the
    textbook reinvestment-focused company Cathie Wood seeks — NOT missing data.

    tushare ``c_pay_dist_dpcp_int_exp`` (分配股利利润偿付利息支付现金) is 0.0 when a
    company distributes nothing in a period. ``_score_cathie_reinvestment_focus``
    computes ``payout_ratio = dividends / fcf``; a zero-dividend company has
    payout_ratio 0 (< 0.2 -> score 2 "Strong reinvestment"). Previously the
    truthiness filter ``and item.dividends_and_other_cash_distributions`` dropped
    every zero-dividend period, so an all-zero-dividend company fell through to
    "Insufficient dividend data" (score 0) — the exact opposite of the intended
    signal. Falsy-zero family (R105/R122), semantic inversion.
    """
    from src.agents.cathie_wood_helpers import _score_cathie_reinvestment_focus

    financial_line_items = [
        # Zero dividends (pure reinvestment) + positive FCF in every period
        SimpleNamespace(free_cash_flow=100.0, dividends_and_other_cash_distributions=0.0),
        SimpleNamespace(free_cash_flow=120.0, dividends_and_other_cash_distributions=0.0),
    ]

    score, detail = _score_cathie_reinvestment_focus(financial_line_items)

    # Zero-dividend company must score as strong reinvestment, NOT "Insufficient"
    assert score == 2
    assert "Strong focus on reinvestment" in detail


def test_rnd_trends_includes_zero_rd_aligning_with_rnd_intensity_sibling():
    """research_and_development == 0 is legitimate (no innovation spend), not
    missing. The within-file sibling ``_score_cathie_rnd_intensity`` already
    filters R&D with ``is not None`` (line 106); ``_score_cathie_rnd_trends``
    used truthiness (line 121) — a within-file semantic split. A company that
    paused R&D (R&D=0 in the latest period) must still be evaluated rather than
    silently dropping the period. Falsy-zero family (R105/R122).
    """
    from src.agents.cathie_wood_helpers import _score_cathie_rnd_trends

    financial_line_items = [
        # Latest period: R&D paused (legitimate 0); revenue present
        SimpleNamespace(research_and_development=0.0, revenue=1000.0),
        SimpleNamespace(research_and_development=100.0, revenue=800.0),
    ]

    score, details = _score_cathie_rnd_trends(financial_line_items)

    # Must NOT report "Insufficient R&D data" — the 0-R&D period is present data
    assert not any("Insufficient" in d for d in details)


def test_capex_commitment_includes_zero_capex_period():
    """capital_expenditure == 0 is legitimate (no infrastructure spend in a
    period), not missing. Same falsy-zero pattern as R122 (buffett) /
    _score_munger_capital_intensity sibling (both already use ``is not None``).
    A zero-capex period must count toward the >= 2 data minimum rather than be
    silently dropped. Falsy-zero family (R105/R122).
    """
    from src.agents.cathie_wood_helpers import _score_cathie_capex_commitment

    financial_line_items = [
        # Exactly 2 periods; one has legitimate zero capex
        SimpleNamespace(capital_expenditure=0.0, revenue=1000.0),
        SimpleNamespace(capital_expenditure=-50.0, revenue=1000.0),
    ]

    score, detail = _score_cathie_capex_commitment(financial_line_items)

    # Zero-capex period is present -> not "Insufficient CAPEX data"
    assert detail != "Insufficient CAPEX data"
