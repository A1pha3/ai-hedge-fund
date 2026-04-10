from collections.abc import Callable


def _score_ackman_revenue_growth(financial_line_items: list, calculate_cagr: Callable[..., float | None]) -> tuple[int, str]:
    growth_rate = calculate_cagr(financial_line_items, field="revenue")
    if growth_rate is None:
        return 0, "Insufficient revenue data for CAGR calculation."
    if growth_rate > 0.15:
        return 2, f"Revenue CAGR of {growth_rate:.1%} over the period (strong growth)."
    if growth_rate > 0.05:
        return 1, f"Revenue CAGR of {growth_rate:.1%} (moderate growth)."
    return 0, f"Revenue CAGR of {growth_rate:.1%} (weak growth)."


def _score_ackman_profitability_and_cash_flow(financial_line_items: list) -> tuple[int, list[str]]:
    score = 0
    details: list[str] = []
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

    return score, details


def _score_ackman_roe(metrics: list) -> tuple[int, str]:
    latest_metrics = metrics[0]
    if latest_metrics.return_on_equity and latest_metrics.return_on_equity > 0.15:
        return 2, f"High ROE of {latest_metrics.return_on_equity:.1%}, indicating a competitive advantage."
    if latest_metrics.return_on_equity:
        return 0, f"ROE of {latest_metrics.return_on_equity:.1%} is moderate."
    return 0, "ROE data not available."


def _score_ackman_leverage(financial_line_items: list) -> tuple[int, str]:
    debt_to_equity_vals = [getattr(item, "debt_to_equity", None) for item in financial_line_items if getattr(item, "debt_to_equity", None) is not None]
    if debt_to_equity_vals:
        below_one_count = sum(1 for d in debt_to_equity_vals if d < 1.0)
        if below_one_count >= (len(debt_to_equity_vals) // 2 + 1):
            return 2, "Debt-to-equity < 1.0 for the majority of periods (reasonable leverage)."
        return 0, "Debt-to-equity >= 1.0 in many periods (could be high leverage)."

    liab_to_assets = []
    for item in financial_line_items:
        total_liabilities = getattr(item, "total_liabilities", None)
        total_assets = getattr(item, "total_assets", None)
        if total_liabilities and total_assets and total_assets > 0:
            liab_to_assets.append(total_liabilities / total_assets)

    if not liab_to_assets:
        return 0, "No consistent leverage ratio data available."

    below_50pct_count = sum(1 for ratio in liab_to_assets if ratio < 0.5)
    if below_50pct_count >= (len(liab_to_assets) // 2 + 1):
        return 2, "Liabilities-to-assets < 50% for majority of periods."
    return 0, "Liabilities-to-assets >= 50% in many periods."


def _score_ackman_dividends(financial_line_items: list) -> tuple[int, str]:
    dividends_list = [getattr(item, "dividends_and_other_cash_distributions", None) for item in financial_line_items if getattr(item, "dividends_and_other_cash_distributions", None) is not None]
    if not dividends_list:
        return 0, "No dividend data found across periods."

    paying_dividends_count = sum(1 for d in dividends_list if d < 0)
    if paying_dividends_count >= (len(dividends_list) // 2 + 1):
        return 1, "Company has a history of returning capital to shareholders (dividends)."
    return 0, "Dividends not consistently paid or no data on distributions."


def _score_ackman_buybacks(financial_line_items: list) -> tuple[int, str]:
    shares = [getattr(item, "outstanding_shares", None) for item in financial_line_items if getattr(item, "outstanding_shares", None) is not None]
    if len(shares) < 2:
        return 0, "No multi-period share count data to assess buybacks."
    if shares[0] < shares[-1]:
        return 1, "Outstanding shares have decreased over time (possible buybacks)."
    return 0, "Outstanding shares have not decreased over the available periods."
