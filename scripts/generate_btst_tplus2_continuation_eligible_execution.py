from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPORTS_DIR = Path("data/reports")
DEFAULT_LANE_RULEPACK_PATH = REPORTS_DIR / "btst_tplus2_continuation_lane_rulepack_latest.json"
DEFAULT_WATCHLIST_EXECUTION_PATH = REPORTS_DIR / "btst_tplus2_continuation_watchlist_execution_latest.json"
DEFAULT_ELIGIBLE_GATE_PATH = REPORTS_DIR / "btst_tplus2_continuation_eligible_gate_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_tplus2_continuation_eligible_execution_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_tplus2_continuation_eligible_execution_latest.md"


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _build_eligible_execution(lane_rulepack: dict[str, Any], watchlist_execution: dict[str, Any], eligible_gate: dict[str, Any]) -> dict[str, Any]:
    lane_rules = dict(lane_rulepack.get("lane_rules") or {})
    raw_eligible_tickers = [str(item) for item in list(lane_rulepack.get("eligible_tickers") or []) if str(item).strip()]
    focus_ticker = str(eligible_gate.get("focus_ticker") or watchlist_execution.get("focus_ticker") or "")
    adopted_watch_row = dict(watchlist_execution.get("adopted_watch_row") or {})
    gate_verdict = str(eligible_gate.get("gate_verdict") or "")

    if gate_verdict == "approve_eligible_promotion" and focus_ticker and focus_ticker not in raw_eligible_tickers:
        execution_verdict = "eligible_extension_applied"
        added_eligible_tickers = [focus_ticker]
        effective_eligible_tickers = raw_eligible_tickers + [focus_ticker]
    elif focus_ticker and focus_ticker in raw_eligible_tickers:
        execution_verdict = "eligible_extension_already_applied"
        added_eligible_tickers = []
        effective_eligible_tickers = list(raw_eligible_tickers)
    else:
        execution_verdict = "eligible_extension_held"
        added_eligible_tickers = []
        effective_eligible_tickers = list(raw_eligible_tickers)

    adopted_eligible_row = None
    if focus_ticker and execution_verdict in {"eligible_extension_applied", "eligible_extension_already_applied"}:
        adopted_eligible_row = {
            "ticker": focus_ticker,
            "entry_type": "promoted_watch_eligible",
            "priority_score": adopted_watch_row.get("priority_score"),
            "lane_stage": lane_rules.get("lane_stage", lane_rulepack.get("lane_stage")),
            "capital_mode": lane_rules.get("capital_mode", lane_rulepack.get("capital_mode")),
            "promotion_blocker": "governance_review_pending",
            "watchlist_validation_status": adopted_watch_row.get("watchlist_validation_status"),
            "recent_supporting_window_count": adopted_watch_row.get("recent_supporting_window_count"),
            "recent_window_count": adopted_watch_row.get("recent_window_count"),
            "recent_support_ratio": adopted_watch_row.get("recent_support_ratio"),
            "next_step": "Treat this as an effective eligible continuation name while keeping capital_mode=paper_only until broader lane governance changes.",
            "t_plus_2_close_positive_rate": adopted_watch_row.get("t_plus_2_close_positive_rate"),
            "t_plus_2_close_return_mean": adopted_watch_row.get("t_plus_2_close_return_mean"),
            "next_close_positive_rate": adopted_watch_row.get("next_close_positive_rate"),
        }

    recommendation = (
        f"Treat {focus_ticker} as an effective eligible continuation ticker while keeping the base rulepack unchanged."
        if execution_verdict == "eligible_extension_applied"
        else (
            f"{focus_ticker} is already part of the effective eligible continuation set."
            if execution_verdict == "eligible_extension_already_applied"
            else "Keep the effective eligible continuation set unchanged until the stricter gate approves promotion."
        )
    )

    return {
        "focus_ticker": focus_ticker or None,
        "gate_verdict": gate_verdict or None,
        "execution_verdict": execution_verdict,
        "raw_eligible_tickers": raw_eligible_tickers,
        "effective_eligible_tickers": effective_eligible_tickers,
        "added_eligible_tickers": added_eligible_tickers,
        "adopted_eligible_row": adopted_eligible_row,
        "recommendation": recommendation,
    }


def generate_btst_tplus2_continuation_eligible_execution(
    *,
    lane_rulepack_path: str | Path,
    watchlist_execution_path: str | Path,
    eligible_gate_path: str | Path,
) -> dict[str, Any]:
    lane_rulepack = _load_json(lane_rulepack_path)
    watchlist_execution = _load_json(watchlist_execution_path)
    eligible_gate = _load_json(eligible_gate_path)
    analysis = _build_eligible_execution(lane_rulepack, watchlist_execution, eligible_gate)
    analysis["source_reports"] = {
        "lane_rulepack": str(Path(lane_rulepack_path).expanduser().resolve()),
        "watchlist_execution": str(Path(watchlist_execution_path).expanduser().resolve()),
        "eligible_gate": str(Path(eligible_gate_path).expanduser().resolve()),
    }
    return analysis


def render_btst_tplus2_continuation_eligible_execution_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST T+2 Continuation Eligible Execution")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- focus_ticker: {analysis['focus_ticker']}")
    lines.append(f"- gate_verdict: {analysis['gate_verdict']}")
    lines.append(f"- execution_verdict: {analysis['execution_verdict']}")
    lines.append(f"- raw_eligible_tickers: {analysis['raw_eligible_tickers']}")
    lines.append(f"- effective_eligible_tickers: {analysis['effective_eligible_tickers']}")
    lines.append(f"- added_eligible_tickers: {analysis['added_eligible_tickers']}")
    lines.append(f"- adopted_eligible_row: {analysis['adopted_eligible_row']}")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute eligible-lane adoption from an approved continuation eligible gate.")
    parser.add_argument("--lane-rulepack-path", default=str(DEFAULT_LANE_RULEPACK_PATH))
    parser.add_argument("--watchlist-execution-path", default=str(DEFAULT_WATCHLIST_EXECUTION_PATH))
    parser.add_argument("--eligible-gate-path", default=str(DEFAULT_ELIGIBLE_GATE_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = generate_btst_tplus2_continuation_eligible_execution(
        lane_rulepack_path=args.lane_rulepack_path,
        watchlist_execution_path=args.watchlist_execution_path,
        eligible_gate_path=args.eligible_gate_path,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_tplus2_continuation_eligible_execution_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
