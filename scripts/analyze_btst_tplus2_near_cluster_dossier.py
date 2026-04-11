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
from scripts.btst_report_utils import normalize_trade_date
from src.paper_trading.frozen_replay import load_frozen_post_market_plans


REPORTS_DIR = Path("data/reports")
DEFAULT_UPSTREAM_HANDOFF_BOARD_PATH = REPORTS_DIR / "btst_candidate_pool_upstream_handoff_board_latest.json"
DEFAULT_LANE_OBJECTIVE_SUPPORT_PATH = REPORTS_DIR / "btst_candidate_pool_lane_objective_support_latest.json"
DEFAULT_REPORT_MANIFEST_PATH = REPORTS_DIR / "report_manifest_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_tplus2_near_cluster_dossier_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_tplus2_near_cluster_dossier_latest.md"
TIER_PRIORITY = {
    "governance_followup": 0,
    "strict_peer": 0,
    "near_cluster_peer": 1,
    "observation_candidate": 2,
    "unclassified": 3,
}


def _is_continuation_governance_followup(row: dict[str, Any]) -> bool:
    payload = dict(row or {})
    latest_followup_decision = str(payload.get("latest_followup_decision") or "").strip()
    downstream_followup_lane = str(payload.get("downstream_followup_lane") or "").strip()
    downstream_followup_status = str(payload.get("downstream_followup_status") or "").strip()
    board_phase = str(payload.get("board_phase") or "").strip()
    blocker = str(payload.get("downstream_followup_blocker") or "").strip()
    if downstream_followup_lane == "t_plus_2_continuation_review":
        return True
    if downstream_followup_status in {"continuation_confirm_then_review", "continuation_only_confirm_then_review"}:
        return True
    if latest_followup_decision and latest_followup_decision not in {"near_miss", "selected"}:
        return False
    return board_phase == "post_recall_downstream_followup" and blocker == "no_selected_persistence_or_independent_edge"


def governance_followup_payoff_confirmed(
    governance_objective_support: dict[str, Any],
    *,
    recent_tier_window_count: int,
    recent_window_count: int,
) -> bool:
    return (
        recent_tier_window_count >= 3
        and recent_window_count >= 3
        and int(governance_objective_support.get("closed_cycle_count") or 0) >= 10
        and float(governance_objective_support.get("next_close_positive_rate") or 0.0) >= 0.75
        and float(governance_objective_support.get("t_plus_2_positive_rate") or 0.0) >= 0.75
        and float(governance_objective_support.get("t_plus_2_return_hit_rate_at_target") or 0.0) >= 0.75
        and float(governance_objective_support.get("mean_t_plus_2_return") or 0.0) >= 0.03
    )


def _plan_contains_focus_ticker(plan_payload: dict[str, Any], candidate_ticker: str) -> bool:
    filters = dict(dict(dict(plan_payload.get("risk_metrics") or {}).get("funnel_diagnostics") or {}).get("filters") or {})
    for filter_key in ("short_trade_candidates", "watchlist"):
        filter_payload = dict(filters.get(filter_key) or {})
        tickers = list(filter_payload.get("tickers") or [])
        if any(str(item) == candidate_ticker or (isinstance(item, dict) and str(item.get("ticker") or "") == candidate_ticker) for item in tickers):
            return True
        released_shadow_entries = list(filter_payload.get("released_shadow_entries") or [])
        if any(str(dict(item or {}).get("ticker") or "") == candidate_ticker for item in released_shadow_entries):
            return True
    return False


