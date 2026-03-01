from __future__ import annotations

"""Valuation Agent

Implements four complementary valuation methodologies and aggregates them with
configurable weights. 
"""

import json
import statistics

from langchain_core.messages import HumanMessage

from src.graph.state import AgentState, show_agent_reasoning
from src.tools.api import (
    get_financial_metrics,
    get_market_cap,
    search_line_items,
)
from src.utils.api_key import get_api_key_from_state
from src.utils.progress import progress
from src.utils.ticker_utils import get_currency_symbol


def valuation_analyst_agent(state: AgentState, agent_id: str = "valuation_analyst_agent"):
    """Run valuation across tickers and write signals back to `state`."""

    data = state["data"]
    end_date = data["end_date"]
    tickers = data["tickers"]
    api_key = get_api_key_from_state(state, "FINANCIAL_DATASETS_API_KEY")
    valuation_analysis: dict[str, dict] = {}

    for ticker in tickers:
        progress.update_status(agent_id, ticker, "Fetching financial data")

        # --- Historical financial metrics ---
        financial_metrics = get_financial_metrics(
            ticker=ticker,
            end_date=end_date,
            period="ttm",
            limit=8,
            api_key=api_key,
        )
        if not financial_metrics:
            progress.update_status(agent_id, ticker, "Failed: No financial metrics found")
            valuation_analysis[ticker] = {
                "signal": "neutral",
                "confidence": 0,
                "reasoning": {"error": "No financial metrics available for valuation analysis"},
            }
            continue
        most_recent_metrics = financial_metrics[0]

        # --- Enhanced line‑items ---
        # 使用 "annual" period 确保 DCF 模型获取完整年度数据
        # A股使用累计会计制度，"ttm" 返回的 Q1/H1/Q3 数据不能作为年度等间距序列
        progress.update_status(agent_id, ticker, "Gathering comprehensive line items")
        line_items = search_line_items(
            ticker=ticker,
            line_items=["free_cash_flow", "net_income", "depreciation_and_amortization", "capital_expenditure", "working_capital", "total_debt", "cash_and_equivalents", "interest_expense", "revenue", "operating_income", "ebit", "ebitda"],
            end_date=end_date,
            period="annual",
            limit=8,
            api_key=api_key,
        )
        if len(line_items) < 2:
            progress.update_status(agent_id, ticker, "Failed: Insufficient financial line items")
            valuation_analysis[ticker] = {
                "signal": "neutral",
                "confidence": 0,
                "reasoning": {"error": f"Insufficient financial line items (found {len(line_items)}, need at least 2)"},
            }
            continue
        li_curr, li_prev = line_items[0], line_items[1]

        # ------------------------------------------------------------------
        # Valuation models
        # ------------------------------------------------------------------
        # Handle potential None values for working capital
        wc_curr = getattr(li_curr, "working_capital", None)
        wc_prev = getattr(li_prev, "working_capital", None)
        if wc_curr is not None and wc_prev is not None:
            wc_change = wc_curr - wc_prev
        else:
            wc_change = 0  # Default to 0 if working capital data is unavailable

        # Owner Earnings
        owner_val = calculate_owner_earnings_value(
            net_income=getattr(li_curr, "net_income", None),
            depreciation=getattr(li_curr, "depreciation_and_amortization", None),
            capex=getattr(li_curr, "capital_expenditure", None),
            working_capital_change=wc_change,
            growth_rate=most_recent_metrics.earnings_growth or 0.05,
        )

        # Enhanced Discounted Cash Flow with WACC and scenarios
        progress.update_status(agent_id, ticker, "Calculating WACC and enhanced DCF")

        # Calculate WACC
        wacc = calculate_wacc(
            market_cap=most_recent_metrics.market_cap or 0,
            total_debt=getattr(li_curr, "total_debt", None),
            cash=getattr(li_curr, "cash_and_equivalents", None),
            interest_coverage=most_recent_metrics.interest_coverage,
            debt_to_equity=most_recent_metrics.debt_to_equity,
        )

        # Prepare FCF history for enhanced DCF
        fcf_history = []
        for li in line_items:
            if hasattr(li, "free_cash_flow") and li.free_cash_flow is not None:
                fcf_history.append(li.free_cash_flow)

        # Enhanced DCF with scenarios
        dcf_results = calculate_dcf_scenarios(fcf_history=fcf_history, growth_metrics={"revenue_growth": most_recent_metrics.revenue_growth, "fcf_growth": most_recent_metrics.free_cash_flow_growth, "earnings_growth": most_recent_metrics.earnings_growth}, wacc=wacc, market_cap=most_recent_metrics.market_cap or 0, revenue_growth=most_recent_metrics.revenue_growth)

        dcf_val = dcf_results["expected_value"]

        # Implied Equity Value
        ev_ebitda_val = calculate_ev_ebitda_value(financial_metrics)

        # Residual Income Model
        rim_val = calculate_residual_income_value(
            market_cap=most_recent_metrics.market_cap,
            net_income=getattr(li_curr, "net_income", None),
            price_to_book_ratio=most_recent_metrics.price_to_book_ratio,
            book_value_growth=most_recent_metrics.book_value_growth or 0.03,
        )

        # ------------------------------------------------------------------
        # Aggregate & signal
        # ------------------------------------------------------------------
        market_cap = get_market_cap(ticker, end_date, api_key=api_key)
        if not market_cap:
            progress.update_status(agent_id, ticker, "Failed: Market cap unavailable")
            valuation_analysis[ticker] = {
                "signal": "neutral",
                "confidence": 0,
                "reasoning": {"error": "Market cap unavailable for valuation analysis"},
            }
            continue

        method_values = {
            "dcf": {"value": dcf_val, "weight": 0.35},
            "owner_earnings": {"value": owner_val, "weight": 0.35},
            "ev_ebitda": {"value": ev_ebitda_val, "weight": 0.20},
            "residual_income": {"value": rim_val, "weight": 0.10},
        }

        cs = get_currency_symbol(ticker)
        total_weight = sum(v["weight"] for v in method_values.values() if v["value"] > 0)
        methods_succeeded = sum(1 for v in method_values.values() if v["value"] > 0)
        methods_total = len(method_values)
        if total_weight == 0:
            progress.update_status(agent_id, ticker, "All valuation methods non-positive")
            method_value_summary = {name: vals["value"] for name, vals in method_values.items()}
            valuation_analysis[ticker] = {
                "signal": "bearish",
                "confidence": 85,
                "reasoning": {
                    "summary": "All valuation methods returned non-positive intrinsic values while market cap is positive",
                    "market_cap": market_cap,
                    "method_values": method_value_summary,
                    "details": f"DCF: {cs}{dcf_val:,.2f}, Owner Earnings: {cs}{owner_val:,.2f}, EV/EBITDA: {cs}{ev_ebitda_val:,.2f}, Residual Income: {cs}{rim_val:,.2f}",
                },
            }
            continue

        for v in method_values.values():
            v["gap"] = (v["value"] - market_cap) / market_cap if v["value"] > 0 else None

        weighted_gap = sum(v["weight"] * v["gap"] for v in method_values.values() if v["gap"] is not None) / total_weight

        signal = "bullish" if weighted_gap > 0.15 else "bearish" if weighted_gap < -0.15 else "neutral"
        # Penalize confidence when most valuation methods fail (data unavailable)
        coverage_ratio = methods_succeeded / methods_total  # e.g., 1/4 = 0.25
        raw_confidence = abs(weighted_gap) / 0.30 * 100
        confidence = round(min(raw_confidence * coverage_ratio, 100))

        # Enhanced reasoning with DCF scenario details
        reasoning = {}
        for m, vals in method_values.items():
            # Always include the method, even if value is 0 or negative
            if vals['value'] <= 0:
                # 区分"数据不足"和"计算结果为负/零"
                if m == "owner_earnings":
                    base_details = f"Value: N/A (owner earnings negative, business not generating positive owner earnings), Market Cap: {cs}{market_cap:,.2f}, "
                elif m == "dcf" and any(isinstance(x, (int, float)) and x < 0 for x in fcf_history[:1]):
                    base_details = f"Value: N/A (negative free cash flow), Market Cap: {cs}{market_cap:,.2f}, "
                else:
                    base_details = f"Value: N/A (insufficient data), Market Cap: {cs}{market_cap:,.2f}, "
            else:
                base_details = f"Value: {cs}{vals['value']:,.2f}, Market Cap: {cs}{market_cap:,.2f}, "
            if vals["gap"] is not None:
                base_details += f"Gap: {vals['gap']:.1%}, Weight: {vals['weight']*100:.0f}%"
            else:
                base_details += f"Gap: N/A (data unavailable), Weight: {vals['weight']*100:.0f}%"

            # Add enhanced DCF details
            if m == "dcf" and "dcf_results" in locals():
                enhanced_details = f"{base_details}\n" f"  WACC: {wacc:.1%}, Bear: {cs}{dcf_results['downside']:,.2f}, " f"Bull: {cs}{dcf_results['upside']:,.2f}, Range: {cs}{dcf_results['range']:,.2f}"
            else:
                enhanced_details = base_details

            reasoning[f"{m}_analysis"] = {
                "signal": ("bullish" if vals["gap"] and vals["gap"] > 0.15 else "bearish" if vals["gap"] and vals["gap"] < -0.15 else "neutral"),
                "details": enhanced_details,
            }

        # Add overall DCF scenario summary if available
        if "dcf_results" in locals():
            reasoning["dcf_scenario_analysis"] = {"bear_case": f"{cs}{dcf_results['downside']:,.2f}", "base_case": f"{cs}{dcf_results['scenarios']['base']:,.2f}", "bull_case": f"{cs}{dcf_results['upside']:,.2f}", "wacc_used": f"{wacc:.1%}", "fcf_periods_analyzed": len(fcf_history)}
        
        # Add summary if reasoning is still empty (fallback)
        if not reasoning:
            reasoning["summary"] = {
                "signal": signal,
                "details": f"Weighted valuation gap: {weighted_gap:.1%}. Market Cap: {cs}{market_cap:,.2f}. All valuation methods returned zero or negative values.",
            }

        valuation_analysis[ticker] = {
            "signal": signal,
            "confidence": confidence,
            "reasoning": reasoning,
        }
        progress.update_status(agent_id, ticker, "Done", analysis=json.dumps(reasoning, indent=4))

    # ---- Emit message (for LLM tool chain) ----
    msg = HumanMessage(content=json.dumps(valuation_analysis), name=agent_id)
    if state["metadata"].get("show_reasoning"):
        show_agent_reasoning(valuation_analysis, "Valuation Analysis Agent")

    # Add the signal to the analyst_signals list
    state["data"]["analyst_signals"][agent_id] = valuation_analysis

    progress.update_status(agent_id, None, "Done")

    return {"messages": [msg], "data": data}


