from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.generate_btst_tplus2_continuation_observation_pool import generate_btst_tplus2_continuation_observation_pool


REPORTS_DIR = Path("data/reports")
DEFAULT_REPORTS_ROOT = REPORTS_DIR
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_tplus2_continuation_lane_rulepack_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_tplus2_continuation_lane_rulepack_latest.md"


def generate_btst_tplus2_continuation_lane_rulepack(
    reports_root: str | Path,
    *,
    anchor_ticker: str = "600988",
    profile_name: str = "watchlist_zero_catalyst_guard_relief",
    report_name_contains: str = "btst_",
) -> dict[str, Any]:
    observation_pool = generate_btst_tplus2_continuation_observation_pool(
        reports_root,
        anchor_ticker=anchor_ticker,
        profile_name=profile_name,
        report_name_contains=report_name_contains,
    )
    entries = list(observation_pool.get("entries") or [])
    eligible_entries = [item for item in entries if str(item.get("entry_type") or "") in {"anchor_cluster", "same_cluster_peer"}]
    watch_entries = [item for item in entries if str(item.get("entry_type") or "") == "near_cluster_watch"]

    if eligible_entries and watch_entries:
        lane_status = "anchor_plus_validation_watch"
        recommendation = "Use this lane as paper-only / observation-only, and keep near-cluster names on validation watch until they become strict peers."
    elif eligible_entries:
        lane_status = "single_ticker_observation_lane"
        recommendation = "Use this lane as paper-only / observation-only until more peers appear or pooled validation is available."
    else:
        lane_status = "no_ready_entries"
        recommendation = "No T+2 continuation lane should be activated yet."

    return {
        "reports_root": str(Path(reports_root).expanduser().resolve()),
        "anchor_ticker": anchor_ticker,
        "profile_name": profile_name,
        "report_name_contains": report_name_contains,
        "lane_status": lane_status,
        "observation_pool_entry_count": len(entries),
        "eligible_tickers": [str(item.get("ticker") or "") for item in eligible_entries if str(item.get("ticker") or "").strip()],
        "watchlist_tickers": [str(item.get("ticker") or "") for item in watch_entries if str(item.get("ticker") or "").strip()],
        "lane_rules": {
            "lane_stage": "observation_only",
            "capital_mode": "paper_only",
            "max_active_names": 1,
            "block_from_default_btst_tradeable_surface": True,
            "required_entry_types": ["anchor_cluster", "same_cluster_peer"],
            "watchlist_entry_types": ["near_cluster_watch"],
            "required_candidate_source": "layer_c_watchlist",
            "required_holding_window": "t_plus_2_continuation",
            "entry_trigger": "pre-market observation only; no direct promotion into default BTST selected/near_miss",
            "review_points": ["next_close_review", "t_plus_2_close_review"],
            "promotion_condition": "Only consider paper execution after pooled lane validation shows stable T+2 edge beyond the anchor ticker.",
            "watchlist_promotion_condition": "Near-cluster watchlist names require another confirming window or strict-peer upgrade before joining eligible_tickers.",
            "stop_condition": "Disable the lane if recurring cluster_count drops to 0 or same-cluster peers fail to appear over additional windows.",
        },
        "entries": entries,
        "recommendation": recommendation,
    }


def render_btst_tplus2_continuation_lane_rulepack_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST T+2 Continuation Lane Rulepack")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- lane_status: {analysis['lane_status']}")
    lines.append(f"- anchor_ticker: {analysis['anchor_ticker']}")
    lines.append(f"- observation_pool_entry_count: {analysis['observation_pool_entry_count']}")
    lines.append(f"- eligible_tickers: {analysis['eligible_tickers']}")
    lines.append(f"- watchlist_tickers: {analysis.get('watchlist_tickers')}")
    lines.append("")
    lines.append("## Lane Rules")
    for key, value in dict(analysis.get("lane_rules") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Observation Entries")
    for item in list(analysis.get("entries") or []):
        lines.append(
            f"- {item['ticker']}: entry_type={item['entry_type']}, lane_stage={item['lane_stage']}, "
            f"priority_score={item['priority_score']}, t_plus_2_close_positive_rate={item.get('t_plus_2_close_positive_rate')}, "
            f"t_plus_2_close_return_mean={item.get('t_plus_2_close_return_mean')}"
        )
    if not list(analysis.get("entries") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a rule pack for the BTST T+2 continuation lane.")
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--anchor-ticker", default="600988")
    parser.add_argument("--profile-name", default="watchlist_zero_catalyst_guard_relief")
    parser.add_argument("--report-name-contains", default="btst_")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = generate_btst_tplus2_continuation_lane_rulepack(
        args.reports_root,
        anchor_ticker=str(args.anchor_ticker or "600988"),
        profile_name=str(args.profile_name or "watchlist_zero_catalyst_guard_relief"),
        report_name_contains=str(args.report_name_contains or "btst_"),
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_tplus2_continuation_lane_rulepack_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
