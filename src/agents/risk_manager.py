import json

import numpy as np
import pandas as pd
from langchain_core.messages import HumanMessage

from src.agents.risk_manager_helpers import (
    _build_correlation_matrix,
    _build_missing_price_analysis,
    _build_risk_analysis_entry,
    _calculate_total_portfolio_value,
    _collect_market_data,
)
from src.graph.state import AgentState, show_agent_reasoning
from src.tools.api import get_prices, prices_to_df
from src.utils.api_key import get_api_key_from_state
from src.utils.progress import progress
from src.utils.ticker_utils import get_currency_symbol


##### Risk Management Agent #####
def risk_management_agent(state: AgentState, agent_id: str = "risk_management_agent"):
    """Controls position sizing based on volatility-adjusted risk factors for multiple tickers."""
    portfolio = state["data"]["portfolio"]
    data = state["data"]
    tickers = data["tickers"]
    api_key = get_api_key_from_state(state, "FINANCIAL_DATASETS_API_KEY")
    risk_analysis = {}
    all_tickers = set(tickers) | set(portfolio.get("positions", {}).keys())
    current_prices, volatility_data, returns_by_ticker = _collect_market_data(
        all_tickers=all_tickers,
        data=data,
        api_key=api_key,
        agent_id=agent_id,
        progress_callback=progress.update_status,
        get_prices_callable=get_prices,
        prices_to_df_callable=prices_to_df,
        calculate_volatility_metrics_callable=calculate_volatility_metrics,
    )
    correlation_matrix = _build_correlation_matrix(returns_by_ticker)
    active_positions = {t for t, pos in portfolio.get("positions", {}).items() if abs(pos.get("long", 0) - pos.get("short", 0)) > 0}
    total_portfolio_value = _calculate_total_portfolio_value(portfolio, current_prices)
    progress.update_status(agent_id, None, f"Total portfolio value: {total_portfolio_value:.2f}")

    for ticker in tickers:
        progress.update_status(agent_id, ticker, "Calculating volatility- and correlation-adjusted limits")

        if ticker not in current_prices or current_prices[ticker] <= 0:
            progress.update_status(agent_id, ticker, "Failed: No valid price data")
            risk_analysis[ticker] = _build_missing_price_analysis()
            continue

        risk_analysis[ticker], combined_limit_pct = _build_risk_analysis_entry(
            portfolio=portfolio,
            ticker=ticker,
            current_prices=current_prices,
            volatility_data=volatility_data,
            correlation_matrix=correlation_matrix,
            active_positions=active_positions,
            total_portfolio_value=total_portfolio_value,
            calculate_volatility_adjusted_limit_callable=calculate_volatility_adjusted_limit,
            calculate_correlation_multiplier_callable=calculate_correlation_multiplier,
        )
        progress.update_status(
            agent_id,
            ticker,
            f"Adj. limit: {combined_limit_pct:.1%}, Available: {get_currency_symbol(ticker)}{risk_analysis[ticker]['remaining_position_limit']:.0f}",
        )

    progress.update_status(agent_id, None, "Done")

    message = HumanMessage(
        content=json.dumps(risk_analysis),
        name=agent_id,
    )

    if state["metadata"]["show_reasoning"]:
        show_agent_reasoning(risk_analysis, "Volatility-Adjusted Risk Management Agent")

    # Add the signal to the analyst_signals list
    state["data"]["analyst_signals"][agent_id] = risk_analysis

    return {
        "messages": state["messages"] + [message],
        "data": data,
    }


def calculate_volatility_metrics(prices_df: pd.DataFrame, lookback_days: int = 60) -> dict:
    """Calculate comprehensive volatility metrics from price data."""
    if len(prices_df) < 2:
        return {"daily_volatility": 0.05, "annualized_volatility": 0.05 * np.sqrt(252), "volatility_percentile": 100, "data_points": len(prices_df)}

    # Calculate daily returns
    daily_returns = prices_df["close"].pct_change().dropna()

    if len(daily_returns) < 2:
        return {"daily_volatility": 0.05, "annualized_volatility": 0.05 * np.sqrt(252), "volatility_percentile": 100, "data_points": len(daily_returns)}

    # Use the most recent lookback_days for volatility calculation
    recent_returns = daily_returns.tail(min(lookback_days, len(daily_returns)))

    # Calculate volatility metrics
    daily_vol = recent_returns.std()
    annualized_vol = daily_vol * np.sqrt(252)  # Annualize assuming 252 trading days

    # Calculate percentile rank of recent volatility vs historical volatility
    if len(daily_returns) >= 30:  # Need sufficient history for percentile calculation
        # Calculate 30-day rolling volatility for the full history
        rolling_vol = daily_returns.rolling(window=30).std().dropna()
        if len(rolling_vol) > 0:
            # Compare current volatility against historical rolling volatilities
            current_vol_percentile = (rolling_vol <= daily_vol).mean() * 100
        else:
            current_vol_percentile = 50  # Default to median
    else:
        current_vol_percentile = 50  # Default to median if insufficient data

    return {"daily_volatility": float(daily_vol) if not np.isnan(daily_vol) else 0.025, "annualized_volatility": float(annualized_vol) if not np.isnan(annualized_vol) else 0.25, "volatility_percentile": float(current_vol_percentile) if not np.isnan(current_vol_percentile) else 50.0, "data_points": len(recent_returns)}


def calculate_volatility_adjusted_limit(annualized_volatility: float) -> float:
    """
    Calculate position limit as percentage of portfolio based on volatility.

    Logic:
    - Low volatility (<15%): Up to 25% allocation
    - Medium volatility (15-30%): 15-20% allocation
    - High volatility (>30%): 10-15% allocation
    - Very high volatility (>50%): Max 10% allocation
    """
    base_limit = 0.20  # 20% baseline

    if annualized_volatility < 0.15:  # Low volatility
        # Allow higher allocation for stable stocks
        vol_multiplier = 1.25  # Up to 25%
    elif annualized_volatility < 0.30:  # Medium volatility
        # Standard allocation with slight adjustment based on volatility
        vol_multiplier = 1.0 - (annualized_volatility - 0.15) * 0.5  # 20% -> 12.5%
    elif annualized_volatility < 0.50:  # High volatility
        # Reduce allocation significantly
        vol_multiplier = 0.75 - (annualized_volatility - 0.30) * 0.5  # 15% -> 5%
    else:  # Very high volatility (>50%)
        # Minimum allocation for very risky stocks
        vol_multiplier = 0.50  # Max 10%

    # Apply bounds to ensure reasonable limits
    vol_multiplier = max(0.25, min(1.25, vol_multiplier))  # 5% to 25% range

    return base_limit * vol_multiplier


def calculate_correlation_multiplier(avg_correlation: float) -> float:
    """Map average correlation to an adjustment multiplier.
    - Very high correlation (>= 0.8): reduce limit sharply (0.7x)
    - High correlation (0.6-0.8): reduce (0.85x)
    - Moderate correlation (0.4-0.6): neutral (1.0x)
    - Low correlation (0.2-0.4): slight increase (1.05x)
    - Very low correlation (< 0.2): increase (1.10x)
    """
    if avg_correlation >= 0.80:
        return 0.70
    if avg_correlation >= 0.60:
        return 0.85
    if avg_correlation >= 0.40:
        return 1.00
    if avg_correlation >= 0.20:
        return 1.05
    return 1.10
