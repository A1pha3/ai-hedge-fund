def _score_munger_roic(financial_line_items: list) -> tuple[int, str]:
    roic_values = [item.return_on_invested_capital for item in financial_line_items if hasattr(item, "return_on_invested_capital") and item.return_on_invested_capital is not None]
    if not roic_values:
        return 0, "No ROIC data available"

    high_roic_count = sum(1 for r in roic_values if r > 0.15)
    if high_roic_count >= len(roic_values) * 0.8:
        return 3, f"Excellent ROIC: >15% in {high_roic_count}/{len(roic_values)} periods"
    if high_roic_count >= len(roic_values) * 0.5:
        return 2, f"Good ROIC: >15% in {high_roic_count}/{len(roic_values)} periods"
    if high_roic_count > 0:
        return 1, f"Mixed ROIC: >15% in only {high_roic_count}/{len(roic_values)} periods"
    return 0, "Poor ROIC: Never exceeds 15% threshold"


def _score_munger_pricing_power(financial_line_items: list) -> tuple[int, str]:
    gross_margins = [item.gross_margin for item in financial_line_items if hasattr(item, "gross_margin") and item.gross_margin is not None]
    if not (gross_margins and len(gross_margins) >= 3):
        return 0, "Insufficient gross margin data"

    margin_trend = sum(1 for i in range(1, len(gross_margins)) if gross_margins[i] >= gross_margins[i - 1])
    if margin_trend >= len(gross_margins) * 0.7:
        return 2, "Strong pricing power: Gross margins consistently improving"
    avg_margin = sum(gross_margins) / len(gross_margins)
    if avg_margin > 0.3:
        return 1, f"Good pricing power: Average gross margin {avg_margin:.1%}"
    return 0, "Limited pricing power: Low or declining gross margins"


def _score_munger_capital_intensity(financial_line_items: list) -> tuple[int, str]:
    if len(financial_line_items) < 3:
        return 0, "Insufficient data for capital intensity analysis"

    capex_to_revenue = []
    for item in financial_line_items:
        if hasattr(item, "capital_expenditure") and item.capital_expenditure is not None and hasattr(item, "revenue") and item.revenue is not None and item.revenue > 0:
            capex_ratio = abs(item.capital_expenditure) / item.revenue
            capex_to_revenue.append(capex_ratio)

    if not capex_to_revenue:
        return 0, "No capital expenditure data available"

    avg_capex_ratio = sum(capex_to_revenue) / len(capex_to_revenue)
    if avg_capex_ratio < 0.05:
        return 2, f"Low capital requirements: Avg capex {avg_capex_ratio:.1%} of revenue"
    if avg_capex_ratio < 0.10:
        return 1, f"Moderate capital requirements: Avg capex {avg_capex_ratio:.1%} of revenue"
    return 0, f"High capital requirements: Avg capex {avg_capex_ratio:.1%} of revenue"


def _score_munger_intangibles(financial_line_items: list) -> tuple[int, list[str]]:
    score = 0
    details: list[str] = []

    r_and_d = [item.research_and_development for item in financial_line_items if hasattr(item, "research_and_development") and item.research_and_development is not None]
    goodwill_and_intangible_assets = [
        item.goodwill_and_intangible_assets
        for item in financial_line_items
        if hasattr(item, "goodwill_and_intangible_assets") and item.goodwill_and_intangible_assets is not None
    ]

    if r_and_d and sum(r_and_d) > 0:
        score += 1
        details.append("Invests in R&D, building intellectual property")

    if goodwill_and_intangible_assets and len(goodwill_and_intangible_assets) > 0:
        score += 1
        details.append("Significant goodwill/intangible assets, suggesting brand value or IP")

    return score, details


