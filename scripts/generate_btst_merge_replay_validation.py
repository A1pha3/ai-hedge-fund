from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.replay_selection_target_calibration import (
    analyze_selection_target_replay_inputs,
    analyze_selection_target_replay_sources,
    load_selection_target_replay_sources,
)
from src.execution.merge_approved_breakout_uplift import (
    apply_merge_approved_breakout_uplift_to_signal_map,
    apply_merge_approved_layer_c_alignment_uplift,
    apply_merge_approved_sector_resonance_uplift,
)

REPORTS_ROOT = Path("data/reports")
MERGE_REASON_CODE = "merge_approved_continuation"
MERGE_REASON_SOURCE = "layer_c_watchlist_merge_approved"
TARGET_PREMIUM_FEASIBLE_MAX = 0.03
MODERATE_EXECUTION_UPLIFT_MAX = 0.08


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _decision_rank(decision: str | None) -> int:
    order = {"none": 0, "blocked": 1, "rejected": 2, "near_miss": 3, "selected": 4}
    return order.get(str(decision or "none"), 0)


def _format_float(value: Any) -> float | None:
    if value is None:
        return None
    return round(float(value), 4)


def _append_reason_code(entry: dict[str, Any], reason_code: str) -> dict[str, Any]:
    normalized = dict(entry or {})
    reason_codes = [str(value) for value in list(normalized.get("candidate_reason_codes", normalized.get("reasons", [])) or []) if str(value or "").strip()]
    if reason_code not in reason_codes:
        reason_codes.append(reason_code)
    normalized["candidate_reason_codes"] = reason_codes
    normalized.setdefault("candidate_source", str(normalized.get("source") or MERGE_REASON_SOURCE))
    return normalized


def _rank_signal_headroom(metrics_payload: dict[str, Any]) -> list[dict[str, Any]]:
    metric_names = (
        "breakout_freshness",
        "trend_acceleration",
        "volume_expansion_quality",
        "close_strength",
        "sector_resonance",
        "catalyst_freshness",
        "layer_c_alignment",
    )
    weights = {
        str(name): float(value)
        for name, value in dict(metrics_payload.get("positive_score_weights") or {}).items()
        if str(name or "").strip()
    }
    ranked_rows: list[dict[str, Any]] = []
    for metric_name in metric_names:
        if metric_name not in metrics_payload:
            continue
        metric_value = max(0.0, min(1.0, float(metrics_payload.get(metric_name) or 0.0)))
        metric_weight = max(0.0, float(weights.get(metric_name, 0.0) or 0.0))
        contribution = round(metric_weight * metric_value, 4)
        headroom = round(metric_weight * max(0.0, 1.0 - metric_value), 4)
        ranked_rows.append(
            {
                "metric": metric_name,
                "value": round(metric_value, 4),
                "weight": round(metric_weight, 4),
                "contribution": contribution,
                "headroom": headroom,
            }
        )
    return sorted(ranked_rows, key=lambda row: (row["headroom"], row["weight"], -row["value"]), reverse=True)


def _required_score_uplift(gap: float | None, decision: str) -> float:
    if gap is None or _decision_rank(decision) >= _decision_rank("selected"):
        return 0.0
    return round(max(0.0, float(gap)), 4)


def _classify_remaining_leverage(*, merge_decision: str, required_to_selected: float, required_to_near_miss: float) -> tuple[str, str]:
    if merge_decision == "selected":
        return "already_selected", "none"
    if merge_decision == "near_miss":
        if required_to_selected <= TARGET_PREMIUM_FEASIBLE_MAX:
            return "target_premium_feasible", "target"
        if required_to_selected <= MODERATE_EXECUTION_UPLIFT_MAX:
            return "moderate_execution_uplift_required", "execution"
        return "strong_execution_signal_uplift_required", "execution_signal"
    if merge_decision == "rejected":
        if required_to_near_miss <= TARGET_PREMIUM_FEASIBLE_MAX:
            return "near_miss_threshold_tuning_feasible", "target"
        if required_to_near_miss <= MODERATE_EXECUTION_UPLIFT_MAX:
            return "execution_watchlist_uplift_required", "execution"
        return "strong_upstream_signal_uplift_required", "upstream_signal"
    return "insufficient_focus_signal", "research"


def _inject_merge_approved_context(payload: dict[str, Any], focus_ticker: str) -> dict[str, Any]:
    mutated = copy.deepcopy(dict(payload or {}))
    for key in ("watchlist", "rejected_entries", "supplemental_short_trade_entries", "upstream_shadow_observation_entries"):
        updated_entries: list[dict[str, Any]] = []
        for raw_entry in list(mutated.get(key) or []):
            entry = dict(raw_entry or {})
            if str(entry.get("ticker") or "").strip() == focus_ticker:
                entry = _append_reason_code(entry, MERGE_REASON_CODE)
                updated_signals, breakout_uplift = apply_merge_approved_breakout_uplift_to_signal_map(
                    entry.get("strategy_signals"),
                    score_b=float(entry.get("score_b", 0.0) or 0.0),
                )
                entry["strategy_signals"] = {name: signal.model_dump(mode="json") for name, signal in updated_signals.items()}
                entry["merge_approved_breakout_signal_uplift"] = breakout_uplift
                entry, alignment_uplift = apply_merge_approved_layer_c_alignment_uplift(
                    entry,
                    breakout_diagnostics=breakout_uplift,
                )
                entry["merge_approved_layer_c_alignment_uplift"] = alignment_uplift
                entry, sector_uplift = apply_merge_approved_sector_resonance_uplift(
                    entry,
                    alignment_diagnostics=alignment_uplift,
                )
                entry["merge_approved_sector_resonance_uplift"] = sector_uplift
            updated_entries.append(entry)
        if updated_entries:
            mutated[key] = updated_entries
    return mutated