#############################
# Helper Valuation Functions
#############################


def calculate_owner_earnings_value(
    net_income: float | None,
    depreciation: float | None,
    capex: float | None,
    working_capital_change: float | None,
    growth_rate: float = 0.05,
    required_return: float = 0.15,
    margin_of_safety: float = 0.25,
    num_years: int = 5,
) -> float:
    """Buffett owner‑earnings valuation with margin‑of‑safety."""
    if not all(isinstance(x, (int, float)) for x in [net_income, depreciation, capex, working_capital_change]):
        return 0

    owner_earnings = net_income + depreciation - capex - working_capital_change
    if owner_earnings <= 0:
        return 0

    # Clamp growth_rate to a reasonable range to prevent nonsensical valuations
    # from extreme earnings_growth values (e.g. -522.7% → -5.227)
    growth_rate = max(min(growth_rate, 0.30), -0.20)

    pv = 0.0
    for yr in range(1, num_years + 1):
        future = owner_earnings * (1 + growth_rate) ** yr
        pv += future / (1 + required_return) ** yr

    terminal_growth = min(growth_rate, 0.03)
    term_val = (owner_earnings * (1 + growth_rate) ** num_years * (1 + terminal_growth)) / (required_return - terminal_growth)
    pv_term = term_val / (1 + required_return) ** num_years

    intrinsic = pv + pv_term
    return intrinsic * (1 - margin_of_safety)


