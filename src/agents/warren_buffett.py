import json
import math

from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from typing_extensions import Literal

from src.agents.warren_buffett_helpers import (
    _analyze_buffett_earnings_consistency,
    _build_buffett_intrinsic_value_details,
    _build_buffett_owner_earnings_details,
    _calculate_buffett_dcf_components,
    _collect_buffett_capex_ratio_inputs,
    _resolve_buffett_conservative_growth,
    _resolve_buffett_dcf_assumptions,
    _resolve_buffett_maintenance_capex_methods,
    _resolve_buffett_maintenance_capex_value,
    _resolve_buffett_owner_earnings_inputs,
    _resolve_buffett_working_capital_change,
    _score_buffett_asset_efficiency,
    _score_buffett_current_ratio,
    _score_buffett_debt_to_equity,
    _score_buffett_fundamental_roe,
    _score_buffett_gross_margin_level,
    _score_buffett_gross_margin_trend,
    _score_buffett_margin_strength,
    _score_buffett_operating_margin,
    _score_buffett_performance_stability,
    _score_buffett_roe_consistency,
)
from src.graph.state import AgentState, show_agent_reasoning
from src.tools.api import get_financial_metrics, get_market_cap, search_line_items
from src.utils.api_key import get_api_key_from_state
from src.utils.llm import call_llm
from src.utils.progress import progress
from src.utils.ticker_utils import get_currency_context, get_currency_symbol


class WarrenBuffettSignal(BaseModel):
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: int = Field(description="Confidence 0-100")
    reasoning: str = Field(description="Reasoning for the decision")
    reasoning_cn: str = Field(description="Reasoning in Chinese")


def _latest_line_item_number(line_items: list, field: str) -> float | None:
    """Return the most recent finite numeric value for a given LineItem field."""
    for line_item in line_items or []:
        value = getattr(line_item, field, None)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return number
    return None


