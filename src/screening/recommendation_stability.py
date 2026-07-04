"""P-1 推荐稳定性度量 — Top-N 日间重叠率.

产品目标原话"**稳定**找到未来 30 天最有投资价值"——核心形容词"稳定"此前无任何
度量。一只昨 BUY 今 AVOID 明又 BUY 的票在系统里完全合法，却直接违背"稳定"。
本模块读最近 N 份 ``auto_screening_*.json`` 报告，计算相邻交易日 Top-N ticker
集的 Jaccard 重叠率均值，输出一个 0-1 的稳定性分数 + 中文标签（稳定/波动/剧烈
轮换/数据不足），供 ``--top-picks`` footer 展示。

设计原则:
  - **零新数据源** — 复用 ``consecutive_recommendation.load_auto_screening_history``
  - **纯展示** — 不进排序、不改 BUY 门控，只让用户校准对推荐稳定性的信任
  - **Jaccard 对称** — |A∩B|/|A∪B|，对 Top-N 集大小不敏感

CLI: ``--top-picks`` footer 调用 ``render_stability_line(compute_recommendation_stability(...))``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src.utils.display import Fore, Style

#: 重叠率 ≥ 此阈值 → "稳定"（≈每日 Top-3 基本不动）
_STABLE_THRESHOLD: float = 0.67
#: 重叠率 ≥ 此阈值 → "波动"（< 此为 "剧烈轮换"）
_VOLATILE_THRESHOLD: float = 0.34


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class RecommendationStabilityReport:
    """推荐稳定性度量结果。"""

    lookback_days: int
    top_n: int
    day_count: int = 0
    #: 0-1 相邻日 Jaccard 均值；不足 2 日时为 None（无法计算）
    stability_score: float | None = None
    #: 每对相邻日的 Jaccard 值（day_count-1 个）
    adjacent_overlaps: list[float] = field(default_factory=list)
    label: str = "数据不足"
    #: loop 82 (asymmetric-staleness drain): YYYYMMDD, 最新一份报告的日期
    #: (None → render 不 stamp, 不 fabricate)
    latest_report_date: str | None = None

    @property
    def available(self) -> bool:
        """是否算出了有效稳定性分数（≥2 份报告）。"""
        return self.stability_score is not None


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def _top_n_tickers(payload: dict[str, Any], top_n: int) -> set[str]:
    """从报告 payload 提取 Top-N ticker 集（报告已按 score_b 降序）。"""
    recs = payload.get("recommendations") or []
    return {str(rec.get("ticker", "")) for rec in recs[:top_n] if isinstance(rec, dict) and rec.get("ticker")}


def _jaccard(a: set[str], b: set[str]) -> float:
    """两集合的 Jaccard 相似度 |A∩B|/|A∪B|；两空集视为 1.0（完全一致）。"""
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def compute_recommendation_stability(
    *,
    reports_dir: Path | None = None,
    lookback_days: int = 5,
    top_n: int = 3,
) -> RecommendationStabilityReport:
    """计算最近 N 日的推荐稳定性（相邻日 Top-N Jaccard 均值）。

    Args:
        reports_dir: 报告目录（None 时用 ``resolve_report_dir()``）
        lookback_days: 回溯天数（含最新日）
        top_n: 每日取 Top-N ticker

    Returns:
        :class:`RecommendationStabilityReport`（不足 2 份报告时 stability_score=None）
    """
    from src.screening.consecutive_recommendation import (
        load_auto_screening_history,
        resolve_report_dir,
    )

    search_dir = reports_dir or resolve_report_dir()
    history = load_auto_screening_history(
        lookback_days=lookback_days,
        report_dir=search_dir,
    )

    report = RecommendationStabilityReport(
        lookback_days=lookback_days,
        top_n=top_n,
        day_count=len(history),
    )

    # loop 82: capture newest report date for the render stamp. history is
    # sorted desc by date (load_auto_screening_history), so history[0] is newest.
    if history:
        report.latest_report_date = str(history[0].get("date", "") or "").replace("-", "") or None

    if len(history) < 2:
        return report  # stability_score=None, label="数据不足"

    # history 按日期降序（newest first）；Jaccard 对称，顺序不影响均值
    daily_tops = [_top_n_tickers(item.get("payload", {}), top_n) for item in history]

    overlaps = [_jaccard(daily_tops[i], daily_tops[i + 1]) for i in range(len(daily_tops) - 1)]
    report.adjacent_overlaps = overlaps
    score = sum(overlaps) / len(overlaps) if overlaps else 0.0
    report.stability_score = round(score, 4)

    if score >= _STABLE_THRESHOLD:
        report.label = "稳定"
    elif score >= _VOLATILE_THRESHOLD:
        report.label = "波动"
    else:
        report.label = "剧烈轮换"

    return report


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_stability_line(report: RecommendationStabilityReport) -> str:
    """渲染一行稳定性摘要（数据不足时返回空串，不渲染）。

    loop 82 (asymmetric-staleness drain): 末尾追加 ``| 数据时点 YYYY-MM-DD``
    mirroring the 9 sibling footer blocks. 稳定性读自多日 auto_screening_*.json
    history (stale-prone); 无 stamp 时 operator 看不出 "稳定" 裁决是基于新鲜还是
    过期数据 — 而 "稳定" 绿标直接校准对系统可靠性的信任。
    """
    if not report.available:
        return ""
    pct = (report.stability_score or 0.0) * 100
    if report.stability_score is not None and report.stability_score >= _STABLE_THRESHOLD:
        color = Fore.GREEN
    elif report.stability_score is not None and report.stability_score >= _VOLATILE_THRESHOLD:
        color = Fore.YELLOW
    else:
        color = Fore.RED
    body = f"  {Fore.CYAN}📊 推荐稳定性:{Style.RESET_ALL} " f"近 {report.day_count} 日 Top {report.top_n} 重叠率 " f"{color}{pct:.0f}% ({report.label}){Style.RESET_ALL}  " f"(相邻日 Jaccard 均值)"
    return body + _format_as_of_stamp(report.latest_report_date)


def _format_as_of_stamp(latest_report_date: str | None) -> str:
    """Render `` | 数据时点 YYYY-MM-DD`` from a YYYYMMDD string (None → "")."""
    if not latest_report_date:
        return ""
    try:
        iso = datetime.strptime(str(latest_report_date), "%Y%m%d").date().isoformat()
        return f" {Fore.WHITE}| 数据时点 {iso}{Style.RESET_ALL}"
    except ValueError:
        return ""


__all__ = [
    "RecommendationStabilityReport",
    "compute_recommendation_stability",
    "render_stability_line",
]
