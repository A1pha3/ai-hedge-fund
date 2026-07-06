"""统计工具测试。纯数学, 无 IO。"""

from __future__ import annotations

import numpy as np

from src.screening.offensive.statistics import (
    Distribution,
    compute_distribution,
    information_coefficient,
)


def test_compute_distribution_basic_positive_convexity():
    """60% 赢 +20%, 40% 输 -8% → convexity_ratio > 1, winrate 0.6。"""
    returns = np.array([0.20, 0.25, 0.18, -0.08, -0.07, 0.22, -0.09, 0.20, -0.08, 0.21])
    dist = compute_distribution(returns)
    assert dist.n == 10
    assert abs(dist.winrate - 0.6) < 1e-9
    assert dist.avg_gain > 0.15
    assert dist.avg_loss < -0.05
    assert dist.convexity_ratio > 1.5  # (0.2×0.6)/(0.08×0.4) ≈ 3.75
    assert dist.expected_return > 0


def test_compute_distribution_all_wins():
    """全赢: avg_loss=0, convexity_ratio=inf (cap 到 999)。"""
    returns = np.array([0.1, 0.2, 0.15])
    dist = compute_distribution(returns)
    assert dist.winrate == 1.0
    assert dist.convexity_ratio >= 999  # capped sentinel


def test_compute_distribution_empty_returns_zero_n():
    dist = compute_distribution(np.array([]))
    assert dist.n == 0
    assert dist.winrate == 0.0


def test_information_coefficient_perfect_positive():
    """scores 与 forward_returns 完全正相关 → IC ≈ 1。"""
    scores = np.array([1, 2, 3, 4, 5])
    fwd = np.array([0.01, 0.02, 0.03, 0.04, 0.05])
    ic = information_coefficient(scores, fwd)
    assert ic > 0.99


def test_information_coefficient_orthogonal_near_zero():
    """不相关 → IC ≈ 0。"""
    np.random.seed(42)
    scores = np.arange(100)
    fwd = np.random.randn(100)
    ic = information_coefficient(scores, fwd)
    assert abs(ic) < 0.2


def test_ci_bracket_contains_mean():
    """bootstrap CI 包含样本均值。"""
    np.random.seed(0)
    returns = np.random.randn(50) * 0.05 + 0.03
    dist = compute_distribution(returns)
    assert dist.ci_low <= dist.expected_return <= dist.ci_high


# ---- Benjamini-Hochberg FDR (v2 §C.5) ----


def test_fdr_all_significant_passes():
    """全部极显著 p-value → 全部通过 FDR。"""
    from src.screening.offensive.statistics import benjamini_hochberg_fdr

    p = np.array([0.001, 0.002, 0.003])
    q, sig = benjamini_hochberg_fdr(p, alpha=0.05)
    assert len(sig) == 3


def test_fdr_filters_noise():
    """几个极小 p + 几个大 p → 大 p 的不通过。"""
    from src.screening.offensive.statistics import benjamini_hochberg_fdr

    p = np.array([0.001, 0.45, 0.50, 0.60])  # 第 1 个显著, 其余噪声
    q, sig = benjamini_hochberg_fdr(p, alpha=0.05)
    assert 0 in sig  # 极显著的通过
    assert 1 not in sig and 2 not in sig and 3 not in sig  # 噪声的不通过


def test_fdr_empty_input():
    from src.screening.offensive.statistics import benjamini_hochberg_fdr

    q, sig = benjamini_hochberg_fdr(np.array([]))
    assert len(q) == 0
    assert sig == []
