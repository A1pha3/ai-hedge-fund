"""P1-2 行业轮动信号 — 单元测试

覆盖场景:
1.  3 个行业、正常数据 → 正确排名
2.  同 momentum_score → 稳定排序 (按 avg_score_b / candidate_count / name)
3.  industry_sw 缺失 → "未知" 组排除
4.  candidate_count < 2 → 排除
5.  空推荐 → 空列表
6.  单一行业 → 只展示该行业
7.  所有行业候选数 < 2 → 空列表
8.  score_b 为 None/NaN → 安全处理
9.  momentum_score 计算验证 (direction * confidence / 4-strategy 归一化)
10. to_dict() 序列化
11. 边界: candidate_count == min_candidates 保留
12. 边界: 负向 / 正向 极端动量
13. 集成: format_rotation_block 输出格式
14. 集成: top_strong / bottom_weak 选择器
15. 防御: 非 dict 输入项被忽略
"""

from __future__ import annotations

import math

import pytest

from src.screening.industry_rotation import (
    bottom_weak_industries,
    calculate_industry_rotation,
    format_rotation_block,
    IndustrySignal,
    MIN_CANDIDATES_PER_INDUSTRY,
    top_strong_industries,
    UNKNOWN_INDUSTRY,
)

# ============================================================================
# Fixtures
# ============================================================================


def _make_rec(
    ticker: str,
    industry: str,
    score_b: float,
    *,
    trend_dir: int = 1,
    trend_conf: float = 60.0,
    mr_dir: int = 0,
    mr_conf: float = 0.0,
    fund_dir: int = 1,
    fund_conf: float = 70.0,
    event_dir: int = 0,
    event_conf: float = 0.0,
) -> dict:
    """生成单个推荐结果 dict (含 industry_sw, score_b, 4-strategy signals)。"""
    return {
        "ticker": ticker,
        "name": ticker,
        "industry_sw": industry,
        "score_b": score_b,
        "decision": "watch",
        "strategy_signals": {
            "trend": {"direction": trend_dir, "confidence": trend_conf},
            "mean_reversion": {"direction": mr_dir, "confidence": mr_conf},
            "fundamental": {"direction": fund_dir, "confidence": fund_conf},
            "event_sentiment": {"direction": event_dir, "confidence": event_conf},
        },
        "metrics": {},
        "arbitration_applied": [],
    }


# ============================================================================
# Test 1: 3 个行业、正常数据 → 正确排名
# ============================================================================


def test_three_industries_basic_ranking():
    """电子 (强) > 计算机 (中) > 房地产 (弱) — 按 momentum_score 降序。"""
    recs = [
        # 电子: 3 候选, 高动量
        _make_rec("300001", "电子", 0.65, trend_dir=1, trend_conf=80, fund_dir=1, fund_conf=85),
        _make_rec("300002", "电子", 0.70, trend_dir=1, trend_conf=75, fund_dir=1, fund_conf=90),
        _make_rec("300003", "电子", 0.60, trend_dir=1, trend_conf=70, fund_dir=1, fund_conf=80),
        # 计算机: 2 候选, 中等
        _make_rec("600001", "计算机", 0.40, trend_dir=1, trend_conf=50, fund_dir=1, fund_conf=55),
        _make_rec("600002", "计算机", 0.45, trend_dir=0, trend_conf=0, fund_dir=1, fund_conf=60),
        # 房地产: 2 候选, 弱
        _make_rec("000001", "房地产", -0.10, trend_dir=-1, trend_conf=40, fund_dir=-1, fund_conf=45),
        _make_rec("000002", "房地产", -0.20, trend_dir=-1, trend_conf=35, fund_dir=-1, fund_conf=50),
    ]

    signals = calculate_industry_rotation(recs, "20260607")

    assert len(signals) == 3
    assert signals[0].industry_name == "电子"
    assert signals[0].rank == 1
    assert signals[1].industry_name == "计算机"
    assert signals[1].rank == 2
    assert signals[2].industry_name == "房地产"
    assert signals[2].rank == 3
    assert signals[0].candidate_count == 3
    assert signals[0].momentum_score > signals[1].momentum_score > signals[2].momentum_score
    # 房地产 momentum 必为负
    assert signals[2].momentum_score < 0


# ============================================================================
# Test 2: 同 momentum_score → 稳定排序
# ============================================================================


