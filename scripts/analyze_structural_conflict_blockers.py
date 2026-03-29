from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_selection_snapshots(selection_root: Path):
    for day_dir in sorted(path for path in selection_root.iterdir() if path.is_dir()):
        snapshot_path = day_dir / "selection_snapshot.json"
        if snapshot_path.exists():
            yield _load_json(snapshot_path)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _summarize(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "mean": round(mean(values), 4),
    }


def render_structural_conflict_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Structural Conflict Blocker Review")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- report_dir: {analysis['report_dir']}")
    lines.append(f"- trade_day_count: {analysis['trade_day_count']}")
    lines.append(f"- blocked_count: {analysis['blocked_count']}")
    lines.append(f"- candidate_source_counts: {analysis['candidate_source_counts']}")
    lines.append(f"- delta_classification_counts: {analysis['delta_classification_counts']}")
    lines.append("")
    lines.append("## Score Summary")
    lines.append(f"- score_target: {analysis['score_target_distribution']}")
    lines.append(f"- gap_to_near_miss: {analysis['gap_to_near_miss_distribution']}")
    lines.append(f"- gap_to_select: {analysis['gap_to_select_distribution']}")
    lines.append("")
    lines.append("## Penalty Exposure")
    lines.append(f"- mean_penalties: {analysis['mean_penalties']}")
    lines.append(f"- mean_positive_metrics: {analysis['mean_positive_metrics']}")
    lines.append("")
    lines.append("## Day Breakdown")
    for row in analysis['day_breakdown']:
        lines.append(
            f"- {row['trade_date']}: blocked={row['blocked_count']}, mean_score_target={row['mean_score_target']}, mean_gap_to_near_miss={row['mean_gap_to_near_miss']}"
        )
    lines.append("")
    lines.append("## Recommended Focus")
    for row in analysis['recommended_focus_areas']:
        lines.append(f"- P{row['priority']}: {row['focus_area']} -> {row['why']}")
    lines.append("")
    lines.append("## Representative Cases")
    for row in analysis['top_examples']:
        lines.append(
            f"- {row['trade_date']} {row['ticker']}: source={row['candidate_source']}, score_target={row['score_target']}, gap_to_near_miss={row['gap_to_near_miss']}, penalties={row['penalties']}, top_reasons={row['top_reasons']}"
        )
    return "\n".join(lines) + "\n"


