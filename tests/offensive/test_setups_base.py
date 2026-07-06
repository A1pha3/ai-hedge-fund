"""Setup 抽象基类测试。"""
from __future__ import annotations

import pytest

from src.screening.offensive.setups.base import Setup, DetectionResult


class _FakeSetup(Setup):
    name = "fake"
    natural_horizon = 5

    def detect(self, ticker, trade_date, context):
        return DetectionResult(
            hit=True,
            ticker=ticker,
            trade_date=trade_date,
            trigger_strength=0.8,
            invalidation_condition="价格跌破 entry × 0.92",
            metadata={"foo": "bar"},
        )


def test_detection_result_fields():
    r = DetectionResult(hit=True, ticker="X", trade_date="20260701", trigger_strength=0.5, invalidation_condition="c", metadata={})
    assert r.hit is True
    assert r.ticker == "X"


def test_setup_subclass_must_implement_detect():
    """Setup ABC 强制子类实现 detect。"""
    with pytest.raises(TypeError):
        Setup()  # 不能实例化 ABC


def test_setup_subclass_detect_returns_result():
    s = _FakeSetup()
    r = s.detect("300054", "20260701", context={})
    assert isinstance(r, DetectionResult)
    assert r.hit is True
    assert r.trigger_strength == 0.8
    assert "0.92" in r.invalidation_condition
