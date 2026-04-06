from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPORTS_DIR = Path("data/reports")
DEFAULT_LANE_RULEPACK_PATH = REPORTS_DIR / "btst_tplus2_continuation_lane_rulepack_latest.json"
DEFAULT_PROMOTION_REVIEW_PATH = REPORTS_DIR / "btst_tplus2_continuation_promotion_review_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_tplus2_continuation_promotion_gate_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_tplus2_continuation_promotion_gate_latest.md"


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _build_promotion_gate(lane_rulepack: dict[str, Any], promotion_review: dict[str, Any]) -> dict[str, Any]:
    lane_rules = dict(lane_rulepack.get("lane_rules") or {})
    focus_ticker = str(promotion_review.get("focus_ticker") or "")
    eligible_tickers = [str(item) for item in list(lane_rulepack.get("eligible_tickers") or []) if str(item).strip()]
    watchlist_tickers = [str(item) for item in list(lane_rulepack.get("watchlist_tickers") or []) if str(item).strip()]
    gate_blockers: list[str] = []
    promotion_review_verdict = str(promotion_review.get("promotion_review_verdict") or "")
    promotion_review_blockers = [str(item) for item in list(promotion_review.get("promotion_blockers") or []) if str(item).strip()]

    if not focus_ticker:
        gate_blockers.append("missing_focus_ticker")
    if promotion_review_verdict != "watch_review_ready":
        gate_blockers.append("promotion_review_not_ready")
    if promotion_review_blockers:
        gate_blockers.extend(promotion_review_blockers)
    if focus_ticker and focus_ticker in eligible_tickers:
        gate_blockers.append("focus_already_eligible")

    lane_stage = str(lane_rules.get("lane_stage") or lane_rulepack.get("lane_stage") or "")
    capital_mode = str(lane_rules.get("capital_mode") or lane_rulepack.get("capital_mode") or "")
    if lane_stage and lane_stage != "observation_only":
        gate_blockers.append("unexpected_lane_stage")
    if capital_mode and capital_mode != "paper_only":
        gate_blockers.append("unexpected_capital_mode")

    if focus_ticker and focus_ticker in watchlist_tickers:
        gate_verdict = "already_on_watchlist"
        operator_action = "keep_watchlist_unchanged"
        proposed_watchlist_tickers = list(watchlist_tickers)
    elif gate_blockers:
        gate_verdict = "hold_watchlist_promotion"
        operator_action = "keep_watchlist_unchanged"
        proposed_watchlist_tickers = list(watchlist_tickers)
    else:
        gate_verdict = "approve_watchlist_promotion"
        operator_action = "append_focus_to_watchlist"
        proposed_watchlist_tickers = watchlist_tickers + [focus_ticker]

    if gate_verdict == "approve_watchlist_promotion":
        recommendation = (
            f"Approve {focus_ticker} as an additional near-cluster watchlist ticker while keeping "
            f"eligible_tickers={eligible_tickers} unchanged and the continuation lane isolated from default BTST."
        )
    elif gate_verdict == "already_on_watchlist":
        recommendation = f"{focus_ticker} is already on watchlist_tickers; no additional governance action is required."
    else:
        recommendation = "Hold watchlist promotion and keep the focus candidate inside validation review until the gate blockers clear."

    return {
        "focus_ticker": focus_ticker or None,
        "promotion_review_verdict": promotion_review_verdict or None,
        "promotion_review_blockers": promotion_review_blockers,
        "gate_verdict": gate_verdict,
        "gate_blockers": gate_blockers,
        "current_watchlist_tickers": watchlist_tickers,
        "proposed_watchlist_tickers": proposed_watchlist_tickers,
        "eligible_tickers": eligible_tickers,
        "operator_action": operator_action,
        "execution_mode": "manual_rulepack_update",
        "recommendation": recommendation,
    }


def generate_btst_tplus2_continuation_promotion_gate(
    *,
    lane_rulepack_path: str | Path,
    promotion_review_path: str | Path,
) -> dict[str, Any]:
    lane_rulepack = _load_json(lane_rulepack_path)
    promotion_review = _load_json(promotion_review_path)
    analysis = _build_promotion_gate(lane_rulepack, promotion_review)
    analysis["source_reports"] = {
        "lane_rulepack": str(Path(lane_rulepack_path).expanduser().resolve()),
        "promotion_review": str(Path(promotion_review_path).expanduser().resolve()),
    }
    return analysis


def render_btst_tplus2_continuation_promotion_gate_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST T+2 Continuation Promotion Gate")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- focus_ticker: {analysis['focus_ticker']}")
    lines.append(f"- promotion_review_verdict: {analysis['promotion_review_verdict']}")
    lines.append(f"- promotion_review_blockers: {analysis['promotion_review_blockers']}")
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
