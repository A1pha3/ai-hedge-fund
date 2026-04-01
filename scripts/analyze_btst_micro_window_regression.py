from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.btst_analysis_utils import (
    build_day_breakdown as _build_day_breakdown,
    build_false_negative_proxy_rows as _build_false_negative_proxy_rows,
    build_surface_summary as _build_surface_summary,
    compare_reports as _compare_reports,
    extract_btst_price_outcome as _extract_btst_price_outcome,
    iter_selection_snapshots as _iter_selection_snapshots,
    load_session_summary_aggregate as _load_session_summary_aggregate,
    normalize_trade_date as _normalize_trade_date,
    round_or_none as _round_or_none,
    safe_float as _safe_float,
)


def analyze_btst_micro_window_report(
    report_dir: str | Path,
    *,
    label: str,
    next_high_hit_threshold: float = 0.02,
) -> dict[str, Any]:
    report_path = Path(report_dir).expanduser().resolve()
    selection_root = report_path / "selection_artifacts"
    rows: list[dict[str, Any]] = []
    price_cache: dict[tuple[str, str], Any] = {}
    decision_counts: Counter[str] = Counter()
    candidate_source_counts: Counter[str] = Counter()
    cycle_status_counts: Counter[str] = Counter()
    data_status_counts: Counter[str] = Counter()
    target_modes: Counter[str] = Counter()

    for snapshot in _iter_selection_snapshots(report_path) or []:
        trade_date = _normalize_trade_date(snapshot.get("trade_date"))
        target_mode = str(snapshot.get("target_mode") or "unknown")
        target_modes[target_mode] += 1
        for ticker, evaluation in dict(snapshot.get("selection_targets") or {}).items():
            short_trade = dict((evaluation or {}).get("short_trade") or {})
            if not short_trade:
                continue

            price_outcome = _extract_btst_price_outcome(str(ticker), trade_date, price_cache)
            candidate_source = str((evaluation or {}).get("candidate_source") or dict(short_trade.get("explainability_payload") or {}).get("candidate_source") or "unknown")
            row = {
                "report_label": label,
                "trade_date": trade_date,
                "ticker": str(ticker),
                "decision": str(short_trade.get("decision") or "unknown"),
                "score_target": _round_or_none(_safe_float(short_trade.get("score_target"))),
                "preferred_entry_mode": short_trade.get("preferred_entry_mode"),
                "candidate_source": candidate_source,
                "candidate_reason_codes": list((evaluation or {}).get("candidate_reason_codes") or []),
                "delta_classification": (evaluation or {}).get("delta_classification"),
                "blockers": list(short_trade.get("blockers") or []),
                "gate_status": dict(short_trade.get("gate_status") or {}),
                "target_mode": target_mode,
                **price_outcome,
            }
            rows.append(row)
            decision_counts[row["decision"]] += 1
            candidate_source_counts[candidate_source] += 1
            cycle_status_counts[str(row.get("cycle_status") or "unknown")] += 1
            data_status_counts[str(row.get("data_status") or "unknown")] += 1

    rows.sort(key=lambda row: (str(row.get("trade_date") or ""), str(row.get("ticker") or "")))
    actionable_rows = [row for row in rows if row.get("decision") in {"selected", "near_miss"}]
    selected_rows = [row for row in rows if row.get("decision") == "selected"]
    near_miss_rows = [row for row in rows if row.get("decision") == "near_miss"]
    blocked_rows = [row for row in rows if row.get("decision") == "blocked"]
    rejected_rows = [row for row in rows if row.get("decision") == "rejected"]
    false_negative_rows = _build_false_negative_proxy_rows(rows, next_high_hit_threshold=next_high_hit_threshold)

    top_tradeable_rows = sorted(actionable_rows, key=lambda row: (1 if row.get("decision") == "selected" else 0, float(row.get("score_target") or -999.0), float(row.get("next_high_return") or -999.0)), reverse=True)[:8]

    session_summary_aggregate = None
    artifact_status = "complete"
    if not selection_root.exists():
        session_summary_aggregate = _load_session_summary_aggregate(report_path)
        artifact_status = "missing_selection_artifacts"

    if actionable_rows:
        recommendation = "当前窗口已经形成可研究的 tradeable surface，下一步优先比较 actionable surface 的机会质量与 false negative proxy 的剩余规模。"
    elif false_negative_rows:
        recommendation = "当前窗口的 tradeable surface 仍为空或偏窄，但 closed-cycle false negative proxy 已经存在，优先继续做 score frontier / case-based release，而不是重开 admission floor。"
    elif session_summary_aggregate is not None:
        recommendation = "当前报告目录缺少 selection_artifacts，无法自动重建逐行 surface；请结合 session_summary 聚合统计与原始产物完整性一起解读。"
    else:
        recommendation = "当前窗口既没有稳定的 tradeable surface，也没有形成可用 false negative proxy，先检查样本窗口或价格补齐情况。"

    false_negative_source_counts: Counter[str] = Counter(str(row.get("candidate_source") or "unknown") for row in false_negative_rows)
    false_negative_decision_counts: Counter[str] = Counter(str(row.get("decision") or "unknown") for row in false_negative_rows)

    return {
        "label": label,
        "report_dir": str(report_path),
        "artifact_status": artifact_status,
        "session_summary_aggregate": session_summary_aggregate,
        "target_mode": target_modes.most_common(1)[0][0] if target_modes else "unknown",
        "trade_dates": sorted({str(row.get("trade_date") or "") for row in rows}),
        "row_count": len(rows),
        "decision_counts": dict(decision_counts),
        "candidate_source_counts": dict(candidate_source_counts),
        "cycle_status_counts": dict(cycle_status_counts),
        "data_status_counts": dict(data_status_counts),
        "surface_summaries": {
            "all": _build_surface_summary(rows, next_high_hit_threshold=next_high_hit_threshold),
            "tradeable": _build_surface_summary(actionable_rows, next_high_hit_threshold=next_high_hit_threshold),
            "selected": _build_surface_summary(selected_rows, next_high_hit_threshold=next_high_hit_threshold),
            "near_miss": _build_surface_summary(near_miss_rows, next_high_hit_threshold=next_high_hit_threshold),
            "blocked": _build_surface_summary(blocked_rows, next_high_hit_threshold=next_high_hit_threshold),
            "rejected": _build_surface_summary(rejected_rows, next_high_hit_threshold=next_high_hit_threshold),
        },
        "false_negative_proxy_summary": {
            "count": len(false_negative_rows),
            "candidate_source_counts": dict(false_negative_source_counts),
            "decision_counts": dict(false_negative_decision_counts),
            "surface_metrics": _build_surface_summary(false_negative_rows, next_high_hit_threshold=next_high_hit_threshold),
        },
        "top_tradeable_rows": top_tradeable_rows,
        "top_false_negative_rows": false_negative_rows[:8],
        "day_breakdown": _build_day_breakdown(rows),
        "recommendation": recommendation,
        "rows": rows,
    }