def test_tie_break_by_avg_score_b_and_count():
    """当两个行业 momentum_score 相同时, 按 avg_score_b 降序, 再按 candidate_count。"""
    # 构造 A/B 两个行业, 让它们有相同 momentum_score 但不同 avg_score_b
    # A: score_b=0.5 全部 (avg=0.5)
    # B: score_b=0.3 全部 (avg=0.3)
    # 二者 candidate_count 都是 2
    recs = [
        # 行业 A — momentum 应当相同
        _make_rec("A1", "行业A", 0.5, trend_dir=1, trend_conf=60, fund_dir=1, fund_conf=60),
        _make_rec("A2", "行业A", 0.5, trend_dir=1, trend_conf=60, fund_dir=1, fund_conf=60),
        # 行业 B — momentum 应当相同
        _make_rec("B1", "行业B", 0.3, trend_dir=1, trend_conf=60, fund_dir=1, fund_conf=60),
        _make_rec("B2", "行业B", 0.3, trend_dir=1, trend_conf=60, fund_dir=1, fund_conf=60),
    ]

    signals = calculate_industry_rotation(recs, "20260607")
    assert len(signals) == 2
    # A 应当排第一 (avg_score_b 更高)
    assert signals[0].industry_name == "行业A"
    assert signals[1].industry_name == "行业B"
    # momentum 应当相同
    assert math.isclose(signals[0].momentum_score, signals[1].momentum_score, abs_tol=0.01)


def test_tie_break_by_candidate_count():
    """当 momentum_score 和 avg_score_b 均相同时, 按 candidate_count 降序。"""
    # 行业 A: 3 候选
    # 行业 B: 2 候选
    # 二者 score_b 全为 0.5 (avg_score_b 相同)
    recs = [
        _make_rec("A1", "行业A", 0.5, trend_dir=1, trend_conf=60, fund_dir=1, fund_conf=60),
        _make_rec("A2", "行业A", 0.5, trend_dir=1, trend_conf=60, fund_dir=1, fund_conf=60),
        _make_rec("A3", "行业A", 0.5, trend_dir=1, trend_conf=60, fund_dir=1, fund_conf=60),
        _make_rec("B1", "行业B", 0.5, trend_dir=1, trend_conf=60, fund_dir=1, fund_conf=60),
        _make_rec("B2", "行业B", 0.5, trend_dir=1, trend_conf=60, fund_dir=1, fund_conf=60),
    ]
    signals = calculate_industry_rotation(recs, "20260607")
    assert len(signals) == 2
    # A 候选多 → 排第一
    assert signals[0].industry_name == "行业A"
    assert signals[0].candidate_count == 3


# ============================================================================
# Test 3: industry_sw 缺失 → "未知" 组排除
# ============================================================================


def test_missing_industry_sw_excluded():
    """industry_sw 缺失的标的归入 "未知" 组, 但不出现在最终排名中。"""
    recs = [
        _make_rec("300001", "电子", 0.65, trend_dir=1, trend_conf=80, fund_dir=1, fund_conf=80),
        _make_rec("300002", "电子", 0.60, trend_dir=1, trend_conf=70, fund_dir=1, fund_conf=70),
        # 缺失 industry_sw
        {"ticker": "X1", "name": "X1", "industry_sw": "", "score_b": 0.99, "strategy_signals": {}, "metrics": {}, "arbitration_applied": []},
        {"ticker": "X2", "name": "X2", "industry_sw": None, "score_b": 0.99, "strategy_signals": {}, "metrics": {}, "arbitration_applied": []},
    ]
    signals = calculate_industry_rotation(recs, "20260607")
    assert len(signals) == 1
    assert signals[0].industry_name == "电子"
    assert all(s.industry_name != UNKNOWN_INDUSTRY for s in signals)


# ============================================================================
# Test 4: candidate_count < 2 → 排除
# ============================================================================


def test_single_candidate_industry_excluded():
    """只含 1 个候选的行业 (样本太少) 不会出现在最终排名中。"""
    recs = [
        _make_rec("300001", "电子", 0.65, trend_dir=1, trend_conf=80, fund_dir=1, fund_conf=80),
        _make_rec("300002", "电子", 0.60, trend_dir=1, trend_conf=70, fund_dir=1, fund_conf=70),
        # 单候选 — 应当被剔除
        _make_rec("600001", "孤狼行业", 0.99, trend_dir=1, trend_conf=99, fund_dir=1, fund_conf=99),
    ]
    signals = calculate_industry_rotation(recs, "20260607")
    assert len(signals) == 1
    assert signals[0].industry_name == "电子"
    # "孤狼行业" 候选数=1 < MIN_CANDIDATES_PER_INDUSTRY (2)
    assert all(s.industry_name != "孤狼行业" for s in signals)


# ============================================================================
# Test 5: 空推荐 → 空列表
# ============================================================================