def warren_buffett_agent(state: AgentState, agent_id: str = "warren_buffett_agent"):
    """Analyzes stocks using Buffett's principles and LLM reasoning."""
    data = state["data"]
    end_date = data["end_date"]
    tickers = data["tickers"]
    api_key = get_api_key_from_state(state, "FINANCIAL_DATASETS_API_KEY")
    # Collect all analysis for LLM reasoning
    analysis_data = {}
    buffett_analysis = {}

    for ticker in tickers:
        progress.update_status(agent_id, ticker, "Fetching financial metrics")
        # Fetch required data - request more periods for better trend analysis
        metrics = get_financial_metrics(ticker, end_date, period="ttm", limit=10, api_key=api_key)

        progress.update_status(agent_id, ticker, "Gathering financial line items")
        financial_line_items = search_line_items(
            ticker,
            [
                "capital_expenditure",
                "depreciation_and_amortization",
                "net_income",
                "outstanding_shares",
                "total_assets",
                "total_liabilities",
                "shareholders_equity",
                "dividends_and_other_cash_distributions",
                "issuance_or_purchase_of_equity_shares",
                "gross_profit",
                "revenue",
                "free_cash_flow",
            ],
            end_date,
            period="annual",
            limit=10,
            api_key=api_key,
        )

        progress.update_status(agent_id, ticker, "Getting market cap")
        # Get current market cap
        market_cap = get_market_cap(ticker, end_date, api_key=api_key)

        progress.update_status(agent_id, ticker, "Analyzing fundamentals")
        # Analyze fundamentals
        fundamental_analysis = analyze_fundamentals(metrics)

        progress.update_status(agent_id, ticker, "Analyzing consistency")
        consistency_analysis = analyze_consistency(financial_line_items)

        progress.update_status(agent_id, ticker, "Analyzing competitive moat")
        moat_analysis = analyze_moat(metrics)

        progress.update_status(agent_id, ticker, "Analyzing pricing power")
        pricing_power_analysis = analyze_pricing_power(financial_line_items, metrics)

        progress.update_status(agent_id, ticker, "Analyzing book value growth")
        book_value_analysis = analyze_book_value_growth(financial_line_items)

        progress.update_status(agent_id, ticker, "Analyzing management quality")
        mgmt_analysis = analyze_management_quality(financial_line_items)

        progress.update_status(agent_id, ticker, "Calculating intrinsic value")
        intrinsic_value_analysis = calculate_intrinsic_value(financial_line_items, currency_symbol=get_currency_symbol(ticker))

        # Calculate total score without circle of competence (LLM will handle that)
        total_score = fundamental_analysis["score"] + consistency_analysis["score"] + moat_analysis["score"] + mgmt_analysis["score"] + pricing_power_analysis["score"] + book_value_analysis["score"]

        # Update max possible score calculation
        max_possible_score = 10 + moat_analysis["max_score"] + mgmt_analysis["max_score"] + 5 + 5  # fundamental_analysis (ROE, debt, margins, current ratio)  # pricing_power (0-5)  # book_value_growth (0-5)

        # Add margin of safety analysis if we have both intrinsic value and current price
        margin_of_safety = None
        intrinsic_value = intrinsic_value_analysis["intrinsic_value"]
        if intrinsic_value and market_cap:
            margin_of_safety = (intrinsic_value - market_cap) / market_cap

        # Combine all analysis results for LLM evaluation
        analysis_data[ticker] = {
            "ticker": ticker,
            "score": total_score,
            "max_score": max_possible_score,
            "fundamental_analysis": fundamental_analysis,
            "consistency_analysis": consistency_analysis,
            "moat_analysis": moat_analysis,
            "pricing_power_analysis": pricing_power_analysis,
            "book_value_analysis": book_value_analysis,
            "management_analysis": mgmt_analysis,
            "intrinsic_value_analysis": intrinsic_value_analysis,
            "market_cap": market_cap,
            "margin_of_safety": margin_of_safety,
            "financial_metrics": metrics[0].model_dump() if metrics else None,
        }

        progress.update_status(agent_id, ticker, "Generating Warren Buffett analysis")
        buffett_output = generate_buffett_output(
            ticker=ticker,
            analysis_data=analysis_data[ticker],
            state=state,
            agent_id=agent_id,
        )

        # Store analysis in consistent format with other agents
        buffett_analysis[ticker] = {
            "signal": buffett_output.signal,
            "confidence": buffett_output.confidence,
            "reasoning": buffett_output.reasoning,
            "reasoning_cn": buffett_output.reasoning_cn,
        }

        progress.update_status(agent_id, ticker, "Done", analysis=buffett_output.reasoning)

    # Create the message
    message = HumanMessage(content=json.dumps(buffett_analysis), name=agent_id)

    # Show reasoning if requested
    if state["metadata"]["show_reasoning"]:
        show_agent_reasoning(buffett_analysis, agent_id)

    # Add the signal to the analyst_signals list
    state["data"]["analyst_signals"][agent_id] = buffett_analysis

    progress.update_status(agent_id, None, "Done")

    return {"messages": [message], "data": state["data"]}


def analyze_fundamentals(metrics: list) -> dict[str, any]:
    """Analyze company fundamentals based on Buffett's criteria."""
    if not metrics:
        return {"score": 0, "details": "Insufficient fundamental data"}

    latest_metrics = metrics[0]
    roe_score, roe_reason = _score_buffett_fundamental_roe(latest_metrics)
    debt_score, debt_reason = _score_buffett_debt_to_equity(latest_metrics)
    margin_score, margin_reason = _score_buffett_operating_margin(latest_metrics)
    liquidity_score, liquidity_reason = _score_buffett_current_ratio(latest_metrics)

    return {
        "score": roe_score + debt_score + margin_score + liquidity_score,
        "details": "; ".join([roe_reason, debt_reason, margin_reason, liquidity_reason]),
        "metrics": latest_metrics.model_dump(),
    }


