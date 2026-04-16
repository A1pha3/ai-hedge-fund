import json

from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel
from typing import Literal

from src.agents.mohnish_pabrai_helpers import (
    _resolve_pabrai_normalized_fcf,
    _score_pabrai_capex_intensity,
    _score_pabrai_doubling_yield_support,
    _score_pabrai_fcf_growth,
    _score_pabrai_fcf_stability,
    _score_pabrai_fcf_yield,
    _score_pabrai_leverage,
    _score_pabrai_liquidity,
    _score_pabrai_net_cash,
    _score_pabrai_revenue_trajectory,
)
from src.graph.state import AgentState, show_agent_reasoning
from src.agents.prompt_rules import with_fact_grounding_rules
from src.tools.api import get_market_cap, search_line_items
from src.utils.api_key import get_api_key_from_state
from src.utils.financial_calcs import calculate_cagr_from_line_items
from src.utils.llm import call_llm
from src.utils.progress import progress
from src.utils.ticker_utils import get_currency_context, get_currency_symbol


class MohnishPabraiSignal(BaseModel):
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: float
    reasoning: str
    reasoning_cn: str


def mohnish_pabrai_agent(state: AgentState, agent_id: str = "mohnish_pabrai_agent"):
    """Evaluate stocks using Mohnish Pabrai's checklist and 'heads I win, tails I don't lose much' approach."""
    data = state["data"]
    end_date = data["end_date"]
    tickers = data["tickers"]
    api_key = get_api_key_from_state(state, "FINANCIAL_DATASETS_API_KEY")

    analysis_data: dict[str, any] = {}
    pabrai_analysis: dict[str, any] = {}

    # Pabrai focuses on: downside protection, simple business, moat via unit economics, FCF yield vs alternatives,
    # and potential for doubling in 2-3 years at low risk.
    for ticker in tickers:
        progress.update_status(agent_id, ticker, "Gathering financial line items")
        line_items = search_line_items(
            ticker,
            [
                # Profitability and cash generation
                "revenue",
                "gross_profit",
                "gross_margin",
                "operating_income",
                "operating_margin",
                "net_income",
                "free_cash_flow",
                # Balance sheet - debt and liquidity
                "total_debt",
                "cash_and_equivalents",
                "current_assets",
                "current_liabilities",
                "shareholders_equity",
                "debt_to_equity",
                # Capital intensity
                "capital_expenditure",
                "depreciation_and_amortization",
                # Shares outstanding for per-share context
                "outstanding_shares",
            ],
            end_date,
            period="annual",
            limit=8,
            api_key=api_key,
        )

        progress.update_status(agent_id, ticker, "Getting market cap")
        market_cap = get_market_cap(ticker, end_date, api_key=api_key)

        progress.update_status(agent_id, ticker, "Analyzing downside protection")
        downside = analyze_downside_protection(line_items, ticker)

        progress.update_status(agent_id, ticker, "Analyzing cash yield and valuation")
        valuation = analyze_pabrai_valuation(line_items, market_cap)

        progress.update_status(agent_id, ticker, "Assessing potential to double")
        double_potential = analyze_double_potential(line_items, market_cap)

        # Combine to an overall score in spirit of Pabrai: heavily weight downside and cash yield
        total_score = downside["score"] * 0.45 + valuation["score"] * 0.35 + double_potential["score"] * 0.20
        max_score = 10

        if total_score >= 7.5:
            signal = "bullish"
        elif total_score <= 4.0:
            signal = "bearish"
        else:
            signal = "neutral"

        # 计算 revenue growth 用于传递给 LLM (处理A股YTD累计数据)
        revenue_growth = calculate_cagr_from_line_items(line_items, field="revenue")

        analysis_data[ticker] = {
            "signal": signal,
            "score": total_score,
            "max_score": max_score,
            "downside_protection": downside,
            "valuation": valuation,
            "double_potential": double_potential,
            "market_cap": market_cap,
            "revenue_growth": revenue_growth,
        }

        progress.update_status(agent_id, ticker, "Generating Pabrai analysis")
        pabrai_output = generate_pabrai_output(
            ticker=ticker,
            analysis_data=analysis_data,
            state=state,
            agent_id=agent_id,
        )

        pabrai_analysis[ticker] = {
            "signal": pabrai_output.signal,
            "confidence": pabrai_output.confidence,
            "reasoning": pabrai_output.reasoning,
            "reasoning_cn": pabrai_output.reasoning_cn,
        }

        progress.update_status(agent_id, ticker, "Done", analysis=pabrai_output.reasoning)

    message = HumanMessage(content=json.dumps(pabrai_analysis), name=agent_id)

    if state["metadata"]["show_reasoning"]:
        show_agent_reasoning(pabrai_analysis, "Mohnish Pabrai Agent")

    progress.update_status(agent_id, None, "Done")

    state["data"]["analyst_signals"][agent_id] = pabrai_analysis

    return {"messages": [message], "data": state["data"]}


