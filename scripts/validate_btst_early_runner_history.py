from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_btst_selected_outcome_proof import _extract_holding_outcome
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


def _safe_mean(values: list[float]) -> float | None:
    """Return one safe mean for realized-return buckets."""
    if not values:
        return None
    return sum(values) / len(values)


def _historical_positive_expectation(value: Any) -> bool | None:
    """Convert one historical positive-rate field into a boolean expectation."""
    if value is None:
        return None
    return float(value) >= 0.5


def _resolve_row_expectation(row: dict[str, Any], key: str) -> bool | None:
    """Resolve one row's historical expectation from nested prior fields when available."""
    historical_prior = dict(row.get("historical_prior") or {})
    return _historical_positive_expectation(
        historical_prior.get(key) if historical_prior else row.get(key)
    )


def _build_bucket_outcome_stats(rows: list[dict[str, Any]], trade_date: str, price_cache: dict[tuple[str, str], Any]) -> dict[str, Any]:
    """Build realized next-close and T+2 attribution stats for one bucket of tickers."""
    unique_rows: list[dict[str, Any]] = []
    seen_tickers: set[str] = set()
    for row in rows:
        ticker = str(row.get("ticker") or "").strip()
        if ticker and ticker not in seen_tickers:
            seen_tickers.add(ticker)
            unique_rows.append(dict(row))

    next_close_returns: list[float] = []
    t_plus_2_returns: list[float] = []
    next_close_positive_count = 0
    t_plus_2_positive_count = 0
    next_close_expectation_count = 0
    next_close_matched_count = 0
    next_close_violated_count = 0
    next_close_observed_without_positive_expectation_count = 0
    outcome_rows: list[dict[str, Any]] = []

    for row in unique_rows:
        ticker = str(row.get("ticker") or "").strip()
        if not ticker:
            continue
        outcome = _extract_holding_outcome(ticker, trade_date, price_cache)
        next_close_return = outcome.get("next_close_return")
        t_plus_2_return = outcome.get("t_plus_2_close_return")
        expected_next_close_positive = _resolve_row_expectation(row, "next_close_positive_rate")

        if next_close_return is not None:
            next_close_returns.append(float(next_close_return))
            if float(next_close_return) > 0:
                next_close_positive_count += 1
            if expected_next_close_positive is not None:
                next_close_expectation_count += 1
                if expected_next_close_positive:
                    if float(next_close_return) > 0:
                        next_close_matched_count += 1
                    else:
                        next_close_violated_count += 1
                else:
                    next_close_observed_without_positive_expectation_count += 1

        if t_plus_2_return is not None:
            t_plus_2_returns.append(float(t_plus_2_return))
            if float(t_plus_2_return) > 0:
                t_plus_2_positive_count += 1

        outcome_rows.append(
            {
                "ticker": ticker,
                "next_close_return": next_close_return,
                "t_plus_2_close_return": t_plus_2_return,
                "cycle_status": outcome.get("cycle_status"),
                "data_status": outcome.get("data_status"),
                "historical_next_close_expectation_positive": expected_next_close_positive,
            }
        )

    next_close_available_count = len(next_close_returns)
    t_plus_2_available_count = len(t_plus_2_returns)
    return {
        "candidate_count": len(unique_rows),
        "tickers": [str(row.get("ticker") or "").strip() for row in unique_rows if str(row.get("ticker") or "").strip()],
        "next_close_available_count": next_close_available_count,
        "next_close_positive_count": next_close_positive_count,
        "next_close_positive_rate": _safe_ratio(next_close_positive_count, next_close_available_count),
        "next_close_mean_return": _safe_mean(next_close_returns),
        "t_plus_2_available_count": t_plus_2_available_count,
        "t_plus_2_positive_count": t_plus_2_positive_count,
        "t_plus_2_positive_rate": _safe_ratio(t_plus_2_positive_count, t_plus_2_available_count),
        "t_plus_2_mean_return": _safe_mean(t_plus_2_returns),
        "next_close_expectation_count": next_close_expectation_count,
        "next_close_matched_count": next_close_matched_count,
        "next_close_violated_count": next_close_violated_count,
        "next_close_observed_without_positive_expectation_count": next_close_observed_without_positive_expectation_count,
        "outcomes": outcome_rows,
    }


def _build_outcome_attribution(signal_date_iso: str, intersection: dict[str, Any]) -> dict[str, Any]:
    """Build realized attribution stats for intersection, only-early-runner, and second-entry buckets."""
    price_cache: dict[tuple[str, str], Any] = {}
    overlap_rows = [dict(row or {}) for row in list(intersection.get("overlap_rows") or [])]
    only_rows = [dict(row or {}) for row in list(intersection.get("only_early_runner_rows") or [])]
    second_entry_rows = [dict(row or {}) for row in list(intersection.get("second_entry_rows") or [])]
    return {
        "intersection": _build_bucket_outcome_stats(overlap_rows, signal_date_iso, price_cache),
        "only_early_runner": _build_bucket_outcome_stats(only_rows, signal_date_iso, price_cache),
        "second_entry": _build_bucket_outcome_stats(second_entry_rows, signal_date_iso, price_cache),
    }


