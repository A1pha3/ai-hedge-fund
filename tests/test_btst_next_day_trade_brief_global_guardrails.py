from __future__ import annotations

from src.paper_trading._btst_reporting import brief_builder, brief_rendering


def test_btst_brief_builder_regime_guardrail_risk_off() -> None:
    guardrail = brief_builder._btst_regime_gate_guardrail({"market_state": {"regime_gate_level": "risk_off"}})
    assert guardrail is not None
    assert "risk_off" in guardrail


def test_btst_next_day_trade_brief_markdown_renders_global_guardrails() -> None:
    analysis = {
        "trade_date": "2026-05-22",
        "next_trade_date": "2026-05-23",
        "target_mode": "short_trade_only",
        "selection_target": "short_trade_only",
        "summary": {
            "short_trade_selected_count": 0,
            "short_trade_near_miss_count": 0,
            "short_trade_blocked_count": 0,
            "short_trade_rejected_count": 0,
            "short_trade_formal_blocked_selected_count": 0,
            "short_trade_formal_non_halt_blocked_selected_count": 0,
            "short_trade_formal_non_halt_gate_counts": {},
            "short_trade_formal_non_halt_prior_quality_counts": {},
            "short_trade_formal_block_flag_counts": {},
            "short_trade_opportunity_pool_count": 0,
            "no_history_observer_count": 0,
            "research_upside_radar_count": 0,
            "runner_recall_review_count": 0,
            "catalyst_theme_count": 0,
            "catalyst_theme_shadow_count": 0,
            "catalyst_theme_frontier_promoted_count": 0,
            "upstream_shadow_candidate_count": 0,
            "upstream_shadow_promotable_count": 0,
            "excluded_research_count": 0,
        },
        "recommendation": "空仓观察",
        "global_guardrails": ["Regime gate (risk_off): 默认不做正式买入，只允许观察/确认性复审；若无明确修复信号则空仓。"],
        "selected_entries": [],
        "near_miss_entries": [],
        "opportunity_pool_entries": [],
        "risky_observer_entries": [],
        "no_history_observer_entries": [],
        "weak_history_pruned_entries": [],
        "research_upside_radar_entries": [],
        "runner_recall_review_entries": [],
        "catalyst_theme_entries": [],
        "catalyst_theme_frontier_priority": {},
        "catalyst_theme_shadow_entries": [],
        "excluded_research_entries": [],
        "upstream_shadow_summary": {},
        "upstream_shadow_entries": [],
        "rollout_validation": {},
    }

    markdown = brief_rendering.render_btst_next_day_trade_brief_markdown(analysis)
    assert "## Global Guardrails" in markdown
    assert "Regime gate (risk_off)" in markdown
