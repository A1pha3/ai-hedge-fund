from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts._btst_p1_p2_next_actions import P2_RUNBOOK_JSON_PATH, build_top3_runbook, ensure_inputs
from scripts.analyze_targeted_release_outcomes import analyze_targeted_release_outcomes, render_targeted_release_outcomes_markdown
from scripts.analyze_targeted_short_trade_boundary_release import analyze_targeted_short_trade_boundary_release, render_targeted_short_trade_boundary_release_markdown
from scripts.analyze_targeted_short_trade_near_miss_release import analyze_targeted_short_trade_near_miss_release, render_targeted_short_trade_near_miss_release_markdown
from scripts.analyze_targeted_structural_conflict_release import analyze_targeted_structural_conflict_release, render_targeted_structural_conflict_release_markdown


REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "p2_top3_experiment_execution_summary_20260330.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "p2_top3_experiment_execution_summary_20260330.md"

ACTION_TIER_ORDER = {
    "primary_promote": 0,
    "shadow_keep": 1,
    "structural_shadow_keep": 2,
    "structural_shadow_hold": 3,
    "primary_watch": 4,
    "shadow_rollback": 5,
    "structural_rollback": 6,
    "primary_rollback": 7,
}


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _parse_targets(raw_targets: list[str]) -> set[tuple[str, str]]:
    targets: set[tuple[str, str]] = set()
    for token in raw_targets:
        trade_date, ticker = str(token).split(":", 1)
        targets.add((trade_date, ticker))
    return targets


def _artifact_paths(artifact_stub: str, artifact_suffix: str) -> dict[str, Path]:
    prefix = REPORTS_DIR / f"{artifact_stub}_{artifact_suffix}"
    return {
        "release_json": prefix.with_name(f"{prefix.name}_release.json"),
        "release_md": prefix.with_name(f"{prefix.name}_release.md"),
        "outcome_json": prefix.with_name(f"{prefix.name}_outcomes.json"),
        "outcome_md": prefix.with_name(f"{prefix.name}_outcomes.md"),
    }


def _release_cli_preview(experiment: dict[str, Any], artifact_paths: dict[str, Path]) -> list[str]:
    bundle = dict(experiment.get("execution_bundle") or {})
    mode = str(bundle.get("release_mode") or "")
    targets = ",".join(experiment.get("target_cases") or [])
    base = [
        "./.venv/bin/python",
        str(bundle.get("release_script") or ""),
        "--report-dir",
        str(bundle.get("report_dir") or ""),
        "--targets",
        targets,
    ]
    if mode == "near_miss_promotion":
        base.extend(
            [
                "--select-threshold",
                str(dict(experiment["parameter_change"]["select_threshold"])["to"]),
                "--stale-weight",
                str(dict(bundle.get("default_weights") or {}).get("stale_weight")),
                "--extension-weight",
                str(dict(bundle.get("default_weights") or {}).get("extension_weight")),
            ]
        )
    elif mode == "score_frontier_release":
        base.extend(
            [
                "--near-miss-threshold",
                str(dict(experiment["parameter_change"]["near_miss_threshold"])["to"]),
                "--stale-weight",
                str(dict(bundle.get("default_weights") or {}).get("stale_weight")),
                "--extension-weight",
                str(dict(bundle.get("default_weights") or {}).get("extension_weight")),
            ]
        )
    else:
        base.extend(["--profile-overrides-json", json.dumps(bundle.get("profile_overrides") or {}, ensure_ascii=False, separators=(",", ":"))])
    base.extend(["--output-json", str(artifact_paths["release_json"]), "--output-md", str(artifact_paths["release_md"])])

    outcome = [
        "./.venv/bin/python",
        str(bundle.get("generic_outcome_script") or ""),
        "--release-report",
        str(artifact_paths["release_json"]),
        "--next-high-hit-threshold",
        str(dict(bundle.get("default_weights") or {}).get("next_high_hit_threshold", 0.02)),
        "--output-json",
        str(artifact_paths["outcome_json"]),
        "--output-md",
        str(artifact_paths["outcome_md"]),
    ]
    return [" ".join(base), " ".join(outcome)]