def analyze_structural_conflict_blockers(report_dir: str | Path) -> dict[str, Any]:
    report_path = Path(report_dir).expanduser().resolve()
    selection_root = report_path / "selection_artifacts"

    candidate_source_counts: Counter[str] = Counter()
    delta_classification_counts: Counter[str] = Counter()
    score_targets: list[float] = []
    gap_to_near_miss_values: list[float] = []
    gap_to_select_values: list[float] = []
    penalty_values: dict[str, list[float]] = defaultdict(list)
    positive_metric_values: dict[str, list[float]] = defaultdict(list)
    top_examples: list[dict[str, Any]] = []
    day_buckets: dict[str, dict[str, list[float] | int]] = defaultdict(lambda: {"scores": [], "gaps": [], "count": 0})

    for snapshot in _iter_selection_snapshots(selection_root):
        trade_date = str(snapshot.get("trade_date") or "")
        selection_targets = dict(snapshot.get("selection_targets") or {})
        for ticker, evaluation in selection_targets.items():
            short_trade = dict((evaluation or {}).get("short_trade") or {})
            blockers = [str(blocker) for blocker in list(short_trade.get("blockers") or []) if str(blocker or "").strip()]
            if "layer_c_bearish_conflict" not in blockers:
                continue

            metrics_payload = dict(short_trade.get("metrics_payload") or {})
            candidate_source = str((evaluation or {}).get("candidate_source") or "unknown")
            delta_classification = str((evaluation or {}).get("delta_classification") or "")
            score_target = _safe_float(short_trade.get("score_target"))
            gap_to_near_miss = round(0.46 - score_target, 4)
            gap_to_select = round(0.58 - score_target, 4)

            candidate_source_counts[candidate_source] += 1
            if delta_classification:
                delta_classification_counts[delta_classification] += 1
            score_targets.append(score_target)
            gap_to_near_miss_values.append(gap_to_near_miss)
            gap_to_select_values.append(gap_to_select)

            day_bucket = day_buckets[trade_date]
            day_bucket["count"] = int(day_bucket["count"]) + 1
            cast_scores = day_bucket["scores"]
            cast_gaps = day_bucket["gaps"]
            assert isinstance(cast_scores, list) and isinstance(cast_gaps, list)
            cast_scores.append(score_target)
            cast_gaps.append(gap_to_near_miss)

            for metric_name in [
                "layer_c_avoid_penalty",
                "stale_trend_repair_penalty",
                "overhead_supply_penalty",
                "extension_without_room_penalty",
            ]:
                penalty_values[metric_name].append(_safe_float(metrics_payload.get(metric_name)))
            for metric_name in [
                "breakout_freshness",
                "trend_acceleration",
                "volume_expansion_quality",
                "close_strength",
                "sector_resonance",
                "catalyst_freshness",
                "layer_c_alignment",
            ]:
                positive_metric_values[metric_name].append(_safe_float(metrics_payload.get(metric_name)))

            top_examples.append(
                {
                    "trade_date": trade_date,
                    "ticker": str(ticker),
                    "candidate_source": candidate_source,
                    "score_target": round(score_target, 4),
                    "gap_to_near_miss": gap_to_near_miss,
                    "gap_to_select": gap_to_select,
                    "penalties": {
                        key: round(_safe_float(metrics_payload.get(key)), 4)
                        for key in [
                            "layer_c_avoid_penalty",
                            "stale_trend_repair_penalty",
                            "overhead_supply_penalty",
                            "extension_without_room_penalty",
                        ]
                    },
                    "top_reasons": list(short_trade.get("top_reasons") or []),
                }
            )

    top_examples.sort(key=lambda row: (row["score_target"], row["trade_date"], row["ticker"]), reverse=True)
    day_breakdown = []
    for trade_date, bucket in sorted(day_buckets.items(), key=lambda item: item[0]):
        scores = bucket["scores"]
        gaps = bucket["gaps"]
        assert isinstance(scores, list) and isinstance(gaps, list)
        day_breakdown.append(
            {
                "trade_date": trade_date,
                "blocked_count": int(bucket["count"]),
                "mean_score_target": round(mean(scores), 4) if scores else None,
                "mean_gap_to_near_miss": round(mean(gaps), 4) if gaps else None,
            }
        )

    mean_penalties = {key: round(mean(values), 4) for key, values in penalty_values.items() if values}
    mean_positive_metrics = {key: round(mean(values), 4) for key, values in positive_metric_values.items() if values}
    recommended_focus_areas = []
    if top_examples:
        best_case = top_examples[0]
        recommended_focus_areas.append(
            {
                "priority": 1,
                "focus_area": "review_bearish_conflict_hard_block_for_high_score_cases",
                "why": f"最高分 blocked 样本 {best_case['ticker']} 的 score_target={best_case['score_target']}，距 near_miss 仅 {best_case['gap_to_near_miss']}，优先级高于继续审低分 blocked 样本。",
            }
        )
    if mean_penalties:
        ordered_penalties = sorted(mean_penalties.items(), key=lambda item: item[1], reverse=True)
        recommendations_text = ", ".join(f"{name}={value}" for name, value in ordered_penalties[:2])
        recommended_focus_areas.append(
            {
                "priority": len(recommended_focus_areas) + 1,
                "focus_area": "audit_conflict_and_penalty_coupling",
                "why": f"structural conflict 样本的主要 penalty 暴露集中在 {recommendations_text}，需要审查 hard block 与这些 penalty 是否重复惩罚。",
            }
        )

    return {
        "report_dir": str(report_path),
        "trade_day_count": len(day_breakdown),
        "blocked_count": len(score_targets),
        "candidate_source_counts": dict(candidate_source_counts.most_common()),
        "delta_classification_counts": dict(delta_classification_counts.most_common()),
        "score_target_distribution": _summarize(score_targets),
        "gap_to_near_miss_distribution": _summarize(gap_to_near_miss_values),
        "gap_to_select_distribution": _summarize(gap_to_select_values),
        "mean_penalties": mean_penalties,
        "mean_positive_metrics": mean_positive_metrics,
        "day_breakdown": day_breakdown,
        "recommended_focus_areas": recommended_focus_areas,
        "top_examples": top_examples[:8],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze layer_c_bearish_conflict blocked cluster for a dual-target report directory.")
    parser.add_argument("--report-dir", required=True, help="Paper trading report directory containing selection_artifacts")
    parser.add_argument("--output-json", default="", help="Optional output JSON path")
    parser.add_argument("--output-md", default="", help="Optional output Markdown path")
    args = parser.parse_args()

    analysis = analyze_structural_conflict_blockers(args.report_dir)
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_structural_conflict_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()