def test_empty_recommendations_returns_empty():
    """recommendations 为 None / [] / 全是非 dict 时, 返回空列表。"""
    assert calculate_industry_rotation([], "20260607") == []
    assert calculate_industry_rotation(None, "20260607") == []  # type: ignore[arg-type]
    assert calculate_industry_rotation(["not a dict", 123, None], "20260607") == []  # type: ignore[list-item]


# ============================================================================
# Test 6: 单一行业 → 只展示该行业
# ============================================================================


def test_single_industry_returns_one_signal():
    """所有候选都在同一行业, 返回 1 个信号, rank=1。"""
    recs = [
        _make_rec("300001", "电子", 0.65, trend_dir=1, trend_conf=80, fund_dir=1, fund_conf=80),
        _make_rec("300002", "电子", 0.60, trend_dir=1, trend_conf=70, fund_dir=1, fund_conf=70),
    ]
    signals = calculate_industry_rotation(recs, "20260607")
    assert len(signals) == 1
    assert signals[0].industry_name == "电子"
    assert signals[0].rank == 1
    assert signals[0].candidate_count == 2


# ============================================================================
# Test 7: 所有行业候选数 < 2 → 空列表
# ============================================================================


def test_all_industries_have_one_candidate_returns_empty():
    """每个行业都只有 1 个候选, 全部被剔除, 返回空列表。"""
    recs = [
        _make_rec("300001", "电子", 0.65, trend_dir=1, trend_conf=80, fund_dir=1, fund_conf=80),
        _make_rec("300002", "计算机", 0.60, trend_dir=1, trend_conf=70, fund_dir=1, fund_conf=70),
        _make_rec("300003", "房地产", 0.55, trend_dir=1, trend_conf=60, fund_dir=1, fund_conf=60),
    ]
    signals = calculate_industry_rotation(recs, "20260607")
    assert signals == []


# ============================================================================
# Test 8: score_b 为 None / NaN → 安全处理
# ============================================================================


def test_score_b_none_and_nan_handled():
    """score_b 为 None / NaN 时, 安全降级为 0.0, 不抛异常。"""
    recs = [
        _make_rec("300001", "电子", 0.65, trend_dir=1, trend_conf=80, fund_dir=1, fund_conf=80),
        # score_b=None
        {**_make_rec("300002", "电子", 0.60, trend_dir=1, trend_conf=70, fund_dir=1, fund_conf=70), "score_b": None},
        # score_b=NaN
        {**_make_rec("300003", "电子", 0.55, trend_dir=1, trend_conf=60, fund_dir=1, fund_conf=60), "score_b": float("nan")},
    ]
    signals = calculate_industry_rotation(recs, "20260607")
    # 不应当抛异常
    assert len(signals) == 1
    # avg_score_b = (0.65 + 0.0 + 0.0) / 3 = 0.2166...
    assert math.isclose(signals[0].avg_score_b, (0.65 + 0.0 + 0.0) / 3, abs_tol=0.01)


def test_score_b_inf_and_garbage_handled():
    """score_b 为 inf 或非数值字符串时, 安全处理为 0.0。"""
    recs = [
        _make_rec("300001", "电子", 0.65, trend_dir=1, trend_conf=80, fund_dir=1, fund_conf=80),
        {**_make_rec("300002", "电子", 0.60, trend_dir=1, trend_conf=70, fund_dir=1, fund_conf=70), "score_b": "not_a_number"},
        {**_make_rec("300003", "电子", 0.55, trend_dir=1, trend_conf=60, fund_dir=1, fund_conf=60), "score_b": float("inf")},
    ]
    signals = calculate_industry_rotation(recs, "20260607")
    assert len(signals) == 1
    # 0.65 + 0.0 + 0.0 = 0.65, /3 = 0.2166...
    assert math.isclose(signals[0].avg_score_b, (0.65 + 0.0 + 0.0) / 3, abs_tol=0.01)


# ============================================================================
# Test 9: momentum_score 计算验证
# ============================================================================


def test_momentum_score_formula_correctness():
    """momentum_score = mean(direction_i * confidence_i) over 4 strategies.

    验证: 单标的 trend=+1*80, mr=0*0, fund=+1*70, event=0*0
        → (80 + 0 + 70 + 0) / 4 = 37.5
    行业内 2 个相同候选, momentum = 37.5
    """
    recs = [
        _make_rec("300001", "电子", 0.65, trend_dir=1, trend_conf=80, fund_dir=1, fund_conf=70),
        _make_rec("300002", "电子", 0.60, trend_dir=1, trend_conf=80, fund_dir=1, fund_conf=70),
    ]
    signals = calculate_industry_rotation(recs, "20260607")
    assert len(signals) == 1
    expected = 37.5
    assert math.isclose(signals[0].momentum_score, expected, abs_tol=0.001)