def _run_release(experiment: dict[str, Any], artifact_paths: dict[str, Path]) -> dict[str, Any]:
    bundle = dict(experiment.get("execution_bundle") or {})
    mode = str(bundle.get("release_mode") or "")
    report_dir = str(bundle.get("report_dir") or "")
    targets = _parse_targets(list(experiment.get("target_cases") or []))

    if mode == "near_miss_promotion":
        analysis = analyze_targeted_short_trade_near_miss_release(
            report_dir,
            targets=targets,
            select_threshold=float(dict(experiment["parameter_change"]["select_threshold"])["to"]),
            stale_weight=float(dict(bundle.get("default_weights") or {}).get("stale_weight", 0.12)),
            extension_weight=float(dict(bundle.get("default_weights") or {}).get("extension_weight", 0.08)),
        )
        markdown = render_targeted_short_trade_near_miss_release_markdown(analysis)
    elif mode == "score_frontier_release":
        analysis = analyze_targeted_short_trade_boundary_release(
            report_dir,
            targets=targets,
            near_miss_threshold=float(dict(experiment["parameter_change"]["near_miss_threshold"])["to"]),
            stale_weight=float(dict(bundle.get("default_weights") or {}).get("stale_weight", 0.12)),
            extension_weight=float(dict(bundle.get("default_weights") or {}).get("extension_weight", 0.08)),
        )
        markdown = render_targeted_short_trade_boundary_release_markdown(analysis)
    elif mode == "structural_conflict_release":
        analysis = analyze_targeted_structural_conflict_release(
            report_dir,
            targets=targets,
            profile_overrides=dict(bundle.get("profile_overrides") or {}),
        )
        markdown = render_targeted_structural_conflict_release_markdown(analysis)
    else:
        raise ValueError(f"Unsupported release mode: {mode}")

    artifact_paths["release_json"].write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    artifact_paths["release_md"].write_text(markdown, encoding="utf-8")
    return analysis


def _meets_requirements(outcome: dict[str, Any], requirements: dict[str, Any]) -> bool:
    for key, threshold in requirements.items():
        if key == "min_next_close_return_mean":
            value = outcome.get("next_close_return_mean")
            if value is None or float(value) <= float(threshold):
                return False
        elif key == "min_next_close_positive_rate":
            value = outcome.get("next_close_positive_rate")
            if value is None or float(value) < float(threshold):
                return False
        elif key == "min_next_high_return_mean":
            value = outcome.get("next_high_return_mean")
            if value is None or float(value) < float(threshold):
                return False
    return True


def _evaluate_verdict(experiment: dict[str, Any], outcome: dict[str, Any]) -> tuple[str, str]:
    policy = dict(experiment.get("evaluation_policy") or {})
    target_case_count = int(outcome.get("target_case_count") or 0)
    promoted_target_case_count = int(outcome.get("promoted_target_case_count") or 0)
    changed_non_target_case_count = int(outcome.get("changed_non_target_case_count") or 0)
    promotion_required = bool(policy.get("target_promotion_required"))
    promotion_ok = (not promotion_required) or (target_case_count > 0 and promoted_target_case_count == target_case_count)
    spillover_ok = changed_non_target_case_count <= int(policy.get("max_changed_non_target_case_count", 0))

    if spillover_ok and promotion_ok and _meets_requirements(outcome, dict(policy.get("go_requirements") or {})):
        return "go", str(dict(experiment.get("decision_rules") or {}).get("go") or "")
    if spillover_ok and promotion_ok and _meets_requirements(outcome, dict(policy.get("shadow_only_requirements") or {})):
        return "shadow_only", str(dict(experiment.get("decision_rules") or {}).get("shadow_only") or "")
    return "rollback", str(dict(experiment.get("decision_rules") or {}).get("rollback") or "")


