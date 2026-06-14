"""Signal Consistency Cross-Check -- P7-1.

When multiple strategies give conflicting signals for the same stock,
flag it in the recommendation output. Stocks with high internal
disagreement are less reliable predictions.

CLI:
    python src/main.py --signal-consistency
    python src/main.py --auto   (auto-appended to report)

Integration:
    ``run_auto_screening()`` appends ``signal_consistency`` to report.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.screening.consecutive_recommendation import resolve_report_dir
from src.utils.display import Fore, Style

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CONSISTENCY_LEVELS: dict[str, dict[str, Any]] = {
    "high": {"label": "高度一致", "color": Fore.GREEN, "min_agreement": 0.75},
    "medium": {"label": "部分分歧", "color": Fore.YELLOW, "min_agreement": 0.50},
    "low": {"label": "严重分歧", "color": Fore.RED, "min_agreement": 0.0},
}

_SIGNAL_FIELDS: tuple[str, ...] = ("signal", "direction", "confidence")


# ---------------------------------------------------------------------------
# Core consistency check
# ---------------------------------------------------------------------------


def check_signal_consistency(
    recommendations: list[dict[str, Any]],
    *,
    strategy_names: tuple[str, ...] = ("trend", "mean_reversion", "fundamental", "event_sentiment"),
) -> list[dict[str, Any]]:
    """Check internal signal consistency for each recommendation.

    Args:
        recommendations: List of recommendation dicts from auto_screening report.
        strategy_names: Strategy names to check.

    Returns:
        List of consistency reports, one per recommendation.
    """
    results: list[dict[str, Any]] = []

    for rec in recommendations:
        ticker = str(rec.get("ticker", ""))
        name = str(rec.get("name", ""))
        strategy_signals = rec.get("strategy_signals") or {}
        score_b = float(rec.get("score_b", 0) or 0)

        if not strategy_signals:
            results.append({
                "ticker": ticker,
                "name": name,
                "consistency_level": "unknown",
                "agreement_ratio": 0.0,
                "bullish_count": 0,
                "bearish_count": 0,
                "neutral_count": 0,
                "total_strategies": 0,
                "conflicting_strategies": [],
                "note": "no strategy signals available",
            })
            continue

        # Count signal directions
        bullish = 0
        bearish = 0
        neutral = 0
        direction_map: dict[str, str] = {}

        for sname in strategy_names:
            sig = strategy_signals.get(sname) or {}
            signal = str(sig.get("signal", "neutral")).lower()
            direction_map[sname] = signal
            if signal == "bullish":
                bullish += 1
            elif signal == "bearish":
                bearish += 1
            else:
                neutral += 1

        total = bullish + bearish + neutral
        if total == 0:
            agreement_ratio = 0.0
        else:
            # Agreement = strongest direction / total
            max_direction = max(bullish, bearish, neutral)
            agreement_ratio = max_direction / total

        # Determine consistency level
        consistency_level = "low"
        for level, config in _CONSISTENCY_LEVELS.items():
            if agreement_ratio >= config["min_agreement"]:
                consistency_level = level
                break

        # Find conflicting strategies
        dominant = "bullish" if bullish >= bearish else "bearish" if bearish > bullish else "neutral"
        conflicting = [s for s, d in direction_map.items() if d != dominant and d != "neutral"]

        results.append({
            "ticker": ticker,
            "name": name,
            "score_b": round(score_b, 4),
            "consistency_level": consistency_level,
            "agreement_ratio": round(agreement_ratio, 2),
            "bullish_count": bullish,
            "bearish_count": bearish,
            "neutral_count": neutral,
            "total_strategies": total,
            "dominant_direction": dominant,
            "conflicting_strategies": conflicting,
        })

    return results


def filter_by_consistency(
    recommendations: list[dict[str, Any]],
    min_consistency: str = "medium",
) -> list[dict[str, Any]]:
    """Filter recommendations to only include those meeting minimum consistency.

    Args:
        recommendations: List from check_signal_consistency().
        min_consistency: Minimum level ("high", "medium", "low").

    Returns:
        Filtered list.
    """
    level_order = {"high": 3, "medium": 2, "low": 1, "unknown": 0}
    min_score = level_order.get(min_consistency, 0)
    return [
        rec for rec in recommendations
        if level_order.get(rec.get("consistency_level", "unknown"), 0) >= min_score
    ]


def render_consistency_report(consistency_results: list[dict[str, Any]]) -> str:
    """Render signal consistency check as readable text.

    Args:
        consistency_results: Output of check_signal_consistency().

    Returns:
        Formatted string.
    """
    if not consistency_results:
        return f"{Fore.YELLOW}⚠ No recommendations to check{Style.RESET_ALL}"

    lines = [f"\n{Fore.CYAN}🔍 Signal Consistency Cross-Check{Style.RESET_ALL}", ""]

    # Summary stats
    levels = {"high": 0, "medium": 0, "low": 0, "unknown": 0}
    for r in consistency_results:
        levels[r.get("consistency_level", "unknown")] += 1

    lines.append(
        f"  {Fore.GREEN}High: {levels['high']}{Style.RESET_ALL}  "
        f"{Fore.YELLOW}Medium: {levels['medium']}{Style.RESET_ALL}  "
        f"{Fore.RED}Low: {levels['low']}{Style.RESET_ALL}  "
        f"Unknown: {levels['unknown']}"
    )

    # Flag low-consistency stocks
    low_consistency = [r for r in consistency_results if r.get("consistency_level") == "low"]
    if low_consistency:
        lines.append(f"\n  {Fore.RED}⚠ Low Consistency (internal disagreement):{Style.RESET_ALL}")
        for r in low_consistency[:10]:
            conflict_str = ", ".join(r.get("conflicting_strategies", []))
            lines.append(
                f"    {Fore.RED}•{Style.RESET_ALL} {r['name']} ({r['ticker']}) "
                f"agreement={r['agreement_ratio']:.0%} "
                f"bull={r['bullish_count']}/bear={r['bearish_count']}/neut={r['neutral_count']}"
                f"{f' conflicts: [{conflict_str}]' if conflict_str else ''}"
            )

    # Show high-consistency stocks
    high_consistency = [r for r in consistency_results if r.get("consistency_level") == "high"]
    if high_consistency:
        lines.append(f"\n  {Fore.GREEN}✓ High Consistency (strong agreement):{Style.RESET_ALL}")
        for r in high_consistency[:5]:
            lines.append(
                f"    {Fore.GREEN}•{Style.RESET_ALL} {r['name']} ({r['ticker']}) "
                f"agreement={r['agreement_ratio']:.0%} "
                f"direction={r.get('dominant_direction', '?')} "
                f"score_b={r.get('score_b', '—')}"
            )

    return "\n".join(lines)


def run_consistency_check(
    reports_dir: Path | None = None,
    *,
    top_n: int = 20,
) -> int:
    """Run signal consistency check on latest report.

    Returns exit code.
    """
    from src.screening.data_quality_audit import _find_latest_report

    search_dir = reports_dir or resolve_report_dir()
    report_path = _find_latest_report(search_dir)
    if report_path is None:
        print(f"{Fore.YELLOW}⚠ No auto_screening report found{Style.RESET_ALL}")
        return 1

    report = json.loads(report_path.read_text(encoding="utf-8"))
    recs = (report.get("recommendations") or [])[:top_n]

    results = check_signal_consistency(recs)
    print(render_consistency_report(results))
    return 0