def test_momentum_score_negative_when_all_bearish():
    """所有方向都是 -1, momentum_score 必为负。"""
    recs = [
        _make_rec("000001", "房地产", -0.5, trend_dir=-1, trend_conf=60, mr_dir=-1, mr_conf=50, fund_dir=-1, fund_conf=70, event_dir=-1, event_conf=40),
        _make_rec("000002", "房地产", -0.3, trend_dir=-1, trend_conf=50, mr_dir=-1, mr_conf=60, fund_dir=-1, fund_conf=80, event_dir=0, event_conf=0),
    ]
    signals = calculate_industry_rotation(recs, "20260607")
    assert len(signals) == 1
    assert signals[0].momentum_score < 0


def test_momentum_score_extreme_positive():
    """所有方向 +1, confidence=100, momentum_score = 100.0。"""
    recs = [
        _make_rec("300001", "电子", 1.0, trend_dir=1, trend_conf=100, mr_dir=1, mr_conf=100, fund_dir=1, fund_conf=100, event_dir=1, event_conf=100),
    ]
    signals = calculate_industry_rotation(recs, "20260607", min_candidates=1)
    assert len(signals) == 1
    assert math.isclose(signals[0].momentum_score, 100.0, abs_tol=0.001)


# ============================================================================
# Test 10: to_dict() 序列化
# ============================================================================


def test_to_dict_serialization():
    """IndustrySignal.to_dict() 返回的 dict 包含全部字段且类型正确。"""
    sig = IndustrySignal(
        industry_name="电子",
        industry_code="SW2021_801080",
        momentum_score=72.3456,
        avg_score_b=0.6789,
        candidate_count=3,
        north_money_flow=12.5,
        rank=1,
        tickers=["300001", "300002", "300003"],
    )
    d = sig.to_dict()
    assert d["industry_name"] == "电子"
    assert d["industry_code"] == "SW2021_801080"
    assert d["momentum_score"] == 72.3456
    assert d["avg_score_b"] == 0.6789
    assert d["candidate_count"] == 3
    assert d["north_money_flow"] == 12.5
    assert d["rank"] == 1
    assert d["tickers"] == ["300001", "300002", "300003"]


def test_to_dict_rounding():
    """to_dict() 默认 round 到 4 位小数。"""
    sig = IndustrySignal(industry_name="X", momentum_score=0.123456789)
    d = sig.to_dict()
    assert d["momentum_score"] == 0.1235  # 4 位 round


# ============================================================================
# Test 11: 边界 — candidate_count == min_candidates 保留
# ============================================================================


def test_boundary_candidate_count_equals_min():
    """candidate_count == min_candidates 时, 应当保留。"""
    recs = [
        _make_rec("300001", "电子", 0.65, trend_dir=1, trend_conf=80, fund_dir=1, fund_conf=80),
        _make_rec("300002", "电子", 0.60, trend_dir=1, trend_conf=70, fund_dir=1, fund_conf=70),
    ]
    signals = calculate_industry_rotation(recs, "20260607", min_candidates=2)
    assert len(signals) == 1
    assert signals[0].industry_name == "电子"


def test_custom_min_candidates():
    """自定义 min_candidates=3 时, 候选数=2 的行业被剔除。"""
    recs = [
        # 行业 A: 3 候选
        _make_rec("A1", "行业A", 0.5, trend_dir=1, trend_conf=60, fund_dir=1, fund_conf=60),
        _make_rec("A2", "行业A", 0.5, trend_dir=1, trend_conf=60, fund_dir=1, fund_conf=60),
        _make_rec("A3", "行业A", 0.5, trend_dir=1, trend_conf=60, fund_dir=1, fund_conf=60),
        # 行业 B: 2 候选 — min_candidates=3 时被剔除
        _make_rec("B1", "行业B", 0.5, trend_dir=1, trend_conf=60, fund_dir=1, fund_conf=60),
        _make_rec("B2", "行业B", 0.5, trend_dir=1, trend_conf=60, fund_dir=1, fund_conf=60),
    ]
    signals = calculate_industry_rotation(recs, "20260607", min_candidates=3)
    assert len(signals) == 1
    assert signals[0].industry_name == "行业A"


# ============================================================================
# Test 12: 集成 — format_rotation_block 输出格式
# ============================================================================


