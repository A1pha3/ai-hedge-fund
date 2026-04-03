from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPORTS_DIR = Path("data/reports")
DEFAULT_FAILURE_DOSSIER_PATH = REPORTS_DIR / "btst_no_candidate_entry_failure_dossier_latest.json"
DEFAULT_WATCHLIST_RECALL_DOSSIER_PATH = REPORTS_DIR / "btst_watchlist_recall_dossier_latest.json"
DEFAULT_CANDIDATE_POOL_RECALL_DOSSIER_PATH = REPORTS_DIR / "btst_candidate_pool_recall_dossier_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_candidate_pool_upstream_handoff_board_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_candidate_pool_upstream_handoff_board_latest.md"


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


def _prototype_for_ticker(experiment_queue: list[dict[str, Any]], ticker: str) -> dict[str, Any]:
    for row in experiment_queue:
        if ticker in {str(value or "") for value in list(row.get("tickers") or [])}:
            return dict(row)
    return {}


def analyze_btst_candidate_pool_upstream_handoff_board(
    failure_dossier_path: str | Path,
    *,
    watchlist_recall_dossier_path: str | Path | None = None,
    candidate_pool_recall_dossier_path: str | Path | None = None,
) -> dict[str, Any]:
    failure_dossier = _maybe_load_json(failure_dossier_path)
    watchlist_dossier = _maybe_load_json(watchlist_recall_dossier_path)
    recall_dossier = _maybe_load_json(candidate_pool_recall_dossier_path)

    failure_rows = {
        str(row.get("ticker") or ""): dict(row)
        for row in list(failure_dossier.get("priority_ticker_dossiers") or [])
        if str(row.get("ticker") or "").strip()
    }
    watchlist_rows = {
        str(row.get("ticker") or ""): dict(row)
        for row in list(watchlist_dossier.get("priority_ticker_dossiers") or [])
        if str(row.get("ticker") or "").strip()
    }
    recall_action_rows = {
        str(row.get("ticker") or ""): dict(row)
        for row in list(recall_dossier.get("action_queue") or [])
        if str(row.get("ticker") or "").strip()
    }
    experiment_queue = [dict(row) for row in list(recall_dossier.get("priority_handoff_branch_experiment_queue") or [])]

    focus_tickers: list[str] = []
    for ticker in list(failure_dossier.get("top_upstream_absence_tickers") or []):
        normalized = str(ticker or "").strip()
        if normalized and normalized not in focus_tickers:
            focus_tickers.append(normalized)
    for ticker in list(watchlist_dossier.get("focus_tickers") or []):
        normalized = str(ticker or "").strip()
        if normalized and normalized not in focus_tickers:
            focus_tickers.append(normalized)
    for ticker in list(recall_dossier.get("focus_tickers") or []):
        normalized = str(ticker or "").strip()
        if normalized and normalized not in focus_tickers:
            focus_tickers.append(normalized)

    board_rows: list[dict[str, Any]] = []
    for ticker in focus_tickers:
        failure_row = dict(failure_rows.get(ticker) or {})
        watchlist_row = dict(watchlist_rows.get(ticker) or {})
        recall_row = dict(recall_action_rows.get(ticker) or {})
        truncation_profile = dict(recall_row.get("truncation_liquidity_profile") or {})
        prototype = _prototype_for_ticker(experiment_queue, ticker)

        replay_input_visible_report_count = int(failure_row.get("replay_input_visible_report_count") or 0)
        watchlist_visible_report_count = int(failure_row.get("watchlist_visible_report_count") or 0)
        candidate_pool_visible_count = int(watchlist_row.get("candidate_pool_visible_count") or 0)

        board_rows.append(
            {
                "ticker": ticker,
                "primary_failure_class": failure_row.get("primary_failure_class"),
                "first_broken_handoff": failure_row.get("handoff_stage") or watchlist_row.get("dominant_recall_stage"),
                "watchlist_recall_stage": watchlist_row.get("dominant_recall_stage"),
                "candidate_pool_blocking_stage": recall_row.get("dominant_blocking_stage"),
                "priority_handoff": truncation_profile.get("priority_handoff"),
                "prototype_task_id": prototype.get("task_id"),
                "prototype_readiness": prototype.get("prototype_readiness"),
                "prototype_type": prototype.get("prototype_type"),
                "primary_report_dir": failure_row.get("primary_report_dir") or watchlist_row.get("primary_report_dir"),
                "replay_input_visible_report_count": replay_input_visible_report_count,
                "watchlist_visible_report_count": watchlist_visible_report_count,
                "candidate_pool_visible_count": candidate_pool_visible_count,
                "layer_b_visible_count": int(watchlist_row.get("layer_b_visible_count") or 0),
                "candidate_pool_rank_gap_min": truncation_profile.get("min_rank_gap_to_cutoff"),
                "avg_amount_share_of_cutoff_mean": truncation_profile.get("avg_amount_share_of_cutoff_mean"),
                "avg_amount_share_of_min_gate_mean": truncation_profile.get("avg_amount_share_of_min_gate_mean"),
                "profile_summary": truncation_profile.get("profile_summary"),
                "failure_reason": failure_row.get("failure_reason"),
                "next_step": prototype.get("prototype_summary") or recall_row.get("next_step") or failure_row.get("next_step"),
            }
        )

    board_rows.sort(
        key=lambda row: (
            0 if str(row.get("first_broken_handoff") or "") == "absent_from_watchlist" else 1,
            0 if str(row.get("priority_handoff") or "") == "layer_a_liquidity_corridor" else 1,
            float(row.get("candidate_pool_rank_gap_min") or 999999),
            str(row.get("ticker") or ""),
        )
    )
    for index, row in enumerate(board_rows, start=1):
        row["board_rank"] = index

    stage_summary = {
        "first_broken_handoff_counts": {},
        "priority_handoff_counts": {},
    }
    for row in board_rows:
        first_broken = str(row.get("first_broken_handoff") or "unknown")
        priority_handoff = str(row.get("priority_handoff") or "unknown")
        stage_summary["first_broken_handoff_counts"][first_broken] = stage_summary["first_broken_handoff_counts"].get(first_broken, 0) + 1
        stage_summary["priority_handoff_counts"][priority_handoff] = stage_summary["priority_handoff_counts"].get(priority_handoff, 0) + 1

    if board_rows:
        recommendation = (
            f"upstream handoff board 已收敛到 {focus_tickers[:3]}。"
            " 这些票当前都不该再下钻 candidate-entry 语义，而应先沿 replay input -> watchlist -> candidate_pool 的断点回补。"
        )
        next_actions = [
            f"先补 {row.get('ticker')} 的 first_broken_handoff={row.get('first_broken_handoff')}，再进入 {row.get('priority_handoff')} lane 的 downstream probe。"
            for row in board_rows[:3]
        ]
        board_status = "ready_for_upstream_handoff_execution"
    else:
        recommendation = "当前没有可执行的 upstream handoff 焦点票。"
        next_actions = []
        board_status = "skipped_no_focus_tickers"

    return {
        "failure_dossier_path": str(Path(failure_dossier_path).expanduser().resolve()),
        "watchlist_recall_dossier_path": str(Path(watchlist_recall_dossier_path).expanduser().resolve()) if watchlist_recall_dossier_path else None,
        "candidate_pool_recall_dossier_path": str(Path(candidate_pool_recall_dossier_path).expanduser().resolve()) if candidate_pool_recall_dossier_path else None,
        "board_status": board_status,
        "focus_tickers": focus_tickers,
        "stage_summary": stage_summary,
        "board_rows": board_rows,
        "recommendation": recommendation,
        "next_actions": next_actions,
    }


