"""凸性 setup 统计工具: 分布计算 + IC + bootstrap CI。

纯数学, 无 IO, 无 LLM。可独立单测。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# 当 avg_loss==0 (全赢) 时 convexity_ratio 的上限哨兵
_CONVEXITY_CAP = 999.0


@dataclass(frozen=True)
class Distribution:
    """历史收益分布的统计摘要。"""

    n: int
    winrate: float
    avg_gain: float  # 正收益样本均值
    avg_loss: float  # 负收益样本均值 (负数)
    convexity_ratio: float  # (avg_gain × winrate) / (|avg_loss| × lossrate)
    expected_return: float  # = winrate × avg_gain + lossrate × avg_loss
    ci_low: float  # 95% bootstrap CI 下界 (expected_return)
    ci_high: float  # 95% bootstrap CI 上界
    ic: float = 0.0  # vs 全市场基线的 information coefficient (可选)


def _bootstrap_expected_return_ci(returns: np.ndarray, n_boot: int = 2000, seed: int = 42, alpha: float = 0.05) -> tuple[float, float]:
    """Bootstrap expected_return (均值) 的双侧 CI。"""
    if len(returns) == 0:
        return (0.0, 0.0)
    rng = np.random.default_rng(seed)
    boots = np.empty(n_boot)
    for i in range(n_boot):
        sample = rng.choice(returns, size=len(returns), replace=True)
        boots[i] = sample.mean()
    return float(np.quantile(boots, alpha / 2)), float(np.quantile(boots, 1 - alpha / 2))


def compute_distribution(returns: np.ndarray) -> Distribution:
    """从收益序列计算分布摘要。

    Args:
        returns: T+N 收益率序列 (小数, e.g. 0.05 = +5%)。允许空。

    Returns:
        Distribution; n=0 时其余字段为 0。
    """
    returns = np.asarray(returns, dtype=float)
    returns = returns[np.isfinite(returns)]
    n = len(returns)
    if n == 0:
        return Distribution(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    wins = returns[returns > 0]
    losses = returns[returns <= 0]
    winrate = len(wins) / n if n > 0 else 0.0
    lossrate = 1.0 - winrate
    avg_gain = float(wins.mean()) if len(wins) > 0 else 0.0
    avg_loss = float(losses.mean()) if len(losses) > 0 else 0.0

    if avg_loss == 0.0:
        convexity = _CONVEXITY_CAP  # 全赢或 losses 全 0, 凸性无穷 (capped)
    else:
        convexity = (avg_gain * winrate) / (abs(avg_loss) * lossrate)

    expected_return = float(returns.mean())
    ci_low, ci_high = _bootstrap_expected_return_ci(returns)

    return Distribution(
        n=n,
        winrate=winrate,
        avg_gain=avg_gain,
        avg_loss=avg_loss,
        convexity_ratio=convexity,
        expected_return=expected_return,
        ci_low=ci_low,
        ci_high=ci_high,
    )


def information_coefficient(scores: np.ndarray, forward_returns: np.ndarray) -> float:
    """Spearman rank IC: scores 与 forward_returns 的秩相关。

    Args:
        scores: setup 触发强度 / 信号分 (命中=1, 未命中=0 也可)
        forward_returns: 对应的 T+N 收益

    Returns:
        Spearman IC ∈ [-1, 1]; 输入长度不足或方差为 0 时返回 0。
    """
    scores = np.asarray(scores, dtype=float)
    forward_returns = np.asarray(forward_returns, dtype=float)
    mask = np.isfinite(scores) & np.isfinite(forward_returns)
    scores, forward_returns = scores[mask], forward_returns[mask]
    if len(scores) < 5 or scores.std() == 0 or forward_returns.std() == 0:
        return 0.0
    # Spearman = Pearson on ranks
    from scipy.stats import rankdata

    return float(np.corrcoef(rankdata(scores), rankdata(forward_returns))[0, 1])


def benjamini_hochberg_fdr(p_values: np.ndarray, alpha: float = 0.05) -> tuple[np.ndarray, list[int]]:
    """Benjamini-Hochberg FDR 校正 (v2 §C.5 防多重检验 p-hacking)。

    多个 setup 同时回测时, 单个 p-value 显著不等于整体显著 (假阳性膨胀)。
    BH 校正控制 false discovery rate。

    Args:
        p_values: N 个检验的原始 p-value
        alpha: 目标 FDR (默认 0.05)

    Returns:
        (q_values, significant_indices): 校正后的 q-value 数组 + 显著的索引列表
    """
    p_values = np.asarray(p_values, dtype=float)
    n = len(p_values)
    if n == 0:
        return np.array([]), []

    # BH: 排序, q_i = p_i × n / rank_i, 累积 min
    order = np.argsort(p_values)
    ranked = p_values[order]
    q = np.empty(n)
    prev_q = 1.0
    for i in range(n - 1, -1, -1):
        rank = i + 1
        raw_q = ranked[i] * n / rank
        prev_q = min(prev_q, raw_q, 1.0)
        q[i] = prev_q
    # 还原原顺序
    q_original_order = np.empty(n)
    q_original_order[order] = q
    significant = [i for i in range(n) if q_original_order[i] <= alpha]
    return q_original_order, significant
