"""Composite Confidence Score — P11-1.

Combines multiple independent signals into a single unified confidence score
per recommendation.  This gives users ONE number to rank picks, instead of
having to mentally combine score_b, momentum, sector strength, consistency,
etc.

Formula::

    composite = base_score
              + momentum_bonus   (from signal_momentum, ±0.10)
              + sector_bonus     (from sector_strength, ±0.05)
              + consistency_adj  (high +0.05, medium 0, low -0.10)
              + freshness_adj    (fresh 0, stale -0.05)

    composite is clamped to [-1.0, +1.0].

CLI::

    python src/main.py --composite-score [--top-n=20]

Integration:
    ``--decision-flow`` Step 10 outputs composite scores for all recommendations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.screening.consecutive_recommendation import resolve_report_dir
from src.screening.data_quality_audit import _find_latest_report
from src.screening.sector_strength import compute_sector_strength
from src.screening.signal_momentum import compute_signal_momentum
from src.screening.signal_consistency import check_signal_consistency
from src.screening.trend_resonance import compute_trend_resonance
from src.screening.volume_confirmation import compute_volume_confirmation
from src.utils.display import Fore, Style


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Consistency adjustment by level
_CONSISTENCY_ADJ: dict[str, float] = {
    "high": 0.05,
    "medium": 0.0,
    "low": -0.10,
    "unknown": -0.05,
}

#: Freshness penalty when data is stale
_STALE_PENALTY: float = -0.05


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class CompositeEntry:
    """Composite confidence score for a single ticker."""

    ticker: str
    name: str = ""
    base_score: float = 0.0
    momentum_bonus: float = 0.0
    sector_bonus: float = 0.0
    consistency_adj: float = 0.0
    volume_factor: float = 0.0
    trend_resonance_factor: float = 0.0
    composite_score: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class CompositeReport:
    """Composite confidence report."""

    trade_date: str = ""
    items: list[CompositeEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_date": self.trade_date,
            "items": [
                {
                    "ticker": item.ticker,
                    "name": item.name,
                    "base_score": round(item.base_score, 4),
                    "momentum_bonus": round(item.momentum_bonus, 4),
                    "sector_bonus": round(item.sector_bonus, 4),
                    "consistency_adj": round(item.consistency_adj, 4),
                    "volume_factor": round(item.volume_factor, 4),
                    "trend_resonance_factor": round(item.trend_resonance_factor, 4),
                    "composite_score": round(item.composite_score, 4),
                }
                for item in self.items
            ],
        }


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def compute_composite_scores(
    *,
    top_n: int = 20,
    lookback_days: int = 5,
    reports_dir: Path | None = None,
) -> CompositeReport:
    """Compute composite confidence scores for latest recommendations.

    Combines:
    1. Base score_b from the latest screening report
    2. Signal momentum bonus (P10-1)
    3. Sector strength bonus (P10-2)
    4. Signal consistency adjustment (P7-1)
    5. Volume-price confirmation (P11-2)

    Args:
        top_n: Number of top recommendations to score
        lookback_days: Lookback for momentum/sector analysis
        reports_dir: Reports directory

    Returns:
        :class:`CompositeReport`
    """
    import json

    search_dir = reports_dir or resolve_report_dir()

    # Load latest report
    report_path = _find_latest_report(search_dir)
    if report_path is None:
        return CompositeReport()

    report_data = json.loads(report_path.read_text(encoding="utf-8"))
    recs = (report_data.get("recommendations") or [])[:top_n]
    trade_date = report_data.get("date", "")

    return compute_composite_scores_for_recommendations(
        recommendations=recs,
        trade_date=trade_date,
        lookback_days=lookback_days,
        reports_dir=search_dir,
    )


def compute_composite_scores_for_recommendations(
    *,
    recommendations: list[dict[str, Any]],
    trade_date: str = "",
    lookback_days: int = 5,
    reports_dir: Path | None = None,
) -> CompositeReport:
    """Compute composite scores for an explicit recommendation list."""
    recs = list(recommendations)
    if not recs:
        return CompositeReport(trade_date=trade_date)

    # Compute momentum (P10-1)
    top_n = len(recs)
    search_dir = reports_dir or resolve_report_dir()
    try:
        momentum_report = compute_signal_momentum(
            top_n=top_n,
            lookback_days=lookback_days,
            reports_dir=search_dir,
        )
        momentum_map = {item.ticker: item.momentum_bonus for item in momentum_report.items}
    except Exception:
        momentum_map = {}

    # Compute sector strength (P10-2)
    try:
        sector_report = compute_sector_strength(
            top_n=top_n,
            lookback_days=lookback_days,
            reports_dir=search_dir,
        )
        sector_map = {item.ticker: item.strength_bonus for item in sector_report.items}
    except Exception:
        sector_map = {}

    # Compute signal consistency (P7-1)
    try:
        consistency_results = check_signal_consistency(recs)
        consistency_map = {
            item.get("ticker", ""): _CONSISTENCY_ADJ.get(item.get("consistency_level", "unknown"), 0.0)
            for item in consistency_results
        }
    except Exception:
        consistency_map = {}

    # Compute volume confirmation (P11-2)
    try:
        volume_report = compute_volume_confirmation(
            top_n=top_n,
            lookback_days=lookback_days,
            reports_dir=search_dir,
        )
        volume_map = {item.ticker: item.volume_factor for item in volume_report.items}
    except Exception:
        volume_map = {}

    # Compute trend resonance (P14-1)
    try:
        trend_report = compute_trend_resonance(
            top_n=top_n,
            reports_dir=search_dir,
        )
        trend_map = {item.ticker: item.resonance_factor for item in trend_report.items}
    except Exception:
        trend_map = {}

    # Build composite entries
    items: list[CompositeEntry] = []
    for rec in recs:
        ticker = str(rec.get("ticker", ""))
        name = str(rec.get("name", "") or "")
        base_score = float(rec.get("score_b", 0.0) or 0.0)

        mom = momentum_map.get(ticker, 0.0)
        sec = sector_map.get(ticker, 0.0)
        con = consistency_map.get(ticker, 0.0)
        vol = volume_map.get(ticker, 0.0)
        trf = trend_map.get(ticker, 0.0)

        composite = max(-1.0, min(1.0, base_score + mom + sec + con + vol + trf))

        items.append(
            CompositeEntry(
                ticker=ticker,
                name=name,
                base_score=base_score,
                momentum_bonus=mom,
                sector_bonus=sec,
                consistency_adj=con,
                volume_factor=vol,
                trend_resonance_factor=trf,
                composite_score=composite,
                details={
                    "momentum_label": "bonus" if mom > 0 else "penalty" if mom < 0 else "neutral",
                    "sector_label": "strong" if sec > 0 else "weak" if sec < 0 else "neutral",
                    "consistency_level": "high" if con > 0 else "low" if con < 0 else "medium",
                    "volume_confirmation": "confirmed" if vol > 0 else "divergence" if vol < 0 else "neutral",
                    "trend_resonance": "resonance" if trf > 0.02 else "conflict" if trf < -0.02 else "neutral",
                },
            )
        )

    # Sort by composite score descending
    items.sort(key=lambda x: x.composite_score, reverse=True)

    return CompositeReport(trade_date=trade_date, items=items)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt_adj(value: float) -> str:
    """Format an adjustment value with color."""
    if value > 0:
        return f"{Fore.GREEN}+{value:.2f}{Style.RESET_ALL}"
    if value < 0:
        return f"{Fore.RED}{value:.2f}{Style.RESET_ALL}"
    return f" {value:.2f}"


def _composite_grade(score: float) -> str:
    """Convert composite score to a letter grade."""
    if score >= 0.7:
        return f"{Fore.GREEN}A{Style.RESET_ALL}"
    if score >= 0.5:
        return f"{Fore.GREEN}B{Style.RESET_ALL}"
    if score >= 0.3:
        return f"{Fore.YELLOW}C{Style.RESET_ALL}"
    if score >= 0.1:
        return f"{Fore.YELLOW}D{Style.RESET_ALL}"
    return f"{Fore.RED}F{Style.RESET_ALL}"


def render_composite_scores(report: CompositeReport) -> str:
    """Render composite confidence scores as a readable table."""
    if not report.items:
        return f"\n{Fore.CYAN}🎯 Composite Confidence Score{Style.RESET_ALL}\n  无推荐数据\n"

    lines = [
        f"\n{Fore.CYAN}🎯 Composite Confidence Score (综合信心评分){Style.RESET_ALL}",
        "  = base + momentum + sector + consistency + volume + trend",
        "",
        f"  {'标的':<8} {'名称':<10} {'Base':>6} {'动量':>6} {'行业':>6} {'一致':>6} {'量价':>6} {'趋势':>6} {'综合':>7} {'等级':>4}",
        f"  {'─' * 8} {'─' * 10} {'─' * 6} {'─' * 6} {'─' * 6} {'─' * 6} {'─' * 6} {'─' * 6} {'─' * 7} {'─' * 4}",
    ]

    for item in report.items:
        grade = _composite_grade(item.composite_score)
        lines.append(
            f"  {item.ticker:<8} {item.name[:10]:<10} "
            f"{item.base_score:>6.3f} {_fmt_adj(item.momentum_bonus):>14} "
            f"{_fmt_adj(item.sector_bonus):>14} {_fmt_adj(item.consistency_adj):>14} "
            f"{_fmt_adj(item.volume_factor):>14} {_fmt_adj(item.trend_resonance_factor):>14} "
            f"{item.composite_score:>+7.3f} {grade:>6}"
        )

    # Summary
    a_count = sum(1 for i in report.items if i.composite_score >= 0.7)
    b_count = sum(1 for i in report.items if 0.5 <= i.composite_score < 0.7)
    weak_count = sum(1 for i in report.items if i.composite_score < 0.3)
    lines.append("")
    lines.append(
        f"  A级(≥0.7): {a_count}  B级(0.5-0.7): {b_count}  "
        f"低信心(<0.3): {weak_count}  总计: {len(report.items)}"
    )
    return "\n".join(lines)


def render_composite_compact(report: CompositeReport) -> str:
    """Render a compact summary for decision flow integration."""
    if not report.items:
        return "  无综合评分数据"

    lines = [f"  综合信心评分 (Top {min(5, len(report.items))}):"]
    for item in report.items[:5]:
        grade = _composite_grade(item.composite_score)
        lines.append(
            f"    {item.ticker:<8} {item.name[:8]:<8} "
            f"综合={item.composite_score:+.3f} {grade}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def run_composite_score(argv: list[str] | None = None) -> int:
    """CLI entry point for --composite-score."""
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
    report = compute_composite_scores(
        top_n=top_n,
        lookback_days=lookback,
        reports_dir=reports_dir,
    )
    print(render_composite_scores(report))
    return 0
