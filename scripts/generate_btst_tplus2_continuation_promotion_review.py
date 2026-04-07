from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_btst_tplus2_near_cluster_dossier import governance_followup_payoff_confirmed


REPORTS_DIR = Path("data/reports")
DEFAULT_QUEUE_PATH = REPORTS_DIR / "btst_tplus2_continuation_validation_queue_latest.json"
DEFAULT_FOCUS_DOSSIER_FALLBACK_PATH = REPORTS_DIR / "btst_tplus2_candidate_dossier_300505_latest.json"
DEFAULT_WATCH_DOSSIER_PATH = REPORTS_DIR / "btst_tplus2_near_cluster_dossier_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_tplus2_continuation_promotion_review_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_tplus2_continuation_promotion_review_latest.md"
READY_PROMOTION_REVIEW_VERDICTS = {"watch_review_ready", "ready_for_default_btst_merge_review"}


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _resolve_focus_dossier_path(queue_path: str | Path, focus_dossier_path: str | Path | None) -> Path:
    if focus_dossier_path:
        return Path(focus_dossier_path).expanduser().resolve()
    queue = _load_json(queue_path)
    focus_ticker = str(dict(queue.get("focus_candidate") or {}).get("ticker") or "").strip()
    if focus_ticker:
        return (REPORTS_DIR / f"btst_tplus2_candidate_dossier_{focus_ticker}_latest.json").expanduser().resolve()
    return DEFAULT_FOCUS_DOSSIER_FALLBACK_PATH.expanduser().resolve()


def _build_promotion_review(queue: dict[str, Any], focus_dossier: dict[str, Any], watch_dossier: dict[str, Any]) -> dict[str, Any]:
    focus_candidate = dict(queue.get("focus_candidate") or {})
    focus_ticker = str(focus_candidate.get("ticker") or focus_dossier.get("candidate_ticker") or "")
    benchmark_ticker = str(watch_dossier.get("candidate_ticker") or "")

    focus_recent_tier_verdict = str(focus_dossier.get("recent_tier_verdict") or "")
    focus_promotion_readiness_verdict = str(focus_dossier.get("promotion_readiness_verdict") or "")
    focus_promotion_path_status = str(focus_dossier.get("promotion_path_status") or "")
    focus_promotion_merge_review_verdict = str(focus_dossier.get("promotion_merge_review_verdict") or "")
    focus_recent_tier_window_count = int(focus_dossier.get("recent_tier_window_count") or 0)
    focus_recent_window_count = int(focus_dossier.get("recent_window_count") or 0)
    focus_next_close_positive_rate = float(dict(focus_dossier.get("tier_focus_surface_summary") or {}).get("next_close_positive_rate") or 0.0)
    focus_t_plus_2_positive_rate = float(dict(focus_dossier.get("tier_focus_surface_summary") or {}).get("t_plus_2_close_positive_rate") or 0.0)
    focus_t_plus_2_mean = float(
        dict(dict(focus_dossier.get("tier_focus_surface_summary") or {}).get("t_plus_2_close_return_distribution") or {}).get("mean") or 0.0
    )
    benchmark_recent_support_ratio = float(watch_dossier.get("recent_support_ratio") or 0.0)
    benchmark_t_plus_2_mean = float(
        dict(dict(watch_dossier.get("recent_supporting_surface_summary") or {}).get("t_plus_2_close_return_distribution") or {}).get("mean") or 0.0
    )

    blockers: list[str] = []
    candidate_tier_focus = str(focus_dossier.get("candidate_tier_focus") or "")
    governance_objective_support = dict(focus_dossier.get("governance_objective_support") or {})
    governance_payoff_ready = governance_followup_payoff_confirmed(
        governance_objective_support,
        recent_tier_window_count=focus_recent_tier_window_count,
        recent_window_count=focus_recent_window_count,
    )
    if candidate_tier_focus == "governance_followup" and not governance_payoff_ready:
        blockers.append("governance_followup_needs_multiwindow_payoff")
    elif candidate_tier_focus not in {"observation_candidate", "governance_followup"}:
        blockers.append("focus_not_observation_candidate")
    if focus_recent_tier_verdict not in {"recent_tier_confirmed", "governance_followup_payoff_confirmed"}:
        if focus_recent_tier_verdict == "governance_followup_pending_evidence":
            if focus_recent_window_count > 0:
                blockers.append("recent_followup_windows_present_but_payoff_unconfirmed")
            else:
                blockers.append("recent_payoff_windows_missing")
        else:
            blockers.append("recent_tier_not_confirmed")
    if focus_recent_tier_window_count < 3:
        blockers.append("insufficient_recent_windows")
    has_historical_objective_support = bool(governance_objective_support)
    if candidate_tier_focus != "governance_followup" and focus_next_close_positive_rate < 0.5:
        blockers.append("weak_next_close_follow_through")
    if candidate_tier_focus != "governance_followup" and (focus_t_plus_2_positive_rate < 0.5 or focus_t_plus_2_mean <= 0.0):
        blockers.append("weak_t_plus_2_follow_through")
    if candidate_tier_focus == "governance_followup" and not has_historical_objective_support:
        blockers.append("historical_objective_support_missing")

    manifest_merge_ready = (
        focus_promotion_readiness_verdict == "merge_review_ready"
        or focus_promotion_path_status == "merge_review_ready"
        or focus_promotion_merge_review_verdict == "ready_for_default_btst_merge_review"
    )

    if blockers:
        promotion_review_verdict = "hold_validation_queue"
        recommendation = "Keep the focus candidate in validation queue until blockers clear; do not promote it into near_cluster_watch."
    elif manifest_merge_ready:
        promotion_review_verdict = "ready_for_default_btst_merge_review"
        recommendation = "Focus candidate has satisfied the continuation lane merge criteria and should escalate into default BTST merge review under explicit governance approval."
    else:
        promotion_review_verdict = "watch_review_ready"
        recommendation = "Focus candidate is ready for near-cluster watch review, but do not auto-promote it into watchlist_tickers without explicit governance approval."

    return {
        "focus_ticker": focus_ticker or None,
        "benchmark_watch_ticker": benchmark_ticker or None,
        "promotion_review_verdict": promotion_review_verdict,
        "promotion_blockers": blockers,
        "focus_candidate": focus_candidate,
        "comparison_summary": {
            "focus_recent_tier_verdict": focus_recent_tier_verdict,
            "focus_promotion_readiness_verdict": focus_promotion_readiness_verdict,
            "focus_promotion_path_status": focus_promotion_path_status,
            "focus_promotion_merge_review_verdict": focus_promotion_merge_review_verdict,
            "focus_recent_tier_window_count": focus_recent_tier_window_count,
            "focus_recent_window_count": focus_recent_window_count,
            "focus_next_close_positive_rate": focus_next_close_positive_rate,
            "focus_t_plus_2_positive_rate": focus_t_plus_2_positive_rate,
            "focus_t_plus_2_close_return_mean": focus_t_plus_2_mean,
            "benchmark_recent_support_ratio": benchmark_recent_support_ratio,
            "benchmark_t_plus_2_close_return_mean": benchmark_t_plus_2_mean,
            "t_plus_2_mean_gap_vs_watch": round(focus_t_plus_2_mean - benchmark_t_plus_2_mean, 4),
            "governance_payoff_ready": governance_payoff_ready,
        },
        "recommendation": recommendation,
    }


