from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_short_trade_boundary_score_failures import analyze_short_trade_boundary_score_failures


DEFAULT_NEAR_MISS_THRESHOLD = 0.46
DEFAULT_STALE_WEIGHT = 0.12
DEFAULT_OVERHEAD_WEIGHT = 0.1
DEFAULT_EXTENSION_WEIGHT = 0.08
DEFAULT_AVOID_WEIGHT = 1.0


def _parse_float_grid(raw: str, *, allow_none: bool = False) -> list[float | None]:
    values: list[float | None] = []
    for token in str(raw).split(","):
        normalized = token.strip().lower()
        if not normalized:
            continue
        if allow_none and normalized == "none":
            values.append(None)
            continue
        values.append(float(normalized))
    return values


def _round(value: float) -> float:
    return round(float(value), 4)


def _resolve_default_thresholds(row: dict[str, Any]) -> dict[str, float]:
    thresholds = dict(row.get("thresholds") or {})
    return {
        "near_miss_threshold": float(thresholds.get("near_miss_threshold") or DEFAULT_NEAR_MISS_THRESHOLD),
        "stale_score_penalty_weight": float(thresholds.get("stale_score_penalty_weight") or DEFAULT_STALE_WEIGHT),
        "overhead_score_penalty_weight": float(thresholds.get("overhead_score_penalty_weight") or DEFAULT_OVERHEAD_WEIGHT),
        "extension_score_penalty_weight": float(thresholds.get("extension_score_penalty_weight") or DEFAULT_EXTENSION_WEIGHT),
        "layer_c_avoid_penalty": float(thresholds.get("layer_c_avoid_penalty") or DEFAULT_AVOID_WEIGHT),
    }


def _compute_replayed_score(
    *,
    row: dict[str, Any],
    stale_weight: float,
    overhead_weight: float,
    extension_weight: float,
    avoid_weight: float,
) -> float:
    total_positive = float(row.get("total_positive_contribution") or 0.0)
    stale_penalty = float(row.get("stale_trend_repair_penalty") or 0.0) * stale_weight
    overhead_penalty = float(row.get("overhead_supply_penalty") or 0.0) * overhead_weight
    extension_penalty = float(row.get("extension_without_room_penalty") or 0.0) * extension_weight
    avoid_penalty = float(row.get("layer_c_avoid_penalty") or 0.0) * avoid_weight
    return total_positive - stale_penalty - overhead_penalty - extension_penalty - avoid_penalty


def _adjustment_cost(*, default_thresholds: dict[str, float], near_miss_threshold: float, stale_weight: float, extension_weight: float) -> float:
    return _round(
        max(0.0, default_thresholds["near_miss_threshold"] - near_miss_threshold)
        + max(0.0, default_thresholds["stale_score_penalty_weight"] - stale_weight)
        + max(0.0, default_thresholds["extension_score_penalty_weight"] - extension_weight)
    )


