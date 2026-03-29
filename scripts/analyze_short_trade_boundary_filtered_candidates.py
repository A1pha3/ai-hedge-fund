from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.short_trade_boundary_analysis_utils import (
    classify_boundary_candidate,
    collect_candidate_rows,
    default_boundary_thresholds,
    parse_candidate_sources,
)


def render_short_trade_boundary_filtered_candidates_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Short Trade Boundary Filtered Candidate Review")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- report_dir: {analysis['report_dir']}")
    lines.append(f"- candidate_sources_filter: {analysis['candidate_sources_filter']}")
    lines.append(f"- thresholds: {analysis['thresholds']}")
    lines.append(f"- total_candidate_count: {analysis['total_candidate_count']}")
    lines.append(f"- qualified_candidate_count: {analysis['qualified_candidate_count']}")
    lines.append(f"- filtered_candidate_count: {analysis['filtered_candidate_count']}")
    lines.append(f"- filtered_reason_counts: {analysis['filtered_reason_counts']}")
    lines.append("")
    lines.append("## Closest To Pass")
    for row in analysis["closest_to_pass_rows"]:
        lines.append(
            f"- {row['trade_date']} {row['ticker']}: primary_reason={row['primary_reason']}, total_shortfall={row['total_shortfall']}, failed_thresholds={row['failed_thresholds']}, next_high_return={row['next_high_return']}, next_close_return={row['next_close_return']}"
        )
    lines.append("")
    lines.append("## Qualified Top Cases")
    for row in analysis["qualified_top_cases"]:
        lines.append(
            f"- {row['trade_date']} {row['ticker']}: candidate_score={row['candidate_score']}, next_high_return={row['next_high_return']}, next_close_return={row['next_close_return']}"
        )
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def analyze_short_trade_boundary_filtered_candidates(
    report_dir: str | Path,
    *,
    candidate_sources: set[str] | None = None,
    thresholds: dict[str, float] | None = None,
    top_n: int = 8,
    next_high_hit_threshold: float = 0.02,
) -> dict[str, Any]:
    resolved_thresholds = dict(default_boundary_thresholds())
    if thresholds:
        resolved_thresholds.update({key: round(float(value), 4) for key, value in thresholds.items()})

    candidate_payload = collect_candidate_rows(
        report_dir,
        candidate_sources=candidate_sources,
        next_high_hit_threshold=next_high_hit_threshold,
    )
    rows = list(candidate_payload["rows"])
    filtered_rows: list[dict[str, Any]] = []
    qualified_rows: list[dict[str, Any]] = []
    filtered_reason_counts: Counter[str] = Counter()

    for row in rows:
        classification = classify_boundary_candidate(row, resolved_thresholds)
        enriched_row = {**row, **classification}
        if classification["qualified"]:
            qualified_rows.append(enriched_row)
            continue
        filtered_reason_counts[str(classification["primary_reason"])] += 1
        filtered_rows.append(enriched_row)

    closest_to_pass_rows = sorted(
        [row for row in filtered_rows if row.get("total_shortfall") is not None],
        key=lambda row: (
            float(row.get("total_shortfall") or 999.0),
            int(row.get("failed_threshold_count") or 999),
            -float(row.get("next_high_return") or -999.0),
            -float(row.get("next_close_return") or -999.0),
            str(row.get("trade_date") or ""),
            str(row.get("ticker") or ""),
        ),
    )[:top_n]
    qualified_top_cases = sorted(
        qualified_rows,
        key=lambda row: (
            float(row.get("next_high_return") or -999.0),
            float(row.get("next_close_return") or -999.0),
            float(row.get("candidate_score") or 0.0),
        ),
        reverse=True,
    )[:top_n]

    if closest_to_pass_rows:
        first_row = closest_to_pass_rows[0]
        recommendation = (
            f"当前最接近放行的是 {first_row['trade_date']} / {first_row['ticker']}，"
            f"primary_reason={first_row['primary_reason']}，total_shortfall={first_row['total_shortfall']}。"
        )
    elif qualified_rows:
        recommendation = "当前候选池里的样本都已通过现有 boundary floor，没有额外 edge candidate 需要审查。"
    else:
        recommendation = "当前候选池里没有通过现有 floor 的样本，也没有可用于做边缘放行判断的明细。"

    return {
        "report_dir": candidate_payload["report_dir"],
        "candidate_sources_filter": candidate_payload["candidate_sources_filter"],
        "thresholds": resolved_thresholds,
        "total_candidate_count": len(rows),
        "qualified_candidate_count": len(qualified_rows),
        "filtered_candidate_count": len(filtered_rows),
        "data_status_counts": candidate_payload["data_status_counts"],
        "candidate_source_counts": candidate_payload["candidate_source_counts"],
        "filtered_reason_counts": dict(filtered_reason_counts.most_common()),
        "closest_to_pass_rows": closest_to_pass_rows,
        "qualified_top_cases": qualified_top_cases,
        "rows": filtered_rows,
        "recommendation": recommendation,
    }


def main() -> None:
    defaults = default_boundary_thresholds()
    parser = argparse.ArgumentParser(description="Inspect filtered short-trade boundary candidates and rank the closest-to-pass rows.")
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--candidate-sources", default="layer_b_boundary")
    parser.add_argument("--candidate-score-min", type=float, default=defaults["candidate_score_min"])
    parser.add_argument("--breakout-min", type=float, default=defaults["breakout_freshness_min"])
    parser.add_argument("--trend-min", type=float, default=defaults["trend_acceleration_min"])
    parser.add_argument("--volume-min", type=float, default=defaults["volume_expansion_quality_min"])
    parser.add_argument("--catalyst-min", type=float, default=defaults["catalyst_freshness_min"])
    parser.add_argument("--top-n", type=int, default=8)
    parser.add_argument("--next-high-hit-threshold", type=float, default=0.02)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    analysis = analyze_short_trade_boundary_filtered_candidates(
        args.report_dir,
        candidate_sources=parse_candidate_sources(args.candidate_sources),
        thresholds={
            "candidate_score_min": float(args.candidate_score_min),
            "breakout_freshness_min": float(args.breakout_min),
            "trend_acceleration_min": float(args.trend_min),
            "volume_expansion_quality_min": float(args.volume_min),
            "catalyst_freshness_min": float(args.catalyst_min),
        },
        top_n=int(args.top_n),
        next_high_hit_threshold=float(args.next_high_hit_threshold),
    )
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_short_trade_boundary_filtered_candidates_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()