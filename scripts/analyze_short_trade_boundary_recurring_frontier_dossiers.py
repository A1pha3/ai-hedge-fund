from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _round(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 4)


def render_short_trade_boundary_recurring_frontier_dossiers_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Recurring Short Trade Boundary Frontier Dossiers")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- recurring_frontier_report: {analysis['recurring_frontier_report']}")
    lines.append(f"- outcome_report: {analysis['outcome_report']}")
    lines.append(f"- ticker_count: {analysis['ticker_count']}")
    lines.append("")
    lines.append("## Dossiers")
    for row in analysis["dossiers"]:
        lines.append(
            f"- {row['ticker']}: priority_rank={row['priority_rank']}, occurrences={row['occurrence_count']}, minimal_adjustment_cost={row['minimal_adjustment_cost']}, next_high_return_mean={row['next_high_return_mean']}, next_close_return_mean={row['next_close_return_mean']}, next_high_hit_rate_at_threshold={row['next_high_hit_rate_at_threshold']}, next_close_positive_rate={row['next_close_positive_rate']}, pattern_label={row['pattern_label']}"
        )
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def analyze_short_trade_boundary_recurring_frontier_dossiers(
    recurring_frontier_report: str | Path,
    outcome_report: str | Path,
) -> dict[str, Any]:
    frontier_analysis = _load_json(recurring_frontier_report)
    outcome_analysis = _load_json(outcome_report)

    outcome_rows = list(outcome_analysis.get("rows") or [])
    outcomes_by_ticker: dict[str, list[dict[str, Any]]] = {}
    for row in outcome_rows:
        ticker = str(row.get("ticker") or "")
        if not ticker:
            continue
        outcomes_by_ticker.setdefault(ticker, []).append(row)

    dossiers: list[dict[str, Any]] = []
    for index, row in enumerate(list(frontier_analysis.get("priority_queue") or []), start=1):
        ticker = str(row.get("ticker") or "")
        matching_outcomes = list(outcomes_by_ticker.get(ticker) or [])
        next_high_returns = [float(item["next_high_return"]) for item in matching_outcomes if item.get("data_status") == "ok"]
        next_close_returns = [float(item["next_close_return"]) for item in matching_outcomes if item.get("data_status") == "ok"]
        next_open_returns = [float(item["next_open_return"]) for item in matching_outcomes if item.get("data_status") == "ok"]
        next_high_hit_threshold = float(outcome_analysis.get("next_high_hit_threshold") or 0.02)
        next_high_hits = sum(1 for value in next_high_returns if value >= next_high_hit_threshold)
        next_close_positive = sum(1 for value in next_close_returns if value > 0)

        if next_high_returns and next_close_returns:
            if mean(next_close_returns) > 0:
                pattern_label = "recurring frontier with close continuation"
            elif mean(next_high_returns) > 0.03:
                pattern_label = "recurring frontier with intraday upside"
            else:
                pattern_label = "recurring frontier with weak follow-through"
        else:
            pattern_label = "recurring frontier without usable outcome bars"

        dossiers.append(
            {
                "ticker": ticker,
                "priority_rank": index,
                "occurrence_count": int(row.get("occurrence_count") or 0),
                "trade_dates": list(row.get("trade_dates") or []),
                "baseline_score_mean": _round(row.get("baseline_score_mean")),
                "gap_to_near_miss_mean": _round(row.get("gap_to_near_miss_mean")),
                "minimal_adjustment_cost": _round(row.get("minimal_adjustment_cost")),
                "max_adjustment_cost": _round(row.get("max_adjustment_cost")),
                "threshold_only_rescue_count": int(row.get("threshold_only_rescue_count") or 0),
                "dominant_pattern": dict(row.get("dominant_pattern") or {}),
                "outcome_sample_count": len(next_high_returns),
                "next_open_return_mean": _round(mean(next_open_returns)) if next_open_returns else None,
                "next_high_return_mean": _round(mean(next_high_returns)) if next_high_returns else None,
                "next_close_return_mean": _round(mean(next_close_returns)) if next_close_returns else None,
                "next_high_hit_rate_at_threshold": _round(next_high_hits / len(next_high_returns)) if next_high_returns else None,
                "next_close_positive_rate": _round(next_close_positive / len(next_close_returns)) if next_close_returns else None,
                "top_outcome_case": max(matching_outcomes, key=lambda item: float(item.get("next_high_return") or -999.0), default=None),
                "worst_close_case": min(matching_outcomes, key=lambda item: float(item.get("next_close_return") or 999.0), default=None),
                "pattern_label": pattern_label,
            }
        )

    if dossiers:
        lead = dossiers[0]
        recommendation = (
            f"当前 recurring frontier 应先看 {lead['ticker']}。它维持 priority_rank=1，"
            f"minimal_adjustment_cost={lead['minimal_adjustment_cost']}，"
            f"同时真实 outcome 模式为 {lead['pattern_label']}。"
        )
    else:
        recommendation = "当前没有可生成 dossier 的 recurring frontier ticker。"

    return {
        "recurring_frontier_report": str(Path(recurring_frontier_report).expanduser().resolve()),
        "outcome_report": str(Path(outcome_report).expanduser().resolve()),
        "ticker_count": len(dossiers),
        "next_high_hit_threshold": _round(outcome_analysis.get("next_high_hit_threshold")),
        "dossiers": dossiers,
        "recommendation": recommendation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Join recurring frontier ranking with ticker-scoped next-day outcomes.")
    parser.add_argument("--recurring-frontier-report", required=True)
    parser.add_argument("--outcome-report", required=True)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    analysis = analyze_short_trade_boundary_recurring_frontier_dossiers(
        args.recurring_frontier_report,
        args.outcome_report,
    )
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_short_trade_boundary_recurring_frontier_dossiers_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()