def _build_missing_fundamentals_result() -> dict:
    return {
        "signal": "neutral",
        "confidence": 0,
        "reasoning": {"error": "No financial metrics available for fundamental analysis"},
    }


def _analyze_fundamentals_profitability(metrics) -> tuple[str, dict]:
    return_on_equity = metrics.return_on_equity
    net_margin = metrics.net_margin
    operating_margin = metrics.operating_margin

    thresholds = [
        (return_on_equity, 0.15),
        (net_margin, 0.20),
        (operating_margin, 0.15),
    ]
    profitability_score = sum(metric is not None and metric > threshold for metric, threshold in thresholds)
    signal = "bullish" if profitability_score >= 2 else "bearish" if profitability_score == 0 else "neutral"
    return signal, {
        "signal": signal,
        "details": (f"ROE(TTM): {return_on_equity:.2%}" if return_on_equity is not None else "ROE: N/A")
        + ", "
        + (f"Net Margin(TTM): {net_margin:.2%}" if net_margin is not None else "Net Margin: N/A")
        + ", "
        + (f"Op Margin(TTM): {operating_margin:.2%}" if operating_margin is not None else "Op Margin: N/A"),
    }


def _analyze_fundamentals_growth(metrics) -> tuple[str, dict]:
    revenue_growth = metrics.revenue_growth
    earnings_growth = metrics.earnings_growth
    book_value_growth = metrics.book_value_growth

    if earnings_growth is not None:
        earnings_growth = max(-1.0, min(5.0, earnings_growth))

    thresholds = [
        (revenue_growth, 0.10),
        (earnings_growth, 0.10),
        (book_value_growth, 0.10),
    ]
    growth_score = sum(metric is not None and metric > threshold for metric, threshold in thresholds)
    signal = "bullish" if growth_score >= 2 else "bearish" if growth_score == 0 else "neutral"
    return signal, {
        "signal": signal,
        "details": (f"Revenue Growth(TTM YoY): {revenue_growth:.2%}" if revenue_growth is not None else "Revenue Growth: N/A")
        + ", "
        + (f"Earnings Growth(TTM YoY): {earnings_growth:.2%}" if earnings_growth is not None else "Earnings Growth: N/A"),
    }


def _analyze_fundamentals_health(metrics) -> tuple[str, dict]:
    current_ratio = metrics.current_ratio
    debt_to_equity = metrics.debt_to_equity
    free_cash_flow_per_share = metrics.free_cash_flow_per_share
    earnings_per_share = metrics.earnings_per_share

    health_score = 0
    if current_ratio and current_ratio > 1.5:
        health_score += 1
    if debt_to_equity and debt_to_equity < 0.5:
        health_score += 1
    if free_cash_flow_per_share and earnings_per_share and free_cash_flow_per_share > earnings_per_share * 0.8:
        health_score += 1

    signal = "bullish" if health_score >= 2 else "bearish" if health_score == 0 else "neutral"
    return signal, {
        "signal": signal,
        "details": (f"Current Ratio: {current_ratio:.2f}" if current_ratio is not None else "Current Ratio: N/A")
        + ", "
        + (f"D/E: {debt_to_equity:.2f}" if debt_to_equity is not None else "D/E: N/A"),
    }


def _analyze_fundamentals_price_ratios(metrics) -> tuple[str, dict]:
    pe_ratio = metrics.price_to_earnings_ratio
    pb_ratio = metrics.price_to_book_ratio
    ps_ratio = metrics.price_to_sales_ratio

    thresholds = [
        (pe_ratio, 25),
        (pb_ratio, 3),
        (ps_ratio, 5),
    ]
    available_price_metrics = [metric for metric, _ in thresholds if metric is not None]
    if not available_price_metrics:
        signal = "neutral"
    else:
        price_ratio_score = sum(metric > threshold for metric, threshold in thresholds if metric is not None)
        signal = "bearish" if price_ratio_score >= 2 else "bullish" if price_ratio_score == 0 else "neutral"

    return signal, {
        "signal": signal,
        "details": (f"P/E(TTM): {pe_ratio:.2f}" if pe_ratio is not None else "P/E: N/A")
        + ", "
        + (f"P/B: {pb_ratio:.2f}" if pb_ratio is not None else "P/B: N/A")
        + ", "
        + (f"P/S: {ps_ratio:.2f}" if ps_ratio is not None else "P/S: N/A"),
    }


def _finalize_fundamentals_signal(signals: list[str], reasoning: dict) -> dict:
    bullish_signals = signals.count("bullish")
    bearish_signals = signals.count("bearish")

    if bullish_signals > bearish_signals:
        overall_signal = "bullish"
    elif bearish_signals > bullish_signals:
        overall_signal = "bearish"
    else:
        overall_signal = "neutral"

    confidence = round(max(bullish_signals, bearish_signals) / len(signals), 2) * 100
    return {
        "signal": overall_signal,
        "confidence": confidence,
        "reasoning": reasoning,
    }
