from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.btst_momentum_rollout_recheck_decision as decision


def test_build_rollout_recheck_decision_returns_ready_for_release_review_when_win_rate_and_payoff_improve() -> None:
    payload = decision.build_momentum_rollout_recheck_decision(
        comparison={
            "winner": {"trial_index": 602},
            "winner_vs_active_baseline": {
                "baseline_name": "momentum_optimized",
                "candidate": {"next_close_positive_rate": 0.5377, "next_close_payoff_ratio": 1.9198, "window_count": 24},
                "baseline": {"next_close_positive_rate": 0.5440, "next_close_payoff_ratio": 1.7800, "window_count": 24},
                "next_close_positive_rate_delta": 0.0063,
                "next_close_payoff_ratio_delta": 0.1398,
                "blockers": [],
            },
            "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
            "release_posture": "hold",
            "fail_closed": True,
        }
    )

    assert payload["action"] == "ready_for_release_review"
    assert payload["release_posture"] == "hold"
    assert payload["guardrails"] == ["no_manifest_publication", "no_btst_skill_promotion"]


def test_build_rollout_recheck_decision_falls_back_to_measurement_repair_when_required_deltas_are_missing() -> None:
    payload = decision.build_momentum_rollout_recheck_decision(
        comparison={
            "winner": {"trial_index": 602},
            "winner_vs_active_baseline": {
                "baseline_name": "momentum_optimized",
                "candidate": {"next_close_positive_rate": 0.5377, "next_close_payoff_ratio": 1.9198, "window_count": 24},
                "baseline": {"next_close_positive_rate": 0.5440, "next_close_payoff_ratio": 1.7800, "window_count": 24},
                "blockers": [],
            },
            "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
            "release_posture": "hold",
            "fail_closed": True,
        }
    )

    assert payload["action"] == "fallback_measurement_repair"


def test_build_rollout_recheck_decision_returns_retain_hold_when_win_rate_does_not_improve() -> None:
    payload = decision.build_momentum_rollout_recheck_decision(
        comparison={
            "winner": {"trial_index": 602},
            "winner_vs_active_baseline": {
                "baseline_name": "momentum_optimized",
                "candidate": {"next_close_positive_rate": 0.5377, "next_close_payoff_ratio": 1.9198, "window_count": 24},
                "baseline": {"next_close_positive_rate": 0.5440, "next_close_payoff_ratio": 1.7800, "window_count": 24},
                "next_close_positive_rate_delta": -0.0063,
                "next_close_payoff_ratio_delta": 0.1398,
                "blockers": [],
            },
            "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
            "release_posture": "hold",
            "fail_closed": True,
        }
    )

    assert payload["action"] == "retain_hold"


def test_build_rollout_recheck_decision_returns_retain_hold_when_blockers_present() -> None:
    payload = decision.build_momentum_rollout_recheck_decision(
        comparison={
            "winner": {"trial_index": 602},
            "winner_vs_active_baseline": {
                "baseline_name": "momentum_optimized",
                "candidate": {"next_close_positive_rate": 0.5377, "next_close_payoff_ratio": 1.9198, "window_count": 24},
                "baseline": {"next_close_positive_rate": 0.5440, "next_close_payoff_ratio": 1.7800, "window_count": 24},
                "next_close_positive_rate_delta": 0.0063,
                "next_close_payoff_ratio_delta": 0.1398,
                "blockers": ["sample_size_too_small"],
            },
            "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
            "release_posture": "hold",
            "fail_closed": True,
        }
    )

    assert payload["action"] == "retain_hold"


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
                    "candidate": {"next_close_positive_rate": 0.5377, "next_close_payoff_ratio": 1.9198, "window_count": 24},
                    "baseline": {"next_close_positive_rate": 0.5440, "next_close_payoff_ratio": 1.7800, "window_count": 24},
                    "next_close_positive_rate_delta": 0.0063,
                    "next_close_payoff_ratio_delta": 0.1398,
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
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["action"] == "ready_for_release_review"
    assert output_md.exists()

