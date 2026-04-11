import json

from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel
from typing_extensions import Literal

from src.agents.rakesh_jhunjhunwala_helpers import (
    _calculate_rakesh_projected_dcf_value,
    _resolve_rakesh_discount_profile,
    _resolve_rakesh_historical_growth,
    _resolve_rakesh_sustainable_growth,
    _score_rakesh_current_ratio,
    _score_rakesh_debt_ratio,
    _score_rakesh_eps_cagr,
    _score_rakesh_dividends,
    _score_rakesh_free_cash_flow,
    _score_rakesh_growth_consistency,
    _score_rakesh_income_cagr,
    _score_rakesh_share_issuance,
    _score_rakesh_operating_margin,
    _score_rakesh_quality_debt_factor,
    _score_rakesh_quality_growth_consistency,
    _score_rakesh_quality_roe_factor,
    _score_rakesh_revenue_cagr,
    _score_rakesh_roe,
)
from src.graph.state import AgentState, show_agent_reasoning
from src.tools.api import get_financial_metrics, get_market_cap, search_line_items
from src.utils.api_key import get_api_key_from_state
from src.utils.financial_calcs import calculate_cagr_from_line_items
from src.utils.llm import call_llm
from src.utils.progress import progress
from src.utils.ticker_utils import get_currency_context


class RakeshJhunjhunwalaSignal(BaseModel):
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: float
    reasoning: str
    reasoning_cn: str


def rakesh_jhunjhunwala_agent(state: AgentState, agent_id: str = "rakesh_jhunjhunwala_agent"):
    """Analyzes stocks using Rakesh Jhunjhunwala's principles and LLM reasoning."""
    data = state["data"]
    end_date = data["end_date"]
    tickers = data["tickers"]
    api_key = get_api_key_from_state(state, "FINANCIAL_DATASETS_API_KEY")
    # Collect all analysis for LLM reasoning
    analysis_data = {}
    jhunjhunwala_analysis = {}

    for ticker in tickers:

        # Core Data
        progress.update_status(agent_id, ticker, "Fetching financial metrics")
        metrics = get_financial_metrics(ticker, end_date, period="ttm", limit=5, api_key=api_key)

        progress.update_status(agent_id, ticker, "Fetching financial line items")
        financial_line_items = search_line_items(
            ticker,
            ["net_income", "earnings_per_share", "ebit", "operating_income", "revenue", "operating_margin", "total_assets", "total_liabilities", "current_assets", "current_liabilities", "free_cash_flow", "dividends_and_other_cash_distributions", "issuance_or_purchase_of_equity_shares"],
            end_date,
            period="annual",
            api_key=api_key,
        )

        progress.update_status(agent_id, ticker, "Getting market cap")
        market_cap = get_market_cap(ticker, end_date, api_key=api_key)

        # ─── Analyses ───────────────────────────────────────────────────────────
        progress.update_status(agent_id, ticker, "Analyzing growth")
        growth_analysis = analyze_growth(financial_line_items)

        progress.update_status(agent_id, ticker, "Analyzing profitability")
        profitability_analysis = analyze_profitability(financial_line_items)

        progress.update_status(agent_id, ticker, "Analyzing balance sheet")
        balancesheet_analysis = analyze_balance_sheet(financial_line_items)

        progress.update_status(agent_id, ticker, "Analyzing cash flow")
        cashflow_analysis = analyze_cash_flow(financial_line_items)

        progress.update_status(agent_id, ticker, "Analyzing management actions")
        management_analysis = analyze_management_actions(financial_line_items)

        progress.update_status(agent_id, ticker, "Calculating intrinsic value")
        # Calculate intrinsic value once
        intrinsic_value = calculate_intrinsic_value(financial_line_items, market_cap)

        # ─── Score & margin of safety ──────────────────────────────────────────
        total_score = growth_analysis["score"] + profitability_analysis["score"] + balancesheet_analysis["score"] + cashflow_analysis["score"] + management_analysis["score"]
        # Fixed: Correct max_score calculation based on actual scoring breakdown
        max_score = 24  # 8(prof) + 7(growth) + 4(bs) + 3(cf) + 2(mgmt) = 24

        # Calculate margin of safety
        margin_of_safety = (intrinsic_value - market_cap) / market_cap if intrinsic_value and market_cap else None

        # Jhunjhunwala's decision rules (30% minimum margin of safety for conviction)
        if margin_of_safety is not None and margin_of_safety >= 0.30:
            signal = "bullish"
        elif margin_of_safety is not None and margin_of_safety <= -0.30:
            signal = "bearish"
        else:
            # Use quality score as tie-breaker for neutral cases
            quality_score = assess_quality_metrics(financial_line_items)
            if quality_score >= 0.7 and total_score >= max_score * 0.6:
                signal = "bullish"  # High quality company at fair price
            elif quality_score <= 0.4 or total_score <= max_score * 0.3:
                signal = "bearish"  # Poor quality or fundamentals
            else:
                signal = "neutral"

        # Confidence based on margin of safety and quality
        if margin_of_safety is not None:
            confidence = min(max(abs(margin_of_safety) * 150, 20), 95)  # 20-95% range
        else:
            confidence = min(max((total_score / max_score) * 100, 10), 80)  # Based on score

        # Create comprehensive analysis summary
        intrinsic_value_analysis = analyze_rakesh_jhunjhunwala_style(financial_line_items, intrinsic_value=intrinsic_value, current_price=market_cap)

        analysis_data[ticker] = {
            "signal": signal,
            "score": total_score,
            "max_score": max_score,
            "margin_of_safety": margin_of_safety,
            "growth_analysis": growth_analysis,
            "profitability_analysis": profitability_analysis,
            "balancesheet_analysis": balancesheet_analysis,
            "cashflow_analysis": cashflow_analysis,
            "management_analysis": management_analysis,
            "intrinsic_value_analysis": intrinsic_value_analysis,
            "intrinsic_value": intrinsic_value,
            "market_cap": market_cap,
            "financial_metrics": metrics[0].model_dump() if metrics else None,
        }

        # ─── LLM: craft Jhunjhunwala‑style narrative ──────────────────────────────
        progress.update_status(agent_id, ticker, "Generating Jhunjhunwala analysis")
        jhunjhunwala_output = generate_jhunjhunwala_output(
            ticker=ticker,
            analysis_data=analysis_data[ticker],
            state=state,
            agent_id=agent_id,
        )

        jhunjhunwala_analysis[ticker] = {
            "signal": jhunjhunwala_output.signal,
            "confidence": jhunjhunwala_output.confidence,
            "reasoning": jhunjhunwala_output.reasoning,
            "reasoning_cn": jhunjhunwala_output.reasoning_cn,
        }

        progress.update_status(agent_id, ticker, "Done", analysis=jhunjhunwala_output.reasoning)

    # ─── Push message back to graph state ──────────────────────────────────────
    message = HumanMessage(content=json.dumps(jhunjhunwala_analysis), name=agent_id)

    if state["metadata"]["show_reasoning"]:
        show_agent_reasoning(jhunjhunwala_analysis, "Rakesh Jhunjhunwala Agent")

    state["data"]["analyst_signals"][agent_id] = jhunjhunwala_analysis
    progress.update_status(agent_id, None, "Done")

    return {"messages": [message], "data": state["data"]}


