from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any

from scripts.analyze_btst_micro_window_regression import (
    analyze_btst_micro_window_report,
)
from scripts.btst_analysis_utils import build_day_breakdown as _build_day_breakdown
from scripts.btst_analysis_utils import build_surface_summary as _build_surface_summary
from scripts.btst_analysis_utils import normalize_trade_date as _normalize_trade_date

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


def _build_weekly_recommendation(
    *,
    missing_trade_dates: list[str],
    tradeable_summary: dict[str, Any],
    selected_report_count: int,
    selected_shadow_scenarios: list[dict[str, Any]],
) -> str:
    if missing_trade_dates:
        return f"周验证仍有缺口：缺少 {missing_trade_dates} 的完整 short_trade_only 日报目录，应先补齐产物再做 shadow-only 周度目标复盘。"
    if int(tradeable_summary.get("closed_cycle_count") or 0) == 0:
        return "当前周窗口尚未形成 closed-cycle tradeable 样本，先把周内日报闭环补齐，再继续 shadow-only payoff 复盘。"
    if selected_shadow_scenarios:
        top_scenario = dict(selected_shadow_scenarios[0] or {})
        surface_summary = dict(top_scenario.get("surface_summary") or {})
        return f"本周已形成 {selected_report_count} 个可验证日报；优先继续 shadow-only 验证剔除 {list(top_scenario.get('excluded_candidate_sources') or [])} 的正式层情景，" f"因为该情景下 selected 的 5D/+15% 命中率可提升到 `{surface_summary.get('max_future_high_return_2_5d_hit_rate_at_15pct')}`。"
    if float(tradeable_summary.get("next_close_positive_rate") or 0.0) >= 0.6 and float(tradeable_summary.get("next_close_payoff_ratio") or 0.0) >= 1.5:
        return f"本周已形成 {selected_report_count} 个可验证日报，但当前结论仍只用于 shadow-only 周评估，不直接推进默认参数收紧。"
    return f"本周已形成 {selected_report_count} 个可验证日报，但 tradeable surface 仍未达到强势阈值；继续做 shadow-only 参数与候选压缩验证，不扩大候选池。"


