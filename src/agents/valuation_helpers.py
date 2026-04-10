from __future__ import annotations


def _build_missing_valuation_metrics_result() -> dict[str, object]:
    return {
        "signal": "neutral",
        "confidence": 0,
        "reasoning": {"error": "No financial metrics available for valuation analysis"},
    }


def _build_insufficient_line_items_result(line_item_count: int) -> dict[str, object]:
    return {
        "signal": "neutral",
        "confidence": 0,
        "reasoning": {"error": f"Insufficient financial line items (found {line_item_count}, need at least 2)"},
    }


def _build_market_cap_unavailable_result() -> dict[str, object]:
    return {
        "signal": "neutral",
        "confidence": 0,
        "reasoning": {"error": "Market cap unavailable for valuation analysis"},
    }


def _calculate_working_capital_change(current_line_item, previous_line_item) -> float:
    working_capital_current = getattr(current_line_item, "working_capital", None)
    working_capital_previous = getattr(previous_line_item, "working_capital", None)
    if working_capital_current is None or working_capital_previous is None:
        return 0
    return working_capital_current - working_capital_previous


def _collect_free_cash_flow_history(line_items: list) -> list[float]:
    return [line_item.free_cash_flow for line_item in line_items if hasattr(line_item, "free_cash_flow") and line_item.free_cash_flow is not None]


def _build_method_values(dcf_value: float, owner_earnings_value: float, ev_ebitda_value: float, residual_income_value: float) -> dict[str, dict[str, float]]:
    return {
        "dcf": {"value": dcf_value, "weight": 0.35},
        "owner_earnings": {"value": owner_earnings_value, "weight": 0.35},
        "ev_ebitda": {"value": ev_ebitda_value, "weight": 0.20},
        "residual_income": {"value": residual_income_value, "weight": 0.10},
    }


def _summarize_method_coverage(method_values: dict[str, dict[str, float]]) -> tuple[float, int, int]:
    total_weight = sum(value["weight"] for value in method_values.values() if value["value"] > 0)
    methods_succeeded = sum(1 for value in method_values.values() if value["value"] > 0)
    methods_total = len(method_values)
    return total_weight, methods_succeeded, methods_total


def _build_all_non_positive_result(method_values: dict[str, dict[str, float]], market_cap: float, currency_symbol: str) -> dict[str, object]:
    method_value_summary = {name: values["value"] for name, values in method_values.items()}
    return {
        "signal": "bearish",
        "confidence": 85,
        "reasoning": {
            "summary": "All valuation methods returned non-positive intrinsic values while market cap is positive",
            "market_cap": market_cap,
            "method_values": method_value_summary,
            "details": (
                f"DCF: {currency_symbol}{method_values['dcf']['value']:,.2f}, "
                f"Owner Earnings: {currency_symbol}{method_values['owner_earnings']['value']:,.2f}, "
                f"EV/EBITDA: {currency_symbol}{method_values['ev_ebitda']['value']:,.2f}, "
                f"Residual Income: {currency_symbol}{method_values['residual_income']['value']:,.2f}"
            ),
        },
    }


def _attach_method_gaps(method_values: dict[str, dict[str, float]], market_cap: float) -> None:
    for values in method_values.values():
        values["gap"] = (values["value"] - market_cap) / market_cap if values["value"] > 0 else None


def _calculate_weighted_gap(method_values: dict[str, dict[str, float]], total_weight: float) -> float:
    return sum(value["weight"] * value["gap"] for value in method_values.values() if value["gap"] is not None) / total_weight


def _resolve_valuation_signal(weighted_gap: float) -> str:
    if weighted_gap > 0.15:
        return "bullish"
    if weighted_gap < -0.15:
        return "bearish"
    return "neutral"


def _resolve_valuation_confidence(weighted_gap: float, methods_succeeded: int, methods_total: int) -> int:
    coverage_ratio = methods_succeeded / methods_total
    raw_confidence = abs(weighted_gap) / 0.30 * 100
    return round(min(raw_confidence * coverage_ratio, 100))


def _build_method_base_details(method_name: str, values: dict[str, float], market_cap: float, currency_symbol: str, free_cash_flow_history: list[float]) -> str:
    if values["value"] <= 0:
        if method_name == "owner_earnings":
            base_details = f"Value: N/A (owner earnings negative, business not generating positive owner earnings), Market Cap: {currency_symbol}{market_cap:,.2f}, "
        elif method_name == "dcf" and any(isinstance(value, (int, float)) and value < 0 for value in free_cash_flow_history[:1]):
            base_details = f"Value: N/A (negative free cash flow), Market Cap: {currency_symbol}{market_cap:,.2f}, "
        else:
            base_details = f"Value: N/A (insufficient data), Market Cap: {currency_symbol}{market_cap:,.2f}, "
    else:
        base_details = f"Value: {currency_symbol}{values['value']:,.2f}, Market Cap: {currency_symbol}{market_cap:,.2f}, "

    if values["gap"] is not None:
        return f"{base_details}Gap: {values['gap']:.1%}, Weight: {values['weight']*100:.0f}%"
    return f"{base_details}Gap: N/A (data unavailable), Weight: {values['weight']*100:.0f}%"


def _build_method_reasoning(method_values: dict[str, dict[str, float]], market_cap: float, currency_symbol: str, free_cash_flow_history: list[float], wacc: float, dcf_results: dict[str, object]) -> dict[str, dict[str, object]]:
    reasoning: dict[str, dict[str, object]] = {}
    for method_name, values in method_values.items():
        details = _build_method_base_details(method_name, values, market_cap, currency_symbol, free_cash_flow_history)
        if method_name == "dcf":
            details = (
                f"{details}\n"
                f"  WACC: {wacc:.1%}, Bear: {currency_symbol}{dcf_results['downside']:,.2f}, "
                f"Bull: {currency_symbol}{dcf_results['upside']:,.2f}, Range: {currency_symbol}{dcf_results['range']:,.2f}"
            )
        reasoning[f"{method_name}_analysis"] = {
            "signal": _resolve_valuation_signal(values["gap"]) if values["gap"] is not None else "neutral",
            "details": details,
        }
    return reasoning


def _build_dcf_scenario_analysis(currency_symbol: str, dcf_results: dict[str, object], free_cash_flow_history: list[float]) -> dict[str, object]:
    return {
        "bear_case": f"{currency_symbol}{dcf_results['downside']:,.2f}",
        "base_case": f"{currency_symbol}{dcf_results['scenarios']['base']:,.2f}",
        "bull_case": f"{currency_symbol}{dcf_results['upside']:,.2f}",
        "wacc_used": f"{dcf_results['wacc']:.1%}",
        "fcf_periods_analyzed": len(free_cash_flow_history),
    }


def _build_fallback_reasoning(signal: str, weighted_gap: float, market_cap: float, currency_symbol: str) -> dict[str, dict[str, str]]:
    return {
        "summary": {
            "signal": signal,
            "details": f"Weighted valuation gap: {weighted_gap:.1%}. Market Cap: {currency_symbol}{market_cap:,.2f}. All valuation methods returned zero or negative values.",
        }
    }

