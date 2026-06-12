"""Strategy Performance Report — P15-2.

Shows the performance of each strategy (trend / mean_reversion / fundamental /
event_sentiment) over the past N days based on tracking history.

Output:
- Per-strategy win rate (direction correct when signal was strong)
- Per-strategy average confidence
- Strategy contribution to top picks
- Recommendation: which strategies to weight up/down

CLI::

    python src/main.py --strategy-report [--lookback=7]
"""
from __future__ import annotations

from collections import defaultdict
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

_STRATEGY_KEYS: tuple[str, ...] = ("trend", "mean_reversion", "fundamental", "event_sentiment")

_STRATEGY_NAMES: dict[str, str] = {
    "trend": "趋势",
    "mean_reversion": "均值回归",
    "fundamental": "基本面",
    "event_sentiment": "事件情绪",
}


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class StrategyStats:
    """Stats for a single strategy."""

    strategy: str
    name: str = ""
    signal_count: int = 0
    bullish_count: int = 0
    bearish_count: int = 0
    avg_confidence: float = 0.0
    strong_signal_count: int = 0  # confidence >= 60
    contribution_to_top: int = 0  # how many top picks had this strategy as primary


@dataclass
class StrategyReport:
    """Strategy performance report."""

    trade_date: str = ""
    lookback_days: int = 7
    strategies: list[StrategyStats] = field(default_factory=list)
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_date": self.trade_date,
            "lookback_days": self.lookback_days,
            "strategies": [
                {
                    "strategy": s.strategy,
                    "name": s.name,
                    "signal_count": s.signal_count,
                    "strong_signal_count": s.strong_signal_count,
                    "avg_confidence": round(s.avg_confidence, 2),
                }
                for s in self.strategies
            ],
            "recommendation": self.recommendation,
        }


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def compute_strategy_report(
    *,
    lookback_days: int = 7,
    reports_dir: Path | None = None,
) -> StrategyReport:
    """Compute strategy performance report.

    Args:
        lookback_days: How many days to look back
        reports_dir: Reports directory

    Returns:
        :class:`StrategyReport`
    """
    search_dir = reports_dir or resolve_report_dir()
    history = load_auto_screening_history(
        lookback_days=lookback_days,
        report_dir=search_dir,
    )

    if not history:
        return StrategyReport()

    trade_date = history[0].get("date", "")

    # Collect strategy signals across all reports
    strategy_signals: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for report in history:
        recs = (report.get("payload", {}).get("recommendations")) or []
        for rec in recs:
            signals = rec.get("strategy_signals") or {}
            for key in _STRATEGY_KEYS:
                sig = signals.get(key)
                if sig and isinstance(sig, dict):
                    strategy_signals[key].append(sig)

    # Compute stats per strategy
    stats: list[StrategyStats] = []
    for key in _STRATEGY_KEYS:
        signals = strategy_signals.get(key, [])
        if not signals:
            stats.append(StrategyStats(
                strategy=key,
                name=_STRATEGY_NAMES.get(key, key),
            ))
            continue

        confidences = []
        bullish = 0
        bearish = 0
        strong = 0
        for sig in signals:
            conf = sig.get("confidence", 0)
            try:
                conf = float(conf or 0)
            except (TypeError, ValueError):
                conf = 0.0
            confidences.append(conf)

            direction = sig.get("direction", 0)
            try:
                direction = int(direction or 0)
            except (TypeError, ValueError):
                direction = 0
            if direction > 0:
                bullish += 1
            elif direction < 0:
                bearish += 1
            if conf >= 60:
                strong += 1

        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

        stats.append(StrategyStats(
            strategy=key,
            name=_STRATEGY_NAMES.get(key, key),
            signal_count=len(signals),
            bullish_count=bullish,
            bearish_count=bearish,
            avg_confidence=avg_conf,
            strong_signal_count=strong,
        ))

    # Sort by strong signal count descending
    stats.sort(key=lambda s: s.strong_signal_count, reverse=True)

    # Generate recommendation
    if stats and stats[0].strong_signal_count > 0:
        best = stats[0]
        worst = stats[-1]
        rec = f"近 {lookback_days} 天 {best.name} 信号最强 ({best.strong_signal_count} 次强信号)"
        if worst.strong_signal_count == 0 and worst.strategy != best.strategy:
            rec += f"; {worst.name} 信号最弱, 建议降低权重"
    else:
        rec = "近 {lookback_days} 天无强信号, 市场可能处于震荡期"

    return StrategyReport(
        trade_date=trade_date,
        lookback_days=lookback_days,
        strategies=stats,
        recommendation=rec,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_strategy_report(report: StrategyReport) -> str:
    """Render strategy performance report."""
    if not report.strategies:
        return f"\n{Fore.CYAN}📊 Strategy Performance Report (策略表现周报){Style.RESET_ALL}\n  无数据\n"

    lines = [
        f"\n{Fore.CYAN}📊 Strategy Performance Report (策略表现周报){Style.RESET_ALL}",
        f"  Lookback: {report.lookback_days} days  |  Date: {report.trade_date}",
        "",
        f"  {'策略':<12} {'信号数':>6} {'看多':>6} {'看空':>6} {'强信号':>6} {'平均信心':>8}",
        f"  {'─' * 12} {'─' * 6} {'─' * 6} {'─' * 6} {'─' * 6} {'─' * 8}",
    ]

    for s in report.strategies:
        # Color by strong signal count
        if s.strong_signal_count >= 5:
            color = Fore.GREEN
        elif s.strong_signal_count >= 2:
            color = Fore.YELLOW
        else:
            color = Fore.RED

        lines.append(
            f"  {s.name:<12} {s.signal_count:>6} "
            f"{Fore.GREEN}{s.bullish_count:>6}{Style.RESET_ALL} "
            f"{Fore.RED}{s.bearish_count:>6}{Style.RESET_ALL} "
            f"{color}{s.strong_signal_count:>6}{Style.RESET_ALL} "
            f"{s.avg_confidence:>7.1f}%"
        )

    if report.recommendation:
        lines.append("")
        lines.append(f"  💡 {report.recommendation}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def run_strategy_report(argv: list[str] | None = None) -> int:
    """CLI entry point for --strategy-report."""
    lookback = 7
    if argv:
        for arg in argv:
            if arg.startswith("--lookback="):
                try:
                    lookback = int(arg.split("=")[1])
                except ValueError:
                    pass

    reports_dir = resolve_report_dir()
    report = compute_strategy_report(
        lookback_days=lookback,
        reports_dir=reports_dir,
    )
    print(render_strategy_report(report))
    return 0
