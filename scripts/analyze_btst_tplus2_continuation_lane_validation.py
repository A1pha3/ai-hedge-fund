from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.btst_analysis_utils import build_surface_summary
from scripts.analyze_btst_tplus2_continuation_peer_scan import _collect_rows
from scripts.generate_btst_tplus2_continuation_observation_pool import generate_btst_tplus2_continuation_observation_pool


REPORTS_DIR = Path("data/reports")
DEFAULT_REPORTS_ROOT = REPORTS_DIR
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_tplus2_continuation_lane_validation_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_tplus2_continuation_lane_validation_latest.md"


def _window_verdict(summary: dict[str, Any]) -> str:
    next_close_positive_rate = summary.get("next_close_positive_rate")
    t_plus_2_close_positive_rate = summary.get("t_plus_2_close_positive_rate")
    next_close_median = dict(summary.get("next_close_return_distribution") or {}).get("median")
    t_plus_2_median = dict(summary.get("t_plus_2_close_return_distribution") or {}).get("median")

    if (
        next_close_positive_rate is not None
        and t_plus_2_close_positive_rate is not None
        and next_close_median is not None
        and t_plus_2_median is not None
    ):
        next_close_positive_rate = float(next_close_positive_rate)
        t_plus_2_close_positive_rate = float(t_plus_2_close_positive_rate)
        next_close_median = float(next_close_median)
        t_plus_2_median = float(t_plus_2_median)
        if (
            (t_plus_2_close_positive_rate > next_close_positive_rate and t_plus_2_median >= next_close_median)
            or (t_plus_2_close_positive_rate >= next_close_positive_rate and t_plus_2_median > next_close_median)
        ):
            return "supports_tplus2_lane"
    return "mixed_or_weak"


def analyze_btst_tplus2_continuation_lane_validation(
    reports_root: str | Path,
    *,
    anchor_ticker: str = "600988",
    profile_name: str = "watchlist_zero_catalyst_guard_relief",
    report_name_contains: str = "btst_",
    next_high_hit_threshold: float = 0.02,
) -> dict[str, Any]:
    observation_pool = generate_btst_tplus2_continuation_observation_pool(
        reports_root,
        anchor_ticker=anchor_ticker,
        profile_name=profile_name,
        report_name_contains=report_name_contains,
        next_high_hit_threshold=next_high_hit_threshold,
    )
    eligible_tickers = [str(item.get("ticker") or "") for item in list(observation_pool.get("entries") or []) if str(item.get("ticker") or "").strip()]
    rows = _collect_rows(
        reports_root,
        profile_name=profile_name,
        report_name_contains=report_name_contains,
        next_high_hit_threshold=next_high_hit_threshold,
    )
    lane_rows = [row for row in rows if str(row.get("ticker") or "") in set(eligible_tickers)]

    per_window_rows: dict[str, list[dict[str, Any]]] = {}
    for row in lane_rows:
        per_window_rows.setdefault(str(row.get("report_label") or "unknown"), []).append(row)

    per_window_summaries = []
    for report_label, window_rows in sorted(per_window_rows.items()):
        surface_summary = build_surface_summary(window_rows, next_high_hit_threshold=next_high_hit_threshold)
        per_window_summaries.append(
            {
                "report_label": report_label,
                "row_count": len(window_rows),
                "tickers": sorted({str(row.get("ticker") or "") for row in window_rows}),
                "surface_summary": surface_summary,
                "window_verdict": _window_verdict(surface_summary),
            }
        )

    aggregate_surface_summary = build_surface_summary(lane_rows, next_high_hit_threshold=next_high_hit_threshold)
    support_count = sum(1 for item in per_window_summaries if item["window_verdict"] == "supports_tplus2_lane")
    if lane_rows and support_count == len(per_window_summaries):
        recommendation = "Lane validation supports the T+2 continuation thesis across all observed windows. Keep the lane paper-only, but it is ready for deeper governance review."
    elif lane_rows:
        recommendation = "Lane validation is mixed. Keep the lane in observation-only mode until more windows accumulate."
    else:
        recommendation = "No observation-pool rows were found for lane validation."

    return {
        "reports_root": str(Path(reports_root).expanduser().resolve()),
        "anchor_ticker": anchor_ticker,
        "profile_name": profile_name,
        "report_name_contains": report_name_contains,
        "eligible_tickers": eligible_tickers,
        "lane_row_count": len(lane_rows),
        "decision_counts": dict(Counter(str(row.get("decision") or "unknown") for row in lane_rows)),
        "aggregate_surface_summary": aggregate_surface_summary,
        "per_window_summaries": per_window_summaries,
        "recommendation": recommendation,
    }


def render_btst_tplus2_continuation_lane_validation_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST T+2 Continuation Lane Validation")
    lines.append("")
    lines.append("## Scope")
    lines.append(f"- anchor_ticker: {analysis['anchor_ticker']}")
    lines.append(f"- eligible_tickers: {analysis['eligible_tickers']}")
    lines.append(f"- lane_row_count: {analysis['lane_row_count']}")
    lines.append(f"- decision_counts: {analysis['decision_counts']}")
    lines.append("")
    lines.append("## Aggregate Surface")
    lines.append(f"- {analysis['aggregate_surface_summary']}")
    lines.append("")
    lines.append("## Per-Window")
    for item in list(analysis.get("per_window_summaries") or []):
        lines.append(
            f"- {item['report_label']}: row_count={item['row_count']}, verdict={item['window_verdict']}, "
            f"next_close_positive_rate={item['surface_summary'].get('next_close_positive_rate')}, "
            f"t_plus_2_close_positive_rate={item['surface_summary'].get('t_plus_2_close_positive_rate')}"
        )
    if not list(analysis.get("per_window_summaries") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the BTST T+2 continuation lane across replay windows.")
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--anchor-ticker", default="600988")
    parser.add_argument("--profile-name", default="watchlist_zero_catalyst_guard_relief")
    parser.add_argument("--report-name-contains", default="btst_")
    parser.add_argument("--next-high-hit-threshold", type=float, default=0.02)
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_tplus2_continuation_lane_validation(
        args.reports_root,
        anchor_ticker=str(args.anchor_ticker or "600988"),
        profile_name=str(args.profile_name or "watchlist_zero_catalyst_guard_relief"),
        report_name_contains=str(args.report_name_contains or "btst_"),
        next_high_hit_threshold=float(args.next_high_hit_threshold),
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_tplus2_continuation_lane_validation_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
