from __future__ import annotations

from collections.abc import Callable
from typing import Any


StepBuilder = Callable[..., str | None]
LeadStepBuilder = Callable[..., str]


def extract_carryover_contract_context(control_tower_snapshot: dict[str, Any]) -> dict[str, Any]:
    selected_summary = dict(control_tower_snapshot.get("selected_outcome_refresh_summary") or {})
    audit_summary = dict(control_tower_snapshot.get("carryover_multiday_continuation_audit_summary") or {})
    peer_summary = dict(control_tower_snapshot.get("carryover_aligned_peer_harvest_summary") or {})
    peer_expansion_summary = dict(control_tower_snapshot.get("carryover_peer_expansion_summary") or {})
    peer_proof_summary = dict(control_tower_snapshot.get("carryover_aligned_peer_proof_summary") or {})
    peer_promotion_gate_summary = dict(control_tower_snapshot.get("carryover_peer_promotion_gate_summary") or {})
    peer_focus_ticker = str(
        peer_promotion_gate_summary.get("focus_ticker")
        or peer_proof_summary.get("focus_ticker")
        or peer_expansion_summary.get("focus_ticker")
        or peer_summary.get("focus_ticker")
        or ""
    ).strip()
    peer_focus_status = str(
        peer_promotion_gate_summary.get("focus_gate_verdict")
        or peer_proof_summary.get("focus_promotion_review_verdict")
        or peer_expansion_summary.get("focus_status")
        or peer_summary.get("focus_status")
        or ""
    ).strip()
    return {
        "audit_summary": audit_summary,
        "formal_selected_ticker": str(selected_summary.get("focus_ticker") or audit_summary.get("selected_ticker") or "").strip(),
        "overall_contract_verdict": str(selected_summary.get("focus_overall_contract_verdict") or "").strip(),
        "selected_preferred_entry_mode": str(audit_summary.get("selected_preferred_entry_mode") or "").strip(),
        "selected_execution_quality_label": str(audit_summary.get("selected_execution_quality_label") or "").strip(),
        "selected_entry_timing_bias": str(audit_summary.get("selected_entry_timing_bias") or "").strip(),
        "peer_focus_ticker": peer_focus_ticker,
        "peer_focus_status": peer_focus_status,
        "peer_proof_focus_ticker": str(peer_proof_summary.get("focus_ticker") or "").strip(),
        "peer_proof_focus_verdict": str(peer_proof_summary.get("focus_promotion_review_verdict") or "").strip(),
        "peer_promotion_gate_focus_ticker": str(peer_promotion_gate_summary.get("focus_ticker") or "").strip(),
        "peer_promotion_gate_focus_verdict": str(peer_promotion_gate_summary.get("focus_gate_verdict") or "").strip(),
        "priority_expansion_tickers": list(peer_expansion_summary.get("priority_expansion_tickers") or []),
        "watch_with_risk_tickers": list(peer_expansion_summary.get("watch_with_risk_tickers") or []),
        "ready_for_promotion_review_tickers": list(peer_proof_summary.get("ready_for_promotion_review_tickers") or []),
        "promotion_gate_ready_tickers": list(peer_promotion_gate_summary.get("ready_tickers") or []),
    }


def describe_selected_contract_style(*, audit_summary: dict[str, Any]) -> str:
    preferred_entry_mode = str(audit_summary.get("selected_preferred_entry_mode") or "").strip()
    execution_quality_label = str(audit_summary.get("selected_execution_quality_label") or "").strip()
    entry_timing_bias = str(audit_summary.get("selected_entry_timing_bias") or "").strip()
    if preferred_entry_mode == "intraday_confirmation_only" or execution_quality_label in {"intraday_only", "gap_chase_risk"} or entry_timing_bias == "confirm_then_reduce":
        return "intraday confirmation-only"
    if audit_summary.get("selected_path_t2_bias_only"):
        return "confirm-then-hold + T+2 bias"
    return "confirm-then-hold"


def prioritize_ticker_in_list(tickers: list[Any], prioritized_ticker: str) -> list[str]:
    normalized_prioritized_ticker = str(prioritized_ticker or "").strip()
    ordered = [str(ticker).strip() for ticker in tickers if str(ticker).strip()]
    if normalized_prioritized_ticker and normalized_prioritized_ticker in ordered:
        ordered = [normalized_prioritized_ticker] + [ticker for ticker in ordered if ticker != normalized_prioritized_ticker]
    return ordered


