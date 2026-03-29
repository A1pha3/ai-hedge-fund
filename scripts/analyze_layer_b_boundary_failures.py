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


def _top_mean_metrics(metric_values: dict[str, list[float]], *, reverse: bool, limit: int = 6) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metric_name, values in metric_values.items():
        if not values:
            continue
        rows.append({"metric": metric_name, "mean": round(mean(values), 4), "count": len(values)})
    rows.sort(key=lambda row: (row["mean"], row["metric"]), reverse=reverse)
    return rows[:limit]


def render_layer_b_boundary_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Layer B Boundary Failure Analysis")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- report_dir: {analysis['report_dir']}")
    lines.append(f"- trade_day_count: {analysis['trade_day_count']}")
    lines.append(f"- layer_b_boundary_rejected_count: {analysis['layer_b_boundary_rejected_count']}")
    lines.append(f"- candidate_reason_code_counts: {analysis['candidate_reason_code_counts']}")
    lines.append(f"- decision_counts: {analysis['decision_counts']}")
    lines.append("")
    lines.append("## Score Summary")
    lines.append(f"- score_target: {analysis['score_target_distribution']}")
    lines.append(f"- gap_to_near_miss: {analysis['gap_to_near_miss_distribution']}")
    lines.append(f"- score_b: {analysis['score_b_distribution']}")
    lines.append(f"- score_final: {analysis['score_final_distribution']}")
    lines.append("")
    lines.append("## Factor Means")
    lines.append(f"- strongest_positive_metrics: {analysis['strongest_positive_metrics']}")
    lines.append(f"- weakest_positive_metrics: {analysis['weakest_positive_metrics']}")
    lines.append(f"- strongest_negative_metrics: {analysis['strongest_negative_metrics']}")
    lines.append("")
    lines.append("## Day Breakdown")
    for row in analysis["day_breakdown"]:
        lines.append(
            f"- {row['trade_date']}: rejected={row['rejected_count']}, mean_score_target={row['mean_score_target']}, mean_gap_to_near_miss={row['mean_gap_to_near_miss']}, mean_score_b={row['mean_score_b']}"
        )
    lines.append("")
    lines.append("## Recommended Focus")
    for row in analysis["recommended_focus_areas"]:
        lines.append(f"- P{row['priority']}: {row['focus_area']} -> {row['why']}")
    lines.append("")
    lines.append("## Representative Cases")
    for row in analysis["top_examples"]:
        lines.append(
            f"- {row['trade_date']} {row['ticker']}: score_target={row['score_target']}, gap_to_near_miss={row['gap_to_near_miss']}, score_b={row['score_b']}, top_reasons={row['top_reasons']}"
        )
    return "\n".join(lines) + "\n"


