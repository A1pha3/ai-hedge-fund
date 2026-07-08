"""Phase 0 验证过的已知 setup 分布 (从全池真实回测产出)。

这些是 --daily-action 用于 Kelly 仓位 + 风险计划的"先验"。
每个分布对应一个 setup 在特定 horizon 的全池 execution-adjusted 历史统计。

⚠ 重要: 这些分布来自历史回测, 不是未来承诺。setup IC 会衰减, 需定期重测
(月度重校准, 见 risk_framework 的衰减监控)。

当前已验证 (2026-07-08 全池 302 ticker 真实回测, 新 detect 含条件4):
- btst_breakout @ T+10: cv=2.18, winrate=60.9%, E=+4.46%, n=915, IC=0.131
  → 条件4 (涨停前5日涨幅≤5%) 过滤后, alpha 显著提升 (旧版 cv=1.53/win=50.6%)
  → CI [3.46%, 5.51%] 远不跨 0, IC 0.131 有排序信息
  → 与 OversoldBounce 的超跌反转逻辑同构
- oversold_bounce @ T+5: cv=2.51, winrate=59.2%, E=+3.42%, n=1113, IC=0.041
  → 超跌反弹 (30日跌>20% + 资金回流), T+5 alpha 最强
  → CI [2.78%, 4.03%] 远不跨 0, crisis regime 下 alpha 更集中 (+3.58%)
"""

from __future__ import annotations

from src.screening.offensive.statistics import Distribution

# BTST 突破 T+10 全池真实分布 (2026-07-08 重算, 含条件4: 涨停前5日涨幅≤5%)
# 302 ticker × 2020-2026, 9283 候选涨停日 → 941 命中 → 915 execution-adjusted
BTST_BREAKOUT_T10 = Distribution(
    n=915,
    winrate=0.609,
    avg_gain=0.1354,  # +13.54%
    avg_loss=-0.0966,  # -9.66%
    convexity_ratio=2.18,
    expected_return=0.0446,  # +4.46%
    ci_low=0.0346,
    ci_high=0.0551,
    ic=0.131,
)

# OversoldBounce 超跌反弹 T+5 全池真实分布 (2026-07-08)
# 302 ticker × 2020-2026, 27352 候选超跌日 → 1124 命中 → 1113 execution-adjusted
OVERSOLD_BOUNCE_T5 = Distribution(
    n=1113,
    winrate=0.592,
    avg_gain=0.0962,  # +9.62%
    avg_loss=-0.0557,  # -5.57%
    convexity_ratio=2.51,
    expected_return=0.0342,  # +3.42%
    ci_low=0.0278,
    ci_high=0.0403,
    ic=0.041,
)

# 已知分布注册表: {(setup_name, horizon): Distribution}
# --daily-action 查这个表拿先验分布
KNOWN_DISTRIBUTIONS: dict[tuple[str, int], Distribution] = {
    ("btst_breakout", 10): BTST_BREAKOUT_T10,
    ("oversold_bounce", 5): OVERSOLD_BOUNCE_T5,
}


def get_known_distribution(setup_name: str, horizon: int) -> Distribution | None:
    """查已知分布; 未验证的 setup 返回 None (--daily-action 会拒绝出信号)."""
    return KNOWN_DISTRIBUTIONS.get((setup_name, horizon))
