from __future__ import annotations

from collections.abc import Callable
from typing import Any


ExtractPrioritySummary = Callable[[dict[str, Any]], dict[str, int]]
ResolvePriorityHandoffExperiment = Callable[..., dict[str, Any]]
BuildPriorityHandoffExperimentWhyNowParts = Callable[[dict[str, Any]], list[str]]
BuildPriorityHandoffExperimentNextStep = Callable[[dict[str, Any]], str]
NormalizePrimaryShadowReplay = Callable[[Any], dict[str, Any]]
CollectControlTowerTickerSet = Callable[[dict[str, Any], str], set[str]]
FindCandidatePoolFocusLiquidityProfile = Callable[[dict[str, Any], str], dict[str, Any]]
AppendPrimaryShadowReplayContext = Callable[[list[str], dict[str, Any]], None]
AppendTruncationContext = Callable[..., None]
BuildCorridorPrimaryShadowNextStep = Callable[..., str]


def build_recall_priority_task(
    latest_btst_snapshot: dict[str, Any],
    control_tower_snapshot: dict[str, Any],
    *,
    extract_priority_summary: ExtractPrioritySummary,
    resolve_priority_handoff_experiment: ResolvePriorityHandoffExperiment,
    build_priority_handoff_experiment_why_now_parts: BuildPriorityHandoffExperimentWhyNowParts,
    build_priority_handoff_experiment_next_step: BuildPriorityHandoffExperimentNextStep,
) -> dict[str, Any] | None:
    priority_summary = extract_priority_summary(latest_btst_snapshot)
    if int(priority_summary.get("primary_count") or 0) > 0:
        return None

    candidate_pool_recall_dossier = dict(control_tower_snapshot.get("candidate_pool_recall_dossier") or {})
    dominant_stage = str(candidate_pool_recall_dossier.get("dominant_stage") or "").strip()
    if not dominant_stage:
        return None

    active_upstream_focus_tickers = list(control_tower_snapshot.get("active_candidate_pool_upstream_handoff_focus_tickers") or [])[:3]
    top_stage_tickers = list(dict(candidate_pool_recall_dossier.get("top_stage_tickers") or {}).get(dominant_stage) or [])[:3]
    focus_tickers = active_upstream_focus_tickers if dominant_stage == "candidate_pool_truncated_after_filters" and active_upstream_focus_tickers else top_stage_tickers
    priority_handoff_experiment = resolve_priority_handoff_experiment(
        candidate_pool_recall_dossier=candidate_pool_recall_dossier,
        focus_tickers=focus_tickers,
    )
    frontier_verdict = str(dict(candidate_pool_recall_dossier.get("truncation_frontier_summary") or {}).get("frontier_verdict") or "").strip()
    why_now_parts = [
        "latest BTST still has 0 primary selections",
        f"dominant recall stage={dominant_stage}",
    ]
    if focus_tickers:
        why_now_parts.append(f"focus_tickers={focus_tickers}")
    if frontier_verdict:
        why_now_parts.append(f"frontier_verdict={frontier_verdict}")
    if priority_handoff_experiment:
        why_now_parts.extend(build_priority_handoff_experiment_why_now_parts(priority_handoff_experiment))

    next_actions = list(candidate_pool_recall_dossier.get("next_actions") or [])
    next_step_default = str(candidate_pool_recall_dossier.get("recommendation") or "").strip() or "review candidate-pool recall dossier and upstream hard-filter stages"
    prioritized_handoff_next_step = None
    if dominant_stage == "candidate_pool_truncated_after_filters" and active_upstream_focus_tickers:
        prioritized_handoff_next_step = (
            f"先补 {active_upstream_focus_tickers} 的 pre-truncation 排名观测与 top300 frontier，"
            "确认它们为何通过 Layer A 过滤后仍在 candidate_pool truncation 被压掉。"
        )
        if priority_handoff_experiment:
            prioritized_handoff_next_step = "；".join(
                [
                    prioritized_handoff_next_step,
                    build_priority_handoff_experiment_next_step(priority_handoff_experiment),
                ]
            )
        next_step_default = prioritized_handoff_next_step
    elif priority_handoff_experiment:
        next_step_default = build_priority_handoff_experiment_next_step(priority_handoff_experiment)
    next_step = prioritized_handoff_next_step or next(
        (str(action).strip() for action in next_actions if str(action).strip()),
        next_step_default,
    )
    return {
        "task_id": "candidate_pool_recall_priority",
        "title": "优先修复 Layer A candidate-pool truncation 主链路" if dominant_stage == "candidate_pool_truncated_after_filters" and active_upstream_focus_tickers else f"优先修复 {dominant_stage} recall 主链路",
        "why_now": " | ".join(why_now_parts),
        "next_step": str(next_step),
        "source": "candidate_pool_recall_dossier",
    }


