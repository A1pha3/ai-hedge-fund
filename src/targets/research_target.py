from __future__ import annotations

from typing import Any

from src.execution.models import LayerCResult
from src.targets.explainability import derive_confidence, trim_reasons
from src.targets.models import TargetEvaluationResult


def evaluate_research_selected_target(*, trade_date: str, item: LayerCResult, rank_hint: int | None = None, included_in_buy_orders: bool = False) -> TargetEvaluationResult:
    positive_tags = ["watchlist_selected", "layer_c_pass"]
    negative_tags: list[str] = []
    top_reasons = [
        f"score_final={float(item.score_final):.4f}",
        f"score_b={float(item.score_b):.4f}",
        f"score_c={float(item.score_c):.4f}",
    ]
    gate_status = {
        "score": "pass",
        "layer_c": "pass",
        "execution_bridge": "pass" if included_in_buy_orders else "pending",
    }
    if item.bc_conflict:
        negative_tags.append("bc_conflict_present")
        top_reasons.append(f"bc_conflict={item.bc_conflict}")
        gate_status["consensus"] = "review"
    else:
        positive_tags.append("consensus_stable")
        gate_status["consensus"] = "pass"
    if included_in_buy_orders:
        positive_tags.append("buy_order_ready")

    return TargetEvaluationResult(
        target_type="research",
        decision="selected",
        score_target=float(item.score_final),
        confidence=derive_confidence(float(item.score_final), float(item.quality_score)),
        rank_hint=rank_hint,
        positive_tags=positive_tags,
        negative_tags=negative_tags,
        blockers=[],
        top_reasons=trim_reasons(top_reasons),
        rejection_reasons=[],
        gate_status=gate_status,
        expected_holding_window="multi_day_research",
        preferred_entry_mode="watchlist_followthrough",
        metrics_payload={
            "score_b": round(float(item.score_b), 4),
            "score_c": round(float(item.score_c), 4),
            "score_final": round(float(item.score_final), 4),
            "quality_score": round(float(item.quality_score), 4),
        },
        explainability_payload={
            "source": "layer_c_watchlist",
            "trade_date": trade_date,
            "agent_contribution_summary": dict(item.agent_contribution_summary or {}),
            "decision": item.decision,
            "bc_conflict": item.bc_conflict,
        },
    )


def evaluate_research_rejected_target(*, trade_date: str, entry: dict[str, Any], rank_hint: int | None = None) -> TargetEvaluationResult:
    score_b = float(entry.get("score_b", 0.0) or 0.0)
    score_c = float(entry.get("score_c", 0.0) or 0.0)
    score_final = float(entry.get("score_final", 0.0) or 0.0)
    reason = str(entry.get("reason") or "filtered_from_watchlist")
    reasons = [str(current) for current in list(entry.get("reasons", []) or [])]
    decision = "near_miss" if reason != "decision_avoid" else "rejected"
    blockers = [reason]
    top_reasons = [reason, f"score_final={score_final:.4f}", f"score_b={score_b:.4f}"]
    gate_status = {
        "score": "near_miss" if decision == "near_miss" else "fail",
        "layer_c": "fail",
    }

    return TargetEvaluationResult(
        target_type="research",
        decision=decision,
        score_target=score_final,
        confidence=derive_confidence(abs(score_final), abs(score_b)),
        rank_hint=rank_hint,
        positive_tags=["candidate_retained_for_review"] if decision == "near_miss" else [],
        negative_tags=trim_reasons([reason, *reasons], limit=2),
        blockers=blockers,
        top_reasons=trim_reasons(top_reasons),
        rejection_reasons=trim_reasons(reasons or [reason]),
        gate_status=gate_status,
        expected_holding_window="research_followup" if decision == "near_miss" else None,
        preferred_entry_mode="watchlist_recheck" if decision == "near_miss" else None,
        metrics_payload={
            "score_b": round(score_b, 4),
            "score_c": round(score_c, 4),
            "score_final": round(score_final, 4),
        },
        explainability_payload={
            "source": "watchlist_filter_diagnostics",
            "trade_date": trade_date,
            "decision": str(entry.get("decision") or ""),
            "bc_conflict": entry.get("bc_conflict"),
            "agent_contribution_summary": dict(entry.get("agent_contribution_summary") or {}),
        },
    )