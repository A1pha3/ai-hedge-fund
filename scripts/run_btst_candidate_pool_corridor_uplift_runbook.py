from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.run_btst_candidate_pool_corridor_shadow_pack import analyze_btst_candidate_pool_corridor_shadow_pack
from scripts.run_btst_candidate_pool_lane_pair_board import analyze_btst_candidate_pool_lane_pair_board


REPORTS_DIR = Path("data/reports")
DEFAULT_CANDIDATE_POOL_RECALL_DOSSIER_PATH = REPORTS_DIR / "btst_candidate_pool_recall_dossier_latest.json"
DEFAULT_CORRIDOR_SHADOW_PACK_PATH = REPORTS_DIR / "btst_candidate_pool_corridor_shadow_pack_latest.json"
DEFAULT_LANE_PAIR_BOARD_PATH = REPORTS_DIR / "btst_candidate_pool_lane_pair_board_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_candidate_pool_corridor_uplift_runbook_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_candidate_pool_corridor_uplift_runbook_latest.md"


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _maybe_load_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return {}
    return _load_json(resolved)


def _find_corridor_experiment(recall_dossier: dict[str, Any]) -> dict[str, Any]:
    for row in list(recall_dossier.get("priority_handoff_branch_experiment_queue") or []):
        if str(row.get("priority_handoff") or "") == "layer_a_liquidity_corridor":
            return dict(row)
    return {}


def analyze_btst_candidate_pool_corridor_uplift_runbook(
    candidate_pool_recall_dossier_path: str | Path,
    *,
    corridor_shadow_pack_path: str | Path | None = None,
    lane_pair_board_path: str | Path | None = None,
) -> dict[str, Any]:
    recall_dossier = _maybe_load_json(candidate_pool_recall_dossier_path)
    corridor_shadow_pack = _maybe_load_json(corridor_shadow_pack_path)
    if not corridor_shadow_pack:
        corridor_shadow_pack = analyze_btst_candidate_pool_corridor_shadow_pack(REPORTS_DIR / "btst_candidate_pool_corridor_validation_pack_latest.json")

    lane_pair_board = _maybe_load_json(lane_pair_board_path)
    if not lane_pair_board:
        lane_pair_board = analyze_btst_candidate_pool_lane_pair_board(
            REPORTS_DIR / "btst_candidate_pool_corridor_shadow_pack_latest.json",
            REPORTS_DIR / "btst_candidate_pool_rebucket_comparison_bundle_latest.json",
        )

    corridor_experiment = _find_corridor_experiment(recall_dossier)
    primary_shadow = dict(corridor_shadow_pack.get("primary_shadow_replay") or {})
    parallel_watch = [dict(row) for row in list(corridor_shadow_pack.get("parallel_watch_lanes") or [])]
    board_leader = dict(lane_pair_board.get("board_leader") or {})

    runbook_status = "ready_for_upstream_uplift_probe" if corridor_experiment and primary_shadow else "skipped_no_corridor_probe"
    execution_steps = [
        f"保持 {primary_shadow.get('ticker') or 'primary corridor ticker'} 为唯一 primary shadow replay 槽位。",
        f"把 {[row.get('ticker') for row in parallel_watch if row.get('ticker')]} 仅作为 confirmatory parallel watch，不允许替换 primary。",
        "仅验证 upstream base-liquidity uplift 是否压缩 nearest frontier multiple，不讨论 cutoff 微调。",
        f"若 pair board leader 仍是 {board_leader.get('ticker') or 'corridor primary'}，则继续保持 corridor-first。",
    ]
    success_criteria = list(corridor_shadow_pack.get("success_criteria") or [])
    if corridor_experiment.get("success_signal"):
        success_criteria.append(str(corridor_experiment.get("success_signal")))
    guardrails = list(corridor_shadow_pack.get("guardrails") or [])
    if corridor_experiment.get("guardrail_summary"):
        guardrails.append(str(corridor_experiment.get("guardrail_summary")))

    recommendation = (
        f"corridor uplift runbook 当前应围绕 {primary_shadow.get('ticker') or 'N/A'} 展开，"
        f"并保持 {board_leader.get('ticker') or 'N/A'} 的 lane pair leader 语义不变。"
    )

    return {
        "candidate_pool_recall_dossier_path": str(Path(candidate_pool_recall_dossier_path).expanduser().resolve()),
        "corridor_shadow_pack_path": str(Path(corridor_shadow_pack_path).expanduser().resolve()) if corridor_shadow_pack_path else None,
        "lane_pair_board_path": str(Path(lane_pair_board_path).expanduser().resolve()) if lane_pair_board_path else None,
        "runbook_status": runbook_status,
        "priority_handoff": corridor_experiment.get("priority_handoff"),
        "prototype_task_id": corridor_experiment.get("task_id"),
        "prototype_readiness": corridor_experiment.get("prototype_readiness"),
        "prototype_type": corridor_experiment.get("prototype_type"),
        "primary_shadow_replay": primary_shadow.get("ticker"),
        "parallel_watch_tickers": [str(row.get("ticker") or "") for row in parallel_watch if str(row.get("ticker") or "").strip()],
        "lane_pair_board_leader": board_leader.get("ticker"),
        "leader_lane_family": board_leader.get("lane_family"),
        "uplift_to_cutoff_multiple_mean": corridor_experiment.get("uplift_to_cutoff_multiple_mean"),
        "uplift_to_cutoff_multiple_min": corridor_experiment.get("uplift_to_cutoff_multiple_min"),
        "target_cutoff_avg_amount_20d_mean": corridor_experiment.get("target_cutoff_avg_amount_20d_mean"),
        "prototype_summary": corridor_experiment.get("prototype_summary"),
        "evaluation_summary": corridor_experiment.get("evaluation_summary"),
        "why_now": corridor_experiment.get("why_now"),
        "execution_steps": execution_steps,
        "success_criteria": success_criteria,
        "guardrails": guardrails,
        "recommendation": recommendation,
        "next_step": execution_steps[0] if execution_steps else None,
    }


