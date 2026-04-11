def _score_buffett_fundamental_roe(latest_metrics) -> tuple[int, str]:
    if latest_metrics.return_on_equity and latest_metrics.return_on_equity > 0.15:
        return 2, f"Strong ROE of {latest_metrics.return_on_equity:.1%}"
    if latest_metrics.return_on_equity:
        return 0, f"Weak ROE of {latest_metrics.return_on_equity:.1%}"
    return 0, "ROE data not available"


def _score_buffett_debt_to_equity(latest_metrics) -> tuple[int, str]:
    if latest_metrics.debt_to_equity and latest_metrics.debt_to_equity < 0.5:
        return 2, "Conservative debt levels"
    if latest_metrics.debt_to_equity:
        return 0, f"High debt to equity ratio of {latest_metrics.debt_to_equity:.1f}"
    return 0, "Debt to equity data not available"


def _score_buffett_operating_margin(latest_metrics) -> tuple[int, str]:
    if latest_metrics.operating_margin and latest_metrics.operating_margin > 0.15:
        return 2, "Strong operating margins"
    if latest_metrics.operating_margin:
        return 0, f"Weak operating margin of {latest_metrics.operating_margin:.1%}"
    return 0, "Operating margin data not available"


def _score_buffett_current_ratio(latest_metrics) -> tuple[int, str]:
    if latest_metrics.current_ratio and latest_metrics.current_ratio > 1.5:
        return 1, "Good liquidity position"
    if latest_metrics.current_ratio:
        return 0, f"Weak liquidity with current ratio of {latest_metrics.current_ratio:.1f}"
    return 0, "Current ratio data not available"


def _analyze_buffett_earnings_consistency(financial_line_items: list) -> tuple[int, str]:
    earnings_values = [getattr(item, "net_income", None) for item in financial_line_items if getattr(item, "net_income", None) is not None]
    if len(earnings_values) < 4:
        return 0, "Insufficient earnings data for trend analysis"

    earnings_growth = all(earnings_values[index] > earnings_values[index + 1] for index in range(len(earnings_values) - 1))
    if earnings_growth:
        return 3, "Consistent earnings growth over past periods"
    return 0, "Inconsistent earnings growth pattern"


def _score_buffett_roe_consistency(historical_roes: list[float]) -> tuple[int, str]:
    if len(historical_roes) < 5:
        return 0, "Insufficient ROE history for moat analysis"

    high_roe_periods = sum(1 for roe in historical_roes if roe > 0.15)
    roe_consistency = high_roe_periods / len(historical_roes)
    if roe_consistency >= 0.8:
        avg_roe = sum(historical_roes) / len(historical_roes)
        return 2, f"Excellent ROE consistency: {high_roe_periods}/{len(historical_roes)} periods >15% (avg: {avg_roe:.1%}) - indicates durable competitive advantage"
    if roe_consistency >= 0.6:
        return 1, f"Good ROE performance: {high_roe_periods}/{len(historical_roes)} periods >15%"
    return 0, f"Inconsistent ROE: only {high_roe_periods}/{len(historical_roes)} periods >15%"


def _score_buffett_margin_strength(historical_margins: list[float]) -> tuple[int, str | None]:
    if len(historical_margins) < 5:
        return 0, None

    avg_margin = sum(historical_margins) / len(historical_margins)
    recent_margins = historical_margins[:3]
    older_margins = historical_margins[-3:]
    recent_avg = sum(recent_margins) / len(recent_margins)
    older_avg = sum(older_margins) / len(older_margins)

    if avg_margin > 0.2 and recent_avg >= older_avg:
        return 1, f"Strong and stable operating margins (avg: {avg_margin:.1%}) indicate pricing power moat"
    if avg_margin > 0.15:
        return 0, f"Decent operating margins (avg: {avg_margin:.1%}) suggest some competitive advantage"
    return 0, f"Low operating margins (avg: {avg_margin:.1%}) suggest limited pricing power"


def _score_buffett_asset_efficiency(metrics: list) -> tuple[int, str | None]:
    asset_turnovers = [m.asset_turnover for m in metrics if hasattr(m, "asset_turnover") and m.asset_turnover is not None]
    if len(asset_turnovers) >= 3 and any(turnover > 1.0 for turnover in asset_turnovers):
        return 1, "Efficient asset utilization suggests operational moat"
    return 0, None


def _score_buffett_performance_stability(historical_roes: list[float], historical_margins: list[float]) -> tuple[int, str | None]:
    if not (len(historical_roes) >= 5 and len(historical_margins) >= 5):
        return 0, None

    roe_avg = sum(historical_roes) / len(historical_roes)
    roe_variance = sum((roe - roe_avg) ** 2 for roe in historical_roes) / len(historical_roes)
    roe_stability = 1 - (roe_variance**0.5) / roe_avg if roe_avg > 0 else 0

    margin_avg = sum(historical_margins) / len(historical_margins)
    margin_variance = sum((margin - margin_avg) ** 2 for margin in historical_margins) / len(historical_margins)
    margin_stability = 1 - (margin_variance**0.5) / margin_avg if margin_avg > 0 else 0

    overall_stability = (roe_stability + margin_stability) / 2
    if overall_stability > 0.7:
        return 1, f"High performance stability ({overall_stability:.1%}) suggests strong competitive moat"
    return 0, None