def _extract_current_plan_visibility_summary(reports_root: str | Path, candidate_ticker: str) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    raw_daily_events_trade_dates: set[str] = set()
    current_plan_visible_trade_dates: set[str] = set()
    current_plan_visibility_gap_trade_dates: set[str] = set()
    current_plan_visible_report_dirs: set[str] = set()
    current_plan_visibility_gap_report_dirs: set[str] = set()

    for daily_events_path in sorted(resolved_reports_root.rglob("daily_events.jsonl")):
        try:
            raw_text = daily_events_path.read_text(encoding="utf-8")
        except OSError:
            continue
        if candidate_ticker not in raw_text:
            continue
        try:
            plans_by_date = load_frozen_post_market_plans(daily_events_path)
        except ValueError:
            continue
        for trade_date, plan in plans_by_date.items():
            normalized_trade_date = normalize_trade_date(trade_date)
            if normalized_trade_date is None:
                continue
            raw_daily_events_trade_dates.add(normalized_trade_date)
            report_dir = str(daily_events_path.parent.resolve())
            if _plan_contains_focus_ticker(plan.model_dump(mode="json"), candidate_ticker):
                current_plan_visible_trade_dates.add(normalized_trade_date)
                current_plan_visible_report_dirs.add(report_dir)
            else:
                current_plan_visibility_gap_trade_dates.add(normalized_trade_date)
                current_plan_visibility_gap_report_dirs.add(report_dir)

    return {
        "raw_daily_events_trade_dates": sorted(raw_daily_events_trade_dates),
        "raw_daily_events_trade_date_count": len(raw_daily_events_trade_dates),
        "current_plan_visible_trade_dates": sorted(current_plan_visible_trade_dates),
        "current_plan_visible_trade_date_count": len(current_plan_visible_trade_dates),
        "current_plan_visible_report_dirs": sorted(current_plan_visible_report_dirs),
        "current_plan_visible_report_count": len(current_plan_visible_report_dirs),
        "current_plan_visibility_gap_trade_dates": sorted(current_plan_visibility_gap_trade_dates - current_plan_visible_trade_dates),
        "current_plan_visibility_gap_trade_date_count": len(current_plan_visibility_gap_trade_dates - current_plan_visible_trade_dates),
        "current_plan_visibility_gap_report_dirs": sorted(current_plan_visibility_gap_report_dirs - current_plan_visible_report_dirs),
        "current_plan_visibility_gap_report_count": len(current_plan_visibility_gap_report_dirs - current_plan_visible_report_dirs),
    }


def _load_continuation_promotion_ready_summary(reports_root: str | Path, candidate_ticker: str) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    manifest_path = resolved_reports_root / DEFAULT_REPORT_MANIFEST_PATH.name
    if not manifest_path.exists():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    summary = dict(payload.get("continuation_promotion_ready_summary") or {})
    if str(summary.get("focus_ticker") or "").strip() != str(candidate_ticker or "").strip():
        return {}
    return summary


def _collect_candidate_rows_for_dossier(
    rows: list[dict[str, Any]],
    *,
    anchor_ticker: str,
    candidate_ticker: str,
    similarity_threshold: float,
    near_similarity_threshold: float,
    observation_similarity_threshold: float,
) -> list[dict[str, Any]]:
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
    return candidate_rows


def _summarize_candidate_windows(
    candidate_rows: list[dict[str, Any]],
    *,
    next_high_hit_threshold: float,
    recent_window_limit: int,
) -> dict[str, Any]:
    per_window_rows: dict[str, list[dict[str, Any]]] = {}
    for row in candidate_rows:
        per_window_rows.setdefault(str(row.get("report_label") or "unknown"), []).append(row)
    per_window_summaries = _build_per_window_summaries(per_window_rows, next_high_hit_threshold=next_high_hit_threshold)
    tier_counts = _count_candidate_tiers(candidate_rows)
    candidate_tier_focus = _resolve_candidate_tier_focus(tier_counts)
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
    return {
        "per_window_summaries": per_window_summaries,
        "tier_counts": tier_counts,
        "candidate_tier_focus": candidate_tier_focus,
        "supporting_rows": supporting_rows,
        "tier_focus_rows": tier_focus_rows,
        "surface_summary": surface_summary,
        "supporting_surface_summary": supporting_surface_summary,
        "tier_focus_surface_summary": tier_focus_surface_summary,
        "recent_window_summaries": recent_window_summaries,
        "recent_supporting_window_count": recent_supporting_window_count,
        "recent_support_ratio": recent_support_ratio,
        "recent_supporting_surface_summary": recent_supporting_surface_summary,
        "recent_tier_window_count": recent_tier_window_count,
        "recent_tier_ratio": recent_tier_ratio,
        "recent_tier_surface_summary": recent_tier_surface_summary,
    }


