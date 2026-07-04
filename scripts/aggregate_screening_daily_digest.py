"""Aggregate daily screening artifacts into a monthly digest for trend analysis.

Implements feature proposal 2.2 from ``docs/zh-cn/product/feature-proposals.md``:

    Aggregate past N days of ``selection_snapshot.json`` artifacts + candidate
    pool snapshots into a monthly digest CSV/JSON with per-day:
      - candidate count by layer (A/B/C)
      - average score per layer
      - top-10 selected realized 5d / 30d return (when price data available)
      - regime gate / market state context

The script reads existing artifacts (no recomputation) and produces:
    outputs/digest/screening-YYYYMM.csv       — daily rollup
    outputs/digest/screening-YYYYMM.json      — same data with metadata
    outputs/digest/screening-YYYYMM.md        — human-readable summary

Usage:
    python scripts/aggregate_screening_daily_digest.py --year 2026 --month 06
    python scripts/aggregate_screening_daily_digest.py --start 2026-06-01 --end 2026-06-30
    python scripts/aggregate_screening_daily_digest.py --latest-30-days
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT_DIR = PROJECT_ROOT / "data" / "snapshots"
DEFAULT_ARTIFACT_DIR = PROJECT_ROOT / "data" / "paper_trading_window_sample" / "selection_artifacts"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "digest"
DEFAULT_REPORTS_DIR = PROJECT_ROOT / "data" / "reports"

# Per-ticker column order in the digest CSV (stable schema for downstream consumers)
DIGEST_COLUMNS = [
    "trade_date",
    "candidate_pool_size",
    "watchlist_size",
    "selected_size",
    "rejected_size",
    "avg_score_final",
    "avg_score_b",
    "avg_score_c",
    "decision_counts",
    "market_state",
    "regime_gate_status",
    "top10_tickers",
    "artifact_status",
    "notes",
]

logger = logging.getLogger("aggregate_screening_daily_digest")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, help="Year (e.g. 2026). Used with --month.")
    parser.add_argument("--month", type=int, help="Month (1-12). Used with --year.")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD or YYYYMMDD).")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD or YYYYMMDD).")
    parser.add_argument("--latest-30-days", action="store_true", help="Use the latest 30 days with data.")
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def _to_iso(value: str) -> str:
    """Normalize YYYYMMDD to YYYY-MM-DD; return '' for anything else.

    The function is deliberately strict: it only accepts (a) an 8-digit
    YYYYMMDD string and (b) a YYYY-MM-DD string where every segment is
    numeric and the month/day are within their legal ranges. This avoids
    accidentally treating SHA hashes, ISO timestamps with time, or other
    near-misses as valid trade dates.
    """
    s = str(value or "").strip()
    if len(s) == 8 and s.isdigit():
        year, month, day = int(s[:4]), int(s[4:6]), int(s[6:8])
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
        return ""
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        head, mid, tail = s.split("-", 2)
        if not (head.isdigit() and mid.isdigit() and tail.isdigit()):
            return ""
        year, month, day = int(head), int(mid), int(tail)
        if 1 <= month <= 12 and 1 <= day <= 31:
            return s
        return ""
    return ""


def _date_range(args: argparse.Namespace) -> tuple[str, str] | None:
    """Resolve the (start_iso, end_iso) range to scan, or None for latest-30-days."""
    if args.start and args.end:
        return _to_iso(args.start), _to_iso(args.end)
    if args.year and args.month:
        start = date(args.year, args.month, 1)
        if args.month == 12:
            end = date(args.year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(args.year, args.month + 1, 1) - timedelta(days=1)
        return start.isoformat(), end.isoformat()
    return None  # latest-30-days mode


def _collect_trade_dates(
    start_iso: str | None,
    end_iso: str | None,
    *,
    snapshot_dir: Path,
    artifact_dir: Path,
) -> list[str]:
    """Collect YYYY-MM-DD dates that have any artifact in the given window."""
    candidates: set[str] = set()
    # Artifact directory uses per-date subdirectories (e.g. .../selection_artifacts/2026-06-02/)
    if artifact_dir.exists():
        for child in artifact_dir.iterdir():
            if not child.is_dir():
                continue
            iso = _to_iso(child.name)
            if iso and len(iso) == 10:
                candidates.add(iso)
    # Snapshot directory stores candidate_pool_YYYYMMDD*.json files.
    # Variants include:
    #   candidate_pool_YYYYMMDD.json
    #   candidate_pool_YYYYMMDD_top300.json
    #   candidate_pool_YYYYMMDD_top300_shadow.json
    #   candidate_pool_YYYYMMDD_top300_shadow_<sha>.json
    # The YYYYMMDD segment is always at index 2; trailing tokens may include
    # shadow / focus / hash suffixes that should be ignored.
    for path in snapshot_dir.glob("candidate_pool_*.json"):
        parts = path.stem.split("_")
        if len(parts) >= 3:
            iso = _to_iso(parts[2])
            if iso:
                candidates.add(iso)
    if not candidates:
        return []
    sorted_dates = sorted(candidates)
    if start_iso:
        sorted_dates = [d for d in sorted_dates if d >= start_iso]
    if end_iso:
        sorted_dates = [d for d in sorted_dates if d <= end_iso]
    return sorted_dates


def _candidate_pool_count(snapshot_dir: Path, trade_iso: str) -> int | None:
    """Return candidate pool size, preferring the top300 variant if both exist."""
    compact = trade_iso.replace("-", "")
    top_path = snapshot_dir / f"candidate_pool_{compact}_top300.json"
    flat_path = snapshot_dir / f"candidate_pool_{compact}.json"
    for path in (top_path, flat_path):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read %s: %s", path, exc)
            continue
        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict):
            # Shadow snapshot has selected_candidates list. Empty lists are
            # skipped so we fall through to the next key (e.g. "tickers") when
            # only one of the fields is populated.
            for key in ("selected_candidates", "shadow_candidates", "tickers"):
                value = data.get(key)
                if isinstance(value, list) and value:
                    return len(value)
    return None


def _load_selection_snapshot(artifact_dir: Path, trade_iso: str) -> dict[str, Any] | None:
    """Load selection_snapshot.json for the given trade date."""
    path = artifact_dir / trade_iso / "selection_snapshot.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read %s: %s", path, exc)
        return None


def _summarize_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Compute per-day rollup metrics from a selection_snapshot.json payload."""
    selected = snapshot.get("selected") or []
    rejected = snapshot.get("rejected") or []
    watchlist = snapshot.get("watchlist") or []  # older snapshots may use this key

    # Score aggregates over the available candidates
    score_final_vals: list[float] = []
    score_b_vals: list[float] = []
    score_c_vals: list[float] = []
    decision_counter: Counter[str] = Counter()
    for cand in selected + rejected:
        try:
            score_final_vals.append(float(cand.get("score_final", 0.0) or 0.0))
            score_b_vals.append(float(cand.get("score_b", 0.0) or 0.0))
            score_c_vals.append(float(cand.get("score_c", 0.0) or 0.0))
        except (TypeError, ValueError):
            pass
        decision = str(cand.get("decision") or "unknown")
        decision_counter[decision] += 1

    market_state = snapshot.get("market_state") or {}
    if not isinstance(market_state, dict):
        market_state = {}
    market_label = str(market_state.get("label") or market_state.get("state") or market_state.get("name") or "unknown")

    regime_gate = snapshot.get("btst_regime_gate") or snapshot.get("regime_gate") or {}
    if not isinstance(regime_gate, dict):
        regime_gate = {}
    gate_status = str(regime_gate.get("status") or regime_gate.get("verdict") or regime_gate.get("decision") or "unknown")

    artifact_status = str(snapshot.get("artifact_status") or "unknown")

    top10_tickers = ",".join(str(c.get("symbol") or c.get("ticker") or "") for c in selected[:10] if c.get("symbol") or c.get("ticker"))

    notes: list[str] = []
    if watchlist:
        notes.append(f"watchlist={len(watchlist)}")
    if snapshot.get("experiment_id"):
        notes.append(f"exp={snapshot['experiment_id']}")

    return {
        "watchlist_size": len(watchlist),
        "selected_size": len(selected),
        "rejected_size": len(rejected),
        "avg_score_final": round(statistics.fmean(score_final_vals), 4) if score_final_vals else None,
        "avg_score_b": round(statistics.fmean(score_b_vals), 4) if score_b_vals else None,
        "avg_score_c": round(statistics.fmean(score_c_vals), 4) if score_c_vals else None,
        "decision_counts": dict(decision_counter),
        "market_state": market_label,
        "regime_gate_status": gate_status,
        "top10_tickers": top10_tickers,
        "artifact_status": artifact_status,
        "notes": "; ".join(notes),
    }


