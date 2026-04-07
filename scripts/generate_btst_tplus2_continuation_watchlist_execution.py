from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.execution.merge_approved_loader import DEFAULT_BTST_MERGE_APPROVED_EXECUTION_ACTIVE
from scripts.generate_btst_tplus2_continuation_promotion_review import READY_PROMOTION_REVIEW_VERDICTS


REPORTS_DIR = Path("data/reports")
DEFAULT_LANE_RULEPACK_PATH = REPORTS_DIR / "btst_tplus2_continuation_lane_rulepack_latest.json"
DEFAULT_VALIDATION_QUEUE_PATH = REPORTS_DIR / "btst_tplus2_continuation_validation_queue_latest.json"
DEFAULT_PROMOTION_GATE_PATH = REPORTS_DIR / "btst_tplus2_continuation_promotion_gate_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_tplus2_continuation_watchlist_execution_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_tplus2_continuation_watchlist_execution_latest.md"


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _build_watchlist_execution(lane_rulepack: dict[str, Any], validation_queue: dict[str, Any], promotion_gate: dict[str, Any]) -> dict[str, Any]:
    lane_rules = dict(lane_rulepack.get("lane_rules") or {})
    raw_watchlist_tickers = [str(item) for item in list(lane_rulepack.get("watchlist_tickers") or []) if str(item).strip()]
    eligible_tickers = [str(item) for item in list(lane_rulepack.get("eligible_tickers") or []) if str(item).strip()]
    focus_ticker = str(promotion_gate.get("focus_ticker") or validation_queue.get("focus_ticker") or "")
    focus_candidate = dict(validation_queue.get("focus_candidate") or {})
    gate_verdict = str(promotion_gate.get("gate_verdict") or "")
    governance_ready_watch = (
        str(focus_candidate.get("candidate_tier_focus") or "") == "governance_followup"
        and str(focus_candidate.get("promotion_readiness_verdict") or "") in {"watch_review_ready", "merge_review_ready"}
    )
    promotion_review_verdict = str(promotion_gate.get("promotion_review_verdict") or "")
    merge_review_ready = promotion_review_verdict == "ready_for_default_btst_merge_review"
    governance_ready_watch = governance_ready_watch or promotion_review_verdict in READY_PROMOTION_REVIEW_VERDICTS

    if gate_verdict == "approve_watchlist_promotion" and focus_ticker and focus_ticker not in raw_watchlist_tickers:
        execution_verdict = "watchlist_extension_applied"
        added_watchlist_tickers = [focus_ticker]
        effective_watchlist_tickers = raw_watchlist_tickers + [focus_ticker]
    elif focus_ticker and focus_ticker in raw_watchlist_tickers:
        execution_verdict = "watchlist_extension_already_applied"
        added_watchlist_tickers = []
        effective_watchlist_tickers = list(raw_watchlist_tickers)
    else:
        execution_verdict = "watchlist_extension_held"
        added_watchlist_tickers = []
        effective_watchlist_tickers = list(raw_watchlist_tickers)

    adopted_watch_row = None
    if focus_ticker and execution_verdict in {"watchlist_extension_applied", "watchlist_extension_already_applied"}:
        adopted_watch_row = {
            "ticker": focus_ticker,
            "entry_type": "promoted_validation_watch",
            "priority_score": focus_candidate.get("priority_rank"),
            "lane_stage": lane_rules.get("lane_stage", lane_rulepack.get("lane_stage")),
            "capital_mode": lane_rules.get("capital_mode", lane_rulepack.get("capital_mode")),
            "promotion_blocker": (
                DEFAULT_BTST_MERGE_APPROVED_EXECUTION_ACTIVE
                if merge_review_ready
                else ("governance_approved_continuation_watch" if governance_ready_watch else "near_cluster_only")
            ),
            "merge_approved_daily_pipeline_active": merge_review_ready,
            "watchlist_validation_status": (
                str(focus_candidate.get("recent_tier_verdict") or "governance_followup_payoff_confirmed")
                if governance_ready_watch
                else "promoted_from_validation_queue"
            ),
            "recent_supporting_window_count": focus_candidate.get("recent_tier_window_count"),
            "recent_window_count": focus_candidate.get("recent_window_count"),
            "recent_support_ratio": focus_candidate.get("recent_tier_ratio"),
            "next_step": (
                "Keep this continuation watch candidate visible because merge-approved daily-pipeline uplift is already active; do not demote it back to near-cluster-only handling while governance review completes."
                if merge_review_ready
                else (
                "Track this governance-approved continuation watch candidate under isolated paper-only controls; do not merge it into default BTST."
                if governance_ready_watch
                else "Track this adopted validation watch candidate outside eligible_tickers until a strict-peer upgrade appears."
                )
            ),
            "t_plus_2_close_positive_rate": focus_candidate.get("t_plus_2_close_positive_rate"),
            "t_plus_2_close_return_mean": focus_candidate.get("t_plus_2_close_return_mean"),
            "next_close_positive_rate": focus_candidate.get("next_close_positive_rate"),
        }

    if execution_verdict == "watchlist_extension_applied":
        recommendation = (
            (
                f"Treat {focus_ticker} as a formal continuation watchlist ticker because merge-approved daily-pipeline uplift is already active; "
                f"keep eligible_tickers={eligible_tickers} unchanged while governance completes the merge review."
            )
            if merge_review_ready
            else (
                f"Treat {focus_ticker} as a formal continuation watchlist ticker while keeping "
                f"eligible_tickers={eligible_tickers} unchanged and the continuation lane isolated from default BTST."
            )
        )
    elif execution_verdict == "watchlist_extension_already_applied":
        recommendation = f"{focus_ticker} is already part of the effective continuation watchlist."
    else:
        recommendation = "Keep the effective continuation watchlist unchanged until promotion gate approval is present."

    return {
        "focus_ticker": focus_ticker or None,
        "gate_verdict": gate_verdict or None,
        "execution_verdict": execution_verdict,
        "raw_watchlist_tickers": raw_watchlist_tickers,
        "effective_watchlist_tickers": effective_watchlist_tickers,
        "added_watchlist_tickers": added_watchlist_tickers,
        "eligible_tickers": eligible_tickers,
        "adopted_watch_row": adopted_watch_row,
        "recommendation": recommendation,
    }