def _build_candidate_source_breakdown(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        candidate_source = str(row.get("candidate_source") or "unknown")
        grouped.setdefault(candidate_source, []).append(row)

    breakdown: list[dict[str, Any]] = []
    for candidate_source, source_rows in grouped.items():
        runner_rows = [row for row in source_rows if row.get("max_future_high_return_2_5d") is not None]
        runner_hits = sum(1 for row in runner_rows if bool(row.get("future_high_hit_15pct_2_5d")))
        runner_hit_rate = None if not runner_rows else round(runner_hits / len(runner_rows), 4)
        max_future_high_returns = [float(row["max_future_high_return_2_5d"]) for row in runner_rows if row.get("max_future_high_return_2_5d") is not None]
        t_plus_2_close_returns = [float(row["t_plus_2_close_return"]) for row in source_rows if row.get("t_plus_2_close_return") is not None]
        breakdown.append(
            {
                "candidate_source": candidate_source,
                "count": len(source_rows),
                "closed_cycle_count": len(t_plus_2_close_returns),
                "max_future_high_return_2_5d_hit_rate_at_15pct": runner_hit_rate,
                "max_future_high_return_2_5d_return_mean": None if not max_future_high_returns else round(mean(max_future_high_returns), 4),
                "t_plus_2_close_positive_rate": None if not t_plus_2_close_returns else round(sum(1 for value in t_plus_2_close_returns if value > 0.0) / len(t_plus_2_close_returns), 4),
            }
        )

    breakdown.sort(
        key=lambda row: (
            float(row.get("max_future_high_return_2_5d_hit_rate_at_15pct") or -1.0),
            float(row.get("max_future_high_return_2_5d_return_mean") or -999.0),
            int(row.get("count") or 0),
            str(row.get("candidate_source") or ""),
        ),
        reverse=True,
    )
    return breakdown


def _build_runner_false_negative_summary(rows: list[dict[str, Any]], *, next_high_hit_threshold: float) -> dict[str, Any]:
    runner_false_negative_rows = [row for row in rows if bool(row.get("future_high_hit_15pct_2_5d"))]
    candidate_source_counts = Counter(str(row.get("candidate_source") or "unknown") for row in runner_false_negative_rows)
    return {
        "count": len(runner_false_negative_rows),
        "candidate_source_counts": dict(candidate_source_counts),
        "surface_metrics": _build_surface_summary(runner_false_negative_rows, next_high_hit_threshold=next_high_hit_threshold),
        "top_rows": runner_false_negative_rows[:8],
    }


def _build_selected_shadow_scenarios(selected_rows: list[dict[str, Any]], *, next_high_hit_threshold: float) -> tuple[list[str], list[dict[str, Any]]]:
    selected_candidate_source_breakdown = _build_candidate_source_breakdown(selected_rows)
    payoff_drag_candidate_sources = sorted(str(row.get("candidate_source") or "") for row in selected_candidate_source_breakdown if int(row.get("count") or 0) >= 2 and float(row.get("max_future_high_return_2_5d_hit_rate_at_15pct") or 0.0) <= 0.0)
    scenarios: list[dict[str, Any]] = []
    if payoff_drag_candidate_sources:
        remaining_rows = [row for row in selected_rows if str(row.get("candidate_source") or "") not in set(payoff_drag_candidate_sources)]
        removed_rows = [row for row in selected_rows if str(row.get("candidate_source") or "") in set(payoff_drag_candidate_sources)]
        scenarios.append(
            {
                "scenario_id": "exclude_payoff_drag_sources",
                "excluded_candidate_sources": payoff_drag_candidate_sources,
                "removed_count": len(removed_rows),
                "remaining_count": len(remaining_rows),
                "surface_summary": _build_surface_summary(remaining_rows, next_high_hit_threshold=next_high_hit_threshold),
                "removed_surface_summary": _build_surface_summary(removed_rows, next_high_hit_threshold=next_high_hit_threshold),
            }
        )
    return payoff_drag_candidate_sources, scenarios


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
    blocked_rejected_rows = [row for row in all_rows if row.get("decision") in {"blocked", "rejected"}]
    runner_false_negative_summary = _build_runner_false_negative_summary(
        blocked_rejected_rows,
        next_high_hit_threshold=next_high_hit_threshold,
    )
    selected_candidate_source_breakdown = _build_candidate_source_breakdown(selected_rows)
    selected_payoff_drag_candidate_sources, selected_shadow_scenarios = _build_selected_shadow_scenarios(
        selected_rows,
        next_high_hit_threshold=next_high_hit_threshold,
    )

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
        "blocked_rejected": _build_surface_summary(blocked_rejected_rows, next_high_hit_threshold=next_high_hit_threshold),
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
        "runner_false_negative_summary": runner_false_negative_summary,
        "selected_candidate_source_breakdown": selected_candidate_source_breakdown,
        "selected_payoff_drag_candidate_sources": selected_payoff_drag_candidate_sources,
        "selected_shadow_scenarios": selected_shadow_scenarios,
        "weekly_day_breakdown": _build_day_breakdown(all_rows),
        "next_high_hit_threshold": round(float(next_high_hit_threshold), 4),
        "recommendation": _build_weekly_recommendation(
            missing_trade_dates=missing_trade_dates,
            tradeable_summary=weekly_surface_summaries["tradeable"],
            selected_report_count=len(selected_reports),
            selected_shadow_scenarios=selected_shadow_scenarios,
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
    for label in ("all", "tradeable", "selected", "near_miss", "blocked_rejected"):
        lines.append(f"- {label}: {analysis.get('weekly_surface_summaries', {}).get(label)}")
    lines.append("")
    lines.append("## 5D / +15% Objective Focus")
    lines.append(f"- selected_5d_hit_rate_15pct: {dict(analysis.get('weekly_surface_summaries', {}).get('selected') or {}).get('max_future_high_return_2_5d_hit_rate_at_15pct')}")
    lines.append(f"- near_miss_5d_hit_rate_15pct: {dict(analysis.get('weekly_surface_summaries', {}).get('near_miss') or {}).get('max_future_high_return_2_5d_hit_rate_at_15pct')}")
    lines.append(f"- blocked_rejected_5d_hit_rate_15pct: {dict(analysis.get('weekly_surface_summaries', {}).get('blocked_rejected') or {}).get('max_future_high_return_2_5d_hit_rate_at_15pct')}")
    lines.append(f"- runner_false_negative_summary: {analysis.get('runner_false_negative_summary')}")
    lines.append("- rollout_status: shadow-only review; not a default upgrade.")
    lines.append("")
    lines.append("## Selected Candidate Source Breakdown")
    for row in list(analysis.get("selected_candidate_source_breakdown") or []):
        lines.append(f"- {row.get('candidate_source')}: {row}")
    if not list(analysis.get("selected_candidate_source_breakdown") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Selected Shadow Scenarios")
    if list(analysis.get("selected_shadow_scenarios") or []):
        lines.append(f"- payoff_drag_candidate_sources: {analysis.get('selected_payoff_drag_candidate_sources')}")
        for row in list(analysis.get("selected_shadow_scenarios") or []):
            lines.append(f"- {row.get('scenario_id')}: excluded_candidate_sources={row.get('excluded_candidate_sources')} removed_count={row.get('removed_count')} remaining_count={row.get('remaining_count')} surface_summary={row.get('surface_summary')}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Daily Summaries")
    for row in list(analysis.get("daily_summaries") or []):
        lines.append(f"- trade_date={row.get('trade_date')} report_dir_name={row.get('report_dir_name')} decision_counts={row.get('decision_counts')} cycle_status_counts={row.get('cycle_status_counts')} tradeable_surface={row.get('tradeable_surface')}")
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
