from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

from scripts.btst_analysis_utils import (
    extract_btst_price_outcome as _extract_btst_price_outcome,
)
from scripts.btst_analysis_utils import (
    iter_selection_snapshots as _iter_selection_snapshots,
)
from scripts.btst_analysis_utils import normalize_trade_date as _normalize_trade_date
from scripts.btst_analysis_utils import round_or_none as _round_or_none
from scripts.btst_analysis_utils import safe_float as _safe_float
from scripts.btst_latest_followup_utils import _load_btst_runtime_5d_prior_by_ticker
from scripts.btst_report_utils import (
    discover_nested_report_dirs as discover_report_dirs,
)
from src.paper_trading._btst_reporting.payoff_review_lane import (
    build_payoff_review_entries,
)

REPORTS_DIR = Path("data/reports")
DEFAULT_REPORTS_ROOT = REPORTS_DIR
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_5d_15pct_objective_monitor_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_5d_15pct_objective_monitor_latest.md"


def _summarize_distribution(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "mean": round(mean(values), 4),
    }


def _rate(hit_count: int, total_count: int) -> float | None:
    if total_count <= 0:
        return None
    return round(hit_count / total_count, 4)


def _objective_fit_score(*, hit_rate: float | None, mean_return: float | None, objective_hit_rate_target: float, return_target: float) -> float:
    hit_component = 0.0 if hit_rate is None else min(float(hit_rate) / objective_hit_rate_target, 1.0)
    payoff_component = 0.0 if mean_return is None else min(float(mean_return) / return_target, 1.0)
    return round((hit_component * 0.7) + (payoff_component * 0.3), 4)


def _surface_summary(
    rows: list[dict[str, Any]],
    *,
    objective_hit_rate_target: float,
    return_target: float,
) -> dict[str, Any]:
    closed_rows = [row for row in rows if row.get("max_future_high_return_2_5d") is not None]
    returns = [float(row["max_future_high_return_2_5d"]) for row in closed_rows]
    hit_count = sum(1 for value in returns if value >= return_target)
    hit_rate = _rate(hit_count, len(closed_rows))
    mean_return = round(mean(returns), 4) if returns else None
    time_to_hit_values = [float(row["time_to_hit_15pct"]) for row in closed_rows if row.get("time_to_hit_15pct") is not None]
    verdict = "insufficient_closed_cycle_samples"
    if closed_rows:
        verdict = "meets_strict_btst_objective" if hit_rate is not None and hit_rate >= objective_hit_rate_target else "below_strict_btst_objective"
    objective_fit_score = _objective_fit_score(
        hit_rate=hit_rate,
        mean_return=mean_return,
        objective_hit_rate_target=objective_hit_rate_target,
        return_target=return_target,
    )
    return {
        "closed_cycle_count": len(closed_rows),
        "max_future_high_return_2_5d_distribution": _summarize_distribution(returns),
        "max_future_high_return_2_5d_hit_rate_at_target": hit_rate,
        "objective_hit_rate_target": objective_hit_rate_target,
        "max_future_high_return_2_5d_target": return_target,
        "max_future_high_return_2_5d_hit_count": hit_count,
        "mean_max_future_high_return_2_5d": mean_return,
        "time_to_hit_15pct_distribution": _summarize_distribution(time_to_hit_values),
        "objective_fit_score": objective_fit_score,
        "objective_gap": {
            "hit_rate_gap": None if hit_rate is None else round(objective_hit_rate_target - hit_rate, 4),
            "mean_return_gap": None if mean_return is None else round(return_target - mean_return, 4),
        },
        "verdict": verdict,
    }


def _group_leaderboard(
    rows: list[dict[str, Any]],
    *,
    group_key: str,
    objective_hit_rate_target: float,
    return_target: float,
    min_closed_cycle_count: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(group_key) or "unknown")].append(row)

    leaderboard: list[dict[str, Any]] = []
    for label, group_rows in grouped.items():
        summary = _surface_summary(group_rows, objective_hit_rate_target=objective_hit_rate_target, return_target=return_target)
        if int(summary.get("closed_cycle_count") or 0) < min_closed_cycle_count:
            continue
        leaderboard.append({"group_key": group_key, "group_label": label, "row_count": len(group_rows), **summary})

    leaderboard.sort(
        key=lambda row: (
            float(row.get("objective_fit_score") or -999.0),
            float(row.get("max_future_high_return_2_5d_hit_rate_at_target") or -999.0),
            float(row.get("mean_max_future_high_return_2_5d") or -999.0),
            int(row.get("closed_cycle_count") or 0),
            str(row.get("group_label") or ""),
        ),
        reverse=True,
    )
    return leaderboard


