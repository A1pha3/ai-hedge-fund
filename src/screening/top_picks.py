"""One-Command Top Picks — P12-2.

The simplest way to get actionable buy recommendations.
Runs the full decision pipeline and outputs a compact ranked list
with composite confidence scores.

This is the "what should I buy today?" command.

CLI::

    python src/main.py --top-picks [--count=5]
    python src/main.py --top-picks --count=3 --lookback=30

Design principle:
    One command → one answer. No analysis paralysis.
    The user sees: ticker, name, composite score, grade, and why.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.screening.composite_score import (
    compute_composite_scores,
    _composite_grade,
    _fmt_adj,
)
from src.screening.consecutive_recommendation import resolve_report_dir
from src.screening.data_quality_audit import _find_latest_report
from src.utils.display import Fore, Style


def run_top_picks(
    *,
    count: int = 5,
    lookback_days: int = 5,
    reports_dir: Path | None = None,
) -> int:
    """Run full decision pipeline and output top picks.

    Args:
        count: Number of picks to show (default 5)
        lookback_days: Lookback for momentum/sector analysis
        reports_dir: Reports directory

    Returns:
        Exit code
    """
    search_dir = reports_dir or resolve_report_dir()

    # Step 1: Load latest report
    report_path = _find_latest_report(search_dir)
    if report_path is None:
        print(f"{Fore.RED}No auto_screening report found. Run --auto first.{Style.RESET_ALL}")
        return 1

    report_data = json.loads(report_path.read_text(encoding="utf-8"))
    recs = (report_data.get("recommendations") or [])[:count * 3]  # Load more for filtering
    trade_date = report_data.get("trade_date", "")

    if not recs:
        print(f"{Fore.YELLOW}No recommendations in latest report.{Style.RESET_ALL}")
        return 0

    # Step 2: Compute composite scores
    composite = compute_composite_scores(
        top_n=count * 3,
        lookback_days=lookback_days,
        reports_dir=search_dir,
    )

    if not composite.items:
        print(f"{Fore.YELLOW}Unable to compute composite scores.{Style.RESET_ALL}")
        return 0

    # Step 3: Render compact output
    print(f"\n{Fore.CYAN}{Style.BRIGHT}🎯 Today's Top Picks{Style.RESET_ALL}")
    print(f"  Date: {trade_date}  |  Based on composite confidence score (5-factor fusion)")
    print(f"{Fore.WHITE}{'─' * 72}{Style.RESET_ALL}")

    for idx, item in enumerate(composite.items[:count], 1):
        grade = _composite_grade(item.composite_score)
        name = (item.name or item.ticker)[:14]

        # Signal breakdown
        parts = []
        if item.momentum_bonus > 0:
            parts.append(f"{Fore.GREEN}动量↑{Style.RESET_ALL}")
        elif item.momentum_bonus < 0:
            parts.append(f"{Fore.RED}动量↓{Style.RESET_ALL}")
        if item.sector_bonus > 0:
            parts.append(f"{Fore.GREEN}行业强{Style.RESET_ALL}")
        elif item.sector_bonus < 0:
            parts.append(f"{Fore.RED}行业弱{Style.RESET_ALL}")
        if item.consistency_adj > 0:
            parts.append(f"{Fore.GREEN}一致{Style.RESET_ALL}")
        elif item.consistency_adj < 0:
            parts.append(f"{Fore.RED}分歧{Style.RESET_ALL}")
        if item.volume_factor > 0:
            parts.append(f"{Fore.GREEN}放量{Style.RESET_ALL}")
        elif item.volume_factor < 0:
            parts.append(f"{Fore.RED}缩量{Style.RESET_ALL}")

        signal_str = " ".join(parts) if parts else f"{Fore.WHITE}中性{Style.RESET_ALL}"

        # Color by composite score
        if item.composite_score >= 0.5:
            score_color = Fore.GREEN + Style.BRIGHT
        elif item.composite_score >= 0.3:
            score_color = Fore.YELLOW
        else:
            score_color = Fore.RED

        print(
            f"  {Fore.WHITE}{idx}.{Style.RESET_ALL} "
            f"{Fore.CYAN}{item.ticker:<8}{Style.RESET_ALL} "
            f"{name:<14} "
            f"{score_color}{item.composite_score:>+.3f}{Style.RESET_ALL} "
            f"{grade}  "
            f"(base={item.base_score:.3f} {signal_str})"
        )

    print(f"{Fore.WHITE}{'─' * 72}{Style.RESET_ALL}")

    # Quick tips
    strong_picks = [i for i in composite.items[:count] if i.composite_score >= 0.5]
    if strong_picks:
        tickers = ", ".join(f"{Fore.CYAN}{p.ticker}{Style.RESET_ALL}" for p in strong_picks[:3])
        print(f"  💡 High confidence picks: {tickers}")
    else:
        print(f"  ⚠ No high-confidence picks today. Consider waiting for better signals.")

    print()
    return 0
