from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_btst_tplus2_continuation_peer_scan import (
    DEFAULT_TOLERANCES,
    _classify_recent_tier_verdict,
    _build_anchor_profile,
    _classify_peer_tier,
    _collect_rows,
    _row_similarity,
)
from scripts.btst_analysis_utils import build_surface_summary
from scripts.btst_latest_followup_utils import load_upstream_shadow_followup_history_by_ticker


REPORTS_DIR = Path("data/reports")
DEFAULT_UPSTREAM_HANDOFF_BOARD_PATH = REPORTS_DIR / "btst_candidate_pool_upstream_handoff_board_latest.json"
DEFAULT_LANE_OBJECTIVE_SUPPORT_PATH = REPORTS_DIR / "btst_candidate_pool_lane_objective_support_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_tplus2_near_cluster_dossier_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_tplus2_near_cluster_dossier_latest.md"
TIER_PRIORITY = {
    "governance_followup": 0,
    "strict_peer": 0,
    "near_cluster_peer": 1,
    "observation_candidate": 2,
    "unclassified": 3,
}


def analyze_btst_tplus2_near_cluster_dossier(
    reports_root: str | Path,
    *,
    anchor_ticker: str = "600988",
    candidate_ticker: str = "600989",
    profile_name: str = "watchlist_zero_catalyst_guard_relief",
    report_name_contains: str = "btst_",
    next_high_hit_threshold: float = 0.02,
    similarity_threshold: float = 1.35,
    near_similarity_threshold: float = 2.1,
    observation_similarity_threshold: float = 2.8,
    recent_window_limit: int = 5,
    upstream_handoff_board_path: str | Path | None = None,
    lane_objective_support_path: str | Path | None = None,
) -> dict[str, Any]:
    rows = _collect_rows(
        reports_root,
        profile_name=profile_name,
        report_name_contains=report_name_contains,
        next_high_hit_threshold=next_high_hit_threshold,
    )
    anchor_profile = _build_anchor_profile(rows, anchor_ticker=anchor_ticker)

    candidate_rows: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("ticker") or "") != candidate_ticker:
            continue
        similarity_score, metric_distances, structure_match = _row_similarity(row, anchor_profile=anchor_profile, tolerances=DEFAULT_TOLERANCES)
        if not metric_distances:
            continue
        peer_tier = _classify_peer_tier(
            row,
            structure_match=structure_match,
            similarity_score=similarity_score,
            strict_similarity_threshold=similarity_threshold,
            near_similarity_threshold=near_similarity_threshold,
            observation_similarity_threshold=observation_similarity_threshold,
        )
        candidate_rows.append(
            {
                **row,
                "similarity_score": similarity_score,
                "metric_distances": metric_distances,
                "structure_match": structure_match,
                "peer_tier": peer_tier,
            }
        )

    per_window_rows: dict[str, list[dict[str, Any]]] = {}
    for row in candidate_rows:
        per_window_rows.setdefault(str(row.get("report_label") or "unknown"), []).append(row)

    per_window_summaries = []
    for report_label, window_rows in sorted(per_window_rows.items()):
        supporting_window_rows = [row for row in window_rows if str(row.get("peer_tier") or "") in {"strict_peer", "near_cluster_peer"}]
        surface_summary = build_surface_summary(window_rows, next_high_hit_threshold=next_high_hit_threshold)
        per_window_summaries.append(
            {
                "report_label": report_label,
                "row_count": len(window_rows),
                "tier_set": sorted({str(row.get("peer_tier") or "none") for row in window_rows}),
                "surface_summary": surface_summary,
                "supporting_row_count": len(supporting_window_rows),
                "supporting_window": bool(supporting_window_rows),
            }
        )

    tier_counts: dict[str, int] = {}
    for row in candidate_rows:
        tier = str(row.get("peer_tier") or "unclassified")
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

    candidate_tier_focus = "unclassified"
    if tier_counts:
        candidate_tier_focus = sorted(
            tier_counts,
            key=lambda tier: (
                TIER_PRIORITY.get(tier, 99),
                -int(tier_counts.get(tier) or 0),
            ),
        )[0]

    supporting_rows = [row for row in candidate_rows if str(row.get("peer_tier") or "") in {"strict_peer", "near_cluster_peer"}]
    tier_focus_rows = [row for row in candidate_rows if str(row.get("peer_tier") or "unclassified") == candidate_tier_focus]
    surface_summary = build_surface_summary(candidate_rows, next_high_hit_threshold=next_high_hit_threshold)
    supporting_surface_summary = build_surface_summary(supporting_rows, next_high_hit_threshold=next_high_hit_threshold)
    tier_focus_surface_summary = build_surface_summary(tier_focus_rows, next_high_hit_threshold=next_high_hit_threshold)
    recent_window_summaries = per_window_summaries[-max(int(recent_window_limit), 0) :] if recent_window_limit > 0 else []
    recent_labels = {str(item.get("report_label") or "") for item in recent_window_summaries}
    recent_supporting_window_count = sum(1 for item in recent_window_summaries if bool(item.get("supporting_window")))
    recent_support_ratio = round(recent_supporting_window_count / len(recent_window_summaries), 4) if recent_window_summaries else 0.0
    recent_supporting_rows = [
        row
        for row in candidate_rows
        if str(row.get("report_label") or "") in recent_labels and str(row.get("peer_tier") or "") in {"strict_peer", "near_cluster_peer"}
    ]
    recent_supporting_surface_summary = build_surface_summary(recent_supporting_rows, next_high_hit_threshold=next_high_hit_threshold)
    recent_tier_rows = [
        row
        for row in candidate_rows
        if str(row.get("report_label") or "") in recent_labels and str(row.get("peer_tier") or "unclassified") == candidate_tier_focus
    ]
    recent_tier_window_count = len({str(row.get("report_label") or "") for row in recent_tier_rows})
    recent_tier_ratio = round(recent_tier_window_count / len(recent_window_summaries), 4) if recent_window_summaries else 0.0
    recent_tier_surface_summary = build_surface_summary(recent_tier_rows, next_high_hit_threshold=next_high_hit_threshold)

    governance_followup = {}
    governance_objective_support = {}
    governance_recent_followup_rows: list[dict[str, Any]] = []
    resolved_upstream_handoff_board_path = Path(upstream_handoff_board_path or DEFAULT_UPSTREAM_HANDOFF_BOARD_PATH).expanduser().resolve()
    if resolved_upstream_handoff_board_path.exists():
        upstream_handoff_board = json.loads(resolved_upstream_handoff_board_path.read_text(encoding="utf-8"))
        governance_followup = next(
            (
                dict(row or {})
                for row in list(upstream_handoff_board.get("board_rows") or [])
                if str((row or {}).get("ticker") or "") == candidate_ticker
                and str((row or {}).get("downstream_followup_lane") or "") == "t_plus_2_continuation_review"
            ),
            {},
        )
    resolved_lane_objective_support_path = Path(lane_objective_support_path or DEFAULT_LANE_OBJECTIVE_SUPPORT_PATH).expanduser().resolve()
    if resolved_lane_objective_support_path.exists():
        lane_objective_support = json.loads(resolved_lane_objective_support_path.read_text(encoding="utf-8"))
        governance_objective_support = next(
            (
                dict(row or {})
                for row in list(lane_objective_support.get("ticker_rows") or [])
                if str((row or {}).get("ticker") or "") == candidate_ticker
            ),
            {},
        )
    governance_recent_followup_rows = [
        dict(row or {})
        for row in list(load_upstream_shadow_followup_history_by_ticker(reports_root).get(candidate_ticker) or [])
    ]
    if not per_window_summaries and governance_followup and governance_recent_followup_rows:
        per_window_summaries = [
            {
                "report_label": str(row.get("trade_date") or row.get("report_dir") or "unknown"),
                "row_count": 1,
                "tier_set": [f"governance_followup_{str(row.get('decision') or 'unknown')}"],
                "surface_summary": {},
                "supporting_row_count": 1 if str(row.get("decision") or "") in {"near_miss", "selected"} else 0,
                "supporting_window": str(row.get("decision") or "") in {"near_miss", "selected"},
                "report_dir": row.get("report_dir"),
                "decision": row.get("decision"),
                "candidate_source": row.get("candidate_source"),
                "downstream_bottleneck": row.get("downstream_bottleneck"),
                "score_target": row.get("score_target"),
            }
            for row in governance_recent_followup_rows
        ]
        recent_window_summaries = per_window_summaries[: max(int(recent_window_limit), 0)] if recent_window_limit > 0 else []
        recent_supporting_window_count = sum(1 for item in recent_window_summaries if bool(item.get("supporting_window")))
        recent_support_ratio = round(recent_supporting_window_count / len(recent_window_summaries), 4) if recent_window_summaries else 0.0
        recent_tier_window_count = len(recent_window_summaries)
        recent_tier_ratio = 1.0 if recent_window_summaries else 0.0

    if tier_counts.get("strict_peer"):
        verdict = "strict_peer_candidate"
    elif tier_counts.get("near_cluster_peer"):
        verdict = "near_cluster_candidate"
    elif candidate_rows:
        verdict = "observation_only_candidate"
    elif governance_followup:
        verdict = "governance_followup_candidate"
    else:
        verdict = "candidate_not_found"

    if verdict == "governance_followup_candidate":
        recent_validation_verdict = "governance_followup_pending_evidence"
    elif not recent_window_summaries:
        recent_validation_verdict = "no_recent_windows"
    elif recent_supporting_window_count == 0:
        recent_validation_verdict = "recent_support_absent"
    elif recent_support_ratio < 0.5:
        recent_validation_verdict = "recent_support_thin"
    elif (
        float(recent_supporting_surface_summary.get("next_close_positive_rate") or 0.0) >= 0.5
        and float(recent_supporting_surface_summary.get("t_plus_2_close_positive_rate") or 0.0) >= 0.5
    ):
        recent_validation_verdict = "recent_support_confirmed"
    else:
        recent_validation_verdict = "recent_support_mixed"

    if verdict == "governance_followup_candidate":
        candidate_tier_focus = "governance_followup"
        recent_tier_verdict = "governance_followup_pending_evidence"
    else:
        recent_tier_verdict = _classify_recent_tier_verdict(
            recent_tier_window_count,
            len(recent_window_summaries),
            recent_tier_surface_summary,
        )
    if candidate_tier_focus == "strict_peer" and recent_tier_verdict == "recent_tier_confirmed":
        promotion_readiness_verdict = "strict_peer_ready"
    elif candidate_tier_focus == "near_cluster_peer" and recent_tier_verdict == "recent_tier_confirmed":
        promotion_readiness_verdict = "watchlist_ready"
    elif candidate_tier_focus == "observation_candidate" and recent_tier_verdict == "recent_tier_confirmed":
        promotion_readiness_verdict = "validation_queue_ready"
    elif candidate_tier_focus == "observation_candidate" and recent_tier_verdict in {"recent_tier_mixed", "recent_tier_thin"}:
        promotion_readiness_verdict = "validation_queue_watch"
    elif candidate_tier_focus == "governance_followup":
        promotion_readiness_verdict = "governance_validation_required"
    elif verdict == "candidate_not_found":
        promotion_readiness_verdict = "candidate_not_found"
    else:
        promotion_readiness_verdict = "low_priority"

    if candidate_tier_focus == "governance_followup" and governance_objective_support:
        tier_focus_surface_summary = {
            "next_close_positive_rate": governance_objective_support.get("next_close_positive_rate"),
            "t_plus_2_close_positive_rate": governance_objective_support.get("t_plus_2_positive_rate"),
            "t_plus_2_close_return_distribution": {
                "mean": governance_objective_support.get("mean_t_plus_2_return"),
            },
            "next_high_hit_rate_at_threshold": governance_objective_support.get("next_high_hit_rate_at_threshold"),
            "closed_cycle_count": governance_objective_support.get("closed_cycle_count"),
        }
        recent_tier_surface_summary = dict(tier_focus_surface_summary)

    return {
        "reports_root": str(Path(reports_root).expanduser().resolve()),
        "anchor_ticker": anchor_ticker,
        "candidate_ticker": candidate_ticker,
        "candidate_row_count": len(candidate_rows),
        "supporting_row_count": len(supporting_rows),
        "tier_counts": tier_counts,
        "verdict": verdict,
        "candidate_tier_focus": candidate_tier_focus,
        "governance_followup": governance_followup,
        "governance_objective_support": governance_objective_support,
        "governance_recent_followup_rows": governance_recent_followup_rows,
        "tier_focus_row_count": len(tier_focus_rows),
        "recent_window_limit": recent_window_limit,
        "recent_window_count": len(recent_window_summaries),
        "recent_supporting_window_count": recent_supporting_window_count,
        "recent_support_ratio": recent_support_ratio,
        "recent_validation_verdict": recent_validation_verdict,
        "recent_tier_window_count": recent_tier_window_count,
        "recent_tier_ratio": recent_tier_ratio,
        "recent_tier_verdict": recent_tier_verdict,
        "promotion_readiness_verdict": promotion_readiness_verdict,
        "supporting_surface_summary": supporting_surface_summary,
        "recent_supporting_surface_summary": recent_supporting_surface_summary,
        "tier_focus_surface_summary": tier_focus_surface_summary,
        "recent_tier_surface_summary": recent_tier_surface_summary,
        "all_surface_summary": surface_summary,
        "recent_window_summaries": recent_window_summaries,
        "per_window_summaries": per_window_summaries,
    }


