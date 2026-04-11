from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPORTS_DIR = Path("data/reports")
DEFAULT_SHADOW_LANE_PRIORITY_PATH = REPORTS_DIR / "p4_shadow_lane_priority_board_20260401.json"
DEFAULT_RECURRING_PAIR_COMPARISON_PATH = REPORTS_DIR / "recurring_frontier_release_pair_comparison_600821_vs_300113_catalyst_floor_zero_refresh_20260401.json"
DEFAULT_CANDIDATE_REPORT_PATH = REPORTS_DIR / "multi_window_short_trade_role_candidates_20260401.json"
DEFAULT_RECURRING_TRANSITION_REPORT_PATH = REPORTS_DIR / "recurring_frontier_transition_candidates_all_windows_20260401.json"
DEFAULT_RECURRING_CLOSE_BUNDLE_PATH = REPORTS_DIR / "btst_recurring_shadow_close_bundle_300113_20260401.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "p6_recurring_shadow_runbook_20260401.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "p6_recurring_shadow_runbook_20260401.md"
TARGET_DISTINCT_WINDOW_COUNT = 2


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _safe_load_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return {}
    return json.loads(resolved.read_text(encoding="utf-8"))


def _find_ticker_row(report: dict[str, Any], ticker: str) -> dict[str, Any]:
    normalized_ticker = str(ticker or "").strip()
    for row in list(report.get("candidates") or []):
        if str(row.get("ticker") or "") == normalized_ticker:
            return dict(row)
    return {}


def _build_recurring_close_bundle_command(close_candidate_ticker: str, intraday_control_ticker: str) -> str:
    return (
        "python scripts/run_btst_recurring_shadow_close_bundle.py "
        "--report-dir data/reports/paper_trading_window_<window>_btst_catalyst_floor_zero_refresh "
        "--recurring-frontier-report data/reports/short_trade_boundary_recurring_frontier_cases_catalyst_floor_zero_refresh_<date>.json "
        f"--outcome-report data/reports/pre_layer_short_trade_outcomes_{intraday_control_ticker}_{close_candidate_ticker}_catalyst_floor_zero_refresh_<date>.json "
        f"--close-candidate-ticker {close_candidate_ticker} "
        f"--intraday-control-ticker {intraday_control_ticker} "
        f"--intraday-control-outcomes-report data/reports/recurring_frontier_ticker_release_outcomes_{intraday_control_ticker}_catalyst_floor_zero_refresh_<date>.json "
        f"--close-release-json data/reports/recurring_frontier_ticker_release_{close_candidate_ticker}_catalyst_floor_zero_refresh_<date>.json "
        f"--close-release-md data/reports/recurring_frontier_ticker_release_{close_candidate_ticker}_catalyst_floor_zero_refresh_<date>.md "
        f"--close-outcomes-json data/reports/recurring_frontier_ticker_release_outcomes_{close_candidate_ticker}_catalyst_floor_zero_refresh_<date>.json "
        f"--close-outcomes-md data/reports/recurring_frontier_ticker_release_outcomes_{close_candidate_ticker}_catalyst_floor_zero_refresh_<date>.md "
        f"--pair-json data/reports/recurring_frontier_release_pair_comparison_{intraday_control_ticker}_vs_{close_candidate_ticker}_catalyst_floor_zero_refresh_<date>.json "
        f"--pair-md data/reports/recurring_frontier_release_pair_comparison_{intraday_control_ticker}_vs_{close_candidate_ticker}_catalyst_floor_zero_refresh_<date>.md "
        f"--summary-json data/reports/btst_recurring_shadow_close_bundle_{close_candidate_ticker}_<date>.json "
        f"--summary-md data/reports/btst_recurring_shadow_close_bundle_{close_candidate_ticker}_<date>.md"
    )


