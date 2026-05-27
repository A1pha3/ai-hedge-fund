from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.generate_btst_doc_bundle import (
    _build_intersection_summary,
    _discover_report_dir,
    _load_early_runner_context,
    _normalize_signal_date,
    _read_json,
    _resolve_opportunity_rows,
    _resolve_selected_rows,
    _resolve_watch_rows,
    generate_btst_doc_bundle,
)

REPORTS_DIR = Path("data/reports")
OUTPUTS_DIR = Path("outputs")


def _safe_ratio(numerator: int, denominator: int) -> float:
    """Return one safe ratio for summary metrics."""
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _discover_signal_dates(reports_root: Path, month_prefix: str) -> list[str]:
    """Discover unique signal dates for one month from short-trade session summaries."""
    session_paths = sorted(reports_root.glob(f"paper_trading_{month_prefix}*_short_trade_only_*_plan/session_summary.json"))
    signal_dates: set[str] = set()
    for session_path in session_paths:
        payload = json.loads(session_path.read_text(encoding="utf-8"))
        trade_date = str(payload.get("trade_date") or payload.get("start_date") or payload.get("end_date") or "").replace("-", "")
        if len(trade_date) == 8 and trade_date.isdigit():
            signal_dates.add(trade_date)
    return sorted(signal_dates)


def _build_row(reports_root: Path, signal_date: str, bundle_root: Path) -> dict[str, Any]:
    """Replay one signal date with the scheme-A bundle and collect validation metrics."""
    signal_date_compact, signal_date_iso = _normalize_signal_date(signal_date)
    output_dir = bundle_root / signal_date_compact
    bundle_result = generate_btst_doc_bundle(
        signal_date_compact,
        reports_root=reports_root,
        output_dir=output_dir,
        refresh_early_runner=False,
    )
    report_dir = _discover_report_dir(reports_root, signal_date_iso, None)
    session_summary = _read_json(report_dir / "session_summary.json")
    followup_paths = dict(session_summary.get("btst_followup") or {})
    brief = _read_json(Path(followup_paths["brief_json"]))
    priority_board = _read_json(Path(followup_paths["priority_board_json"])) if followup_paths.get("priority_board_json") else {}
    early_runner = _load_early_runner_context(reports_root, signal_date_iso, refresh=False)
    formal_rows = [
        *_resolve_selected_rows(brief, priority_board),
        *_resolve_watch_rows(brief, priority_board),
        *_resolve_opportunity_rows(brief, priority_board),
    ]
    intersection = _build_intersection_summary(early_runner, formal_rows)
    return {
        "signal_date": signal_date_compact,
        "next_trade_date": brief.get("next_trade_date"),
        "report_dir": report_dir.name,
        "early_runner_status": bundle_result.get("early_runner_status"),
        "early_runner_latest_trade_date": bundle_result.get("early_runner_latest_trade_date"),
        "formal_count": len(formal_rows),
        "intersection_count": int(bundle_result.get("early_runner_intersection_count") or len(list(intersection.get("overlap_rows") or []))),
        "intersection_tickers": [str(item.get("ticker") or "").strip() for item in list(intersection.get("overlap_rows") or [])],
        "only_early_runner_count": int(bundle_result.get("early_runner_only_count") or len(list(intersection.get("only_early_runner_rows") or []))),
        "only_early_runner_tickers": [str(item.get("ticker") or "").strip() for item in list(intersection.get("only_early_runner_rows") or [])],
        "second_entry_count": int(bundle_result.get("early_runner_second_entry_count") or len(list(intersection.get("second_entry_rows") or []))),
        "second_entry_tickers": [str(item.get("ticker") or "").strip() for item in list(intersection.get("second_entry_rows") or [])],
        "written_files": list(bundle_result.get("written_files") or []),
    }


def _count_recent_exact_streak(rows: list[dict[str, Any]]) -> int:
    """Count the exact-status streak from the latest row backwards."""
    streak = 0
    for row in reversed(rows):
        if str(row.get("early_runner_status") or "") == "exact":
            streak += 1
        else:
            break
    return streak


