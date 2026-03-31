from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any


REPORTS_DIR = Path("data/reports")
DEFAULT_REPORTS_ROOT = REPORTS_DIR
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_replay_cohort_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_replay_cohort_latest.md"


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _safe_load_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return {}
    return json.loads(resolved.read_text(encoding="utf-8"))


def _normalize_trade_date(value: Any) -> str | None:
    if value is None:
        return None
    digits = "".join(ch for ch in str(value).strip() if ch.isdigit())
    if len(digits) != 8:
        return None
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"


def _looks_like_report_dir(path: Path) -> bool:
    return path.is_dir() and (path / "session_summary.json").exists() and (path / "selection_artifacts").exists()


def _normalize_pct(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    return round(float(value), 2)


def _mean_pct(values: list[float | None]) -> float | None:
    filtered = [float(value) for value in values if isinstance(value, (int, float))]
    if not filtered:
        return None
    return round(mean(filtered), 2)


def _extract_total_return_pct(summary: dict[str, Any]) -> float | None:
    values = [item.get("Portfolio Value") for item in list(summary.get("portfolio_values") or []) if isinstance(item, dict)]
    numeric_values = [float(value) for value in values if isinstance(value, (int, float))]
    if len(numeric_values) < 2 or numeric_values[0] == 0:
        return None
    return round(((numeric_values[-1] / numeric_values[0]) - 1.0) * 100.0, 2)


def _extract_btst_brief_summary(summary: dict[str, Any]) -> dict[str, Any]:
    followup = dict(summary.get("btst_followup") or {})
    artifacts = dict(summary.get("artifacts") or {})
    brief_path = followup.get("brief_json") or artifacts.get("btst_next_day_trade_brief_json")
    brief = _safe_load_json(brief_path)
    return dict(brief.get("summary") or {})


def _extract_report_row(report_dir: Path) -> dict[str, Any] | None:
    if not _looks_like_report_dir(report_dir):
        return None
    summary = _safe_load_json(report_dir / "session_summary.json")
    if not summary:
        return None

    plan_generation = dict(summary.get("plan_generation") or {})
    selection_target = str(plan_generation.get("selection_target") or summary.get("selection_target") or "")
    mode = str(plan_generation.get("mode") or "")
    has_btst_followup = bool(summary.get("btst_followup"))
    if not has_btst_followup and selection_target not in {"short_trade_only", "dual_target", "research_only"}:
        return None

    brief_summary = _extract_btst_brief_summary(summary)
    followup = dict(summary.get("btst_followup") or {})
    artifacts = dict(summary.get("artifacts") or {})
    priority_board_json_path = followup.get("priority_board_json") or artifacts.get("btst_next_day_priority_board_json")

    trade_date = _normalize_trade_date(followup.get("trade_date") or summary.get("end_date"))
    next_trade_date = _normalize_trade_date(followup.get("next_trade_date"))

    return {
        "report_dir": str(report_dir.resolve()),
        "report_dir_name": report_dir.name,
        "selection_target": selection_target or None,
        "plan_mode": mode or None,
        "is_frozen_replay": "frozen" in mode,
        "has_btst_followup": has_btst_followup,
        "start_date": summary.get("start_date"),
        "end_date": summary.get("end_date"),
        "trade_date": trade_date,
        "next_trade_date": next_trade_date,
        "trade_day_count": int((summary.get("daily_event_stats") or {}).get("day_count") or 0),
        "executed_trade_days": int((summary.get("daily_event_stats") or {}).get("executed_trade_days") or 0),
        "total_executed_orders": int((summary.get("daily_event_stats") or {}).get("total_executed_orders") or 0),
        "total_return_pct": _extract_total_return_pct(summary),
        "sharpe_ratio": summary.get("performance_metrics", {}).get("sharpe_ratio"),
        "max_drawdown_pct": _normalize_pct(summary.get("performance_metrics", {}).get("max_drawdown")),
        "selected_count": int(brief_summary.get("short_trade_selected_count") or 0),
        "near_miss_count": int(brief_summary.get("short_trade_near_miss_count") or 0),
        "blocked_count": int(brief_summary.get("short_trade_blocked_count") or 0),
        "rejected_count": int(brief_summary.get("short_trade_rejected_count") or 0),
        "opportunity_pool_count": int(brief_summary.get("short_trade_opportunity_pool_count") or 0),
        "research_upside_radar_count": int(brief_summary.get("research_upside_radar_count") or 0),
        "priority_board_available": bool(priority_board_json_path),
    }


def _build_cohort_summary(rows: list[dict[str, Any]], *, label: str) -> dict[str, Any]:
    live_rows = [row for row in rows if not row.get("is_frozen_replay")]
    frozen_rows = [row for row in rows if row.get("is_frozen_replay")]
    actionable_rows = [
        row
        for row in rows
        if int(row.get("selected_count") or 0) > 0 or int(row.get("near_miss_count") or 0) > 0 or int(row.get("opportunity_pool_count") or 0) > 0
    ]
    latest_row = rows[0] if rows else None
    return {
        "label": label,
        "report_count": len(rows),
        "live_report_count": len(live_rows),
        "frozen_report_count": len(frozen_rows),
        "actionable_report_count": len(actionable_rows),
        "avg_total_return_pct": _mean_pct([row.get("total_return_pct") for row in rows]),
        "avg_max_drawdown_pct": _mean_pct([row.get("max_drawdown_pct") for row in rows]),
        "avg_executed_trade_days": _mean_pct([row.get("executed_trade_days") for row in rows]),
        "avg_total_executed_orders": _mean_pct([row.get("total_executed_orders") for row in rows]),
        "latest_report_dir": latest_row.get("report_dir_name") if latest_row else None,
        "latest_trade_date": latest_row.get("trade_date") if latest_row else None,
    }


def analyze_btst_replay_cohort(reports_root: str | Path) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    rows = [
        row
        for row in (_extract_report_row(path) for path in resolved_reports_root.iterdir())
        if row is not None
    ]
    rows.sort(
        key=lambda row: (
            row.get("selection_target") == "short_trade_only",
            row.get("trade_date") or row.get("end_date") or "",
            row.get("report_dir_name") or "",
        ),
        reverse=True,
    )

    short_trade_rows = [row for row in rows if row.get("selection_target") == "short_trade_only"]
    frozen_rows = [row for row in rows if row.get("is_frozen_replay")]
    dual_target_rows = [row for row in rows if row.get("selection_target") == "dual_target"]

    latest_short_trade_row = short_trade_rows[0] if short_trade_rows else None
    top_return_rows = sorted(
        [row for row in rows if isinstance(row.get("total_return_pct"), (int, float))],
        key=lambda row: float(row.get("total_return_pct") or 0.0),
        reverse=True,
    )[:5]

    recommendation = "当前 BTST replay cohort 仍缺足够长的短线闭环样本，应优先把它当作 coverage / watchlist 质量监控，而不是过度解读收益率。"
    if short_trade_rows:
        actionable_short_trade_count = sum(
            1
            for row in short_trade_rows
            if int(row.get("selected_count") or 0) > 0 or int(row.get("near_miss_count") or 0) > 0 or int(row.get("opportunity_pool_count") or 0) > 0
        )
        if actionable_short_trade_count > 0:
            recommendation = (
                "short_trade_only cohort 已出现可操作观察层样本，但当前成交天数和闭环收益样本仍偏少；应继续把它作为 next-day priority board 的历史支撑，而不是提前当成稳定收益证据。"
            )

    return {
        "reports_root": str(resolved_reports_root),
        "report_count": len(rows),
        "selection_target_counts": {
            "short_trade_only": len(short_trade_rows),
            "dual_target": len(dual_target_rows),
            "other": len(rows) - len(short_trade_rows) - len(dual_target_rows),
        },
        "cohort_summaries": [
            _build_cohort_summary(rows, label="all_btst_capable_reports"),
            _build_cohort_summary(short_trade_rows, label="short_trade_only"),
            _build_cohort_summary(frozen_rows, label="frozen_replay"),
            _build_cohort_summary(dual_target_rows, label="dual_target"),
        ],
        "latest_short_trade_row": latest_short_trade_row,
        "top_return_rows": top_return_rows,
        "report_rows": rows,
        "recommendation": recommendation,
    }


def render_btst_replay_cohort_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Replay Cohort")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- report_count: {analysis.get('report_count')}")
    lines.append(f"- selection_target_counts: {analysis.get('selection_target_counts')}")
    lines.append(f"- recommendation: {analysis.get('recommendation')}")
    lines.append("")

    lines.append("## Cohort Summaries")
    for summary in list(analysis.get("cohort_summaries") or []):
        lines.append(
            f"- label={summary.get('label')} report_count={summary.get('report_count')} live_report_count={summary.get('live_report_count')} frozen_report_count={summary.get('frozen_report_count')} actionable_report_count={summary.get('actionable_report_count')} avg_total_return_pct={summary.get('avg_total_return_pct')} avg_max_drawdown_pct={summary.get('avg_max_drawdown_pct')} latest_report_dir={summary.get('latest_report_dir')}"
        )
    lines.append("")

    lines.append("## Latest Short-Trade Report")
    latest_short_trade = dict(analysis.get("latest_short_trade_row") or {})
    if not latest_short_trade:
        lines.append("- none")
    else:
        for key in (
            "report_dir_name",
            "plan_mode",
            "trade_date",
            "next_trade_date",
            "selected_count",
            "near_miss_count",
            "opportunity_pool_count",
            "total_return_pct",
            "executed_trade_days",
            "total_executed_orders",
        ):
            lines.append(f"- {key}: {latest_short_trade.get(key)}")
    lines.append("")

    lines.append("## Top Return Rows")
    for row in list(analysis.get("top_return_rows") or []):
        lines.append(
            f"- {row.get('report_dir_name')}: selection_target={row.get('selection_target')} mode={row.get('plan_mode')} total_return_pct={row.get('total_return_pct')} selected_count={row.get('selected_count')} near_miss_count={row.get('near_miss_count')} opportunity_pool_count={row.get('opportunity_pool_count')}"
        )
    if not list(analysis.get("top_return_rows") or []):
        lines.append("- none")
    lines.append("")

    lines.append("## Recent Report Rows")
    for row in list(analysis.get("report_rows") or [])[:12]:
        lines.append(
            f"- {row.get('report_dir_name')}: selection_target={row.get('selection_target')} mode={row.get('plan_mode')} trade_date={row.get('trade_date')} total_return_pct={row.get('total_return_pct')} selected_count={row.get('selected_count')} near_miss_count={row.get('near_miss_count')} opportunity_pool_count={row.get('opportunity_pool_count')}"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a replay cohort summary across BTST-capable live and frozen paper-trading reports.")
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_replay_cohort(args.reports_root)
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_replay_cohort_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()