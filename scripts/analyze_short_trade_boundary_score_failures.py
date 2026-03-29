from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


NEAR_MISS_THRESHOLD = 0.46
SELECT_THRESHOLD = 0.58


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


def _gap_band(score_target: float) -> str:
    gap_to_near_miss = NEAR_MISS_THRESHOLD - score_target
    if gap_to_near_miss <= 0.02:
        return "gap<=0.02"
    if gap_to_near_miss <= 0.04:
        return "gap<=0.04"
    if gap_to_near_miss <= 0.06:
        return "gap<=0.06"
    return "gap>0.06"


def _build_row(*, trade_date: str, ticker: str, short_trade: dict[str, Any]) -> dict[str, Any]:
    metrics_payload = dict(short_trade.get("metrics_payload") or {})
    top_reasons = [str(reason) for reason in list(short_trade.get("top_reasons") or []) if str(reason or "").strip()]
    score_target = _safe_float(short_trade.get("score_target"))
    total_positive = _safe_float(metrics_payload.get("total_positive_contribution"))
    total_negative = _safe_float(metrics_payload.get("total_negative_contribution"))
    return {
        "trade_date": trade_date,
        "ticker": ticker,
        "score_target": round(score_target, 4),
        "gap_to_near_miss": round(NEAR_MISS_THRESHOLD - score_target, 4),
        "gap_to_select": round(SELECT_THRESHOLD - score_target, 4),
        "breakout_freshness": round(_safe_float(metrics_payload.get("breakout_freshness")), 4),
        "trend_acceleration": round(_safe_float(metrics_payload.get("trend_acceleration")), 4),
        "volume_expansion_quality": round(_safe_float(metrics_payload.get("volume_expansion_quality")), 4),
        "catalyst_freshness": round(_safe_float(metrics_payload.get("catalyst_freshness")), 4),
        "close_strength": round(_safe_float(metrics_payload.get("close_strength")), 4),
        "sector_resonance": round(_safe_float(metrics_payload.get("sector_resonance")), 4),
        "layer_c_alignment": round(_safe_float(metrics_payload.get("layer_c_alignment")), 4),
        "stale_trend_repair_penalty": round(_safe_float(metrics_payload.get("stale_trend_repair_penalty")), 4),
        "overhead_supply_penalty": round(_safe_float(metrics_payload.get("overhead_supply_penalty")), 4),
        "extension_without_room_penalty": round(_safe_float(metrics_payload.get("extension_without_room_penalty")), 4),
        "layer_c_avoid_penalty": round(_safe_float(metrics_payload.get("layer_c_avoid_penalty")), 4),
        "total_positive_contribution": round(total_positive, 4),
        "total_negative_contribution": round(total_negative, 4),
        "weighted_positive_contributions": dict(metrics_payload.get("weighted_positive_contributions") or {}),
        "weighted_negative_contributions": dict(metrics_payload.get("weighted_negative_contributions") or {}),
        "top_reasons": top_reasons,
        "gap_band": _gap_band(score_target),
    }


def _mean_contributions(rows: list[dict[str, Any]], field: str) -> dict[str, float]:
    sums: Counter[str] = Counter()
    counts: Counter[str] = Counter()
    for row in rows:
        for key, value in dict(row.get(field) or {}).items():
            sums[str(key)] += _safe_float(value)
            counts[str(key)] += 1
    return {key: round(sums[key] / counts[key], 4) for key in sorted(sums)}


