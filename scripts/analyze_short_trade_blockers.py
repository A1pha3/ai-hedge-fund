from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


SELECT_THRESHOLD = 0.58
NEAR_MISS_THRESHOLD = 0.46


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


def _summarize_scores(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "mean": round(mean(values), 4),
    }


def _build_example(
    *,
    trade_date: str,
    ticker: str,
    candidate_source: str,
    candidate_reason_codes: list[str],
    available_strategy_signals: list[str],
    short_trade: dict[str, Any],
    delta_classification: str | None,
) -> dict[str, Any]:
    metrics_payload = dict(short_trade.get("metrics_payload") or {})
    return {
        "trade_date": trade_date,
        "ticker": ticker,
        "candidate_source": candidate_source,
        "candidate_reason_codes": candidate_reason_codes,
        "available_strategy_signals": available_strategy_signals,
        "decision": short_trade.get("decision"),
        "score_target": round(_safe_float(short_trade.get("score_target")), 4),
        "gap_to_select": round(SELECT_THRESHOLD - _safe_float(short_trade.get("score_target")), 4),
        "gap_to_near_miss": round(NEAR_MISS_THRESHOLD - _safe_float(short_trade.get("score_target")), 4),
        "blockers": list(short_trade.get("blockers") or []),
        "negative_tags": list(short_trade.get("negative_tags") or []),
        "top_reasons": list(short_trade.get("top_reasons") or []),
        "gate_status": dict(short_trade.get("gate_status") or {}),
        "score_b": metrics_payload.get("score_b"),
        "score_c": metrics_payload.get("score_c"),
        "score_final": metrics_payload.get("score_final"),
        "layer_c_alignment": metrics_payload.get("layer_c_alignment"),
        "layer_c_avoid_penalty": metrics_payload.get("layer_c_avoid_penalty"),
        "overhead_supply_penalty": metrics_payload.get("overhead_supply_penalty"),
        "delta_classification": delta_classification,
    }


def render_short_trade_blocker_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Short Trade Blocker Analysis")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- report_dir: {analysis['report_dir']}")
    lines.append(f"- trade_day_count: {analysis['trade_day_count']}")
    lines.append(f"- target_mode: {analysis.get('target_mode') or 'unknown'}")
    lines.append(f"- short_trade_target_count: {analysis['short_trade_target_count']}")
    lines.append(f"- short_trade_decision_counts: {analysis['short_trade_decision_counts']}")
    lines.append("")
    lines.append("## Blocker Summary")
    lines.append(f"- blocker_counts: {analysis['blocker_counts']}")
    lines.append(f"- negative_tag_counts: {analysis['negative_tag_counts']}")
    lines.append(f"- candidate_source_counts: {analysis['candidate_source_counts']}")
    lines.append(f"- candidate_reason_code_counts: {analysis['candidate_reason_code_counts']}")
    lines.append(f"- signal_availability: {analysis['signal_availability']}")
    lines.append(f"- available_strategy_signal_counts: {analysis['available_strategy_signal_counts']}")
    lines.append("")
    lines.append("## Score Distribution")
    lines.append(f"- all_scores: {analysis['score_distribution']['all']}")
    lines.append(f"- blocked_scores: {analysis['score_distribution']['blocked']}")
    lines.append(f"- rejected_scores: {analysis['score_distribution']['rejected']}")
    lines.append(f"- near_miss_scores: {analysis['score_distribution']['near_miss']}")
    lines.append(f"- selected_scores: {analysis['score_distribution']['selected']}")
    lines.append("")
    lines.append("## Day Breakdown")
    for row in analysis["day_breakdown"]:
        lines.append(
            f"- {row['trade_date']}: total={row['short_trade_target_count']}, selected={row['selected_count']}, near_miss={row['near_miss_count']}, blocked={row['blocked_count']}, rejected={row['rejected_count']}"
        )
    lines.append("")
    lines.append("## Representative Cases")
    for row in analysis["top_blocked_examples"]:
        lines.append(
            f"- {row['trade_date']} {row['ticker']}: score_short={row['score_target']}, source={row['candidate_source']}, blockers={row['blockers']}, top_reasons={row['top_reasons']}"
        )
    return "\n".join(lines) + "\n"