def generate_btst_tplus2_continuation_promotion_review(
    *,
    queue_path: str | Path,
    focus_dossier_path: str | Path,
    watch_dossier_path: str | Path,
) -> dict[str, Any]:
    queue = _load_json(queue_path)
    focus_dossier = _load_json(focus_dossier_path)
    watch_dossier = _load_json(watch_dossier_path)
    return _build_promotion_review(queue, focus_dossier, watch_dossier)


def render_btst_tplus2_continuation_promotion_review_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST T+2 Continuation Promotion Review")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- focus_ticker: {analysis['focus_ticker']}")
    lines.append(f"- benchmark_watch_ticker: {analysis['benchmark_watch_ticker']}")
    lines.append(f"- promotion_review_verdict: {analysis['promotion_review_verdict']}")
    lines.append(f"- promotion_blockers: {analysis['promotion_blockers']}")
    lines.append(f"- comparison_summary: {analysis['comparison_summary']}")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Review whether a validation-queue candidate is ready for near-cluster watch review.")
    parser.add_argument("--queue-path", default=str(DEFAULT_QUEUE_PATH))
    parser.add_argument("--focus-dossier-path", default=None)
    parser.add_argument("--watch-dossier-path", default=str(DEFAULT_WATCH_DOSSIER_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    resolved_focus_dossier_path = _resolve_focus_dossier_path(args.queue_path, args.focus_dossier_path)
    analysis = generate_btst_tplus2_continuation_promotion_review(
        queue_path=args.queue_path,
        focus_dossier_path=resolved_focus_dossier_path,
        watch_dossier_path=args.watch_dossier_path,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_tplus2_continuation_promotion_review_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
