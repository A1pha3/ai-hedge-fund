from __future__ import annotations

import json
from pathlib import Path

import scripts.generate_btst_tplus2_continuation_watchboard as watchboard


def test_generate_btst_tplus2_continuation_watchboard_combines_governance_and_rollup(monkeypatch, tmp_path: Path) -> None:
    observation_pool_path = tmp_path / "pool.json"
    lane_rulepack_path = tmp_path / "rulepack.json"
    lane_validation_path = tmp_path / "validation.json"
    watchlist_validation_path = tmp_path / "watchlist_validation.json"
    validation_queue_path = tmp_path / "validation_queue.json"
    promotion_review_path = tmp_path / "promotion_review.json"
    promotion_gate_path = tmp_path / "promotion_gate.json"

    observation_pool_path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "ticker": "600988",
                        "entry_type": "anchor_cluster",
                        "priority_score": 28.55,
                        "t_plus_2_close_positive_rate": 1.0,
                        "t_plus_2_close_return_mean": 0.0355,
                        "next_close_positive_rate": 0.5,
                    },
                    {
                        "ticker": "600989",
                        "entry_type": "near_cluster_watch",
                        "priority_score": 18.94,
                        "t_plus_2_close_positive_rate": 1.0,
                        "t_plus_2_close_return_mean": 0.0117,
                        "next_close_positive_rate": 1.0,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    lane_rulepack_path.write_text(
        json.dumps(
            {
                "eligible_tickers": ["600988"],
                "watchlist_tickers": ["600989"],
                "lane_rules": {"lane_stage": "observation_only", "capital_mode": "paper_only"},
            }
        ),
        encoding="utf-8",
    )
    lane_validation_path.write_text(
        json.dumps({"eligible_tickers": ["600988"], "per_window_summaries": [{"window_verdict": "supports_tplus2_lane"}]}),
        encoding="utf-8",
    )
    watchlist_validation_path.write_text(
        json.dumps(
            {
                "candidate_ticker": "600989",
                "recent_validation_verdict": "recent_support_confirmed",
                "recent_supporting_window_count": 4,
                "recent_window_count": 4,
                "recent_support_ratio": 1.0,
            }
        ),
        encoding="utf-8",
    )
    validation_queue_path.write_text(
        json.dumps(
            {
                "focus_candidate": {"ticker": "300505", "promotion_readiness_verdict": "validation_queue_ready"},
                "queue_rows": [
                    {"ticker": "300505", "priority_rank": 2, "candidate_tier_focus": "observation_candidate", "recent_tier_verdict": "recent_tier_confirmed", "promotion_readiness_verdict": "validation_queue_ready"}
                ],
            }
        ),
        encoding="utf-8",
    )
    promotion_review_path.write_text(
        json.dumps(
            {
                "focus_ticker": "300505",
                "promotion_review_verdict": "watch_review_ready",
                "promotion_blockers": [],
            }
        ),
        encoding="utf-8",
    )
    promotion_gate_path.write_text(
        json.dumps(
            {
                "focus_ticker": "300505",
                "gate_verdict": "approve_watchlist_promotion",
                "gate_blockers": [],
                "operator_action": "append_focus_to_watchlist",
                "proposed_watchlist_tickers": ["600989", "300505"],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        watchboard,
        "analyze_btst_tplus2_continuation_peer_rollup",
        lambda *_args, **_kwargs: {
            "rollup_verdict": "first_near_cluster_breakthrough",
            "top_candidate": {"ticker": "600989", "tier": "near_cluster_peer"},
            "risk_flags": [{"ticker": "300724", "tier": "observation_candidate", "reason": "negative_or_weak_follow_through", "t_plus_2_close_return_mean": -0.0182}],
        },
    )

    analysis = watchboard.generate_btst_tplus2_continuation_watchboard(
        tmp_path,
        observation_pool_path=observation_pool_path,
        lane_rulepack_path=lane_rulepack_path,
        lane_validation_path=lane_validation_path,
        watchlist_validation_path=watchlist_validation_path,
        validation_queue_path=validation_queue_path,
        promotion_review_path=promotion_review_path,
        promotion_gate_path=promotion_gate_path,
    )

    assert analysis["eligible_tickers"] == ["600988"]
    assert analysis["watchlist_tickers"] == ["600989"]
    assert analysis["rollup_verdict"] == "first_near_cluster_breakthrough"
    assert analysis["top_candidate"]["ticker"] == "600989"
    assert analysis["top_candidate"]["recent_validation_verdict"] == "recent_support_confirmed"
    assert analysis["recent_supporting_window_count"] == 4
    assert analysis["focus_validation_candidate"]["ticker"] == "300505"
    assert analysis["focus_promotion_review"]["promotion_review_verdict"] == "watch_review_ready"
    assert analysis["focus_promotion_gate"]["gate_verdict"] == "approve_watchlist_promotion"
    assert analysis["validation_queue_rows"][0]["ticker"] == "300505"

    markdown = watchboard.render_btst_tplus2_continuation_watchboard_markdown(analysis)
    assert "# BTST T+2 Continuation Watchboard" in markdown
    assert "recent_support_confirmed" in markdown
    assert "300505" in markdown
    assert "approve_watchlist_promotion" in markdown
