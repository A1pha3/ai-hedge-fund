from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPORTS_DIR = Path("data/reports")
DEFAULT_EXECUTION_SUMMARY_PATH = REPORTS_DIR / "p2_top3_experiment_execution_summary_20260330.json"
DEFAULT_FRONTIER_REPORT_PATH = REPORTS_DIR / "short_trade_boundary_score_failures_frontier_catalyst_floor_zero_full_20260329.json"
DEFAULT_SCOREBOARD_REPORT_PATH = REPORTS_DIR / "short_trade_release_priority_scoreboard_20260329.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "p4_shadow_entry_expansion_board_300383_20260330.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "p4_shadow_entry_expansion_board_300383_20260330.md"
DEFAULT_STALE_WEIGHT = 0.12
DEFAULT_EXTENSION_WEIGHT = 0.08


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _find_execution_row(execution_summary: dict[str, Any], ticker: str) -> dict[str, Any]:
    for row in list(execution_summary.get("experiments") or []):
        if str(row.get("ticker") or "") == ticker:
            return dict(row)
    raise ValueError(f"Ticker not found in execution summary: {ticker}")


def _is_threshold_only_frontier_row(row: dict[str, Any]) -> bool:
    return float(row.get("stale_weight") or 0.0) == DEFAULT_STALE_WEIGHT and float(row.get("extension_weight") or 0.0) == DEFAULT_EXTENSION_WEIGHT


def analyze_btst_shadow_entry_expansion(
    execution_summary_path: str | Path,
    *,
    frontier_report_path: str | Path,
    scoreboard_report_path: str | Path,
    ticker: str = "300383",
) -> dict[str, Any]:
    normalized_ticker = str(ticker).strip()
    execution_summary = _load_json(execution_summary_path)
    frontier_report = _load_json(frontier_report_path)
    scoreboard_report = _load_json(scoreboard_report_path)

    execution_row = _find_execution_row(execution_summary, normalized_ticker)
    frontier_rows = [dict(row) for row in list(frontier_report.get("minimal_near_miss_rows") or [])]
    frontier_rows.sort(key=lambda row: (float(row.get("adjustment_cost") or 999.0), str(row.get("trade_date") or ""), str(row.get("ticker") or "")))
    scoreboard_by_ticker = {str(entry.get("ticker") or ""): dict(entry) for entry in list(scoreboard_report.get("entries") or [])}

    current_frontier_row = next((row for row in frontier_rows if str(row.get("ticker") or "") == normalized_ticker), {})
    threshold_only_rows = [row for row in frontier_rows if _is_threshold_only_frontier_row(row)]
    threshold_only_tickers = sorted({str(row.get("ticker") or "") for row in threshold_only_rows if str(row.get("ticker") or "")})

    peer_rows: list[dict[str, Any]] = []
    for row in frontier_rows:
        peer_ticker = str(row.get("ticker") or "")
        if peer_ticker == normalized_ticker:
            continue
        scoreboard_entry = scoreboard_by_ticker.get(peer_ticker) or {}
        peer_rows.append(
            {
                **row,
                "peer_class": "threshold_only" if _is_threshold_only_frontier_row(row) else "penalty_coupled",
                "scoreboard_rank": scoreboard_entry.get("priority_rank"),
                "lane_type": scoreboard_entry.get("lane_type"),
                "has_existing_release_outcome": bool(scoreboard_entry),
            }
        )

    peer_rows.sort(
        key=lambda row: (
            0 if row["has_existing_release_outcome"] else 1,
            float(row.get("adjustment_cost") or 999.0),
            int(row.get("scoreboard_rank") or 999),
            str(row.get("ticker") or ""),
        )
    )

    unique_threshold_only = threshold_only_tickers == [normalized_ticker]
    same_rule_expansion_ready = any(row["peer_class"] == "threshold_only" for row in peer_rows)
    evidence_gaps: list[str] = []
    if int(execution_row.get("target_case_count") or 0) < 2:
        evidence_gaps.append("target_case_count<2，300383 仍然只是单样本 shadow entry。")
    if unique_threshold_only:
        evidence_gaps.append("当前整个 frontier 里只有 300383 一只 threshold-only 低成本释放样本。")
    if not same_rule_expansion_ready:
        evidence_gaps.append("不存在第二只可按同一 threshold-only 规则复制的同类样本。")

    if unique_threshold_only and not same_rule_expansion_ready:
        expansion_verdict = "hold_shadow_only_no_same_rule_expansion"
        recommendation = (
            "300383 可以继续保留在 shadow queue，但不能把同一条 threshold-only 放松直接扩成默认或批量规则。"
            " 如果要扩大 shadow 实验范围，应优先转向已有 outcome 证据的 recurring frontier lane，而不是克隆 300383 的单票 release。"
        )
    elif same_rule_expansion_ready:
        expansion_verdict = "shadow_peer_scan_ready"
        recommendation = "300383 之外还存在同类 threshold-only peer，可继续做受控 shadow peer scan。"
    else:
        expansion_verdict = "halt_shadow_expansion"
        recommendation = "300383 当前不再适合作为 shadow 扩样起点，应暂停同类扩展。"

    return {
        "generated_on": execution_summary.get("generated_on"),
        "execution_summary": str(Path(execution_summary_path).expanduser().resolve()),
        "frontier_report": str(Path(frontier_report_path).expanduser().resolve()),
        "scoreboard_report": str(Path(scoreboard_report_path).expanduser().resolve()),
        "ticker": normalized_ticker,
        "action_tier": execution_row.get("action_tier"),
        "target_case_count": execution_row.get("target_case_count"),
        "next_high_return_mean": execution_row.get("next_high_return_mean"),
        "next_close_return_mean": execution_row.get("next_close_return_mean"),
        "next_close_positive_rate": execution_row.get("next_close_positive_rate"),
        "frontier_uniqueness": {
            "threshold_only_candidate_count": len(threshold_only_rows),
            "threshold_only_tickers": threshold_only_tickers,
            "current_shadow_is_unique_threshold_only": unique_threshold_only,
            "same_rule_expansion_ready": same_rule_expansion_ready,
        },
        "current_frontier_row": current_frontier_row,
        "priority_peer_rows": peer_rows[:5],
        "expansion_verdict": expansion_verdict,
        "evidence_gaps": evidence_gaps,
        "next_actions": [
            f"继续把 {normalized_ticker} 固定在 shadow queue，不得抢占 primary 位置。",
            "同规则扩样前，必须先出现第二只 threshold-only peer 且仍保持零 spillover。",
            "若需要扩大 shadow lane，优先复核已有 outcome 证据的 recurring frontier peer，而不是直接复制 300383 的参数。",
        ],
        "recommendation": recommendation,
    }


