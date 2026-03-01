import json

from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel
from typing_extensions import Literal

from src.graph.state import AgentState, show_agent_reasoning
from src.tools.api import get_financial_metrics, get_market_cap, search_line_items
from src.utils.api_key import get_api_key_from_state
from src.utils.financial_calcs import calculate_cagr_from_line_items, calculate_revenue_growth_cagr
from src.utils.llm import call_llm
from src.utils.progress import progress
from src.utils.ticker_utils import get_currency_context


class BillAckmanSignal(BaseModel):
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: float
    reasoning: str
    reasoning_cn: str


def bill_ackman_agent(state: AgentState, agent_id: str = "bill_ackman_agent"):
    """
    Analyzes stocks using Bill Ackman's investing principles and LLM reasoning.
    Fetches multiple periods of data for a more robust long-term view.
    Incorporates brand/competitive advantage, activism potential, and other key factors.
    """
    data = state["data"]
    end_date = data["end_date"]
    tickers = data["tickers"]
    api_key = get_api_key_from_state(state, "FINANCIAL_DATASETS_API_KEY")
    analysis_data = {}
    ackman_analysis = {}

    for ticker in tickers:
        progress.update_status(agent_id, ticker, "Fetching financial metrics")
        metrics = get_financial_metrics(ticker, end_date, period="annual", limit=5, api_key=api_key)

        progress.update_status(agent_id, ticker, "Gathering financial line items")
        # Request multiple periods of data (annual or TTM) for a more robust long-term view.
        financial_line_items = search_line_items(
            ticker,
            [
                "revenue",
                "operating_margin",
                "debt_to_equity",
                "free_cash_flow",
                "total_assets",
                "total_liabilities",
                "dividends_and_other_cash_distributions",
                "outstanding_shares",
                # Optional: intangible_assets if available
                # "intangible_assets"
            ],
            end_date,
            period="annual",
            limit=10,
            api_key=api_key,
        )

        progress.update_status(agent_id, ticker, "Getting market cap")
        market_cap = get_market_cap(ticker, end_date, api_key=api_key)

        progress.update_status(agent_id, ticker, "Analyzing business quality")
        quality_analysis = analyze_business_quality(metrics, financial_line_items)

        progress.update_status(agent_id, ticker, "Analyzing balance sheet and capital structure")
        balance_sheet_analysis = analyze_financial_discipline(metrics, financial_line_items)

        progress.update_status(agent_id, ticker, "Analyzing activism potential")
        activism_analysis = analyze_activism_potential(financial_line_items)

        progress.update_status(agent_id, ticker, "Calculating intrinsic value & margin of safety")
        valuation_analysis = analyze_valuation(financial_line_items, market_cap)

        # Combine partial scores or signals
        total_score = quality_analysis["score"] + balance_sheet_analysis["score"] + activism_analysis["score"] + valuation_analysis["score"]
        max_possible_score = 20  # Adjust weighting as desired (5 from each sub-analysis, for instance)

        # Generate a simple buy/hold/sell (bullish/neutral/bearish) signal
        if total_score >= 0.7 * max_possible_score:
            signal = "bullish"
        elif total_score <= 0.3 * max_possible_score:
            signal = "bearish"
        else:
            signal = "neutral"

        analysis_data[ticker] = {"signal": signal, "score": total_score, "max_score": max_possible_score, "quality_analysis": quality_analysis, "balance_sheet_analysis": balance_sheet_analysis, "activism_analysis": activism_analysis, "valuation_analysis": valuation_analysis}

        progress.update_status(agent_id, ticker, "Generating Bill Ackman analysis")
        ackman_output = generate_ackman_output(
            ticker=ticker,
            analysis_data=analysis_data,
            state=state,
            agent_id=agent_id,
        )

        ackman_analysis[ticker] = {
            "signal": ackman_output.signal,
            "confidence": ackman_output.confidence,
            "reasoning": ackman_output.reasoning,
            "reasoning_cn": ackman_output.reasoning_cn,
        }

        progress.update_status(agent_id, ticker, "Done", analysis=ackman_output.reasoning)

    # Wrap results in a single message for the chain
    message = HumanMessage(content=json.dumps(ackman_analysis), name=agent_id)

    # Show reasoning if requested
    if state["metadata"]["show_reasoning"]:
        show_agent_reasoning(ackman_analysis, "Bill Ackman Agent")

    # Add signals to the overall state
    state["data"]["analyst_signals"][agent_id] = ackman_analysis

    progress.update_status(agent_id, None, "Done")

    return {"messages": [message], "data": state["data"]}


