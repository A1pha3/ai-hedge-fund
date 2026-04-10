import json

from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel
from typing_extensions import Literal

from src.agents.charlie_munger_helpers import (
    _calculate_munger_intrinsic_value_range,
    _score_munger_cash_conversion,
    _score_munger_cash_generation_predictability,
    _score_munger_cash_management,
    _score_munger_capital_intensity,
    _score_munger_debt_management,
    _score_munger_fcf_trend,
    _score_munger_fcf_yield,
    _score_munger_insider_activity,
    _score_munger_intangibles,
    _score_munger_margin_predictability,
    _score_munger_margin_of_safety,
    _score_munger_operating_predictability,
    _score_munger_pricing_power,
    _score_munger_revenue_predictability,
    _score_munger_roic,
    _score_munger_share_count,
)
from src.agents.prompt_rules import with_fact_grounding_rules
from src.graph.state import AgentState, show_agent_reasoning
from src.tools.api import (
    get_company_news,
    get_financial_metrics,
    get_insider_trades,
    get_market_cap,
    search_line_items,
)
from src.utils.api_key import get_api_key_from_state
from src.utils.financial_calcs import calculate_cagr_from_line_items, calculate_revenue_growth_cagr
from src.utils.llm import call_llm
from src.utils.progress import progress
from src.utils.ticker_utils import get_currency_context


class CharlieMungerSignal(BaseModel):
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: int
    reasoning: str
    reasoning_cn: str


def charlie_munger_agent(state: AgentState, agent_id: str = "charlie_munger_agent"):
    """
    Analyzes stocks using Charlie Munger's investing principles and mental models.
    Focuses on moat strength, management quality, predictability, and valuation.
    """
    data = state["data"]
    end_date = data["end_date"]
    tickers = data["tickers"]
    api_key = get_api_key_from_state(state, "FINANCIAL_DATASETS_API_KEY")
    analysis_data = {}
    munger_analysis = {}

    for ticker in tickers:
        progress.update_status(agent_id, ticker, "Fetching financial metrics")
        metrics = get_financial_metrics(ticker, end_date, period="annual", limit=10, api_key=api_key)  # Munger looks at longer periods

        progress.update_status(agent_id, ticker, "Gathering financial line items")
        financial_line_items = search_line_items(
            ticker,
            [
                "revenue",
                "net_income",
                "operating_income",
                "return_on_invested_capital",
                "gross_margin",
                "operating_margin",
                "free_cash_flow",
                "capital_expenditure",
                "cash_and_equivalents",
                "total_liabilities",
                "shareholders_equity",
                "outstanding_shares",
                "research_and_development",
                "goodwill_and_intangible_assets",
            ],
            end_date,
            period="annual",
            limit=10,  # Munger examines long-term trends
            api_key=api_key,
        )

        progress.update_status(agent_id, ticker, "Getting market cap")
        market_cap = get_market_cap(ticker, end_date, api_key=api_key)

        progress.update_status(agent_id, ticker, "Fetching insider trades")
        # Munger values management with skin in the game
        insider_trades = get_insider_trades(
            ticker,
            end_date,
            limit=100,
            api_key=api_key,
        )

        progress.update_status(agent_id, ticker, "Fetching company news")
        # Munger avoids businesses with frequent negative press
        company_news = get_company_news(
            ticker,
            end_date,
            limit=10,
            api_key=api_key,
        )

        progress.update_status(agent_id, ticker, "Analyzing moat strength")
        moat_analysis = analyze_moat_strength(metrics, financial_line_items)

        progress.update_status(agent_id, ticker, "Analyzing management quality")
        management_analysis = analyze_management_quality(financial_line_items, insider_trades)

        progress.update_status(agent_id, ticker, "Analyzing business predictability")
        predictability_analysis = analyze_predictability(financial_line_items)

        progress.update_status(agent_id, ticker, "Calculating Munger-style valuation")
        valuation_analysis = calculate_munger_valuation(financial_line_items, market_cap)

        # Combine partial scores with Munger's weighting preferences
        # Munger weights quality and predictability higher than current valuation
        total_score = moat_analysis["score"] * 0.35 + management_analysis["score"] * 0.25 + predictability_analysis["score"] * 0.25 + valuation_analysis["score"] * 0.15

        max_possible_score = 10  # Scale to 0-10

        # Generate a simple buy/hold/sell signal
        if total_score >= 7.5:  # Munger has very high standards
            signal = "bullish"
        elif total_score <= 5.5:
            signal = "bearish"
        else:
            signal = "neutral"

        analysis_data[ticker] = {
            "signal": signal,
            "score": total_score,
            "max_score": max_possible_score,
            "moat_analysis": moat_analysis,
            "management_analysis": management_analysis,
            "predictability_analysis": predictability_analysis,
            "valuation_analysis": valuation_analysis,
            # Include some qualitative assessment from news
            "news_sentiment": analyze_news_sentiment(company_news) if company_news else "No news data available",
        }

        progress.update_status(agent_id, ticker, "Generating Charlie Munger analysis")
        munger_output = generate_munger_output(ticker=ticker, analysis_data=analysis_data[ticker], state=state, agent_id=agent_id, confidence_hint=compute_confidence(analysis_data[ticker], signal))

        munger_analysis[ticker] = {
            "signal": munger_output.signal,
            "confidence": munger_output.confidence,
            "reasoning": munger_output.reasoning,
            "reasoning_cn": munger_output.reasoning_cn,
        }

        progress.update_status(agent_id, ticker, "Done", analysis=munger_output.reasoning)

    # Wrap results in a single message for the chain
    message = HumanMessage(content=json.dumps(munger_analysis), name=agent_id)

    # Show reasoning if requested
    if state["metadata"]["show_reasoning"]:
        show_agent_reasoning(munger_analysis, "Charlie Munger Agent")

    progress.update_status(agent_id, None, "Done")

    # Add signals to the overall state
    state["data"]["analyst_signals"][agent_id] = munger_analysis

    return {"messages": [message], "data": state["data"]}


