from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_btst_tplus2_continuation_clusters import analyze_btst_tplus2_continuation_clusters
from scripts.analyze_btst_tplus2_continuation_peer_scan import analyze_btst_tplus2_continuation_peer_scan


REPORTS_DIR = Path("data/reports")
DEFAULT_REPORTS_ROOT = REPORTS_DIR
DEFAULT_UPSTREAM_HANDOFF_BOARD_PATH = REPORTS_DIR / "btst_candidate_pool_upstream_handoff_board_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_tplus2_continuation_observation_pool_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_tplus2_continuation_observation_pool_latest.md"


def _build_anchor_entries(cluster_analysis: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in list(cluster_analysis.get("ticker_summaries") or []):
        if str(item.get("pattern_label") or "") != "recurring_tplus2_continuation_cluster":
            continue
        surface = dict(item.get("surface_summary") or {})
        entries.append(
            {
                "ticker": item["ticker"],
                "entry_type": "anchor_cluster",
                "lane_stage": "observation_only",
                "priority_score": round(
                    (float(item.get("distinct_report_count") or 0) * 10.0)
                    + (float(surface.get("t_plus_2_close_positive_rate") or 0.0) * 5.0)
                    + (float(dict(surface.get("t_plus_2_close_return_distribution") or {}).get("mean") or 0.0) * 100.0),
                    4,
                ),
                "distinct_report_count": item.get("distinct_report_count"),
                "observation_count": item.get("observation_count"),
                "next_close_positive_rate": surface.get("next_close_positive_rate"),
                "t_plus_2_close_positive_rate": surface.get("t_plus_2_close_positive_rate"),
                "t_plus_2_close_return_mean": dict(surface.get("t_plus_2_close_return_distribution") or {}).get("mean"),
                "cluster_pattern": item.get("pattern_label"),
                "rationale": item.get("recommendation"),
            }
        )
    return entries


def _build_peer_entries(peer_analysis: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in list(peer_analysis.get("peer_summaries") or []):
        surface = dict(item.get("surface_summary") or {})
        entries.append(
            {
                "ticker": item["ticker"],
                "entry_type": "same_cluster_peer",
                "lane_stage": "observation_only",
                "priority_score": round(
                    (float(item.get("distinct_report_count") or 0) * 10.0)
                    + (float(surface.get("t_plus_2_close_positive_rate") or 0.0) * 5.0)
                    - float(item.get("mean_similarity_score") or 0.0),
                    4,
                ),
                "distinct_report_count": item.get("distinct_report_count"),
                "observation_count": item.get("observation_count"),
                "next_close_positive_rate": surface.get("next_close_positive_rate"),
                "t_plus_2_close_positive_rate": surface.get("t_plus_2_close_positive_rate"),
                "t_plus_2_close_return_mean": dict(surface.get("t_plus_2_close_return_distribution") or {}).get("mean"),
                "mean_similarity_score": item.get("mean_similarity_score"),
                "rationale": "Same-cluster peer from continuation peer scan.",
            }
        )
    return entries


def _build_watch_entries(peer_analysis: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in list(peer_analysis.get("near_peer_summaries") or []):
        surface = dict(item.get("surface_summary") or {})
        entries.append(
            {
                "ticker": item["ticker"],
                "entry_type": "near_cluster_watch",
                "lane_stage": "validation_watch",
                "priority_score": round(
                    (float(item.get("distinct_report_count") or 0) * 1.5)
                    + (float(surface.get("t_plus_2_close_positive_rate") or 0.0) * 5.0)
                    - float(item.get("mean_similarity_score") or 0.0),
                    4,
                ),
                "distinct_report_count": item.get("distinct_report_count"),
                "observation_count": item.get("observation_count"),
                "next_close_positive_rate": surface.get("next_close_positive_rate"),
                "t_plus_2_close_positive_rate": surface.get("t_plus_2_close_positive_rate"),
                "t_plus_2_close_return_mean": dict(surface.get("t_plus_2_close_return_distribution") or {}).get("mean"),
                "mean_similarity_score": item.get("mean_similarity_score"),
                "rationale": "Near-cluster continuation candidate: keep on validation watch, not eligible lane membership.",
            }
        )
    return entries


def _maybe_load_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return {}
    return json.loads(resolved.read_text(encoding="utf-8"))


def _build_governance_followup_entries(upstream_handoff_board: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in list(upstream_handoff_board.get("board_rows") or []):
        row = dict(item or {})
        if str(row.get("downstream_followup_lane") or "") != "t_plus_2_continuation_review":
            continue
        entries.append(
            {
                "ticker": row.get("ticker"),
                "entry_type": "governance_followup",
                "lane_stage": "validation_watch",
                "priority_score": 1000.0 - float(row.get("board_rank") or 999.0),
                "distinct_report_count": 1,
                "observation_count": 1,
                "next_close_positive_rate": None,
                "t_plus_2_close_positive_rate": None,
                "t_plus_2_close_return_mean": None,
                "governance_status": row.get("downstream_followup_status"),
                "governance_blocker": row.get("downstream_followup_blocker"),
                "rationale": row.get("downstream_followup_summary")
                or "Post-recall continuation review candidate sourced from the upstream handoff board.",
            }
        )
    return entries


def generate_btst_tplus2_continuation_observation_pool(
    reports_root: str | Path,
    *,
    anchor_ticker: str = "600988",
    profile_name: str = "watchlist_zero_catalyst_guard_relief",
    report_name_contains: str = "btst_",
    next_high_hit_threshold: float = 0.02,
    similarity_threshold: float = 1.35,
    upstream_handoff_board_path: str | Path | None = None,
) -> dict[str, Any]:
    cluster_analysis = analyze_btst_tplus2_continuation_clusters(
        reports_root,
        profile_name=profile_name,
        report_name_contains=report_name_contains,
        next_high_hit_threshold=next_high_hit_threshold,
    )
    peer_analysis = analyze_btst_tplus2_continuation_peer_scan(
        reports_root,
        anchor_ticker=anchor_ticker,
        profile_name=profile_name,
        report_name_contains=report_name_contains,
        next_high_hit_threshold=next_high_hit_threshold,
        similarity_threshold=similarity_threshold,
    )
    upstream_handoff_board = _maybe_load_json(upstream_handoff_board_path or DEFAULT_UPSTREAM_HANDOFF_BOARD_PATH)

    entries = (
        _build_governance_followup_entries(upstream_handoff_board)
        + _build_anchor_entries(cluster_analysis)
        + _build_peer_entries(peer_analysis)
        + _build_watch_entries(peer_analysis)
    )
    entries.sort(key=lambda item: (float(item.get("priority_score") or -999.0), str(item.get("ticker") or "")), reverse=True)

    if entries:
        recommendation = "Observation pool ready. Keep these names outside the default BTST tradeable surface and validate them in a dedicated T+2 continuation lane."
    else:
        recommendation = "No continuation observation pool entries are ready yet."

    return {
        "reports_root": str(Path(reports_root).expanduser().resolve()),
        "anchor_ticker": anchor_ticker,
        "upstream_handoff_board_path": str(Path(upstream_handoff_board_path or DEFAULT_UPSTREAM_HANDOFF_BOARD_PATH).expanduser().resolve()),
        "profile_name": profile_name,
        "report_name_contains": report_name_contains,
        "governance_followup_count": len([item for item in entries if str(item.get("entry_type") or "") == "governance_followup"]),
        "entry_count": len(entries),
        "entries": entries,
        "cluster_summary": {
            "continuation_row_count": cluster_analysis.get("continuation_row_count"),
            "ticker_count": cluster_analysis.get("ticker_count"),
            "recurring_cluster_count": cluster_analysis.get("recurring_cluster_count"),
        },
        "peer_summary": {
            "peer_count": peer_analysis.get("peer_count"),
            "near_cluster_count": peer_analysis.get("near_cluster_count"),
            "recommendation": peer_analysis.get("recommendation"),
        },
        "recommendation": recommendation,
    }


def render_btst_tplus2_continuation_observation_pool_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST T+2 Continuation Observation Pool")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- anchor_ticker: {analysis['anchor_ticker']}")
    lines.append(f"- governance_followup_count: {analysis.get('governance_followup_count')}")
    lines.append(f"- entry_count: {analysis['entry_count']}")
    lines.append(f"- cluster_summary: {analysis['cluster_summary']}")
    lines.append(f"- peer_summary: {analysis['peer_summary']}")
    lines.append("")
    lines.append("## Observation Entries")
    for item in list(analysis.get("entries") or []):
        lines.append(
            f"- {item['ticker']}: entry_type={item['entry_type']}, lane_stage={item['lane_stage']}, "
            f"priority_score={item['priority_score']}, next_close_positive_rate={item.get('next_close_positive_rate')}, "
            f"t_plus_2_close_positive_rate={item.get('t_plus_2_close_positive_rate')}, "
            f"t_plus_2_close_return_mean={item.get('t_plus_2_close_return_mean')}"
        )
        if item.get("governance_status"):
            lines.append(
                f"  governance: status={item.get('governance_status')} blocker={item.get('governance_blocker')}"
            )
    if not list(analysis.get("entries") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a dedicated BTST T+2 continuation observation pool.")
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--anchor-ticker", default="600988")
    parser.add_argument("--profile-name", default="watchlist_zero_catalyst_guard_relief")
    parser.add_argument("--report-name-contains", default="btst_")
    parser.add_argument("--next-high-hit-threshold", type=float, default=0.02)
    parser.add_argument("--similarity-threshold", type=float, default=1.35)
    parser.add_argument("--upstream-handoff-board-path", default=str(DEFAULT_UPSTREAM_HANDOFF_BOARD_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = generate_btst_tplus2_continuation_observation_pool(
        args.reports_root,
        anchor_ticker=str(args.anchor_ticker or "600988"),
        profile_name=str(args.profile_name or "watchlist_zero_catalyst_guard_relief"),
        report_name_contains=str(args.report_name_contains or "btst_"),
        next_high_hit_threshold=float(args.next_high_hit_threshold),
        similarity_threshold=float(args.similarity_threshold),
        upstream_handoff_board_path=args.upstream_handoff_board_path,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_tplus2_continuation_observation_pool_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
