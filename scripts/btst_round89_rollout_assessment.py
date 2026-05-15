from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.btst_round89_rollout_helpers import build_round89_rollout_assessment


def _format_metric(value: float | int | None) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, int):
        return str(value)
    return f"{value:.4f}"


def _render_markdown(assessment: dict) -> str:
    candidate_profile = str(assessment.get("candidate_profile") or "trend_corrected_v1")
    surface_name = str(assessment.get("surface_name") or "selected")
    surface_summaries = assessment.get("surface_summaries") or {}
    comparison_summary = assessment.get("comparison_summary") or {}
    candidate_summary = ((surface_summaries.get(candidate_profile) or {}).get(surface_name) or {})
    blockers = list(assessment.get("blockers") or [])

    lines = [
        "# Round 89 Rollout Assessment",
        "",
        f"Round 89 Rollout Recommendation: **{assessment.get('action', 'hold')}**",
        "",
        f"- candidate_profile: `{candidate_profile}`",
        f"- surface_name: `{surface_name}`",
        "",
        "## Candidate Surface Summary",
        "",
    ]
    for metric, value in candidate_summary.items():
        lines.append(f"- {metric}: {_format_metric(value)}")

    lines.extend(["", "## Blockers", ""])
    if blockers:
        for blocker in blockers:
            lines.append(f"- `{blocker}`")
    else:
        lines.append("- none")

    lines.extend(["", "## Baseline Comparison", ""])
    for baseline_name, baseline_summary in comparison_summary.items():
        lines.append(f"### vs `{baseline_name}`")
        lines.append("")
        for metric, value in baseline_summary.items():
            lines.append(f"- {metric}: {_format_metric(value)}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assess whether Round 89 trend-corrected results are ready for rollout.")
    parser.add_argument("--input-json", required=True, help="Path to btst_round89_reversal_fix_comparison.json")
    parser.add_argument("--output-json", required=True, help="Path to write the rollout assessment JSON")
    parser.add_argument("--output-md", required=True, help="Path to write the rollout assessment Markdown")
    parser.add_argument("--candidate-profile", default="trend_corrected_v1", help="Candidate profile to assess")
    parser.add_argument("--surface-name", default="selected", help="Surface to use for rollout guardrails")
    parser.add_argument("--baseline-profile", action="append", dest="baseline_profiles", help="Baseline profiles to compare against (repeatable)")
    args = parser.parse_args(argv)

    input_path = Path(args.input_json).expanduser().resolve()
    output_json_path = Path(args.output_json).expanduser().resolve()
    output_md_path = Path(args.output_md).expanduser().resolve()

    payload = json.loads(input_path.read_text(encoding="utf-8"))
    baseline_profiles = tuple(args.baseline_profiles or ("ic_v5", "momentum_optimized"))
    assessment = build_round89_rollout_assessment(
        payload,
        candidate_profile=args.candidate_profile,
        baseline_profiles=baseline_profiles,
        surface_name=args.surface_name,
    )

    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_md_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(json.dumps(assessment, ensure_ascii=False, indent=2), encoding="utf-8")
    output_md_path.write_text(_render_markdown(assessment), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
