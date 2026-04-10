from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_btst_candidate_pool_branch_priority_board import analyze_btst_candidate_pool_branch_priority_board
from scripts.analyze_btst_candidate_pool_lane_objective_support import analyze_btst_candidate_pool_lane_objective_support
from scripts.analyze_btst_candidate_pool_rebucket_objective_validation import analyze_btst_candidate_pool_rebucket_objective_validation
from scripts.run_btst_candidate_pool_rebucket_shadow_pack import run_btst_candidate_pool_rebucket_shadow_pack


REPORTS_DIR = Path("data/reports")
DEFAULT_DOSSIER_PATH = REPORTS_DIR / "btst_candidate_pool_recall_dossier_latest.json"
DEFAULT_LANE_OBJECTIVE_SUPPORT_PATH = REPORTS_DIR / "btst_candidate_pool_lane_objective_support_latest.json"
DEFAULT_BRANCH_PRIORITY_BOARD_PATH = REPORTS_DIR / "btst_candidate_pool_branch_priority_board_latest.json"
DEFAULT_REBUCKET_SHADOW_PACK_PATH = REPORTS_DIR / "btst_candidate_pool_rebucket_shadow_pack_latest.json"
DEFAULT_REBUCKET_OBJECTIVE_VALIDATION_PATH = REPORTS_DIR / "btst_candidate_pool_rebucket_objective_validation_latest.json"
DEFAULT_OBJECTIVE_MONITOR_PATH = REPORTS_DIR / "btst_tplus1_tplus2_objective_monitor_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_candidate_pool_rebucket_comparison_bundle_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_candidate_pool_rebucket_comparison_bundle_latest.md"


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


def _delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return round(float(left) - float(right), 4)


def _find_branch_row(rows: list[dict[str, Any]], handoff: str) -> dict[str, Any]:
    for row in rows:
        if str(row.get("priority_handoff") or "") == handoff:
            return dict(row)
    return {}