def _resolve_report_dir_candidate(reports_root: Path, value: Any) -> str:
    raw_value = str(value or "").strip()
    if not raw_value:
        return ""
    raw_path = Path(raw_value).expanduser()
    if raw_path.is_absolute():
        return str(raw_path)
    return str((reports_root / raw_path).resolve())


def _discover_report_dirs_from_dossier(reports_root: Path, dossier: dict[str, Any]) -> list[str]:
    report_dirs: list[str] = []
    for key in ("report_dir", "latest_followup_report_dir", "latest_report_dir"):
        resolved = _resolve_report_dir_candidate(reports_root, dossier.get(key))
        if resolved:
            report_dirs.append(resolved)
    for collection_key in ("recent_window_summaries", "per_window_summaries"):
        for row in list(dossier.get(collection_key) or []):
            normalized_row = dict(row or {})
            report_dir = _resolve_report_dir_candidate(reports_root, normalized_row.get("report_dir"))
            if report_dir:
                report_dirs.append(report_dir)
                continue
            report_label_dir = _resolve_report_dir_candidate(reports_root, normalized_row.get("report_label"))
            if report_label_dir:
                report_dirs.append(report_label_dir)
    return sorted(dict.fromkeys(report_dirs))


def _resolve_focus_tickers(reports_root: Path, explicit_tickers: list[str] | None, candidate_limit: int) -> list[str]:
    if explicit_tickers:
        return [ticker for ticker in explicit_tickers if str(ticker or "").strip()]

    resolved: list[str] = []
    default_merge_review_path = reports_root / "btst_default_merge_review_latest.json"
    if default_merge_review_path.exists():
        default_merge_review = _load_json(default_merge_review_path)
        focus_ticker = str(default_merge_review.get("focus_ticker") or "").strip()
        if focus_ticker:
            resolved.append(focus_ticker)

    ranking_path = reports_root / "btst_continuation_merge_candidate_ranking_latest.json"
    if ranking_path.exists():
        ranking = _load_json(ranking_path)
        for row in list(ranking.get("ranked_candidates") or []):
            ticker = str(dict(row or {}).get("ticker") or "").strip()
            if ticker and ticker not in resolved:
                resolved.append(ticker)
            if len(resolved) >= max(1, candidate_limit):
                break
    return resolved[: max(1, candidate_limit)]


