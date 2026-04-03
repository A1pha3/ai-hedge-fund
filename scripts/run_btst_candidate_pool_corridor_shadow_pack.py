from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.run_btst_candidate_pool_corridor_validation_pack import analyze_btst_candidate_pool_corridor_validation_pack


REPORTS_DIR = Path("data/reports")
DEFAULT_CORRIDOR_VALIDATION_PACK_PATH = REPORTS_DIR / "btst_candidate_pool_corridor_validation_pack_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_candidate_pool_corridor_shadow_pack_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_candidate_pool_corridor_shadow_pack_latest.md"


def _build_refresh_commands(*, corridor_validation_pack_path: str | Path) -> list[str]:
    resolved_validation_pack_path = Path(corridor_validation_pack_path).expanduser().resolve()
    return [
        "python scripts/run_btst_candidate_pool_corridor_validation_pack.py "
        "--dossier-path data/reports/btst_candidate_pool_recall_dossier_latest.json "
        "--lane-objective-support-path data/reports/btst_candidate_pool_lane_objective_support_latest.json "
        "--branch-priority-board-path data/reports/btst_candidate_pool_branch_priority_board_latest.json "
        "--objective-monitor-path data/reports/btst_tplus1_tplus2_objective_monitor_latest.json "
        "--output-json data/reports/btst_candidate_pool_corridor_validation_pack_latest.json "
        "--output-md data/reports/btst_candidate_pool_corridor_validation_pack_latest.md",
        "python scripts/run_btst_candidate_pool_corridor_shadow_pack.py "
        f"--corridor-validation-pack-path {resolved_validation_pack_path} "
        "--output-json data/reports/btst_candidate_pool_corridor_shadow_pack_latest.json "
        "--output-md data/reports/btst_candidate_pool_corridor_shadow_pack_latest.md",
    ]


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


def _build_lane(row: dict[str, Any], *, lane_role: str, lane_rank: int) -> dict[str, Any]:
    return {
        "ticker": row.get("ticker"),
        "lane_role": lane_role,
        "lane_rank": lane_rank,
        "validation_priority_rank": row.get("validation_priority_rank"),
        "tractability_tier": row.get("tractability_tier"),
        "corridor_priority_rank": row.get("corridor_priority_rank"),
        "closed_cycle_count": row.get("closed_cycle_count"),
        "mean_t_plus_2_return": row.get("mean_t_plus_2_return"),
        "t_plus_2_return_hit_rate_at_target": row.get("t_plus_2_return_hit_rate_at_target"),
        "t_plus_2_positive_rate": row.get("t_plus_2_positive_rate"),
        "objective_fit_score": row.get("objective_fit_score"),
        "uplift_to_cutoff_multiple_mean": row.get("uplift_to_cutoff_multiple_mean"),
        "profile_summary": row.get("profile_summary"),
    }


