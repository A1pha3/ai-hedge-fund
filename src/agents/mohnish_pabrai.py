import json

from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel
from typing_extensions import Literal

from src.graph.state import AgentState, show_agent_reasoning
from src.agents.prompt_rules import with_fact_grounding_rules
from src.tools.api import get_financial_metrics, get_market_cap, search_line_items
from src.utils.api_key import get_api_key_from_state
from src.utils.financial_calcs import calculate_cagr_from_line_items, calculate_revenue_growth_cagr
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
        progress.update_status(agent_id, ticker, "Fetching financial metrics")
        metrics = get_financial_metrics(ticker, end_date, period="annual", limit=8, api_key=api_key)

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


def _analyze_pabrai_net_cash(cash: float | None, debt: float | None, ticker: str) -> tuple[int, str | None]:
    if cash is None or debt is None:
        return 0, None

    net_cash = cash - debt
    currency_symbol = get_currency_symbol(ticker)
    if net_cash > 0:
        return 3, f"Net cash position: {currency_symbol}{net_cash:,.0f}"
    return 0, f"Net debt position: {currency_symbol}{net_cash:,.0f}"


def _analyze_pabrai_liquidity(current_assets: float | None, current_liabilities: float | None) -> tuple[int, str | None]:
    if current_assets is None or current_liabilities is None or current_liabilities <= 0:
        return 0, None

    current_ratio = current_assets / current_liabilities
    if current_ratio >= 2.0:
        return 2, f"Strong liquidity (current ratio {current_ratio:.2f})"
    if current_ratio >= 1.2:
        return 1, f"Adequate liquidity (current ratio {current_ratio:.2f})"
    return 0, f"Weak liquidity (current ratio {current_ratio:.2f})"


def _analyze_pabrai_leverage(latest: object, debt: float | None, equity: float | None) -> tuple[int, str | None]:
    dte_direct = getattr(latest, "debt_to_equity", None)
    if dte_direct is not None:
        de_ratio = dte_direct
    elif equity is not None and equity > 0 and debt is not None:
        de_ratio = debt / equity
    else:
        de_ratio = None

    if de_ratio is None:
        return 0, None
    if de_ratio < 0.3:
        return 2, f"Very low leverage (D/E {de_ratio:.2f})"
    if de_ratio < 0.7:
        return 1, f"Moderate leverage (D/E {de_ratio:.2f})"
    return 0, f"High leverage (D/E {de_ratio:.2f})"


def _analyze_pabrai_fcf_stability(financial_line_items: list) -> tuple[int, str | None]:
    fcf_values = [getattr(li, "free_cash_flow", None) for li in financial_line_items if getattr(li, "free_cash_flow", None) is not None]
    if not fcf_values or len(fcf_values) < 3:
        return 0, None

    recent_avg = sum(fcf_values[:3]) / 3
    older = sum(fcf_values[-3:]) / 3 if len(fcf_values) >= 6 else fcf_values[-1]
    if recent_avg > 0 and recent_avg >= older:
        return 2, "Positive and improving/stable FCF"
    if recent_avg > 0:
        return 1, "Positive but declining FCF"
    return 0, "Negative FCF"


def _resolve_pabrai_normalized_fcf(financial_line_items: list) -> tuple[float | None, str | None]:
    fcf_values = [getattr(li, "free_cash_flow", None) for li in financial_line_items if getattr(li, "free_cash_flow", None) is not None]
    if not fcf_values or len(fcf_values) < 3:
        return None, "Insufficient FCF history"

    normalized_fcf = sum(fcf_values[: min(5, len(fcf_values))]) / min(5, len(fcf_values))
    if normalized_fcf <= 0:
        return normalized_fcf, "Non-positive normalized FCF"
    return normalized_fcf, None


def _score_pabrai_fcf_yield(fcf_yield: float) -> tuple[int, str]:
    if fcf_yield > 0.10:
        return 4, f"Exceptional value: {fcf_yield:.1%} FCF yield"
    if fcf_yield > 0.07:
        return 3, f"Attractive value: {fcf_yield:.1%} FCF yield"
    if fcf_yield > 0.05:
        return 2, f"Reasonable value: {fcf_yield:.1%} FCF yield"
    if fcf_yield > 0.03:
        return 1, f"Borderline value: {fcf_yield:.1%} FCF yield"
    return 0, f"Expensive: {fcf_yield:.1%} FCF yield"


