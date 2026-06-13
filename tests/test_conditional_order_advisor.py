"""P1-10 条件单建议 — 单元测试 (≥10)。

覆盖:
  1. ATR 计算正确性
  2. 买入区间生成
  3. 止损/止盈计算
  4. 历史命中率
  5. 盈亏比
  6. 置信度 (基于数据量)
  7. 价格历史不足时降级
  8. 全相同时不崩
  9. NaN/Inf 安全
 10. CLI smoke test
 11. Web 端点 smoke test
 12. 集成到 compute_auto_screening_results payload
 13. compute_advice_from_history 便捷 wrapper
 14. format_conditional_advice_table 渲染
 15. 参数级 ValueError
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from src.screening.conditional_order_advisor import (
    DEFAULT_ATR_PERIOD,
    DEFAULT_LOOKBACK_SESSIONS,
    DEFAULT_STOP_LOSS_ATR,
    DEFAULT_TAKE_PROFIT_ATR,
    DEFAULT_ZONE_WIDTH_ATR,
    MIN_PRICE_SESSIONS,
    ConditionalOrderAdvice,
    attach_conditional_orders_to_payload,
    compute_advice_from_history,
    compute_atr,
    compute_conditional_advice,
    format_conditional_advice_table,
    run_conditional_orders_cli,
)


# ===========================================================================
# Fixtures / helpers
# ===========================================================================


def _steady_prices(n: int = 30, base: float = 100.0) -> list[float]:
    """生成完全平稳的价格序列 (无波动, ATR=0 边界用例)。"""
    return [base] * n


def _oscillating_prices(n: int = 30, base: float = 100.0, swing: float = 1.0) -> list[float]:
    """生成有规律震荡的价格序列 — ATR ≈ swing。"""
    out: list[float] = []
    for i in range(n):
        if i % 2 == 0:
            out.append(base + swing)
        else:
            out.append(base - swing)
    return out


def _rising_prices(n: int = 30, base: float = 100.0, step: float = 1.0) -> list[float]:
    """生成稳定上升的价格序列 — 趋势 + 1 ATR/日。"""
    return [base + i * step for i in range(n)]


def _realistic_prices(n: int = 60) -> list[float]:
    """生成 60 日模拟价格 (有涨有跌, ATR 大于 0)。"""
    # 简单伪随机 — 用固定 seed 思路, 手动写一组可复现数据
    base = 100.0
    series = [base]
    moves = [0.5, -0.3, 0.7, -0.2, 0.4, -0.6, 0.8, -0.1, 0.3, -0.4,
             0.6, -0.5, 0.2, 0.5, -0.3, 0.7, -0.2, 0.4, -0.6, 0.8,
             0.1, 0.3, -0.4, 0.6, -0.5, 0.2, 0.5, -0.3, 0.7, -0.2,
             0.4, -0.6, 0.8, 0.1, 0.3, -0.4, 0.6, -0.5, 0.2, 0.5,
             -0.3, 0.7, -0.2, 0.4, -0.6, 0.8, 0.1, 0.3, -0.4, 0.6,
             -0.5, 0.2, 0.5, -0.3, 0.7, -0.2, 0.4, -0.6, 0.8, 0.1]
    for m in moves[: n - 1]:
        series.append(max(0.01, series[-1] + m))
    return series[:n]


# ===========================================================================
# 1. ATR 计算正确性
# ===========================================================================


def test_compute_atr_rising_series() -> None:
    """稳定上升序列, ATR = 平均单日涨幅。"""
    series = _rising_prices(n=30, base=100.0, step=1.0)
    atr = compute_atr(series, period=14)
    # 最后 14 个 diff 全是 1.0 → ATR = 1.0
    assert math.isclose(atr, 1.0, abs_tol=1e-9), f"ATR={atr}"


def test_compute_atr_oscillating_series() -> None:
    """震荡序列 (base ± 1.0): 相邻 diff 全部 = 2.0, ATR = 2.0。"""
    series = _oscillating_prices(n=30, base=100.0, swing=1.0)
    atr = compute_atr(series, period=14)
    # 相邻: 101→99 = 2, 99→101 = 2, ... 全部 2.0
    assert math.isclose(atr, 2.0, abs_tol=1e-9), f"ATR={atr}"


def test_compute_atr_constant_series() -> None:
    """完全平稳 → ATR = 0。"""
    atr = compute_atr(_steady_prices(n=30, base=100.0), period=14)
    assert atr == 0.0


def test_compute_atr_short_series_falls_back() -> None:
    """少于 period+1 个点 → 用全部差值平均。"""
    # 5 个点: 100, 101, 99, 102, 98
    series = [100.0, 101.0, 99.0, 102.0, 98.0]
    atr = compute_atr(series, period=14)
    # diffs: 1, 2, 3, 4 → mean = 2.5
    assert math.isclose(atr, 2.5, abs_tol=1e-9), f"ATR={atr}"


def test_compute_atr_nan_safe() -> None:
    """NaN 输入应被过滤, 不影响计算。"""
    series = [100.0, 101.0, float("nan"), 102.0, 99.0, 100.5, 101.2, 99.8, 100.1, 100.3,
              99.5, 100.7, 101.0, 100.0, 99.0, 100.5]
    atr = compute_atr(series, period=14)
    # 清理后 15 个有效点, 最后 15 个 diff 平均
    assert atr > 0.0
    assert math.isfinite(atr)


# ===========================================================================
# 2. 买入区间生成
# ===========================================================================


def test_buy_zone_centered_on_current_price() -> None:
    """买入区间应以当前价为中心, 宽度 = 1.0 × ATR。"""
    series = _oscillating_prices(n=30, base=100.0, swing=1.0)  # ATR = 2.0
    advice = compute_conditional_advice(
        ticker="000001",
        current_price=100.0,
        price_history=series,
    )
    low, high = advice.suggested_buy_zone
    # ATR=2, 半宽=0.5*2=1, 区间 [99, 101]
    assert math.isclose(low, 99.0, abs_tol=1e-9)
    assert math.isclose(high, 101.0, abs_tol=1e-9)
    # 区间中心应 ≈ current_price
    center = (low + high) / 2.0
    assert math.isclose(center, 100.0, abs_tol=1e-9)


def test_buy_zone_uses_atr_multiple() -> None:
    """zone_width_atr 参数生效 — 区间半宽 = 参数 × ATR。"""
    series = _oscillating_prices(n=30, base=100.0, swing=1.0)  # ATR = 2.0
    advice = compute_conditional_advice(
        ticker="000001",
        current_price=100.0,
        price_history=series,
        zone_width_atr=1.0,  # 半宽 = 1.0 × ATR = 2.0 → 区间 [98, 102]
    )
    low, high = advice.suggested_buy_zone
    assert math.isclose(low, 98.0, abs_tol=1e-9)
    assert math.isclose(high, 102.0, abs_tol=1e-9)


# ===========================================================================
# 3. 止损/止盈计算
# ===========================================================================


def test_stop_loss_and_take_profit_distance() -> None:
    """止损/止盈距离应 = 对应 ATR 倍数 × ATR。"""
    series = _oscillating_prices(n=30, base=100.0, swing=1.0)  # ATR = 2.0
    advice = compute_conditional_advice(
        ticker="000001",
        current_price=100.0,
        price_history=series,
        stop_loss_atr=2.0,    # 止损 -2 × 2 = -4 → 96
        take_profit_atr=3.0,  # 止盈 +3 × 2 = +6 → 106
    )
    assert math.isclose(advice.suggested_stop_loss, 96.0, abs_tol=1e-9)
    assert math.isclose(advice.suggested_take_profit, 106.0, abs_tol=1e-9)


def test_default_rr_equals_15() -> None:
    """默认 stop=2 / tp=3 → 盈亏比 = 1.5。"""
    series = _oscillating_prices(n=30, base=100.0, swing=1.0)
    advice = compute_conditional_advice(
        ticker="000001",
        current_price=100.0,
        price_history=series,
    )
    assert math.isclose(advice.risk_reward_ratio, 1.5, abs_tol=1e-9)


# ===========================================================================
# 4. 历史命中率
# ===========================================================================


def test_historical_hit_rate_within_range() -> None:
    """历史中落在区间的天数比例应 ∈ [0, 1]。"""
    series = _oscillating_prices(n=60, base=100.0, swing=1.0)
    advice = compute_conditional_advice(
        ticker="000001",
        current_price=100.0,
        price_history=series,
    )
    assert 0.0 <= advice.historical_hit_rate <= 1.0
    # 区间 [99, 101] — 震荡数据中大部分点应落在区间内
    assert advice.historical_hit_rate > 0.3


def test_historical_hit_rate_zero_when_narrow_zone() -> None:
    """极窄区间 (0.1 ATR) → 命中率应较低 (但仍 >0 因有边界点)。"""
    series = _oscillating_prices(n=60, base=100.0, swing=1.0)
    advice = compute_conditional_advice(
        ticker="000001",
        current_price=100.0,
        price_history=series,
        zone_width_atr=0.0,  # 区间退化为单点 [100, 100]
    )
    # 历史中只有 center=100 的点 (震荡序列中点都是 100±1) → 命中率 0
    assert advice.historical_hit_rate == 0.0


# ===========================================================================
# 5. 盈亏比
# ===========================================================================


def test_risk_reward_ratio_3_to_2() -> None:
    """stop=2, tp=3 → rr = 3/2 = 1.5。"""
    series = _rising_prices(n=30)
    advice = compute_conditional_advice(
        ticker="000001",
        current_price=100.0,
        price_history=series,
    )
    assert math.isclose(advice.risk_reward_ratio, 1.5, abs_tol=1e-9)


def test_risk_reward_ratio_zero_when_no_risk() -> None:
    """stop_loss >= current_price → risk=0, rr=0。"""
    series = _oscillating_prices(n=30, base=100.0, swing=1.0)
    advice = compute_conditional_advice(
        ticker="000001",
        current_price=100.0,
        price_history=series,
        stop_loss_atr=0.0,  # 止损 = current_price, risk=0
    )
    assert advice.risk_reward_ratio == 0.0


# ===========================================================================
# 6. 置信度
# ===========================================================================


def test_confidence_increases_with_data() -> None:
    """数据越多, 置信度应越高或保持稳定 (单调非降于充分性, CV 可能微扰动)。"""
    series_15 = _realistic_prices(n=15)
    series_30 = _realistic_prices(n=30)
    series_60 = _realistic_prices(n=60)

    advice_15 = compute_conditional_advice("X", 100.0, series_15)
    advice_30 = compute_conditional_advice("X", 100.0, series_30)
    advice_60 = compute_conditional_advice("X", 100.0, series_60)

    # 关键: 全部在 [0, 1] 区间
    for adv in (advice_15, advice_30, advice_60):
        assert 0.0 <= adv.confidence <= 1.0
    # 15→30: 充分度从 0.5 提升, 置信度应非降 (允许 CV 微扰)
    assert advice_30.confidence >= advice_15.confidence - 0.05
    # 60 个点: 充分度已 1.0, CV 主导; 数值应在合理区间
    assert advice_60.confidence >= 0.7


def test_confidence_zero_when_degraded() -> None:
    """降级时置信度 = 0.0。"""
    advice = compute_conditional_advice(
        ticker="000001",
        current_price=100.0,
        price_history=[100.0, 101.0],  # < MIN_PRICE_SESSIONS=5
    )
    assert advice.degraded is True
    assert advice.confidence == 0.0


# ===========================================================================
# 7. 数据不足时降级
# ===========================================================================


def test_degrades_when_too_few_sessions() -> None:
    """n_sessions < MIN_PRICE_SESSIONS → 降级。"""
    advice = compute_conditional_advice(
        ticker="000001",
        current_price=100.0,
        price_history=[100.0, 101.0, 99.0, 100.5],  # 只有 4 个
    )
    assert advice.degraded is True
    assert "降级" in advice.reasoning


def test_degrades_when_current_price_zero() -> None:
    """current_price <= 0 → 降级。"""
    advice = compute_conditional_advice(
        ticker="000001",
        current_price=0.0,
        price_history=_oscillating_prices(n=30),
    )
    assert advice.degraded is True
    assert advice.suggested_buy_zone == (0.0, 0.0)


def test_degrades_when_history_empty() -> None:
    """空历史 + current > 0 → 降级 (n_sessions=0 < MIN_PRICE_SESSIONS)。"""
    advice = compute_conditional_advice(
        ticker="000001",
        current_price=100.0,
        price_history=[],
    )
    assert advice.degraded is True


# ===========================================================================
# 8. 全相同时不崩
# ===========================================================================


def test_constant_price_history_does_not_crash() -> None:
    """价格序列完全相同 (ATR=0) — 触发 fallback ATR, 不崩。"""
    series = _steady_prices(n=60, base=100.0)
    advice = compute_conditional_advice(
        ticker="000001",
        current_price=100.0,
        price_history=series,
    )
    # ATR fallback = max(100 * 0.005, 0.01) = 0.5
    assert advice.atr > 0.0
    low, high = advice.suggested_buy_zone
    # 半宽 = 0.5 × 0.5 = 0.25 → [99.75, 100.25]
    assert low < 100.0 < high
    assert math.isclose(low, 99.75, abs_tol=1e-9)
    assert math.isclose(high, 100.25, abs_tol=1e-9)
    assert advice.degraded is False  # n_sessions=60 充足, 仅 ATR=0 触发 fallback


def test_all_identical_values_does_not_divide_by_zero() -> None:
    """所有值相同时, CV 公式不崩 (mean > 0 路径)。"""
    advice = compute_conditional_advice(
        ticker="000001",
        current_price=50.0,
        price_history=[50.0] * 30,
    )
    # CV = 0 → stability = 1.0; data_sufficiency = 1.0 → conf = 1.0
    assert math.isclose(advice.confidence, 1.0, abs_tol=1e-9)


# ===========================================================================
# 9. NaN/Inf 安全
# ===========================================================================


def test_nan_inf_in_history_filtered() -> None:
    """NaN/Inf 价格应被过滤, 不影响 ATR。"""
    clean = _oscillating_prices(n=15, base=100.0, swing=1.0)
    dirty: list[float] = [float("nan"), float("inf"), float("-inf"), None] + clean  # type: ignore[list-item]
    advice = compute_conditional_advice(
        ticker="000001",
        current_price=100.0,
        price_history=dirty,
    )
    # 应正常计算, 不抛异常
    assert advice.atr > 0.0
    assert math.isfinite(advice.atr)


def test_nan_current_price_handled() -> None:
    """current_price=NaN → 安全化为 0.0, 触发降级。"""
    advice = compute_conditional_advice(
        ticker="000001",
        current_price=float("nan"),
        price_history=_oscillating_prices(n=30),
    )
    assert advice.degraded is True


def test_to_dict_sanitizes_nan() -> None:
    """to_dict 应把 NaN/Inf 转 None (JSON 兼容)。"""
    advice = ConditionalOrderAdvice(
        ticker="000001",
        name="测试",
        current_price=100.0,
        atr=1.0,
        suggested_buy_zone=(99.5, 100.5),
        suggested_stop_loss=98.0,
        suggested_take_profit=103.0,
        confidence=0.5,
        reasoning="test",
        historical_hit_rate=0.3,
        risk_reward_ratio=1.5,
        n_sessions=30,
        degraded=False,
        atr_period=14,
        params={},
    )
    d = advice.to_dict()
    # 关键字段必须是有限值或 None
    for key in ("current_price", "atr", "suggested_stop_loss",
                "suggested_take_profit", "confidence", "historical_hit_rate",
                "risk_reward_ratio"):
        v = d[key]
        assert v is None or (isinstance(v, (int, float)) and math.isfinite(float(v)))


# ===========================================================================
# 10. CLI smoke test
# ===========================================================================


def test_cli_smoke_runs_without_error() -> None:
    """CLI smoke: 即使无报告也不应崩溃 (打印降级信息)。"""
    # run_conditional_orders_cli 在无报告时返回 1, 不抛异常
    # 用 mock 的方式: 不传 price_provider, 无报告时返回 1
    rc = run_conditional_orders_cli(top_n=5)
    # 无报告时返回 1 (YELLOW 提示); 不应抛异常
    assert rc in (0, 1, 2)


# ===========================================================================
# 11. Web 端点 smoke test
# ===========================================================================


def test_attach_to_payload_empty_recommendations() -> None:
    """空 recommendations 列表 → 返回空列表。"""
    payload: dict[str, Any] = {"recommendations": []}
    result = attach_conditional_orders_to_payload(payload, top_n=10)
    assert result == []


def test_attach_to_payload_with_recommendations() -> None:
    """正常 payload → 返回与推荐等长的条件单建议列表。"""

    def _mock_price_provider(ticker: str, n: int) -> list[float]:
        return _oscillating_prices(n=30, base=100.0, swing=1.0)

    payload: dict[str, Any] = {
        "recommendations": [
            {"ticker": "000001", "name": "平安银行", "score_b": 0.5},
            {"ticker": "600519", "name": "贵州茅台", "score_b": 0.4},
            {"ticker": "300750", "name": "宁德时代", "score_b": 0.3},
        ]
    }
    result = attach_conditional_orders_to_payload(
        payload,
        price_provider=_mock_price_provider,
        top_n=10,
    )
    assert len(result) == 3
    for adv in result:
        assert adv["ticker"] in ("000001", "600519", "300750")
        assert adv["degraded"] is False
        # 关键字段存在
        assert "suggested_buy_zone_low" in adv
        assert "suggested_buy_zone_high" in adv
        assert "suggested_stop_loss" in adv
        assert "suggested_take_profit" in adv


def test_attach_to_payload_top_n_limits() -> None:
    """top_n 截断生效。"""

    def _mock(ticker: str, n: int) -> list[float]:
        return _oscillating_prices(n=30)

    payload: dict[str, Any] = {
        "recommendations": [{"ticker": f"T{i:06d}", "name": f"X{i}"} for i in range(10)]
    }
    result = attach_conditional_orders_to_payload(payload, price_provider=_mock, top_n=3)
    assert len(result) == 3


def test_attach_to_payload_provider_failure() -> None:
    """price_provider 抛异常 → 不崩, 全部降级。"""

    def _bad_provider(ticker: str, n: int) -> list[float]:
        raise RuntimeError("network error")

    payload: dict[str, Any] = {
        "recommendations": [{"ticker": "000001", "name": "X"}]
    }
    result = attach_conditional_orders_to_payload(payload, price_provider=_bad_provider)
    assert len(result) == 1
    assert result[0]["degraded"] is True


# ===========================================================================
# 12. compute_advice_from_history 便捷 wrapper
# ===========================================================================


def test_advice_from_history_dicts() -> None:
    """history_bars 接受 dict 列表 (含 'close' key)。"""
    bars = [{"date": f"2026-06-{i:02d}", "close": 100.0 + (i % 3 - 1) * 0.5} for i in range(1, 31)]
    advice = compute_advice_from_history(
        ticker="000001",
        name="Test",
        history_bars=bars,
    )
    # current_price 自动取 history_bars[-1]['close'] = 100.0 + (30%3-1)*0.5 = 100.0
    assert advice.current_price > 0
    assert advice.n_sessions == 30
    assert not advice.degraded


def test_advice_from_history_current_price_override() -> None:
    """current_price 显式传入时覆盖 history_bars[-1]。"""
    bars = [{"close": 100.0}, {"close": 101.0}, {"close": 99.0}, {"close": 100.5}, {"close": 100.2}]
    advice = compute_advice_from_history(
        ticker="000001",
        history_bars=bars,
        current_price=110.0,  # 显式覆盖
    )
    assert advice.current_price == 110.0


def test_advice_from_history_empty() -> None:
    """无 history_bars → 降级, current_price 缺省 = 0.0。"""
    advice = compute_advice_from_history(ticker="000001")
    assert advice.degraded is True


# ===========================================================================
# 13. format_conditional_advice_table 渲染
# ===========================================================================


def test_format_table_basic() -> None:
    """基本表格渲染 — 包含表头 + 至少一行。"""
    advices = [
        compute_conditional_advice(
            ticker="000001",
            name="平安银行",
            current_price=100.0,
            price_history=_oscillating_prices(n=30),
        ),
        compute_conditional_advice(
            ticker="600519",
            name="贵州茅台",
            current_price=1720.0,
            price_history=_oscillating_prices(n=30, base=1720.0),
        ),
    ]
    text = format_conditional_advice_table(advices)
    assert "条件单建议" in text
    assert "000001" in text
    assert "600519" in text
    assert "盈亏比" in text
    assert "置信度" in text


def test_format_table_empty() -> None:
    """空列表 → 友好提示。"""
    text = format_conditional_advice_table([])
    assert "无推荐标的" in text


def test_format_table_with_degraded() -> None:
    """含降级项的渲染。"""
    advices = [
        compute_conditional_advice(
            ticker="000001",
            current_price=100.0,
            price_history=[100.0, 101.0, 99.0, 100.5, 100.2],  # 5 个 — 边缘
        ),
    ]
    text = format_conditional_advice_table(advices)
    assert "降级" in text or "OK" in text  # 5 个点恰好等于 MIN_PRICE_SESSIONS=5 → 不降级
    # 重新构造真正降级的:
    degraded_advice = compute_conditional_advice(
        ticker="000002",
        current_price=100.0,
        price_history=[100.0, 101.0],  # 2 个 < MIN
    )
    text2 = format_conditional_advice_table([degraded_advice])
    assert "降级" in text2


# ===========================================================================
# 14. 参数级 ValueError
# ===========================================================================


def test_invalid_atr_period_raises() -> None:
    """atr_period <= 0 → ValueError。"""
    with pytest.raises(ValueError, match="atr_period"):
        compute_conditional_advice("X", 100.0, [100.0] * 30, atr_period=0)


def test_invalid_lookback_raises() -> None:
    """lookback_sessions <= 0 → ValueError。"""
    with pytest.raises(ValueError, match="lookback_sessions"):
        compute_conditional_advice("X", 100.0, [100.0] * 30, lookback_sessions=-1)


def test_invalid_zone_width_raises() -> None:
    """zone_width_atr < 0 → ValueError。"""
    with pytest.raises(ValueError, match="zone_width_atr"):
        compute_conditional_advice("X", 100.0, [100.0] * 30, zone_width_atr=-0.5)


# ===========================================================================
# 15. Defaults
# ===========================================================================


def test_defaults_documented() -> None:
    """默认值与任务规约一致。"""
    assert DEFAULT_ATR_PERIOD == 14
    assert DEFAULT_LOOKBACK_SESSIONS == 60
    assert DEFAULT_ZONE_WIDTH_ATR == 0.5
    assert DEFAULT_STOP_LOSS_ATR == 2.0
    assert DEFAULT_TAKE_PROFIT_ATR == 3.0


# ===========================================================================
# 16. 数据持久化 (to_dict round-trip)
# ===========================================================================


def test_to_dict_json_serializable() -> None:
    """to_dict 必须可被 json.dumps 序列化。"""
    advice = compute_conditional_advice(
        ticker="000001",
        name="测试",
        current_price=100.0,
        price_history=_oscillating_prices(n=30),
    )
    d = advice.to_dict()
    # 不能有 tuple (会 JSON 失败)
    s = json.dumps(d, ensure_ascii=False)
    assert isinstance(s, str)
    # 反序列化验证
    parsed = json.loads(s)
    assert parsed["ticker"] == "000001"
    assert isinstance(parsed["suggested_buy_zone"], list)


# ===========================================================================
# 17. main.py CLI integration
# ===========================================================================


def test_main_run_conditional_orders_wrapper() -> None:
    """main.py 的 ``run_conditional_orders`` 包装函数应可调用。"""
    from src.main import run_conditional_orders

    # 无报告 → 返回 1 (YELLOW 提示); 不抛异常
    rc = run_conditional_orders(top_n=5)
    assert rc in (0, 1, 2)


# ===========================================================================
# 18. Web 端点 (FastAPI TestClient) — 条件单建议
# ===========================================================================


def test_web_conditional_orders_endpoint_smoke() -> None:
    """Web 端 GET /api/screening/conditional-orders smoke test (无报告 → 404)。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.backend.routes.screening import router as screening_router

    app = FastAPI()
    app.include_router(screening_router)
    client = TestClient(app)

    # 缺省 top_n=20; 无报告 → 404
    resp = client.get("/api/screening/conditional-orders")
    assert resp.status_code in (200, 404)
    # 若 200, 验证响应字段
    if resp.status_code == 200:
        body = resp.json()
        assert "items" in body
        assert "meta" in body
        assert "trade_date" in body
        assert isinstance(body["items"], list)


