from __future__ import annotations

"""Growth Agent

Implements a growth-focused valuation methodology.
"""

import json
import statistics

from langchain_core.messages import HumanMessage

from src.graph.state import AgentState, show_agent_reasoning
from src.tools.api import (
    get_financial_metrics,
    get_insider_trades,
)
from src.utils.api_key import get_api_key_from_state
from src.utils.progress import progress
from src.utils.ticker_utils import get_currency_symbol


def growth_analyst_agent(state: AgentState, agent_id: str = "growth_analyst_agent"):
    """Run growth analysis across tickers and write signals back to `state`."""

    data = state["data"]
    end_date = data["end_date"]
    tickers = data["tickers"]
    api_key = get_api_key_from_state(state, "FINANCIAL_DATASETS_API_KEY")
    growth_analysis: dict[str, dict] = {}

    for ticker in tickers:
        progress.update_status(agent_id, ticker, "Fetching financial data")

        # --- Historical financial metrics ---
        financial_metrics = get_financial_metrics(
            ticker=ticker,
            end_date=end_date,
            period="ttm",
            limit=12,  # 3 years of ttm data
            api_key=api_key,
        )
        if not financial_metrics or len(financial_metrics) < 4:
            progress.update_status(agent_id, ticker, "Failed: Not enough financial metrics")
            growth_analysis[ticker] = {
                "signal": "neutral",
                "confidence": 0,
                "reasoning": {"error": f"Insufficient financial metrics (found {len(financial_metrics) if financial_metrics else 0}, need at least 4)"},
            }
            continue

        most_recent_metrics = financial_metrics[0]

        # --- Insider Trades ---
        insider_trades = get_insider_trades(ticker=ticker, end_date=end_date, limit=1000, api_key=api_key)

        # ------------------------------------------------------------------
        # Tool Implementation
        # ------------------------------------------------------------------

        # 1. Historical Growth Analysis
        growth_trends = analyze_growth_trends(financial_metrics)

        # 2. Growth-Oriented Valuation
        valuation_metrics = analyze_valuation(most_recent_metrics)

        # 3. Margin Expansion Monitor
        margin_trends = analyze_margin_trends(financial_metrics)

        # 4. Insider Conviction Tracker
        insider_conviction = analyze_insider_conviction(insider_trades)

        # 5. Financial Health Check
        financial_health = check_financial_health(most_recent_metrics)

        # ------------------------------------------------------------------
        # Aggregate & signal
        # ------------------------------------------------------------------
        scores = {"growth": growth_trends["score"], "valuation": valuation_metrics["score"], "margins": margin_trends["score"], "insider": insider_conviction["score"], "health": financial_health["score"]}

        weights = {"growth": 0.40, "valuation": 0.25, "margins": 0.15, "insider": 0.10, "health": 0.10}

        weighted_score = sum(scores[key] * weights[key] for key in scores)

        if weighted_score > 0.6:
            signal = "bullish"
        elif weighted_score < 0.4:
            signal = "bearish"
        else:
            signal = "neutral"

        confidence = round(abs(weighted_score - 0.5) * 2 * 100)

        # Build structured reasoning compatible with _format_reasoning_to_markdown
        def fmt_pct(val):
            return f"{val:.2%}" if val is not None else "N/A"

        def fmt_float(val):
            return f"{val:.2f}" if val is not None else "N/A"

        reasoning = {
            "historical_growth": {
                "signal": "bullish" if growth_trends["score"] > 0.6 else "bearish" if growth_trends["score"] < 0.4 else "neutral",
                "details": f"Revenue Growth: {fmt_pct(growth_trends['revenue_growth'])}, EPS Growth: {fmt_pct(growth_trends['eps_growth'])}, FCF Growth: {fmt_pct(growth_trends['fcf_growth'])}",
                "metrics": {k: (v if v is not None else "N/A") for k, v in growth_trends.items() if k != "score"},
            },
            "growth_valuation": {
                "signal": "bullish" if valuation_metrics["score"] > 0.6 else "bearish" if valuation_metrics["score"] < 0.4 else "neutral",
                "details": f"PEG Ratio: {fmt_float(valuation_metrics['peg_ratio'])}, P/S Ratio: {fmt_float(valuation_metrics['price_to_sales_ratio'])}",
                "metrics": {k: (v if v is not None else "N/A") for k, v in valuation_metrics.items() if k != "score"},
            },
            "margin_expansion": {
                "signal": "bullish" if margin_trends["score"] > 0.6 else "bearish" if margin_trends["score"] < 0.4 else "neutral",
                "details": f"Gross Margin: {fmt_pct(margin_trends['gross_margin'])}, Operating Margin: {fmt_pct(margin_trends['operating_margin'])}, Net Margin: {fmt_pct(margin_trends['net_margin'])}",
                "metrics": {k: (v if v is not None else "N/A") for k, v in margin_trends.items() if k != "score"},
            },
            "insider_conviction": {
                "signal": "bullish" if insider_conviction["score"] > 0.6 else "bearish" if insider_conviction["score"] < 0.4 else "neutral",
                "details": f"Net Flow Ratio: {insider_conviction['net_flow_ratio']:.2f}, Total Buys: {get_currency_symbol(ticker)}{insider_conviction['buys']:,.0f}, Total Sells: {get_currency_symbol(ticker)}{insider_conviction['sells']:,.0f}",
                "metrics": {k: v for k, v in insider_conviction.items() if k != "score"},
            },
            "financial_health": {
                "signal": "bullish" if financial_health["score"] > 0.6 else "bearish" if financial_health["score"] < 0.4 else "neutral",
                "details": f"Debt/Equity: {fmt_float(financial_health['debt_to_equity'])}, Current Ratio: {fmt_float(financial_health['current_ratio'])}",
                "metrics": {k: (v if v is not None else "N/A") for k, v in financial_health.items() if k != "score"},
            },
            "final_analysis": {"signal": signal, "confidence": confidence, "weighted_score": round(weighted_score, 2)},
        }

        growth_analysis[ticker] = {
            "signal": signal,
            "confidence": confidence,
            "reasoning": reasoning,
        }
        progress.update_status(agent_id, ticker, "Done", analysis=json.dumps(reasoning, indent=4))

    # ---- Emit message (for LLM tool chain) ----
    msg = HumanMessage(content=json.dumps(growth_analysis), name=agent_id)
    if state["metadata"].get("show_reasoning"):
        show_agent_reasoning(growth_analysis, "Growth Analysis Agent")

    # Add the signal to the analyst_signals list
    state["data"]["analyst_signals"][agent_id] = growth_analysis

    progress.update_status(agent_id, None, "Done")

    return {"messages": [msg], "data": data}


