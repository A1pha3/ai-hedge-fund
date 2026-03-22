from src.research.models import RejectedCandidate, SelectedCandidate, SelectionSnapshot
from src.research.review_renderer import render_selection_review


def test_render_selection_review_contains_key_sections():
    snapshot = SelectionSnapshot(
        run_id="session_001",
        trade_date="2026-03-22",
        decision_timestamp="2026-03-22T15:05:00+08:00",
        data_available_until="2026-03-22T15:00:00+08:00",
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
                execution_bridge={"included_in_buy_orders": True},
                research_prompts={
                    "why_selected": ["Layer B 综合分数高"],
                    "what_to_check": ["确认逻辑不是事件噪声"],
                },
            )
        ],
        rejected=[
            RejectedCandidate(
                symbol="300750",
                rejection_stage="watchlist",
                rejection_reason_text="analyst_divergence_high",
            )
        ],
    )

    markdown = render_selection_review(snapshot)

    assert "# 选股审查日报 - 2026-03-22" in markdown
    assert "## 今日入选股票" in markdown
    assert "000001" in markdown
    assert "## 接近入选但落选" in markdown
    assert "300750" in markdown