def _build_rerun_commands(close_candidate_ticker: str, intraday_control_ticker: str) -> list[str]:
    return [
        "python scripts/analyze_multi_window_short_trade_role_candidates.py --report-root-dirs data/reports --report-name-contains paper_trading_window --min-short-trade-trade-dates 2 --output-json data/reports/multi_window_short_trade_role_candidates_YYYYMMDD.json --output-md data/reports/multi_window_short_trade_role_candidates_YYYYMMDD.md",
        "python scripts/analyze_recurring_frontier_transition_candidates.py --recurring-frontier-report data/reports/short_trade_boundary_recurring_frontier_cases_catalyst_floor_zero_YYYYMMDD.json --role-history-report-root-dirs data/reports --report-name-contains paper_trading_window --output-json data/reports/recurring_frontier_transition_candidates_all_windows_YYYYMMDD.json --output-md data/reports/recurring_frontier_transition_candidates_all_windows_YYYYMMDD.md",
        _build_recurring_close_bundle_command(close_candidate_ticker, intraday_control_ticker),
        f"python scripts/analyze_btst_recurring_shadow_runbook.py --candidate-report data/reports/multi_window_short_trade_role_candidates_YYYYMMDD.json --recurring-transition-report data/reports/recurring_frontier_transition_candidates_all_windows_YYYYMMDD.json --recurring-close-bundle data/reports/btst_recurring_shadow_close_bundle_{close_candidate_ticker}_YYYYMMDD.json --output-json data/reports/p6_recurring_shadow_runbook_YYYYMMDD.json --output-md data/reports/p6_recurring_shadow_runbook_YYYYMMDD.md",
        f"python scripts/analyze_btst_rollout_governance_board.py --recurring-shadow-runbook data/reports/p6_recurring_shadow_runbook_YYYYMMDD.json --recurring-close-bundle data/reports/btst_recurring_shadow_close_bundle_{close_candidate_ticker}_YYYYMMDD.json --output-json data/reports/p5_btst_rollout_governance_board_YYYYMMDD.json --output-md data/reports/p5_btst_rollout_governance_board_YYYYMMDD.md",
    ]


def _build_validation_track(
    base_row: dict[str, Any],
    *,
    candidate_report: dict[str, Any],
    transition_report: dict[str, Any],
    objective: str,
    keep_guardrails: list[str],
    pending_lane_status: str,
) -> dict[str, Any]:
    ticker = str(base_row.get("ticker") or "").strip()
    candidate_row = _find_ticker_row(candidate_report, ticker)
    transition_row = _find_ticker_row(transition_report, ticker)
    distinct_window_count = int(candidate_row.get("distinct_window_count") or 0)
    missing_window_count = max(0, TARGET_DISTINCT_WINDOW_COUNT - distinct_window_count)
    transition_locality = str(transition_row.get("transition_locality") or candidate_row.get("transition_locality") or "unknown")
    current_window_role_count = int(transition_row.get("current_window_role_count") or candidate_row.get("short_trade_trade_date_count") or 0)

    if candidate_row and distinct_window_count >= TARGET_DISTINCT_WINDOW_COUNT and transition_locality == "multi_window_stable":
        validation_verdict = "independent_window_requirement_satisfied"
        lane_status = "ready_for_shadow_validation"
    elif candidate_row:
        validation_verdict = "await_new_independent_window_data"
        lane_status = pending_lane_status
    else:
        validation_verdict = "candidate_report_missing"
        lane_status = "candidate_report_missing"

    return {
        **base_row,
        "objective": objective,
        "keep_guardrails": keep_guardrails,
        "distinct_window_count": distinct_window_count,
        "target_window_count": TARGET_DISTINCT_WINDOW_COUNT,
        "missing_window_count": missing_window_count,
        "window_keys": list(candidate_row.get("window_keys") or []),
        "transition_locality": transition_locality,
        "current_window_role_count": current_window_role_count,
        "validation_verdict": validation_verdict,
        "lane_status": lane_status,
        "candidate_report_recommendation": candidate_row.get("recommendation"),
        "transition_report_recommendation": transition_row.get("recommendation"),
    }