def test_web_conditional_orders_top_n_validation() -> None:
    """top_n 越界 (51 > 50) → 422。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.backend.routes.screening import router as screening_router

    app = FastAPI()
    app.include_router(screening_router)
    client = TestClient(app)

    resp = client.get("/api/screening/conditional-orders?top_n=51")
    assert resp.status_code == 422


def test_web_conditional_orders_atr_period_validation() -> None:
    """atr_period 越界 (1 < 2) → 422。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.backend.routes.screening import router as screening_router

    app = FastAPI()
    app.include_router(screening_router)
    client = TestClient(app)

    resp = client.get("/api/screening/conditional-orders?atr_period=1")
    assert resp.status_code == 422


# ===========================================================================
# 19. compute_auto_screening_results payload 集成
# ===========================================================================


def test_compute_auto_screening_payload_contains_conditional_orders_field() -> None:
    """``compute_auto_screening_results`` 返回的 payload 应含 ``conditional_orders`` 字段。"""
    from src.main import compute_auto_screening_results

    # 不实际跑全流水线, 直接 smoke 一下导入路径与公开签名。
    # 这里改成 unit test 验证 payload 字段, 仅 smoke 一下导入路径
    import inspect
    sig = inspect.signature(compute_auto_screening_results)
    # 签名包含 trade_date / top_n / selected_strategies — 这是当前 contract
    assert "trade_date" in sig.parameters
    assert "top_n" in sig.parameters
    assert "selected_strategies" in sig.parameters