def analyze_moat_strength(metrics: list, financial_line_items: list) -> dict:
    """
    Analyze the business's competitive advantage using Munger's approach:
    - Consistent high returns on capital (ROIC)
    - Pricing power (stable/improving gross margins)
    - Low capital requirements
    - Network effects and intangible assets (R&D investments, goodwill)
    """
    score = 0
    details = []

    if not metrics or not financial_line_items:
        return {"score": 0, "details": "Insufficient data to analyze moat strength"}

    roic_score, roic_detail = _score_munger_roic(financial_line_items)
    score += roic_score
    details.append(roic_detail)

    pricing_score, pricing_detail = _score_munger_pricing_power(financial_line_items)
    score += pricing_score
    details.append(pricing_detail)

    capex_score, capex_detail = _score_munger_capital_intensity(financial_line_items)
    score += capex_score
    details.append(capex_detail)

    intangibles_score, intangibles_details = _score_munger_intangibles(financial_line_items)
    score += intangibles_score
    details.extend(intangibles_details)

    # Scale score to 0-10 range
    final_score = min(10, score * 10 / 9)  # Max possible raw score is 9

    return {"score": final_score, "details": "; ".join(details)}


def analyze_management_quality(financial_line_items: list, insider_trades: list) -> dict:
    """
    Evaluate management quality using Munger's criteria:
    - Capital allocation wisdom
    - Insider ownership and transactions
    - Cash management efficiency
    - Candor and transparency
    - Long-term focus
    """
    score = 0
    details = []

    if not financial_line_items:
        return {"score": 0, "details": "Insufficient data to analyze management quality"}

    cash_conversion_score, cash_conversion_detail, _ = _score_munger_cash_conversion(financial_line_items)
    score += cash_conversion_score
    details.append(cash_conversion_detail)

    debt_score, debt_detail, recent_de_ratio = _score_munger_debt_management(financial_line_items)
    score += debt_score
    details.append(debt_detail)

    cash_score, cash_detail, cash_to_revenue = _score_munger_cash_management(financial_line_items)
    score += cash_score
    details.append(cash_detail)

    insider_score, insider_detail, insider_buy_ratio = _score_munger_insider_activity(insider_trades)
    score += insider_score
    details.append(insider_detail)

    share_score, share_detail, share_count_trend = _score_munger_share_count(financial_line_items)
    score += share_score
    details.append(share_detail)

    # Scale score to 0-10 range
    # Maximum possible raw score would be 12 (3+3+2+2+2)
    final_score = max(0, min(10, score * 10 / 12))

    return {
        "score": final_score,
        "details": "; ".join(details),
        "insider_buy_ratio": insider_buy_ratio,
        "recent_de_ratio": recent_de_ratio,
        "cash_to_revenue": cash_to_revenue,
        "share_count_trend": share_count_trend,
    }


