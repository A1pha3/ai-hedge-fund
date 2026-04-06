from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_btst_tplus2_continuation_peer_scan import analyze_btst_tplus2_continuation_peer_scan


REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_tplus2_continuation_expansion_board_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_tplus2_continuation_expansion_board_latest.md"
TIER_PRIORITY = {
    "strict_peer": 0,
    "near_cluster_peer": 1,
    "observation_candidate": 2,
}
RECENT_TIER_PRIORITY = {
    "recent_tier_confirmed": 0,
    "recent_tier_mixed": 1,
    "recent_tier_thin": 2,
    "recent_tier_absent": 3,
    "no_recent_windows": 4,
}


def _surface_metric(summary: dict[str, Any], key: str) -> float:
    value = dict(summary.get("surface_summary") or {}).get(key)
    return float(value) if value is not None else -999.0


def generate_btst_tplus2_continuation_expansion_board(
    reports_root: str | Path,
    *,
    anchor_ticker: str = "600988",
    profile_name: str = "watchlist_zero_catalyst_guard_relief",
    report_name_contains: str = "btst_",
) -> dict[str, Any]:
    scan = analyze_btst_tplus2_continuation_peer_scan(
        reports_root,
        anchor_ticker=anchor_ticker,
        profile_name=profile_name,
        report_name_contains=report_name_contains,
    )

    board_rows: list[dict[str, Any]] = []
    for tier_key, items in (
        ("strict_peer", list(scan.get("peer_summaries") or [])),
        ("near_cluster_peer", list(scan.get("near_peer_summaries") or [])),
        ("observation_candidate", list(scan.get("observation_candidate_summaries") or [])),
    ):
        for item in items:
            surface = dict(item.get("surface_summary") or {})
            board_rows.append(
                {
                    "ticker": item.get("ticker"),
                    "tier": tier_key,
                    "distinct_report_count": item.get("distinct_report_count"),
                    "observation_count": item.get("observation_count"),
                    "mean_similarity_score": item.get("mean_similarity_score"),
                    "recent_window_count": item.get("recent_window_count"),
                    "recent_tier_window_count": item.get("recent_tier_window_count"),
                    "recent_tier_ratio": item.get("recent_tier_ratio"),
                    "recent_tier_verdict": item.get("recent_tier_verdict"),
                    "next_close_positive_rate": surface.get("next_close_positive_rate"),
                    "t_plus_2_close_positive_rate": surface.get("t_plus_2_close_positive_rate"),
                    "t_plus_2_close_return_mean": dict(surface.get("t_plus_2_close_return_distribution") or {}).get("mean"),
                    "next_step": (
                        "Promote into the dedicated continuation observation lane immediately."
                        if tier_key == "strict_peer"
                        else "Track as the first expansion candidate and wait for another confirming window."
                        if tier_key == "near_cluster_peer"
                        else "Keep outside the tradeable surface and use only as a loose observation candidate."
                    ),
                }
            )

    deduped_rows: dict[str, dict[str, Any]] = {}
    for row in board_rows:
        ticker = str(row.get("ticker") or "")
        existing = deduped_rows.get(ticker)
        if not existing:
            deduped_rows[ticker] = row
            continue
        current_key = (
            TIER_PRIORITY.get(str(row.get("tier") or "observation_candidate"), 99),
            RECENT_TIER_PRIORITY.get(str(row.get("recent_tier_verdict") or "no_recent_windows"), 99),
            -int(row.get("recent_tier_window_count") or 0),
            -float(row.get("recent_tier_ratio") or 0.0),
            -float(row.get("next_close_positive_rate") if row.get("next_close_positive_rate") is not None else -999.0),
            -float(row.get("t_plus_2_close_return_mean") if row.get("t_plus_2_close_return_mean") is not None else -999.0),
            -int(row.get("distinct_report_count") or 0),
            -int(row.get("observation_count") or 0),
            float(row.get("mean_similarity_score") or 999.0),
        )
        existing_key = (
            TIER_PRIORITY.get(str(existing.get("tier") or "observation_candidate"), 99),
            RECENT_TIER_PRIORITY.get(str(existing.get("recent_tier_verdict") or "no_recent_windows"), 99),
            -int(existing.get("recent_tier_window_count") or 0),
            -float(existing.get("recent_tier_ratio") or 0.0),
            -float(existing.get("next_close_positive_rate") if existing.get("next_close_positive_rate") is not None else -999.0),
            -float(existing.get("t_plus_2_close_return_mean") if existing.get("t_plus_2_close_return_mean") is not None else -999.0),
            -int(existing.get("distinct_report_count") or 0),
            -int(existing.get("observation_count") or 0),
            float(existing.get("mean_similarity_score") or 999.0),
        )
        if current_key < existing_key:
            deduped_rows[ticker] = row

    board_rows = list(deduped_rows.values())
    board_rows.sort(
        key=lambda row: (
            TIER_PRIORITY.get(str(row.get("tier") or "observation_candidate"), 99),
            RECENT_TIER_PRIORITY.get(str(row.get("recent_tier_verdict") or "no_recent_windows"), 99),
            -int(row.get("recent_tier_window_count") or 0),
            -float(row.get("recent_tier_ratio") or 0.0),
            -float(row.get("next_close_positive_rate") if row.get("next_close_positive_rate") is not None else -999.0),
            -float(row.get("t_plus_2_close_return_mean") if row.get("t_plus_2_close_return_mean") is not None else -999.0),
            -int(row.get("distinct_report_count") or 0),
            -int(row.get("observation_count") or 0),
            float(row.get("mean_similarity_score") or 999.0),
            -float(row.get("t_plus_2_close_positive_rate") if row.get("t_plus_2_close_positive_rate") is not None else -999.0),
        )
    )
    for index, row in enumerate(board_rows, start=1):
        row["priority_rank"] = index

    next_validation_candidates = [
        {
            "ticker": row.get("ticker"),
            "tier": row.get("tier"),
            "priority_rank": row.get("priority_rank"),
            "recent_tier_verdict": row.get("recent_tier_verdict"),
            "recent_tier_window_count": row.get("recent_tier_window_count"),
            "recent_window_count": row.get("recent_window_count"),
            "recent_tier_ratio": row.get("recent_tier_ratio"),
            "next_close_positive_rate": row.get("next_close_positive_rate"),
            "t_plus_2_close_positive_rate": row.get("t_plus_2_close_positive_rate"),
            "t_plus_2_close_return_mean": row.get("t_plus_2_close_return_mean"),
        }
        for row in board_rows[1:]
        if str(row.get("recent_tier_verdict") or "") in {"recent_tier_confirmed", "recent_tier_mixed", "recent_tier_thin"}
        and (row.get("next_close_positive_rate") is None or float(row.get("next_close_positive_rate")) > 0.0)
        and (row.get("t_plus_2_close_return_mean") is None or float(row.get("t_plus_2_close_return_mean")) > 0.0)
    ][:3]

    if board_rows:
        leader = board_rows[0]
        recommendation = (
            f"Current top continuation expansion candidate is {leader['ticker']} in tier={leader['tier']}. "
            f"Recent tier verdict={leader.get('recent_tier_verdict')} ({leader.get('recent_tier_window_count')}/{leader.get('recent_window_count')}). "
            "Do not widen default BTST; route follow-up through the isolated continuation lane only."
        )
    else:
        recommendation = "No continuation expansion candidates are available yet; keep the lane as a single-ticker observation path."

    return {
        "reports_root": str(Path(reports_root).expanduser().resolve()),
        "anchor_ticker": anchor_ticker,
        "strict_peer_count": int(scan.get("peer_count") or 0),
        "near_cluster_count": int(scan.get("near_cluster_count") or 0),
        "observation_candidate_count": int(scan.get("observation_candidate_count") or 0),
        "board_rows": board_rows,
        "next_validation_candidates": next_validation_candidates,
        "recommendation": recommendation,
    }