def render_short_trade_boundary_score_failure_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Short Trade Boundary Score-Fail Analysis")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- report_dir: {analysis['report_dir']}")
    lines.append(f"- trade_day_count: {analysis['trade_day_count']}")
    lines.append(f"- rejected_short_trade_boundary_count: {analysis['rejected_short_trade_boundary_count']}")
    lines.append(f"- gap_band_counts: {analysis['gap_band_counts']}")
    lines.append(f"- recurring_ticker_counts: {analysis['recurring_ticker_counts']}")
    lines.append("")
    lines.append("## Metric Summary")
    for key, value in analysis["metric_summary"].items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Mean Contributions")
    lines.append(f"- positive: {analysis['mean_positive_contributions']}")
    lines.append(f"- negative: {analysis['mean_negative_contributions']}")
    lines.append("")
    lines.append("## Closest Cases")
    for row in analysis["closest_to_near_miss_cases"]:
        lines.append(
            f"- {row['trade_date']} {row['ticker']}: score_target={row['score_target']}, gap_to_near_miss={row['gap_to_near_miss']}, breakout={row['breakout_freshness']}, trend={row['trend_acceleration']}, volume={row['volume_expansion_quality']}, catalyst={row['catalyst_freshness']}, close={row['close_strength']}, stale_penalty={row['stale_trend_repair_penalty']}, extension_penalty={row['extension_without_room_penalty']}"
        )
    lines.append("")
    lines.append("## Representative Rows")
    for row in analysis["representative_cases"]:
        lines.append(
            f"- {row['trade_date']} {row['ticker']}: gap_band={row['gap_band']}, score_target={row['score_target']}, total_positive={row['total_positive_contribution']}, total_negative={row['total_negative_contribution']}, top_reasons={row['top_reasons']}"
        )
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def analyze_short_trade_boundary_score_failures(report_dir: str | Path) -> dict[str, Any]:
    report_path = Path(report_dir).expanduser().resolve()
    selection_root = report_path / "selection_artifacts"

    rows: list[dict[str, Any]] = []
    recurring_ticker_counts: Counter[str] = Counter()
    trade_dates: set[str] = set()
    top_reason_counts: Counter[str] = Counter()

    for snapshot in _iter_selection_snapshots(selection_root):
        trade_date = str(snapshot.get("trade_date") or "")
        trade_dates.add(trade_date)
        selection_targets = dict(snapshot.get("selection_targets") or {})
        for ticker, evaluation in selection_targets.items():
            candidate_source = str((evaluation or {}).get("candidate_source") or "")
            short_trade = dict((evaluation or {}).get("short_trade") or {})
            if candidate_source != "short_trade_boundary":
                continue
            if str(short_trade.get("decision") or "") != "rejected":
                continue
            row = _build_row(trade_date=trade_date, ticker=str(ticker), short_trade=short_trade)
            rows.append(row)
            recurring_ticker_counts[str(ticker)] += 1
            top_reason_counts.update(row["top_reasons"])

    rows.sort(key=lambda row: (row["score_target"], row["trade_date"], row["ticker"]), reverse=True)

    metric_names = [
        "score_target",
        "gap_to_near_miss",
        "gap_to_select",
        "breakout_freshness",
        "trend_acceleration",
        "volume_expansion_quality",
        "catalyst_freshness",
        "close_strength",
        "sector_resonance",
        "layer_c_alignment",
        "stale_trend_repair_penalty",
        "overhead_supply_penalty",
        "extension_without_room_penalty",
        "layer_c_avoid_penalty",
        "total_positive_contribution",
        "total_negative_contribution",
    ]
    metric_summary = {key: _summarize([_safe_float(row.get(key)) for row in rows]) for key in metric_names}

    gap_band_counts: Counter[str] = Counter(row["gap_band"] for row in rows)

    recommendation = "当前窗口没有 short_trade_boundary score-fail 样本。"
    if rows:
        far_from_near_miss = gap_band_counts.get("gap>0.06", 0)
        mean_catalyst = metric_summary["catalyst_freshness"]["mean"]
        mean_stale_penalty = metric_summary["stale_trend_repair_penalty"]["mean"]
        mean_extension_penalty = metric_summary["extension_without_room_penalty"]["mean"]
        if far_from_near_miss >= len(rows) - 1:
            recommendation = (
                f"这批 short_trade_boundary score-fail 样本大多不是只差一点阈值：{far_from_near_miss}/{len(rows)} 个样本距离 near_miss 仍超过 0.06。"
                f" admission metrics 已普遍通过 boundary floor，但 catalyst_freshness 均值只有 {mean_catalyst}，且 stale/extension penalty 均值分别为 {mean_stale_penalty} 和 {mean_extension_penalty}，说明下一步更应审查 score construction 与 penalty frontier，而不是继续放宽 admission floor。"
            )
        else:
            recommendation = "这批 short_trade_boundary score-fail 样本里已有相当比例贴近 near_miss，可优先做 threshold/frontier 试验。"

    analysis = {
        "report_dir": str(report_path),
        "selection_artifact_root": str(selection_root),
        "trade_day_count": len(trade_dates),
        "rejected_short_trade_boundary_count": len(rows),
        "gap_band_counts": dict(gap_band_counts),
        "metric_summary": metric_summary,
        "mean_positive_contributions": _mean_contributions(rows, "weighted_positive_contributions"),
        "mean_negative_contributions": _mean_contributions(rows, "weighted_negative_contributions"),
        "recurring_ticker_counts": dict(recurring_ticker_counts.most_common()),
        "top_reason_counts": dict(top_reason_counts.most_common()),
        "closest_to_near_miss_cases": rows[:8],
        "representative_cases": sorted(rows, key=lambda row: (row["gap_band"], -row["score_target"], row["ticker"]))[:8],
        "rows": rows,
        "recommendation": recommendation,
    }
    return analysis


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze rejected short_trade_boundary candidates within a paper trading report.")
    parser.add_argument("--report-dir", required=True, help="Paper trading report directory containing selection_artifacts")
    parser.add_argument("--output-json", default="", help="Optional output JSON path")
    parser.add_argument("--output-md", default="", help="Optional output Markdown path")
    args = parser.parse_args()

    analysis = analyze_short_trade_boundary_score_failures(args.report_dir)
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_short_trade_boundary_score_failure_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()