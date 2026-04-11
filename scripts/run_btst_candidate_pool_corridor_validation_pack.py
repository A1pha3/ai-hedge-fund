from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_btst_candidate_pool_corridor_narrow_probe import analyze_btst_candidate_pool_corridor_narrow_probe
from scripts.analyze_btst_candidate_pool_branch_priority_board import analyze_btst_candidate_pool_branch_priority_board
from scripts.analyze_btst_candidate_pool_lane_objective_support import analyze_btst_candidate_pool_lane_objective_support


REPORTS_DIR = Path("data/reports")
DEFAULT_DOSSIER_PATH = REPORTS_DIR / "btst_candidate_pool_recall_dossier_latest.json"
DEFAULT_LANE_OBJECTIVE_SUPPORT_PATH = REPORTS_DIR / "btst_candidate_pool_lane_objective_support_latest.json"
DEFAULT_BRANCH_PRIORITY_BOARD_PATH = REPORTS_DIR / "btst_candidate_pool_branch_priority_board_latest.json"
DEFAULT_OBJECTIVE_MONITOR_PATH = REPORTS_DIR / "btst_tplus1_tplus2_objective_monitor_latest.json"
DEFAULT_CORRIDOR_NARROW_PROBE_PATH = REPORTS_DIR / "btst_candidate_pool_corridor_narrow_probe_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_candidate_pool_corridor_validation_pack_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_candidate_pool_corridor_validation_pack_latest.md"


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


def _find_branch_row(rows: list[dict[str, Any]], handoff: str) -> dict[str, Any]:
    for row in rows:
        if str(row.get("priority_handoff") or "") == handoff:
            return dict(row)
    return {}


def _find_corridor_rows(branch_priority_board: dict[str, Any], lane_support: dict[str, Any]) -> list[dict[str, Any]]:
    corridor_rows_by_ticker = {
        str(row.get("ticker") or ""): dict(row)
        for row in list(branch_priority_board.get("corridor_ticker_rows") or [])
        if str(row.get("ticker") or "")
    }
    merged_rows: list[dict[str, Any]] = []
    for objective_row in list(lane_support.get("ticker_rows") or []):
        if str(objective_row.get("priority_handoff") or "") != "layer_a_liquidity_corridor":
            continue
        ticker = str(objective_row.get("ticker") or "")
        merged_rows.append(
            {
                **corridor_rows_by_ticker.get(ticker, {}),
                **dict(objective_row),
                "ticker": ticker,
            }
        )
    merged_rows.sort(
        key=lambda row: (
            int(row.get("corridor_priority_rank") or 99),
            -(float(row.get("objective_fit_score") or -999.0)),
            -(float(row.get("mean_t_plus_2_return") or -999.0)),
            str(row.get("ticker") or ""),
        )
    )
    for index, row in enumerate(merged_rows, start=1):
        row["validation_priority_rank"] = index
    return merged_rows


def _load_corridor_narrow_probe(
    corridor_narrow_probe_path: str | Path | None,
    *,
    dossier_path: str | Path,
) -> dict[str, Any]:
    narrow_probe = _maybe_load_json(corridor_narrow_probe_path)
    if narrow_probe:
        return narrow_probe
    return analyze_btst_candidate_pool_corridor_narrow_probe(
        candidate_pool_recall_dossier_path=dossier_path,
    )


def _resolve_parallel_watch_rows(
    corridor_ticker_rows: list[dict[str, Any]],
    *,
    excluded_low_gate_tail_tickers: set[str],
) -> list[dict[str, Any]]:
    selected_rows = [dict(row) for row in corridor_ticker_rows[1:3]]
    return [row for row in selected_rows if str(row.get("ticker") or "") not in excluded_low_gate_tail_tickers]


