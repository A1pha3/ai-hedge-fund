from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPORTS_DIR = Path("data/reports")
DEFAULT_LANE_RULEPACK_PATH = REPORTS_DIR / "btst_tplus2_continuation_lane_rulepack_latest.json"
DEFAULT_LANE_VALIDATION_PATH = REPORTS_DIR / "btst_tplus2_continuation_lane_validation_latest.json"
DEFAULT_WATCHLIST_EXECUTION_PATH = REPORTS_DIR / "btst_tplus2_continuation_watchlist_execution_latest.json"
DEFAULT_PROMOTION_REVIEW_PATH = REPORTS_DIR / "btst_tplus2_continuation_promotion_review_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_tplus2_continuation_eligible_gate_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_tplus2_continuation_eligible_gate_latest.md"


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _build_eligible_gate(
    lane_rulepack: dict[str, Any],
    lane_validation: dict[str, Any],
    watchlist_execution: dict[str, Any],
    promotion_review: dict[str, Any],
) -> dict[str, Any]:
    lane_rules = dict(lane_rulepack.get("lane_rules") or {})
    raw_eligible_tickers = [str(item) for item in list(lane_rulepack.get("eligible_tickers") or []) if str(item).strip()]
    focus_ticker = str(watchlist_execution.get("focus_ticker") or promotion_review.get("focus_ticker") or "")
    adopted_watch_row = dict(watchlist_execution.get("adopted_watch_row") or {})
    aggregate_surface_summary = dict(lane_validation.get("aggregate_surface_summary") or {})
    support_count = sum(1 for item in list(lane_validation.get("per_window_summaries") or []) if str(item.get("window_verdict") or "") == "supports_tplus2_lane")
    window_count = len(list(lane_validation.get("per_window_summaries") or []))
    support_ratio = round(support_count / window_count, 4) if window_count else 0.0
    comparison_summary = dict(promotion_review.get("comparison_summary") or {})

    gate_blockers: list[str] = []
    if not focus_ticker:
        gate_blockers.append("missing_focus_ticker")
    if str(watchlist_execution.get("execution_verdict") or "") not in {"watchlist_extension_applied", "watchlist_extension_already_applied"}:
        gate_blockers.append("watchlist_execution_not_ready")
    if str(promotion_review.get("promotion_review_verdict") or "") != "watch_review_ready":
        gate_blockers.append("promotion_review_not_ready")
    if not adopted_watch_row:
        gate_blockers.append("missing_adopted_watch_row")
    if focus_ticker and focus_ticker in raw_eligible_tickers:
        gate_blockers.append("focus_already_eligible")
    if support_count < 4:
        gate_blockers.append("insufficient_lane_support_windows")
    if support_ratio < 0.75:
        gate_blockers.append("lane_support_ratio_too_low")
    if float(adopted_watch_row.get("recent_support_ratio") or 0.0) < 0.75:
        gate_blockers.append("focus_recent_support_too_low")
    if int(adopted_watch_row.get("recent_supporting_window_count") or 0) < 4:
        gate_blockers.append("focus_recent_window_count_too_low")
    if float(adopted_watch_row.get("next_close_positive_rate") or 0.0) < 0.75:
        gate_blockers.append("focus_next_close_too_weak")
    if float(adopted_watch_row.get("t_plus_2_close_positive_rate") or 0.0) < 0.75:
        gate_blockers.append("focus_t_plus_2_positive_rate_too_low")
    if float(adopted_watch_row.get("t_plus_2_close_return_mean") or 0.0) < float(dict(aggregate_surface_summary.get("t_plus_2_close_return_distribution") or {}).get("mean") or 0.0):
        gate_blockers.append("focus_t_plus_2_mean_below_lane")
    if float(comparison_summary.get("t_plus_2_mean_gap_vs_watch") or 0.0) <= 0.0:
        gate_blockers.append("focus_not_outperforming_watch")
    if bool(lane_rules.get("block_from_default_btst_tradeable_surface")) is not True:
        gate_blockers.append("default_surface_block_missing")

    if gate_blockers:
        gate_verdict = "hold_eligible_promotion"
        operator_action = "keep_eligible_unchanged"
    else:
        gate_verdict = "approve_eligible_promotion"
        operator_action = "append_focus_to_eligible"

    recommendation = (
        f"Approve {focus_ticker} as an additional effective eligible continuation ticker while keeping the lane isolated from default BTST."
        if gate_verdict == "approve_eligible_promotion"
        else "Hold eligible promotion until lane support and adopted-watch quality remain strong enough for a stricter continuation promotion."
    )

    return {
        "focus_ticker": focus_ticker or None,
        "gate_verdict": gate_verdict,
        "gate_blockers": gate_blockers,
        "raw_eligible_tickers": raw_eligible_tickers,
        "lane_support_window_count": support_count,
        "lane_window_count": window_count,
        "lane_support_ratio": support_ratio,
        "focus_recent_support_ratio": adopted_watch_row.get("recent_support_ratio"),
        "focus_recent_supporting_window_count": adopted_watch_row.get("recent_supporting_window_count"),
        "focus_t_plus_2_close_return_mean": adopted_watch_row.get("t_plus_2_close_return_mean"),
        "lane_t_plus_2_close_return_mean": dict(aggregate_surface_summary.get("t_plus_2_close_return_distribution") or {}).get("mean"),
        "focus_t_plus_2_mean_gap_vs_watch": comparison_summary.get("t_plus_2_mean_gap_vs_watch"),
        "operator_action": operator_action,
        "execution_mode": "manual_eligible_overlay",
        "recommendation": recommendation,
    }


