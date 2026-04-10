from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _load_lane_objective_support(path: str | Path | None) -> dict[str, dict[str, Any]]:
    if not path:
        return {}
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return {}
    payload = _load_json(resolved)
    rows_by_handoff: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(list(payload.get("branch_rows") or []), start=1):
        handoff = str(row.get("priority_handoff") or "").strip()
        if not handoff:
            continue
        enriched = dict(row)
        enriched["objective_support_rank"] = index
        rows_by_handoff[handoff] = enriched
    return rows_by_handoff


def _round(value: float | int | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _readiness_rank(value: str) -> int:
    order = {
        "shadow_ready_rebucket_signal": 1,
        "shadow_ready_boundary_gap": 2,
        "shadow_ready_large_gap": 3,
        "shadow_ready_without_rebucket_signal": 4,
        "research_only": 9,
    }
    return int(order.get(str(value or ""), 99))


def _build_corridor_ticker_rows(priority_ticker_dossiers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for dossier in priority_ticker_dossiers:
        ticker = str(dossier.get("ticker") or "").strip()
        profile = dict(dossier.get("truncation_liquidity_profile") or {})
        if str(profile.get("priority_handoff") or "") != "layer_a_liquidity_corridor":
            continue
        occurrences = [
            dict(row)
            for row in list(dossier.get("occurrence_evidence") or [])
            if str(row.get("blocking_stage") or "") == "candidate_pool_truncated_after_filters"
        ]
        uplift_values = [
            round(1.0 / float(value), 4)
            for value in [row.get("pre_truncation_avg_amount_share_of_cutoff") for row in occurrences]
            if isinstance(value, (int, float)) and float(value) > 0
        ]
        rank_gaps = [float(row.get("pre_truncation_rank_gap_to_cutoff")) for row in occurrences if isinstance(row.get("pre_truncation_rank_gap_to_cutoff"), (int, float))]
        rebucket_gaps = [float(row.get("estimated_rank_gap_after_rebucket")) for row in occurrences if isinstance(row.get("estimated_rank_gap_after_rebucket"), (int, float))]
        lower_cap_counts = [float(row.get("top300_lower_market_cap_hot_peer_count")) for row in occurrences if isinstance(row.get("top300_lower_market_cap_hot_peer_count"), (int, float))]
        uplift_mean = _mean(uplift_values)
        if uplift_mean is None:
            tractability_tier = "research_only"
        elif uplift_mean <= 5.0:
            tractability_tier = "first_shadow_probe"
        elif uplift_mean <= 10.0:
            tractability_tier = "second_shadow_probe"
        else:
            tractability_tier = "upstream_research_only"
        rows.append(
            {
                "ticker": ticker,
                "occurrence_count": len(occurrences),
                "uplift_to_cutoff_multiple_mean": uplift_mean,
                "uplift_to_cutoff_multiple_min": min(uplift_values) if uplift_values else None,
                "uplift_to_cutoff_multiple_max": max(uplift_values) if uplift_values else None,
                "avg_rank_gap_to_cutoff": _mean(rank_gaps),
                "estimated_rank_gap_after_rebucket_mean": _mean(rebucket_gaps),
                "top300_lower_market_cap_hot_peer_count_mean": _mean(lower_cap_counts),
                "tractability_tier": tractability_tier,
                "profile_summary": profile.get("profile_summary"),
            }
        )
    rows.sort(
        key=lambda row: (
            {"first_shadow_probe": 1, "second_shadow_probe": 2, "upstream_research_only": 3, "research_only": 9}.get(str(row.get("tractability_tier") or ""), 99),
            float(row.get("uplift_to_cutoff_multiple_mean") or 9999.0),
            str(row.get("ticker") or ""),
        )
    )
    for index, row in enumerate(rows, start=1):
        row["corridor_priority_rank"] = index
    return rows


def _build_branch_rows(branch_queue: list[dict[str, Any]], objective_rows_by_handoff: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    branch_rows: list[dict[str, Any]] = []
    for row in branch_queue:
        handoff = str(row.get("priority_handoff") or "")
        prototype_readiness = str(row.get("prototype_readiness") or "")
        objective_row = dict(objective_rows_by_handoff.get(handoff) or {})
        branch_rows.append(
            {
                "priority_handoff": handoff,
                "task_id": row.get("task_id"),
                "tickers": list(row.get("tickers") or []),
                "prototype_type": row.get("prototype_type"),
                "prototype_readiness": prototype_readiness,
                "branch_queue_rank": row.get("priority_rank"),
                "execution_priority_rank_hint": _resolve_execution_priority_rank_hint(handoff, prototype_readiness),
                "uplift_to_cutoff_multiple_mean": row.get("uplift_to_cutoff_multiple_mean"),
                "top300_lower_market_cap_hot_peer_count_mean": row.get("top300_lower_market_cap_hot_peer_count_mean"),
                "estimated_rank_gap_after_rebucket_mean": row.get("estimated_rank_gap_after_rebucket_mean"),
                "evaluation_summary": row.get("evaluation_summary"),
                "guardrail_summary": row.get("guardrail_summary"),
                "objective_support_rank": objective_row.get("objective_support_rank"),
                "objective_support_verdict": objective_row.get("support_verdict"),
                "objective_closed_cycle_count": objective_row.get("closed_cycle_count"),
                "objective_mean_t_plus_2_return": objective_row.get("mean_t_plus_2_return"),
                "objective_return_hit_rate": objective_row.get("t_plus_2_return_hit_rate_at_target"),
            }
        )
    branch_rows.sort(
        key=lambda row: (
            int(row.get("execution_priority_rank_hint") or 99),
            _readiness_rank(str(row.get("prototype_readiness") or "")),
            float(row.get("uplift_to_cutoff_multiple_mean") or 9999.0),
            -float(row.get("top300_lower_market_cap_hot_peer_count_mean") or 0.0),
            str(row.get("priority_handoff") or ""),
        )
    )
    for index, row in enumerate(branch_rows, start=1):
        row["execution_priority_rank"] = index
    return branch_rows


def _resolve_execution_priority_rank_hint(handoff: str, prototype_readiness: str) -> int:
    if handoff == "post_gate_liquidity_competition" and prototype_readiness == "shadow_ready_rebucket_signal":
        return 1
    if handoff == "layer_a_liquidity_corridor":
        return 2
    return 3 + _readiness_rank(prototype_readiness)


def _build_priority_alignment(
    branch_rows: list[dict[str, Any]], objective_rows_by_handoff: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    structural_leader = dict(branch_rows[0]) if branch_rows else {}
    objective_leader = dict(min(objective_rows_by_handoff.values(), key=lambda row: int(row.get("objective_support_rank") or 999))) if objective_rows_by_handoff else {}
    priority_alignment_status = "no_objective_support"
    alignment_summary = "当前缺少 lane objective support，branch priority board 仍只能按结构 tractability 排序。"
    if not (structural_leader and objective_leader):
        return structural_leader, objective_leader, priority_alignment_status, alignment_summary
    if str(structural_leader.get("priority_handoff") or "") == str(objective_leader.get("priority_handoff") or ""):
        return (
            structural_leader,
            objective_leader,
            "aligned_top_lane",
            f"结构优先 lane 与后验证据 leader 一致，当前都指向 {structural_leader.get('priority_handoff')}。",
        )
    return (
        structural_leader,
        objective_leader,
        "divergent_top_lane",
        (
            f"结构 tractability 当前优先 {structural_leader.get('priority_handoff')}，"
            f"但后验证据 leader 是 {objective_leader.get('priority_handoff')}。"
        ),
    )


def _build_next_3_tasks(
    branch_rows: list[dict[str, Any]],
    corridor_ticker_rows: list[dict[str, Any]],
    priority_alignment_status: str,
    objective_leader: dict[str, Any],
) -> list[dict[str, Any]]:
    next_3_tasks: list[dict[str, Any]] = []
    if branch_rows:
        next_3_tasks.append(_build_structural_leader_task(branch_rows[0]))
    if priority_alignment_status == "divergent_top_lane" and objective_leader:
        next_3_tasks.append(_build_objective_followup_task(objective_leader))
    for row in corridor_ticker_rows[:2]:
        next_3_tasks.append(
            {
                "task_id": f"corridor_{row['ticker']}_uplift_probe",
                "title": f"排序 {row['ticker']} corridor uplift 优先级",
                "why_now": f"当前 uplift burden={row.get('uplift_to_cutoff_multiple_mean')}，tractability_tier={row.get('tractability_tier')}。",
                "next_step": "按 uplift burden 从低到高安排 shadow uplift 观察顺序。",
            }
        )
    return next_3_tasks[:3]


def _build_structural_leader_task(leader: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": str(leader.get("task_id") or "candidate_pool_branch_task"),
        "title": f"优先推进 {leader.get('priority_handoff')} shadow lane",
        "why_now": str(leader.get("evaluation_summary") or ""),
        "next_step": "先生成 branch-specific shadow pack，并保持 guardrail 不变。",
    }


def _build_objective_followup_task(objective_leader: dict[str, Any]) -> dict[str, Any]:
    objective_handoff = str(objective_leader.get("priority_handoff") or "")
    return {
        "task_id": f"objective_followup_{objective_handoff}",
        "title": f"补强 {objective_handoff} 的收益验证 lane",
        "why_now": (
            f"后验 support_verdict={objective_leader.get('support_verdict')}，"
            f"mean_t_plus_2_return={objective_leader.get('mean_t_plus_2_return')}。"
        ),
        "next_step": "保持结构 guardrail，不改现网阈值，先补齐 objective-led parallel validation。",
    }


def _build_recommendation(
    branch_rows: list[dict[str, Any]],
    corridor_ticker_rows: list[dict[str, Any]],
    priority_alignment_status: str,
    objective_leader: dict[str, Any],
) -> str:
    if not branch_rows:
        return "当前 candidate-pool recall 的第一优先 lane 应切到 post_gate competition rebucket shadow，其次再按 corridor uplift burden 排序 003036/300720 这类上游流动性修复样本。"
    leader = branch_rows[0]
    recommendation = (
        f"当前 candidate-pool recall 的第一优先 lane 是 {leader['priority_handoff']}，"
        f"因为它已进入 {leader['prototype_readiness']} 且 {leader.get('evaluation_summary') or ''}"
    )
    if corridor_ticker_rows:
        recommendation = f"{recommendation} corridor 车道内部则应优先处理 {corridor_ticker_rows[0]['ticker']}。"
    if priority_alignment_status == "divergent_top_lane" and objective_leader:
        recommendation = (
            f"{recommendation} 但后验证据更强的 lane 是 {objective_leader.get('priority_handoff')}，"
            f"support_verdict={objective_leader.get('support_verdict')}，mean_t_plus_2_return={objective_leader.get('mean_t_plus_2_return')}，"
            "因此应保持当前结构第一实验不变，同时把 objective leader 升级为并行验证主线。"
        )
    return recommendation


def analyze_btst_candidate_pool_branch_priority_board(dossier_path: str | Path, lane_objective_support_path: str | Path | None = None) -> dict[str, Any]:
    dossier = _load_json(dossier_path)
    branch_queue = [dict(row) for row in list(dossier.get("priority_handoff_branch_experiment_queue") or [])]
    priority_ticker_dossiers = [dict(row) for row in list(dossier.get("priority_ticker_dossiers") or [])]
    corridor_ticker_rows = _build_corridor_ticker_rows(priority_ticker_dossiers)
    objective_rows_by_handoff = _load_lane_objective_support(lane_objective_support_path)
    branch_rows = _build_branch_rows(branch_queue, objective_rows_by_handoff)
    structural_leader, objective_leader, priority_alignment_status, alignment_summary = _build_priority_alignment(
        branch_rows, objective_rows_by_handoff
    )
    next_3_tasks = _build_next_3_tasks(
        branch_rows,
        corridor_ticker_rows,
        priority_alignment_status,
        objective_leader,
    )
    recommendation = _build_recommendation(
        branch_rows,
        corridor_ticker_rows,
        priority_alignment_status,
        objective_leader,
    )

    return {
        "dossier_path": str(Path(dossier_path).expanduser().resolve()),
        "lane_objective_support_path": str(Path(lane_objective_support_path).expanduser().resolve()) if lane_objective_support_path else None,
        "branch_count": len(branch_rows),
        "branch_rows": branch_rows,
        "corridor_ticker_rows": corridor_ticker_rows,
        "priority_alignment_status": priority_alignment_status,
        "alignment_summary": alignment_summary,
        "top_structural_handoff": structural_leader.get("priority_handoff"),
        "top_objective_handoff": objective_leader.get("priority_handoff"),
        "next_3_tasks": next_3_tasks,
        "recommendation": recommendation,
    }


def render_btst_candidate_pool_branch_priority_board_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Candidate Pool Branch Priority Board")
    lines.append("")
    lines.append("## Branches")
    for row in list(analysis.get("branch_rows") or []):
        lines.append(
            f"- rank={row['execution_priority_rank']} handoff={row['priority_handoff']} readiness={row['prototype_readiness']} tickers={row['tickers']} uplift_to_cutoff_multiple_mean={row.get('uplift_to_cutoff_multiple_mean')} smaller_cap_hot_peer_count_mean={row.get('top300_lower_market_cap_hot_peer_count_mean')}"
        )
        lines.append(f"  evaluation_summary: {row.get('evaluation_summary')}")
        lines.append(f"  guardrail_summary: {row.get('guardrail_summary')}")
        if row.get("objective_support_verdict") is not None:
            lines.append(
                f"  objective_support: rank={row.get('objective_support_rank')} verdict={row.get('objective_support_verdict')} closed_cycle_count={row.get('objective_closed_cycle_count')} mean_t_plus_2_return={row.get('objective_mean_t_plus_2_return')} return_hit_rate={row.get('objective_return_hit_rate')}"
            )
    lines.append("")
    lines.append("## Alignment")
    lines.append(f"- priority_alignment_status: {analysis.get('priority_alignment_status')}")
    lines.append(f"- top_structural_handoff: {analysis.get('top_structural_handoff')}")
    lines.append(f"- top_objective_handoff: {analysis.get('top_objective_handoff')}")
    lines.append(f"- alignment_summary: {analysis.get('alignment_summary')}")
    lines.append("")
    lines.append("## Corridor Tickers")
    for row in list(analysis.get("corridor_ticker_rows") or []):
        lines.append(
            f"- rank={row['corridor_priority_rank']} ticker={row['ticker']} tractability_tier={row['tractability_tier']} uplift_to_cutoff_multiple_mean={row.get('uplift_to_cutoff_multiple_mean')} occurrence_count={row['occurrence_count']} avg_rank_gap_to_cutoff={row.get('avg_rank_gap_to_cutoff')}"
        )
        lines.append(f"  profile_summary: {row.get('profile_summary')}")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis.get('recommendation')}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Prioritize BTST candidate-pool recall branches for the next shadow experiments.")
    parser.add_argument("--dossier-path", default="data/reports/btst_candidate_pool_recall_dossier_latest.json")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    analysis = analyze_btst_candidate_pool_branch_priority_board(args.dossier_path)
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_btst_candidate_pool_branch_priority_board_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
