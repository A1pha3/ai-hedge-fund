"""Verdict distribution daily monitor — F4 evaluator (AutoDev C8/NS-18 gap 4).

Tracks BUY/HOLD/AVOID ratio drift across daily ``auto_screening_YYYYMMDD.json``
reports so the owner can self-audit model conservatism. F4 (reduce low-quality
candidates) next_evaluator per ``decision-state.json``.

The script reads existing report artifacts (no recomputation) and produces
append-only JSONL tracking at ``outputs/monitoring/verdict_distribution_tracking.jsonl``.

Each JSONL line schema::

    {
      "trade_date": "20260701",
      "report_path": "data/reports/auto_screening_20260701.json",
      "market_regime": "normal",
      "total_recommendations": 300,
      "verdict_counts": {"BUY": 12, "HOLD": 80, "AVOID": 208},
      "verdict_ratios": {"BUY": 0.04, "HOLD": 0.267, "AVOID": 0.693},
      "ts": "2026-07-02T08:30:00Z"
    }

Usage::

    uv run python scripts/monitor_avoid_ratio.py
        # Process latest auto_screening_*.json report, append to JSONL

    uv run python scripts/monitor_avoid_ratio.py --backfill
        # Scan all historical reports, dedup by trade_date, append missing

    uv run python scripts/monitor_avoid_ratio.py --trend
        # Print last 7 days trend from JSONL

    uv run python scripts/monitor_avoid_ratio.py --trend --days 30
        # Print last 30 days trend

    uv run python scripts/monitor_avoid_ratio.py --report-date 20260701
        # Process a specific date's report

Note: ``build_front_door_verdict`` reads ``composite_score_gated`` (NS-11 C232
pre-bonus isolation) when present, else falls back to ``composite_score``. Raw
report recommendations lack ``composite_score_gated`` (computed at top_picks
runtime), so monitor verdicts may differ slightly from ``--top-picks`` footer
distribution. This is acceptable for F4 trend monitoring — we track drift, not
absolute parity with the front-door representative_picks view.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORTS_DIR = PROJECT_ROOT / "data" / "reports"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "monitoring"
DEFAULT_TRACKING_FILE = DEFAULT_OUTPUT_DIR / "verdict_distribution_tracking.jsonl"

logger = logging.getLogger("monitor_avoid_ratio")


# ---------------------------------------------------------------------------
# Report loading
# ---------------------------------------------------------------------------


def _find_latest_report(reports_dir: Path) -> Path | None:
    """Locate the latest ``auto_screening_YYYYMMDD.json`` in ``reports_dir``.

    Mirrors the date-validation rule from
    :func:`src.screening.data_quality_audit._find_latest_report`: only stems
    parseable as ``%Y%m%d`` are considered, so malformed filenames (e.g.
    ``auto_screening_garbage.json``) cannot be selected as "latest".
    """
    candidates: list[tuple[datetime, Path]] = []
    for path in reports_dir.glob("auto_screening_*.json"):
        stem = path.stem.removeprefix("auto_screening_")
        try:
            dt = datetime.strptime(stem, "%Y%m%d")
        except ValueError:
            logger.debug("skipping malformed report filename: %s", path.name)
            continue
        candidates.append((dt, path))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[-1][1]


def _find_report_by_date(reports_dir: Path, trade_date: str) -> Path | None:
    """Locate ``auto_screening_{trade_date}.json`` with strict date validation."""
    if not (len(trade_date) == 8 and trade_date.isdigit()):
        logger.warning("invalid --report-date %r (expected YYYYMMDD)", trade_date)
        return None
    try:
        datetime.strptime(trade_date, "%Y%m%d")
    except ValueError as exc:
        logger.warning("invalid --report-date %r: %s", trade_date, exc)
        return None
    path = reports_dir / f"auto_screening_{trade_date}.json"
    return path if path.exists() else None


def _list_all_reports(reports_dir: Path) -> list[tuple[datetime, Path]]:
    """List all dated ``auto_screening_YYYYMMDD.json`` files sorted ascending."""
    out: list[tuple[datetime, Path]] = []
    for path in reports_dir.glob("auto_screening_*.json"):
        stem = path.stem.removeprefix("auto_screening_")
        try:
            dt = datetime.strptime(stem, "%Y%m%d")
        except ValueError:
            logger.debug("skipping malformed report filename: %s", path.name)
            continue
        out.append((dt, path))
    out.sort(key=lambda x: x[0])
    return out


def _load_report(path: Path) -> dict[str, Any] | None:
    """Load report JSON with explicit error handling.

    Returns ``None`` on read/parse failure; caller treats as missing data.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        logger.warning("report read failed (%s): %s", path.name, exc, exc_info=True)
        return None
    except json.JSONDecodeError as exc:
        logger.warning("report JSON parse failed (%s): %s", path.name, exc, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Verdict distribution computation
# ---------------------------------------------------------------------------


def compute_verdict_distribution(
    report: dict[str, Any],
) -> dict[str, Any]:
    """Compute BUY/HOLD/AVOID counts + ratios over all recommendations.

    Uses :func:`src.screening.investability.build_front_door_verdict` so the
    monitor stays in sync with the front-door decision logic (NS-11 pre-bonus
    gate, C219 T+5/T+10 horizon, C245 crisis regime conditional, NS-18 gap 1
    invalidation_reasons). ``market_regime`` is read from
    ``report.market_state.regime_gate_level`` (the same field
    :func:`top_picks._render_market_gate` consumes).
    """
    # Lazy import to keep script startup fast and avoid circular deps at module
    # load time when tests stub the function.
    from src.screening.investability import build_front_door_verdict

    market_state = report.get("market_state") or {}
    market_regime = str(market_state.get("regime_gate_level") or "unknown")
    recommendations = report.get("recommendations") or []
    counts = {"BUY": 0, "HOLD": 0, "AVOID": 0}
    for rec in recommendations:
        if not isinstance(rec, dict):
            continue
        verdict = build_front_door_verdict(rec, market_regime=market_regime)
        action = verdict.get("action", "AVOID")
        counts[action] = counts.get(action, 0) + 1
    total = sum(counts.values())
    ratios = {
        k: (v / total if total else 0.0)
        for k, v in counts.items()
    }
    return {
        "market_regime": market_regime,
        "total_recommendations": total,
        "verdict_counts": counts,
        "verdict_ratios": ratios,
    }


def _build_tracking_entry(
    trade_date: str,
    report_path: Path,
    distribution: dict[str, Any],
) -> dict[str, Any]:
    """Assemble a single JSONL tracking record."""
    return {
        "trade_date": trade_date,
        "report_path": str(report_path.relative_to(PROJECT_ROOT))
        if report_path.is_relative_to(PROJECT_ROOT)
        else str(report_path),
        "market_regime": distribution["market_regime"],
        "total_recommendations": distribution["total_recommendations"],
        "verdict_counts": distribution["verdict_counts"],
        "verdict_ratios": distribution["verdict_ratios"],
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------------------------------------------------------------------------
# Tracking JSONL read / append
# ---------------------------------------------------------------------------


def _read_existing_dates(tracking_file: Path) -> set[str]:
    """Return the set of ``trade_date`` values already in the tracking file.

    Used for backfill dedup so re-running ``--backfill`` is idempotent.
    """
    if not tracking_file.exists():
        return set()
    seen: set[str] = set()
    for line in tracking_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.debug("skipping malformed tracking line: %s", exc)
            continue
        trade_date = entry.get("trade_date")
        if isinstance(trade_date, str) and trade_date:
            seen.add(trade_date)
    return seen


def _append_entry(tracking_file: Path, entry: dict[str, Any]) -> None:
    """Append a single tracking record as one JSONL line."""
    tracking_file.parent.mkdir(parents=True, exist_ok=True)
    with tracking_file.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logger.info(
        "appended trade_date=%s BUY=%d HOLD=%d AVOID=%d (total=%d, regime=%s)",
        entry["trade_date"],
        entry["verdict_counts"]["BUY"],
        entry["verdict_counts"]["HOLD"],
        entry["verdict_counts"]["AVOID"],
        entry["total_recommendations"],
        entry["market_regime"],
    )


def _process_report(
    report_path: Path,
    tracking_file: Path,
    *,
    force: bool = False,
) -> dict[str, Any] | None:
    """Load a single report, compute distribution, append to tracking JSONL.

    When ``force`` is False (default), skips dates already present in the
    tracking file (idempotent backfill). Returns the entry dict on success,
    ``None`` on skip/failure.
    """
    stem = report_path.stem.removeprefix("auto_screening_")
    try:
        datetime.strptime(stem, "%Y%m%d")
    except ValueError:
        logger.warning("skipping malformed report filename: %s", report_path.name)
        return None
    if not force:
        existing = _read_existing_dates(tracking_file)
        if stem in existing:
            logger.debug("skipping %s (already tracked, use --force to overwrite)", stem)
            return None
    report = _load_report(report_path)
    if report is None:
        return None
    distribution = compute_verdict_distribution(report)
    entry = _build_tracking_entry(stem, report_path, distribution)
    _append_entry(tracking_file, entry)
    return entry


# ---------------------------------------------------------------------------
# Trend rendering
# ---------------------------------------------------------------------------


def _read_tracking_entries(tracking_file: Path) -> list[dict[str, Any]]:
    """Read all tracking entries, sorted ascending by trade_date."""
    if not tracking_file.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in tracking_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError as exc:
            logger.debug("skipping malformed tracking line: %s", exc)
            continue
    entries.sort(key=lambda e: str(e.get("trade_date") or ""))
    return entries


def render_trend(entries: list[dict[str, Any]], days: int) -> str:
    """Render a compact multi-day trend table from tracking entries.

    Shows the last ``days`` entries with per-day BUY/HOLD/AVOID counts, AVOID
    ratio, and delta vs the previous day so the owner can spot conservatism
    drift at a glance.
    """
    if not entries:
        return "(no tracking data yet — run without --trend first)"
    tail = entries[-days:] if days > 0 else entries
    lines = [
        f"\n  Verdict distribution trend (last {len(tail)} days)",
        f"  {'trade_date':<10}  {'regime':<10}  {'BUY':>5}  {'HOLD':>5}  "
        f"{'AVOID':>5}  {'AVOID%':>7}  {'ΔAVOID%':>8}",
    ]
    prev_avoid_ratio: float | None = None
    for e in tail:
        counts = e.get("verdict_counts") or {}
        ratios = e.get("verdict_ratios") or {}
        avoid_ratio = float(ratios.get("AVOID") or 0.0)
        delta_str = ""
        if prev_avoid_ratio is not None:
            delta = avoid_ratio - prev_avoid_ratio
            sign = "+" if delta >= 0 else ""
            delta_str = f"{sign}{delta * 100:+.1f}"
        lines.append(
            f"  {str(e.get('trade_date') or ''):<10}  "
            f"{str(e.get('market_regime') or ''):<10}  "
            f"{int(counts.get('BUY') or 0):>5}  "
            f"{int(counts.get('HOLD') or 0):>5}  "
            f"{int(counts.get('AVOID') or 0):>5}  "
            f"{avoid_ratio * 100:>6.1f}%  "
            f"{delta_str:>8}"
        )
        prev_avoid_ratio = avoid_ratio
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report-date",
        type=str,
        default="",
        help="Process a specific YYYYMMDD report (default: latest available).",
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Scan all historical reports and append missing dates (idempotent).",
    )
    parser.add_argument(
        "--trend",
        action="store_true",
        help="Print recent trend from tracking JSONL (no new computation).",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Trend window size in days (default: 7). Used with --trend.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-compute and overwrite an existing trade_date entry (append a new line).",
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=DEFAULT_REPORTS_DIR,
        help="Reports directory (default: data/reports).",
    )
    parser.add_argument(
        "--tracking-file",
        type=Path,
        default=DEFAULT_TRACKING_FILE,
        help="Tracking JSONL path (default: outputs/monitoring/verdict_distribution_tracking.jsonl).",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.trend:
        entries = _read_tracking_entries(args.tracking_file)
        print(render_trend(entries, args.days))
        return 0

    if not args.reports_dir.exists():
        logger.warning("reports dir not found: %s", args.reports_dir)
        return 1

    if args.backfill:
        reports = _list_all_reports(args.reports_dir)
        if not reports:
            logger.warning("no auto_screening_*.json reports found in %s", args.reports_dir)
            return 1
        logger.info("backfilling %d reports → %s", len(reports), args.tracking_file)
        appended = 0
        for _dt, path in reports:
            if _process_report(path, args.tracking_file, force=args.force) is not None:
                appended += 1
        logger.info("backfill done: %d new entries appended", appended)
        return 0

    if args.report_date:
        report_path = _find_report_by_date(args.reports_dir, args.report_date)
    else:
        report_path = _find_latest_report(args.reports_dir)
    if report_path is None:
        logger.warning(
            "no report found (reports_dir=%s, --report-date=%r)",
            args.reports_dir,
            args.report_date,
        )
        return 1

    entry = _process_report(report_path, args.tracking_file, force=args.force)
    if entry is None:
        return 1
    # Echo a single-line summary so the owner sees the day's verdict mix
    counts = entry["verdict_counts"]
    ratios = entry["verdict_ratios"]
    print(
        f"{entry['trade_date']} regime={entry['market_regime']} "
        f"BUY={counts['BUY']} HOLD={counts['HOLD']} AVOID={counts['AVOID']} "
        f"(AVOID={ratios['AVOID'] * 100:.1f}%)"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
