from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

from scripts.analyze_btst_tplus2_continuation_clusters import _is_continuation_row
from scripts.btst_analysis_utils import build_surface_summary
from scripts.btst_profile_replay_utils import analyze_btst_profile_replay_window
from scripts.btst_report_utils import discover_report_dirs


REPORTS_DIR = Path("data/reports")
DEFAULT_REPORTS_ROOT = REPORTS_DIR
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_tplus2_continuation_peer_scan_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_tplus2_continuation_peer_scan_latest.md"
REFERENCE_METRICS = (
    "breakout_freshness",
    "trend_acceleration",
    "catalyst_freshness",
    "layer_c_alignment",
    "sector_resonance",
    "close_strength",
)
DEFAULT_TOLERANCES = {
    "breakout_freshness": 0.08,
    "trend_acceleration": 0.08,
    "catalyst_freshness": 0.05,
    "layer_c_alignment": 0.04,
    "sector_resonance": 0.04,
    "close_strength": 0.18,
}
TIER_RANK = {
    "strict_peer": 0,
    "near_cluster_peer": 1,
    "observation_candidate": 2,
}
RECENT_TIER_VERDICT_RANK = {
    "recent_tier_confirmed": 0,
    "recent_tier_mixed": 1,
    "recent_tier_thin": 2,
    "recent_tier_absent": 3,
    "no_recent_windows": 4,
}


def _metric_payload(row: dict[str, Any]) -> dict[str, Any]:
    return dict(row.get("metrics_payload") or {})


