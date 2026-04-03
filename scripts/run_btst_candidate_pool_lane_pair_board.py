from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.run_btst_candidate_pool_corridor_shadow_pack import analyze_btst_candidate_pool_corridor_shadow_pack
from scripts.run_btst_candidate_pool_rebucket_comparison_bundle import analyze_btst_candidate_pool_rebucket_comparison_bundle


REPORTS_DIR = Path("data/reports")
DEFAULT_CORRIDOR_SHADOW_PACK_PATH = REPORTS_DIR / "btst_candidate_pool_corridor_shadow_pack_latest.json"
DEFAULT_REBUCKET_COMPARISON_BUNDLE_PATH = REPORTS_DIR / "btst_candidate_pool_rebucket_comparison_bundle_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_candidate_pool_lane_pair_board_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_candidate_pool_lane_pair_board_latest.md"


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


def _candidate_row(
    *,
    ticker: str | None,
    lane_family: str,
    role: str,
    mean_t_plus_2_return: float | None,
    objective_fit_score: float | None,
    t_plus_2_return_hit_rate_at_target: float | None,
    t_plus_2_positive_rate: float | None,
    tractability_tier: str | None,
) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "lane_family": lane_family,
        "role": role,
        "mean_t_plus_2_return": mean_t_plus_2_return,
        "objective_fit_score": objective_fit_score,
        "t_plus_2_return_hit_rate_at_target": t_plus_2_return_hit_rate_at_target,
        "t_plus_2_positive_rate": t_plus_2_positive_rate,
        "tractability_tier": tractability_tier,
    }


def analyze_btst_candidate_pool_lane_pair_board(
    corridor_shadow_pack_path: str | Path,
    rebucket_comparison_bundle_path: str | Path,
) -> dict[str, Any]:
    corridor_pack = _maybe_load_json(corridor_shadow_pack_path)
    if not corridor_pack:
        corridor_pack = analyze_btst_candidate_pool_corridor_shadow_pack(REPORTS_DIR / "btst_candidate_pool_corridor_validation_pack_latest.json")

    rebucket_bundle = _maybe_load_json(rebucket_comparison_bundle_path)
    if not rebucket_bundle:
        rebucket_bundle = analyze_btst_candidate_pool_rebucket_comparison_bundle(REPORTS_DIR / "btst_candidate_pool_recall_dossier_latest.json")

    primary = dict(corridor_pack.get("primary_shadow_replay") or {})
    parallel = [dict(row) for row in list(corridor_pack.get("parallel_watch_lanes") or [])]
    rebucket = dict(rebucket_bundle.get("rebucket_objective_row") or {})

    candidates = [
        _candidate_row(
            ticker=primary.get("ticker"),
            lane_family="corridor",
            role="primary_shadow_replay",
            mean_t_plus_2_return=primary.get("mean_t_plus_2_return"),
            objective_fit_score=primary.get("objective_fit_score"),
            t_plus_2_return_hit_rate_at_target=primary.get("t_plus_2_return_hit_rate_at_target"),
            t_plus_2_positive_rate=primary.get("t_plus_2_positive_rate"),
            tractability_tier=primary.get("tractability_tier"),
        ),
        _candidate_row(
            ticker=rebucket.get("ticker") or (list(rebucket.get("tickers") or [])[:1] or [None])[0],
            lane_family="rebucket",
            role="structural_challenger",
            mean_t_plus_2_return=rebucket.get("mean_t_plus_2_return"),
            objective_fit_score=rebucket.get("objective_fit_score"),
            t_plus_2_return_hit_rate_at_target=rebucket.get("t_plus_2_return_hit_rate_at_target"),
            t_plus_2_positive_rate=rebucket.get("t_plus_2_positive_rate"),
            tractability_tier=rebucket.get("prototype_readiness"),
        ),
    ]
    for row in parallel:
        candidates.append(
            _candidate_row(
                ticker=row.get("ticker"),
                lane_family="corridor",
                role="parallel_watch",
                mean_t_plus_2_return=row.get("mean_t_plus_2_return"),
                objective_fit_score=row.get("objective_fit_score"),
                t_plus_2_return_hit_rate_at_target=row.get("t_plus_2_return_hit_rate_at_target"),
                t_plus_2_positive_rate=row.get("t_plus_2_positive_rate"),
                tractability_tier=row.get("tractability_tier"),
            )
        )

    candidates = [row for row in candidates if row.get("ticker")]
    candidates.sort(
        key=lambda row: (
            0 if row.get("role") == "primary_shadow_replay" else 1,
            -(float(row.get("objective_fit_score") or -999.0)),
            -(float(row.get("mean_t_plus_2_return") or -999.0)),
            str(row.get("ticker") or ""),
        )
    )
    for index, row in enumerate(candidates, start=1):
        row["board_rank"] = index

    pair_status = "ready_for_ranked_comparison" if candidates else "skipped_missing_candidates"
    board_leader = dict(candidates[0]) if candidates else {}

    comparison = {
        "corridor_primary_ticker": primary.get("ticker"),
        "corridor_primary_objective_fit_score": primary.get("objective_fit_score"),
        "corridor_primary_mean_t_plus_2_return": primary.get("mean_t_plus_2_return"),
        "rebucket_ticker": rebucket.get("ticker") or (list(rebucket.get("tickers") or [])[:1] or [None])[0],
        "rebucket_objective_fit_score": rebucket.get("objective_fit_score"),
        "rebucket_mean_t_plus_2_return": rebucket.get("mean_t_plus_2_return"),
        "alignment_status": rebucket_bundle.get("priority_alignment_status"),
    }

    if board_leader.get("lane_family") == "corridor":
        recommendation = (
            f"lane pair board 当前仍应由 corridor 主导，首选 ticker={board_leader.get('ticker')}。"
            f" rebucket ticker={comparison.get('rebucket_ticker')} 保留为结构 challenger，用于并行收益对照。"
        )
    elif board_leader:
        recommendation = (
            f"rebucket 当前在 pair board 中反超，ticker={board_leader.get('ticker')}。"
            " 但只有在新增窗口继续成立时，才允许它挤占 corridor primary replay 槽位。"
        )
    else:
        recommendation = "当前没有可排名的 corridor/rebucket lane 候选。"

    next_actions = [
        f"保持 corridor primary ticker {primary.get('ticker') or 'N/A'} 为第一 replay 槽位。",
        f"保持 rebucket ticker {comparison.get('rebucket_ticker') or 'N/A'} 为结构 challenger，对照 corridor 主槽位表现。",
        "parallel_watch 只承担 confirmatory evidence，不允许直接替换 primary replay 优先级。",
    ]

    return {
        "corridor_shadow_pack_path": str(Path(corridor_shadow_pack_path).expanduser().resolve()),
        "rebucket_comparison_bundle_path": str(Path(rebucket_comparison_bundle_path).expanduser().resolve()),
        "pair_status": pair_status,
        "board_leader": board_leader,
        "candidates": candidates,
        "comparison": comparison,
        "recommendation": recommendation,
        "next_actions": next_actions,
    }