def calculate_intrinsic_value(
    free_cash_flow: float | None,
    growth_rate: float = 0.05,
    discount_rate: float = 0.10,
    terminal_growth_rate: float = 0.02,
    num_years: int = 5,
) -> float:
    """Classic DCF on FCF with constant growth and terminal value."""
    if free_cash_flow is None or free_cash_flow <= 0:
        return 0

    pv = 0.0
    for yr in range(1, num_years + 1):
        fcft = free_cash_flow * (1 + growth_rate) ** yr
        pv += fcft / (1 + discount_rate) ** yr

    term_val = (free_cash_flow * (1 + growth_rate) ** num_years * (1 + terminal_growth_rate)) / (discount_rate - terminal_growth_rate)
    pv_term = term_val / (1 + discount_rate) ** num_years

    return pv + pv_term


def calculate_ev_ebitda_value(financial_metrics: list):
    """Implied equity value via median EV/EBITDA multiple.

    Uses **normalized (median) EBITDA** across available periods instead of
    only the current period's EBITDA.  This avoids seasonal / TTM distortions
    where a single quarter can produce an EBITDA far below the company's
    run-rate, leading to a spuriously low (or zero) equity estimate.
    """
    if not financial_metrics:
        return 0
    m0 = financial_metrics[0]
    if not (m0.enterprise_value and m0.market_cap):
        return 0

    # Collect EV/EBITDA pairs and derive EBITDA for each period
    ev_ebitda_ratios: list[float] = []
    ebitda_values: list[float] = []
    for m in financial_metrics:
        ratio = m.enterprise_value_to_ebitda_ratio
        ev = m.enterprise_value
        if ratio and ev and ratio > 0:
            ev_ebitda_ratios.append(ratio)
            ebitda_values.append(ev / ratio)

    if not ev_ebitda_ratios:
        return 0

    # Use median EBITDA to smooth seasonal / TTM distortions
    ebitda_normalized = statistics.median(ebitda_values)
    if ebitda_normalized <= 0:
        return 0

    med_mult = statistics.median(ev_ebitda_ratios)
    ev_implied = med_mult * ebitda_normalized
    net_debt = (m0.enterprise_value or 0) - (m0.market_cap or 0)
    return max(ev_implied - net_debt, 0)