def _deduplicate_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    deduplicated: list[dict[str, Any]] = []
    seen_keys: set[tuple[Any, ...]] = set()
    duplicate_count = 0
    for row in rows:
        row_key = (
            str(row.get("trade_date") or ""),
            str(row.get("ticker") or ""),
            str(row.get("decision") or ""),
            str(row.get("candidate_source") or ""),
            row.get("max_future_high_return_2_5d"),
        )
        if row_key in seen_keys:
            duplicate_count += 1
            continue
        seen_keys.add(row_key)
        deduplicated.append(row)
    return deduplicated, duplicate_count


def _recommendation(
    *,
    tradeable_surface: dict[str, Any],
    decision_leaderboard: list[dict[str, Any]],
    ticker_leaderboard: list[dict[str, Any]],
    false_negative_rows: list[dict[str, Any]],
) -> str:
    if str(tradeable_surface.get("verdict") or "") == "meets_strict_btst_objective":
        return "当前 tradeable surface 已达到 5日内上涨 15% 的严格目标，应优先扩张相同结构样本并检查容量上限，而不是先放松阈值。"
    best_decision = decision_leaderboard[0] if decision_leaderboard else {}
    best_ticker = ticker_leaderboard[0] if ticker_leaderboard else {}
    if false_negative_rows:
        return f"当前还未稳定达到 5D/+15% 目标；优先复盘 {false_negative_rows[0].get('ticker') or '最高优先级 false negative'} 这类已经命中目标却未被放行的样本，并围绕 {best_decision.get('group_label') or '当前最优决策层'} 做结构化提纯。"
    if best_ticker:
        return f"当前还未稳定达到 5D/+15% 目标；最接近目标的是 {best_ticker.get('group_label')}，应先增加同类闭环样本再考虑升级默认策略。"
    return "当前 closed-cycle 证据不足或整体未达标，默认结论应继续保持观察优先，不应为了覆盖而主动放松执行阈值。"


def _append_overview_markdown(lines: list[str], analysis: dict[str, Any]) -> None:
    lines.append("## Objective")
    for key in ("generated_at", "reports_root", "report_dir_count", "objective_hit_rate_target", "max_future_high_return_2_5d_target", "leaderboard_min_closed_cycle_count"):
        lines.append(f"- {key}: {analysis.get(key)}")
    lines.append("")


def _append_surface_summary_markdown(lines: list[str], analysis: dict[str, Any]) -> None:
    lines.append("## Surface Summary")
    for label in (
        "all_surface",
        "tradeable_surface",
        "selected_surface",
        "near_miss_surface",
        "non_tradeable_surface",
        "payoff_review_surface",
    ):
        summary = dict(analysis.get(label) or {})
        if not summary:
            continue
        lines.append(
            f"- {label}: closed_cycle_count={summary.get('closed_cycle_count')}, hit_rate={summary.get('max_future_high_return_2_5d_hit_rate_at_target')}, mean_max_return={summary.get('mean_max_future_high_return_2_5d')}, verdict={summary.get('verdict')}, objective_fit_score={summary.get('objective_fit_score')}"
        )
    lines.append("")


def _append_leaderboard_markdown(lines: list[str], title: str, rows: list[dict[str, Any]]) -> None:
    lines.append(f"## {title}")
    for row in rows:
        lines.append(
            f"- {row.get('group_label')}: closed_cycle_count={row.get('closed_cycle_count')}, hit_rate={row.get('max_future_high_return_2_5d_hit_rate_at_target')}, mean_max_return={row.get('mean_max_future_high_return_2_5d')}, verdict={row.get('verdict')}, objective_fit_score={row.get('objective_fit_score')}"
        )
    if not rows:
        lines.append("- none")
    lines.append("")


def _append_goal_rows_markdown(lines: list[str], title: str, rows: list[dict[str, Any]]) -> None:
    lines.append(f"## {title}")
    for row in rows:
        lines.append(
            f"- {row.get('trade_date')} {row.get('ticker')}: decision={row.get('decision')}, source={row.get('candidate_source')}, max_future_high_return_2_5d={row.get('max_future_high_return_2_5d')}, score_target={row.get('score_target')}"
        )
    if not rows:
        lines.append("- none")
    lines.append("")


def _append_recommendation_markdown(lines: list[str], analysis: dict[str, Any]) -> None:
    lines.append("## Recommendation")
    lines.append(f"- {analysis.get('recommendation')}")
    lines.append("")


