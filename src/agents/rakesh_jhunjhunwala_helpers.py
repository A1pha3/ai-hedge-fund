def _score_rakesh_roe(latest) -> tuple[int, str]:
    if getattr(latest, "net_income", None) and latest.net_income > 0 and getattr(latest, "total_assets", None) and getattr(latest, "total_liabilities", None) and latest.total_assets and latest.total_liabilities:
        shareholders_equity = latest.total_assets - latest.total_liabilities
        if shareholders_equity > 0:
            roe = (latest.net_income / shareholders_equity) * 100
            if roe > 20:
                return 3, f"Excellent ROE: {roe:.1f}%"
            if roe > 15:
                return 2, f"Good ROE: {roe:.1f}%"
            if roe > 10:
                return 1, f"Decent ROE: {roe:.1f}%"
            return 0, f"Low ROE: {roe:.1f}%"
        return 0, "Negative shareholders equity"
    return 0, "Unable to calculate ROE - missing data"


def _score_rakesh_operating_margin(latest) -> tuple[int, str]:
    if getattr(latest, "operating_income", None) and latest.operating_income and getattr(latest, "revenue", None) and latest.revenue and latest.revenue > 0:
        operating_margin = (latest.operating_income / latest.revenue) * 100
        if operating_margin > 20:
            return 2, f"Excellent operating margin: {operating_margin:.1f}%"
        if operating_margin > 15:
            return 1, f"Good operating margin: {operating_margin:.1f}%"
        if operating_margin > 0:
            return 0, f"Positive operating margin: {operating_margin:.1f}%"
        return 0, f"Negative operating margin: {operating_margin:.1f}%"
    return 0, "Unable to calculate operating margin"


def _score_rakesh_eps_cagr(financial_line_items: list) -> tuple[int, str]:
    eps_values = [
        getattr(item, "earnings_per_share", None)
        for item in financial_line_items
        if getattr(item, "earnings_per_share", None) is not None and getattr(item, "earnings_per_share", None) > 0
    ]
    if len(eps_values) < 3:
        return 0, "Insufficient EPS data for growth analysis"

    initial_eps = eps_values[-1]
    final_eps = eps_values[0]
    years = len(eps_values) - 1
    if initial_eps <= 0:
        return 0, "Cannot calculate EPS growth from negative base"

    eps_cagr = ((final_eps / initial_eps) ** (1 / years) - 1) * 100
    if eps_cagr > 20:
        return 3, f"High EPS CAGR: {eps_cagr:.1f}%"
    if eps_cagr > 15:
        return 2, f"Good EPS CAGR: {eps_cagr:.1f}%"
    if eps_cagr > 10:
        return 1, f"Moderate EPS CAGR: {eps_cagr:.1f}%"
    return 0, f"Low EPS CAGR: {eps_cagr:.1f}%"


def _score_rakesh_revenue_cagr(revenue_cagr: float | None) -> tuple[int, str]:
    if revenue_cagr is None:
        return 0, "Insufficient revenue data for CAGR calculation"

    revenue_cagr_pct = revenue_cagr * 100
    if revenue_cagr_pct > 20:
        return 3, f"Excellent revenue CAGR: {revenue_cagr_pct:.1f}%"
    if revenue_cagr_pct > 15:
        return 2, f"Good revenue CAGR: {revenue_cagr_pct:.1f}%"
    if revenue_cagr_pct > 10:
        return 1, f"Moderate revenue CAGR: {revenue_cagr_pct:.1f}%"
    return 0, f"Low revenue CAGR: {revenue_cagr_pct:.1f}%"


def _score_rakesh_income_cagr(financial_line_items: list) -> tuple[int, str]:
    net_incomes = [
        getattr(item, "net_income", None)
        for item in financial_line_items
        if getattr(item, "net_income", None) is not None and getattr(item, "net_income", None) > 0
    ]
    if len(net_incomes) < 3:
        return 0, "Insufficient net income data for CAGR calculation"

    initial_income = net_incomes[-1]
    final_income = net_incomes[0]
    years = len(net_incomes) - 1
    if initial_income <= 0:
        return 0, "Cannot calculate income CAGR from zero base"

    income_cagr = ((final_income / initial_income) ** (1 / years) - 1) * 100
    if income_cagr > 25:
        return 3, f"Excellent income CAGR: {income_cagr:.1f}%"
    if income_cagr > 20:
        return 2, f"High income CAGR: {income_cagr:.1f}%"
    if income_cagr > 15:
        return 1, f"Good income CAGR: {income_cagr:.1f}%"
    return 0, f"Moderate income CAGR: {income_cagr:.1f}%"


