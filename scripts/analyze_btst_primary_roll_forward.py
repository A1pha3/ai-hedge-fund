from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPORTS_DIR = Path("data/reports")
DEFAULT_EXECUTION_SUMMARY_PATH = REPORTS_DIR / "p2_top3_experiment_execution_summary_20260330.json"
DEFAULT_MULTI_WINDOW_CANDIDATE_REPORT_PATH = REPORTS_DIR / "multi_window_short_trade_role_candidates_20260329.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "p4_primary_roll_forward_validation_001309_20260330.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "p4_primary_roll_forward_validation_001309_20260330.md"


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _find_execution_row(execution_summary: dict[str, Any], ticker: str) -> dict[str, Any]:
    for row in list(execution_summary.get("experiments") or []):
        if str(row.get("ticker") or "") == ticker:
            return dict(row)
    raise ValueError(f"Ticker not found in execution summary: {ticker}")


def _find_candidate_row(candidate_report: dict[str, Any], ticker: str) -> dict[str, Any]:
    for row in list(candidate_report.get("candidates") or []):
        if str(row.get("ticker") or "") == ticker:
            return dict(row)
    return {}


def analyze_btst_primary_roll_forward(
    execution_summary_path: str | Path,
    *,
    candidate_report_path: str | Path,
    ticker: str = "001309",
) -> dict[str, Any]:
    normalized_ticker = str(ticker).strip()
    execution_summary = _load_json(execution_summary_path)
    candidate_report = _load_json(candidate_report_path)

    execution_row = _find_execution_row(execution_summary, normalized_ticker)
    candidate_row = _find_candidate_row(candidate_report, normalized_ticker)

    changed_non_target_case_count = int(execution_row.get("changed_non_target_case_count") or 0)
    next_close_return_mean = float(execution_row.get("next_close_return_mean") or 0.0)
    next_close_positive_rate = float(execution_row.get("next_close_positive_rate") or 0.0)
    target_case_count = int(execution_row.get("target_case_count") or 0)
    short_trade_trade_date_count = int(candidate_row.get("short_trade_trade_date_count") or 0)
    distinct_window_count = int(candidate_row.get("distinct_window_count") or 0)
    transition_locality = str(candidate_row.get("transition_locality") or "not_in_candidate_scan")

    keep_guardrails_ok = (
        str(execution_row.get("action_tier") or "") == "primary_promote"
        and changed_non_target_case_count == 0
        and next_close_return_mean > 0
        and next_close_positive_rate >= 0.75
    )
    multi_window_ready = transition_locality == "multi_window_stable" or distinct_window_count >= 2
    default_upgrade_eligible = keep_guardrails_ok and multi_window_ready

    evidence_gaps: list[str] = []
    if target_case_count < 2:
        evidence_gaps.append("target_case_count<2，当前 primary 入口样本仍偏少。")
    if short_trade_trade_date_count < 3:
        evidence_gaps.append("short_trade_trade_date_count<3，当前窗口内重复证据不足。")
    if distinct_window_count < 2:
        evidence_gaps.append("distinct_window_count<2，尚未形成跨窗口稳定复现证据。")
    if transition_locality != "multi_window_stable":
        evidence_gaps.append("当前仍是 emergent_local_baseline，不得直接讨论默认升级。")

    if default_upgrade_eligible:
        roll_forward_verdict = "eligible_for_default_upgrade_review"
        recommendation = (
            f"{normalized_ticker} 已同时满足 controlled follow-through guardrails 与 multi-window 稳定性，"
            "可以进入默认升级评审。"
        )
    elif keep_guardrails_ok:
        roll_forward_verdict = "continue_controlled_roll_forward"
        recommendation = (
            f"{normalized_ticker} 继续作为唯一 primary controlled follow-through 入口推进，"
            "但当前仍缺跨窗口稳定复现证据，因此只能做滚动复核，不能升级成默认规则。"
        )
    else:
        roll_forward_verdict = "halt_or_rollback"
        recommendation = (
            f"{normalized_ticker} 当前不再满足 primary follow-through 的 keep guardrails，"
            "应暂停滚动推进并重新检查 release 语义。"
        )

    return {
        "generated_on": execution_summary.get("generated_on"),
        "execution_summary": str(Path(execution_summary_path).expanduser().resolve()),
        "candidate_report": str(Path(candidate_report_path).expanduser().resolve()),
        "ticker": normalized_ticker,
        "action_tier": execution_row.get("action_tier"),
        "target_case_count": target_case_count,
        "promoted_target_case_count": execution_row.get("promoted_target_case_count"),
        "changed_non_target_case_count": changed_non_target_case_count,
        "next_high_return_mean": execution_row.get("next_high_return_mean"),
        "next_close_return_mean": execution_row.get("next_close_return_mean"),
        "next_close_positive_rate": execution_row.get("next_close_positive_rate"),
        "short_trade_trade_date_count": short_trade_trade_date_count,
        "distinct_window_count": distinct_window_count,
        "distinct_report_count": candidate_row.get("distinct_report_count"),
        "transition_locality": transition_locality,
        "window_keys": list(candidate_row.get("window_keys") or []),
        "role_counts": dict(candidate_row.get("role_counts") or {}),
        "keep_guardrails_ok": keep_guardrails_ok,
        "default_upgrade_eligible": default_upgrade_eligible,
        "roll_forward_verdict": roll_forward_verdict,
        "evidence_gaps": evidence_gaps,
        "next_actions": [
            f"继续把 {normalized_ticker} 固定为唯一 primary controlled follow-through 入口。",
            "至少补到一个新增独立窗口后，再讨论默认升级。",
            "滚动复核期间若 changed_non_target_case_count 再次大于 0 或 close continuation 转负，则立即降级。",
        ],
        "release_report": execution_row.get("release_report"),
        "outcome_report": execution_row.get("outcome_report"),
        "recommendation": recommendation,
    }