def render_btst_tplus2_near_cluster_dossier_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST T+2 Near-Cluster Dossier")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- anchor_ticker: {analysis['anchor_ticker']}")
    lines.append(f"- candidate_ticker: {analysis['candidate_ticker']}")
    lines.append(f"- candidate_row_count: {analysis['candidate_row_count']}")
    lines.append(f"- supporting_row_count: {analysis['supporting_row_count']}")
    lines.append(f"- tier_counts: {analysis['tier_counts']}")
    lines.append(f"- verdict: {analysis['verdict']}")
    lines.append(f"- candidate_tier_focus: {analysis['candidate_tier_focus']}")
    lines.append(f"- governance_followup: {analysis.get('governance_followup')}")
    lines.append(f"- governance_objective_support: {analysis.get('governance_objective_support')}")
    lines.append(f"- governance_recent_followup_rows: {analysis.get('governance_recent_followup_rows')}")
    lines.append(f"- tier_focus_row_count: {analysis['tier_focus_row_count']}")
    lines.append(f"- recent_window_limit: {analysis['recent_window_limit']}")
    lines.append(f"- recent_window_count: {analysis['recent_window_count']}")
    lines.append(f"- recent_supporting_window_count: {analysis['recent_supporting_window_count']}")
    lines.append(f"- recent_support_ratio: {analysis['recent_support_ratio']}")
    lines.append(f"- recent_validation_verdict: {analysis['recent_validation_verdict']}")
    lines.append(f"- recent_tier_window_count: {analysis['recent_tier_window_count']}")
    lines.append(f"- recent_tier_ratio: {analysis['recent_tier_ratio']}")
    lines.append(f"- recent_tier_verdict: {analysis['recent_tier_verdict']}")
    lines.append(f"- promotion_readiness_verdict: {analysis['promotion_readiness_verdict']}")
    lines.append(f"- supporting_surface_summary: {analysis['supporting_surface_summary']}")
    lines.append(f"- recent_supporting_surface_summary: {analysis['recent_supporting_surface_summary']}")
    lines.append(f"- tier_focus_surface_summary: {analysis['tier_focus_surface_summary']}")
    lines.append(f"- recent_tier_surface_summary: {analysis['recent_tier_surface_summary']}")
    lines.append(f"- all_surface_summary: {analysis['all_surface_summary']}")
    lines.append("")
    lines.append("## Recent Windows")
    for item in list(analysis.get("recent_window_summaries") or []):
        lines.append(
            f"- {item['report_label']}: row_count={item['row_count']}, supporting_window={item['supporting_window']}, "
            f"supporting_row_count={item['supporting_row_count']}, tier_set={item['tier_set']}, "
            f"next_close_positive_rate={item['surface_summary'].get('next_close_positive_rate')}, "
            f"t_plus_2_close_positive_rate={item['surface_summary'].get('t_plus_2_close_positive_rate')}"
        )
    if not list(analysis.get("recent_window_summaries") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Per-Window")
    for item in list(analysis.get("per_window_summaries") or []):
        lines.append(
            f"- {item['report_label']}: row_count={item['row_count']}, supporting_window={item['supporting_window']}, "
            f"supporting_row_count={item['supporting_row_count']}, tier_set={item['tier_set']}, "
            f"next_close_positive_rate={item['surface_summary'].get('next_close_positive_rate')}, "
            f"t_plus_2_close_positive_rate={item['surface_summary'].get('t_plus_2_close_positive_rate')}"
        )
    if not list(analysis.get("per_window_summaries") or []):
        lines.append("- none")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a multi-window dossier for a continuation near-cluster candidate.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR))
    parser.add_argument("--anchor-ticker", default="600988")
    parser.add_argument("--candidate-ticker", default="600989")
    parser.add_argument("--profile-name", default="watchlist_zero_catalyst_guard_relief")
    parser.add_argument("--report-name-contains", default="btst_")
    parser.add_argument("--recent-window-limit", type=int, default=5)
    parser.add_argument("--upstream-handoff-board-path", default=str(DEFAULT_UPSTREAM_HANDOFF_BOARD_PATH))
    parser.add_argument("--lane-objective-support-path", default=str(DEFAULT_LANE_OBJECTIVE_SUPPORT_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_tplus2_near_cluster_dossier(
        args.reports_root,
        anchor_ticker=str(args.anchor_ticker or "600988"),
        candidate_ticker=str(args.candidate_ticker or "600989"),
        profile_name=str(args.profile_name or "watchlist_zero_catalyst_guard_relief"),
        report_name_contains=str(args.report_name_contains or "btst_"),
        recent_window_limit=int(args.recent_window_limit),
        upstream_handoff_board_path=args.upstream_handoff_board_path,
        lane_objective_support_path=args.lane_objective_support_path,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_tplus2_near_cluster_dossier_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
