from __future__ import annotations

import statistics


def _score_druckenmiller_growth_metric(growth_value: float | None, metric_name: str, slight_label: str) -> tuple[int, str]:
    if growth_value is None:
        return 0, f"Insufficient {metric_name} data for CAGR calculation."
    if growth_value > 0.08:
        return 3, f"Strong annualized {metric_name} growth: {growth_value:.1%}"
    if growth_value > 0.04:
        return 2, f"Moderate annualized {metric_name} growth: {growth_value:.1%}"
    if growth_value > 0.01:
        return 1, f"{slight_label}: {growth_value:.1%}"
    return 0, f"Minimal/negative {metric_name} growth: {growth_value:.1%}" if metric_name == "revenue" else f"Minimal/negative annualized {metric_name} growth: {growth_value:.1%}"


def _score_druckenmiller_price_momentum(prices: list) -> tuple[int, str]:
    if not prices or len(prices) <= 30:
        return 0, "Not enough recent price data for momentum analysis."

    sorted_prices = sorted(prices, key=lambda price: price.time)
    close_prices = [price.close for price in sorted_prices if price.close is not None]
    if len(close_prices) < 2:
        return 0, "Insufficient price data for momentum calculation."

    start_price = close_prices[0]
    end_price = close_prices[-1]
    if start_price <= 0:
        return 0, "Invalid start price (<= 0); can't compute momentum."

    pct_change = (end_price - start_price) / start_price
    if pct_change > 0.50:
        return 3, f"Very strong price momentum: {pct_change:.1%}"
    if pct_change > 0.20:
        return 2, f"Moderate price momentum: {pct_change:.1%}"
    if pct_change > 0:
        return 1, f"Slight positive momentum: {pct_change:.1%}"
    return 0, f"Negative price momentum: {pct_change:.1%}"


def _resolve_druckenmiller_de_ratio(financial_line_items: list) -> float | None:
    direct_ratio = getattr(financial_line_items[0], "debt_to_equity", None) if financial_line_items else None
    if direct_ratio is not None:
        return direct_ratio

    debt_values = [getattr(item, "total_debt", None) for item in financial_line_items if getattr(item, "total_debt", None) is not None]
    equity_values = [getattr(item, "shareholders_equity", None) for item in financial_line_items if getattr(item, "shareholders_equity", None) is not None]
    if debt_values and equity_values and len(debt_values) == len(equity_values):
        recent_equity = equity_values[0] if equity_values[0] else 1e-9
        return debt_values[0] / recent_equity
    return None


def _score_druckenmiller_de_ratio(de_ratio: float | None) -> tuple[int, str]:
    if de_ratio is None:
        return 0, "No debt/equity data available."
    if de_ratio < 0.3:
        return 3, f"Low debt-to-equity: {de_ratio:.2f}"
    if de_ratio < 0.7:
        return 2, f"Moderate debt-to-equity: {de_ratio:.2f}"
    if de_ratio < 1.5:
        return 1, f"Somewhat high debt-to-equity: {de_ratio:.2f}"
    return 0, f"High debt-to-equity: {de_ratio:.2f}"


def _score_druckenmiller_volatility(prices: list) -> tuple[int, str]:
    if len(prices) <= 10:
        return 0, "Not enough price data for volatility analysis."

    sorted_prices = sorted(prices, key=lambda price: price.time)
    close_prices = [price.close for price in sorted_prices if price.close is not None]
    if len(close_prices) <= 10:
        return 0, "Not enough close-price data points for volatility analysis."

    daily_returns = []
    for index in range(1, len(close_prices)):
        previous_close = close_prices[index - 1]
        if previous_close > 0:
            daily_returns.append((close_prices[index] - previous_close) / previous_close)
    if not daily_returns:
        return 0, "Insufficient daily returns data for volatility calc."

    stdev = statistics.pstdev(daily_returns)
    if stdev < 0.01:
        return 3, f"Low volatility: daily returns stdev {stdev:.2%}"
    if stdev < 0.02:
        return 2, f"Moderate volatility: daily returns stdev {stdev:.2%}"
    if stdev < 0.04:
        return 1, f"High volatility: daily returns stdev {stdev:.2%}"
    return 0, f"Very high volatility: daily returns stdev {stdev:.2%}"


def _collect_druckenmiller_valuation_inputs(financial_line_items: list) -> dict[str, object]:
    debt_values = [getattr(item, "total_debt", None) for item in financial_line_items if getattr(item, "total_debt", None) is not None]
    cash_values = [getattr(item, "cash_and_equivalents", None) for item in financial_line_items if getattr(item, "cash_and_equivalents", None) is not None]
    return {
        "fcf_values": [getattr(item, "free_cash_flow", None) for item in financial_line_items if getattr(item, "free_cash_flow", None) is not None],
        "ebit_values": [getattr(item, "ebit", None) for item in financial_line_items if getattr(item, "ebit", None) is not None],
        "ebitda_values": [getattr(item, "ebitda", None) for item in financial_line_items if getattr(item, "ebitda", None) is not None],
        "recent_debt": debt_values[0] if debt_values else 0,
        "recent_cash": cash_values[0] if cash_values else 0,
    }


def _score_druckenmiller_pe(pe: float | None) -> tuple[int, str]:
    if pe is None:
        return 0, "No positive net income for P/E calculation"
    if pe < 15:
        return 2, f"Attractive P/E: {pe:.2f}"
    if pe < 25:
        return 1, f"Fair P/E: {pe:.2f}"
    return 0, f"High or Very high P/E: {pe:.2f}"


def _score_druckenmiller_pfcf(recent_fcf: float | None, market_cap: float) -> tuple[int, str]:
    if not recent_fcf or recent_fcf <= 0:
        return 0, "No positive free cash flow for P/FCF calculation"
    pfcf = market_cap / recent_fcf
    if pfcf < 15:
        return 2, f"Attractive P/FCF: {pfcf:.2f}"
    if pfcf < 25:
        return 1, f"Fair P/FCF: {pfcf:.2f}"
    return 0, f"High/Very high P/FCF: {pfcf:.2f}"


def _score_druckenmiller_ev_ebit(enterprise_value: float, recent_ebit: float | None) -> tuple[int, str]:
    if enterprise_value <= 0 or not recent_ebit or recent_ebit <= 0:
        return 0, "No valid EV/EBIT because EV <= 0 or EBIT <= 0"
    ev_ebit = enterprise_value / recent_ebit
    if ev_ebit < 15:
        return 2, f"Attractive EV/EBIT: {ev_ebit:.2f}"
    if ev_ebit < 25:
        return 1, f"Fair EV/EBIT: {ev_ebit:.2f}"
    return 0, f"High EV/EBIT: {ev_ebit:.2f}"


def _score_druckenmiller_ev_ebitda(enterprise_value: float, recent_ebitda: float | None) -> tuple[int, str]:
    if enterprise_value <= 0 or not recent_ebitda or recent_ebitda <= 0:
        return 0, "No valid EV/EBITDA because EV <= 0 or EBITDA <= 0"
    ev_ebitda = enterprise_value / recent_ebitda
    if ev_ebitda < 10:
        return 2, f"Attractive EV/EBITDA: {ev_ebitda:.2f}"
    if ev_ebitda < 18:
        return 1, f"Fair EV/EBITDA: {ev_ebitda:.2f}"
    return 0, f"High EV/EBITDA: {ev_ebitda:.2f}"