def _build_group_summary(rows: list[dict[str, Any]], group_key: str) -> dict[str, Any]:
    """Aggregate one bucket's realized attribution metrics across all replay rows."""
    candidate_count = 0
    next_close_available_count = 0
    next_close_positive_count = 0
    next_close_return_sum = 0.0
    t_plus_2_available_count = 0
    t_plus_2_positive_count = 0
    t_plus_2_return_sum = 0.0
    next_close_expectation_count = 0
    next_close_matched_count = 0
    next_close_violated_count = 0
    next_close_observed_without_positive_expectation_count = 0

    for row in rows:
        group = dict(dict(row.get("outcome_attribution") or {}).get(group_key) or {})
        candidate_count += int(group.get("candidate_count") or 0)
        next_close_available_count += int(group.get("next_close_available_count") or 0)
        next_close_positive_count += int(group.get("next_close_positive_count") or 0)
        t_plus_2_available_count += int(group.get("t_plus_2_available_count") or 0)
        t_plus_2_positive_count += int(group.get("t_plus_2_positive_count") or 0)
        next_close_expectation_count += int(group.get("next_close_expectation_count") or 0)
        next_close_matched_count += int(group.get("next_close_matched_count") or 0)
        next_close_violated_count += int(group.get("next_close_violated_count") or 0)
        next_close_observed_without_positive_expectation_count += int(group.get("next_close_observed_without_positive_expectation_count") or 0)
        if group.get("next_close_mean_return") is not None:
            next_close_return_sum += float(group.get("next_close_mean_return") or 0.0) * int(group.get("next_close_available_count") or 0)
        if group.get("t_plus_2_mean_return") is not None:
            t_plus_2_return_sum += float(group.get("t_plus_2_mean_return") or 0.0) * int(group.get("t_plus_2_available_count") or 0)

    return {
        "candidate_count": candidate_count,
        "next_close_available_count": next_close_available_count,
        "next_close_positive_count": next_close_positive_count,
        "next_close_positive_rate": _safe_ratio(next_close_positive_count, next_close_available_count),
        "next_close_mean_return": None if next_close_available_count <= 0 else next_close_return_sum / next_close_available_count,
        "t_plus_2_available_count": t_plus_2_available_count,
        "t_plus_2_positive_count": t_plus_2_positive_count,
        "t_plus_2_positive_rate": _safe_ratio(t_plus_2_positive_count, t_plus_2_available_count),
        "t_plus_2_mean_return": None if t_plus_2_available_count <= 0 else t_plus_2_return_sum / t_plus_2_available_count,
        "next_close_expectation_count": next_close_expectation_count,
        "next_close_matched_count": next_close_matched_count,
        "next_close_violated_count": next_close_violated_count,
        "next_close_observed_without_positive_expectation_count": next_close_observed_without_positive_expectation_count,
    }


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
    outcome_attribution = _build_outcome_attribution(signal_date_iso, intersection)
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
        "outcome_attribution": outcome_attribution,
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
    intersection_outcome_summary = _build_group_summary(rows, "intersection")
    only_early_runner_outcome_summary = _build_group_summary(rows, "only_early_runner")
    second_entry_outcome_summary = _build_group_summary(rows, "second_entry")
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
        "intersection_outcome_summary": intersection_outcome_summary,
        "only_early_runner_outcome_summary": only_early_runner_outcome_summary,
        "second_entry_outcome_summary": second_entry_outcome_summary,
    }


def _fmt_pct(value: Any) -> str:
    """Format one ratio-like value as percentage text for the report."""
    if value is None:
        return "n/a"
    return f"{float(value):.2%}"


def _fmt_return(value: Any) -> str:
    """Format one realized return with percentage sign for the report."""
    if value is None:
        return "n/a"
    return f"{float(value):.2%}"


def _render_group_outcome_lines(title: str, summary: dict[str, Any]) -> list[str]:
    """Render one bucket's realized attribution summary as compact markdown bullets."""
    resolved_summary = {
        "candidate_count": 0,
        "next_close_available_count": 0,
        "next_close_positive_rate": 0.0,
        "next_close_mean_return": None,
        "t_plus_2_available_count": 0,
        "t_plus_2_positive_rate": 0.0,
        "t_plus_2_mean_return": None,
        "next_close_matched_count": 0,
        "next_close_expectation_count": 0,
        "next_close_violated_count": 0,
        "next_close_observed_without_positive_expectation_count": 0,
        **dict(summary or {}),
    }
    return [
        f"### {title}",
        "",
        f"- 样本票数：`{resolved_summary['candidate_count']}`；next_close 可评估：`{resolved_summary['next_close_available_count']}`；T+2 可评估：`{resolved_summary['t_plus_2_available_count']}`。",
        f"- next_close 正收益率 / 平均收益：`{_fmt_pct(resolved_summary['next_close_positive_rate'])}` / `{_fmt_return(resolved_summary['next_close_mean_return'])}`。",
        f"- T+2 正收益率 / 平均收益：`{_fmt_pct(resolved_summary['t_plus_2_positive_rate'])}` / `{_fmt_return(resolved_summary['t_plus_2_mean_return'])}`。",
        f"- 历史正向预期对齐：匹配 `[{resolved_summary['next_close_matched_count']}/{resolved_summary['next_close_expectation_count']}]`；违背 `[{resolved_summary['next_close_violated_count']}/{resolved_summary['next_close_expectation_count']}]`；无正向预期仅观察：`{resolved_summary['next_close_observed_without_positive_expectation_count']}`。",
        "",
    ]


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
        "## 结果归因",
        "",
    ]
    lines.extend(_render_group_outcome_lines("交集优先复审层", dict(summary.get("intersection_outcome_summary") or {})))
    lines.extend(_render_group_outcome_lines("补充复审层", dict(summary.get("only_early_runner_outcome_summary") or {})))
    lines.extend(_render_group_outcome_lines("回补机会层", dict(summary.get("second_entry_outcome_summary") or {})))
    lines.extend(
        [
            "## 每日结果",
            "",
            "| signal_date | next_trade_date | status | latest_trade_date | formal_count | intersection_count | only_early_runner_count | second_entry_count | intersection_tickers | only_early_runner_tickers | second_entry_tickers |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |",
        ]
    )
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
