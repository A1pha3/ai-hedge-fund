from __future__ import annotations

import json
import math

from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel
from typing_extensions import Literal

from src.graph.state import AgentState, show_agent_reasoning
from src.tools.api import (
    get_financial_metrics,
    get_market_cap,
    search_line_items,
)
from src.utils.api_key import get_api_key_from_state
from src.utils.llm import call_llm
from src.utils.progress import progress
from src.utils.ticker_utils import get_currency_context


class AswathDamodaranSignal(BaseModel):
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: float
    reasoning: str
    reasoning_cn: str


def _latest_line_item_number(line_items: list, field: str) -> float | None:
    """
    Return the most recent finite numeric value for a given LineItem field.

    The line_items list is expected to be ordered from most recent to oldest, but this
    function will simply scan in the given order and return the first usable value.
    """
    for li in line_items or []:
        value = getattr(li, field, None)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return number
    return None


def aswath_damodaran_agent(state: AgentState, agent_id: str = "aswath_damodaran_agent"):
    """
    Analyze US equities through Aswath Damodaran's intrinsic-value lens:
      • Cost of Equity via CAPM (risk-free + β·ERP)
      • 5-yr revenue / FCFF growth trends & reinvestment efficiency
      • FCFF-to-Firm DCF → equity value → per-share intrinsic value
      • Cross-check with relative valuation (PE vs. Fwd PE sector median proxy)
    Produces a trading signal and explanation in Damodaran's analytical voice.
    """
    data = state["data"]
    end_date = data["end_date"]
    tickers = data["tickers"]
    api_key = get_api_key_from_state(state, "FINANCIAL_DATASETS_API_KEY")

    analysis_data: dict[str, dict] = {}
    damodaran_signals: dict[str, dict] = {}

    for ticker in tickers:
        # ─── Fetch core data ────────────────────────────────────────────────────
        progress.update_status(agent_id, ticker, "Fetching financial metrics")
        metrics = get_financial_metrics(ticker, end_date, period="ttm", limit=5, api_key=api_key)

        progress.update_status(agent_id, ticker, "Fetching financial line items")
        line_items = search_line_items(
            ticker,
            [
                "free_cash_flow",
                "ebit",
                "interest_expense",
                "capital_expenditure",
                "depreciation_and_amortization",
                "outstanding_shares",
                "net_income",
                "total_debt",
            ],
            end_date,
            period="annual",
            limit=5,
            api_key=api_key,
        )

        progress.update_status(agent_id, ticker, "Getting market cap")
        market_cap = get_market_cap(ticker, end_date, api_key=api_key)

        # ─── Analyses ───────────────────────────────────────────────────────────
        progress.update_status(agent_id, ticker, "Analyzing growth and reinvestment")
        growth_analysis = analyze_growth_and_reinvestment(metrics, line_items)

        progress.update_status(agent_id, ticker, "Analyzing risk profile")
        risk_analysis = analyze_risk_profile(metrics, line_items, ticker=ticker)

        progress.update_status(agent_id, ticker, "Calculating intrinsic value (DCF)")
        intrinsic_val_analysis = calculate_intrinsic_value_dcf(metrics, line_items, risk_analysis)

        progress.update_status(agent_id, ticker, "Assessing relative valuation")
        relative_val_analysis = analyze_relative_valuation(metrics)

        # ─── Score & margin of safety ──────────────────────────────────────────
        total_score = growth_analysis["score"] + risk_analysis["score"] + relative_val_analysis["score"]
        max_score = growth_analysis["max_score"] + risk_analysis["max_score"] + relative_val_analysis["max_score"]

        intrinsic_value = intrinsic_val_analysis["intrinsic_value"]
        margin_of_safety = (intrinsic_value - market_cap) / market_cap if intrinsic_value and market_cap else None

        # Decision rules (Damodaran tends to act with ~20-25 % MOS)
        if margin_of_safety is not None and margin_of_safety >= 0.25:
            signal = "bullish"
        elif margin_of_safety is not None and margin_of_safety <= -0.25:
            signal = "bearish"
        else:
            signal = "neutral"

        analysis_data[ticker] = {
            "signal": signal,
            "score": total_score,
            "max_score": max_score,
            "margin_of_safety": margin_of_safety,
            "growth_analysis": growth_analysis,
            "risk_analysis": risk_analysis,
            "relative_val_analysis": relative_val_analysis,
            "intrinsic_val_analysis": intrinsic_val_analysis,
            "market_cap": market_cap,
        }

        # ─── LLM: craft Damodaran-style narrative ──────────────────────────────
        progress.update_status(agent_id, ticker, "Generating Damodaran analysis")
        damodaran_output = generate_damodaran_output(
            ticker=ticker,
            analysis_data=analysis_data,
            state=state,
            agent_id=agent_id,
        )

        damodaran_signals[ticker] = {
            "signal": damodaran_output.signal,
            "confidence": damodaran_output.confidence,
            "reasoning": damodaran_output.reasoning,
            "reasoning_cn": damodaran_output.reasoning_cn,
        }

        progress.update_status(agent_id, ticker, "Done", analysis=damodaran_output.reasoning)

    # ─── Push message back to graph state ──────────────────────────────────────
    message = HumanMessage(content=json.dumps(damodaran_signals), name=agent_id)

    if state["metadata"]["show_reasoning"]:
        show_agent_reasoning(damodaran_signals, "Aswath Damodaran Agent")

    state["data"]["analyst_signals"][agent_id] = damodaran_signals
    progress.update_status(agent_id, None, "Done")

    return {"messages": [message], "data": state["data"]}


