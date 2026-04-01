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


def _format_target_decision(candidate, target_name: str) -> str | None:
    decision = (candidate.target_decisions or {}).get(target_name)
    if decision is None:
        return None
    summary = str(decision.decision or "unknown")
    score_target = float(getattr(decision, "score_target", 0.0) or 0.0)
    blockers = list(getattr(decision, "blockers", []) or [])
    if blockers:
        return f"{summary} (score={score_target:.4f}, blockers={', '.join(blockers[:2])})"
    return f"{summary} (score={score_target:.4f})"


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
        research_target_summary = _format_target_decision(candidate, "research")
        if research_target_summary:
            lines.append(f"- research_target: {research_target_summary}")
        short_trade_target_summary = _format_target_decision(candidate, "short_trade")
        if short_trade_target_summary:
            lines.append(f"- short_trade_target: {short_trade_target_summary}")
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
        research_target_summary = _format_target_decision(candidate, "research")
        if research_target_summary:
            lines.append(f"- research_target: {research_target_summary}")
        short_trade_target_summary = _format_target_decision(candidate, "short_trade")
        if short_trade_target_summary:
            lines.append(f"- short_trade_target: {short_trade_target_summary}")
        reason_text = candidate.rejection_reason_text or ", ".join(candidate.rejection_reason_codes)
        lines.append(f"- 原因: {reason_text}")
        lines.append("")
    return lines


def _render_target_summary(snapshot: SelectionSnapshot) -> list[str]:
    summary = snapshot.target_summary.model_dump(mode="json") if hasattr(snapshot.target_summary, "model_dump") else dict(snapshot.target_summary or {})
    lines = [
        "## 双目标空壳状态",
        "",
        f"- target_mode: {snapshot.target_mode}",
        f"- selection_target_count: {summary.get('selection_target_count', 0)}",
        f"- research_target_count: {summary.get('research_target_count', 0)}",
        f"- short_trade_target_count: {summary.get('short_trade_target_count', 0)}",
        f"- research_selected_count: {summary.get('research_selected_count', 0)}",
        f"- research_near_miss_count: {summary.get('research_near_miss_count', 0)}",
        f"- research_rejected_count: {summary.get('research_rejected_count', 0)}",
        f"- short_trade_selected_count: {summary.get('short_trade_selected_count', 0)}",
        f"- short_trade_near_miss_count: {summary.get('short_trade_near_miss_count', 0)}",
        f"- short_trade_blocked_count: {summary.get('short_trade_blocked_count', 0)}",
        f"- short_trade_rejected_count: {summary.get('short_trade_rejected_count', 0)}",
        f"- shell_target_count: {summary.get('shell_target_count', 0)}",
    ]
    if snapshot.selection_targets:
        lines.append(f"- attached_target_tickers: {', '.join(sorted(snapshot.selection_targets.keys()))}")
    else:
        lines.append("- attached_target_tickers: none")
    lines.append("")
    return lines


def _render_symbol_list(label: str, values: list[str]) -> str:
    return f"- {label}: {', '.join(values)}" if values else f"- {label}: none"


def _render_counter_map(label: str, values: dict[str, int]) -> str:
    if not values:
        return f"- {label}: none"
    parts = [f"{key}={value}" for key, value in sorted(values.items())]
    return f"- {label}: {', '.join(parts)}"


def _render_research_target_summary(snapshot: SelectionSnapshot) -> list[str]:
    view = snapshot.research_view
    return [
        "## Research Target Summary",
        "",
        _render_symbol_list("selected_symbols", list(view.selected_symbols or [])),
        _render_symbol_list("near_miss_symbols", list(view.near_miss_symbols or [])),
        _render_symbol_list("rejected_symbols", list(view.rejected_symbols or [])),
        _render_counter_map("blocker_counts", dict(view.blocker_counts or {})),
        "",
    ]


def _render_short_trade_target_summary(snapshot: SelectionSnapshot) -> list[str]:
    view = snapshot.short_trade_view
    return [
        "## Short Trade Target Summary",
        "",
        _render_symbol_list("selected_symbols", list(view.selected_symbols or [])),
        _render_symbol_list("near_miss_symbols", list(view.near_miss_symbols or [])),
        _render_symbol_list("rejected_symbols", list(view.rejected_symbols or [])),
        _render_symbol_list("blocked_symbols", list(view.blocked_symbols or [])),
        _render_counter_map("blocker_counts", dict(view.blocker_counts or {})),
        "",
    ]


def _render_target_delta_highlights(snapshot: SelectionSnapshot) -> list[str]:
    delta = snapshot.dual_target_delta
    lines = [
        "## Target Delta Highlights",
        "",
        _render_counter_map("delta_counts", dict(delta.delta_counts or {})),
        _render_symbol_list("dominant_delta_reasons", list(delta.dominant_delta_reasons or [])),
    ]
    representative_cases = list(delta.representative_cases or [])
    if representative_cases:
        lines.append("- representative_cases:")
        for case in representative_cases[:5]:
            ticker = str(case.get("ticker") or "")
            delta_classification = str(case.get("delta_classification") or "none")
            research_decision = str(case.get("research_decision") or "none")
            short_trade_decision = str(case.get("short_trade_decision") or "none")
            lines.append(f"  - {ticker}: {delta_classification} (research={research_decision}, short_trade={short_trade_decision})")
    else:
        lines.append("- representative_cases: none")
    lines.append("")
    return lines


