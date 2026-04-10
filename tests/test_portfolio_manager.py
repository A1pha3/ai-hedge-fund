from src.agents.portfolio_manager import _build_consistent_reasoning, _make_decision_from_signals, compute_allowed_actions


def test_compute_allowed_actions_preserves_long_short_and_cover_capacities():
    result = compute_allowed_actions(
        tickers=["AAA", "BBB"],
        current_prices={"AAA": 10.0, "BBB": 20.0},
        max_shares={"AAA": 50, "BBB": 40},
        portfolio={
            "cash": 500.0,
            "positions": {
                "AAA": {"long": 15, "short": 0},
                "BBB": {"long": 0, "short": 5},
            },
            "margin_requirement": 0.5,
            "margin_used": 100.0,
            "equity": 1000.0,
        },
    )

    assert result == {
        "AAA": {"hold": 0, "buy": 50, "sell": 15, "short": 50},
        "BBB": {"hold": 0, "buy": 25, "short": 40, "cover": 5},
    }


def test_compute_allowed_actions_keeps_zero_margin_requirement_short_path():
    result = compute_allowed_actions(
        tickers=["CCC"],
        current_prices={"CCC": 25.0},
        max_shares={"CCC": 12},
        portfolio={
            "cash": 0.0,
            "positions": {},
            "margin_requirement": 0.0,
            "margin_used": 0.0,
            "equity": 0.0,
        },
    )

    assert result == {"CCC": {"hold": 0, "short": 12}}


def test_make_decision_from_signals_caps_buy_quantity_and_confidence():
    decision = _make_decision_from_signals(
        "AAA",
        {
            "a1": {"sig": "bullish", "conf": 90},
            "a2": {"sig": "bullish", "conf": 60},
            "a3": {"sig": "bearish", "conf": 20},
        },
        {"hold": 0, "buy": 150},
    )

    assert decision.action == "buy"
    assert decision.quantity == 100
    assert decision.confidence == 57
    assert decision.reasoning == "多数分析师看涨(权重150 vs 20)，建议买入"


def test_make_decision_from_signals_falls_back_to_sell_when_short_unavailable():
    decision = _make_decision_from_signals(
        "BBB",
        {
            "a1": {"sig": "bearish", "conf": 80},
            "a2": {"sig": "bearish", "conf": 70},
            "a3": {"sig": "bullish", "conf": 20},
        },
        {"hold": 0, "sell": 35},
    )

    assert decision.action == "sell"
    assert decision.quantity == 35
    assert decision.confidence == 57
    assert decision.reasoning == "多数分析师看跌(权重150 vs 20)，建议卖出"


def test_make_decision_from_signals_returns_hold_when_total_weight_is_zero():
    decision = _make_decision_from_signals(
        "CCC",
        {
            "a1": {"sig": "neutral", "conf": 0},
            "a2": {"sig": "neutral", "conf": 0},
        },
        {"hold": 0},
    )

    assert decision.action == "hold"
    assert decision.quantity == 0
    assert decision.confidence == 0
    assert decision.reasoning == "分析师信号权重为零"


def test_build_consistent_reasoning_preserves_directional_wording():
    signals = {
        "warren_buffett_agent": {"sig": "bullish", "conf": 88},
        "charlie_munger_agent": {"sig": "bullish", "conf": 72},
        "risk_guard": {"sig": "neutral", "conf": 15},
        "news_agent": {"sig": "bearish", "conf": 61},
    }

    assert _build_consistent_reasoning(signals, "buy") == "看涨2票/中性1票/看跌1票，Warren Buffett(88%)、Charlie Munger(72%)偏多"
    assert _build_consistent_reasoning(signals, "sell") == "看跌1票/中性1票/看涨2票，News(61%)偏空"
    assert _build_consistent_reasoning(signals, "hold") == "看涨2票/看跌1票/中性1票，信号分歧"
    assert _build_consistent_reasoning({}, "hold") == "无分析师信号，保持观望"