def build_labeled_why_now_segments(*segments: tuple[Any, str]) -> list[str]:
    labeled_segments: list[str] = []
    for value, label in segments:
        if value:
            labeled_segments.append(f"{label}={value}")
    return labeled_segments


def build_carryover_contract_why_now_parts(context: dict[str, Any]) -> list[str]:
    audit_summary = dict(context.get("audit_summary") or {})
    why_now_parts = [f"formal_selected={context.get('formal_selected_ticker')}"]
    why_now_parts.extend(
        build_labeled_why_now_segments(
            (context.get("overall_contract_verdict"), "contract_verdict"),
            (context.get("peer_focus_ticker"), "peer_focus"),
            (context.get("peer_focus_status"), "peer_status"),
            (context.get("peer_proof_focus_ticker"), "peer_proof_focus"),
            (context.get("peer_proof_focus_verdict"), "peer_proof_verdict"),
            (context.get("peer_promotion_gate_focus_ticker"), "peer_gate_focus"),
            (context.get("peer_promotion_gate_focus_verdict"), "peer_gate_verdict"),
        )
    )
    if audit_summary.get("selected_path_t2_bias_only"):
        why_now_parts.append("t_plus_2_bias_only")
    if audit_summary.get("broad_family_only_multiday_unsupported"):
        why_now_parts.append("broad_family_only_not_multiday_ready")
    why_now_parts.extend(
        build_labeled_why_now_segments(
            (context.get("selected_preferred_entry_mode"), "selected_entry_mode"),
            (context.get("selected_execution_quality_label"), "selected_execution_quality"),
        )
    )
    if context.get("watch_with_risk_tickers"):
        why_now_parts.append(f"watch_with_risk={context.get('watch_with_risk_tickers')}")
    return why_now_parts


def build_carryover_contract_next_steps(
    context: dict[str, Any],
    *,
    build_carryover_contract_lead_step: LeadStepBuilder,
    build_carryover_contract_broad_family_step: StepBuilder,
    build_carryover_contract_peer_focus_step: StepBuilder,
    build_carryover_contract_priority_expansion_step: StepBuilder,
    build_carryover_contract_promotion_review_step: StepBuilder,
    build_carryover_contract_promotion_gate_step: StepBuilder,
    build_carryover_contract_watch_with_risk_step: StepBuilder,
) -> list[str]:
    audit_summary = dict(context.get("audit_summary") or {})
    formal_selected_ticker = str(context.get("formal_selected_ticker") or "").strip()
    peer_focus_ticker = str(context.get("peer_focus_ticker") or "").strip()
    peer_focus_status = str(context.get("peer_focus_status") or "").strip()
    priority_expansion_tickers = prioritize_ticker_in_list(list(context.get("priority_expansion_tickers") or []), peer_focus_ticker)
    ready_for_promotion_review_tickers = list(context.get("ready_for_promotion_review_tickers") or [])
    promotion_gate_ready_tickers = list(context.get("promotion_gate_ready_tickers") or [])
    watch_with_risk_tickers = list(context.get("watch_with_risk_tickers") or [])
    contract_style = describe_selected_contract_style(audit_summary=audit_summary)

    next_steps = [build_carryover_contract_lead_step(formal_selected_ticker=formal_selected_ticker, contract_style=contract_style)]
    broad_family_step = build_carryover_contract_broad_family_step(bool(audit_summary.get("broad_family_only_multiday_unsupported")))
    if broad_family_step:
        next_steps.append(broad_family_step)
    peer_focus_step = build_carryover_contract_peer_focus_step(peer_focus_ticker=peer_focus_ticker, peer_focus_status=peer_focus_status)
    if peer_focus_step:
        next_steps.append(peer_focus_step)
    priority_expansion_step = build_carryover_contract_priority_expansion_step(priority_expansion_tickers)
    if priority_expansion_step:
        next_steps.append(priority_expansion_step)
    promotion_review_step = build_carryover_contract_promotion_review_step(ready_for_promotion_review_tickers)
    if promotion_review_step:
        next_steps.append(promotion_review_step)
    promotion_gate_step = build_carryover_contract_promotion_gate_step(promotion_gate_ready_tickers)
    if promotion_gate_step:
        next_steps.append(promotion_gate_step)
    watch_with_risk_step = build_carryover_contract_watch_with_risk_step(watch_with_risk_tickers)
    if watch_with_risk_step:
        next_steps.append(watch_with_risk_step)
    return next_steps
