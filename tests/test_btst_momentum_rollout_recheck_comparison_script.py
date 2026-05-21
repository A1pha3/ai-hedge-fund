from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.btst_momentum_rollout_recheck_comparison as comparison


def test_build_rollout_recheck_comparison_extracts_winner_baseline_and_challenger_context() -> None:
    payload = comparison.build_momentum_rollout_recheck_comparison(
        rollout_pack={
            "winner": {"trial_index": 602},
            "challengers": [{"trial_index": 1226}, {"trial_index": 74}],
            "active_baseline": {"profile_name": "momentum_optimized"},
            "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
            "release_posture": "hold",
            "fail_closed": True,
        },
        source_report={
            "results": [
                {"trial_index": 602, "metrics": {"next_close_positive_rate": 0.5377, "next_close_payoff_ratio": 1.9198, "window_count": 24}},
                {"trial_index": 1226, "metrics": {"next_close_positive_rate": 0.5200, "next_close_payoff_ratio": 1.7000, "window_count": 24}},
                {"trial_index": 74, "metrics": {"next_close_positive_rate": 0.5100, "next_close_payoff_ratio": 1.6500, "window_count": 24}},
            ],
            "comparison_summary": {
                "momentum_optimized": {
                    "candidate": {"next_close_positive_rate": 0.5377, "next_close_payoff_ratio": 1.9198, "window_count": 24},
                    "baseline": {"next_close_positive_rate": 0.5440, "next_close_payoff_ratio": 1.7800, "window_count": 24},
                    "next_close_positive_rate_delta": -0.0063,
                    "next_close_payoff_ratio_delta": 0.1398,
                }
            },
            "rollout_recommendation_details": {
                "baseline_verdicts": {"momentum_optimized": {"status": "blocked", "blockers": ["next_close_positive_rate_regressed_vs_momentum_optimized"]}},
            },
        },
    )

    assert payload["winner"]["trial_index"] == 602
    assert payload["winner_vs_active_baseline"] == {
        "baseline_name": "momentum_optimized",
        "candidate": {"next_close_positive_rate": 0.5377, "next_close_payoff_ratio": 1.9198, "window_count": 24},
        "baseline": {"next_close_positive_rate": 0.5440, "next_close_payoff_ratio": 1.7800, "window_count": 24},
        "next_close_positive_rate_delta": -0.0063,
        "next_close_payoff_ratio_delta": 0.1398,
        "blockers": ["next_close_positive_rate_regressed_vs_momentum_optimized"],
    }
    assert payload["challenger_context"][0]["trial_index"] == 1226


def test_build_rollout_recheck_comparison_fails_closed_when_active_baseline_missing_from_summary() -> None:
    with pytest.raises(SystemExit, match="comparison_summary"):
        comparison.build_momentum_rollout_recheck_comparison(
            rollout_pack={"winner": {"trial_index": 602}, "challengers": [], "active_baseline": {"profile_name": "btst_precision_v2"}, "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"], "release_posture": "hold", "fail_closed": True},
            source_report={"results": [{"trial_index": 602, "metrics": {"next_close_positive_rate": 0.5377}}], "comparison_summary": {"momentum_optimized": {}}},
        )


def test_main_writes_rollout_recheck_comparison_outputs(tmp_path: Path) -> None:
    rollout_pack_json = tmp_path / "rollout_pack.json"
    source_json = tmp_path / "source.json"
    output_json = tmp_path / "comparison.json"
    output_md = tmp_path / "comparison.md"

    rollout_pack_json.write_text(json.dumps({"winner": {"trial_index": 602}, "challengers": [], "active_baseline": {"profile_name": "momentum_optimized"}, "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"], "release_posture": "hold", "fail_closed": True}), encoding="utf-8")
    source_json.write_text(json.dumps({"results": [{"trial_index": 602, "metrics": {"next_close_positive_rate": 0.5377, "next_close_payoff_ratio": 1.9198, "window_count": 24}}], "comparison_summary": {"momentum_optimized": {"candidate": {"next_close_positive_rate": 0.5377, "next_close_payoff_ratio": 1.9198, "window_count": 24}, "baseline": {"next_close_positive_rate": 0.5440, "next_close_payoff_ratio": 1.7800, "window_count": 24}, "next_close_positive_rate_delta": -0.0063, "next_close_payoff_ratio_delta": 0.1398}}, "rollout_recommendation_details": {"baseline_verdicts": {"momentum_optimized": {"status": "blocked", "blockers": ["next_close_positive_rate_regressed_vs_momentum_optimized"]}}}}), encoding="utf-8")

    result = comparison.main(
        [
            "--rollout-pack-json",
            str(rollout_pack_json),
            "--source-json",
            str(source_json),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ]
    )

    assert result == 0
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["winner_vs_active_baseline"]["baseline_name"] == "momentum_optimized"
    assert data["winner_vs_active_baseline"]["blockers"] == ["next_close_positive_rate_regressed_vs_momentum_optimized"]
    assert output_md.exists()
