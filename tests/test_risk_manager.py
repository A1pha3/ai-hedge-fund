import pandas as pd

import src.agents.risk_manager as risk_manager_module
from src.agents.risk_manager import risk_management_agent


def test_risk_management_agent_returns_missing_price_payload_when_all_prices_missing(monkeypatch):
    monkeypatch.setattr(risk_manager_module.progress, "update_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(risk_manager_module, "get_api_key_from_state", lambda state, key: "fake")
    monkeypatch.setattr(risk_manager_module, "get_prices", lambda **kwargs: [])

    state = {
        "messages": [],
        "metadata": {"show_reasoning": False},
        "data": {
            "tickers": ["AAA"],
            "start_date": "2026-01-01",
            "end_date": "2026-04-10",
            "portfolio": {"cash": 1000.0, "positions": {}},
            "analyst_signals": {},
        },
    }

    result = risk_management_agent(state)

    assert result["data"]["analyst_signals"]["risk_management_agent"]["AAA"] == {
        "remaining_position_limit": 0.0,
        "current_price": 0.0,
        "reasoning": {"error": "Missing price data for risk calculation"},
    }


def test_risk_management_agent_preserves_single_ticker_limit_payload(monkeypatch):
    monkeypatch.setattr(risk_manager_module.progress, "update_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(risk_manager_module, "get_api_key_from_state", lambda state, key: "fake")
    monkeypatch.setattr(risk_manager_module, "get_prices", lambda **kwargs: ["stub"])
    monkeypatch.setattr(risk_manager_module, "prices_to_df", lambda prices: pd.DataFrame({"close": [10, 11, 12, 11, 13, 14]}))
    # Use vol=0.00 so the continuous interpolation returns the first anchor (1.25 -> 25%)
    # exactly, avoiding float-precision issues in the test comparison.
    monkeypatch.setattr(
        risk_manager_module,
        "calculate_volatility_metrics",
        lambda df: {
            "daily_volatility": 0.0,
            "annualized_volatility": 0.0,
            "volatility_percentile": 0,
            "data_points": 5,
        },
    )

    state = {
        "messages": [],
        "metadata": {"show_reasoning": False},
        "data": {
            "tickers": ["AAA"],
            "start_date": "2026-01-01",
            "end_date": "2026-04-10",
            "portfolio": {"cash": 1000.0, "positions": {"AAA": {"long": 10, "short": 0}}},
            "analyst_signals": {},
        },
    }

    result = risk_management_agent(state)

    # With vol=0.00, the first anchor (1.25 multiplier) applies exactly:
    # combined_limit_pct = 0.20 * 1.25 = 0.25
    # portfolio_value = 1000 + 10*14 = 1140
    # position_limit = 1140 * 0.25 = 285.0
    # current_position_value = 10*14 = 140
    # remaining = 285 - 140 = 145
    assert result["data"]["analyst_signals"]["risk_management_agent"]["AAA"] == {
        "remaining_position_limit": 145.0,
        "current_price": 14.0,
        "volatility_metrics": {
            "daily_volatility": 0.0,
            "annualized_volatility": 0.0,
            "volatility_percentile": 0.0,
            "data_points": 5,
        },
        "correlation_metrics": {
            "avg_correlation_with_active": None,
            "max_correlation_with_active": None,
            "top_correlated_tickers": [],
        },
        "reasoning": {
            "portfolio_value": 1140.0,
            "current_position_value": 140.0,
            "base_position_limit_pct": 0.25,
            "correlation_multiplier": 1.0,
            "combined_position_limit_pct": 0.25,
            "position_limit": 285.0,
            "remaining_limit": 145.0,
            "available_cash": 1000.0,
            "risk_adjustment": "Volatility x Correlation adjusted: 25.0% (base 25.0%)",
        },
    }