def analyze_btst_candidate_pool_corridor_validation_pack(
    dossier_path: str | Path,
    *,
    lane_objective_support_path: str | Path | None = None,
    branch_priority_board_path: str | Path | None = None,
    objective_monitor_path: str | Path | None = None,
    corridor_narrow_probe_path: str | Path | None = None,
) -> dict[str, Any]:
    resolved_dossier_path = Path(dossier_path).expanduser().resolve()
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

    corridor_objective_row = _find_branch_row(list(lane_support.get("branch_rows") or []), "layer_a_liquidity_corridor")
    corridor_branch_row = _find_branch_row(list(branch_priority_board.get("branch_rows") or []), "layer_a_liquidity_corridor")
    corridor_ticker_rows = _find_corridor_rows(branch_priority_board, lane_support)
    corridor_narrow_probe = _load_corridor_narrow_probe(
        corridor_narrow_probe_path,
        dossier_path=resolved_dossier_path,
    )
    excluded_low_gate_tail_tickers = {
        str(ticker).strip()
        for ticker in list(corridor_narrow_probe.get("excluded_low_gate_tail_tickers") or [])
        if str(ticker).strip()
    }
    primary_ticker_row = dict(corridor_ticker_rows[0]) if corridor_ticker_rows else {}
    parallel_watch_rows = _resolve_parallel_watch_rows(
        corridor_ticker_rows,
        excluded_low_gate_tail_tickers=excluded_low_gate_tail_tickers,
    )
    focus_ticker = str(primary_ticker_row.get("ticker") or "").strip() or None
    leader_gap_to_target = (
        round(1.0 - float(primary_ticker_row.get("objective_fit_score")), 4)
        if isinstance(primary_ticker_row.get("objective_fit_score"), (int, float))
        else None
    )
    promotion_readiness_status = (
        "corridor_shadow_probe_ready"
        if str(primary_ticker_row.get("tractability_tier") or "") in {"second_shadow_probe", "parallel_probe", "primary"}
        else "corridor_shadow_probe_pending"
    )

    if not corridor_objective_row:
        pack_status = "skipped_no_corridor_lane"
        recommendation = "当前 dossier 没有 layer_a_liquidity_corridor lane，corridor validation pack 暂时只保留为空位监控。"
    elif str(corridor_objective_row.get("support_verdict") or "") == "candidate_pool_false_negative_outperforms_tradeable_surface":
        pack_status = "parallel_probe_ready"
        recommendation = (
            f"corridor lane 当前已是 objective leader，closed_cycle_count={corridor_objective_row.get('closed_cycle_count')}，"
            f"mean_t_plus_2_return={corridor_objective_row.get('mean_t_plus_2_return')}。"
            f" 应先验证 {primary_ticker_row.get('ticker')} 的 tractable uplift 路线，并把其余 ticker 作为并行确认样本。"
        )
        if excluded_low_gate_tail_tickers:
            recommendation += f" 已从并行样本中剔除 excluded low-gate tail={sorted(excluded_low_gate_tail_tickers)}。"
    else:
        pack_status = "accumulate_more_corridor_evidence"
        recommendation = "corridor lane 仍需更多 closed-cycle 支持，暂不应从 objective leader 升级成强执行车道。"

    runbook = [
        "保持 Layer A liquidity gate 与 top300 cutoff 默认口径不变，只做 corridor uplift shadow validation。",
        f"优先围绕 {primary_ticker_row.get('ticker') or 'primary corridor ticker'} 回查 uplift burden 与 nearest frontier multiple。",
        "把剩余 corridor ticker 作为 parallel confirmation，不允许直接把 corridor 误写成 top300 micro-boundary 调参问题。",
    ]

    return {
        "source_dossier": str(resolved_dossier_path),
        "lane_objective_support_path": str(Path(lane_objective_support_path).expanduser().resolve()) if lane_objective_support_path else None,
        "branch_priority_board_path": str(Path(branch_priority_board_path).expanduser().resolve()) if branch_priority_board_path else None,
        "pack_status": pack_status,
        "focus_ticker": focus_ticker,
        "leader_gap_to_target": leader_gap_to_target,
        "promotion_readiness_status": promotion_readiness_status,
        "corridor_objective_row": corridor_objective_row,
        "corridor_branch_row": corridor_branch_row,
        "corridor_narrow_probe_path": str(Path(corridor_narrow_probe_path).expanduser().resolve()) if corridor_narrow_probe_path else None,
        "corridor_ticker_rows": corridor_ticker_rows,
        "primary_validation_ticker": primary_ticker_row,
        "parallel_watch_tickers": parallel_watch_rows,
        "excluded_low_gate_tail_tickers": sorted(excluded_low_gate_tail_tickers),
        "recommendation": recommendation,
        "runbook": runbook,
    }