def analyze_btst_recurring_shadow_runbook(
    shadow_lane_priority_path: str | Path,
    *,
    recurring_pair_comparison_path: str | Path,
    candidate_report_path: str | Path,
    recurring_transition_report_path: str | Path,
    recurring_close_bundle_path: str | Path | None = None,
) -> dict[str, Any]:
    shadow_lane_priority = _load_json(shadow_lane_priority_path)
    pair_comparison = _load_json(recurring_pair_comparison_path)
    candidate_report = _load_json(candidate_report_path)
    transition_report = _load_json(recurring_transition_report_path)
    recurring_close_bundle = _safe_load_json(recurring_close_bundle_path)
    lane_rows = list(shadow_lane_priority.get("lane_rows") or [])

    close_candidate_row = next((row for row in lane_rows if str(row.get("lane_role") or "") == "recurring_shadow_close_candidate"), {})
    intraday_control_row = next((row for row in lane_rows if str(row.get("lane_role") or "") == "recurring_shadow_intraday_control"), {})
    close_candidate_ticker = str(close_candidate_row.get("ticker") or "close_candidate")
    intraday_control_ticker = str(intraday_control_row.get("ticker") or "intraday_control")

    close_candidate = _build_validation_track(
        close_candidate_row,
        candidate_report=candidate_report,
        transition_report=transition_report,
        objective="把 recurring frontier 中最接近 close-continuation 的 lane 固定为 shadow 验证入口。",
        keep_guardrails=[
            "继续保持 recurring lane 内部 changed_non_target_case_count=0",
            "next_close_positive_rate 不低于 0.66",
            "不得把 penalty-coupled lane 写成 threshold-only 规则",
        ],
        pending_lane_status="await_new_close_candidate_window",
    )
    intraday_control = _build_validation_track(
        intraday_control_row,
        candidate_report=candidate_report,
        transition_report=transition_report,
        objective="保留 recurring intraday 控制样本，区分 intraday upside 与 close continuation。",
        keep_guardrails=[
            "只作为 intraday 对照，不参与 close 规则升级",
            "若 next_high_return_mean 优势消失，可从 control 队列移除",
        ],
        pending_lane_status="await_new_intraday_control_window",
    )

    close_candidate_bundle_command = _build_recurring_close_bundle_command(close_candidate_ticker, intraday_control_ticker)
    close_candidate_bundle_path_resolved = None
    if recurring_close_bundle_path:
        close_candidate_bundle_path_resolved = str(Path(recurring_close_bundle_path).expanduser().resolve())
    if recurring_close_bundle and str(recurring_close_bundle.get("close_candidate_ticker") or "") == close_candidate_ticker:
        close_candidate["bundle_report"] = close_candidate_bundle_path_resolved
        close_candidate["bundle_recommendation"] = recurring_close_bundle.get("recommendation")
        close_candidate["bundle_next_step"] = recurring_close_bundle.get("next_step")
        close_candidate["next_step"] = recurring_close_bundle.get("next_step") or close_candidate.get("next_step")

    if close_candidate.get("validation_verdict") == "independent_window_requirement_satisfied" and intraday_control.get("validation_verdict") == "independent_window_requirement_satisfied":
        global_validation_verdict = "recurring_shadow_window_requirement_satisfied"
    else:
        global_validation_verdict = "await_new_recurring_window_evidence"

    close_candidate_execution_step = f"并行把 {close_candidate_ticker} 固定为 recurring shadow close 候选。"
    if recurring_close_bundle and str(recurring_close_bundle.get("close_candidate_ticker") or "") == close_candidate_ticker:
        close_candidate_execution_step = f"{close_candidate_execution_step[:-1]}，并直接复用 close bundle。"

    rerun_commands = _build_rerun_commands(close_candidate_ticker, intraday_control_ticker)

    runbook = {
        "shadow_lane_priority": str(Path(shadow_lane_priority_path).expanduser().resolve()),
        "recurring_pair_comparison": str(Path(recurring_pair_comparison_path).expanduser().resolve()),
        "candidate_report": str(Path(candidate_report_path).expanduser().resolve()),
        "recurring_transition_report": str(Path(recurring_transition_report_path).expanduser().resolve()),
        "recurring_close_bundle": close_candidate_bundle_path_resolved,
        "close_candidate": close_candidate,
        "intraday_control": intraday_control,
        "global_guardrails": [
            "recurring shadow lane 只在 300383 same-rule expansion blocked 时启用，不与 single-name shadow 混用。",
            f"{close_candidate_ticker} 代表 close-continuation recurring shadow 候选，{intraday_control_ticker} 代表 intraday control。",
            f"若 {close_candidate_ticker} 的 close continuation 再次转弱，不得因为 {intraday_control_ticker} 的 intraday upside 仍强就升级 recurring shadow lane。",
        ],
        "execution_sequence": [
            "先保留 300383 作为 single-name shadow，不做参数克隆式扩张。",
            close_candidate_execution_step,
            f"同时把 {intraday_control_ticker} 固定为 recurring intraday control，专门监控 intraday-only 漂移。",
        ],
        "global_validation_verdict": global_validation_verdict,
        "rerun_commands": rerun_commands,
        "close_candidate_bundle_command": close_candidate_bundle_command,
        "recommendation": (f"当前 recurring shadow lane 应按 {close_candidate_ticker} close-candidate + {intraday_control_ticker} intraday-control 的双轨结构推进，" "而不是把 recurring frontier 当成单一 shadow 规则。当前未完成项同样只剩新增独立窗口证据，而不是缺少额外规则。" f" close-candidate 侧已具备可直接复用的 bundle，后续应优先走 bundle + governance 回接，而不是手工拼脚本链。"),
        "pair_recommendation": pair_comparison.get("recommendation"),
    }
    return runbook


