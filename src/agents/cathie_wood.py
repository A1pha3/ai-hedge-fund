import json

from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel
from typing import Literal

from src.agents.cathie_wood_helpers import (
    _calculate_yoy_growth_rates,
    _score_cathie_capex_commitment,
    _score_cathie_fcf_funding,
    _score_cathie_gross_margin_profile,
    _score_cathie_operating_efficiency,
    _score_cathie_operating_leverage,
    _score_cathie_rnd_trends,
    _score_cathie_revenue_disruption,
    _score_cathie_reinvestment_focus,
    _score_cathie_rnd_intensity,
)
from src.agents.prompt_rules import with_fact_grounding_rules
from src.graph.state import AgentState, show_agent_reasoning
from src.tools.api import get_financial_metrics, get_market_cap, search_line_items
from src.utils.api_key import get_api_key_from_state
from src.utils.financial_calcs import calculate_cagr_from_line_items
from src.utils.llm import call_llm
from src.utils.progress import progress
from src.utils.ticker_utils import get_currency_context

class CathieWoodSignal(BaseModel):
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: float
    reasoning: str
    reasoning_cn: str


def cathie_wood_agent(state: AgentState, agent_id: str = "cathie_wood_agent"):
    """
    Analyzes stocks using Cathie Wood's investing principles and LLM reasoning.
    1. Prioritizes companies with breakthrough technologies or business models
    2. Focuses on industries with rapid adoption curves and massive TAM (Total Addressable Market).
    3. Invests mostly in AI, robotics, genomic sequencing, fintech, and blockchain.
    4. Willing to endure short-term volatility for long-term gains.
    """
    data = state["data"]
    end_date = data["end_date"]
    tickers = data["tickers"]
    api_key = get_api_key_from_state(state, "FINANCIAL_DATASETS_API_KEY")
    analysis_data = {}
    cw_analysis = {}

    for ticker in tickers:
        progress.update_status(agent_id, ticker, "Fetching financial metrics")
        metrics = get_financial_metrics(ticker, end_date, period="annual", limit=5, api_key=api_key)

        progress.update_status(agent_id, ticker, "Gathering financial line items")
        # Request multiple periods of data (annual or TTM) for a more robust view.
        financial_line_items = search_line_items(
            ticker,
            [
                "revenue",
                "net_income",
                "gross_margin",
                "operating_margin",
                "debt_to_equity",
                "free_cash_flow",
                "total_assets",
                "total_liabilities",
                "dividends_and_other_cash_distributions",
                "outstanding_shares",
                "research_and_development",
                "capital_expenditure",
                "operating_expense",
            ],
            end_date,
            period="annual",
            limit=10,
            api_key=api_key,
        )

        progress.update_status(agent_id, ticker, "Getting market cap")
        market_cap = get_market_cap(ticker, end_date, api_key=api_key)

        progress.update_status(agent_id, ticker, "Analyzing disruptive potential")
        disruptive_analysis = analyze_disruptive_potential(metrics, financial_line_items)

        progress.update_status(agent_id, ticker, "Analyzing innovation-driven growth")
        innovation_analysis = analyze_innovation_growth(metrics, financial_line_items)

        progress.update_status(agent_id, ticker, "Calculating valuation & high-growth scenario")
        valuation_analysis = analyze_cathie_wood_valuation(financial_line_items, market_cap)

        # Combine partial scores or signals
        total_score = disruptive_analysis["score"] + innovation_analysis["score"] + valuation_analysis["score"]
        max_possible_score = 15  # Adjust weighting as desired

        if total_score >= 0.7 * max_possible_score:
            signal = "bullish"
        elif total_score <= 0.3 * max_possible_score:
            signal = "bearish"
        else:
            signal = "neutral"

        analysis_data[ticker] = {"signal": signal, "score": total_score, "max_score": max_possible_score, "disruptive_analysis": disruptive_analysis, "innovation_analysis": innovation_analysis, "valuation_analysis": valuation_analysis}

        progress.update_status(agent_id, ticker, "Generating Cathie Wood analysis")
        cw_output = generate_cathie_wood_output(
            ticker=ticker,
            analysis_data=analysis_data,
            state=state,
            agent_id=agent_id,
        )

        cw_analysis[ticker] = {
            "signal": cw_output.signal,
            "confidence": cw_output.confidence,
            "reasoning": cw_output.reasoning,
            "reasoning_cn": cw_output.reasoning_cn,
        }

        progress.update_status(agent_id, ticker, "Done", analysis=cw_output.reasoning)

    message = HumanMessage(content=json.dumps(cw_analysis), name=agent_id)

    if state["metadata"].get("show_reasoning"):
        show_agent_reasoning(cw_analysis, agent_id)

    state["data"]["analyst_signals"][agent_id] = cw_analysis

    progress.update_status(agent_id, None, "Done")

    return {"messages": [message], "data": state["data"]}