def test_format_rotation_block_with_signals():
    """format_rotation_block 包含"强势行业"和"弱势行业"两个小节。"""
    recs = [
        _make_rec("300001", "电子", 0.65, trend_dir=1, trend_conf=80, fund_dir=1, fund_conf=80),
        _make_rec("300002", "电子", 0.60, trend_dir=1, trend_conf=70, fund_dir=1, fund_conf=70),
        _make_rec("600001", "房地产", -0.20, trend_dir=-1, trend_conf=40, fund_dir=-1, fund_conf=45),
        _make_rec("600002", "房地产", -0.30, trend_dir=-1, trend_conf=50, fund_dir=-1, fund_conf=55),
    ]
    signals = calculate_industry_rotation(recs, "20260607")
    block = format_rotation_block(signals, top_n=5, bottom_n=3)
    assert "强势行业:" in block
    assert "弱势行业:" in block
    assert "电子" in block
    assert "房地产" in block
    assert "↑" in block
    assert "↓" in block


def test_format_rotation_block_empty():
    """空信号时输出友好提示。"""
    block = format_rotation_block([])
    assert "无行业轮动信号" in block


# ============================================================================
# Test 13: 集成 — top_strong / bottom_weak 选择器
# ============================================================================


def test_top_strong_and_bottom_weak():
    """top_strong / bottom_weak 选择器返回正确行业。"""
    recs = [
        _make_rec("A1", "电子A", 0.8, trend_dir=1, trend_conf=90, fund_dir=1, fund_conf=90),
        _make_rec("A2", "电子A", 0.7, trend_dir=1, trend_conf=80, fund_dir=1, fund_conf=80),
        _make_rec("B1", "医药B", 0.5, trend_dir=1, trend_conf=60, fund_dir=1, fund_conf=60),
        _make_rec("B2", "医药B", 0.4, trend_dir=1, trend_conf=50, fund_dir=1, fund_conf=50),
        _make_rec("C1", "消费C", 0.3, trend_dir=1, trend_conf=40, fund_dir=1, fund_conf=40),
        _make_rec("C2", "消费C", 0.2, trend_dir=1, trend_conf=30, fund_dir=1, fund_conf=30),
        _make_rec("D1", "地产D", -0.1, trend_dir=-1, trend_conf=40, fund_dir=-1, fund_conf=40),
        _make_rec("D2", "地产D", -0.2, trend_dir=-1, trend_conf=50, fund_dir=-1, fund_conf=50),
    ]
    signals = calculate_industry_rotation(recs, "20260607")
    strong = top_strong_industries(signals, n=2)
    weak = bottom_weak_industries(signals, n=2)
    assert len(strong) == 2
    assert {s.industry_name for s in strong} == {"电子A", "医药B"}
    assert len(weak) == 2
    assert {s.industry_name for s in weak} == {"消费C", "地产D"}


# ============================================================================
# Test 14: 防御 — 非 dict 输入项被忽略
# ============================================================================


def test_non_dict_items_are_ignored():
    """混合 dict / 非 dict 输入时, 只处理 dict, 不抛异常。"""
    recs = [
        _make_rec("300001", "电子", 0.65, trend_dir=1, trend_conf=80, fund_dir=1, fund_conf=80),
        "not a dict",  # type: ignore[list-item]
        123,  # type: ignore[list-item]
        None,  # type: ignore[list-item]
        _make_rec("300002", "电子", 0.60, trend_dir=1, trend_conf=70, fund_dir=1, fund_conf=70),
    ]
    signals = calculate_industry_rotation(recs, "20260607")
    assert len(signals) == 1
    assert signals[0].industry_name == "电子"
    assert signals[0].candidate_count == 2


# ============================================================================
# Test 15: 集成 — 行业名称中的 tickers 字段正确填充
# ============================================================================


def test_tickers_field_populated():
    """IndustrySignal.tickers 包含该行业所有候选标的的 ticker。"""
    recs = [
        _make_rec("300001", "电子", 0.65, trend_dir=1, trend_conf=80, fund_dir=1, fund_conf=80),
        _make_rec("300002", "电子", 0.60, trend_dir=1, trend_conf=70, fund_dir=1, fund_conf=70),
        _make_rec("300003", "电子", 0.55, trend_dir=1, trend_conf=60, fund_dir=1, fund_conf=60),
    ]
    signals = calculate_industry_rotation(recs, "20260607")
    assert len(signals) == 1
    assert set(signals[0].tickers) == {"300001", "300002", "300003"}


# ============================================================================
# Test 16: 集成 — north_money_flow 默认 0, 不影响排序
# ============================================================================