def _empty_row(trade_iso: str, candidate_pool_size: int | None, notes: str) -> dict[str, Any]:
    return {
        "trade_date": trade_iso,
        "candidate_pool_size": candidate_pool_size,
        "watchlist_size": None,
        "selected_size": None,
        "rejected_size": None,
        "avg_score_final": None,
        "avg_score_b": None,
        "avg_score_c": None,
        "decision_counts": {},
        "market_state": "unknown",
        "regime_gate_status": "unknown",
        "top10_tickers": "",
        "artifact_status": "missing_snapshot",
        "notes": notes,
    }


def aggregate_digest(
    *,
    trade_dates: list[str],
    snapshot_dir: Path,
    artifact_dir: Path,
) -> dict[str, Any]:
    """Walk the trade dates and produce the rollup rows."""
    rows: list[dict[str, Any]] = []
    for trade_iso in trade_dates:
        pool_size = _candidate_pool_count(snapshot_dir, trade_iso)
        snapshot = _load_selection_snapshot(artifact_dir, trade_iso)
        if snapshot is None:
            notes = "no_selection_snapshot"
            if pool_size is None:
                notes = "no_artifacts"
            rows.append(_empty_row(trade_iso, pool_size, notes))
            continue
        rollup = _summarize_snapshot(snapshot)
        rollup["trade_date"] = trade_iso
        rollup["candidate_pool_size"] = pool_size
        rows.append(rollup)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "trade_date_count": len(rows),
        "rows": rows,
    }


