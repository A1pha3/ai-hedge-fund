from collections.abc import Callable


def _score_pabrai_net_cash(cash: float | None, debt: float | None, ticker: str, get_currency_symbol: Callable[[str], str]) -> tuple[int, str | None]:
    if cash is None or debt is None:
        return 0, None

    net_cash = cash - debt
    currency_symbol = get_currency_symbol(ticker)
    if net_cash > 0:
        return 3, f"Net cash position: {currency_symbol}{net_cash:,.0f}"
    return 0, f"Net debt position: {currency_symbol}{net_cash:,.0f}"


def _score_pabrai_liquidity(current_assets: float | None, current_liabilities: float | None) -> tuple[int, str | None]:
    if current_assets is None or current_liabilities is None or current_liabilities <= 0:
        return 0, None

    current_ratio = current_assets / current_liabilities
    if current_ratio >= 2.0:
        return 2, f"Strong liquidity (current ratio {current_ratio:.2f})"
    if current_ratio >= 1.2:
        return 1, f"Adequate liquidity (current ratio {current_ratio:.2f})"
    return 0, f"Weak liquidity (current ratio {current_ratio:.2f})"


def _score_pabrai_leverage(latest: object, debt: float | None, equity: float | None) -> tuple[int, str | None]:
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


def _score_pabrai_fcf_stability(financial_line_items: list) -> tuple[int, str | None]:
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


def _score_pabrai_revenue_trajectory(financial_line_items: list, calculate_cagr: Callable[..., float | None]) -> tuple[int, str | None]:
    if len(financial_line_items) < 3:
        return 0, None

    rev_growth = calculate_cagr(financial_line_items, field="revenue")
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


def _score_pabrai_doubling_yield_support(
    financial_line_items: list,
    market_cap: float,
    analyze_valuation: Callable[..., dict],
) -> tuple[int, str | None]:
    valuation = analyze_valuation(financial_line_items, market_cap)
    fcf_yield = valuation.get("fcf_yield")
    if fcf_yield is None:
        return 0, None
    if fcf_yield > 0.08:
        return 3, "High FCF yield can drive doubling via retained cash/Buybacks"
    if fcf_yield > 0.05:
        return 1, "Reasonable FCF yield supports moderate compounding"
    return 0, None
