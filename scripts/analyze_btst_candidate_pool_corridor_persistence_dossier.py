from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPORTS_DIR = Path("data/reports")
DEFAULT_CORRIDOR_PACK_PATH = REPORTS_DIR / "btst_candidate_pool_corridor_validation_pack_latest.json"
DEFAULT_LANE_PAIR_BOARD_PATH = REPORTS_DIR / "btst_candidate_pool_lane_pair_board_latest.json"
DEFAULT_OBJECTIVE_MONITOR_PATH = REPORTS_DIR / "btst_tplus1_tplus2_objective_monitor_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_candidate_pool_corridor_persistence_dossier_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_candidate_pool_corridor_persistence_dossier_latest.md"


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return round(float(left) - float(right), 4)


def _resolve_focus_ticker(corridor_pack: dict[str, Any], lane_pair_board: dict[str, Any], focus_ticker: str | None) -> str:
    if focus_ticker:
        return str(focus_ticker)
    board_leader = dict(lane_pair_board.get("board_leader") or {})
    if str(board_leader.get("lane_family") or "") == "corridor" and str(board_leader.get("ticker") or "").strip():
        return str(board_leader.get("ticker"))
    primary = dict(corridor_pack.get("primary_validation_ticker") or {})
    if str(primary.get("ticker") or "").strip():
        return str(primary.get("ticker"))
    raise ValueError("No corridor focus ticker could be resolved.")


def _find_corridor_row(corridor_pack: dict[str, Any], ticker: str) -> dict[str, Any]:
    primary = dict(corridor_pack.get("primary_validation_ticker") or {})
    if str(primary.get("ticker") or "") == ticker:
        return primary
    for row in list(corridor_pack.get("parallel_watch_tickers") or []):
        candidate = dict(row or {})
        if str(candidate.get("ticker") or "") == ticker:
            return candidate
    for row in list(corridor_pack.get("corridor_ticker_rows") or []):
        candidate = dict(row or {})
        if str(candidate.get("ticker") or "") == ticker:
            return candidate
    return {}


def _find_lane_pair_candidate(lane_pair_board: dict[str, Any], ticker: str) -> dict[str, Any]:
    for row in list(lane_pair_board.get("candidates") or []):
        candidate = dict(row or {})
        if str(candidate.get("ticker") or "") == ticker:
            return candidate
    return {}


