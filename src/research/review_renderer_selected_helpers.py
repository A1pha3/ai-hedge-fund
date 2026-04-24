from __future__ import annotations

from src.research.models import SelectedCandidate


def render_selected_candidate(candidate: SelectedCandidate, index: int, format_target_decision, format_layer_b_factor) -> list[str]:
    lines = [
        f"### {index}. {candidate.symbol} {candidate.name}".rstrip(),
        f"- final_score: {candidate.score_final:.4f}",
        f"- buy_order: {'yes' if candidate.execution_bridge.get('included_in_buy_orders') else 'no'}",
    ]
    lines.extend(_render_target_decisions(candidate, format_target_decision))
    lines.extend(_render_execution_bridge(candidate))
    lines.extend(_render_layer_b_summary(candidate, format_layer_b_factor))
    lines.extend(_render_prompt_section(candidate=candidate, label="为什么入选", key="why_selected", limit=3))
    lines.extend(_render_downgrade_section(candidate))
    lines.extend(_render_execution_eligibility_section(candidate))
    lines.extend(_render_prompt_section(candidate=candidate, label="建议重点复核", key="what_to_check", limit=2))
    lines.append("")
    return lines


def _render_target_decisions(candidate: SelectedCandidate, format_target_decision) -> list[str]:
    lines: list[str] = []
    research_target_summary = format_target_decision(candidate, "research")
    if research_target_summary:
        lines.append(f"- research_target: {research_target_summary}")
    short_trade_target_summary = format_target_decision(candidate, "short_trade")
    if short_trade_target_summary:
        lines.append(f"- short_trade_target: {short_trade_target_summary}")
    return lines


def _render_execution_bridge(candidate: SelectedCandidate) -> list[str]:
    lines: list[str] = []
    if candidate.execution_bridge.get("block_reason"):
        blocker = str(candidate.execution_bridge.get("block_reason"))
        constraint_binding = candidate.execution_bridge.get("constraint_binding")
        if constraint_binding:
            blocker = f"{blocker} (binding={constraint_binding})"
        lines.append(f"- buy_order_blocker: {blocker}")
    if candidate.execution_bridge.get("reentry_review_until"):
        lines.append(f"- reentry_review_until: {candidate.execution_bridge.get('reentry_review_until')}")
    return lines


def _render_layer_b_summary(candidate: SelectedCandidate, format_layer_b_factor) -> list[str]:
    top_factors = list((candidate.layer_b_summary or {}).get("top_factors", []) or [])
    if not top_factors:
        return []
    return ["- Layer B 因子摘要:"] + [f"  - {format_layer_b_factor(factor)}" for factor in top_factors[:3]]


def _render_prompt_section(*, candidate: SelectedCandidate, label: str, key: str, limit: int) -> list[str]:
    return [f"- {label}:"] + [f"  - {reason}" for reason in list(candidate.research_prompts.get(key, []))[:limit]]


def _render_downgrade_section(candidate: SelectedCandidate) -> list[str]:
    downgrade_reasons = [str(reason) for reason in list((candidate.target_context or {}).get("downgrade_reasons", []) or []) if str(reason or "").strip()]
    if not downgrade_reasons:
        downgrade_reasons = ["无，保留正式执行资格"]
    return ["- 为何被降级:"] + [f"  - {reason}" for reason in downgrade_reasons[:3]]


def _render_execution_eligibility_section(candidate: SelectedCandidate) -> list[str]:
    target_context = dict(candidate.target_context or {})
    details: list[str] = []
    if target_context.get("btst_regime_gate"):
        details.append(f"gate={target_context['btst_regime_gate']}")
    if target_context.get("historical_prior_quality_level"):
        details.append(f"prior={target_context['historical_prior_quality_level']}")
    status = "是" if target_context.get("execution_eligible") else "否"
    return [f"- 是否可执行:", f"  - {status}" + (f" ({', '.join(details)})" if details else "")]