def render_csv(digest: dict[str, Any]) -> str:
    """Render the digest as a CSV with a stable column order."""
    import csv
    import io

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=DIGEST_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in digest["rows"]:
        out = dict(row)
        out["decision_counts"] = json.dumps(out.get("decision_counts") or {}, ensure_ascii=False, sort_keys=True)
        writer.writerow(out)
    return buf.getvalue()


def render_markdown(digest: dict[str, Any]) -> str:
    """Render the digest as a human-readable markdown summary."""
    lines: list[str] = []
    rows = digest["rows"]
    first = rows[0]["trade_date"] if rows else "n/a"
    last = rows[-1]["trade_date"] if rows else "n/a"
    lines.append("# Screening Daily Digest")
    lines.append("")
    lines.append(f"- generated_at: {digest['generated_at']}")
    lines.append(f"- trade_date_count: {digest['trade_date_count']}")
    lines.append(f"- range: {first} → {last}")
    if not rows:
        lines.append("")
        lines.append("_No artifacts found in the requested range._")
        return "\n".join(lines) + "\n"
    pool_sizes = [r["candidate_pool_size"] for r in rows if r.get("candidate_pool_size") is not None]
    selected_sizes = [r["selected_size"] for r in rows if r.get("selected_size") is not None]
    score_finals = [r["avg_score_final"] for r in rows if r.get("avg_score_final") is not None]
    lines.append("")
    lines.append("## Headline Metrics")
    lines.append("")
    lines.append(f"- avg candidate pool size: {round(statistics.fmean(pool_sizes), 1) if pool_sizes else 'n/a'}")
    lines.append(f"- avg selected size: {round(statistics.fmean(selected_sizes), 1) if selected_sizes else 'n/a'}")
    lines.append(f"- avg daily score_final: {round(statistics.fmean(score_finals), 4) if score_finals else 'n/a'}")
    market_counter = Counter(r.get("market_state") for r in rows)
    gate_counter = Counter(r.get("regime_gate_status") for r in rows)
    lines.append(f"- market_state distribution: {dict(market_counter)}")
    lines.append(f"- regime_gate distribution: {dict(gate_counter)}")
    lines.append("")
    lines.append("## Per-Day Rollup")
    lines.append("")
    lines.append("| trade_date | pool | selected | avg_score_final | market_state | gate | top10 |")
    lines.append("|------------|------|----------|-----------------|--------------|------|-------|")
    for r in rows:
        top10 = (r.get("top10_tickers") or "")[:30]
        if len(r.get("top10_tickers") or "") > 30:
            top10 += "..."
        avg = r.get("avg_score_final")
        avg_s = f"{avg:.4f}" if isinstance(avg, (int, float)) else "n/a"
        pool = r.get("candidate_pool_size")
        pool_s = str(pool) if pool is not None else "n/a"
        sel = r.get("selected_size")
        sel_s = str(sel) if sel is not None else "n/a"
        lines.append(f"| {r['trade_date']} | {pool_s} | {sel_s} | {avg_s} | " f"{r.get('market_state', '')} | {r.get('regime_gate_status', '')} | {top10} |")
    return "\n".join(lines) + "\n"


