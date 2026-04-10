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


def _resolve_watchlist_validation(
    watchlist_validation_path: str | Path | None,
    *,
    promotion_review_path: str | Path | None,
    watchlist_execution_path: str | Path | None,
) -> tuple[Path | None, dict[str, Any]]:
    initial_path = Path(watchlist_validation_path or DEFAULT_WATCHLIST_VALIDATION_PATH).expanduser().resolve()
    initial_payload = _load_optional_json(initial_path)
    promotion_review = _load_optional_json(promotion_review_path)
    watchlist_execution = _load_optional_json(watchlist_execution_path)
    focus_ticker = str(promotion_review.get("focus_ticker") or watchlist_execution.get("focus_ticker") or "").strip()
    if not focus_ticker:
        return (initial_path if initial_path.exists() else None), initial_payload
    if str(initial_payload.get("candidate_ticker") or "").strip() == focus_ticker:
        return (initial_path if initial_path.exists() else None), initial_payload
    candidate_path = initial_path.parent / f"btst_tplus2_candidate_dossier_{focus_ticker}_latest.json"
    candidate_payload = _load_optional_json(candidate_path)
    if candidate_payload:
        return candidate_path, candidate_payload
    return (initial_path if initial_path.exists() else None), initial_payload


def _build_governance_context(
    observation_pool_path: str | Path,
    *,
    lane_rulepack_path: str | Path,
    lane_validation_path: str | Path,
    watchlist_validation_path: str | Path | None,
    promotion_review_path: str | Path | None,
    promotion_gate_path: str | Path | None,
    watchlist_execution_path: str | Path | None,
    eligible_gate_path: str | Path | None,
    eligible_execution_path: str | Path | None,
    execution_gate_path: str | Path | None,
    execution_overlay_path: str | Path | None,
) -> dict[str, Any]:
    observation_pool = _load_json(observation_pool_path)
    lane_rulepack = _load_json(lane_rulepack_path)
    lane_validation = _load_json(lane_validation_path)
    resolved_watchlist_validation_path, watchlist_validation = _resolve_watchlist_validation(
        watchlist_validation_path,
        promotion_review_path=promotion_review_path,
        watchlist_execution_path=watchlist_execution_path,
    )
    promotion_review = _load_optional_json(promotion_review_path)
    promotion_gate = _load_optional_json(promotion_gate_path)
    watchlist_execution = _load_optional_json(watchlist_execution_path)
    eligible_gate = _load_optional_json(eligible_gate_path)
    eligible_execution = _load_optional_json(eligible_execution_path)
    execution_gate = _load_optional_json(execution_gate_path)
    execution_overlay = _load_optional_json(execution_overlay_path)
    lane_rules = dict(lane_rulepack.get("lane_rules") or {})
    validation_windows = list(lane_validation.get("per_window_summaries") or [])
    support_count = sum(1 for item in validation_windows if str(item.get("window_verdict") or "") == "supports_tplus2_lane")
    return {
        "observation_pool": observation_pool,
        "lane_rulepack": lane_rulepack,
        "lane_validation": lane_validation,
        "resolved_watchlist_validation_path": resolved_watchlist_validation_path,
        "watchlist_validation": watchlist_validation,
        "promotion_review": promotion_review,
        "promotion_gate": promotion_gate,
        "watchlist_execution": watchlist_execution,
        "eligible_gate": eligible_gate,
        "eligible_execution": eligible_execution,
        "execution_gate": execution_gate,
        "execution_overlay": execution_overlay,
        "lane_stage": lane_rules.get("lane_stage", lane_rulepack.get("lane_stage")),
        "capital_mode": lane_rules.get("capital_mode", lane_rulepack.get("capital_mode")),
        "focus_ticker": str(
            promotion_review.get("focus_ticker")
            or watchlist_execution.get("focus_ticker")
            or eligible_execution.get("focus_ticker")
            or execution_overlay.get("focus_ticker")
            or ""
        ).strip(),
        "merge_review_ready": str(promotion_review.get("promotion_review_verdict") or "").strip() == "ready_for_default_btst_merge_review",
        "entries": list(observation_pool.get("entries") or []),
        "rulepack_eligible_tickers": list(lane_rulepack.get("eligible_tickers") or lane_validation.get("eligible_tickers") or []),
        "rulepack_watchlist_tickers": list(lane_rulepack.get("watchlist_tickers") or []),
        "support_count": support_count,
        "mixed_count": len(validation_windows) - support_count,
        "watchlist_validation_status": str(
            watchlist_validation.get("recent_validation_verdict")
            or watchlist_validation.get("recent_tier_verdict")
            or "watchlist_validation_missing"
        ),
        "recent_supporting_window_count": int(
            watchlist_validation.get("recent_supporting_window_count")
            or watchlist_validation.get("recent_tier_window_count")
            or 0
        ),
        "recent_window_count": int(watchlist_validation.get("recent_window_count") or 0),
        "recent_support_ratio": float(
            watchlist_validation.get("recent_support_ratio")
            or watchlist_validation.get("recent_tier_ratio")
            or 0.0
        ),
    }


