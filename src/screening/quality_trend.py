"""Q-3 推荐质量趋势 — 滚动窗口 T+30 胜率趋势 (模型在变好还是变坏?).

P-1 量"推荐"稳定性 (日间重叠), 无"表现"稳定性。本模块把 tracking_history 按
recommended_date 分到 N 个滚动时间窗 (默认 4 周), 计算每窗成熟 T+30 胜率,
导出趋势方向 (↑改善 / ↓恶化 / →平稳 / —数据不足)。

输出让用户校准对系统整体的信任: 胜率逐周上升 = 模型当前有效; 下降 = 市场可能
drift, 谨慎。服务"稳定"模型层 (系统级自信, P-1 推荐-稳定维度的互补)。

设计原则:
  - **复用 tracking_history** — 零新数据源
  - **仅成熟 T+30** — 未满 30 天的窗口 win_rate=None (诚实)
  - **趋势阈值 ±5pp** — 小于阈值视为平稳 (避免噪声误判)

CLI: ``--confidence-calibration`` footer 展示
「📈 推荐质量趋势: W-3 52% → W-2 58% → W-1 61% → 当前 — (↑改善)」。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.utils.display import Fore, Style

#: 趋势方向阈值 (百分点): |last - first| >= 此值才算改善/恶化, 否则平稳
_TREND_THRESHOLD: float = 0.05  # 5pp


@dataclass
class QualityWindow:
    """单个时间窗的 T+30 胜率。"""

    label: str  # "W-3" / "W-2" / "W-1" / "当前"
    t30_win_rate: float | None = None  # None = 无成熟 T+30
    sample_count: int = 0  # 该窗全部记录数
    mature_count: int = 0  # 其中已有 T+30 收益的成熟记录


@dataclass
class QualityTrendReport:
    """滚动窗口 T+30 胜率趋势。"""

    windows: list[QualityWindow] = field(default_factory=list)
    trend_direction: str = "—数据不足"


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN
        return None
    return result


def _win_rate(returns: list[float]) -> float | None:
    if not returns:
        return None
    return sum(1 for x in returns if x > 0) / len(returns)


def compute_quality_trend(
    *,
    reports_dir: Path | None = None,
    n_windows: int = 4,
    window_days: int = 7,
) -> QualityTrendReport:
    """计算 N 个滚动时间窗的 T+30 胜率趋势。

    Args:
        reports_dir: 报告目录 (None 时用 ``resolve_report_dir()``)
        n_windows: 窗口数 (默认 4 = 近 4 周)
        window_days: 每窗天数 (默认 7)

    Returns:
        :class:`QualityTrendReport` (无数据 → 所有窗 None, 趋势 数据不足)
    """
    from src.screening.consecutive_recommendation import (
        load_tracking_history,
        resolve_report_dir,
    )

    search_dir = reports_dir or resolve_report_dir()
    records = load_tracking_history(search_dir)

    # Anchor on the latest recommended_date; windows go backwards
    parsed: list[tuple[str, float | None]] = []
    latest_date_str = ""
    for rec in records:
        d = str(rec.get("recommended_date", "") or "").replace("-", "")
        if len(d) != 8 or not d.isdigit():
            continue
        if d > latest_date_str:
            latest_date_str = d
        parsed.append((d, _optional_float(rec.get("next_30day_return"))))

    report = QualityTrendReport()
    if not latest_date_str:
        report.windows = [
            QualityWindow(label=_window_label(i, n_windows)) for i in range(n_windows)
        ]
        return report

    from datetime import datetime, timedelta

    latest_dt = datetime.strptime(latest_date_str, "%Y%m%d")
    windows: list[QualityWindow] = []
    # oldest window first: [latest - n_windows*window_days, latest - (n_windows-1)*window_days), ...
    for i in range(n_windows):
        end_offset = (n_windows - 1 - i) * window_days  # oldest: (n-1)*wd; newest: 0
        win_end = latest_dt - timedelta(days=end_offset)
        win_start = win_end - timedelta(days=window_days)
        # inclusive of win_start, exclusive of win_end (except newest which includes end)
        in_window: list[float | None] = []
        sample = 0
        mature = 0
        for d, t30 in parsed:
            try:
                dt = datetime.strptime(d, "%Y%m%d")
            except ValueError:
                continue
            if i == n_windows - 1:
                # newest window: [win_start, win_end] inclusive both
                if not (win_start <= dt <= win_end):
                    continue
            else:
                if not (win_start <= dt < win_end):
                    continue
            sample += 1
            if t30 is not None:
                mature += 1
                in_window.append(t30)
        t30_returns = [x for x in in_window if x is not None]
        windows.append(
            QualityWindow(
                label=_window_label(i, n_windows),
                t30_win_rate=_win_rate(t30_returns),
                sample_count=sample,
                mature_count=mature,
            )
        )

    report.windows = windows
    report.trend_direction = _derive_trend(windows)
    return report


def _window_label(i: int, n_windows: int) -> str:
    """Oldest = W-(n-1), ..., newest = 当前."""
    offset = n_windows - 1 - i
    if offset == 0:
        return "当前"
    return f"W-{offset}"


def _derive_trend(windows: list[QualityWindow]) -> str:
    rates = [w.t30_win_rate for w in windows if w.t30_win_rate is not None]
    if len(rates) < 2:
        return "—数据不足"
    first, last = rates[0], rates[-1]
    delta = last - first
    if delta >= _TREND_THRESHOLD:
        return "↑改善"
    if delta <= -_TREND_THRESHOLD:
        return "↓恶化"
    return "→平稳"


def render_quality_trend_line(report: QualityTrendReport) -> str:
    """渲染一行质量趋势 (无数据 → 数据不足提示)。"""
    parts: list[str] = []
    for w in report.windows:
        if w.t30_win_rate is not None:
            parts.append(f"{w.label} {w.t30_win_rate * 0:.0f}{w.t30_win_rate * 100:.0f}%")
        else:
            parts.append(f"{w.label} —")
    trend = report.trend_direction
    if "改善" in trend or "↑" in trend:
        color = Fore.GREEN
    elif "恶化" in trend or "↓" in trend:
        color = Fore.RED
    else:
        color = Fore.YELLOW
    return (
        f"  {Fore.CYAN}📈 推荐质量趋势 (T+30):{Style.RESET_ALL} "
        f"{' → '.join(parts)}  {color}{trend}{Style.RESET_ALL}"
    )


__all__ = [
    "QualityWindow",
    "QualityTrendReport",
    "compute_quality_trend",
    "render_quality_trend_line",
]