def analyze_short_trade_blockers(report_dir: str | Path) -> dict[str, Any]:
    report_path = Path(report_dir).expanduser().resolve()
    selection_root = report_path / "selection_artifacts"
    session_summary_path = report_path / "session_summary.json"
    session_summary = _load_json(session_summary_path) if session_summary_path.exists() else {}

    short_trade_decision_counts: Counter[str] = Counter()
    blocker_counts: Counter[str] = Counter()
    negative_tag_counts: Counter[str] = Counter()
    candidate_source_counts: Counter[str] = Counter()
    candidate_reason_code_counts: Counter[str] = Counter()
    available_strategy_signal_counts: Counter[str] = Counter()
    signal_availability_counts: Counter[str] = Counter()
    delta_classification_counts: Counter[str] = Counter()
    gate_status_counts: dict[str, Counter[str]] = defaultdict(Counter)
    score_distribution_by_decision: dict[str, list[float]] = defaultdict(list)
    top_blocked_examples: list[dict[str, Any]] = []
    top_near_threshold_examples: list[dict[str, Any]] = []
    day_breakdown: list[dict[str, Any]] = []

    for snapshot in _iter_selection_snapshots(selection_root):
        trade_date = str(snapshot.get("trade_date") or "")
        selection_targets = dict(snapshot.get("selection_targets") or {})
        day_counts: Counter[str] = Counter()

        for ticker, evaluation in selection_targets.items():
            short_trade = dict((evaluation or {}).get("short_trade") or {})
            if not short_trade:
                continue

            decision = str(short_trade.get("decision") or "unknown")
            score_target = _safe_float(short_trade.get("score_target"))
            candidate_source = str((evaluation or {}).get("candidate_source") or "unknown")
            candidate_reason_codes = [str(reason) for reason in list((evaluation or {}).get("candidate_reason_codes") or []) if str(reason or "").strip()]
            delta_classification = (evaluation or {}).get("delta_classification")
            explainability_payload = dict(short_trade.get("explainability_payload") or {})
            available_strategy_signals = [
                str(signal_name)
                for signal_name in list(explainability_payload.get("available_strategy_signals") or [])
                if str(signal_name or "").strip()
            ]

            short_trade_decision_counts[decision] += 1
            day_counts[decision] += 1
            candidate_source_counts[candidate_source] += 1
            candidate_reason_code_counts.update(candidate_reason_codes)
            available_strategy_signal_counts.update(available_strategy_signals)
            signal_availability_counts["missing_all"] += 1 if not available_strategy_signals else 0
            signal_availability_counts["has_any"] += 1 if available_strategy_signals else 0
            score_distribution_by_decision[decision].append(score_target)
            score_distribution_by_decision["all"].append(score_target)

            if delta_classification:
                delta_classification_counts[str(delta_classification)] += 1

            for blocker in list(short_trade.get("blockers") or []):
                blocker_counts[str(blocker)] += 1
            for tag in list(short_trade.get("negative_tags") or []):
                negative_tag_counts[str(tag)] += 1
            for gate_name, gate_value in dict(short_trade.get("gate_status") or {}).items():
                gate_status_counts[str(gate_name)][str(gate_value)] += 1

            example = _build_example(
                trade_date=trade_date,
                ticker=str(ticker),
                candidate_source=candidate_source,
                candidate_reason_codes=candidate_reason_codes,
                available_strategy_signals=available_strategy_signals,
                short_trade=short_trade,
                delta_classification=str(delta_classification) if delta_classification else None,
            )
            if decision == "blocked":
                top_blocked_examples.append(example)
            if decision in {"blocked", "rejected", "near_miss"} and score_target >= 0.15:
                top_near_threshold_examples.append(example)

        day_breakdown.append(
            {
                "trade_date": trade_date,
                "short_trade_target_count": sum(day_counts.values()),
                "selected_count": day_counts.get("selected", 0),
                "near_miss_count": day_counts.get("near_miss", 0),
                "blocked_count": day_counts.get("blocked", 0),
                "rejected_count": day_counts.get("rejected", 0),
            }
        )

    top_blocked_examples.sort(key=lambda item: (item["score_target"], item["trade_date"], item["ticker"]), reverse=True)
    top_near_threshold_examples.sort(key=lambda item: (item["score_target"], item["trade_date"], item["ticker"]), reverse=True)

    analysis = {
        "report_dir": str(report_path),
        "selection_artifact_root": str(selection_root),
        "trade_day_count": len(day_breakdown),
        "target_mode": ((session_summary.get("plan_generation") or {}).get("selection_target") or session_summary.get("target_mode") or None),
        "session_dual_target_summary": dict(session_summary.get("dual_target_summary") or {}),
        "short_trade_target_count": sum(short_trade_decision_counts.values()),
        "short_trade_decision_counts": dict(short_trade_decision_counts),
        "blocker_counts": dict(blocker_counts.most_common()),
        "negative_tag_counts": dict(negative_tag_counts.most_common()),
        "candidate_source_counts": dict(candidate_source_counts.most_common()),
        "candidate_reason_code_counts": dict(candidate_reason_code_counts.most_common()),
        "signal_availability": dict(signal_availability_counts.most_common()),
        "available_strategy_signal_counts": dict(available_strategy_signal_counts.most_common()),
        "delta_classification_counts": dict(delta_classification_counts.most_common()),
        "gate_status_counts": {gate_name: dict(counter.most_common()) for gate_name, counter in gate_status_counts.items()},
        "score_distribution": {
            "all": _summarize_scores(score_distribution_by_decision["all"]),
            "blocked": _summarize_scores(score_distribution_by_decision["blocked"]),
            "rejected": _summarize_scores(score_distribution_by_decision["rejected"]),
            "near_miss": _summarize_scores(score_distribution_by_decision["near_miss"]),
            "selected": _summarize_scores(score_distribution_by_decision["selected"]),
        },
        "day_breakdown": day_breakdown,
        "top_blocked_examples": top_blocked_examples[:8],
        "top_near_threshold_examples": top_near_threshold_examples[:8],
    }
    return analysis


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze short trade blocker distribution for a dual-target report directory.")
    parser.add_argument("--report-dir", required=True, help="Paper trading report directory containing selection_artifacts")
    parser.add_argument("--output-json", default="", help="Optional output JSON path")
    parser.add_argument("--output-md", default="", help="Optional output Markdown path")
    args = parser.parse_args()

    analysis = analyze_short_trade_blockers(args.report_dir)
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_short_trade_blocker_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()