def _score_munger_cash_conversion(financial_line_items: list) -> tuple[int, str, float | None]:
    fcf_values = [item.free_cash_flow for item in financial_line_items if hasattr(item, "free_cash_flow") and item.free_cash_flow is not None]
    net_income_values = [item.net_income for item in financial_line_items if hasattr(item, "net_income") and item.net_income is not None]

    if not (fcf_values and net_income_values and len(fcf_values) == len(net_income_values)):
        return 0, "Missing FCF or Net Income data", None

    fcf_to_ni_ratios = [fcf_values[i] / net_income_values[i] for i in range(len(fcf_values)) if net_income_values[i] and net_income_values[i] > 0]

    if not fcf_to_ni_ratios:
        return 0, "Could not calculate FCF to Net Income ratios", None

    avg_ratio = sum(fcf_to_ni_ratios) / len(fcf_to_ni_ratios)
    if avg_ratio > 1.1:
        return 3, f"Excellent cash conversion: FCF/NI ratio of {avg_ratio:.2f}", avg_ratio
    if avg_ratio > 0.9:
        return 2, f"Good cash conversion: FCF/NI ratio of {avg_ratio:.2f}", avg_ratio
    if avg_ratio > 0.7:
        return 1, f"Moderate cash conversion: FCF/NI ratio of {avg_ratio:.2f}", avg_ratio
    return 0, f"Poor cash conversion: FCF/NI ratio of only {avg_ratio:.2f}", avg_ratio


def _score_munger_debt_management(financial_line_items: list) -> tuple[int, str, float | None]:
    debt_values = [item.total_debt for item in financial_line_items if hasattr(item, "total_debt") and item.total_debt is not None]
    equity_values = [item.shareholders_equity for item in financial_line_items if hasattr(item, "shareholders_equity") and item.shareholders_equity is not None]

    if not (debt_values and equity_values and len(debt_values) == len(equity_values)):
        return 0, "Missing debt or equity data", None

    recent_de_ratio = debt_values[0] / equity_values[0] if equity_values[0] > 0 else float("inf")
    if recent_de_ratio < 0.3:
        return 3, f"Conservative debt management: D/E ratio of {recent_de_ratio:.2f}", recent_de_ratio
    if recent_de_ratio < 0.7:
        return 2, f"Prudent debt management: D/E ratio of {recent_de_ratio:.2f}", recent_de_ratio
    if recent_de_ratio < 1.5:
        return 1, f"Moderate debt level: D/E ratio of {recent_de_ratio:.2f}", recent_de_ratio
    return 0, f"High debt level: D/E ratio of {recent_de_ratio:.2f}", recent_de_ratio


def _score_munger_cash_management(financial_line_items: list) -> tuple[int, str, float | None]:
    cash_values = [item.cash_and_equivalents for item in financial_line_items if hasattr(item, "cash_and_equivalents") and item.cash_and_equivalents is not None]
    revenue_values = [item.revenue for item in financial_line_items if hasattr(item, "revenue") and item.revenue is not None]

    if not (cash_values and revenue_values and len(cash_values) > 0 and len(revenue_values) > 0):
        return 0, "Insufficient cash or revenue data", None

    cash_to_revenue = cash_values[0] / revenue_values[0] if revenue_values[0] > 0 else 0
    if 0.1 <= cash_to_revenue <= 0.25:
        return 2, f"Prudent cash management: Cash/Revenue ratio of {cash_to_revenue:.2f}", cash_to_revenue
    if 0.05 <= cash_to_revenue < 0.1 or 0.25 < cash_to_revenue <= 0.4:
        return 1, f"Acceptable cash position: Cash/Revenue ratio of {cash_to_revenue:.2f}", cash_to_revenue
    if cash_to_revenue > 0.4:
        return 0, f"Excess cash reserves: Cash/Revenue ratio of {cash_to_revenue:.2f}", cash_to_revenue
    return 0, f"Low cash reserves: Cash/Revenue ratio of {cash_to_revenue:.2f}", cash_to_revenue


