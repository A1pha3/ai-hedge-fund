"""P2-4 历史推荐胜率看板 — 近 N 天推荐胜率趋势 + 平均收益率曲线。

数据来源: ``data/reports/tracking_history.json`` (P1-3 ``recommendation_tracker.py`` 产出)。

设计目标:
- **零配置** — 默认读取 P1-3 自动追踪的 ``tracking_history.json``
- **API-ready** — ``compute_winrate_dashboard`` 返回 ``WinRateSummary`` dataclass,
  可直接序列化为 JSON 供 Web 端点消费
- **CLI 友好** — ``render_winrate_dashboard`` 生成 ASCII 趋势图 + 统计摘要
- **优雅降级** — 历史文件损坏 / 缺失 / 数据不完整一律返回空摘要, 不抛异常

典型用法::

    from src.screening.winrate_dashboard import (
        compute_winrate_dashboard,
        render_winrate_dashboard,
    )

    summary = compute_winrate_dashboard(
        tracking_history_path=Path("data/reports/tracking_history.json"),
        lookback_days=30,
    )
    print(render_winrate_dashboard(summary))

CLI::

    uv run python src/main.py --winrate-dashboard [--winrate-lookback=30]

Web::

    GET /api/screening/winrate-dashboard?lookback_days=30
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.utils.numeric import optional_float as _optional_float, safe_float as _safe_float

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class DailyWinRate:
    """单日推荐胜率快照。

    Attributes:
        date: 推荐日期 YYYYMMDD
        total_recommendations: 当日推荐标的总数
        t1_winners: T+1 盈利标的数 (收益率 > 0)
        t1_win_rate: T+1 胜率 (0-1); None 表示无可用数据
        t1_avg_return: T+1 平均收益率 (%, 可正可负); None 表示无可用数据
        t3_win_rate: T+3 胜率; None 表示无可用数据
        t3_avg_return: T+3 平均收益率; None
        t5_win_rate: T+5 胜率; None
        t5_avg_return: T+5 平均收益率; None
    """

    date: str
    total_recommendations: int = 0
    t1_winners: int = 0
    t1_win_rate: float | None = None
    t1_avg_return: float | None = None
    t3_win_rate: float | None = None
    t3_avg_return: float | None = None
    t5_win_rate: float | None = None
    t5_avg_return: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WinRateSummary:
    """近 N 天推荐胜率汇总。

    Attributes:
        period_days: 回溯天数
        total_days: 实际有推荐记录的天数
        total_recommendations: 总推荐标的数
        avg_t1_win_rate: 全周期平均 T+1 胜率; None 表示无数据
        avg_t1_return: 全周期平均 T+1 收益率; None
        avg_t3_win_rate: 全周期平均 T+3 胜率; None
        avg_t3_return: 全周期平均 T+3 收益率; None
        avg_t5_win_rate: 全周期平均 T+5 胜率; None
        avg_t5_return: 全周期平均 T+5 收益率; None
        trend: 趋势方向 ``"improving"`` / ``"declining"`` / ``"stable"``
        daily: 日度数据列表 (按日期升序)
    """

    period_days: int = 30
    total_days: int = 0
    total_recommendations: int = 0
    avg_t1_win_rate: float | None = None
    avg_t1_return: float | None = None
    avg_t3_win_rate: float | None = None
    avg_t3_return: float | None = None
    avg_t5_win_rate: float | None = None
    avg_t5_return: float | None = None
    trend: str = "stable"
    daily: list[DailyWinRate] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------






def _parse_date(date_str: str) -> datetime | None:
    """YYYYMMDD / YYYY-MM-DD -> datetime; 失败返回 None。"""
    if not date_str:
        return None
    cleaned = str(date_str).replace("-", "").strip()
    if len(cleaned) != 8 or not cleaned.isdigit():
        return None
    try:
        return datetime.strptime(cleaned, "%Y%m%d")
    except ValueError:
        return None


def _format_date_short(date_str: str) -> str:
    """YYYYMMDD -> MM-DD (用于趋势图展示)。"""
    cleaned = date_str.replace("-", "").strip()
    if len(cleaned) == 8:
        return f"{cleaned[4:6]}-{cleaned[6:]}"
    return date_str


def _load_tracking_history(path: Path) -> list[dict[str, Any]]:
    """读取 tracking_history.json; 缺失/损坏返回空列表。"""
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[WinRateDashboard] history 解析失败 %s: %s", path, exc)
        return []
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        return []
    return records


def _compute_horizon_stats(records: list[dict[str, Any]], return_field: str) -> tuple[float | None, float | None, int]:
    """计算指定 horizon 的胜率和平均收益。

    Args:
        records: 同一 recommended_date 的记录列表
        return_field: ``"next_day_return"`` / ``"next_3day_return"`` / ``"next_5day_return"``

    Returns:
        (win_rate, avg_return, tracked_count)
    """
    returns: list[float] = []
    for rec in records:
        raw = rec.get(return_field)
        fv = _optional_float(raw)
        if fv is not None:
            returns.append(fv)

    if not returns:
        return None, None, 0

    winners = sum(1 for r in returns if r > 0)
    win_rate = winners / len(returns)
    avg_return = sum(returns) / len(returns)
    return win_rate, avg_return, len(returns)


def _determine_trend(daily_rates: list[DailyWinRate], window: int = 7) -> str:
    """判定趋势方向: 最近 window 天 vs 前 window 天。

    Returns:
        ``"improving"`` / ``"declining"`` / ``"stable"``
    """
    t1_rates = [d.t1_win_rate for d in daily_rates if d.t1_win_rate is not None]
    if len(t1_rates) < 2:
        return "stable"

    recent = t1_rates[-window:] if len(t1_rates) >= window else t1_rates[len(t1_rates) // 2:]
    earlier = t1_rates[:window] if len(t1_rates) >= window else t1_rates[: len(t1_rates) // 2]

    if not recent or not earlier:
        return "stable"

    recent_avg = sum(recent) / len(recent)
    earlier_avg = sum(earlier) / len(earlier)
    diff = recent_avg - earlier_avg

    if diff > 0.05:
        return "improving"
    if diff < -0.05:
        return "declining"
    return "stable"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_winrate_dashboard(
    tracking_history_path: Path,
    lookback_days: int = 30,
) -> WinRateSummary:
    """从 P1-3 tracking_history.json 中读取历史推荐和实际收益, 按日聚合胜率和平均收益。

    Args:
        tracking_history_path: ``data/reports/tracking_history.json`` 路径
        lookback_days: 回溯天数 (默认 30)

    Returns:
        :class:`WinRateSummary` 含汇总统计和日度趋势数据。
    """
    history = _load_tracking_history(tracking_history_path)
    if not history:
        return WinRateSummary(period_days=lookback_days)

    # 按日期切分
    today = datetime.now()
    cutoff = today - timedelta(days=lookback_days)

    by_date: dict[str, list[dict[str, Any]]] = {}
    for rec in history:
        rec_date_str = str(rec.get("recommended_date", "") or "")
        rec_dt = _parse_date(rec_date_str)
        if rec_dt is None:
            continue
        if rec_dt < cutoff:
            continue
        date_key = rec_date_str.replace("-", "")
        by_date.setdefault(date_key, []).append(rec)

    if not by_date:
        return WinRateSummary(period_days=lookback_days)

    # 按日聚合
    daily_list: list[DailyWinRate] = []
    for date_key in sorted(by_date.keys()):
        day_records = by_date[date_key]
        t1_wr, t1_ar, t1_tracked = _compute_horizon_stats(day_records, "next_day_return")
        t3_wr, t3_ar, _ = _compute_horizon_stats(day_records, "next_3day_return")
        t5_wr, t5_ar, _ = _compute_horizon_stats(day_records, "next_5day_return")

        daily_list.append(
            DailyWinRate(
                date=date_key,
                total_recommendations=len(day_records),
                t1_winners=sum(1 for r in day_records if _optional_float(r.get("next_day_return")) is not None and _optional_float(r.get("next_day_return")) > 0),
                t1_win_rate=t1_wr,
                t1_avg_return=t1_ar,
                t3_win_rate=t3_wr,
                t3_avg_return=t3_ar,
                t5_win_rate=t5_wr,
                t5_avg_return=t5_ar,
            )
        )

    # 全周期汇总
    all_t1_rates = [d.t1_win_rate for d in daily_list if d.t1_win_rate is not None]
    all_t1_returns = [d.t1_avg_return for d in daily_list if d.t1_avg_return is not None]
    all_t3_rates = [d.t3_win_rate for d in daily_list if d.t3_win_rate is not None]
    all_t3_returns = [d.t3_avg_return for d in daily_list if d.t3_avg_return is not None]
    all_t5_rates = [d.t5_win_rate for d in daily_list if d.t5_win_rate is not None]
    all_t5_returns = [d.t5_avg_return for d in daily_list if d.t5_avg_return is not None]

    total_recs = sum(d.total_recommendations for d in daily_list)
    trend = _determine_trend(daily_list)

    return WinRateSummary(
        period_days=lookback_days,
        total_days=len(daily_list),
        total_recommendations=total_recs,
        avg_t1_win_rate=(sum(all_t1_rates) / len(all_t1_rates)) if all_t1_rates else None,
        avg_t1_return=(sum(all_t1_returns) / len(all_t1_returns)) if all_t1_returns else None,
        avg_t3_win_rate=(sum(all_t3_rates) / len(all_t3_rates)) if all_t3_rates else None,
        avg_t3_return=(sum(all_t3_returns) / len(all_t3_returns)) if all_t3_returns else None,
        avg_t5_win_rate=(sum(all_t5_rates) / len(all_t5_rates)) if all_t5_rates else None,
        avg_t5_return=(sum(all_t5_returns) / len(all_t5_returns)) if all_t5_returns else None,
        trend=trend,
        daily=daily_list,
    )


def render_winrate_dashboard(summary: WinRateSummary) -> str:
    """ASCII 趋势图 + 统计摘要。

    Args:
        summary: :func:`compute_winrate_dashboard` 的返回值

    Returns:
        多行字符串, 含趋势图和统计摘要。
    """
    if summary.total_days == 0:
        return f"暂无推荐历史数据 (近 {summary.period_days} 天无追踪记录)\n"

    lines: list[str] = []
    border = "━" * 56
    lines.append(f"{'━' * 3} 历史推荐胜率看板 · 近 {summary.period_days} 天 {'━' * 3}")
    lines.append("")
    lines.append(f"总推荐: {summary.total_recommendations} 只 ({summary.total_days} 天)")

    def _fmt_pct(value: float | None) -> str:
        if value is None:
            return "—"
        return f"{value * 100:.1f}%"

    def _fmt_ret(value: float | None) -> str:
        if value is None:
            return "—"
        sign = "+" if value >= 0 else ""
        return f"{sign}{value:.2f}%"

    lines.append(f"T+1 平均胜率: {_fmt_pct(summary.avg_t1_win_rate)} | T+3: {_fmt_pct(summary.avg_t3_win_rate)} | T+5: {_fmt_pct(summary.avg_t5_win_rate)}")
    lines.append(f"T+1 平均收益: {_fmt_ret(summary.avg_t1_return)} | T+3: {_fmt_ret(summary.avg_t3_return)} | T+5: {_fmt_ret(summary.avg_t5_return)}")

    trend_label = {
        "improving": "📈 improving",
        "declining": "📉 declining",
        "stable": "➡️  stable",
    }.get(summary.trend, summary.trend)
    lines.append(f"趋势: {trend_label}")
    lines.append("")

    # 日度趋势图 (T+1 胜率)
    if summary.daily:
        lines.append(f"日度趋势 (T+1 胜率):")
        bar_width = 20
        for day in summary.daily:
            date_label = _format_date_short(day.date)
            wr = day.t1_win_rate
            if wr is not None:
                pct = wr * 100
                filled = max(0, min(bar_width, int(round(pct / 100 * bar_width))))
                bar = "█" * filled + "░" * (bar_width - filled)
                lines.append(f"  {date_label} {bar} {pct:.0f}%")
            else:
                bar = "░" * bar_width
                lines.append(f"  {date_label} {bar} —")

    return "\n".join(lines) + "\n"
