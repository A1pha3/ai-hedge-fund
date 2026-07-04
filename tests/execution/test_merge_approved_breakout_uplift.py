"""R152 — merge_approved_breakout_uplift NaN-escalation 守卫测试。

背景:
  ``_clamp_confidence`` 此前用 ``max(0.0, min(100.0, float(value or 0.0)))``。
  对 NaN 输入: ``float(NaN or 0.0)`` = NaN (NaN 是 truthy, ``or`` 不兜底),
  再 ``min(100.0, NaN)`` 在 CPython 返回 100.0 (NaN 比较 quirks), 最后
  ``max(0.0, 100.0)`` = 100.0。即 NaN confidence 被 escalate 成 **满分 100**。

  ``StrategySignal.confidence`` 是 Pydantic 字段 (拒绝 NaN/inf/>100), 但
  ``sub_factors`` 内层 dict 的 confidence 值 **不经 Pydantic 校验**。一个 NaN
  sub_factor confidence 经 ``_signal_snapshot`` 变成 100.0, 再让
  ``_positive_complete`` gate 通过, 最终使 **垃圾置信度的标的** 获得 breakout
  uplift 资格 (boost 前门排名)。同族 R146 (NaN-through-constraints) /
  R141b (NaN-through-slope) / BH-012, 本变体更严重 (NaN→max 而非单纯传播)。

  修复: ``_clamp_confidence`` 用 ``math.isfinite`` 守卫, NaN/inf/非数值 → 0.0
  (invalid = 无置信度, 正确 fail gate)。
"""

from __future__ import annotations

import math

from src.execution.merge_approved_breakout_uplift import (
    MERGE_APPROVED_BREAKOUT_UPLIFT_TREND_CONFIDENCE_MIN,
    _clamp_confidence,
    _positive_complete,
    _signal_snapshot,
    apply_merge_approved_breakout_uplift_to_signal_map,
)
from src.screening.models import StrategySignal

# ===========================================================================
# R152a — _clamp_confidence NaN/inf 不再 escalate 到 100.0
# ===========================================================================


def test_clamp_confidence_nan_returns_zero() -> None:
    """R152: NaN confidence → 0.0 (此前被 escalate 到 100.0 满分)。"""
    result = _clamp_confidence(float("nan"))
    assert result == 0.0
    assert not math.isnan(result)


def test_clamp_confidence_inf_returns_zero() -> None:
    """R152: inf confidence → 0.0 (invalid = 无置信度), 不再 → 100.0。"""
    assert _clamp_confidence(float("inf")) == 0.0
    assert _clamp_confidence(float("-inf")) == 0.0


def test_clamp_confidence_none_and_non_numeric_return_zero() -> None:
    """R152: None / 非数值 → 0.0, 不抛异常。"""
    assert _clamp_confidence(None) == 0.0  # type: ignore[arg-type]
    assert _clamp_confidence("abc") == 0.0  # type: ignore[arg-type]


def test_clamp_confidence_valid_floats_unaffected() -> None:
    """R152: 合法 float 仍正确 clamp 到 [0, 100], 修复不改变正常路径。"""
    assert _clamp_confidence(50.0) == 50.0
    assert _clamp_confidence(0.0) == 0.0
    assert _clamp_confidence(100.0) == 100.0
    assert _clamp_confidence(-5.0) == 0.0
    assert _clamp_confidence(150.0) == 100.0
    assert _clamp_confidence(72.5) == 72.5


# ===========================================================================
# R152b — NaN sub_factor confidence 不再让 _signal_snapshot 产出 100.0
# ===========================================================================


def _signal_with_nan_momentum_confidence() -> StrategySignal:
    """构造 trend signal: momentum sub_factor 的 confidence 是 NaN (sub_factors
    内层不经 Pydantic 校验, NaN 可达)。direction/completeness 合法。"""
    return StrategySignal(
        direction=1,
        confidence=80.0,
        completeness=1.0,
        sub_factors={
            "momentum": {"direction": 1, "confidence": float("nan"), "completeness": 1.0, "metrics": {}},
            "volatility": {
                "direction": 1,
                "confidence": 70.0,
                "completeness": 1.0,
                "metrics": {"volatility_regime": 1.5, "atr_ratio": 0.1},
            },
        },
    )


def test_signal_snapshot_nan_confidence_not_escalated() -> None:
    """R152: NaN sub_factor confidence 经 _signal_snapshot 后 = 0.0, 不再 = 100.0。"""
    trend = _signal_with_nan_momentum_confidence()
    snap = _signal_snapshot(trend, "momentum")
    assert snap["confidence"] == 0.0
    assert not math.isnan(snap["confidence"])


def test_positive_complete_nan_confidence_fails_gate() -> None:
    """R152: NaN-confidence sub_factor 应 fail _positive_complete (invalid ≠ positive)。

    修复前: _signal_snapshot 把 NaN escalate 到 100.0, _positive_complete 读到 100.0
    误判为 positive (gate 通过垃圾信号)。
    """
    trend = _signal_with_nan_momentum_confidence()
    snap = _signal_snapshot(trend, "momentum")
    result = _positive_complete(snap, confidence_min=MERGE_APPROVED_BREAKOUT_UPLIFT_TREND_CONFIDENCE_MIN)
    assert result is False, "NaN-confidence sub_factor must not pass the positive-complete gate"


# ===========================================================================
# R152c — NaN sub_factor confidence 不再让标的获得 breakout uplift 资格
# ===========================================================================


def test_nan_momentum_confidence_does_not_qualify_for_uplift() -> None:
    """R152 端到端: momentum sub_factor confidence=NaN 的标的不应 eligible。

    修复前: NaN→100.0 escalation 让 gate_hits['momentum_subfactor']=True,
    eligible=True, 垃圾置信度标的获得 breakout boost (前门排名提升)。
    score_b=0.3 (>SCORE_B_MIN), trend 本身合法 — 仅 momentum 是 NaN。
    """
    trend = _signal_with_nan_momentum_confidence()
    signals = {"trend": trend}
    _updated, diagnostics = apply_merge_approved_breakout_uplift_to_signal_map(signals, score_b=0.3)
    assert diagnostics["gate_hits"]["momentum_subfactor"] is False, "NaN-confidence momentum must fail its gate, not escalate to pass"
    assert diagnostics["eligible"] is False, "A stock with NaN (garbage) momentum confidence must not qualify for the breakout uplift"
    assert diagnostics["applied"] is False
