from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPORTS_DIR = Path("data/reports")
DEFAULT_LANE_RULEPACK_PATH = REPORTS_DIR / "btst_tplus2_continuation_lane_rulepack_latest.json"
DEFAULT_LANE_VALIDATION_PATH = REPORTS_DIR / "btst_tplus2_continuation_lane_validation_latest.json"
DEFAULT_ELIGIBLE_EXECUTION_PATH = REPORTS_DIR / "btst_tplus2_continuation_eligible_execution_latest.json"
DEFAULT_PROMOTION_REVIEW_PATH = REPORTS_DIR / "btst_tplus2_continuation_promotion_review_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_tplus2_continuation_execution_gate_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_tplus2_continuation_execution_gate_latest.md"


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _build_execution_gate_context(
    lane_rulepack: dict[str, Any],
    lane_validation: dict[str, Any],
    eligible_execution: dict[str, Any],
    promotion_review: dict[str, Any],
) -> dict[str, Any]:
    lane_rules = dict(lane_rulepack.get("lane_rules") or {})
    adopted_eligible_row = dict(eligible_execution.get("adopted_eligible_row") or {})
    aggregate_surface_summary = dict(lane_validation.get("aggregate_surface_summary") or {})
    comparison_summary = dict(promotion_review.get("comparison_summary") or {})
    windows = list(lane_validation.get("per_window_summaries") or [])
    support_count = sum(1 for item in windows if str(item.get("window_verdict") or "") == "supports_tplus2_lane")
    window_count = len(windows)
    return {
        "lane_rules": lane_rules,
        "focus_ticker": str(eligible_execution.get("focus_ticker") or promotion_review.get("focus_ticker") or ""),
        "adopted_eligible_row": adopted_eligible_row,
        "comparison_summary": comparison_summary,
        "support_count": support_count,
        "window_count": window_count,
        "support_ratio": round(support_count / window_count, 4) if window_count else 0.0,
        "governance_payoff_ready": bool(comparison_summary.get("governance_payoff_ready")),
        "focus_recent_support_ratio": float(adopted_eligible_row.get("recent_support_ratio") or 0.0),
        "focus_recent_supporting_window_count": int(adopted_eligible_row.get("recent_supporting_window_count") or 0),
        "focus_next_close_positive_rate": float(adopted_eligible_row.get("next_close_positive_rate") or 0.0),
        "focus_t_plus_2_close_positive_rate": float(adopted_eligible_row.get("t_plus_2_close_positive_rate") or 0.0),
        "focus_mean": float(adopted_eligible_row.get("t_plus_2_close_return_mean") or 0.0),
        "lane_mean": float(dict(aggregate_surface_summary.get("t_plus_2_close_return_distribution") or {}).get("mean") or 0.0),
        "eligible_execution_verdict": str(eligible_execution.get("execution_verdict") or ""),
        "focus_t_plus_2_mean_gap_vs_watch": float(comparison_summary.get("t_plus_2_mean_gap_vs_watch") or 0.0),
        "capital_mode": str(lane_rules.get("capital_mode") or lane_rulepack.get("capital_mode") or ""),
    }


def _collect_execution_gate_readiness_blockers(context: dict[str, Any]) -> list[str]:
    gate_blockers: list[str] = []
    if not context["focus_ticker"]:
        gate_blockers.append("missing_focus_ticker")
    if context["eligible_execution_verdict"] not in {"eligible_extension_applied", "eligible_extension_already_applied"}:
        gate_blockers.append("eligible_execution_not_ready")
    if not context["adopted_eligible_row"]:
        gate_blockers.append("missing_adopted_eligible_row")
    if context["support_count"] < 6:
        gate_blockers.append("insufficient_lane_support_windows")
    if context["support_ratio"] < 0.85:
        gate_blockers.append("lane_support_ratio_too_low")
    if context["focus_recent_support_ratio"] < 1.0:
        gate_blockers.append("focus_recent_support_not_perfect")
    if context["focus_recent_supporting_window_count"] < 4:
        gate_blockers.append("focus_recent_window_count_too_low")
    return gate_blockers


def _collect_execution_gate_payoff_blockers(context: dict[str, Any]) -> list[str]:
    gate_blockers: list[str] = []
    if context["focus_next_close_positive_rate"] < 0.75:
        gate_blockers.append("focus_next_close_below_execution_floor")
    if context["focus_t_plus_2_close_positive_rate"] < 0.8:
        gate_blockers.append("focus_t_plus_2_positive_rate_below_execution_floor")
    if context["focus_mean"] < context["lane_mean"]:
        gate_blockers.append("focus_t_plus_2_mean_below_lane")
    if context["focus_t_plus_2_mean_gap_vs_watch"] <= 0.0:
        gate_blockers.append("focus_not_outperforming_watch")
    if not context["governance_payoff_ready"]:
        gate_blockers.append("focus_governance_payoff_not_confirmed")
    if context["capital_mode"] != "paper_only":
        gate_blockers.append("capital_mode_not_paper_only")
    return gate_blockers


def _collect_execution_gate_blockers(context: dict[str, Any]) -> list[str]:
    return _collect_execution_gate_readiness_blockers(context) + _collect_execution_gate_payoff_blockers(context)