def analyze_consistency(financial_line_items: list) -> dict[str, any]:
    """Analyze earnings consistency and growth."""
    if len(financial_line_items) < 4:  # Need at least 4 periods for trend analysis
        return {"score": 0, "details": "Insufficient historical data"}
    score, details = _analyze_buffett_earnings_consistency(financial_line_items)
    return {"score": score, "details": details}


def analyze_moat(metrics: list) -> dict[str, any]:
    """
    Evaluate whether the company likely has a durable competitive advantage (moat).
    Enhanced to include multiple moat indicators that Buffett actually looks for:
    1. Consistent high returns on capital
    2. Pricing power (stable/growing margins)
    3. Scale advantages (improving metrics with size)
    4. Brand strength (inferred from margins and consistency)
    5. Switching costs (inferred from customer retention)
    """
    if not metrics or len(metrics) < 5:  # Need more data for proper moat analysis
        return {"score": 0, "max_score": 5, "details": "Insufficient data for comprehensive moat analysis"}

    reasoning = []
    moat_score = 0
    max_score = 5

    historical_roes = [m.return_on_equity for m in metrics if m.return_on_equity is not None]
    historical_margins = [m.operating_margin for m in metrics if m.operating_margin is not None]
    roe_score, roe_detail = _score_buffett_roe_consistency(historical_roes)
    moat_score += roe_score
    reasoning.append(roe_detail)

    margin_score, margin_detail = _score_buffett_margin_strength(historical_margins)
    moat_score += margin_score
    if margin_detail:
        reasoning.append(margin_detail)

    asset_efficiency_score, asset_efficiency_detail = _score_buffett_asset_efficiency(metrics)
    moat_score += asset_efficiency_score
    if asset_efficiency_detail:
        reasoning.append(asset_efficiency_detail)

    stability_score, stability_detail = _score_buffett_performance_stability(historical_roes, historical_margins)
    moat_score += stability_score
    if stability_detail:
        reasoning.append(stability_detail)

    moat_score = min(moat_score, max_score)

    return {
        "score": moat_score,
        "max_score": max_score,
        "details": "; ".join(reasoning) if reasoning else "Limited moat analysis available",
    }


def analyze_management_quality(financial_line_items: list) -> dict[str, any]:
    """
    Checks for share dilution or consistent buybacks, and some dividend track record.
    A simplified approach:
      - if there's net share repurchase or stable share count, it suggests management
        might be shareholder-friendly.
      - if there's a big new issuance, it might be a negative sign (dilution).
    """
    if not financial_line_items:
        return {"score": 0, "max_score": 2, "details": "Insufficient data for management analysis"}

    reasoning = []
    mgmt_score = 0

    latest = financial_line_items[0]
    if hasattr(latest, "issuance_or_purchase_of_equity_shares") and latest.issuance_or_purchase_of_equity_shares and latest.issuance_or_purchase_of_equity_shares < 0:
        # Negative means the company spent money on buybacks
        mgmt_score += 1
        reasoning.append("Company has been repurchasing shares (shareholder-friendly)")

    if hasattr(latest, "issuance_or_purchase_of_equity_shares") and latest.issuance_or_purchase_of_equity_shares and latest.issuance_or_purchase_of_equity_shares > 0:
        # Positive issuance means new shares => possible dilution
        reasoning.append("Recent common stock issuance (potential dilution)")
    else:
        reasoning.append("No significant new stock issuance detected")

    # Check for any dividends
    if hasattr(latest, "dividends_and_other_cash_distributions") and latest.dividends_and_other_cash_distributions and latest.dividends_and_other_cash_distributions < 0:
        mgmt_score += 1
        reasoning.append("Company has a track record of paying dividends")
    else:
        reasoning.append("No or minimal dividends paid")

    return {
        "score": mgmt_score,
        "max_score": 2,
        "details": "; ".join(reasoning),
    }


