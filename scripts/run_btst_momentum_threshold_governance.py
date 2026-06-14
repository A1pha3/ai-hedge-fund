from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from scripts.analyze_btst_multi_window_profile_validation import (
    analyze_btst_multi_window_profile_validation,
    render_btst_multi_window_profile_validation_markdown,
)
from scripts.btst_momentum_threshold_rollout_assessment import (
    build_momentum_threshold_rollout_assessment,
)
from scripts.btst_optimized_profile_manifest_helpers import (
    publish_btst_optimized_profile_manifest,
)

PROFILE_NAME = "momentum_tuned_governed_v1"
BASELINE_PROFILE = "momentum_optimized"
PROFILE_OVERRIDES = {
    "select_threshold": 0.38,
    "near_miss_threshold": 0.24,
    "selected_rank_cap_ratio": 0.50,
}
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data" / "reports"
DEFAULT_REPORTS_ROOT = REPO_ROOT / "data" / "reports"
EXPECTED_MARKDOWN_RENDER_EXCEPTIONS = (KeyError, TypeError, ValueError)


def _resolve_subprocess_dotenv_path() -> Path | None:
    local_dotenv_path = REPO_ROOT / ".env"
    if local_dotenv_path.exists():
        return local_dotenv_path
    try:
        git_common_dir = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    if not git_common_dir:
        return None
    common_dir_path = Path(git_common_dir)
    if not common_dir_path.is_absolute():
        common_dir_path = (REPO_ROOT / common_dir_path).resolve()
    if common_dir_path.name != ".git":
        return None
    repo_root_dotenv_path = common_dir_path.parent / ".env"
    return repo_root_dotenv_path if repo_root_dotenv_path.exists() else None


def _build_backtest_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    dotenv_path = _resolve_subprocess_dotenv_path()
    if dotenv_path is None:
        return env
    for key, value in dotenv_values(dotenv_path).items():
        if value is not None:
            env[key] = value
    return env


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _summarize_selected_backtest(profile_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    selected_entries = list((payload.get(profile_name) or {}).get("selected") or [])
    win_rates = [float(entry["win_rate"]) for entry in selected_entries if entry.get("win_rate") is not None]
    payoff_ratios = [float(entry["payoff_ratio"]) for entry in selected_entries if entry.get("payoff_ratio") is not None]
    average_returns = [float(entry["avg_ret"]) for entry in selected_entries if entry.get("avg_ret") is not None]
    return {
        "profile_name": profile_name,
        "selected_day_count": len(selected_entries),
        "win_rate": round(sum(win_rates) / len(win_rates), 4) if win_rates else 0.0,
        "payoff_ratio": round(sum(payoff_ratios) / len(payoff_ratios), 4) if payoff_ratios else 0.0,
        "avg_ret": round(sum(average_returns) / len(average_returns), 4) if average_returns else 0.0,
    }


def run_20day_backtest(*, output_root: str | Path) -> dict[str, Any]:
    resolved_output_root = Path(output_root).expanduser().resolve()
    raw_output_path = resolved_output_root / "btst_20day_backtest_governed_raw.json"
    summary_output_path = resolved_output_root / "btst_20day_backtest_governed_summary.json"
    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "btst_20day_backtest.py"),
            "--profiles",
            PROFILE_NAME,
            "--output-json",
            str(raw_output_path),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        env=_build_backtest_subprocess_env(),
        text=True,
    )
    summary = _summarize_selected_backtest(PROFILE_NAME, json.loads(raw_output_path.read_text(encoding="utf-8")))
    _write_json(summary_output_path, summary)
    return summary


