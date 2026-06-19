"""Sector Rotation Weighting — P10-2.

Use sector (行业) rotation momentum to weight stock recommendations.
Stocks in **strong** sectors receive a bonus; stocks in **weak** sectors
receive a penalty.  This integrates top-down (sector) and bottom-up
(stock-level) analysis into a single ranking.

Data source:
    Reuses :mod:`src.screening.industry_rotation` sector momentum scores.
    If industry_rotation data is unavailable, falls back to neutral (no bonus).

CLI::

    python src/main.py --sector-strength [--top-n=20] [--lookback=5]

Integration:
    ``--auto`` output now includes ``sector_strength`` field per recommendation.
    ``--conviction-ranking`` can include sector strength as a factor.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.screening.consecutive_recommendation import (
    load_auto_screening_history,
    resolve_report_dir,
)
from src.screening.industry_rotation import (
    bottom_weak_industries,
    calculate_industry_rotation,
    IndustrySignal,
    top_strong_industries,
)
from src.utils.display import Fore, Style

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Bonus for stocks in top-strength sectors
_STRONG_SECTOR_BONUS: float = 0.05

#: Penalty for stocks in bottom-weak sectors
_WEAK_SECTOR_PENALTY: float = -0.05

#: How many top/bottom sectors to consider
_STRONG_COUNT: int = 3
_WEAK_COUNT: int = 3


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class SectorStrengthInfo:
    """Sector strength info for a single ticker."""

    ticker: str
    name: str = ""
    industry: str = ""
    sector_momentum: float = 0.0
    sector_rank: int = 0
    sector_total: int = 0
    strength_bonus: float = 0.0
    strength_label: str = "neutral"


@dataclass
class SectorStrengthReport:
    """Sector strength report for all recommended tickers."""

    trade_date: str = ""
    lookback_days: int = 5
    strong_sectors: list[str] = field(default_factory=list)
    weak_sectors: list[str] = field(default_factory=list)
    items: list[SectorStrengthInfo] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_date": self.trade_date,
            "lookback_days": self.lookback_days,
            "strong_sectors": self.strong_sectors,
            "weak_sectors": self.weak_sectors,
            "items": [
                {
                    "ticker": item.ticker,
                    "name": item.name,
                    "industry": item.industry,
                    "sector_momentum": round(item.sector_momentum, 4),
                    "sector_rank": item.sector_rank,
                    "strength_bonus": round(item.strength_bonus, 4),
                    "strength_label": item.strength_label,
                }
                for item in self.items
            ],
        }


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def _build_sector_lookup(
    signals: list[IndustrySignal],
) -> dict[str, tuple[float, int, int]]:
    """Build a lookup from industry name → (momentum, rank, total).

    Returns:
        ``{"电子": (0.45, 1, 30), ...}``
    """
    if not signals:
        return {}

    total = len(signals)
    lookup: dict[str, tuple[float, int, int]] = {}
    for rank_idx, sig in enumerate(signals, start=1):
        lookup[sig.industry_name] = (sig.momentum_score, rank_idx, total)

    return lookup


def compute_sector_strength(
    *,
    top_n: int = 20,
    lookback_days: int = 5,
    reports_dir: Path | None = None,
) -> SectorStrengthReport:
    """Compute sector strength for the latest recommendations.

    Args:
        top_n: Number of top recommendations to analyze
        lookback_days: How many days for industry rotation lookback
        reports_dir: Reports directory

    Returns:
        :class:`SectorStrengthReport`
    """
    search_dir = reports_dir or resolve_report_dir()
    history = load_auto_screening_history(
        lookback_days=lookback_days,
        report_dir=search_dir,
    )

    if not history:
        return SectorStrengthReport(lookback_days=lookback_days)

    # Latest report
    latest = history[0]
    latest_payload = latest.get("payload", {})
    trade_date = latest.get("date", "")
    latest_recs = (latest_payload.get("recommendations") or [])[:top_n]

    if not latest_recs:
        return SectorStrengthReport(trade_date=trade_date, lookback_days=lookback_days)

    # Compute industry rotation signals
    try:
        industry_signals = calculate_industry_rotation(
            recommendations=latest_recs,
            trade_date=trade_date,
            lookback_days=lookback_days,
            reports_dir=str(search_dir),
        )
    except Exception:
        # Traceability: empty industry_signals makes strong/weak sector sets empty,
        # silently disabling sector filtering for the whole candidate pool. Log so a
        # rotation-computation failure is observable rather than masked as neutral.
        logger.debug("industry rotation computation failed; sector filtering disabled", exc_info=True)
        industry_signals = []

    sector_lookup = _build_sector_lookup(industry_signals)

    # Identify strong and weak sectors
    strong = [s.industry_name for s in top_strong_industries(industry_signals, _STRONG_COUNT)]
    weak = [s.industry_name for s in bottom_weak_industries(industry_signals, _WEAK_COUNT)]
    strong_set = set(strong)
    weak_set = set(weak)

    items: list[SectorStrengthInfo] = []
    for rec in latest_recs:
        ticker = str(rec.get("ticker", ""))
        name = str(rec.get("name", "") or "")
        industry = str(rec.get("industry_sw") or rec.get("industry") or "未知").strip()

        if industry in sector_lookup:
            momentum, rank, total = sector_lookup[industry]
        else:
            momentum, rank, total = 0.0, 0, 0

        # Determine strength label and bonus
        if industry in strong_set:
            label = "strong"
            bonus = _STRONG_SECTOR_BONUS
        elif industry in weak_set:
            label = "weak"
            bonus = _WEAK_SECTOR_PENALTY
        else:
            label = "neutral"
            bonus = 0.0

        items.append(
            SectorStrengthInfo(
                ticker=ticker,
                name=name,
                industry=industry,
                sector_momentum=momentum,
                sector_rank=rank,
                sector_total=total,
                strength_bonus=bonus,
                strength_label=label,
            )
        )

    # Sort by strength bonus descending
    items.sort(key=lambda x: x.strength_bonus, reverse=True)

    return SectorStrengthReport(
        trade_date=trade_date,
        lookback_days=lookback_days,
        strong_sectors=strong,
        weak_sectors=weak,
        items=items,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _strength_label_colored(label: str) -> str:
    if label == "strong":
        return f"{Fore.GREEN}强{Style.RESET_ALL}"
    if label == "weak":
        return f"{Fore.RED}弱{Style.RESET_ALL}"
    return f"{Fore.WHITE}中性{Style.RESET_ALL}"


def render_sector_strength(report: SectorStrengthReport) -> str:
    """Render sector strength as a readable table."""
    if not report.items:
        return f"\n{Fore.CYAN}🏭 Sector Strength (行业动量){Style.RESET_ALL}\n  无推荐数据\n"

    lines = [
        f"\n{Fore.CYAN}🏭 Sector Strength (行业动量){Style.RESET_ALL}",
        f"  基于 {report.lookback_days} 天行业轮动数据",
        "",
    ]

    if report.strong_sectors:
        lines.append(
            f"  {Fore.GREEN}强势行业: {', '.join(report.strong_sectors)}{Style.RESET_ALL}"
        )
    if report.weak_sectors:
        lines.append(
            f"  {Fore.RED}弱势行业: {', '.join(report.weak_sectors)}{Style.RESET_ALL}"
        )

    lines.append("")
    lines.append(
        f"  {'标的':<8} {'名称':<12} {'行业':<10} {'行业动量':>8} {'排名':>6} {'强度':>6} {'加权':>6}"
    )
    lines.append(
        f"  {'─' * 8} {'─' * 12} {'─' * 10} {'─' * 8} {'─' * 6} {'─' * 6} {'─' * 6}"
    )

    for item in report.items:
        label = _strength_label_colored(item.strength_label)
        bonus_str = (
            f"{Fore.GREEN}+{item.strength_bonus:.2f}{Style.RESET_ALL}"
            if item.strength_bonus > 0
            else f"{Fore.RED}{item.strength_bonus:.2f}{Style.RESET_ALL}"
            if item.strength_bonus < 0
            else "  0.00"
        )
        rank_str = f"{item.sector_rank}/{item.sector_total}" if item.sector_total > 0 else "—"
        lines.append(
            f"  {item.ticker:<8} {item.name[:12]:<12} {item.industry[:10]:<10} "
            f"{item.sector_momentum:>+8.4f} {rank_str:>6} {label:>8} {bonus_str:>14}"
        )

    # Summary
    strong_count = sum(1 for i in report.items if i.strength_label == "strong")
    weak_count = sum(1 for i in report.items if i.strength_label == "weak")
    neutral_count = len(report.items) - strong_count - weak_count
    lines.append("")
    lines.append(
        f"  {Fore.GREEN}强行业: {strong_count}{Style.RESET_ALL}  "
        f"{Fore.WHITE}中性: {neutral_count}{Style.RESET_ALL}  "
        f"{Fore.RED}弱行业: {weak_count}{Style.RESET_ALL}"
    )
    lines.append(
        f"  {Fore.WHITE}说明: 强行业标的 +{_STRONG_SECTOR_BONUS:.2f}, "
        f"弱行业标的 {_WEAK_SECTOR_PENALTY:.2f}{Style.RESET_ALL}"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def run_sector_strength(argv: list[str] | None = None) -> int:
    """CLI entry point for --sector-strength."""
    top_n = 20
    lookback = 5
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
    report = compute_sector_strength(
        top_n=top_n,
        lookback_days=lookback,
        reports_dir=reports_dir,
    )
    print(render_sector_strength(report))
    return 0
