from __future__ import annotations


def validate_metric_required_fields(metric, index: int, get_attr) -> tuple[bool, str | None]:
    ticker = get_attr(metric, "ticker")
    if not ticker:
        return False, f"Metric[{index}]: missing ticker"

    report_period = get_attr(metric, "report_period")
    if not report_period:
        return False, f"Metric[{index}]: missing report_period"
    return True, None


def collect_metric_warning_messages(metric, index: int, get_attr) -> list[str]:
    warnings: list[str] = []

    pe = get_attr(metric, "price_to_earnings_ratio")
    if pe is not None and pe < 0:
        warnings.append(f"Metric[{index}]: negative P/E ratio")

    pb = get_attr(metric, "price_to_book_ratio")
    if pb is not None and pb < 0:
        warnings.append(f"Metric[{index}]: negative P/B ratio")

    roe = get_attr(metric, "return_on_equity")
    if roe is not None and not -1 <= roe <= 1:
        warnings.append(f"Metric[{index}]: ROE outside [-1, 1]")

    debt_to_equity = get_attr(metric, "debt_to_equity")
    if debt_to_equity is not None and debt_to_equity < 0:
        warnings.append(f"Metric[{index}]: negative debt_to_equity")

    return warnings