def _derive_action_semantics(experiment: dict[str, Any], verdict: str) -> dict[str, Any]:
    default_mode = str(experiment.get("default_mode") or "")
    if default_mode == "primary_controlled_follow_through":
        if verdict == "go":
            return {
                "action_lane": "primary",
                "action_tier": "primary_promote",
                "action_summary": "作为唯一 primary controlled follow-through 入口继续推进。",
                "primary_eligible": True,
            }
        if verdict == "shadow_only":
            return {
                "action_lane": "primary",
                "action_tier": "primary_watch",
                "action_summary": "继续保留为 primary 候选观察样本，但不得升级为默认入口。",
                "primary_eligible": False,
            }
        return {
            "action_lane": "primary",
            "action_tier": "primary_rollback",
            "action_summary": "回滚该 primary 候选，不再作为默认主实验入口。",
            "primary_eligible": False,
        }
    if default_mode == "secondary_shadow_entry":
        if verdict == "rollback":
            return {
                "action_lane": "shadow",
                "action_tier": "shadow_rollback",
                "action_summary": "移出 shadow queue，不进入默认升级讨论。",
                "primary_eligible": False,
            }
        return {
            "action_lane": "shadow",
            "action_tier": "shadow_keep",
            "action_summary": "继续保留为 shadow entry，不得抢占 primary 位置。",
            "primary_eligible": False,
        }
    if default_mode == "shadow_structural_candidate":
        if verdict == "go":
            return {
                "action_lane": "structural_shadow",
                "action_tier": "structural_shadow_keep",
                "action_summary": "仅保留 targeted structural shadow queue，不进入 cluster-wide 放松。",
                "primary_eligible": False,
            }
        if verdict == "shadow_only":
            return {
                "action_lane": "structural_shadow",
                "action_tier": "structural_shadow_hold",
                "action_summary": "继续单票观察，不做 cluster-wide structural release。",
                "primary_eligible": False,
            }
        return {
            "action_lane": "structural_shadow",
            "action_tier": "structural_rollback",
            "action_summary": "停止该 structural release 方向，不再推进窗口级放松。",
            "primary_eligible": False,
        }
    return {
        "action_lane": "other",
        "action_tier": verdict,
        "action_summary": "保留当前实验结论。",
        "primary_eligible": False,
    }


def render_execution_summary_markdown(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Top 3 Experiment Execution Summary")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- runbook: {summary['runbook']}")
    lines.append(f"- executed_experiment_count: {summary['executed_experiment_count']}")
    lines.append(f"- recommendation: {summary['recommendation']}")
    lines.append("")
    lines.append("## Experiments")
    for row in summary["experiments"]:
        lines.append(
            f"- rank={row['priority_rank']} id={row['experiment_id']} ticker={row['ticker']} verdict={row['verdict']} action_tier={row['action_tier']} promoted={row['promoted_target_case_count']}/{row['target_case_count']} changed_non_target_case_count={row['changed_non_target_case_count']} next_high_return_mean={row['next_high_return_mean']} next_close_return_mean={row['next_close_return_mean']}"
        )
        lines.append(f"  rationale: {row['rationale']}")
        lines.append(f"  action_summary: {row['action_summary']}")
        lines.append(f"  release_report: {row['release_report']}")
        lines.append(f"  outcome_report: {row['outcome_report']}")
    return "\n".join(lines) + "\n"


