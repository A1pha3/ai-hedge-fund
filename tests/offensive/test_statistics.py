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


# ---- setup_p_value (单样本 t 检验, FDR 的输入) ----


def test_setup_p_value_significant_positive():
    """显著正收益 (n=100, mean≈+5%) → p < 0.05."""
    from src.screening.offensive.statistics import setup_p_value

    rng = np.random.default_rng(42)
    returns = rng.normal(0.05, 0.10, 100)  # mean +5%, std 10%
    p = setup_p_value(returns)
    assert p < 0.05, f"显著正收益应 p<0.05, got {p}"
    assert p >= 0.0


def test_setup_p_value_noise_not_significant():
    """噪声 (mean≈0) → p > 0.1 (不拒绝 H0: mean=0)."""
    from src.screening.offensive.statistics import setup_p_value

    rng = np.random.default_rng(42)
    returns = rng.normal(0.0, 0.10, 100)  # mean 0, 纯噪声
    p = setup_p_value(returns)
    assert p > 0.1, f"噪声应 p>0.1, got {p}"


def test_setup_p_value_empty_returns_one():
    """空输入 → p=1.0 (保守, 不拒绝 H0)."""
    from src.screening.offensive.statistics import setup_p_value

    assert setup_p_value(np.array([])) == 1.0


def test_setup_p_value_insufficient_n_returns_one():
    """n<2 无法做 t 检验 → p=1.0 (保守)."""
    from src.screening.offensive.statistics import setup_p_value

    assert setup_p_value(np.array([0.05])) == 1.0  # n=1


def test_setup_p_value_zero_variance_returns_one():
    """方差为 0 (全相同) → t 检验退化 → p=1.0 (保守).

    全零收益 (无 alpha 信号) 应保守判为不显著.
    """
    from src.screening.offensive.statistics import setup_p_value

    assert setup_p_value(np.array([0.0, 0.0, 0.0, 0.0])) == 1.0
