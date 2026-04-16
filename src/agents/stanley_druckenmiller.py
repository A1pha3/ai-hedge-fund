import json

from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel
from typing import Literal

from src.agents.stanley_druckenmiller_helpers import (
    _collect_druckenmiller_valuation_inputs,
    _resolve_druckenmiller_de_ratio,
    _score_druckenmiller_de_ratio,
    _score_druckenmiller_ev_ebit,
    _score_druckenmiller_ev_ebitda,
    _score_druckenmiller_growth_metric,
    _score_druckenmiller_pe,
    _score_druckenmiller_pfcf,
    _score_druckenmiller_price_momentum,
    _score_druckenmiller_volatility,
)
from src.agents.prompt_rules import with_fact_grounding_rules
from src.graph.state import AgentState, show_agent_reasoning
from src.tools.api import (
    get_company_news,
    get_insider_trades,
    get_market_cap,
    get_prices,
    search_line_items,
)
from src.utils.api_key import get_api_key_from_state
from src.utils.financial_calcs import calculate_cagr_from_line_items, calculate_pe_from_line_items
from src.utils.llm import call_llm
from src.utils.progress import progress
from src.utils.ticker_utils import get_currency_context


class StanleyDruckenmillerSignal(BaseModel):
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: float
    reasoning: str
    reasoning_cn: str


def stanley_druckenmiller_agent(state: AgentState, agent_id: str = "stanley_druckenmiller_agent"):
    """
    Analyzes stocks using Stanley Druckenmiller's investing principles:
      - Seeking asymmetric risk-reward opportunities
      - Emphasizing growth, momentum, and sentiment
      - Willing to be aggressive if conditions are favorable
      - Focus on preserving capital by avoiding high-risk, low-reward bets

    Returns a bullish/bearish/neutral signal with confidence and reasoning.
    """
    data = state["data"]
    start_date = data["start_date"]
    end_date = data["end_date"]
    tickers = data["tickers"]
    api_key = get_api_key_from_state(state, "FINANCIAL_DATASETS_API_KEY")
    analysis_data = {}
    druck_analysis = {}

    for ticker in tickers:
        progress.update_status(agent_id, ticker, "Gathering financial line items")
        # Include relevant line items for Stan Druckenmiller's approach:
        #   - Growth & momentum: revenue, EPS, operating_income, ...
        #   - Valuation: net_income, free_cash_flow, ebit, ebitda
        #   - Leverage: total_debt, shareholders_equity
        #   - Liquidity: cash_and_equivalents
        financial_line_items = search_line_items(
            ticker,
            [
                "revenue",
                "earnings_per_share",
                "net_income",
                "operating_income",
                "gross_margin",
                "operating_margin",
                "free_cash_flow",
                "capital_expenditure",
                "cash_and_equivalents",
                "total_debt",
                "shareholders_equity",
                "outstanding_shares",
                "debt_to_equity",
                "ebit",
                "ebitda",
            ],
            end_date,
            period="annual",
            limit=10,
            api_key=api_key,
        )

        progress.update_status(agent_id, ticker, "Getting market cap")
        market_cap = get_market_cap(ticker, end_date, api_key=api_key)

        progress.update_status(agent_id, ticker, "Fetching insider trades")
        insider_trades = get_insider_trades(ticker, end_date, limit=50, api_key=api_key)

        progress.update_status(agent_id, ticker, "Fetching company news")
        company_news = get_company_news(ticker, end_date, limit=50, api_key=api_key)

        progress.update_status(agent_id, ticker, "Fetching recent price data for momentum")
        prices = get_prices(ticker, start_date=start_date, end_date=end_date, api_key=api_key)

        progress.update_status(agent_id, ticker, "Analyzing growth & momentum")
        growth_momentum_analysis = analyze_growth_and_momentum(financial_line_items, prices)

        progress.update_status(agent_id, ticker, "Analyzing sentiment")
        sentiment_analysis = analyze_sentiment(company_news)

        progress.update_status(agent_id, ticker, "Analyzing insider activity")
        insider_activity = analyze_insider_activity(insider_trades)

        progress.update_status(agent_id, ticker, "Analyzing risk-reward")
        risk_reward_analysis = analyze_risk_reward(financial_line_items, prices)

        progress.update_status(agent_id, ticker, "Performing Druckenmiller-style valuation")
        valuation_analysis = analyze_druckenmiller_valuation(financial_line_items, market_cap)

        # Combine partial scores with weights typical for Druckenmiller:
        #   35% Growth/Momentum, 20% Risk/Reward, 20% Valuation,
        #   15% Sentiment, 10% Insider Activity = 100%
        total_score = growth_momentum_analysis["score"] * 0.35 + risk_reward_analysis["score"] * 0.20 + valuation_analysis["score"] * 0.20 + sentiment_analysis["score"] * 0.15 + insider_activity["score"] * 0.10

        max_possible_score = 10

        # Simple bullish/neutral/bearish signal
        if total_score >= 7.5:
            signal = "bullish"
        elif total_score <= 4.5:
            signal = "bearish"
        else:
            signal = "neutral"

        analysis_data[ticker] = {
            "signal": signal,
            "score": total_score,
            "max_score": max_possible_score,
            "growth_momentum_analysis": growth_momentum_analysis,
            "sentiment_analysis": sentiment_analysis,
            "insider_activity": insider_activity,
            "risk_reward_analysis": risk_reward_analysis,
            "valuation_analysis": valuation_analysis,
        }

        progress.update_status(agent_id, ticker, "Generating Stanley Druckenmiller analysis")
        druck_output = generate_druckenmiller_output(
            ticker=ticker,
            analysis_data=analysis_data,
            state=state,
            agent_id=agent_id,
        )

        druck_analysis[ticker] = {
            "signal": druck_output.signal,
            "confidence": druck_output.confidence,
            "reasoning": druck_output.reasoning,
            "reasoning_cn": druck_output.reasoning_cn,
        }

        progress.update_status(agent_id, ticker, "Done", analysis=druck_output.reasoning)

    # Wrap results in a single message
    message = HumanMessage(content=json.dumps(druck_analysis), name=agent_id)

    if state["metadata"].get("show_reasoning"):
        show_agent_reasoning(druck_analysis, "Stanley Druckenmiller Agent")

    state["data"]["analyst_signals"][agent_id] = druck_analysis

    progress.update_status(agent_id, None, "Done")

    return {"messages": [message], "data": state["data"]}


