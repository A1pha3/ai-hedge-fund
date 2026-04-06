from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPORTS_DIR = Path("data/reports")
DEFAULT_OBSERVATION_POOL_PATH = REPORTS_DIR / "btst_tplus2_continuation_observation_pool_latest.json"
DEFAULT_LANE_RULEPACK_PATH = REPORTS_DIR / "btst_tplus2_continuation_lane_rulepack_latest.json"
DEFAULT_LANE_VALIDATION_PATH = REPORTS_DIR / "btst_tplus2_continuation_lane_validation_latest.json"
DEFAULT_WATCHLIST_VALIDATION_PATH = REPORTS_DIR / "btst_tplus2_near_cluster_dossier_latest.json"
DEFAULT_PROMOTION_REVIEW_PATH = REPORTS_DIR / "btst_tplus2_continuation_promotion_review_latest.json"
DEFAULT_PROMOTION_GATE_PATH = REPORTS_DIR / "btst_tplus2_continuation_promotion_gate_latest.json"
DEFAULT_WATCHLIST_EXECUTION_PATH = REPORTS_DIR / "btst_tplus2_continuation_watchlist_execution_latest.json"
DEFAULT_ELIGIBLE_GATE_PATH = REPORTS_DIR / "btst_tplus2_continuation_eligible_gate_latest.json"
DEFAULT_ELIGIBLE_EXECUTION_PATH = REPORTS_DIR / "btst_tplus2_continuation_eligible_execution_latest.json"
DEFAULT_EXECUTION_GATE_PATH = REPORTS_DIR / "btst_tplus2_continuation_execution_gate_latest.json"
DEFAULT_EXECUTION_OVERLAY_PATH = REPORTS_DIR / "btst_tplus2_continuation_execution_overlay_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_tplus2_continuation_governance_board_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_tplus2_continuation_governance_board_latest.md"


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _load_optional_json(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return {}
    return json.loads(resolved.read_text(encoding="utf-8"))


def generate_btst_tplus2_continuation_governance_board(
    observation_pool_path: str | Path,
    *,
    lane_rulepack_path: str | Path,
    lane_validation_path: str | Path,
    watchlist_validation_path: str | Path | None = DEFAULT_WATCHLIST_VALIDATION_PATH,
    promotion_review_path: str | Path | None = DEFAULT_PROMOTION_REVIEW_PATH,
    promotion_gate_path: str | Path | None = DEFAULT_PROMOTION_GATE_PATH,
    watchlist_execution_path: str | Path | None = DEFAULT_WATCHLIST_EXECUTION_PATH,
    eligible_gate_path: str | Path | None = DEFAULT_ELIGIBLE_GATE_PATH,
    eligible_execution_path: str | Path | None = DEFAULT_ELIGIBLE_EXECUTION_PATH,
    execution_gate_path: str | Path | None = DEFAULT_EXECUTION_GATE_PATH,
    execution_overlay_path: str | Path | None = DEFAULT_EXECUTION_OVERLAY_PATH,
) -> dict[str, Any]:
    observation_pool = _load_json(observation_pool_path)
    lane_rulepack = _load_json(lane_rulepack_path)
    lane_validation = _load_json(lane_validation_path)
    watchlist_validation = _load_optional_json(watchlist_validation_path)
    promotion_review = _load_optional_json(promotion_review_path)
    promotion_gate = _load_optional_json(promotion_gate_path)
    watchlist_execution = _load_optional_json(watchlist_execution_path)
    eligible_gate = _load_optional_json(eligible_gate_path)
    eligible_execution = _load_optional_json(eligible_execution_path)
    execution_gate = _load_optional_json(execution_gate_path)
    execution_overlay = _load_optional_json(execution_overlay_path)
    lane_rules = dict(lane_rulepack.get("lane_rules") or {})
    lane_stage = lane_rules.get("lane_stage", lane_rulepack.get("lane_stage"))
    capital_mode = lane_rules.get("capital_mode", lane_rulepack.get("capital_mode"))

    entries = list(observation_pool.get("entries") or [])
    rulepack_eligible_tickers = list(lane_rulepack.get("eligible_tickers") or lane_validation.get("eligible_tickers") or [])
    eligible_tickers = list(eligible_execution.get("effective_eligible_tickers") or rulepack_eligible_tickers)
    rulepack_watchlist_tickers = list(lane_rulepack.get("watchlist_tickers") or [])
    watchlist_tickers = list(watchlist_execution.get("effective_watchlist_tickers") or rulepack_watchlist_tickers)
    validation_windows = list(lane_validation.get("per_window_summaries") or [])
    support_count = sum(1 for item in validation_windows if str(item.get("window_verdict") or "") == "supports_tplus2_lane")
    mixed_count = len(validation_windows) - support_count
    watchlist_validation_status = str(watchlist_validation.get("recent_validation_verdict") or "watchlist_validation_missing")
    recent_supporting_window_count = int(watchlist_validation.get("recent_supporting_window_count") or 0)
    recent_window_count = int(watchlist_validation.get("recent_window_count") or 0)
    recent_support_ratio = float(watchlist_validation.get("recent_support_ratio") or 0.0)

    if len(rulepack_eligible_tickers) <= 1 and watchlist_tickers:
        governance_status = "single_ticker_with_validation_watch"
        if watchlist_validation_status in {"recent_support_absent", "no_recent_windows", "watchlist_validation_missing"}:
            promotion_blocker = "recent_validation_pending"
        elif watchlist_validation_status in {"recent_support_thin", "recent_support_mixed"}:
            promotion_blocker = "recent_validation_thin"
        else:
            promotion_blocker = "near_cluster_only"
    elif len(rulepack_eligible_tickers) <= 1:
        governance_status = "single_ticker_observation_only"
        promotion_blocker = "peerless_cluster"
    elif mixed_count > 0:
        governance_status = "multi_ticker_but_validation_mixed"
        promotion_blocker = "validation_mixed"
    else:
        governance_status = "paper_lane_ready_for_review"
        promotion_blocker = "governance_review_pending"

    board_rows = []
    for entry in entries:
        ticker = str(entry.get("ticker") or "")
        board_rows.append(
            {
                "ticker": ticker,
                "entry_type": entry.get("entry_type"),
                "priority_score": entry.get("priority_score"),
                "lane_stage": lane_stage,
                "capital_mode": capital_mode,
                "promotion_blocker": promotion_blocker,
                "watchlist_validation_status": watchlist_validation_status if str(entry.get("entry_type") or "") == "near_cluster_watch" else None,
                "recent_supporting_window_count": recent_supporting_window_count if str(entry.get("entry_type") or "") == "near_cluster_watch" else None,
                "recent_window_count": recent_window_count if str(entry.get("entry_type") or "") == "near_cluster_watch" else None,
                "recent_support_ratio": recent_support_ratio if str(entry.get("entry_type") or "") == "near_cluster_watch" else None,
                "next_step": (
                    "Validate this near-cluster watch candidate across fresh windows before promoting it into lane eligibility."
                    if str(entry.get("entry_type") or "") == "near_cluster_watch" and promotion_blocker != "near_cluster_only"
                    else (
                        "Keep this near-cluster watch candidate outside eligible_tickers until a strict-peer upgrade appears."
                        if str(entry.get("entry_type") or "") == "near_cluster_watch"
                        else "Accumulate more windows and a second same-cluster peer before considering any paper execution promotion."
                    )
                ),
                "t_plus_2_close_positive_rate": entry.get("t_plus_2_close_positive_rate"),
                "t_plus_2_close_return_mean": entry.get("t_plus_2_close_return_mean"),
                "next_close_positive_rate": entry.get("next_close_positive_rate"),
            }
        )
    existing_row_keys = {(str(row.get("ticker") or ""), str(row.get("entry_type") or "")) for row in board_rows}
    adopted_watch_row = dict(watchlist_execution.get("adopted_watch_row") or {})
    adopted_ticker = str(adopted_watch_row.get("ticker") or "")
    adopted_watch_type = str(adopted_watch_row.get("entry_type") or "")
    if adopted_ticker and (adopted_ticker, adopted_watch_type) not in existing_row_keys:
        board_rows.append(adopted_watch_row)
        existing_row_keys.add((adopted_ticker, adopted_watch_type))
    adopted_eligible_row = dict(eligible_execution.get("adopted_eligible_row") or {})
    adopted_eligible_ticker = str(adopted_eligible_row.get("ticker") or "")
    adopted_eligible_type = str(adopted_eligible_row.get("entry_type") or "")
    if adopted_eligible_ticker and (adopted_eligible_ticker, adopted_eligible_type) not in existing_row_keys:
        board_rows.append(adopted_eligible_row)
        existing_row_keys.add((adopted_eligible_ticker, adopted_eligible_type))
    adopted_execution_row = dict(execution_overlay.get("adopted_execution_row") or {})
    adopted_execution_ticker = str(adopted_execution_row.get("ticker") or "")
    adopted_execution_type = str(adopted_execution_row.get("entry_type") or "")
    if adopted_execution_ticker and (adopted_execution_ticker, adopted_execution_type) not in existing_row_keys:
        board_rows.append(adopted_execution_row)

    recommendation = (
        f"Current continuation governance status is {governance_status}. "
        f"Keep the lane at {lane_stage} / {capital_mode} with effective_eligible_tickers={eligible_tickers}. "
        f"Validation support windows={support_count}, mixed windows={mixed_count}, "
        f"watchlist_validation_status={watchlist_validation_status}, recent_support={recent_supporting_window_count}/{recent_window_count}; "
        f"focus promotion gate={promotion_gate.get('gate_verdict')} eligible_gate={eligible_gate.get('gate_verdict')} execution_gate={execution_gate.get('gate_verdict')}; do not merge this lane into default BTST."
    )

    return {
        "source_reports": {
            "observation_pool": str(Path(observation_pool_path).expanduser().resolve()),
            "lane_rulepack": str(Path(lane_rulepack_path).expanduser().resolve()),
            "lane_validation": str(Path(lane_validation_path).expanduser().resolve()),
            "watchlist_validation": str(Path(watchlist_validation_path).expanduser().resolve()) if watchlist_validation_path is not None else None,
            "promotion_gate": str(Path(promotion_gate_path).expanduser().resolve()) if promotion_gate_path is not None else None,
            "watchlist_execution": str(Path(watchlist_execution_path).expanduser().resolve()) if watchlist_execution_path is not None else None,
            "eligible_gate": str(Path(eligible_gate_path).expanduser().resolve()) if eligible_gate_path is not None else None,
            "eligible_execution": str(Path(eligible_execution_path).expanduser().resolve()) if eligible_execution_path is not None else None,
            "execution_gate": str(Path(execution_gate_path).expanduser().resolve()) if execution_gate_path is not None else None,
            "execution_overlay": str(Path(execution_overlay_path).expanduser().resolve()) if execution_overlay_path is not None else None,
        },
        "governance_status": governance_status,
        "promotion_blocker": promotion_blocker,
        "eligible_tickers": eligible_tickers,
        "rulepack_eligible_tickers": rulepack_eligible_tickers,
        "watchlist_tickers": watchlist_tickers,
        "rulepack_watchlist_tickers": rulepack_watchlist_tickers,
        "validation_support_window_count": support_count,
        "validation_mixed_window_count": mixed_count,
        "watchlist_validation_status": watchlist_validation_status,
        "recent_supporting_window_count": recent_supporting_window_count,
        "recent_window_count": recent_window_count,
        "recent_support_ratio": recent_support_ratio,
        "focus_promotion_review_verdict": promotion_review.get("promotion_review_verdict"),
        "focus_promotion_blockers": promotion_review.get("promotion_blockers"),
        "focus_promotion_ticker": promotion_review.get("focus_ticker"),
        "focus_promotion_gate_verdict": promotion_gate.get("gate_verdict"),
        "focus_promotion_gate_blockers": promotion_gate.get("gate_blockers"),
        "focus_promotion_gate_action": promotion_gate.get("operator_action"),
        "focus_promotion_gate_watchlist": promotion_gate.get("proposed_watchlist_tickers"),
        "focus_watchlist_execution_verdict": watchlist_execution.get("execution_verdict"),
        "focus_watchlist_execution_added": watchlist_execution.get("added_watchlist_tickers"),
        "focus_eligible_gate_verdict": eligible_gate.get("gate_verdict"),
        "focus_eligible_gate_blockers": eligible_gate.get("gate_blockers"),
        "focus_eligible_gate_action": eligible_gate.get("operator_action"),
        "focus_eligible_execution_verdict": eligible_execution.get("execution_verdict"),
        "focus_eligible_execution_added": eligible_execution.get("added_eligible_tickers"),
        "focus_execution_gate_verdict": execution_gate.get("gate_verdict"),
        "focus_execution_gate_blockers": execution_gate.get("gate_blockers"),
        "focus_execution_gate_action": execution_gate.get("operator_action"),
        "focus_execution_overlay_verdict": execution_overlay.get("execution_verdict"),
        "focus_execution_overlay_added": execution_overlay.get("added_execution_candidates"),
        "board_rows": board_rows,
        "recommendation": recommendation,
    }


def render_btst_tplus2_continuation_governance_board_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST T+2 Continuation Governance Board")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- governance_status: {analysis['governance_status']}")
    lines.append(f"- promotion_blocker: {analysis['promotion_blocker']}")
    lines.append(f"- eligible_tickers: {analysis['eligible_tickers']}")
    lines.append(f"- rulepack_eligible_tickers: {analysis.get('rulepack_eligible_tickers')}")
    lines.append(f"- watchlist_tickers: {analysis.get('watchlist_tickers')}")
    lines.append(f"- rulepack_watchlist_tickers: {analysis.get('rulepack_watchlist_tickers')}")
    lines.append(f"- validation_support_window_count: {analysis['validation_support_window_count']}")
    lines.append(f"- validation_mixed_window_count: {analysis['validation_mixed_window_count']}")
    lines.append(f"- watchlist_validation_status: {analysis['watchlist_validation_status']}")
    lines.append(f"- recent_supporting_window_count: {analysis['recent_supporting_window_count']}")
    lines.append(f"- recent_window_count: {analysis['recent_window_count']}")
    lines.append(f"- recent_support_ratio: {analysis['recent_support_ratio']}")
    lines.append(f"- focus_promotion_ticker: {analysis.get('focus_promotion_ticker')}")
    lines.append(f"- focus_promotion_review_verdict: {analysis.get('focus_promotion_review_verdict')}")
    lines.append(f"- focus_promotion_blockers: {analysis.get('focus_promotion_blockers')}")
    lines.append(f"- focus_promotion_gate_verdict: {analysis.get('focus_promotion_gate_verdict')}")
    lines.append(f"- focus_promotion_gate_blockers: {analysis.get('focus_promotion_gate_blockers')}")
    lines.append(f"- focus_promotion_gate_action: {analysis.get('focus_promotion_gate_action')}")
    lines.append(f"- focus_promotion_gate_watchlist: {analysis.get('focus_promotion_gate_watchlist')}")
    lines.append(f"- focus_watchlist_execution_verdict: {analysis.get('focus_watchlist_execution_verdict')}")
    lines.append(f"- focus_watchlist_execution_added: {analysis.get('focus_watchlist_execution_added')}")
    lines.append(f"- focus_eligible_gate_verdict: {analysis.get('focus_eligible_gate_verdict')}")
    lines.append(f"- focus_eligible_gate_blockers: {analysis.get('focus_eligible_gate_blockers')}")
    lines.append(f"- focus_eligible_gate_action: {analysis.get('focus_eligible_gate_action')}")
    lines.append(f"- focus_eligible_execution_verdict: {analysis.get('focus_eligible_execution_verdict')}")
    lines.append(f"- focus_eligible_execution_added: {analysis.get('focus_eligible_execution_added')}")
    lines.append(f"- focus_execution_gate_verdict: {analysis.get('focus_execution_gate_verdict')}")
    lines.append(f"- focus_execution_gate_blockers: {analysis.get('focus_execution_gate_blockers')}")
    lines.append(f"- focus_execution_gate_action: {analysis.get('focus_execution_gate_action')}")
    lines.append(f"- focus_execution_overlay_verdict: {analysis.get('focus_execution_overlay_verdict')}")
    lines.append(f"- focus_execution_overlay_added: {analysis.get('focus_execution_overlay_added')}")
    lines.append("")
    lines.append("## Board")
    for row in analysis["board_rows"]:
        lines.append(
            f"- ticker={row['ticker']} entry_type={row['entry_type']} lane_stage={row['lane_stage']} capital_mode={row['capital_mode']} "
            f"priority_score={row['priority_score']} t_plus_2_close_positive_rate={row['t_plus_2_close_positive_rate']} "
            f"t_plus_2_close_return_mean={row['t_plus_2_close_return_mean']} next_close_positive_rate={row['next_close_positive_rate']} "
            f"watchlist_validation_status={row.get('watchlist_validation_status')} recent_supporting_window_count={row.get('recent_supporting_window_count')} "
            f"recent_window_count={row.get('recent_window_count')} recent_support_ratio={row.get('recent_support_ratio')}"
        )
        lines.append(f"  next_step: {row['next_step']}")
    if not analysis["board_rows"]:
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a governance board for the BTST T+2 continuation lane.")
    parser.add_argument("--observation-pool", default=str(DEFAULT_OBSERVATION_POOL_PATH))
    parser.add_argument("--lane-rulepack", default=str(DEFAULT_LANE_RULEPACK_PATH))
    parser.add_argument("--lane-validation", default=str(DEFAULT_LANE_VALIDATION_PATH))
    parser.add_argument("--watchlist-validation", default=str(DEFAULT_WATCHLIST_VALIDATION_PATH))
    parser.add_argument("--promotion-review", default=str(DEFAULT_PROMOTION_REVIEW_PATH))
    parser.add_argument("--promotion-gate", default=str(DEFAULT_PROMOTION_GATE_PATH))
    parser.add_argument("--watchlist-execution", default=str(DEFAULT_WATCHLIST_EXECUTION_PATH))
    parser.add_argument("--eligible-gate", default=str(DEFAULT_ELIGIBLE_GATE_PATH))
    parser.add_argument("--eligible-execution", default=str(DEFAULT_ELIGIBLE_EXECUTION_PATH))
    parser.add_argument("--execution-gate", default=str(DEFAULT_EXECUTION_GATE_PATH))
    parser.add_argument("--execution-overlay", default=str(DEFAULT_EXECUTION_OVERLAY_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = generate_btst_tplus2_continuation_governance_board(
        args.observation_pool,
        lane_rulepack_path=args.lane_rulepack,
        lane_validation_path=args.lane_validation,
        watchlist_validation_path=args.watchlist_validation,
        promotion_review_path=args.promotion_review,
        promotion_gate_path=args.promotion_gate,
        watchlist_execution_path=args.watchlist_execution,
        eligible_gate_path=args.eligible_gate,
        eligible_execution_path=args.eligible_execution,
        execution_gate_path=args.execution_gate,
        execution_overlay_path=args.execution_overlay,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_tplus2_continuation_governance_board_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