def analyze_downside_protection(financial_line_items: list, ticker: str = "") -> dict[str, any]:
    """Assess balance-sheet strength and downside resiliency (capital preservation first)."""
    if not financial_line_items:
        return {"score": 0, "details": "Insufficient data"}

    latest = financial_line_items[0]
    details: list[str] = []
    score = 0

    cash = getattr(latest, "cash_and_equivalents", None)
    debt = getattr(latest, "total_debt", None)
    current_assets = getattr(latest, "current_assets", None)
    current_liabilities = getattr(latest, "current_liabilities", None)
    equity = getattr(latest, "shareholders_equity", None)

    net_cash_score, net_cash_detail = _score_pabrai_net_cash(cash, debt, ticker, get_currency_symbol)
    score += net_cash_score
    if net_cash_detail:
        details.append(net_cash_detail)

    liquidity_score, liquidity_detail = _score_pabrai_liquidity(current_assets, current_liabilities)
    score += liquidity_score
    if liquidity_detail:
        details.append(liquidity_detail)

    leverage_score, leverage_detail = _score_pabrai_leverage(latest, debt, equity)
    score += leverage_score
    if leverage_detail:
        details.append(leverage_detail)

    fcf_score, fcf_detail = _score_pabrai_fcf_stability(financial_line_items)
    score += fcf_score
    if fcf_detail:
        details.append(fcf_detail)

    return {"score": min(10, score), "details": "; ".join(details)}


def analyze_pabrai_valuation(financial_line_items: list, market_cap: float | None) -> dict[str, any]:
    """Value via simple FCF yield and asset-light preference (keep it simple, low mistakes)."""
    if not financial_line_items or market_cap is None or market_cap <= 0:
        return {"score": 0, "details": "Insufficient data", "fcf_yield": None, "normalized_fcf": None}

    details: list[str] = []
    normalized_fcf, normalized_fcf_error = _resolve_pabrai_normalized_fcf(financial_line_items)
    if normalized_fcf_error == "Insufficient FCF history":
        return {"score": 0, "details": normalized_fcf_error, "fcf_yield": None, "normalized_fcf": None}
    if normalized_fcf_error is not None:
        return {"score": 0, "details": normalized_fcf_error, "fcf_yield": None, "normalized_fcf": normalized_fcf}

    fcf_yield = normalized_fcf / market_cap

    score, fcf_yield_detail = _score_pabrai_fcf_yield(fcf_yield)
    details.append(fcf_yield_detail)

    capex_score, capex_detail = _score_pabrai_capex_intensity(financial_line_items)
    score += capex_score
    if capex_detail is not None:
        details.append(capex_detail)

    return {"score": min(10, score), "details": "; ".join(details), "fcf_yield": fcf_yield, "normalized_fcf": normalized_fcf}


def analyze_double_potential(financial_line_items: list, market_cap: float | None) -> dict[str, any]:
    """Estimate low-risk path to double capital in ~2-3 years: runway from FCF growth + rerating."""
    if not financial_line_items or market_cap is None or market_cap <= 0:
        return {"score": 0, "details": "Insufficient data"}

    details: list[str] = []
    score = 0
    revenue_score, revenue_detail = _score_pabrai_revenue_trajectory(financial_line_items, calculate_cagr_from_line_items)
    score += revenue_score
    if revenue_detail:
        details.append(revenue_detail)

    fcf_growth_score, fcf_growth_detail = _score_pabrai_fcf_growth(financial_line_items)
    score += fcf_growth_score
    if fcf_growth_detail:
        details.append(fcf_growth_detail)

    yield_support_score, yield_support_detail = _score_pabrai_doubling_yield_support(financial_line_items, market_cap, analyze_pabrai_valuation)
    score += yield_support_score
    if yield_support_detail:
        details.append(yield_support_detail)

    return {"score": min(10, score), "details": "; ".join(details)}


def generate_pabrai_output(
    ticker: str,
    analysis_data: dict[str, any],
    state: AgentState,
    agent_id: str,
) -> MohnishPabraiSignal:
    """Generate Pabrai-style decision focusing on low risk, high uncertainty bets and cloning."""
    template = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                with_fact_grounding_rules(
                    """You are Mohnish Pabrai. Apply my value investing philosophy:

          - Heads I win; tails I don't lose much: prioritize downside protection first.
          - Buy businesses with simple, understandable models and durable moats.
          - Demand high free cash flow yields and low leverage; prefer asset-light models.
          - Look for situations where intrinsic value is rising and price is significantly lower.
          - Favor cloning great investors' ideas and checklists over novelty.
          - Seek potential to double capital in 2-3 years with low risk.
          - Avoid leverage, complexity, and fragile balance sheets.

            Provide candid, checklist-driven reasoning, with emphasis on capital preservation and expected mispricing.
            """
                ),
            ),
            (
                "human",
                """Analyze {ticker} using the provided data.

          DATA:
          {analysis_data}

          {currency_context}

          Return EXACTLY this JSON:
          {{
            "signal": "bullish" | "bearish" | "neutral",
            "confidence": float (0-100),
            "reasoning": "string with Pabrai-style analysis in English focusing on downside protection, FCF yield, and doubling potential",
            "reasoning_cn": "string with the same analysis in Chinese/中文, maintaining the same level of detail and investment insights"
          }}
          """,
            ),
        ]
    )

    prompt = template.invoke(
        {
            "analysis_data": json.dumps(analysis_data, indent=2),
            "ticker": ticker,
            "currency_context": get_currency_context(ticker),
        }
    )

    def create_default_pabrai_signal():
        return MohnishPabraiSignal(
            signal="neutral",
            confidence=0.0,
            reasoning="Error in analysis, defaulting to neutral",
            reasoning_cn="分析出错，默认返回中性",
        )

    return call_llm(
        prompt=prompt,
        state=state,
        pydantic_model=MohnishPabraiSignal,
        agent_name=agent_id,
        default_factory=create_default_pabrai_signal,
    )
