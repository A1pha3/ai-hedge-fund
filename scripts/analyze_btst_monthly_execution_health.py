from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.analyze_btst_monthly_scorecard import _compact_date


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _write_text(path: str | Path, text: str) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _write_json(path: str | Path, payload: Any) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _iter_plan_dirs(*, reports_dir: Path) -> list[Path]:
    return [path for path in sorted(reports_dir.glob("paper_trading_*_plan")) if path.is_dir()]


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _count_tickers(payload: Any) -> int:
    if isinstance(payload, list):
        return int(len(payload))
    return 0


def _extract_selected_tickers(brief: dict[str, Any]) -> list[str]:
    tickers: list[str] = []
    primary = brief.get("primary_entry")
    if isinstance(primary, dict):
        ticker = str(primary.get("ticker") or "").strip()
        if ticker:
            tickers.append(ticker)

    for entry in list(brief.get("selected_entries") or []):
        if not isinstance(entry, dict):
            continue
        ticker = str(entry.get("ticker") or "").strip()
        if ticker:
            tickers.append(ticker)

    seen: set[str] = set()
    out: list[str] = []
    for ticker in tickers:
        if ticker in seen:
            continue
        seen.add(ticker)
        out.append(ticker)
    return out


@dataclass
class DailyExecutionHealth:
    trade_date: str
    next_trade_date: str | None
    plan_dir: str
    brief_path: str
    selected_count: int
    near_miss_count: int
    opportunity_pool_count: int
    execution_blocked_candidate_count: int | None
    p2_execution_blocked_count: int | None
    short_trade_selected_count: int | None
    short_trade_near_miss_count: int | None
    short_trade_blocked_count: int | None
    short_trade_rejected_count: int | None


def analyze_btst_monthly_execution_health(
    *,
    month: str,
    reports_dir: str | Path = "data/reports",
) -> dict[str, Any]:
    root = Path(reports_dir).expanduser().resolve()

    selected_runs: dict[str, dict[str, Any]] = {}

    for plan_dir in _iter_plan_dirs(reports_dir=root):
        brief_path = plan_dir / "btst_next_day_trade_brief_latest.json"
        if not brief_path.is_file():
            continue

        try:
            brief = _load_json(brief_path)
        except Exception:
            continue

        trade_date = _compact_date(str(brief.get("trade_date") or "").strip())
        if not trade_date or not trade_date.startswith(str(month).strip()):
            continue

        mtime = float(brief_path.stat().st_mtime)
        prev = selected_runs.get(trade_date)
        if prev is None or float(prev.get("mtime") or 0.0) < mtime:
            selected_runs[trade_date] = {
                "trade_date": trade_date,
                "plan_dir": str(plan_dir),
                "brief_path": str(brief_path),
                "mtime": mtime,
            }

    daily_rows: list[dict[str, Any]] = []

    for trade_date in sorted(selected_runs.keys()):
        run = dict(selected_runs[trade_date] or {})
        plan_dir = Path(str(run.get("plan_dir") or "")).expanduser().resolve()
        brief_path = Path(str(run.get("brief_path") or "")).expanduser().resolve()
        brief = _load_json(brief_path)

        next_trade_date = _compact_date(str(brief.get("next_trade_date") or "").strip()) or None

        selected_tickers = _extract_selected_tickers(brief)
        near_miss = list(brief.get("near_miss_entries") or [])
        opportunity_pool = list(brief.get("opportunity_pool_entries") or [])

        summary = dict(brief.get("summary") or {})

        session_summary_path = str(brief.get("session_summary_path") or "").strip()
        session_summary: dict[str, Any] = {}
        if session_summary_path:
            try:
                session_summary = _load_json(session_summary_path)
            except Exception:
                session_summary = {}

        reporting = dict(session_summary.get("reporting_target_summary") or {})
        dual = dict(session_summary.get("dual_target_summary") or {})

        row = DailyExecutionHealth(
            trade_date=trade_date,
            next_trade_date=next_trade_date,
            plan_dir=str(plan_dir),
            brief_path=str(brief_path),
            selected_count=len(selected_tickers),
            near_miss_count=_count_tickers(near_miss),
            opportunity_pool_count=_count_tickers(opportunity_pool),
            execution_blocked_candidate_count=_as_int(summary.get("execution_blocked_candidate_count")),
            p2_execution_blocked_count=_as_int(reporting.get("p2_execution_blocked_count") or dual.get("p2_execution_blocked_count")),
            short_trade_selected_count=_as_int(reporting.get("short_trade_selected_count") or dual.get("short_trade_selected_count")),
            short_trade_near_miss_count=_as_int(reporting.get("short_trade_near_miss_count") or dual.get("short_trade_near_miss_count")),
            short_trade_blocked_count=_as_int(reporting.get("short_trade_blocked_count") or dual.get("short_trade_blocked_count")),
            short_trade_rejected_count=_as_int(reporting.get("short_trade_rejected_count") or dual.get("short_trade_rejected_count")),
        )

        daily_rows.append(row.__dict__)

    zero_pick_days = [row["trade_date"] for row in daily_rows if int(row.get("selected_count") or 0) == 0]

    def mean_int(key: str) -> float | None:
        values = [int(row[key]) for row in daily_rows if row.get(key) is not None]
        if not values:
            return None
        return float(sum(values) / len(values))

    overall = {
        "month": str(month),
        "source": "paper_trading.trade_brief+session_summary",
        "day_count": len(daily_rows),
        "days_with_picks": int(sum(1 for row in daily_rows if int(row.get("selected_count") or 0) > 0)),
        "zero_pick_days": list(zero_pick_days),
        "mean_selected_count": mean_int("selected_count"),
        "mean_near_miss_count": mean_int("near_miss_count"),
        "mean_opportunity_pool_count": mean_int("opportunity_pool_count"),
        "mean_p2_execution_blocked_count": mean_int("p2_execution_blocked_count"),
        "mean_short_trade_selected_count": mean_int("short_trade_selected_count"),
        "mean_short_trade_near_miss_count": mean_int("short_trade_near_miss_count"),
        "mean_short_trade_blocked_count": mean_int("short_trade_blocked_count"),
        "mean_short_trade_rejected_count": mean_int("short_trade_rejected_count"),
    }

    return {
        "month": str(month),
        "reports_dir": str(root),
        "overall": overall,
        "daily": daily_rows,
        "selected_runs": [selected_runs[key] for key in sorted(selected_runs.keys())],
    }


