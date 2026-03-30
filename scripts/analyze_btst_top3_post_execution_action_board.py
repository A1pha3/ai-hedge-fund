from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPORTS_DIR = Path("data/reports")
DEFAULT_EXECUTION_SUMMARY_PATH = REPORTS_DIR / "p2_top3_experiment_execution_summary_20260330.json"
DEFAULT_READINESS_REPORT_PATH = REPORTS_DIR / "case_based_short_trade_entry_readiness_20260329.json"
DEFAULT_SCOREBOARD_REPORT_PATH = REPORTS_DIR / "short_trade_release_priority_scoreboard_20260329.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "p3_top3_post_execution_action_board_20260330.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "p3_top3_post_execution_action_board_20260330.md"


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _build_next_step(action_tier: str, ticker: str) -> str:
    if action_tier == "primary_promote":
        return f"把 {ticker} 固定为唯一 primary controlled follow-through 入口，并推进到滚动窗口复核。"
    if action_tier == "shadow_keep":
        return f"把 {ticker} 保留在 shadow queue；未扩样前禁止升级为 primary。"
    if action_tier in {"structural_shadow_keep", "structural_shadow_hold"}:
        return f"把 {ticker} 固定为单票 structural shadow 观察样本，不做 cluster-wide structural release。"
    if action_tier == "shadow_rollback":
        return f"把 {ticker} 从 shadow queue 移除。"
    if action_tier == "primary_watch":
        return f"继续观察 {ticker}，但不进入默认 primary 口径。"
    return f"停止推进 {ticker} 的当前 release 方向。"


def _build_task(row: dict[str, Any]) -> dict[str, Any]:
    action_tier = str(row.get("action_tier") or "")
    ticker = str(row.get("ticker") or "")
    if action_tier == "primary_promote":
        return {
            "task_id": f"{ticker}_primary_follow_through_roll_forward",
            "title": f"推进 {ticker} primary follow-through",
            "why_now": "这是当前唯一同时满足低污染、低成本和正向 close continuation 的 primary 入口。",
            "action_tier": action_tier,
            "acceptance_criteria": [
                "继续保持 changed_non_target_case_count=0",
                "next_close_return_mean 继续大于 0",
                "next_close_positive_rate 不低于 0.75",
            ],
            "next_step": row["next_step"],
            "release_report": row.get("release_report"),
            "outcome_report": row.get("outcome_report"),
            "cli_preview": row.get("cli_preview"),
        }
    if action_tier == "shadow_keep":
        return {
            "task_id": f"{ticker}_shadow_queue_hold",
            "title": f"维持 {ticker} shadow entry",
            "why_now": "它已证明方向正确，但仍是单样本 threshold-only release，不应抢占 primary 位置。",
            "action_tier": action_tier,
            "acceptance_criteria": [
                "继续保持 changed_non_target_case_count=0",
                "样本扩展前不升级为 primary",
                "next_close_return_mean 继续大于 0",
            ],
            "next_step": row["next_step"],
            "release_report": row.get("release_report"),
            "outcome_report": row.get("outcome_report"),
            "cli_preview": row.get("cli_preview"),
        }
    return {
        "task_id": f"{ticker}_structural_shadow_freeze",
        "title": f"冻结 {ticker} structural release 扩散",
        "why_now": "它虽能被定向释放，但后验机会质量不足，不应外推成结构默认放松。",
        "action_tier": action_tier,
        "acceptance_criteria": [
            "禁止 cluster-wide structural release",
            "仅保留 targeted 单票观察",
            "若后验 close continuation 仍为负，则继续挂起",
        ],
        "next_step": row["next_step"],
        "release_report": row.get("release_report"),
        "outcome_report": row.get("outcome_report"),
        "cli_preview": row.get("cli_preview"),
    }


