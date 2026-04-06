from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.generate_btst_tplus2_continuation_expansion_board import generate_btst_tplus2_continuation_expansion_board


REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_tplus2_continuation_peer_rollup_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_tplus2_continuation_peer_rollup_latest.md"


def analyze_btst_tplus2_continuation_peer_rollup(
    reports_root: str | Path,
    *,
    anchor_ticker: str = "600988",
    profile_name: str = "watchlist_zero_catalyst_guard_relief",
    report_name_contains: str = "btst_",
) -> dict[str, Any]:
    expansion_board = generate_btst_tplus2_continuation_expansion_board(
        reports_root,
        anchor_ticker=anchor_ticker,
        profile_name=profile_name,
        report_name_contains=report_name_contains,
    )
    board_rows = list(expansion_board.get("board_rows") or [])
    next_validation_candidates = list(expansion_board.get("next_validation_candidates") or [])
    top_candidate = dict(board_rows[0] or {}) if board_rows else {}
    risk_flags = [
        {
            "ticker": row.get("ticker"),
            "tier": row.get("tier"),
            "reason": "negative_or_weak_follow_through",
            "t_plus_2_close_return_mean": row.get("t_plus_2_close_return_mean"),
            "next_close_positive_rate": row.get("next_close_positive_rate"),
        }
        for row in board_rows
        if (row.get("t_plus_2_close_return_mean") is not None and float(row.get("t_plus_2_close_return_mean")) <= 0.0)
        or (row.get("next_close_positive_rate") is not None and float(row.get("next_close_positive_rate")) <= 0.0)
    ]

    if int(expansion_board.get("strict_peer_count") or 0) > 0:
        rollup_verdict = "strict_peer_breakthrough"
        recommendation = "Continuation expansion has reached strict-peer quality. Keep the lane isolated, but promotion review can shift from peer discovery to pooled validation."
    elif int(expansion_board.get("near_cluster_count") or 0) > 0:
        rollup_verdict = "first_near_cluster_breakthrough"
        recommendation = (
            "Continuation expansion has moved beyond a single-name pattern, but only into the near-cluster tier. "
            f"Top candidate recent_tier_verdict={top_candidate.get('recent_tier_verdict')} "
            f"({top_candidate.get('recent_tier_window_count')}/{top_candidate.get('recent_window_count')}). "
            "Focus next work on validating the top near-cluster candidate across new windows."
        )
    elif board_rows:
        rollup_verdict = "observation_only_candidates_present"
        recommendation = "Only loose observation candidates exist. Keep the lane in single-name observation mode until a near-cluster or strict peer emerges."
    else:
        rollup_verdict = "no_peer_expansion"
        recommendation = "No peer expansion evidence exists yet. Continue treating the lane as a single-anchor continuation pattern."

    return {
        "reports_root": str(Path(reports_root).expanduser().resolve()),
        "anchor_ticker": anchor_ticker,
        "strict_peer_count": expansion_board.get("strict_peer_count"),
        "near_cluster_count": expansion_board.get("near_cluster_count"),
        "observation_candidate_count": expansion_board.get("observation_candidate_count"),
        "rollup_verdict": rollup_verdict,
        "top_candidate": top_candidate,
        "next_validation_candidates": next_validation_candidates,
        "risk_flags": risk_flags,
        "recommendation": recommendation,
    }


def render_btst_tplus2_continuation_peer_rollup_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST T+2 Continuation Peer Rollup")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- anchor_ticker: {analysis['anchor_ticker']}")
    lines.append(f"- rollup_verdict: {analysis['rollup_verdict']}")
    lines.append(f"- strict_peer_count: {analysis['strict_peer_count']}")
    lines.append(f"- near_cluster_count: {analysis['near_cluster_count']}")
    lines.append(f"- observation_candidate_count: {analysis['observation_candidate_count']}")
    lines.append("")
    lines.append("## Top Candidate")
    if analysis.get("top_candidate"):
        candidate = dict(analysis["top_candidate"])
        lines.append(
            f"- ticker={candidate.get('ticker')} tier={candidate.get('tier')} reports={candidate.get('distinct_report_count')} "
            f"observations={candidate.get('observation_count')} similarity={candidate.get('mean_similarity_score')} "
            f"recent_tier_verdict={candidate.get('recent_tier_verdict')} "
            f"recent_tier_window_count={candidate.get('recent_tier_window_count')}/{candidate.get('recent_window_count')} "
            f"next_close_positive_rate={candidate.get('next_close_positive_rate')} "
            f"t_plus_2_close_positive_rate={candidate.get('t_plus_2_close_positive_rate')} "
            f"t_plus_2_close_return_mean={candidate.get('t_plus_2_close_return_mean')}"
        )
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Next Validation Candidates")
    for item in list(analysis.get("next_validation_candidates") or []):
        lines.append(
            f"- ticker={item['ticker']} tier={item['tier']} rank={item['priority_rank']} "
            f"recent_tier_verdict={item['recent_tier_verdict']} "
            f"recent_tier_window_count={item['recent_tier_window_count']}/{item['recent_window_count']} "
            f"recent_tier_ratio={item['recent_tier_ratio']}"
        )
    if not list(analysis.get("next_validation_candidates") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Risk Flags")
    for item in list(analysis.get("risk_flags") or []):
        lines.append(
            f"- ticker={item['ticker']} tier={item['tier']} reason={item['reason']} "
            f"t_plus_2_close_return_mean={item['t_plus_2_close_return_mean']} next_close_positive_rate={item['next_close_positive_rate']}"
        )
    if not list(analysis.get("risk_flags") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Roll up continuation peer-expansion evidence into a single verdict.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR))
    parser.add_argument("--anchor-ticker", default="600988")
    parser.add_argument("--profile-name", default="watchlist_zero_catalyst_guard_relief")
    parser.add_argument("--report-name-contains", default="btst_")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_tplus2_continuation_peer_rollup(
        args.reports_root,
        anchor_ticker=str(args.anchor_ticker or "600988"),
        profile_name=str(args.profile_name or "watchlist_zero_catalyst_guard_relief"),
        report_name_contains=str(args.report_name_contains or "btst_"),
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_tplus2_continuation_peer_rollup_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
