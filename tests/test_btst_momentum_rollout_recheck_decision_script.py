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


def test_build_rollout_recheck_decision_falls_back_to_measurement_repair_when_candidate_and_baseline_are_empty() -> None:
    payload = decision.build_momentum_rollout_recheck_decision(
        comparison={
            "winner": {"trial_index": 602},
            "winner_vs_active_baseline": {
                "baseline_name": "momentum_optimized",
                "candidate": {},
                "baseline": {},
                "next_close_positive_rate_delta": 0.0063,
                "next_close_payoff_ratio_delta": 0.1398,
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


def test_build_rollout_recheck_decision_falls_back_when_candidate_incomplete_despite_positive_deltas() -> None:
    """Regression: incomplete candidate should fail closed even with positive deltas and no blockers."""
    payload = decision.build_momentum_rollout_recheck_decision(
        comparison={
            "winner": {"trial_index": 602},
            "winner_vs_active_baseline": {
                "baseline_name": "momentum_optimized",
                "candidate": {"next_close_positive_rate": 0.5377},  # Missing payoff_ratio and window_count
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

    assert payload["action"] == "fallback_measurement_repair"


def test_build_rollout_recheck_decision_falls_back_when_baseline_incomplete_despite_positive_deltas() -> None:
    """Regression: incomplete baseline should fail closed even with positive deltas and no blockers."""
    payload = decision.build_momentum_rollout_recheck_decision(
        comparison={
            "winner": {"trial_index": 602},
            "winner_vs_active_baseline": {
                "baseline_name": "momentum_optimized",
                "candidate": {"next_close_positive_rate": 0.5377, "next_close_payoff_ratio": 1.9198, "window_count": 24},
                "baseline": {"next_close_positive_rate": 0.5440},  # Missing payoff_ratio and window_count
                "next_close_positive_rate_delta": 0.0063,
                "next_close_payoff_ratio_delta": 0.1398,
                "blockers": [],
            },
            "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
            "release_posture": "hold",
            "fail_closed": True,
        }
    )

    assert payload["action"] == "fallback_measurement_repair"


def test_build_rollout_recheck_decision_falls_back_when_candidate_has_null_values() -> None:
    """Regression: candidate with None values should fail closed even with positive deltas and no blockers."""
    payload = decision.build_momentum_rollout_recheck_decision(
        comparison={
            "winner": {"trial_index": 602},
            "winner_vs_active_baseline": {
                "baseline_name": "momentum_optimized",
                "candidate": {"next_close_positive_rate": None, "next_close_payoff_ratio": 1.9198, "window_count": 24},
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

    assert payload["action"] == "fallback_measurement_repair"


def test_build_rollout_recheck_decision_falls_back_when_baseline_has_null_values() -> None:
    """Regression: baseline with None values should fail closed even with positive deltas and no blockers."""
    payload = decision.build_momentum_rollout_recheck_decision(
        comparison={
            "winner": {"trial_index": 602},
            "winner_vs_active_baseline": {
                "baseline_name": "momentum_optimized",
                "candidate": {"next_close_positive_rate": 0.5377, "next_close_payoff_ratio": 1.9198, "window_count": 24},
                "baseline": {"next_close_positive_rate": 0.5440, "next_close_payoff_ratio": None, "window_count": 24},
                "next_close_positive_rate_delta": 0.0063,
                "next_close_payoff_ratio_delta": 0.1398,
                "blockers": [],
            },
            "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
            "release_posture": "hold",
            "fail_closed": True,
        }
    )

    assert payload["action"] == "fallback_measurement_repair"


def test_build_rollout_recheck_decision_falls_back_when_candidate_has_zero_window_count() -> None:
    """Regression: candidate with zero window_count should fail closed even with positive deltas and no blockers."""
    payload = decision.build_momentum_rollout_recheck_decision(
        comparison={
            "winner": {"trial_index": 602},
            "winner_vs_active_baseline": {
                "baseline_name": "momentum_optimized",
                "candidate": {"next_close_positive_rate": 0.5377, "next_close_payoff_ratio": 1.9198, "window_count": 0},
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

    assert payload["action"] == "fallback_measurement_repair"


def test_build_rollout_recheck_decision_falls_back_when_measurement_values_are_malformed() -> None:
    """Regression: malformed non-None measurement values must fail closed."""
    payload = decision.build_momentum_rollout_recheck_decision(
        comparison={
            "winner": {"trial_index": 602},
            "winner_vs_active_baseline": {
                "baseline_name": "momentum_optimized",
                "candidate": {"next_close_positive_rate": "invalid", "next_close_payoff_ratio": False, "window_count": 24},
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

    assert payload["action"] == "fallback_measurement_repair"


def test_build_rollout_recheck_decision_falls_back_when_measurement_values_are_negative() -> None:
    """Regression: negative measurement values must fail closed."""
    payload = decision.build_momentum_rollout_recheck_decision(
        comparison={
            "winner": {"trial_index": 602},
            "winner_vs_active_baseline": {
                "baseline_name": "momentum_optimized",
                "candidate": {"next_close_positive_rate": -0.5377, "next_close_payoff_ratio": -1.9198, "window_count": 24},
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

    assert payload["action"] == "fallback_measurement_repair"



def test_build_rollout_recheck_decision_falls_back_when_candidate_contains_nan_values() -> None:
    """Regression: NaN measurement values must fail closed."""
    payload = decision.build_momentum_rollout_recheck_decision(
        comparison={
            "winner": {"trial_index": 602},
            "winner_vs_active_baseline": {
                "baseline_name": "momentum_optimized",
                "candidate": {"next_close_positive_rate": float("nan"), "next_close_payoff_ratio": 1.9198, "window_count": 24},
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

    assert payload["action"] == "fallback_measurement_repair"


def test_build_rollout_recheck_decision_falls_back_when_deltas_contain_infinity_values() -> None:
    """Regression: infinite delta values must fail closed."""
    payload = decision.build_momentum_rollout_recheck_decision(
        comparison={
            "winner": {"trial_index": 602},
            "winner_vs_active_baseline": {
                "baseline_name": "momentum_optimized",
                "candidate": {"next_close_positive_rate": 0.5377, "next_close_payoff_ratio": 1.9198, "window_count": 24},
                "baseline": {"next_close_positive_rate": 0.5440, "next_close_payoff_ratio": 1.7800, "window_count": 24},
                "next_close_positive_rate_delta": float("inf"),
                "next_close_payoff_ratio_delta": 0.1398,
                "blockers": [],
            },
            "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
            "release_posture": "hold",
            "fail_closed": True,
        }
    )

    assert payload["action"] == "fallback_measurement_repair"


def test_build_rollout_recheck_decision_falls_back_when_both_deltas_are_positive_infinity() -> None:
    """Regression: both deltas being positive infinity should fail closed, not produce ready_for_release_review."""
    payload = decision.build_momentum_rollout_recheck_decision(
        comparison={
            "winner": {"trial_index": 602},
            "winner_vs_active_baseline": {
                "baseline_name": "momentum_optimized",
                "candidate": {"next_close_positive_rate": 0.5377, "next_close_payoff_ratio": 1.9198, "window_count": 24},
                "baseline": {"next_close_positive_rate": 0.5440, "next_close_payoff_ratio": 1.7800, "window_count": 24},
                "next_close_positive_rate_delta": float("inf"),
                "next_close_payoff_ratio_delta": float("inf"),
                "blockers": [],
            },
            "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
            "release_posture": "hold",
            "fail_closed": True,
        }
    )

    assert payload["action"] == "fallback_measurement_repair"


def test_build_rollout_recheck_decision_falls_back_when_deltas_contain_nan_values() -> None:
    """Regression: NaN delta values must fail closed."""
    payload = decision.build_momentum_rollout_recheck_decision(
        comparison={
            "winner": {"trial_index": 602},
            "winner_vs_active_baseline": {
                "baseline_name": "momentum_optimized",
                "candidate": {"next_close_positive_rate": 0.5377, "next_close_payoff_ratio": 1.9198, "window_count": 24},
                "baseline": {"next_close_positive_rate": 0.5440, "next_close_payoff_ratio": 1.7800, "window_count": 24},
                "next_close_positive_rate_delta": float("nan"),
                "next_close_payoff_ratio_delta": 0.1398,
                "blockers": [],
            },
            "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
            "release_posture": "hold",
            "fail_closed": True,
        }
    )

    assert payload["action"] == "fallback_measurement_repair"


def test_build_rollout_recheck_decision_produces_valid_json_when_candidate_contains_infinity() -> None:
    """Regression: non-finite measurement values must not appear in JSON output."""
    payload = decision.build_momentum_rollout_recheck_decision(
        comparison={
            "winner": {"trial_index": 602},
            "winner_vs_active_baseline": {
                "baseline_name": "momentum_optimized",
                "candidate": {"next_close_positive_rate": float("inf"), "next_close_payoff_ratio": 1.9198, "window_count": 24},
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

    assert payload["action"] == "fallback_measurement_repair"
    # The payload must be serializable to valid JSON (no Infinity/NaN)
    json_str = json.dumps(payload, ensure_ascii=False)
    assert "Infinity" not in json_str
    assert "NaN" not in json_str


def test_build_rollout_recheck_decision_produces_valid_json_when_baseline_contains_nan() -> None:
    """Regression: non-finite measurement values must not appear in JSON output."""
    payload = decision.build_momentum_rollout_recheck_decision(
        comparison={
            "winner": {"trial_index": 602},
            "winner_vs_active_baseline": {
                "baseline_name": "momentum_optimized",
                "candidate": {"next_close_positive_rate": 0.5377, "next_close_payoff_ratio": 1.9198, "window_count": 24},
                "baseline": {"next_close_positive_rate": float("nan"), "next_close_payoff_ratio": 1.7800, "window_count": 24},
                "next_close_positive_rate_delta": 0.0063,
                "next_close_payoff_ratio_delta": 0.1398,
                "blockers": [],
            },
            "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
            "release_posture": "hold",
            "fail_closed": True,
        }
    )

    assert payload["action"] == "fallback_measurement_repair"
    # The payload must be serializable to valid JSON (no Infinity/NaN)
    json_str = json.dumps(payload, ensure_ascii=False)
    assert "Infinity" not in json_str
    assert "NaN" not in json_str


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