def render_btst_candidate_pool_corridor_uplift_runbook_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Candidate Pool Corridor Uplift Runbook")
    lines.append("")
    lines.append("## Status")
    lines.append(f"- runbook_status: {analysis.get('runbook_status')}")
    lines.append(f"- primary_shadow_replay: {analysis.get('primary_shadow_replay')}")
    lines.append(f"- parallel_watch_tickers: {analysis.get('parallel_watch_tickers')}")
    lines.append(f"- lane_pair_board_leader: {analysis.get('lane_pair_board_leader')}")
    lines.append(f"- leader_lane_family: {analysis.get('leader_lane_family')}")
    lines.append("")
    lines.append("## Probe")
    lines.append(f"- prototype_task_id: {analysis.get('prototype_task_id')}")
    lines.append(f"- prototype_readiness: {analysis.get('prototype_readiness')}")
    lines.append(f"- prototype_type: {analysis.get('prototype_type')}")
    lines.append(f"- uplift_to_cutoff_multiple_mean: {analysis.get('uplift_to_cutoff_multiple_mean')}")
    lines.append(f"- uplift_to_cutoff_multiple_min: {analysis.get('uplift_to_cutoff_multiple_min')}")
    lines.append(f"- target_cutoff_avg_amount_20d_mean: {analysis.get('target_cutoff_avg_amount_20d_mean')}")
    lines.append(f"- prototype_summary: {analysis.get('prototype_summary')}")
    lines.append(f"- evaluation_summary: {analysis.get('evaluation_summary')}")
    lines.append(f"- why_now: {analysis.get('why_now')}")
    lines.append("")
    lines.append("## Execution Steps")
    for item in list(analysis.get("execution_steps") or []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Success Criteria")
    for item in list(analysis.get("success_criteria") or []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Guardrails")
    for item in list(analysis.get("guardrails") or []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis.get('recommendation')}")
    lines.append(f"- next_step: {analysis.get('next_step')}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build a runnable corridor uplift probe runbook for candidate-pool recall governance.")
    parser.add_argument("--candidate-pool-recall-dossier-path", default=str(DEFAULT_CANDIDATE_POOL_RECALL_DOSSIER_PATH))
    parser.add_argument("--corridor-shadow-pack-path", default=str(DEFAULT_CORRIDOR_SHADOW_PACK_PATH))
    parser.add_argument("--lane-pair-board-path", default=str(DEFAULT_LANE_PAIR_BOARD_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_candidate_pool_corridor_uplift_runbook(
        args.candidate_pool_recall_dossier_path,
        corridor_shadow_pack_path=args.corridor_shadow_pack_path,
        lane_pair_board_path=args.lane_pair_board_path,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md = Path(args.output_md).expanduser().resolve()
    output_md.write_text(render_btst_candidate_pool_corridor_uplift_runbook_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))