def _resolve_buffett_conservative_growth(financial_line_items: list) -> float:
    historical_earnings = [item.net_income for item in financial_line_items[:5] if hasattr(item, "net_income") and item.net_income]
    if len(historical_earnings) < 3:
        return 0.03

    oldest_earnings = historical_earnings[-1]
    latest_earnings = historical_earnings[0]
    years = len(historical_earnings) - 1

    if oldest_earnings > 0 and latest_earnings > 0:
        historical_growth = ((latest_earnings / oldest_earnings) ** (1 / years)) - 1
        historical_growth = max(-0.05, min(historical_growth, 0.15))
        return historical_growth * 0.7
    if oldest_earnings > 0 and latest_earnings <= 0:
        return -0.05
    return 0.03


def _resolve_buffett_dcf_assumptions(conservative_growth: float) -> dict[str, float | int]:
    return {
        "stage1_growth": min(conservative_growth, 0.08),
        "stage2_growth": min(conservative_growth * 0.5, 0.04),
        "terminal_growth": 0.025,
        "discount_rate": 0.10,
        "stage1_years": 5,
        "stage2_years": 5,
        "historical_growth": conservative_growth,
    }


def _calculate_buffett_dcf_components(owner_earnings: float, assumptions: dict[str, float | int]) -> dict[str, float]:
    stage1_growth = float(assumptions["stage1_growth"])
    stage2_growth = float(assumptions["stage2_growth"])
    terminal_growth = float(assumptions["terminal_growth"])
    discount_rate = float(assumptions["discount_rate"])
    stage1_years = int(assumptions["stage1_years"])
    stage2_years = int(assumptions["stage2_years"])

    stage1_pv = 0.0
    for year in range(1, stage1_years + 1):
        future_earnings = owner_earnings * (1 + stage1_growth) ** year
        stage1_pv += future_earnings / (1 + discount_rate) ** year

    stage2_pv = 0.0
    stage1_final_earnings = owner_earnings * (1 + stage1_growth) ** stage1_years
    for year in range(1, stage2_years + 1):
        future_earnings = stage1_final_earnings * (1 + stage2_growth) ** year
        stage2_pv += future_earnings / (1 + discount_rate) ** (stage1_years + year)

    final_earnings = stage1_final_earnings * (1 + stage2_growth) ** stage2_years
    terminal_earnings = final_earnings * (1 + terminal_growth)
    terminal_value = terminal_earnings / (discount_rate - terminal_growth)
    terminal_pv = terminal_value / (1 + discount_rate) ** (stage1_years + stage2_years)

    intrinsic_value = stage1_pv + stage2_pv + terminal_pv
    return {
        "stage1_pv": stage1_pv,
        "stage2_pv": stage2_pv,
        "terminal_pv": terminal_pv,
        "intrinsic_value": intrinsic_value,
        "conservative_intrinsic_value": intrinsic_value * 0.85,
    }


def _build_buffett_intrinsic_value_details(currency_symbol: str, owner_earnings: float, assumptions: dict[str, float | int], dcf_components: dict[str, float]) -> list[str]:
    return [
        f"Using three-stage DCF: Stage 1 ({float(assumptions['stage1_growth']):.1%}, {int(assumptions['stage1_years'])}y), Stage 2 ({float(assumptions['stage2_growth']):.1%}, {int(assumptions['stage2_years'])}y), Terminal ({float(assumptions['terminal_growth']):.1%})",
        f"Stage 1 PV: {currency_symbol}{dcf_components['stage1_pv']:,.0f}",
        f"Stage 2 PV: {currency_symbol}{dcf_components['stage2_pv']:,.0f}",
        f"Terminal PV: {currency_symbol}{dcf_components['terminal_pv']:,.0f}",
        f"Total IV: {currency_symbol}{dcf_components['intrinsic_value']:,.0f}",
        f"Conservative IV (15% haircut): {currency_symbol}{dcf_components['conservative_intrinsic_value']:,.0f}",
        f"Owner earnings: {currency_symbol}{owner_earnings:,.0f}",
        f"Discount rate: {float(assumptions['discount_rate']):.1%}",
    ]


def _resolve_buffett_owner_earnings_inputs(financial_line_items: list) -> tuple[dict[str, float] | None, list[str]]:
    latest = financial_line_items[0]
    details: list[str] = []

    net_income = getattr(latest, "net_income", None)
    depreciation = getattr(latest, "depreciation_and_amortization", None)
    capex = getattr(latest, "capital_expenditure", None)

    if not all([net_income is not None, depreciation is not None, capex is not None]):
        if depreciation is None and len(financial_line_items) >= 2:
            for hist_item in financial_line_items[1:]:
                hist_depr = getattr(hist_item, "depreciation_and_amortization", None)
                if hist_depr is not None:
                    depreciation = hist_depr
                    details.append(f"Note: Using historical depreciation as fallback (¥{depreciation:,.0f})")
                    break
        if depreciation is None and capex is not None:
            depreciation = abs(capex) * 0.6
            details.append(f"Note: Estimated depreciation as 60% of capex (¥{depreciation:,.0f})")
        if not all([net_income is not None, depreciation is not None, capex is not None]):
            missing = []
            if net_income is None:
                missing.append("net income")
            if depreciation is None:
                missing.append("depreciation")
            if capex is None:
                missing.append("capital expenditure")
            return None, [f"Missing components: {', '.join(missing)}"]

    return {
        "net_income": net_income,
        "depreciation": depreciation,
        "capex": capex,
    }, details