def _resolve_governance_status(context: dict[str, Any]) -> tuple[str, str]:
    if context["merge_review_ready"]:
        return "ready_for_default_btst_merge_review", "default_btst_merge_review_pending"
    if len(context["rulepack_eligible_tickers"]) <= 1 and context["watchlist_tickers"]:
        if context["watchlist_validation_status"] in {"recent_support_absent", "no_recent_windows", "watchlist_validation_missing"}:
            return "single_ticker_with_validation_watch", "recent_validation_pending"
        if context["watchlist_validation_status"] in {"recent_support_thin", "recent_support_mixed"}:
            return "single_ticker_with_validation_watch", "recent_validation_thin"
        return "single_ticker_with_validation_watch", "near_cluster_only"
    if len(context["rulepack_eligible_tickers"]) <= 1:
        return "single_ticker_observation_only", "peerless_cluster"
    if context["mixed_count"] > 0:
        return "multi_ticker_but_validation_mixed", "validation_mixed"
    return "paper_lane_ready_for_review", "governance_review_pending"


def _resolve_governance_next_step(entry_type: str, *, merge_review_ready: bool, focus_ticker: str, ticker: str, promotion_blocker: str) -> str:
    if merge_review_ready and ticker == focus_ticker:
        return "Escalate this focus ticker into default BTST merge review under explicit governance approval."
    if entry_type == "near_cluster_watch" and promotion_blocker != "near_cluster_only":
        return "Validate this near-cluster watch candidate across fresh windows before promoting it into lane eligibility."
    if entry_type == "near_cluster_watch":
        return "Keep this near-cluster watch candidate outside eligible_tickers until a strict-peer upgrade appears."
    return "Accumulate more windows and a second same-cluster peer before considering any paper execution promotion."


def _build_governance_board_row(
    entry: dict[str, Any],
    *,
    lane_stage: Any,
    capital_mode: Any,
    promotion_blocker: str,
    watchlist_validation_status: str,
    recent_supporting_window_count: int,
    recent_window_count: int,
    recent_support_ratio: float,
    merge_review_ready: bool,
    focus_ticker: str,
) -> dict[str, Any]:
    entry_type = str(entry.get("entry_type") or "")
    ticker = str(entry.get("ticker") or "")
    is_watch = entry_type == "near_cluster_watch"
    return {
        "ticker": ticker,
        "entry_type": entry.get("entry_type"),
        "priority_score": entry.get("priority_score"),
        "lane_stage": lane_stage,
        "capital_mode": capital_mode,
        "promotion_blocker": promotion_blocker,
        "watchlist_validation_status": watchlist_validation_status if is_watch else None,
        "recent_supporting_window_count": recent_supporting_window_count if is_watch else None,
        "recent_window_count": recent_window_count if is_watch else None,
        "recent_support_ratio": recent_support_ratio if is_watch else None,
        "next_step": _resolve_governance_next_step(
            entry_type,
            merge_review_ready=merge_review_ready,
            focus_ticker=focus_ticker,
            ticker=ticker,
            promotion_blocker=promotion_blocker,
        ),
        "t_plus_2_close_positive_rate": entry.get("t_plus_2_close_positive_rate"),
        "t_plus_2_close_return_mean": entry.get("t_plus_2_close_return_mean"),
        "next_close_positive_rate": entry.get("next_close_positive_rate"),
    }


