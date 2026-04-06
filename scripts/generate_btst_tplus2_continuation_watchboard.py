from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_btst_tplus2_continuation_peer_rollup import analyze_btst_tplus2_continuation_peer_rollup
from scripts.generate_btst_tplus2_continuation_governance_board import generate_btst_tplus2_continuation_governance_board


REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_tplus2_continuation_watchboard_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_tplus2_continuation_watchboard_latest.md"
DEFAULT_WATCHLIST_VALIDATION_PATH = REPORTS_DIR / "btst_tplus2_near_cluster_dossier_latest.json"
DEFAULT_VALIDATION_QUEUE_PATH = REPORTS_DIR / "btst_tplus2_continuation_validation_queue_latest.json"
DEFAULT_PROMOTION_REVIEW_PATH = REPORTS_DIR / "btst_tplus2_continuation_promotion_review_latest.json"
DEFAULT_PROMOTION_GATE_PATH = REPORTS_DIR / "btst_tplus2_continuation_promotion_gate_latest.json"


def _load_optional_json(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return {}
    return json.loads(resolved.read_text(encoding="utf-8"))


def generate_btst_tplus2_continuation_watchboard(
    reports_root: str | Path,
    *,
    observation_pool_path: str | Path,
    lane_rulepack_path: str | Path,
    lane_validation_path: str | Path,
    watchlist_validation_path: str | Path | None = DEFAULT_WATCHLIST_VALIDATION_PATH,
    validation_queue_path: str | Path | None = DEFAULT_VALIDATION_QUEUE_PATH,
    promotion_review_path: str | Path | None = DEFAULT_PROMOTION_REVIEW_PATH,
    promotion_gate_path: str | Path | None = DEFAULT_PROMOTION_GATE_PATH,
) -> dict[str, Any]:
    governance_board = generate_btst_tplus2_continuation_governance_board(
        observation_pool_path,
        lane_rulepack_path=lane_rulepack_path,
        lane_validation_path=lane_validation_path,
        watchlist_validation_path=watchlist_validation_path,
        promotion_review_path=promotion_review_path,
        promotion_gate_path=promotion_gate_path,
    )
    rollup = analyze_btst_tplus2_continuation_peer_rollup(reports_root)
    watchlist_validation = _load_optional_json(watchlist_validation_path)
    validation_queue = _load_optional_json(validation_queue_path)
    promotion_review = _load_optional_json(promotion_review_path)
    promotion_gate = _load_optional_json(promotion_gate_path)
    watch_rows = list(governance_board.get("board_rows") or [])
    risk_flags = list(rollup.get("risk_flags") or [])
    top_candidate = dict(rollup.get("top_candidate") or {})
    if top_candidate and str(top_candidate.get("ticker") or "") == str(watchlist_validation.get("candidate_ticker") or ""):
        top_candidate["recent_validation_verdict"] = watchlist_validation.get("recent_validation_verdict")
        top_candidate["recent_supporting_window_count"] = watchlist_validation.get("recent_supporting_window_count")
        top_candidate["recent_window_count"] = watchlist_validation.get("recent_window_count")
        top_candidate["recent_support_ratio"] = watchlist_validation.get("recent_support_ratio")

    return {
        "governance_status": governance_board.get("governance_status"),
        "promotion_blocker": governance_board.get("promotion_blocker"),
        "eligible_tickers": governance_board.get("eligible_tickers"),
        "watchlist_tickers": governance_board.get("watchlist_tickers"),
        "watchlist_validation_status": governance_board.get("watchlist_validation_status"),
        "recent_supporting_window_count": governance_board.get("recent_supporting_window_count"),
        "recent_window_count": governance_board.get("recent_window_count"),
        "recent_support_ratio": governance_board.get("recent_support_ratio"),
        "rollup_verdict": rollup.get("rollup_verdict"),
        "top_candidate": top_candidate,
        "focus_validation_candidate": validation_queue.get("focus_candidate"),
        "focus_promotion_review": promotion_review,
        "focus_promotion_gate": promotion_gate,
        "validation_queue_rows": validation_queue.get("queue_rows"),
        "risk_flags": risk_flags,
        "watch_rows": watch_rows,
        "recommendation": (
            f"Watchboard status: governance={governance_board.get('governance_status')}, rollup={rollup.get('rollup_verdict')}. "
            f"Watchlist validation={governance_board.get('watchlist_validation_status')} with recent_support="
            f"{governance_board.get('recent_supporting_window_count')}/{governance_board.get('recent_window_count')}. "
            f"Focus validation candidate={dict(validation_queue.get('focus_candidate') or {}).get('ticker')} "
            f"review={promotion_review.get('promotion_review_verdict')} "
            f"gate={promotion_gate.get('gate_verdict')}. "
            "Keep anchor lane isolated, validate watchlist names separately, and do not widen default BTST."
        ),
    }


def render_btst_tplus2_continuation_watchboard_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST T+2 Continuation Watchboard")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- governance_status: {analysis['governance_status']}")
    lines.append(f"- promotion_blocker: {analysis['promotion_blocker']}")
    lines.append(f"- eligible_tickers: {analysis['eligible_tickers']}")
    lines.append(f"- watchlist_tickers: {analysis['watchlist_tickers']}")
    lines.append(f"- watchlist_validation_status: {analysis.get('watchlist_validation_status')}")
    lines.append(f"- recent_supporting_window_count: {analysis.get('recent_supporting_window_count')}")
    lines.append(f"- recent_window_count: {analysis.get('recent_window_count')}")
    lines.append(f"- recent_support_ratio: {analysis.get('recent_support_ratio')}")
    lines.append(f"- rollup_verdict: {analysis['rollup_verdict']}")
    lines.append(f"- top_candidate: {analysis['top_candidate']}")
    lines.append(f"- focus_validation_candidate: {analysis.get('focus_validation_candidate')}")
    lines.append(f"- focus_promotion_review: {analysis.get('focus_promotion_review')}")
    lines.append(f"- focus_promotion_gate: {analysis.get('focus_promotion_gate')}")
    lines.append("")
    lines.append("## Watch Rows")
    for row in list(analysis.get("watch_rows") or []):
        lines.append(
            f"- ticker={row['ticker']} entry_type={row['entry_type']} lane_stage={row['lane_stage']} "
            f"t_plus_2_close_positive_rate={row['t_plus_2_close_positive_rate']} "
            f"t_plus_2_close_return_mean={row['t_plus_2_close_return_mean']}"
        )
    if not list(analysis.get("watch_rows") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Validation Queue")
    for item in list(analysis.get("validation_queue_rows") or []):
        lines.append(
            f"- ticker={item['ticker']} priority_rank={item['priority_rank']} candidate_tier_focus={item['candidate_tier_focus']} "
            f"recent_tier_verdict={item['recent_tier_verdict']} promotion_readiness_verdict={item['promotion_readiness_verdict']}"
        )
    if not list(analysis.get("validation_queue_rows") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Risk Flags")
    for item in list(analysis.get("risk_flags") or []):
        lines.append(
            f"- ticker={item['ticker']} tier={item['tier']} reason={item['reason']} "
            f"t_plus_2_close_return_mean={item['t_plus_2_close_return_mean']}"
        )
    if not list(analysis.get("risk_flags") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a unified continuation watchboard.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR))
    parser.add_argument("--observation-pool", default=str(REPORTS_DIR / "btst_tplus2_continuation_observation_pool_latest.json"))
    parser.add_argument("--lane-rulepack", default=str(REPORTS_DIR / "btst_tplus2_continuation_lane_rulepack_latest.json"))
    parser.add_argument("--lane-validation", default=str(REPORTS_DIR / "btst_tplus2_continuation_lane_validation_latest.json"))
    parser.add_argument("--watchlist-validation", default=str(DEFAULT_WATCHLIST_VALIDATION_PATH))
    parser.add_argument("--validation-queue", default=str(DEFAULT_VALIDATION_QUEUE_PATH))
    parser.add_argument("--promotion-review", default=str(DEFAULT_PROMOTION_REVIEW_PATH))
    parser.add_argument("--promotion-gate", default=str(DEFAULT_PROMOTION_GATE_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = generate_btst_tplus2_continuation_watchboard(
        args.reports_root,
        observation_pool_path=args.observation_pool,
        lane_rulepack_path=args.lane_rulepack,
        lane_validation_path=args.lane_validation,
        watchlist_validation_path=args.watchlist_validation,
        validation_queue_path=args.validation_queue,
        promotion_review_path=args.promotion_review,
        promotion_gate_path=args.promotion_gate,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_tplus2_continuation_watchboard_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
