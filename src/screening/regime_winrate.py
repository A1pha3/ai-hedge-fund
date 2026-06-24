"""R-5.A 按 regime 展示真实历史胜率 / regime-aware win-rate disclosure.

真实回测 (2026-06-24, 14 日期 91 只真实推荐) 揭示一个反直觉但关键的事实:
系统 ``regime_gate_level`` 的标签语义是为**风控**设计的, 但对**选股赚钱**而言
方向相反——

  crisis regime (广度极弱, 结构性行情): 真实 T+30 胜率 73%, median +8.24%
      → 模型选股能发挥 (挑出少数大涨的票) → **赚钱**
  normal regime (广度强, 普涨普跌震荡): 真实 T+30 胜率 24%, median -8.74%
      → 选股无 alpha (买什么都差不多且震荡易亏) → **亏钱**

这不是 regime gate 的 bug (广度弱=结构脆弱是标准风控语义), 而是它与"赚钱工具"
目标的**错配**: gate 在结构性行情 (选股最强场景) 降仓, 在震荡市 (选股无效) 满仓。

R-5.A 是**零行为改变**的第一步: 不碰 gate / 不碰仓位, 只在 --top-picks footer
按 current regime 展示真实历史胜率, 让用户看到当前期望自己决定。这是赚钱工具的
诚实基础, 也是验证"结构性行情赚钱"假设是否持续的第一步。

数据源: ``REGIME_HISTORICAL_WINRATES`` 内嵌真实回测结果 (随 daily scheduling
累积应定期重算; 硬编码是 v1, 后续可改为从 tracking_history 动态算)。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.utils.display import Fore, Style


@dataclass(frozen=True)
class RegimeWinrateSummary:
    """单个 regime 的真实历史 T+30 表现摘要。"""

    regime: str
    has_data: bool = False
    winrate: float = 0.0  # 0-1, T+30 正收益比例
    avg_return: float = 0.0  # 百分点
    median_return: float = 0.0  # 百分点 (典型票, 免异常值)
    sample_count: int = 0


# 真实回测结果 (2026-06-24, 扩充至 32 日期 ~189 只真实推荐, tushare 真实 T+30)。
# 扩样本后结论: 三 regime 胜率接近 (normal 43% / crisis 47% / risk_off 30%),
# 典型票 (median) 都微亏到平 — 没有哪个 regime 明显赚钱 (推翻了早期小样本
# "crisis 73% 赚钱" 的偏差结论)。regime 差异主要体现在 risk_off 略差。
# 随 daily scheduling 累积应定期重算 (v2 扩充版, 替代 v1 91 只小样本)。
REGIME_HISTORICAL_WINRATES: dict[str, dict] = {
    "crisis": {"winrate": 0.468, "avg_return": 0.58, "median_return": -0.93, "sample_count": 119},
    "normal": {"winrate": 0.434, "avg_return": 1.31, "median_return": -4.37, "sample_count": 60},
    "risk_off": {"winrate": 0.30, "avg_return": -1.89, "median_return": -5.12, "sample_count": 10},
}


# regime 的产品语义提示 (基于扩充后真实回测: 三 regime 胜率都 30-47%, 典型票微亏)
_REGIME_ADVICE: dict[str, str] = {
    "crisis": "广度弱结构性行情, 历史胜率 ~47%, 典型票微亏 (扩样本后无显著 alpha)",
    "normal": "广度强常态市, 历史胜率 ~43%, 典型票微亏, 建议谨慎",
    "risk_off": "避险/弱势市, 历史胜率仅 ~30%, 典型票 -5%, 建议空仓/轻仓",
}


def compute_regime_winrate_summary(regime: str) -> RegimeWinrateSummary:
    """查 regime 的真实历史 T+30 表现。

    Args:
        regime: ``regime_gate_level`` 值 (normal / crisis / risk_off)

    Returns:
        :class:`RegimeWinrateSummary` (无样本/未知 regime → ``has_data=False``)
    """
    key = (regime or "").strip().lower()
    stats = REGIME_HISTORICAL_WINRATES.get(key)
    if not stats:
        return RegimeWinrateSummary(regime=regime or "")
    return RegimeWinrateSummary(
        regime=key,
        has_data=True,
        winrate=stats["winrate"],
        avg_return=stats["avg_return"],
        median_return=stats["median_return"],
        sample_count=stats["sample_count"],
    )


def render_regime_winrate_line(regime: str) -> str:
    """渲染单行 regime 真实胜率提示 (无数据 → 空串)。

    展示形如:
      ``  📊 当前市场 (crisis): 历史真实胜率 73% | 典型 +8.24% | 结构性行情...``
    颜色随胜率: ≥50% 绿 / 30-50% 黄 / <30% 红。
    """
    s = compute_regime_winrate_summary(regime)
    if not s.has_data:
        return ""

    if s.winrate >= 0.5:
        color = Fore.GREEN
    elif s.winrate >= 0.3:
        color = Fore.YELLOW
    else:
        color = Fore.RED

    advice = _REGIME_ADVICE.get(s.regime, "")
    parts = [
        f"  📊 当前市场 ({s.regime}): {color}历史真实胜率 {s.winrate:.0%}{Style.RESET_ALL}",
        f"| 典型 {s.median_return:+.1f}%",
        f"| 样本 n={s.sample_count}",
    ]
    if advice:
        parts.append(f"| {color}{advice}{Style.RESET_ALL}")
    return " ".join(parts)


__all__ = [
    "RegimeWinrateSummary",
    "REGIME_HISTORICAL_WINRATES",
    "compute_regime_winrate_summary",
    "render_regime_winrate_line",
]