def _score_rakesh_growth_consistency(revenues: list) -> tuple[int, str] | None:
    if len(revenues) < 3:
        return None

    declining_years = sum(1 for index in range(1, len(revenues)) if revenues[index - 1] > revenues[index])
    consistency_ratio = 1 - (declining_years / (len(revenues) - 1))
    if consistency_ratio >= 0.8:
        return 1, f"Consistent growth pattern ({consistency_ratio*100:.0f}% of years)"
    return 0, f"Inconsistent growth pattern ({consistency_ratio*100:.0f}% of years)"


def _score_rakesh_quality_roe_factor(latest) -> float:
    if getattr(latest, "net_income", None) and getattr(latest, "total_assets", None) and getattr(latest, "total_liabilities", None) and latest.total_assets and latest.total_liabilities:
        shareholders_equity = latest.total_assets - latest.total_liabilities
        if shareholders_equity > 0 and latest.net_income:
            roe = latest.net_income / shareholders_equity
            if roe > 0.20:
                return 1.0
            if roe > 0.15:
                return 0.8
            if roe > 0.10:
                return 0.6
            return 0.3
        return 0.0
    return 0.5


def _score_rakesh_quality_debt_factor(latest) -> float:
    if getattr(latest, "total_assets", None) and getattr(latest, "total_liabilities", None) and latest.total_assets and latest.total_liabilities:
        debt_ratio = latest.total_liabilities / latest.total_assets
        if debt_ratio < 0.3:
            return 1.0
        if debt_ratio < 0.5:
            return 0.7
        if debt_ratio < 0.7:
            return 0.4
        return 0.1
    return 0.5


def _score_rakesh_quality_growth_consistency(financial_line_items: list) -> float:
    net_incomes = [
        getattr(item, "net_income", None)
        for item in financial_line_items[:4]
        if getattr(item, "net_income", None) is not None and getattr(item, "net_income", None) > 0
    ]
    if len(net_incomes) < 3:
        return 0.5

    declining_years = sum(1 for index in range(1, len(net_incomes)) if net_incomes[index - 1] > net_incomes[index])
    return 1 - (declining_years / (len(net_incomes) - 1))


def _resolve_rakesh_historical_growth(net_incomes: list[float]) -> float:
    initial_income = net_incomes[-1]
    final_income = net_incomes[0]
    years = len(net_incomes) - 1
    if initial_income <= 0:
        return 0.05
    return (final_income / initial_income) ** (1 / years) - 1


def _resolve_rakesh_sustainable_growth(historical_growth: float) -> float:
    if historical_growth > 0.25:
        return 0.20
    if historical_growth > 0.15:
        return historical_growth * 0.8
    if historical_growth > 0.05:
        return historical_growth * 0.9
    return 0.05


def _resolve_rakesh_discount_profile(quality_score: float) -> tuple[float, int]:
    if quality_score >= 0.8:
        return 0.12, 18
    if quality_score >= 0.6:
        return 0.15, 15
    return 0.18, 12


def _calculate_rakesh_projected_dcf_value(current_earnings: float, sustainable_growth: float, discount_rate: float, terminal_multiple: int) -> float:
    dcf_value = 0.0
    for year in range(1, 6):
        projected_earnings = current_earnings * ((1 + sustainable_growth) ** year)
        dcf_value += projected_earnings / ((1 + discount_rate) ** year)

    year_5_earnings = current_earnings * ((1 + sustainable_growth) ** 5)
    terminal_value = (year_5_earnings * terminal_multiple) / ((1 + discount_rate) ** 5)
    return dcf_value + terminal_value