def analyze_growth_and_momentum(financial_line_items: list, prices: list) -> dict:
    """
    Evaluate:
      - Revenue Growth (YoY)
      - EPS Growth (YoY)
      - Price Momentum
    """
    if not financial_line_items or len(financial_line_items) < 2:
        return {"score": 0, "details": "Insufficient financial data for growth analysis"}

    details = []
    raw_score = 0  # We'll sum up a maximum of 9 raw points, then scale to 0–10
    rev_growth = calculate_cagr_from_line_items(financial_line_items, field="revenue")
    revenue_points, revenue_details = _score_druckenmiller_growth_metric(rev_growth, "revenue", "Slight annualized revenue growth")
    raw_score += revenue_points
    details.append(revenue_details)

    eps_growth = calculate_cagr_from_line_items(financial_line_items, field="earnings_per_share")
    eps_points, eps_details = _score_druckenmiller_growth_metric(eps_growth, "EPS", "Slight annualized EPS growth")
    raw_score += eps_points
    details.append(eps_details)

    momentum_points, momentum_details = _score_druckenmiller_price_momentum(prices)
    raw_score += momentum_points
    details.append(momentum_details)

    final_score = min(10, (raw_score / 9) * 10)
    return {"score": final_score, "details": "; ".join(details)}


def analyze_insider_activity(insider_trades: list) -> dict:
    """
    Simple insider-trade analysis:
      - If there's heavy insider buying, we nudge the score up.
      - If there's mostly selling, we reduce it.
      - Otherwise, neutral.
    """
    # Default is neutral (5/10).
    score = 5
    details = []

    if not insider_trades:
        details.append("No insider trades data; defaulting to neutral")
        return {"score": score, "details": "; ".join(details)}

    buys, sells = 0, 0
    for trade in insider_trades:
        # Use transaction_shares to determine if it's a buy or sell
        # Negative shares = sell, positive shares = buy
        if trade.transaction_shares is not None:
            if trade.transaction_shares > 0:
                buys += 1
            elif trade.transaction_shares < 0:
                sells += 1

    total = buys + sells
    if total == 0:
        details.append("No buy/sell transactions found; neutral")
        return {"score": score, "details": "; ".join(details)}

    buy_ratio = buys / total
    if buy_ratio > 0.7:
        # Heavy buying => +3 points from the neutral 5 => 8
        score = 8
        details.append(f"Heavy insider buying: {buys} buys vs. {sells} sells")
    elif buy_ratio > 0.4:
        # Moderate buying => +1 => 6
        score = 6
        details.append(f"Moderate insider buying: {buys} buys vs. {sells} sells")
    else:
        # Low insider buying => -1 => 4
        score = 4
        details.append(f"Mostly insider selling: {buys} buys vs. {sells} sells")

    return {"score": score, "details": "; ".join(details)}


