from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

from scripts.btst_analysis_utils import (
    extract_btst_price_outcome as _extract_btst_price_outcome,
    iter_selection_snapshots as _iter_selection_snapshots,
    normalize_trade_date as _normalize_trade_date,
    round_or_none as _round_or_none,
    safe_float as _safe_float,
)
from scripts.btst_report_utils import discover_nested_report_dirs as discover_report_dirs


REPORTS_DIR = Path("data/reports")
DEFAULT_REPORTS_ROOT = REPORTS_DIR
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_tplus1_tplus2_objective_monitor_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_tplus1_tplus2_objective_monitor_latest.md"


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


def _objective_fit_score(*, positive_rate: float | None, return_hit_rate: float | None, mean_return: float | None, positive_rate_target: float, return_target: float) -> float:
    positive_component = 0.0 if positive_rate is None else min(float(positive_rate) / positive_rate_target, 1.0)
    hit_component = 0.0 if return_hit_rate is None else min(float(return_hit_rate) / positive_rate_target, 1.0)
    payoff_component = 0.0 if mean_return is None else min(float(mean_return) / return_target, 1.0)
    return round((positive_component * 0.35) + (hit_component * 0.45) + (payoff_component * 0.20), 4)


def _surface_summary(
    rows: list[dict[str, Any]],
    *,
    positive_rate_target: float,
    return_target: float,
) -> dict[str, Any]:
    closed_rows = [row for row in rows if row.get("t_plus_2_close_return") is not None]
    returns = [float(row["t_plus_2_close_return"]) for row in closed_rows]
    positive_count = sum(1 for value in returns if value > 0)
    return_hit_count = sum(1 for value in returns if value >= return_target)
    positive_rate = _rate(positive_count, len(closed_rows))
    return_hit_rate = _rate(return_hit_count, len(closed_rows))
    mean_return = round(mean(returns), 4) if returns else None
    verdict = "insufficient_closed_cycle_samples"
    if closed_rows:
        if positive_rate is not None and return_hit_rate is not None and positive_rate >= positive_rate_target and return_hit_rate >= positive_rate_target:
            verdict = "meets_strict_btst_objective"
        elif positive_rate is not None and positive_rate >= positive_rate_target:
            verdict = "meets_win_rate_only"
        elif return_hit_rate is not None and return_hit_rate >= positive_rate_target:
            verdict = "meets_payoff_hit_rate_only"
        else:
            verdict = "below_strict_btst_objective"
    objective_fit_score = _objective_fit_score(
        positive_rate=positive_rate,
        return_hit_rate=return_hit_rate,
        mean_return=mean_return,
        positive_rate_target=positive_rate_target,
        return_target=return_target,
    )
    return {
        "closed_cycle_count": len(closed_rows),
        "t_plus_2_close_return_distribution": _summarize_distribution(returns),
        "t_plus_2_positive_rate": positive_rate,
        "t_plus_2_return_hit_rate_at_target": return_hit_rate,
        "t_plus_2_positive_rate_target": positive_rate_target,
        "t_plus_2_return_target": return_target,
        "t_plus_2_positive_count": positive_count,
        "t_plus_2_return_hit_count": return_hit_count,
        "mean_t_plus_2_return": mean_return,
        "objective_fit_score": objective_fit_score,
        "objective_gap": {
            "positive_rate_gap": None if positive_rate is None else round(positive_rate_target - positive_rate, 4),
            "return_hit_rate_gap": None if return_hit_rate is None else round(positive_rate_target - return_hit_rate, 4),
            "mean_return_gap": None if mean_return is None else round(return_target - mean_return, 4),
        },
        "verdict": verdict,
    }