def analyze_predictability(financial_line_items: list) -> dict:
    """
    Assess the predictability of the business - Munger strongly prefers businesses
    whose future operations and cashflows are relatively easy to predict.
    """
    score = 0
    details = []

    if not financial_line_items or len(financial_line_items) < 5:
        return {"score": 0, "details": "Insufficient data to analyze business predictability (need 5+ years)"}

    revenue_score, revenue_detail = _score_munger_revenue_predictability(financial_line_items, calculate_cagr_from_line_items)
    score += revenue_score
    details.append(revenue_detail)

    operations_score, operations_detail = _score_munger_operating_predictability(financial_line_items)
    score += operations_score
    details.append(operations_detail)

    margin_score, margin_detail = _score_munger_margin_predictability(financial_line_items)
    score += margin_score
    details.append(margin_detail)

    cash_generation_score, cash_generation_detail = _score_munger_cash_generation_predictability(financial_line_items)
    score += cash_generation_score
    details.append(cash_generation_detail)

    # Scale score to 0-10 range
    # Maximum possible raw score would be 10 (3+3+2+2)
    final_score = min(10, score * 10 / 10)

    return {"score": final_score, "details": "; ".join(details)}


def calculate_munger_valuation(financial_line_items: list, market_cap: float) -> dict:
    """
    Calculate intrinsic value using Munger's approach:
    - Focus on owner earnings (approximated by FCF)
    - Simple multiple on normalized earnings
    - Prefer paying a fair price for a wonderful business
    """
    score = 0
    details = []

    if not financial_line_items or market_cap is None:
        return {"score": 0, "details": "Insufficient data to perform valuation"}

    # Get FCF values (Munger's preferred "owner earnings" metric)
    fcf_values = [item.free_cash_flow for item in financial_line_items if hasattr(item, "free_cash_flow") and item.free_cash_flow is not None]

    if not fcf_values or len(fcf_values) < 3:
        return {"score": 0, "details": "Insufficient free cash flow data for valuation"}

    # 1. Normalize earnings by taking average of last 3-5 years
    # (Munger prefers to normalize earnings to avoid over/under-valuation based on cyclical factors)
    normalized_fcf = sum(fcf_values[: min(5, len(fcf_values))]) / min(5, len(fcf_values))

    if normalized_fcf <= 0:
        return {"score": 0, "details": f"Negative or zero normalized FCF ({normalized_fcf}), cannot value", "intrinsic_value": None}

    # 2. Calculate FCF yield (inverse of P/FCF multiple)
    if market_cap <= 0:
        return {"score": 0, "details": f"Invalid market cap ({market_cap}), cannot value"}

    fcf_yield_score, fcf_yield_detail, fcf_yield = _score_munger_fcf_yield(normalized_fcf, market_cap)
    score += fcf_yield_score
    details.append(fcf_yield_detail)

    intrinsic_value_range = _calculate_munger_intrinsic_value_range(normalized_fcf)

    margin_score, margin_detail, margin_of_safety_vs_fair_value = _score_munger_margin_of_safety(intrinsic_value_range["reasonable"], market_cap)
    score += margin_score
    details.append(margin_detail)

    fcf_trend_score, fcf_trend_detail = _score_munger_fcf_trend(fcf_values)
    score += fcf_trend_score
    details.append(fcf_trend_detail)

    # Scale score to 0-10 range
    # Maximum possible raw score would be 10 (4+3+3)
    final_score = min(10, score * 10 / 10)

    return {
        "score": final_score,
        "details": "; ".join(details),
        "intrinsic_value_range": intrinsic_value_range,
        "fcf_yield": fcf_yield,
        "normalized_fcf": normalized_fcf,
        "margin_of_safety_vs_fair_value": margin_of_safety_vs_fair_value,
    }


