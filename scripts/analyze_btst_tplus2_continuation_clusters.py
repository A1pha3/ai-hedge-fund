from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.btst_analysis_utils import build_surface_summary, summarize_distribution
from scripts.btst_profile_replay_utils import analyze_btst_profile_replay_window
from scripts.btst_report_utils import discover_report_dirs


REPORTS_DIR = Path("data/reports")
DEFAULT_REPORTS_ROOT = REPORTS_DIR
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_tplus2_continuation_clusters_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_tplus2_continuation_clusters_latest.md"


def _is_continuation_row(row: dict[str, Any]) -> bool:
    payload = dict(row.get("metrics_payload") or {})
    continuation_candidate = dict(payload.get("t_plus_2_continuation_candidate") or {})
    if continuation_candidate.get("applied") is True:
        return True
    positive_tags = [str(tag) for tag in list(row.get("positive_tags") or payload.get("positive_tags") or [])]
    return "t_plus_2_continuation_candidate" in positive_tags


def _summarize_ticker(rows: list[dict[str, Any]], *, next_high_hit_threshold: float) -> dict[str, Any]:
    sorted_rows = sorted(rows, key=lambda row: (str(row.get("trade_date") or ""), str(row.get("report_label") or "")))
    decision_counts = Counter(str(row.get("decision") or "unknown") for row in sorted_rows)
    candidate_source_counts = Counter(str(row.get("candidate_source") or "unknown") for row in sorted_rows)
    report_labels = sorted({str(row.get("report_label") or "") for row in sorted_rows})
    trade_dates = sorted({str(row.get("trade_date") or "") for row in sorted_rows})
    metrics_payloads = [dict(row.get("metrics_payload") or {}) for row in sorted_rows]

    def _metric_distribution(name: str) -> dict[str, float | int | None]:
        values = [float(payload.get(name)) for payload in metrics_payloads if payload.get(name) is not None]
        return summarize_distribution(values)

    surface_summary = build_surface_summary(sorted_rows, next_high_hit_threshold=next_high_hit_threshold)
    next_close_positive_rate = surface_summary.get("next_close_positive_rate")
    t_plus_2_close_positive_rate = surface_summary.get("t_plus_2_close_positive_rate")
    next_close_median = dict(surface_summary.get("next_close_return_distribution") or {}).get("median")
    t_plus_2_median = dict(surface_summary.get("t_plus_2_close_return_distribution") or {}).get("median")

    if (
        len(report_labels) >= 2
        and next_close_positive_rate is not None
        and t_plus_2_close_positive_rate is not None
        and float(t_plus_2_close_positive_rate) > float(next_close_positive_rate)
        and next_close_median is not None
        and t_plus_2_median is not None
        and float(t_plus_2_median) > float(next_close_median)
    ):
        pattern_label = "recurring_tplus2_continuation_cluster"
        recommendation = f"{sorted_rows[0]['ticker']} 已呈现跨窗口 recurring continuation 画像，优先作为独立 T+2 观察簇而不是 BTST 默认放行样本。"
    elif t_plus_2_close_positive_rate is not None and next_close_positive_rate is not None and float(t_plus_2_close_positive_rate) > float(next_close_positive_rate):
        pattern_label = "window_local_tplus2_tradeoff"
        recommendation = f"{sorted_rows[0]['ticker']} 更像窗口内的 T+2 tradeoff 样本，先继续累积同类观察。"
    else:
        pattern_label = "ambiguous_continuation_candidate"
        recommendation = f"{sorted_rows[0]['ticker']} 尚未形成稳定 continuation 优势，暂时保留为观察对象。"

    return {
        "ticker": str(sorted_rows[0].get("ticker") or ""),
        "observation_count": len(sorted_rows),
        "distinct_report_count": len(report_labels),
        "distinct_trade_date_count": len(trade_dates),
        "report_labels": report_labels,
        "trade_dates": trade_dates,
        "decision_counts": dict(decision_counts),
        "candidate_source_counts": dict(candidate_source_counts),
        "surface_summary": surface_summary,
        "metric_distributions": {
            "breakout_freshness": _metric_distribution("breakout_freshness"),
            "trend_acceleration": _metric_distribution("trend_acceleration"),
            "catalyst_freshness": _metric_distribution("catalyst_freshness"),
            "layer_c_alignment": _metric_distribution("layer_c_alignment"),
            "sector_resonance": _metric_distribution("sector_resonance"),
            "close_strength": _metric_distribution("close_strength"),
        },
        "pattern_label": pattern_label,
        "recommendation": recommendation,
        "best_t_plus_2_case": max(sorted_rows, key=lambda row: float(row.get("t_plus_2_close_return") or -999.0), default=None),
        "worst_next_close_case": min(sorted_rows, key=lambda row: float(row.get("next_close_return") or 999.0), default=None),
    }