def _resolve_execution_gate_decision(gate_blockers: list[str]) -> tuple[str, str]:
    if gate_blockers:
        return "hold_execution_candidate", "keep_execution_overlay_unchanged"
    return "approve_execution_candidate", "append_focus_to_execution_overlay"


def _build_execution_gate_recommendation(gate_verdict: str, focus_ticker: str) -> str:
    if gate_verdict == "approve_execution_candidate":
        return f"Approve {focus_ticker} as an effective paper execution candidate for the isolated continuation lane."
    return "Hold execution-candidate promotion until the continuation lane retains stronger support and the focus ticker clears the controlled execution floor."


def _build_execution_gate(
    lane_rulepack: dict[str, Any],
    lane_validation: dict[str, Any],
    eligible_execution: dict[str, Any],
    promotion_review: dict[str, Any],
) -> dict[str, Any]:
    context = _build_execution_gate_context(lane_rulepack, lane_validation, eligible_execution, promotion_review)
    gate_blockers = _collect_execution_gate_blockers(context)
    gate_verdict, operator_action = _resolve_execution_gate_decision(gate_blockers)
    adopted_eligible_row = context["adopted_eligible_row"]

    return {
        "focus_ticker": context["focus_ticker"] or None,
        "gate_verdict": gate_verdict,
        "gate_blockers": gate_blockers,
        "lane_support_window_count": context["support_count"],
        "lane_window_count": context["window_count"],
        "lane_support_ratio": context["support_ratio"],
        "focus_recent_support_ratio": adopted_eligible_row.get("recent_support_ratio"),
        "focus_recent_supporting_window_count": adopted_eligible_row.get("recent_supporting_window_count"),
        "focus_next_close_positive_rate": adopted_eligible_row.get("next_close_positive_rate"),
        "focus_t_plus_2_close_positive_rate": adopted_eligible_row.get("t_plus_2_close_positive_rate"),
        "focus_t_plus_2_close_return_mean": adopted_eligible_row.get("t_plus_2_close_return_mean"),
        "lane_t_plus_2_close_return_mean": context["lane_mean"],
        "focus_t_plus_2_mean_gap_vs_watch": promotion_review.get("comparison_summary", {}).get("t_plus_2_mean_gap_vs_watch"),
        "governance_payoff_ready": context["governance_payoff_ready"],
        "operator_action": operator_action,
        "execution_mode": "paper_overlay_only",
        "recommendation": _build_execution_gate_recommendation(gate_verdict, context["focus_ticker"]),
    }


def generate_btst_tplus2_continuation_execution_gate(
    *,
    lane_rulepack_path: str | Path,
    lane_validation_path: str | Path,
    eligible_execution_path: str | Path,
    promotion_review_path: str | Path,
) -> dict[str, Any]:
    lane_rulepack = _load_json(lane_rulepack_path)
    lane_validation = _load_json(lane_validation_path)
    eligible_execution = _load_json(eligible_execution_path)
    promotion_review = _load_json(promotion_review_path)
    analysis = _build_execution_gate(lane_rulepack, lane_validation, eligible_execution, promotion_review)
    analysis["source_reports"] = {
        "lane_rulepack": str(Path(lane_rulepack_path).expanduser().resolve()),
        "lane_validation": str(Path(lane_validation_path).expanduser().resolve()),
        "eligible_execution": str(Path(eligible_execution_path).expanduser().resolve()),
        "promotion_review": str(Path(promotion_review_path).expanduser().resolve()),
    }
    return analysis


def render_btst_tplus2_continuation_execution_gate_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST T+2 Continuation Execution Gate")
    lines.append("")
    lines.append("## Overview")
    for key in [
        "focus_ticker",
        "gate_verdict",
        "gate_blockers",
        "lane_support_window_count",
        "lane_window_count",
        "lane_support_ratio",
        "focus_recent_support_ratio",
        "focus_recent_supporting_window_count",
        "focus_next_close_positive_rate",
        "focus_t_plus_2_close_positive_rate",
        "focus_t_plus_2_close_return_mean",
        "lane_t_plus_2_close_return_mean",
        "focus_t_plus_2_mean_gap_vs_watch",
        "operator_action",
        "execution_mode",
    ]:
        lines.append(f"- {key}: {analysis[key]}")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a strict paper execution gate for continuation-lane promotions.")
    parser.add_argument("--lane-rulepack-path", default=str(DEFAULT_LANE_RULEPACK_PATH))
    parser.add_argument("--lane-validation-path", default=str(DEFAULT_LANE_VALIDATION_PATH))
    parser.add_argument("--eligible-execution-path", default=str(DEFAULT_ELIGIBLE_EXECUTION_PATH))
    parser.add_argument("--promotion-review-path", default=str(DEFAULT_PROMOTION_REVIEW_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = generate_btst_tplus2_continuation_execution_gate(
        lane_rulepack_path=args.lane_rulepack_path,
        lane_validation_path=args.lane_validation_path,
        eligible_execution_path=args.eligible_execution_path,
        promotion_review_path=args.promotion_review_path,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_tplus2_continuation_execution_gate_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
