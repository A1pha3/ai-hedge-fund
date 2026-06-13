"""P0-3 信号衰减检测器 — 在推荐报告中标注信号衰减预警。

读取过去 N 天 (默认 3 天) 的 ``auto_screening_*.json`` 推荐报告，
对比每个标的的当前 score_b 与历史 score_b，计算衰减程度并标注 DecayLevel。

输出:
  - DecayLevel: 衰减等级枚举 (NONE / MILD / MODERATE / SEVERE)
  - DecayInfo: 单标的衰减详情
  - detect_signal_decay: 主入口
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

from src.utils.numeric import safe_float as _coerce_score_b

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Filename pattern: auto_screening_YYYYMMDD.json
_REPORT_FILENAME_PATTERN = re.compile(r"^auto_screening_(\d{8})\.json$")

# Decay thresholds (percentage drop of score_b)
_MILD_THRESHOLD: float = 10.0       # >= 10% drop
_MODERATE_THRESHOLD: float = 20.0   # >= 20% drop
_SEVERE_THRESHOLD: float = 40.0     # >= 40% drop


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class DecayLevel(str, Enum):
    """信号衰减等级枚举。"""

    NONE = "none"           # 无衰减 (下降 < 10% 或上升)
    MILD = "mild"           # 轻微衰减 (score_b 下降 10-20%)
    MODERATE = "moderate"   # 中度衰减 (score_b 下降 20-40%)
    SEVERE = "severe"       # 严重衰减 (score_b 下降 > 40%)


@dataclass
class DecayInfo:
    """单标的信号衰减详情。"""

    ticker: str
    level: DecayLevel
    current_score: float
    previous_score: float | None   # None = 首次出现
    change_pct: float | None       # None = 首次出现; None = previous_score 为 0
    days_since_peak: int           # 距离最高分的天数; 0 = 今天就是最高分

    def to_dict(self) -> dict[str, Any]:
        """序列化为可 JSON 化的字典。"""
        return {
            "level": self.level.value,
            "current_score": self.current_score,
            "previous_score": self.previous_score,
            "change_pct": self.change_pct,
            "days_since_peak": self.days_since_peak,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_date(date_str: str) -> datetime:
    """将 YYYYMMDD 或 YYYY-MM-DD 解析为 ``datetime``。"""
    cleaned = date_str.replace("-", "").strip()
    if len(cleaned) != 8:
        raise ValueError(f"Invalid date format: {date_str!r} (expected YYYYMMDD)")
    return datetime.strptime(cleaned, "%Y%m%d")


def _classify_decay(change_pct: float | None) -> DecayLevel:
    """根据 change_pct 判定 DecayLevel。

    change_pct 为 None (首次出现或 previous_score 为 0) 时返回 NONE。
    change_pct >= 0 (信号增强或不变) 时返回 NONE。
    """
    if change_pct is None:
        return DecayLevel.NONE
    if change_pct >= 0:
        return DecayLevel.NONE
    # Use small epsilon to handle floating-point imprecision at exact boundaries
    abs_drop = abs(change_pct) + 1e-9
    if abs_drop >= _SEVERE_THRESHOLD:
        return DecayLevel.SEVERE
    if abs_drop >= _MODERATE_THRESHOLD:
        return DecayLevel.MODERATE
    if abs_drop >= _MILD_THRESHOLD:
        return DecayLevel.MILD
    return DecayLevel.NONE


def _compute_change_pct(current: float, previous: float) -> float | None:
    """计算变化百分比。

    ``change_pct = (current - previous) / max(abs(previous), 0.01) * 100``

    Returns None if previous is exactly 0.0 (avoid meaningless division).
    """
    if previous == 0.0:
        return None
    denom = max(abs(previous), 0.01)
    return (current - previous) / denom * 100.0


# ---------------------------------------------------------------------------
# History loading
# ---------------------------------------------------------------------------


def _load_score_history(
    *,
    lookback_days: int,
    report_dir: Path,
    end_date: str,
) -> list[dict[str, Any]]:
    """加载 report_dir 下窗口期内所有 auto_screening_*.json 的 score_b 数据。

    Returns:
        按日期升序排列的列表，每项包含 ``date`` 和 ``score_map`` (ticker -> score_b)。
    """
    if not report_dir.exists():
        return []

    try:
        end_dt = _parse_date(end_date)
    except ValueError as exc:
        logger.warning("[SignalDecay] end_date 解析失败: %s", exc)
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
        # 包含 end_date 当天在内的 lookback_days 天窗口
        # 但我们排除当天（只要历史数据）
        if report_dt >= end_dt:
            continue
        if report_dt < start_dt:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("[SignalDecay] 跳过损坏报告 %s: %s", path.name, exc)
            continue
        score_map: dict[str, float] = {}
        for rec in payload.get("recommendations", []) or []:
            if not isinstance(rec, dict):
                continue
            ticker = rec.get("ticker")
            if ticker:
                score_map[ticker] = _coerce_score_b(rec.get("score_b"))
        collected.append((report_dt, {"date": date_str, "score_map": score_map}))

    collected.sort(key=lambda pair: pair[0])
    return [item for _, item in collected]


# ---------------------------------------------------------------------------
# Main detection function
# ---------------------------------------------------------------------------


def detect_signal_decay(
    current_recommendations: list[dict[str, Any]],
    report_dir: Path,
    lookback_days: int = 3,
    end_date: str | None = None,
) -> dict[str, DecayInfo]:
    """对比当前推荐与历史推荐的 score_b，计算每个标的的衰减程度。

    Args:
        current_recommendations: 当前推荐的列表，每项需包含 ``ticker`` 和 ``score_b``。
        report_dir: 报告目录 (data/reports)。
        lookback_days: 向前回溯天数 (不含当天)；默认 3。
        end_date: 当前日期 (YYYYMMDD)；为 None 时使用最新报告日期。

    Returns:
        ``{ticker: DecayInfo}`` 映射。
    """
    if end_date is None:
        end_date = _infer_end_date(report_dir)
        if end_date is None:
            # No reports at all — all tickers get NONE
            return {
                rec.get("ticker", ""): DecayInfo(
                    ticker=rec.get("ticker", ""),
                    level=DecayLevel.NONE,
                    current_score=_coerce_score_b(rec.get("score_b")),
                    previous_score=None,
                    change_pct=None,
                    days_since_peak=0,
                )
                for rec in current_recommendations
                if isinstance(rec, dict) and rec.get("ticker")
            }

    # Load historical score data (excludes end_date)
    history = _load_score_history(
        lookback_days=lookback_days,
        report_dir=report_dir,
        end_date=end_date,
    )

    # Build per-ticker historical scores list: [(date_str, score), ...]
    ticker_history: dict[str, list[tuple[str, float]]] = {}
    for entry in history:
        date_str = entry["date"]
        score_map = entry["score_map"]
        for ticker, score in score_map.items():
            ticker_history.setdefault(ticker, []).append((date_str, score))

    result: dict[str, DecayInfo] = {}
    for rec in current_recommendations:
        if not isinstance(rec, dict):
            continue
        ticker = rec.get("ticker", "")
        if not ticker:
            continue
        current_score = _coerce_score_b(rec.get("score_b"))

        hist = ticker_history.get(ticker, [])

        if not hist:
            # 首次出现 — 无历史数据
            result[ticker] = DecayInfo(
                ticker=ticker,
                level=DecayLevel.NONE,
                current_score=current_score,
                previous_score=None,
                change_pct=None,
                days_since_peak=0,
            )
            continue

        # previous_score: 最近一天的历史 score_b
        previous_score = hist[-1][1]

        # Calculate change_pct
        if previous_score == 0.0:
            change_pct = None
        else:
            change_pct = _compute_change_pct(current_score, previous_score)

        # Determine decay level
        level = _classify_decay(change_pct)

        # Calculate days_since_peak: 找到历史最高 score_b 的日期
        all_scores = [(date_str, score) for date_str, score in hist]
        all_scores.append((end_date, current_score))

        peak_score = max(s for _, s in all_scores)
        # Find the first date that has the peak score
        peak_date_str = end_date  # default: today
        for date_str, score in all_scores:
            if score == peak_score:
                peak_date_str = date_str
                break

        try:
            peak_dt = _parse_date(peak_date_str)
            end_dt = _parse_date(end_date)
            days_since_peak = max(0, (end_dt - peak_dt).days)
        except ValueError:
            days_since_peak = 0

        result[ticker] = DecayInfo(
            ticker=ticker,
            level=level,
            current_score=current_score,
            previous_score=previous_score,
            change_pct=change_pct,
            days_since_peak=days_since_peak,
        )

    return result


def _infer_end_date(report_dir: Path) -> str | None:
    """从报告目录推断最新日期。"""
    if not report_dir.exists():
        return None
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
    if latest is None:
        return None
    return latest.strftime("%Y%m%d")


# ---------------------------------------------------------------------------
# Decay summary helper
# ---------------------------------------------------------------------------


def build_decay_summary(decay_map: dict[str, DecayInfo]) -> dict[str, int]:
    """从 DecayInfo 映射中构建衰减等级汇总。"""
    summary: dict[str, int] = {level.value: 0 for level in DecayLevel}
    for info in decay_map.values():
        summary[info.level.value] += 1
    return summary