def test_north_money_flow_default_zero():
    """默认 north_money_flow=0.0, 不参与排序。"""
    sig1 = IndustrySignal(industry_name="A", momentum_score=50.0, north_money_flow=0.0)
    sig2 = IndustrySignal(industry_name="B", momentum_score=40.0, north_money_flow=99.0)
    # sig1 应当排第一, north_money_flow 不影响
    assert sig1.momentum_score > sig2.momentum_score
    assert sig1.north_money_flow == 0.0
    assert sig2.north_money_flow == 99.0


# ============================================================================
# Test 17: constants
# ============================================================================


def test_constants_exposed():
    """MIN_CANDIDATES_PER_INDUSTRY = 2, UNKNOWN_INDUSTRY = '未知'."""
    assert MIN_CANDIDATES_PER_INDUSTRY == 2
    assert UNKNOWN_INDUSTRY == "未知"


# ============================================================================
# Test 18: strategy_signals 缺失 → momentum=0
# ============================================================================


def test_missing_strategy_signals_yields_zero_momentum():
    """strategy_signals 缺失或为空 dict, momentum_score = 0.0。"""
    recs = [
        {"ticker": "300001", "name": "300001", "industry_sw": "电子", "score_b": 0.5, "strategy_signals": {}, "metrics": {}, "arbitration_applied": []},
        {"ticker": "300002", "name": "300002", "industry_sw": "电子", "score_b": 0.6, "strategy_signals": None, "metrics": {}, "arbitration_applied": []},
    ]
    signals = calculate_industry_rotation(recs, "20260607")
    assert len(signals) == 1
    # momentum 应当为 0
    assert math.isclose(signals[0].momentum_score, 0.0, abs_tol=0.001)


# ============================================================================
# Test 19: 集成 — trade_date 不影响结果 (保留参数供未来使用)
# ============================================================================


def test_trade_date_does_not_affect_result():
    """trade_date 当前不影响计算结果, 仅保留供未来接入时序数据。"""
    recs = [
        _make_rec("300001", "电子", 0.65, trend_dir=1, trend_conf=80, fund_dir=1, fund_conf=80),
        _make_rec("300002", "电子", 0.60, trend_dir=1, trend_conf=70, fund_dir=1, fund_conf=70),
    ]
    s1 = calculate_industry_rotation(recs, "20260101")
    s2 = calculate_industry_rotation(recs, "20261231")
    assert s1[0].momentum_score == s2[0].momentum_score


# ============================================================================
# Test 20: 集成 — 相同 momentum+score+count 时按行业名稳定排序
# ============================================================================


def test_final_tie_break_by_industry_name():
    """所有主排序键都相同时, 按 industry_name 升序确定排名。"""
    # 行业 "Z" 应当排第二 (按字母 Z > A)
    recs = [
        _make_rec("A1", "A行业", 0.5, trend_dir=1, trend_conf=60, fund_dir=1, fund_conf=60),
        _make_rec("A2", "A行业", 0.5, trend_dir=1, trend_conf=60, fund_dir=1, fund_conf=60),
        _make_rec("Z1", "Z行业", 0.5, trend_dir=1, trend_conf=60, fund_dir=1, fund_conf=60),
        _make_rec("Z2", "Z行业", 0.5, trend_dir=1, trend_conf=60, fund_dir=1, fund_conf=60),
    ]
    signals = calculate_industry_rotation(recs, "20260607")
    # A < Z (按字符串升序)
    assert signals[0].industry_name == "A行业"
    assert signals[1].industry_name == "Z行业"


# ============================================================================
# Test 21: P5-2 时序特性 — lookback_days=1 时不使用历史 (backward compatible)
# ============================================================================


