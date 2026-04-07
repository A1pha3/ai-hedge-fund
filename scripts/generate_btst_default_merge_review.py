from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPORTS_DIR = Path("data/reports")
DEFAULT_MANIFEST_PATH = REPORTS_DIR / "report_manifest_latest.json"
DEFAULT_PROMOTION_REVIEW_PATH = REPORTS_DIR / "btst_tplus2_continuation_promotion_review_latest.json"
DEFAULT_GOVERNANCE_BOARD_PATH = REPORTS_DIR / "btst_tplus2_continuation_governance_board_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_default_merge_review_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_default_merge_review_latest.md"


def _load_optional_json(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return {}
    return json.loads(resolved.read_text(encoding="utf-8"))


def _resolve_focus_dossier_path(reports_dir: Path, focus_ticker: str, focus_dossier_path: str | Path | None) -> Path | None:
    if focus_dossier_path:
        return Path(focus_dossier_path).expanduser().resolve()
    if not focus_ticker:
        return None
    candidate_path = reports_dir / f"btst_tplus2_candidate_dossier_{focus_ticker}_latest.json"
    return candidate_path if candidate_path.exists() else None


def generate_btst_default_merge_review(
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    promotion_review_path: str | Path = DEFAULT_PROMOTION_REVIEW_PATH,
    governance_board_path: str | Path = DEFAULT_GOVERNANCE_BOARD_PATH,
    focus_dossier_path: str | Path | None = None,
) -> dict[str, Any]:
    manifest = _load_optional_json(manifest_path)
    promotion_review = _load_optional_json(promotion_review_path)
    governance_board = _load_optional_json(governance_board_path)
    continuation_summary = dict(manifest.get("continuation_promotion_ready_summary") or {})
    focus_ticker = str(
        continuation_summary.get("focus_ticker")
        or promotion_review.get("focus_ticker")
        or governance_board.get("focus_ticker")
        or ""
    ).strip()
    resolved_focus_dossier_path = _resolve_focus_dossier_path(Path(manifest_path).expanduser().resolve().parent, focus_ticker, focus_dossier_path)
    focus_dossier = _load_optional_json(resolved_focus_dossier_path)
    objective_support = dict(focus_dossier.get("governance_objective_support") or {})

    promotion_review_verdict = str(promotion_review.get("promotion_review_verdict") or "").strip()
    governance_status = str(governance_board.get("governance_status") or "").strip()
    summary_verdict = str(continuation_summary.get("promotion_merge_review_verdict") or "").strip()
    ready = any(
        verdict == "ready_for_default_btst_merge_review"
        for verdict in (promotion_review_verdict, governance_status, summary_verdict)
    )

    blockers = [
        *[str(item) for item in list(continuation_summary.get("unresolved_requirements") or []) if str(item).strip()],
        *[str(item) for item in list(promotion_review.get("promotion_blockers") or []) if str(item).strip()],
    ]
    if ready:
        blockers = []

    recommendation = (
        f"{focus_ticker} 已满足 continuation -> default BTST merge review 的前置条件。"
        f" observed_windows={continuation_summary.get('observed_independent_window_count')}, "
        f"positive_rate_delta={continuation_summary.get('t_plus_2_positive_rate_delta_vs_default_btst')}, "
        f"mean_return_delta={continuation_summary.get('t_plus_2_mean_return_delta_vs_default_btst')}。"
        " 建议把这条 continuation edge 直接升级到 default BTST merge review，并优先审阅其 counterfactual uplift。"
        if ready and focus_ticker
        else "当前没有 continuation 焦点票进入 default BTST merge review；继续保持 continuation lane 独立治理。"
    )
    required_positive_rate_delta = continuation_summary.get("required_positive_rate_delta_vs_default_btst")
    required_mean_return_delta = continuation_summary.get("required_mean_return_delta_vs_default_btst")
    positive_rate_delta = continuation_summary.get("t_plus_2_positive_rate_delta_vs_default_btst")
    mean_return_delta = continuation_summary.get("t_plus_2_mean_return_delta_vs_default_btst")
    positive_rate_margin = (
        round(float(positive_rate_delta) - float(required_positive_rate_delta), 4)
        if positive_rate_delta is not None and required_positive_rate_delta is not None
        else None
    )
    mean_return_margin = (
        round(float(mean_return_delta) - float(required_mean_return_delta), 4)
        if mean_return_delta is not None and required_mean_return_delta is not None
        else None
    )
    if positive_rate_margin is None or mean_return_margin is None:
        counterfactual_verdict = "insufficient_merge_threshold_context"
    elif positive_rate_margin >= 0 and mean_return_margin >= 0:
        counterfactual_verdict = "supports_default_btst_merge"
    else:
        counterfactual_verdict = "fails_default_btst_merge_threshold"
    counterfactual_validation = {
        "counterfactual_verdict": counterfactual_verdict,
        "required_positive_rate_delta_vs_default_btst": required_positive_rate_delta,
        "required_mean_return_delta_vs_default_btst": required_mean_return_delta,
        "focus_t_plus_2_positive_rate": continuation_summary.get("focus_t_plus_2_positive_rate"),
        "default_btst_t_plus_2_positive_rate": continuation_summary.get("default_btst_t_plus_2_positive_rate"),
        "t_plus_2_positive_rate_delta_vs_default_btst": positive_rate_delta,
        "t_plus_2_positive_rate_margin_vs_threshold": positive_rate_margin,
        "focus_t_plus_2_mean_return": continuation_summary.get("focus_t_plus_2_mean_return"),
        "default_btst_t_plus_2_mean_return": continuation_summary.get("default_btst_t_plus_2_mean_return"),
        "t_plus_2_mean_return_delta_vs_default_btst": mean_return_delta,
        "t_plus_2_mean_return_margin_vs_threshold": mean_return_margin,
        "edge_threshold_verdict": continuation_summary.get("edge_threshold_verdict"),
        "persistence_verdict": continuation_summary.get("persistence_verdict"),
        "observed_independent_window_count": continuation_summary.get("observed_independent_window_count"),
        "target_independent_window_count": continuation_summary.get("target_independent_window_count"),
    }

    return {
        "focus_ticker": focus_ticker or None,
        "merge_review_verdict": "ready_for_default_btst_merge_review" if ready and focus_ticker else "hold_continuation_lane",
        "operator_action": "review_default_btst_merge" if ready and focus_ticker else "hold_continuation_lane",
        "promotion_path_status": continuation_summary.get("promotion_path_status"),
        "promotion_merge_review_verdict": summary_verdict or None,
        "promotion_review_verdict": promotion_review_verdict or None,
        "governance_status": governance_status or None,
        "governance_blocker": governance_board.get("promotion_blocker"),
        "blockers": blockers,
        "qualifying_window_buckets": list(continuation_summary.get("qualifying_window_buckets") or []),
        "observed_independent_window_count": continuation_summary.get("observed_independent_window_count"),
        "weighted_observed_window_credit": continuation_summary.get("weighted_observed_window_credit"),
        "candidate_dossier_current_plan_visible_trade_dates": continuation_summary.get("candidate_dossier_current_plan_visible_trade_dates"),
        "candidate_dossier_current_plan_visibility_gap_trade_dates": continuation_summary.get("candidate_dossier_current_plan_visibility_gap_trade_dates"),
        "t_plus_2_positive_rate_delta_vs_default_btst": continuation_summary.get("t_plus_2_positive_rate_delta_vs_default_btst"),
        "t_plus_2_mean_return_delta_vs_default_btst": continuation_summary.get("t_plus_2_mean_return_delta_vs_default_btst"),
        "required_positive_rate_delta_vs_default_btst": required_positive_rate_delta,
        "required_mean_return_delta_vs_default_btst": required_mean_return_delta,
        "counterfactual_validation": counterfactual_validation,
        "latest_followup_decision": focus_dossier.get("latest_followup_decision"),
        "downstream_followup_status": focus_dossier.get("downstream_followup_status"),
        "focus_closed_cycle_count": objective_support.get("closed_cycle_count"),
        "focus_support_verdict": objective_support.get("support_verdict"),
        "recommendation": recommendation,
        "source_reports": {
            "manifest": str(Path(manifest_path).expanduser().resolve()),
            "promotion_review": str(Path(promotion_review_path).expanduser().resolve()),
            "governance_board": str(Path(governance_board_path).expanduser().resolve()),
            "focus_dossier": str(resolved_focus_dossier_path) if resolved_focus_dossier_path is not None else None,
        },
    }


def render_btst_default_merge_review_markdown(analysis: dict[str, Any]) -> str:
    lines = [
        "# BTST Default Merge Review",
        "",
        "## Overview",
        f"- focus_ticker: {analysis['focus_ticker']}",
        f"- merge_review_verdict: {analysis['merge_review_verdict']}",
        f"- operator_action: {analysis['operator_action']}",
        f"- promotion_path_status: {analysis.get('promotion_path_status')}",
        f"- promotion_merge_review_verdict: {analysis.get('promotion_merge_review_verdict')}",
        f"- promotion_review_verdict: {analysis.get('promotion_review_verdict')}",
        f"- governance_status: {analysis.get('governance_status')}",
        f"- governance_blocker: {analysis.get('governance_blocker')}",
        f"- blockers: {analysis.get('blockers')}",
        f"- qualifying_window_buckets: {analysis.get('qualifying_window_buckets')}",
        f"- observed_independent_window_count: {analysis.get('observed_independent_window_count')}",
        f"- weighted_observed_window_credit: {analysis.get('weighted_observed_window_credit')}",
        f"- current_plan_visible_trade_dates: {analysis.get('candidate_dossier_current_plan_visible_trade_dates')}",
        f"- current_plan_visibility_gap_trade_dates: {analysis.get('candidate_dossier_current_plan_visibility_gap_trade_dates')}",
        f"- required_positive_rate_delta_vs_default_btst: {analysis.get('required_positive_rate_delta_vs_default_btst')}",
        f"- required_mean_return_delta_vs_default_btst: {analysis.get('required_mean_return_delta_vs_default_btst')}",
        f"- t_plus_2_positive_rate_delta_vs_default_btst: {analysis.get('t_plus_2_positive_rate_delta_vs_default_btst')}",
        f"- t_plus_2_mean_return_delta_vs_default_btst: {analysis.get('t_plus_2_mean_return_delta_vs_default_btst')}",
        f"- counterfactual_validation: {analysis.get('counterfactual_validation')}",
        f"- latest_followup_decision: {analysis.get('latest_followup_decision')}",
        f"- downstream_followup_status: {analysis.get('downstream_followup_status')}",
        "",
        "## Recommendation",
        f"- {analysis['recommendation']}",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a single default BTST merge review artifact from continuation governance outputs.")
    parser.add_argument("--manifest-path", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--promotion-review-path", default=str(DEFAULT_PROMOTION_REVIEW_PATH))
    parser.add_argument("--governance-board-path", default=str(DEFAULT_GOVERNANCE_BOARD_PATH))
    parser.add_argument("--focus-dossier-path", default=None)
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = generate_btst_default_merge_review(
        manifest_path=args.manifest_path,
        promotion_review_path=args.promotion_review_path,
        governance_board_path=args.governance_board_path,
        focus_dossier_path=args.focus_dossier_path,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_default_merge_review_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