def _build_per_window_summaries(
    per_window_rows: dict[str, list[dict[str, Any]]],
    *,
    next_high_hit_threshold: float,
) -> list[dict[str, Any]]:
    per_window_summaries: list[dict[str, Any]] = []
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
    return per_window_summaries


def _count_candidate_tiers(candidate_rows: list[dict[str, Any]]) -> dict[str, int]:
    tier_counts: dict[str, int] = {}
    for row in candidate_rows:
        tier = str(row.get("peer_tier") or "unclassified")
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    return tier_counts


def _resolve_candidate_tier_focus(tier_counts: dict[str, int]) -> str:
    if not tier_counts:
        return "unclassified"
    return sorted(
        tier_counts,
        key=lambda tier: (
            TIER_PRIORITY.get(tier, 99),
            -int(tier_counts.get(tier) or 0),
        ),
    )[0]


def _load_governance_context(
    reports_root: str | Path,
    *,
    candidate_ticker: str,
    upstream_handoff_board_path: str | Path | None,
    lane_objective_support_path: str | Path | None,
) -> dict[str, Any]:
    governance_followup = {}
    governance_objective_support = {}
    resolved_upstream_handoff_board_path = Path(upstream_handoff_board_path or DEFAULT_UPSTREAM_HANDOFF_BOARD_PATH).expanduser().resolve()
    if resolved_upstream_handoff_board_path.exists():
        upstream_handoff_board = json.loads(resolved_upstream_handoff_board_path.read_text(encoding="utf-8"))
        governance_followup = next(
            (
                dict(row or {})
                for row in list(upstream_handoff_board.get("board_rows") or [])
                if str((row or {}).get("ticker") or "") == candidate_ticker
                and _is_continuation_governance_followup(dict(row or {}))
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
    return {
        "governance_followup": governance_followup,
        "governance_objective_support": governance_objective_support,
        "governance_recent_followup_rows": governance_recent_followup_rows,
    }


def _apply_governance_window_fallback(
    *,
    per_window_summaries: list[dict[str, Any]],
    governance_followup: dict[str, Any],
    governance_recent_followup_rows: list[dict[str, Any]],
    recent_window_limit: int,
) -> dict[str, Any]:
    updated_per_window_summaries = list(per_window_summaries)
    if not updated_per_window_summaries and governance_followup and governance_recent_followup_rows:
        updated_per_window_summaries = [
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
    recent_window_summaries = updated_per_window_summaries[: max(int(recent_window_limit), 0)] if recent_window_limit > 0 else []
    recent_supporting_window_count = sum(1 for item in recent_window_summaries if bool(item.get("supporting_window")))
    recent_support_ratio = round(recent_supporting_window_count / len(recent_window_summaries), 4) if recent_window_summaries else 0.0
    recent_tier_window_count = len(recent_window_summaries)
    recent_tier_ratio = 1.0 if recent_window_summaries else 0.0
    return {
        "per_window_summaries": updated_per_window_summaries,
        "recent_window_summaries": recent_window_summaries,
        "recent_supporting_window_count": recent_supporting_window_count,
        "recent_support_ratio": recent_support_ratio,
        "recent_tier_window_count": recent_tier_window_count,
        "recent_tier_ratio": recent_tier_ratio,
    }


def _resolve_dossier_verdict(
    *,
    tier_counts: dict[str, int],
    candidate_rows: list[dict[str, Any]],
    governance_followup: dict[str, Any],
) -> str:
    if tier_counts.get("strict_peer"):
        return "strict_peer_candidate"
    if tier_counts.get("near_cluster_peer"):
        return "near_cluster_candidate"
    if candidate_rows:
        return "observation_only_candidate"
    if governance_followup:
        return "governance_followup_candidate"
    return "candidate_not_found"


def _resolve_recent_validation_verdict(
    *,
    verdict: str,
    recent_window_summaries: list[dict[str, Any]],
    recent_supporting_window_count: int,
    recent_support_ratio: float,
    recent_supporting_surface_summary: dict[str, Any],
) -> str:
    if verdict == "governance_followup_candidate":
        return "governance_followup_pending_evidence"
    if not recent_window_summaries:
        return "no_recent_windows"
    if recent_supporting_window_count == 0:
        return "recent_support_absent"
    if recent_support_ratio < 0.5:
        return "recent_support_thin"
    if (
        float(recent_supporting_surface_summary.get("next_close_positive_rate") or 0.0) >= 0.5
        and float(recent_supporting_surface_summary.get("t_plus_2_close_positive_rate") or 0.0) >= 0.5
    ):
        return "recent_support_confirmed"
    return "recent_support_mixed"


def _resolve_promotion_readiness_verdict(
    *,
    candidate_tier_focus: str,
    recent_tier_verdict: str,
    verdict: str,
    continuation_promotion_ready_summary: dict[str, Any],
) -> str:
    if candidate_tier_focus == "strict_peer" and recent_tier_verdict == "recent_tier_confirmed":
        promotion_readiness_verdict = "strict_peer_ready"
    elif candidate_tier_focus == "near_cluster_peer" and recent_tier_verdict == "recent_tier_confirmed":
        promotion_readiness_verdict = "watchlist_ready"
    elif candidate_tier_focus == "observation_candidate" and recent_tier_verdict == "recent_tier_confirmed":
        promotion_readiness_verdict = "validation_queue_ready"
    elif candidate_tier_focus == "observation_candidate" and recent_tier_verdict in {"recent_tier_mixed", "recent_tier_thin"}:
        promotion_readiness_verdict = "validation_queue_watch"
    elif candidate_tier_focus == "governance_followup" and recent_tier_verdict == "governance_followup_payoff_confirmed":
        promotion_readiness_verdict = "watch_review_ready"
    elif candidate_tier_focus == "governance_followup":
        promotion_readiness_verdict = "governance_validation_required"
    elif verdict == "candidate_not_found":
        promotion_readiness_verdict = "candidate_not_found"
    else:
        promotion_readiness_verdict = "low_priority"
    if str(continuation_promotion_ready_summary.get("promotion_merge_review_verdict") or "").strip() == "ready_for_default_btst_merge_review":
        return "merge_review_ready"
    return promotion_readiness_verdict


def _resolve_recent_tier_state(
    *,
    verdict: str,
    candidate_tier_focus: str,
    governance_objective_support: dict[str, Any],
    recent_tier_window_count: int,
    recent_window_count: int,
    recent_window_summaries: list[dict[str, Any]],
    recent_tier_surface_summary: dict[str, Any],
) -> tuple[str, bool]:
    governance_payoff_ready = governance_followup_payoff_confirmed(
        governance_objective_support,
        recent_tier_window_count=recent_tier_window_count,
        recent_window_count=recent_window_count,
    )
    if verdict == "governance_followup_candidate":
        return ("governance_followup_payoff_confirmed" if governance_payoff_ready else "governance_followup_pending_evidence"), governance_payoff_ready
    return (
        _classify_recent_tier_verdict(
            recent_tier_window_count,
            len(recent_window_summaries),
            recent_tier_surface_summary,
        ),
        governance_payoff_ready,
    )


def _build_near_cluster_dossier_analysis(
    *,
    reports_root: str | Path,
    anchor_ticker: str,
    candidate_ticker: str,
    candidate_rows: list[dict[str, Any]],
    supporting_rows: list[dict[str, Any]],
    tier_counts: dict[str, int],
    verdict: str,
    candidate_tier_focus: str,
    governance_followup: dict[str, Any],
    governance_objective_support: dict[str, Any],
    governance_recent_followup_rows: list[dict[str, Any]],
    current_plan_visibility_summary: dict[str, Any],
    continuation_promotion_ready_summary: dict[str, Any],
    latest_followup_decision: str | None,
    downstream_followup_status: str | None,
    recent_window_limit: int,
    recent_window_summaries: list[dict[str, Any]],
    recent_supporting_window_count: int,
    recent_support_ratio: float,
    recent_validation_verdict: str,
    recent_tier_window_count: int,
    recent_tier_ratio: float,
    recent_tier_verdict: str,
    promotion_readiness_verdict: str,
    supporting_surface_summary: dict[str, Any],
    recent_supporting_surface_summary: dict[str, Any],
    tier_focus_surface_summary: dict[str, Any],
    recent_tier_surface_summary: dict[str, Any],
    surface_summary: dict[str, Any],
    per_window_summaries: list[dict[str, Any]],
    tier_focus_rows: list[dict[str, Any]],
) -> dict[str, Any]:
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
        "current_plan_visibility_summary": current_plan_visibility_summary,
        "continuation_promotion_ready_summary": continuation_promotion_ready_summary,
        "latest_followup_decision": latest_followup_decision,
        "downstream_followup_status": downstream_followup_status,
        "current_plan_visible_trade_dates": list(current_plan_visibility_summary.get("current_plan_visible_trade_dates") or []),
        "current_plan_visibility_gap_trade_dates": list(current_plan_visibility_summary.get("current_plan_visibility_gap_trade_dates") or []),
        "qualifying_window_buckets": list(continuation_promotion_ready_summary.get("qualifying_window_buckets") or []),
        "promotion_path_status": continuation_promotion_ready_summary.get("promotion_path_status"),
        "promotion_merge_review_verdict": continuation_promotion_ready_summary.get("promotion_merge_review_verdict"),
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
    current_plan_visibility_summary = _extract_current_plan_visibility_summary(reports_root, candidate_ticker)
    continuation_promotion_ready_summary = _load_continuation_promotion_ready_summary(reports_root, candidate_ticker)
    candidate_rows = _collect_candidate_rows_for_dossier(
        rows,
        anchor_ticker=anchor_ticker,
        candidate_ticker=candidate_ticker,
        similarity_threshold=similarity_threshold,
        near_similarity_threshold=near_similarity_threshold,
        observation_similarity_threshold=observation_similarity_threshold,
    )
    window_summary = _summarize_candidate_windows(
        candidate_rows,
        next_high_hit_threshold=next_high_hit_threshold,
        recent_window_limit=recent_window_limit,
    )
    per_window_summaries = window_summary["per_window_summaries"]
    tier_counts = window_summary["tier_counts"]
    candidate_tier_focus = window_summary["candidate_tier_focus"]
    supporting_rows = window_summary["supporting_rows"]
    tier_focus_rows = window_summary["tier_focus_rows"]
    surface_summary = window_summary["surface_summary"]
    supporting_surface_summary = window_summary["supporting_surface_summary"]
    tier_focus_surface_summary = window_summary["tier_focus_surface_summary"]
    recent_window_summaries = window_summary["recent_window_summaries"]
    recent_supporting_window_count = window_summary["recent_supporting_window_count"]
    recent_support_ratio = window_summary["recent_support_ratio"]
    recent_supporting_surface_summary = window_summary["recent_supporting_surface_summary"]
    recent_tier_window_count = window_summary["recent_tier_window_count"]
    recent_tier_ratio = window_summary["recent_tier_ratio"]
    recent_tier_surface_summary = window_summary["recent_tier_surface_summary"]
    governance_context = _load_governance_context(
        reports_root,
        candidate_ticker=candidate_ticker,
        upstream_handoff_board_path=upstream_handoff_board_path,
        lane_objective_support_path=lane_objective_support_path,
    )
    governance_followup = governance_context["governance_followup"]
    governance_objective_support = governance_context["governance_objective_support"]
    governance_recent_followup_rows = governance_context["governance_recent_followup_rows"]
    if not per_window_summaries and governance_followup and governance_recent_followup_rows:
        fallback_summary = _apply_governance_window_fallback(
            per_window_summaries=per_window_summaries,
            governance_followup=governance_followup,
            governance_recent_followup_rows=governance_recent_followup_rows,
            recent_window_limit=recent_window_limit,
        )
        per_window_summaries = fallback_summary["per_window_summaries"]
        recent_window_summaries = fallback_summary["recent_window_summaries"]
        recent_supporting_window_count = fallback_summary["recent_supporting_window_count"]
        recent_support_ratio = fallback_summary["recent_support_ratio"]
        recent_tier_window_count = fallback_summary["recent_tier_window_count"]
        recent_tier_ratio = fallback_summary["recent_tier_ratio"]
    verdict = _resolve_dossier_verdict(
        tier_counts=tier_counts,
        candidate_rows=candidate_rows,
        governance_followup=governance_followup,
    )
    recent_validation_verdict = _resolve_recent_validation_verdict(
        verdict=verdict,
        recent_window_summaries=recent_window_summaries,
        recent_supporting_window_count=recent_supporting_window_count,
        recent_support_ratio=recent_support_ratio,
        recent_supporting_surface_summary=recent_supporting_surface_summary,
    )
    recent_tier_verdict, governance_payoff_ready = _resolve_recent_tier_state(
        verdict=verdict,
        candidate_tier_focus=candidate_tier_focus,
        governance_objective_support=governance_objective_support,
        recent_tier_window_count=recent_tier_window_count,
        recent_window_count=len(recent_window_summaries),
        recent_window_summaries=recent_window_summaries,
        recent_tier_surface_summary=recent_tier_surface_summary,
    )
    if verdict == "governance_followup_candidate":
        candidate_tier_focus = "governance_followup"
    promotion_readiness_verdict = _resolve_promotion_readiness_verdict(
        candidate_tier_focus=candidate_tier_focus,
        recent_tier_verdict=recent_tier_verdict,
        verdict=verdict,
        continuation_promotion_ready_summary=continuation_promotion_ready_summary,
    )

    latest_followup_decision = str(governance_followup.get("latest_followup_decision") or "").strip() or None
    downstream_followup_status = str(governance_followup.get("downstream_followup_status") or "").strip() or None

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

    return _build_near_cluster_dossier_analysis(
        reports_root=reports_root,
        anchor_ticker=anchor_ticker,
        candidate_ticker=candidate_ticker,
        candidate_rows=candidate_rows,
        supporting_rows=supporting_rows,
        tier_counts=tier_counts,
        verdict=verdict,
        candidate_tier_focus=candidate_tier_focus,
        governance_followup=governance_followup,
        governance_objective_support=governance_objective_support,
        governance_recent_followup_rows=governance_recent_followup_rows,
        current_plan_visibility_summary=current_plan_visibility_summary,
        continuation_promotion_ready_summary=continuation_promotion_ready_summary,
        latest_followup_decision=latest_followup_decision,
        downstream_followup_status=downstream_followup_status,
        recent_window_limit=recent_window_limit,
        recent_window_summaries=recent_window_summaries,
        recent_supporting_window_count=recent_supporting_window_count,
        recent_support_ratio=recent_support_ratio,
        recent_validation_verdict=recent_validation_verdict,
        recent_tier_window_count=recent_tier_window_count,
        recent_tier_ratio=recent_tier_ratio,
        recent_tier_verdict=recent_tier_verdict,
        promotion_readiness_verdict=promotion_readiness_verdict,
        supporting_surface_summary=supporting_surface_summary,
        recent_supporting_surface_summary=recent_supporting_surface_summary,
        tier_focus_surface_summary=tier_focus_surface_summary,
        recent_tier_surface_summary=recent_tier_surface_summary,
        surface_summary=surface_summary,
        per_window_summaries=per_window_summaries,
        tier_focus_rows=tier_focus_rows,
    )


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
    lines.append(f"- current_plan_visibility_summary: {analysis.get('current_plan_visibility_summary')}")
    lines.append(f"- continuation_promotion_ready_summary: {analysis.get('continuation_promotion_ready_summary')}")
    lines.append(f"- latest_followup_decision: {analysis.get('latest_followup_decision')}")
    lines.append(f"- downstream_followup_status: {analysis.get('downstream_followup_status')}")
    lines.append(f"- current_plan_visible_trade_dates: {analysis.get('current_plan_visible_trade_dates')}")
    lines.append(f"- current_plan_visibility_gap_trade_dates: {analysis.get('current_plan_visibility_gap_trade_dates')}")
    lines.append(f"- qualifying_window_buckets: {analysis.get('qualifying_window_buckets')}")
    lines.append(f"- promotion_path_status: {analysis.get('promotion_path_status')}")
    lines.append(f"- promotion_merge_review_verdict: {analysis.get('promotion_merge_review_verdict')}")
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