def analyze_btst_candidate_pool_corridor_shadow_pack(
    corridor_validation_pack_path: str | Path,
) -> dict[str, Any]:
    pack = _maybe_load_json(corridor_validation_pack_path)
    if not pack:
        pack = analyze_btst_candidate_pool_corridor_validation_pack(REPORTS_DIR / "btst_candidate_pool_recall_dossier_latest.json")

    pack_status = str(pack.get("pack_status") or "skipped_no_corridor_lane")
    primary = dict(pack.get("primary_validation_ticker") or {})
    parallel = [dict(row) for row in list(pack.get("parallel_watch_tickers") or [])]

    if pack_status == "parallel_probe_ready" and primary:
        shadow_status = "ready_for_primary_shadow_replay"
    elif pack_status == "accumulate_more_corridor_evidence":
        shadow_status = "hold_for_more_corridor_evidence"
    else:
        shadow_status = "skipped_no_corridor_lane"

    lanes: list[dict[str, Any]] = []
    if primary:
        lanes.append(_build_lane(primary, lane_role="primary_shadow_replay", lane_rank=1))
    for index, row in enumerate(parallel, start=2):
        lanes.append(_build_lane(row, lane_role="parallel_watch", lane_rank=index))

    success_criteria = [
        "primary ticker 在新增窗口里仍维持 t_plus_2_return_hit_rate_at_target 不低于当前 tradeable surface。",
        "parallel ticker 只做 confirmatory evidence，不允许反向挤占 primary ticker 的 shadow replay 槽位。",
        "若 corridor lane 的 uplift_to_cutoff_multiple_mean 继续高企，则保持 upstream probe 语义，不改写成 top300 cutoff 微调。",
    ]
    guardrails = [
        "保持 Layer A liquidity gate 与 top300 cutoff 默认口径不变。",
        "primary shadow replay 只验证 corridor uplift 方向，不直接推动默认策略改动。",
        "tractability_tier=upstream_research_only 的 ticker 不得被提升为 primary。",
    ]

    if shadow_status == "ready_for_primary_shadow_replay":
        recommendation = (
            f"corridor lane 已可进入 primary shadow replay，当前首选 ticker={primary.get('ticker')}，"
            f"并行确认 ticker={[row.get('ticker') for row in parallel if row.get('ticker')]}."
        )
    elif shadow_status == "hold_for_more_corridor_evidence":
        recommendation = "corridor lane 仍需更多 closed-cycle 证据，暂不进入 primary shadow replay。"
    else:
        recommendation = "当前没有可执行的 corridor lane，shadow pack 仅保留为空位监控。"

    refresh_commands = _build_refresh_commands(corridor_validation_pack_path=corridor_validation_pack_path)
    shadow_replay_commands: list[str] = []
    if primary:
        shadow_replay_commands.append(refresh_commands[-1])
    for row in parallel:
        ticker = str(row.get("ticker") or "").strip()
        if ticker:
            shadow_replay_commands.append(
                "python scripts/run_btst_candidate_pool_corridor_shadow_pack.py "
                f"--corridor-validation-pack-path {Path(corridor_validation_pack_path).expanduser().resolve()} "
                "--output-json data/reports/btst_candidate_pool_corridor_shadow_pack_latest.json "
                "--output-md data/reports/btst_candidate_pool_corridor_shadow_pack_latest.md "
                f"# parallel_watch={ticker}"
            )

    return {
        "corridor_validation_pack_path": str(Path(corridor_validation_pack_path).expanduser().resolve()),
        "shadow_status": shadow_status,
        "source_pack_status": pack_status,
        "primary_shadow_replay": _build_lane(primary, lane_role="primary_shadow_replay", lane_rank=1) if primary else {},
        "parallel_watch_lanes": [_build_lane(row, lane_role="parallel_watch", lane_rank=index) for index, row in enumerate(parallel, start=2)],
        "lanes": lanes,
        "success_criteria": success_criteria,
        "guardrails": guardrails,
        "refresh_commands": refresh_commands,
        "shadow_replay_commands": shadow_replay_commands,
        "recommendation": recommendation,
        "next_step": f"先对 {primary.get('ticker') or 'primary corridor ticker'} 保持 corridor uplift shadow replay，再用并行样本确认 lane 稳定性。",
    }



def render_btst_candidate_pool_corridor_shadow_pack_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Candidate Pool Corridor Shadow Pack")
    lines.append("")
    lines.append("## Status")
    lines.append(f"- shadow_status: {analysis.get('shadow_status')}")
    lines.append(f"- source_pack_status: {analysis.get('source_pack_status')}")
    lines.append("")
    lines.append("## Lanes")
    for row in list(analysis.get("lanes") or []):
        lines.append(
            f"- ticker={row.get('ticker')} lane_role={row.get('lane_role')} tractability_tier={row.get('tractability_tier')} closed_cycle_count={row.get('closed_cycle_count')} mean_t_plus_2_return={row.get('mean_t_plus_2_return')} uplift_to_cutoff_multiple_mean={row.get('uplift_to_cutoff_multiple_mean')}"
        )
    if not list(analysis.get("lanes") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Success Criteria")
    for item in list(analysis.get("success_criteria") or []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Guardrails")
    for item in list(analysis.get("guardrails") or []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Commands")
    for item in list(analysis.get("refresh_commands") or []):
        lines.append(f"- refresh_command: {item}")
    for item in list(analysis.get("shadow_replay_commands") or []):
        lines.append(f"- shadow_replay_command: {item}")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis.get('recommendation')}")
    lines.append(f"- next_step: {analysis.get('next_step')}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build a corridor shadow pack for candidate-pool recall governance.")
    parser.add_argument("--corridor-validation-pack-path", default=str(DEFAULT_CORRIDOR_VALIDATION_PACK_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_candidate_pool_corridor_shadow_pack(args.corridor_validation_pack_path)
    output_json = Path(args.output_json).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md = Path(args.output_md).expanduser().resolve()
    output_md.write_text(render_btst_candidate_pool_corridor_shadow_pack_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))
