import json

from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel
from typing_extensions import Literal

from src.agents.peter_lynch_helpers import (
    _describe_lynch_pe_and_growth,
    _score_lynch_debt_profile,
    _score_lynch_eps_growth,
    _score_lynch_free_cash_flow,
    _score_lynch_operating_margin,
    _score_lynch_pe_and_peg,
    _score_lynch_revenue_growth,
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
from src.utils.financial_calcs import (
    calculate_cagr_from_line_items,
    calculate_pe_from_line_items,
)
from src.utils.llm import call_llm
from src.utils.progress import progress
from src.utils.ticker_utils import get_currency_context


class PeterLynchSignal(BaseModel):
    """
    Container for the Peter Lynch-style output signal.
    """

    signal: Literal["bullish", "bearish", "neutral"]
    confidence: float
    reasoning: str
    reasoning_cn: str


def peter_lynch_agent(state: AgentState, agent_id: str = "peter_lynch_agent"):
    """
    Analyzes stocks using Peter Lynch's investing principles:
      - Invest in what you know (clear, understandable businesses).
      - Growth at a Reasonable Price (GARP), emphasizing the PEG ratio.
      - Look for consistent revenue & EPS increases and manageable debt.
      - Be alert for potential "ten-baggers" (high-growth opportunities).
      - Avoid overly complex or highly leveraged businesses.
      - Use news sentiment and insider trades for secondary inputs.
      - If fundamentals strongly align with GARP, be more aggressive.

    The result is a bullish/bearish/neutral signal, along with a
    confidence (0–100) and a textual reasoning explanation.
    """

    data = state["data"]
    end_date = data["end_date"]
    tickers = data["tickers"]
    api_key = get_api_key_from_state(state, "FINANCIAL_DATASETS_API_KEY")
    analysis_data = {}
    lynch_analysis = {}

    for ticker in tickers:
        progress.update_status(agent_id, ticker, "Gathering financial line items")
        # Relevant line items for Peter Lynch's approach
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

        # Perform sub-analyses:
        progress.update_status(agent_id, ticker, "Analyzing growth")
        growth_analysis = analyze_lynch_growth(financial_line_items)

        progress.update_status(agent_id, ticker, "Analyzing fundamentals")
        fundamentals_analysis = analyze_lynch_fundamentals(financial_line_items)

        progress.update_status(agent_id, ticker, "Analyzing valuation (focus on PEG)")
        valuation_analysis = analyze_lynch_valuation(financial_line_items, market_cap)

        progress.update_status(agent_id, ticker, "Analyzing sentiment")
        sentiment_analysis = analyze_sentiment(company_news)

        progress.update_status(agent_id, ticker, "Analyzing insider activity")
        insider_activity = analyze_insider_activity(insider_trades)

        # Combine partial scores with weights typical for Peter Lynch:
        #   30% Growth, 25% Valuation, 20% Fundamentals,
        #   15% Sentiment, 10% Insider Activity = 100%
        total_score = growth_analysis["score"] * 0.30 + valuation_analysis["score"] * 0.25 + fundamentals_analysis["score"] * 0.20 + sentiment_analysis["score"] * 0.15 + insider_activity["score"] * 0.10

        max_possible_score = 10.0

        # Map final score to signal
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
            "growth_analysis": growth_analysis,
            "valuation_analysis": valuation_analysis,
            "fundamentals_analysis": fundamentals_analysis,
            "sentiment_analysis": sentiment_analysis,
            "insider_activity": insider_activity,
        }

        progress.update_status(agent_id, ticker, "Generating Peter Lynch analysis")
        lynch_output = generate_lynch_output(
            ticker=ticker,
            analysis_data=analysis_data[ticker],
            state=state,
            agent_id=agent_id,
        )

        lynch_analysis[ticker] = {
            "signal": lynch_output.signal,
            "confidence": lynch_output.confidence,
            "reasoning": lynch_output.reasoning,
            "reasoning_cn": lynch_output.reasoning_cn,
        }

        progress.update_status(agent_id, ticker, "Done", analysis=lynch_output.reasoning)

    # Wrap up results
    message = HumanMessage(content=json.dumps(lynch_analysis), name=agent_id)

    if state["metadata"].get("show_reasoning"):
        show_agent_reasoning(lynch_analysis, "Peter Lynch Agent")

    # Save signals to state
    state["data"]["analyst_signals"][agent_id] = lynch_analysis

    progress.update_status(agent_id, None, "Done")

    return {"messages": [message], "data": state["data"]}


def analyze_lynch_growth(financial_line_items: list) -> dict:
    """
    Evaluate growth based on revenue and EPS trends:
      - Consistent revenue growth
      - Consistent EPS growth
    Peter Lynch liked companies with steady, understandable growth,
    often searching for potential 'ten-baggers' with a long runway.
    """
    if not financial_line_items or len(financial_line_items) < 2:
        return {"score": 0, "details": "Insufficient financial data for growth analysis"}

    details = []
    raw_score = 0  # We'll sum up points, then scale to 0–10 eventually

    revenue_score, revenue_detail = _score_lynch_revenue_growth(financial_line_items, calculate_cagr_from_line_items)
    raw_score += revenue_score
    details.append(revenue_detail)

    eps_score, eps_detail = _score_lynch_eps_growth(financial_line_items, calculate_cagr_from_line_items)
    raw_score += eps_score
    details.append(eps_detail)

    # raw_score can be up to 6 => scale to 0–10
    final_score = min(10, (raw_score / 6) * 10)
    return {"score": final_score, "details": "; ".join(details)}

