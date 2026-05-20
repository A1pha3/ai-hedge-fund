from __future__ import annotations

from pathlib import Path

from scripts.run_btst_momentum_threshold_governance import run_pipeline


def test_run_pipeline_publishes_manifest_only_when_assessment_promotes(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "scripts.run_btst_momentum_threshold_governance.run_20day_backtest",
        lambda **_: {"profile_name": "momentum_tuned_governed_v1", "win_rate": 0.48, "payoff_ratio": 1.39},
    )
    monkeypatch.setattr(
        "scripts.run_btst_momentum_threshold_governance.run_multi_window_validation",
        lambda **_: {
            "baseline_profile": "momentum_optimized",
            "variant_profile": "momentum_tuned_governed_v1",
            "keep_baseline_count": 0,
            "variant_supports_t1_count": 2,
            "mixed_count": 0,
        },
    )
    monkeypatch.setattr(
        "scripts.run_btst_momentum_threshold_governance.build_momentum_threshold_rollout_assessment",
        lambda **_: {"action": "promote", "blockers": [], "candidate_profile": "momentum_tuned_governed_v1"},
    )

    published: dict[str, object] = {}

    def fake_publish(**kwargs):
        published.update(kwargs)
        return {"status": "published", "manifest_path": str(tmp_path / "btst_latest_optimized_profile.json")}

    monkeypatch.setattr("scripts.run_btst_momentum_threshold_governance.publish_btst_optimized_profile_manifest", fake_publish)

    result = run_pipeline(output_root=tmp_path)

    assert result["assessment"]["action"] == "promote"
    assert published["profile_name"] == "momentum_tuned_governed_v1"


def test_run_pipeline_passes_hold_assessment_into_manifest_publication(monkeypatch, tmp_path: Path) -> None:
    output_root = tmp_path / "nested" / "outputs"
    monkeypatch.setattr(
        "scripts.run_btst_momentum_threshold_governance.run_20day_backtest",
        lambda **_: {"profile_name": "momentum_tuned_governed_v1", "win_rate": 0.46, "payoff_ratio": 1.35},
    )
    monkeypatch.setattr(
        "scripts.run_btst_momentum_threshold_governance.run_multi_window_validation",
        lambda **_: {
            "baseline_profile": "momentum_optimized",
            "variant_profile": "momentum_tuned_governed_v1",
            "keep_baseline_count": 1,
            "variant_supports_t1_count": 0,
            "mixed_count": 1,
        },
    )
    monkeypatch.setattr(
        "scripts.run_btst_momentum_threshold_governance.build_momentum_threshold_rollout_assessment",
        lambda **_: {
            "action": "hold",
            "blockers": ["window_validation_keeps_baseline"],
            "candidate_profile": "momentum_tuned_governed_v1",
        },
    )

    published: dict[str, object] = {}

    def fake_publish(**kwargs):
        published.update(kwargs)
        return {"status": "skipped", "reason": "rollout_recommendation_hold"}

    monkeypatch.setattr("scripts.run_btst_momentum_threshold_governance.publish_btst_optimized_profile_manifest", fake_publish)

    result = run_pipeline(output_root=output_root)

    assert output_root.exists()
    assert result["manifest_result"] == {"status": "skipped", "reason": "rollout_recommendation_hold"}
    assert published["rollout_recommendation"] == "hold"
    assert published["source_path"] == output_root / "btst_momentum_threshold_rollout_assessment.json"
    assert published["profile_overrides"] == {
        "select_threshold": 0.38,
        "near_miss_threshold": 0.24,
        "selected_rank_cap_ratio": 0.50,
    }