def analyze_profitability(financial_line_items: list) -> dict[str, any]:
    """
    Analyze profitability metrics like net income, EBIT, EPS, operating income.
    Focus on strong, consistent earnings growth and operating efficiency.
    """
    if not financial_line_items:
        return {"score": 0, "details": "No profitability data available"}

    latest = financial_line_items[0]
    score = 0
    reasoning = []
    roe_score, roe_reasoning = _score_rakesh_roe(latest)
    score += roe_score
    reasoning.append(roe_reasoning)

    margin_score, margin_reasoning = _score_rakesh_operating_margin(latest)
    score += margin_score
    reasoning.append(margin_reasoning)

    eps_score, eps_reasoning = _score_rakesh_eps_cagr(financial_line_items)
    score += eps_score
    reasoning.append(eps_reasoning)

    return {"score": score, "details": "; ".join(reasoning)}


def analyze_growth(financial_line_items: list) -> dict[str, any]:
    """
    Analyze revenue and net income growth trends using CAGR.
    Jhunjhunwala favored companies with strong, consistent compound growth.
    """
    if len(financial_line_items) < 3:
        return {"score": 0, "details": "Insufficient data for growth analysis"}

    score = 0
    reasoning = []
    revenue_cagr = calculate_cagr_from_line_items(financial_line_items, field="revenue")
    revenue_score, revenue_reasoning = _score_rakesh_revenue_cagr(revenue_cagr)
    score += revenue_score
    reasoning.append(revenue_reasoning)

    revenues = [getattr(item, "revenue", None) for item in financial_line_items if getattr(item, "revenue", None) is not None]
    income_score, income_reasoning = _score_rakesh_income_cagr(financial_line_items)
    score += income_score
    reasoning.append(income_reasoning)

    consistency_result = _score_rakesh_growth_consistency(revenues)
    if consistency_result is not None:
        consistency_score, consistency_reasoning = consistency_result
        score += consistency_score
        reasoning.append(consistency_reasoning)

    return {"score": score, "details": "; ".join(reasoning)}