def render_btst_recurring_shadow_runbook_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Recurring Shadow Runbook")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- recommendation: {analysis['recommendation']}")
    lines.append(f"- pair_recommendation: {analysis['pair_recommendation']}")
    lines.append(f"- global_validation_verdict: {analysis['global_validation_verdict']}")
    lines.append("")
    lines.append("## Close Candidate")
    lines.append(f"- ticker: {analysis['close_candidate'].get('ticker')}")
    lines.append(f"- lane_status: {analysis['close_candidate'].get('lane_status')}")
    lines.append(f"- validation_verdict: {analysis['close_candidate'].get('validation_verdict')}")
    lines.append(f"- distinct_window_count: {analysis['close_candidate'].get('distinct_window_count')}")
    lines.append(f"- missing_window_count: {analysis['close_candidate'].get('missing_window_count')}")
    lines.append(f"- transition_locality: {analysis['close_candidate'].get('transition_locality')}")
    lines.append(f"- next_step: {analysis['close_candidate'].get('next_step')}")
    for item in analysis["close_candidate"].get("keep_guardrails") or []:
        lines.append(f"- keep_guardrail: {item}")
    lines.append("")
    lines.append("## Intraday Control")
    lines.append(f"- ticker: {analysis['intraday_control'].get('ticker')}")
    lines.append(f"- lane_status: {analysis['intraday_control'].get('lane_status')}")
    lines.append(f"- validation_verdict: {analysis['intraday_control'].get('validation_verdict')}")
    lines.append(f"- distinct_window_count: {analysis['intraday_control'].get('distinct_window_count')}")
    lines.append(f"- missing_window_count: {analysis['intraday_control'].get('missing_window_count')}")
    lines.append(f"- transition_locality: {analysis['intraday_control'].get('transition_locality')}")
    lines.append(f"- next_step: {analysis['intraday_control'].get('next_step')}")
    for item in analysis["intraday_control"].get("keep_guardrails") or []:
        lines.append(f"- keep_guardrail: {item}")
    lines.append("")
    lines.append("## Execution Sequence")
    for item in analysis["execution_sequence"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Bundle")
    lines.append(f"- recurring_close_bundle: {analysis.get('recurring_close_bundle')}")
    lines.append(f"- close_candidate_bundle_command: {analysis.get('close_candidate_bundle_command')}")
    lines.append("")
    lines.append("## Rerun Commands")
    for item in analysis["rerun_commands"]:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a recurring shadow runbook from the shadow lane priority board.")
    parser.add_argument("--shadow-lane-priority", default=str(DEFAULT_SHADOW_LANE_PRIORITY_PATH))
    parser.add_argument("--recurring-pair-comparison", default=str(DEFAULT_RECURRING_PAIR_COMPARISON_PATH))
    parser.add_argument("--candidate-report", default=str(DEFAULT_CANDIDATE_REPORT_PATH))
    parser.add_argument("--recurring-transition-report", default=str(DEFAULT_RECURRING_TRANSITION_REPORT_PATH))
    parser.add_argument("--recurring-close-bundle", default=str(DEFAULT_RECURRING_CLOSE_BUNDLE_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_recurring_shadow_runbook(
        args.shadow_lane_priority,
        recurring_pair_comparison_path=args.recurring_pair_comparison,
        candidate_report_path=args.candidate_report,
        recurring_transition_report_path=args.recurring_transition_report,
        recurring_close_bundle_path=args.recurring_close_bundle,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_recurring_shadow_runbook_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
