from collections.abc import Callable


def _calculate_yoy_growth_rates(line_items: list, field: str = "revenue") -> list[float]:
    pairs = []
    for item in line_items:
        val = getattr(item, field, None)
        period = getattr(item, "report_period", "") or ""
        if val is not None and val > 0 and len(period) >= 8:
            pairs.append((val, period))

    if len(pairs) < 2:
        return []

    quarter_map: dict[str, list[tuple[float, str]]] = {}
    for val, period in pairs:
        quarter_key = period[4:8]
        year = period[:4]
        quarter_map.setdefault(quarter_key, []).append((val, year))

    growth_rates = []
    for quarter_key, year_data in quarter_map.items():
        year_data.sort(key=lambda x: x[1], reverse=True)
        for i in range(len(year_data) - 1):
            newer_val, newer_year = year_data[i]
            older_val, _ = year_data[i + 1]
            if older_val > 0:
                growth_rate = (newer_val - older_val) / older_val
                growth_rates.append((growth_rate, newer_year + quarter_key))

    growth_rates.sort(key=lambda x: x[1], reverse=True)
    return [rate for rate, _ in growth_rates]


def _score_cathie_revenue_disruption(
    financial_line_items: list,
    calculate_cagr: Callable[..., float | None],
    calculate_yoy: Callable[..., list[float]],
) -> tuple[int, list[str]]:
    details: list[str] = []
    revenues = [getattr(item, "revenue", None) for item in financial_line_items if getattr(item, "revenue", None) is not None]
    if len(revenues) < 3:
        return 0, ["Insufficient revenue data for growth analysis"]

    score = 0
    cagr_growth = calculate_cagr(financial_line_items, field="revenue")
    growth_rates = calculate_yoy(financial_line_items, field="revenue")

    if len(growth_rates) >= 2 and growth_rates[0] > growth_rates[-1]:
        score += 2
        details.append(f"Revenue growth is accelerating: {(growth_rates[0]*100):.1f}% vs {(growth_rates[-1]*100):.1f}%")

    if cagr_growth is not None:
        if cagr_growth > 1.0:
            score += 3
            details.append(f"Exceptional revenue CAGR: {cagr_growth:.1%}")
        elif cagr_growth > 0.5:
            score += 2
            details.append(f"Strong revenue CAGR: {cagr_growth:.1%}")
        elif cagr_growth > 0.2:
            score += 1
            details.append(f"Moderate revenue CAGR: {cagr_growth:.1%}")
    else:
        details.append("Insufficient revenue data for CAGR calculation")

    return score, details


def _score_cathie_gross_margin_profile(financial_line_items: list) -> tuple[int, list[str]]:
    gross_margins = [item.gross_margin for item in financial_line_items if hasattr(item, "gross_margin") and item.gross_margin is not None]
    if len(gross_margins) < 2:
        return 0, ["Insufficient gross margin data"]

    score = 0
    details: list[str] = []
    margin_trend = gross_margins[0] - gross_margins[-1]
    if margin_trend > 0.05:
        score += 2
        details.append(f"Expanding gross margins: +{(margin_trend*100):.1f}%")
    elif margin_trend > 0:
        score += 1
        details.append(f"Slightly improving gross margins: +{(margin_trend*100):.1f}%")

    if gross_margins[0] > 0.50:
        score += 2
        details.append(f"High gross margin: {(gross_margins[0]*100):.1f}%")

    return score, details


def _score_cathie_operating_leverage(financial_line_items: list, calculate_cagr: Callable[..., float | None]) -> tuple[int, str | None]:
    revenues = [getattr(item, "revenue", None) for item in financial_line_items if getattr(item, "revenue", None) is not None]
    operating_expenses = [item.operating_expense for item in financial_line_items if hasattr(item, "operating_expense") and item.operating_expense is not None]

    if len(revenues) >= 2 and len(operating_expenses) >= 2:
        rev_growth = calculate_cagr(financial_line_items, field="revenue")
        opex_growth = calculate_cagr(financial_line_items, field="operating_expense")
        if rev_growth is not None and opex_growth is not None and rev_growth > opex_growth:
            return 2, "Positive operating leverage: Revenue growing faster than expenses"
        return 0, None
    return 0, "Insufficient data for operating leverage analysis"


def _score_cathie_rnd_intensity(financial_line_items: list) -> tuple[int, str | None]:
    # R125 / positional-mismatch family: pair R&D with revenue from the SAME period.
    # Filtering each field independently then indexing [0] crossed periods when some
    # items lacked one field (item0 had revenue but no R&D -> rd[0]=item1.R&D over
    # rev[0]=item0.revenue). Pair in one comprehension, like the munger sibling.
    paired = [(item.research_and_development, item.revenue) for item in financial_line_items if hasattr(item, "research_and_development") and item.research_and_development is not None and getattr(item, "revenue", None) is not None]
    if not paired:
        return 0, "No R&D data available"

    recent_rnd, recent_rev = paired[0]
    rd_intensity = recent_rnd / recent_rev if recent_rev != 0 else 0
    if rd_intensity > 0.15:
        return 3, f"High R&D investment: {(rd_intensity*100):.1f}% of revenue"
    if rd_intensity > 0.08:
        return 2, f"Moderate R&D investment: {(rd_intensity*100):.1f}% of revenue"
    if rd_intensity > 0.05:
        return 1, f"Some R&D investment: {(rd_intensity*100):.1f}% of revenue"
    return 0, None