def analyze_btst_tplus2_continuation_clusters(
    reports_root: str | Path,
    *,
    profile_name: str = "watchlist_zero_catalyst_guard_relief",
    report_name_contains: str = "btst_",
    next_high_hit_threshold: float = 0.02,
) -> dict[str, Any]:
    report_dirs = discover_report_dirs(reports_root, report_name_contains=report_name_contains)
    continuation_rows: list[dict[str, Any]] = []

    for report_dir in report_dirs:
        replay = analyze_btst_profile_replay_window(
            report_dir,
            profile_name=profile_name,
            label=Path(report_dir).name,
            next_high_hit_threshold=next_high_hit_threshold,
        )
        continuation_rows.extend(row for row in list(replay.get("rows") or []) if _is_continuation_row(row))

    continuation_rows.sort(key=lambda row: (str(row.get("ticker") or ""), str(row.get("trade_date") or ""), str(row.get("report_label") or "")))
    grouped_rows: dict[str, list[dict[str, Any]]] = {}
    for row in continuation_rows:
        grouped_rows.setdefault(str(row.get("ticker") or ""), []).append(row)

    ticker_summaries = sorted(
        (
            _summarize_ticker(rows, next_high_hit_threshold=next_high_hit_threshold)
            for ticker, rows in grouped_rows.items()
            if ticker
        ),
        key=lambda item: (
            int(item["distinct_report_count"]),
            int(item["observation_count"]),
            float((item["surface_summary"].get("t_plus_2_close_positive_rate") or -1.0)),
            float((item["surface_summary"].get("next_close_positive_rate") or -1.0)),
            item["ticker"],
        ),
        reverse=True,
    )

    recurring_cluster_count = sum(1 for item in ticker_summaries if item["distinct_report_count"] >= 2)
    strong_t_plus_2_edge_count = sum(
        1
        for item in ticker_summaries
        if item["surface_summary"].get("t_plus_2_close_positive_rate") is not None
        and item["surface_summary"].get("next_close_positive_rate") is not None
        and float(item["surface_summary"]["t_plus_2_close_positive_rate"]) > float(item["surface_summary"]["next_close_positive_rate"])
    )

    if recurring_cluster_count > 0 and strong_t_plus_2_edge_count > 0:
        recommendation = "Detected recurring T+2 continuation clusters. Next step should focus on same-cluster ticker search and a dedicated observation lane rather than loosening default BTST gates."
    elif ticker_summaries:
        recommendation = "Continuation candidates exist but do not yet form a broad recurring cluster. Keep default BTST logic unchanged and continue accumulating windows."
    else:
        recommendation = "No T+2 continuation candidates were found in the selected BTST windows."

    return {
        "reports_root": str(Path(reports_root).expanduser().resolve()),
        "report_name_contains": report_name_contains,
        "report_dir_count": len(report_dirs),
        "report_dirs": [str(Path(path).expanduser().resolve()) for path in report_dirs],
        "profile_name": profile_name,
        "next_high_hit_threshold": next_high_hit_threshold,
        "continuation_row_count": len(continuation_rows),
        "ticker_count": len(ticker_summaries),
        "recurring_cluster_count": recurring_cluster_count,
        "strong_t_plus_2_edge_count": strong_t_plus_2_edge_count,
        "decision_counts": dict(Counter(str(row.get("decision") or "unknown") for row in continuation_rows)),
        "candidate_source_counts": dict(Counter(str(row.get("candidate_source") or "unknown") for row in continuation_rows)),
        "surface_summary": build_surface_summary(continuation_rows, next_high_hit_threshold=next_high_hit_threshold),
        "ticker_summaries": ticker_summaries,
        "recommendation": recommendation,
    }


def render_btst_tplus2_continuation_clusters_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST T+2 Continuation Clusters")
    lines.append("")
    lines.append("## Scope")
    lines.append(f"- reports_root: {analysis['reports_root']}")
    lines.append(f"- report_dir_count: {analysis['report_dir_count']}")
    lines.append(f"- profile_name: {analysis['profile_name']}")
    lines.append(f"- continuation_row_count: {analysis['continuation_row_count']}")
    lines.append(f"- ticker_count: {analysis['ticker_count']}")
    lines.append(f"- recurring_cluster_count: {analysis['recurring_cluster_count']}")
    lines.append("")
    lines.append("## Cluster Summary")
    lines.append(f"- decision_counts: {analysis['decision_counts']}")
    lines.append(f"- candidate_source_counts: {analysis['candidate_source_counts']}")
    lines.append(f"- surface_summary: {analysis['surface_summary']}")
    lines.append("")
    lines.append("## Ticker Clusters")
    for summary in list(analysis.get("ticker_summaries") or []):
        surface = dict(summary.get("surface_summary") or {})
        lines.append(
            f"- {summary['ticker']}: reports={summary['distinct_report_count']}, observations={summary['observation_count']}, "
            f"next_close_positive_rate={surface.get('next_close_positive_rate')}, "
            f"t_plus_2_close_positive_rate={surface.get('t_plus_2_close_positive_rate')}, "
            f"pattern={summary['pattern_label']}"
        )
    if not list(analysis.get("ticker_summaries") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Cluster recurring BTST T+2 continuation candidates across replay windows.")
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--report-name-contains", default="btst_")
    parser.add_argument("--profile-name", default="watchlist_zero_catalyst_guard_relief")
    parser.add_argument("--next-high-hit-threshold", type=float, default=0.02)
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_tplus2_continuation_clusters(
        args.reports_root,
        profile_name=str(args.profile_name or "watchlist_zero_catalyst_guard_relief"),
        report_name_contains=str(args.report_name_contains or "btst_"),
        next_high_hit_threshold=float(args.next_high_hit_threshold),
    )

    output_json = Path(args.output_json).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md = Path(args.output_md).expanduser().resolve()
    output_md.write_text(render_btst_tplus2_continuation_clusters_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
