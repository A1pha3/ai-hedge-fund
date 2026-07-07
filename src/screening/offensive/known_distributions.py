"""Phase 0 验证过的已知 setup 分布 (从全池真实回测产出)。

这些是 --daily-action 用于 Kelly 仓位 + 风险计划的"先验"。
每个分布对应一个 setup 在特定 horizon 的全池 execution-adjusted 历史统计。

⚠ 重要: 这些分布来自历史回测, 不是未来承诺。setup IC 会衰减, 需定期重测
(月度重校准, 见 risk_framework 的衰减监控)。

当前已验证 (2026-07-07 全池 300 ticker 真实回测):
- btst_breakout @ T+10: cv=1.53, winrate=50.6%, E=+2.57%, n=5374
  → 小但统计显著的真实 edge (CI 不跨 0)
  → IS/OOS 有分裂 (IS cv=1.29 / OOS cv=2.04), 用 half-Kelly 保守对冲
"""

from __future__ import annotations

from src.screening.offensive.statistics import Distribution

# BTST 突破 T+10 全池真实分布 (2026-07-07 explore_btst_fullpool.py 产出)
# 300 ticker × 2020-2026, 9242 候选涨停日 → 5715 命中 → ~5374 execution-adjusted
BTST_BREAKOUT_T10 = Distribution(
    n=5374,
    winrate=0.506,
    avg_gain=0.1457,  # +14.57%
    avg_loss=-0.0975,  # -9.75%
    convexity_ratio=1.53,
    expected_return=0.0257,  # +2.57%
    ci_low=0.0213,
    ci_high=0.0301,
    ic=0.0,  # 全池 IC 未单算 (setup 命中 vs 基线); 用 convexity 代替准入判断
)

# 已知分布注册表: {(setup_name, horizon): Distribution}
# --daily-action 查这个表拿先验分布
KNOWN_DISTRIBUTIONS: dict[tuple[str, int], Distribution] = {
    ("btst_breakout", 10): BTST_BREAKOUT_T10,
}


def get_known_distribution(setup_name: str, horizon: int) -> Distribution | None:
    """查已知分布; 未验证的 setup 返回 None (--daily-action 会拒绝出信号)."""
    return KNOWN_DISTRIBUTIONS.get((setup_name, horizon))