def _append_unique_board_row(board_rows: list[dict[str, Any]], existing_row_keys: set[tuple[str, str]], row: dict[str, Any]) -> None:
    ticker = str(row.get("ticker") or "")
    entry_type = str(row.get("entry_type") or "")
    if ticker and (ticker, entry_type) not in existing_row_keys:
        board_rows.append(row)
        existing_row_keys.add((ticker, entry_type))


def _build_governance_board_rows(context: dict[str, Any], *, promotion_blocker: str) -> list[dict[str, Any]]:
    board_rows = [
        _build_governance_board_row(
            entry,
            lane_stage=context["lane_stage"],
            capital_mode=context["capital_mode"],
            promotion_blocker=promotion_blocker,
            watchlist_validation_status=context["watchlist_validation_status"],
            recent_supporting_window_count=context["recent_supporting_window_count"],
            recent_window_count=context["recent_window_count"],
            recent_support_ratio=context["recent_support_ratio"],
            merge_review_ready=context["merge_review_ready"],
            focus_ticker=context["focus_ticker"],
        )
        for entry in context["entries"]
    ]
    existing_row_keys = {(str(row.get("ticker") or ""), str(row.get("entry_type") or "")) for row in board_rows}
    _append_unique_board_row(board_rows, existing_row_keys, dict(context["watchlist_execution"].get("adopted_watch_row") or {}))
    _append_unique_board_row(board_rows, existing_row_keys, dict(context["eligible_execution"].get("adopted_eligible_row") or {}))
    _append_unique_board_row(board_rows, existing_row_keys, dict(context["execution_overlay"].get("adopted_execution_row") or {}))
    return board_rows


