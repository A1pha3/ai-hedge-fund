from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def _default_output_dir(start_date: str, end_date: str, variant_name: str) -> Path:
    normalized_variant = variant_name.replace("-", "_")
    return Path("data/reports") / f"paper_trading_window_{start_date.replace('-', '')}_{end_date.replace('-', '')}_live_short_trade_boundary_{normalized_variant}"


def _build_variant_env(variant_name: str) -> dict[str, str]:
    if variant_name == "catalyst_floor_zero":
        return {"DAILY_PIPELINE_SHORT_TRADE_BOUNDARY_CATALYST_MIN": "0.0"}
    raise ValueError(f"Unknown variant_name: {variant_name}")


def _run_command(command: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, check=False)


def _validate_report_artifacts(output_dir: Path) -> dict[str, Any]:
    report_dir = output_dir.expanduser().resolve()
    session_summary_path = report_dir / "session_summary.json"
    daily_events_path = report_dir / "daily_events.jsonl"
    timing_log_path = report_dir / "pipeline_timings.jsonl"
    selection_root = report_dir / "selection_artifacts"
    snapshot_paths = sorted(selection_root.glob("*/selection_snapshot.json")) if selection_root.exists() else []

    missing_paths: list[str] = []
    for candidate in (session_summary_path, daily_events_path, timing_log_path):
        if not candidate.exists():
            missing_paths.append(str(candidate))
    if not selection_root.exists():
        missing_paths.append(str(selection_root))
    elif not snapshot_paths:
        missing_paths.append(str(selection_root / "*/selection_snapshot.json"))

    validation: dict[str, Any] = {
        "report_dir": str(report_dir),
        "session_summary_exists": session_summary_path.exists(),
        "daily_events_exists": daily_events_path.exists(),
        "timing_log_exists": timing_log_path.exists(),
        "selection_artifact_root_exists": selection_root.exists(),
        "selection_snapshot_count": len(snapshot_paths),
        "latest_selection_snapshot": str(snapshot_paths[-1]) if snapshot_paths else None,
        "missing_paths": missing_paths,
        "is_complete": not missing_paths,
    }
    if session_summary_path.exists():
        try:
            session_summary = json.loads(session_summary_path.read_text(encoding="utf-8"))
        except Exception as error:
            validation["session_summary_read_error"] = str(error)
        else:
            validation["summary_dual_target_counts"] = dict(session_summary.get("dual_target_summary") or {})
            validation["summary_daily_event_stats"] = dict(session_summary.get("daily_event_stats") or {})
            validation["summary_artifacts"] = dict(session_summary.get("artifacts") or {})
    return validation


def run_short_trade_boundary_variant_validation(
    *,
    repo_root: Path,
    start_date: str,
    end_date: str,
    selection_target: str,
    model_provider: str | None,
    model_name: str | None,
    variant_name: str,
    output_dir: Path,
) -> dict[str, Any]:
    env = os.environ.copy()
    variant_env = _build_variant_env(variant_name)
    env.update(variant_env)

    run_command = [
        sys.executable,
        "scripts/run_paper_trading.py",
        "--start-date",
        start_date,
        "--end-date",
        end_date,
        "--selection-target",
        selection_target,
        "--output-dir",
        str(output_dir),
    ]
    if model_provider:
        run_command.extend(["--model-provider", model_provider])
    if model_name:
        run_command.extend(["--model-name", model_name])

    run_result = _run_command(run_command, cwd=repo_root, env=env)
    result: dict[str, Any] = {
        "variant_name": variant_name,
        "env": variant_env,
        "run_command": run_command,
        "run_exit_code": run_result.returncode,
        "run_stdout": run_result.stdout,
        "run_stderr": run_result.stderr,
        "output_dir": str(output_dir),
    }
    if run_result.returncode != 0:
        return result

    artifact_validation = _validate_report_artifacts(output_dir)
    result["artifact_validation"] = artifact_validation
    if not artifact_validation.get("is_complete"):
        result["run_exit_code"] = 2
        result["error"] = "required_report_artifacts_missing"
        return result

    coverage_json = output_dir / "short_trade_boundary_filtered_candidates.json"
    coverage_md = output_dir / "short_trade_boundary_filtered_candidates.md"
    analyze_command = [
        sys.executable,
        "scripts/analyze_short_trade_boundary_filtered_candidates.py",
        "--report-dir",
        str(output_dir),
        "--candidate-sources",
        "short_trade_boundary",
        "--output-json",
        str(coverage_json),
        "--output-md",
        str(coverage_md),
    ]
    analyze_result = _run_command(analyze_command, cwd=repo_root, env=env)
    result.update(
        {
            "analysis_command": analyze_command,
            "analysis_exit_code": analyze_result.returncode,
            "analysis_stdout": analyze_result.stdout,
            "analysis_stderr": analyze_result.stderr,
            "analysis_output_json": str(coverage_json),
            "analysis_output_md": str(coverage_md),
        }
    )
    result["artifact_validation"] = _validate_report_artifacts(output_dir)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a reusable short-trade boundary live validation variant and post-process its filtered-candidate report.")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--selection-target", default="dual_target", choices=["research_only", "short_trade_only", "dual_target"])
    parser.add_argument("--model-provider", default=None)
    parser.add_argument("--model-name", default=None)
    parser.add_argument("--variant-name", default="catalyst_floor_zero")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--summary-json", default="")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else (repo_root / _default_output_dir(args.start_date, args.end_date, args.variant_name)).resolve()
    summary = run_short_trade_boundary_variant_validation(
        repo_root=repo_root,
        start_date=args.start_date,
        end_date=args.end_date,
        selection_target=args.selection_target,
        model_provider=args.model_provider,
        model_name=args.model_name,
        variant_name=args.variant_name,
        output_dir=output_dir,
    )
    if args.summary_json:
        summary_path = Path(args.summary_json).expanduser().resolve()
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary.get("run_exit_code") not in (0, None):
        raise SystemExit(int(summary["run_exit_code"]))
    if summary.get("analysis_exit_code") not in (0, None):
        raise SystemExit(int(summary["analysis_exit_code"]))


if __name__ == "__main__":
    main()