def analyze_sentiment(news_items: list) -> dict:
    """
    Basic news sentiment: negative keyword check vs. overall volume.
    """
    if not news_items:
        return {"score": 5, "details": "No news data; defaulting to neutral sentiment"}

    negative_keywords = ["lawsuit", "fraud", "negative", "downturn", "decline", "investigation", "recall"]
    negative_count = 0
    for news in news_items:
        title_lower = (news.title or "").lower()
        if any(word in title_lower for word in negative_keywords):
            negative_count += 1

    details = []
    if negative_count > len(news_items) * 0.3:
        # More than 30% negative => somewhat bearish => 3/10
        score = 3
        details.append(f"High proportion of negative headlines: {negative_count}/{len(news_items)}")
    elif negative_count > 0:
        # Some negativity => 6/10
        score = 6
        details.append(f"Some negative headlines: {negative_count}/{len(news_items)}")
    else:
        # Mostly positive => 8/10
        score = 8
        details.append("Mostly positive/neutral headlines")

    return {"score": score, "details": "; ".join(details)}


def analyze_risk_reward(financial_line_items: list, prices: list) -> dict:
    """
    Assesses risk via:
      - Debt-to-Equity
      - Price Volatility
    Aims for strong upside with contained downside.
    """
    if not financial_line_items or not prices:
        return {"score": 0, "details": "Insufficient data for risk-reward analysis"}

    details = []
    raw_score = 0  # We'll accumulate up to 6 raw points, then scale to 0-10
    de_ratio = _resolve_druckenmiller_de_ratio(financial_line_items)
    debt_points, debt_details = _score_druckenmiller_de_ratio(de_ratio)
    raw_score += debt_points
    details.append(debt_details)

    volatility_points, volatility_details = _score_druckenmiller_volatility(prices)
    raw_score += volatility_points
    details.append(volatility_details)

    final_score = min(10, (raw_score / 6) * 10)
    return {"score": final_score, "details": "; ".join(details)}


def analyze_druckenmiller_valuation(financial_line_items: list, market_cap: float | None) -> dict:
    """
    Druckenmiller is willing to pay up for growth, but still checks:
      - P/E
      - P/FCF
      - EV/EBIT
      - EV/EBITDA
    Each can yield up to 2 points => max 8 raw points => scale to 0–10.
    """
    if not financial_line_items or market_cap is None:
        return {"score": 0, "details": "Insufficient data to perform valuation"}

    details = []
    raw_score = 0
    valuation_inputs = _collect_druckenmiller_valuation_inputs(financial_line_items)
    enterprise_value = market_cap + valuation_inputs["recent_debt"] - valuation_inputs["recent_cash"]

    pe = calculate_pe_from_line_items(market_cap, financial_line_items)
    pe_points, pe_details = _score_druckenmiller_pe(pe)
    raw_score += pe_points
    details.append(pe_details)

    recent_fcf = valuation_inputs["fcf_values"][0] if valuation_inputs["fcf_values"] else None
    pfcf_points, pfcf_details = _score_druckenmiller_pfcf(recent_fcf, market_cap)
    raw_score += pfcf_points
    details.append(pfcf_details)

    recent_ebit = valuation_inputs["ebit_values"][0] if valuation_inputs["ebit_values"] else None
    ev_ebit_points, ev_ebit_details = _score_druckenmiller_ev_ebit(enterprise_value, recent_ebit)
    raw_score += ev_ebit_points
    details.append(ev_ebit_details)

    recent_ebitda = valuation_inputs["ebitda_values"][0] if valuation_inputs["ebitda_values"] else None
    ev_ebitda_points, ev_ebitda_details = _score_druckenmiller_ev_ebitda(enterprise_value, recent_ebitda)
    raw_score += ev_ebitda_points
    details.append(ev_ebitda_details)

    final_score = min(10, (raw_score / 8) * 10)
    return {"score": final_score, "details": "; ".join(details)}