def _score_cathie_rnd_trends(financial_line_items: list) -> tuple[int, list[str]]:
    # R125 / positional-mismatch family: pair R&D with revenue from the SAME period
    # so [0]/[-1] indexing aligns periods (independent filters crossed periods when
    # some items lacked one field, fabricating false "Increasing R&D intensity").
    paired = [(item.research_and_development, item.revenue) for item in financial_line_items if hasattr(item, "research_and_development") and item.research_and_development is not None and getattr(item, "revenue", None) is not None]

    if not (paired and len(paired) >= 2):
        return 0, ["Insufficient R&D data for trend analysis"]

    rd_expenses = [p[0] for p in paired]
    revenues = [p[1] for p in paired]

    score = 0
    details: list[str] = []
    rd_growth = (rd_expenses[0] - rd_expenses[-1]) / abs(rd_expenses[-1]) if rd_expenses[-1] != 0 else 0
    if rd_growth > 0.5:
        score += 3
        details.append(f"Strong R&D investment growth: +{(rd_growth*100):.1f}%")
    elif rd_growth > 0.2:
        score += 2
        details.append(f"Moderate R&D investment growth: +{(rd_growth*100):.1f}%")

    rd_intensity_start = rd_expenses[-1] / revenues[-1] if revenues[-1] and revenues[-1] != 0 else 0
    rd_intensity_end = rd_expenses[0] / revenues[0] if revenues[0] and revenues[0] != 0 else 0
    if rd_intensity_end > rd_intensity_start:
        score += 2
        details.append(f"Increasing R&D intensity: {(rd_intensity_end*100):.1f}% vs {(rd_intensity_start*100):.1f}%")
    return score, details


def _score_cathie_fcf_funding(financial_line_items: list) -> tuple[int, str]:
    fcf_vals = [getattr(item, "free_cash_flow", None) for item in financial_line_items if getattr(item, "free_cash_flow", None) is not None]
    if not (fcf_vals and len(fcf_vals) >= 2):
        return 0, "Insufficient FCF data for analysis"

    fcf_growth = (fcf_vals[0] - fcf_vals[-1]) / abs(fcf_vals[-1]) if fcf_vals[-1] != 0 else 0.0
    positive_fcf_count = sum(1 for f in fcf_vals if f > 0)

    if fcf_growth > 0.3 and positive_fcf_count == len(fcf_vals):
        return 3, "Strong and consistent FCF growth, excellent innovation funding capacity"
    if positive_fcf_count >= len(fcf_vals) * 0.75:
        return 2, "Consistent positive FCF, good innovation funding capacity"
    if positive_fcf_count > len(fcf_vals) * 0.5:
        return 1, "Moderately consistent FCF, adequate innovation funding capacity"
    return 0, None


def _score_cathie_operating_efficiency(financial_line_items: list) -> tuple[int, str]:
    op_margin_vals = [getattr(item, "operating_margin", None) for item in financial_line_items if getattr(item, "operating_margin", None) is not None]
    if not (op_margin_vals and len(op_margin_vals) >= 2):
        return 0, "Insufficient operating margin data"

    margin_trend = op_margin_vals[0] - op_margin_vals[-1]
    if op_margin_vals[0] > 0.15 and margin_trend > 0:
        return 3, f"Strong and improving operating margin: {(op_margin_vals[0]*100):.1f}%"
    if op_margin_vals[0] > 0.10:
        return 2, f"Healthy operating margin: {(op_margin_vals[0]*100):.1f}%"
    if margin_trend > 0:
        return 1, "Improving operating efficiency"
    return 0, None


def _score_cathie_capex_commitment(financial_line_items: list) -> tuple[int, str]:
    # R125 / positional-mismatch family: pair capex with revenue from the SAME period
    # so abs(capex[0])/revenues[0] aligns periods (independent filters crossed periods
    # when some items lacked one field, inflating capex_intensity and flipping scores).
    paired = [(item.capital_expenditure, item.revenue) for item in financial_line_items if hasattr(item, "capital_expenditure") and item.capital_expenditure is not None and getattr(item, "revenue", None) is not None]
    if not (paired and len(paired) >= 2):
        return 0, "Insufficient CAPEX data"

    capex = [p[0] for p in paired]
    revenues = [p[1] for p in paired]

    capex_intensity = abs(capex[0]) / revenues[0] if revenues[0] != 0 else 0
    capex_growth = (abs(capex[0]) - abs(capex[-1])) / abs(capex[-1]) if capex[-1] != 0 else 0

    if capex_intensity > 0.10 and capex_growth > 0.2:
        return 2, "Strong investment in growth infrastructure"
    if capex_intensity > 0.05:
        return 1, "Moderate investment in growth infrastructure"
    return 0, None


def _score_cathie_reinvestment_focus(financial_line_items: list) -> tuple[int, str]:
    # R125 / positional-mismatch family: pair dividends with FCF from the SAME period.
    # Previously dividends[0]/fcf_vals[0] crossed periods when some items lacked one
    # field (e.g. item0 had zero FCF but no dividends -> fcf[0]=0 triggered the
    # ``else 1`` payout, masking item1's real low payout ratio).
    paired = [(item.dividends_and_other_cash_distributions, item.free_cash_flow) for item in financial_line_items if hasattr(item, "dividends_and_other_cash_distributions") and item.dividends_and_other_cash_distributions is not None and getattr(item, "free_cash_flow", None) is not None]
    if not paired:
        return 0, "Insufficient dividend data"

    latest_dividends, latest_fcf = paired[0]
    # R123 / falsy-zero family: dividends == 0 (paid nothing = pure reinvestment) is
    # the signal this function seeks — use ``is not None`` so zero-dividend companies
    # score as reinvestment-focused instead of falling through to "Insufficient data".
    latest_payout_ratio = latest_dividends / latest_fcf if latest_fcf != 0 else 1
    if latest_payout_ratio < 0.2:
        return 2, "Strong focus on reinvestment over dividends"
    if latest_payout_ratio < 0.4:
        return 1, "Moderate focus on reinvestment over dividends"
    return 0, None
