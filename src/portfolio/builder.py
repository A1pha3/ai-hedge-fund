"""P3-4: 推荐组合构建器 — 从 Top N 推荐自动构建最优组合权重。

P2-2 (param_compare) + P2-6 (stock_detail) 提供选股/分析能力,
P3-4 在此基础上提供"组合层"建议:
  - 接收 Top N 推荐列表 + 约束 (行业分散 / 单股权重上限 / 风险预算)
  - 输出: 各标的权重 + 组合预期 Sharpe + 与等权组合对比
  - 优化算法: 反 IC 加权 (Sharpe 最大化近似, 无 scipy 依赖)

设计原则:
  - **无外部依赖** — 纯函数, 测试可注入合成数据
  - **简单优化** — 反 IC 加权 (简化版, 避免 scipy/cvxpy)
  - **约束友好** — 行业集中度 + 个股权重双约束
  - **降级友好** — 推荐为空时返回空组合
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from src.utils.numeric import safe_float as _safe_float

logger = logging.getLogger(__name__)

#: 行业集中度上限 (任一行业占总权重)
DEFAULT_INDUSTRY_CAP: float = 0.30

#: 单个标的权重上限
DEFAULT_POSITION_CAP: float = 0.20

#: 最小权重下限 (0 = 允许完全排除某标的)
DEFAULT_POSITION_FLOOR: float = 0.0


@dataclass
class PortfolioPosition:
    """组合中单一持仓。

    Attributes:
        ticker: 6 位 A 股代码
        name: 股票名
        industry: 申万一级行业
        score_b: 该股 score_b
        front_door_action: 前门 BUY/HOLD/AVOID 判决 (仅展示, 不参与权重)
        weight: 组合权重 (0~1, sum of all positions = 1.0)
    """

    ticker: str = ""
    name: str = ""
    industry: str = ""
    score_b: float = 0.0
    front_door_action: str = "AVOID"
    weight: float = 0.0


@dataclass
class PortfolioSummary:
    """组合构建结果。

    Attributes:
        positions: 持仓列表 (含权重)
        total_weight: 实际权重总和 (应 ≈ 1.0)
        industry_breakdown: 行业权重汇总
        n_positions: 持仓数
        concentration_top1: 最大单一持仓权重
        concentration_top3: 前 3 大持仓权重之和
        expected_sharpe: 组合预期 Sharpe (简化估算 = sum(score_b * weight))
        equal_weight_sharpe: 等权组合 Sharpe (对比基准)
    """

    positions: list[PortfolioPosition] = field(default_factory=list)
    total_weight: float = 0.0
    industry_breakdown: dict[str, float] = field(default_factory=dict)
    n_positions: int = 0
    concentration_top1: float = 0.0
    concentration_top3: float = 0.0
    expected_sharpe: float = 0.0
    equal_weight_sharpe: float = 0.0


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def _allocate_weights(
    score_bs: list[float],
    industries: list[str],
    *,
    position_cap: float,
    industry_cap: float,
) -> list[float]:
    """简化版组合权重优化 — 贪心算法 + 单次约束。

    算法:
      1. 按 score_b 降序遍历每个标的
      2. 初始权重 = score_b / total_score
      3. 按顺序分配, 受 position_cap 和 industry_cap 约束
      4. 分配后总和 = min(1.0, 实际分配), 不主动归一化 (让 cap 真实生效)
    """
    if not score_bs:
        return []

    n = len(score_bs)
    # Sort by score_b desc; preserve original indices
    indexed = sorted(enumerate(zip(score_bs, industries)), key=lambda x: x[1][0], reverse=True)

    # Extract scores
    scores_only = [item[1][0] for item in indexed]
    total_score = sum(s for s in scores_only if s > 0)
    if total_score <= 0:
        return [1.0 / n] * n  # Equal weight, no normalization needed

    # Initial target weights
    target_weights = [s / total_score if s > 0 else 0.0 for s in scores_only]

    # Greedy constraint: cap each in order
    industry_weights: dict[str, float] = {}
    final_weights: list[float] = [0.0] * n
    for i, (orig_idx, (score, industry)) in enumerate(indexed):
        w = target_weights[i]
        if w <= 0:
            continue
        # Apply position cap
        if w > position_cap:
            w = position_cap
        # Apply industry cap
        existing = industry_weights.get(industry, 0.0)
        if existing + w > industry_cap:
            w = max(0.0, industry_cap - existing)
        final_weights[i] = w
        industry_weights[industry] = existing + w

    # Map back to original indices
    result = [0.0] * n
    for i, (orig_idx, _) in enumerate(indexed):
        result[orig_idx] = final_weights[i]
    return result


def compute_portfolio(
    recommendations: list[dict[str, Any]],
    *,
    top_n: int = 10,
    position_cap: float = DEFAULT_POSITION_CAP,
    industry_cap: float = DEFAULT_INDUSTRY_CAP,
    market_regime: str = "normal",
) -> PortfolioSummary:
    """主入口: 从 Top N 推荐构建最优组合。

    Args:
        recommendations: 推荐列表 (从 auto_screening report)
        top_n: 选 top N 个股进入组合
        position_cap: 单股权重上限
        industry_cap: 行业集中度上限

    Returns:
        PortfolioSummary
    """
    summary = PortfolioSummary()

    if not recommendations:
        return summary

    # Select top N by score_b
    filtered = [rec for rec in recommendations if isinstance(rec, dict) and rec.get("ticker")]
    if not filtered:
        return summary

    # Sort by score_b desc. BH-011 family (sibling: composite_score.py:312,
    # top_picks._apply_consecutive_bonus_and_resort): score_b clusters in [0,1] so
    # ties at the Top-N membership boundary are common. A single-key sort preserves
    # upstream (auto_screening report array) order on ties, which is not contractually
    # sorted — two identical runs could allocate capital to different tickers, breaking
    # the "稳定找到" goal. Add ticker ascending as the deterministic final key.
    filtered.sort(
        key=lambda r: (
            -_safe_float(r.get("score_b", 0.0), 0.0),
            str(r.get("ticker") or ""),
        ),
    )
    selected = filtered[:top_n]

    if not selected:
        return summary

    # Extract fields
    score_bs = [_safe_float(r.get("score_b", 0.0), 0.0) for r in selected]
    industries = [str(r.get("industry_sw") or r.get("industry") or "未知").strip() for r in selected]

    # Compute weights
    weights = _allocate_weights(score_bs, industries, position_cap=position_cap, industry_cap=industry_cap)

    # Build positions
    for rec, w in zip(selected, weights):
        try:
            from src.screening.investability import build_front_door_verdict

            front_door_action = str(
                build_front_door_verdict(rec, market_regime=market_regime).get("action", "AVOID") or "AVOID"
            )
        except Exception as exc:  # noqa: BLE001 — portfolio display should degrade, not abort
            logger.warning(
                "portfolio-builder: build_front_door_verdict 失败, 前门判决显示为不可用: %s",
                exc,
                exc_info=True,
            )
            front_door_action = "不可用"
        summary.positions.append(
            PortfolioPosition(
                ticker=str(rec.get("ticker", "")),
                name=str(rec.get("name", "")),
                industry=str(rec.get("industry_sw") or rec.get("industry") or "未知").strip(),
                score_b=_safe_float(rec.get("score_b", 0.0), 0.0),
                front_door_action=front_door_action,
                weight=round(w, 4),
            )
        )

    summary.n_positions = len(summary.positions)
    summary.total_weight = sum(p.weight for p in summary.positions)

    # Industry breakdown
    for p in summary.positions:
        summary.industry_breakdown[p.industry] = summary.industry_breakdown.get(p.industry, 0.0) + p.weight

    # Concentration
    sorted_weights = sorted([p.weight for p in summary.positions], reverse=True)
    summary.concentration_top1 = sorted_weights[0] if sorted_weights else 0.0
    summary.concentration_top3 = sum(sorted_weights[:3])

    # Expected Sharpe (simplified = sum(score_b * weight))
    summary.expected_sharpe = sum(p.score_b * p.weight for p in summary.positions)

    # Equal-weight baseline (for comparison)
    n = len(summary.positions)
    if n > 0:
        summary.equal_weight_sharpe = sum(p.score_b for p in summary.positions) / n

    return summary


# ---------------------------------------------------------------------------
# CLI rendering
# ---------------------------------------------------------------------------


def render_portfolio(summary: PortfolioSummary) -> str:
    """ASCII 渲染。"""
    if summary.n_positions == 0:
        return "  无组合数据 — 推荐列表为空"

    lines: list[str] = []
    lines.append("━" * 70)
    lines.append(f"  推荐组合构建器 (P3-4) · {summary.n_positions} 持仓")
    lines.append("━" * 70)
    lines.append("")

    # Positions table
    lines.append(f"  {'ticker':<10} {'行业':<10} {'score_b':>8} {'前门':>8} {'权重':>8}")
    lines.append("  " + "-" * 52)
    for p in summary.positions:
        lines.append(
            f"  {p.ticker:<10} {p.industry:<10} {p.score_b:>+8.4f} "
            f"{p.front_door_action:>8} {p.weight:>8.2%}"
        )
    lines.append("")

    # Industry breakdown
    if summary.industry_breakdown:
        lines.append("  行业分布:")
        sorted_ind = sorted(summary.industry_breakdown.items(), key=lambda x: x[1], reverse=True)
        for ind, w in sorted_ind:
            bar = "█" * int(w * 40)
            lines.append(f"    {ind:<12} {w:>6.2%}  {bar}")
        lines.append("")

    # Metrics
    lines.append("  组合指标:")
    lines.append(f"    持仓数: {summary.n_positions}")
    lines.append(f"    最大单一持仓: {summary.concentration_top1:.2%}")
    lines.append(f"    前 3 大持仓合计: {summary.concentration_top3:.2%}")
    lines.append(f"    预期 Sharpe (估算): {summary.expected_sharpe:+.4f}")
    lines.append(f"    等权 Sharpe (对比): {summary.equal_weight_sharpe:+.4f}")

    improvement = (summary.expected_sharpe - summary.equal_weight_sharpe) if summary.equal_weight_sharpe != 0 else 0.0
    lines.append(f"    相对等权提升: {improvement:+.4f}")
    lines.append("━" * 70)
    return "\n".join(lines)
