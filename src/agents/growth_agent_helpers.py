def _build_growth_series(metrics: list, clamp_growth) -> tuple[list, list, list]:
    revenue_growth = [metric.revenue_growth for metric in metrics]
    eps_growth = [clamp_growth(metric.earnings_per_share_growth) for metric in metrics]
    fcf_growth = [clamp_growth(metric.free_cash_flow_growth) for metric in metrics]
    return revenue_growth, eps_growth, fcf_growth


def _calculate_growth_trends(revenue_growth: list, eps_growth: list, fcf_growth: list, calculate_trend) -> tuple[float, float, float]:
    revenue_trend = calculate_trend(revenue_growth)
    eps_trend = calculate_trend(eps_growth)
    fcf_trend = calculate_trend(fcf_growth)
    return revenue_trend, eps_trend, fcf_trend


def _score_revenue_growth(revenue_growth: list, revenue_trend: float) -> float:
    if revenue_growth[0] is None:
        return 0.0
    if revenue_growth[0] > 0.20:
        score = 0.4
    elif revenue_growth[0] > 0.10:
        score = 0.2
    elif revenue_growth[0] < -0.10:
        score = -0.2
    else:
        score = 0.0
    if revenue_trend > 0:
        score += 0.1
    return score


def _score_eps_growth(eps_growth: list, eps_trend: float) -> float:
    if eps_growth[0] is None:
        return 0.0
    if eps_growth[0] > 0.20:
        score = 0.25
    elif eps_growth[0] > 0.10:
        score = 0.1
    elif eps_growth[0] < -0.50:
        score = -0.2
    elif eps_growth[0] < -0.10:
        score = -0.1
    else:
        score = 0.0
    if eps_trend > 0:
        score += 0.05
    return score


def _score_fcf_growth(fcf_growth: list) -> float:
    if fcf_growth[0] is not None and fcf_growth[0] > 0.15:
        return 0.1
    return 0.0


def _build_growth_trend_result(
    score: float,
    revenue_growth: list,
    revenue_trend: float,
    eps_growth: list,
    eps_trend: float,
    fcf_growth: list,
    fcf_trend: float,
) -> dict:
    return {
        "score": max(min(score, 1.0), 0.0),
        "revenue_growth": revenue_growth[0],
        "revenue_trend": revenue_trend,
        "eps_growth": eps_growth[0],
        "eps_trend": eps_trend,
        "fcf_growth": fcf_growth[0],
        "fcf_trend": fcf_trend,
    }