def calculate_residual_income_value(
    market_cap: float | None,
    net_income: float | None,
    price_to_book_ratio: float | None,
    book_value_growth: float = 0.03,
    cost_of_equity: float = 0.10,
    terminal_growth_rate: float = 0.03,
    num_years: int = 5,
):
    """Residual Income Model (Edwards‑Bell‑Ohlson).

    The EBO model values equity as ``book_value + PV(future residual income)``.
    Residual income *can* be negative (i.e. the company earns less than its
    cost of equity on book value).  In that case the PV of RI is negative and
    the intrinsic value sits *below* book value — but it may still be a
    meaningful positive number.  Returning 0 when RI₀ < 0 discards all
    information from the model for loss‑making companies and is overly
    aggressive.
    """
    if not (market_cap and price_to_book_ratio and price_to_book_ratio > 0):
        return 0

    # net_income may be None (data missing) — treat as zero for the RI calc
    ni = net_income if isinstance(net_income, (int, float)) else 0

    book_val = market_cap / price_to_book_ratio
    ri0 = ni - cost_of_equity * book_val

    # When RI is negative, cap the terminal‑value decay so the model doesn't
    # produce absurdly low values.  We fade negative RI to zero over the
    # projection window (assume the company eventually earns its CoE).
    if ri0 < 0:
        # For negative RI: assume it linearly recovers to 0 over num_years
        pv_ri = 0.0
        for yr in range(1, num_years + 1):
            fade = max(1.0 - yr / num_years, 0.0)  # 1.0 → 0.0
            ri_t = ri0 * fade
            pv_ri += ri_t / (1 + cost_of_equity) ** yr
        # No terminal value for negative RI (assumed to recover)
        pv_term = 0.0
    else:
        pv_ri = 0.0
        for yr in range(1, num_years + 1):
            ri_t = ri0 * (1 + book_value_growth) ** yr
            pv_ri += ri_t / (1 + cost_of_equity) ** yr

        term_ri = ri0 * (1 + book_value_growth) ** (num_years + 1) / (cost_of_equity - terminal_growth_rate)
        pv_term = term_ri / (1 + cost_of_equity) ** num_years

    intrinsic = book_val + pv_ri + pv_term
    return max(intrinsic * 0.8, 0)  # 20% margin of safety, floor at 0