def render_btst_5d_15pct_objective_monitor_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = ["# BTST 5D / +15% Objective Monitor", ""]
    _append_overview_markdown(lines, analysis)
    _append_surface_summary_markdown(lines, analysis)
    _append_leaderboard_markdown(lines, "Decision Leaderboard", list(analysis.get("decision_leaderboard") or []))
    _append_leaderboard_markdown(lines, "Candidate Source Leaderboard", list(analysis.get("candidate_source_leaderboard") or []))
    _append_leaderboard_markdown(lines, "Ticker Leaderboard", list(analysis.get("ticker_leaderboard") or []))
    _append_goal_rows_markdown(lines, "Strict Goal Cases", list(analysis.get("strict_goal_rows") or []))
    _append_goal_rows_markdown(lines, "False Negative Strict Goal Cases", list(analysis.get("false_negative_strict_goal_rows") or []))
    _append_recommendation_markdown(lines, analysis)
    return "\n".join(lines)


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _resolve_existing_json_path(raw_path: Any, report_dir: Path) -> Path | None:
    if not raw_path:
        return None
    candidate = Path(str(raw_path)).expanduser()
    candidates = [candidate]
    if not candidate.is_absolute():
        candidates.append(report_dir / candidate)
    for item in candidates:
        if item.exists():
            return item.resolve()
    return None


def _load_btst_brief(report_dir: Path) -> dict[str, Any]:
    session_summary_path = report_dir / "session_summary.json"
    candidates: list[Path] = [report_dir / "btst_next_day_trade_brief_latest.json"]
    if session_summary_path.exists():
        try:
            session_summary = _read_json(session_summary_path)
        except (OSError, json.JSONDecodeError):
            session_summary = {}
        brief_path = _resolve_existing_json_path(dict(session_summary.get("btst_followup") or {}).get("brief_json"), report_dir)
        if brief_path is not None:
            candidates.insert(0, brief_path)

    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            return dict(_read_json(candidate))
        except (OSError, json.JSONDecodeError):
            continue
    return {}


def _build_payoff_review_entries_from_snapshot(
    snapshot: dict[str, Any],
    *,
    runtime_5d_prior_by_ticker: dict[str, dict[str, Any]],
    max_entries: int = 5,
) -> list[dict[str, Any]]:
    selection_targets = dict(snapshot.get("selection_targets") or {})
    selected_entries: list[dict[str, Any]] = []
    near_miss_entries: list[dict[str, Any]] = []
    for ticker, evaluation in selection_targets.items():
        short_trade = dict((evaluation or {}).get("short_trade") or {})
        if not short_trade:
            continue
        decision = str(short_trade.get("decision") or "unknown")
        if decision not in {"selected", "near_miss"}:
            continue
        runtime_prior = dict(runtime_5d_prior_by_ticker.get(str(ticker)) or {})
        if not runtime_prior:
            continue
        candidate_source = str((evaluation or {}).get("candidate_source") or dict(short_trade.get("explainability_payload") or {}).get("candidate_source") or "unknown")
        entry = {
            "ticker": str(ticker),
            "decision": decision,
            "candidate_source": candidate_source,
            "score_target": _round_or_none(_safe_float(short_trade.get("score_target"))),
            "historical_prior": runtime_prior,
        }
        if decision == "selected":
            selected_entries.append(entry)
        else:
            near_miss_entries.append(entry)

    if not selected_entries and not near_miss_entries:
        return []

    previous = os.getenv("BTST_PAYOFF_REVIEW_LANE_MODE")
    os.environ["BTST_PAYOFF_REVIEW_LANE_MODE"] = "report"
    try:
        return build_payoff_review_entries(
            selected_entries=selected_entries,
            near_miss_entries=near_miss_entries,
            max_entries=max_entries,
        )
    finally:
        if previous is None:
            os.environ.pop("BTST_PAYOFF_REVIEW_LANE_MODE", None)
        else:
            os.environ["BTST_PAYOFF_REVIEW_LANE_MODE"] = previous


