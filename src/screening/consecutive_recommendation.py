"""P0-6 多日推荐聚合 — 连续推荐标记 + 稳定性加权。

读取最近 N 天 (默认 3 天) 的 ``auto_screening_*.json`` 推荐报告，
计算每个 ticker 出现的连续天数及稳定性加权分 (0-10)。

输出:
  - ConsecutiveStats: 单标的连续推荐统计
  - RecommendationStatus: 枚举 (首次出现 / 连续 2 天 / 连续 3+ 天 / 断点)
  - compute_consecutive_recommendations: 主入口
  - enrich_recommendations_with_history: 给推荐结果附加连续推荐字段
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

from src.utils.numeric import safe_float as _coerce_score_b

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_LOOKBACK_DAYS: int = 3

# Stability bonus curve (0-10).
#   streak=1 -> 0.0 (first appearance / no continuity)
#   streak=2 -> 3.0 (moderate confidence)
#   streak>=3 -> 10.0 (high confidence, capped)
_STABILITY_BONUS_BY_STREAK: dict[int, float] = {
    1: 0.0,
    2: 3.0,
    3: 10.0,
}

# Filename pattern: auto_screening_YYYYMMDD.json
_REPORT_FILENAME_PATTERN = re.compile(r"^auto_screening_(\d{8})\.json$")


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class RecommendationStatus(str, Enum):
    """连续推荐状态枚举。"""

    FIRST_APPEARANCE = "first_appearance"
    CONSECUTIVE_2DAYS = "consecutive_2days"
    CONSECUTIVE_3PLUS = "consecutive_3plus"
    BROKEN_STREAK = "broken_streak"
    REENTRY_SIGNAL = "reentry_signal"  # P4-2: 曾被推荐 (score_b >= 0.3), 消失后重返


@dataclass
class ConsecutiveStats:
    """单标的连续推荐统计。"""

    ticker: str
    consecutive_days: int
    status: RecommendationStatus
    recommendation_history: list[dict[str, Any]] = field(default_factory=list)
    stability_bonus: float = 0.0


# ---------------------------------------------------------------------------
# Storage resolution
# ---------------------------------------------------------------------------


def resolve_report_dir(start: Path | None = None) -> Path:
    """定位 ``data/reports`` 目录。

    优先使用传入的 ``start`` 路径；否则从当前工作目录向上查找
    包含 ``data/reports`` 的位置；最后回退到 ``Path("data/reports")``。
    """
    if start is not None:
        candidate = start / "data" / "reports"
        if candidate.exists():
            return candidate
        # 也允许直接传入 reports 目录本身
        if start.name == "reports" and start.exists():
            return start
    cwd = Path.cwd()
    for ancestor in (cwd, *cwd.parents):
        candidate = ancestor / "data" / "reports"
        if candidate.exists():
            return candidate
    return Path("data/reports")


def load_tracking_history(report_dir: Path) -> list[dict[str, Any]]:
    """读取 ``tracking_history.json`` 的 records 列表; 缺失/损坏返回 []。

    集中化实现, 供 confidence_calibration / verify_recommendations /
    daily_brief / winrate_dashboard 共享, 消除 4 处重复代码。
    """
    path = report_dir / "tracking_history.json"
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    records = payload.get("records") if isinstance(payload, dict) else payload
    return list(records) if isinstance(records, list) else []


def _parse_date(date_str: str) -> datetime:
    """将 YYYYMMDD 或 YYYY-MM-DD 解析为 ``datetime``。"""
    cleaned = date_str.replace("-", "").strip()
    if len(cleaned) != 8:
        raise ValueError(f"Invalid date format: {date_str!r} (expected YYYYMMDD)")
    return datetime.strptime(cleaned, "%Y%m%d")


def _format_date(dt: datetime) -> str:
    """``datetime`` -> YYYYMMDD。"""
    return dt.strftime("%Y%m%d")




# ---------------------------------------------------------------------------
# History loading
# ---------------------------------------------------------------------------


def load_auto_screening_history(
    *,
    lookback_days: int,
    report_dir: Path,
    end_date: str | None = None,
) -> list[dict[str, Any]]:
    """加载 ``report_dir`` 下窗口期内的所有 ``auto_screening_*.json``。

    Args:
        lookback_days: 向前回溯天数 (含 ``end_date`` 当天)。
        report_dir: ``data/reports`` 目录。
        end_date: 窗口的结束日期 (YYYYMMDD，**含**)；为 None 时使用最新报告日期。

    Returns:
        按日期降序排列的报告列表，每项包含 ``date`` 和 ``payload``。
    """
    if not report_dir.exists():
        logger.warning("[ConsecutiveRec] report_dir 不存在: %s", report_dir)
        return []

    if end_date is None:
        latest = _latest_report_date(report_dir)
        if latest is None:
            return []
        end_dt = latest
    else:
        try:
            end_dt = _parse_date(end_date)
        except ValueError as exc:
            logger.warning("[ConsecutiveRec] end_date 解析失败: %s", exc)
            return []
    start_dt = end_dt - timedelta(days=lookback_days - 1)

    collected: list[tuple[datetime, dict[str, Any]]] = []
    for path in report_dir.glob("auto_screening_*.json"):
        match = _REPORT_FILENAME_PATTERN.match(path.name)
        if not match:
            continue
        date_str = match.group(1)
        try:
            report_dt = _parse_date(date_str)
        except ValueError:
            continue
        if report_dt < start_dt or report_dt > end_dt:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("[ConsecutiveRec] 跳过损坏报告 %s: %s", path.name, exc)
            continue
        collected.append((report_dt, {"date": date_str, "payload": payload, "path": str(path)}))

    collected.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in collected]


def _latest_report_date(report_dir: Path) -> datetime | None:
    """返回 ``report_dir`` 下最新报告的日期。"""
    latest: datetime | None = None
    for path in report_dir.glob("auto_screening_*.json"):
        match = _REPORT_FILENAME_PATTERN.match(path.name)
        if not match:
            continue
        try:
            dt = _parse_date(match.group(1))
        except ValueError:
            continue
        if latest is None or dt > latest:
            latest = dt
    return latest


# ---------------------------------------------------------------------------
# Streak computation
# ---------------------------------------------------------------------------


def _classify_status(streak: int) -> RecommendationStatus:
    """根据连续天数返回状态。"""
    if streak >= 3:
        return RecommendationStatus.CONSECUTIVE_3PLUS
    if streak == 2:
        return RecommendationStatus.CONSECUTIVE_2DAYS
    if streak == 1:
        return RecommendationStatus.FIRST_APPEARANCE
    return RecommendationStatus.FIRST_APPEARANCE


def compute_consecutive_recommendations(
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    report_dir: Path,
    end_date: str | None = None,
) -> dict[str, ConsecutiveStats]:
    """计算每个 ticker 的连续推荐统计。

    Args:
        lookback_days: 向前回溯天数 (含 ``end_date`` 当天)；默认 3。
        report_dir: 报告目录。
        end_date: 窗口结束日期 (YYYYMMDD，含)；为 None 时使用最新报告日期。

    Returns:
        ``{ticker: ConsecutiveStats}`` 映射。仅包含至少出现一次的 ticker。
    """
    history = load_auto_screening_history(
        lookback_days=lookback_days,
        report_dir=report_dir,
        end_date=end_date,
    )

    # history 已按日期降序
    seen: set[str] = set()
    appearances: dict[str, list[dict[str, Any]]] = {}

    for entry in history:  # 降序
        date_str = entry["date"]
        payload = entry["payload"]
        recommendations = payload.get("recommendations", []) or []
        for rec in recommendations:
            # ALPHA-001: 防御性处理 None/非 dict 推荐条目, 避免 AttributeError 崩溃整个聚合
            if not isinstance(rec, dict):
                continue
            ticker = rec.get("ticker")
            if not ticker:
                continue
            seen.add(ticker)
            appearances.setdefault(ticker, []).append(
                {
                    "date": date_str,
                    # ALPHA-002: score_b 为 None/NaN/非数值时归零, 避免污染下游消费者
                    "score_b": _coerce_score_b(rec.get("score_b")),
                }
            )

    # 反转成升序便于计算连续 streak
    for ticker in appearances:
        appearances[ticker].sort(key=lambda d: d["date"])

    if end_date is None:
        end_dt = _latest_report_date(report_dir)
    else:
        end_dt = _parse_date(end_date)
    if end_dt is None:
        return {}

    stats_map: dict[str, ConsecutiveStats] = {}
    for ticker in sorted(seen):
        days = appearances[ticker]
        if not days:
            continue
        # 计算截至 end_dt 的连续 streak
        # 从最新一天 (end_dt) 向前追踪连续
        latest_date = _parse_date(days[-1]["date"])
        if latest_date != end_dt:
            # 最新推荐日期早于 end_dt -> 已经是历史，streak 仅追溯到最新一天
            gap_days = (end_dt - latest_date).days
            streak = 0
            status = RecommendationStatus.FIRST_APPEARANCE
            _ = gap_days  # silence unused warning
        else:
            # 从 end_dt 向前追踪连续
            streak = 1
            cursor = latest_date
            for entry in reversed(days[:-1]):
                cursor = cursor - timedelta(days=1)
                if _parse_date(entry["date"]) == cursor:
                    streak += 1
                else:
                    break
            status = _classify_status(streak)
            if streak == 1 and len(days) > 1:
                # 窗口内仅今天出现，但前几日有出现 -> 这是断点重启
                status = RecommendationStatus.BROKEN_STREAK

        bonus = _STABILITY_BONUS_BY_STREAK.get(streak, 10.0 if streak >= 3 else 0.0)

        # P4-2: Re-entry detection — 标的曾在窗口内以 score_b >= 0.3 被推荐,
        # 之后消失 (不在中间某天的推荐中), 现在又出现。
        # 这种 "去而复返" 模式在 A 股中是高置信信号 (回调到位后重启)。
        if status == RecommendationStatus.BROKEN_STREAK and len(days) >= 2:
            # 检查历史中是否有高 score_b 推荐且中间有间断
            max_historical_score = max((d.get("score_b", 0.0) or 0.0) for d in days)
            if max_historical_score >= 0.30:
                status = RecommendationStatus.REENTRY_SIGNAL
                bonus = 5.0  # 中等偏高 — 不如连续 3 天 (10.0), 但强于首次出现 (0.0)

        # 只保留在窗口内的历史
        in_window = [d for d in days if _parse_date(d["date"]) >= end_dt - timedelta(days=lookback_days - 1)]
        stats_map[ticker] = ConsecutiveStats(
            ticker=ticker,
            consecutive_days=streak,
            status=status,
            recommendation_history=in_window,
            stability_bonus=bonus,
        )

    return stats_map


# ---------------------------------------------------------------------------
# Recommendation enrichment
# ---------------------------------------------------------------------------


def enrich_recommendations_with_history(
    *,
    recommendations: list[dict[str, Any]],
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    report_dir: Path,
    end_date: str | None = None,
) -> list[dict[str, Any]]:
    """为推荐列表中每条记录附加连续推荐元数据 (in place + 返回)。

    每个 ``recommendation`` dict 上会新增:
      - ``consecutive_days``: 连续推荐天数 (int)
      - ``recommendation_history``: 近 N 天评分趋势 (list[dict])
      - ``stability_bonus``: 稳定性加权分 (0-10)
    """
    stats_map = compute_consecutive_recommendations(
        lookback_days=lookback_days,
        report_dir=report_dir,
        end_date=end_date,
    )

    for rec in recommendations:
        ticker = rec.get("ticker", "")
        stats = stats_map.get(ticker)
        if stats is None:
            rec["consecutive_days"] = 0
            rec["recommendation_history"] = []
            rec["stability_bonus"] = 0.0
            rec["consecutive_status"] = ""
        else:
            rec["consecutive_days"] = stats.consecutive_days
            rec["recommendation_history"] = list(stats.recommendation_history)
            rec["stability_bonus"] = stats.stability_bonus
            rec["consecutive_status"] = stats.status.value

    return recommendations
