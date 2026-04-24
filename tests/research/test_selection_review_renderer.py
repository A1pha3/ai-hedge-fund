from src.research.models import RejectedCandidate, SelectedCandidate, SelectionSnapshot
from src.research.review_renderer import render_selection_review
from src.targets.models import DualTargetEvaluation, DualTargetSummary, TargetEvaluationResult


def test_render_selection_review_contains_key_sections():
    snapshot = SelectionSnapshot(
        run_id="session_001",
        trade_date="2026-03-22",
        decision_timestamp="2026-03-22T15:05:00+08:00",
        data_available_until="2026-03-22T15:00:00+08:00",
        target_mode="research_only",
        universe_summary={
            "input_symbol_count": 100,
            "candidate_count": 20,
            "high_pool_count": 8,
            "watchlist_count": 2,
            "catalyst_theme_candidate_count": 1,
            "catalyst_theme_shadow_candidate_count": 1,
            "buy_order_count": 1,
        },
        selected=[
            SelectedCandidate(
                symbol="000001",
                score_final=0.72,
                layer_b_summary={
                    "top_factors": [
                        {"name": "trend", "weight": 0.3, "source": "market_state.adjusted_weights"},
                    ]
                },
                execution_bridge={"included_in_buy_orders": False, "block_reason": "blocked_by_reentry_score_confirmation", "constraint_binding": "score", "reentry_review_until": "20260312"},
                research_prompts={
                    "why_selected": ["Layer B 综合分数高"],
                    "what_to_check": ["确认逻辑不是事件噪声"],
                },
                target_context={
                    "execution_eligible": False,
                    "downgrade_reasons": ["btst_regime_gate_not_tradeable", "historical_prior_not_execution_ready"],
                    "historical_prior_quality_level": "watch_only",
                    "btst_regime_gate": "shadow_only",
                },
                target_decisions={
                    "research": TargetEvaluationResult(target_type="research", decision="selected", score_target=0.72),
                    "short_trade": TargetEvaluationResult(
                        target_type="short_trade",
                        decision="blocked",
                        score_target=0.31,
                        blockers=["missing_trend_signal"],
                        execution_eligible=False,
                        downgrade_reasons=["btst_regime_gate_not_tradeable"],
                        historical_prior_quality_level="watch_only",
                        btst_regime_gate="shadow_only",
                    ),
                },
            )
        ],
        rejected=[
            RejectedCandidate(
                symbol="300750",
                rejection_stage="watchlist",
                rejection_reason_text="analyst_divergence_high",
                target_decisions={
                    "research": TargetEvaluationResult(target_type="research", decision="near_miss", score_target=0.39),
                },
            )
        ],
        selection_targets={"000001": DualTargetEvaluation(ticker="000001", trade_date="2026-03-22")},
        target_summary=DualTargetSummary(target_mode="research_only", selection_target_count=1, research_selected_count=1, shell_target_count=1),
        research_view={
            "selected_symbols": ["000001"],
            "near_miss_symbols": ["300750"],
            "rejected_symbols": [],
            "blocker_counts": {"analyst_divergence_high": 1},
        },
        short_trade_view={
            "selected_symbols": [],
            "near_miss_symbols": [],
            "rejected_symbols": [],
            "blocked_symbols": ["000001"],
            "blocker_counts": {"missing_trend_signal": 1},
        },
        dual_target_delta={
            "delta_counts": {"research_pass_short_reject": 1},
            "representative_cases": [
                {
                    "ticker": "000001",
                    "delta_classification": "research_pass_short_reject",
                    "research_decision": "selected",
                    "short_trade_decision": "blocked",
                    "delta_summary": ["research target selected while short trade target stays blocked"],
                }
            ],
            "dominant_delta_reasons": ["research target selected while short trade target stays blocked"],
        },
        catalyst_theme_candidates=[
            {
                "ticker": "300999",
                "candidate_source": "catalyst_theme",
                "score_target": 0.4123,
                "preferred_entry_mode": "theme_research_followup",
                "positive_tags": ["strong_catalyst_freshness"],
                "top_reasons": ["catalyst_freshness=0.82", "sector_resonance=0.25"],
                "metrics": {
                    "breakout_freshness": 0.31,
                    "trend_acceleration": 0.26,
                    "close_strength": 0.57,
                    "sector_resonance": 0.25,
                    "catalyst_freshness": 0.82,
                },
                "gate_status": {"data": "pass", "structural": "fail", "score": "proxy_only"},
                "blockers": ["stale_trend_repair_penalty"],
            }
        ],
        catalyst_theme_shadow_candidates=[
            {
                "ticker": "301000",
                "candidate_source": "catalyst_theme_shadow",
                "score_target": 0.3891,
                "preferred_entry_mode": "theme_research_followup",
                "positive_tags": ["strong_catalyst_freshness"],
                "top_reasons": ["candidate_score=0.39", "total_shortfall=0.07"],
                "metrics": {
                    "breakout_freshness": 0.28,
                    "trend_acceleration": 0.22,
                    "close_strength": 0.41,
                    "sector_resonance": 0.18,
                    "catalyst_freshness": 0.79,
                },
                "gate_status": {"data": "pass", "structural": "fail", "score": "shadow"},
                "blockers": ["sector_resonance_below_catalyst_theme_floor"],
                "filter_reason": "sector_resonance_below_catalyst_theme_floor",
                "threshold_shortfalls": {"sector_resonance": 0.02, "candidate_score": 0.05},
                "failed_threshold_count": 2,
                "total_shortfall": 0.07,
            }
        ],
    )

    markdown = render_selection_review(snapshot)

    assert "# 选股审查日报 - 2026-03-22" in markdown
    assert "## 今日入选股票" in markdown
    assert "000001" in markdown
    assert "buy_order_blocker: blocked_by_reentry_score_confirmation (binding=score)" in markdown
    assert "reentry_review_until: 20260312" in markdown
    assert "Layer B 因子摘要" in markdown
    assert "trend: weight=0.3000" in markdown
    assert "## 双目标空壳状态" in markdown
    assert "## Research Target Summary" in markdown
    assert "selected_symbols: 000001" in markdown
    assert "near_miss_symbols: 300750" in markdown
    assert "## Short Trade Target Summary" in markdown
    assert "blocked_symbols: 000001" in markdown
    assert "## Target Delta Highlights" in markdown
    assert "delta_counts: research_pass_short_reject=1" in markdown
    assert "## 题材催化研究池" in markdown
    assert "300999" in markdown
    assert "301000" in markdown
    assert "catalyst_theme_shadow_candidate_count: 1" in markdown
    assert "近阈值影子池" in markdown
    assert "filter_reason: sector_resonance_below_catalyst_theme_floor" in markdown
    assert "target_mode: research_only" in markdown
    assert "attached_target_tickers: 000001" in markdown
    assert "research_target: selected (score=0.7200)" in markdown
    assert "short_trade_target: blocked (score=0.3100, blockers=missing_trend_signal)" in markdown
    assert "为什么入选" in markdown
    assert "为何被降级" in markdown
    assert "是否可执行" in markdown
    assert "historical_prior_not_execution_ready" in markdown
    assert "否" in markdown
    assert "## 接近入选但落选" in markdown
    assert "300750" in markdown
