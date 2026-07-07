"""P3-3: 行业 + 个股交叉选择 — 找出强势行业中的最优个股。

在已有 P1-2 行业轮动信号基础上, 增加交叉过滤功能:
给定一个行业轮动信号列表和推荐列表, 输出"强势行业 + 行业最优个股"
的组合, 帮用户聚焦"既在风口又在头部"的双重优质标的。

设计原则:
  - **零外部依赖** — 复用 ``calculate_industry_rotation`` + recommendations
  - **可配置 Top N** — 默认输出前 5 个行业
  - **降级友好** — 推荐列表为空时返回空结果
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from src.screening.industry_rotation import calculate_industry_rotation
from src.utils.numeric import safe_float as _safe_float

logger = logging.getLogger(__name__)


@dataclass
class IndustryTopPick:
    """一个行业内的最优个股推荐。

    Attributes:
        ticker: 6 位 A 股代码
        name: 股票名
        score_b: 个股 score_b (-1 ~ +1)
        decision: 决策 (bullish/bearish/neutral)
    """

    ticker: str = ""
    name: str = ""
    score_b: float = 0.0
    decision: str = ""
    front_door_action: str = "AVOID"


@dataclass
class CrossPick:
    """一个行业 + 行业最优个股的组合。

    Attributes:
        industry_name: 行业名
        industry_rank: 行业在轮动中的排名 (1=最强)
        momentum_score: 行业动量得分
        candidate_count: 行业内候选数
        top_picks: 该行业内 score_b 最高的 1-3 个个股
    """

    industry_name: str = ""
    industry_rank: int = 0
    momentum_score: float = 0.0
    candidate_count: int = 0
    top_picks: list[IndustryTopPick] = field(default_factory=list)


def _extract_top_picks_for_industry(
    recommendations: list[dict[str, Any]],
    industry_name: str,
    max_picks: int = 3,
    *,
    market_regime: str = "normal",
) -> list[IndustryTopPick]:
    """从推荐列表中提取指定行业的 Top N 个股。"""
    if not recommendations or not industry_name:
        return []

    picks: list[IndustryTopPick] = []
    for rec in recommendations:
        if not isinstance(rec, dict):
            continue
        # Match industry_sw field (defensive)
        rec_industry = str(rec.get("industry_sw") or rec.get("industry") or "").strip()
        if rec_industry != industry_name:
            continue

        ticker = str(rec.get("ticker", ""))
        if not ticker:
            continue
        try:
            from src.screening.investability import build_front_door_verdict

            front_door_action = str(
                build_front_door_verdict(rec, market_regime=market_regime).get("action", "AVOID") or "AVOID"
            )
        except Exception as exc:  # noqa: BLE001 — diagnostic renderer should keep working
            logger.warning(
                "industry-cross-picks: build_front_door_verdict 失败, 前门判决显示为不可用: %s",
                exc,
                exc_info=True,
            )
            front_door_action = "不可用"

        picks.append(
            IndustryTopPick(
                ticker=ticker,
                name=str(rec.get("name", "")),
                score_b=_safe_float(rec.get("score_b", 0.0), 0.0),
                decision=str(rec.get("decision", "")),
                front_door_action=front_door_action,
            )
        )

    # Sort by score_b desc
    picks.sort(key=lambda p: p.score_b, reverse=True)
    return picks[:max_picks]


def compute_cross_picks(
    recommendations: list[dict[str, Any]],
    *,
    trade_date: str = "",
    top_industries: int = 5,
    picks_per_industry: int = 3,
    market_regime: str = "normal",
) -> list[CrossPick]:
    """主入口: 计算行业 + 个股交叉选择。

    Args:
        recommendations: 当日推荐列表 (从 auto_screening report)
        trade_date: 报告日期 (用于显示)
        top_industries: 输出前 N 个强势行业
        picks_per_industry: 每个行业输出 Top N 个股

    Returns:
        排序好的 CrossPick 列表 (按 momentum_score 降序)
    """
    if not recommendations:
        return []

    # 1. 计算行业轮动信号
    signals = calculate_industry_rotation(recommendations, trade_date)
    if not signals:
        return []

    # 2. 取 top N 强势行业 (momentum_score 降序)
    top_signals = signals[:top_industries]

    # 3. 对每个行业提取 Top N 个股
    cross_picks: list[CrossPick] = []
    for sig in top_signals:
        top_picks = _extract_top_picks_for_industry(
            recommendations,
            industry_name=sig.industry_name,
            max_picks=picks_per_industry,
            market_regime=market_regime,
        )
        cross_picks.append(
            CrossPick(
                industry_name=sig.industry_name,
                industry_rank=sig.rank,
                momentum_score=sig.momentum_score,
                candidate_count=sig.candidate_count,
                top_picks=top_picks,
            )
        )

    return cross_picks


def render_cross_picks(cross_picks: list[CrossPick]) -> str:
    """ASCII 渲染。"""
    if not cross_picks:
        return "  无交叉选择数据 — 行业轮动信号不足"

    lines: list[str] = []
    lines.append("━" * 70)
    lines.append("  行业 + 个股交叉选择 (P3-3)")
    lines.append("━" * 70)
    lines.append("")

    for cp in cross_picks:
        lines.append(f"  #{cp.industry_rank} {cp.industry_name}")
        lines.append(f"     动量: {cp.momentum_score:+.1f}  |  候选: {cp.candidate_count} 只")
        if cp.top_picks:
            lines.append("     Top 标的:")
            for pick in cp.top_picks:
                lines.append(
                    f"       • {pick.ticker} {pick.name}  score_b={pick.score_b:+.3f}  "
                    f"{pick.decision}  前门={pick.front_door_action}"
                )
        else:
            lines.append("     Top 标的: (无)")
        lines.append("")

    return "\n".join(lines)


def compute_cross_picks_verdict_summary(
    cross_picks: list[CrossPick],
) -> tuple[list[str], list[str], list[str], int]:
    """遍历 cross-picks 的所有 Top 个票, 按前门判决分组.

    Returns:
        (buy_tickers, hold_tickers, avoid_tickers, total_count)
    """
    verdict_groups: dict[str, list[str]] = {"BUY": [], "HOLD": [], "AVOID": []}
    for cp in cross_picks:
        for pick in cp.top_picks:
            action = str(pick.front_door_action or "AVOID")
            verdict_groups.setdefault(action, []).append(pick.ticker)

    buy_tickers = verdict_groups.get("BUY", [])
    hold_tickers = verdict_groups.get("HOLD", [])
    avoid_tickers = verdict_groups.get("AVOID", [])
    total_count = sum(len(g) for g in verdict_groups.values())
    return buy_tickers, hold_tickers, avoid_tickers, total_count