def analyze_disruptive_potential(metrics: list, financial_line_items: list) -> dict:
    """
    Analyze whether the company has disruptive products, technology, or business model.
    Evaluates multiple dimensions of disruptive potential:
    1. Revenue Growth Acceleration - indicates market adoption
    2. R&D Intensity - shows innovation investment
    3. Gross Margin Trends - suggests pricing power and scalability
    4. Operating Leverage - demonstrates business model efficiency
    5. Market Share Dynamics - indicates competitive position
    """
    score = 0
    details = []

    if not metrics or not financial_line_items:
        return {"score": 0, "details": "Insufficient data to analyze disruptive potential"}

    revenue_score, revenue_details = _score_cathie_revenue_disruption(
        financial_line_items,
        calculate_cagr_from_line_items,
        _calculate_yoy_growth_rates,
    )
    score += revenue_score
    details.extend(revenue_details)

    margin_score, margin_details = _score_cathie_gross_margin_profile(financial_line_items)
    score += margin_score
    details.extend(margin_details)

    leverage_score, leverage_detail = _score_cathie_operating_leverage(
        financial_line_items,
        calculate_cagr_from_line_items,
    )
    score += leverage_score
    if leverage_detail:
        details.append(leverage_detail)

    rnd_score, rnd_detail = _score_cathie_rnd_intensity(financial_line_items)
    score += rnd_score
    if rnd_detail:
        details.append(rnd_detail)

    # Normalize score to be out of 5
    max_possible_score = 12  # Sum of all possible points
    normalized_score = (score / max_possible_score) * 5

    return {"score": normalized_score, "details": "; ".join(details), "raw_score": score, "max_score": max_possible_score}


def analyze_innovation_growth(metrics: list, financial_line_items: list) -> dict:
    """
    Evaluate the company's commitment to innovation and potential for exponential growth.
    Analyzes multiple dimensions:
    1. R&D Investment Trends - measures commitment to innovation
    2. Free Cash Flow Generation - indicates ability to fund innovation
    3. Operating Efficiency - shows scalability of innovation
    4. Capital Allocation - reveals innovation-focused management
    5. Growth Reinvestment - demonstrates commitment to future growth
    """
    score = 0
    details = []

    if not metrics or not financial_line_items:
        return {"score": 0, "details": "Insufficient data to analyze innovation-driven growth"}

    rnd_score, rnd_details = _score_cathie_rnd_trends(financial_line_items)
    score += rnd_score
    details.extend(rnd_details)

    fcf_score, fcf_detail = _score_cathie_fcf_funding(financial_line_items)
    score += fcf_score
    if fcf_detail:
        details.append(fcf_detail)

    efficiency_score, efficiency_detail = _score_cathie_operating_efficiency(financial_line_items)
    score += efficiency_score
    if efficiency_detail:
        details.append(efficiency_detail)

    capex_score, capex_detail = _score_cathie_capex_commitment(financial_line_items)
    score += capex_score
    if capex_detail:
        details.append(capex_detail)

    reinvestment_score, reinvestment_detail = _score_cathie_reinvestment_focus(financial_line_items)
    score += reinvestment_score
    if reinvestment_detail:
        details.append(reinvestment_detail)

    # Normalize score to be out of 5
    max_possible_score = 15  # Sum of all possible points
    normalized_score = (score / max_possible_score) * 5

    return {"score": normalized_score, "details": "; ".join(details), "raw_score": score, "max_score": max_possible_score}


