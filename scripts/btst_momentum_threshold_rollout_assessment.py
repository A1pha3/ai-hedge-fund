from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROUND82_PAYOFF_RATIO_REFERENCE = 1.39
ROUND82_WIN_RATE_REFERENCE = 0.48


def build_momentum_threshold_rollout_assessment(backtest_summary: dict[str, Any], multi_window_validation: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []

    # Fail closed if no validation windows
    report_dir_count = int(multi_window_validation.get("report_dir_count", 0) or 0)
    rows = multi_window_validation.get("rows", [])
    if report_dir_count == 0 or not rows:
        blockers.append("multi_window_validation_missing")
    if int(multi_window_validation.get("keep_baseline_count", 0) or 0) > 0:
        blockers.append("window_validation_keeps_baseline")
    if float(backtest_summary.get("payoff_ratio", 0.0) or 0.0) < ROUND82_PAYOFF_RATIO_REFERENCE:
        blockers.append("backtest_payoff_below_round82_reference")
    if float(backtest_summary.get("win_rate", 0.0) or 0.0) < ROUND82_WIN_RATE_REFERENCE:
        blockers.append("backtest_win_rate_below_round82_reference")

    return {
        "candidate_profile": backtest_summary.get("profile_name") or multi_window_validation.get("variant_profile"),
        "baseline_profile": multi_window_validation.get("baseline_profile"),
        "action": "promote" if not blockers else "hold",
        "blockers": blockers,
        "backtest_summary": backtest_summary,
        "multi_window_validation": multi_window_validation,
    }


def _format_metric(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _render_markdown(assessment: dict[str, Any]) -> str:
    lines = [
        "# Momentum Threshold Rollout Assessment",
        "",
        f"Recommendation: **{assessment.get('action', 'hold')}**",
        "",
        f"- candidate_profile: `{assessment.get('candidate_profile')}`",
        f"- baseline_profile: `{assessment.get('baseline_profile')}`",
        "",
        "## Blockers",
        "",
    ]

    blockers = list(assessment.get("blockers") or [])
    if blockers:
        for blocker in blockers:
            lines.append(f"- `{blocker}`")
    else:
        lines.append("- none")

    lines.extend(["", "## Backtest Summary", ""])
    for key, value in (assessment.get("backtest_summary") or {}).items():
        lines.append(f"- {key}: {_format_metric(value)}")

    lines.extend(["", "## Multi-window Validation", ""])
    for key, value in (assessment.get("multi_window_validation") or {}).items():
        if key == "rows":
            lines.append(f"- rows: {len(value or [])}")
            continue
        lines.append(f"- {key}: {_format_metric(value)}")

    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assess whether the governed momentum-threshold candidate is ready for rollout.")
    parser.add_argument("--backtest-json", required=True, help="Path to the governed candidate backtest summary JSON")
    parser.add_argument("--multi-window-json", required=True, help="Path to the multi-window validation JSON")
    parser.add_argument("--output-json", required=True, help="Path to write the rollout assessment JSON")
    parser.add_argument("--output-md", required=True, help="Path to write the rollout assessment Markdown")
    args = parser.parse_args(argv)

    backtest_json_path = Path(args.backtest_json).expanduser().resolve()
    multi_window_json_path = Path(args.multi_window_json).expanduser().resolve()
    output_json_path = Path(args.output_json).expanduser().resolve()
    output_md_path = Path(args.output_md).expanduser().resolve()

    backtest_summary = json.loads(backtest_json_path.read_text(encoding="utf-8"))
    multi_window_validation = json.loads(multi_window_json_path.read_text(encoding="utf-8"))
    assessment = build_momentum_threshold_rollout_assessment(
        backtest_summary=backtest_summary,
        multi_window_validation=multi_window_validation,
    )

    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_md_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(json.dumps(assessment, ensure_ascii=False, indent=2), encoding="utf-8")
    output_md_path.write_text(_render_markdown(assessment), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