def analyze_balance_sheet(financial_line_items: list) -> dict[str, any]:
    """
    Check financial strength - healthy asset/liability structure, liquidity.
    Jhunjhunwala favored companies with clean balance sheets and manageable debt.
    """
    if not financial_line_items:
        return {"score": 0, "details": "No balance sheet data"}

    latest = financial_line_items[0]
    debt_score, debt_reason = _score_rakesh_debt_ratio(latest)
    current_ratio_score, current_ratio_reason = _score_rakesh_current_ratio(latest)
    return {
        "score": debt_score + current_ratio_score,
        "details": "; ".join([debt_reason, current_ratio_reason]),
    }


def analyze_cash_flow(financial_line_items: list) -> dict[str, any]:
    """
    Evaluate free cash flow and dividend behavior.
    Jhunjhunwala appreciated companies generating strong free cash flow and rewarding shareholders.
    """
    if not financial_line_items:
        return {"score": 0, "details": "No cash flow data"}

    latest = financial_line_items[0]
    free_cash_flow_score, free_cash_flow_reason = _score_rakesh_free_cash_flow(latest)
    dividend_score, dividend_reason = _score_rakesh_dividends(latest)
    return {
        "score": free_cash_flow_score + dividend_score,
        "details": "; ".join([free_cash_flow_reason, dividend_reason]),
    }


def analyze_management_actions(financial_line_items: list) -> dict[str, any]:
    """
    Look at share issuance or buybacks to assess shareholder friendliness.
    Jhunjhunwala liked managements who buy back shares or avoid dilution.
    """
    if not financial_line_items:
        return {"score": 0, "details": "No management action data"}

    latest = financial_line_items[0]
    issuance_score, issuance_reason = _score_rakesh_share_issuance(latest)
    return {"score": issuance_score, "details": issuance_reason}


def assess_quality_metrics(financial_line_items: list) -> float:
    """
    Assess company quality based on Jhunjhunwala's criteria.
    Returns a score between 0 and 1.
    """
    if not financial_line_items:
        return 0.5  # Neutral score

    latest = financial_line_items[0]
    quality_factors = [
        _score_rakesh_quality_roe_factor(latest),
        _score_rakesh_quality_debt_factor(latest),
        _score_rakesh_quality_growth_consistency(financial_line_items),
    ]
    return sum(quality_factors) / len(quality_factors) if quality_factors else 0.5


def calculate_intrinsic_value(financial_line_items: list, market_cap: float) -> float:
    """
    Calculate intrinsic value using Rakesh Jhunjhunwala's approach:
    - Focus on earnings power and growth
    - Conservative discount rates
    - Quality premium for consistent performers
    """
    if not financial_line_items or not market_cap:
        return None

    try:
        latest = financial_line_items[0]

        # Need positive earnings as base
        if not getattr(latest, "net_income", None) or latest.net_income <= 0:
            return None

        # Get historical earnings for growth calculation
        net_incomes = [getattr(item, "net_income", None) for item in financial_line_items[:5] if getattr(item, "net_income", None) is not None and getattr(item, "net_income", None) > 0]

        if len(net_incomes) < 2:
            # Use current earnings with conservative multiple for stable companies
            return latest.net_income * 12  # Conservative P/E of 12

        historical_growth = _resolve_rakesh_historical_growth(net_incomes)
        sustainable_growth = _resolve_rakesh_sustainable_growth(historical_growth)
        quality_score = assess_quality_metrics(financial_line_items)
        discount_rate, terminal_multiple = _resolve_rakesh_discount_profile(quality_score)
        return _calculate_rakesh_projected_dcf_value(latest.net_income, sustainable_growth, discount_rate, terminal_multiple)

    except Exception:
        # Fallback to simple earnings multiple
        if getattr(latest, "net_income", None) and latest.net_income > 0:
            return latest.net_income * 15
        return None


def analyze_rakesh_jhunjhunwala_style(
    financial_line_items: list,
    owner_earnings: float = None,
    intrinsic_value: float = None,
    current_price: float = None,
) -> dict[str, any]:
    """
    Comprehensive analysis in Rakesh Jhunjhunwala's investment style.
    """
    # Run sub-analyses
    profitability = analyze_profitability(financial_line_items)
    growth = analyze_growth(financial_line_items)
    balance_sheet = analyze_balance_sheet(financial_line_items)
    cash_flow = analyze_cash_flow(financial_line_items)
    management = analyze_management_actions(financial_line_items)

    total_score = profitability["score"] + growth["score"] + balance_sheet["score"] + cash_flow["score"] + management["score"]

    details = f"Profitability: {profitability['details']}\n" f"Growth: {growth['details']}\n" f"Balance Sheet: {balance_sheet['details']}\n" f"Cash Flow: {cash_flow['details']}\n" f"Management Actions: {management['details']}"

    # Use provided intrinsic value or calculate if not provided
    if not intrinsic_value:
        intrinsic_value = calculate_intrinsic_value(financial_line_items, current_price)

    valuation_gap = None
    if intrinsic_value and current_price:
        valuation_gap = intrinsic_value - current_price

    return {
        "total_score": total_score,
        "details": details,
        "owner_earnings": owner_earnings,
        "intrinsic_value": intrinsic_value,
        "current_price": current_price,
        "valuation_gap": valuation_gap,
        "breakdown": {
            "profitability": profitability,
            "growth": growth,
            "balance_sheet": balance_sheet,
            "cash_flow": cash_flow,
            "management": management,
        },
    }


