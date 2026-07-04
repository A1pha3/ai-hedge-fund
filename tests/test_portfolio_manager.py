from src.agents.portfolio_manager import (
    _build_consistent_reasoning,
    _make_decision_from_signals,
    compute_allowed_actions,
)
from src.agents.portfolio_manager_helpers import (
    _accumulate_signal_weights,
    _collect_signal_counts,
    _resolve_max_short,
)


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


# ---------------------------------------------------------------------------
# BUG A fix: _resolve_max_short must divide by price * margin_requirement,
# not just price.  With 50% margin the old formula over-counted by ~2x.
# ---------------------------------------------------------------------------


def test_resolve_max_short_accounts_for_margin_requirement():
    """Short capacity must be limited by margin, not just raw price.

    With equity=1000, margin_requirement=0.5, margin_used=0, price=10:
      available_equity = 1000 - 0 = 1000
      per_share_margin = 10 * 0.5 = 5
      max_shares = int(1000 // 5) = 200
    """
    # margin_requirement = 0.5
    assert _resolve_max_short(10.0, 1000, 0.5, 0.0, 1000.0) == 200

    # margin_requirement = 1.0 (100% margin -- each share costs full price)
    # available_equity = 1000 - 0 = 1000, max = int(1000 // (10*1.0)) = 100
    assert _resolve_max_short(10.0, 1000, 1.0, 0.0, 1000.0) == 100

    # With existing margin used
    # available_equity = 1000 - 500 = 500
    # max = int(500 // 5) = 100
    assert _resolve_max_short(10.0, 1000, 0.5, 500.0, 1000.0) == 100


def test_resolve_max_short_with_high_margin_requirement_reduces_capacity():
    """Higher margin_requirement reduces short capacity.

    capacity = equity / (price * margin_requirement)
    Doubling margin_requirement halves capacity (linear inverse).
    With mr=0.25: capacity = 1000 / (10*0.25) = 400
    With mr=0.50: capacity = 1000 / (10*0.50) = 200
    So low (400) = 2 * high (200).
    """
    low = _resolve_max_short(10.0, 1000, 0.25, 0.0, 1000.0)
    high = _resolve_max_short(10.0, 1000, 0.50, 0.0, 1000.0)
    assert low == 2 * high
    assert low == 400
    assert high == 200


def test_resolve_max_short_returns_zero_for_negative_equity():
    assert _resolve_max_short(10.0, 1000, 0.5, 0.0, -100.0) == 0


def test_resolve_max_short_returns_zero_for_nan_inputs():
    assert _resolve_max_short(float("nan"), 1000, 0.5, 0.0, 1000.0) == 0
    assert _resolve_max_short(10.0, 1000, 0.5, 0.0, float("nan")) == 0


def test_resolve_max_short_returns_max_qty_when_margin_requirement_zero():
    assert _resolve_max_short(10.0, 42, 0.0, 0.0, 1000.0) == 42


def test_resolve_max_short_returns_zero_for_nan_margin_requirement():
    """NaN margin_requirement must not crash; treat as 0 (max_qty cap)."""
    assert _resolve_max_short(10.0, 1000, float("nan"), 0.0, 1000.0) == 0


def test_resolve_max_short_returns_zero_for_nan_max_qty():
    """NaN max_qty must not crash; treat as 0 (no short allowed)."""
    assert _resolve_max_short(10.0, float("nan"), 0.5, 0.0, 1000.0) == 0


def test_resolve_max_buy_returns_zero_for_none_max_qty():
    """_resolve_max_buy must not crash when caller passes None max_qty.

    A None max_qty is the convention for 'no constraint from the risk
    manager' and must degrade to 0 (no buy allowed) rather than raise.
    """
    from src.agents.portfolio_manager_helpers import _resolve_max_buy

    assert _resolve_max_buy(1000.0, 10.0, None) == 0


def test_resolve_max_short_respects_max_qty_cap():
    """Even if margin allows more, max_qty must cap the result."""
    assert _resolve_max_short(1.0, 10, 0.5, 0.0, 10000.0) == 10


def test_compute_allowed_actions_short_capacity_respects_margin():
    """End-to-end: compute_allowed_actions short qty must shrink when margin
    requirement increases (not stay constant as the old bug did)."""
    portfolio_lo = {
        "cash": 1000.0,
        "positions": {},
        "margin_requirement": 0.25,
        "margin_used": 0.0,
    }
    portfolio_hi = {
        "cash": 1000.0,
        "positions": {},
        "margin_requirement": 0.50,
        "margin_used": 0.0,
    }
    result_lo = compute_allowed_actions(
        tickers=["X"],
        current_prices={"X": 10.0},
        max_shares={"X": 9999},
        portfolio=portfolio_lo,
    )
    result_hi = compute_allowed_actions(
        tickers=["X"],
        current_prices={"X": 10.0},
        max_shares={"X": 9999},
        portfolio=portfolio_hi,
    )
    # Higher margin requirement means fewer shares can be shorted
    assert result_lo["X"]["short"] > result_hi["X"]["short"]


def test_r100_accumulate_signal_weights_conf_null_does_not_crash():
    """R100 (R73/R76 bare-coercion 同族): payload ``conf`` 为 JSON null 时,
    ``.get("conf", 0)`` 返回 None (默认值仅 key 缺失生效), 裸 ``float(None)``
    抛 TypeError 中断整个 generate_trading_decision 交易决策路径。

    当前两个 caller 都用 ``is not None`` 守卫, 故 latent; 但 helper 是
    public decision-path 边界, 未来 caller (web / serialized state replay)
    易传 null。safe_float 在边界 fail-soft 而非崩整个决策。
    """
    # conf=None (key present, value null) must not raise.
    bullish, bearish, neutral, total = _accumulate_signal_weights({"agent_a": {"sig": "bullish", "conf": None}})
    assert bullish == 0.0
    assert total == 0.0
    # Missing key still defaults to 0 (no regression).
    bullish2, _, _, total2 = _accumulate_signal_weights({"agent_a": {"sig": "bullish"}})
    assert bullish2 == 0.0
    assert total2 == 0.0
    # Normal confidence still accumulates correctly.
    bullish3, _, _, total3 = _accumulate_signal_weights({"agent_a": {"sig": "bullish", "conf": 80}})
    assert bullish3 == 80.0
    assert total3 == 80.0


def test_r100_collect_signal_counts_conf_null_does_not_crash():
    """R100: 同族 _collect_signal_counts 也用 ``or 0`` (null-safe 但带
    falsy-zero 潜在风险)。统一 safe_float 消除 decision-path confidence
    解析的语义分裂。conf=None / conf=0.0 都必须忠实保留为 0 贡献。"""
    counts, top = _collect_signal_counts({"agent_a": {"sig": "bullish", "conf": None}})
    assert counts["bullish"] == 1
    assert top["bullish"][0] == ("agent_a", 0.0)
    # conf=0.0 (真实"零信心") must be preserved as 0.0, not coerced weirdly.
    counts2, top2 = _collect_signal_counts({"agent_a": {"sig": "bearish", "conf": 0.0}})
    assert counts2["bearish"] == 1
    assert top2["bearish"][0] == ("agent_a", 0.0)
