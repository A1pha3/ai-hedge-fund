"""R-3 组合风险预算总览 — portfolio-level risk-budget synthesis.

P-4 (行业集中度), Q-4 (相关性仓位折减), R145 (per-pick 仓位) 各自度量一个风险
维度, 但此前无单一"组合总风险 vs 预算"数。R-3 把集中度 + 相关性合成一个
0-100% 的预算占用, 让用户一眼看到"今天这个组合用了多少风险预算"。

设计原则:
  - **read-only 合成** — 复用既有 ``compute_industry_concentration`` /
    ``compute_correlation_discount``, 不重算, 不进排序/决策
  - **诚实降级** — 数据不足 (无合法行业 / <2 picks) → 静默不渲染 (同 R-1/R-2)
  - **预算占用有界** — 0-100%, 高占用 → ⚠ 告警

CLI: ``--top-picks`` footer 经 ``_print_portfolio_risk_block`` 展示
「🎯 组合风险: 72%/100% 预算  ⚠ 集中度高 + 相关性折减」。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.utils.display import Fore, Style


@dataclass
class PortfolioRiskSummary:
    """组合风险预算合成结果 (供前门单行展示)。"""

    has_data: bool = False
    pick_count: int = 0
    #: Top 行业占比 (0-1), 来自 P-4 compute_industry_concentration
    concentration_share: float = 0.0
    concentration_over_threshold: bool = False
    #: 最高 pair 相关度 (None = <2 picks), 来自 Q-4 compute_correlation_discount
    max_pair_correlation: float | None = None
    has_correlation_risk: bool = False
    #: 0-100, 组合占用的风险预算百分比 (集中度 + 相关性合成)
    risk_budget_used: float = 0.0
    #: 触发告警的维度列表 (用于渲染时点名是集中/相关/两者)
    risk_dimensions: list[str] = field(default_factory=list)


def summarize_portfolio_risk(picks: list[dict]) -> PortfolioRiskSummary:
    """合成 P-4 集中度 + Q-4 相关性为组合风险预算摘要。

    Args:
        picks: 推荐 dict 列表 (读 ``industry_sw`` / ``score_b``)

    Returns:
        :class:`PortfolioRiskSummary` (空 picks → ``has_data=False``)
    """
    if not picks:
        return PortfolioRiskSummary()

    from src.screening.correlation_discount import compute_correlation_discount
    from src.screening.portfolio_concentration import compute_industry_concentration

    concentration = compute_industry_concentration(picks)
    correlation = compute_correlation_discount(picks)

    dims: list[str] = []

    # 集中度贡献: top_share 0-1 → 0-60% 预算 (集中度是组合风险的主要驱动)
    # 单只票 (pick_count=1) 时 top_share=1.0 但不算集中 (无"组合"可言)
    if concentration.pick_count >= 2:
        concentration_budget = concentration.top_share * 60.0
        if concentration.over_threshold:
            dims.append("集中度高")
    else:
        concentration_budget = 0.0

    # 相关性贡献: max_pair_correlation 0-1 → 0-40% 预算
    max_corr = correlation.max_pair_correlation
    has_corr_risk = bool(correlation.overlap_warning)
    if max_corr is not None and has_corr_risk:
        correlation_budget = max_corr * 40.0
        dims.append("相关性折减")
    else:
        correlation_budget = 0.0

    risk_budget_used = min(100.0, concentration_budget + correlation_budget)

    return PortfolioRiskSummary(
        has_data=True,
        pick_count=len(picks),
        concentration_share=concentration.top_share,
        concentration_over_threshold=concentration.over_threshold,
        max_pair_correlation=max_corr,
        has_correlation_risk=has_corr_risk,
        risk_budget_used=risk_budget_used,
        risk_dimensions=dims,
    )


def render_portfolio_risk_line(summary: PortfolioRiskSummary) -> str:
    """渲染单行组合风险预算摘要 (无数据 → 空串)。"""
    if not summary.has_data:
        return ""

    used = summary.risk_budget_used
    if used >= 70.0:
        color = Fore.RED
    elif used >= 40.0:
        color = Fore.YELLOW
    else:
        color = Fore.GREEN

    parts = [f"  🎯 组合风险: {color}{used:.0f}%/100% 预算{Style.RESET_ALL}"]
    if summary.risk_dimensions:
        dims = " + ".join(summary.risk_dimensions)
        parts.append(f"  {Fore.YELLOW}⚠ {dims}{Style.RESET_ALL}")
    return " ".join(parts)


__all__ = [
    "PortfolioRiskSummary",
    "summarize_portfolio_risk",
    "render_portfolio_risk_line",
]