def render_btst_candidate_pool_upstream_handoff_board_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Candidate Pool Upstream Handoff Board")
    lines.append("")
    lines.append("## Status")
    lines.append(f"- board_status: {analysis.get('board_status')}")
    lines.append(f"- focus_tickers: {analysis.get('focus_tickers')}")
    lines.append(f"- stage_summary: {analysis.get('stage_summary')}")
    lines.append("")
    lines.append("## Board")
    for row in list(analysis.get("board_rows") or []):
        lines.append(
            f"- board_rank={row.get('board_rank')} ticker={row.get('ticker')} first_broken_handoff={row.get('first_broken_handoff')} priority_handoff={row.get('priority_handoff')} prototype_readiness={row.get('prototype_readiness')} candidate_pool_rank_gap_min={row.get('candidate_pool_rank_gap_min')}"
        )
        lines.append(f"  failure_reason: {row.get('failure_reason')}")
        lines.append(f"  next_step: {row.get('next_step')}")
    if not list(analysis.get("board_rows") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis.get('recommendation')}")
    for item in list(analysis.get("next_actions") or []):
        lines.append(f"- next_action: {item}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build an upstream handoff board for candidate-pool recall focus tickers.")
    parser.add_argument("--failure-dossier-path", default=str(DEFAULT_FAILURE_DOSSIER_PATH))
    parser.add_argument("--watchlist-recall-dossier-path", default=str(DEFAULT_WATCHLIST_RECALL_DOSSIER_PATH))
    parser.add_argument("--candidate-pool-recall-dossier-path", default=str(DEFAULT_CANDIDATE_POOL_RECALL_DOSSIER_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_candidate_pool_upstream_handoff_board(
        args.failure_dossier_path,
        watchlist_recall_dossier_path=args.watchlist_recall_dossier_path,
        candidate_pool_recall_dossier_path=args.candidate_pool_recall_dossier_path,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md = Path(args.output_md).expanduser().resolve()
    output_md.write_text(render_btst_candidate_pool_upstream_handoff_board_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))