def calculate_owner_earnings(financial_line_items: list, currency_symbol: str = "$") -> dict[str, any]:
    """
    Calculate owner earnings (Buffett's preferred measure of true earnings power).
    Enhanced methodology: Net Income + Depreciation/Amortization - Maintenance CapEx - Working Capital Changes
    Uses multi-period analysis for better maintenance capex estimation.
    """
    if not financial_line_items or len(financial_line_items) < 2:
        return {"owner_earnings": None, "details": ["Insufficient data for owner earnings calculation"]}

    resolved_inputs, details = _resolve_buffett_owner_earnings_inputs(financial_line_items)
    if resolved_inputs is None:
        return {"owner_earnings": None, "details": details}

    net_income = resolved_inputs["net_income"]
    depreciation = resolved_inputs["depreciation"]
    capex = resolved_inputs["capex"]

    # Enhanced maintenance capex estimation using historical analysis
    maintenance_capex = estimate_maintenance_capex(financial_line_items)

    working_capital_change, working_capital_detail = _resolve_buffett_working_capital_change(financial_line_items, currency_symbol)
    if working_capital_detail:
        details.append(working_capital_detail)

    # Calculate owner earnings
    owner_earnings = net_income + depreciation - maintenance_capex - working_capital_change

    details = _build_buffett_owner_earnings_details(currency_symbol, net_income, depreciation, maintenance_capex, owner_earnings, details)

    return {
        "owner_earnings": owner_earnings,
        "components": {"net_income": net_income, "depreciation": depreciation, "maintenance_capex": maintenance_capex, "working_capital_change": working_capital_change, "total_capex": abs(capex) if capex else 0},
        "details": details,
    }


def estimate_maintenance_capex(financial_line_items: list) -> float:
    """
    Estimate maintenance capital expenditure using multiple approaches.
    Buffett considers this crucial for understanding true owner earnings.
    """
    if not financial_line_items:
        return 0

    capex_ratios = _collect_buffett_capex_ratio_inputs(financial_line_items)
    method_1, method_2, latest_revenue = _resolve_buffett_maintenance_capex_methods(financial_line_items)
    return _resolve_buffett_maintenance_capex_value(capex_ratios, method_1, method_2, latest_revenue)


def calculate_intrinsic_value(financial_line_items: list, currency_symbol: str = "$") -> dict[str, any]:
    """
    Calculate intrinsic value using enhanced DCF with owner earnings.
    Uses more sophisticated assumptions and conservative approach like Buffett.
    """
    if not financial_line_items or len(financial_line_items) < 3:
        return {"intrinsic_value": None, "details": ["Insufficient data for reliable valuation"]}

    # Calculate owner earnings with better methodology
    earnings_data = calculate_owner_earnings(financial_line_items, currency_symbol=currency_symbol)
    if not earnings_data["owner_earnings"]:
        return {"intrinsic_value": None, "details": earnings_data["details"]}

    owner_earnings = earnings_data["owner_earnings"]
    shares_outstanding = _latest_line_item_number(financial_line_items, "outstanding_shares")

    if not shares_outstanding or shares_outstanding <= 0:
        return {"intrinsic_value": None, "details": ["Missing or invalid shares outstanding data"]}

    conservative_growth = _resolve_buffett_conservative_growth(financial_line_items)
    assumptions = _resolve_buffett_dcf_assumptions(conservative_growth)
    dcf_components = _calculate_buffett_dcf_components(owner_earnings, assumptions)
    details = _build_buffett_intrinsic_value_details(currency_symbol, owner_earnings, assumptions, dcf_components)

    return {
        "intrinsic_value": dcf_components["conservative_intrinsic_value"],
        "raw_intrinsic_value": dcf_components["intrinsic_value"],
        "owner_earnings": owner_earnings,
        "assumptions": assumptions,
        "details": details,
    }