def _summarize_focus_row(
    *,
    focus_ticker: str,
    report_dir: str,
    trade_date: str,
    baseline_diag: dict[str, Any] | None,
    merge_diag: dict[str, Any] | None,
) -> dict[str, Any]:
    baseline_decision = str((baseline_diag or {}).get("replayed_decision") or "not_present")
    merge_decision = str((merge_diag or {}).get("replayed_decision") or "not_present")
    decision_delta = _decision_rank(merge_decision) - _decision_rank(baseline_decision)
    classification = "unchanged"
    if decision_delta > 0 and merge_decision == "selected":
        classification = "promoted_to_selected"
    elif decision_delta > 0 and merge_decision == "near_miss":
        classification = "promoted_to_near_miss"
    elif decision_delta > 0:
        classification = "decision_improved"
    elif decision_delta < 0:
        classification = "decision_deteriorated"
    elif _format_float((merge_diag or {}).get("replayed_score_target")) != _format_float((baseline_diag or {}).get("replayed_score_target")):
        classification = "score_shift_only"

    merge_relief = dict(dict((merge_diag or {}).get("replayed_metrics_payload") or {}).get("merge_approved_continuation_relief") or {})
    merge_metrics_payload = dict((merge_diag or {}).get("replayed_metrics_payload") or {})
    breakout_signal_uplift = dict((merge_diag or {}).get("merge_approved_breakout_signal_uplift") or {})
    layer_c_alignment_uplift = dict((merge_diag or {}).get("merge_approved_layer_c_alignment_uplift") or {})
    sector_resonance_uplift = dict((merge_diag or {}).get("merge_approved_sector_resonance_uplift") or {})
    prepared_breakout_penalty_relief = dict(merge_metrics_payload.get("prepared_breakout_penalty_relief") or {})
    prepared_breakout_catalyst_relief = dict(merge_metrics_payload.get("prepared_breakout_catalyst_relief") or {})
    prepared_breakout_volume_relief = dict(merge_metrics_payload.get("prepared_breakout_volume_relief") or {})
    prepared_breakout_continuation_relief = dict(merge_metrics_payload.get("prepared_breakout_continuation_relief") or {})
    prepared_breakout_selected_catalyst_relief = dict(merge_metrics_payload.get("prepared_breakout_selected_catalyst_relief") or {})
    baseline_score = (baseline_diag or {}).get("replayed_score_target")
    merge_score = (merge_diag or {}).get("replayed_score_target")
    score_delta = None if baseline_score is None or merge_score is None else round(float(merge_score) - float(baseline_score), 4)
    merge_gap_to_selected = _format_float((merge_diag or {}).get("replayed_gap_to_selected"))
    merge_gap_to_near_miss = _format_float((merge_diag or {}).get("replayed_gap_to_near_miss"))
    required_to_selected = _required_score_uplift(merge_gap_to_selected, merge_decision)
    required_to_near_miss = _required_score_uplift(merge_gap_to_near_miss, merge_decision)
    remaining_leverage_classification, recommended_primary_lever = _classify_remaining_leverage(
        merge_decision=merge_decision,
        required_to_selected=required_to_selected,
        required_to_near_miss=required_to_near_miss,
    )
    signal_headroom_ranking = _rank_signal_headroom(merge_metrics_payload)
    priority_signal_levers = [row["metric"] for row in signal_headroom_ranking[:3]]
    return {
        "focus_ticker": focus_ticker,
        "trade_date": trade_date,
        "report_dir": report_dir,
        "baseline_replayed_decision": baseline_decision,
        "merge_replayed_decision": merge_decision,
        "stored_decision": (baseline_diag or {}).get("stored_decision"),
        "candidate_source": (merge_diag or baseline_diag or {}).get("candidate_source"),
        "candidate_reason_codes": list((merge_diag or baseline_diag or {}).get("candidate_reason_codes") or []),
        "baseline_replayed_score_target": _format_float(baseline_score),
        "merge_replayed_score_target": _format_float(merge_score),
        "score_target_delta": score_delta,
        "baseline_gap_to_near_miss": _format_float((baseline_diag or {}).get("replayed_gap_to_near_miss")),
        "merge_gap_to_near_miss": merge_gap_to_near_miss,
        "baseline_gap_to_selected": _format_float((baseline_diag or {}).get("replayed_gap_to_selected")),
        "merge_gap_to_selected": merge_gap_to_selected,
        "required_score_uplift_to_near_miss": required_to_near_miss,
        "required_score_uplift_to_selected": required_to_selected,
        "decision_delta_rank": decision_delta,
        "decision_uplift_classification": classification,
        "remaining_leverage_classification": remaining_leverage_classification,
        "recommended_primary_lever": recommended_primary_lever,
        "priority_signal_levers": priority_signal_levers,
        "signal_headroom_ranking": signal_headroom_ranking[:5],
        "breakout_signal_uplift_applied": bool(breakout_signal_uplift.get("applied")),
        "breakout_signal_uplift_eligible": bool(breakout_signal_uplift.get("eligible")),
        "breakout_signal_uplift_confidence_delta": dict(breakout_signal_uplift.get("confidence_delta") or {}),
        "volume_signal_uplift_applied": bool(breakout_signal_uplift.get("volume_carryover_applied")),
        "volume_signal_uplift_eligible": bool(dict(breakout_signal_uplift.get("gate_hits") or {}).get("volatility_subfactor")),
        "volume_signal_uplift_confidence_delta": {
            "volatility_confidence": dict(breakout_signal_uplift.get("confidence_delta") or {}).get("volatility_confidence")
        },
        "layer_c_alignment_uplift_applied": bool(layer_c_alignment_uplift.get("applied")),
        "layer_c_alignment_uplift_eligible": bool(layer_c_alignment_uplift.get("eligible")),
        "layer_c_alignment_uplift_delta": dict(layer_c_alignment_uplift.get("delta") or {}),
        "sector_resonance_uplift_applied": bool(sector_resonance_uplift.get("applied")),
        "sector_resonance_uplift_eligible": bool(sector_resonance_uplift.get("eligible")),
        "sector_resonance_uplift_delta": dict(sector_resonance_uplift.get("delta") or {}),
        "prepared_breakout_penalty_relief_applied": bool(prepared_breakout_penalty_relief.get("applied")),
        "prepared_breakout_penalty_relief_eligible": bool(prepared_breakout_penalty_relief.get("eligible")),
        "prepared_breakout_penalty_relief_gate_hits": dict(prepared_breakout_penalty_relief.get("gate_hits") or {}),
        "prepared_breakout_penalty_relief_penalty_delta": {
            "stale_score_penalty_weight": None
            if prepared_breakout_penalty_relief.get("effective_stale_score_penalty_weight") is None
            else round(
                float(prepared_breakout_penalty_relief.get("effective_stale_score_penalty_weight") or 0.0)
                - float(prepared_breakout_penalty_relief.get("base_stale_score_penalty_weight") or 0.0),
                4,
            ),
            "extension_score_penalty_weight": None
            if prepared_breakout_penalty_relief.get("effective_extension_score_penalty_weight") is None
            else round(
                float(prepared_breakout_penalty_relief.get("effective_extension_score_penalty_weight") or 0.0)
                - float(prepared_breakout_penalty_relief.get("base_extension_score_penalty_weight") or 0.0),
                4,
            ),
        },
        "prepared_breakout_catalyst_relief_applied": bool(prepared_breakout_catalyst_relief.get("applied")),
        "prepared_breakout_catalyst_relief_eligible": bool(prepared_breakout_catalyst_relief.get("eligible")),
        "prepared_breakout_catalyst_relief_gate_hits": dict(prepared_breakout_catalyst_relief.get("gate_hits") or {}),
        "prepared_breakout_catalyst_relief_catalyst_delta": None
        if prepared_breakout_catalyst_relief.get("effective_catalyst_freshness") is None
        else round(
            float(prepared_breakout_catalyst_relief.get("effective_catalyst_freshness") or 0.0)
            - float(prepared_breakout_catalyst_relief.get("base_catalyst_freshness") or 0.0),
            4,
        ),
        "prepared_breakout_volume_relief_applied": bool(prepared_breakout_volume_relief.get("applied")),
        "prepared_breakout_volume_relief_eligible": bool(prepared_breakout_volume_relief.get("eligible")),
        "prepared_breakout_volume_relief_gate_hits": dict(prepared_breakout_volume_relief.get("gate_hits") or {}),
        "prepared_breakout_volume_relief_volume_delta": None
        if prepared_breakout_volume_relief.get("effective_volume_expansion_quality") is None
        else round(
            float(prepared_breakout_volume_relief.get("effective_volume_expansion_quality") or 0.0)
            - float(prepared_breakout_volume_relief.get("base_volume_expansion_quality") or 0.0),
            4,
        ),
        "prepared_breakout_continuation_relief_applied": bool(prepared_breakout_continuation_relief.get("applied")),
        "prepared_breakout_continuation_relief_eligible": bool(prepared_breakout_continuation_relief.get("eligible")),
        "prepared_breakout_continuation_relief_gate_hits": dict(prepared_breakout_continuation_relief.get("gate_hits") or {}),
        "prepared_breakout_continuation_relief_breakout_delta": None
        if prepared_breakout_continuation_relief.get("effective_breakout_freshness") is None
        else round(
            float(prepared_breakout_continuation_relief.get("effective_breakout_freshness") or 0.0)
            - float(prepared_breakout_continuation_relief.get("base_breakout_freshness") or 0.0),
            4,
        ),
        "prepared_breakout_continuation_relief_trend_delta": None
        if prepared_breakout_continuation_relief.get("effective_trend_acceleration") is None
        else round(
            float(prepared_breakout_continuation_relief.get("effective_trend_acceleration") or 0.0)
            - float(prepared_breakout_continuation_relief.get("base_trend_acceleration") or 0.0),
            4,
        ),
        "prepared_breakout_selected_catalyst_relief_applied": bool(prepared_breakout_selected_catalyst_relief.get("applied")),
        "prepared_breakout_selected_catalyst_relief_eligible": bool(prepared_breakout_selected_catalyst_relief.get("eligible")),
        "prepared_breakout_selected_catalyst_relief_gate_hits": dict(prepared_breakout_selected_catalyst_relief.get("gate_hits") or {}),
        "prepared_breakout_selected_catalyst_relief_breakout_delta": None
        if prepared_breakout_selected_catalyst_relief.get("effective_breakout_freshness") is None
        else round(
            float(prepared_breakout_selected_catalyst_relief.get("effective_breakout_freshness") or 0.0)
            - float(prepared_breakout_selected_catalyst_relief.get("base_breakout_freshness") or 0.0),
            4,
        ),
        "prepared_breakout_selected_catalyst_relief_catalyst_delta": None
        if prepared_breakout_selected_catalyst_relief.get("effective_catalyst_freshness") is None
        else round(
            float(prepared_breakout_selected_catalyst_relief.get("effective_catalyst_freshness") or 0.0)
            - float(prepared_breakout_selected_catalyst_relief.get("base_catalyst_freshness") or 0.0),
            4,
        ),
        "merge_relief_applied": bool(merge_relief.get("applied")),
        "merge_relief_eligible": bool(merge_relief.get("eligible")),
        "merge_relief_gate_hits": dict(merge_relief.get("gate_hits") or {}),
        "merge_effective_select_threshold": _format_float(merge_relief.get("effective_select_threshold")),
        "merge_effective_near_miss_threshold": _format_float(merge_relief.get("effective_near_miss_threshold")),
    }