def _render_catalyst_theme_section(snapshot: SelectionSnapshot) -> list[str]:
    lines = ["## 题材催化研究池", ""]
    if not snapshot.catalyst_theme_candidates and not snapshot.catalyst_theme_shadow_candidates:
        lines.append("- none")
        lines.append("")
        return lines

    if snapshot.catalyst_theme_candidates:
        lines.append("### 正式研究池")
        lines.append("")
        for index, entry in enumerate(snapshot.catalyst_theme_candidates, start=1):
            metrics = dict(entry.get("metrics") or {})
            lines.append(f"#### {index}. {entry.get('ticker')}")
            lines.append(f"- candidate_source: {entry.get('candidate_source')}")
            lines.append(f"- candidate_score: {float(entry.get('score_target', 0.0) or 0.0):.4f}")
            lines.append(f"- preferred_entry_mode: {entry.get('preferred_entry_mode') or 'n/a'}")
            lines.append(f"- positive_tags: {', '.join(entry.get('positive_tags') or []) or 'n/a'}")
            lines.append(f"- top_reasons: {', '.join(entry.get('top_reasons') or []) or 'n/a'}")
            blockers = list(entry.get("blockers") or [])
            lines.append(f"- blockers: {', '.join(blockers) if blockers else 'none'}")
            gate_status = dict(entry.get("gate_status") or {})
            lines.append("- gate_status: " + (", ".join(f"{key}={value}" for key, value in gate_status.items()) if gate_status else "none"))
            lines.append(
                "- key_metrics: "
                + ", ".join(
                    [
                        f"breakout={float(metrics.get('breakout_freshness', 0.0) or 0.0):.4f}",
                        f"trend={float(metrics.get('trend_acceleration', 0.0) or 0.0):.4f}",
                        f"close={float(metrics.get('close_strength', 0.0) or 0.0):.4f}",
                        f"sector={float(metrics.get('sector_resonance', 0.0) or 0.0):.4f}",
                        f"catalyst={float(metrics.get('catalyst_freshness', 0.0) or 0.0):.4f}",
                    ]
                )
            )
            lines.append("")

    if snapshot.catalyst_theme_shadow_candidates:
        lines.append("### 近阈值影子池")
        lines.append("")
        for index, entry in enumerate(snapshot.catalyst_theme_shadow_candidates, start=1):
            metrics = dict(entry.get("metrics") or {})
            threshold_shortfalls = dict(entry.get("threshold_shortfalls") or {})
            lines.append(f"#### {index}. {entry.get('ticker')}")
            lines.append(f"- filter_reason: {entry.get('filter_reason') or 'n/a'}")
            lines.append(f"- candidate_source: {entry.get('candidate_source')}")
            lines.append(f"- candidate_score: {float(entry.get('score_target', 0.0) or 0.0):.4f}")
            lines.append(f"- total_shortfall: {float(entry.get('total_shortfall', 0.0) or 0.0):.4f}")
            lines.append(f"- failed_threshold_count: {int(entry.get('failed_threshold_count', 0) or 0)}")
            lines.append(f"- preferred_entry_mode: {entry.get('preferred_entry_mode') or 'n/a'}")
            lines.append(f"- positive_tags: {', '.join(entry.get('positive_tags') or []) or 'n/a'}")
            lines.append(f"- top_reasons: {', '.join(entry.get('top_reasons') or []) or 'n/a'}")
            lines.append(
                "- threshold_shortfalls: "
                + (
                    ", ".join(f"{key}={float(value or 0.0):.4f}" for key, value in threshold_shortfalls.items())
                    if threshold_shortfalls
                    else "none"
                )
            )
            blockers = list(entry.get("blockers") or [])
            lines.append(f"- blockers: {', '.join(blockers) if blockers else 'none'}")
            gate_status = dict(entry.get("gate_status") or {})
            lines.append("- gate_status: " + (", ".join(f"{key}={value}" for key, value in gate_status.items()) if gate_status else "none"))
            lines.append(
                "- key_metrics: "
                + ", ".join(
                    [
                        f"breakout={float(metrics.get('breakout_freshness', 0.0) or 0.0):.4f}",
                        f"trend={float(metrics.get('trend_acceleration', 0.0) or 0.0):.4f}",
                        f"close={float(metrics.get('close_strength', 0.0) or 0.0):.4f}",
                        f"sector={float(metrics.get('sector_resonance', 0.0) or 0.0):.4f}",
                        f"catalyst={float(metrics.get('catalyst_freshness', 0.0) or 0.0):.4f}",
                    ]
                )
            )
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
        f"- catalyst_theme_candidate_count: {counts.get('catalyst_theme_candidate_count', 0)}",
        f"- catalyst_theme_shadow_candidate_count: {counts.get('catalyst_theme_shadow_candidate_count', 0)}",
        f"- buy_order_count: {counts.get('buy_order_count', 0)}",
        "",
    ]
    lines.extend(_render_target_summary(snapshot))
    lines.extend(_render_research_target_summary(snapshot))
    lines.extend(_render_short_trade_target_summary(snapshot))
    lines.extend(_render_target_delta_highlights(snapshot))
    lines.extend(_render_catalyst_theme_section(snapshot))
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