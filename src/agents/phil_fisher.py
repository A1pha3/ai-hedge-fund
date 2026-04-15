import json
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel
from typing_extensions import Literal

from src.agents.phil_fisher_helpers import (
    _score_fisher_debt_to_equity,
    _score_fisher_eps_growth,
    _score_fisher_fcf_consistency,
    _score_fisher_gross_margin,
    _score_fisher_margin_volatility,
    _score_fisher_operating_margin_consistency,
    _score_fisher_revenue_growth,
    _score_fisher_rnd_intensity,
    _score_fisher_roe,
)
from src.graph.state import AgentState, show_agent_reasoning
from src.agents.prompt_rules import with_fact_grounding_rules
from src.tools.api import (
    get_company_news,
    get_insider_trades,
    get_market_cap,
    search_line_items,
)
from src.utils.api_key import get_api_key_from_state
from src.utils.financial_calcs import calculate_cagr_from_line_items, calculate_pe_from_line_items
from src.utils.llm import call_llm
from src.utils.progress import progress
from src.utils.ticker_utils import get_currency_context


class PhilFisherSignal(BaseModel):
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: float
    reasoning: str
    reasoning_cn: str


def phil_fisher_agent(state: AgentState, agent_id: str = "phil_fisher_agent"):
    """
    Analyzes stocks using Phil Fisher's investing principles:
      - Seek companies with long-term above-average growth potential
      - Emphasize quality of management and R&D
      - Look for strong margins, consistent growth, and manageable leverage
      - Combine fundamental 'scuttlebutt' style checks with basic sentiment and insider data
      - Willing to pay up for quality, but still mindful of valuation
      - Generally focuses on long-term compounding

    Returns a bullish/bearish/neutral signal with confidence and reasoning.
    """
    data = state["data"]
    end_date = data["end_date"]
    tickers = data["tickers"]
    api_key = get_api_key_from_state(state, "FINANCIAL_DATASETS_API_KEY")
    analysis_data = {}
    fisher_analysis = {}

    for ticker in tickers:
        progress.update_status(agent_id, ticker, "Gathering financial line items")
        # Include relevant line items for Phil Fisher's approach:
        #   - Growth & Quality: revenue, net_income, earnings_per_share, R&D expense
        #   - Margins & Stability: operating_income, operating_margin, gross_margin
        #   - Management Efficiency & Leverage: total_debt, shareholders_equity, free_cash_flow
        #   - Valuation: net_income, free_cash_flow (for P/E, P/FCF), ebit, ebitda
        financial_line_items = search_line_items(
            ticker,
            [
                "revenue",
                "net_income",
                "earnings_per_share",
                "free_cash_flow",
                "research_and_development",
                "operating_income",
                "operating_margin",
                "gross_margin",
                "total_debt",
                "shareholders_equity",
                "debt_to_equity",
                "cash_and_equivalents",
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

        progress.update_status(agent_id, ticker, "Analyzing growth & quality")
        growth_quality = analyze_fisher_growth_quality(financial_line_items)

        progress.update_status(agent_id, ticker, "Analyzing margins & stability")
        margins_stability = analyze_margins_stability(financial_line_items)

        progress.update_status(agent_id, ticker, "Analyzing management efficiency & leverage")
        mgmt_efficiency = analyze_management_efficiency_leverage(financial_line_items)

        progress.update_status(agent_id, ticker, "Analyzing valuation (Fisher style)")
        fisher_valuation = analyze_fisher_valuation(financial_line_items, market_cap)

        progress.update_status(agent_id, ticker, "Analyzing insider activity")
        insider_activity = analyze_insider_activity(insider_trades)

        progress.update_status(agent_id, ticker, "Analyzing sentiment")
        sentiment_analysis = analyze_sentiment(company_news)

        # Combine partial scores with weights typical for Fisher:
        #   30% Growth & Quality
        #   25% Margins & Stability
        #   20% Management Efficiency
        #   15% Valuation
        #   5% Insider Activity
        #   5% Sentiment
        total_score = growth_quality["score"] * 0.30 + margins_stability["score"] * 0.25 + mgmt_efficiency["score"] * 0.20 + fisher_valuation["score"] * 0.15 + insider_activity["score"] * 0.05 + sentiment_analysis["score"] * 0.05

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
            "growth_quality": growth_quality,
            "margins_stability": margins_stability,
            "management_efficiency": mgmt_efficiency,
            "valuation_analysis": fisher_valuation,
            "insider_activity": insider_activity,
            "sentiment_analysis": sentiment_analysis,
        }

        progress.update_status(agent_id, ticker, "Generating Phil Fisher-style analysis")
        fisher_output = generate_fisher_output(
            ticker=ticker,
            analysis_data=analysis_data,
            state=state,
            agent_id=agent_id,
        )

        fisher_analysis[ticker] = {
            "signal": fisher_output.signal,
            "confidence": fisher_output.confidence,
            "reasoning": fisher_output.reasoning,
            "reasoning_cn": fisher_output.reasoning_cn,
        }

        progress.update_status(agent_id, ticker, "Done", analysis=fisher_output.reasoning)

    # Wrap results in a single message
    message = HumanMessage(content=json.dumps(fisher_analysis), name=agent_id)

    if state["metadata"].get("show_reasoning"):
        show_agent_reasoning(fisher_analysis, "Phil Fisher Agent")

    state["data"]["analyst_signals"][agent_id] = fisher_analysis

    progress.update_status(agent_id, None, "Done")

    return {"messages": [message], "data": state["data"]}


def analyze_fisher_growth_quality(financial_line_items: list) -> dict:
    """
    Evaluate growth & quality:
      - Consistent Revenue Growth
      - Consistent EPS Growth
      - R&D as a % of Revenue (if relevant, indicative of future-oriented spending)
    """
    if not financial_line_items or len(financial_line_items) < 2:
        return {
            "score": 0,
            "details": "Insufficient financial data for growth/quality analysis",
        }

    details = []
    raw_score = 0  # up to 9 raw points => scale to 0–10

    revenue_score, revenue_detail = _score_fisher_revenue_growth(financial_line_items, calculate_cagr_from_line_items)
    raw_score += revenue_score
    details.append(revenue_detail)

    eps_score, eps_detail = _score_fisher_eps_growth(financial_line_items, calculate_cagr_from_line_items)
    raw_score += eps_score
    details.append(eps_detail)

    rnd_score, rnd_detail = _score_fisher_rnd_intensity(financial_line_items)
    raw_score += rnd_score
    details.append(rnd_detail)

    # scale raw_score (max 9) to 0–10
    final_score = min(10, (raw_score / 9) * 10)
    return {"score": final_score, "details": "; ".join(details)}


def analyze_margins_stability(financial_line_items: list) -> dict:
    """
    Looks at margin consistency (gross/operating margin) and general stability over time.
    """
    if not financial_line_items or len(financial_line_items) < 2:
        return {
            "score": 0,
            "details": "Insufficient data for margin stability analysis",
        }

    details = []
    raw_score = 0  # up to 6 => scale to 0-10

    op_margins = [getattr(fi, "operating_margin", None) for fi in financial_line_items if getattr(fi, "operating_margin", None) is not None]
    consistency_score, consistency_detail = _score_fisher_operating_margin_consistency(op_margins)
    raw_score += consistency_score
    details.append(consistency_detail)

    gross_margin_score, gross_margin_detail = _score_fisher_gross_margin(financial_line_items)
    raw_score += gross_margin_score
    details.append(gross_margin_detail)

    volatility_score, volatility_detail = _score_fisher_margin_volatility(op_margins)
    raw_score += volatility_score
    details.append(volatility_detail)

    # scale raw_score (max 6) to 0-10
    final_score = min(10, (raw_score / 6) * 10)
    return {"score": final_score, "details": "; ".join(details)}


def analyze_management_efficiency_leverage(financial_line_items: list) -> dict:
    """
    Evaluate management efficiency & leverage:
      - Return on Equity (ROE)
      - Debt-to-Equity ratio
      - Possibly check if free cash flow is consistently positive
    """
    if not financial_line_items:
        return {
            "score": 0,
            "details": "No financial data for management efficiency analysis",
        }

    details = []
    raw_score = 0  # up to 6 => scale to 0–10

    ni_values = [getattr(fi, "net_income", None) for fi in financial_line_items if getattr(fi, "net_income", None) is not None]
    eq_values = [getattr(fi, "shareholders_equity", None) for fi in financial_line_items if getattr(fi, "shareholders_equity", None) is not None]

    roe_score, roe_detail = _score_fisher_roe(ni_values, eq_values)
    raw_score += roe_score
    details.append(roe_detail)

    leverage_score, leverage_detail = _score_fisher_debt_to_equity(financial_line_items, eq_values)
    raw_score += leverage_score
    details.append(leverage_detail)

    fcf_score, fcf_detail = _score_fisher_fcf_consistency(financial_line_items)
    raw_score += fcf_score
    details.append(fcf_detail)

    final_score = min(10, (raw_score / 6) * 10)
    return {"score": final_score, "details": "; ".join(details)}


def analyze_fisher_valuation(financial_line_items: list, market_cap: float | None) -> dict:
    """
    Phil Fisher is willing to pay for quality and growth, but still checks:
      - P/E
      - P/FCF
      - (Optionally) Enterprise Value metrics, but simpler approach is typical
    We will grant up to 2 points for each of two metrics => max 4 raw => scale to 0–10.
    """
    if not financial_line_items or market_cap is None:
        return {"score": 0, "details": "Insufficient data to perform valuation"}

    details = []
    raw_score = 0

    # Gather needed data
    fcf_values = [getattr(fi, "free_cash_flow", None) for fi in financial_line_items if getattr(fi, "free_cash_flow", None) is not None]

    # 1) P/E (使用年化净利润，处理A股YTD累计数据)
    pe = calculate_pe_from_line_items(market_cap, financial_line_items)
    if pe is not None:
        pe_points = 0
        if pe < 20:
            pe_points = 2
            details.append(f"Reasonably attractive P/E: {pe:.2f}")
        elif pe < 30:
            pe_points = 1
            details.append(f"Somewhat high but possibly justifiable P/E: {pe:.2f}")
        else:
            details.append(f"Very high P/E: {pe:.2f}")
        raw_score += pe_points
    else:
        details.append("No positive net income for P/E calculation")

    # 2) P/FCF
    recent_fcf = fcf_values[0] if fcf_values else None
    if recent_fcf and recent_fcf > 0:
        pfcf = market_cap / recent_fcf
        pfcf_points = 0
        if pfcf < 20:
            pfcf_points = 2
            details.append(f"Reasonable P/FCF: {pfcf:.2f}")
        elif pfcf < 30:
            pfcf_points = 1
            details.append(f"Somewhat high P/FCF: {pfcf:.2f}")
        else:
            details.append(f"Excessively high P/FCF: {pfcf:.2f}")
        raw_score += pfcf_points
    else:
        details.append("No positive free cash flow for P/FCF calculation")

    # scale raw_score (max 4) to 0–10
    final_score = min(10, (raw_score / 4) * 10)
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
        score = 8
        details.append(f"Heavy insider buying: {buys} buys vs. {sells} sells")
    elif buy_ratio > 0.4:
        score = 6
        details.append(f"Moderate insider buying: {buys} buys vs. {sells} sells")
    else:
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
        score = 3
        details.append(f"High proportion of negative headlines: {negative_count}/{len(news_items)}")
    elif negative_count > 0:
        score = 6
        details.append(f"Some negative headlines: {negative_count}/{len(news_items)}")
    else:
        score = 8
        details.append("Mostly positive/neutral headlines")

    return {"score": score, "details": "; ".join(details)}


def generate_fisher_output(
    ticker: str,
    analysis_data: dict[str, any],
    state: AgentState,
    agent_id: str,
) -> PhilFisherSignal:
    """
    Generates a JSON signal in the style of Phil Fisher.
    """
    template = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                with_fact_grounding_rules(
                    """You are a Phil Fisher AI agent, making investment decisions using his principles:
  
              1. Emphasize long-term growth potential and quality of management.
              2. Focus on companies investing in R&D for future products/services.
              3. Look for strong profitability and consistent margins.
              4. Willing to pay more for exceptional companies but still mindful of valuation.
              5. Rely on thorough research (scuttlebutt) and thorough fundamental checks.
              
              When providing your reasoning, be thorough and specific by:
              1. Discussing the company's growth prospects in detail with specific metrics and trends
              2. Evaluating management quality and their capital allocation decisions
              3. Highlighting R&D investments and product pipeline that could drive future growth
              4. Assessing consistency of margins and profitability metrics with precise numbers
              5. Explaining competitive advantages that could sustain growth over 3-5+ years
              6. Using Phil Fisher's methodical, growth-focused, and long-term oriented voice
              
              For example, if bullish: "This company exhibits the sustained growth characteristics we seek, with revenue increasing at 18% annually over five years. Management has demonstrated exceptional foresight by allocating 15% of revenue to R&D, which has produced three promising new product lines. The consistent operating margins of 22-24% indicate pricing power and operational efficiency that should continue to..."
              
              For example, if bearish: "Despite operating in a growing industry, management has failed to translate R&D investments (only 5% of revenue) into meaningful new products. Margins have fluctuated between 10-15%, showing inconsistent operational execution. The company faces increasing competition from three larger competitors with superior distribution networks. Given these concerns about long-term growth sustainability..."
              
              You must output a JSON object with:
                - "signal": "bullish" or "bearish" or "neutral"
                - "confidence": a float between 0 and 100
                - "reasoning": a detailed explanation
              """
                ),
            ),
            (
                "human",
                """Based on the following analysis, create a Phil Fisher-style investment signal.

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
        return PhilFisherSignal(
            signal="neutral",
            confidence=0.0,
            reasoning="Error in analysis, defaulting to neutral",
            reasoning_cn="分析出错，默认返回中性",
        )

    return call_llm(
        prompt=prompt,
        pydantic_model=PhilFisherSignal,
        state=state,
        agent_name=agent_id,
        default_factory=create_default_signal,
    )
