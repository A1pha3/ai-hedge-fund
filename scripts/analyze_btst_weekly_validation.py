from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from scripts.analyze_btst_micro_window_regression import analyze_btst_micro_window_report
from scripts.btst_analysis_utils import (
    build_day_breakdown as _build_day_breakdown,
    build_surface_summary as _build_surface_summary,
    normalize_trade_date as _normalize_trade_date,
)

REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_weekly_validation_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_weekly_validation_latest.md"


def _coerce_trade_date(value: str | None) -> str:
    normalized = _normalize_trade_date(value)
    if not normalized:
        raise ValueError(f"Invalid trade date: {value}")
    return normalized


def _iter_trade_dates(start_date: str, end_date: str) -> list[str]:
    start = datetime.strptime(_coerce_trade_date(start_date), "%Y-%m-%d")
    end = datetime.strptime(_coerce_trade_date(end_date), "%Y-%m-%d")
    if end < start:
        raise ValueError("end_date must be on or after start_date")
    dates: list[str] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return dates


def _load_snapshot_trade_dates(report_dir: Path) -> list[str]:
    trade_dates: list[str] = []
    for snapshot_path in sorted(report_dir.rglob("selection_snapshot.json")):
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        trade_date = _normalize_trade_date(payload.get("trade_date"))
        if trade_date:
            trade_dates.append(trade_date)
    return sorted(dict.fromkeys(trade_dates))