def generate_druckenmiller_output(
    ticker: str,
    analysis_data: dict[str, any],
    state: AgentState,
    agent_id: str,
) -> StanleyDruckenmillerSignal:
    """
    Generates a JSON signal in the style of Stanley Druckenmiller.
    """
    template = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                with_fact_grounding_rules(
                    """You are a Stanley Druckenmiller AI agent, making investment decisions using his principles:
            
              1. Seek asymmetric risk-reward opportunities (large upside, limited downside).
              2. Emphasize growth, momentum, and market sentiment.
              3. Preserve capital by avoiding major drawdowns.
              4. Willing to pay higher valuations for true growth leaders.
              5. Be aggressive when conviction is high.
              6. Cut losses quickly if the thesis changes.
                            
              Rules:
              - Reward companies showing strong revenue/earnings growth and positive stock momentum.
              - Evaluate sentiment and insider activity as supportive or contradictory signals.
              - Watch out for high leverage or extreme volatility that threatens capital.
              - Output a JSON object with signal, confidence, and a reasoning string.
              
              When providing your reasoning, be thorough and specific by:
              1. Explaining the growth and momentum metrics that most influenced your decision
              2. Highlighting the risk-reward profile with specific numerical evidence
              3. Discussing market sentiment and catalysts that could drive price action
              4. Addressing both upside potential and downside risks
              5. Providing specific valuation context relative to growth prospects
              6. Using Stanley Druckenmiller's decisive, momentum-focused, and conviction-driven voice
              
              For example, if bullish: "The company shows exceptional momentum with revenue accelerating from 22% to 35% YoY and the stock up 28% over the past three months. Risk-reward is highly asymmetric with 70% upside potential based on FCF multiple expansion and only 15% downside risk given the strong balance sheet with 3x cash-to-debt. Insider buying and positive market sentiment provide additional tailwinds..."
              For example, if bearish: "Despite recent stock momentum, revenue growth has decelerated from 30% to 12% YoY, and operating margins are contracting. The risk-reward proposition is unfavorable with limited 10% upside potential against 40% downside risk. The competitive landscape is intensifying, and insider selling suggests waning confidence. I'm seeing better opportunities elsewhere with more favorable setups..."
              """
                ),
            ),
            (
                "human",
                """Based on the following analysis, create a Druckenmiller-style investment signal.

              Analysis Data for {ticker}:
              {analysis_data}

              {currency_context}

              Return the trading signal in this JSON format:
              {{
                "signal": "bullish/bearish/neutral",
                "confidence": float (0-100),
                "reasoning": "string in English",
                "reasoning_cn": "same analysis in Chinese/中文"
              }}
              """,
            ),
        ]
    )

    prompt = template.invoke({"analysis_data": json.dumps(analysis_data, indent=2), "ticker": ticker, "currency_context": get_currency_context(ticker)})

    def create_default_signal():
        return StanleyDruckenmillerSignal(
            signal="neutral",
            confidence=0.0,
            reasoning="Error in analysis, defaulting to neutral",
            reasoning_cn="分析出错，默认返回中性",
        )

    return call_llm(
        prompt=prompt,
        pydantic_model=StanleyDruckenmillerSignal,
        agent_name=agent_id,
        state=state,
        default_factory=create_default_signal,
    )
