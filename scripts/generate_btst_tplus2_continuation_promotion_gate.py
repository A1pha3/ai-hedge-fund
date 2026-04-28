from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.generate_btst_tplus2_continuation_promotion_review import READY_PROMOTION_REVIEW_VERDICTS


REPORTS_DIR = Path("data/reports")
DEFAULT_LANE_RULEPACK_PATH = REPORTS_DIR / "btst_tplus2_continuation_lane_rulepack_latest.json"
DEFAULT_PROMOTION_REVIEW_PATH = REPORTS_DIR / "btst_tplus2_continuation_promotion_review_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_tplus2_continuation_promotion_gate_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_tplus2_continuation_promotion_gate_latest.md"


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _resolve_default_expansion_status(payload: dict[str, Any]) -> str:
    ready_tickers = [str(item).strip() for item in list(payload.get("promotion_ready_tickers") or []) if str(item).strip()]
    explicit_status = str(payload.get("default_expansion_status") or "").strip()
    if ready_tickers:
        return "ready_for_peer_promotion"
    if explicit_status:
        return explicit_status
    return "pending_peer_proof"


def _build_promotion_gate_context(lane_rulepack: dict[str, Any], promotion_review: dict[str, Any]) -> dict[str, Any]:
    lane_rules = dict(lane_rulepack.get("lane_rules") or {})
    promotion_ready_tickers = [str(item).strip() for item in list(promotion_review.get("promotion_ready_tickers") or []) if str(item).strip()]
    return {
        "focus_ticker": str(promotion_review.get("focus_ticker") or ""),
        "eligible_tickers": [str(item) for item in list(lane_rulepack.get("eligible_tickers") or []) if str(item).strip()],
        "watchlist_tickers": [str(item) for item in list(lane_rulepack.get("watchlist_tickers") or []) if str(item).strip()],
        "promotion_review_verdict": str(promotion_review.get("promotion_review_verdict") or ""),
        "promotion_review_blockers": [str(item) for item in list(promotion_review.get("promotion_blockers") or []) if str(item).strip()],
        "promotion_ready_tickers": promotion_ready_tickers,
        "default_expansion_status": _resolve_default_expansion_status(
            {
                "promotion_ready_tickers": promotion_ready_tickers,
                "default_expansion_status": promotion_review.get("default_expansion_status"),
            }
        ),
        "lane_stage": str(lane_rules.get("lane_stage") or lane_rulepack.get("lane_stage") or ""),
        "capital_mode": str(lane_rules.get("capital_mode") or lane_rulepack.get("capital_mode") or ""),
    }


def _collect_promotion_gate_blockers(context: dict[str, Any]) -> list[str]:
    gate_blockers: list[str] = []
    if not context["focus_ticker"]:
        gate_blockers.append("missing_focus_ticker")
    if context["promotion_review_verdict"] not in READY_PROMOTION_REVIEW_VERDICTS:
        gate_blockers.append("promotion_review_not_ready")
    if context["promotion_review_blockers"]:
        gate_blockers.extend(context["promotion_review_blockers"])
    if context["focus_ticker"] and context["focus_ticker"] in context["eligible_tickers"]:
        gate_blockers.append("focus_already_eligible")
    if context["lane_stage"] and context["lane_stage"] != "observation_only":
        gate_blockers.append("unexpected_lane_stage")
    if context["capital_mode"] and context["capital_mode"] != "paper_only":
        gate_blockers.append("unexpected_capital_mode")
    return gate_blockers


def _resolve_promotion_gate_decision(context: dict[str, Any], gate_blockers: list[str]) -> tuple[str, str, list[str]]:
    if context["focus_ticker"] and context["focus_ticker"] in context["watchlist_tickers"]:
        return "already_on_watchlist", "keep_watchlist_unchanged", list(context["watchlist_tickers"])
    if gate_blockers:
        return "hold_watchlist_promotion", "keep_watchlist_unchanged", list(context["watchlist_tickers"])
    return "approve_watchlist_promotion", "append_focus_to_watchlist", context["watchlist_tickers"] + [context["focus_ticker"]]


def _build_promotion_gate_recommendation(gate_verdict: str, *, focus_ticker: str, eligible_tickers: list[str]) -> str:
    if gate_verdict == "approve_watchlist_promotion":
        return (
            f"Approve {focus_ticker} as an additional near-cluster watchlist ticker while keeping "
            f"eligible_tickers={eligible_tickers} unchanged and the continuation lane isolated from default BTST."
        )
    if gate_verdict == "already_on_watchlist":
        return f"{focus_ticker} is already on watchlist_tickers; no additional governance action is required."
    return "Hold watchlist promotion and keep the focus candidate inside validation review until the gate blockers clear."


