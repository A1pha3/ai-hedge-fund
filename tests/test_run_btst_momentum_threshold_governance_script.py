from __future__ import annotations

import json
import subprocess
from pathlib import Path

import scripts.run_btst_momentum_threshold_governance as governance_runner
from scripts.run_btst_momentum_threshold_governance import run_pipeline


def test_summarize_selected_backtest_aggregates_selected_entries() -> None:
    summary = governance_runner._summarize_selected_backtest(
        governance_runner.PROFILE_NAME,
        {
            governance_runner.PROFILE_NAME: {
                "selected": [
                    {"win_rate": 0.4, "payoff_ratio": 1.1, "avg_ret": 0.2},
                    {"win_rate": 0.6, "payoff_ratio": 1.3, "avg_ret": 0.4},
                ]
            }
        },
    )

    assert summary == {
        "profile_name": governance_runner.PROFILE_NAME,
        "selected_day_count": 2,
        "win_rate": 0.5,
        "payoff_ratio": 1.2,
        "avg_ret": 0.3,
    }


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

    # Assert top-level keys
    assert set(result.keys()) == {"backtest_summary", "multi_window_validation", "assessment", "manifest_result"}
    # Assert representative field values
    assert result["assessment"]["action"] == "promote"
    assert result["backtest_summary"]["profile_name"] == "momentum_tuned_governed_v1"
    assert result["multi_window_validation"]["variant_profile"] == "momentum_tuned_governed_v1"
    assert result["manifest_result"]["status"] == "published"
    # Assert manifest_path is canonical
    from scripts.run_btst_momentum_threshold_governance import REPO_ROOT
    expected_manifest_path = REPO_ROOT / "data" / "reports" / "btst_latest_optimized_profile.json"
    # Accept Path or str for published["manifest_path"]
    if isinstance(published["manifest_path"], str):
        assert published["manifest_path"] == str(expected_manifest_path)
    else:
        assert published["manifest_path"] == expected_manifest_path
    # Accept test double manifest_path for manifest_result (since fake_publish returns tmp_path)
    manifest_path_result = result["manifest_result"]["manifest_path"]
    if manifest_path_result == str(expected_manifest_path):
        pass
    else:
        # Accept test double path (tmp_path) if present
        assert manifest_path_result == str(tmp_path / "btst_latest_optimized_profile.json")
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


