"""P-4 组合级行业集中度 — Top 行业占比 + 超阈值风险提示.

R145 给 per-pick 仓位, 但组合层级"你 40% 在科技, 集中度超限"视角此前缺失。
本模块从推荐/持仓列表聚合 industry_sw, 计算 Top 行业占比, 超过阈值 (默认 30%)
时在 ``--top-picks`` / ``--position-check`` footer 展示 ⚠ 风险提示, 服务"仓位"
维度的组合层级风控。

设计原则:
  - **count-based** — 每只推荐 = 1 单位 (position-weighted 需持仓数据, 留待 P-3 闭环)
  - **过滤未知行业** — industry_sw 为空/"未知" 不计入分母 (不污染集中度)
  - **纯展示** — 不改 BUY 门控, 只让用户校准组合分散度

CLI: ``--top-picks`` / ``--position-check`` footer 调用
``render_concentration_line(compute_industry_concentration(picks))``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.utils.display import Fore, Style

#: Top 行业占比 ≥ 此阈值 → ⚠ 集中超限提示 (count-based, 3 只同行业 / 10 只组合)
_DEFAULT_THRESHOLD: float = 0.30

#: 视为"无行业"的字符串 (从 recommendations 的 industry_sw 来, 不计入集中度分母)
_UNKNOWN_INDUSTRIES: frozenset[str] = frozenset({"", "未知", "unknown", "none", "—"})


@dataclass
class IndustryConcentrationReport:
    """组合行业集中度度量结果。"""

    top_industry: str = ""
    top_share: float = 0.0  # 0-1, Top 行业占有效 pick 的比例
    pick_count: int = 0  # 有效 (有合法 industry_sw) 的 pick 数
    over_threshold: bool = False
    threshold: float = 0.0
    #: 行业 → 占比 (仅有效行业), 按 share 降序; 供调试/扩展展示
    distribution: dict[str, float] = field(default_factory=dict)


def _is_known_industry(raw: Any) -> bool:
    """industry_sw 非空且不在未知集合中才算合法行业。"""
    name = str(raw or "").strip()
    return bool(name) and name.lower() not in _UNKNOWN_INDUSTRIES


def compute_industry_concentration(
    picks: list[dict[str, Any]],
    threshold: float = _DEFAULT_THRESHOLD,
) -> IndustryConcentrationReport:
    """计算组合的行业集中度 (count-based Top 行业占比)。

    Args:
        picks: 推荐/持仓 dict 列表 (读 ``industry_sw`` 字段)
        threshold: Top 行业占比 ≥ 此值 → over_threshold=True

    Returns:
        :class:`IndustryConcentrationReport` (空 picks → pick_count=0, over=False)
    """
    if not picks:
        return IndustryConcentrationReport(threshold=threshold)

    counts: dict[str, int] = {}
    for pick in picks:
        if not isinstance(pick, dict):
            continue
        industry = str(pick.get("industry_sw", "") or "").strip()
        if not _is_known_industry(industry):
            continue
        counts[industry] = counts.get(industry, 0) + 1

    valid_count = sum(counts.values())
    if valid_count == 0:
        return IndustryConcentrationReport(threshold=threshold)

    distribution = {ind: c / valid_count for ind, c in counts.items()}
    # Top industry: highest share; tie → sort by share desc then name for determinism
    top_industry, top_share = max(
        distribution.items(), key=lambda kv: (kv[1], kv[0])
    ) if distribution else ("", 0.0)
    # max() on (share, name) picks the lexicographically-largest name on ties —
    # stable across runs for the same input

    return IndustryConcentrationReport(
        top_industry=top_industry,
        top_share=round(top_share, 4),
        pick_count=valid_count,
        over_threshold=top_share >= threshold,
        threshold=threshold,
        distribution=distribution,
    )


def render_concentration_line(report: IndustryConcentrationReport) -> str:
    """渲染一行组合行业集中度摘要 (无有效 pick → 空串)。"""
    if report.pick_count == 0:
        return ""
    pct = report.top_share * 100
    if report.over_threshold:
        return (
            f"  {Fore.CYAN}🏭 组合行业集中度:{Style.RESET_ALL} "
            f"{report.top_industry} {Fore.RED}{pct:.0f}%{Style.RESET_ALL} "
            f"{Fore.RED}⚠ > {report.threshold * 100:.0f}% 集中超限, "
            f"建议分散{Style.RESET_ALL}"
        )
    return (
        f"  {Fore.CYAN}🏭 组合行业集中度:{Style.RESET_ALL} "
        f"{report.top_industry} {pct:.0f}%  (分散度 OK, 阈值 {report.threshold * 100:.0f}%)"
    )


__all__ = [
    "IndustryConcentrationReport",
    "compute_industry_concentration",
    "render_concentration_line",
]