def _analyze_report_dir(report_dir: Path, focus_ticker: str, *, profile_name: str = "default") -> dict[str, Any]:
    baseline = analyze_selection_target_replay_inputs(report_dir, profile_name=profile_name, focus_tickers=[focus_ticker])
    merge_sources = [
        (path, _inject_merge_approved_context(payload, focus_ticker))
        for path, payload in load_selection_target_replay_sources(report_dir)
    ]
    merge = analyze_selection_target_replay_sources(
        merge_sources,
        profile_name=profile_name,
        focus_tickers=[focus_ticker],
    )
    baseline_by_trade_date = {str(row.get("trade_date") or ""): row for row in list(baseline.get("focused_score_diagnostics") or [])}
    merge_by_trade_date = {str(row.get("trade_date") or ""): row for row in list(merge.get("focused_score_diagnostics") or [])}
    trade_dates = sorted({*baseline_by_trade_date.keys(), *merge_by_trade_date.keys()})
    return {
        "report_dir": str(report_dir),
        "trade_dates": [
            _summarize_focus_row(
                focus_ticker=focus_ticker,
                report_dir=str(report_dir),
                trade_date=trade_date,
                baseline_diag=baseline_by_trade_date.get(trade_date),
                merge_diag=merge_by_trade_date.get(trade_date),
            )
            for trade_date in trade_dates
        ],
        "baseline_analysis": baseline,
        "merge_analysis": merge,
    }