####################################
# Enhanced DCF Helper Functions
####################################


def calculate_wacc(market_cap: float, total_debt: float | None, cash: float | None, interest_coverage: float | None, debt_to_equity: float | None, beta_proxy: float = 1.0, risk_free_rate: float = 0.045, market_risk_premium: float = 0.06) -> float:
    """Calculate WACC using available financial data."""

    # Cost of Equity (CAPM)
    cost_of_equity = risk_free_rate + beta_proxy * market_risk_premium

    # Cost of Debt - estimate from interest coverage
    if interest_coverage and interest_coverage > 0:
        # Higher coverage = lower cost of debt
        cost_of_debt = max(risk_free_rate + 0.01, risk_free_rate + (10 / interest_coverage))
    else:
        cost_of_debt = risk_free_rate + 0.05  # Default spread

    # Weights
    net_debt = max((total_debt or 0) - (cash or 0), 0)
    total_value = market_cap + net_debt

    if total_value > 0:
        weight_equity = market_cap / total_value
        weight_debt = net_debt / total_value

        # Tax shield (assume 25% corporate tax rate)
        wacc = (weight_equity * cost_of_equity) + (weight_debt * cost_of_debt * 0.75)
    else:
        wacc = cost_of_equity

    return min(max(wacc, 0.06), 0.20)  # Floor 6%, cap 20%


def calculate_fcf_volatility(fcf_history: list[float]) -> float:
    """Calculate FCF volatility as coefficient of variation."""
    if len(fcf_history) < 3:
        return 0.5  # Default moderate volatility

    # Filter out zeros and negatives for volatility calc
    positive_fcf = [fcf for fcf in fcf_history if fcf > 0]
    if len(positive_fcf) < 2:
        return 0.8  # High volatility if mostly negative FCF

    try:
        mean_fcf = statistics.mean(positive_fcf)
        std_fcf = statistics.stdev(positive_fcf)
        return min(std_fcf / mean_fcf, 1.0) if mean_fcf > 0 else 0.8
    except:
        return 0.5


