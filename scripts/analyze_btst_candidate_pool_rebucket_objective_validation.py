from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_btst_candidate_pool_lane_objective_support import (
    DEFAULT_DOSSIER_PATH,
    DEFAULT_OBJECTIVE_MONITOR_PATH,
    analyze_btst_candidate_pool_lane_objective_support,
)


DEFAULT_REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = DEFAULT_REPORTS_DIR / "btst_candidate_pool_rebucket_objective_validation_latest.json"
DEFAULT_OUTPUT_MD = DEFAULT_REPORTS_DIR / "btst_candidate_pool_rebucket_objective_validation_latest.md"


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _select_rebucket_experiment(dossier: dict[str, Any], *, ticker: str | None = None) -> dict[str, Any] | None:
    queue = [
        dict(row)
        for row in list(dossier.get("priority_handoff_branch_experiment_queue") or [])
        if str(row.get("prototype_type") or "") == "post_gate_competition_rebucket_probe"
    ]
    if ticker:
        queue = [row for row in queue if ticker in list(row.get("tickers") or [])]
    if not queue:
        return None
    return dict(queue[0])


def analyze_btst_candidate_pool_rebucket_objective_validation(
    dossier_path: str | Path,
    *,
    objective_monitor_path: str | Path | None = None,
    lane_objective_support_path: str | Path | None = None,
    ticker: str | None = None,
) -> dict[str, Any]:
    dossier = _load_json(dossier_path)
    experiment = _select_rebucket_experiment(dossier, ticker=ticker)
    lane_support: dict[str, Any]
    if lane_objective_support_path and Path(lane_objective_support_path).expanduser().resolve().exists():
        lane_support = _load_json(lane_objective_support_path)
    else:
        lane_support = analyze_btst_candidate_pool_lane_objective_support(
            dossier_path,
            objective_monitor_path=objective_monitor_path,
        )

    branch_row = next(
        (
            dict(row)
            for row in list(lane_support.get("branch_rows") or [])
            if str(row.get("priority_handoff") or "") == "post_gate_liquidity_competition"
        ),
        {},
    )
    target_tickers = [str(value) for value in list((experiment or {}).get("tickers") or []) if str(value or "").strip()]
    ticker_rows = [
        dict(row)
        for row in list(lane_support.get("ticker_rows") or [])
        if str(row.get("ticker") or "") in target_tickers
    ]

    if experiment is None:
        validation_status = "skipped_no_rebucket_candidate"
        recommendation = "candidate-pool recall dossier 当前没有 post_gate_competition_rebucket_probe 候选，因此 rebucket objective validation 暂时只保留为空位监控，不形成收益验证结论。"
        runbook = [
            "继续观察 candidate-pool recall priority_handoff_branch_experiment_queue 是否出现 post_gate_competition_rebucket_probe。",
            "一旦出现 rebucket 候选，立即复用 lane objective support 做后验收益校验。",
            "在没有 rebucket 候选前，不要把 rebucket lane 误判为已具备收益验证支持。",
        ]
        return {
            "source_dossier": str(Path(dossier_path).expanduser().resolve()),
            "lane_objective_support_path": str(Path(lane_objective_support_path).expanduser().resolve()) if lane_objective_support_path else None,
            "objective_monitor_path": str(Path(objective_monitor_path).expanduser().resolve()) if objective_monitor_path else None,
            "experiment": {},
            "branch_objective_row": branch_row,
            "target_ticker_rows": [],
            "validation_status": validation_status,
            "mean_return_delta_vs_tradeable_surface": branch_row.get("mean_return_delta_vs_tradeable_surface"),
            "return_hit_rate_delta_vs_tradeable_surface": branch_row.get("return_hit_rate_delta_vs_tradeable_surface"),
            "runbook": runbook,
            "recommendation": recommendation,
        }

    support_verdict = str(branch_row.get("support_verdict") or "insufficient_closed_cycle_samples")
    mean_return_delta = branch_row.get("mean_return_delta_vs_tradeable_surface")
    return_hit_rate_delta = branch_row.get("return_hit_rate_delta_vs_tradeable_surface")
    if support_verdict == "candidate_pool_false_negative_outperforms_tradeable_surface":
        validation_status = "advance_shadow_replay_comparison"
    elif support_verdict == "candidate_pool_false_negative_has_positive_post_hoc_edge":
        validation_status = "keep_first_priority_shadow_validation"
    elif support_verdict == "candidate_pool_false_negative_beats_non_tradeable_surface_only":
        validation_status = "accumulate_more_closed_cycle_support"
    else:
        validation_status = "hold_structure_only"

    recommendation = (
        f"当前 rebucket lane 的后验 verdict={support_verdict}，"
        f"closed_cycle_count={branch_row.get('closed_cycle_count')}，"
        f"mean_t_plus_2_return={branch_row.get('mean_t_plus_2_return')}。"
    )
    if validation_status == "advance_shadow_replay_comparison":
        recommendation = (
            f"{recommendation} 它已不只是结构上可疑，而是后验上同时不弱于当前 tradeable surface，"
            "应进入真正的 shadow replay 对照比较。"
        )
    elif validation_status == "keep_first_priority_shadow_validation":
        recommendation = (
            f"{recommendation} 它已经显示正向后验 edge，虽然还没全面超过 tradeable surface，"
            "但仍应保持 candidate-pool recall 的第一优先验证 lane。"
        )
    elif validation_status == "accumulate_more_closed_cycle_support":
        recommendation = (
            f"{recommendation} 它暂时只证明自己优于 non-tradeable surface，"
            "还不能据此讨论升级，应继续积累 closed-cycle 证据。"
        )
    else:
        recommendation = f"{recommendation} 当前更像结构性研究线索，暂时不足以支持收益导向的优先升级。"

    runbook = [
        "先保持 MIN_AVG_AMOUNT_20D 不变，只做 rebucket shadow replay 对照。",
        "优先检查 rebucket lane 的 mean_t_plus_2_return 和 return_hit_rate 是否继续不弱于当前 tradeable surface。",
        "只有当 closed-cycle 增量样本继续稳定时，才允许讨论把 rebucket lane 提升到更高治理级别。",
    ]

    return {
        "source_dossier": str(Path(dossier_path).expanduser().resolve()),
        "lane_objective_support_path": str(Path(lane_objective_support_path).expanduser().resolve()) if lane_objective_support_path else None,
        "objective_monitor_path": str(Path(objective_monitor_path).expanduser().resolve()) if objective_monitor_path else None,
        "experiment": experiment,
        "branch_objective_row": branch_row,
        "target_ticker_rows": ticker_rows,
        "validation_status": validation_status,
        "mean_return_delta_vs_tradeable_surface": mean_return_delta,
        "return_hit_rate_delta_vs_tradeable_surface": return_hit_rate_delta,
        "runbook": runbook,
        "recommendation": recommendation,
    }


