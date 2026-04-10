import json
from types import SimpleNamespace

import src.agents.valuation as valuation


def test_valuation_agent_builds_bullish_payload_with_dcf_scenarios(monkeypatch):
    monkeypatch.setattr(valuation, "get_api_key_from_state", lambda state, name: "k")
    monkeypatch.setattr(valuation.progress, "update_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        valuation,
        "get_financial_metrics",
        lambda **kwargs: [
            SimpleNamespace(
                earnings_growth=0.12,
                market_cap=1000.0,
                interest_coverage=8.0,
                debt_to_equity=0.3,
                revenue_growth=0.15,
                free_cash_flow_growth=0.2,
                price_to_book_ratio=1.5,
                book_value_growth=0.08,
            )
        ],
    )
    monkeypatch.setattr(
        valuation,
        "search_line_items",
        lambda **kwargs: [
            SimpleNamespace(
                net_income=100.0,
                depreciation_and_amortization=20.0,
                capital_expenditure=30.0,
                working_capital=50.0,
                total_debt=100.0,
                cash_and_equivalents=20.0,
                free_cash_flow=80.0,
            ),
            SimpleNamespace(
                net_income=90.0,
                depreciation_and_amortization=18.0,
                capital_expenditure=25.0,
                working_capital=45.0,
                total_debt=110.0,
                cash_and_equivalents=15.0,
                free_cash_flow=75.0,
            ),
        ],
    )
    monkeypatch.setattr(valuation, "get_market_cap", lambda *args, **kwargs: 1000.0)
    monkeypatch.setattr(valuation, "calculate_owner_earnings_value", lambda **kwargs: 1400.0)
    monkeypatch.setattr(valuation, "calculate_wacc", lambda **kwargs: 0.1)
    monkeypatch.setattr(
        valuation,
        "calculate_dcf_scenarios",
        lambda **kwargs: {
            "expected_value": 1600.0,
            "downside": 1200.0,
            "upside": 2000.0,
            "range": 800.0,
            "scenarios": {"base": 1600.0},
        },
    )
    monkeypatch.setattr(valuation, "calculate_ev_ebitda_value", lambda *args, **kwargs: 1100.0)
    monkeypatch.setattr(valuation, "calculate_residual_income_value", lambda **kwargs: 900.0)
    monkeypatch.setattr(valuation, "get_currency_symbol", lambda ticker: "¥")

    state = {
        "messages": [],
        "data": {"end_date": "2026-04-10", "tickers": ["000001"], "analyst_signals": {}},
        "metadata": {"show_reasoning": False},
    }

    result = valuation.valuation_analyst_agent(state)

    assert json.loads(result["messages"][0].content) == {
        "000001": {
            "signal": "bullish",
            "confidence": 100,
            "reasoning": {
                "dcf_analysis": {
                    "signal": "bullish",
                    "details": "Value: ¥1,600.00, Market Cap: ¥1,000.00, Gap: 60.0%, Weight: 35%\n  WACC: 10.0%, Bear: ¥1,200.00, Bull: ¥2,000.00, Range: ¥800.00",
                },
                "owner_earnings_analysis": {
                    "signal": "bullish",
                    "details": "Value: ¥1,400.00, Market Cap: ¥1,000.00, Gap: 40.0%, Weight: 35%",
                },
                "ev_ebitda_analysis": {
                    "signal": "neutral",
                    "details": "Value: ¥1,100.00, Market Cap: ¥1,000.00, Gap: 10.0%, Weight: 20%",
                },
                "residual_income_analysis": {
                    "signal": "neutral",
                    "details": "Value: ¥900.00, Market Cap: ¥1,000.00, Gap: -10.0%, Weight: 10%",
                },
                "dcf_scenario_analysis": {
                    "bear_case": "¥1,200.00",
                    "base_case": "¥1,600.00",
                    "bull_case": "¥2,000.00",
                    "wacc_used": "10.0%",
                    "fcf_periods_analyzed": 2,
                },
            },
        }
    }
    assert result["data"]["analyst_signals"] == {
        "valuation_analyst_agent": {
            "000001": {
                "signal": "bullish",
                "confidence": 100,
                "reasoning": {
                    "dcf_analysis": {
                        "signal": "bullish",
                        "details": "Value: ¥1,600.00, Market Cap: ¥1,000.00, Gap: 60.0%, Weight: 35%\n  WACC: 10.0%, Bear: ¥1,200.00, Bull: ¥2,000.00, Range: ¥800.00",
                    },
                    "owner_earnings_analysis": {
                        "signal": "bullish",
                        "details": "Value: ¥1,400.00, Market Cap: ¥1,000.00, Gap: 40.0%, Weight: 35%",
                    },
                    "ev_ebitda_analysis": {
                        "signal": "neutral",
                        "details": "Value: ¥1,100.00, Market Cap: ¥1,000.00, Gap: 10.0%, Weight: 20%",
                    },
                    "residual_income_analysis": {
                        "signal": "neutral",
                        "details": "Value: ¥900.00, Market Cap: ¥1,000.00, Gap: -10.0%, Weight: 10%",
                    },
                    "dcf_scenario_analysis": {
                        "bear_case": "¥1,200.00",
                        "base_case": "¥1,600.00",
                        "bull_case": "¥2,000.00",
                        "wacc_used": "10.0%",
                        "fcf_periods_analyzed": 2,
                    },
                },
            }
        }
    }


def test_valuation_agent_returns_neutral_error_when_metrics_are_missing(monkeypatch):
    monkeypatch.setattr(valuation, "get_api_key_from_state", lambda state, name: "k")
    monkeypatch.setattr(valuation.progress, "update_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(valuation, "get_financial_metrics", lambda **kwargs: [])

    state = {
        "messages": [],
        "data": {"end_date": "2026-04-10", "tickers": ["000001"], "analyst_signals": {}},
        "metadata": {"show_reasoning": False},
    }

    result = valuation.valuation_analyst_agent(state)

    assert json.loads(result["messages"][0].content) == {
        "000001": {
            "signal": "neutral",
            "confidence": 0,
            "reasoning": {"error": "No financial metrics available for valuation analysis"},
        }
    }
    assert result["data"]["analyst_signals"] == {
        "valuation_analyst_agent": {
            "000001": {
                "signal": "neutral",
                "confidence": 0,
                "reasoning": {"error": "No financial metrics available for valuation analysis"},
            }
        }
    }
