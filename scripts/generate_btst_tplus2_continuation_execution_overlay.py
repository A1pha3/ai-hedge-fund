from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.execution.merge_approved_loader import (
    DEFAULT_BTST_MERGE_APPROVED_EXECUTION_ACTIVE,
    is_merge_approved_execution_blocker,
)


REPORTS_DIR = Path("data/reports")
DEFAULT_ELIGIBLE_EXECUTION_PATH = REPORTS_DIR / "btst_tplus2_continuation_eligible_execution_latest.json"
DEFAULT_EXECUTION_GATE_PATH = REPORTS_DIR / "btst_tplus2_continuation_execution_gate_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_tplus2_continuation_execution_overlay_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_tplus2_continuation_execution_overlay_latest.md"


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _build_execution_overlay(eligible_execution: dict[str, Any], execution_gate: dict[str, Any]) -> dict[str, Any]:
    focus_ticker = str(execution_gate.get("focus_ticker") or eligible_execution.get("focus_ticker") or "")
    adopted_eligible_row = dict(eligible_execution.get("adopted_eligible_row") or {})
    gate_verdict = str(execution_gate.get("gate_verdict") or "")
    merge_review_ready = is_merge_approved_execution_blocker(adopted_eligible_row.get("promotion_blocker"))

    if gate_verdict == "approve_execution_candidate" and focus_ticker:
        execution_verdict = "execution_candidate_applied"
        effective_execution_candidates = [focus_ticker]
        added_execution_candidates = [focus_ticker]
    else:
        execution_verdict = "execution_candidate_held"
        effective_execution_candidates = []
        added_execution_candidates = []

    adopted_execution_row = None
    if focus_ticker and execution_verdict == "execution_candidate_applied":
        adopted_execution_row = {
            "ticker": focus_ticker,
            "entry_type": "paper_execution_candidate",
            "priority_score": adopted_eligible_row.get("priority_score"),
            "lane_stage": adopted_eligible_row.get("lane_stage"),
            "capital_mode": "paper_only",
            "promotion_blocker": DEFAULT_BTST_MERGE_APPROVED_EXECUTION_ACTIVE if merge_review_ready else "no_selected_persistence_or_independent_edge",
            "merge_approved_daily_pipeline_active": merge_review_ready,
            "watchlist_validation_status": adopted_eligible_row.get("watchlist_validation_status"),
            "recent_supporting_window_count": adopted_eligible_row.get("recent_supporting_window_count"),
            "recent_window_count": adopted_eligible_row.get("recent_window_count"),
            "recent_support_ratio": adopted_eligible_row.get("recent_support_ratio"),
            "persistence_requirement": "selected_persistence_across_independent_windows",
            "independent_edge_requirement": "outperform_default_btst_on_independent_windows",
            "lane_support_window_count": execution_gate.get("lane_support_window_count"),
            "lane_window_count": execution_gate.get("lane_window_count"),
            "lane_support_ratio": execution_gate.get("lane_support_ratio"),
            "governance_payoff_ready": execution_gate.get("governance_payoff_ready"),
            "t_plus_2_mean_gap_vs_watch": execution_gate.get("focus_t_plus_2_mean_gap_vs_watch"),
            "next_step": (
                "Keep this paper execution candidate visible because merge-approved daily-pipeline uplift is already active; if governance completes the review, promote it through the default BTST merge path."
                if merge_review_ready
                else "Use only as an isolated paper execution candidate; require selected persistence across independent windows "
                "plus a repeatable edge versus default BTST before merging into default selected/near_miss."
            ),
            "t_plus_2_close_positive_rate": adopted_eligible_row.get("t_plus_2_close_positive_rate"),
            "t_plus_2_close_return_mean": adopted_eligible_row.get("t_plus_2_close_return_mean"),
            "next_close_positive_rate": adopted_eligible_row.get("next_close_positive_rate"),
            "lane_t_plus_2_close_return_mean": execution_gate.get("lane_t_plus_2_close_return_mean"),
        }

    recommendation = (
        (
            f"Keep {focus_ticker} as a paper execution candidate because merge-approved daily-pipeline uplift is already active while governance finalizes the merge review."
        )
        if execution_verdict == "execution_candidate_applied" and merge_review_ready
        else (
        f"Treat {focus_ticker} as an isolated paper execution candidate while keeping the continuation lane outside default BTST."
        if execution_verdict == "execution_candidate_applied"
        else "Keep the execution overlay empty until the stricter execution gate approves a candidate."
        )
    )

    return {
        "focus_ticker": focus_ticker or None,
        "gate_verdict": gate_verdict or None,
        "execution_verdict": execution_verdict,
        "effective_execution_candidates": effective_execution_candidates,
        "added_execution_candidates": added_execution_candidates,
        "adopted_execution_row": adopted_execution_row,
        "recommendation": recommendation,
    }


def generate_btst_tplus2_continuation_execution_overlay(
    *,
    eligible_execution_path: str | Path,
    execution_gate_path: str | Path,
) -> dict[str, Any]:
    eligible_execution = _load_json(eligible_execution_path)
    execution_gate = _load_json(execution_gate_path)
    analysis = _build_execution_overlay(eligible_execution, execution_gate)
    analysis["source_reports"] = {
        "eligible_execution": str(Path(eligible_execution_path).expanduser().resolve()),
        "execution_gate": str(Path(execution_gate_path).expanduser().resolve()),
    }
    return analysis


def render_btst_tplus2_continuation_execution_overlay_markdown(analysis: dict[str, Any]) -> str:
    lines = [
        "# BTST T+2 Continuation Execution Overlay",
        "",
        "## Overview",
        f"- focus_ticker: {analysis['focus_ticker']}",
        f"- gate_verdict: {analysis['gate_verdict']}",
        f"- execution_verdict: {analysis['execution_verdict']}",
        f"- effective_execution_candidates: {analysis['effective_execution_candidates']}",
        f"- added_execution_candidates: {analysis['added_execution_candidates']}",
        f"- adopted_execution_row: {analysis['adopted_execution_row']}",
        "",
        "## Recommendation",
        f"- {analysis['recommendation']}",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply a continuation paper execution overlay from an approved execution gate.")
    parser.add_argument("--eligible-execution-path", default=str(DEFAULT_ELIGIBLE_EXECUTION_PATH))
    parser.add_argument("--execution-gate-path", default=str(DEFAULT_EXECUTION_GATE_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = generate_btst_tplus2_continuation_execution_overlay(
        eligible_execution_path=args.eligible_execution_path,
        execution_gate_path=args.execution_gate_path,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_tplus2_continuation_execution_overlay_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
