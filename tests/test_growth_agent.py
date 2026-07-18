from types import SimpleNamespace

from src.agents.growth_agent import analyze_growth_trends, analyze_insider_conviction


def test_analyze_growth_trends_clamps_extreme_eps_and_preserves_current_trend_math():
    metrics = [
        SimpleNamespace(revenue_growth=0.25, earnings_per_share_growth=6.5, free_cash_flow_growth=0.18),
        SimpleNamespace(revenue_growth=0.18, earnings_per_share_growth=0.22, free_cash_flow_growth=0.12),
        SimpleNamespace(revenue_growth=0.12, earnings_per_share_growth=0.15, free_cash_flow_growth=0.08),
        SimpleNamespace(revenue_growth=0.08, earnings_per_share_growth=0.10, free_cash_flow_growth=0.04),
    ]

    result = analyze_growth_trends(metrics)

    # 趋势语义修正 (2026-07-18): 序列 newest-first 倒序回归, slope>0 = 真实加速.
    # revenue 0.08→0.25 加速 (+0.057), eps 0.10→5.0 加速 (+1.477), fcf 0.04→0.18 加速.
    assert result == {
        "score": 0.9,
        "raw_score": 0.9,
        "revenue_growth": 0.25,
        "revenue_trend": 0.05699999999999998,
        "eps_growth": 5.0,
        "eps_trend": 1.4769999999999999,
        "fcf_growth": 0.18,
        "fcf_trend": 0.046,
    }


def test_analyze_growth_trends_keeps_zero_floor_for_declining_inputs():
    metrics = [
        SimpleNamespace(revenue_growth=-0.15, earnings_per_share_growth=-2.0, free_cash_flow_growth=-3.0),
        SimpleNamespace(revenue_growth=-0.08, earnings_per_share_growth=-0.30, free_cash_flow_growth=-0.20),
        SimpleNamespace(revenue_growth=0.02, earnings_per_share_growth=-0.05, free_cash_flow_growth=0.01),
        SimpleNamespace(revenue_growth=0.05, earnings_per_share_growth=0.02, free_cash_flow_growth=0.02),
    ]

    result = analyze_growth_trends(metrics)

    # 趋势语义修正: 输入随时间恶化 (0.05→-0.15), slope 应为负 (减速).
    # raw_score 保留未钳位原值 (score 仍为 0 地板).
    assert result == {
        "score": 0.0,
        "raw_score": -0.4,
        "revenue_growth": -0.15,
        "revenue_trend": -0.06999999999999999,
        "eps_growth": -1.0,
        "eps_trend": -0.33099999999999996,
        "fcf_growth": -1.0,
        "fcf_trend": -0.32700000000000007,
    }


def test_analyze_insider_conviction_handles_missing_transaction_shares():
    """InsiderTrade.transaction_shares is ``float | None``.

    A trade with a transaction_value but a missing share count previously raised
    ``TypeError: '>' not supported between NoneType and int`` on the filter
    ``t.transaction_shares > 0``. Sibling agents (michael_burry) guard with
    ``(t.transaction_shares or 0)``; this pins the same guard on growth_agent.
    """
    # Mixed trades: a normal buy, a normal sell, and a buy with missing shares.
    trades = [
        SimpleNamespace(transaction_value=1_000_000.0, transaction_shares=10_000.0),
        SimpleNamespace(transaction_value=-500_000.0, transaction_shares=-5_000.0),
        SimpleNamespace(transaction_value=2_000_000.0, transaction_shares=None),
    ]

    # Must not raise; None-shares trade is skipped (direction unknown).
    result = analyze_insider_conviction(trades)

    assert "score" in result
    assert isinstance(result["score"], (int, float))
    # Only the two guarded trades count: buys=1M, sells=500k -> net positive ratio.
    assert result["score"] >= 0.5