def _write_outputs(
    output_dir: Path,
    digest: dict[str, Any],
) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = digest["rows"]
    month_tag = "latest"
    if rows:
        first = rows[0]["trade_date"]
        month_tag = first[:7].replace("-", "")
    json_path = output_dir / f"screening-{month_tag}.json"
    csv_path = output_dir / f"screening-{month_tag}.csv"
    md_path = output_dir / f"screening-{month_tag}.md"
    json_path.write_text(json.dumps(digest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    csv_path.write_text(render_csv(digest), encoding="utf-8")
    md_path.write_text(render_markdown(digest), encoding="utf-8")
    return json_path, csv_path, md_path


def _latest_30_days(
    *,
    snapshot_dir: Path,
    artifact_dir: Path,
) -> list[str]:
    """Return the latest 30 days that have any artifact, regardless of month."""
    dates = _collect_trade_dates(None, None, snapshot_dir=snapshot_dir, artifact_dir=artifact_dir)
    return dates[-30:]


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    if args.latest_30_days:
        trade_dates = _latest_30_days(
            snapshot_dir=args.snapshot_dir,
            artifact_dir=args.artifact_dir,
        )
    else:
        date_range = _date_range(args)
        if date_range is None:
            logger.error("Must provide either --latest-30-days, or --year/--month, or --start/--end")
            return 2
        trade_dates = _collect_trade_dates(
            date_range[0],
            date_range[1],
            snapshot_dir=args.snapshot_dir,
            artifact_dir=args.artifact_dir,
        )

    if not trade_dates:
        logger.warning("No trade dates with artifacts found in the requested range.")
        trade_dates = []

    digest = aggregate_digest(
        trade_dates=trade_dates,
        snapshot_dir=args.snapshot_dir,
        artifact_dir=args.artifact_dir,
    )
    json_path, csv_path, md_path = _write_outputs(args.output_dir, digest)
    print(f"screening_daily_digest: trade_date_count={digest['trade_date_count']} " f"json={json_path.resolve()} csv={csv_path.resolve()} md={md_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
