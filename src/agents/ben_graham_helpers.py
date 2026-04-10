def _score_graham_current_ratio(current_assets: float, current_liabilities: float) -> tuple[int, str]:
    if current_liabilities <= 0:
        return 0, "Cannot compute current ratio (missing or zero current_liabilities)."

    current_ratio = current_assets / current_liabilities
    if current_ratio >= 2.0:
        return 2, f"Current ratio = {current_ratio:.2f} (>=2.0: solid)."
    if current_ratio >= 1.5:
        return 1, f"Current ratio = {current_ratio:.2f} (moderately strong)."
    return 0, f"Current ratio = {current_ratio:.2f} (<1.5: weaker liquidity)."


def _score_graham_debt_ratio(total_assets: float, total_liabilities: float) -> tuple[int, str]:
    if total_assets <= 0:
        return 0, "Cannot compute debt ratio (missing total_assets)."

    debt_ratio = total_liabilities / total_assets
    if debt_ratio < 0.5:
        return 2, f"Debt ratio = {debt_ratio:.2f}, under 0.50 (conservative)."
    if debt_ratio < 0.8:
        return 1, f"Debt ratio = {debt_ratio:.2f}, somewhat high but could be acceptable."
    return 0, f"Debt ratio = {debt_ratio:.2f}, quite high by Graham standards."


def _score_graham_dividend_record(financial_line_items: list) -> tuple[int, str]:
    div_periods = [getattr(item, "dividends_and_other_cash_distributions", None) for item in financial_line_items if getattr(item, "dividends_and_other_cash_distributions", None) is not None]
    if not div_periods:
        return 0, "No dividend data available to assess payout consistency."

    div_paid_years = sum(1 for d in div_periods if d < 0)
    if div_paid_years == 0:
        return 0, "Company did not pay dividends in these periods."
    if div_paid_years >= (len(div_periods) // 2 + 1):
        return 1, "Company paid dividends in the majority of the reported years."
    return 0, "Company has some dividend payments, but not most years."
