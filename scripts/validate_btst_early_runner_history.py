from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_btst_selected_outcome_proof import _extract_holding_outcome
from scripts.btst_strategy_thresholds import (
    default_strategy_thresholds,
    DEFAULT_STRATEGY_THRESHOLDS_PROFILE,
    resolve_strategy_thresholds,
    resolve_strategy_thresholds_config_path,
)
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


def _default_strategy_thresholds() -> dict[str, Any]:
    """Return the default conservative thresholds for scheme-A strategy suggestions."""
    return default_strategy_thresholds()


def _resolve_strategy_thresholds(
    overrides: dict[str, Any] | None = None,
    *,
    config_path: str | Path | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    """Merge default values, repository config values, and runtime overrides in that order."""
    return resolve_strategy_thresholds(overrides, config_path=config_path, profile=profile)


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
    return _historical_positive_expectation(historical_prior.get(key) if historical_prior else row.get(key))


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


def _build_strategy_recommendations(summary: dict[str, Any], thresholds: dict[str, Any]) -> list[dict[str, Any]]:
    """Build conservative strategy actions from attribution metrics and observation stability."""
    recommendations: list[dict[str, Any]] = []
    intersection = dict(summary.get("intersection_outcome_summary") or {})
    only_early_runner = dict(summary.get("only_early_runner_outcome_summary") or {})
    second_entry = dict(summary.get("second_entry_outcome_summary") or {})

    if summary.get("meets_minimum_directory_switch_gate"):
        recommendations.append(
            {
                "id": "directory-switch-trial",
                "level": "medium",
                "action": "开始准备正式目录试运行",
                "reason": "最近 exact 稳定且交集样本已连续出现，可考虑保留 scheme_a 并行观察的同时，试运行切回正式目录。",
            }
        )
    else:
        recommendations.append(
            {
                "id": "stay-scheme-a",
                "level": "high",
                "action": "继续保留 scheme_a 观察目录",
                "reason": "观察期稳定性或交集覆盖仍不足，当前不建议切回正式目录。",
            }
        )

    intersection_rate = float(intersection.get("next_close_positive_rate") or 0.0)
    only_rate = float(only_early_runner.get("next_close_positive_rate") or 0.0)
    intersection_mean = intersection.get("next_close_mean_return")
    only_mean = only_early_runner.get("next_close_mean_return")
    if int(intersection.get("candidate_count") or 0) >= int(thresholds["intersection_min_candidate_count"]) and (intersection_rate >= only_rate + float(thresholds["intersection_uplift_rate_threshold"]) or (intersection_mean is not None and only_mean is not None and float(intersection_mean) >= float(only_mean) + float(thresholds["intersection_uplift_mean_return_threshold"]))):
        recommendations.append(
            {
                "id": "raise-intersection-priority",
                "level": "high",
                "action": "提高交集优先复审层权重",
                "reason": (f"交集层 next_close 正收益率 `{intersection_rate:.2%}`，" f"相对补充层 `{only_rate:.2%}` 已出现明显优势。"),
            }
        )
    elif int(intersection.get("candidate_count") or 0) == 0:
        recommendations.append(
            {
                "id": "wait-intersection-evidence",
                "level": "medium",
                "action": "继续等待交集层样本积累",
                "reason": "当前还没有足够交集样本，不适合提前提高交集层权重。",
            }
        )

    if int(only_early_runner.get("candidate_count") or 0) >= int(thresholds["only_early_runner_min_candidate_count"]) and (
        only_rate < float(thresholds["only_early_runner_max_positive_rate"]) or (only_mean is not None and float(only_mean) < 0) or (int(intersection.get("candidate_count") or 0) >= int(thresholds["intersection_min_candidate_count"]) and intersection_rate >= only_rate + float(thresholds["intersection_uplift_rate_threshold"]))
    ):
        recommendations.append(
            {
                "id": "tighten-only-early-runner",
                "level": "high",
                "action": "收紧 only early-runner 曝光",
                "reason": (f"补充层 next_close 正收益率 `{only_rate:.2%}`，" f"平均收益 `{_fmt_return(only_mean)}`，更像补充观察而不是主执行来源。"),
            }
        )
    elif int(only_early_runner.get("candidate_count") or 0) > 0:
        recommendations.append(
            {
                "id": "keep-only-early-runner-shadow",
                "level": "low",
                "action": "保留 only early-runner 影子观察",
                "reason": "补充层仍有一定存在价值，但暂不建议升级成正式主层。",
            }
        )

    second_next_close_mean = second_entry.get("next_close_mean_return")
    second_t2_mean = second_entry.get("t_plus_2_mean_return")
    if int(second_entry.get("candidate_count") or 0) >= int(thresholds["second_entry_min_candidate_count"]) and second_t2_mean is not None and (second_next_close_mean is None or float(second_t2_mean) > float(second_next_close_mean) + float(thresholds["second_entry_t2_advantage_threshold"])):
        recommendations.append(
            {
                "id": "delay-second-entry-confirmation",
                "level": "medium",
                "action": "保留 second-entry，但只用于延后确认/回补",
                "reason": (f"回补层 T+2 平均收益 `{_fmt_return(second_t2_mean)}`" f" 高于 next_close `{_fmt_return(second_next_close_mean)}`，更适合延后确认。"),
            }
        )
    elif int(second_entry.get("candidate_count") or 0) >= int(thresholds["second_entry_min_candidate_count"]) and ((second_next_close_mean is not None and float(second_next_close_mean) < 0) and (second_t2_mean is None or float(second_t2_mean) <= 0)):
        recommendations.append(
            {
                "id": "shrink-second-entry",
                "level": "medium",
                "action": "压缩 second-entry 触发频率",
                "reason": "回补层在 next_close 和 T+2 上都没有体现优势，应该继续收窄触发条件。",
            }
        )
    elif int(second_entry.get("candidate_count") or 0) > 0:
        recommendations.append(
            {
                "id": "keep-second-entry-isolated",
                "level": "low",
                "action": "继续单独隔离 second-entry",
                "reason": "回补层已有样本，但还不足以升级为更高优先级，只适合保持独立跟踪。",
            }
        )

    return recommendations


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


def _build_row(
    reports_root: Path,
    signal_date: str,
    bundle_root: Path,
    *,
    strategy_thresholds_config_path: str | Path | None = None,
    strategy_thresholds_profile: str = DEFAULT_STRATEGY_THRESHOLDS_PROFILE,
) -> dict[str, Any]:
    """Replay one signal date with the scheme-A bundle and collect validation metrics."""
    signal_date_compact, signal_date_iso = _normalize_signal_date(signal_date)
    output_dir = bundle_root / signal_date_compact
    bundle_result = generate_btst_doc_bundle(
        signal_date_compact,
        reports_root=reports_root,
        output_dir=output_dir,
        refresh_early_runner=False,
        strategy_thresholds_config_path=strategy_thresholds_config_path,
        strategy_thresholds_profile=strategy_thresholds_profile,
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


def _build_summary(
    rows: list[dict[str, Any]],
    strategy_thresholds: dict[str, Any] | None = None,
    *,
    strategy_thresholds_config_path: str | Path | None = None,
    strategy_thresholds_profile: str = DEFAULT_STRATEGY_THRESHOLDS_PROFILE,
) -> dict[str, Any]:
    """Aggregate monthly validation metrics from per-day rows."""
    thresholds = _resolve_strategy_thresholds(
        strategy_thresholds,
        config_path=strategy_thresholds_config_path,
        profile=strategy_thresholds_profile,
    )
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
    meets_recent_exact_gate = recent_exact_streak >= int(thresholds["min_recent_exact_streak"])
    meets_minimum_directory_switch_gate = meets_recent_exact_gate and intersection_positive_count >= int(thresholds["min_intersection_positive_days"]) and (not bool(thresholds["require_zero_unavailable_days_for_directory_switch"]) or unavailable_count == 0)
    intersection_outcome_summary = _build_group_summary(rows, "intersection")
    only_early_runner_outcome_summary = _build_group_summary(rows, "only_early_runner")
    second_entry_outcome_summary = _build_group_summary(rows, "second_entry")
    summary = {
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
        "strategy_thresholds_config_path": (
            resolve_strategy_thresholds_config_path(
                strategy_thresholds_config_path,
                profile=strategy_thresholds_profile,
            ).as_posix()
        ),
        "strategy_thresholds_profile": strategy_thresholds_profile,
        "strategy_thresholds": thresholds,
        "intersection_outcome_summary": intersection_outcome_summary,
        "only_early_runner_outcome_summary": only_early_runner_outcome_summary,
        "second_entry_outcome_summary": second_entry_outcome_summary,
    }
    summary["strategy_recommendations"] = _build_strategy_recommendations(summary, thresholds)
    return summary


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
        "## 建议阈值",
        "",
        f"- profile：`{summary.get('strategy_thresholds_profile')}`；配置文件：`{summary.get('strategy_thresholds_config_path')}`。",
        f"- exact 连续门槛：`{dict(summary.get('strategy_thresholds') or {}).get('min_recent_exact_streak')}`；交集出现天数门槛：`{dict(summary.get('strategy_thresholds') or {}).get('min_intersection_positive_days')}`。",
        f"- 交集层 uplift 门槛：胜率差 `+{_fmt_pct(dict(summary.get('strategy_thresholds') or {}).get('intersection_uplift_rate_threshold'))}`；均值差 `+{_fmt_return(dict(summary.get('strategy_thresholds') or {}).get('intersection_uplift_mean_return_threshold'))}`。",
        f"- 补充层最大容忍正收益率：`{_fmt_pct(dict(summary.get('strategy_thresholds') or {}).get('only_early_runner_max_positive_rate'))}`；回补层 T+2 优势门槛：`+{_fmt_return(dict(summary.get('strategy_thresholds') or {}).get('second_entry_t2_advantage_threshold'))}`。",
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
    lines.extend(["## 自动策略建议", ""])
    for item in list(summary.get("strategy_recommendations") or []):
        lines.append(f"- [{item.get('level')}] {item.get('action')}：{item.get('reason')}")
    if not list(summary.get("strategy_recommendations") or []):
        lines.append("- 当前样本不足，暂不输出自动策略建议。")
    lines.append("")
    lines.extend(
        [
            "## 每日结果",
            "",
            "| signal_date | next_trade_date | status | latest_trade_date | formal_count | intersection_count | only_early_runner_count | second_entry_count | intersection_tickers | only_early_runner_tickers | second_entry_tickers |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |",
        ]
    )
    for row in rows:
        lines.append(f"| {row['signal_date']} | {row['next_trade_date']} | {row['early_runner_status']} | {row['early_runner_latest_trade_date']} | {row['formal_count']} | {row['intersection_count']} | {row['only_early_runner_count']} | {row['second_entry_count']} | {row['intersection_tickers']} | {row['only_early_runner_tickers']} | {row['second_entry_tickers']} |")
    return "\n".join(lines) + "\n"


def _build_profile_comparison(profile_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Compare multiple profile summaries and highlight the strongest edges."""
    profiles = [
        {
            "profile": profile,
            "exact_rate": dict(result.get("summary") or {}).get("exact_rate", 0.0),
            "intersection_positive_rate": dict(result.get("summary") or {}).get("intersection_positive_rate", 0.0),
            "only_early_runner_positive_rate": dict(result.get("summary") or {}).get("only_early_runner_positive_rate", 0.0),
            "intersection_next_close_positive_rate": dict(dict(result.get("summary") or {}).get("intersection_outcome_summary") or {}).get("next_close_positive_rate", 0.0),
            "intersection_next_close_mean_return": dict(dict(result.get("summary") or {}).get("intersection_outcome_summary") or {}).get("next_close_mean_return"),
            "only_early_runner_next_close_mean_return": dict(dict(result.get("summary") or {}).get("only_early_runner_outcome_summary") or {}).get("next_close_mean_return"),
            "second_entry_t_plus_2_mean_return": dict(dict(result.get("summary") or {}).get("second_entry_outcome_summary") or {}).get("t_plus_2_mean_return"),
            "meets_minimum_directory_switch_gate": bool(dict(result.get("summary") or {}).get("meets_minimum_directory_switch_gate")),
            "json_path": result.get("json_path"),
            "md_path": result.get("md_path"),
        }
        for profile, result in profile_results.items()
    ]
    sorted_profiles = sorted(profiles, key=lambda item: str(item["profile"]))
    recommended_profile = None
    reasons: list[str] = []
    if sorted_profiles:
        ranked_profiles = sorted(
            sorted_profiles,
            key=lambda item: (
                float(item.get("intersection_next_close_positive_rate") or 0.0),
                float(item.get("intersection_next_close_mean_return") or -999.0),
                float(item.get("exact_rate") or 0.0),
                -float(item.get("only_early_runner_positive_rate") or 0.0),
            ),
            reverse=True,
        )
        recommended_profile = ranked_profiles[0]["profile"]
        if len(ranked_profiles) >= 2:
            top = ranked_profiles[0]
            runner_up = ranked_profiles[1]
            reasons.append(f"`{top['profile']}` 的交集层 next_close 正收益率更高：`{_fmt_pct(top.get('intersection_next_close_positive_rate'))}` vs `{_fmt_pct(runner_up.get('intersection_next_close_positive_rate'))}`。")
            reasons.append(f"`{top['profile']}` 的交集层平均收益更好：`{_fmt_return(top.get('intersection_next_close_mean_return'))}` vs `{_fmt_return(runner_up.get('intersection_next_close_mean_return'))}`。")
    return {
        "profiles": sorted_profiles,
        "recommended_profile": recommended_profile,
        "recommendation_reasons": reasons,
    }


def _render_profile_comparison_markdown(month_prefix: str, comparison: dict[str, Any]) -> str:
    """Render one markdown report that compares multiple strategy-threshold profiles."""
    lines = [
        f"# {month_prefix} BTST Profile 对照复盘",
        "",
        f"- 推荐 profile：`{comparison.get('recommended_profile') or 'n/a'}`",
        "",
        "## 总览",
        "",
        "| profile | exact_rate | intersection_positive_rate | only_early_runner_positive_rate | intersection_next_close_positive_rate | intersection_next_close_mean_return | second_entry_t_plus_2_mean_return | directory_switch_gate |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in list(comparison.get("profiles") or []):
        lines.append(
            f"| {item['profile']} | {_fmt_pct(item.get('exact_rate'))} | {_fmt_pct(item.get('intersection_positive_rate'))} | {_fmt_pct(item.get('only_early_runner_positive_rate'))} | {_fmt_pct(item.get('intersection_next_close_positive_rate'))} | {_fmt_return(item.get('intersection_next_close_mean_return'))} | {_fmt_return(item.get('second_entry_t_plus_2_mean_return'))} | {item.get('meets_minimum_directory_switch_gate')} |"
        )
    lines.extend(["", "## 推荐理由", ""])
    if list(comparison.get("recommendation_reasons") or []):
        for reason in list(comparison.get("recommendation_reasons") or []):
            lines.append(f"- {reason}")
    else:
        lines.append("- 当前样本不足，尚未形成明显 profile 优势。")
    return "\n".join(lines) + "\n"


def validate_btst_early_runner_history(
    month_prefix: str,
    *,
    reports_root: str | Path = REPORTS_DIR,
    output_dir: str | Path | None = None,
    strategy_thresholds: dict[str, Any] | None = None,
    strategy_thresholds_config_path: str | Path | None = None,
    strategy_thresholds_profile: str = DEFAULT_STRATEGY_THRESHOLDS_PROFILE,
) -> dict[str, Any]:
    """Replay one month of BTST outputs with scheme-A early-runner validation enabled."""
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    resolved_output_dir = Path(output_dir).expanduser().resolve() if output_dir else (OUTPUTS_DIR / month_prefix / "validation_scheme_a").resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    signal_dates = _discover_signal_dates(resolved_reports_root, month_prefix)
    rows = [
        _build_row(
            resolved_reports_root,
            signal_date,
            resolved_output_dir,
            strategy_thresholds_config_path=strategy_thresholds_config_path,
            strategy_thresholds_profile=strategy_thresholds_profile,
        )
        for signal_date in signal_dates
    ]
    resolved_thresholds = _resolve_strategy_thresholds(
        strategy_thresholds,
        config_path=strategy_thresholds_config_path,
        profile=strategy_thresholds_profile,
    )
    summary = _build_summary(
        rows,
        strategy_thresholds=resolved_thresholds,
        strategy_thresholds_config_path=strategy_thresholds_config_path,
        strategy_thresholds_profile=strategy_thresholds_profile,
    )
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


def compare_btst_early_runner_profiles(
    month_prefix: str,
    *,
    profiles: list[str] | tuple[str, ...],
    reports_root: str | Path = REPORTS_DIR,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Run monthly validation for multiple profiles and write one comparison report."""
    resolved_output_dir = Path(output_dir).expanduser().resolve() if output_dir else (OUTPUTS_DIR / month_prefix / "validation_scheme_a_profiles").resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    profile_results: dict[str, dict[str, Any]] = {}
    for profile in profiles:
        profile_output_dir = resolved_output_dir / str(profile)
        profile_results[str(profile)] = validate_btst_early_runner_history(
            month_prefix,
            reports_root=reports_root,
            output_dir=profile_output_dir,
            strategy_thresholds_profile=str(profile),
        )
    comparison = _build_profile_comparison(profile_results)
    json_path = resolved_output_dir / f"{month_prefix}-btst-profile-comparison.json"
    md_path = resolved_output_dir / f"{month_prefix}-btst-profile-comparison.md"
    payload = {
        "month_prefix": month_prefix,
        "profiles": list(profiles),
        "comparison": comparison,
        "profile_results": profile_results,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_render_profile_comparison_markdown(month_prefix, comparison), encoding="utf-8")
    return {
        "status": "compared",
        "month_prefix": month_prefix,
        "output_dir": resolved_output_dir.as_posix(),
        "json_path": json_path.as_posix(),
        "md_path": md_path.as_posix(),
        "comparison": comparison,
        "profile_results": profile_results,
    }


def main() -> None:
    """CLI entrypoint for monthly early-runner history validation."""
    parser = argparse.ArgumentParser(description="Replay BTST historical dates and validate scheme-A early-runner behavior.")
    parser.add_argument("--month-prefix", required=True, help="Month prefix like 202605.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR))
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--strategy-thresholds-config", default="")
    parser.add_argument("--strategy-thresholds-profile", default=DEFAULT_STRATEGY_THRESHOLDS_PROFILE)
    parser.add_argument("--compare-profiles", nargs="*", default=[])
    parser.add_argument("--min-recent-exact-streak", type=int, default=_default_strategy_thresholds()["min_recent_exact_streak"])
    parser.add_argument("--min-intersection-positive-days", type=int, default=_default_strategy_thresholds()["min_intersection_positive_days"])
    parser.add_argument("--allow-unavailable-days-for-directory-switch", action="store_true")
    parser.add_argument("--intersection-uplift-rate-threshold", type=float, default=_default_strategy_thresholds()["intersection_uplift_rate_threshold"])
    parser.add_argument("--intersection-uplift-mean-return-threshold", type=float, default=_default_strategy_thresholds()["intersection_uplift_mean_return_threshold"])
    parser.add_argument("--only-early-runner-max-positive-rate", type=float, default=_default_strategy_thresholds()["only_early_runner_max_positive_rate"])
    parser.add_argument("--second-entry-t2-advantage-threshold", type=float, default=_default_strategy_thresholds()["second_entry_t2_advantage_threshold"])
    args = parser.parse_args()
    if list(args.compare_profiles):
        result = compare_btst_early_runner_profiles(
            args.month_prefix,
            profiles=list(args.compare_profiles),
            reports_root=args.reports_root,
            output_dir=args.output_dir or None,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    result = validate_btst_early_runner_history(
        args.month_prefix,
        reports_root=args.reports_root,
        output_dir=args.output_dir or None,
        strategy_thresholds_config_path=args.strategy_thresholds_config or None,
        strategy_thresholds_profile=args.strategy_thresholds_profile,
        strategy_thresholds={
            "min_recent_exact_streak": args.min_recent_exact_streak,
            "min_intersection_positive_days": args.min_intersection_positive_days,
            "require_zero_unavailable_days_for_directory_switch": not args.allow_unavailable_days_for_directory_switch,
            "intersection_uplift_rate_threshold": args.intersection_uplift_rate_threshold,
            "intersection_uplift_mean_return_threshold": args.intersection_uplift_mean_return_threshold,
            "only_early_runner_max_positive_rate": args.only_early_runner_max_positive_rate,
            "second_entry_t2_advantage_threshold": args.second_entry_t2_advantage_threshold,
        },
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
