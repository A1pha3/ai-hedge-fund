import json

from langchain_core.messages import HumanMessage

from src.agents.fundamentals_helpers import (
    _analyze_fundamentals_growth,
    _analyze_fundamentals_health,
    _analyze_fundamentals_price_ratios,
    _analyze_fundamentals_profitability,
    _build_missing_fundamentals_result,
    _finalize_fundamentals_signal,
)
from src.graph.state import AgentState, show_agent_reasoning
from src.tools.api import get_financial_metrics
from src.utils.api_key import get_api_key_from_state
from src.utils.progress import progress


##### Fundamental Agent #####
def fundamentals_analyst_agent(state: AgentState, agent_id: str = "fundamentals_analyst_agent"):
    """Analyzes fundamental data and generates trading signals for multiple tickers."""
    data = state["data"]
    end_date = data["end_date"]
    tickers = data["tickers"]
    api_key = get_api_key_from_state(state, "FINANCIAL_DATASETS_API_KEY")
    # Initialize fundamental analysis for each ticker
    fundamental_analysis = {}

    for ticker in tickers:
        progress.update_status(agent_id, ticker, "Fetching financial metrics")

        # Get the financial metrics
        financial_metrics = get_financial_metrics(
            ticker=ticker,
            end_date=end_date,
            period="ttm",
            limit=10,
            api_key=api_key,
        )

        if not financial_metrics:
            progress.update_status(agent_id, ticker, "Failed: No financial metrics found")
            fundamental_analysis[ticker] = _build_missing_fundamentals_result()
            continue

        metrics = financial_metrics[0]
        signals = []
        reasoning = {}

        progress.update_status(agent_id, ticker, "Analyzing profitability")
        profitability_signal, profitability_reasoning = _analyze_fundamentals_profitability(metrics)
        signals.append(profitability_signal)
        reasoning["profitability_signal"] = profitability_reasoning

        progress.update_status(agent_id, ticker, "Analyzing growth")
        growth_signal, growth_reasoning = _analyze_fundamentals_growth(metrics)
        signals.append(growth_signal)
        reasoning["growth_signal"] = growth_reasoning

        progress.update_status(agent_id, ticker, "Analyzing financial health")
        health_signal, health_reasoning = _analyze_fundamentals_health(metrics)
        signals.append(health_signal)
        reasoning["financial_health_signal"] = health_reasoning

        progress.update_status(agent_id, ticker, "Analyzing valuation ratios")
        price_ratio_signal, price_ratio_reasoning = _analyze_fundamentals_price_ratios(metrics)
        signals.append(price_ratio_signal)
        reasoning["price_ratios_signal"] = price_ratio_reasoning

        progress.update_status(agent_id, ticker, "Calculating final signal")
        fundamental_analysis[ticker] = _finalize_fundamentals_signal(signals, reasoning)

        progress.update_status(agent_id, ticker, "Done", analysis=json.dumps(reasoning, indent=4))

    # Create the fundamental analysis message
    message = HumanMessage(
        content=json.dumps(fundamental_analysis),
        name=agent_id,
    )

    # Print the reasoning if the flag is set
    if state["metadata"]["show_reasoning"]:
        show_agent_reasoning(fundamental_analysis, "Fundamental Analysis Agent")

    # Add the signal to the analyst_signals list
    state["data"]["analyst_signals"][agent_id] = fundamental_analysis

    progress.update_status(agent_id, None, "Done")

    return {
        "messages": [message],
        "data": data,
    }