def render_btst_candidate_pool_corridor_validation_pack_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Candidate Pool Corridor Validation Pack")
    lines.append("")
    lines.append("## Lane")
    lines.append(f"- pack_status: {analysis.get('pack_status')}")
    corridor_objective_row = dict(analysis.get("corridor_objective_row") or {})
    lines.append(
        f"- corridor_objective: verdict={corridor_objective_row.get('support_verdict')} closed_cycle_count={corridor_objective_row.get('closed_cycle_count')} objective_fit_score={corridor_objective_row.get('objective_fit_score')} mean_t_plus_2_return={corridor_objective_row.get('mean_t_plus_2_return')}"
    )
    lines.append("")
    lines.append("## Primary Validation")
    primary = dict(analysis.get("primary_validation_ticker") or {})
    lines.append(
        f"- primary_ticker: ticker={primary.get('ticker')} validation_priority_rank={primary.get('validation_priority_rank')} corridor_priority_rank={primary.get('corridor_priority_rank')} tractability_tier={primary.get('tractability_tier')} mean_t_plus_2_return={primary.get('mean_t_plus_2_return')} uplift_to_cutoff_multiple_mean={primary.get('uplift_to_cutoff_multiple_mean')}"
    )
    lines.append("")
    lines.append("## Parallel Watch")
    for row in list(analysis.get("parallel_watch_tickers") or []):
        lines.append(
            f"- ticker={row.get('ticker')} validation_priority_rank={row.get('validation_priority_rank')} tractability_tier={row.get('tractability_tier')} mean_t_plus_2_return={row.get('mean_t_plus_2_return')} uplift_to_cutoff_multiple_mean={row.get('uplift_to_cutoff_multiple_mean')}"
        )
    if not list(analysis.get("parallel_watch_tickers") or []):
        lines.append("- none")
    for ticker in list(analysis.get("excluded_low_gate_tail_tickers") or []):
        lines.append(f"- excluded_low_gate_tail={ticker}")
    lines.append("")
    lines.append("## Runbook")
    for item in list(analysis.get("runbook") or []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis.get('recommendation')}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a corridor validation pack for candidate-pool recall governance.")
    parser.add_argument("--dossier-path", default=str(DEFAULT_DOSSIER_PATH))
    parser.add_argument("--lane-objective-support-path", default=str(DEFAULT_LANE_OBJECTIVE_SUPPORT_PATH))
    parser.add_argument("--branch-priority-board-path", default=str(DEFAULT_BRANCH_PRIORITY_BOARD_PATH))
    parser.add_argument("--objective-monitor-path", default=str(DEFAULT_OBJECTIVE_MONITOR_PATH))
    parser.add_argument("--corridor-narrow-probe-path", default=str(DEFAULT_CORRIDOR_NARROW_PROBE_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_candidate_pool_corridor_validation_pack(
        args.dossier_path,
        lane_objective_support_path=args.lane_objective_support_path,
        branch_priority_board_path=args.branch_priority_board_path,
        objective_monitor_path=args.objective_monitor_path,
        corridor_narrow_probe_path=args.corridor_narrow_probe_path,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md = Path(args.output_md).expanduser().resolve()
    output_md.write_text(render_btst_candidate_pool_corridor_validation_pack_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
