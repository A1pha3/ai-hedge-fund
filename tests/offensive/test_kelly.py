"""Kelly 仓位计算测试。"""
from __future__ import annotations

import pytest

from src.screening.offensive.kelly import kelly_fraction, compute_kelly_size, KellySize
from src.screening.offensive.statistics import Distribution


def test_kelly_fraction_strong_setup():
    """winrate 0.6, +20%, -8% → Kelly > 0 (正期望, 该下注)。"""
    k = kelly_fraction(0.6, 0.20, -0.08)
    # kelly = 0.6/0.08 - 0.4/0.20 = 7.5 - 2.0 = 5.5 (极强, 实际会 cap)
    assert k > 1.0


def test_kelly_fraction_negative_expectation():
    """winrate 0.3, +10%, -10% → Kelly < 0 (不该下注)。"""
    k = kelly_fraction(0.3, 0.10, -0.10)
    assert k < 0


def test_kelly_fraction_zero_on_invalid_inputs():
    assert kelly_fraction(0.0, 0.1, -0.1) == 0.0  # winrate=0
    assert kelly_fraction(0.5, 0.0, -0.1) == 0.0  # avg_gain=0
    assert kelly_fraction(0.5, 0.1, 0.0) == 0.0  # avg_loss=0


def test_compute_kelly_size_half_kelly():
    """half-Kelly = 0.5 × full Kelly。"""
    dist = Distribution(n=60, winrate=0.6, avg_gain=0.20, avg_loss=-0.08,
                        convexity_ratio=3.0, expected_return=0.1, ci_low=0.05, ci_high=0.15, ic=0.08)
    ks = compute_kelly_size(dist)
    assert ks.kelly_raw > 1.0  # 强 setup
    assert abs(ks.kelly_half - 0.5 * ks.kelly_raw) < 1e-9


def test_compute_kelly_size_capped_at_max_pct():
    """half-Kelly 超过 max_pct 时被 cap。"""
    dist = Distribution(n=60, winrate=0.7, avg_gain=0.30, avg_loss=-0.05,
                        convexity_ratio=10.0, expected_return=0.2, ci_low=0.15, ci_high=0.25, ic=0.10)
    ks = compute_kelly_size(dist, max_pct=0.10)
    assert ks.position_pct <= 0.10
    assert ks.capped is True


def test_compute_kelly_size_correlation_discount_reduces_position():
    """相关性折价降低仓位 (用弱 setup 避免 max_pct cap 干扰)。"""
    # winrate 0.55, +5%, -3% → kelly = 0.55/0.03 - 0.45/0.05 = 18.33 - 9 = 9.33; half = 4.67
    # 用更弱的: winrate 0.52, +3%, -2.5% → kelly = 0.52/0.025 - 0.48/0.03 = 20.8 - 16 = 4.8; half=2.4
    # 还是太强。用一个刚好 half-kelly 在 0.05 附近的:
    # winrate 0.52, avg_gain 0.04, avg_loss -0.04 → kelly = 0.52/0.04 - 0.48/0.04 = 13 - 12 = 1.0; half=0.5
    dist = Distribution(n=60, winrate=0.52, avg_gain=0.04, avg_loss=-0.04,
                        convexity_ratio=1.3, expected_return=0.005, ci_low=-0.01, ci_high=0.02, ic=0.06)
    ks_no_discount = compute_kelly_size(dist, correlation_discount=1.0, max_pct=1.0)
    ks_discount = compute_kelly_size(dist, correlation_discount=0.5, max_pct=1.0)
    assert ks_discount.position_pct < ks_no_discount.position_pct
    assert abs(ks_discount.position_pct - ks_no_discount.position_pct * 0.5) < 1e-9


def test_compute_kelly_size_negative_returns_zero():
    """负期望 (Kelly<0) → 仓位 0。"""
    dist = Distribution(n=60, winrate=0.3, avg_gain=0.10, avg_loss=-0.10,
                        convexity_ratio=0.5, expected_return=-0.04, ci_low=-0.08, ci_high=0.0, ic=-0.05)
    ks = compute_kelly_size(dist)
    assert ks.position_pct == 0.0