def _load_rebucket_bundle_inputs(
    *,
    resolved_dossier_path: Path,
    lane_objective_support_path: str | Path | None,
    branch_priority_board_path: str | Path | None,
    rebucket_shadow_pack_path: str | Path | None,
    rebucket_objective_validation_path: str | Path | None,
    objective_monitor_path: str | Path | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    lane_support = _maybe_load_json(lane_objective_support_path)
    if not lane_support:
        lane_support = analyze_btst_candidate_pool_lane_objective_support(
            resolved_dossier_path,
            objective_monitor_path=objective_monitor_path,
        )

    branch_priority_board = _maybe_load_json(branch_priority_board_path)
    if not branch_priority_board:
        branch_priority_board = analyze_btst_candidate_pool_branch_priority_board(
            resolved_dossier_path,
            lane_objective_support_path=lane_objective_support_path,
        )

    rebucket_shadow_pack = _maybe_load_json(rebucket_shadow_pack_path)
    if not rebucket_shadow_pack:
        try:
            rebucket_shadow_pack = run_btst_candidate_pool_rebucket_shadow_pack(
                resolved_dossier_path,
                output_dir=resolved_dossier_path.parent,
            )
        except ValueError:
            rebucket_shadow_pack = {}

    rebucket_validation = _maybe_load_json(rebucket_objective_validation_path)
    if not rebucket_validation:
        rebucket_validation = analyze_btst_candidate_pool_rebucket_objective_validation(
            resolved_dossier_path,
            objective_monitor_path=objective_monitor_path,
            lane_objective_support_path=lane_objective_support_path,
        )
    return lane_support, branch_priority_board, rebucket_shadow_pack, rebucket_validation


def _resolve_rebucket_bundle_status(
    *,
    rebucket_structural_row: dict[str, Any],
    rebucket_objective_row: dict[str, Any],
    validation_status: str,
) -> str:
    if not rebucket_structural_row and not rebucket_objective_row:
        return "skipped_no_rebucket_lane"
    if validation_status == "advance_shadow_replay_comparison":
        return "ready_for_parallel_comparison"
    if validation_status == "keep_first_priority_shadow_validation":
        return "keep_shadow_first"
    if validation_status == "accumulate_more_closed_cycle_support":
        return "needs_more_closed_cycle_support"
    return "hold_structure_only"


def _build_rebucket_bundle_comparison(
    *,
    rebucket_structural_row: dict[str, Any],
    objective_leader: dict[str, Any],
    rebucket_objective_row: dict[str, Any],
    corridor_objective_row: dict[str, Any],
) -> dict[str, Any]:
    return {
        "structural_rank_gap_vs_objective_leader": _delta(
            rebucket_structural_row.get("execution_priority_rank"),
            objective_leader.get("objective_priority_rank"),
        ),
        "objective_fit_gap_vs_corridor": _delta(
            rebucket_objective_row.get("objective_fit_score"),
            corridor_objective_row.get("objective_fit_score"),
        ),
        "mean_t_plus_2_return_gap_vs_corridor": _delta(
            rebucket_objective_row.get("mean_t_plus_2_return"),
            corridor_objective_row.get("mean_t_plus_2_return"),
        ),
        "return_hit_rate_gap_vs_corridor": _delta(
            rebucket_objective_row.get("t_plus_2_return_hit_rate_at_target"),
            corridor_objective_row.get("t_plus_2_return_hit_rate_at_target"),
        ),
        "positive_rate_gap_vs_corridor": _delta(
            rebucket_objective_row.get("t_plus_2_positive_rate"),
            corridor_objective_row.get("t_plus_2_positive_rate"),
        ),
    }


def _build_rebucket_bundle_guidance(
    *,
    bundle_status: str,
    validation_status: str,
    comparison: dict[str, Any],
) -> tuple[str, str]:
    if bundle_status == "ready_for_parallel_comparison":
        recommendation = (
            "rebucket lane 已具备进入 parallel comparison bundle 的条件。"
            f" 结构上它仍是第一优先 lane，但相对 corridor 的后验证据差值为 "
            f"mean_t_plus_2_return_gap={comparison.get('mean_t_plus_2_return_gap_vs_corridor')}、"
            f"objective_fit_gap={comparison.get('objective_fit_gap_vs_corridor')}；"
            "因此下一步不是改默认阈值，而是把 rebucket shadow replay 与 corridor parallel validation 放到同一张收益对照板上。"
        )
    elif bundle_status == "skipped_no_rebucket_lane":
        recommendation = "当前 dossier 没有可执行的 rebucket lane，comparison bundle 仅保留为 nightly 空位监控。"
    else:
        recommendation = (
            f"rebucket lane 当前 validation_status={validation_status}，"
            "仍应保留在结构优先队列，但暂不具备升级成收益主线对照实验的条件。"
        )

    next_step = (
        "当前没有 active rebucket challenger；先修复 persistence / active lane 资格，再讨论是否回到与 corridor 的并行收益对照。"
        if bundle_status == "skipped_no_rebucket_lane"
        else "对 301292 保持 rebucket shadow replay，对照 corridor objective leader 的 300720/003036 并行验证结果；"
        "只有当 rebucket 在新增 closed-cycle 样本里继续维持不弱于 tradeable surface，才讨论进一步治理升级。"
    )
    return recommendation, next_step


def analyze_btst_candidate_pool_rebucket_comparison_bundle(
    dossier_path: str | Path,
    *,
    lane_objective_support_path: str | Path | None = None,
    branch_priority_board_path: str | Path | None = None,
    rebucket_shadow_pack_path: str | Path | None = None,
    rebucket_objective_validation_path: str | Path | None = None,
    objective_monitor_path: str | Path | None = None,
) -> dict[str, Any]:
    resolved_dossier_path = Path(dossier_path).expanduser().resolve()
    lane_support, branch_priority_board, rebucket_shadow_pack, rebucket_validation = _load_rebucket_bundle_inputs(
        resolved_dossier_path=resolved_dossier_path,
        lane_objective_support_path=lane_objective_support_path,
        branch_priority_board_path=branch_priority_board_path,
        rebucket_shadow_pack_path=rebucket_shadow_pack_path,
        rebucket_objective_validation_path=rebucket_objective_validation_path,
        objective_monitor_path=objective_monitor_path,
    )

    structural_rows = list(branch_priority_board.get("branch_rows") or [])
    objective_rows = list(lane_support.get("branch_rows") or [])
    structural_leader = dict(structural_rows[0]) if structural_rows else {}
    objective_leader = dict(objective_rows[0]) if objective_rows else {}
    rebucket_structural_row = _find_branch_row(structural_rows, "post_gate_liquidity_competition")
    rebucket_objective_row = dict(rebucket_validation.get("branch_objective_row") or {})
    rebucket_shadow_status = str(rebucket_shadow_pack.get("shadow_status") or "")

    if not rebucket_objective_row:
        rebucket_objective_row = _find_branch_row(objective_rows, "post_gate_liquidity_competition")
    if rebucket_shadow_status and rebucket_shadow_status != "ready_for_rebucket_shadow_replay":
        rebucket_structural_row = {}
        rebucket_objective_row = {}

    corridor_objective_row = _find_branch_row(objective_rows, "layer_a_liquidity_corridor")
    validation_status = str(rebucket_validation.get("validation_status") or "skipped_no_rebucket_candidate")
    bundle_status = _resolve_rebucket_bundle_status(
        rebucket_structural_row=rebucket_structural_row,
        rebucket_objective_row=rebucket_objective_row,
        validation_status=validation_status,
    )
    comparison = _build_rebucket_bundle_comparison(
        rebucket_structural_row=rebucket_structural_row,
        objective_leader=objective_leader,
        rebucket_objective_row=rebucket_objective_row,
        corridor_objective_row=corridor_objective_row,
    )
    recommendation, next_step = _build_rebucket_bundle_guidance(
        bundle_status=bundle_status,
        validation_status=validation_status,
        comparison=comparison,
    )

    return {
        "source_dossier": str(resolved_dossier_path),
        "lane_objective_support_path": str(Path(lane_objective_support_path).expanduser().resolve()) if lane_objective_support_path else None,
        "branch_priority_board_path": str(Path(branch_priority_board_path).expanduser().resolve()) if branch_priority_board_path else None,
        "rebucket_shadow_pack_path": str(Path(rebucket_shadow_pack_path).expanduser().resolve()) if rebucket_shadow_pack_path else None,
        "rebucket_objective_validation_path": str(Path(rebucket_objective_validation_path).expanduser().resolve()) if rebucket_objective_validation_path else None,
        "bundle_status": bundle_status,
        "priority_alignment_status": branch_priority_board.get("priority_alignment_status"),
        "structural_leader": structural_leader,
        "objective_leader": objective_leader,
        "rebucket_structural_row": rebucket_structural_row,
        "rebucket_objective_row": rebucket_objective_row,
        "corridor_objective_row": corridor_objective_row,
        "rebucket_shadow_pack": rebucket_shadow_pack,
        "rebucket_objective_validation": rebucket_validation,
        "comparison": comparison,
        "recommendation": recommendation,
        "next_step": next_step,
    }


def render_btst_candidate_pool_rebucket_comparison_bundle_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Candidate Pool Rebucket Comparison Bundle")
    lines.append("")
    lines.append("## Status")
    lines.append(f"- bundle_status: {analysis.get('bundle_status')}")
    lines.append(f"- priority_alignment_status: {analysis.get('priority_alignment_status')}")
    lines.append("")
    lines.append("## Leaders")
    structural_leader = dict(analysis.get("structural_leader") or {})
    objective_leader = dict(analysis.get("objective_leader") or {})
    lines.append(
        f"- structural_leader: handoff={structural_leader.get('priority_handoff')} rank={structural_leader.get('execution_priority_rank')} readiness={structural_leader.get('prototype_readiness')}"
    )
    lines.append(
        f"- objective_leader: handoff={objective_leader.get('priority_handoff')} rank={objective_leader.get('objective_priority_rank')} verdict={objective_leader.get('support_verdict')} mean_t_plus_2_return={objective_leader.get('mean_t_plus_2_return')}"
    )
    lines.append("")
    lines.append("## Rebucket Lane")
    rebucket_objective_row = dict(analysis.get("rebucket_objective_row") or {})
    lines.append(
        f"- rebucket_objective: verdict={rebucket_objective_row.get('support_verdict')} closed_cycle_count={rebucket_objective_row.get('closed_cycle_count')} objective_fit_score={rebucket_objective_row.get('objective_fit_score')} mean_t_plus_2_return={rebucket_objective_row.get('mean_t_plus_2_return')}"
    )
    rebucket_validation = dict(analysis.get("rebucket_objective_validation") or {})
    lines.append(
        f"- rebucket_validation: validation_status={rebucket_validation.get('validation_status')} recommendation={rebucket_validation.get('recommendation')}"
    )
    lines.append("")
    lines.append("## Comparison")
    for key, value in dict(analysis.get("comparison") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis.get('recommendation')}")
    lines.append(f"- next_step: {analysis.get('next_step')}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a rebucket comparison bundle for candidate-pool recall governance.")
    parser.add_argument("--dossier-path", default=str(DEFAULT_DOSSIER_PATH))
    parser.add_argument("--lane-objective-support-path", default=str(DEFAULT_LANE_OBJECTIVE_SUPPORT_PATH))
    parser.add_argument("--branch-priority-board-path", default=str(DEFAULT_BRANCH_PRIORITY_BOARD_PATH))
    parser.add_argument("--rebucket-shadow-pack-path", default=str(DEFAULT_REBUCKET_SHADOW_PACK_PATH))
    parser.add_argument("--rebucket-objective-validation-path", default=str(DEFAULT_REBUCKET_OBJECTIVE_VALIDATION_PATH))
    parser.add_argument("--objective-monitor-path", default=str(DEFAULT_OBJECTIVE_MONITOR_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_candidate_pool_rebucket_comparison_bundle(
        args.dossier_path,
        lane_objective_support_path=args.lane_objective_support_path,
        branch_priority_board_path=args.branch_priority_board_path,
        rebucket_shadow_pack_path=args.rebucket_shadow_pack_path,
        rebucket_objective_validation_path=args.rebucket_objective_validation_path,
        objective_monitor_path=args.objective_monitor_path,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md = Path(args.output_md).expanduser().resolve()
    output_md.write_text(render_btst_candidate_pool_rebucket_comparison_bundle_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
