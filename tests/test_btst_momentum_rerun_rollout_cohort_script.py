import json
from pathlib import Path

import pytest

import scripts.btst_momentum_rerun_rollout_cohort as cohort


def test_build_rerun_cohort_keeps_winner_first_and_caps_challengers() -> None:
    payload = cohort.build_momentum_rerun_rollout_cohort(
        shortlist={
            "best_candidate": {"trial_index": 602, "params": {"select_threshold": 0.46}, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
            "candidates": [
                {"trial_index": 602, "params": {"select_threshold": 0.46}, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
                {"trial_index": 1226, "params": {"select_threshold": 0.46}, "cross_window_blocker_count": 1, "risk_blocker_count": 1},
                {"trial_index": 74, "params": {"select_threshold": 0.46}, "cross_window_blocker_count": 2, "risk_blocker_count": 1},
                {"trial_index": 361, "params": {"select_threshold": 0.46}, "cross_window_blocker_count": 2, "risk_blocker_count": 1},
                {"trial_index": 938, "params": {"select_threshold": 0.46}, "cross_window_blocker_count": 2, "risk_blocker_count": 1},
            ],
        },
        decision={"action": "rerun_rollout_check", "best_candidate": {"trial_index": 602}},
    )

    assert payload["winner"]["trial_index"] == 602
    assert [row["trial_index"] for row in payload["challengers"]] == [1226, 74, 361]
    assert payload["challenger_count"] == 3


def test_build_rerun_cohort_fails_closed_when_decision_does_not_target_shortlist_winner() -> None:
    with pytest.raises(SystemExit, match="decision winner"):
        cohort.build_momentum_rerun_rollout_cohort(
            shortlist={"best_candidate": {"trial_index": 602}, "candidates": [{"trial_index": 602}]},
            decision={"action": "rerun_rollout_check", "best_candidate": {"trial_index": 700}},
        )


def test_main_writes_rerun_cohort_outputs(tmp_path: Path) -> None:
    shortlist_json = tmp_path / "shortlist.json"
    decision_json = tmp_path / "decision.json"
    output_json = tmp_path / "cohort.json"
    output_md = tmp_path / "cohort.md"
    shortlist_json.write_text(
        json.dumps(
            {
                "best_candidate": {"trial_index": 602, "params": {"select_threshold": 0.46}, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
                "candidates": [
                    {"trial_index": 602, "params": {"select_threshold": 0.46}, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
                    {"trial_index": 1226, "params": {"select_threshold": 0.46}, "cross_window_blocker_count": 1, "risk_blocker_count": 1},
                ],
            }
        ),
        encoding="utf-8",
    )
    decision_json.write_text(json.dumps({"action": "rerun_rollout_check", "best_candidate": {"trial_index": 602}}), encoding="utf-8")

    result = cohort.main(
        [
            "--shortlist-json",
            str(shortlist_json),
            "--decision-json",
            str(decision_json),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ]
    )

    assert result == 0
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["winner"]["trial_index"] == 602
    assert output_md.exists()


def test_build_rerun_cohort_does_not_emit_undocumented_action_field() -> None:
    payload = cohort.build_momentum_rerun_rollout_cohort(
        shortlist={
            "best_candidate": {"trial_index": 602, "params": {"select_threshold": 0.46}, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
            "candidates": [{"trial_index": 602, "params": {"select_threshold": 0.46}, "cross_window_blocker_count": 0, "risk_blocker_count": 0}],
        },
        decision={"action": "rerun_rollout_check", "best_candidate": {"trial_index": 602}},
    )

    assert "action" not in payload


def test_build_rerun_cohort_fails_closed_when_shortlist_candidates_repeat_trial_index() -> None:
    with pytest.raises(SystemExit, match="duplicate trial_index"):
        cohort.build_momentum_rerun_rollout_cohort(
            shortlist={
                "best_candidate": {"trial_index": 602, "params": {"select_threshold": 0.46}, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
                "candidates": [
                    {"trial_index": 602, "params": {"select_threshold": 0.46}, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
                    {"trial_index": 1226, "params": {"select_threshold": 0.46}, "cross_window_blocker_count": 1, "risk_blocker_count": 1},
                    {"trial_index": 602, "params": {"select_threshold": 0.46}, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
                ],
            },
            decision={"action": "rerun_rollout_check", "best_candidate": {"trial_index": 602}},
        )
