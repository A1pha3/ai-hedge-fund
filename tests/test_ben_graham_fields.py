from types import SimpleNamespace

from src.agents.ben_graham import analyze_financial_strength


def test_analyze_financial_strength_scores_strong_liquidity_conservative_debt_and_dividends():
    financial_line_items = [
        SimpleNamespace(
            total_assets=100.0,
            total_liabilities=40.0,
            current_assets=120.0,
            current_liabilities=50.0,
            dividends_and_other_cash_distributions=-2.0,
        ),
        SimpleNamespace(dividends_and_other_cash_distributions=-1.0),
        SimpleNamespace(dividends_and_other_cash_distributions=0.0),
    ]

    result = analyze_financial_strength(financial_line_items)

    assert result["score"] == 5
    assert "Current ratio = 2.40 (>=2.0: solid)." in result["details"]
    assert "Debt ratio = 0.40, under 0.50 (conservative)." in result["details"]
    assert "Company paid dividends in the majority of the reported years." in result["details"]


def test_analyze_financial_strength_reports_missing_ratio_inputs_and_absent_dividend_history():
    financial_line_items = [
        SimpleNamespace(
            total_assets=0.0,
            total_liabilities=25.0,
            current_assets=20.0,
            current_liabilities=0.0,
        ),
        SimpleNamespace(),
    ]

    result = analyze_financial_strength(financial_line_items)

    assert result["score"] == 0
    assert "Cannot compute current ratio (missing or zero current_liabilities)." in result["details"]
    assert "Cannot compute debt ratio (missing total_assets)." in result["details"]
    assert "No dividend data available to assess payout consistency." in result["details"]