def analyze_business_quality(metrics: list, financial_line_items: list) -> dict:
    """
    Analyze whether the company has a high-quality business with stable or growing cash flows,
    durable competitive advantages (moats), and potential for long-term growth.
    Also tries to infer brand strength if intangible_assets data is present (optional).
    """
    score = 0
    details = []

    if not metrics or not financial_line_items:
        return {"score": 0, "details": "Insufficient data to analyze business quality"}

    # 1. Multi-period revenue growth analysis - 使用统一的 CAGR 计算方法(处理A股YTD累计数据)
    growth_rate = calculate_cagr_from_line_items(financial_line_items, field="revenue")
    if growth_rate is not None:
        if growth_rate > 0.15:  # 15% CAGR is strong
            score += 2
            details.append(f"Revenue CAGR of {growth_rate:.1%} over the period (strong growth).")
        elif growth_rate > 0.05:  # 5% CAGR is moderate
            score += 1
            details.append(f"Revenue CAGR of {growth_rate:.1%} (moderate growth).")
        else:
            details.append(f"Revenue CAGR of {growth_rate:.1%} (weak growth).")
    else:
        details.append("Insufficient revenue data for CAGR calculation.")

    # 2. Operating margin and free cash flow consistency
    fcf_vals = [getattr(item, "free_cash_flow", None) for item in financial_line_items if getattr(item, "free_cash_flow", None) is not None]
    op_margin_vals = [getattr(item, "operating_margin", None) for item in financial_line_items if getattr(item, "operating_margin", None) is not None]

    if op_margin_vals:
        above_15 = sum(1 for m in op_margin_vals if m > 0.15)
        if above_15 >= (len(op_margin_vals) // 2 + 1):
            score += 2
            details.append("Operating margins have often exceeded 15% (indicates good profitability).")
        else:
            details.append("Operating margin not consistently above 15%.")
    else:
        details.append("No operating margin data across periods.")

    if fcf_vals:
        positive_fcf_count = sum(1 for f in fcf_vals if f > 0)
        if positive_fcf_count >= (len(fcf_vals) // 2 + 1):
            score += 1
            details.append("Majority of periods show positive free cash flow.")
        else:
            details.append("Free cash flow not consistently positive.")
    else:
        details.append("No free cash flow data across periods.")

    # 3. Return on Equity (ROE) check from the latest metrics
    latest_metrics = metrics[0]
    if latest_metrics.return_on_equity and latest_metrics.return_on_equity > 0.15:
        score += 2
        details.append(f"High ROE of {latest_metrics.return_on_equity:.1%}, indicating a competitive advantage.")
    elif latest_metrics.return_on_equity:
        details.append(f"ROE of {latest_metrics.return_on_equity:.1%} is moderate.")
    else:
        details.append("ROE data not available.")

    # 4. (Optional) Brand Intangible (if intangible_assets are fetched)
    # intangible_vals = [item.intangible_assets for item in financial_line_items if item.intangible_assets]
    # if intangible_vals and sum(intangible_vals) > 0:
    #     details.append("Significant intangible assets may indicate brand value or proprietary tech.")
    #     score += 1

    return {"score": score, "details": "; ".join(details)}


def analyze_financial_discipline(metrics: list, financial_line_items: list) -> dict:
    """
    Evaluate the company's balance sheet over multiple periods:
    - Debt ratio trends
    - Capital returns to shareholders over time (dividends, buybacks)
    """
    score = 0
    details = []

    if not metrics or not financial_line_items:
        return {"score": 0, "details": "Insufficient data to analyze financial discipline"}

    # 1. Multi-period debt ratio or debt_to_equity
    debt_to_equity_vals = [getattr(item, "debt_to_equity", None) for item in financial_line_items if getattr(item, "debt_to_equity", None) is not None]
    if debt_to_equity_vals:
        below_one_count = sum(1 for d in debt_to_equity_vals if d < 1.0)
        if below_one_count >= (len(debt_to_equity_vals) // 2 + 1):
            score += 2
            details.append("Debt-to-equity < 1.0 for the majority of periods (reasonable leverage).")
        else:
            details.append("Debt-to-equity >= 1.0 in many periods (could be high leverage).")
    else:
        # Fallback to total_liabilities / total_assets
        liab_to_assets = []
        for item in financial_line_items:
            total_liabilities = getattr(item, "total_liabilities", None)
            total_assets = getattr(item, "total_assets", None)
            if total_liabilities and total_assets and total_assets > 0:
                liab_to_assets.append(total_liabilities / total_assets)

        if liab_to_assets:
            below_50pct_count = sum(1 for ratio in liab_to_assets if ratio < 0.5)
            if below_50pct_count >= (len(liab_to_assets) // 2 + 1):
                score += 2
                details.append("Liabilities-to-assets < 50% for majority of periods.")
            else:
                details.append("Liabilities-to-assets >= 50% in many periods.")
        else:
            details.append("No consistent leverage ratio data available.")

    # 2. Capital allocation approach (dividends + share counts)
    dividends_list = [getattr(item, "dividends_and_other_cash_distributions", None) for item in financial_line_items if getattr(item, "dividends_and_other_cash_distributions", None) is not None]
    if dividends_list:
        paying_dividends_count = sum(1 for d in dividends_list if d < 0)
        if paying_dividends_count >= (len(dividends_list) // 2 + 1):
            score += 1
            details.append("Company has a history of returning capital to shareholders (dividends).")
        else:
            details.append("Dividends not consistently paid or no data on distributions.")
    else:
        details.append("No dividend data found across periods.")

    # Check for decreasing share count (simple approach)
    shares = [getattr(item, "outstanding_shares", None) for item in financial_line_items if getattr(item, "outstanding_shares", None) is not None]
    if len(shares) >= 2:
        # For buybacks, the newest count should be less than the oldest count
        if shares[0] < shares[-1]:
            score += 1
            details.append("Outstanding shares have decreased over time (possible buybacks).")
        else:
            details.append("Outstanding shares have not decreased over the available periods.")
    else:
        details.append("No multi-period share count data to assess buybacks.")

    return {"score": score, "details": "; ".join(details)}


def analyze_activism_potential(financial_line_items: list) -> dict:
    """
    Bill Ackman often engages in activism if a company has a decent brand or moat
    but is underperforming operationally.

    We'll do a simplified approach:
    - Look for positive revenue trends but subpar margins
    - That may indicate 'activism upside' if operational improvements could unlock value.
    """
    if not financial_line_items:
        return {"score": 0, "details": "Insufficient data for activism potential"}

    # Check revenue growth vs. operating margin - 使用统一的 CAGR 计算方法(处理A股YTD累计数据)
    op_margins = [getattr(item, "operating_margin", None) for item in financial_line_items if getattr(item, "operating_margin", None) is not None]

    if len(financial_line_items) < 2 or not op_margins:
        return {"score": 0, "details": "Not enough data to assess activism potential (need multi-year revenue + margins)."}

    revenue_growth = calculate_cagr_from_line_items(financial_line_items, field="revenue")
    avg_margin = sum(op_margins) / len(op_margins)

    score = 0
    details = []

    # Suppose if there's decent revenue growth but margins are below 10%, Ackman might see activism potential.
    if revenue_growth is not None and revenue_growth > 0.15 and avg_margin < 0.10:
        score += 2
        details.append(f"Revenue CAGR is healthy (~{revenue_growth*100:.1f}%), but margins are low (avg {avg_margin*100:.1f}%). " "Activism could unlock margin improvements.")
    else:
        details.append("No clear sign of activism opportunity (either margins are already decent or growth is weak).")

    return {"score": score, "details": "; ".join(details)}


def analyze_valuation(financial_line_items: list, market_cap: float) -> dict:
    """
    Ackman invests in companies trading at a discount to intrinsic value.
    Uses a simplified DCF with FCF as a proxy, plus margin of safety analysis.
    """
    if not financial_line_items or market_cap is None:
        return {"score": 0, "details": "Insufficient data to perform valuation"}

    # Use normalized FCF (average of available periods) to account for cyclicality
    # This prevents overvaluation of cyclical companies based on a single peak period
    fcf_values = [getattr(item, "free_cash_flow", None) for item in financial_line_items if getattr(item, "free_cash_flow", None) is not None]
    if not fcf_values:
        return {"score": 0, "details": "No FCF data available for valuation", "intrinsic_value": None}

    # Use normalized (average) FCF for DCF, not just the latest
    normalized_fcf = sum(fcf_values[:min(5, len(fcf_values))]) / min(5, len(fcf_values))
    latest_fcf = fcf_values[0] if fcf_values else 0
    fcf = normalized_fcf if len(fcf_values) >= 3 else latest_fcf

    if fcf <= 0:
        return {"score": 0, "details": f"No positive FCF for valuation; normalized FCF = {fcf:,.0f}", "intrinsic_value": None}

    # Quality-adjusted DCF assumptions
    # Assess company quality to avoid unrealistic valuations for weak businesses
    op_margins = [getattr(item, "operating_margin", None) for item in financial_line_items if getattr(item, "operating_margin", None) is not None]
    avg_op_margin = sum(op_margins) / len(op_margins) if op_margins else 0
    net_incomes = [getattr(item, "net_income", None) for item in financial_line_items[:3] if getattr(item, "net_income", None) is not None]
    avg_ni = sum(net_incomes) / len(net_incomes) if net_incomes else 0
    debt_to_equities = [getattr(item, "debt_to_equity", None) for item in financial_line_items if getattr(item, "debt_to_equity", None) is not None]
    avg_de = sum(debt_to_equities) / len(debt_to_equities) if debt_to_equities else 0

    if avg_op_margin < 0 or avg_ni < 0:
        # Loss-making company: very conservative assumptions
        growth_rate = 0.02
        terminal_multiple = 6
        discount_rate = 0.14
    elif avg_op_margin < 0.10:
        # Low-margin company: moderate assumptions
        growth_rate = 0.04
        terminal_multiple = 10
        discount_rate = 0.12
    else:
        # Healthy company: standard assumptions
        growth_rate = 0.06
        terminal_multiple = 15
        discount_rate = 0.10

    # Additional leverage penalty
    if avg_de > 1.5:
        discount_rate += 0.02
        terminal_multiple = max(terminal_multiple - 2, 5)

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
    # Simple scoring
    if margin_of_safety > 0.3:
        score += 3
    elif margin_of_safety > 0.1:
        score += 1

    details = [f"Calculated intrinsic value: ~{intrinsic_value:,.2f}", f"Market cap: ~{market_cap:,.2f}", f"Margin of safety: {margin_of_safety:.2%}"]

    return {"score": score, "details": "; ".join(details), "intrinsic_value": intrinsic_value, "margin_of_safety": margin_of_safety}


def generate_ackman_output(
    ticker: str,
    analysis_data: dict[str, any],
    state: AgentState,
    agent_id: str,
) -> BillAckmanSignal:
    """
    Generates investment decisions in the style of Bill Ackman.
    Includes more explicit references to brand strength, activism potential,
    catalysts, and management changes in the system prompt.
    """
    template = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """You are a Bill Ackman AI agent, making investment decisions using his principles:

            1. Seek high-quality businesses with durable competitive advantages (moats), often in well-known consumer or service brands.
            2. Prioritize consistent free cash flow and growth potential over the long term.
            3. Advocate for strong financial discipline (reasonable leverage, efficient capital allocation).
            4. Valuation matters: target intrinsic value with a margin of safety.
            5. Consider activism where management or operational improvements can unlock substantial upside.
            6. Concentrate on a few high-conviction investments.

            In your reasoning:
            - Emphasize brand strength, moat, or unique market positioning.
            - Review free cash flow generation and margin trends as key signals.
            - Analyze leverage, share buybacks, and dividends as capital discipline metrics.
            - Provide a valuation assessment with numerical backup (DCF, multiples, etc.).
            - Identify any catalysts for activism or value creation (e.g., cost cuts, better capital allocation).
            - Use a confident, analytic, and sometimes confrontational tone when discussing weaknesses or opportunities.

            Return your final recommendation (signal: bullish, neutral, or bearish) with a 0-100 confidence and a thorough reasoning section.
            """,
            ),
            (
                "human",
                """Based on the following analysis, create an Ackman-style investment signal.

            Analysis Data for {ticker}:
            {analysis_data}

            {currency_context}

            Return your output in strictly valid JSON:
            {{
              "signal": "bullish" | "bearish" | "neutral",
              "confidence": float (0-100),
              "reasoning": "string in English",
              "reasoning_cn": "same analysis in Chinese/中文"
            }}
            """,
            ),
        ]
    )

    prompt = template.invoke({"analysis_data": json.dumps(analysis_data, indent=2), "ticker": ticker, "currency_context": get_currency_context(ticker)})

    def create_default_bill_ackman_signal():
        return BillAckmanSignal(
            signal="neutral",
            confidence=0.0,
            reasoning="Error in analysis, defaulting to neutral",
            reasoning_cn="分析出错，默认返回中性",
        )

    return call_llm(
        prompt=prompt,
        pydantic_model=BillAckmanSignal,
        agent_name=agent_id,
        state=state,
        default_factory=create_default_bill_ackman_signal,
    )