def _candidate_recommendation(rows: list[dict[str, Any]]) -> str:
    if any(str(row.get("decision_uplift_classification")) == "promoted_to_selected" for row in rows):
        return "supports_merge_approved_replay_followup"
    if any(str(row.get("decision_uplift_classification")) == "promoted_to_near_miss" for row in rows):
        return "supports_merge_approved_watchlist_followup"
    if any(str(row.get("remaining_leverage_classification")) == "strong_upstream_signal_uplift_required" for row in rows):
        return "upstream_signal_uplift_required"
    if any(str(row.get("remaining_leverage_classification")) == "strong_execution_signal_uplift_required" for row in rows if row.get("merge_relief_applied")):
        return "execution_signal_uplift_required"
    if any(str(row.get("remaining_leverage_classification")) == "moderate_execution_uplift_required" for row in rows if row.get("merge_relief_applied")):
        return "execution_uplift_required"
    if any(str(row.get("remaining_leverage_classification")) in {"target_premium_feasible", "near_miss_threshold_tuning_feasible"} for row in rows if row.get("merge_relief_applied")):
        return "target_tuning_feasible"
    if any(bool(row.get("merge_relief_applied")) for row in rows):
        return "relief_applied_without_decision_promotion"
    return "no_incremental_merge_approved_replay_uplift_observed"


def _summarize_candidate_result(*, focus_ticker: str, report_rows: list[dict[str, Any]]) -> dict[str, Any]:
    all_rows = [trade_date_row for report_row in report_rows for trade_date_row in list(report_row.get("trade_dates") or [])]
    score_deltas = [float(row["score_target_delta"]) for row in all_rows if row.get("score_target_delta") is not None]
    promoted_to_selected_count = sum(1 for row in all_rows if row.get("decision_uplift_classification") == "promoted_to_selected")
    promoted_to_near_miss_count = sum(1 for row in all_rows if row.get("decision_uplift_classification") == "promoted_to_near_miss")
    relief_applied_count = sum(1 for row in all_rows if bool(row.get("merge_relief_applied")))
    breakout_signal_uplift_applied_count = sum(1 for row in all_rows if bool(row.get("breakout_signal_uplift_applied")))
    volume_signal_uplift_applied_count = sum(1 for row in all_rows if bool(row.get("volume_signal_uplift_applied")))
    layer_c_alignment_uplift_applied_count = sum(1 for row in all_rows if bool(row.get("layer_c_alignment_uplift_applied")))
    sector_resonance_uplift_applied_count = sum(1 for row in all_rows if bool(row.get("sector_resonance_uplift_applied")))
    prepared_breakout_penalty_relief_applied_count = sum(1 for row in all_rows if bool(row.get("prepared_breakout_penalty_relief_applied")))
    prepared_breakout_catalyst_relief_applied_count = sum(1 for row in all_rows if bool(row.get("prepared_breakout_catalyst_relief_applied")))
    prepared_breakout_volume_relief_applied_count = sum(1 for row in all_rows if bool(row.get("prepared_breakout_volume_relief_applied")))
    prepared_breakout_continuation_relief_applied_count = sum(1 for row in all_rows if bool(row.get("prepared_breakout_continuation_relief_applied")))
    prepared_breakout_selected_catalyst_relief_applied_count = sum(1 for row in all_rows if bool(row.get("prepared_breakout_selected_catalyst_relief_applied")))
    relief_rows = [row for row in all_rows if bool(row.get("merge_relief_applied"))]
    lever_source_rows = relief_rows or all_rows
    required_selected_values = [float(row["required_score_uplift_to_selected"]) for row in lever_source_rows if row.get("required_score_uplift_to_selected") is not None]
    recommended_primary_levers = [str(row.get("recommended_primary_lever")) for row in lever_source_rows if str(row.get("recommended_primary_lever") or "").strip()]
    recommended_signal_levers = [
        lever
        for row in lever_source_rows
        for lever in list(row.get("priority_signal_levers") or [])[:2]
        if str(lever or "").strip()
    ]
    best_row = min(lever_source_rows, key=lambda row: float(row.get("required_score_uplift_to_selected") or 999.0), default=None)
    return {
        "focus_ticker": focus_ticker,
        "report_dir_count": len(report_rows),
        "trade_date_count": len(all_rows),
        "promoted_to_selected_count": promoted_to_selected_count,
        "promoted_to_near_miss_count": promoted_to_near_miss_count,
        "relief_applied_count": relief_applied_count,
        "breakout_signal_uplift_applied_count": breakout_signal_uplift_applied_count,
        "volume_signal_uplift_applied_count": volume_signal_uplift_applied_count,
        "layer_c_alignment_uplift_applied_count": layer_c_alignment_uplift_applied_count,
        "sector_resonance_uplift_applied_count": sector_resonance_uplift_applied_count,
        "prepared_breakout_penalty_relief_applied_count": prepared_breakout_penalty_relief_applied_count,
        "prepared_breakout_catalyst_relief_applied_count": prepared_breakout_catalyst_relief_applied_count,
        "prepared_breakout_volume_relief_applied_count": prepared_breakout_volume_relief_applied_count,
        "prepared_breakout_continuation_relief_applied_count": prepared_breakout_continuation_relief_applied_count,
        "prepared_breakout_selected_catalyst_relief_applied_count": prepared_breakout_selected_catalyst_relief_applied_count,
        "mean_score_target_delta": _format_float(sum(score_deltas) / len(score_deltas)) if score_deltas else None,
        "max_score_target_delta": _format_float(max(score_deltas)) if score_deltas else None,
        "minimum_required_score_uplift_to_selected": _format_float(min(required_selected_values)) if required_selected_values else None,
        "best_trade_date_for_selected_promotion": None if best_row is None else best_row.get("trade_date"),
        "recommended_primary_lever": None if not recommended_primary_levers else max(set(recommended_primary_levers), key=recommended_primary_levers.count),
        "recommended_signal_levers": sorted(set(recommended_signal_levers), key=lambda lever: (-recommended_signal_levers.count(lever), lever))[:3],
        "candidate_recommendation": _candidate_recommendation(all_rows),
        "rows": all_rows,
    }


