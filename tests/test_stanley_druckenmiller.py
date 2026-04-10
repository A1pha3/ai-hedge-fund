from types import SimpleNamespace

from src.agents.stanley_druckenmiller import (
    analyze_druckenmiller_valuation,
    analyze_growth_and_momentum,
    analyze_risk_reward,
)


def test_analyze_growth_and_momentum_preserves_price_only_bullish_path():
    financial_line_items = [
        SimpleNamespace(revenue=180.0, earnings_per_share=9.0),
        SimpleNamespace(revenue=150.0, earnings_per_share=7.0),
        SimpleNamespace(revenue=120.0, earnings_per_share=5.0),
    ]
    prices = [SimpleNamespace(time=index, close=100 + index * 2) for index in range(40)]

    assert analyze_growth_and_momentum(financial_line_items, prices) == {
        "score": 3.333333333333333,
        "details": "Insufficient revenue data for CAGR calculation.; Insufficient EPS data for CAGR calculation.; Very strong price momentum: 78.0%",
    }


def test_analyze_growth_and_momentum_preserves_missing_data_guard():
    assert analyze_growth_and_momentum([SimpleNamespace(revenue=None, earnings_per_share=None)], []) == {
        "score": 0,
        "details": "Insufficient financial data for growth analysis",
    }


def test_analyze_risk_reward_preserves_direct_debt_and_low_volatility_path():
    financial_line_items = [SimpleNamespace(debt_to_equity=0.25)]
    prices = [SimpleNamespace(time=index, close=100 + (index % 2)) for index in range(12)]

    assert analyze_risk_reward(financial_line_items, prices) == {
        "score": 10,
        "details": "Low debt-to-equity: 0.25; Low volatility: daily returns stdev 0.99%",
    }


def test_analyze_risk_reward_preserves_fallback_debt_and_high_volatility_path():
    financial_line_items = [
        SimpleNamespace(total_debt=60.0, shareholders_equity=100.0),
        SimpleNamespace(total_debt=70.0, shareholders_equity=95.0),
    ]
    prices = [SimpleNamespace(time=index, close=value) for index, value in enumerate([100, 110, 95, 120, 90, 130, 85, 125, 80, 140, 75, 150])]

    assert analyze_risk_reward(financial_line_items, prices) == {
        "score": 3.333333333333333,
        "details": "Moderate debt-to-equity: 0.60; Very high volatility: daily returns stdev 46.81%",
    }


def test_analyze_druckenmiller_valuation_preserves_attractive_multi_metric_path():
    financial_line_items = [
        SimpleNamespace(net_income=100.0, free_cash_flow=80.0, ebit=120.0, ebitda=150.0, total_debt=200.0, cash_and_equivalents=50.0),
        SimpleNamespace(net_income=90.0, free_cash_flow=75.0, ebit=110.0, ebitda=140.0, total_debt=210.0, cash_and_equivalents=40.0),
    ]

    assert analyze_druckenmiller_valuation(financial_line_items, 1000.0) == {
        "score": 7.5,
        "details": "No positive net income for P/E calculation; Attractive P/FCF: 12.50; Attractive EV/EBIT: 9.58; Attractive EV/EBITDA: 7.67",
    }


def test_analyze_druckenmiller_valuation_preserves_zero_score_sparse_path():
    financial_line_items = [
        SimpleNamespace(net_income=None, free_cash_flow=-10.0, ebit=0.0, ebitda=None, total_debt=20.0, cash_and_equivalents=30.0)
    ]

    assert analyze_druckenmiller_valuation(financial_line_items, 1000.0) == {
        "score": 0.0,
        "details": "No positive net income for P/E calculation; No positive free cash flow for P/FCF calculation; No valid EV/EBIT because EV <= 0 or EBIT <= 0; No valid EV/EBITDA because EV <= 0 or EBITDA <= 0",
    }
