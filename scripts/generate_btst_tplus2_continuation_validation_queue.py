from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_btst_tplus2_near_cluster_dossier import analyze_btst_tplus2_near_cluster_dossier
from scripts.generate_btst_tplus2_continuation_promotion_review import _build_promotion_review
from scripts.generate_btst_tplus2_continuation_expansion_board import generate_btst_tplus2_continuation_expansion_board


REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_tplus2_continuation_validation_queue_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_tplus2_continuation_validation_queue_latest.md"


def _build_validation_queue_row(*, seed: dict[str, Any], dossier: dict[str, Any]) -> dict[str, Any]:
    promotion_readiness_verdict = str(dossier.get("promotion_readiness_verdict") or "")
    candidate_tier_focus = str(dossier.get("candidate_tier_focus") or "")
    return {
        "ticker": str(seed.get("ticker") or ""),
        "seed_tier": seed.get("tier"),
        "priority_rank": seed.get("priority_rank"),
        "candidate_tier_focus": candidate_tier_focus,
        "recent_tier_verdict": dossier.get("recent_tier_verdict"),
        "recent_tier_window_count": dossier.get("recent_tier_window_count"),
        "recent_window_count": dossier.get("recent_window_count"),
        "recent_tier_ratio": dossier.get("recent_tier_ratio"),
        "promotion_readiness_verdict": promotion_readiness_verdict,
        "next_close_positive_rate": dict(dossier.get("tier_focus_surface_summary") or {}).get("next_close_positive_rate"),
        "t_plus_2_close_positive_rate": dict(dossier.get("tier_focus_surface_summary") or {}).get("t_plus_2_close_positive_rate"),
        "t_plus_2_close_return_mean": dict(dict(dossier.get("tier_focus_surface_summary") or {}).get("t_plus_2_close_return_distribution") or {}).get("mean"),
        "next_step": (
            "Escalate into default BTST merge review under explicit governance approval."
            if candidate_tier_focus == "governance_followup" and promotion_readiness_verdict == "merge_review_ready"
            else (
                "Promote into near-cluster watch review under the governance-approved continuation lane."
                if candidate_tier_focus == "governance_followup" and promotion_readiness_verdict == "watch_review_ready"
                else (
                    "Promote into near-cluster watch review if another confirming window appears."
                    if promotion_readiness_verdict == "validation_queue_ready"
                    else (
                        "Keep on queue watch until recent governance followup converts into payoff-confirmed continuation evidence."
                        if candidate_tier_focus == "governance_followup"
                        else "Keep on queue watch until recent tier confirmation strengthens."
                    )
                )
            )
        ),
    }


