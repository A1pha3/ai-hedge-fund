from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_btst_candidate_entry_rollout_governance import derive_candidate_entry_shadow_state
from scripts.btst_report_utils import load_json as _load_json, looks_like_report_dir as _looks_like_report_dir, normalize_trade_date as _normalize_trade_date, safe_load_json as _safe_load_json


REPORTS_DIR = Path("data/reports")
DEFAULT_REPORTS_ROOT = REPORTS_DIR
DEFAULT_ACTION_BOARD_PATH = REPORTS_DIR / "p3_top3_post_execution_action_board_20260401.json"
DEFAULT_ROLLOUT_GOVERNANCE_PATH = REPORTS_DIR / "p5_btst_rollout_governance_board_20260401.json"
DEFAULT_PRIMARY_WINDOW_GAP_PATH = REPORTS_DIR / "p6_primary_window_gap_001309_20260330.json"
DEFAULT_RECURRING_SHADOW_RUNBOOK_PATH = REPORTS_DIR / "p6_recurring_shadow_runbook_20260401.json"
DEFAULT_PRIMARY_WINDOW_VALIDATION_RUNBOOK_PATH = REPORTS_DIR / "p7_primary_window_validation_runbook_001309_20260330.json"
DEFAULT_STRUCTURAL_SHADOW_RUNBOOK_PATH = REPORTS_DIR / "p8_structural_shadow_runbook_300724_20260330.json"
DEFAULT_CANDIDATE_ENTRY_GOVERNANCE_PATH = REPORTS_DIR / "p9_candidate_entry_rollout_governance_20260330.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_governance_synthesis_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_governance_synthesis_latest.md"


def _find_row(rows: list[dict[str, Any]], ticker: str) -> dict[str, Any]:
    normalized_ticker = str(ticker or "").strip()
    return next((dict(row or {}) for row in rows if str((row or {}).get("ticker") or "") == normalized_ticker), {})


def _find_row_by_tier(rows: list[dict[str, Any]], governance_tier: str) -> dict[str, Any]:
    normalized_tier = str(governance_tier or "").strip()
    return next((dict(row or {}) for row in rows if str((row or {}).get("governance_tier") or "") == normalized_tier), {})


def _resolve_recurring_lane_row(rows: list[dict[str, Any]], ticker: str, governance_tier: str) -> dict[str, Any]:
    row = _find_row(rows, ticker)
    if row:
        return row
    return _find_row_by_tier(rows, governance_tier)


def _first(items: list[Any], default: Any = None) -> Any:
    return items[0] if items else default