def _resolve_buffett_working_capital_change(financial_line_items: list, currency_symbol: str) -> tuple[float, str | None]:
    if len(financial_line_items) < 2:
        return 0, None

    latest = financial_line_items[0]
    previous = financial_line_items[1]
    try:
        current_assets_current = getattr(latest, "current_assets", None)
        current_liab_current = getattr(latest, "current_liabilities", None)
        current_assets_previous = getattr(previous, "current_assets", None)
        current_liab_previous = getattr(previous, "current_liabilities", None)

        if all([current_assets_current, current_liab_current, current_assets_previous, current_liab_previous]):
            wc_current = current_assets_current - current_liab_current
            wc_previous = current_assets_previous - current_liab_previous
            working_capital_change = wc_current - wc_previous
            return working_capital_change, f"Working capital change: {currency_symbol}{working_capital_change:,.0f}"
    except Exception:
        return 0, None

    return 0, None


def _build_buffett_owner_earnings_details(
    currency_symbol: str,
    net_income: float,
    depreciation: float,
    maintenance_capex: float,
    owner_earnings: float,
    details: list[str],
) -> list[str]:
    if owner_earnings < net_income * 0.3:
        details.append("Warning: Owner earnings significantly below net income - high capex intensity")
    if maintenance_capex > depreciation * 2:
        details.append("Warning: Estimated maintenance capex seems high relative to depreciation")

    details.extend(
        [
            f"Net income: {currency_symbol}{net_income:,.0f}",
            f"Depreciation: {currency_symbol}{depreciation:,.0f}",
            f"Estimated maintenance capex: {currency_symbol}{maintenance_capex:,.0f}",
            f"Owner earnings: {currency_symbol}{owner_earnings:,.0f}",
        ]
    )
    return details


def _score_buffett_gross_margin_trend(gross_margins: list[float]) -> tuple[int, str | None]:
    if len(gross_margins) < 3:
        return 0, None

    recent_avg = sum(gross_margins[:2]) / 2 if len(gross_margins) >= 2 else gross_margins[0]
    older_avg = sum(gross_margins[-2:]) / 2 if len(gross_margins) >= 2 else gross_margins[-1]

    if recent_avg > older_avg + 0.02:
        return 3, "Expanding gross margins indicate strong pricing power"
    if recent_avg > older_avg:
        return 2, "Improving gross margins suggest good pricing power"
    if abs(recent_avg - older_avg) < 0.01:
        return 1, "Stable gross margins during economic uncertainty"
    return 0, "Declining gross margins may indicate pricing pressure"


def _score_buffett_gross_margin_level(gross_margins: list[float]) -> tuple[int, str | None]:
    if not gross_margins:
        return 0, None

    avg_margin = sum(gross_margins) / len(gross_margins)
    if avg_margin > 0.5:
        return 2, f"Consistently high gross margins ({avg_margin:.1%}) indicate strong pricing power"
    if avg_margin > 0.3:
        return 1, f"Good gross margins ({avg_margin:.1%}) suggest decent pricing power"
    return 0, None


def _collect_buffett_capex_ratio_inputs(financial_line_items: list) -> list[float]:
    capex_ratios = []
    for item in financial_line_items[:5]:
        if hasattr(item, "capital_expenditure") and hasattr(item, "revenue"):
            if item.capital_expenditure and item.revenue and item.revenue > 0:
                capex_ratios.append(abs(item.capital_expenditure) / item.revenue)
    return capex_ratios


def _resolve_buffett_maintenance_capex_methods(financial_line_items: list) -> tuple[float, float, float]:
    latest_depreciation = getattr(financial_line_items[0], "depreciation_and_amortization", None) or 0
    latest_capex = abs(getattr(financial_line_items[0], "capital_expenditure", None) or 0)
    method_1 = latest_capex * 0.85
    method_2 = latest_depreciation

    latest_revenue = financial_line_items[0].revenue if hasattr(financial_line_items[0], "revenue") and financial_line_items[0].revenue else 0
    return method_1, method_2, latest_revenue


def _resolve_buffett_maintenance_capex_value(capex_ratios: list[float], method_1: float, method_2: float, latest_revenue: float) -> float:
    if len(capex_ratios) >= 3:
        avg_capex_ratio = sum(capex_ratios) / len(capex_ratios)
        method_3 = avg_capex_ratio * latest_revenue if latest_revenue else 0
        return sorted([method_1, method_2, method_3])[1]
    return max(method_1, method_2)