#############################
# Helper Functions
#############################


def _calculate_trend(data: list[float | None]) -> float:
    """Calculates the slope of the trend line for the given data."""
    clean_data = [d for d in data if d is not None]
    if len(clean_data) < 2:
        return 0.0

    y = clean_data
    x = list(range(len(y)))

    try:
        # Simple linear regression
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(i * j for i, j in zip(x, y))
        sum_x2 = sum(i**2 for i in x)
        n = len(y)

        slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x**2)
        return slope
    except ZeroDivisionError:
        return 0.0


def _clamp_growth(value, lower=-1.0, upper=5.0):
    """Clamp growth rate to a meaningful range. Values beyond [-100%, +500%] are
    typically caused by zero-crossing and are not meaningful for analysis."""
    if value is None:
        return None
    return max(lower, min(upper, value))


def analyze_growth_trends(metrics: list) -> dict:
    """Analyzes historical growth trends."""

    rev_growth = [m.revenue_growth for m in metrics]
    # Clamp EPS/FCF growth to avoid extreme values from zero-crossing
    eps_growth = [_clamp_growth(m.earnings_per_share_growth) for m in metrics]
    fcf_growth = [_clamp_growth(m.free_cash_flow_growth) for m in metrics]

    rev_trend = _calculate_trend(rev_growth)
    eps_trend = _calculate_trend(eps_growth)
    fcf_trend = _calculate_trend(fcf_growth)

    # Score based on recent growth and trend
    score = 0

    # Revenue
    if rev_growth[0] is not None:
        if rev_growth[0] > 0.20:
            score += 0.4
        elif rev_growth[0] > 0.10:
            score += 0.2
        elif rev_growth[0] < -0.10:
            score -= 0.2  # Penalize significant revenue decline
        if rev_trend > 0:
            score += 0.1  # Accelerating

    # EPS
    if eps_growth[0] is not None:
        if eps_growth[0] > 0.20:
            score += 0.25
        elif eps_growth[0] > 0.10:
            score += 0.1
        elif eps_growth[0] < -0.50:
            score -= 0.2  # Penalize severe EPS decline
        elif eps_growth[0] < -0.10:
            score -= 0.1  # Penalize moderate EPS decline
        if eps_trend > 0:
            score += 0.05

    # FCF
    if fcf_growth[0] is not None:
        if fcf_growth[0] > 0.15:
            score += 0.1

    score = max(min(score, 1.0), 0.0)

    return {"score": score, "revenue_growth": rev_growth[0], "revenue_trend": rev_trend, "eps_growth": eps_growth[0], "eps_trend": eps_trend, "fcf_growth": fcf_growth[0], "fcf_trend": fcf_trend}