def build_candidate_pool_corridor_primary_shadow_task(
    control_tower_snapshot: dict[str, Any],
    *,
    normalize_primary_shadow_replay: NormalizePrimaryShadowReplay,
    collect_control_tower_ticker_set: CollectControlTowerTickerSet,
    find_candidate_pool_focus_liquidity_profile: FindCandidatePoolFocusLiquidityProfile,
    append_primary_shadow_replay_context: AppendPrimaryShadowReplayContext,
    append_truncation_context: AppendTruncationContext,
    build_corridor_primary_shadow_next_step: BuildCorridorPrimaryShadowNextStep,
) -> dict[str, Any] | None:
    shadow_status = str(control_tower_snapshot.get("candidate_pool_corridor_shadow_pack_status") or "").strip()
    shadow_summary = dict(control_tower_snapshot.get("candidate_pool_corridor_shadow_pack_summary") or {})
    primary_shadow_replay = normalize_primary_shadow_replay(shadow_summary.get("primary_shadow_replay"))
    focus_ticker = str(primary_shadow_replay.get("ticker") or "").strip()
    if shadow_status != "ready_for_primary_shadow_replay" or not focus_ticker:
        return None

    why_now_parts = [f"focus_ticker={focus_ticker}", f"shadow_status={shadow_status}"]
    active_absent_from_watchlist_tickers = collect_control_tower_ticker_set(control_tower_snapshot, "active_no_candidate_entry_absent_from_watchlist_tickers")
    active_absent_from_candidate_pool_tickers = collect_control_tower_ticker_set(control_tower_snapshot, "active_watchlist_recall_absent_from_candidate_pool_tickers")
    active_shadow_visible_focus_tickers = collect_control_tower_ticker_set(control_tower_snapshot, "active_candidate_pool_recall_shadow_visible_focus_tickers")
    if not active_shadow_visible_focus_tickers:
        active_shadow_visible_focus_tickers = collect_control_tower_ticker_set(control_tower_snapshot, "candidate_pool_recall_shadow_visible_focus_tickers")
    candidate_pool_recall_dominant_stage = str(control_tower_snapshot.get("candidate_pool_recall_dominant_stage") or "").strip()
    focus_liquidity_profile = find_candidate_pool_focus_liquidity_profile(control_tower_snapshot, focus_ticker)
    corridor_uplift_runbook_summary = dict(control_tower_snapshot.get("candidate_pool_corridor_uplift_runbook_summary") or {})
    append_primary_shadow_replay_context(why_now_parts, primary_shadow_replay)
    shadow_visible_profile = next(
        (
            dict(row)
            for row in list(
                control_tower_snapshot.get("active_candidate_pool_recall_shadow_visible_focus_profiles")
                or control_tower_snapshot.get("candidate_pool_recall_shadow_visible_focus_profiles")
                or []
            )
            if str(row.get("ticker") or "").strip() == focus_ticker
        ),
        {},
    )
    if focus_ticker in active_shadow_visible_focus_tickers:
        why_now_parts.append("earliest_breakpoint=focused_shadow_visible")
        if shadow_visible_profile.get("candidate_pool_shadow_lane"):
            why_now_parts.append(f"shadow_visible_lane={shadow_visible_profile.get('candidate_pool_shadow_lane')}")
        if shadow_visible_profile.get("candidate_pool_shadow_reason"):
            why_now_parts.append(f"shadow_visible_reason={shadow_visible_profile.get('candidate_pool_shadow_reason')}")
        if shadow_visible_profile.get("candidate_pool_shadow_rank") is not None:
            why_now_parts.append(f"shadow_visible_rank={shadow_visible_profile.get('candidate_pool_shadow_rank')}")
    elif focus_ticker in active_absent_from_candidate_pool_tickers:
        why_now_parts.append("earliest_breakpoint=absent_from_candidate_pool")
    elif focus_ticker in active_absent_from_watchlist_tickers:
        why_now_parts.append("earliest_breakpoint=absent_from_watchlist")
    append_truncation_context(
        why_now_parts,
        candidate_pool_recall_dominant_stage=candidate_pool_recall_dominant_stage,
        focus_liquidity_profile=focus_liquidity_profile,
    )
    next_step = build_corridor_primary_shadow_next_step(
        focus_ticker=focus_ticker,
        shadow_summary=shadow_summary,
        corridor_uplift_runbook_summary=corridor_uplift_runbook_summary,
        candidate_pool_recall_dominant_stage=candidate_pool_recall_dominant_stage,
        focus_liquidity_profile=focus_liquidity_profile,
        active_absent_from_candidate_pool_tickers=active_absent_from_candidate_pool_tickers,
        active_absent_from_watchlist_tickers=active_absent_from_watchlist_tickers,
        active_shadow_visible_focus_tickers=active_shadow_visible_focus_tickers,
    )

    return {
        "task_id": "candidate_pool_corridor_primary_shadow_priority",
        "title": f"优先推进 {focus_ticker} corridor primary shadow replay",
        "why_now": " | ".join(why_now_parts),
        "next_step": next_step,
        "source": "candidate_pool_corridor_shadow_replay",
    }


