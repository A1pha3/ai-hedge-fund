from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPORTS_DIR = Path("data/reports")
DEFAULT_STRUCTURAL_WINDOW_REVIEW_PATH = REPORTS_DIR / "p8_structural_conflict_rescue_window_20260330.json"
DEFAULT_RELEASE_REPORT_PATH = REPORTS_DIR / "300724_structural_conflict_shadow_release_20260330_release.json"
DEFAULT_OUTCOME_REPORT_PATH = REPORTS_DIR / "300724_structural_conflict_shadow_release_20260330_outcomes.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "p8_structural_shadow_runbook_300724_20260330.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "p8_structural_shadow_runbook_300724_20260330.md"


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def analyze_btst_structural_shadow_runbook(
    structural_window_review_path: str | Path,
    *,
    release_report_path: str | Path,
    outcome_report_path: str | Path,
    ticker: str = "300724",
) -> dict[str, Any]:
    normalized_ticker = str(ticker).strip()
    structural_window_review = _load_json(structural_window_review_path)
    release_report = _load_json(release_report_path)
    outcome_report = _load_json(outcome_report_path)

    priority_row = next(
        (row for row in list(structural_window_review.get("priority_queue") or []) if str(row.get("ticker") or "") == normalized_ticker),
        {},
    )
    target_case = next(
        (row for row in list(outcome_report.get("target_cases") or []) if str(row.get("ticker") or "") == normalized_ticker),
        {},
    )

    changed_non_target_case_count = int(release_report.get("changed_non_target_case_count") or 0)
    next_high_return_mean = float(outcome_report.get("next_high_return_mean") or 0.0)
    next_close_return_mean = float(outcome_report.get("next_close_return_mean") or 0.0)
    next_close_positive_rate = float(outcome_report.get("next_close_positive_rate") or 0.0)

    if changed_non_target_case_count > 0:
        freeze_verdict = "rollback_cluster_release_contaminated"
    elif next_close_return_mean <= 0.0 or next_close_positive_rate < 0.5:
        freeze_verdict = "hold_single_name_only_quality_negative"
    else:
        freeze_verdict = "shadow_recheck_allowed_single_name_only"

    next_step = (
        f"保持 {normalized_ticker} 为单票 structural shadow 冻结样本；"
        "只有未来新窗口出现新的 structural conflict 高优先级样本，且定向 release 继续保持零 spillover、"
        "同时 close continuation 转正，才允许重开 structural lane 评审。"
    )
    rerun_commands = [
        "python scripts/analyze_structural_conflict_rescue_window.py --report-dir data/reports/paper_trading_window_YYYYMMDD_YYYYMMDD_live_m2_7_dual_target_... --output-json data/reports/p8_structural_conflict_rescue_window_YYYYMMDD.json --output-md data/reports/p8_structural_conflict_rescue_window_YYYYMMDD.md",
        f"python scripts/analyze_targeted_structural_conflict_release.py --report-dir data/reports/paper_trading_window_YYYYMMDD_YYYYMMDD_live_m2_7_dual_target_... --targets YYYY-MM-DD:{normalized_ticker} --profile-overrides-json '{{\"hard_block_bearish_conflicts\":[],\"overhead_conflict_penalty_conflicts\":[],\"near_miss_threshold\":0.42}}' --output-json data/reports/{normalized_ticker}_structural_conflict_shadow_release_YYYYMMDD_release.json --output-md data/reports/{normalized_ticker}_structural_conflict_shadow_release_YYYYMMDD_release.md",
        f"python scripts/analyze_targeted_release_outcomes.py --release-report data/reports/{normalized_ticker}_structural_conflict_shadow_release_YYYYMMDD_release.json --next-high-hit-threshold 0.02 --output-json data/reports/{normalized_ticker}_structural_conflict_shadow_release_YYYYMMDD_outcomes.json --output-md data/reports/{normalized_ticker}_structural_conflict_shadow_release_YYYYMMDD_outcomes.md",
    ]

    recommendation = (
        f"{normalized_ticker} 当前不再是‘是否能 rescue’的问题，而是‘rescue 后是否值得扩散’的问题。"
        " 现有证据表明它虽可单票从 blocked 提升到 near_miss，且不会污染其它样本，"
        "但次日 intraday 与 close continuation 同时转弱，因此 structural lane 现在应进入治理性冻结，"
        "而不是继续把 cluster-wide release 当成主线。"
    )

    return {
        "structural_window_review": str(Path(structural_window_review_path).expanduser().resolve()),
        "release_report": str(Path(release_report_path).expanduser().resolve()),
        "outcome_report": str(Path(outcome_report_path).expanduser().resolve()),
        "ticker": normalized_ticker,
        "lane_status": "structural_shadow_hold_only",
        "freeze_verdict": freeze_verdict,
        "window_blocked_case_count": structural_window_review.get("blocked_case_count"),
        "window_near_miss_rescuable_count": structural_window_review.get("near_miss_rescuable_count"),
        "window_selected_rescuable_count": structural_window_review.get("selected_rescuable_count"),
        "priority_case": priority_row,
        "target_case": target_case,
        "changed_non_target_case_count": changed_non_target_case_count,
        "next_high_return_mean": round(next_high_return_mean, 4),
        "next_close_return_mean": round(next_close_return_mean, 4),
        "next_close_positive_rate": round(next_close_positive_rate, 4),
        "keep_guardrails": [
            "changed_non_target_case_count == 0",
            f"{normalized_ticker} 只保留为单票 structural shadow，不做 cluster-wide structural release",
            "若 next_close_return_mean <= 0 或 next_close_positive_rate < 0.5，则继续冻结，不进入默认升级评审",
        ],
        "reopen_conditions": [
            "未来新窗口出现新的 layer_c_bearish_conflict 高优先级样本，并在 structural_conflict_rescue_window 中进入 priority_queue 前列",
            "新的 targeted structural release 继续保持 changed_non_target_case_count == 0",
            "新的 targeted release outcomes 同时满足 next_high_return_mean > 0 与 next_close_return_mean > 0",
        ],
        "rerun_commands": rerun_commands,
        "next_step": next_step,
        "recommendation": recommendation,
    }