def analyze_news_sentiment(news_items: list) -> str:
    """
    Simple qualitative analysis of recent news.
    Munger pays attention to significant news but doesn't overreact to short-term stories.
    """
    if not news_items or len(news_items) == 0:
        return "No news data available"

    # Just return a simple count for now - in a real implementation, this would use NLP
    return f"Qualitative review of {len(news_items)} recent news items would be needed"


def _r(x, n=3):
    try:
        return round(float(x), n)
    except Exception:
        return None


def make_munger_facts_bundle(analysis: dict[str, any]) -> dict[str, any]:
    moat = analysis.get("moat_analysis") or {}
    mgmt = analysis.get("management_analysis") or {}
    pred = analysis.get("predictability_analysis") or {}
    val = analysis.get("valuation_analysis") or {}
    ivr = val.get("intrinsic_value_range") or {}

    moat_score = _r(moat.get("score"), 2) or 0
    mgmt_score = _r(mgmt.get("score"), 2) or 0
    pred_score = _r(pred.get("score"), 2) or 0
    val_score = _r(val.get("score"), 2) or 0

    # Simple mental-model flags (booleans/ints = cheap tokens, strong guidance)
    flags = {
        "moat_strong": moat_score >= 7,
        "predictable": pred_score >= 7,
        "owner_aligned": (mgmt_score >= 7) or ((mgmt.get("insider_buy_ratio") or 0) >= 0.6),
        "low_leverage": (mgmt.get("recent_de_ratio") is not None and mgmt.get("recent_de_ratio") < 1.0),
        "sensible_cash": (mgmt.get("cash_to_revenue") is not None and 0.1 <= mgmt.get("cash_to_revenue") <= 0.25),
        "low_capex": None,  # inferred in moat score already; keep placeholder if you later expose a ratio
        "mos_positive": (val.get("mos_to_reasonable") or 0) > 0.0,
        "fcf_yield_ok": (val.get("fcf_yield") or 0) >= 0.05,
        "share_count_friendly": (mgmt.get("share_count_trend") == "decreasing"),
    }

    return {
        "pre_signal": analysis.get("signal"),
        "score": _r(analysis.get("score"), 2),
        "max_score": _r(analysis.get("max_score"), 2),
        "moat_score": moat_score,
        "mgmt_score": mgmt_score,
        "predictability_score": pred_score,
        "valuation_score": val_score,
        "fcf_yield": _r(val.get("fcf_yield"), 4),
        "normalized_fcf": _r(val.get("normalized_fcf"), 0),
        "reasonable_value": _r(ivr.get("reasonable"), 0),
        "margin_of_safety_vs_fair_value": _r(val.get("margin_of_safety_vs_fair_value"), 3),
        "insider_buy_ratio": _r(mgmt.get("insider_buy_ratio"), 2),
        "recent_de_ratio": _r(mgmt.get("recent_de_ratio"), 2),
        "cash_to_revenue": _r(mgmt.get("cash_to_revenue"), 2),
        "share_count_trend": mgmt.get("share_count_trend"),
        "flags": flags,
        # keep one-liners, very short
        "notes": {
            "moat": (moat.get("details") or "")[:120],
            "mgmt": (mgmt.get("details") or "")[:120],
            "predictability": (pred.get("details") or "")[:120],
            "valuation": (val.get("details") or "")[:120],
        },
    }