# ────────────────────────────────────────────────────────────────────────────────
# Helper analyses
# ────────────────────────────────────────────────────────────────────────────────
def analyze_growth_and_reinvestment(metrics: list, line_items: list) -> dict[str, any]:
    """
    Growth score (0-4):
      +2  5-yr CAGR of revenue > 8 %
      +1  5-yr CAGR of revenue > 3 %
      +1  Positive FCFF growth over 5 yr
    Reinvestment efficiency (ROIC > WACC) adds +1
    """
    max_score = 4
    if len(metrics) < 2:
        return {"score": 0, "max_score": max_score, "details": "Insufficient history"}

    # Revenue CAGR (oldest to latest)
    revs = [m.revenue for m in reversed(metrics) if hasattr(m, "revenue") and m.revenue]
    if len(revs) >= 2 and revs[0] > 0:
        cagr = (revs[-1] / revs[0]) ** (1 / (len(revs) - 1)) - 1
    else:
        cagr = None

    score, details = 0, []

    if cagr is not None:
        if cagr > 0.08:
            score += 2
            details.append(f"Revenue CAGR {cagr:.1%} (> 8 %)")
        elif cagr > 0.03:
            score += 1
            details.append(f"Revenue CAGR {cagr:.1%} (> 3 %)")
        else:
            details.append(f"Sluggish revenue CAGR {cagr:.1%}")
    else:
        details.append("Revenue data incomplete")

    # FCFF growth (proxy: free_cash_flow trend)
    fcfs = [getattr(li, "free_cash_flow", None) for li in reversed(line_items or [])]
    fcfs = [v for v in fcfs if v is not None]
    if len(fcfs) >= 2 and fcfs[-1] > fcfs[0]:
        score += 1
        details.append("Positive FCFF growth")
    else:
        details.append("Flat or declining FCFF")

    # Reinvestment efficiency (ROIC vs. 10 % hurdle)
    latest = metrics[0]
    if latest.return_on_invested_capital and latest.return_on_invested_capital > 0.10:
        score += 1
        details.append(f"ROIC {latest.return_on_invested_capital:.1%} (> 10 %)")

    return {"score": score, "max_score": max_score, "details": "; ".join(details), "metrics": latest.model_dump()}