def analyze_cathie_wood_valuation(financial_line_items: list, market_cap: float) -> dict:
    """
    Cathie Wood often focuses on long-term exponential growth potential. We can do
    a simplified approach looking for a large total addressable market (TAM) and the
    company's ability to capture a sizable portion.
    """
    if not financial_line_items or market_cap is None:
        return {"score": 0, "details": "Insufficient data for valuation"}

    latest = financial_line_items[0]
    fcf = getattr(latest, "free_cash_flow", None)

    if fcf is None:
        # Latest period FCF not yet available — try the next available period
        for item in financial_line_items[1:]:
            fcf = getattr(item, "free_cash_flow", None)
            if fcf is not None:
                break

    if fcf is None or fcf <= 0:
        reason = "Latest FCF data not yet available" if fcf is None else f"Negative FCF ({fcf:,.0f})"
        return {"score": 0, "details": f"No positive FCF for valuation; {reason}", "intrinsic_value": None}

    # Check if company is loss-making — reduce growth assumptions accordingly
    net_income = getattr(latest, "net_income", None)
    operating_margin = getattr(latest, "operating_margin", None)
    is_loss_making = (net_income is not None and net_income < 0) or (operating_margin is not None and operating_margin < 0)

    # Quality-adjusted DCF parameters for innovative companies
    if is_loss_making:
        # Loss-making: use conservative growth, higher discount, lower terminal
        growth_rate = 0.05  # 5% (cannot assume innovation-driven growth with negative earnings)
        discount_rate = 0.20  # Higher risk for loss-making
        terminal_multiple = 8  # Conservative terminal
    else:
        # Profitable: standard Cathie Wood growth assumptions
        growth_rate = 0.20  # 20% annual growth for innovative company
        discount_rate = 0.15
        terminal_multiple = 25
    projection_years = 5

    present_value = 0
    for year in range(1, projection_years + 1):
        future_fcf = fcf * (1 + growth_rate) ** year
        pv = future_fcf / ((1 + discount_rate) ** year)
        present_value += pv

    # Terminal Value
    terminal_value = (fcf * (1 + growth_rate) ** projection_years * terminal_multiple) / ((1 + discount_rate) ** projection_years)
    intrinsic_value = present_value + terminal_value

    margin_of_safety = (intrinsic_value - market_cap) / market_cap

    score = 0
    if margin_of_safety > 0.5:
        score += 3
    elif margin_of_safety > 0.2:
        score += 1

    details = [f"Calculated intrinsic value: ~{intrinsic_value:,.2f}", f"Market cap: ~{market_cap:,.2f}", f"Margin of safety: {margin_of_safety:.2%}"]

    return {"score": score, "details": "; ".join(details), "intrinsic_value": intrinsic_value, "margin_of_safety": margin_of_safety}


def generate_cathie_wood_output(
    ticker: str,
    analysis_data: dict[str, any],
    state: AgentState,
    agent_id: str = "cathie_wood_agent",
) -> CathieWoodSignal:
    """
    Generates investment decisions in the style of Cathie Wood.
    """
    template = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                with_fact_grounding_rules(
                    """You are a Cathie Wood AI agent, making investment decisions using her principles:

            1. Seek companies leveraging disruptive innovation.
            2. Emphasize exponential growth potential, large TAM.
            3. Focus on technology, healthcare, or other future-facing sectors.
            4. Consider multi-year time horizons for potential breakthroughs.
            5. Accept higher volatility in pursuit of high returns.
            6. Evaluate management's vision and ability to invest in R&D.

            Rules:
            - Identify disruptive or breakthrough technology.
            - Evaluate strong potential for multi-year revenue growth.
            - Check if the company can scale effectively in a large market.
            - Use a growth-biased valuation approach.
            - Provide a data-driven recommendation (bullish, bearish, or neutral).
            
            When providing your reasoning, be thorough and specific by:
            1. Identifying the specific disruptive technologies/innovations the company is leveraging
            2. Highlighting growth metrics that indicate exponential potential (revenue acceleration, expanding TAM)
            3. Discussing the long-term vision and transformative potential over 5+ year horizons
            4. Explaining how the company might disrupt traditional industries or create new markets
            5. Addressing R&D investment and innovation pipeline that could drive future growth
            6. Using Cathie Wood's optimistic, future-focused, and conviction-driven voice
            
            For example, if bullish: "The company's AI-driven platform is transforming the $500B healthcare analytics market, with evidence of platform adoption accelerating from 40% to 65% YoY. Their R&D investments of 22% of revenue are creating a technological moat that positions them to capture a significant share of this expanding market. The current valuation doesn't reflect the exponential growth trajectory we expect as..."
            For example, if bearish: "While operating in the genomics space, the company lacks truly disruptive technology and is merely incrementally improving existing techniques. R&D spending at only 8% of revenue signals insufficient investment in breakthrough innovation. With revenue growth slowing from 45% to 20% YoY, there's limited evidence of the exponential adoption curve we look for in transformative companies..."
            """
                ),
            ),
            (
                "human",
                """Based on the following analysis, create a Cathie Wood-style investment signal.

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

    def create_default_cathie_wood_signal():
        return CathieWoodSignal(
            signal="neutral",
            confidence=0.0,
            reasoning="Error in analysis, defaulting to neutral",
            reasoning_cn="分析出错，默认返回中性",
        )

    return call_llm(
        prompt=prompt,
        pydantic_model=CathieWoodSignal,
        agent_name=agent_id,
        state=state,
        default_factory=create_default_cathie_wood_signal,
    )


# source: https://ark-invest.com