def test_lookback_days_1_ignores_history(tmp_path):
    """lookback_days=1 时, 不使用历史, 结果与旧版本一致。"""
    # 创建历史报告 (但 lookback_days=1 应当忽略)
    reports_dir = tmp_path / "data" / "reports"
    reports_dir.mkdir(parents=True)

    # 历史报告: 20260605 电子行业强势
    import json

    history_report = {
        "mode": "auto_screening",
        "date": "20260605",
        "recommendations": [
            _make_rec("300001", "电子", 0.8, trend_dir=1, trend_conf=90, fund_dir=1, fund_conf=90),
            _make_rec("300002", "电子", 0.75, trend_dir=1, trend_conf=85, fund_dir=1, fund_conf=85),
        ],
    }
    (reports_dir / "auto_screening_20260605.json").write_text(json.dumps(history_report, ensure_ascii=False))

    # 当前推荐: 电子仅有微弱信号
    recs = [
        _make_rec("300001", "电子", 0.2, trend_dir=1, trend_conf=30, fund_dir=1, fund_conf=30),
        _make_rec("300002", "电子", 0.25, trend_dir=1, trend_conf=35, fund_dir=1, fund_conf=35),
    ]

    signals = calculate_industry_rotation(recs, trade_date="20260607", lookback_days=1, reports_dir=str(reports_dir))

    # lookback_days=1 时不应使用历史, 所以 momentum_score 仅来自当前数据
    # rec1: trend=(1*30), fund=(1*30), mr=0, event=0 → momentum=15.0
    # rec2: trend=(1*35), fund=(1*35), mr=0, event=0 → momentum=17.5
    # avg_momentum = (15.0 + 17.5) / 2 = 16.25
    assert len(signals) == 1
    assert math.isclose(signals[0].momentum_score, 16.25, abs_tol=0.1)
    # 不应有历史加分
    assert signals[0].history_bonus == 0.0
    assert signals[0].history_presence_ratio == 0.0


# ============================================================================
# Test 22: P5-2 时序特性 — lookback_days > 1 使用历史加强信号
# ============================================================================


def test_lookback_days_gt_1_uses_history_boost(tmp_path):
    """lookback_days > 1 时, 持续出现的行业因历史强度获得加分。"""
    reports_dir = tmp_path / "data" / "reports"
    reports_dir.mkdir(parents=True)

    import json

    # 历史报告 1: 20260605 电子强, 计算机弱
    history1 = {
        "mode": "auto_screening",
        "date": "20260605",
        "recommendations": [
            _make_rec("300001", "电子", 0.75, trend_dir=1, trend_conf=80, fund_dir=1, fund_conf=85),
            _make_rec("300002", "电子", 0.70, trend_dir=1, trend_conf=75, fund_dir=1, fund_conf=80),
            _make_rec("600001", "计算机", 0.1, trend_dir=1, trend_conf=20, fund_dir=1, fund_conf=25),
            _make_rec("600002", "计算机", 0.15, trend_dir=1, trend_conf=25, fund_dir=1, fund_conf=30),
        ],
    }
    (reports_dir / "auto_screening_20260605.json").write_text(json.dumps(history1, ensure_ascii=False))

    # 历史报告 2: 20260606 电子继续强, 计算机继续弱
    history2 = {
        "mode": "auto_screening",
        "date": "20260606",
        "recommendations": [
            _make_rec("300003", "电子", 0.78, trend_dir=1, trend_conf=82, fund_dir=1, fund_conf=88),
            _make_rec("300004", "电子", 0.72, trend_dir=1, trend_conf=77, fund_dir=1, fund_conf=82),
            _make_rec("600003", "计算机", 0.12, trend_dir=1, trend_conf=22, fund_dir=1, fund_conf=27),
            _make_rec("600004", "计算机", 0.18, trend_dir=1, trend_conf=28, fund_dir=1, fund_conf=32),
        ],
    }
    (reports_dir / "auto_screening_20260606.json").write_text(json.dumps(history2, ensure_ascii=False))

    # 当前推荐 20260607: 电子和计算机动量相同 (都是中性)
    recs = [
        _make_rec("300005", "电子", 0.4, trend_dir=1, trend_conf=50, fund_dir=1, fund_conf=50),
        _make_rec("300006", "电子", 0.45, trend_dir=1, trend_conf=52, fund_dir=1, fund_conf=52),
        _make_rec("600005", "计算机", 0.38, trend_dir=1, trend_conf=50, fund_dir=1, fund_conf=50),
        _make_rec("600006", "计算机", 0.42, trend_dir=1, trend_conf=52, fund_dir=1, fund_conf=52),
    ]

    signals = calculate_industry_rotation(recs, trade_date="20260607", lookback_days=3, reports_dir=str(reports_dir))  # 使用 2 天历史 + 当前

    # 电子应当排名第一 (因为历史强势)
    # 计算机应当排名第二 (历史弱势但当前也有)
    assert len(signals) == 2
    assert signals[0].industry_name == "电子", f"Expected 电子 first, got {signals[0].industry_name}"
    assert signals[1].industry_name == "计算机"

    # 电子的 history_presence_ratio 应为 1.0 (两天都出现)
    # 计算机的 history_presence_ratio 也应为 1.0
    # 但电子的 history_avg_score_b 应显著高于计算机
    assert signals[0].history_presence_ratio == 1.0
    assert signals[1].history_presence_ratio == 1.0
    assert signals[0].history_avg_score_b > signals[1].history_avg_score_b