def _discover_complete_short_trade_reports(reports_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for report_dir in sorted(path for path in reports_root.iterdir() if path.is_dir()):
        if "short_trade_only" not in report_dir.name:
            continue
        if not (report_dir / "session_summary.json").exists():
            continue
        trade_dates = _load_snapshot_trade_dates(report_dir)
        if not trade_dates:
            continue
        rows.append(
            {
                "report_dir": str(report_dir.resolve()),
                "report_dir_name": report_dir.name,
                "trade_dates": trade_dates,
                "has_session_summary": True,
                "report_mtime_ns": int(report_dir.stat().st_mtime_ns),
                "snapshot_count": len(trade_dates),
            }
        )
    return rows


def _select_reports_by_trade_date(reports_root: Path, trade_dates: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    candidates = _discover_complete_short_trade_reports(reports_root)
    by_trade_date: dict[str, list[dict[str, Any]]] = {}
    for row in candidates:
        for trade_date in row["trade_dates"]:
            by_trade_date.setdefault(trade_date, []).append(row)

    selected: list[dict[str, Any]] = []
    missing: list[str] = []
    for trade_date in trade_dates:
        rows = list(by_trade_date.get(trade_date) or [])
        if not rows:
            missing.append(trade_date)
            continue
        best = max(
            rows,
            key=lambda row: (
                1 if row.get("has_session_summary") else 0,
                int(row.get("report_mtime_ns") or 0),
                int(row.get("snapshot_count") or 0),
                str(row.get("report_dir_name") or ""),
            ),
        )
        selected.append(
            {
                "trade_date": trade_date,
                "report_dir": best["report_dir"],
                "report_dir_name": best["report_dir_name"],
            }
        )
    return selected, missing


def _build_weekly_recommendation(*, missing_trade_dates: list[str], tradeable_summary: dict[str, Any], selected_report_count: int) -> str:
    if missing_trade_dates:
        return f"周验证仍有缺口：缺少 {missing_trade_dates} 的完整 short_trade_only 日报目录，应先补齐产物再解读本周胜率。"
    if int(tradeable_summary.get("closed_cycle_count") or 0) == 0:
        return "当前周窗口尚未形成 closed-cycle tradeable 样本，先把周内日报闭环继续补齐。"
    if float(tradeable_summary.get("next_close_positive_rate") or 0.0) >= 0.6 and float(tradeable_summary.get("next_close_payoff_ratio") or 0.0) >= 1.5:
        return f"本周已形成 {selected_report_count} 个可验证日报，tradeable surface 质量偏强，可据此继续推进默认参数收紧。"
    return f"本周已形成 {selected_report_count} 个可验证日报，但 tradeable surface 仍未达到强势阈值，先做参数与候选压缩验证，不要扩大候选池。"


def analyze_btst_weekly_validation(
    reports_root: str | Path,
    *,
    start_date: str,
    end_date: str,
    next_high_hit_threshold: float = 0.02,
) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    trade_dates = _iter_trade_dates(start_date, end_date)
    selected_reports, missing_trade_dates = _select_reports_by_trade_date(resolved_reports_root, trade_dates)

    daily_analyses = [
        analyze_btst_micro_window_report(
            row["report_dir"],
            label=row["trade_date"],
            next_high_hit_threshold=next_high_hit_threshold,
            trade_date_filter=row["trade_date"],
        )
        for row in selected_reports
    ]

    all_rows = [row for analysis in daily_analyses for row in list(analysis.get("rows") or [])]
    tradeable_rows = [row for row in all_rows if row.get("decision") in {"selected", "near_miss"}]
    selected_rows = [row for row in all_rows if row.get("decision") == "selected"]
    near_miss_rows = [row for row in all_rows if row.get("decision") == "near_miss"]

    daily_summaries = []
    for selected_report, analysis in zip(selected_reports, daily_analyses):
        daily_summaries.append(
            {
                "trade_date": selected_report["trade_date"],
                "report_dir": selected_report["report_dir"],
                "report_dir_name": selected_report["report_dir_name"],
                "decision_counts": analysis.get("decision_counts"),
                "cycle_status_counts": analysis.get("cycle_status_counts"),
                "tradeable_surface": dict((analysis.get("surface_summaries") or {}).get("tradeable") or {}),
                "selected_surface": dict((analysis.get("surface_summaries") or {}).get("selected") or {}),
                "near_miss_surface": dict((analysis.get("surface_summaries") or {}).get("near_miss") or {}),
                "recommendation": analysis.get("recommendation"),
            }
        )

    weekly_surface_summaries = {
        "all": _build_surface_summary(all_rows, next_high_hit_threshold=next_high_hit_threshold),
        "tradeable": _build_surface_summary(tradeable_rows, next_high_hit_threshold=next_high_hit_threshold),
        "selected": _build_surface_summary(selected_rows, next_high_hit_threshold=next_high_hit_threshold),
        "near_miss": _build_surface_summary(near_miss_rows, next_high_hit_threshold=next_high_hit_threshold),
    }

    return {
        "reports_root": str(resolved_reports_root),
        "start_date": _coerce_trade_date(start_date),
        "end_date": _coerce_trade_date(end_date),
        "trade_dates": trade_dates,
        "missing_trade_dates": missing_trade_dates,
        "selected_report_count": len(selected_reports),
        "selected_reports": selected_reports,
        "daily_summaries": daily_summaries,
        "weekly_surface_summaries": weekly_surface_summaries,
        "weekly_day_breakdown": _build_day_breakdown(all_rows),
        "next_high_hit_threshold": round(float(next_high_hit_threshold), 4),
        "recommendation": _build_weekly_recommendation(
            missing_trade_dates=missing_trade_dates,
            tradeable_summary=weekly_surface_summaries["tradeable"],
            selected_report_count=len(selected_reports),
        ),
    }


def render_btst_weekly_validation_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Weekly Validation")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- reports_root: {analysis.get('reports_root')}")
    lines.append(f"- trade_dates: {analysis.get('trade_dates')}")
    lines.append(f"- missing_trade_dates: {analysis.get('missing_trade_dates')}")
    lines.append(f"- selected_report_count: {analysis.get('selected_report_count')}")
    lines.append(f"- recommendation: {analysis.get('recommendation')}")
    lines.append("")
    lines.append("## Weekly Surface Summary")
    for label in ("all", "tradeable", "selected", "near_miss"):
        lines.append(f"- {label}: {analysis.get('weekly_surface_summaries', {}).get(label)}")
    lines.append("")
    lines.append("## Daily Summaries")
    for row in list(analysis.get("daily_summaries") or []):
        lines.append(
            f"- trade_date={row.get('trade_date')} report_dir_name={row.get('report_dir_name')} decision_counts={row.get('decision_counts')} cycle_status_counts={row.get('cycle_status_counts')} tradeable_surface={row.get('tradeable_surface')}"
        )
    if not list(analysis.get("daily_summaries") or []):
        lines.append("- none")
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a BTST week by selecting the latest complete short_trade_only report per trade date and summarizing realized next-day outcomes.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR))
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--next-high-hit-threshold", type=float, default=0.02)
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_weekly_validation(
        args.reports_root,
        start_date=args.start_date,
        end_date=args.end_date,
        next_high_hit_threshold=args.next_high_hit_threshold,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_weekly_validation_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
