"""NS-3 北极星 P&L 趋势仪表: 按推荐日等权累积真实 T+30 P&L.

北极星目标: 用户按推荐操作 30 天真实 P&L>0. 本模块量化该目标的当前状态,
在 ``--top-picks`` footer 展示, 让 owner/用户看到是否向 >0 收敛.

**三维度诚实度量** (吸取 R-6/R-7 mean 被异常值污染教训):
  - 累积等权 mean T+30 P&L (趋势, 但可能被少数大赢家拉高)
  - 整体 winrate (典型票能否赚钱, count-based 免异常值污染)
  - overall median (典型票真实 T+30, 免异常值污染)

verdict:
  - **divergent** (⚠): mean 正但 winrate<50% 或 median<0 — 表面达标但典型票微亏
    (少数大赢家拉高 mean, 真实数据就是此态: +190% mean 但 46% winrate, -2% median)
  - **positive** (✓): mean + median + winrate 全正 — 真趋近北极星
  - **negative** (⚠): mean 负 — 明显亏
  - **insufficient**: n < min_n (诚实, 静默)

纯诊断不改 gate/factor/仓位. 复用 consecutive_recommendation 数据加载,
镜像 rank_monotonicity / regime_winrate 的 footer-block 模式 (best-effort,
数据不足静默, 永不破坏前门).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.utils.display import Fore, Style

_MIN_N_DEFAULT = 20  # 与 state_type_calibration _Q1_MIN_N 对齐
_RECENT_DAYS = 5  # 最近 N 日 avg (趋势方向)


def _finite_float(value: Any) -> float | None:
    """NaN/Inf/garbage → None (镜像 rank_monotonicity._finite_float)."""
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN
        return None
    return result


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


@dataclass
class NorthStarPnlReport:
    """北极星 P&L 趋势报告 (三维度)."""

    cumulative_mean_pnl: float = 0.0  # 累积等权 mean T+30 (%)
    overall_winrate: float | None = None  # 0-1, T+30 正收益比例
    overall_median: float | None = None  # %, 典型票 T+30 (免异常值)
    sample_dates: int = 0
    sample_count: int = 0
    recent_daily_avg: float | None = None  # 最近 N 日等权 avg (%)
    mean_median_divergence: bool = False  # mean 正但 winrate<50% 或 median<0
    verdict: str = "insufficient"  # insufficient | divergent | positive | negative
    daily_series: list[tuple[str, float]] = field(default_factory=list)  # (date, daily_mean)


def compute_north_star_pnl_from_loaded(
    records: list[dict[str, Any]],
    *,
    min_n: int = _MIN_N_DEFAULT,
    recent_days: int = _RECENT_DAYS,
) -> NorthStarPnlReport:
    """纯函数: 用已加载的 tracking records 算北极星 P&L 报告 (可注入测试)."""
    from collections import defaultdict

    by_date: dict[str, list[float]] = defaultdict(list)
    all_returns: list[float] = []
    for rec in records:
        t30 = _finite_float(rec.get("next_30day_return"))
        if t30 is None:
            continue
        date_raw = str(rec.get("recommended_date", "") or "").replace("-", "")
        if not date_raw:
            date_raw = "unknown"
        by_date[date_raw].append(t30)
        all_returns.append(t30)

    n = len(all_returns)
    if n < min_n:
        return NorthStarPnlReport(sample_count=n, verdict="insufficient")

    # 按日等权 avg → 累积 sum (北极星定义: 按推荐日等权累积)
    daily_series: list[tuple[str, float]] = []
    cumulative = 0.0
    for dt in sorted(by_date):
        daily_avg = sum(by_date[dt]) / len(by_date[dt])
        daily_series.append((dt, daily_avg))
        cumulative += daily_avg

    winrate = sum(1 for x in all_returns if x > 0) / n
    median = _median(all_returns)
    recent = daily_series[-recent_days:] if len(daily_series) >= 1 else []
    recent_avg = sum(d for _, d in recent) / len(recent) if recent else None

    # 背离检测: mean 累积正但 winrate<50% 或 median<0 → mean 被少数赢家拉高
    mean_per_record = sum(all_returns) / n
    divergence = bool(
        cumulative > 0 and (winrate < 0.5 or (median is not None and median < 0))
    )

    if divergence:
        verdict = "divergent"
    elif cumulative > 0 and winrate >= 0.5 and (median is not None and median >= 0):
        verdict = "positive"
    elif cumulative <= 0:
        verdict = "negative"
    else:
        # cumulative>0 但不满足 positive 全条件且未触发 divergence 边界 — 保守 divergent
        verdict = "divergent" if (median is not None and median < 0) else "positive"

    return NorthStarPnlReport(
        cumulative_mean_pnl=cumulative,
        overall_winrate=winrate,
        overall_median=median,
        sample_dates=len(by_date),
        sample_count=n,
        recent_daily_avg=recent_avg,
        mean_median_divergence=divergence,
        verdict=verdict,
        daily_series=daily_series,
    )


def compute_north_star_pnl(
    *, reports_dir: Path | None = None, min_n: int = _MIN_N_DEFAULT
) -> NorthStarPnlReport:
    """从报告目录加载 tracking_history 算北极星 (镜像 rank_monotonicity IO 包装)."""
    from src.screening.consecutive_recommendation import (
        load_tracking_history,
        resolve_report_dir,
    )

    search_dir = reports_dir or resolve_report_dir()
    records = load_tracking_history(search_dir)
    return compute_north_star_pnl_from_loaded(records, min_n=min_n)


# ---------------------------------------------------------------------------
# footer 渲染
# ---------------------------------------------------------------------------


def render_north_star_line(report: NorthStarPnlReport) -> str:
    """渲染单行北极星 P&L 提示 (insufficient → 空串, 永不破坏前门).

    展示形如:
      ``  🎯 北极星 P&L: 累积 +190% (mean) | 胜率 46% | 典型 -2% ⚠ mean 被少数赢家拉高, 典型票微亏 (n=493, 50日)``
      ``  🎯 北极星 P&L: 累积 +12% | 胜率 58% | 典型 +3% ✓ 趋近 >0 (n=120, 30日)``
    """
    if report.verdict == "insufficient" or report.sample_count == 0:
        return ""

    wr = f"{report.overall_winrate:.0%}" if report.overall_winrate is not None else "—"
    med = f"{report.overall_median:+.0f}%" if report.overall_median is not None else "—"
    cum = f"{report.cumulative_mean_pnl:+.0f}%"
    base = (
        f"  🎯 北极星 P&L: 累积 {cum} (mean) | 胜率 {wr} | 典型 {med}"
        f" | n={report.sample_count}, {report.sample_dates}日"
    )

    if report.verdict == "divergent":
        return (
            f"{base} {Fore.RED}⚠ mean 被少数赢家拉高, 典型票微亏 — 北极星未真达标{Style.RESET_ALL}"
        )
    if report.verdict == "positive":
        return f"{base} {Fore.GREEN}✓ 趋近 >0{Style.RESET_ALL}"
    # negative
    return f"{base} {Fore.RED}⚠ 亏 — 远未达北极星{Style.RESET_ALL}"


# ---------------------------------------------------------------------------
# M9: 持有期收益曲线 (holding period) — 全样本, 不受 high bucket n=38 限制
# 各 horizon avg/winrate/median → 最优卖出点 + 推荐票稳健画像.
# 真实 493: winrate 始终 ~46% (持有期无关), avg 随持有期增 (大赢家), median 全负 (典型亏).
# ---------------------------------------------------------------------------


@dataclass
class HoldingPeriodPoint:
    """单个 horizon 的全样本平均收益/胜率/median."""

    horizon: str  # 字段名 e.g. next_5day_return
    avg_return: float | None = None
    winrate: float | None = None
    median_return: float | None = None
    sample_count: int = 0
    verdict: str = "insufficient"  # insufficient | ok


def _horizon_short_label(horizon_field: str) -> str:
    m = re.search(r"(\d+)", horizon_field)
    return f"T+{m.group(1)}" if m else horizon_field


def compute_holding_period_curve_from_loaded(
    records: list[dict[str, Any]],
    horizons: list[str],
    *,
    min_n: int = 20,
) -> list[HoldingPeriodPoint]:
    """全样本各 horizon 的 avg/winrate/median (不受 score bucket n=38 限制)."""
    out: list[HoldingPeriodPoint] = []
    for horizon in horizons:
        returns = [_finite_float(rec.get(horizon)) for rec in records]
        returns = [r for r in returns if r is not None]
        if len(returns) < min_n:
            out.append(HoldingPeriodPoint(horizon=horizon, sample_count=len(returns), verdict="insufficient"))
            continue
        n = len(returns)
        avg = sum(returns) / n
        winrate = sum(1 for x in returns if x > 0) / n
        median = _median(returns)
        out.append(
            HoldingPeriodPoint(
                horizon=horizon, avg_return=avg, winrate=winrate, median_return=median, sample_count=n, verdict="ok"
            )
        )
    return out


def render_holding_period_line(curve: list[HoldingPeriodPoint]) -> str:
    """渲染持有期收益曲线 (全 insufficient → 空串).

    展示形如:
      ``  📊 持有期: T+5 +0.5%/46% | T+30 +3.6%/46% | winrate 稳46% (持有期无关) + median 全负 (典型亏, 靠大赢家)``
    """
    if not curve or all(p.verdict == "insufficient" for p in curve):
        return ""
    ok = [p for p in curve if p.verdict == "ok"]
    if not ok:
        return ""

    def _seg(p: HoldingPeriodPoint) -> str:
        label = _horizon_short_label(p.horizon)
        if p.avg_return is None or p.winrate is None:
            return f"{label} 样本不足"
        return f"{label} {p.avg_return:+.1f}%/{p.winrate:.0%}"

    parts = [_seg(p) for p in curve if p.verdict == "ok"]
    body = " | ".join(parts)

    # 洞察: winrate 稳定? median 全负? avg 随 horizon 增?
    insights: list[str] = []
    winrates = [p.winrate for p in ok if p.winrate is not None]
    if len(winrates) >= 2 and (max(winrates) - min(winrates)) < 0.05:
        insights.append(f"winrate 稳~{sum(winrates) / len(winrates):.0%} (持有期无关)")
    medians = [p.median_return for p in ok if p.median_return is not None]
    if medians and all(m < 0 for m in medians):
        insights.append("median 全负 (典型票亏, 靠少数大赢家拉高 avg)")
    avgs = [p.avg_return for p in ok if p.avg_return is not None]
    if len(avgs) >= 2 and avgs[-1] > avgs[0]:
        insights.append(f"avg 随持有期增 ({avgs[0]:+.1f}%→{avgs[-1]:+.1f}%, 长持暴露大赢家)")

    suffix = f" — {'; '.join(insights)}" if insights else ""
    return f"  📊 持有期: {body}{Fore.YELLOW}{suffix}{Style.RESET_ALL}"


__all__ = [
    "NorthStarPnlReport",
    "HoldingPeriodPoint",
    "compute_north_star_pnl",
    "compute_north_star_pnl_from_loaded",
    "compute_holding_period_curve_from_loaded",
    "render_north_star_line",
    "render_holding_period_line",
]