def analyze_risk_profile(metrics: list, line_items: list, ticker: str = None) -> dict[str, any]:
    """
    Risk score (0-3):
      +1  Beta < 1.3
      +1  Debt/Equity < 1
      +1  Interest Coverage > 3×
    """
    max_score = 3
    if not metrics:
        return {"score": 0, "max_score": max_score, "details": "No metrics"}

    latest = metrics[0]
    score, details = 0, []

    # Beta
    beta = getattr(latest, "beta", None)
    if beta is not None:
        if beta < 1.3:
            score += 1
            details.append(f"Beta {beta:.2f}")
        else:
            details.append(f"High beta {beta:.2f}")
    else:
        details.append("Beta NA")

    # Debt / Equity
    dte = getattr(latest, "debt_to_equity", None)
    if dte is not None:
        if dte < 1:
            score += 1
            details.append(f"D/E {dte:.1f}")
        else:
            details.append(f"High D/E {dte:.1f}")
    else:
        details.append("D/E NA")

    # Interest coverage
    ebit = _latest_line_item_number(line_items, "ebit") or getattr(latest, "ebit", None)
    interest = _latest_line_item_number(line_items, "interest_expense") or getattr(latest, "interest_expense", None)
    if ebit and interest and interest != 0:
        coverage = ebit / abs(interest)
        if coverage > 3:
            score += 1
            details.append(f"Interest coverage × {coverage:.1f}")
        else:
            details.append(f"Weak coverage × {coverage:.1f}")
    else:
        details.append("Interest coverage NA")

    # Determine if company is loss-making
    net_income = _latest_line_item_number(line_items, "net_income")
    is_loss_making = net_income is not None and net_income < 0

    # Compute cost of equity with leverage adjustment
    cost_of_equity = estimate_cost_of_equity(beta, ticker=ticker, debt_to_equity=dte, is_loss_making=is_loss_making)

    return {
        "score": score,
        "max_score": max_score,
        "details": "; ".join(details),
        "beta": beta,
        "cost_of_equity": cost_of_equity,
    }