def analyze_btst_top3_post_execution_action_board(
    execution_summary_path: str | Path,
    *,
    readiness_report_path: str | Path,
    scoreboard_report_path: str | Path,
) -> dict[str, Any]:
    execution_summary = _load_json(execution_summary_path)
    readiness_report = _load_json(readiness_report_path)
    scoreboard_report = _load_json(scoreboard_report_path)
    runbook = _load_json(execution_summary["runbook"])

    readiness_by_ticker = {str(entry.get("ticker") or ""): entry for entry in list(readiness_report.get("entries") or [])}
    scoreboard_by_ticker = {str(entry.get("ticker") or ""): entry for entry in list(scoreboard_report.get("entries") or [])}
    experiment_by_id = {str(entry.get("experiment_id") or ""): entry for entry in list(runbook.get("top_3_experiments") or [])}

    board_rows: list[dict[str, Any]] = []
    for row in list(execution_summary.get("experiments") or []):
        ticker = str(row.get("ticker") or "")
        readiness = dict(readiness_by_ticker.get(ticker) or {})
        scoreboard = dict(scoreboard_by_ticker.get(ticker) or {})
        experiment = dict(experiment_by_id.get(str(row.get("experiment_id") or "")) or {})
        board_rows.append(
            {
                "priority_rank": row.get("priority_rank"),
                "experiment_id": row.get("experiment_id"),
                "ticker": ticker,
                "track": row.get("track"),
                "default_mode": row.get("default_mode"),
                "execution_verdict": row.get("verdict"),
                "action_tier": row.get("action_tier"),
                "action_summary": row.get("action_summary"),
                "primary_eligible": row.get("primary_eligible"),
                "readiness_tier": readiness.get("readiness_tier"),
                "scoreboard_rank": scoreboard.get("priority_rank"),
                "objective": experiment.get("objective"),
                "keep_guardrails": list(experiment.get("keep_guardrails") or []),
                "decision_rules": dict(experiment.get("decision_rules") or {}),
                "next_step": _build_next_step(str(row.get("action_tier") or ""), ticker),
                "next_high_return_mean": row.get("next_high_return_mean"),
                "next_close_return_mean": row.get("next_close_return_mean"),
                "next_close_positive_rate": row.get("next_close_positive_rate"),
                "changed_non_target_case_count": row.get("changed_non_target_case_count"),
                "release_report": row.get("release_report"),
                "outcome_report": row.get("outcome_report"),
                "cli_preview": row.get("cli_preview"),
            }
        )

    task_order = {"primary_promote": 0, "shadow_keep": 1, "structural_shadow_keep": 2, "structural_shadow_hold": 3}
    board_rows.sort(key=lambda row: (task_order.get(str(row.get("action_tier") or ""), 99), int(row.get("priority_rank") or 99)))
    next_3_tasks = [_build_task(row) for row in board_rows[:3]]

    recommendation = execution_summary.get("recommendation") or "当前没有形成明确的 post-execution action board 结论。"
    return {
        "generated_on": execution_summary.get("generated_on"),
        "source_reports": {
            "execution_summary": str(Path(execution_summary_path).expanduser().resolve()),
            "readiness_report": str(Path(readiness_report_path).expanduser().resolve()),
            "scoreboard_report": str(Path(scoreboard_report_path).expanduser().resolve()),
            "runbook": execution_summary.get("runbook"),
        },
        "recommendation": recommendation,
        "board_rows": board_rows,
        "next_3_tasks": next_3_tasks,
    }


def render_btst_top3_post_execution_action_board_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Top 3 Post-Execution Action Board")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- recommendation: {analysis['recommendation']}")
    lines.append(f"- execution_summary: {analysis['source_reports']['execution_summary']}")
    lines.append(f"- readiness_report: {analysis['source_reports']['readiness_report']}")
    lines.append(f"- scoreboard_report: {analysis['source_reports']['scoreboard_report']}")
    lines.append("")
    lines.append("## Board")
    for row in analysis["board_rows"]:
        lines.append(
            f"- rank={row['priority_rank']} ticker={row['ticker']} action_tier={row['action_tier']} execution_verdict={row['execution_verdict']} readiness_tier={row['readiness_tier']} scoreboard_rank={row['scoreboard_rank']} next_high_return_mean={row['next_high_return_mean']} next_close_return_mean={row['next_close_return_mean']}"
        )
        lines.append(f"  action_summary: {row['action_summary']}")
        lines.append(f"  next_step: {row['next_step']}")
    lines.append("")
    lines.append("## Immediate Next 3")
    for task in analysis["next_3_tasks"]:
        lines.append(f"- {task['task_id']}: {task['title']}")
        lines.append(f"  why_now: {task['why_now']}")
        lines.append(f"  next_step: {task['next_step']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a researcher-facing action board from BTST Top 3 post-execution results.")
    parser.add_argument("--execution-summary", default=str(DEFAULT_EXECUTION_SUMMARY_PATH))
    parser.add_argument("--readiness-report", default=str(DEFAULT_READINESS_REPORT_PATH))
    parser.add_argument("--scoreboard-report", default=str(DEFAULT_SCOREBOARD_REPORT_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_top3_post_execution_action_board(
        args.execution_summary,
        readiness_report_path=args.readiness_report,
        scoreboard_report_path=args.scoreboard_report,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_top3_post_execution_action_board_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()