def compute_confidence(analysis: dict, signal: str) -> int:
    # Pull component scores (0..10 each in your pipeline)
    moat = float((analysis.get("moat_analysis") or {}).get("score") or 0)
    mgmt = float((analysis.get("management_analysis") or {}).get("score") or 0)
    pred = float((analysis.get("predictability_analysis") or {}).get("score") or 0)
    val = float((analysis.get("valuation_analysis") or {}).get("score") or 0)

    # Quality dominates (Munger): 0.35*moat + 0.25*mgmt + 0.25*pred (max 8.5)
    quality = 0.35 * moat + 0.25 * mgmt + 0.25 * pred  # 0..8.5
    quality_pct = 100 * (quality / 8.5) if quality > 0 else 0  # 0..100

    # Valuation bump from MOS vs “reasonable”
    mos = (analysis.get("valuation_analysis") or {}).get("margin_of_safety_vs_fair_value")
    mos = float(mos) if mos is not None else 0.0
    # Convert MOS into a bounded +/-10pp adjustment
    val_adj = max(-10.0, min(10.0, mos * 100.0 / 3.0))  # ~+/-10pp if MOS is around +/-30%

    # Base confidence: weighted toward quality, then small valuation adjustment
    base = 0.85 * quality_pct + 0.15 * (val * 10)  # val score 0..10 -> 0..100
    base = base + val_adj

    # Ensure bucket semantics by clamping into Munger buckets depending on signal
    if signal == "bullish":
        # If overvalued (mos<0), cap to mixed bucket
        upper = 100 if mos > 0 else 69
        lower = 50 if quality_pct >= 55 else 30
    elif signal == "bearish":
        # If clearly overvalued (mos< -0.05), allow very low bucket
        lower = 10 if mos < -0.05 else 30
        upper = 49
    else:  # neutral
        lower, upper = 50, 69

    conf = int(round(max(lower, min(upper, base))))
    # Keep inside global 10..100
    return max(10, min(100, conf))


def generate_munger_output(
    ticker: str,
    analysis_data: dict[str, any],
    state: AgentState,
    agent_id: str,
    confidence_hint: int,
) -> CharlieMungerSignal:
    facts_bundle = make_munger_facts_bundle(analysis_data)
    template = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                with_fact_grounding_rules(
                    "You are Charlie Munger. Decide bullish, bearish, or neutral using only the facts. "
                    "Return JSON only. Keep reasoning under 120 characters. "
                    "Use the provided confidence exactly; do not change it."
                ),
            ),
            (
                "human",
                "Ticker: {ticker}\n"
                "Facts:\n{facts}\n"
                "Confidence: {confidence}\n"
                "{currency_context}\n"
                "Return exactly:\n"
                "{{\n"  # escaped {
                '  "signal": "bullish" | "bearish" | "neutral",\n'
                f'  "confidence": {confidence_hint},\n'
                '  "reasoning": "short justification in English",\n'
                '  "reasoning_cn": "same justification in Chinese/中文"\n'
                "}}",
            ),  # escaped }
        ]
    )

    prompt = template.invoke(
        {
            "ticker": ticker,
            "facts": json.dumps(facts_bundle, separators=(",", ":"), ensure_ascii=False),
            "confidence": confidence_hint,
            "currency_context": get_currency_context(ticker),
        }
    )

    def _default():
        return CharlieMungerSignal(
            signal="neutral",
            confidence=confidence_hint,
            reasoning="Insufficient data",
            reasoning_cn="数据不足",
        )

    return call_llm(
        prompt=prompt,
        pydantic_model=CharlieMungerSignal,
        agent_name=agent_id,
        state=state,
        default_factory=_default,
    )