def render_btst_candidate_pool_rebucket_objective_validation_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Candidate Pool Rebucket Objective Validation")
    lines.append("")
    lines.append("## Experiment")
    experiment = dict(analysis.get("experiment") or {})
    lines.append(f"- task_id: {experiment.get('task_id')}")
    lines.append(f"- priority_handoff: {experiment.get('priority_handoff')}")
    lines.append(f"- prototype_readiness: {experiment.get('prototype_readiness')}")
    lines.append(f"- tickers: {experiment.get('tickers')}")
    lines.append("")
    lines.append("## Objective Verdict")
    branch_row = dict(analysis.get("branch_objective_row") or {})
    lines.append(
        f"- validation_status: {analysis.get('validation_status')}"
    )
    lines.append(
        f"- support_verdict: {branch_row.get('support_verdict')} closed_cycle_count={branch_row.get('closed_cycle_count')} positive_rate={branch_row.get('t_plus_2_positive_rate')} return_hit_rate={branch_row.get('t_plus_2_return_hit_rate_at_target')} mean_t_plus_2_return={branch_row.get('mean_t_plus_2_return')}"
    )
    lines.append(
        f"- delta_vs_tradeable_surface: mean_return={analysis.get('mean_return_delta_vs_tradeable_surface')} return_hit_rate={analysis.get('return_hit_rate_delta_vs_tradeable_surface')}"
    )
    lines.append("")
    lines.append("## Target Tickers")
    for row in list(analysis.get("target_ticker_rows") or []):
        lines.append(
            f"- ticker={row.get('ticker')} verdict={row.get('support_verdict')} closed_cycle_count={row.get('closed_cycle_count')} positive_rate={row.get('t_plus_2_positive_rate')} return_hit_rate={row.get('t_plus_2_return_hit_rate_at_target')} mean_t_plus_2_return={row.get('mean_t_plus_2_return')}"
        )
    if not list(analysis.get("target_ticker_rows") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Runbook")
    for item in list(analysis.get("runbook") or []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis.get('recommendation')}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate whether the candidate-pool rebucket lane has enough post-hoc BTST objective support.")
    parser.add_argument("--dossier-path", default=str(DEFAULT_DOSSIER_PATH))
    parser.add_argument("--objective-monitor-path", default=str(DEFAULT_OBJECTIVE_MONITOR_PATH))
    parser.add_argument("--lane-objective-support-path", default="")
    parser.add_argument("--ticker", default=None)
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_candidate_pool_rebucket_objective_validation(
        args.dossier_path,
        objective_monitor_path=args.objective_monitor_path,
        lane_objective_support_path=args.lane_objective_support_path or None,
        ticker=args.ticker,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md = Path(args.output_md).expanduser().resolve()
    output_md.write_text(render_btst_candidate_pool_rebucket_objective_validation_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()