def run_btst_top3_experiments(runbook_path: str | Path) -> dict[str, Any]:
    ensure_inputs()
    build_top3_runbook()
    runbook = _load_json(runbook_path)
    artifact_suffix = str(runbook.get("generated_on") or "").replace("-", "")

    executed_rows: list[dict[str, Any]] = []
    for experiment in list(runbook.get("top_3_experiments") or []):
        bundle = dict(experiment.get("execution_bundle") or {})
        artifact_paths = _artifact_paths(str(bundle.get("artifact_stub") or experiment["experiment_id"]), artifact_suffix)
        release_analysis = _run_release(experiment, artifact_paths)
        outcome_analysis = analyze_targeted_release_outcomes(
            artifact_paths["release_json"],
            next_high_hit_threshold=float(dict(bundle.get("default_weights") or {}).get("next_high_hit_threshold", 0.02)),
        )
        artifact_paths["outcome_json"].write_text(json.dumps(outcome_analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        artifact_paths["outcome_md"].write_text(render_targeted_release_outcomes_markdown(outcome_analysis), encoding="utf-8")

        verdict, rationale = _evaluate_verdict(experiment, outcome_analysis)
        action_semantics = _derive_action_semantics(experiment, verdict)
        target_cases = list(outcome_analysis.get("target_cases") or [])
        ticker = str(outcome_analysis.get("ticker") or (target_cases[0].get("ticker") if target_cases else ""))
        executed_rows.append(
            {
                "priority_rank": experiment["priority_rank"],
                "experiment_id": experiment["experiment_id"],
                "track": experiment["track"],
            "default_mode": experiment.get("default_mode"),
                "ticker": ticker,
                "target_case_count": outcome_analysis.get("target_case_count"),
                "promoted_target_case_count": outcome_analysis.get("promoted_target_case_count"),
                "changed_non_target_case_count": outcome_analysis.get("changed_non_target_case_count"),
                "next_high_return_mean": outcome_analysis.get("next_high_return_mean"),
                "next_close_return_mean": outcome_analysis.get("next_close_return_mean"),
                "next_close_positive_rate": outcome_analysis.get("next_close_positive_rate"),
                "verdict": verdict,
                "rationale": rationale,
            **action_semantics,
                "release_report": str(artifact_paths["release_json"]),
                "outcome_report": str(artifact_paths["outcome_json"]),
                "reference_release_report": dict(bundle.get("reference_artifacts") or {}).get("release_report"),
                "reference_outcome_report": dict(bundle.get("reference_artifacts") or {}).get("outcome_report"),
                "cli_preview": _release_cli_preview(experiment, artifact_paths),
                "release_analysis": release_analysis,
                "outcome_analysis": outcome_analysis,
            }
        )

    executed_rows.sort(
        key=lambda row: (
            ACTION_TIER_ORDER.get(str(row.get("action_tier") or ""), 99),
            int(row.get("priority_rank") or 99),
        )
    )

    primary_rows = [row for row in executed_rows if row.get("primary_eligible")]
    shadow_rows = [row["experiment_id"] for row in executed_rows if row.get("action_tier") == "shadow_keep"]
    structural_hold_rows = [row["experiment_id"] for row in executed_rows if row.get("action_tier") in {"structural_shadow_keep", "structural_shadow_hold"}]
    if primary_rows:
        recommendation_parts = [f"优先推进 {primary_rows[0]['experiment_id']}。"]
        if shadow_rows:
            recommendation_parts.append(f"{'、'.join(shadow_rows)} 仅保留 shadow queue。")
        if structural_hold_rows:
            recommendation_parts.append(f"{'、'.join(structural_hold_rows)} 继续 structural shadow hold，不做 cluster-wide 放松。")
        recommendation = "".join(recommendation_parts)
    elif executed_rows:
        recommendation = f"当前没有 primary-promote 级实验，优先观察 {executed_rows[0]['experiment_id']}。"
    else:
        recommendation = "当前没有可执行的 Top 3 实验。"

    return {
        "generated_on": runbook.get("generated_on"),
        "runbook": str(Path(runbook_path).expanduser().resolve()),
        "executed_experiment_count": len(executed_rows),
        "recommendation": recommendation,
        "experiments": executed_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute the BTST Top 3 case-based experiments and write a consolidated summary.")
    parser.add_argument("--runbook", default=str(P2_RUNBOOK_JSON_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    summary = run_btst_top3_experiments(args.runbook)
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_execution_summary_markdown(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()