"""Selection artifact digest: aggregate candidate-pool / scoring trends over a date range.

Reads daily ``selection_snapshot.json`` artifacts produced by
``src.research.artifacts`` and produces a summary covering:

- average candidate count, score distribution, score std
- unique tickers across the period, recurring tickers (>= *min_recurrence* days)
- per-day breakdown (candidate count, top score, top tickers)
- per-ticker frequency map

Usage (CLI)::

    python -m src.research.digest --start 2026-05-06 --end 2026-06-05
    python -m src.research.digest --start 20260506 --end 20260605 --artifact-root /path/to/selection_artifacts
    python -m src.research.digest --last 30

Usage (API)::

    from src.research.digest import run_digest

    result = run_digest(start_date="2026-05-06", end_date="2026-06-05")
    print(result.to_json(indent=2))
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.utils.date_utils import format_date as _format_date, parse_date as _parse_date


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DailyDigest:
    """Per-day digest extracted from a single selection_snapshot.json."""

    date: str
    candidates: int
    top_score: float | None
    top_tickers: list[str]
    avg_score: float | None
    score_std: float | None
    near_miss_count: int
    rejected_count: int
    market_regime: str | None


@dataclass
class DigestResult:
    """Full digest result for a date range."""

    period_start: str
    period_end: str
    total_days: int
    days_with_data: int
    summary: dict[str, Any] = field(default_factory=dict)
    daily: list[DailyDigest] = field(default_factory=list)
    ticker_frequency: dict[str, int] = field(default_factory=dict)

    # -- serialization helpers ------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, **json_kwargs: Any) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, **json_kwargs)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------



def _read_selection_snapshot(artifact_root: Path, trade_date: str) -> dict[str, Any] | None:
    """Read a selection_snapshot.json. Returns None if not found."""
    formatted = _format_date(trade_date)
    snapshot_path = artifact_root / formatted / "selection_snapshot.json"
    if not snapshot_path.exists():
        return None
    return json.loads(snapshot_path.read_text(encoding="utf-8"))


def _extract_scores(entries: list[dict[str, Any]]) -> list[float]:
    """Extract score_final from a list of selected / rejected entries."""
    scores: list[float] = []
    for entry in entries:
        sf = entry.get("score_final")
        if sf is not None:
            try:
                scores.append(float(sf))
            except (TypeError, ValueError):
                pass
    return scores


def _compute_std(values: list[float]) -> float | None:
    """Sample standard deviation (Bessel-corrected). Returns None for < 2 values."""
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return round(math.sqrt(variance), 6)


def _extract_daily_digest(snapshot: dict[str, Any], trade_date: str) -> DailyDigest:
    """Build a DailyDigest from a single snapshot dict."""
    selected: list[dict[str, Any]] = snapshot.get("selected") or []
    rejected: list[dict[str, Any]] = snapshot.get("rejected") or []

    # Near-miss is embedded in target_summary at the top level (flat) per
    # src.targets.models.DualTargetSummary: ``short_trade_near_miss_count`` and
    # ``research_near_miss_count`` are sibling fields, NOT nested under a
    # ``short_trade`` sub-dict.  We also accept the legacy nested format for
    # backward compatibility with hand-rolled test fixtures.
    near_miss_count = 0
    target_summary = snapshot.get("target_summary") or {}
    if isinstance(target_summary, dict):
        # Flat fields (canonical): add both short_trade and research near-miss counts
        flat_short = int(target_summary.get("short_trade_near_miss_count", 0) or 0)
        flat_research = int(target_summary.get("research_near_miss_count", 0) or 0)
        # Use short_trade as the primary signal (Layer B); only add research
        # if the snapshot doesn't separate them.  When both are present
        # (canonical case), short_trade is the operational count.
        if flat_short or flat_research:
            near_miss_count = flat_short if flat_short else flat_research
        # Legacy nested format fallback
        st = target_summary.get("short_trade")
        if isinstance(st, dict) and near_miss_count == 0:
            near_miss_count = int(st.get("near_miss_count", 0) or 0)

    # Also check target_context for near_miss count as fallback
    if near_miss_count == 0:
        target_context = snapshot.get("target_context") or []
        if isinstance(target_context, list):
            for ctx in target_context:
                short_trade = ctx.get("short_trade") or {}
                if isinstance(short_trade, dict) and short_trade.get("decision") == "near_miss":
                    near_miss_count += 1

    all_scored = selected + rejected
    scores = _extract_scores(all_scored)

    top_tickers: list[str] = []
    top_score: float | None = None
    if selected:
        sorted_sel = sorted(selected, key=lambda e: float(e.get("score_final") or 0), reverse=True)
        top_tickers = [
            str(e.get("symbol", ""))
            for e in sorted_sel[:10]
            if str(e.get("symbol", "")).strip()
        ]
        top_score = float(sorted_sel[0].get("score_final") or 0)

    avg_score: float | None = None
    if scores:
        avg_score = round(sum(scores) / len(scores), 6)

    market_state = snapshot.get("market_state") or {}
    regime: str | None = None
    if isinstance(market_state, dict):
        regime = market_state.get("regime_gate_level")

    return DailyDigest(
        date=_format_date(trade_date),
        candidates=len(selected),
        top_score=top_score,
        top_tickers=top_tickers,
        avg_score=avg_score,
        score_std=_compute_std(scores),
        near_miss_count=near_miss_count,
        rejected_count=len(rejected),
        market_regime=regime,
    )


# ---------------------------------------------------------------------------
# Artifact root discovery
# ---------------------------------------------------------------------------


def _find_artifact_root(start_date: str, end_date: str) -> Path:
    """Find the artifact root directory.

    Searches common locations and prefers the one that contains data
    for the requested date range.
    """
    repo_root = Path(__file__).resolve().parents[2]
    formatted_start = _format_date(start_date)

    candidates: list[Path] = [
        repo_root / "data" / "selection_artifacts",
        repo_root / "data" / "paper_trading_window_sample" / "selection_artifacts",
    ]

    # Scan report directories for matching data
    reports_root = repo_root / "data" / "reports"
    if reports_root.exists():
        for report_dir in sorted(reports_root.iterdir()):
            if not report_dir.is_dir():
                continue
            sa = report_dir / "selection_artifacts"
            if sa.is_dir() and (sa / formatted_start / "selection_snapshot.json").exists():
                candidates.insert(0, sa)

    # Prefer the first candidate that has the start date
    for candidate in candidates:
        if (candidate / formatted_start / "selection_snapshot.json").exists():
            return candidate

    # Fallback: first candidate that exists at all
    for candidate in candidates:
        if candidate.is_dir():
            return candidate

    # Last resort
    return candidates[0]


def _discover_artifact_roots(start_date: str, end_date: str) -> list[Path]:
    """Discover all artifact roots that may have data for the requested range.

    Returns a prioritized list. The most relevant root (with the most
    matching dates) comes first.
    """
    repo_root = Path(__file__).resolve().parents[2]
    _format_date(start_date)

    roots: list[tuple[int, Path]] = []

    # Known top-level locations
    for static in (
        repo_root / "data" / "selection_artifacts",
        repo_root / "data" / "paper_trading_window_sample" / "selection_artifacts",
    ):
        if static.is_dir():
            count = sum(1 for p in static.iterdir() if p.is_dir() and (p / "selection_snapshot.json").exists())
            if count > 0:
                roots.append((count, static))

    # Report directories
    reports_root = repo_root / "data" / "reports"
    if reports_root.exists():
        for report_dir in sorted(reports_root.iterdir()):
            if not report_dir.is_dir():
                continue
            sa = report_dir / "selection_artifacts"
            if not sa.is_dir():
                continue
            count = sum(1 for p in sa.iterdir() if p.is_dir() and (p / "selection_snapshot.json").exists())
            if count > 0:
                roots.append((count, sa))

    # Sort by count descending; return only paths
    roots.sort(key=lambda t: t[0], reverse=True)
    return [r for _, r in roots]


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------


def run_digest(
    *,
    start_date: str,
    end_date: str | None = None,
    artifact_root: Path | str | None = None,
    min_recurrence: int = 5,
    scan_all_roots: bool = False,
) -> DigestResult:
    """Run the selection artifact digest for a date range.

    Args:
        start_date: Start date (YYYYMMDD or YYYY-MM-DD).
        end_date: End date inclusive. If None, defaults to today.
        artifact_root: Explicit artifact root. If None, auto-discovers.
        min_recurrence: Minimum days a ticker must appear to be "recurring".
        scan_all_roots: If True and *artifact_root* is None, scans all
            discovered artifact roots and merges data. If False, uses
            the first matching root.

    Returns:
        DigestResult with summary, daily breakdown, and ticker frequency.
    """
    formatted_start = _format_date(start_date)

    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    formatted_end = _format_date(end_date)

    start_dt = _parse_date(formatted_start)
    end_dt = _parse_date(formatted_end)

    if start_dt > end_dt:
        return DigestResult(
            period_start=formatted_start,
            period_end=formatted_end,
            total_days=0,
            days_with_data=0,
            summary={"error": f"start_date ({formatted_start}) > end_date ({formatted_end})"},
        )

    # Determine artifact root(s)
    if artifact_root is not None:
        roots = [Path(artifact_root)]
    elif scan_all_roots:
        roots = _discover_artifact_roots(formatted_start, formatted_end)
    else:
        roots = [_find_artifact_root(formatted_start, formatted_end)]

    # Iterate over each calendar day and read snapshots
    daily_digests: list[DailyDigest] = []
    ticker_counter: Counter[str] = Counter()
    seen_dates: set[str] = set()

    current_dt = start_dt
    while current_dt <= end_dt:
        date_str = current_dt.strftime("%Y-%m-%d")
        current_dt += timedelta(days=1)

        snapshot: dict[str, Any] | None = None
        for root in roots:
            snapshot = _read_selection_snapshot(root, date_str)
            if snapshot is not None:
                break

        if snapshot is None:
            continue

        # Skip duplicate dates (can happen when scanning multiple roots)
        snapshot_date = _format_date(snapshot.get("trade_date", date_str))
        if snapshot_date in seen_dates:
            continue
        seen_dates.add(snapshot_date)

        daily = _extract_daily_digest(snapshot, snapshot_date)
        daily_digests.append(daily)

        # Accumulate ticker frequency
        selected: list[dict[str, Any]] = snapshot.get("selected") or []
        for entry in selected:
            sym = str(entry.get("symbol", "")).strip()
            if sym:
                ticker_counter[sym] += 1

    # Build summary
    total_days = (end_dt - start_dt).days + 1
    days_with_data = len(daily_digests)

    if days_with_data == 0:
        return DigestResult(
            period_start=formatted_start,
            period_end=formatted_end,
            total_days=total_days,
            days_with_data=0,
            summary={"warning": "No selection artifacts found for the requested period"},
        )

    candidate_counts = [d.candidates for d in daily_digests]
    avg_candidates = round(sum(candidate_counts) / len(candidate_counts), 2)

    top_scores = [d.top_score for d in daily_digests if d.top_score is not None]
    avg_top_score = round(sum(top_scores) / len(top_scores), 6) if top_scores else None

    all_scores: list[float] = []
    for d in daily_digests:
        if d.avg_score is not None:
            all_scores.append(d.avg_score)
    score_std = _compute_std(all_scores)

    unique_tickers_total = len(ticker_counter)
    recurring_tickers = sorted(
        [t for t, c in ticker_counter.items() if c >= min_recurrence],
        key=lambda t: ticker_counter[t],
        reverse=True,
    )

    summary: dict[str, Any] = {
        "total_days": total_days,
        "days_with_data": days_with_data,
        "avg_candidates": avg_candidates,
        "avg_top_score": avg_top_score,
        "score_std": score_std,
        "unique_tickers_total": unique_tickers_total,
        "recurring_tickers": recurring_tickers,
        "min_recurrence": int(min_recurrence),  # ALPHA-R20.11: propagate to formatter
    }

    # Sort daily by date
    daily_digests.sort(key=lambda d: d.date)

    return DigestResult(
        period_start=formatted_start,
        period_end=formatted_end,
        total_days=total_days,
        days_with_data=days_with_data,
        summary=summary,
        daily=daily_digests,
        ticker_frequency=dict(ticker_counter.most_common()),
    )


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_digest_markdown(result: DigestResult) -> str:
    """Format the digest result as a human-readable Markdown string."""
    lines: list[str] = []
    lines.append(f"# Selection Digest: {result.period_start} ~ {result.period_end}")
    lines.append("")

    s = result.summary
    if s.get("warning"):
        lines.append(f"> **Warning**: {s['warning']}")
        return "\n".join(lines)
    if s.get("error"):
        lines.append(f"> **Error**: {s['error']}")
        return "\n".join(lines)

    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Days in range | {s.get('total_days', 'N/A')} |")
    lines.append(f"| Days with data | {s.get('days_with_data', 'N/A')} |")
    lines.append(f"| Avg candidates/day | {s.get('avg_candidates', 'N/A')} |")
    lines.append(f"| Avg top score | {s.get('avg_top_score', 'N/A')} |")
    lines.append(f"| Score std | {s.get('score_std', 'N/A')} |")
    lines.append(f"| Unique tickers | {s.get('unique_tickers_total', 'N/A')} |")
    # ALPHA-R20.11: read min_recurrence from the summary dict (set by run_digest)
    # so non-default values (e.g. min_recurrence=10) are reflected in the header.
    min_recurrence_for_header = int(s.get("min_recurrence", 5) or 5)
    lines.append(f"| Recurring tickers (>= {min_recurrence_for_header}d) | {len(s.get('recurring_tickers', []))} |")
    lines.append("")

    # Recurring tickers
    recurring = s.get("recurring_tickers", [])
    if recurring:
        lines.append("### Recurring Tickers")
        lines.append("")
        for ticker in recurring[:20]:
            freq = result.ticker_frequency.get(ticker, 0)
            lines.append(f"- `{ticker}`: {freq} days")
        if len(recurring) > 20:
            lines.append(f"- ... and {len(recurring) - 20} more")
        lines.append("")

    # Daily breakdown
    lines.append("## Daily Breakdown")
    lines.append("")
    lines.append("| Date | Candidates | Top Score | Avg Score | Near Miss | Rejected | Regime | Top Tickers |")
    lines.append("|------|-----------|-----------|-----------|-----------|----------|--------|-------------|")
    for d in result.daily:
        top_s = f"{d.top_score:.4f}" if d.top_score is not None else "N/A"
        avg_s = f"{d.avg_score:.4f}" if d.avg_score is not None else "N/A"
        regime = d.market_regime or "-"
        top_t = ", ".join(d.top_tickers[:5]) if d.top_tickers else "-"
        lines.append(f"| {d.date} | {d.candidates} | {top_s} | {avg_s} | {d.near_miss_count} | {d.rejected_count} | {regime} | {top_t} |")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Selection artifact digest: aggregate candidate-pool / scoring trends over a date range",
    )
    parser.add_argument(
        "--start",
        help="Start date in YYYYMMDD or YYYY-MM-DD format",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="End date inclusive (default: today). YYYYMMDD or YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--last",
        type=int,
        default=None,
        help="Shortcut: digest last N days (overrides --start/--end)",
    )
    parser.add_argument(
        "--min-recurrence",
        type=int,
        default=5,
        help="Minimum days a ticker must appear to be 'recurring' (default: 5)",
    )
    parser.add_argument(
        "--artifact-root",
        type=str,
        default=None,
        help="Override artifact root directory",
    )
    parser.add_argument(
        "--scan-all-roots",
        action="store_true",
        help="Scan all artifact roots and merge (useful when data is scattered across report dirs)",
    )
    parser.add_argument(
        "--format",
        choices=["json", "markdown", "md"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    args = parser.parse_args(argv)

    # Resolve date range
    if args.last:
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=args.last - 1)
        start_date = start_dt.strftime("%Y-%m-%d")
        end_date = end_dt.strftime("%Y-%m-%d")
    elif args.start:
        start_date = args.start
        end_date = args.end
    else:
        parser.error("Either --start or --last is required")
        return  # unreachable, satisfies type checker

    result = run_digest(
        start_date=start_date,
        end_date=end_date,
        artifact_root=Path(args.artifact_root) if args.artifact_root else None,
        min_recurrence=args.min_recurrence,
        scan_all_roots=args.scan_all_roots,
    )

    if args.format == "json":
        print(result.to_json(indent=2))
    else:
        print(format_digest_markdown(result))


if __name__ == "__main__":
    main()
