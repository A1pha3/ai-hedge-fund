from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any

import scripts.btst_analysis_utils as btst_utils


DEFAULT_REPORTS_DIR = Path("data/reports")
DEFAULT_DOSSIER_PATH = DEFAULT_REPORTS_DIR / "btst_candidate_pool_recall_dossier_latest.json"
DEFAULT_OBJECTIVE_MONITOR_PATH = DEFAULT_REPORTS_DIR / "btst_tplus1_tplus2_objective_monitor_latest.json"
DEFAULT_OUTPUT_JSON = DEFAULT_REPORTS_DIR / "btst_candidate_pool_lane_objective_support_latest.json"
DEFAULT_OUTPUT_MD = DEFAULT_REPORTS_DIR / "btst_candidate_pool_lane_objective_support_latest.md"
DEFAULT_NEXT_HIGH_HIT_THRESHOLD = 0.02
DEFAULT_T_PLUS_2_RETURN_TARGET = 0.05
DEFAULT_POSITIVE_RATE_TARGET = 0.8


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _rate(hit_count: int, total_count: int) -> float | None:
    if total_count <= 0:
        return None
    return round(hit_count / total_count, 4)


def _round_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 4)


def _objective_fit_score(*, positive_rate: float | None, return_hit_rate: float | None, mean_return: float | None, positive_rate_target: float, return_target: float) -> float:
    positive_component = 0.0 if positive_rate is None else min(float(positive_rate) / positive_rate_target, 1.0)
    hit_component = 0.0 if return_hit_rate is None else min(float(return_hit_rate) / positive_rate_target, 1.0)
    payoff_component = 0.0 if mean_return is None else min(float(mean_return) / return_target, 1.0)
    return round((positive_component * 0.35) + (hit_component * 0.45) + (payoff_component * 0.20), 4)


def _delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return round(float(left) - float(right), 4)


def _support_rank(verdict: str) -> int:
    order = {
        "candidate_pool_false_negative_outperforms_tradeable_surface": 1,
        "candidate_pool_false_negative_has_positive_post_hoc_edge": 2,
        "candidate_pool_false_negative_beats_non_tradeable_surface_only": 3,
        "weak_post_hoc_edge": 4,
        "insufficient_closed_cycle_samples": 9,
    }
    return int(order.get(str(verdict or ""), 99))


