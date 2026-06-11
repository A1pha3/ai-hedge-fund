"""Recommendation Outlier Detection -- P8-2.

Detect stocks whose score_b changed dramatically day-over-day.
Large single-day jumps may indicate data quality issues rather
than genuine signal improvements.

CLI:
    python src/main.py --outlier-detect
    python src/main.py --outlier-detect --top-n=20 --threshold=0.3
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.screening.consecutive_recommendation import resolve_report_dir
from src.utils.display import Fore, Style
from src.screening.daily_delta import _load_sorted_reports


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_OUTLIER_THRESHOLD: float = 0.30  # 30% score jump = outlier


# ---------------------------------------------------------------------------
# Core outlier detection
# ---------------------------------------------------------------------------


def detect_outliers(
    *,
    top_n: int = 20,
    threshold: float = _DEFAULT_OUTLIER_THRESHOLD,
    reports_dir: Path | None = None,
) -> dict[str, Any]:
    """Detect recommendation score outliers between adjacent days.

    Args:
        top_n: Number of top recommendations to compare
        threshold: Minimum score_b delta to flag as outlier (default 0.30)
        reports_dir: Reports directory

    Returns:
        Dict with ``outliers``, ``total_compared``, ``threshold``
    """
    search_dir = reports_dir or resolve_report_dir()
    reports = _load_sorted_reports(search_dir)

    if len(reports) < 2:
        return {
            "outliers": [],
            "total_compared": 0,
            "threshold": threshold,
            "error": "Need at least 2 days of reports",
        }

    today_data = reports[0]["data"]
    yesterday_data = reports[1]["data"]

    today_recs = (today_data.get("recommendations") or [])[:top_n]
    yesterday_recs = (yesterday_data.get("recommendations") or [])[:top_n]

    yesterday_map: dict[str, float] = {}
    for rec in yesterday_recs:
        ticker = str(rec.get("ticker", ""))
        score = float(rec.get("score_b", 0) or 0)
        yesterday_map[ticker] = score

    outliers: list[dict[str, Any]] = []
    for rec in today_recs:
        ticker = str(rec.get("ticker", ""))
        name = str(rec.get("name", ""))
        today_score = float(rec.get("score_b", 0) or 0)
        yesterday_score = yesterday_map.get(ticker)

        if yesterday_score is None:
            # New entry — not an outlier, just new
            continue

        delta = today_score - yesterday_score
        abs_delta = abs(delta)

        if abs_delta >= threshold:
            direction = "surge" if delta > 0 else "drop"
            outliers.append({
                "ticker": ticker,
                "name": name,
                "today_score": round(today_score, 4),
                "yesterday_score": round(yesterday_score, 4),
                "delta": round(delta, 4),
                "abs_delta": round(abs_delta, 4),
                "direction": direction,
                "today_rank": today_recs.index(rec) + 1,
            })

    # Sort by absolute delta descending
    outliers.sort(key=lambda x: x["abs_delta"], reverse=True)

    return {
        "today_date": reports[0]["date"],
        "yesterday_date": reports[1]["date"],
        "outliers": outliers,
        "outlier_count": len(outliers),
        "total_compared": len(today_recs),
        "threshold": threshold,
    }


def render_outliers(result: dict[str, Any]) -> str:
    """Render outlier detection results."""
    if result.get("error"):
        return f"{Fore.YELLOW}⚠ {result['error']}{Style.RESET_ALL}"

    lines = [
        f"\n{Fore.CYAN}🔍 Outlier Detection (score_b jumps ≥ {result['threshold']:.0%}){Style.RESET_ALL}",
        f"  Period: {result['yesterday_date']} → {result['today_date']}",
        f"  Compared: {result['total_compared']} stocks",
    ]

    outliers = result.get("outliers", [])
    if not outliers:
        lines.append(f"  {Fore.GREEN}✓ No significant outliers detected{Style.RESET_ALL}")
    else:
        lines.append(f"  {Fore.YELLOW}⚠ {len(outliers)} outlier(s) detected:{Style.RESET_ALL}")
        for o in outliers:
            color = Fore.RED if o["direction"] == "drop" else Fore.GREEN if o["direction"] == "surge" else Fore.WHITE
            arrow = "↑" if o["direction"] == "surge" else "↓"
            lines.append(
                f"    {color}{arrow}{Style.RESET_ALL} {o['name']} ({o['ticker']}) "
                f"{o['yesterday_score']:.4f} → {o['today_score']:.4f} "
                f"(Δ={o['delta']:+.4f}) rank #{o['today_rank']}"
            )
        lines.append("  → Verify data quality for flagged stocks before trading")

    return "\n".join(lines)


def run_outlier_detect(argv: list[str] | None = None) -> int:
    """CLI entry point for --outlier-detect."""
    top_n = 20
    threshold = _DEFAULT_OUTLIER_THRESHOLD
    if argv:
        for arg in argv:
            if arg.startswith("--top-n="):
                try:
                    top_n = int(arg.split("=")[1])
                except ValueError:
                    pass
            elif arg.startswith("--threshold="):
                try:
                    threshold = float(arg.split("=")[1])
                except ValueError:
                    pass

    reports_dir = resolve_report_dir()
    result = detect_outliers(top_n=top_n, threshold=threshold, reports_dir=reports_dir)
    print(render_outliers(result))
    return 0