def render_btst_candidate_pool_lane_pair_board_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Candidate Pool Lane Pair Board")
    lines.append("")
    lines.append("## Status")
    lines.append(f"- pair_status: {analysis.get('pair_status')}")
    leader = dict(analysis.get("board_leader") or {})
    if leader:
        lines.append(
            f"- board_leader: ticker={leader.get('ticker')} lane_family={leader.get('lane_family')} role={leader.get('role')} board_rank={leader.get('board_rank')}"
        )
    lines.append("")
    lines.append("## Candidates")
    for row in list(analysis.get("candidates") or []):
        lines.append(
            f"- board_rank={row.get('board_rank')} ticker={row.get('ticker')} lane_family={row.get('lane_family')} role={row.get('role')} objective_fit_score={row.get('objective_fit_score')} mean_t_plus_2_return={row.get('mean_t_plus_2_return')} tractability_tier={row.get('tractability_tier')}"
        )
    if not list(analysis.get("candidates") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Comparison")
    for key, value in dict(analysis.get("comparison") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis.get('recommendation')}")
    for item in list(analysis.get("next_actions") or []):
        lines.append(f"- next_action: {item}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build a pair board for corridor and rebucket candidate-pool lanes.")
    parser.add_argument("--corridor-shadow-pack-path", default=str(DEFAULT_CORRIDOR_SHADOW_PACK_PATH))
    parser.add_argument("--rebucket-comparison-bundle-path", default=str(DEFAULT_REBUCKET_COMPARISON_BUNDLE_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_candidate_pool_lane_pair_board(
        args.corridor_shadow_pack_path,
        args.rebucket_comparison_bundle_path,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md = Path(args.output_md).expanduser().resolve()
    output_md.write_text(render_btst_candidate_pool_lane_pair_board_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))