def analyze_btst_candidate_pool_corridor_persistence_dossier(
    corridor_pack_path: str | Path,
    *,
    lane_pair_board_path: str | Path,
    objective_monitor_path: str | Path,
    focus_ticker: str | None = None,
) -> dict[str, Any]:
    resolved_corridor_pack_path = Path(corridor_pack_path).expanduser().resolve()
    resolved_lane_pair_board_path = Path(lane_pair_board_path).expanduser().resolve()
    resolved_objective_monitor_path = Path(objective_monitor_path).expanduser().resolve()

    corridor_pack = _load_json(resolved_corridor_pack_path)
    lane_pair_board = _load_json(resolved_lane_pair_board_path)
    objective_monitor = _load_json(resolved_objective_monitor_path)

    resolved_focus_ticker = _resolve_focus_ticker(corridor_pack, lane_pair_board, focus_ticker)
    focus_corridor_row = _find_corridor_row(corridor_pack, resolved_focus_ticker)
    focus_lane_pair_row = _find_lane_pair_candidate(lane_pair_board, resolved_focus_ticker)
    parallel_watch_rows = [
        dict(row or {})
        for row in list(lane_pair_board.get("candidates") or [])
        if str(row.get("role") or "") == "parallel_watch"
    ]
    parallel_watch_row = dict(parallel_watch_rows[0] or {}) if parallel_watch_rows else {}
    tradeable_surface = dict(objective_monitor.get("tradeable_surface") or {})

    same_source_sample_count = focus_lane_pair_row.get("governance_same_source_sample_count")
    same_source_positive_rate = focus_lane_pair_row.get("governance_same_source_next_close_positive_rate")
    same_source_return_mean = focus_lane_pair_row.get("governance_same_source_next_close_return_mean")
    target_independent_sample_count = 2
    missing_independent_sample_count = (
        max(target_independent_sample_count - int(same_source_sample_count or 0), 0)
        if same_source_sample_count is not None
        else None
    )

    continuation_readiness = {
        "governance_status": focus_lane_pair_row.get("governance_status"),
        "governance_blocker": focus_lane_pair_row.get("governance_blocker"),
        "governance_summary": focus_lane_pair_row.get("governance_summary"),
        "current_decision": focus_lane_pair_row.get("current_decision"),
        "current_candidate_source": focus_lane_pair_row.get("current_candidate_source"),
        "same_source_sample_count": same_source_sample_count,
        "same_source_next_close_positive_rate": same_source_positive_rate,
        "same_source_next_close_return_mean": same_source_return_mean,
        "target_independent_sample_count": target_independent_sample_count,
        "missing_independent_sample_count": missing_independent_sample_count,
    }
    objective_edge = {
        "objective_fit_score": focus_corridor_row.get("objective_fit_score"),
        "mean_t_plus_2_return": focus_corridor_row.get("mean_t_plus_2_return"),
        "t_plus_2_positive_rate": focus_corridor_row.get("t_plus_2_positive_rate"),
        "t_plus_2_return_hit_rate_at_target": focus_corridor_row.get("t_plus_2_return_hit_rate_at_target"),
        "positive_rate_delta_vs_tradeable_surface": focus_corridor_row.get("positive_rate_delta_vs_tradeable_surface"),
        "mean_return_delta_vs_tradeable_surface": focus_corridor_row.get("mean_return_delta_vs_tradeable_surface"),
        "return_hit_rate_delta_vs_tradeable_surface": focus_corridor_row.get("return_hit_rate_delta_vs_tradeable_surface"),
        "tradeable_surface_positive_rate": tradeable_surface.get("t_plus_2_positive_rate"),
        "tradeable_surface_mean_return": tradeable_surface.get("mean_t_plus_2_return"),
        "tradeable_surface_return_hit_rate": tradeable_surface.get("t_plus_2_return_hit_rate_at_target"),
        "objective_fit_gap_vs_tradeable_surface": _delta(focus_corridor_row.get("objective_fit_score"), tradeable_surface.get("objective_fit_score")),
    }
    parallel_watch_summary = {
        "ticker": parallel_watch_row.get("ticker"),
        "governance_blocker": parallel_watch_row.get("governance_blocker"),
        "governance_status": parallel_watch_row.get("governance_status"),
        "same_source_sample_count": parallel_watch_row.get("governance_same_source_sample_count"),
        "same_source_next_close_positive_rate": parallel_watch_row.get("governance_same_source_next_close_positive_rate"),
        "same_source_next_close_return_mean": parallel_watch_row.get("governance_same_source_next_close_return_mean"),
        "objective_fit_score": parallel_watch_row.get("objective_fit_score"),
        "mean_t_plus_2_return": parallel_watch_row.get("mean_t_plus_2_return"),
    }

    blocker = str(focus_lane_pair_row.get("governance_blocker") or "").strip()
    if blocker in {"no_selected_persistence_or_independent_edge", "shadow_recall_not_persistent"}:
        verdict = "await_second_independent_selected_window"
        next_confirmation_requirement = (
            f"{resolved_focus_ticker} still needs {missing_independent_sample_count if missing_independent_sample_count is not None else 'additional'} "
            "independent selected sample(s) before merge-readiness can be reconsidered."
        )
        recommendation = (
            f"Keep {resolved_focus_ticker} as corridor primary shadow replay. Do not widen default BTST yet; "
            "the objective edge is already strong, but persistence is still under-sampled."
        )
    elif same_source_positive_rate is not None and float(same_source_positive_rate) <= 0.5:
        verdict = "same_source_edge_not_confirmed"
        next_confirmation_requirement = f"{resolved_focus_ticker} needs another independent selected sample with positive same-source follow-through."
        recommendation = (
            f"{resolved_focus_ticker} remains the corridor leader, but same-source continuation quality is still too weak for default BTST merge review."
        )
    else:
        verdict = "corridor_merge_review_probe_ready"
        next_confirmation_requirement = "The corridor leader has enough persistence and same-source edge to justify merge-review probing."
        recommendation = f"{resolved_focus_ticker} can move from corridor shadow replay into merge-review probing."

    return {
        "corridor_pack_path": str(resolved_corridor_pack_path),
        "lane_pair_board_path": str(resolved_lane_pair_board_path),
        "objective_monitor_path": str(resolved_objective_monitor_path),
        "focus_ticker": resolved_focus_ticker,
        "continuation_readiness": continuation_readiness,
        "objective_edge": objective_edge,
        "parallel_watch_summary": parallel_watch_summary,
        "corridor_pack_status": corridor_pack.get("pack_status"),
        "lane_pair_status": lane_pair_board.get("pair_status"),
        "next_confirmation_requirement": next_confirmation_requirement,
        "verdict": verdict,
        "recommendation": recommendation,
    }


def render_btst_candidate_pool_corridor_persistence_dossier_markdown(analysis: dict[str, Any]) -> str:
    readiness = dict(analysis.get("continuation_readiness") or {})
    objective_edge = dict(analysis.get("objective_edge") or {})
    parallel_watch = dict(analysis.get("parallel_watch_summary") or {})
    lines: list[str] = []
    lines.append("# BTST Candidate Pool Corridor Persistence Dossier")
    lines.append("")
    lines.append("## Focus")
    lines.append(f"- focus_ticker: {analysis.get('focus_ticker')}")
    lines.append(f"- corridor_pack_status: {analysis.get('corridor_pack_status')}")
    lines.append(f"- lane_pair_status: {analysis.get('lane_pair_status')}")
    lines.append("")
    lines.append("## Continuation Readiness")
    lines.append(f"- continuation_readiness: {readiness}")
    lines.append("")
    lines.append("## Objective Edge")
    lines.append(f"- objective_edge: {objective_edge}")
    lines.append("")
    lines.append("## Parallel Watch")
    lines.append(f"- parallel_watch_summary: {parallel_watch}")
    lines.append("")
    lines.append("## Verdict")
    lines.append(f"- verdict: {analysis.get('verdict')}")
    lines.append(f"- next_confirmation_requirement: {analysis.get('next_confirmation_requirement')}")
    lines.append(f"- recommendation: {analysis.get('recommendation')}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Explain why the corridor leader is or is not ready for the next BTST upgrade step.")
    parser.add_argument("--corridor-pack-path", default=str(DEFAULT_CORRIDOR_PACK_PATH))
    parser.add_argument("--lane-pair-board-path", default=str(DEFAULT_LANE_PAIR_BOARD_PATH))
    parser.add_argument("--objective-monitor-path", default=str(DEFAULT_OBJECTIVE_MONITOR_PATH))
    parser.add_argument("--focus-ticker", default="")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_candidate_pool_corridor_persistence_dossier(
        args.corridor_pack_path,
        lane_pair_board_path=args.lane_pair_board_path,
        objective_monitor_path=args.objective_monitor_path,
        focus_ticker=str(args.focus_ticker or "").strip() or None,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md = Path(args.output_md).expanduser().resolve()
    output_md.write_text(render_btst_candidate_pool_corridor_persistence_dossier_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