def build_lane_priority_task(
    latest_btst_snapshot: dict[str, Any],
    control_tower_snapshot: dict[str, Any],
    *,
    lane_id: str,
    task_id: str,
    title_template: str,
    fallback_why_now: str,
    source: str,
    extract_priority_summary: ExtractPrioritySummary,
) -> dict[str, Any] | None:
    lane_row = next((dict(row or {}) for row in list(control_tower_snapshot.get("rollout_lanes") or []) if row.get("lane_id") == lane_id), {})
    if not lane_row:
        return None

    ticker = str(lane_row.get("ticker") or "").strip()
    if not ticker:
        return None

    lane_status = str(lane_row.get("lane_status") or "").strip()
    blocker = str(lane_row.get("blocker") or "").strip()
    why_now_parts = [fallback_why_now]
    if lane_status:
        why_now_parts.append(f"lane_status={lane_status}")
    if blocker:
        why_now_parts.append(f"blocker={blocker}")

    next_step = str(lane_row.get("next_step") or "").strip()
    if lane_id == "primary_roll_forward":
        priority_summary = extract_priority_summary(latest_btst_snapshot)
        if int(priority_summary.get("primary_count") or 0) == 0:
            why_now_parts.append("evidence_only_not_current_formal_selected")
            next_step = f"{next_step}；仅作独立窗口证据补充，不把它包装成当前 formal selected 主票。" if next_step else "仅作独立窗口证据补充，不把它包装成当前 formal selected 主票。"

    return {
        "task_id": task_id,
        "title": title_template.format(ticker=ticker),
        "why_now": " | ".join(why_now_parts),
        "next_step": next_step,
        "source": source,
    }


def collect_control_tower_priority_candidates(
    latest_btst_snapshot: dict[str, Any],
    control_tower_snapshot: dict[str, Any],
    *,
    build_selected_contract_resolution_task: Callable[[dict[str, Any]], dict[str, Any] | None],
    is_low_urgency_selected_contract_resolution: Callable[[dict[str, Any]], bool],
    build_selected_contract_monitor_task: Callable[[dict[str, Any]], dict[str, Any] | None],
    build_gate_ready_priority_task: Callable[[dict[str, Any]], dict[str, Any] | None],
    build_peer_proof_priority_task: Callable[[dict[str, Any]], dict[str, Any] | None],
    build_peer_close_loop_monitor_task: Callable[[dict[str, Any]], dict[str, Any] | None],
    build_carryover_contract_task: Callable[[dict[str, Any]], dict[str, Any] | None],
    build_candidate_pool_corridor_primary_shadow_task: Callable[[dict[str, Any]], dict[str, Any] | None],
    build_recall_priority_task: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any] | None],
    build_lane_priority_task: Callable[..., dict[str, Any] | None],
) -> list[dict[str, Any] | None]:
    selected_contract_resolution_task = build_selected_contract_resolution_task(control_tower_snapshot)
    low_urgency_selected_contract_resolution = is_low_urgency_selected_contract_resolution(control_tower_snapshot)
    prioritized_tasks = [
        build_selected_contract_monitor_task(control_tower_snapshot),
        build_gate_ready_priority_task(control_tower_snapshot),
        build_peer_proof_priority_task(control_tower_snapshot),
        build_candidate_pool_corridor_primary_shadow_task(control_tower_snapshot),
        build_recall_priority_task(latest_btst_snapshot, control_tower_snapshot),
        build_peer_close_loop_monitor_task(control_tower_snapshot),
        build_carryover_contract_task(control_tower_snapshot),
    ]
    if low_urgency_selected_contract_resolution:
        prioritized_tasks.append(selected_contract_resolution_task)
    else:
        prioritized_tasks.insert(0, selected_contract_resolution_task)
    return prioritized_tasks + [
        build_lane_priority_task(
            latest_btst_snapshot,
            control_tower_snapshot,
            lane_id="primary_roll_forward",
            task_id="primary_roll_forward_priority",
            title_template="推进 {ticker} primary controlled follow-through",
            fallback_why_now="唯一 primary 主线仍需补独立窗口证据",
            source="rollout_lane_primary",
        ),
        build_lane_priority_task(
            latest_btst_snapshot,
            control_tower_snapshot,
            lane_id="single_name_shadow",
            task_id="single_name_shadow_priority",
            title_template="保持 {ticker} shadow 单票验证",
            fallback_why_now="shadow 只允许单票低污染验证，不能抢占 primary 主线",
            source="rollout_lane_shadow",
        ),
    ]


def prioritize_control_tower_next_actions(
    latest_btst_snapshot: dict[str, Any],
    control_tower_snapshot: dict[str, Any],
    *,
    collect_control_tower_priority_candidates: Callable[[dict[str, Any], dict[str, Any]], list[dict[str, Any] | None]],
    dedupe_control_tower_tasks: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    prioritized = [task for task in collect_control_tower_priority_candidates(latest_btst_snapshot, control_tower_snapshot) if task]
    merged_tasks = prioritized + list(control_tower_snapshot.get("next_actions") or [])
    return dedupe_control_tower_tasks(merged_tasks)[:3]