def _collect_closed_frontiers(rollout_governance: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    frontier_constraints = [dict(row or {}) for row in list(rollout_governance.get("frontier_constraints") or [])]
    closed_frontiers = [
        row
        for row in frontier_constraints
        if "closed" in str(row.get("status") or "")
    ]
    return frontier_constraints, closed_frontiers


def _extract_latest_btst_candidate(report_dir: Path) -> dict[str, Any] | None:
    if not _looks_like_report_dir(report_dir):
        return None
    summary = _safe_load_json(report_dir / "session_summary.json")
    followup = dict(summary.get("btst_followup") or {})
    artifacts = dict(summary.get("artifacts") or {})
    if not followup and not any(
        artifacts.get(key)
        for key in (
            "btst_next_day_trade_brief_json",
            "btst_premarket_execution_card_json",
            "btst_opening_watch_card_json",
            "btst_next_day_priority_board_json",
        )
    ):
        return None

    plan_generation = dict(summary.get("plan_generation") or {})
    selection_target = str(plan_generation.get("selection_target") or summary.get("selection_target") or "")
    trade_date = _normalize_trade_date(followup.get("trade_date") or summary.get("end_date"))
    next_trade_date = _normalize_trade_date(followup.get("next_trade_date"))
    brief_json_path = followup.get("brief_json") or artifacts.get("btst_next_day_trade_brief_json")
    priority_board_json_path = followup.get("priority_board_json") or artifacts.get("btst_next_day_priority_board_json")
    selection_target_rank = 2 if selection_target == "short_trade_only" else 1

    return {
        "report_dir": report_dir.expanduser().resolve(),
        "summary": summary,
        "followup": followup,
        "artifacts": artifacts,
        "selection_target": selection_target or None,
        "trade_date": trade_date,
        "next_trade_date": next_trade_date,
        "brief_json_path": Path(brief_json_path).expanduser().resolve() if brief_json_path else None,
        "priority_board_json_path": Path(priority_board_json_path).expanduser().resolve() if priority_board_json_path else None,
        "rank": (selection_target_rank, trade_date or "", report_dir.stat().st_mtime_ns, report_dir.name),
    }


def _select_latest_btst_candidate(reports_root: str | Path) -> dict[str, Any] | None:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    candidates = [
        candidate
        for candidate in (_extract_latest_btst_candidate(path) for path in resolved_reports_root.iterdir())
        if candidate is not None
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate["rank"])


def _summarize_btst_followup_entry(bucket_name: str, entry: dict[str, Any]) -> dict[str, Any]:
    historical_prior = dict(entry.get("historical_prior") or {})
    top_reasons = [str(reason) for reason in list(entry.get("top_reasons") or []) if str(reason).strip()]
    candidate_source = str(entry.get("candidate_source") or "").strip() or None
    return {
        "ticker": str(entry.get("ticker") or "").strip(),
        "bucket": bucket_name,
        "decision": entry.get("decision"),
        "candidate_source": candidate_source,
        "score_target": entry.get("score_target"),
        "preferred_entry_mode": entry.get("preferred_entry_mode"),
        "top_reasons": top_reasons,
        "historical_bias_label": historical_prior.get("bias_label"),
        "historical_sample_count": historical_prior.get("sample_count"),
        "historical_next_close_positive_rate": historical_prior.get("next_close_positive_rate"),
        "historical_next_close_return_mean": historical_prior.get("next_close_return_mean"),
        "execution_priority": historical_prior.get("execution_priority"),
        "monitor_priority": historical_prior.get("monitor_priority"),
        "historical_execution_quality_label": historical_prior.get("execution_quality_label"),
        "historical_entry_timing_bias": historical_prior.get("entry_timing_bias"),
        "historical_execution_note": historical_prior.get("execution_note"),
    }


def _followup_bucket_rank(bucket_name: str | None) -> int:
    return {
        "selected_entries": 3,
        "near_miss_entries": 2,
        "opportunity_pool_entries": 1,
        "rejected_entries": 0,
    }.get(str(bucket_name or "").strip(), -1)


def _merge_btst_followup_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_ticker: dict[str, tuple[tuple[Any, ...], dict[str, Any]]] = {}
    for raw_entry in entries:
        entry = dict(raw_entry or {})
        ticker = str(entry.get("ticker") or "").strip()
        if not ticker:
            continue
        rank = (
            _followup_bucket_rank(entry.get("bucket")),
            float(entry.get("score_target") or -999.0),
            str(entry.get("preferred_entry_mode") or ""),
            ticker,
        )
        current = best_by_ticker.get(ticker)
        if current is None or rank > current[0]:
            best_by_ticker[ticker] = (rank, entry)

    merged_entries = [entry for _rank, entry in best_by_ticker.values()]
    merged_entries.sort(
        key=lambda entry: (
            _followup_bucket_rank(entry.get("bucket")),
            float(entry.get("score_target") or -999.0),
            str(entry.get("ticker") or ""),
        ),
        reverse=True,
    )
    return merged_entries


def _merge_btst_followup_payloads(followups: list[dict[str, Any]]) -> dict[str, Any]:
    if not followups:
        return {}
    primary_followup = dict(sorted(followups, key=lambda followup: followup.get("rank"), reverse=True)[0])
    merged_entries = _merge_btst_followup_entries(
        [dict(entry or {}) for followup in followups for entry in list(dict(followup or {}).get("entries") or [])]
    )
    if merged_entries:
        selected_count = sum(1 for entry in merged_entries if str(entry.get("bucket") or "") == "selected_entries")
        near_miss_count = sum(1 for entry in merged_entries if str(entry.get("bucket") or "") == "near_miss_entries")
        opportunity_pool_count = sum(1 for entry in merged_entries if str(entry.get("bucket") or "") == "opportunity_pool_entries")
        rejected_count = sum(1 for entry in merged_entries if str(entry.get("bucket") or "") == "rejected_entries")
    else:
        selected_count = int(primary_followup.get("selected_count") or 0)
        near_miss_count = int(primary_followup.get("near_miss_count") or 0)
        opportunity_pool_count = int(primary_followup.get("opportunity_pool_count") or 0)
        rejected_count = int(primary_followup.get("rejected_count") or 0)
    primary_followup.update(
        {
            "selected_count": selected_count,
            "near_miss_count": near_miss_count,
            "opportunity_pool_count": opportunity_pool_count,
            "rejected_count": rejected_count,
            "entries": merged_entries,
            "evidence_report_dirs": [
                str(dict(followup or {}).get("report_dir") or "").strip()
                for followup in followups
                if str(dict(followup or {}).get("report_dir") or "").strip()
            ],
        }
    )
    return primary_followup


def _build_btst_followup_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    brief = _safe_load_json(candidate.get("brief_json_path"))
    priority_board = _safe_load_json(candidate.get("priority_board_json_path"))
    summary_block = dict(brief.get("summary") or {})
    entries: list[dict[str, Any]] = []
    for bucket_name in ("selected_entries", "near_miss_entries", "opportunity_pool_entries", "rejected_entries"):
        for entry in list(brief.get(bucket_name) or []):
            entries.append(_summarize_btst_followup_entry(bucket_name, dict(entry or {})))

    return {
        "report_dir": str(candidate["report_dir"]),
        "selection_target": candidate.get("selection_target"),
        "trade_date": candidate.get("trade_date"),
        "next_trade_date": candidate.get("next_trade_date"),
        "selected_count": int(summary_block.get("short_trade_selected_count") or 0),
        "near_miss_count": int(summary_block.get("short_trade_near_miss_count") or 0),
        "blocked_count": int(summary_block.get("short_trade_blocked_count") or 0),
        "rejected_count": int(summary_block.get("short_trade_rejected_count") or 0),
        "opportunity_pool_count": int(summary_block.get("short_trade_opportunity_pool_count") or 0),
        "research_upside_radar_count": int(summary_block.get("research_upside_radar_count") or 0),
        "priority_board_headline": priority_board.get("headline"),
        "brief_recommendation": brief.get("recommendation"),
        "entries": entries,
        "rank": candidate.get("rank"),
    }


def _extract_btst_followups(
    reports_root: str | Path,
    *,
    latest_btst_report_dir: str | Path | None = None,
    evidence_btst_report_dirs: list[str | Path] | None = None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if evidence_btst_report_dirs:
        for report_dir in evidence_btst_report_dirs:
            candidate = _extract_latest_btst_candidate(Path(report_dir))
            if candidate is not None:
                candidates.append(candidate)
    elif latest_btst_report_dir:
        candidate = _extract_latest_btst_candidate(Path(latest_btst_report_dir))
        if candidate is not None:
            candidates.append(candidate)
    else:
        candidate = _select_latest_btst_candidate(reports_root)
        if candidate is not None:
            candidates.append(candidate)

    sorted_candidates = sorted(candidates, key=lambda candidate: candidate["rank"], reverse=True)
    grouped_by_trade_date: dict[str, list[dict[str, Any]]] = {}
    for candidate in sorted_candidates:
        payload = _build_btst_followup_payload(candidate)
        group_key = str(payload.get("trade_date") or payload.get("report_dir") or "").strip()
        grouped_by_trade_date.setdefault(group_key, []).append(payload)
    merged_followups = [_merge_btst_followup_payloads(grouped_by_trade_date[key]) for key in grouped_by_trade_date]
    return sorted(merged_followups, key=lambda followup: followup.get("rank"), reverse=True)


def _extract_latest_btst_followup(
    reports_root: str | Path,
    latest_btst_report_dir: str | Path | None = None,
    *,
    evidence_btst_report_dirs: list[str | Path] | None = None,
) -> dict[str, Any]:
    followups = _extract_btst_followups(
        reports_root,
        latest_btst_report_dir=latest_btst_report_dir,
        evidence_btst_report_dirs=evidence_btst_report_dirs,
    )
    if not followups:
        return {}
    return dict(followups[0])


def _derive_execution_surface_constraints(btst_followups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    constraints: list[dict[str, Any]] = []
    for followup in btst_followups:
        entries = [dict(entry or {}) for entry in list(followup.get("entries") or [])]
        if not entries:
            continue

        post_gate_continuation_entries = [
            entry
            for entry in entries
            if entry.get("candidate_source") == "post_gate_liquidity_competition_shadow"
            and entry.get("bucket") in {"selected_entries", "near_miss_entries"}
        ]
        if post_gate_continuation_entries:
            continuation_focus_tickers = [entry.get("ticker") for entry in post_gate_continuation_entries if entry.get("ticker")]
            has_selected_post_gate = any(str(entry.get("bucket") or "") == "selected_entries" for entry in post_gate_continuation_entries)
            constraints.append(
                {
                    "constraint_id": "post_gate_shadow_observation_only",
                    "report_dir": followup.get("report_dir"),
                    "trade_date": followup.get("trade_date"),
                    "lane_id": "post_gate_liquidity_competition_shadow",
                    "status": "continuation_only_confirm_then_review",
                    "blocker": "no_selected_persistence_or_independent_edge",
                    "focus_tickers": continuation_focus_tickers,
                    "evidence": {
                        "selected_count": followup.get("selected_count"),
                        "near_miss_count": followup.get("near_miss_count"),
                        "opportunity_pool_count": followup.get("opportunity_pool_count"),
                        "entries": post_gate_continuation_entries,
                    },
                    "recommendation": (
                        "Keep post-gate shadow names in continuation review until a selected row persists across independent windows."
                        if has_selected_post_gate
                        else "Keep post-gate shadow names in observation / continuation review until a selected row persists across independent windows."
                    ),
                }
            )

        upstream_intraday_only_selected = [
            entry
            for entry in entries
            if entry.get("candidate_source") == "upstream_liquidity_corridor_shadow"
            and entry.get("bucket") == "selected_entries"
            and entry.get("historical_execution_quality_label") in {"intraday_only", "gap_chase_risk"}
        ]
        if upstream_intraday_only_selected:
            focus_tickers = [entry.get("ticker") for entry in upstream_intraday_only_selected if entry.get("ticker")]
            constraints.append(
                {
                    "constraint_id": "upstream_shadow_selected_intraday_bias",
                    "report_dir": followup.get("report_dir"),
                    "trade_date": followup.get("trade_date"),
                    "lane_id": "upstream_liquidity_corridor_shadow",
                    "status": "continuation_confirm_only_intraday_bias",
                    "blocker": "weak_overnight_follow_through_after_shadow_recall",
                    "focus_tickers": focus_tickers,
                    "evidence": {
                        "selected_count": len(upstream_intraday_only_selected),
                        "entries": upstream_intraday_only_selected,
                    },
                    "recommendation": (
                        "Keep upstream shadow selected names in confirmation-only execution when historical follow-through is intraday-only; "
                        "do not treat them as standard overnight BTST holds without fresh same-day strength."
                    ),
                }
            )

        shadow_profitability_cliff = [
            entry
            for entry in entries
            if entry.get("candidate_source") in {"post_gate_liquidity_competition_shadow", "upstream_liquidity_corridor_shadow"}
            and entry.get("bucket") in {"opportunity_pool_entries", "rejected_entries"}
            and "profitability_hard_cliff" in list(entry.get("top_reasons") or [])
        ]
        if shadow_profitability_cliff:
            constraints.append(
                {
                    "constraint_id": "shadow_profitability_cliff_execution_block",
                    "report_dir": followup.get("report_dir"),
                    "trade_date": followup.get("trade_date"),
                    "lane_id": "shadow_recall_surface",
                    "status": "shadow_recall_not_execution_ready",
                    "blocker": "profitability_hard_cliff_and_score_gap",
                    "focus_tickers": [entry.get("ticker") for entry in shadow_profitability_cliff if entry.get("ticker")],
                    "evidence": {
                        "rejected_count": followup.get("rejected_count"),
                        "opportunity_pool_count": followup.get("opportunity_pool_count"),
                        "entries": shadow_profitability_cliff,
                    },
                    "recommendation": "Do not promote shadow recall names with profitability hard-cliff evidence into execution lanes; keep them in replay-input / shadow-governance diagnostics.",
                }
            )

    return constraints


def _build_lane_matrix(
    *,
    action_board: dict[str, Any],
    rollout_governance: dict[str, Any],
    primary_window_gap: dict[str, Any],
    recurring_shadow_runbook: dict[str, Any],
    primary_window_validation_runbook: dict[str, Any],
    structural_shadow_runbook: dict[str, Any],
    candidate_entry_governance: dict[str, Any],
) -> list[dict[str, Any]]:
    governance_rows = [dict(row or {}) for row in list(rollout_governance.get("governance_rows") or [])]
    board_rows = [dict(row or {}) for row in list(action_board.get("board_rows") or [])]
    primary_governance = _find_row(governance_rows, "001309")
    shadow_governance = _find_row(governance_rows, "300383")
    structural_governance = _find_row(governance_rows, "300724")
    primary_board = _find_row(board_rows, "001309")
    shadow_board = _find_row(board_rows, "300383")
    structural_board = _find_row(board_rows, "300724")
    recurring_close = dict(recurring_shadow_runbook.get("close_candidate") or {})
    recurring_intraday = dict(recurring_shadow_runbook.get("intraday_control") or {})
    recurring_close_ticker = str(recurring_close.get("ticker") or "300113")
    recurring_intraday_ticker = str(recurring_intraday.get("ticker") or "600821")
    recurring_close_governance = _resolve_recurring_lane_row(governance_rows, recurring_close_ticker, "recurring_shadow_close_candidate")
    recurring_intraday_governance = _resolve_recurring_lane_row(governance_rows, recurring_intraday_ticker, "recurring_intraday_control")
    candidate_entry_window_scan = dict(candidate_entry_governance.get("window_scan_summary") or {})
    candidate_entry_shadow_state = derive_candidate_entry_shadow_state(
        rollout_readiness=str(candidate_entry_window_scan.get("rollout_readiness") or candidate_entry_governance.get("lane_status") or "unknown"),
        preserve_misfire_report_count=int(candidate_entry_window_scan.get("preserve_misfire_report_count") or 0),
        distinct_window_count_with_filtered_entries=int(candidate_entry_window_scan.get("distinct_window_count_with_filtered_entries") or 0),
        target_window_count=int(candidate_entry_governance.get("target_window_count") or 2),
    )

    return [
        {
            "lane_id": "primary_roll_forward",
            "ticker": "001309",
            "governance_tier": primary_governance.get("governance_tier") or "primary_roll_forward_only",
            "lane_status": primary_governance.get("status") or primary_window_validation_runbook.get("validation_verdict"),
            "action_tier": primary_board.get("action_tier") or "primary_promote",
            "blocker": primary_governance.get("blocker") or "cross_window_stability_missing",
            "missing_window_count": primary_window_gap.get("missing_window_count"),
            "validation_verdict": primary_window_validation_runbook.get("validation_verdict"),
            "next_step": primary_governance.get("next_step") or _first(list(primary_window_validation_runbook.get("rerun_commands") or []), ""),
        },
        {
            "lane_id": "single_name_shadow",
            "ticker": "300383",
            "governance_tier": shadow_governance.get("governance_tier") or "single_name_shadow_only",
            "lane_status": shadow_governance.get("status"),
            "action_tier": shadow_board.get("action_tier") or "shadow_entry",
            "blocker": shadow_governance.get("blocker") or "same_rule_shadow_expansion_not_ready",
            "next_step": shadow_governance.get("next_step") or shadow_board.get("next_step"),
            "validation_verdict": shadow_governance.get("status"),
        },
        {
            "lane_id": "recurring_shadow_close_candidate",
            "ticker": recurring_close_ticker,
            "governance_tier": recurring_close_governance.get("governance_tier") or "recurring_shadow_close_candidate",
            "lane_status": recurring_close_governance.get("status") or recurring_close.get("lane_status"),
            "action_tier": "recurring_shadow_validation",
            "blocker": recurring_close_governance.get("blocker") or "cross_window_stability_missing",
            "missing_window_count": recurring_close.get("missing_window_count"),
            "validation_verdict": recurring_close.get("validation_verdict") or recurring_shadow_runbook.get("global_validation_verdict"),
            "next_step": recurring_close_governance.get("next_step") or recurring_close.get("next_step"),
        },
        {
            "lane_id": "recurring_intraday_control",
            "ticker": recurring_intraday_ticker,
            "governance_tier": recurring_intraday_governance.get("governance_tier") or "recurring_intraday_control",
            "lane_status": recurring_intraday_governance.get("status") or recurring_intraday.get("lane_status"),
            "action_tier": "intraday_control_only",
            "blocker": recurring_intraday_governance.get("blocker") or "cross_window_stability_missing",
            "missing_window_count": recurring_intraday.get("missing_window_count"),
            "validation_verdict": recurring_intraday.get("validation_verdict") or recurring_shadow_runbook.get("global_validation_verdict"),
            "next_step": recurring_intraday_governance.get("next_step") or recurring_intraday.get("next_step"),
        },
        {
            "lane_id": "structural_shadow_hold",
            "ticker": "300724",
            "governance_tier": structural_governance.get("governance_tier") or "structural_shadow_hold_only",
            "lane_status": structural_governance.get("status") or structural_shadow_runbook.get("lane_status"),
            "action_tier": structural_board.get("action_tier") or "structural_shadow_hold",
            "blocker": structural_governance.get("blocker") or "post_release_quality_negative",
            "validation_verdict": structural_shadow_runbook.get("freeze_verdict"),
            "next_step": structural_governance.get("next_step") or structural_shadow_runbook.get("next_step"),
        },
        {
            "lane_id": "candidate_entry_shadow",
            "ticker": str(candidate_entry_governance.get("candidate_entry_rule") or "candidate_entry_rule"),
            "governance_tier": "candidate_entry_shadow_only",
            "lane_status": candidate_entry_governance.get("lane_status") or candidate_entry_shadow_state.get("lane_status"),
            "action_tier": "shadow_only",
            "blocker": candidate_entry_governance.get("default_upgrade_status") or candidate_entry_shadow_state.get("default_upgrade_status"),
            "validation_verdict": candidate_entry_window_scan.get("rollout_readiness"),
            "missing_window_count": candidate_entry_governance.get("missing_window_count") if candidate_entry_governance.get("missing_window_count") is not None else candidate_entry_shadow_state.get("missing_window_count"),
            "target_window_count": candidate_entry_governance.get("target_window_count") if candidate_entry_governance.get("target_window_count") is not None else candidate_entry_shadow_state.get("target_window_count"),
            "upgrade_gap": candidate_entry_governance.get("upgrade_gap") or candidate_entry_shadow_state.get("upgrade_gap"),
            "window_report_count": candidate_entry_window_scan.get("report_count"),
            "filtered_report_count": candidate_entry_window_scan.get("filtered_report_count"),
            "focus_hit_report_count": candidate_entry_window_scan.get("focus_hit_report_count"),
            "preserve_misfire_report_count": candidate_entry_window_scan.get("preserve_misfire_report_count"),
            "distinct_window_count_with_filtered_entries": candidate_entry_window_scan.get("distinct_window_count_with_filtered_entries"),
            "recommended_structural_variant": candidate_entry_governance.get("recommended_structural_variant"),
            "next_step": _first(list(candidate_entry_governance.get("next_actions") or []), ""),
        },
    ]


def _build_next_actions(
    *,
    action_board: dict[str, Any],
    rollout_governance: dict[str, Any],
    candidate_entry_governance: dict[str, Any],
    primary_window_validation_runbook: dict[str, Any],
) -> list[dict[str, Any]]:
    raw_tasks: list[dict[str, Any]] = []

    for task in list(action_board.get("next_3_tasks") or []):
        raw_tasks.append(
            {
                "task_id": task.get("task_id") or "action_board_task",
                "title": task.get("title") or task.get("task_id") or "action_board_task",
                "why_now": task.get("why_now") or "来自 p3 动作板。",
                "next_step": task.get("next_step") or task.get("cli_preview") or "",
                "source": "p3_action_board",
            }
        )

    for task in list(rollout_governance.get("next_3_tasks") or []):
        raw_tasks.append(
            {
                "task_id": task.get("task_id") or "rollout_task",
                "title": task.get("title") or task.get("task_id") or "rollout_task",
                "why_now": task.get("why_now") or "来自 p5 rollout governance。",
                "next_step": task.get("next_step") or "",
                "source": "p5_rollout_governance",
            }
        )

    for index, action in enumerate(list(candidate_entry_governance.get("next_actions") or []), start=1):
        raw_tasks.append(
            {
                "task_id": f"candidate_entry_shadow_followup_{index}",
                "title": f"candidate-entry 旁路跟进 {index}",
                "why_now": "来自 p9 candidate-entry shadow-only 治理。",
                "next_step": str(action),
                "source": "p9_candidate_entry_governance",
            }
        )

    for index, command in enumerate(list(primary_window_validation_runbook.get("rerun_commands") or [])[:2], start=1):
        raw_tasks.append(
            {
                "task_id": f"primary_window_rerun_{index}",
                "title": f"001309 窗口补证复跑命令 {index}",
                "why_now": "primary lane 仍缺新增独立窗口。",
                "next_step": str(command),
                "source": "p7_primary_window_validation_runbook",
            }
        )

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for task in raw_tasks:
        dedupe_key = (str(task.get("title") or ""), str(task.get("next_step") or ""))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped.append(task)
    return deduped[:6]


def analyze_btst_governance_synthesis(
    reports_root: str | Path,
    *,
    action_board_path: str | Path,
    rollout_governance_path: str | Path,
    primary_window_gap_path: str | Path,
    recurring_shadow_runbook_path: str | Path,
    primary_window_validation_runbook_path: str | Path,
    structural_shadow_runbook_path: str | Path,
    candidate_entry_governance_path: str | Path,
    latest_btst_report_dir: str | Path | None = None,
    evidence_btst_report_dirs: list[str | Path] | None = None,
) -> dict[str, Any]:
    action_board = _load_json(action_board_path)
    rollout_governance = _load_json(rollout_governance_path)
    primary_window_gap = _load_json(primary_window_gap_path)
    recurring_shadow_runbook = _load_json(recurring_shadow_runbook_path)
    primary_window_validation_runbook = _load_json(primary_window_validation_runbook_path)
    structural_shadow_runbook = _load_json(structural_shadow_runbook_path)
    candidate_entry_governance = _load_json(candidate_entry_governance_path)
    btst_followups = _extract_btst_followups(
        reports_root,
        latest_btst_report_dir=latest_btst_report_dir,
        evidence_btst_report_dirs=evidence_btst_report_dirs,
    )
    latest_btst_followup = dict(btst_followups[0]) if btst_followups else {}
    execution_surface_constraints = _derive_execution_surface_constraints(btst_followups)
    frontier_constraints, closed_frontiers = _collect_closed_frontiers(rollout_governance)

    lane_matrix = _build_lane_matrix(
        action_board=action_board,
        rollout_governance=rollout_governance,
        primary_window_gap=primary_window_gap,
        recurring_shadow_runbook=recurring_shadow_runbook,
        primary_window_validation_runbook=primary_window_validation_runbook,
        structural_shadow_runbook=structural_shadow_runbook,
        candidate_entry_governance=candidate_entry_governance,
    )
    next_actions = _build_next_actions(
        action_board=action_board,
        rollout_governance=rollout_governance,
        candidate_entry_governance=candidate_entry_governance,
        primary_window_validation_runbook=primary_window_validation_runbook,
    )

    lane_status_counts: dict[str, int] = {}
    for row in lane_matrix:
        status = str(row.get("lane_status") or "unknown")
        lane_status_counts[status] = lane_status_counts.get(status, 0) + 1

    waiting_lane_count = sum(
        1
        for row in lane_matrix
        if any(token in str(row.get("lane_status") or "") for token in ("await", "missing", "shadow_only", "hold"))
    )
    ready_lane_count = sum(
        1
        for row in lane_matrix
        if str(row.get("lane_status") or "")
        in {"primary_controlled_follow_through", "ready_for_shadow_validation", "shadow_rollout_review_ready"}
    )

    recommendation_parts = [
        str(rollout_governance.get("recommendation") or "").strip(),
        str(candidate_entry_governance.get("recommendation") or "").strip(),
    ]
    if latest_btst_followup:
        if int(latest_btst_followup.get("selected_count") or 0) <= 0:
            recommendation_parts.append(
                f"最新 BTST followup 仍没有 selected，当前应继续把 {latest_btst_followup.get('near_miss_count') or 0} 只 near-miss 和 {latest_btst_followup.get('opportunity_pool_count') or 0} 只 opportunity_pool 当成观察层。"
            )
        if latest_btst_followup.get("priority_board_headline"):
            recommendation_parts.append(str(latest_btst_followup.get("priority_board_headline")))
    if execution_surface_constraints:
        recommendation_parts.extend(
            str(row.get("recommendation") or "").strip()
            for row in execution_surface_constraints
            if str(row.get("recommendation") or "").strip()
        )

    return {
        "generated_on": action_board.get("generated_on") or rollout_governance.get("generated_on"),
        "reports_root": str(Path(reports_root).expanduser().resolve()),
        "latest_btst_followup": latest_btst_followup,
        "evidence_btst_followups": btst_followups,
        "execution_surface_constraints": execution_surface_constraints,
        "lane_status_counts": lane_status_counts,
        "ready_lane_count": ready_lane_count,
        "waiting_lane_count": waiting_lane_count,
        "lane_matrix": lane_matrix,
        "next_actions": next_actions,
        "frontier_constraints": frontier_constraints,
        "closed_frontiers": closed_frontiers,
        "recommendation": " ".join(part for part in recommendation_parts if part),
        "source_reports": {
            "action_board": str(Path(action_board_path).expanduser().resolve()),
            "rollout_governance": str(Path(rollout_governance_path).expanduser().resolve()),
            "primary_window_gap": str(Path(primary_window_gap_path).expanduser().resolve()),
            "recurring_shadow_runbook": str(Path(recurring_shadow_runbook_path).expanduser().resolve()),
            "primary_window_validation_runbook": str(Path(primary_window_validation_runbook_path).expanduser().resolve()),
            "structural_shadow_runbook": str(Path(structural_shadow_runbook_path).expanduser().resolve()),
            "candidate_entry_governance": str(Path(candidate_entry_governance_path).expanduser().resolve()),
        },
    }


def render_btst_governance_synthesis_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Governance Synthesis")
    lines.append("")
    _append_governance_synthesis_overview_markdown(lines, analysis)
    _append_governance_synthesis_latest_followup_markdown(lines, analysis)
    _append_governance_synthesis_constraints_markdown(lines, analysis)
    _append_governance_synthesis_lane_matrix_markdown(lines, analysis)
    _append_governance_synthesis_closed_frontiers_markdown(lines, analysis)
    _append_governance_synthesis_next_actions_markdown(lines, analysis)
    return "\n".join(lines) + "\n"


def _append_governance_synthesis_overview_markdown(lines: list[str], analysis: dict[str, Any]) -> None:
    lines.append("## Overview")
    lines.append(f"- recommendation: {analysis.get('recommendation')}")
    lines.append(f"- ready_lane_count: {analysis.get('ready_lane_count')}")
    lines.append(f"- waiting_lane_count: {analysis.get('waiting_lane_count')}")
    lines.append(f"- lane_status_counts: {analysis.get('lane_status_counts')}")
    lines.append("")


def _append_governance_synthesis_latest_followup_markdown(lines: list[str], analysis: dict[str, Any]) -> None:
    latest_followup = dict(analysis.get("latest_btst_followup") or {})
    lines.append("## Latest BTST Followup")
    if not latest_followup:
        lines.append("- none")
    else:
        for key in (
            "report_dir",
            "selection_target",
            "trade_date",
            "next_trade_date",
            "selected_count",
            "near_miss_count",
            "blocked_count",
            "rejected_count",
            "opportunity_pool_count",
            "research_upside_radar_count",
            "priority_board_headline",
            "brief_recommendation",
        ):
            lines.append(f"- {key}: {latest_followup.get(key)}")
    evidence_followups = list(analysis.get("evidence_btst_followups") or [])
    if len(evidence_followups) > 1:
        lines.append(f"- evidence_followup_count: {len(evidence_followups)}")
    lines.append("")


def _append_governance_synthesis_constraints_markdown(lines: list[str], analysis: dict[str, Any]) -> None:
    lines.append("## Execution Surface Constraints")
    execution_surface_constraints = list(analysis.get("execution_surface_constraints") or [])
    if not execution_surface_constraints:
        lines.append("- none")
    else:
        for row in execution_surface_constraints:
            lines.append(
                f"- constraint_id={row.get('constraint_id')} lane_id={row.get('lane_id')} status={row.get('status')} blocker={row.get('blocker')}"
            )
            lines.append(f"  trade_date: {row.get('trade_date')}")
            lines.append(f"  focus_tickers: {row.get('focus_tickers')}")
            lines.append(f"  recommendation: {row.get('recommendation')}")
    lines.append("")


def _append_governance_synthesis_lane_matrix_markdown(lines: list[str], analysis: dict[str, Any]) -> None:
    lines.append("## Lane Matrix")
    for row in list(analysis.get("lane_matrix") or []):
        lines.append(
            f"- lane_id={row.get('lane_id')} ticker={row.get('ticker')} governance_tier={row.get('governance_tier')} lane_status={row.get('lane_status')} blocker={row.get('blocker')}"
        )
        _append_governance_synthesis_lane_detail(lines, row, "action_tier")
        _append_governance_synthesis_lane_detail(lines, row, "validation_verdict")
        for key in (
            "missing_window_count",
            "target_window_count",
            "distinct_window_count_with_filtered_entries",
            "preserve_misfire_report_count",
            "filtered_report_count",
            "focus_hit_report_count",
        ):
            if row.get(key) is not None:
                _append_governance_synthesis_lane_detail(lines, row, key)
        for key in ("upgrade_gap", "recommended_structural_variant", "next_step"):
            if row.get(key):
                _append_governance_synthesis_lane_detail(lines, row, key)
    lines.append("")


def _append_governance_synthesis_lane_detail(lines: list[str], row: dict[str, Any], key: str) -> None:
    lines.append(f"  {key}: {row.get(key)}")


def _append_governance_synthesis_closed_frontiers_markdown(lines: list[str], analysis: dict[str, Any]) -> None:
    lines.append("## Closed Frontiers")
    closed_frontiers = list(analysis.get("closed_frontiers") or [])
    if not closed_frontiers:
        lines.append("- none")
    else:
        for row in closed_frontiers:
            lines.append(
                f"- frontier_id={row.get('frontier_id')} status={row.get('status')} passing_variant_count={row.get('passing_variant_count')} headline={row.get('headline')}"
            )
            lines.append(f"  best_variant: {row.get('best_variant_name')}")
            lines.append(f"  released_tickers: {row.get('best_variant_released_tickers')}")
            lines.append(f"  focus_released_tickers: {row.get('best_variant_focus_released_tickers')}")
    lines.append("")


def _append_governance_synthesis_next_actions_markdown(lines: list[str], analysis: dict[str, Any]) -> None:
    lines.append("## Next Actions")
    for task in list(analysis.get("next_actions") or []):
        lines.append(f"- {task.get('task_id')}: {task.get('title')}")
        lines.append(f"  why_now: {task.get('why_now')}")
        lines.append(f"  next_step: {task.get('next_step')}")
        lines.append(f"  source: {task.get('source')}")
    lines.append("")



def main() -> None:
    parser = argparse.ArgumentParser(description="Synthesize the current BTST governance state and the latest BTST followup into a single control-tower artifact.")
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--action-board", default=str(DEFAULT_ACTION_BOARD_PATH))
    parser.add_argument("--rollout-governance", default=str(DEFAULT_ROLLOUT_GOVERNANCE_PATH))
    parser.add_argument("--primary-window-gap", default=str(DEFAULT_PRIMARY_WINDOW_GAP_PATH))
    parser.add_argument("--recurring-shadow-runbook", default=str(DEFAULT_RECURRING_SHADOW_RUNBOOK_PATH))
    parser.add_argument("--primary-window-validation-runbook", default=str(DEFAULT_PRIMARY_WINDOW_VALIDATION_RUNBOOK_PATH))
    parser.add_argument("--structural-shadow-runbook", default=str(DEFAULT_STRUCTURAL_SHADOW_RUNBOOK_PATH))
    parser.add_argument("--candidate-entry-governance", default=str(DEFAULT_CANDIDATE_ENTRY_GOVERNANCE_PATH))
    parser.add_argument("--latest-btst-report-dir", default="")
    parser.add_argument("--evidence-btst-report-dirs", default="")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    evidence_btst_report_dirs = [
        item.strip()
        for item in str(args.evidence_btst_report_dirs or "").split(",")
        if item.strip()
    ]
    analysis = analyze_btst_governance_synthesis(
        args.reports_root,
        action_board_path=args.action_board,
        rollout_governance_path=args.rollout_governance,
        primary_window_gap_path=args.primary_window_gap,
        recurring_shadow_runbook_path=args.recurring_shadow_runbook,
        primary_window_validation_runbook_path=args.primary_window_validation_runbook,
        structural_shadow_runbook_path=args.structural_shadow_runbook,
        candidate_entry_governance_path=args.candidate_entry_governance,
        latest_btst_report_dir=args.latest_btst_report_dir or None,
        evidence_btst_report_dirs=evidence_btst_report_dirs or None,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_governance_synthesis_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
