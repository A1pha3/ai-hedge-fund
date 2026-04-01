from __future__ import annotations

import json
from pathlib import Path

from scripts.run_short_trade_boundary_variant_validation import run_short_trade_boundary_variant_validation


def test_run_short_trade_boundary_variant_validation_builds_expected_commands(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    calls: list[dict[str, object]] = []

    class Result:
        def __init__(self, returncode: int = 0):
            self.returncode = returncode
            self.stdout = "ok"
            self.stderr = ""

    def fake_run_command(command, *, cwd: Path, env: dict[str, str]):
        calls.append({"command": list(command), "cwd": cwd, "env": dict(env)})
        if "scripts/run_paper_trading.py" in command:
            output_dir = Path(command[command.index("--output-dir") + 1])
            selection_dir = output_dir / "selection_artifacts" / "2026-03-26"
            selection_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "session_summary.json").write_text(
                json.dumps(
                    {
                        "dual_target_summary": {"short_trade_selected_count": 1},
                        "daily_event_stats": {"executed_trade_days": 3},
                        "artifacts": {"selection_artifact_root": str(output_dir / "selection_artifacts")},
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (output_dir / "daily_events.jsonl").write_text("{}\n", encoding="utf-8")
            (output_dir / "pipeline_timings.jsonl").write_text("{}\n", encoding="utf-8")
            (selection_dir / "selection_snapshot.json").write_text("{}\n", encoding="utf-8")
        return Result(0)

    monkeypatch.setattr("scripts.run_short_trade_boundary_variant_validation._run_command", fake_run_command)

    output_dir = repo_root / "out"
    summary = run_short_trade_boundary_variant_validation(
        repo_root=repo_root,
        start_date="2026-03-23",
        end_date="2026-03-26",
        selection_target="dual_target",
        model_provider="MiniMax",
        model_name="MiniMax-M2.7",
        variant_name="catalyst_floor_zero",
        output_dir=output_dir,
    )

    assert summary["run_exit_code"] == 0
    assert summary["analysis_exit_code"] == 0
    assert len(calls) == 2
    assert calls[0]["env"]["DAILY_PIPELINE_SHORT_TRADE_BOUNDARY_CATALYST_MIN"] == "0.0"
    assert "scripts/run_paper_trading.py" in calls[0]["command"]
    assert "scripts/analyze_short_trade_boundary_filtered_candidates.py" in calls[1]["command"]


def test_run_short_trade_boundary_variant_validation_fails_when_required_artifacts_are_missing(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    calls: list[dict[str, object]] = []

    class Result:
        def __init__(self, returncode: int = 0):
            self.returncode = returncode
            self.stdout = "ok"
            self.stderr = ""

    def fake_run_command(command, *, cwd: Path, env: dict[str, str]):
        calls.append({"command": list(command), "cwd": cwd, "env": dict(env)})
        output_dir = Path(command[command.index("--output-dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "session_summary.json").write_text(
            json.dumps(
                {
                    "dual_target_summary": {"short_trade_selected_count": 1},
                    "daily_event_stats": {"executed_trade_days": 3},
                    "artifacts": {"selection_artifact_root": str(output_dir / "selection_artifacts")},
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        (output_dir / "daily_events.jsonl").write_text("{}\n", encoding="utf-8")
        (output_dir / "pipeline_timings.jsonl").write_text("{}\n", encoding="utf-8")
        return Result(0)

    monkeypatch.setattr("scripts.run_short_trade_boundary_variant_validation._run_command", fake_run_command)

    output_dir = repo_root / "out"
    summary = run_short_trade_boundary_variant_validation(
        repo_root=repo_root,
        start_date="2026-03-23",
        end_date="2026-03-26",
        selection_target="dual_target",
        model_provider="MiniMax",
        model_name="MiniMax-M2.7",
        variant_name="catalyst_floor_zero",
        output_dir=output_dir,
    )

    assert summary["run_exit_code"] == 2
    assert summary["error"] == "required_report_artifacts_missing"
    assert summary["artifact_validation"]["is_complete"] is False
    assert summary["artifact_validation"]["selection_artifact_root_exists"] is False
    assert len(calls) == 1