def analyze_relative_valuation(metrics: list) -> dict[str, any]:
    """
    Simple PE check vs. historical median (proxy since sector comps unavailable):
      +1 if TTM P/E < 70 % of 5-yr median
      +0 if between 70 %-130 %
      ‑1 if >130 %
    """
    max_score = 1
    if not metrics or len(metrics) < 5:
        return {"score": 0, "max_score": max_score, "details": "Insufficient P/E history"}

    pes = [m.price_to_earnings_ratio for m in metrics if m.price_to_earnings_ratio]
    if len(pes) < 5:
        return {"score": 0, "max_score": max_score, "details": "P/E data sparse"}

    ttm_pe = pes[0]
    median_pe = sorted(pes)[len(pes) // 2]

    if ttm_pe < 0.7 * median_pe:
        score, desc = 1, f"P/E {ttm_pe:.1f} vs. median {median_pe:.1f} (cheap)"
    elif ttm_pe > 1.3 * median_pe:
        score, desc = -1, f"P/E {ttm_pe:.1f} vs. median {median_pe:.1f} (expensive)"
    else:
        score, desc = 0, f"P/E inline with history"

    return {"score": score, "max_score": max_score, "details": desc}


# ────────────────────────────────────────────────────────────────────────────────
# Intrinsic value via FCFF DCF (Damodaran style)
# ────────────────────────────────────────────────────────────────────────────────
def calculate_intrinsic_value_dcf(metrics: list, line_items: list, risk_analysis: dict) -> dict[str, any]:
    """
    FCFF DCF with:
      • Base FCFF = latest free cash flow
      • Growth = 5-yr revenue CAGR (capped 12 %)
      • Fade linearly to terminal growth 2.5 % by year 10
      • Discount @ cost of equity (no debt split given data limitations)
    """
    if not metrics or len(metrics) < 2 or not line_items:
        return {"intrinsic_value": None, "details": ["Insufficient data"]}

    latest_m = metrics[0]
    shares = _latest_line_item_number(line_items, "outstanding_shares")
    fcff0 = _latest_line_item_number(line_items, "free_cash_flow")
    if fcff0 is None:
        fcf_per_share = getattr(latest_m, "free_cash_flow_per_share", None)
        if fcf_per_share is not None and shares is not None:
            try:
                fcff0 = float(fcf_per_share) * float(shares)
            except (TypeError, ValueError):
                fcff0 = None
    if not fcff0 or not shares:
        return {"intrinsic_value": None, "details": ["Missing FCFF or share count"]}

    # Growth assumptions
    revs = [getattr(m, "revenue", None) for m in reversed(metrics) if getattr(m, "revenue", None) is not None]
    if not revs:
        revs = [getattr(li, "revenue", None) for li in reversed(line_items) if getattr(li, "revenue", None) is not None]
    if len(revs) >= 2 and revs[0] > 0:
        base_growth = min((revs[-1] / revs[0]) ** (1 / (len(revs) - 1)) - 1, 0.12)
    else:
        base_growth = 0.04  # fallback

    terminal_growth = 0.025
    years = 10

    # Discount rate
    discount = risk_analysis.get("cost_of_equity") or 0.09

    # Project FCFF and discount
    pv_sum = 0.0
    g = base_growth
    g_step = (terminal_growth - base_growth) / (years - 1)
    for yr in range(1, years + 1):
        fcff_t = fcff0 * (1 + g)
        pv = fcff_t / (1 + discount) ** yr
        pv_sum += pv
        g += g_step

    # Terminal value (perpetuity with terminal growth)
    tv = fcff0 * (1 + terminal_growth) / (discount - terminal_growth) / (1 + discount) ** years

    equity_value = pv_sum + tv
    intrinsic_per_share = equity_value / shares

    return {
        "intrinsic_value": equity_value,
        "intrinsic_per_share": intrinsic_per_share,
        "assumptions": {
            "base_fcff": fcff0,
            "base_growth": base_growth,
            "terminal_growth": terminal_growth,
            "discount_rate": discount,
            "projection_years": years,
        },
        "details": ["FCFF DCF completed"],
    }


def estimate_cost_of_equity(beta: float | None, ticker: str = None, debt_to_equity: float | None = None, is_loss_making: bool = False) -> float:
    """CAPM with leverage adjustment: r_e = r_f + β_L × ERP + CRP + distress.
    β_L = β_U × (1 + (1-t) × D/E) — Hamada equation for leveraged beta.
    For A-share stocks, adds China country risk premium."""
    risk_free = 0.04  # 10-yr US Treasury proxy
    erp = 0.05  # long-run US equity risk premium
    beta_u = beta if beta is not None else 1.0  # unlevered beta

    # Hamada equation: lever up beta with D/E
    if debt_to_equity is not None and debt_to_equity > 0:
        tax_rate = 0.25  # China corporate tax rate
        beta_l = beta_u * (1 + (1 - tax_rate) * min(debt_to_equity, 5.0))  # cap D/E at 5 to avoid extreme
    else:
        beta_l = beta_u

    cost = risk_free + beta_l * erp

    # Add country risk premium for A-share stocks
    if ticker:
        from src.tools.akshare_api import is_ashare
        if is_ashare(ticker):
            cost += 0.025  # China country risk premium ~2.5%

    # Add distress premium for loss-making companies
    if is_loss_making:
        cost += 0.03  # 3% distress premium for negative earnings

    return cost


# ────────────────────────────────────────────────────────────────────────────────
# LLM generation
# ────────────────────────────────────────────────────────────────────────────────
def generate_damodaran_output(
    ticker: str,
    analysis_data: dict[str, any],
    state: AgentState,
    agent_id: str,
) -> AswathDamodaranSignal:
    """
    Ask the LLM to channel Prof. Damodaran's analytical style:
      • Story → Numbers → Value narrative
      • Emphasize risk, growth, and cash-flow assumptions
      • Cite cost of capital, implied MOS, and valuation cross-checks
    """
    template = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """You are Aswath Damodaran, Professor of Finance at NYU Stern.
                Use your valuation framework to issue trading signals on US equities.

                Speak with your usual clear, data-driven tone:
                  ◦ Start with the company "story" (qualitatively)
                  ◦ Connect that story to key numerical drivers: revenue growth, margins, reinvestment, risk
                  ◦ Conclude with value: your FCFF DCF estimate, margin of safety, and relative valuation sanity checks
                  ◦ Highlight major uncertainties and how they affect value
                Return ONLY the JSON specified below.""",
            ),
            (
                "human",
                """Ticker: {ticker}

                Analysis data:
                {analysis_data}

                {currency_context}

                Respond EXACTLY in this JSON schema:
                {{
                  "signal": "bullish" | "bearish" | "neutral",
                  "confidence": float (0-100),
                  "reasoning": "string in English",
                  "reasoning_cn": "same analysis in Chinese/中文"
                }}""",
            ),
        ]
    )

    prompt = template.invoke({"analysis_data": json.dumps(analysis_data, indent=2), "ticker": ticker, "currency_context": get_currency_context(ticker)})

    def default_signal():
        return AswathDamodaranSignal(
            signal="neutral",
            confidence=0.0,
            reasoning="Parsing error; defaulting to neutral",
            reasoning_cn="解析错误，默认返回中性",
        )

    return call_llm(
        prompt=prompt,
        pydantic_model=AswathDamodaranSignal,
        agent_name=agent_id,
        state=state,
        default_factory=default_signal,
    )