def _build_validation_queue_rows(
    *,
    reports_root: str | Path,
    anchor_ticker: str,
    profile_name: str,
    report_name_contains: str,
    queue_seed: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    queue_rows: list[dict[str, Any]] = []
    for seed in queue_seed:
        ticker = str(seed.get("ticker") or "")
        if not ticker:
            continue
        dossier = analyze_btst_tplus2_near_cluster_dossier(
            reports_root,
            anchor_ticker=anchor_ticker,
            candidate_ticker=ticker,
            profile_name=profile_name,
            report_name_contains=report_name_contains,
        )
        queue_rows.append(_build_validation_queue_row(seed=seed, dossier=dossier))
    return queue_rows


def _resolve_focus_candidate_review(
    *,
    reports_root: str | Path,
    anchor_ticker: str,
    profile_name: str,
    report_name_contains: str,
    resolved_focus_ticker: str,
    queue_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    focus_candidate = next((row for row in queue_rows if str(row.get("ticker") or "") == resolved_focus_ticker), None)
    if not focus_candidate:
        return None, None
    focus_dossier = analyze_btst_tplus2_near_cluster_dossier(
        reports_root,
        anchor_ticker=anchor_ticker,
        candidate_ticker=resolved_focus_ticker,
        profile_name=profile_name,
        report_name_contains=report_name_contains,
    )
    watch_dossier = analyze_btst_tplus2_near_cluster_dossier(
        reports_root,
        anchor_ticker=anchor_ticker,
        candidate_ticker="600989",
        profile_name=profile_name,
        report_name_contains=report_name_contains,
    )
    return focus_candidate, _build_promotion_review({"focus_candidate": focus_candidate}, focus_dossier, watch_dossier)


def _build_validation_queue_analysis(
    *,
    reports_root: str | Path,
    anchor_ticker: str,
    resolved_focus_ticker: str,
    focus_candidate: dict[str, Any] | None,
    promotion_review: dict[str, Any] | None,
    queue_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    recommendation = (
        f"Validation queue ready with {len(queue_rows)} candidates. "
        f"Focus next review on {resolved_focus_ticker or 'none'} and keep all queue names outside the default BTST surface."
    )
    return {
        "reports_root": str(Path(reports_root).expanduser().resolve()),
        "anchor_ticker": anchor_ticker,
        "queue_row_count": len(queue_rows),
        "focus_ticker": resolved_focus_ticker or None,
        "focus_candidate": focus_candidate,
        "promotion_review": promotion_review,
        "queue_rows": queue_rows,
        "recommendation": recommendation,
    }


def generate_btst_tplus2_continuation_validation_queue(
    reports_root: str | Path,
    *,
    anchor_ticker: str = "600988",
    profile_name: str = "watchlist_zero_catalyst_guard_relief",
    report_name_contains: str = "btst_",
    max_candidates: int = 3,
    focus_ticker: str | None = None,
) -> dict[str, Any]:
    expansion_board = generate_btst_tplus2_continuation_expansion_board(
        reports_root,
        anchor_ticker=anchor_ticker,
        profile_name=profile_name,
        report_name_contains=report_name_contains,
    )
    max_candidates = max(int(max_candidates), 0)
    queue_seed = list(expansion_board.get("next_validation_candidates") or [])[:max_candidates]
    expansion_board_rows = [dict(row or {}) for row in list(expansion_board.get("board_rows") or [])]

    resolved_focus_ticker = str(
        focus_ticker
        or dict(expansion_board.get("focus_candidate") or {}).get("ticker")
        or (queue_seed[0].get("ticker") if queue_seed else "")
        or ""
    )
    if resolved_focus_ticker and resolved_focus_ticker not in {str(row.get("ticker") or "") for row in queue_seed}:
        focus_row = next((row for row in expansion_board_rows if str(row.get("ticker") or "") == resolved_focus_ticker), None)
        if focus_row is not None:
            queue_seed = [
                {
                    "ticker": focus_row.get("ticker"),
                    "tier": focus_row.get("tier"),
                    "priority_rank": focus_row.get("priority_rank"),
                },
                *queue_seed[: max(max_candidates - 1, 0)],
            ]

    queue_rows = _build_validation_queue_rows(
        reports_root=reports_root,
        anchor_ticker=anchor_ticker,
        profile_name=profile_name,
        report_name_contains=report_name_contains,
        queue_seed=queue_seed,
    )
    focus_candidate, promotion_review = _resolve_focus_candidate_review(
        reports_root=reports_root,
        anchor_ticker=anchor_ticker,
        profile_name=profile_name,
        report_name_contains=report_name_contains,
        resolved_focus_ticker=resolved_focus_ticker,
        queue_rows=queue_rows,
    )
    return _build_validation_queue_analysis(
        reports_root=reports_root,
        anchor_ticker=anchor_ticker,
        resolved_focus_ticker=resolved_focus_ticker,
        focus_candidate=focus_candidate,
        promotion_review=promotion_review,
        queue_rows=queue_rows,
    )


def render_btst_tplus2_continuation_validation_queue_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST T+2 Continuation Validation Queue")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- anchor_ticker: {analysis['anchor_ticker']}")
    lines.append(f"- queue_row_count: {analysis['queue_row_count']}")
    lines.append(f"- focus_ticker: {analysis['focus_ticker']}")
    lines.append(f"- focus_candidate: {analysis['focus_candidate']}")
    lines.append(f"- promotion_review: {analysis.get('promotion_review')}")
    lines.append("")
    lines.append("## Queue")
    for row in list(analysis.get("queue_rows") or []):
        lines.append(
            f"- rank={row['priority_rank']} ticker={row['ticker']} seed_tier={row['seed_tier']} "
            f"candidate_tier_focus={row['candidate_tier_focus']} recent_tier_verdict={row['recent_tier_verdict']} "
            f"recent_tier_window_count={row['recent_tier_window_count']}/{row['recent_window_count']} "
            f"recent_tier_ratio={row['recent_tier_ratio']} promotion_readiness_verdict={row['promotion_readiness_verdict']}"
        )
        lines.append(f"  next_step: {row['next_step']}")
    if not list(analysis.get("queue_rows") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a second-tier validation queue for continuation candidates.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR))
    parser.add_argument("--anchor-ticker", default="600988")
    parser.add_argument("--profile-name", default="watchlist_zero_catalyst_guard_relief")
    parser.add_argument("--report-name-contains", default="btst_")
    parser.add_argument("--max-candidates", type=int, default=3)
    parser.add_argument("--focus-ticker", default=None)
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = generate_btst_tplus2_continuation_validation_queue(
        args.reports_root,
        anchor_ticker=str(args.anchor_ticker or "600988"),
        profile_name=str(args.profile_name or "watchlist_zero_catalyst_guard_relief"),
        report_name_contains=str(args.report_name_contains or "btst_"),
        max_candidates=int(args.max_candidates),
        focus_ticker=str(args.focus_ticker) if args.focus_ticker else None,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_tplus2_continuation_validation_queue_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