def _most_common_value(values: list[str]) -> str | None:
    if not values:
        return None
    counts: dict[str, int] = {}
    first_seen: dict[str, int] = {}
    for index, value in enumerate(values):
        counts[value] = counts.get(value, 0) + 1
        first_seen.setdefault(value, index)
    return sorted(counts, key=lambda value: (-counts[value], first_seen[value]))[0]


def generate_btst_merge_replay_validation(
    *,
    reports_root: str | Path = REPORTS_ROOT,
    focus_tickers: list[str] | None = None,
    candidate_limit: int = 2,
    profile_name: str = "default",
) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    resolved_focus_tickers = _resolve_focus_tickers(resolved_reports_root, focus_tickers, candidate_limit)
    candidate_results: list[dict[str, Any]] = []

    for focus_ticker in resolved_focus_tickers:
        dossier_path = resolved_reports_root / f"btst_tplus2_candidate_dossier_{focus_ticker}_latest.json"
        if not dossier_path.exists():
            continue
        dossier = _load_json(dossier_path)
        report_rows = []
        for report_dir in _discover_report_dirs_from_dossier(resolved_reports_root, dossier):
            report_path = Path(report_dir).expanduser()
            if not report_path.exists():
                continue
            report_rows.append(_analyze_report_dir(report_path, focus_ticker, profile_name=profile_name))
        candidate_results.append(
            {
                "focus_ticker": focus_ticker,
                "dossier_path": str(dossier_path),
                "report_rows": report_rows,
                "summary": _summarize_candidate_result(focus_ticker=focus_ticker, report_rows=report_rows),
            }
        )

    candidate_summaries = [dict(result.get("summary") or {}) for result in candidate_results]
    promoted_to_selected_count = sum(int(summary.get("promoted_to_selected_count") or 0) for summary in candidate_summaries)
    promoted_to_near_miss_count = sum(int(summary.get("promoted_to_near_miss_count") or 0) for summary in candidate_summaries)
    relief_applied_count = sum(int(summary.get("relief_applied_count") or 0) for summary in candidate_summaries)
    breakout_signal_uplift_applied_count = sum(int(summary.get("breakout_signal_uplift_applied_count") or 0) for summary in candidate_summaries)
    volume_signal_uplift_applied_count = sum(int(summary.get("volume_signal_uplift_applied_count") or 0) for summary in candidate_summaries)
    layer_c_alignment_uplift_applied_count = sum(int(summary.get("layer_c_alignment_uplift_applied_count") or 0) for summary in candidate_summaries)
    sector_resonance_uplift_applied_count = sum(int(summary.get("sector_resonance_uplift_applied_count") or 0) for summary in candidate_summaries)
    prepared_breakout_penalty_relief_applied_count = sum(int(summary.get("prepared_breakout_penalty_relief_applied_count") or 0) for summary in candidate_summaries)
    prepared_breakout_catalyst_relief_applied_count = sum(int(summary.get("prepared_breakout_catalyst_relief_applied_count") or 0) for summary in candidate_summaries)
    prepared_breakout_volume_relief_applied_count = sum(int(summary.get("prepared_breakout_volume_relief_applied_count") or 0) for summary in candidate_summaries)
    prepared_breakout_continuation_relief_applied_count = sum(int(summary.get("prepared_breakout_continuation_relief_applied_count") or 0) for summary in candidate_summaries)
    prepared_breakout_selected_catalyst_relief_applied_count = sum(int(summary.get("prepared_breakout_selected_catalyst_relief_applied_count") or 0) for summary in candidate_summaries)
    leverage_source_summaries = [summary for summary in candidate_summaries if int(summary.get("relief_applied_count") or 0) > 0] or candidate_summaries
    recommended_primary_levers = [str(summary.get("recommended_primary_lever")) for summary in leverage_source_summaries if str(summary.get("recommended_primary_lever") or "").strip()]
    recommended_signal_levers = [
        lever
        for summary in leverage_source_summaries
        for lever in list(summary.get("recommended_signal_levers") or [])[:2]
        if str(lever or "").strip()
    ]
    overall_verdict = "no_merge_replay_uplift"
    if promoted_to_selected_count > 0:
        overall_verdict = "merge_replay_promotes_selected"
    elif promoted_to_near_miss_count > 0:
        overall_verdict = "merge_replay_promotes_watchlist"
    elif relief_applied_count > 0:
        overall_verdict = "merge_replay_relief_applied_without_decision_change"

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "reports_root": str(resolved_reports_root),
        "profile_name": profile_name,
        "focus_tickers": resolved_focus_tickers,
        "candidate_count": len(candidate_summaries),
        "overall_verdict": overall_verdict,
        "promoted_to_selected_count": promoted_to_selected_count,
        "promoted_to_near_miss_count": promoted_to_near_miss_count,
        "relief_applied_count": relief_applied_count,
        "breakout_signal_uplift_applied_count": breakout_signal_uplift_applied_count,
        "volume_signal_uplift_applied_count": volume_signal_uplift_applied_count,
        "layer_c_alignment_uplift_applied_count": layer_c_alignment_uplift_applied_count,
        "sector_resonance_uplift_applied_count": sector_resonance_uplift_applied_count,
        "prepared_breakout_penalty_relief_applied_count": prepared_breakout_penalty_relief_applied_count,
        "prepared_breakout_catalyst_relief_applied_count": prepared_breakout_catalyst_relief_applied_count,
        "prepared_breakout_volume_relief_applied_count": prepared_breakout_volume_relief_applied_count,
        "prepared_breakout_continuation_relief_applied_count": prepared_breakout_continuation_relief_applied_count,
        "prepared_breakout_selected_catalyst_relief_applied_count": prepared_breakout_selected_catalyst_relief_applied_count,
        "recommended_next_lever": _most_common_value(recommended_primary_levers),
        "recommended_signal_levers": sorted(set(recommended_signal_levers), key=lambda lever: (-recommended_signal_levers.count(lever), lever))[:3],
        "candidates": candidate_results,
        "candidate_summaries": candidate_summaries,
    }


