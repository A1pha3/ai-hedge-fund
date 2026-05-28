from __future__ import annotations

import json
from pathlib import Path

import scripts.analyze_btst_layer_c_rollout_validation as rollout_validation


def test_analyze_btst_layer_c_rollout_validation_reports_governed_shadow_ready(tmp_path: Path) -> None:
    weekly_validation_json = tmp_path / "weekly_validation.json"
    weekly_validation_json.write_text(
        json.dumps(
            {
                "selected_surface_summary": {
                    "surface_metrics": {"hit_rate_15pct": 0.3077},
                },
                "selected_shadow_scenarios": {
                    "layer_c_watchlist_only": {
                        "surface_metrics": {"hit_rate_15pct": 0.3333},
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    shadow_replay_json = tmp_path / "shadow_replay.json"
    shadow_replay_json.write_text(
        json.dumps(
            {
                "baseline": {"aggregate_counts": {"execution_eligible_count": 3, "buy_order_count": 3, "selected_count": 79}},
                "shadow": {"aggregate_counts": {"execution_eligible_count": 0, "buy_order_count": 0, "selected_count": 74}},
                "delta": {
                    "execution_eligibility_lost_by_date": {"20260508": ["688183"], "20260522": ["002222", "300054"]},
                    "buy_orders_removed_by_date": {"20260508": ["688183"], "20260522": ["002222", "300054"]},
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    report = rollout_validation.analyze_btst_layer_c_rollout_validation(
        weekly_validation_json=weekly_validation_json,
        shadow_replay_json=shadow_replay_json,
    )

    assert report["recommendation"]["status"] == "governed_shadow_ready"
    assert report["recommendation"]["primary_lane"] == "layer_c_formal_precision_tightening"
    assert "formal buy" in report["recommendation"]["summary"]
    assert report["replay_summary"]["execution_eligible_delta"] == -3
    assert report["payoff_summary"]["selected_hit_rate_15pct"] == 0.3077
    assert report["payoff_summary"]["shadow_hit_rate_15pct"] == 0.3333


def test_layer_c_rollout_validation_markdown_contains_recommendation() -> None:
    report = {
        "recommendation": {
            "status": "governed_shadow_ready",
            "primary_lane": "layer_c_formal_precision_tightening",
            "summary": "先收 formal buy，再继续扩窗验证。",
        },
        "payoff_summary": {
            "selected_hit_rate_15pct": 0.3077,
            "shadow_hit_rate_15pct": 0.3333,
        },
        "replay_summary": {
            "execution_eligible_delta": -3,
            "buy_order_delta": -3,
        },
    }

    markdown = rollout_validation.render_rollout_validation_markdown(report)

    assert "governed_shadow_ready" in markdown
    assert "layer_c_formal_precision_tightening" in markdown
    assert "execution_eligible_delta" in markdown


def test_analyze_btst_layer_c_rollout_validation_writes_artifacts(tmp_path: Path) -> None:
    weekly_validation_json = tmp_path / "weekly_validation.json"
    weekly_validation_json.write_text(
        json.dumps(
            {
                "weekly_surface_summaries": {
                    "selected": {
                        "max_future_high_return_2_5d_hit_rate_at_15pct": 0.3,
                    }
                },
                "selected_shadow_scenarios": [
                    {
                        "scenario_id": "exclude_payoff_drag_sources",
                        "excluded_candidate_sources": ["layer_c_watchlist"],
                        "surface_summary": {
                            "max_future_high_return_2_5d_hit_rate_at_15pct": 0.35,
                        },
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    shadow_replay_json = tmp_path / "shadow_replay.json"
    shadow_replay_json.write_text(
        json.dumps(
            {
                "baseline": {"aggregate_counts": {"execution_eligible_count": 2, "buy_order_count": 2, "selected_count": 10}},
                "shadow": {"aggregate_counts": {"execution_eligible_count": 0, "buy_order_count": 0, "selected_count": 8}},
                "delta": {},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    output_json_path = tmp_path / "rollout.json"
    output_markdown_path = tmp_path / "rollout.md"

    report = rollout_validation.analyze_btst_layer_c_rollout_validation(
        weekly_validation_json=weekly_validation_json,
        shadow_replay_json=shadow_replay_json,
        output_json_path=output_json_path,
        output_markdown_path=output_markdown_path,
    )

    assert report["recommendation"]["status"] == "governed_shadow_ready"
    assert json.loads(output_json_path.read_text(encoding="utf-8"))["recommendation"]["status"] == "governed_shadow_ready"
    assert "BTST Layer-C Rollout Validation" in output_markdown_path.read_text(encoding="utf-8")