def _build_occurrence_rows(
    dossier: dict[str, Any],
    *,
    handoff: str | None = None,
    tickers: list[str] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    normalized_tickers = {str(ticker).strip() for ticker in list(tickers or []) if str(ticker).strip()}
    price_cache: dict[tuple[str, str], Any] = {}

    for ticker_dossier in list(dossier.get("priority_ticker_dossiers") or []):
        dossier_payload = dict(ticker_dossier or {})
        ticker = str(dossier_payload.get("ticker") or "").strip()
        if not ticker:
            continue
        if normalized_tickers and ticker not in normalized_tickers:
            continue

        liquidity_profile = dict(dossier_payload.get("truncation_liquidity_profile") or {})
        priority_handoff = str(liquidity_profile.get("priority_handoff") or "")
        if handoff and priority_handoff != handoff:
            continue

        for occurrence in list(dossier_payload.get("occurrence_evidence") or []):
            occurrence_payload = dict(occurrence or {})
            if str(occurrence_payload.get("blocking_stage") or "") != "candidate_pool_truncated_after_filters":
                continue
            trade_date = btst_utils.normalize_trade_date(occurrence_payload.get("trade_date"))
            if not trade_date:
                continue
            price_outcome = btst_utils.extract_btst_price_outcome(ticker, trade_date, price_cache)
            rows.append(
                {
                    "ticker": ticker,
                    "trade_date": trade_date,
                    "priority_handoff": priority_handoff,
                    "blocking_stage": occurrence_payload.get("blocking_stage"),
                    "failure_reason": dossier_payload.get("failure_reason"),
                    "next_step": dossier_payload.get("next_step"),
                    "pre_truncation_rank_gap_to_cutoff": occurrence_payload.get("pre_truncation_rank_gap_to_cutoff"),
                    "pre_truncation_avg_amount_share_of_cutoff": occurrence_payload.get("pre_truncation_avg_amount_share_of_cutoff"),
                    "top300_lower_market_cap_hot_peer_count": occurrence_payload.get("top300_lower_market_cap_hot_peer_count"),
                    "estimated_rank_gap_after_rebucket": occurrence_payload.get("estimated_rank_gap_after_rebucket"),
                    "top300_lower_market_cap_hot_peer_examples": list(occurrence_payload.get("top300_lower_market_cap_hot_peer_examples") or []),
                    **price_outcome,
                }
            )

    rows.sort(
        key=lambda row: (
            float(row.get("t_plus_2_close_return") if row.get("t_plus_2_close_return") is not None else -999.0),
            float(row.get("next_high_return") if row.get("next_high_return") is not None else -999.0),
            str(row.get("trade_date") or ""),
            str(row.get("ticker") or ""),
        ),
        reverse=True,
    )
    return rows


def _summarize_rows(
    rows: list[dict[str, Any]],
    *,
    next_high_hit_threshold: float,
    t_plus_2_return_target: float,
    positive_rate_target: float,
    baseline_tradeable_surface: dict[str, Any] | None,
    baseline_non_tradeable_surface: dict[str, Any] | None,
) -> dict[str, Any]:
    next_day_rows = [row for row in rows if row.get("next_high_return") is not None]
    closed_rows = [row for row in rows if row.get("t_plus_2_close_return") is not None]
    next_high_returns = [float(row["next_high_return"]) for row in next_day_rows]
    next_close_returns = [float(row["next_close_return"]) for row in next_day_rows if row.get("next_close_return") is not None]
    t_plus_2_returns = [float(row["t_plus_2_close_return"]) for row in closed_rows]

    next_high_hit_rate = _rate(sum(1 for value in next_high_returns if value >= next_high_hit_threshold), len(next_day_rows))
    next_close_positive_rate = _rate(sum(1 for value in next_close_returns if value > 0), len(next_day_rows))
    t_plus_2_positive_rate = _rate(sum(1 for value in t_plus_2_returns if value > 0), len(closed_rows))
    t_plus_2_return_hit_rate = _rate(sum(1 for value in t_plus_2_returns if value >= t_plus_2_return_target), len(closed_rows))
    mean_t_plus_2_return = round(mean(t_plus_2_returns), 4) if t_plus_2_returns else None
    objective_fit_score = _objective_fit_score(
        positive_rate=t_plus_2_positive_rate,
        return_hit_rate=t_plus_2_return_hit_rate,
        mean_return=mean_t_plus_2_return,
        positive_rate_target=positive_rate_target,
        return_target=t_plus_2_return_target,
    )

    baseline_tradeable_surface = dict(baseline_tradeable_surface or {})
    baseline_non_tradeable_surface = dict(baseline_non_tradeable_surface or {})
    tradeable_positive_rate = baseline_tradeable_surface.get("t_plus_2_positive_rate")
    tradeable_return_hit_rate = baseline_tradeable_surface.get("t_plus_2_return_hit_rate_at_target")
    tradeable_mean_return = baseline_tradeable_surface.get("mean_t_plus_2_return")
    non_tradeable_positive_rate = baseline_non_tradeable_surface.get("t_plus_2_positive_rate")
    non_tradeable_mean_return = baseline_non_tradeable_surface.get("mean_t_plus_2_return")

    if not closed_rows:
        support_verdict = "insufficient_closed_cycle_samples"
    elif (
        tradeable_positive_rate is not None
        and tradeable_mean_return is not None
        and t_plus_2_positive_rate is not None
        and mean_t_plus_2_return is not None
        and t_plus_2_positive_rate >= float(tradeable_positive_rate)
        and mean_t_plus_2_return >= float(tradeable_mean_return)
    ):
        support_verdict = "candidate_pool_false_negative_outperforms_tradeable_surface"
    elif (
        t_plus_2_positive_rate is not None
        and mean_t_plus_2_return is not None
        and t_plus_2_positive_rate >= 0.5
        and mean_t_plus_2_return > 0
    ):
        support_verdict = "candidate_pool_false_negative_has_positive_post_hoc_edge"
    elif (
        non_tradeable_positive_rate is not None
        and non_tradeable_mean_return is not None
        and t_plus_2_positive_rate is not None
        and mean_t_plus_2_return is not None
        and (
            t_plus_2_positive_rate >= float(non_tradeable_positive_rate)
            or mean_t_plus_2_return >= float(non_tradeable_mean_return)
        )
    ):
        support_verdict = "candidate_pool_false_negative_beats_non_tradeable_surface_only"
    else:
        support_verdict = "weak_post_hoc_edge"

    strict_goal_rows = [
        row
        for row in closed_rows
        if row.get("t_plus_2_close_return") is not None and float(row.get("t_plus_2_close_return") or -999.0) >= t_plus_2_return_target
    ]
    return {
        "occurrence_count": len(rows),
        "next_day_available_count": len(next_day_rows),
        "closed_cycle_count": len(closed_rows),
        "next_high_hit_threshold": round(next_high_hit_threshold, 4),
        "next_high_hit_rate_at_threshold": next_high_hit_rate,
        "next_close_positive_rate": next_close_positive_rate,
        "t_plus_2_positive_rate": t_plus_2_positive_rate,
        "t_plus_2_return_hit_rate_at_target": t_plus_2_return_hit_rate,
        "t_plus_2_return_target": round(t_plus_2_return_target, 4),
        "mean_t_plus_2_return": mean_t_plus_2_return,
        "objective_fit_score": objective_fit_score,
        "strict_goal_case_count": len(strict_goal_rows),
        "support_verdict": support_verdict,
        "positive_rate_delta_vs_tradeable_surface": _delta(t_plus_2_positive_rate, btst_utils.safe_float(tradeable_positive_rate)),
        "return_hit_rate_delta_vs_tradeable_surface": _delta(t_plus_2_return_hit_rate, btst_utils.safe_float(tradeable_return_hit_rate)),
        "mean_return_delta_vs_tradeable_surface": _delta(mean_t_plus_2_return, btst_utils.safe_float(tradeable_mean_return)),
        "positive_rate_delta_vs_non_tradeable_surface": _delta(t_plus_2_positive_rate, btst_utils.safe_float(non_tradeable_positive_rate)),
        "mean_return_delta_vs_non_tradeable_surface": _delta(mean_t_plus_2_return, btst_utils.safe_float(non_tradeable_mean_return)),
        "top_strict_goal_rows": [
            {
                "trade_date": row.get("trade_date"),
                "ticker": row.get("ticker"),
                "t_plus_2_close_return": row.get("t_plus_2_close_return"),
                "next_high_return": row.get("next_high_return"),
            }
            for row in strict_goal_rows[:3]
        ],
    }


def _build_ticker_rows(
    rows: list[dict[str, Any]],
    *,
    next_high_hit_threshold: float,
    t_plus_2_return_target: float,
    positive_rate_target: float,
    baseline_tradeable_surface: dict[str, Any] | None,
    baseline_non_tradeable_surface: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    ticker_rows: list[dict[str, Any]] = []
    tickers = sorted({str(row.get("ticker") or "") for row in rows if str(row.get("ticker") or "")})
    for ticker in tickers:
        ticker_occurrences = [row for row in rows if str(row.get("ticker") or "") == ticker]
        summary = _summarize_rows(
            ticker_occurrences,
            next_high_hit_threshold=next_high_hit_threshold,
            t_plus_2_return_target=t_plus_2_return_target,
            positive_rate_target=positive_rate_target,
            baseline_tradeable_surface=baseline_tradeable_surface,
            baseline_non_tradeable_surface=baseline_non_tradeable_surface,
        )
        ticker_rows.append(
            {
                "ticker": ticker,
                "priority_handoff": str(ticker_occurrences[0].get("priority_handoff") or ""),
                **summary,
            }
        )
    ticker_rows.sort(
        key=lambda row: (
            _support_rank(str(row.get("support_verdict") or "")),
            -(float(row.get("objective_fit_score") or -999.0)),
            -(float(row.get("mean_t_plus_2_return") or -999.0)),
            str(row.get("ticker") or ""),
        )
    )
    return ticker_rows


def analyze_btst_candidate_pool_lane_objective_support(
    dossier_path: str | Path,
    *,
    objective_monitor_path: str | Path | None = None,
    next_high_hit_threshold: float = DEFAULT_NEXT_HIGH_HIT_THRESHOLD,
    t_plus_2_return_target: float = DEFAULT_T_PLUS_2_RETURN_TARGET,
    positive_rate_target: float = DEFAULT_POSITIVE_RATE_TARGET,
) -> dict[str, Any]:
    dossier = _load_json(dossier_path)
    objective_monitor: dict[str, Any] = {}
    if objective_monitor_path:
        resolved_objective_path = Path(objective_monitor_path).expanduser().resolve()
        if resolved_objective_path.exists():
            objective_monitor = _load_json(resolved_objective_path)

    baseline_tradeable_surface = dict(objective_monitor.get("tradeable_surface") or {})
    baseline_non_tradeable_surface = dict(objective_monitor.get("non_tradeable_surface") or {})
    branch_rows: list[dict[str, Any]] = []
    all_occurrence_rows: list[dict[str, Any]] = []

    for queue_row in list(dossier.get("priority_handoff_branch_experiment_queue") or []):
        branch = dict(queue_row or {})
        handoff = str(branch.get("priority_handoff") or "")
        occurrences = _build_occurrence_rows(dossier, handoff=handoff, tickers=list(branch.get("tickers") or []))
        all_occurrence_rows.extend(occurrences)
        summary = _summarize_rows(
            occurrences,
            next_high_hit_threshold=next_high_hit_threshold,
            t_plus_2_return_target=t_plus_2_return_target,
            positive_rate_target=positive_rate_target,
            baseline_tradeable_surface=baseline_tradeable_surface,
            baseline_non_tradeable_surface=baseline_non_tradeable_surface,
        )
        branch_rows.append(
            {
                "priority_handoff": handoff,
                "task_id": branch.get("task_id"),
                "prototype_readiness": branch.get("prototype_readiness"),
                "tickers": list(branch.get("tickers") or []),
                "prototype_type": branch.get("prototype_type"),
                "evaluation_summary": branch.get("evaluation_summary"),
                "guardrail_summary": branch.get("guardrail_summary"),
                **summary,
            }
        )

    branch_rows.sort(
        key=lambda row: (
            _support_rank(str(row.get("support_verdict") or "")),
            -(float(row.get("objective_fit_score") or -999.0)),
            -(float(row.get("mean_t_plus_2_return") or -999.0)),
            str(row.get("priority_handoff") or ""),
        )
    )
    for index, row in enumerate(branch_rows, start=1):
        row["objective_priority_rank"] = index

    ticker_rows = _build_ticker_rows(
        all_occurrence_rows,
        next_high_hit_threshold=next_high_hit_threshold,
        t_plus_2_return_target=t_plus_2_return_target,
        positive_rate_target=positive_rate_target,
        baseline_tradeable_surface=baseline_tradeable_surface,
        baseline_non_tradeable_surface=baseline_non_tradeable_surface,
    )

    recommendation = "candidate-pool recall lanes 仍缺足够后验证据，不应仅凭结构解释推进升级。"
    if branch_rows:
        leader = branch_rows[0]
        recommendation = (
            f"当前最值得继续保留在 candidate-pool recall 首位验证的 lane 是 {leader.get('priority_handoff')}，"
            f"因为它的后验 verdict={leader.get('support_verdict')}，"
            f"closed_cycle_count={leader.get('closed_cycle_count')}，mean_t_plus_2_return={leader.get('mean_t_plus_2_return')}。"
        )
        if ticker_rows:
            recommendation = f"{recommendation} 其中优先跟踪 {ticker_rows[0].get('ticker')}。"

    return {
        "generated_at": btst_utils.datetime.now().isoformat(timespec="seconds") if hasattr(btst_utils, "datetime") else None,
        "dossier_path": str(Path(dossier_path).expanduser().resolve()),
        "objective_monitor_path": str(Path(objective_monitor_path).expanduser().resolve()) if objective_monitor_path else None,
        "next_high_hit_threshold": round(next_high_hit_threshold, 4),
        "t_plus_2_return_target": round(t_plus_2_return_target, 4),
        "positive_rate_target": round(positive_rate_target, 4),
        "baseline_tradeable_surface": baseline_tradeable_surface,
        "baseline_non_tradeable_surface": baseline_non_tradeable_surface,
        "branch_rows": branch_rows,
        "ticker_rows": ticker_rows,
        "recommendation": recommendation,
    }


def render_btst_candidate_pool_lane_objective_support_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Candidate Pool Lane Objective Support")
    lines.append("")
    lines.append("## Baseline")
    tradeable = dict(analysis.get("baseline_tradeable_surface") or {})
    lines.append(
        f"- tradeable_surface: closed_cycle_count={tradeable.get('closed_cycle_count')}, positive_rate={tradeable.get('t_plus_2_positive_rate')}, return_hit_rate={tradeable.get('t_plus_2_return_hit_rate_at_target')}, mean_t_plus_2_return={tradeable.get('mean_t_plus_2_return')}, verdict={tradeable.get('verdict')}"
    )
    lines.append("")
    lines.append("## Branch Rows")
    for row in list(analysis.get("branch_rows") or []):
        lines.append(
            f"- rank={row.get('objective_priority_rank')} handoff={row.get('priority_handoff')} verdict={row.get('support_verdict')} closed_cycle_count={row.get('closed_cycle_count')} positive_rate={row.get('t_plus_2_positive_rate')} return_hit_rate={row.get('t_plus_2_return_hit_rate_at_target')} mean_t_plus_2_return={row.get('mean_t_plus_2_return')} delta_vs_tradeable={row.get('mean_return_delta_vs_tradeable_surface')}"
        )
        lines.append(f"  evaluation_summary: {row.get('evaluation_summary')}")
    if not list(analysis.get("branch_rows") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Ticker Rows")
    for row in list(analysis.get("ticker_rows") or []):
        lines.append(
            f"- ticker={row.get('ticker')} handoff={row.get('priority_handoff')} verdict={row.get('support_verdict')} closed_cycle_count={row.get('closed_cycle_count')} positive_rate={row.get('t_plus_2_positive_rate')} return_hit_rate={row.get('t_plus_2_return_hit_rate_at_target')} mean_t_plus_2_return={row.get('mean_t_plus_2_return')}"
        )
    if not list(analysis.get("ticker_rows") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis.get('recommendation')}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure post-hoc BTST T+1/T+2 objective support for candidate-pool recall lanes.")
    parser.add_argument("--dossier-path", default=str(DEFAULT_DOSSIER_PATH))
    parser.add_argument("--objective-monitor-path", default=str(DEFAULT_OBJECTIVE_MONITOR_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_candidate_pool_lane_objective_support(
        args.dossier_path,
        objective_monitor_path=args.objective_monitor_path,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md = Path(args.output_md).expanduser().resolve()
    output_md.write_text(render_btst_candidate_pool_lane_objective_support_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()