def calculate_enhanced_dcf_value(fcf_history: list[float], growth_metrics: dict, wacc: float, market_cap: float, revenue_growth: float | None = None) -> float:
    """Enhanced DCF with multi-stage growth.

    When the most-recent FCF is negative but there are positive historical
    values, uses the average of positive historical FCF as a conservative
    proxy.  This avoids returning 0 for cyclical businesses that have
    temporary negative FCF but a track record of positive cash generation.
    """
    if not fcf_history:
        return 0

    fcf_current = fcf_history[0]

    # If current FCF is negative, try to use average positive historical FCF
    if fcf_current <= 0:
        positive_fcf = [f for f in fcf_history if f > 0]
        if not positive_fcf:
            return 0  # No positive FCF in entire history
        # Use average of positive historical FCF with a 30% haircut
        fcf_current = statistics.mean(positive_fcf) * 0.7

    # Analyze FCF trend and quality
    fcf_avg_3yr = sum(fcf_history[:3]) / min(3, len(fcf_history))
    fcf_volatility = calculate_fcf_volatility(fcf_history)

    # Stage 1: High Growth (Years 1-3)
    # Use revenue growth but cap based on business maturity
    high_growth = min(revenue_growth or 0.05, 0.25) if revenue_growth else 0.05
    if market_cap > 50_000_000_000:  # Large cap
        high_growth = min(high_growth, 0.10)

    # Stage 2: Transition (Years 4-7)
    transition_growth = (high_growth + 0.03) / 2

    # Stage 3: Terminal (steady state)
    terminal_growth = min(0.03, high_growth * 0.6)

    # Project FCF with stages
    pv = 0
    base_fcf = max(fcf_current, fcf_avg_3yr * 0.85)  # Conservative base

    # High growth stage
    for year in range(1, 4):
        fcf_projected = base_fcf * (1 + high_growth) ** year
        pv += fcf_projected / (1 + wacc) ** year

    # Transition stage
    for year in range(4, 8):
        transition_rate = transition_growth * (8 - year) / 4  # Declining
        fcf_projected = base_fcf * (1 + high_growth) ** 3 * (1 + transition_rate) ** (year - 3)
        pv += fcf_projected / (1 + wacc) ** year

    # Terminal value
    final_fcf = base_fcf * (1 + high_growth) ** 3 * (1 + transition_growth) ** 4
    if wacc <= terminal_growth:
        terminal_growth = wacc * 0.8  # Adjust if invalid
    terminal_value = (final_fcf * (1 + terminal_growth)) / (wacc - terminal_growth)
    pv_terminal = terminal_value / (1 + wacc) ** 7

    # Quality adjustment based on FCF volatility
    quality_factor = max(0.7, 1 - (fcf_volatility * 0.5))

    return (pv + pv_terminal) * quality_factor


def calculate_dcf_scenarios(fcf_history: list[float], growth_metrics: dict, wacc: float, market_cap: float, revenue_growth: float | None = None) -> dict:
    """Calculate DCF under multiple scenarios.

    When revenue_growth is negative, the growth adjustments are applied to the
    *absolute* deviation so that bear always yields the worst (most negative or
    least positive) growth and bull yields the best.  This prevents the
    multiplicative inversion bug where ``negative_growth * 0.5`` is actually
    *better* than ``negative_growth * 1.5``.
    """

    scenarios = {"bear": {"growth_adj": 0.5, "wacc_adj": 1.2, "terminal_adj": 0.8}, "base": {"growth_adj": 1.0, "wacc_adj": 1.0, "terminal_adj": 1.0}, "bull": {"growth_adj": 1.5, "wacc_adj": 0.9, "terminal_adj": 1.2}}

    results = {}
    base_revenue_growth = revenue_growth or 0.05

    for scenario, adjustments in scenarios.items():
        if base_revenue_growth >= 0:
            # Positive growth: higher multiplier → more growth → higher value (bull)
            adjusted_revenue_growth = base_revenue_growth * adjustments["growth_adj"]
        else:
            # Negative growth: apply adjustment to the absolute magnitude, then
            # swap direction so bear gets *more* negative (worse) growth and
            # bull gets *less* negative (better) growth.
            #   bear: growth_adj=0.5 → inverted to 1.5 → -0.26*1.5 = -0.39 (worse)
            #   bull: growth_adj=1.5 → inverted to 0.5 → -0.26*0.5 = -0.13 (better)
            inverted_adj = 1.0 / adjustments["growth_adj"] if adjustments["growth_adj"] != 0 else 1.0
            adjusted_revenue_growth = base_revenue_growth * inverted_adj

        adjusted_wacc = wacc * adjustments["wacc_adj"]

        results[scenario] = calculate_enhanced_dcf_value(fcf_history=fcf_history, growth_metrics=growth_metrics, wacc=adjusted_wacc, market_cap=market_cap, revenue_growth=adjusted_revenue_growth)

    # Probability-weighted average
    expected_value = results["bear"] * 0.2 + results["base"] * 0.6 + results["bull"] * 0.2

    return {"scenarios": results, "expected_value": expected_value, "range": results["bull"] - results["bear"], "upside": results["bull"], "downside": results["bear"]}