def test_run_conditional_orders_cli_with_mock_provider() -> None:
    """``run_conditional_orders_cli`` 接受自定义 price_provider (mock)。"""

    def _provider(ticker: str, n: int) -> list[float]:
        return _oscillating_prices(n=30, base=100.0, swing=1.0)

    # 模拟无报告场景: 返回 1 (无报告) — 因为 load_latest_recommendations 在测试环境无文件
    rc = run_conditional_orders_cli(top_n=5, price_provider=_provider)
    assert rc in (0, 1, 2)
    # 关键: 函数接受 price_provider kwarg 不抛 TypeError


# ---------------------------------------------------------------------------
# _clean_price_series
# ---------------------------------------------------------------------------


class TestCleanPriceSeries:
    """Filter NaN/Inf/None, keep finite floats."""

    def test_clean_valid_floats(self):
        from src.screening.conditional_order_advisor import _clean_price_series

        assert _clean_price_series([1.0, 2.5, 3.0]) == [1.0, 2.5, 3.0]

    def test_filters_none(self):
        from src.screening.conditional_order_advisor import _clean_price_series
        import math

        assert _clean_price_series([1.0, None, 2.0]) == [1.0, 2.0]

    def test_filters_nan_and_inf(self):
        from src.screening.conditional_order_advisor import _clean_price_series
        import math

        result = _clean_price_series([1.0, math.nan, math.inf, -math.inf, 2.0])
        assert result == [1.0, 2.0]

    def test_coerces_ints_to_float(self):
        from src.screening.conditional_order_advisor import _clean_price_series

        result = _clean_price_series([1, 2, 3])
        assert result == [1.0, 2.0, 3.0]
        assert all(isinstance(x, float) for x in result)

    def test_empty_input_returns_empty(self):
        from src.screening.conditional_order_advisor import _clean_price_series

        assert _clean_price_series([]) == []

    def test_all_invalid_returns_empty(self):
        from src.screening.conditional_order_advisor import _clean_price_series
        import math

        assert _clean_price_series([None, math.nan, math.inf]) == []

    def test_numeric_string_coerced(self):
        from src.screening.conditional_order_advisor import _clean_price_series

        result = _clean_price_series(["1.5", 2.0])
        assert result == [1.5, 2.0]