def render_btst_merge_replay_validation_markdown(analysis: dict[str, Any]) -> str:
    lines = [
        "# BTST Merge Replay Validation",
        "",
        f"- overall_verdict: {analysis.get('overall_verdict')}",
        f"- profile_name: {analysis.get('profile_name')}",
        f"- focus_tickers: {list(analysis.get('focus_tickers') or [])}",
        f"- promoted_to_selected_count: {analysis.get('promoted_to_selected_count')}",
        f"- promoted_to_near_miss_count: {analysis.get('promoted_to_near_miss_count')}",
        f"- relief_applied_count: {analysis.get('relief_applied_count')}",
        f"- breakout_signal_uplift_applied_count: {analysis.get('breakout_signal_uplift_applied_count')}",
        f"- volume_signal_uplift_applied_count: {analysis.get('volume_signal_uplift_applied_count')}",
        f"- layer_c_alignment_uplift_applied_count: {analysis.get('layer_c_alignment_uplift_applied_count')}",
        f"- sector_resonance_uplift_applied_count: {analysis.get('sector_resonance_uplift_applied_count')}",
        f"- prepared_breakout_penalty_relief_applied_count: {analysis.get('prepared_breakout_penalty_relief_applied_count')}",
        f"- prepared_breakout_catalyst_relief_applied_count: {analysis.get('prepared_breakout_catalyst_relief_applied_count')}",
        f"- prepared_breakout_volume_relief_applied_count: {analysis.get('prepared_breakout_volume_relief_applied_count')}",
        f"- prepared_breakout_continuation_relief_applied_count: {analysis.get('prepared_breakout_continuation_relief_applied_count')}",
        f"- prepared_breakout_selected_catalyst_relief_applied_count: {analysis.get('prepared_breakout_selected_catalyst_relief_applied_count')}",
        f"- recommended_next_lever: {analysis.get('recommended_next_lever')}",
        f"- recommended_signal_levers: {list(analysis.get('recommended_signal_levers') or [])}",
        "",
        "## Candidate summaries",
    ]
    for summary in list(analysis.get("candidate_summaries") or []):
        lines.extend(
            [
                "",
                f"### {summary.get('focus_ticker')}",
                f"- candidate_recommendation: {summary.get('candidate_recommendation')}",
                f"- report_dir_count: {summary.get('report_dir_count')}",
                f"- trade_date_count: {summary.get('trade_date_count')}",
                f"- promoted_to_selected_count: {summary.get('promoted_to_selected_count')}",
                f"- promoted_to_near_miss_count: {summary.get('promoted_to_near_miss_count')}",
                f"- relief_applied_count: {summary.get('relief_applied_count')}",
                f"- breakout_signal_uplift_applied_count: {summary.get('breakout_signal_uplift_applied_count')}",
                f"- volume_signal_uplift_applied_count: {summary.get('volume_signal_uplift_applied_count')}",
                f"- layer_c_alignment_uplift_applied_count: {summary.get('layer_c_alignment_uplift_applied_count')}",
                f"- sector_resonance_uplift_applied_count: {summary.get('sector_resonance_uplift_applied_count')}",
                f"- prepared_breakout_penalty_relief_applied_count: {summary.get('prepared_breakout_penalty_relief_applied_count')}",
                f"- prepared_breakout_catalyst_relief_applied_count: {summary.get('prepared_breakout_catalyst_relief_applied_count')}",
                f"- prepared_breakout_volume_relief_applied_count: {summary.get('prepared_breakout_volume_relief_applied_count')}",
                f"- prepared_breakout_continuation_relief_applied_count: {summary.get('prepared_breakout_continuation_relief_applied_count')}",
                f"- prepared_breakout_selected_catalyst_relief_applied_count: {summary.get('prepared_breakout_selected_catalyst_relief_applied_count')}",
                f"- mean_score_target_delta: {summary.get('mean_score_target_delta')}",
                f"- max_score_target_delta: {summary.get('max_score_target_delta')}",
                f"- minimum_required_score_uplift_to_selected: {summary.get('minimum_required_score_uplift_to_selected')}",
                f"- best_trade_date_for_selected_promotion: {summary.get('best_trade_date_for_selected_promotion')}",
                f"- recommended_primary_lever: {summary.get('recommended_primary_lever')}",
                f"- recommended_signal_levers: {list(summary.get('recommended_signal_levers') or [])}",
            ]
        )
        rows = list(summary.get("rows") or [])
        if rows:
            lines.append("")
            lines.append("| trade_date | baseline | merge | delta | required_to_selected | lever | signal_levers | breakout_uplift | volume_uplift | alignment_uplift | sector_uplift | prepared_breakout_penalty_relief | prepared_breakout_catalyst_relief | prepared_breakout_volume_relief | prepared_breakout_continuation_relief | prepared_breakout_selected_catalyst_relief | relief_applied | report_dir |")
            lines.append("| --- | --- | --- | --- | ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
            for row in rows:
                lines.append(
                    f"| {row.get('trade_date')} | {row.get('baseline_replayed_decision')} | {row.get('merge_replayed_decision')} | "
                    f"{row.get('decision_uplift_classification')} | {row.get('required_score_uplift_to_selected')} | {row.get('recommended_primary_lever')} | {','.join(list(row.get('priority_signal_levers') or [])[:2])} | {row.get('breakout_signal_uplift_applied')} | {row.get('volume_signal_uplift_applied')} | {row.get('layer_c_alignment_uplift_applied')} | {row.get('sector_resonance_uplift_applied')} | {row.get('prepared_breakout_penalty_relief_applied')} | {row.get('prepared_breakout_catalyst_relief_applied')} | {row.get('prepared_breakout_volume_relief_applied')} | {row.get('prepared_breakout_continuation_relief_applied')} | {row.get('prepared_breakout_selected_catalyst_relief_applied')} | {row.get('merge_relief_applied')} | "
                    f"{Path(str(row.get('report_dir') or '')).name} |"
                )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate BTST merge-approved continuation uplift against historical replay artifacts.")
    parser.add_argument("--reports-root", default=str(REPORTS_ROOT), help="Reports root containing candidate dossiers and replay report directories.")
    parser.add_argument("--focus-tickers", default=None, help="Comma-separated focus tickers. Defaults to merge-review focus plus top ranked candidates.")
    parser.add_argument("--candidate-limit", type=int, default=2, help="Maximum auto-discovered candidates to analyze.")
    parser.add_argument("--profile-name", default="default", help="Short-trade profile used during replay validation.")
    parser.add_argument("--output", default=None, help="Optional JSON output path.")
    parser.add_argument("--markdown-output", default=None, help="Optional Markdown output path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    focus_tickers = None
    if args.focus_tickers:
        focus_tickers = [ticker.strip() for ticker in str(args.focus_tickers).split(",") if ticker.strip()]
    analysis = generate_btst_merge_replay_validation(
        reports_root=args.reports_root,
        focus_tickers=focus_tickers,
        candidate_limit=max(1, int(args.candidate_limit)),
        profile_name=args.profile_name,
    )
    output_path = Path(args.output) if args.output else Path(args.reports_root) / "btst_merge_replay_validation_latest.json"
    markdown_output_path = Path(args.markdown_output) if args.markdown_output else Path(args.reports_root) / "btst_merge_replay_validation_latest.md"
    _write_text(output_path, json.dumps(analysis, ensure_ascii=False, indent=2) + "\n")
    _write_text(markdown_output_path, render_btst_merge_replay_validation_markdown(analysis))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