def _score_munger_insider_activity(insider_trades: list) -> tuple[int, str, float | None]:
    if not (insider_trades and len(insider_trades) > 0):
        return 0, "No insider trading data available", None

    buys = sum(1 for trade in insider_trades if hasattr(trade, "transaction_type") and trade.transaction_type and trade.transaction_type.lower() in ["buy", "purchase"])
    sells = sum(1 for trade in insider_trades if hasattr(trade, "transaction_type") and trade.transaction_type and trade.transaction_type.lower() in ["sell", "sale"])
    total_trades = buys + sells
    if total_trades <= 0:
        return 0, "No recorded insider transactions", None

    buy_ratio = buys / total_trades
    if buy_ratio > 0.7:
        return 2, f"Strong insider buying: {buys}/{total_trades} transactions are purchases", buy_ratio
    if buy_ratio > 0.4:
        return 1, f"Balanced insider trading: {buys}/{total_trades} transactions are purchases", buy_ratio
    if buy_ratio < 0.1 and sells > 5:
        return -1, f"Concerning insider selling: {sells}/{total_trades} transactions are sales", buy_ratio
    return 0, f"Mixed insider activity: {buys}/{total_trades} transactions are purchases", buy_ratio


def _score_munger_share_count(financial_line_items: list) -> tuple[int, str, str]:
    share_counts = [item.outstanding_shares for item in financial_line_items if hasattr(item, "outstanding_shares") and item.outstanding_shares is not None]
    if not (share_counts and len(share_counts) >= 3):
        return 0, "Insufficient share count data", "unknown"

    if share_counts[0] < share_counts[-1] * 0.95:
        return 2, "Shareholder-friendly: Reducing share count over time", "decreasing"
    if share_counts[0] < share_counts[-1] * 1.05:
        return 1, "Stable share count: Limited dilution", "stable"
    if share_counts[0] > share_counts[-1] * 1.2:
        return -1, "Concerning dilution: Share count increased significantly", "increasing"
    return 0, "Moderate share count increase over time", "increasing"


def _score_munger_revenue_predictability(financial_line_items: list, calculate_cagr_from_line_items_fn) -> tuple[int, str]:
    revenues = [item.revenue for item in financial_line_items if hasattr(item, "revenue") and item.revenue is not None]
    if not (revenues and len(revenues) >= 5):
        return 0, "Insufficient revenue history for predictability analysis"

    cagr_growth = calculate_cagr_from_line_items_fn(financial_line_items, field="revenue")
    growth_rates = []
    growth_rates = [revenues[i] / revenues[i + 1] - 1 for i in range(len(revenues) - 1) if revenues[i + 1] != 0]

    if not growth_rates:
        return 0, "Cannot calculate revenue growth: zero revenue values found"

    avg_growth = sum(growth_rates) / len(growth_rates)
    growth_volatility = sum(abs(r - avg_growth) for r in growth_rates) / len(growth_rates)
    display_growth = cagr_growth if cagr_growth is not None else avg_growth

    if avg_growth > 0.05 and growth_volatility < 0.1:
        return 3, f"Highly predictable revenue: {display_growth:.1%} avg growth with low volatility"
    if avg_growth > 0 and growth_volatility < 0.2:
        return 2, f"Moderately predictable revenue: {display_growth:.1%} avg growth with some volatility"
    if avg_growth > 0:
        return 1, f"Growing but less predictable revenue: {display_growth:.1%} avg growth with high volatility"
    return 0, f"Declining or highly unpredictable revenue: {display_growth:.1%} avg growth"


def _score_munger_operating_predictability(financial_line_items: list) -> tuple[int, str]:
    op_income = [item.operating_income for item in financial_line_items if hasattr(item, "operating_income") and item.operating_income is not None]
    if not (op_income and len(op_income) >= 5):
        return 0, "Insufficient operating income history"

    positive_periods = sum(1 for income in op_income if income > 0)
    if positive_periods == len(op_income):
        return 3, "Highly predictable operations: Operating income positive in all periods"
    if positive_periods >= len(op_income) * 0.8:
        return 2, f"Predictable operations: Operating income positive in {positive_periods}/{len(op_income)} periods"
    if positive_periods >= len(op_income) * 0.6:
        return 1, f"Somewhat predictable operations: Operating income positive in {positive_periods}/{len(op_income)} periods"
    return 0, f"Unpredictable operations: Operating income positive in only {positive_periods}/{len(op_income)} periods"