def test_run_20day_backtest_passes_repo_root_tushare_token_into_subprocess_env(monkeypatch, tmp_path: Path) -> None:
    worktree_root = tmp_path / "worktree"
    worktree_root.mkdir()
    output_root = tmp_path / "outputs"
    main_repo_env = tmp_path / "main-repo.env"
    main_repo_env.write_text("TUSHARE_TOKEN=test-token\n", encoding="utf-8")

    monkeypatch.setattr(governance_runner, "REPO_ROOT", worktree_root)
    monkeypatch.setattr(governance_runner, "_resolve_subprocess_dotenv_path", lambda: main_repo_env, raising=False)
    monkeypatch.setattr(
        governance_runner,
        "_summarize_selected_backtest",
        lambda profile_name, payload: {"profile_name": profile_name, "selected_day_count": 1, "win_rate": 0.5, "payoff_ratio": 1.2, "avg_ret": 0.03},
    )
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)

    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env")
        raw_output_path = output_root / "btst_20day_backtest_governed_raw.json"
        raw_output_path.parent.mkdir(parents=True, exist_ok=True)
        raw_output_path.write_text(
            json.dumps(
                {
                    governance_runner.PROFILE_NAME: {
                        "selected": [
                            {
                                "win_rate": 0.5,
                                "payoff_ratio": 1.2,
                                "avg_ret": 0.03,
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(governance_runner.subprocess, "run", fake_run)

    summary = governance_runner.run_20day_backtest(output_root=output_root)

    assert summary["profile_name"] == governance_runner.PROFILE_NAME
    assert captured["env"]["TUSHARE_TOKEN"] == "test-token"


def test_run_multi_window_validation_uses_shared_repo_reports_root(monkeypatch, tmp_path: Path) -> None:
    worktree_root = tmp_path / "worktree"
    shared_repo_root = tmp_path / "main-repo"
    worktree_reports_root = worktree_root / "data" / "reports"
    shared_reports_root = shared_repo_root / "data" / "reports"
    worktree_reports_root.mkdir(parents=True)
    shared_reports_root.mkdir(parents=True)

    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        assert cmd == ["git", "rev-parse", "--git-common-dir"]
        assert kwargs["cwd"] == worktree_root
        return subprocess.CompletedProcess(cmd, 0, stdout=str(shared_repo_root / ".git"), stderr="")

    def fake_analyze(reports_root, *, baseline_profile, variant_profile):
        captured["reports_root"] = reports_root
        captured["baseline_profile"] = baseline_profile
        captured["variant_profile"] = variant_profile
        return {
            "baseline_profile": baseline_profile,
            "variant_profile": variant_profile,
            "report_dir_count": 1,
            "rows": [{"report_dir": "paper_trading_window_1"}],
            "recommendation": "ok",
            "reports_root": str(reports_root),
            "report_name_contains": "paper_trading_window",
            "variant_select_threshold": 0.38,
            "variant_near_miss_threshold": 0.24,
            "variant_selected_rank_cap_ratio": 0.5,
        }

    monkeypatch.setattr(governance_runner, "REPO_ROOT", worktree_root)
    monkeypatch.setattr(governance_runner, "DEFAULT_REPORTS_ROOT", worktree_reports_root)
    monkeypatch.setattr(governance_runner.subprocess, "run", fake_run)
    monkeypatch.setattr(governance_runner, "analyze_btst_multi_window_profile_validation", fake_analyze)

    governance_runner.run_multi_window_validation(output_root=tmp_path / "outputs")

    assert captured["reports_root"] == shared_reports_root
    assert captured["baseline_profile"] == governance_runner.BASELINE_PROFILE
    assert captured["variant_profile"] == governance_runner.PROFILE_NAME


def test_run_multi_window_validation_records_render_error_for_expected_markdown_failures(monkeypatch, tmp_path: Path) -> None:
    output_root = tmp_path / "outputs"
    summary = {
        "baseline_profile": governance_runner.BASELINE_PROFILE,
        "variant_profile": governance_runner.PROFILE_NAME,
        "report_dir_count": 1,
        "rows": [{"report_dir": "paper_trading_window_1"}],
        "report_name_contains": "paper_trading_window",
    }
    monkeypatch.setattr(governance_runner, "analyze_btst_multi_window_profile_validation", lambda *args, **kwargs: dict(summary))
    monkeypatch.setattr(governance_runner, "render_btst_multi_window_profile_validation_markdown", lambda payload: (_ for _ in ()).throw(KeyError("missing rows")))

    result = governance_runner.run_multi_window_validation(output_root=output_root)

    assert result["render_error"] == "KeyError: 'missing rows'"
    persisted_summary = json.loads((output_root / "btst_multi_window_profile_validation_governed_summary.json").read_text(encoding="utf-8"))
    assert persisted_summary["render_error"] == "KeyError: 'missing rows'"
    fallback_markdown = (output_root / "btst_multi_window_profile_validation_governed_summary.md").read_text(encoding="utf-8")
    assert "render_error: KeyError: 'missing rows'" in fallback_markdown


def test_run_multi_window_validation_propagates_unexpected_markdown_render_failures(monkeypatch, tmp_path: Path) -> None:
    summary = {
        "baseline_profile": governance_runner.BASELINE_PROFILE,
        "variant_profile": governance_runner.PROFILE_NAME,
        "report_dir_count": 1,
        "rows": [{"report_dir": "paper_trading_window_1"}],
        "report_name_contains": "paper_trading_window",
    }
    monkeypatch.setattr(governance_runner, "analyze_btst_multi_window_profile_validation", lambda *args, **kwargs: dict(summary))
    monkeypatch.setattr(governance_runner, "render_btst_multi_window_profile_validation_markdown", lambda payload: (_ for _ in ()).throw(RuntimeError("boom")))

    try:
        governance_runner.run_multi_window_validation(output_root=tmp_path / "outputs")
    except RuntimeError as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("expected RuntimeError from markdown renderer")