def render_btst_monthly_execution_health_markdown(analysis: dict[str, Any]) -> str:
    overall = dict(analysis.get("overall") or {})
    lines: list[str] = []
    month = str(analysis.get("month") or "")

    def fmt(v: Any) -> str:
        if v is None:
            return "n/a"
        if isinstance(v, float):
            return f"{v:.2f}"
        return str(v)

    lines.append(f"# BTST Monthly Execution Health {month}")
    lines.append("")
    lines.append("## Overall")
    lines.append(f"- source: {overall.get('source')}")
    lines.append(f"- day_count: {overall.get('day_count')}, days_with_picks: {overall.get('days_with_picks')}")
    lines.append(f"- mean_selected_count: {fmt(overall.get('mean_selected_count'))}")
    lines.append(f"- mean_near_miss_count: {fmt(overall.get('mean_near_miss_count'))}")
    lines.append(f"- mean_p2_execution_blocked_count: {fmt(overall.get('mean_p2_execution_blocked_count'))}")

    zero_pick = list(overall.get("zero_pick_days") or [])
    if zero_pick:
        lines.append("")
        lines.append(f"- zero_pick_days: {len(zero_pick)}")
        lines.append("  - " + ", ".join(zero_pick[:20]))

    lines.append("")
    lines.append("## Daily breakdown")
    lines.append("| trade_date | selected | near_miss | opp_pool | p2_blocked | short_sel | short_nm | short_blocked | short_rej |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|")

    for row in list(analysis.get("daily") or []):
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("trade_date") or ""),
                    str(row.get("selected_count") or 0),
                    str(row.get("near_miss_count") or 0),
                    str(row.get("opportunity_pool_count") or 0),
                    fmt(row.get("p2_execution_blocked_count")),
                    fmt(row.get("short_trade_selected_count")),
                    fmt(row.get("short_trade_near_miss_count")),
                    fmt(row.get("short_trade_blocked_count")),
                    fmt(row.get("short_trade_rejected_count")),
                ]
            )
            + " |"
        )

    lines.append("")
    lines.append("## Notes")
    lines.append("- This report explains WHY execution produced few/no formal-selected entries by extracting gate/blocked counters.")

    return "\n".join(lines) + "\n"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze BTST monthly execution selection health")
    parser.add_argument("--month", required=True, help="YYYYMM, e.g. 202605")
    parser.add_argument("--reports-dir", default="data/reports")
    parser.add_argument("--output-json", default=None)
    parser.add_argument("--output-md", default=None)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    analysis = analyze_btst_monthly_execution_health(month=args.month, reports_dir=args.reports_dir)
    markdown = render_btst_monthly_execution_health_markdown(analysis)

    if args.output_json:
        _write_json(args.output_json, analysis)
    if args.output_md:
        _write_text(args.output_md, markdown)

    if not args.output_md:
        print(markdown)


if __name__ == "__main__":
    main()