def _parse_labeled_paths(values: list[str]) -> dict[str, str]:
    labeled: dict[str, str] = {}
    for raw in values:
        token = str(raw or "").strip()
        if not token:
            continue
        if "=" not in token:
            raise ValueError(f"Expected label=path, got: {token}")
        label, path = token.split("=", 1)
        labeled[label.strip()] = path.strip()
    return labeled


def analyze_btst_micro_window_regression(
    baseline_report_dir: str | Path,
    *,
    variant_reports: dict[str, str] | None = None,
    forward_reports: dict[str, str] | None = None,
    next_high_hit_threshold: float = 0.02,
    guardrail_next_high_hit_rate: float = 0.5217,
    guardrail_next_close_positive_rate: float = 0.5652,
) -> dict[str, Any]:
    baseline = analyze_btst_micro_window_report(
        baseline_report_dir,
        label="baseline",
        next_high_hit_threshold=next_high_hit_threshold,
    )
    variant_analyses = [
        analyze_btst_micro_window_report(path, label=label, next_high_hit_threshold=next_high_hit_threshold)
        for label, path in sorted((variant_reports or {}).items())
    ]
    forward_analyses = [
        analyze_btst_micro_window_report(path, label=label, next_high_hit_threshold=next_high_hit_threshold)
        for label, path in sorted((forward_reports or {}).items())
    ]
    comparisons = [
        _compare_reports(
            baseline,
            variant,
            guardrail_next_high_hit_rate=guardrail_next_high_hit_rate,
            guardrail_next_close_positive_rate=guardrail_next_close_positive_rate,
        )
        for variant in variant_analyses
    ]

    return {
        "baseline": baseline,
        "variants": variant_analyses,
        "forward_reports": forward_analyses,
        "comparisons": comparisons,
        "next_high_hit_threshold": round(next_high_hit_threshold, 4),
        "guardrail_next_high_hit_rate": round(guardrail_next_high_hit_rate, 4),
        "guardrail_next_close_positive_rate": round(guardrail_next_close_positive_rate, 4),
    }


