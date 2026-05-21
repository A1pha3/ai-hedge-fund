from __future__ import annotations

import json
from pathlib import Path

import scripts.btst_momentum_rollout_recheck_decision as decision


def test_build_rollout_recheck_decision_returns_ready_for_release_review_when_win_rate_and_payoff_improve() -> None:
    payload = decision.build_momentum_rollout_recheck_decision(
        comparison={
            "winner": {"trial_index": 602},
            "winner_vs_active_baseline": {
                "baseline_name": "momentum_optimized",
                "candidate": {"next_close_positive_rate": 0.60, "next_close_payoff_ratio": 2.0, "window_count": 24},
                "baseline": {"next_close_positive_rate": 0.55, "next_close_payoff_ratio": 1.8, "window_count": 24},
                "next_close_positive_rate_delta": 0.05,
                "next_close_payoff_ratio_delta": 0.2,
                "blockers": [],
            },
            "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
            "release_posture": "hold",
            "fail_closed": True,
        }
    )

    assert payload["action"] == "ready_for_release_review"


def test_build_rollout_recheck_decision_falls_back_to_measurement_repair_when_required_deltas_are_missing() -> None:
    payload = decision.build_momentum_rollout_recheck_decision(
        comparison={
            "winner": {"trial_index": 602},
            "winner_vs_active_baseline": {
                "baseline_name": "momentum_optimized",
                "candidate": {"next_close_positive_rate": 0.60, "next_close_payoff_ratio": 2.0, "window_count": 24},
                "baseline": {"next_close_positive_rate": 0.55, "next_close_payoff_ratio": 1.8, "window_count": 24},
                "blockers": [],
            },
            "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
            "release_posture": "hold",
            "fail_closed": True,
        }
    )

    assert payload["action"] == "fallback_measurement_repair"


def test_build_rollout_recheck_decision_returns_retain_hold_when_blockers_present() -> None:
    payload = decision.build_momentum_rollout_recheck_decision(
        comparison={
            "winner": {"trial_index": 602},
            "winner_vs_active_baseline": {
                "baseline_name": "momentum_optimized",
                "candidate": {"next_close_positive_rate": 0.60, "next_close_payoff_ratio": 2.0, "window_count": 24},
                "baseline": {"next_close_positive_rate": 0.55, "next_close_payoff_ratio": 1.8, "window_count": 24},
                "next_close_positive_rate_delta": 0.05,
                "next_close_payoff_ratio_delta": 0.2,
                "blockers": ["sample_size_too_small"],
            },
            "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
            "release_posture": "hold",
            "fail_closed": True,
        }
    )

    assert payload["action"] == "retain_hold"


def test_build_rollout_recheck_decision_clears_deltas_when_falling_back_for_invalid_measurement_evidence() -> None:
    payload = decision.build_momentum_rollout_recheck_decision(
        comparison={
            "winner": {"trial_index": 602},
            "winner_vs_active_baseline": {
                "baseline_name": "momentum_optimized",
                "candidate": {"next_close_positive_rate": 0.60, "next_close_payoff_ratio": 2.0, "window_count": 0},
                "baseline": {"next_close_positive_rate": 0.55, "next_close_payoff_ratio": 1.8, "window_count": 24},
                "next_close_positive_rate_delta": 0.05,
                "next_close_payoff_ratio_delta": 0.2,
                "blockers": [],
            },
            "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
            "release_posture": "hold",
            "fail_closed": True,
        }
    )

    assert payload["action"] == "fallback_measurement_repair"
    assert payload["winner_vs_active_baseline"]["next_close_positive_rate_delta"] is None
    assert payload["winner_vs_active_baseline"]["next_close_payoff_ratio_delta"] is None


def test_main_writes_rollout_recheck_decision_outputs(tmp_path: Path) -> None:
    comparison_json = tmp_path / "comparison.json"
    output_json = tmp_path / "decision.json"
    output_md = tmp_path / "decision.md"

    comparison_json.write_text(
        json.dumps(
            {
                "winner": {"trial_index": 602},
                "winner_vs_active_baseline": {
                    "baseline_name": "momentum_optimized",
                    "candidate": {"next_close_positive_rate": 0.60, "next_close_payoff_ratio": 2.0, "window_count": 24},
                    "baseline": {"next_close_positive_rate": 0.55, "next_close_payoff_ratio": 1.8, "window_count": 24},
                    "next_close_positive_rate_delta": 0.05,
                    "next_close_payoff_ratio_delta": 0.2,
                    "blockers": [],
                },
                "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
                "release_posture": "hold",
                "fail_closed": True,
            }
        ),
        encoding="utf-8",
    )

    result = decision.main(
        [
            "--comparison-json",
            str(comparison_json),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ]
    )

    assert result == 0
    assert output_json.exists()
    assert output_md.exists()