def _resolve_shared_reports_root() -> Path:
    # Try to find the shared repo root using git rev-parse --git-common-dir
    try:
        git_common_dir = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if git_common_dir:
            common_dir_path = Path(git_common_dir)
            if not common_dir_path.is_absolute():
                common_dir_path = (REPO_ROOT / common_dir_path).resolve()
            if common_dir_path.name == ".git":
                repo_root = common_dir_path.parent
                reports_root = repo_root / "data" / "reports"
                if reports_root.exists():
                    return reports_root
    except (FileNotFoundError, subprocess.CalledProcessError, OSError, AttributeError, ValueError):
        pass
    # Fallback to local DEFAULT_REPORTS_ROOT
    return DEFAULT_REPORTS_ROOT

def run_multi_window_validation(*, output_root: str | Path) -> dict[str, Any]:
    resolved_output_root = Path(output_root).expanduser().resolve()
    resolved_output_root.mkdir(parents=True, exist_ok=True)
    output_json_path = resolved_output_root / "btst_multi_window_profile_validation_governed_summary.json"
    output_md_path = resolved_output_root / "btst_multi_window_profile_validation_governed_summary.md"
    reports_root = _resolve_shared_reports_root()
    summary = analyze_btst_multi_window_profile_validation(
        reports_root,
        baseline_profile=BASELINE_PROFILE,
        variant_profile=PROFILE_NAME,
    )
    # Ensure minimal aggregate fields exist so downstream markdown render does not KeyError
    # Tests sometimes provide lightweight fakes that omit aggregate keys; default them here.
    summary.setdefault("reports_root", str(reports_root))
    summary.setdefault("baseline_profile", BASELINE_PROFILE)
    summary.setdefault("variant_profile", PROFILE_NAME)
    for key in (
        "keep_baseline_count",
        "variant_supports_t1_count",
        "variant_improves_t2_only_count",
        "mixed_count",
    ):
        summary.setdefault(key, 0)
    summary.setdefault("recommendation", summary.get("recommendation", "hold"))
    try:
        markdown = render_btst_multi_window_profile_validation_markdown(summary)
    except EXPECTED_MARKDOWN_RENDER_EXCEPTIONS as exc:
        render_error = f"{type(exc).__name__}: {exc}"
        summary["render_error"] = render_error
        fallback_lines = [
            "# BTST Multi-Window Profile Validation",
            "",
            f"- reports_root: {summary.get('reports_root')}",
            f"- report_dir_count: {summary.get('report_dir_count')}",
            f"- report_name_contains: {summary.get('report_name_contains')}",
            f"- render_error: {render_error}",
            "",
        ]
        markdown = "\n".join(fallback_lines)
    output_md_path.write_text(markdown, encoding="utf-8")
    _write_json(output_json_path, summary)
    return summary


def run_pipeline(*, output_root: str | Path) -> dict[str, object]:
    resolved_output_root = Path(output_root).expanduser().resolve()
    resolved_output_root.mkdir(parents=True, exist_ok=True)

    backtest_summary = run_20day_backtest(output_root=resolved_output_root)
    multi_window_validation = run_multi_window_validation(output_root=resolved_output_root)
    assessment = build_momentum_threshold_rollout_assessment(
        backtest_summary=backtest_summary,
        multi_window_validation=multi_window_validation,
    )

    assessment_path = resolved_output_root / "btst_momentum_threshold_rollout_assessment.json"
    _write_json(assessment_path, assessment)
    manifest_result = publish_btst_optimized_profile_manifest(
        manifest_path=REPO_ROOT / "data" / "reports" / "btst_latest_optimized_profile.json",
        rollout_recommendation=str(assessment["action"]),
        profile_name=PROFILE_NAME,
        profile_overrides=PROFILE_OVERRIDES,
        source_path=assessment_path,
        replay_input_paths=[],
    )
    return {
        "backtest_summary": backtest_summary,
        "multi_window_validation": multi_window_validation,
        "assessment": assessment,
        "manifest_result": manifest_result,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run BTST governed momentum-threshold backtest, validation, rollout assessment, and manifest publication.")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT), help="Directory to store governance outputs.")
    args = parser.parse_args(argv)

    result = run_pipeline(output_root=args.output_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
