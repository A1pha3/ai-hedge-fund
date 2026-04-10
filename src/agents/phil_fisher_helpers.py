import statistics
from collections.abc import Callable


def _score_fisher_revenue_growth(financial_line_items: list, calculate_cagr: Callable[..., float | None]) -> tuple[int, str]:
    rev_growth = calculate_cagr(financial_line_items, field="revenue")
    if rev_growth is None:
        return 0, "Insufficient revenue data for CAGR calculation."
    if rev_growth > 0.20:
        return 3, f"Very strong annualized revenue growth: {rev_growth:.1%}"
    if rev_growth > 0.10:
        return 2, f"Moderate annualized revenue growth: {rev_growth:.1%}"
    if rev_growth > 0.03:
        return 1, f"Slight annualized revenue growth: {rev_growth:.1%}"
    return 0, f"Minimal or negative annualized revenue growth: {rev_growth:.1%}"


def _score_fisher_eps_growth(financial_line_items: list, calculate_cagr: Callable[..., float | None]) -> tuple[int, str]:
    eps_growth = calculate_cagr(financial_line_items, field="earnings_per_share")
    if eps_growth is None:
        return 0, "Insufficient EPS data for CAGR calculation."
    if eps_growth > 0.20:
        return 3, f"Very strong annualized EPS growth: {eps_growth:.1%}"
    if eps_growth > 0.10:
        return 2, f"Moderate annualized EPS growth: {eps_growth:.1%}"
    if eps_growth > 0.03:
        return 1, f"Slight annualized EPS growth: {eps_growth:.1%}"
    return 0, f"Minimal or negative annualized EPS growth: {eps_growth:.1%}"


def _score_fisher_rnd_intensity(financial_line_items: list) -> tuple[int, str]:
    rnd_values = [getattr(fi, "research_and_development", None) for fi in financial_line_items if getattr(fi, "research_and_development", None) is not None]
    revenues = [getattr(fi, "revenue", None) for fi in financial_line_items if getattr(fi, "revenue", None) is not None]
    if not (rnd_values and revenues and len(rnd_values) == len(revenues)):
        return 0, "Insufficient R&D data to evaluate"

    recent_rnd = rnd_values[0]
    recent_rev = revenues[0] if revenues[0] else 1e-9
    rnd_ratio = recent_rnd / recent_rev
    if 0.03 <= rnd_ratio <= 0.15:
        return 3, f"R&D ratio {rnd_ratio:.1%} indicates significant investment in future growth"
    if rnd_ratio > 0.15:
        return 2, f"R&D ratio {rnd_ratio:.1%} is very high (could be good if well-managed)"
    if rnd_ratio > 0.0:
        return 1, f"R&D ratio {rnd_ratio:.1%} is somewhat low but still positive"
    return 0, "No meaningful R&D expense ratio"


def _score_fisher_operating_margin_consistency(op_margins: list[float]) -> tuple[int, str]:
    if len(op_margins) < 2:
        return 0, "Not enough operating margin data points"

    oldest_op_margin = op_margins[-1]
    newest_op_margin = op_margins[0]
    if newest_op_margin >= oldest_op_margin > 0:
        return 2, f"Operating margin stable or improving ({oldest_op_margin:.1%} -> {newest_op_margin:.1%})"
    if newest_op_margin > 0:
        return 1, "Operating margin positive but slightly declined"
    return 0, "Operating margin may be negative or uncertain"


def _score_fisher_gross_margin(financial_line_items: list) -> tuple[int, str]:
    gm_values = [getattr(fi, "gross_margin", None) for fi in financial_line_items if getattr(fi, "gross_margin", None) is not None]
    if not gm_values:
        return 0, "No gross margin data available"

    recent_gm = gm_values[0]
    if recent_gm > 0.5:
        return 2, f"Strong gross margin: {recent_gm:.1%}"
    if recent_gm > 0.3:
        return 1, f"Moderate gross margin: {recent_gm:.1%}"
    return 0, f"Low gross margin: {recent_gm:.1%}"


def _score_fisher_margin_volatility(op_margins: list[float]) -> tuple[int, str]:
    if len(op_margins) < 3:
        return 0, "Not enough margin data points for volatility check"

    stdev = statistics.pstdev(op_margins)
    if stdev < 0.02:
        return 2, "Operating margin extremely stable over multiple years"
    if stdev < 0.05:
        return 1, "Operating margin reasonably stable"
    return 0, "Operating margin volatility is high"


def _score_fisher_roe(ni_values: list, eq_values: list) -> tuple[int, str]:
    if not (ni_values and eq_values and len(ni_values) == len(eq_values)):
        return 0, "Insufficient data for ROE calculation"

    recent_ni = ni_values[0]
    recent_eq = eq_values[0] if eq_values[0] else 1e-9
    if recent_ni <= 0:
        return 0, "Recent net income is zero or negative, hurting ROE"

    roe = recent_ni / recent_eq
    if roe > 0.2:
        return 3, f"High ROE: {roe:.1%}"
    if roe > 0.1:
        return 2, f"Moderate ROE: {roe:.1%}"
    if roe > 0:
        return 1, f"Positive but low ROE: {roe:.1%}"
    return 0, f"ROE is near zero or negative: {roe:.1%}"


def _score_fisher_debt_to_equity(financial_line_items: list, eq_values: list) -> tuple[int, str]:
    dte = None
    dte_direct = getattr(financial_line_items[0], "debt_to_equity", None) if financial_line_items else None
    if dte_direct is not None:
        dte = dte_direct
    else:
        debt_values = [getattr(fi, "total_debt", None) for fi in financial_line_items if getattr(fi, "total_debt", None) is not None]
        if debt_values and eq_values and len(debt_values) == len(eq_values):
            recent_equity = eq_values[0] if eq_values[0] else 1e-9
            dte = debt_values[0] / recent_equity

    if dte is None:
        return 0, "No debt/equity data available"
    if dte < 0.3:
        return 2, f"Low debt-to-equity: {dte:.2f}"
    if dte < 1.0:
        return 1, f"Manageable debt-to-equity: {dte:.2f}"
    return 0, f"High debt-to-equity: {dte:.2f}"


def _score_fisher_fcf_consistency(financial_line_items: list) -> tuple[int, str]:
    fcf_values = [getattr(fi, "free_cash_flow", None) for fi in financial_line_items if getattr(fi, "free_cash_flow", None) is not None]
    if not (fcf_values and len(fcf_values) >= 2):
        return 0, "Insufficient or no FCF data to check consistency"

    positive_fcf_count = sum(1 for x in fcf_values if x and x > 0)
    ratio = positive_fcf_count / len(fcf_values)
    if ratio > 0.8:
        return 1, f"Majority of periods have positive FCF ({positive_fcf_count}/{len(fcf_values)})"
    return 0, "Free cash flow is inconsistent or often negative"