def _score_pabrai_capex_intensity(financial_line_items: list) -> tuple[int, str | None]:
    capex_to_revenue = []
    for item in financial_line_items:
        revenue = getattr(item, "revenue", None)
        capex = abs(getattr(item, "capital_expenditure", 0) or 0)
        if revenue and revenue > 0:
            capex_to_revenue.append(capex / revenue)

    if not capex_to_revenue:
        return 0, None

    avg_ratio = sum(capex_to_revenue) / len(capex_to_revenue)
    if avg_ratio < 0.05:
        return 2, f"Asset-light: Avg capex {avg_ratio:.1%} of revenue"
    if avg_ratio < 0.10:
        return 1, f"Moderate capex: Avg capex {avg_ratio:.1%} of revenue"
    return 0, f"Capex heavy: Avg capex {avg_ratio:.1%} of revenue"


def _score_pabrai_revenue_trajectory(financial_line_items: list) -> tuple[int, str | None]:
    if len(financial_line_items) < 3:
        return 0, None

    rev_growth = calculate_cagr_from_line_items(financial_line_items, field="revenue")
    if rev_growth is None:
        return 0, None
    if rev_growth > 0.15:
        return 2, f"Strong revenue trajectory ({rev_growth:.1%})"
    if rev_growth > 0.05:
        return 1, f"Modest revenue growth ({rev_growth:.1%})"
    return 0, None


def _score_pabrai_fcf_growth(financial_line_items: list) -> tuple[int, str | None]:
    fcfs = [getattr(li, "free_cash_flow", None) for li in financial_line_items if getattr(li, "free_cash_flow", None) is not None]
    if len(fcfs) < 3:
        return 0, None

    recent_fcf = sum(fcfs[:3]) / 3
    older_fcf = sum(fcfs[-3:]) / 3 if len(fcfs) >= 6 else fcfs[-1]
    if older_fcf == 0:
        return 0, None

    fcf_growth = (recent_fcf / older_fcf) - 1
    if fcf_growth > 0.20:
        return 3, f"Strong FCF growth ({fcf_growth:.1%})"
    if fcf_growth > 0.08:
        return 2, f"Healthy FCF growth ({fcf_growth:.1%})"
    if fcf_growth > 0:
        return 1, f"Positive FCF growth ({fcf_growth:.1%})"
    return 0, None


def _score_pabrai_doubling_yield_support(financial_line_items: list, market_cap: float) -> tuple[int, str | None]:
    valuation = analyze_pabrai_valuation(financial_line_items, market_cap)
    fcf_yield = valuation.get("fcf_yield")
    if fcf_yield is None:
        return 0, None
    if fcf_yield > 0.08:
        return 3, "High FCF yield can drive doubling via retained cash/Buybacks"
    if fcf_yield > 0.05:
        return 1, "Reasonable FCF yield supports moderate compounding"
    return 0, None


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

    net_cash_score, net_cash_detail = _analyze_pabrai_net_cash(cash, debt, ticker)
    score += net_cash_score
    if net_cash_detail:
        details.append(net_cash_detail)

    liquidity_score, liquidity_detail = _analyze_pabrai_liquidity(current_assets, current_liabilities)
    score += liquidity_score
    if liquidity_detail:
        details.append(liquidity_detail)

    leverage_score, leverage_detail = _analyze_pabrai_leverage(latest, debt, equity)
    score += leverage_score
    if leverage_detail:
        details.append(leverage_detail)

    fcf_score, fcf_detail = _analyze_pabrai_fcf_stability(financial_line_items)
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
    revenue_score, revenue_detail = _score_pabrai_revenue_trajectory(financial_line_items)
    score += revenue_score
    if revenue_detail:
        details.append(revenue_detail)

    fcf_growth_score, fcf_growth_detail = _score_pabrai_fcf_growth(financial_line_items)
    score += fcf_growth_score
    if fcf_growth_detail:
        details.append(fcf_growth_detail)

    yield_support_score, yield_support_detail = _score_pabrai_doubling_yield_support(financial_line_items, market_cap)
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