def render_btst_primary_roll_forward_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Primary Roll-Forward Validation")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- ticker: {analysis['ticker']}")
    lines.append(f"- action_tier: {analysis['action_tier']}")
    lines.append(f"- roll_forward_verdict: {analysis['roll_forward_verdict']}")
    lines.append(f"- default_upgrade_eligible: {analysis['default_upgrade_eligible']}")
    lines.append("")
    lines.append("## Evidence")
    lines.append(f"- target_case_count: {analysis['target_case_count']}")
    lines.append(f"- changed_non_target_case_count: {analysis['changed_non_target_case_count']}")
    lines.append(f"- next_high_return_mean: {analysis['next_high_return_mean']}")
    lines.append(f"- next_close_return_mean: {analysis['next_close_return_mean']}")
    lines.append(f"- next_close_positive_rate: {analysis['next_close_positive_rate']}")
    lines.append(f"- short_trade_trade_date_count: {analysis['short_trade_trade_date_count']}")
    lines.append(f"- distinct_window_count: {analysis['distinct_window_count']}")
    lines.append(f"- transition_locality: {analysis['transition_locality']}")
    lines.append("")
    lines.append("## Evidence Gaps")
    for gap in analysis["evidence_gaps"]:
        lines.append(f"- {gap}")
    if not analysis["evidence_gaps"]:
        lines.append("- none")
    lines.append("")
    lines.append("## Next Actions")
    for action in analysis["next_actions"]:
        lines.append(f"- {action}")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate whether the BTST primary follow-through case is ready for default-upgrade review.")
    parser.add_argument("--execution-summary", default=str(DEFAULT_EXECUTION_SUMMARY_PATH))
    parser.add_argument("--candidate-report", default=str(DEFAULT_MULTI_WINDOW_CANDIDATE_REPORT_PATH))
    parser.add_argument("--ticker", default="001309")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_primary_roll_forward(
        args.execution_summary,
        candidate_report_path=args.candidate_report,
        ticker=args.ticker,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_primary_roll_forward_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()