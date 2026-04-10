from collections.abc import Callable


def _score_lynch_revenue_growth(financial_line_items: list, calculate_cagr: Callable[..., float | None]) -> tuple[int, str]:
    rev_growth = calculate_cagr(financial_line_items, field="revenue")
    if rev_growth is None:
        return 0, "Insufficient revenue data for CAGR calculation."
    if rev_growth > 0.25:
        return 3, f"Strong revenue CAGR: {rev_growth:.1%}"
    if rev_growth > 0.10:
        return 2, f"Moderate revenue CAGR: {rev_growth:.1%}"
    if rev_growth > 0.02:
        return 1, f"Slight revenue CAGR: {rev_growth:.1%}"
    return 0, f"Flat or negative revenue CAGR: {rev_growth:.1%}"


def _score_lynch_eps_growth(financial_line_items: list, calculate_cagr: Callable[..., float | None]) -> tuple[int, str]:
    eps_growth = calculate_cagr(financial_line_items, field="earnings_per_share")
    if eps_growth is None:
        return 0, "Insufficient EPS data for CAGR calculation."
    if eps_growth > 0.25:
        return 3, f"Strong EPS CAGR: {eps_growth:.1%}"
    if eps_growth > 0.10:
        return 2, f"Moderate EPS CAGR: {eps_growth:.1%}"
    if eps_growth > 0.02:
        return 1, f"Slight EPS CAGR: {eps_growth:.1%}"
    return 0, f"Flat or negative EPS CAGR: {eps_growth:.1%}"


def _score_lynch_debt_profile(financial_line_items: list) -> tuple[int, str]:
    de_ratio = None
    dte_direct = getattr(financial_line_items[0], "debt_to_equity", None) if financial_line_items else None
    if dte_direct is not None:
        de_ratio = dte_direct
    else:
        debt_values = [getattr(fi, "total_debt", None) for fi in financial_line_items if getattr(fi, "total_debt", None) is not None]
        eq_values = [getattr(fi, "shareholders_equity", None) for fi in financial_line_items if getattr(fi, "shareholders_equity", None) is not None]
        if debt_values and eq_values and len(debt_values) == len(eq_values) and len(debt_values) > 0:
            de_ratio = debt_values[0] / (eq_values[0] if eq_values[0] else 1e-9)

    if de_ratio is None:
        return 0, "No debt/equity data available."
    if de_ratio < 0.5:
        return 2, f"Low debt-to-equity: {de_ratio:.2f}"
    if de_ratio < 1.0:
        return 1, f"Moderate debt-to-equity: {de_ratio:.2f}"
    return 0, f"High debt-to-equity: {de_ratio:.2f}"


def _score_lynch_operating_margin(financial_line_items: list) -> tuple[int, str]:
    om_values = [getattr(fi, "operating_margin", None) for fi in financial_line_items if getattr(fi, "operating_margin", None) is not None]
    if not om_values:
        return 0, "No operating margin data available."

    om_recent = om_values[0]
    if om_recent > 0.20:
        return 2, f"Strong operating margin: {om_recent:.1%}"
    if om_recent > 0.10:
        return 1, f"Moderate operating margin: {om_recent:.1%}"
    return 0, f"Low operating margin: {om_recent:.1%}"


def _score_lynch_free_cash_flow(financial_line_items: list) -> tuple[int, str]:
    fcf_values = [getattr(fi, "free_cash_flow", None) for fi in financial_line_items if getattr(fi, "free_cash_flow", None) is not None]
    if not fcf_values or fcf_values[0] is None:
        return 0, "No free cash flow data available."
    if fcf_values[0] > 0:
        return 2, f"Positive free cash flow: {fcf_values[0]:,.0f}"
    return 0, f"Recent FCF is negative: {fcf_values[0]:,.0f}"


def _describe_lynch_pe_and_growth(
    financial_line_items: list,
    market_cap: float,
    calculate_pe: Callable[..., float | None],
    calculate_cagr: Callable[..., float | None],
) -> tuple[float | None, float | None, list[str]]:
    details: list[str] = []
    pe_ratio = calculate_pe(market_cap, financial_line_items)
    if pe_ratio is not None:
        details.append(f"Estimated P/E: {pe_ratio:.2f}")
    else:
        details.append("No positive net income => can't compute approximate P/E")

    eps_growth_rate = calculate_cagr(financial_line_items, field="earnings_per_share")
    if eps_growth_rate is not None:
        details.append(f"Annualized EPS growth rate: {eps_growth_rate:.1%}")
    else:
        details.append("Insufficient EPS data to compute growth rate")
    return pe_ratio, eps_growth_rate, details


def _score_lynch_pe_and_peg(pe_ratio: float | None, eps_growth_rate: float | None) -> tuple[int, float | None, list[str]]:
    details: list[str] = []
    raw_score = 0
    peg_ratio = None

    if pe_ratio and eps_growth_rate and eps_growth_rate > 0:
        peg_ratio = pe_ratio / (eps_growth_rate * 100)
        details.append(f"PEG ratio: {peg_ratio:.2f}")

    if pe_ratio is not None:
        if pe_ratio < 15:
            raw_score += 2
        elif pe_ratio < 25:
            raw_score += 1

    if peg_ratio is not None:
        if peg_ratio < 1:
            raw_score += 3
        elif peg_ratio < 2:
            raw_score += 2
        elif peg_ratio < 3:
            raw_score += 1

    return raw_score, peg_ratio, details
