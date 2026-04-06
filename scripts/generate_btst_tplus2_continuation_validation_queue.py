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
    queue_seed = list(expansion_board.get("next_validation_candidates") or [])[: max(int(max_candidates), 0)]

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
        queue_rows.append(
            {
                "ticker": ticker,
                "seed_tier": seed.get("tier"),
                "priority_rank": seed.get("priority_rank"),
                "candidate_tier_focus": dossier.get("candidate_tier_focus"),
                "recent_tier_verdict": dossier.get("recent_tier_verdict"),
                "recent_tier_window_count": dossier.get("recent_tier_window_count"),
                "recent_window_count": dossier.get("recent_window_count"),
                "recent_tier_ratio": dossier.get("recent_tier_ratio"),
                "promotion_readiness_verdict": dossier.get("promotion_readiness_verdict"),
                "next_close_positive_rate": dict(dossier.get("tier_focus_surface_summary") or {}).get("next_close_positive_rate"),
                "t_plus_2_close_positive_rate": dict(dossier.get("tier_focus_surface_summary") or {}).get("t_plus_2_close_positive_rate"),
                "t_plus_2_close_return_mean": dict(dict(dossier.get("tier_focus_surface_summary") or {}).get("t_plus_2_close_return_distribution") or {}).get("mean"),
                "next_step": (
                    "Promote into near-cluster watch review if another confirming window appears."
                    if str(dossier.get("promotion_readiness_verdict") or "") == "validation_queue_ready"
                    else "Keep on queue watch until recent tier confirmation strengthens."
                ),
            }
        )

    resolved_focus_ticker = str(focus_ticker or (queue_rows[0]["ticker"] if queue_rows else ""))
    focus_candidate = next((row for row in queue_rows if str(row.get("ticker") or "") == resolved_focus_ticker), None)
    promotion_review = None
    if focus_candidate:
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
        promotion_review = _build_promotion_review({"focus_candidate": focus_candidate}, focus_dossier, watch_dossier)

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