def _collect_rows(
    reports_root: str | Path,
    *,
    profile_name: str,
    report_name_contains: str,
    next_high_hit_threshold: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for report_dir in discover_report_dirs(reports_root, report_name_contains=report_name_contains):
        replay = analyze_btst_profile_replay_window(
            report_dir,
            profile_name=profile_name,
            label=Path(report_dir).name,
            next_high_hit_threshold=next_high_hit_threshold,
        )
        rows.extend(list(replay.get("rows") or []))
    return rows


def _build_anchor_profile(rows: list[dict[str, Any]], *, anchor_ticker: str) -> dict[str, Any]:
    anchor_rows = [row for row in rows if str(row.get("ticker") or "") == anchor_ticker and _is_continuation_row(row)]
    if not anchor_rows:
        raise ValueError(f"No continuation rows found for anchor ticker: {anchor_ticker}")

    metrics: dict[str, dict[str, float]] = {}
    for metric in REFERENCE_METRICS:
        values = [float(_metric_payload(row).get(metric)) for row in anchor_rows if _metric_payload(row).get(metric) is not None]
        if not values:
            continue
        metrics[metric] = {
            "min": round(min(values), 4),
            "max": round(max(values), 4),
            "mean": round(mean(values), 4),
        }

    return {
        "ticker": anchor_ticker,
        "observation_count": len(anchor_rows),
        "decision_counts": dict(Counter(str(row.get("decision") or "unknown") for row in anchor_rows)),
        "surface_summary": build_surface_summary(anchor_rows, next_high_hit_threshold=0.02),
        "metrics": metrics,
    }


def _row_similarity(row: dict[str, Any], *, anchor_profile: dict[str, Any], tolerances: dict[str, float]) -> tuple[float, dict[str, float], bool]:
    payload = _metric_payload(row)
    metric_distances: dict[str, float] = {}
    for metric, summary in dict(anchor_profile.get("metrics") or {}).items():
        value = payload.get(metric)
        if value is None:
            return (999.0, {}, False)
        anchor_mean = float(summary["mean"])
        tolerance = float(tolerances.get(metric, 0.05))
        metric_distances[metric] = round(abs(float(value) - anchor_mean) / max(tolerance, 1e-6), 4)

    if not metric_distances:
        return (999.0, {}, False)

    structure_match = all(
        float(_metric_payload(row).get(metric)) >= float(summary["min"]) - float(tolerances.get(metric, 0.05))
        and float(_metric_payload(row).get(metric)) <= float(summary["max"]) + float(tolerances.get(metric, 0.05))
        for metric, summary in dict(anchor_profile.get("metrics") or {}).items()
    )
    return (round(mean(metric_distances.values()), 4), metric_distances, structure_match)


def _is_peer_outcome_edge(row: dict[str, Any]) -> bool:
    next_close_return = row.get("next_close_return")
    t_plus_2_close_return = row.get("t_plus_2_close_return")
    if next_close_return is None or t_plus_2_close_return is None:
        return False
    return float(t_plus_2_close_return) > 0.0 and float(t_plus_2_close_return) > float(next_close_return)


def _classify_recent_tier_verdict(
    recent_tier_window_count: int,
    recent_window_count: int,
    recent_surface_summary: dict[str, Any],
) -> str:
    if recent_window_count <= 0:
        return "no_recent_windows"
    if recent_tier_window_count <= 0:
        return "recent_tier_absent"

    recent_tier_ratio = recent_tier_window_count / recent_window_count
    if recent_tier_ratio < 0.5:
        return "recent_tier_thin"

    next_close_positive_rate = recent_surface_summary.get("next_close_positive_rate")
    t_plus_2_close_positive_rate = recent_surface_summary.get("t_plus_2_close_positive_rate")
    next_high_hit_rate = recent_surface_summary.get("next_high_hit_rate_at_threshold")
    t_plus_2_mean = dict(recent_surface_summary.get("t_plus_2_close_return_distribution") or {}).get("mean")
    if (
        t_plus_2_close_positive_rate is not None
        and float(t_plus_2_close_positive_rate) >= 0.5
        and (
            (next_close_positive_rate is not None and float(next_close_positive_rate) >= 0.5)
            or (next_high_hit_rate is not None and float(next_high_hit_rate) >= 0.5)
            or (t_plus_2_mean is not None and float(t_plus_2_mean) > 0.0)
        )
    ):
        return "recent_tier_confirmed"
    return "recent_tier_mixed"


def _classify_peer_tier(
    row: dict[str, Any],
    *,
    structure_match: bool,
    similarity_score: float,
    strict_similarity_threshold: float,
    near_similarity_threshold: float,
    observation_similarity_threshold: float,
) -> str | None:
    next_close_return = row.get("next_close_return")
    t_plus_2_close_return = row.get("t_plus_2_close_return")
    next_high_return = row.get("next_high_return")
    if next_close_return is None or t_plus_2_close_return is None:
        return None

    next_close_return = float(next_close_return)
    t_plus_2_close_return = float(t_plus_2_close_return)
    next_high_return = float(next_high_return or 0.0)
    outcome_edge = t_plus_2_close_return > 0.0 and t_plus_2_close_return > next_close_return

    if structure_match and similarity_score <= strict_similarity_threshold and outcome_edge:
        return "strict_peer"
    if (
        similarity_score <= near_similarity_threshold
        and t_plus_2_close_return > 0.0
        and t_plus_2_close_return >= next_close_return - 0.01
    ):
        return "near_cluster_peer"
    if (
        similarity_score <= observation_similarity_threshold
        and (t_plus_2_close_return > 0.0 or next_high_return >= 0.02)
    ):
        return "observation_candidate"
    return None


def _summarize_tier_rows(
    grouped_rows: dict[str, list[dict[str, Any]]],
    *,
    next_high_hit_threshold: float,
    grouped_all_candidate_rows: dict[str, list[dict[str, Any]]],
    recent_window_limit: int,
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for ticker, ticker_rows in grouped_rows.items():
        ticker_rows = sorted(ticker_rows, key=lambda row: (float(row.get("similarity_score") or 999.0), str(row.get("trade_date") or "")))
        surface_summary = build_surface_summary(ticker_rows, next_high_hit_threshold=next_high_hit_threshold)
        all_candidate_rows = sorted(
            list(grouped_all_candidate_rows.get(ticker) or ticker_rows),
            key=lambda row: (str(row.get("report_label") or ""), str(row.get("trade_date") or "")),
        )
        per_window_rows: dict[str, list[dict[str, Any]]] = {}
        for row in all_candidate_rows:
            per_window_rows.setdefault(str(row.get("report_label") or "unknown"), []).append(row)
        ordered_recent_labels = sorted(per_window_rows)[-max(int(recent_window_limit), 0) :] if recent_window_limit > 0 else []
        recent_window_count = len(ordered_recent_labels)
        recent_tier_rows = [row for row in ticker_rows if str(row.get("report_label") or "") in set(ordered_recent_labels)]
        recent_tier_window_count = len({str(row.get("report_label") or "") for row in recent_tier_rows})
        recent_tier_ratio = round(recent_tier_window_count / recent_window_count, 4) if recent_window_count else 0.0
        recent_surface_summary = (
            build_surface_summary(recent_tier_rows, next_high_hit_threshold=next_high_hit_threshold) if recent_tier_rows else {}
        )
        recent_tier_verdict = _classify_recent_tier_verdict(
            recent_tier_window_count,
            recent_window_count,
            recent_surface_summary,
        )
        summaries.append(
            {
                "ticker": ticker,
                "observation_count": len(ticker_rows),
                "distinct_report_count": len({str(row.get("report_label") or "") for row in ticker_rows}),
                "decision_counts": dict(Counter(str(row.get("decision") or "unknown") for row in ticker_rows)),
                "mean_similarity_score": round(mean(float(row.get("similarity_score") or 999.0) for row in ticker_rows), 4),
                "surface_summary": surface_summary,
                "representative_row": ticker_rows[0],
                "tier": ticker_rows[0].get("peer_tier"),
                "recent_window_count": recent_window_count,
                "recent_tier_window_count": recent_tier_window_count,
                "recent_tier_ratio": recent_tier_ratio,
                "recent_tier_verdict": recent_tier_verdict,
                "recent_tier_surface_summary": recent_surface_summary,
            }
        )

    summaries.sort(
        key=lambda item: (
            RECENT_TIER_VERDICT_RANK.get(str(item.get("recent_tier_verdict") or "no_recent_windows"), 99),
            -int(item.get("recent_tier_window_count") or 0),
            -float(item.get("recent_tier_ratio") or 0.0),
            -int(item["distinct_report_count"]),
            -int(item["observation_count"]),
            TIER_RANK.get(str(item.get("tier") or "observation_candidate"), 99),
            float(item["mean_similarity_score"]),
            -float(item["surface_summary"].get("t_plus_2_close_positive_rate") or -1.0),
            item["ticker"],
        ),
    )
    return summaries


def _classify_peer_candidate_rows(
    rows: list[dict[str, Any]],
    *,
    anchor_ticker: str,
    anchor_profile: dict[str, Any],
    similarity_threshold: float,
    near_similarity_threshold: float,
    observation_similarity_threshold: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    strict_peer_rows: list[dict[str, Any]] = []
    near_peer_rows: list[dict[str, Any]] = []
    observation_candidate_rows: list[dict[str, Any]] = []
    rejected_rows: list[dict[str, Any]] = []
    grouped_all_candidate_rows: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        ticker = str(row.get("ticker") or "")
        if not ticker or ticker == anchor_ticker or str(row.get("candidate_source") or "") != "layer_c_watchlist":
            continue
        candidate_row = _build_peer_candidate_row(
            row,
            anchor_profile=anchor_profile,
            observation_similarity_threshold=observation_similarity_threshold,
        )
        if not candidate_row:
            continue
        grouped_all_candidate_rows.setdefault(ticker, []).append(candidate_row)
        peer_tier = _classify_peer_tier(
            candidate_row,
            structure_match=bool(candidate_row.get("structure_match")),
            similarity_score=float(candidate_row.get("similarity_score") or 999.0),
            strict_similarity_threshold=similarity_threshold,
            near_similarity_threshold=near_similarity_threshold,
            observation_similarity_threshold=observation_similarity_threshold,
        )
        if peer_tier is None:
            rejected_rows.append(candidate_row)
            continue
        candidate_row["peer_tier"] = peer_tier
        if peer_tier == "strict_peer":
            strict_peer_rows.append(candidate_row)
        elif peer_tier == "near_cluster_peer":
            near_peer_rows.append(candidate_row)
        else:
            observation_candidate_rows.append(candidate_row)
    return strict_peer_rows, near_peer_rows, observation_candidate_rows, rejected_rows, grouped_all_candidate_rows


def _build_peer_candidate_row(
    row: dict[str, Any],
    *,
    anchor_profile: dict[str, Any],
    observation_similarity_threshold: float,
) -> dict[str, Any] | None:
    similarity_score, metric_distances, structure_match = _row_similarity(row, anchor_profile=anchor_profile, tolerances=DEFAULT_TOLERANCES)
    if not metric_distances or similarity_score > observation_similarity_threshold:
        return None
    return {
        **row,
        "similarity_score": similarity_score,
        "metric_distances": metric_distances,
        "peer_outcome_edge": _is_peer_outcome_edge(row),
        "structure_match": structure_match,
    }


def _group_rows_by_ticker(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped_rows: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped_rows.setdefault(str(row.get("ticker") or ""), []).append(row)
    return grouped_rows


def _build_peer_scan_recommendation(
    *,
    peer_summaries: list[dict[str, Any]],
    near_peer_summaries: list[dict[str, Any]],
    observation_candidate_summaries: list[dict[str, Any]],
    anchor_ticker: str,
) -> str:
    if peer_summaries:
        return "Found same-cluster continuation peers. Next step should promote them into a dedicated T+2 observation lane and validate pooled outcomes."
    if near_peer_summaries or observation_candidate_summaries:
        return f"No strict same-cluster peer passed around {anchor_ticker}, but tiered expansion found near-cluster / observation candidates worth tracking outside the default BTST surface."
    return f"No same-cluster peer passed the structural + T+2 edge scan around {anchor_ticker}. Treat the current continuation lane as a single-ticker pattern until more windows accumulate."


def _summarize_scan_tiers(
    *,
    strict_peer_rows: list[dict[str, Any]],
    near_peer_rows: list[dict[str, Any]],
    observation_candidate_rows: list[dict[str, Any]],
    grouped_all_candidate_rows: dict[str, list[dict[str, Any]]],
    next_high_hit_threshold: float,
    recent_window_limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    return (
        _summarize_tier_rows(
            _group_rows_by_ticker(strict_peer_rows),
            next_high_hit_threshold=next_high_hit_threshold,
            grouped_all_candidate_rows=grouped_all_candidate_rows,
            recent_window_limit=recent_window_limit,
        ),
        _summarize_tier_rows(
            _group_rows_by_ticker(near_peer_rows),
            next_high_hit_threshold=next_high_hit_threshold,
            grouped_all_candidate_rows=grouped_all_candidate_rows,
            recent_window_limit=recent_window_limit,
        ),
        _summarize_tier_rows(
            _group_rows_by_ticker(observation_candidate_rows),
            next_high_hit_threshold=next_high_hit_threshold,
            grouped_all_candidate_rows=grouped_all_candidate_rows,
            recent_window_limit=recent_window_limit,
        ),
    )


def _build_peer_scan_analysis(
    *,
    reports_root: str | Path,
    profile_name: str,
    report_name_contains: str,
    anchor_ticker: str,
    next_high_hit_threshold: float,
    similarity_threshold: float,
    near_similarity_threshold: float,
    observation_similarity_threshold: float,
    recent_window_limit: int,
    anchor_profile: dict[str, Any],
    peer_summaries: list[dict[str, Any]],
    near_peer_summaries: list[dict[str, Any]],
    observation_candidate_summaries: list[dict[str, Any]],
    rejected_rows: list[dict[str, Any]],
    recommendation: str,
) -> dict[str, Any]:
    return {
        "reports_root": str(Path(reports_root).expanduser().resolve()),
        "profile_name": profile_name,
        "report_name_contains": report_name_contains,
        "anchor_ticker": anchor_ticker,
        "next_high_hit_threshold": next_high_hit_threshold,
        "similarity_threshold": similarity_threshold,
        "near_similarity_threshold": near_similarity_threshold,
        "observation_similarity_threshold": observation_similarity_threshold,
        "recent_window_limit": recent_window_limit,
        "anchor_profile": anchor_profile,
        "peer_count": len(peer_summaries),
        "peer_summaries": peer_summaries,
        "near_cluster_count": len(near_peer_summaries),
        "near_peer_summaries": near_peer_summaries,
        "observation_candidate_count": len(observation_candidate_summaries),
        "observation_candidate_summaries": observation_candidate_summaries,
        "near_peer_rejections": rejected_rows[:12],
        "recommendation": recommendation,
    }


def analyze_btst_tplus2_continuation_peer_scan(
    reports_root: str | Path,
    *,
    anchor_ticker: str = "600988",
    profile_name: str = "watchlist_zero_catalyst_guard_relief",
    report_name_contains: str = "btst_",
    next_high_hit_threshold: float = 0.02,
    similarity_threshold: float = 1.35,
    near_similarity_threshold: float = 2.1,
    observation_similarity_threshold: float = 2.8,
    recent_window_limit: int = 5,
) -> dict[str, Any]:
    rows = _collect_rows(
        reports_root,
        profile_name=profile_name,
        report_name_contains=report_name_contains,
        next_high_hit_threshold=next_high_hit_threshold,
    )
    anchor_profile = _build_anchor_profile(rows, anchor_ticker=anchor_ticker)
    strict_peer_rows, near_peer_rows, observation_candidate_rows, rejected_rows, grouped_all_candidate_rows = _classify_peer_candidate_rows(
        rows,
        anchor_ticker=anchor_ticker,
        anchor_profile=anchor_profile,
        similarity_threshold=similarity_threshold,
        near_similarity_threshold=near_similarity_threshold,
        observation_similarity_threshold=observation_similarity_threshold,
    )

    peer_summaries, near_peer_summaries, observation_candidate_summaries = _summarize_scan_tiers(
        strict_peer_rows=strict_peer_rows,
        near_peer_rows=near_peer_rows,
        observation_candidate_rows=observation_candidate_rows,
        grouped_all_candidate_rows=grouped_all_candidate_rows,
        next_high_hit_threshold=next_high_hit_threshold,
        recent_window_limit=recent_window_limit,
    )

    rejected_rows.sort(key=lambda row: (float(row.get("similarity_score") or 999.0), str(row.get("ticker") or ""), str(row.get("trade_date") or "")))
    recommendation = _build_peer_scan_recommendation(
        peer_summaries=peer_summaries,
        near_peer_summaries=near_peer_summaries,
        observation_candidate_summaries=observation_candidate_summaries,
        anchor_ticker=anchor_ticker,
    )
    return _build_peer_scan_analysis(
        reports_root=reports_root,
        profile_name=profile_name,
        report_name_contains=report_name_contains,
        anchor_ticker=anchor_ticker,
        next_high_hit_threshold=next_high_hit_threshold,
        similarity_threshold=similarity_threshold,
        near_similarity_threshold=near_similarity_threshold,
        observation_similarity_threshold=observation_similarity_threshold,
        recent_window_limit=recent_window_limit,
        anchor_profile=anchor_profile,
        peer_summaries=peer_summaries,
        near_peer_summaries=near_peer_summaries,
        observation_candidate_summaries=observation_candidate_summaries,
        rejected_rows=rejected_rows,
        recommendation=recommendation,
    )


def render_btst_tplus2_continuation_peer_scan_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST T+2 Continuation Peer Scan")
    lines.append("")
    lines.append("## Anchor")
    lines.append(f"- anchor_ticker: {analysis['anchor_ticker']}")
    lines.append(f"- peer_count: {analysis['peer_count']}")
    lines.append(f"- similarity_threshold: {analysis['similarity_threshold']}")
    lines.append(f"- near_similarity_threshold: {analysis['near_similarity_threshold']}")
    lines.append(f"- observation_similarity_threshold: {analysis['observation_similarity_threshold']}")
    lines.append(f"- recent_window_limit: {analysis['recent_window_limit']}")
    lines.append(f"- anchor_profile: {analysis['anchor_profile']}")
    lines.append("")
    lines.append("## Same-Cluster Peers")
    for item in list(analysis.get("peer_summaries") or []):
        surface = dict(item.get("surface_summary") or {})
        lines.append(
            f"- {item['ticker']}: reports={item['distinct_report_count']}, observations={item['observation_count']}, "
            f"mean_similarity_score={item['mean_similarity_score']}, "
            f"recent_tier_window_count={item['recent_tier_window_count']}/{item['recent_window_count']}, "
            f"recent_tier_ratio={item['recent_tier_ratio']}, recent_tier_verdict={item['recent_tier_verdict']}, "
            f"next_close_positive_rate={surface.get('next_close_positive_rate')}, "
            f"t_plus_2_close_positive_rate={surface.get('t_plus_2_close_positive_rate')}"
        )
    if not list(analysis.get("peer_summaries") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Near-Cluster Peers")
    for item in list(analysis.get("near_peer_summaries") or []):
        surface = dict(item.get("surface_summary") or {})
        lines.append(
            f"- {item['ticker']}: reports={item['distinct_report_count']}, observations={item['observation_count']}, "
            f"mean_similarity_score={item['mean_similarity_score']}, "
            f"recent_tier_window_count={item['recent_tier_window_count']}/{item['recent_window_count']}, "
            f"recent_tier_ratio={item['recent_tier_ratio']}, recent_tier_verdict={item['recent_tier_verdict']}, "
            f"next_close_positive_rate={surface.get('next_close_positive_rate')}, "
            f"t_plus_2_close_positive_rate={surface.get('t_plus_2_close_positive_rate')}"
        )
    if not list(analysis.get("near_peer_summaries") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Observation Candidates")
    for item in list(analysis.get("observation_candidate_summaries") or []):
        surface = dict(item.get("surface_summary") or {})
        lines.append(
            f"- {item['ticker']}: reports={item['distinct_report_count']}, observations={item['observation_count']}, "
            f"mean_similarity_score={item['mean_similarity_score']}, "
            f"recent_tier_window_count={item['recent_tier_window_count']}/{item['recent_window_count']}, "
            f"recent_tier_ratio={item['recent_tier_ratio']}, recent_tier_verdict={item['recent_tier_verdict']}, "
            f"next_close_positive_rate={surface.get('next_close_positive_rate')}, "
            f"t_plus_2_close_positive_rate={surface.get('t_plus_2_close_positive_rate')}"
        )
    if not list(analysis.get("observation_candidate_summaries") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Search for 600988-like T+2 continuation peers across BTST replay windows.")
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--report-name-contains", default="btst_")
    parser.add_argument("--profile-name", default="watchlist_zero_catalyst_guard_relief")
    parser.add_argument("--anchor-ticker", default="600988")
    parser.add_argument("--next-high-hit-threshold", type=float, default=0.02)
    parser.add_argument("--similarity-threshold", type=float, default=1.35)
    parser.add_argument("--near-similarity-threshold", type=float, default=2.1)
    parser.add_argument("--observation-similarity-threshold", type=float, default=2.8)
    parser.add_argument("--recent-window-limit", type=int, default=5)
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_tplus2_continuation_peer_scan(
        args.reports_root,
        anchor_ticker=str(args.anchor_ticker or "600988"),
        profile_name=str(args.profile_name or "watchlist_zero_catalyst_guard_relief"),
        report_name_contains=str(args.report_name_contains or "btst_"),
        next_high_hit_threshold=float(args.next_high_hit_threshold),
        similarity_threshold=float(args.similarity_threshold),
        near_similarity_threshold=float(args.near_similarity_threshold),
        observation_similarity_threshold=float(args.observation_similarity_threshold),
        recent_window_limit=int(args.recent_window_limit),
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_tplus2_continuation_peer_scan_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