def analyze_book_value_growth(financial_line_items: list) -> dict[str, any]:
    """Analyze book value per share growth - a key Buffett metric."""
    if len(financial_line_items) < 3:
        return {"score": 0, "details": "Insufficient data for book value analysis"}

    # Extract book values per share
    book_values = []
    for item in financial_line_items:
        shareholders_equity = getattr(item, "shareholders_equity", None)
        shares_outstanding = getattr(item, "outstanding_shares", None)
        if shareholders_equity and shares_outstanding:
            book_values.append(shareholders_equity / shares_outstanding)

    if len(book_values) < 3:
        return {"score": 0, "details": "Insufficient book value data for growth analysis"}

    score = 0
    reasoning = []

    # Analyze growth consistency
    growth_periods = sum(1 for i in range(len(book_values) - 1) if book_values[i] > book_values[i + 1])
    growth_rate = growth_periods / (len(book_values) - 1)

    # Score based on consistency
    if growth_rate >= 0.8:
        score += 3
        reasoning.append("Consistent book value per share growth (Buffett's favorite metric)")
    elif growth_rate >= 0.6:
        score += 2
        reasoning.append("Good book value per share growth pattern")
    elif growth_rate >= 0.4:
        score += 1
        reasoning.append("Moderate book value per share growth")
    else:
        reasoning.append("Inconsistent book value per share growth")

    # Calculate and score CAGR
    cagr_score, cagr_reason = _calculate_book_value_cagr(book_values)
    score += cagr_score
    reasoning.append(cagr_reason)

    return {"score": score, "details": "; ".join(reasoning)}


def _calculate_book_value_cagr(book_values: list) -> tuple[int, str]:
    """Helper function to safely calculate book value CAGR and return score + reasoning."""
    if len(book_values) < 2:
        return 0, "Insufficient data for CAGR calculation"

    oldest_bv, latest_bv = book_values[-1], book_values[0]
    years = len(book_values) - 1

    # Handle different scenarios
    if oldest_bv > 0 and latest_bv > 0:
        cagr = ((latest_bv / oldest_bv) ** (1 / years)) - 1
        if cagr > 0.15:
            return 2, f"Excellent book value CAGR: {cagr:.1%}"
        elif cagr > 0.1:
            return 1, f"Good book value CAGR: {cagr:.1%}"
        else:
            return 0, f"Book value CAGR: {cagr:.1%}"
    elif oldest_bv < 0 < latest_bv:
        return 3, "Excellent: Company improved from negative to positive book value"
    elif oldest_bv > 0 > latest_bv:
        return 0, "Warning: Company declined from positive to negative book value"
    else:
        return 0, "Unable to calculate meaningful book value CAGR due to negative values"


def analyze_pricing_power(financial_line_items: list, metrics: list) -> dict[str, any]:
    """
    Analyze pricing power - Buffett's key indicator of a business moat.
    Looks at ability to raise prices without losing customers (margin expansion during inflation).
    """
    if not financial_line_items or not metrics:
        return {"score": 0, "details": "Insufficient data for pricing power analysis"}

    score = 0
    reasoning = []
    gross_margins = []
    for item in financial_line_items:
        if hasattr(item, "gross_margin") and item.gross_margin is not None:
            gross_margins.append(item.gross_margin)

    trend_score, trend_detail = _score_buffett_gross_margin_trend(gross_margins)
    score += trend_score
    if trend_detail:
        reasoning.append(trend_detail)

    level_score, level_detail = _score_buffett_gross_margin_level(gross_margins)
    score += level_score
    if level_detail:
        reasoning.append(level_detail)

    return {"score": score, "details": "; ".join(reasoning) if reasoning else "Limited pricing power analysis available"}