def analyze_layer_b_boundary_failures(report_dir: str | Path) -> dict[str, Any]:
    report_path = Path(report_dir).expanduser().resolve()
    selection_root = report_path / "selection_artifacts"

    candidate_reason_code_counts: Counter[str] = Counter()
    decision_counts: Counter[str] = Counter()
    score_targets: list[float] = []
    score_bs: list[float] = []
    score_finals: list[float] = []
    gap_to_near_miss_values: list[float] = []
    positive_metric_values: dict[str, list[float]] = defaultdict(list)
    negative_metric_values: dict[str, list[float]] = defaultdict(list)
    top_examples: list[dict[str, Any]] = []
    day_buckets: dict[str, dict[str, list[float] | int]] = defaultdict(lambda: {"scores": [], "gaps": [], "score_bs": [], "count": 0})

    for snapshot in _iter_selection_snapshots(selection_root):
        trade_date = str(snapshot.get("trade_date") or "")
        selection_targets = dict(snapshot.get("selection_targets") or {})
        for ticker, evaluation in selection_targets.items():
            if str((evaluation or {}).get("candidate_source") or "") != "layer_b_boundary":
                continue
            short_trade = dict((evaluation or {}).get("short_trade") or {})
            if str(short_trade.get("decision") or "") != "rejected":
                continue

            metrics_payload = dict(short_trade.get("metrics_payload") or {})
            score_target = _safe_float(short_trade.get("score_target"))
            gap_to_near_miss = round(0.46 - score_target, 4)
            score_b = _safe_float(metrics_payload.get("score_b"))
            score_final = _safe_float(metrics_payload.get("score_final"))
            reason_codes = [str(reason) for reason in list((evaluation or {}).get("candidate_reason_codes") or []) if str(reason or "").strip()]

            decision_counts[str(short_trade.get("decision") or "unknown")] += 1
            candidate_reason_code_counts.update(reason_codes)
            score_targets.append(score_target)
            gap_to_near_miss_values.append(gap_to_near_miss)
            score_bs.append(score_b)
            score_finals.append(score_final)

            day_bucket = day_buckets[trade_date]
            day_bucket["count"] = int(day_bucket["count"]) + 1
            cast_scores = day_bucket["scores"]
            cast_gaps = day_bucket["gaps"]
            cast_score_bs = day_bucket["score_bs"]
            assert isinstance(cast_scores, list) and isinstance(cast_gaps, list) and isinstance(cast_score_bs, list)
            cast_scores.append(score_target)
            cast_gaps.append(gap_to_near_miss)
            cast_score_bs.append(score_b)

            for metric_name, value in dict(metrics_payload.get("weighted_positive_contributions") or {}).items():
                positive_metric_values[str(metric_name)].append(_safe_float(value))
            for metric_name, value in dict(metrics_payload.get("weighted_negative_contributions") or {}).items():
                negative_metric_values[str(metric_name)].append(_safe_float(value))

            top_examples.append(
                {
                    "trade_date": trade_date,
                    "ticker": str(ticker),
                    "score_target": round(score_target, 4),
                    "gap_to_near_miss": gap_to_near_miss,
                    "score_b": round(score_b, 4),
                    "score_final": round(score_final, 4),
                    "top_reasons": list(short_trade.get("top_reasons") or []),
                }
            )

    top_examples.sort(key=lambda row: (row["score_target"], row["trade_date"], row["ticker"]), reverse=True)
    day_breakdown = []
    for trade_date, bucket in sorted(day_buckets.items(), key=lambda item: item[0]):
        scores = bucket["scores"]
        gaps = bucket["gaps"]
        local_score_bs = bucket["score_bs"]
        assert isinstance(scores, list) and isinstance(gaps, list) and isinstance(local_score_bs, list)
        day_breakdown.append(
            {
                "trade_date": trade_date,
                "rejected_count": int(bucket["count"]),
                "mean_score_target": round(mean(scores), 4) if scores else None,
                "mean_gap_to_near_miss": round(mean(gaps), 4) if gaps else None,
                "mean_score_b": round(mean(local_score_bs), 4) if local_score_bs else None,
            }
        )

    recommended_focus_areas = [
        {
            "priority": 1,
            "focus_area": "raise_layer_b_boundary_quality_before_short_trade",
            "why": f"当前共有 {len(score_targets)} 个 layer_b_boundary 样本直接因 score fail 被拒绝，均值 score_target 仅 {round(mean(score_targets), 4) if score_targets else None}，说明主问题是进入 short-trade 评分前的边界候选质量不足。",
        }
    ]
    strongest_negative_metrics = _top_mean_metrics(negative_metric_values, reverse=True)
    if strongest_negative_metrics:
        recommendations_text = ", ".join(f"{row['metric']}={row['mean']}" for row in strongest_negative_metrics[:2])
        recommended_focus_areas.append(
            {
                "priority": 2,
                "focus_area": "review_boundary_penalty_exposure",
                "why": f"layer_b_boundary 样本的主要负向暴露集中在 {recommendations_text}，需要检查这些惩罚是否在边界候选上过早触发。",
            }
        )

    return {
        "report_dir": str(report_path),
        "trade_day_count": len(day_breakdown),
        "layer_b_boundary_rejected_count": len(score_targets),
        "candidate_reason_code_counts": dict(candidate_reason_code_counts.most_common()),
        "decision_counts": dict(decision_counts.most_common()),
        "score_target_distribution": _summarize(score_targets),
        "gap_to_near_miss_distribution": _summarize(gap_to_near_miss_values),
        "score_b_distribution": _summarize(score_bs),
        "score_final_distribution": _summarize(score_finals),
        "strongest_positive_metrics": _top_mean_metrics(positive_metric_values, reverse=True),
        "weakest_positive_metrics": _top_mean_metrics(positive_metric_values, reverse=False),
        "strongest_negative_metrics": _top_mean_metrics(negative_metric_values, reverse=True),
        "day_breakdown": day_breakdown,
        "recommended_focus_areas": recommended_focus_areas,
        "top_examples": top_examples[:8],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze layer_b_boundary short-trade score-fail cluster for a dual-target report directory.")
    parser.add_argument("--report-dir", required=True, help="Paper trading report directory containing selection_artifacts")
    parser.add_argument("--output-json", default="", help="Optional output JSON path")
    parser.add_argument("--output-md", default="", help="Optional output Markdown path")
    args = parser.parse_args()

    analysis = analyze_layer_b_boundary_failures(args.report_dir)
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_layer_b_boundary_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()