def render_short_trade_boundary_score_failure_frontier_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Short Trade Boundary Score-Fail Frontier")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- report_dir: {analysis['report_dir']}")
    lines.append(f"- rejected_short_trade_boundary_count: {analysis['rejected_short_trade_boundary_count']}")
    lines.append(f"- rescueable_case_count: {analysis['rescueable_case_count']}")
    lines.append(f"- rescueable_with_threshold_only_count: {analysis['rescueable_with_threshold_only_count']}")
    lines.append(f"- cost_bucket_counts: {analysis['cost_bucket_counts']}")
    lines.append("")
    lines.append("## Minimal Rescue Rows")
    for row in analysis["minimal_near_miss_rows"]:
        lines.append(
            f"- {row['trade_date']} {row['ticker']}: baseline_score={row['baseline_score_target']}, replayed_score={row['replayed_score_target']}, near_miss_threshold={row['near_miss_threshold']}, stale_weight={row['stale_weight']}, extension_weight={row['extension_weight']}, adjustment_cost={row['adjustment_cost']}"
        )
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def analyze_short_trade_boundary_score_failures_frontier(
    report_dir: str | Path,
    *,
    near_miss_threshold_grid: list[float] | None = None,
    stale_weight_grid: list[float] | None = None,
    extension_weight_grid: list[float] | None = None,
) -> dict[str, Any]:
    base_analysis = analyze_short_trade_boundary_score_failures(report_dir)
    rows = list(base_analysis.get("rows") or [])

    near_miss_values = [float(value) for value in (near_miss_threshold_grid or [0.46, 0.44, 0.42, 0.4, 0.38])]
    stale_values = [float(value) for value in (stale_weight_grid or [0.12, 0.1, 0.08, 0.06, 0.04, 0.02])]
    extension_values = [float(value) for value in (extension_weight_grid or [0.08, 0.06, 0.04, 0.02, 0.0])]

    minimal_rows: list[dict[str, Any]] = []
    for row in rows:
        default_thresholds = _resolve_default_thresholds(row)
        best_row: dict[str, Any] | None = None
        for near_miss_threshold in near_miss_values:
            for stale_weight in stale_values:
                for extension_weight in extension_values:
                    replayed_score = _compute_replayed_score(
                        row=row,
                        stale_weight=stale_weight,
                        overhead_weight=default_thresholds["overhead_score_penalty_weight"],
                        extension_weight=extension_weight,
                        avoid_weight=default_thresholds["layer_c_avoid_penalty"],
                    )
                    if replayed_score < near_miss_threshold:
                        continue
                    candidate = {
                        "trade_date": row["trade_date"],
                        "ticker": row["ticker"],
                        "baseline_score_target": row["score_target"],
                        "replayed_score_target": _round(replayed_score),
                        "gap_to_near_miss_after_replay": _round(near_miss_threshold - replayed_score),
                        "near_miss_threshold": _round(near_miss_threshold),
                        "stale_weight": _round(stale_weight),
                        "extension_weight": _round(extension_weight),
                        "adjustment_cost": _adjustment_cost(
                            default_thresholds=default_thresholds,
                            near_miss_threshold=near_miss_threshold,
                            stale_weight=stale_weight,
                            extension_weight=extension_weight,
                        ),
                    }
                    if best_row is None or (
                        candidate["adjustment_cost"],
                        -candidate["near_miss_threshold"],
                        -candidate["stale_weight"],
                        -candidate["extension_weight"],
                    ) < (
                        best_row["adjustment_cost"],
                        -best_row["near_miss_threshold"],
                        -best_row["stale_weight"],
                        -best_row["extension_weight"],
                    ):
                        best_row = candidate
        if best_row is not None:
            minimal_rows.append(best_row)

    minimal_rows.sort(key=lambda row: (row["adjustment_cost"], row["trade_date"], row["ticker"]))

    cost_bucket_counts = {
        "cost<=0.04": sum(1 for row in minimal_rows if row["adjustment_cost"] <= 0.04),
        "cost<=0.08": sum(1 for row in minimal_rows if row["adjustment_cost"] <= 0.08),
        "cost<=0.12": sum(1 for row in minimal_rows if row["adjustment_cost"] <= 0.12),
        "cost>0.12": sum(1 for row in minimal_rows if row["adjustment_cost"] > 0.12),
    }
    rescueable_with_threshold_only_count = sum(
        1
        for row in minimal_rows
        if row["stale_weight"] == DEFAULT_STALE_WEIGHT and row["extension_weight"] == DEFAULT_EXTENSION_WEIGHT
    )

    if minimal_rows:
        recommendation = (
            f"当前 rejected short_trade_boundary 样本里共有 {len(minimal_rows)}/{len(rows)} 个在扫描空间内存在 near_miss rescue row。"
            f" 其中仅 {rescueable_with_threshold_only_count} 个可以只靠 near_miss threshold 放松获得释放；其余可救样本需要 stale/extension penalty 联动下调，因此后续实验应优先做 score frontier，而不是继续放 admission floor。"
        )
    else:
        recommendation = "当前 rejected short_trade_boundary 样本在给定 threshold/penalty 扫描空间内没有 near_miss rescue row，应优先回到更上游的 score construction 审查。"

    return {
        "report_dir": base_analysis["report_dir"],
        "selection_artifact_root": base_analysis["selection_artifact_root"],
        "rejected_short_trade_boundary_count": len(rows),
        "near_miss_threshold_grid": [float(value) for value in near_miss_values],
        "stale_weight_grid": [float(value) for value in stale_values],
        "extension_weight_grid": [float(value) for value in extension_values],
        "rescueable_case_count": len(minimal_rows),
        "rescueable_with_threshold_only_count": rescueable_with_threshold_only_count,
        "cost_bucket_counts": cost_bucket_counts,
        "minimal_near_miss_rows": minimal_rows,
        "recommendation": recommendation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan near-miss rescue frontier for rejected short_trade_boundary candidates.")
    parser.add_argument("--report-dir", required=True, help="Paper trading report directory containing selection_artifacts")
    parser.add_argument("--near-miss-threshold-grid", default="0.46,0.44,0.42,0.4,0.38", help="Comma-separated grid for near_miss threshold")
    parser.add_argument("--stale-weight-grid", default="0.12,0.1,0.08,0.06,0.04,0.02", help="Comma-separated grid for stale score penalty weight")
    parser.add_argument("--extension-weight-grid", default="0.08,0.06,0.04,0.02,0.0", help="Comma-separated grid for extension score penalty weight")
    parser.add_argument("--output-json", default="", help="Optional output JSON path")
    parser.add_argument("--output-md", default="", help="Optional output Markdown path")
    args = parser.parse_args()

    analysis = analyze_short_trade_boundary_score_failures_frontier(
        args.report_dir,
        near_miss_threshold_grid=[float(value) for value in _parse_float_grid(args.near_miss_threshold_grid)],
        stale_weight_grid=[float(value) for value in _parse_float_grid(args.stale_weight_grid)],
        extension_weight_grid=[float(value) for value in _parse_float_grid(args.extension_weight_grid)],
    )
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_short_trade_boundary_score_failure_frontier_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()