def analyze_btst_5d_15pct_objective_monitor(
    reports_root: str | Path,
    *,
    report_name_contains: str = "paper_trading_window",
    objective_hit_rate_target: float = 0.55,
    max_future_high_return_target: float = 0.15,
    leaderboard_min_closed_cycle_count: int = 2,
    payoff_review_surface_source: str = "brief",
) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    report_dirs = discover_report_dirs([resolved_reports_root], report_name_contains=report_name_contains)
    price_cache: dict[tuple[str, str], Any] = {}
    rows: list[dict[str, Any]] = []
    payoff_review_rows: list[dict[str, Any]] = []

    runtime_5d_prior_by_ticker: dict[str, dict[str, Any]] = {}
    if payoff_review_surface_source == "runtime_5d":
        runtime_5d_prior_by_ticker = _load_btst_runtime_5d_prior_by_ticker(resolved_reports_root)

    for report_dir in report_dirs:
        for snapshot in _iter_selection_snapshots(report_dir) or []:
            trade_date = _normalize_trade_date(snapshot.get("trade_date"))
            for ticker, evaluation in dict(snapshot.get("selection_targets") or {}).items():
                short_trade = dict((evaluation or {}).get("short_trade") or {})
                if not short_trade:
                    continue
                price_outcome = _extract_btst_price_outcome(str(ticker), trade_date, price_cache)
                candidate_source = str((evaluation or {}).get("candidate_source") or dict(short_trade.get("explainability_payload") or {}).get("candidate_source") or "unknown")
                rows.append(
                    {
                        "report_dir_name": report_dir.name,
                        "trade_date": trade_date,
                        "ticker": str(ticker),
                        "decision": str(short_trade.get("decision") or "unknown"),
                        "candidate_source": candidate_source,
                        "score_target": _round_or_none(_safe_float(short_trade.get("score_target"))),
                        "preferred_entry_mode": short_trade.get("preferred_entry_mode"),
                        **price_outcome,
                    }
                )

            if payoff_review_surface_source == "runtime_5d" and runtime_5d_prior_by_ticker:
                runtime_entries = _build_payoff_review_entries_from_snapshot(
                    snapshot,
                    runtime_5d_prior_by_ticker=runtime_5d_prior_by_ticker,
                )
                for entry in runtime_entries:
                    ticker = str((entry or {}).get("ticker") or "").strip()
                    if not ticker:
                        continue
                    price_outcome = _extract_btst_price_outcome(ticker, trade_date, price_cache)
                    payoff_review_rows.append(
                        {
                            "report_dir_name": report_dir.name,
                            "trade_date": trade_date,
                            "ticker": ticker,
                            "decision": str((entry or {}).get("decision") or "unknown"),
                            "candidate_source": str((entry or {}).get("candidate_source") or "unknown"),
                            "score_target": _round_or_none(_safe_float((entry or {}).get("score_target"))),
                            "payoff_review_lane_score": _round_or_none(_safe_float((entry or {}).get("payoff_review_lane_score"))),
                            **price_outcome,
                        }
                    )

        if payoff_review_surface_source != "runtime_5d":
            brief = _load_btst_brief(report_dir)
            payoff_entries = list(brief.get("payoff_review_entries") or [])
            if payoff_entries:
                trade_date = _normalize_trade_date(brief.get("trade_date"))
                for entry in payoff_entries:
                    entry_row = dict(entry or {})
                    ticker = str(entry_row.get("ticker") or "").strip()
                    if not ticker:
                        continue
                    price_outcome = _extract_btst_price_outcome(ticker, trade_date, price_cache)
                    payoff_review_rows.append(
                        {
                            "report_dir_name": report_dir.name,
                            "trade_date": trade_date,
                            "ticker": ticker,
                            "decision": str(entry_row.get("decision") or "unknown"),
                            "candidate_source": str(entry_row.get("candidate_source") or "unknown"),
                            "score_target": _round_or_none(_safe_float(entry_row.get("score_target"))),
                            "payoff_review_lane_score": _round_or_none(_safe_float(entry_row.get("payoff_review_lane_score"))),
                            **price_outcome,
                        }
                    )

    rows.sort(
        key=lambda row: (
            float(row.get("max_future_high_return_2_5d") if row.get("max_future_high_return_2_5d") is not None else -999.0),
            float(row.get("score_target") if row.get("score_target") is not None else -999.0),
            str(row.get("trade_date") or ""),
            str(row.get("ticker") or ""),
        ),
        reverse=True,
    )
    raw_row_count = len(rows)
    rows, duplicate_row_count = _deduplicate_rows(rows)
    decision_counts = Counter(str(row.get("decision") or "unknown") for row in rows)
    candidate_source_counts = Counter(str(row.get("candidate_source") or "unknown") for row in rows)
    cycle_status_counts = Counter(str(row.get("cycle_status") or "unknown") for row in rows)

    tradeable_rows = [row for row in rows if row.get("decision") in {"selected", "near_miss"}]
    selected_rows = [row for row in rows if row.get("decision") == "selected"]
    near_miss_rows = [row for row in rows if row.get("decision") == "near_miss"]
    non_tradeable_rows = [row for row in rows if row.get("decision") in {"blocked", "rejected"}]
    strict_goal_rows = [row for row in rows if row.get("max_future_high_return_2_5d") is not None and float(row.get("max_future_high_return_2_5d") or -999.0) >= max_future_high_return_target]
    false_negative_strict_goal_rows = [row for row in strict_goal_rows if row.get("decision") in {"blocked", "rejected"}]

    analysis = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "reports_root": str(resolved_reports_root),
        "report_dir_count": len(report_dirs),
        "report_dirs": [str(path) for path in report_dirs],
        "objective_hit_rate_target": objective_hit_rate_target,
        "max_future_high_return_2_5d_target": max_future_high_return_target,
        "leaderboard_min_closed_cycle_count": leaderboard_min_closed_cycle_count,
        "payoff_review_surface_source": payoff_review_surface_source,
        "raw_row_count": raw_row_count,
        "row_count": len(rows),
        "duplicate_row_count": duplicate_row_count,
        "decision_counts": dict(decision_counts),
        "candidate_source_counts": dict(candidate_source_counts),
        "cycle_status_counts": dict(cycle_status_counts),
        "all_surface": _surface_summary(rows, objective_hit_rate_target=objective_hit_rate_target, return_target=max_future_high_return_target),
        "tradeable_surface": _surface_summary(tradeable_rows, objective_hit_rate_target=objective_hit_rate_target, return_target=max_future_high_return_target),
        "selected_surface": _surface_summary(selected_rows, objective_hit_rate_target=objective_hit_rate_target, return_target=max_future_high_return_target),
        "near_miss_surface": _surface_summary(near_miss_rows, objective_hit_rate_target=objective_hit_rate_target, return_target=max_future_high_return_target),
        "non_tradeable_surface": _surface_summary(non_tradeable_rows, objective_hit_rate_target=objective_hit_rate_target, return_target=max_future_high_return_target),
        "payoff_review_surface": _surface_summary(payoff_review_rows, objective_hit_rate_target=objective_hit_rate_target, return_target=max_future_high_return_target),
        "decision_leaderboard": _group_leaderboard(rows, group_key="decision", objective_hit_rate_target=objective_hit_rate_target, return_target=max_future_high_return_target, min_closed_cycle_count=leaderboard_min_closed_cycle_count)[:6],
        "candidate_source_leaderboard": _group_leaderboard(rows, group_key="candidate_source", objective_hit_rate_target=objective_hit_rate_target, return_target=max_future_high_return_target, min_closed_cycle_count=leaderboard_min_closed_cycle_count)[:8],
        "ticker_leaderboard": _group_leaderboard(rows, group_key="ticker", objective_hit_rate_target=objective_hit_rate_target, return_target=max_future_high_return_target, min_closed_cycle_count=leaderboard_min_closed_cycle_count)[:8],
        "strict_goal_rows": strict_goal_rows[:10],
        "false_negative_strict_goal_rows": false_negative_strict_goal_rows[:10],
        "payoff_review_rows": payoff_review_rows[:10],
    }
    analysis["recommendation"] = _recommendation(
        tradeable_surface=dict(analysis.get("tradeable_surface") or {}),
        decision_leaderboard=list(analysis.get("decision_leaderboard") or []),
        ticker_leaderboard=list(analysis.get("ticker_leaderboard") or []),
        false_negative_rows=list(analysis.get("false_negative_strict_goal_rows") or []),
    )
    return analysis


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor how far BTST is from the 5-day +15% runner objective.")
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--report-name-contains", default="paper_trading_window")
    parser.add_argument("--objective-hit-rate-target", type=float, default=0.55)
    parser.add_argument("--max-future-high-return-target", type=float, default=0.15)
    parser.add_argument("--leaderboard-min-closed-cycle-count", type=int, default=2)
    parser.add_argument(
        "--payoff-review-surface-source",
        default="brief",
        choices=["brief", "runtime_5d"],
        help="How to build payoff_review_surface: from saved briefs (brief) or recompute per snapshot using runtime 5D priors (runtime_5d).",
    )
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_5d_15pct_objective_monitor(
        args.reports_root,
        report_name_contains=str(args.report_name_contains or "paper_trading_window"),
        objective_hit_rate_target=float(args.objective_hit_rate_target),
        max_future_high_return_target=float(args.max_future_high_return_target),
        leaderboard_min_closed_cycle_count=int(args.leaderboard_min_closed_cycle_count),
        payoff_review_surface_source=str(args.payoff_review_surface_source or "brief"),
    )

    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_5d_15pct_objective_monitor_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