def render_btst_tplus2_continuation_expansion_board_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST T+2 Continuation Expansion Board")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- anchor_ticker: {analysis['anchor_ticker']}")
    lines.append(f"- strict_peer_count: {analysis['strict_peer_count']}")
    lines.append(f"- near_cluster_count: {analysis['near_cluster_count']}")
    lines.append(f"- observation_candidate_count: {analysis['observation_candidate_count']}")
    lines.append("")
    lines.append("## Board")
    for row in list(analysis.get("board_rows") or []):
        lines.append(
            f"- rank={row['priority_rank']} ticker={row['ticker']} tier={row['tier']} reports={row['distinct_report_count']} "
            f"observations={row['observation_count']} similarity={row['mean_similarity_score']} "
            f"recent_tier_window_count={row['recent_tier_window_count']}/{row['recent_window_count']} "
            f"recent_tier_ratio={row['recent_tier_ratio']} recent_tier_verdict={row['recent_tier_verdict']} "
            f"next_close_positive_rate={row['next_close_positive_rate']} "
            f"t_plus_2_close_positive_rate={row['t_plus_2_close_positive_rate']}"
        )
        lines.append(f"  next_step: {row['next_step']}")
    if not list(analysis.get("board_rows") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Next Validation Candidates")
    for row in list(analysis.get("next_validation_candidates") or []):
        lines.append(
            f"- rank={row['priority_rank']} ticker={row['ticker']} tier={row['tier']} "
            f"recent_tier_verdict={row['recent_tier_verdict']} "
            f"recent_tier_window_count={row['recent_tier_window_count']}/{row['recent_window_count']} "
            f"recent_tier_ratio={row['recent_tier_ratio']}"
        )
    if not list(analysis.get("next_validation_candidates") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a continuation-lane expansion board from tiered peer scan results.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR))
    parser.add_argument("--anchor-ticker", default="600988")
    parser.add_argument("--profile-name", default="watchlist_zero_catalyst_guard_relief")
    parser.add_argument("--report-name-contains", default="btst_")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = generate_btst_tplus2_continuation_expansion_board(
        args.reports_root,
        anchor_ticker=str(args.anchor_ticker or "600988"),
        profile_name=str(args.profile_name or "watchlist_zero_catalyst_guard_relief"),
        report_name_contains=str(args.report_name_contains or "btst_"),
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_tplus2_continuation_expansion_board_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