def render_btst_structural_shadow_runbook_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Structural Shadow Runbook")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- ticker: {analysis['ticker']}")
    lines.append(f"- lane_status: {analysis['lane_status']}")
    lines.append(f"- freeze_verdict: {analysis['freeze_verdict']}")
    lines.append(f"- window_blocked_case_count: {analysis['window_blocked_case_count']}")
    lines.append(f"- window_near_miss_rescuable_count: {analysis['window_near_miss_rescuable_count']}")
    lines.append(f"- window_selected_rescuable_count: {analysis['window_selected_rescuable_count']}")
    lines.append(f"- next_high_return_mean: {analysis['next_high_return_mean']}")
    lines.append(f"- next_close_return_mean: {analysis['next_close_return_mean']}")
    lines.append(f"- next_close_positive_rate: {analysis['next_close_positive_rate']}")
    lines.append("")
    lines.append("## Keep Guardrails")
    for item in analysis["keep_guardrails"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Reopen Conditions")
    for item in analysis["reopen_conditions"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Rerun Commands")
    for item in analysis["rerun_commands"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Next Step")
    lines.append(f"- {analysis['next_step']}")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an execution-ready structural shadow hold runbook for the BTST structural conflict lane.")
    parser.add_argument("--structural-window-review", default=str(DEFAULT_STRUCTURAL_WINDOW_REVIEW_PATH))
    parser.add_argument("--release-report", default=str(DEFAULT_RELEASE_REPORT_PATH))
    parser.add_argument("--outcome-report", default=str(DEFAULT_OUTCOME_REPORT_PATH))
    parser.add_argument("--ticker", default="300724")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_structural_shadow_runbook(
        args.structural_window_review,
        release_report_path=args.release_report,
        outcome_report_path=args.outcome_report,
        ticker=args.ticker,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_structural_shadow_runbook_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()