# ============================================================================
# Test 23: P5-2 时序特性 — 历史不存在某行业时 presence_ratio < 1.0
# ============================================================================


def test_partial_history_presence(tmp_path):
    """某行业只在部分历史日期出现, presence_ratio 应反映此情况。"""
    reports_dir = tmp_path / "data" / "reports"
    reports_dir.mkdir(parents=True)

    import json

    # 历史报告 1: 20260605 只有电子
    history1 = {
        "mode": "auto_screening",
        "date": "20260605",
        "recommendations": [
            _make_rec("300001", "电子", 0.7, trend_dir=1, trend_conf=70, fund_dir=1, fund_conf=70),
            _make_rec("300002", "电子", 0.65, trend_dir=1, trend_conf=65, fund_dir=1, fund_conf=65),
        ],
    }
    (reports_dir / "auto_screening_20260605.json").write_text(json.dumps(history1, ensure_ascii=False))

    # 历史报告 2: 20260606 电子 + 计算机
    history2 = {
        "mode": "auto_screening",
        "date": "20260606",
        "recommendations": [
            _make_rec("300003", "电子", 0.72, trend_dir=1, trend_conf=72, fund_dir=1, fund_conf=72),
            _make_rec("300004", "电子", 0.68, trend_dir=1, trend_conf=68, fund_dir=1, fund_conf=68),
            _make_rec("600001", "计算机", 0.5, trend_dir=1, trend_conf=50, fund_dir=1, fund_conf=50),
            _make_rec("600002", "计算机", 0.55, trend_dir=1, trend_conf=55, fund_dir=1, fund_conf=55),
        ],
    }
    (reports_dir / "auto_screening_20260606.json").write_text(json.dumps(history2, ensure_ascii=False))

    # 当前推荐 20260607: 电子和计算机当前动量相同
    recs = [
        _make_rec("300005", "电子", 0.5, trend_dir=1, trend_conf=60, fund_dir=1, fund_conf=60),
        _make_rec("300006", "电子", 0.52, trend_dir=1, trend_conf=62, fund_dir=1, fund_conf=62),
        _make_rec("600003", "计算机", 0.5, trend_dir=1, trend_conf=60, fund_dir=1, fund_conf=60),
        _make_rec("600004", "计算机", 0.52, trend_dir=1, trend_conf=62, fund_dir=1, fund_conf=62),
    ]

    signals = calculate_industry_rotation(recs, trade_date="20260607", lookback_days=3, reports_dir=str(reports_dir))

    # 电子应当排名第一 (history_presence_ratio=1.0, 两天都出现)
    # 计算机排名第二 (history_presence_ratio=0.5, 只在 20260606 出现)
    assert len(signals) == 2
    assert signals[0].industry_name == "电子"
    assert signals[1].industry_name == "计算机"
    assert signals[0].history_presence_ratio == 1.0
    assert math.isclose(signals[1].history_presence_ratio, 0.5, abs_tol=0.01)


# ============================================================================
# Test 24: P5-2 时序特性 — 序列化输出包含历史字段
# ============================================================================


def test_to_dict_includes_history_fields(tmp_path):
    """to_dict() 序列化应包含 history_presence_ratio 和 history_avg_score_b。"""
    reports_dir = tmp_path / "data" / "reports"
    reports_dir.mkdir(parents=True)

    import json

    history1 = {
        "mode": "auto_screening",
        "date": "20260606",
        "recommendations": [
            _make_rec("300001", "电子", 0.8, trend_dir=1, trend_conf=80, fund_dir=1, fund_conf=80),
            _make_rec("300002", "电子", 0.75, trend_dir=1, trend_conf=75, fund_dir=1, fund_conf=75),
        ],
    }
    (reports_dir / "auto_screening_20260606.json").write_text(json.dumps(history1, ensure_ascii=False))

    recs = [
        _make_rec("300003", "电子", 0.6, trend_dir=1, trend_conf=60, fund_dir=1, fund_conf=60),
        _make_rec("300004", "电子", 0.65, trend_dir=1, trend_conf=65, fund_dir=1, fund_conf=65),
    ]

    signals = calculate_industry_rotation(recs, trade_date="20260607", lookback_days=2, reports_dir=str(reports_dir))

    assert len(signals) == 1
    d = signals[0].to_dict()

    # 应包含 history 相关字段
    assert "history_presence_ratio" in d
    assert "history_avg_score_b" in d
    assert "history_bonus" in d
    assert d["history_presence_ratio"] == 1.0
    assert d["history_avg_score_b"] > 0.7  # 历史平均 score_b 应该很高