def _build_promotion_gate(lane_rulepack: dict[str, Any], promotion_review: dict[str, Any]) -> dict[str, Any]:
    context = _build_promotion_gate_context(lane_rulepack, promotion_review)
    gate_blockers = _collect_promotion_gate_blockers(context)
    gate_verdict, operator_action, proposed_watchlist_tickers = _resolve_promotion_gate_decision(context, gate_blockers)

    return {
        "focus_ticker": context["focus_ticker"] or None,
        "promotion_review_verdict": context["promotion_review_verdict"] or None,
        "promotion_review_blockers": context["promotion_review_blockers"],
        "promotion_ready_tickers": context["promotion_ready_tickers"],
        "default_expansion_status": context["default_expansion_status"],
        "gate_verdict": gate_verdict,
        "gate_blockers": gate_blockers,
        "current_watchlist_tickers": context["watchlist_tickers"],
        "proposed_watchlist_tickers": proposed_watchlist_tickers,
        "eligible_tickers": context["eligible_tickers"],
        "operator_action": operator_action,
        "execution_mode": "manual_rulepack_update",
        "recommendation": _build_promotion_gate_recommendation(
            gate_verdict,
            focus_ticker=context["focus_ticker"],
            eligible_tickers=context["eligible_tickers"],
        ),
    }


def generate_btst_tplus2_continuation_promotion_gate(
    *,
    lane_rulepack_path: str | Path,
    promotion_review_path: str | Path,
) -> dict[str, Any]:
    lane_rulepack, promotion_review = _load_promotion_gate_inputs(
        lane_rulepack_path=lane_rulepack_path,
        promotion_review_path=promotion_review_path,
    )
    analysis = _build_promotion_gate(lane_rulepack, promotion_review)
    return _attach_promotion_gate_source_reports(
        analysis=analysis,
        lane_rulepack_path=lane_rulepack_path,
        promotion_review_path=promotion_review_path,
    )


def _load_promotion_gate_inputs(
    *,
    lane_rulepack_path: str | Path,
    promotion_review_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    lane_rulepack = _load_json(lane_rulepack_path)
    promotion_review = _load_json(promotion_review_path)
    return lane_rulepack, promotion_review


def _attach_promotion_gate_source_reports(
    *,
    analysis: dict[str, Any],
    lane_rulepack_path: str | Path,
    promotion_review_path: str | Path,
) -> dict[str, Any]:
    return {
        **analysis,
        "source_reports": {
        "lane_rulepack": str(Path(lane_rulepack_path).expanduser().resolve()),
        "promotion_review": str(Path(promotion_review_path).expanduser().resolve()),
        },
    }


def render_btst_tplus2_continuation_promotion_gate_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST T+2 Continuation Promotion Gate")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- focus_ticker: {analysis['focus_ticker']}")
    lines.append(f"- promotion_review_verdict: {analysis['promotion_review_verdict']}")
    lines.append(f"- promotion_review_blockers: {analysis['promotion_review_blockers']}")
    lines.append(f"- promotion_ready_tickers: {analysis['promotion_ready_tickers']}")
    lines.append(f"- default_expansion_status: {analysis['default_expansion_status']}")
    lines.append(f"- gate_verdict: {analysis['gate_verdict']}")
    lines.append(f"- gate_blockers: {analysis['gate_blockers']}")
    lines.append(f"- current_watchlist_tickers: {analysis['current_watchlist_tickers']}")
    lines.append(f"- proposed_watchlist_tickers: {analysis['proposed_watchlist_tickers']}")
    lines.append(f"- eligible_tickers: {analysis['eligible_tickers']}")
    lines.append(f"- operator_action: {analysis['operator_action']}")
    lines.append(f"- execution_mode: {analysis['execution_mode']}")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a formal promotion gate for continuation watchlist review.")
    parser.add_argument("--lane-rulepack-path", default=str(DEFAULT_LANE_RULEPACK_PATH))
    parser.add_argument("--promotion-review-path", default=str(DEFAULT_PROMOTION_REVIEW_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = generate_btst_tplus2_continuation_promotion_gate(
        lane_rulepack_path=args.lane_rulepack_path,
        promotion_review_path=args.promotion_review_path,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_tplus2_continuation_promotion_gate_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
