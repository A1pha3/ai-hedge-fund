from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPORTS_DIR = Path("data/reports")
DEFAULT_OBJECTIVE_MONITOR_PATH = REPORTS_DIR / "btst_tplus1_tplus2_objective_monitor_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_continuation_merge_candidate_ranking_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_continuation_merge_candidate_ranking_latest.md"


def _load_optional_json(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return {}
    return json.loads(resolved.read_text(encoding="utf-8"))


def _stage_rank(row: dict[str, Any]) -> int:
    promotion_path_status = str(row.get("promotion_path_status") or "").strip()
    promotion_readiness_verdict = str(row.get("promotion_readiness_verdict") or "").strip()
    dossier_verdict = str(row.get("verdict") or "").strip()
    if promotion_path_status == "merge_review_ready":
        return 5
    if promotion_readiness_verdict == "validation_queue_ready":
        return 4
    if dossier_verdict == "governance_followup_candidate":
        return 3
    if dossier_verdict == "observation_only_candidate":
        return 2
    return 1


def _build_candidate_row(dossier: dict[str, Any], default_surface: dict[str, Any]) -> dict[str, Any]:
    governance_objective_support = dict(dossier.get("governance_objective_support") or {})
    tier_focus_surface = dict(dossier.get("tier_focus_surface_summary") or {})
    surface = governance_objective_support if int(governance_objective_support.get("closed_cycle_count") or 0) > 0 else tier_focus_surface
    closed_cycle_count = int(surface.get("closed_cycle_count") or 0)
    candidate_positive_rate = surface.get("t_plus_2_positive_rate") or surface.get("t_plus_2_close_positive_rate")
    candidate_mean_return = surface.get("mean_t_plus_2_return") or dict(surface.get("t_plus_2_close_return_distribution") or {}).get("mean")
    default_positive_rate = default_surface.get("t_plus_2_positive_rate")
    default_mean_return = default_surface.get("mean_t_plus_2_return")
    positive_rate_delta = (
        round(float(candidate_positive_rate) - float(default_positive_rate), 4)
        if candidate_positive_rate is not None and default_positive_rate is not None
        else None
    )
    mean_return_delta = (
        round(float(candidate_mean_return) - float(default_mean_return), 4)
        if candidate_mean_return is not None and default_mean_return is not None
        else None
    )
    recent_support_ratio = float(dossier.get("recent_support_ratio") or 0.0)
    observed_independent_window_count = dossier.get("observed_independent_window_count")
    ranking_score = round(
        _stage_rank(dossier) * 100
        + closed_cycle_count
        + recent_support_ratio * 20
        + (float(positive_rate_delta) * 100 if positive_rate_delta is not None else 0.0)
        + (float(mean_return_delta) * 100 if mean_return_delta is not None else 0.0),
        4,
    )
    return {
        "ticker": dossier.get("candidate_ticker"),
        "verdict": dossier.get("verdict"),
        "candidate_tier_focus": dossier.get("candidate_tier_focus"),
        "promotion_readiness_verdict": dossier.get("promotion_readiness_verdict"),
        "promotion_path_status": dossier.get("promotion_path_status"),
        "promotion_merge_review_verdict": dossier.get("promotion_merge_review_verdict"),
        "latest_followup_decision": dossier.get("latest_followup_decision") or dict(dossier.get("governance_followup") or {}).get("latest_followup_decision"),
        "closed_cycle_count": closed_cycle_count,
        "recent_support_ratio": recent_support_ratio,
        "observed_independent_window_count": observed_independent_window_count,
        "t_plus_2_positive_rate": candidate_positive_rate,
        "mean_t_plus_2_return": candidate_mean_return,
        "t_plus_2_positive_rate_delta_vs_default_btst": positive_rate_delta,
        "mean_t_plus_2_return_delta_vs_default_btst": mean_return_delta,
        "support_verdict": governance_objective_support.get("support_verdict"),
        "ranking_score": ranking_score,
    }


def generate_btst_continuation_merge_candidate_ranking(
    *,
    reports_root: str | Path = REPORTS_DIR,
    objective_monitor_path: str | Path = DEFAULT_OBJECTIVE_MONITOR_PATH,
) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    objective_monitor = _load_optional_json(objective_monitor_path)
    default_surface = dict(objective_monitor.get("tradeable_surface") or {})
    rows: list[dict[str, Any]] = []
    for dossier_path in sorted(resolved_reports_root.glob("btst_tplus2_candidate_dossier_*_latest.json")):
        dossier = _load_optional_json(dossier_path)
        if not dossier:
            continue
        rows.append(_build_candidate_row(dossier, default_surface))
    rows.sort(
        key=lambda row: (
            -_stage_rank(row),
            -(float(row.get("ranking_score") or 0.0)),
            -(int(row.get("closed_cycle_count") or 0)),
            str(row.get("ticker") or ""),
        )
    )
    for index, row in enumerate(rows, start=1):
        row["merge_candidate_rank"] = index

    top_candidate = rows[0] if rows else {}
    recommendation = (
        f"当前最值得继续推进 merge path 的 continuation 候选是 {top_candidate.get('ticker')}，"
        f"stage={top_candidate.get('promotion_path_status') or top_candidate.get('promotion_readiness_verdict')},"
        f" positive_rate_delta={top_candidate.get('t_plus_2_positive_rate_delta_vs_default_btst')},"
        f" mean_return_delta={top_candidate.get('mean_t_plus_2_return_delta_vs_default_btst')}。"
        if top_candidate
        else "当前没有可用的 continuation candidate dossier，无法构建 merge candidate ranking。"
    )
    return {
        "candidate_count": len(rows),
        "default_btst_tradeable_surface": {
            "closed_cycle_count": default_surface.get("closed_cycle_count"),
            "t_plus_2_positive_rate": default_surface.get("t_plus_2_positive_rate"),
            "mean_t_plus_2_return": default_surface.get("mean_t_plus_2_return"),
        },
        "top_candidate": top_candidate or None,
        "ranked_candidates": rows,
        "recommendation": recommendation,
    }


def render_btst_continuation_merge_candidate_ranking_markdown(analysis: dict[str, Any]) -> str:
    lines = [
        "# BTST Continuation Merge Candidate Ranking",
        "",
        "## Overview",
        f"- candidate_count: {analysis.get('candidate_count')}",
        f"- default_btst_tradeable_surface: {analysis.get('default_btst_tradeable_surface')}",
        f"- top_candidate: {analysis.get('top_candidate')}",
        "",
        "## Top Ranked Candidates",
    ]
    for row in list(analysis.get("ranked_candidates") or [])[:5]:
        lines.append(
            f"- rank={row.get('merge_candidate_rank')} ticker={row.get('ticker')} stage={row.get('promotion_path_status') or row.get('promotion_readiness_verdict')} ranking_score={row.get('ranking_score')} positive_rate_delta={row.get('t_plus_2_positive_rate_delta_vs_default_btst')} mean_return_delta={row.get('mean_t_plus_2_return_delta_vs_default_btst')}"
        )
    lines.extend(["", "## Recommendation", f"- {analysis.get('recommendation')}"])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Rank continuation candidates by expected merge value versus default BTST.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR))
    parser.add_argument("--objective-monitor-path", default=str(DEFAULT_OBJECTIVE_MONITOR_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = generate_btst_continuation_merge_candidate_ranking(
        reports_root=args.reports_root,
        objective_monitor_path=args.objective_monitor_path,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_continuation_merge_candidate_ranking_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