def generate_buffett_output(
    ticker: str,
    analysis_data: dict[str, any],
    state: AgentState,
    agent_id: str = "warren_buffett_agent",
) -> WarrenBuffettSignal:
    """Get investment decision from LLM with a compact prompt."""

    # --- Build compact facts here ---
    financial_metrics = analysis_data.get("financial_metrics") or {}
    facts = {
        "score": analysis_data.get("score"),
        "max_score": analysis_data.get("max_score"),
        "revenue_growth": financial_metrics.get("revenue_growth"),
        "earnings_growth": financial_metrics.get("earnings_growth"),
        "return_on_equity": financial_metrics.get("return_on_equity"),
        "operating_margin": financial_metrics.get("operating_margin"),
        "debt_to_equity": financial_metrics.get("debt_to_equity"),
        "current_ratio": financial_metrics.get("current_ratio"),
        "gross_margin": financial_metrics.get("gross_margin"),
        "net_margin": financial_metrics.get("net_margin"),
        "return_on_assets": financial_metrics.get("return_on_assets"),
        "fundamentals": analysis_data.get("fundamental_analysis", {}).get("details"),
        "moat": analysis_data.get("moat_analysis", {}).get("details"),
        "pricing_power": analysis_data.get("pricing_power_analysis", {}).get("details"),
        "book_value": analysis_data.get("book_value_analysis", {}).get("details"),
        "management": analysis_data.get("management_analysis", {}).get("details"),
        "intrinsic_value": analysis_data.get("intrinsic_value_analysis", {}).get("intrinsic_value"),
        "market_cap": analysis_data.get("market_cap"),
        "margin_of_safety": analysis_data.get("margin_of_safety"),
    }

    template = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are Warren Buffett. Decide bullish, bearish, or neutral using ONLY the provided facts.\n"
                "\n"
                "CRITICAL RULES (STRICTLY ENFORCED):\n"
                "1. ONLY use data explicitly provided in the Facts section\n"
                "2. NEVER invent, estimate, or make up any numbers or metrics\n"
                "3. If a data point is missing or null, state 'data not available'\n"
                "4. Do NOT reference any data not in the Facts\n"
                "\n"
                "Checklist for decision:\n"
                "- Circle of competence\n"
                "- Competitive moat\n"
                "- Management quality\n"
                "- Financial strength\n"
                "- Valuation vs intrinsic value\n"
                "- Long-term prospects\n"
                "\n"
                "Signal rules:\n"
                "- Bullish: strong business AND margin_of_safety > 0.\n"
                "- Bearish: poor business OR clearly overvalued.\n"
                "- Neutral: good business but margin_of_safety <= 0, or mixed evidence.\n"
                "\n"
                "Confidence scale:\n"
                "- 90-100%: Exceptional business within my circle, trading at attractive price\n"
                "- 70-89%: Good business with decent moat, fair valuation\n"
                "- 50-69%: Mixed signals, would need more information or better price\n"
                "- 30-49%: Outside my expertise or concerning fundamentals\n"
                "- 10-29%: Poor business or significantly overvalued\n"
                "\n"
                "Keep reasoning concise. ONLY use provided facts. Return JSON only.",
            ),
            ("human", "Ticker: {ticker}\n" "Facts:\n{facts}\n\n" "{currency_context}\n\n" "Return exactly:\n" "{{\n" '  "signal": "bullish" | "bearish" | "neutral",\n' '  "confidence": int,\n' '  "reasoning": "short justification in English",\n' '  "reasoning_cn": "same justification in Chinese/中文"\n' "}}"),
        ]
    )

    prompt = template.invoke(
        {
            "facts": json.dumps(facts, separators=(",", ":"), ensure_ascii=False),
            "ticker": ticker,
            "currency_context": get_currency_context(ticker),
        }
    )

    # Default fallback uses int confidence to match schema and avoid parse retries
    def create_default_warren_buffett_signal():
        return WarrenBuffettSignal(
            signal="neutral",
            confidence=50,
            reasoning="Insufficient data",
            reasoning_cn="数据不足",
        )

    return call_llm(
        prompt=prompt,
        pydantic_model=WarrenBuffettSignal,
        agent_name=agent_id,
        state=state,
        default_factory=create_default_warren_buffett_signal,
    )
