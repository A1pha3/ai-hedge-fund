"""Phase 0 验证过的已知 setup 分布 (从全池真实回测产出)。

这些是 --daily-action 用于 Kelly 仓位 + 风险计划的"先验"。
每个分布对应一个 setup 在特定 horizon 的全池 execution-adjusted 历史统计。

⚠ 重要: 这些分布来自历史回测, 不是未来承诺。setup IC 会衰减, 需定期重测
(月度重校准, 见 risk_framework 的衰减监控)。

当前已验证:
- btst_breakout @ T+10: cv=1.81, winrate=54.2%, E=+3.38%, n=1762, IC=0.126
  → 条件4 (涨停前5日涨幅≤5%) 过滤后, alpha 显著提升 (旧版 cv=1.53/win=50.6%)
  → CI [2.57%, 4.15%] 远不跨 0, IC 0.126 有排序信息
  → paper_trading_backtest 实测更优: win=68.4%, E=+8.15%, n=133 (牛市样本)
- oversold_bounce @ T+5: ⚠ 已用真实成交数据重校准 (2026-07-11)
  → 旧先验 (Phase 0) E=+3.42%/cv=2.51 严重高估: avg_loss 被 2x 低估
  → 真实回测: E=+0.34%, cv=0.96 (<1.5), CI [-3.15%, +3.83%] 跨 0
  → 当前默认暂停 (DAILY_ACTION_DISABLED_SETUPS), 仓位 Kelly f*≈0
"""

from __future__ import annotations

from src.screening.offensive.statistics import Distribution

# BTST 突破 T+10 全池真实分布 (2026-07-08 重算, 含条件4: 涨停前5日涨幅≤5%, 不含涨停日)
# 302 ticker × 2020-2026, 9283 候选涨停日 → 1804 命中 → 1762 execution-adjusted
BTST_BREAKOUT_T10 = Distribution(
    n=1762,
    winrate=0.5420,
    avg_gain=0.1398,  # +13.98%
    avg_loss=-0.0917,  # -9.17%
    convexity_ratio=1.8056,
    expected_return=0.0338,  # +3.38%
    ci_low=0.0257,
    ci_high=0.0415,
    ic=0.1256,
)

# OversoldBounce 超跌反弹 T+5 — 用 paper_trading_backtest 真实成交重校准 (2026-07-11)
# ⚠ 旧先验 (Phase 0 全池回测) avg_loss=-5.57% 严重低估: 实际回测 avg_loss=-11.15% (2x).
#   convexity 从 2.51 降到 0.96 (<1.5 门槛), E[r]=+0.34% 且 95% CI 跨 0 (p≈0.85).
#   这意味着 OversoldBounce 在当前样本无可证明的 alpha, Kelly 会给出极小或零仓位.
# 数据来源: data/paper_trading_backtest/journal.jsonl, 59 笔配对交易 (2026-01~07).
# 样本仅 6 个月牛市, 非定论 — 补全历史数据重跑后再次校准.
OVERSOLD_BOUNCE_T5 = Distribution(
    n=59,
    winrate=0.525,
    avg_gain=0.1073,  # +10.73%
    avg_loss=-0.1115,  # -11.15% (原 -5.57% 严重低估)
    convexity_ratio=0.96,  # <1.5 → Kelly f* ≈ 0, 不值得分配仓位
    expected_return=0.0034,  # +0.34%
    ci_low=-0.0315,  # 95% CI 跨 0 → 无统计显著的 alpha
    ci_high=0.0383,
    ic=0.003,
)

# 已知分布注册表: {(setup_name, horizon): Distribution}
# --daily-action 查这个表拿先验分布
# BTST horizon 从 10→8: T+8 mean 最优 (+6.33% vs T+10 +5.76%), 避免 T+9/T+10 回吐
KNOWN_DISTRIBUTIONS: dict[tuple[str, int], Distribution] = {
    ("btst_breakout", 8): BTST_BREAKOUT_T10,   # key 改 8, 分布仍用 T+10 校准值 (保守)
    ("btst_breakout", 10): BTST_BREAKOUT_T10,   # 保留旧 key 供回测兼容
    ("oversold_bounce", 5): OVERSOLD_BOUNCE_T5,
}


def get_known_distribution(setup_name: str, horizon: int) -> Distribution | None:
    """查已知分布; 未验证的 setup 返回 None (--daily-action 会拒绝出信号)."""
    return KNOWN_DISTRIBUTIONS.get((setup_name, horizon))