def analyze_valuation(metrics) -> dict:
    """Analyzes valuation from a growth perspective."""

    peg_ratio = metrics.peg_ratio
    ps_ratio = metrics.price_to_sales_ratio

    score = 0

    # PEG Ratio
    if peg_ratio is not None:
        if peg_ratio < 1.0:
            score += 0.5
        elif peg_ratio < 2.0:
            score += 0.25

    # Price to Sales Ratio
    if ps_ratio is not None:
        if ps_ratio < 2.0:
            score += 0.5
        elif ps_ratio < 5.0:
            score += 0.25

    score = min(score, 1.0)

    return {"score": score, "peg_ratio": peg_ratio, "price_to_sales_ratio": ps_ratio}


def analyze_margin_trends(metrics: list) -> dict:
    """Analyzes historical margin trends."""

    gross_margins = [m.gross_margin for m in metrics]
    operating_margins = [m.operating_margin for m in metrics]
    net_margins = [m.net_margin for m in metrics]

    gm_trend = _calculate_trend(gross_margins)
    om_trend = _calculate_trend(operating_margins)
    nm_trend = _calculate_trend(net_margins)

    score = 0

    # Gross Margin
    if gross_margins[0] is not None:
        if gross_margins[0] > 0.5:  # Healthy margin
            score += 0.2
        if gm_trend > 0:  # Expanding
            score += 0.2

    # Operating Margin
    if operating_margins[0] is not None:
        if operating_margins[0] > 0.15:  # Healthy margin
            score += 0.2
        if om_trend > 0:  # Expanding
            score += 0.2

    # Net Margin Trend
    if nm_trend > 0:
        score += 0.2

    score = min(score, 1.0)

    return {"score": score, "gross_margin": gross_margins[0], "gross_margin_trend": gm_trend, "operating_margin": operating_margins[0], "operating_margin_trend": om_trend, "net_margin": net_margins[0], "net_margin_trend": nm_trend}


def analyze_insider_conviction(trades: list) -> dict:
    """Analyzes insider trading activity."""

    buys = sum(t.transaction_value for t in trades if t.transaction_value and t.transaction_shares > 0)
    sells = sum(abs(t.transaction_value) for t in trades if t.transaction_value and t.transaction_shares < 0)

    if (buys + sells) == 0:
        net_flow_ratio = 0
    else:
        net_flow_ratio = (buys - sells) / (buys + sells)

    score = 0
    if net_flow_ratio > 0.5:
        score = 1.0
    elif net_flow_ratio > 0.1:
        score = 0.7
    elif net_flow_ratio > -0.1:
        score = 0.5  # Neutral
    else:
        score = 0.2

    return {"score": score, "net_flow_ratio": net_flow_ratio, "buys": buys, "sells": sells}


def check_financial_health(metrics) -> dict:
    """Checks the company's financial health."""

    debt_to_equity = metrics.debt_to_equity
    current_ratio = metrics.current_ratio

    score = 1.0

    # Debt to Equity
    if debt_to_equity is not None:
        if debt_to_equity > 1.5:
            score -= 0.5
        elif debt_to_equity > 0.8:
            score -= 0.2

    # Current Ratio
    if current_ratio is not None:
        if current_ratio < 1.0:
            score -= 0.5
        elif current_ratio < 1.5:
            score -= 0.2

    score = max(score, 0.0)

    return {"score": score, "debt_to_equity": debt_to_equity, "current_ratio": current_ratio}
