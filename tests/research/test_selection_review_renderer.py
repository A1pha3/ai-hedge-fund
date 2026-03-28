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
                target_decisions={
                    "research": TargetEvaluationResult(target_type="research", decision="selected", score_target=0.72),
                    "short_trade": TargetEvaluationResult(target_type="short_trade", decision="rejected", score_target=0.0, blockers=["short_trade_target_rules_not_implemented"]),
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
        target_summary=DualTargetSummary(target_mode="research_only", selection_target_count=1, shell_target_count=1),
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
    assert "target_mode: research_only" in markdown
    assert "attached_target_tickers: 000001" in markdown
    assert "research_target: selected (score=0.7200)" in markdown
    assert "short_trade_target: rejected (score=0.0000, blockers=short_trade_target_rules_not_implemented)" in markdown
    assert "## 接近入选但落选" in markdown
    assert "300750" in markdown