def _build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate monthly validation metrics from per-day rows."""
    total_runs = len(rows)
    exact_count = sum(1 for row in rows if row.get("early_runner_status") == "exact")
    stale_fallback_count = sum(1 for row in rows if row.get("early_runner_status") == "stale_fallback")
    unavailable_count = sum(1 for row in rows if row.get("early_runner_status") == "unavailable")
    intersection_positive_count = sum(1 for row in rows if int(row.get("intersection_count") or 0) > 0)
    only_early_runner_positive_count = sum(1 for row in rows if int(row.get("only_early_runner_count") or 0) > 0)
    second_entry_positive_count = sum(1 for row in rows if int(row.get("second_entry_count") or 0) > 0)
    total_intersection_count = sum(int(row.get("intersection_count") or 0) for row in rows)
    total_only_early_runner_count = sum(int(row.get("only_early_runner_count") or 0) for row in rows)
    total_second_entry_count = sum(int(row.get("second_entry_count") or 0) for row in rows)
    recent_exact_streak = _count_recent_exact_streak(rows)
    meets_recent_exact_gate = recent_exact_streak >= 3
    meets_minimum_directory_switch_gate = meets_recent_exact_gate and intersection_positive_count >= 2 and unavailable_count == 0
    return {
        "total_runs": total_runs,
        "exact_count": exact_count,
        "stale_fallback_count": stale_fallback_count,
        "unavailable_count": unavailable_count,
        "exact_rate": _safe_ratio(exact_count, total_runs),
        "intersection_positive_count": intersection_positive_count,
        "intersection_positive_rate": _safe_ratio(intersection_positive_count, total_runs),
        "only_early_runner_positive_count": only_early_runner_positive_count,
        "only_early_runner_positive_rate": _safe_ratio(only_early_runner_positive_count, total_runs),
        "second_entry_positive_count": second_entry_positive_count,
        "second_entry_positive_rate": _safe_ratio(second_entry_positive_count, total_runs),
        "total_intersection_count": total_intersection_count,
        "total_only_early_runner_count": total_only_early_runner_count,
        "total_second_entry_count": total_second_entry_count,
        "avg_intersection_count": _safe_ratio(total_intersection_count, total_runs),
        "avg_only_early_runner_count": _safe_ratio(total_only_early_runner_count, total_runs),
        "avg_second_entry_count": _safe_ratio(total_second_entry_count, total_runs),
        "recent_exact_streak": recent_exact_streak,
        "meets_recent_exact_gate": meets_recent_exact_gate,
        "meets_minimum_directory_switch_gate": meets_minimum_directory_switch_gate,
    }


def _render_markdown(month_prefix: str, summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    """Render a compact strategy health report in Markdown."""
    lines = [
        f"# {month_prefix} Early Runner 历史回放验证",
        "",
        f"- 样本数量：`{summary['total_runs']}`",
        f"- exact：`{summary['exact_count']}`",
        f"- stale_fallback：`{summary['stale_fallback_count']}`",
        f"- unavailable：`{summary['unavailable_count']}`",
        f"- exact 占比：`{summary['exact_rate']:.2%}`",
        f"- 出现交集票高亮的样本数：`{summary['intersection_positive_count']}`",
        f"- 交集票出现占比：`{summary['intersection_positive_rate']:.2%}`",
        f"- 出现 only early-runner 补充票的样本数：`{summary['only_early_runner_positive_count']}`",
        f"- only early-runner 出现占比：`{summary['only_early_runner_positive_rate']:.2%}`",
        f"- 出现 second-entry / reentry 的样本数：`{summary['second_entry_positive_count']}`",
        f"- second-entry 出现占比：`{summary['second_entry_positive_rate']:.2%}`",
        f"- 交集票总数 / 日均：`{summary['total_intersection_count']}` / `{summary['avg_intersection_count']:.2f}`",
        f"- 补充复审票总数 / 日均：`{summary['total_only_early_runner_count']}` / `{summary['avg_only_early_runner_count']:.2f}`",
        f"- 回补机会票总数 / 日均：`{summary['total_second_entry_count']}` / `{summary['avg_second_entry_count']:.2f}`",
        f"- 最近 exact 连续天数：`{summary['recent_exact_streak']}`",
        f"- 最近 exact gate：`{summary['meets_recent_exact_gate']}`",
        f"- 最小目录切换 gate：`{summary['meets_minimum_directory_switch_gate']}`",
        "",
        "## 策略体检",
        "",
        f"- 近期状态稳定性：{'已达到观察期最近 exact 最小门槛' if summary['meets_recent_exact_gate'] else '尚未达到观察期最近 exact 最小门槛'}。",
        f"- 交集票覆盖：{'开始出现可观察的交集样本' if summary['intersection_positive_count'] > 0 else '当前还没有交集票样本，无法判断交集优先价值'}。",
        f"- 补充复审压力：{'only early-runner 出现频率偏高，需继续关注噪音率' if summary['only_early_runner_positive_rate'] >= 0.5 else 'only early-runner 出现频率可控'}。",
        f"- 回补机会层：{'已有 second-entry / reentry 样本，可单独跟踪回补价值' if summary['second_entry_positive_count'] > 0 else '当前还没有 second-entry / reentry 样本'}。",
        "",
        "## 每日结果",
        "",
        "| signal_date | next_trade_date | status | latest_trade_date | formal_count | intersection_count | only_early_runner_count | second_entry_count | intersection_tickers | only_early_runner_tickers | second_entry_tickers |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['signal_date']} | {row['next_trade_date']} | {row['early_runner_status']} | {row['early_runner_latest_trade_date']} | {row['formal_count']} | {row['intersection_count']} | {row['only_early_runner_count']} | {row['second_entry_count']} | {row['intersection_tickers']} | {row['only_early_runner_tickers']} | {row['second_entry_tickers']} |"
        )
    return "\n".join(lines) + "\n"


def validate_btst_early_runner_history(
    month_prefix: str,
    *,
    reports_root: str | Path = REPORTS_DIR,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Replay one month of BTST outputs with scheme-A early-runner validation enabled."""
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    resolved_output_dir = Path(output_dir).expanduser().resolve() if output_dir else (OUTPUTS_DIR / month_prefix / "validation_scheme_a").resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    signal_dates = _discover_signal_dates(resolved_reports_root, month_prefix)
    rows = [_build_row(resolved_reports_root, signal_date, resolved_output_dir) for signal_date in signal_dates]
    summary = _build_summary(rows)
    json_path = resolved_output_dir / f"{month_prefix}-early-runner-validation.json"
    md_path = resolved_output_dir / f"{month_prefix}-early-runner-validation.md"
    json_path.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_render_markdown(month_prefix, summary, rows), encoding="utf-8")
    return {
        "status": "validated",
        "month_prefix": month_prefix,
        "output_dir": resolved_output_dir.as_posix(),
        "json_path": json_path.as_posix(),
        "md_path": md_path.as_posix(),
        "summary": summary,
    }


def main() -> None:
    """CLI entrypoint for monthly early-runner history validation."""
    parser = argparse.ArgumentParser(description="Replay BTST historical dates and validate scheme-A early-runner behavior.")
    parser.add_argument("--month-prefix", required=True, help="Month prefix like 202605.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR))
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args()
    result = validate_btst_early_runner_history(
        args.month_prefix,
        reports_root=args.reports_root,
        output_dir=args.output_dir or None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