def _score_munger_margin_predictability(financial_line_items: list) -> tuple[int, str]:
    op_margins = [item.operating_margin for item in financial_line_items if hasattr(item, "operating_margin") and item.operating_margin is not None]
    if not (op_margins and len(op_margins) >= 5):
        return 0, "Insufficient margin history"

    avg_margin = sum(op_margins) / len(op_margins)
    margin_volatility = sum(abs(m - avg_margin) for m in op_margins) / len(op_margins)
    if margin_volatility < 0.03:
        return 2, f"Highly predictable margins: {avg_margin:.1%} avg with minimal volatility"
    if margin_volatility < 0.07:
        return 1, f"Moderately predictable margins: {avg_margin:.1%} avg with some volatility"
    return 0, f"Unpredictable margins: {avg_margin:.1%} avg with high volatility ({margin_volatility:.1%})"


def _score_munger_cash_generation_predictability(financial_line_items: list) -> tuple[int, str]:
    fcf_values = [item.free_cash_flow for item in financial_line_items if hasattr(item, "free_cash_flow") and item.free_cash_flow is not None]
    if not (fcf_values and len(fcf_values) >= 5):
        return 0, "Insufficient free cash flow history"

    positive_fcf_periods = sum(1 for fcf in fcf_values if fcf > 0)
    if positive_fcf_periods == len(fcf_values):
        return 2, "Highly predictable cash generation: Positive FCF in all periods"
    if positive_fcf_periods >= len(fcf_values) * 0.8:
        return 1, f"Predictable cash generation: Positive FCF in {positive_fcf_periods}/{len(fcf_values)} periods"
    return 0, f"Unpredictable cash generation: Positive FCF in only {positive_fcf_periods}/{len(fcf_values)} periods"


def _score_munger_fcf_yield(normalized_fcf: float, market_cap: float) -> tuple[int, str, float]:
    fcf_yield = normalized_fcf / market_cap
    if fcf_yield > 0.08:
        return 4, f"Excellent value: {fcf_yield:.1%} FCF yield", fcf_yield
    if fcf_yield > 0.05:
        return 3, f"Good value: {fcf_yield:.1%} FCF yield", fcf_yield
    if fcf_yield > 0.03:
        return 1, f"Fair value: {fcf_yield:.1%} FCF yield", fcf_yield
    return 0, f"Expensive: Only {fcf_yield:.1%} FCF yield", fcf_yield


def _calculate_munger_intrinsic_value_range(normalized_fcf: float) -> dict[str, float]:
    return {
        "conservative": normalized_fcf * 10,
        "reasonable": normalized_fcf * 15,
        "optimistic": normalized_fcf * 20,
    }


def _score_munger_margin_of_safety(reasonable_value: float, market_cap: float) -> tuple[int, str, float]:
    margin_of_safety_vs_fair_value = (reasonable_value - market_cap) / market_cap
    if margin_of_safety_vs_fair_value > 0.3:
        return 3, f"Large margin of safety: {margin_of_safety_vs_fair_value:.1%} upside to reasonable value", margin_of_safety_vs_fair_value
    if margin_of_safety_vs_fair_value > 0.1:
        return 2, f"Moderate margin of safety: {margin_of_safety_vs_fair_value:.1%} upside to reasonable value", margin_of_safety_vs_fair_value
    if margin_of_safety_vs_fair_value > -0.1:
        return 1, f"Fair price: Within 10% of reasonable value ({margin_of_safety_vs_fair_value:.1%})", margin_of_safety_vs_fair_value
    return 0, f"Expensive: {-margin_of_safety_vs_fair_value:.1%} premium to reasonable value", margin_of_safety_vs_fair_value


def _score_munger_fcf_trend(fcf_values: list[float]) -> tuple[int, str]:
    recent_avg = sum(fcf_values[:3]) / 3
    older_avg = sum(fcf_values[-3:]) / 3 if len(fcf_values) >= 6 else fcf_values[-1]

    if recent_avg > older_avg * 1.2:
        return 3, "Growing FCF trend adds to intrinsic value"
    if recent_avg > older_avg:
        return 2, "Stable to growing FCF supports valuation"
    return 0, "Declining FCF trend is concerning"