def generate_btst_tplus2_continuation_watchlist_execution(
    *,
    lane_rulepack_path: str | Path,
    validation_queue_path: str | Path,
    promotion_gate_path: str | Path,
) -> dict[str, Any]:
    lane_rulepack = _load_json(lane_rulepack_path)
    validation_queue = _load_json(validation_queue_path)
    promotion_gate = _load_json(promotion_gate_path)
    analysis = _build_watchlist_execution(lane_rulepack, validation_queue, promotion_gate)
    analysis["source_reports"] = {
        "lane_rulepack": str(Path(lane_rulepack_path).expanduser().resolve()),
        "validation_queue": str(Path(validation_queue_path).expanduser().resolve()),
        "promotion_gate": str(Path(promotion_gate_path).expanduser().resolve()),
    }
    return analysis


def render_btst_tplus2_continuation_watchlist_execution_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST T+2 Continuation Watchlist Execution")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- focus_ticker: {analysis['focus_ticker']}")
    lines.append(f"- gate_verdict: {analysis['gate_verdict']}")
    lines.append(f"- execution_verdict: {analysis['execution_verdict']}")
    lines.append(f"- raw_watchlist_tickers: {analysis['raw_watchlist_tickers']}")
    lines.append(f"- effective_watchlist_tickers: {analysis['effective_watchlist_tickers']}")
    lines.append(f"- added_watchlist_tickers: {analysis['added_watchlist_tickers']}")
    lines.append(f"- eligible_tickers: {analysis['eligible_tickers']}")
    lines.append(f"- adopted_watch_row: {analysis['adopted_watch_row']}")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute continuation watchlist adoption from an approved promotion gate.")
    parser.add_argument("--lane-rulepack-path", default=str(DEFAULT_LANE_RULEPACK_PATH))
    parser.add_argument("--validation-queue-path", default=str(DEFAULT_VALIDATION_QUEUE_PATH))
    parser.add_argument("--promotion-gate-path", default=str(DEFAULT_PROMOTION_GATE_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = generate_btst_tplus2_continuation_watchlist_execution(
        lane_rulepack_path=args.lane_rulepack_path,
        validation_queue_path=args.validation_queue_path,
        promotion_gate_path=args.promotion_gate_path,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_tplus2_continuation_watchlist_execution_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
