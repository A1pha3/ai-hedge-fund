from types import SimpleNamespace

from src.agents.growth_agent import analyze_growth_trends


def test_analyze_growth_trends_clamps_extreme_eps_and_preserves_current_trend_math():
    metrics = [
        SimpleNamespace(revenue_growth=0.25, earnings_per_share_growth=6.5, free_cash_flow_growth=0.18),
        SimpleNamespace(revenue_growth=0.18, earnings_per_share_growth=0.22, free_cash_flow_growth=0.12),
        SimpleNamespace(revenue_growth=0.12, earnings_per_share_growth=0.15, free_cash_flow_growth=0.08),
        SimpleNamespace(revenue_growth=0.08, earnings_per_share_growth=0.10, free_cash_flow_growth=0.04),
    ]

    result = analyze_growth_trends(metrics)

    assert result == {
        "score": 0.75,
        "revenue_growth": 0.25,
        "revenue_trend": -0.05700000000000003,
        "eps_growth": 5.0,
        "eps_trend": -1.4769999999999999,
        "fcf_growth": 0.18,
        "fcf_trend": -0.046,
    }


def test_analyze_growth_trends_keeps_zero_floor_for_declining_inputs():
    metrics = [
        SimpleNamespace(revenue_growth=-0.15, earnings_per_share_growth=-2.0, free_cash_flow_growth=-3.0),
        SimpleNamespace(revenue_growth=-0.08, earnings_per_share_growth=-0.30, free_cash_flow_growth=-0.20),
        SimpleNamespace(revenue_growth=0.02, earnings_per_share_growth=-0.05, free_cash_flow_growth=0.01),
        SimpleNamespace(revenue_growth=0.05, earnings_per_share_growth=0.02, free_cash_flow_growth=0.02),
    ]

    result = analyze_growth_trends(metrics)

    assert result == {
        "score": 0.0,
        "revenue_growth": -0.15,
        "revenue_trend": 0.06999999999999999,
        "eps_growth": -1.0,
        "eps_trend": 0.33100000000000007,
        "fcf_growth": -1.0,
        "fcf_trend": 0.32699999999999996,
    }