def _build_governance_recommendation(context: dict[str, Any], *, governance_status: str) -> str:
    return (
        f"Current continuation governance status is {governance_status}. "
        f"Keep the lane at {context['lane_stage']} / {context['capital_mode']} with effective_eligible_tickers={context['eligible_tickers']}. "
        f"Validation support windows={context['support_count']}, mixed windows={context['mixed_count']}, "
        f"watchlist_validation_status={context['watchlist_validation_status']}, recent_support={context['recent_supporting_window_count']}/{context['recent_window_count']}; "
        f"focus promotion gate={context['promotion_gate'].get('gate_verdict')} eligible_gate={context['eligible_gate'].get('gate_verdict')} execution_gate={context['execution_gate'].get('gate_verdict')}; "
        + (
            "escalate the focus ticker into default BTST merge review under explicit governance approval."
            if context["merge_review_ready"]
            else "do not merge this lane into default BTST."
        )
    )


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
    context = _build_governance_context(
        observation_pool_path,
        lane_rulepack_path=lane_rulepack_path,
        lane_validation_path=lane_validation_path,
        watchlist_validation_path=watchlist_validation_path,
        promotion_review_path=promotion_review_path,
        promotion_gate_path=promotion_gate_path,
        watchlist_execution_path=watchlist_execution_path,
        eligible_gate_path=eligible_gate_path,
        eligible_execution_path=eligible_execution_path,
        execution_gate_path=execution_gate_path,
        execution_overlay_path=execution_overlay_path,
    )
    context["eligible_tickers"] = list(context["eligible_execution"].get("effective_eligible_tickers") or context["rulepack_eligible_tickers"])
    context["watchlist_tickers"] = list(context["watchlist_execution"].get("effective_watchlist_tickers") or context["rulepack_watchlist_tickers"])
    governance_status, promotion_blocker = _resolve_governance_status(context)
    board_rows = _build_governance_board_rows(context, promotion_blocker=promotion_blocker)

    return {
        "source_reports": {
            "observation_pool": str(Path(observation_pool_path).expanduser().resolve()),
            "lane_rulepack": str(Path(lane_rulepack_path).expanduser().resolve()),
            "lane_validation": str(Path(lane_validation_path).expanduser().resolve()),
            "watchlist_validation": str(context["resolved_watchlist_validation_path"]) if context["resolved_watchlist_validation_path"] is not None else None,
            "promotion_gate": str(Path(promotion_gate_path).expanduser().resolve()) if promotion_gate_path is not None else None,
            "watchlist_execution": str(Path(watchlist_execution_path).expanduser().resolve()) if watchlist_execution_path is not None else None,
            "eligible_gate": str(Path(eligible_gate_path).expanduser().resolve()) if eligible_gate_path is not None else None,
            "eligible_execution": str(Path(eligible_execution_path).expanduser().resolve()) if eligible_execution_path is not None else None,
            "execution_gate": str(Path(execution_gate_path).expanduser().resolve()) if execution_gate_path is not None else None,
            "execution_overlay": str(Path(execution_overlay_path).expanduser().resolve()) if execution_overlay_path is not None else None,
        },
        "focus_ticker": context["focus_ticker"] or None,
        "governance_status": governance_status,
        "promotion_blocker": promotion_blocker,
        "eligible_tickers": context["eligible_tickers"],
        "rulepack_eligible_tickers": context["rulepack_eligible_tickers"],
        "watchlist_tickers": context["watchlist_tickers"],
        "rulepack_watchlist_tickers": context["rulepack_watchlist_tickers"],
        "validation_support_window_count": context["support_count"],
        "validation_mixed_window_count": context["mixed_count"],
        "watchlist_validation_status": context["watchlist_validation_status"],
        "recent_supporting_window_count": context["recent_supporting_window_count"],
        "recent_window_count": context["recent_window_count"],
        "recent_support_ratio": context["recent_support_ratio"],
        "focus_promotion_review_verdict": context["promotion_review"].get("promotion_review_verdict"),
        "focus_promotion_blockers": context["promotion_review"].get("promotion_blockers"),
        "focus_promotion_ticker": context["promotion_review"].get("focus_ticker"),
        "focus_promotion_gate_verdict": context["promotion_gate"].get("gate_verdict"),
        "focus_promotion_gate_blockers": context["promotion_gate"].get("gate_blockers"),
        "focus_promotion_gate_action": context["promotion_gate"].get("operator_action"),
        "focus_promotion_gate_watchlist": context["promotion_gate"].get("proposed_watchlist_tickers"),
        "focus_watchlist_execution_verdict": context["watchlist_execution"].get("execution_verdict"),
        "focus_watchlist_execution_added": context["watchlist_execution"].get("added_watchlist_tickers"),
        "focus_eligible_gate_verdict": context["eligible_gate"].get("gate_verdict"),
        "focus_eligible_gate_blockers": context["eligible_gate"].get("gate_blockers"),
        "focus_eligible_gate_action": context["eligible_gate"].get("operator_action"),
        "focus_eligible_execution_verdict": context["eligible_execution"].get("execution_verdict"),
        "focus_eligible_execution_added": context["eligible_execution"].get("added_eligible_tickers"),
        "focus_execution_gate_verdict": context["execution_gate"].get("gate_verdict"),
        "focus_execution_gate_blockers": context["execution_gate"].get("gate_blockers"),
        "focus_execution_gate_action": context["execution_gate"].get("operator_action"),
        "focus_execution_overlay_verdict": context["execution_overlay"].get("execution_verdict"),
        "focus_execution_overlay_added": context["execution_overlay"].get("added_execution_candidates"),
        "board_rows": board_rows,
        "recommendation": _build_governance_recommendation(context, governance_status=governance_status),
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