def generate_btst_tplus2_continuation_eligible_gate(
    *,
    lane_rulepack_path: str | Path,
    lane_validation_path: str | Path,
    watchlist_execution_path: str | Path,
    promotion_review_path: str | Path,
) -> dict[str, Any]:
    lane_rulepack = _load_json(lane_rulepack_path)
    lane_validation = _load_json(lane_validation_path)
    watchlist_execution = _load_json(watchlist_execution_path)
    promotion_review = _load_json(promotion_review_path)
    analysis = _build_eligible_gate(lane_rulepack, lane_validation, watchlist_execution, promotion_review)
    analysis["source_reports"] = {
        "lane_rulepack": str(Path(lane_rulepack_path).expanduser().resolve()),
        "lane_validation": str(Path(lane_validation_path).expanduser().resolve()),
        "watchlist_execution": str(Path(watchlist_execution_path).expanduser().resolve()),
        "promotion_review": str(Path(promotion_review_path).expanduser().resolve()),
    }
    return analysis


def render_btst_tplus2_continuation_eligible_gate_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST T+2 Continuation Eligible Gate")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- focus_ticker: {analysis['focus_ticker']}")
    lines.append(f"- gate_verdict: {analysis['gate_verdict']}")
    lines.append(f"- gate_blockers: {analysis['gate_blockers']}")
    lines.append(f"- raw_eligible_tickers: {analysis['raw_eligible_tickers']}")
    lines.append(f"- lane_support_window_count: {analysis['lane_support_window_count']}")
    lines.append(f"- lane_window_count: {analysis['lane_window_count']}")
    lines.append(f"- lane_support_ratio: {analysis['lane_support_ratio']}")
    lines.append(f"- focus_recent_support_ratio: {analysis['focus_recent_support_ratio']}")
    lines.append(f"- focus_recent_supporting_window_count: {analysis['focus_recent_supporting_window_count']}")
    lines.append(f"- focus_t_plus_2_close_return_mean: {analysis['focus_t_plus_2_close_return_mean']}")
    lines.append(f"- lane_t_plus_2_close_return_mean: {analysis['lane_t_plus_2_close_return_mean']}")
    lines.append(f"- focus_t_plus_2_mean_gap_vs_watch: {analysis['focus_t_plus_2_mean_gap_vs_watch']}")
    lines.append(f"- operator_action: {analysis['operator_action']}")
    lines.append(f"- execution_mode: {analysis['execution_mode']}")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a strict eligible gate for continuation-lane promotions.")
    parser.add_argument("--lane-rulepack-path", default=str(DEFAULT_LANE_RULEPACK_PATH))
    parser.add_argument("--lane-validation-path", default=str(DEFAULT_LANE_VALIDATION_PATH))
    parser.add_argument("--watchlist-execution-path", default=str(DEFAULT_WATCHLIST_EXECUTION_PATH))
    parser.add_argument("--promotion-review-path", default=str(DEFAULT_PROMOTION_REVIEW_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = generate_btst_tplus2_continuation_eligible_gate(
        lane_rulepack_path=args.lane_rulepack_path,
        lane_validation_path=args.lane_validation_path,
        watchlist_execution_path=args.watchlist_execution_path,
        promotion_review_path=args.promotion_review_path,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_tplus2_continuation_eligible_gate_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