def render_btst_shadow_entry_expansion_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Shadow Entry Expansion Board")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- ticker: {analysis['ticker']}")
    lines.append(f"- action_tier: {analysis['action_tier']}")
    lines.append(f"- expansion_verdict: {analysis['expansion_verdict']}")
    lines.append("")
    lines.append("## Frontier Uniqueness")
    lines.append(f"- threshold_only_candidate_count: {analysis['frontier_uniqueness']['threshold_only_candidate_count']}")
    lines.append(f"- threshold_only_tickers: {analysis['frontier_uniqueness']['threshold_only_tickers']}")
    lines.append(f"- current_shadow_is_unique_threshold_only: {analysis['frontier_uniqueness']['current_shadow_is_unique_threshold_only']}")
    lines.append(f"- same_rule_expansion_ready: {analysis['frontier_uniqueness']['same_rule_expansion_ready']}")
    lines.append("")
    lines.append("## Priority Peers")
    for row in analysis["priority_peer_rows"]:
        lines.append(
            f"- ticker={row['ticker']} peer_class={row['peer_class']} adjustment_cost={row['adjustment_cost']} scoreboard_rank={row['scoreboard_rank']} lane_type={row['lane_type']} has_existing_release_outcome={row['has_existing_release_outcome']}"
        )
    if not analysis["priority_peer_rows"]:
        lines.append("- none")
    lines.append("")
    lines.append("## Evidence Gaps")
    for gap in analysis["evidence_gaps"]:
        lines.append(f"- {gap}")
    if not analysis["evidence_gaps"]:
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Assess whether the current BTST shadow entry can be expanded beyond a single threshold-only case.")
    parser.add_argument("--execution-summary", default=str(DEFAULT_EXECUTION_SUMMARY_PATH))
    parser.add_argument("--frontier-report", default=str(DEFAULT_FRONTIER_REPORT_PATH))
    parser.add_argument("--scoreboard-report", default=str(DEFAULT_SCOREBOARD_REPORT_PATH))
    parser.add_argument("--ticker", default="300383")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_shadow_entry_expansion(
        args.execution_summary,
        frontier_report_path=args.frontier_report,
        scoreboard_report_path=args.scoreboard_report,
        ticker=args.ticker,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_shadow_entry_expansion_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()