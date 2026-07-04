from types import SimpleNamespace

from src.agents.stanley_druckenmiller import (
    analyze_druckenmiller_valuation,
    analyze_growth_and_momentum,
    analyze_risk_reward,
)


def test_analyze_growth_and_momentum_preserves_price_only_bullish_path():
    financial_line_items = [
        SimpleNamespace(revenue=180.0, earnings_per_share=9.0),
        SimpleNamespace(revenue=150.0, earnings_per_share=7.0),
        SimpleNamespace(revenue=120.0, earnings_per_share=5.0),
    ]
    prices = [SimpleNamespace(time=index, close=100 + index * 2) for index in range(40)]

    # R116: momentum 现度量近 30 bar 区间 (close[-31]=118 → close[-1]=178 → +50.8%)
    # 而非整段历史 (+78%)。仍落入 Very strong (>50%) 桶, 持续上涨路径保持。
    assert analyze_growth_and_momentum(financial_line_items, prices) == {
        "score": 3.333333333333333,
        "details": "Insufficient revenue data for CAGR calculation.; Insufficient EPS data for CAGR calculation.; Very strong price momentum: 50.8%",
    }


def test_analyze_growth_and_momentum_preserves_missing_data_guard():
    assert analyze_growth_and_momentum([SimpleNamespace(revenue=None, earnings_per_share=None)], []) == {
        "score": 0,
        "details": "Insufficient financial data for growth analysis",
    }


def test_analyze_risk_reward_preserves_direct_debt_and_low_volatility_path():
    financial_line_items = [SimpleNamespace(debt_to_equity=0.25)]
    prices = [SimpleNamespace(time=index, close=100 + (index % 2)) for index in range(12)]

    assert analyze_risk_reward(financial_line_items, prices) == {
        "score": 10,
        "details": "Low debt-to-equity: 0.25; Low volatility: daily returns stdev 0.99%",
    }


def test_analyze_risk_reward_preserves_fallback_debt_and_high_volatility_path():
    financial_line_items = [
        SimpleNamespace(total_debt=60.0, shareholders_equity=100.0),
        SimpleNamespace(total_debt=70.0, shareholders_equity=95.0),
    ]
    prices = [SimpleNamespace(time=index, close=value) for index, value in enumerate([100, 110, 95, 120, 90, 130, 85, 125, 80, 140, 75, 150])]

    assert analyze_risk_reward(financial_line_items, prices) == {
        "score": 3.333333333333333,
        "details": "Moderate debt-to-equity: 0.60; Very high volatility: daily returns stdev 46.81%",
    }


def test_analyze_druckenmiller_valuation_preserves_attractive_multi_metric_path():
    financial_line_items = [
        SimpleNamespace(net_income=100.0, free_cash_flow=80.0, ebit=120.0, ebitda=150.0, total_debt=200.0, cash_and_equivalents=50.0),
        SimpleNamespace(net_income=90.0, free_cash_flow=75.0, ebit=110.0, ebitda=140.0, total_debt=210.0, cash_and_equivalents=40.0),
    ]

    assert analyze_druckenmiller_valuation(financial_line_items, 1000.0) == {
        "score": 7.5,
        "details": "No positive net income for P/E calculation; Attractive P/FCF: 12.50; Attractive EV/EBIT: 9.58; Attractive EV/EBITDA: 7.67",
    }


def test_analyze_druckenmiller_valuation_preserves_zero_score_sparse_path():
    financial_line_items = [SimpleNamespace(net_income=None, free_cash_flow=-10.0, ebit=0.0, ebitda=None, total_debt=20.0, cash_and_equivalents=30.0)]

    assert analyze_druckenmiller_valuation(financial_line_items, 1000.0) == {
        "score": 0.0,
        "details": "No positive net income for P/E calculation; No positive free cash flow for P/FCF calculation; No valid EV/EBIT because EV <= 0 or EBIT <= 0; No valid EV/EBITDA because EV <= 0 or EBITDA <= 0",
    }


def test_druckenmiller_price_momentum_uses_30d_window_not_full_history():
    """R116 / 窗口一致性: _score_druckenmiller_price_momentum 必须用近 30 个 bar 的
    动量, 不能用整段历史。

    背景: 函数 gate 是 ``len(prices) <= 30`` (要求 >30 bar), 强烈暗示 30 天动量窗口;
    但历史上 ``pct_change`` 用 ``close_prices[0]`` 到 ``close_prices[-1]`` (整段历史)。
    默认价格窗口 (resolve_dates default_months_back=3 ≈ 60-65 交易日) 下, prices 含
    ~60 bar → momentum 实际度量的是 ~60 天动量, 与 gate 的 30 天语义不一致。

    Druckenmiller 是宏观动量 agent (Stanley Druckenmiller 的核心风格 = 近期强势动量),
    用整段历史把"前期大涨但近期走平/走弱"的票误判为强动量, 直接破坏 agent 的动量信号
    可信度。sibling technicals agent 用明确的 momentum_1m/3m/6m 窗口, 本函数应对齐
    1m 语义 (近 30 bar)。

    设计: 42 个价格, 前 11 bar 从 100 涨到 150, 后 31 bar 全平在 150。
    - bug (整段历史): close[0]=100 → close[-1]=150 → +50% → "Moderate" (>20%, 不 >50%)
    - fix (30 bar 窗口): close[-31]=150 (idx 11) → close[-1]=150 → 0% → "Negative"
    前 11 bar ramp 落在 30-bar 窗口 (idx 11-41) 之外, 保证窗口全平。
    """
    from src.agents.stanley_druckenmiller_helpers import _score_druckenmiller_price_momentum

    # 前 11 bar: 100 → 150 (斜坡上涨, idx<11); 后 31 bar: 全部 150 (近期走平, idx>=11)
    prices = [SimpleNamespace(time=index, close=(100 + index * 5 if index < 11 else 150)) for index in range(42)]

    points, details = _score_druckenmiller_price_momentum(prices)

    # 30-bar 窗口 (近 30 bar 全在 150) → 0% 动量 → "Negative" (0 points)
    # bug 代码会用整段历史 (+50% → "Moderate" 2 points)
    assert points == 0, f"动量窗口不一致: 应度量近 30 bar 动量 (近期走平 → 0% → 0 points), " f"但用了整段历史 (+50%) 误判为 Moderate, got points={points}, details={details!r}"
