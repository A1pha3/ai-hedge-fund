import json
from types import SimpleNamespace

import src.agents.fundamentals as fundamentals


def test_fundamentals_agent_builds_bullish_payload_with_clamped_growth(monkeypatch):
    monkeypatch.setattr(fundamentals, "get_api_key_from_state", lambda state, name: "k")
    monkeypatch.setattr(fundamentals.progress, "update_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        fundamentals,
        "get_financial_metrics",
        lambda **kwargs: [
            SimpleNamespace(
                return_on_equity=0.20,
                net_margin=0.25,
                operating_margin=0.18,
                revenue_growth=0.12,
                earnings_growth=8.0,
                book_value_growth=0.11,
                current_ratio=1.8,
                debt_to_equity=0.3,
                free_cash_flow_per_share=4.0,
                earnings_per_share=4.5,
                price_to_earnings_ratio=20.0,
                price_to_book_ratio=2.0,
                price_to_sales_ratio=4.0,
            )
        ],
    )

    state = {
        "messages": [],
        "data": {"end_date": "2026-04-10", "tickers": ["AAPL"], "analyst_signals": {}},
        "metadata": {"show_reasoning": False},
    }

    result = fundamentals.fundamentals_analyst_agent(state)

    assert result["messages"][0].name == "fundamentals_analyst_agent"
    assert json.loads(result["messages"][0].content) == {
        "AAPL": {
            "signal": "bullish",
            "confidence": 100.0,
            "reasoning": {
                "profitability_signal": {
                    "signal": "bullish",
                    "details": "ROE(TTM): 20.00%, Net Margin(TTM): 25.00%, Op Margin(TTM): 18.00%",
                },
                "growth_signal": {
                    "signal": "bullish",
                    "details": "Revenue Growth(TTM YoY): 12.00%, Earnings Growth(TTM YoY): 500.00%",
                },
                "financial_health_signal": {
                    "signal": "bullish",
                    "details": "Current Ratio: 1.80, D/E: 0.30",
                },
                "price_ratios_signal": {
                    "signal": "bullish",
                    "details": "P/E(TTM): 20.00, P/B: 2.00, P/S: 4.00",
                },
            },
        }
    }
    assert result["data"]["analyst_signals"] == {
        "fundamentals_analyst_agent": {
            "AAPL": {
                "signal": "bullish",
                "confidence": 100.0,
                "reasoning": {
                    "profitability_signal": {
                        "signal": "bullish",
                        "details": "ROE(TTM): 20.00%, Net Margin(TTM): 25.00%, Op Margin(TTM): 18.00%",
                    },
                    "growth_signal": {
                        "signal": "bullish",
                        "details": "Revenue Growth(TTM YoY): 12.00%, Earnings Growth(TTM YoY): 500.00%",
                    },
                    "financial_health_signal": {
                        "signal": "bullish",
                        "details": "Current Ratio: 1.80, D/E: 0.30",
                    },
                    "price_ratios_signal": {
                        "signal": "bullish",
                        "details": "P/E(TTM): 20.00, P/B: 2.00, P/S: 4.00",
                    },
                },
            }
        }
    }


def test_fundamentals_agent_returns_neutral_error_when_financial_metrics_are_missing(monkeypatch):
    monkeypatch.setattr(fundamentals, "get_api_key_from_state", lambda state, name: "k")
    monkeypatch.setattr(fundamentals.progress, "update_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(fundamentals, "get_financial_metrics", lambda **kwargs: [])

    state = {
        "messages": [],
        "data": {"end_date": "2026-04-10", "tickers": ["MSFT"], "analyst_signals": {}},
        "metadata": {"show_reasoning": False},
    }

    result = fundamentals.fundamentals_analyst_agent(state)

    assert json.loads(result["messages"][0].content) == {
        "MSFT": {
            "signal": "neutral",
            "confidence": 0,
            "reasoning": {"error": "No financial metrics available for fundamental analysis"},
        }
    }
    assert result["data"]["analyst_signals"] == {
        "fundamentals_analyst_agent": {
            "MSFT": {
                "signal": "neutral",
                "confidence": 0,
                "reasoning": {"error": "No financial metrics available for fundamental analysis"},
            }
        }
    }