def _group_leaderboard(
    rows: list[dict[str, Any]],
    *,
    group_key: str,
    positive_rate_target: float,
    return_target: float,
    min_closed_cycle_count: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        label = str(row.get(group_key) or "unknown")
        grouped[label].append(row)

    leaderboard: list[dict[str, Any]] = []
    for label, group_rows in grouped.items():
        summary = _surface_summary(group_rows, positive_rate_target=positive_rate_target, return_target=return_target)
        if int(summary.get("closed_cycle_count") or 0) < min_closed_cycle_count:
            continue
        leaderboard.append(
            {
                "group_key": group_key,
                "group_label": label,
                "row_count": len(group_rows),
                **summary,
            }
        )

    leaderboard.sort(
        key=lambda row: (
            float(row.get("objective_fit_score") or -999.0),
            float(row.get("t_plus_2_return_hit_rate_at_target") or -999.0),
            float(row.get("t_plus_2_positive_rate") or -999.0),
            float(row.get("mean_t_plus_2_return") or -999.0),
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
            row.get("t_plus_2_close_return"),
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
        return "当前 tradeable surface 已达到严格 BTST 目标，可把后续优化重心转向扩大相同结构样本，而不是继续压低准入。"

    best_decision = decision_leaderboard[0] if decision_leaderboard else {}
    best_ticker = ticker_leaderboard[0] if ticker_leaderboard else {}
    if false_negative_rows:
        return (
            "当前没有任何稳定车道达到 80% 胜率与 5% 收益目标；优先做两件事："
            f"第一，围绕 {best_decision.get('group_label') or '当前最优决策层'} 提升可交易面；"
            f"第二，复盘 {false_negative_rows[0].get('ticker') or '最高优先级 false negative'} 这类已命中 5% 目标却未放行的样本。"
        )
    if best_ticker:
        return (
            "当前没有任何稳定车道达到 80% 胜率与 5% 收益目标；"
            f"最接近目标的是 {best_ticker.get('group_label')}，但仍应先累积更多 closed-cycle 样本，再考虑升级。"
        )
    return "当前 closed-cycle 证据不足或整体未达标，默认结论应继续保持观察优先，不应为了覆盖而主动放松执行阈值。"


def _append_objective_monitor_overview_markdown(lines: list[str], analysis: dict[str, Any]) -> None:
    lines.append("## Objective")
    for key in (
        "generated_at",
        "reports_root",
        "report_dir_count",
        "positive_rate_target",
        "t_plus_2_return_target",
        "leaderboard_min_closed_cycle_count",
    ):
        lines.append(f"- {key}: {analysis.get(key)}")
    lines.append("")


def _append_objective_monitor_surface_summary_markdown(lines: list[str], analysis: dict[str, Any]) -> None:
    lines.append("## Surface Summary")
    for label in ("all_surface", "tradeable_surface", "selected_surface", "near_miss_surface", "non_tradeable_surface"):
        summary = dict(analysis.get(label) or {})
        lines.append(
            f"- {label}: closed_cycle_count={summary.get('closed_cycle_count')}, positive_rate={summary.get('t_plus_2_positive_rate')}, return_hit_rate={summary.get('t_plus_2_return_hit_rate_at_target')}, mean_t_plus_2_return={summary.get('mean_t_plus_2_return')}, verdict={summary.get('verdict')}, objective_fit_score={summary.get('objective_fit_score')}"
        )
    lines.append("")


def _append_objective_monitor_leaderboard_markdown(lines: list[str], title: str, rows: list[dict[str, Any]]) -> None:
    lines.append(f"## {title}")
    for row in rows:
        lines.append(
            f"- {row.get('group_label')}: closed_cycle_count={row.get('closed_cycle_count')}, positive_rate={row.get('t_plus_2_positive_rate')}, return_hit_rate={row.get('t_plus_2_return_hit_rate_at_target')}, mean_t_plus_2_return={row.get('mean_t_plus_2_return')}, verdict={row.get('verdict')}, objective_fit_score={row.get('objective_fit_score')}"
        )
    if not rows:
        lines.append("- none")
    lines.append("")


def _append_objective_monitor_goal_rows_markdown(lines: list[str], title: str, rows: list[dict[str, Any]]) -> None:
    lines.append(f"## {title}")
    for row in rows:
        lines.append(
            f"- {row.get('trade_date')} {row.get('ticker')}: decision={row.get('decision')}, source={row.get('candidate_source')}, t_plus_2_close_return={row.get('t_plus_2_close_return')}, score_target={row.get('score_target')}"
        )
    if not rows:
        lines.append("- none")
    lines.append("")


def _append_objective_monitor_recommendation_markdown(lines: list[str], analysis: dict[str, Any]) -> None:
    lines.append("## Recommendation")
    lines.append(f"- {analysis.get('recommendation')}")
    lines.append("")


def render_btst_tplus1_tplus2_objective_monitor_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST T+1 Buy / T+2 Sell Objective Monitor")
    lines.append("")
    _append_objective_monitor_overview_markdown(lines, analysis)
    _append_objective_monitor_surface_summary_markdown(lines, analysis)
    _append_objective_monitor_leaderboard_markdown(lines, "Decision Leaderboard", list(analysis.get("decision_leaderboard") or []))
    _append_objective_monitor_leaderboard_markdown(lines, "Candidate Source Leaderboard", list(analysis.get("candidate_source_leaderboard") or []))
    _append_objective_monitor_leaderboard_markdown(lines, "Ticker Leaderboard", list(analysis.get("ticker_leaderboard") or []))
    _append_objective_monitor_goal_rows_markdown(lines, "Strict Goal Cases", list(analysis.get("strict_goal_rows") or []))
    _append_objective_monitor_goal_rows_markdown(lines, "False Negative Strict Goal Cases", list(analysis.get("false_negative_strict_goal_rows") or []))
    _append_objective_monitor_recommendation_markdown(lines, analysis)
    return "\n".join(lines)


def analyze_btst_tplus1_tplus2_objective_monitor(
    reports_root: str | Path,
    *,
    report_name_contains: str = "paper_trading_window",
    positive_rate_target: float = 0.8,
    t_plus_2_return_target: float = 0.05,
    leaderboard_min_closed_cycle_count: int = 2,
) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    report_dirs = discover_report_dirs([resolved_reports_root], report_name_contains=report_name_contains)
    price_cache: dict[tuple[str, str], Any] = {}
    rows: list[dict[str, Any]] = []

    for report_dir in report_dirs:
        for snapshot in _iter_selection_snapshots(report_dir) or []:
            trade_date = _normalize_trade_date(snapshot.get("trade_date"))
            for ticker, evaluation in dict(snapshot.get("selection_targets") or {}).items():
                short_trade = dict((evaluation or {}).get("short_trade") or {})
                if not short_trade:
                    continue
                price_outcome = _extract_btst_price_outcome(str(ticker), trade_date, price_cache)
                candidate_source = str((evaluation or {}).get("candidate_source") or dict(short_trade.get("explainability_payload") or {}).get("candidate_source") or "unknown")
                row = {
                    "report_dir_name": report_dir.name,
                    "trade_date": trade_date,
                    "ticker": str(ticker),
                    "decision": str(short_trade.get("decision") or "unknown"),
                    "candidate_source": candidate_source,
                    "score_target": _round_or_none(_safe_float(short_trade.get("score_target"))),
                    "preferred_entry_mode": short_trade.get("preferred_entry_mode"),
                    **price_outcome,
                }
                rows.append(row)

    rows.sort(
        key=lambda row: (
            float(row.get("t_plus_2_close_return") if row.get("t_plus_2_close_return") is not None else -999.0),
            float(row.get("score_target") if row.get("score_target") is not None else -999.0),
            str(row.get("trade_date") or ""),
            str(row.get("ticker") or ""),
        ),
        reverse=True,
    )
    raw_row_count = len(rows)
    rows, duplicate_row_count = _deduplicate_rows(rows)
    deduplicated_decision_counts = Counter(str(row.get("decision") or "unknown") for row in rows)
    deduplicated_candidate_source_counts = Counter(str(row.get("candidate_source") or "unknown") for row in rows)
    deduplicated_cycle_status_counts = Counter(str(row.get("cycle_status") or "unknown") for row in rows)

    tradeable_rows = [row for row in rows if row.get("decision") in {"selected", "near_miss"}]
    selected_rows = [row for row in rows if row.get("decision") == "selected"]
    near_miss_rows = [row for row in rows if row.get("decision") == "near_miss"]
    non_tradeable_rows = [row for row in rows if row.get("decision") in {"blocked", "rejected"}]
    strict_goal_rows = [row for row in rows if row.get("t_plus_2_close_return") is not None and float(row.get("t_plus_2_close_return") or -999.0) >= t_plus_2_return_target]
    false_negative_strict_goal_rows = [row for row in strict_goal_rows if row.get("decision") in {"blocked", "rejected"}]

    analysis = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "reports_root": str(resolved_reports_root),
        "report_dir_count": len(report_dirs),
        "report_dirs": [str(path) for path in report_dirs],
        "positive_rate_target": positive_rate_target,
        "t_plus_2_return_target": t_plus_2_return_target,
        "leaderboard_min_closed_cycle_count": leaderboard_min_closed_cycle_count,
        "raw_row_count": raw_row_count,
        "row_count": len(rows),
        "duplicate_row_count": duplicate_row_count,
        "decision_counts": dict(deduplicated_decision_counts),
        "candidate_source_counts": dict(deduplicated_candidate_source_counts),
        "cycle_status_counts": dict(deduplicated_cycle_status_counts),
        "all_surface": _surface_summary(rows, positive_rate_target=positive_rate_target, return_target=t_plus_2_return_target),
        "tradeable_surface": _surface_summary(tradeable_rows, positive_rate_target=positive_rate_target, return_target=t_plus_2_return_target),
        "selected_surface": _surface_summary(selected_rows, positive_rate_target=positive_rate_target, return_target=t_plus_2_return_target),
        "near_miss_surface": _surface_summary(near_miss_rows, positive_rate_target=positive_rate_target, return_target=t_plus_2_return_target),
        "non_tradeable_surface": _surface_summary(non_tradeable_rows, positive_rate_target=positive_rate_target, return_target=t_plus_2_return_target),
        "decision_leaderboard": _group_leaderboard(
            rows,
            group_key="decision",
            positive_rate_target=positive_rate_target,
            return_target=t_plus_2_return_target,
            min_closed_cycle_count=leaderboard_min_closed_cycle_count,
        )[:6],
        "candidate_source_leaderboard": _group_leaderboard(
            rows,
            group_key="candidate_source",
            positive_rate_target=positive_rate_target,
            return_target=t_plus_2_return_target,
            min_closed_cycle_count=leaderboard_min_closed_cycle_count,
        )[:8],
        "ticker_leaderboard": _group_leaderboard(
            rows,
            group_key="ticker",
            positive_rate_target=positive_rate_target,
            return_target=t_plus_2_return_target,
            min_closed_cycle_count=leaderboard_min_closed_cycle_count,
        )[:8],
        "strict_goal_rows": strict_goal_rows[:10],
        "false_negative_strict_goal_rows": false_negative_strict_goal_rows[:10],
    }
    analysis["recommendation"] = _recommendation(
        tradeable_surface=dict(analysis.get("tradeable_surface") or {}),
        decision_leaderboard=list(analysis.get("decision_leaderboard") or []),
        ticker_leaderboard=list(analysis.get("ticker_leaderboard") or []),
        false_negative_rows=list(analysis.get("false_negative_strict_goal_rows") or []),
    )
    return analysis


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor how far BTST is from the T+1 buy / T+2 sell objective of high win rate and 5% payoff.")
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--report-name-contains", default="paper_trading_window")
    parser.add_argument("--positive-rate-target", type=float, default=0.8)
    parser.add_argument("--t-plus-2-return-target", type=float, default=0.05)
    parser.add_argument("--leaderboard-min-closed-cycle-count", type=int, default=2)
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_tplus1_tplus2_objective_monitor(
        args.reports_root,
        report_name_contains=str(args.report_name_contains or "paper_trading_window"),
        positive_rate_target=float(args.positive_rate_target),
        t_plus_2_return_target=float(args.t_plus_2_return_target),
        leaderboard_min_closed_cycle_count=int(args.leaderboard_min_closed_cycle_count),
    )

    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_tplus1_tplus2_objective_monitor_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
