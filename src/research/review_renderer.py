from __future__ import annotations

from src.research.models import SelectionSnapshot


def _format_layer_b_factor(factor: dict) -> str:
    name = str(factor.get("name", "unknown"))
    if "direction" in factor and "confidence" in factor:
        return f"{name}: direction={float(factor.get('direction', 0.0)):.2f}, confidence={float(factor.get('confidence', 0.0)):.2f}"
    if "weight" in factor:
        return f"{name}: weight={float(factor.get('weight', 0.0)):.4f} ({factor.get('source', 'fallback')})"
    if "value" in factor:
        return f"{name}: value={float(factor.get('value', 0.0)):.4f} ({factor.get('source', 'fallback')})"
    return name


def _render_selected_section(snapshot: SelectionSnapshot) -> list[str]:
    lines = ["## 今日入选股票", ""]
    if not snapshot.selected:
        lines.append("- 无入选股票")
        lines.append("")
        return lines

    for index, candidate in enumerate(snapshot.selected, start=1):
        lines.append(f"### {index}. {candidate.symbol} {candidate.name}".rstrip())
        lines.append(f"- final_score: {candidate.score_final:.4f}")
        lines.append(f"- buy_order: {'yes' if candidate.execution_bridge.get('included_in_buy_orders') else 'no'}")
        if candidate.execution_bridge.get("block_reason"):
            blocker = str(candidate.execution_bridge.get("block_reason"))
            constraint_binding = candidate.execution_bridge.get("constraint_binding")
            if constraint_binding:
                blocker = f"{blocker} (binding={constraint_binding})"
            lines.append(f"- buy_order_blocker: {blocker}")
        if candidate.execution_bridge.get("reentry_review_until"):
            lines.append(f"- reentry_review_until: {candidate.execution_bridge.get('reentry_review_until')}")
        top_factors = list((candidate.layer_b_summary or {}).get("top_factors", []) or [])
        if top_factors:
            lines.append("- Layer B 因子摘要:")
            for factor in top_factors[:3]:
                lines.append(f"  - {_format_layer_b_factor(factor)}")
        lines.append("- 入选原因:")
        for reason in list(candidate.research_prompts.get("why_selected", []))[:3]:
            lines.append(f"  - {reason}")
        lines.append("- 建议重点复核:")
        for reason in list(candidate.research_prompts.get("what_to_check", []))[:2]:
            lines.append(f"  - {reason}")
        lines.append("")
    return lines


def _render_rejected_section(snapshot: SelectionSnapshot) -> list[str]:
    lines = ["## 接近入选但落选", ""]
    if not snapshot.rejected:
        lines.append("- 无接近入选但落选的样本")
        lines.append("")
        return lines

    for index, candidate in enumerate(snapshot.rejected, start=1):
        lines.append(f"### {index}. {candidate.symbol} {candidate.name}".rstrip())
        lines.append(f"- rejection_stage: {candidate.rejection_stage}")
        reason_text = candidate.rejection_reason_text or ", ".join(candidate.rejection_reason_codes)
        lines.append(f"- 原因: {reason_text}")
        lines.append("")
    return lines


def render_selection_review(snapshot: SelectionSnapshot) -> str:
    counts = dict(snapshot.universe_summary or {})
    funnel = dict(snapshot.funnel_diagnostics or {})
    lines = [
        f"# 选股审查日报 - {snapshot.trade_date}",
        "",
        "## 运行概览",
        f"- run_id: {snapshot.run_id}",
        f"- universe: {counts.get('input_symbol_count', 0)}",
        f"- candidate_count: {counts.get('candidate_count', 0)}",
        f"- high_pool_count: {counts.get('high_pool_count', 0)}",
        f"- watchlist_count: {counts.get('watchlist_count', 0)}",
        f"- buy_order_count: {counts.get('buy_order_count', 0)}",
        "",
    ]
    lines.extend(_render_selected_section(snapshot))
    lines.extend(_render_rejected_section(snapshot))
    lines.extend(
        [
            "## 当日漏斗观察",
            f"- Layer A -> candidate: {counts.get('input_symbol_count', 0)} -> {counts.get('candidate_count', 0)}",
            f"- candidate -> high_pool: {counts.get('candidate_count', 0)} -> {counts.get('high_pool_count', 0)}",
            f"- high_pool -> watchlist: {counts.get('high_pool_count', 0)} -> {counts.get('watchlist_count', 0)}",
            f"- watchlist -> buy_orders: {counts.get('watchlist_count', 0)} -> {counts.get('buy_order_count', 0)}",
            "",
            "## 研究员标注说明",
            "- review_scope 以 watchlist 为主",
            "- buy_orders 只作为下游承接参考",
        ]
    )
    if funnel:
        lines.extend(["", "## 附加诊断", f"- funnel_diagnostics_keys: {', '.join(sorted(funnel.keys()))}"])
    return "\n".join(lines) + "\n"