def render_btst_micro_window_regression_markdown(analysis: dict[str, Any]) -> str:
    baseline = dict(analysis["baseline"])
    lines: list[str] = []
    lines.append("# BTST Micro-Window Regression Review")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- baseline_report: {baseline['report_dir']}")
    lines.append(f"- baseline_trade_dates: {baseline['trade_dates']}")
    lines.append(f"- next_high_hit_threshold: {analysis['next_high_hit_threshold']}")
    lines.append(f"- guardrail_next_high_hit_rate: {analysis['guardrail_next_high_hit_rate']}")
    lines.append(f"- guardrail_next_close_positive_rate: {analysis['guardrail_next_close_positive_rate']}")
    lines.append("")
    lines.append("## Baseline Summary")
    lines.append(f"- decision_counts: {baseline['decision_counts']}")
    lines.append(f"- candidate_source_counts: {baseline['candidate_source_counts']}")
    lines.append(f"- cycle_status_counts: {baseline['cycle_status_counts']}")
    lines.append(f"- tradeable_surface: {baseline['surface_summaries']['tradeable']}")
    lines.append(f"- false_negative_proxy_summary: {baseline['false_negative_proxy_summary']}")
    lines.append(f"- recommendation: {baseline['recommendation']}")
    lines.append("")
    if analysis["variants"]:
        lines.append("## Variant Comparison")
        for variant, comparison in zip(analysis["variants"], analysis["comparisons"]):
            lines.append(f"### {variant['label']}")
            lines.append(f"- report_dir: {variant['report_dir']}")
            lines.append(f"- artifact_status: {variant.get('artifact_status')}")
            if variant.get("session_summary_aggregate"):
                lines.append(f"- session_summary_aggregate: {variant['session_summary_aggregate']}")
            lines.append(f"- decision_counts: {variant['decision_counts']}")
            lines.append(f"- cycle_status_counts: {variant['cycle_status_counts']}")
            lines.append(f"- tradeable_surface: {variant['surface_summaries']['tradeable']}")
            lines.append(f"- false_negative_proxy_summary: {variant['false_negative_proxy_summary']}")
            lines.append(f"- guardrail_status: {comparison['guardrail_status']}")
            lines.append(f"- comparison_note: {comparison['comparison_note']}")
            lines.append(f"- tradeable_surface_delta: {comparison['tradeable_surface_delta']}")
            lines.append(f"- false_negative_proxy_delta: {comparison['false_negative_proxy_delta']}")
            lines.append("")
    if analysis["forward_reports"]:
        lines.append("## Forward Reports")
        for report in analysis["forward_reports"]:
            lines.append(f"### {report['label']}")
            lines.append(f"- report_dir: {report['report_dir']}")
            lines.append(f"- trade_dates: {report['trade_dates']}")
            lines.append(f"- cycle_status_counts: {report['cycle_status_counts']}")
            lines.append(f"- tradeable_surface: {report['surface_summaries']['tradeable']}")
            lines.append(f"- top_tradeable_rows: {report['top_tradeable_rows']}")
            lines.append(f"- recommendation: {report['recommendation']}")
            lines.append("")
    lines.append("## Baseline Top False Negatives")
    for row in baseline["top_false_negative_rows"]:
        lines.append(
            f"- {row['trade_date']} {row['ticker']}: decision={row['decision']}, source={row['candidate_source']}, next_high_return={row['next_high_return']}, next_close_return={row['next_close_return']}, t_plus_2_close_return={row['t_plus_2_close_return']}, reasons={row['false_negative_proxy_reasons']}"
        )
    if not baseline["top_false_negative_rows"]:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze BTST micro-window regression quality across closed-cycle and forward-only report windows.")
    parser.add_argument("--baseline-report-dir", required=True)
    parser.add_argument("--variant-report", action="append", default=[], help="Repeated label=path entries for comparable variant windows")
    parser.add_argument("--forward-report", action="append", default=[], help="Repeated label=path entries for forward-only windows")
    parser.add_argument("--next-high-hit-threshold", type=float, default=0.02)
    parser.add_argument("--guardrail-next-high-hit-rate", type=float, default=0.5217)
    parser.add_argument("--guardrail-next-close-positive-rate", type=float, default=0.5652)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    analysis = analyze_btst_micro_window_regression(
        args.baseline_report_dir,
        variant_reports=_parse_labeled_paths(list(args.variant_report)),
        forward_reports=_parse_labeled_paths(list(args.forward_report)),
        next_high_hit_threshold=float(args.next_high_hit_threshold),
        guardrail_next_high_hit_rate=float(args.guardrail_next_high_hit_rate),
        guardrail_next_close_positive_rate=float(args.guardrail_next_close_positive_rate),
    )

    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_btst_micro_window_regression_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()