# ────────────────────────────────────────────────────────────────────────────────
# LLM generation
# ────────────────────────────────────────────────────────────────────────────────
def generate_jhunjhunwala_output(
    ticker: str,
    analysis_data: dict[str, any],
    state: AgentState,
    agent_id: str,
) -> RakeshJhunjhunwalaSignal:
    """Get investment decision from LLM with Jhunjhunwala's principles"""

    # Add explicit financial metrics to the data
    financial_metrics = analysis_data.get("financial_metrics") or {}
    enhanced_data = {
        **analysis_data,
        "revenue_growth": financial_metrics.get("revenue_growth"),
        "earnings_growth": financial_metrics.get("earnings_growth"),
        "return_on_equity": financial_metrics.get("return_on_equity"),
        "operating_margin": financial_metrics.get("operating_margin"),
        "debt_to_equity": financial_metrics.get("debt_to_equity"),
        "current_ratio": financial_metrics.get("current_ratio"),
        "gross_margin": financial_metrics.get("gross_margin"),
        "net_margin": financial_metrics.get("net_margin"),
        "return_on_assets": financial_metrics.get("return_on_assets"),
    }

    # 移除可能包含误导性增长率的字段
    enhanced_data.pop("growth_analysis", None)
    enhanced_data.pop("profitability_analysis", None)
    enhanced_data.pop("intrinsic_value_analysis", None)

    template = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """You are a Rakesh Jhunjhunwala AI agent. Decide on investment signals based on Rakesh Jhunjhunwala's principles:
                - Circle of Competence: Only invest in businesses you understand
                - Margin of Safety (> 30%): Buy at a significant discount to intrinsic value
                - Economic Moat: Look for durable competitive advantages
                - Quality Management: Seek conservative, shareholder-oriented teams
                - Financial Strength: Favor low debt, strong returns on equity
                - Long-term Horizon: Invest in businesses, not just stocks
                - Growth Focus: Look for companies with consistent earnings and revenue growth
                - Sell only if fundamentals deteriorate or valuation far exceeds intrinsic value

                CRITICAL RULES (STRICTLY ENFORCED):
                1. ONLY use data explicitly provided in the Analysis Data section
                2. NEVER invent, estimate, or make up any numbers or metrics
                3. If a data point is missing or null, state 'data not available'
                4. Do NOT reference any data not in the Analysis Data

                When providing your reasoning, be thorough and specific by:
                1. Explaining the key factors that influenced your decision the most (both positive and negative)
                2. Highlighting how the company aligns with or violates specific Jhunjhunwala principles
                3. Providing quantitative evidence ONLY from the provided data (e.g., specific margins, ROE values, debt levels)
                4. Concluding with a Jhunjhunwala-style assessment of the investment opportunity
                5. Using Rakesh Jhunjhunwala's voice and conversational style in your explanation

                For example, if bullish: "I'm particularly impressed with the consistent growth and strong balance sheet, reminiscent of quality companies that create long-term wealth..."
                For example, if bearish: "The deteriorating margins and high debt levels concern me - this doesn't fit the profile of companies that build lasting value..."

                Follow these guidelines strictly.
                """,
            ),
            (
                "human",
                """Based on the following data, create the investment signal as Rakesh Jhunjhunwala would:

                Analysis Data for {ticker}:
                {analysis_data}

                {currency_context}

                Return the trading signal in the following JSON format exactly:
                {{
                  "signal": "bullish" | "bearish" | "neutral",
                  "confidence": float between 0 and 100,
                  "reasoning": "string in English",
                  "reasoning_cn": "same analysis in Chinese/中文"
                }}
                """,
            ),
        ]
    )

    prompt = template.invoke({"analysis_data": json.dumps(enhanced_data, indent=2), "ticker": ticker, "currency_context": get_currency_context(ticker)})

    # Default fallback signal in case parsing fails
    def create_default_rakesh_jhunjhunwala_signal():
        return RakeshJhunjhunwalaSignal(
            signal="neutral",
            confidence=0.0,
            reasoning="Error in analysis, defaulting to neutral",
            reasoning_cn="分析出错，默认返回中性",
        )

    return call_llm(
        prompt=prompt,
        pydantic_model=RakeshJhunjhunwalaSignal,
        state=state,
        agent_name=agent_id,
        default_factory=create_default_rakesh_jhunjhunwala_signal,
    )
