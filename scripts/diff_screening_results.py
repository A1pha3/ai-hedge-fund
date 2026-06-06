"""Compare two auto-screening JSON reports to surface new entrants, dropouts, and rank movers.

Usage:
    python scripts/diff_screening_results.py --date1 20260601 --date2 20260602
    python scripts/diff_screening_results.py --date1 20260601              # auto-pick latest as date2

Output (printed + saved to data/reports/screening_diff_{date1}_{date2}.json):
- NEW ENTRANTS: tickers in date2 top-N but not date1 top-N
- DROPPED OUT: tickers in date1 top-N but not date2 top-N
- RANK MOVERS: tickers in both, sorted by absolute rank delta
- SCORE MOVERS: tickers in both, sorted by absolute score delta
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_REPORTS_DIR = Path("data/reports")


def _load_report(date: str, reports_dir: Path) -> dict | None:
    path = reports_dir / f"auto_screening_{date}.json"
    if not path.exists():
        print(f"[diff] 报告不存在: {path}", file=sys.stderr)
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        print(f"[diff] 报告 {path} 解析失败: {exc}", file=sys.stderr)
        return None


def _latest_date(reports_dir: Path) -> str | None:
    files = sorted(reports_dir.glob("auto_screening_*.json"), reverse=True)
    if not files:
        return None
    # Filename pattern: auto_screening_YYYYMMDD.json
    name = files[0].stem  # auto_screening_YYYYMMDD
    return name.replace("auto_screening_", "")


def _build_index(report: dict | None) -> dict[str, dict]:
    """Return {ticker: {'rank': int, 'score_b': float, 'name': str, 'industry_sw': str}}."""
    if not report:
        return {}
    index: dict[str, dict] = {}
    for rank, rec in enumerate(report.get("recommendations", []), 1):
        t = rec.get("ticker")
        if not t:
            continue
        index[t] = {
            "rank": rank,
            "score_b": rec.get("score_b", 0.0),
            "name": rec.get("name", ""),
            "industry_sw": rec.get("industry_sw", ""),
        }
    return index


def compute_diff(
    index1: dict[str, dict],
    index2: dict[str, dict],
) -> dict:
    """Compute new entrants, dropouts, rank movers, score movers between two indexes."""
    tickers1 = set(index1)
    tickers2 = set(index2)

    new_entrants = sorted(tickers2 - tickers1)
    dropouts = sorted(tickers1 - tickers2)
    in_both = tickers1 & tickers2

    rank_movers = []
    score_movers = []
    for t in in_both:
        d1 = index1[t]
        d2 = index2[t]
        rank_delta = d1["rank"] - d2["rank"]  # positive = moved up (lower rank number)
        score_delta = d2["score_b"] - d1["score_b"]
        entry = {
            "ticker": t,
            "name": d2.get("name", "") or d1.get("name", ""),
            "industry_sw": d2.get("industry_sw", "") or d1.get("industry_sw", ""),
            "rank_from": d1["rank"],
            "rank_to": d2["rank"],
            "rank_delta": rank_delta,
            "score_from": d1["score_b"],
            "score_to": d2["score_b"],
            "score_delta": score_delta,
        }
        if rank_delta != 0:
            rank_movers.append(entry)
        if abs(score_delta) > 1e-6:
            score_movers.append({**entry})

    rank_movers.sort(key=lambda x: -abs(x["rank_delta"]))
    score_movers.sort(key=lambda x: -abs(x["score_delta"]))

    return {
        "new_entrants": [
            {"ticker": t, **index2[t]} for t in new_entrants
        ],
        "dropouts": [
            {"ticker": t, **index1[t]} for t in dropouts
        ],
        "rank_movers": rank_movers,
        "score_movers": score_movers,
    }


def format_table(diff: dict, date1: str, date2: str) -> str:
    """Format the diff as a human-readable table."""
    lines = []
    lines.append(f"\n{'=' * 70}")
    lines.append(f"[Screening Diff] {date1}  →  {date2}")
    lines.append("=" * 70)

    new = diff["new_entrants"]
    if new:
        lines.append(f"\n[NEW ENTRANTS] {len(new)} 只新进 Top N:")
        for e in new:
            lines.append(
                f"  + {e['ticker']} {e['name']} ({e['industry_sw']}) "
                f"rank={e['rank']} score_b={e['score_b']:+.4f}"
            )

    dropouts = diff["dropouts"]
    if dropouts:
        lines.append(f"\n[DROPPED OUT] {len(dropouts)} 只掉出 Top N:")
        for e in dropouts:
            lines.append(
                f"  - {e['ticker']} {e['name']} ({e['industry_sw']}) "
                f"was rank={e['rank']} score_b={e['score_b']:+.4f}"
            )

    movers = diff["rank_movers"]
    if movers:
        lines.append(f"\n[RANK MOVERS] {len(movers)} 只排名变化:")
        for m in movers[:10]:  # top-10 movers
            arrow = "↑" if m["rank_delta"] > 0 else "↓"
            lines.append(
                f"  {arrow} {m['ticker']} {m['name']} ({m['industry_sw']}) "
                f"#{m['rank_from']} → #{m['rank_to']} (Δ={m['rank_delta']:+d}) "
                f"score_b: {m['score_from']:+.4f} → {m['score_to']:+.4f}"
            )

    if not (new or dropouts or movers):
        lines.append("\n  无变化: 两次 Top N 完全相同")

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare two auto-screening reports to surface new entrants, dropouts, and rank movers"
    )
    parser.add_argument(
        "--date1",
        type=str,
        required=True,
        help="Earlier date (YYYYMMDD)",
    )
    parser.add_argument(
        "--date2",
        type=str,
        default=None,
        help="Later date (YYYYMMDD). If omitted, uses the latest available report.",
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=DEFAULT_REPORTS_DIR,
        help=f"Reports directory (default: {DEFAULT_REPORTS_DIR})",
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Print only the JSON diff (no table)",
    )
    args = parser.parse_args()

    reports_dir: Path = args.reports_dir
    if not reports_dir.exists():
        print(f"[diff] 报告目录不存在: {reports_dir}", file=sys.stderr)
        return 1

    date2 = args.date2 or _latest_date(reports_dir)
    if not date2:
        print(f"[diff] 未找到任何 auto_screening_*.json 报告", file=sys.stderr)
        return 1
    if date2 == args.date1:
        print(f"[diff] date1 和 date2 相同 ({args.date1}), 没有可比信息", file=sys.stderr)
        return 1

    r1 = _load_report(args.date1, reports_dir)
    r2 = _load_report(date2, reports_dir)
    if r1 is None or r2 is None:
        return 1

    idx1 = _build_index(r1)
    idx2 = _build_index(r2)
    if not idx1:
        print(f"[diff] {args.date1} 报告没有 recommendations", file=sys.stderr)
        return 1
    if not idx2:
        print(f"[diff] {date2} 报告没有 recommendations", file=sys.stderr)
        return 1

    diff = compute_diff(idx1, idx2)
    diff_payload = {
        "date1": args.date1,
        "date2": date2,
        **diff,
    }

    if not args.json_only:
        print(format_table(diff, args.date1, date2))

    # Save diff to file
    diff_path = reports_dir / f"screening_diff_{args.date1}_{date2}.json"
    diff_path.write_text(json.dumps(diff_payload, ensure_ascii=False, indent=2))
    print(f"  详细 diff 已保存: {diff_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
