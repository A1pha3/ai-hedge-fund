"""Signal Momentum Scoring — P10-1.

Track score_b trajectory over the last N days for each recommended stock.
Stocks with **improving** signals are more reliable than those with flat or
declining trajectories.

The momentum is computed as the slope of a simple linear regression of
score_b over the lookback window.  The result is normalized to a
``momentum_label`` and ``momentum_bonus`` that can be integrated into
conviction ranking.

CLI::

    python src/main.py --signal-momentum [--lookback=5] [--top-n=20]

Integration:
    ``--conviction-ranking`` now includes ``signal_momentum`` as a factor
    (configurable via ``--momentum-weight``, default 0.15).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.screening.consecutive_recommendation import (
    load_auto_screening_history,
    resolve_report_dir,
)
from src.utils.display import Fore, Style


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_LOOKBACK: int = 5
_MOMENTUM_THRESHOLD_STRONG: float = 0.02  # score_b improvement per day
_MOMENTUM_THRESHOLD_WEAK: float = 0.005


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

MOMENTUM_LABELS = ("strong_improving", "improving", "stable", "declining", "strong_declining")


@dataclass
class MomentumInfo:
    """Signal momentum for a single ticker."""

    ticker: str
    name: str = ""
    score_current: float = 0.0
    score_history: list[float] = field(default_factory=list)
    slope: float = 0.0
    momentum_label: str = "stable"
    momentum_bonus: float = 0.0
    days_observed: int = 0


@dataclass
class MomentumReport:
    """Signal momentum report for all recommended tickers."""

    trade_date: str = ""
    lookback_days: int = _DEFAULT_LOOKBACK
    items: list[MomentumInfo] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_date": self.trade_date,
            "lookback_days": self.lookback_days,
            "items": [
                {
                    "ticker": item.ticker,
                    "name": item.name,
                    "score_current": round(item.score_current, 4),
                    "slope": round(item.slope, 6),
                    "momentum_label": item.momentum_label,
                    "momentum_bonus": round(item.momentum_bonus, 4),
                    "days_observed": item.days_observed,
                }
                for item in self.items
            ],
        }


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def _simple_slope(values: list[float]) -> float:
    """Compute the slope of a simple linear regression through *values*.

    Uses the formula:  slope = Σ((x - x̄)(y - ȳ)) / Σ((x - x̄)²)

    Returns 0.0 if fewer than 2 data points.
    """
    n = len(values)
    if n < 2:
        return 0.0

    x_mean = (n - 1) / 2.0  # indices 0..n-1
    y_mean = sum(values) / n

    numerator = 0.0
    denominator = 0.0
    for i, y in enumerate(values):
        dx = float(i) - x_mean
        dy = y - y_mean
        numerator += dx * dy
        denominator += dx * dx

    if denominator == 0.0:
        return 0.0

    return numerator / denominator


def _classify_momentum(slope: float) -> tuple[str, float]:
    """Classify slope into a momentum label and bonus.

    Returns (label, bonus) where bonus is in [-0.10, +0.10].
    """
    if slope >= _MOMENTUM_THRESHOLD_STRONG:
        return "strong_improving", 0.10
    if slope >= _MOMENTUM_THRESHOLD_WEAK:
        return "improving", 0.05
    if slope <= -_MOMENTUM_THRESHOLD_STRONG:
        return "strong_declining", -0.10
    if slope <= -_MOMENTUM_THRESHOLD_WEAK:
        return "declining", -0.05
    return "stable", 0.0


def compute_signal_momentum(
    *,
    top_n: int = 20,
    lookback_days: int = _DEFAULT_LOOKBACK,
    reports_dir: Path | None = None,
) -> MomentumReport:
    """Compute signal momentum for the latest recommendations.

    Args:
        top_n: Number of top recommendations to analyze
        lookback_days: How many days of history to use (default 5)
        reports_dir: Reports directory

    Returns:
        :class:`MomentumReport`
    """
    search_dir = reports_dir or resolve_report_dir()
    history = load_auto_screening_history(
        lookback_days=lookback_days,
        report_dir=search_dir,
    )

    if not history:
        return MomentumReport(lookback_days=lookback_days)

    # Latest report
    latest = history[0]
    latest_payload = latest.get("payload", {})
    trade_date = latest.get("date", "")
    latest_recs = (latest_payload.get("recommendations") or [])[:top_n]

    # Build score_b history for each ticker across all reports
    # history is sorted newest-first
    ticker_scores: dict[str, list[float]] = {}
    ticker_names: dict[str, str] = {}

    # Process reports in chronological order (oldest first) for slope calc
    for report in reversed(history):
        recs = (report.get("payload", {}).get("recommendations")) or []
        for rec in recs:
            ticker = str(rec.get("ticker", ""))
            if not ticker:
                continue
            score = float(rec.get("score_b", 0.0) or 0.0)
            ticker_scores.setdefault(ticker, []).append(score)
            name = str(rec.get("name", "") or "")
            if name and ticker not in ticker_names:
                ticker_names[ticker] = name

    # Compute momentum for each recommended ticker
    items: list[MomentumInfo] = []
    for rec in latest_recs:
        ticker = str(rec.get("ticker", ""))
        name = str(rec.get("name", "") or ticker_names.get(ticker, ""))
        current_score = float(rec.get("score_b", 0.0) or 0.0)
        scores = ticker_scores.get(ticker, [])

        if not scores:
            items.append(
                MomentumInfo(
                    ticker=ticker,
                    name=name,
                    score_current=current_score,
                    slope=0.0,
                    momentum_label="stable",
                    momentum_bonus=0.0,
                    days_observed=0,
                )
            )
            continue

        slope = _simple_slope(scores)
        label, bonus = _classify_momentum(slope)

        items.append(
            MomentumInfo(
                ticker=ticker,
                name=name,
                score_current=current_score,
                score_history=scores,
                slope=slope,
                momentum_label=label,
                momentum_bonus=bonus,
                days_observed=len(scores),
            )
        )

    # Sort by momentum bonus descending (improving first)
    items.sort(key=lambda x: x.momentum_bonus, reverse=True)

    return MomentumReport(
        trade_date=trade_date,
        lookback_days=lookback_days,
        items=items,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _momentum_label_colored(label: str) -> str:
    """Color-code a momentum label."""
    if label in ("strong_improving", "improving"):
        return f"{Fore.GREEN}{label}{Style.RESET_ALL}"
    if label in ("strong_declining", "declining"):
        return f"{Fore.RED}{label}{Style.RESET_ALL}"
    return f"{Fore.WHITE}{label}{Style.RESET_ALL}"


def _momentum_arrow(bonus: float) -> str:
    """Return an arrow indicator for momentum bonus."""
    if bonus > 0.05:
        return f"{Fore.GREEN}↑↑{Style.RESET_ALL}"
    if bonus > 0:
        return f"{Fore.GREEN}↑{Style.RESET_ALL}"
    if bonus < -0.05:
        return f"{Fore.RED}↓↓{Style.RESET_ALL}"
    if bonus < 0:
        return f"{Fore.RED}↓{Style.RESET_ALL}"
    return "→"


def render_signal_momentum(report: MomentumReport) -> str:
    """Render signal momentum as a readable table."""
    if not report.items:
        return f"\n{Fore.CYAN}📈 Signal Momentum{Style.RESET_ALL}\n  无推荐数据\n"

    lines = [
        f"\n{Fore.CYAN}📈 Signal Momentum (信号动量){Style.RESET_ALL}",
        f"  基于 {report.lookback_days} 天 score_b 轨迹",
        "",
        f"  {'标的':<8} {'名称':<12} {'Score':>7} {'动量':>4} {'斜率':>9} {'状态':<20} {'观测':>4}",
        f"  {'─' * 8} {'─' * 12} {'─' * 7} {'─' * 4} {'─' * 9} {'─' * 20} {'─' * 4}",
    ]

    for item in report.items:
        arrow = _momentum_arrow(item.momentum_bonus)
        label_str = _momentum_label_colored(item.momentum_label)
        lines.append(
            f"  {item.ticker:<8} {item.name[:12]:<12} {item.score_current:>7.3f} "
            f"{arrow:>6} {item.slope:>+9.5f} {label_str:>30} {item.days_observed:>4}"
        )

    # Summary
    improving = sum(1 for i in report.items if i.momentum_bonus > 0)
    declining = sum(1 for i in report.items if i.momentum_bonus < 0)
    stable = len(report.items) - improving - declining
    lines.append("")
    lines.append(
        f"  {Fore.GREEN}↑ 改善: {improving}{Style.RESET_ALL}  "
        f"{Fore.WHITE}→ 稳定: {stable}{Style.RESET_ALL}  "
        f"{Fore.RED}↓ 下降: {declining}{Style.RESET_ALL}"
    )
    lines.append(f"  {Fore.WHITE}说明: 动量 = score_b 的线性回归斜率。正值 = 推荐信号持续增强。{Style.RESET_ALL}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def run_signal_momentum(argv: list[str] | None = None) -> int:
    """CLI entry point for --signal-momentum."""
    top_n = 20
    lookback = _DEFAULT_LOOKBACK
    if argv:
        for arg in argv:
            if arg.startswith("--top-n="):
                try:
                    top_n = int(arg.split("=")[1])
                except ValueError:
                    pass
            elif arg.startswith("--lookback="):
                try:
                    lookback = int(arg.split("=")[1])
                except ValueError:
                    pass

    reports_dir = resolve_report_dir()
    report = compute_signal_momentum(
        top_n=top_n,
        lookback_days=lookback,
        reports_dir=reports_dir,
    )
    print(render_signal_momentum(report))
    return 0