def analyze_lynch_fundamentals(financial_line_items: list) -> dict:
    """
    Evaluate basic fundamentals:
      - Debt/Equity
      - Operating margin (or gross margin)
      - Positive Free Cash Flow
    Lynch avoided heavily indebted or complicated businesses.
    """
    if not financial_line_items:
        return {"score": 0, "details": "Insufficient fundamentals data"}

    details = []
    raw_score = 0  # We'll accumulate up to 6 points, then scale to 0–10

    debt_score, debt_detail = _score_lynch_debt_profile(financial_line_items)
    raw_score += debt_score
    details.append(debt_detail)

    margin_score, margin_detail = _score_lynch_operating_margin(financial_line_items)
    raw_score += margin_score
    details.append(margin_detail)

    fcf_score, fcf_detail = _score_lynch_free_cash_flow(financial_line_items)
    raw_score += fcf_score
    details.append(fcf_detail)

    # raw_score up to 6 => scale to 0–10
    final_score = min(10, (raw_score / 6) * 10)
    return {"score": final_score, "details": "; ".join(details)}


def analyze_lynch_valuation(financial_line_items: list, market_cap: float | None) -> dict:
    """
    Peter Lynch's approach to 'Growth at a Reasonable Price' (GARP):
      - Emphasize the PEG ratio: (P/E) / Growth Rate
      - Also consider a basic P/E if PEG is unavailable
    A PEG < 1 is very attractive; 1-2 is fair; >2 is expensive.
    """
    if not financial_line_items or market_cap is None:
        return {"score": 0, "details": "Insufficient data for valuation"}

    pe_ratio, eps_growth_rate, details = _describe_lynch_pe_and_growth(
        financial_line_items,
        market_cap,
        calculate_pe_from_line_items,
        calculate_cagr_from_line_items,
    )
    raw_score, _, peg_details = _score_lynch_pe_and_peg(pe_ratio, eps_growth_rate)
    details.extend(peg_details)

    final_score = min(10, (raw_score / 5) * 10)
    return {"score": final_score, "details": "; ".join(details)}


def analyze_sentiment(news_items: list) -> dict:
    """
    Basic news sentiment check. Negative headlines weigh on the final score.
    """
    if not news_items:
        return {"score": 5, "details": "No news data; default to neutral sentiment"}

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
        details.append("Mostly positive or neutral headlines")

    return {"score": score, "details": "; ".join(details)}


def analyze_insider_activity(insider_trades: list) -> dict:
    """
    Simple insider-trade analysis:
      - If there's heavy insider buying, it's a positive sign.
      - If there's mostly selling, it's a negative sign.
      - Otherwise, neutral.
    """
    # Default 5 (neutral)
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
        details.append("No significant buy/sell transactions found; neutral stance")
        return {"score": score, "details": "; ".join(details)}

    buy_ratio = buys / total
    if buy_ratio > 0.7:
        # Heavy buying => +3 => total 8
        score = 8
        details.append(f"Heavy insider buying: {buys} buys vs. {sells} sells")
    elif buy_ratio > 0.4:
        # Some buying => +1 => total 6
        score = 6
        details.append(f"Moderate insider buying: {buys} buys vs. {sells} sells")
    else:
        # Mostly selling => -1 => total 4
        score = 4
        details.append(f"Mostly insider selling: {buys} buys vs. {sells} sells")

    return {"score": score, "details": "; ".join(details)}


def generate_lynch_output(
    ticker: str,
    analysis_data: dict[str, any],
    state: AgentState,
    agent_id: str,
) -> PeterLynchSignal:
    """
    Generates a final JSON signal in Peter Lynch's voice & style.
    """
    template = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                with_fact_grounding_rules(
                    """You are a Peter Lynch AI agent. You make investment decisions based on Peter Lynch's well-known principles:
                
                1. Invest in What You Know: Emphasize understandable businesses, possibly discovered in everyday life.
                2. Growth at a Reasonable Price (GARP): Rely on the PEG ratio as a prime metric.
                3. Look for 'Ten-Baggers': Companies capable of growing earnings and share price substantially.
                4. Steady Growth: Prefer consistent revenue/earnings expansion, less concern about short-term noise.
                5. Avoid High Debt: Watch for dangerous leverage.
                6. Management & Story: A good 'story' behind the stock, but not overhyped or too complex.
                
                When you provide your reasoning, do it in Peter Lynch's voice:
                - Cite the PEG ratio
                - Mention 'ten-bagger' potential if applicable
                - Refer to personal or anecdotal observations (e.g., "If my kids love the product...")
                - Use practical, folksy language
                - Provide key positives and negatives
                - Conclude with a clear stance (bullish, bearish, or neutral)
                
                Return your final output strictly in JSON with the fields:
                {{
                  "signal": "bullish" | "bearish" | "neutral",
                  "confidence": 0 to 100,
                  "reasoning": "string in English",
                  "reasoning_cn": "same analysis in Chinese/中文"
                }}
                """
                ),
            ),
            (
                "human",
                """Based on the following analysis data for {ticker}, produce your Peter Lynch–style investment signal.

                Analysis Data:
                {analysis_data}

                {currency_context}

                Return only valid JSON with "signal", "confidence", and "reasoning".
                """,
            ),
        ]
    )

    prompt = template.invoke({"analysis_data": json.dumps(analysis_data, indent=2), "ticker": ticker, "currency_context": get_currency_context(ticker)})

    def create_default_signal():
        return PeterLynchSignal(
            signal="neutral",
            confidence=0.0,
            reasoning="Error in analysis; defaulting to neutral",
            reasoning_cn="分析出错，默认返回中性",
        )

    return call_llm(
        prompt=prompt,
        pydantic_model=PeterLynchSignal,
        agent_name=agent_id,
        state=state,
        default_factory=create_default_signal,
    )
