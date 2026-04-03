from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.btst_latest_followup_utils import load_latest_upstream_shadow_followup_by_ticker


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


def _resolved_reports_root(*, failure_dossier_path: str | Path, candidate_pool_recall_dossier_path: str | Path | None) -> Path:
    reference_path = Path(candidate_pool_recall_dossier_path or failure_dossier_path).expanduser().resolve()
    return reference_path.parent


def _build_validated_followup_reason(ticker: str, followup_row: dict[str, Any]) -> str:
    decision = str(followup_row.get("decision") or "unknown")
    bottleneck = str(followup_row.get("downstream_bottleneck") or "")
    if decision == "near_miss":
        return f"{ticker} 已在最新 short-trade followup 中通过 upstream shadow recall 正式进入 near_miss，当前首要问题不再是 watchlist/candidate_pool 缺席。"
    if bottleneck == "profitability_hard_cliff":
        return f"{ticker} 已在最新 short-trade followup 中完成 upstream shadow recall 验证，但当前主矛盾转为 profitability_hard_cliff，而不是上游 absence。"
    if decision == "rejected":
        return f"{ticker} 已在最新 short-trade followup 中完成 upstream shadow recall 验证，但仍停留在 recalled-shadow rejected 层。"
    return f"{ticker} 已在最新 short-trade followup 中完成 upstream shadow recall 验证，应转入当前 decision 对应的 downstream 分层。"


def _build_validated_followup_next_step(ticker: str, followup_row: dict[str, Any], *, priority_handoff: str | None) -> str:
    decision = str(followup_row.get("decision") or "unknown")
    bottleneck = str(followup_row.get("downstream_bottleneck") or "")
    priority_handoff_token = str(priority_handoff or "").strip() or "upstream_shadow"
    if decision == "near_miss":
        return f"保持 {ticker} 的 {priority_handoff_token} lane 背景，仅转入 near_miss opening watch / downstream observation，不再重复 upstream recall probe。"
    if bottleneck == "profitability_hard_cliff":
        return f"把 {ticker} 转入 recalled-shadow profitability hard cliff diagnostics，保留 {priority_handoff_token} lane 背景，但不再重复 watchlist/candidate_pool recall。"
    if decision == "rejected":
        return f"把 {ticker} 留在 recalled-shadow rejected followup，继续下钻当前 score fail / gate fail 原因，而不是重复 upstream recall。"
    return f"把 {ticker} 转回当前 short-trade decision 对应的 downstream followup，不再继续 upstream recall probe。"


def _board_sort_key(row: dict[str, Any]) -> tuple[int, int, float, str]:
    first_broken = str(row.get("first_broken_handoff") or "")
    priority_handoff = str(row.get("priority_handoff") or "")
    unresolved_priority = 0 if first_broken in {"absent_from_watchlist", "absent_from_candidate_pool", "candidate_pool_truncated_after_filters"} else 1
    handoff_priority = 0 if priority_handoff == "layer_a_liquidity_corridor" else 1
    return (
        unresolved_priority,
        handoff_priority,
        float(row.get("candidate_pool_rank_gap_min") or 999999),
        str(row.get("ticker") or ""),
    )


def _build_handoff_commands(*, ticker: str, priority_handoff: str | None) -> list[str]:
    normalized_priority_handoff = str(priority_handoff or "").strip()
    commands = [
        "python scripts/run_btst_candidate_pool_upstream_handoff_board.py "
        "--failure-dossier-path data/reports/btst_no_candidate_entry_failure_dossier_latest.json "
        "--watchlist-recall-dossier-path data/reports/btst_watchlist_recall_dossier_latest.json "
        "--candidate-pool-recall-dossier-path data/reports/btst_candidate_pool_recall_dossier_latest.json "
        "--output-json data/reports/btst_candidate_pool_upstream_handoff_board_latest.json "
        "--output-md data/reports/btst_candidate_pool_upstream_handoff_board_latest.md",
    ]
    if normalized_priority_handoff == "layer_a_liquidity_corridor":
        commands.append(
            "python scripts/run_btst_candidate_pool_corridor_uplift_runbook.py "
            "--candidate-pool-recall-dossier-path data/reports/btst_candidate_pool_recall_dossier_latest.json "
            "--corridor-shadow-pack-path data/reports/btst_candidate_pool_corridor_shadow_pack_latest.json "
            "--lane-pair-board-path data/reports/btst_candidate_pool_lane_pair_board_latest.json "
            "--output-json data/reports/btst_candidate_pool_corridor_uplift_runbook_latest.json "
            "--output-md data/reports/btst_candidate_pool_corridor_uplift_runbook_latest.md "
            f"# focus_ticker={ticker}"
        )
    elif normalized_priority_handoff == "post_gate_liquidity_competition":
        commands.append(
            "python scripts/run_btst_candidate_pool_rebucket_shadow_pack.py "
            "--dossier-path data/reports/btst_candidate_pool_recall_dossier_latest.json "
            f"--ticker {ticker} --output-dir data/reports"
        )
        commands.append(
            "python scripts/analyze_btst_candidate_pool_rebucket_objective_validation.py "
            "--dossier-path data/reports/btst_candidate_pool_recall_dossier_latest.json "
            "--objective-monitor-path data/reports/btst_tplus1_tplus2_objective_monitor_latest.json "
            "--lane-objective-support-path data/reports/btst_candidate_pool_lane_objective_support_latest.json "
            f"--ticker {ticker} "
            "--output-json data/reports/btst_candidate_pool_rebucket_objective_validation_latest.json "
            "--output-md data/reports/btst_candidate_pool_rebucket_objective_validation_latest.md"
        )
    return commands


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
    latest_followup_by_ticker = load_latest_upstream_shadow_followup_by_ticker(
        _resolved_reports_root(
            failure_dossier_path=failure_dossier_path,
            candidate_pool_recall_dossier_path=candidate_pool_recall_dossier_path,
        )
    )

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
        latest_followup_row = dict(latest_followup_by_ticker.get(ticker) or {})

        replay_input_visible_report_count = int(failure_row.get("replay_input_visible_report_count") or 0)
        watchlist_visible_report_count = int(failure_row.get("watchlist_visible_report_count") or 0)
        candidate_pool_visible_count = int(watchlist_row.get("candidate_pool_visible_count") or 0)

        first_broken_handoff = failure_row.get("handoff_stage") or watchlist_row.get("dominant_recall_stage")
        board_phase = "upstream_handoff_gap"
        failure_reason = failure_row.get("failure_reason")
        next_step = prototype.get("prototype_summary") or recall_row.get("next_step") or failure_row.get("next_step")
        recommended_commands = _build_handoff_commands(ticker=ticker, priority_handoff=truncation_profile.get("priority_handoff"))
        if latest_followup_row:
            first_broken_handoff = "downstream_validated_after_shadow_recall"
            board_phase = "post_recall_downstream_followup"
            failure_reason = _build_validated_followup_reason(ticker, latest_followup_row)
            next_step = _build_validated_followup_next_step(ticker, latest_followup_row, priority_handoff=truncation_profile.get("priority_handoff"))
            recommended_commands = [recommended_commands[0]] if recommended_commands else []

        board_rows.append(
            {
                "ticker": ticker,
                "board_phase": board_phase,
                "primary_failure_class": failure_row.get("primary_failure_class"),
                "first_broken_handoff": first_broken_handoff,
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
                "failure_reason": failure_reason,
                "next_step": next_step,
                "latest_followup_decision": latest_followup_row.get("decision"),
                "latest_followup_trade_date": latest_followup_row.get("trade_date"),
                "latest_followup_report_dir": latest_followup_row.get("report_dir"),
                "latest_followup_top_reasons": list(latest_followup_row.get("top_reasons") or []),
                "latest_followup_positive_tags": list(latest_followup_row.get("positive_tags") or []),
                "latest_followup_gate_status": dict(latest_followup_row.get("gate_status") or {}),
                "latest_followup_downstream_bottleneck": latest_followup_row.get("downstream_bottleneck"),
                "recommended_commands": recommended_commands,
            }
        )

    board_rows.sort(key=_board_sort_key)
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

    validated_rows = [row for row in board_rows if str(row.get("board_phase") or "") == "post_recall_downstream_followup"]
    unresolved_rows = [row for row in board_rows if str(row.get("board_phase") or "") != "post_recall_downstream_followup"]

    if board_rows:
        if validated_rows and unresolved_rows:
            recommendation = (
                f"upstream handoff board 当前分成两段：{[row.get('ticker') for row in unresolved_rows[:3]]} 仍是 upstream recall gap，"
                f"而 {[row.get('ticker') for row in validated_rows[:3]]} 已在最新正式 shadow rerun 中完成 downstream 分层验证，不应再按 absent_from_watchlist 处理。"
            )
            board_status = "mixed_upstream_and_post_recall_followup"
        elif validated_rows:
            recommendation = (
                f"当前焦点票 {[row.get('ticker') for row in validated_rows[:3]]} 已在最新正式 shadow rerun 中完成 downstream 分层验证，"
                "下一步应按当前 short-trade decision 继续 followup，而不是重复 upstream recall probe。"
            )
            board_status = "post_recall_followup_ready"
        else:
            recommendation = (
                f"upstream handoff board 已收敛到 {focus_tickers[:3]}。"
                " 这些票当前都不该再下钻 candidate-entry 语义，而应先沿 replay input -> watchlist -> candidate_pool 的断点回补。"
            )
            board_status = "ready_for_upstream_handoff_execution"

        next_actions = []
        for row in unresolved_rows[:2]:
            next_actions.append(
                f"先补 {row.get('ticker')} 的 first_broken_handoff={row.get('first_broken_handoff')}，再进入 {row.get('priority_handoff')} lane 的 downstream probe。"
            )
        for row in validated_rows[:2]:
            next_actions.append(
                f"{row.get('ticker')} 已完成正式 shadow recall 验证，当前转入 decision={row.get('latest_followup_decision')} 的 downstream followup。"
            )
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
            f"- board_rank={row.get('board_rank')} ticker={row.get('ticker')} board_phase={row.get('board_phase')} first_broken_handoff={row.get('first_broken_handoff')} priority_handoff={row.get('priority_handoff')} prototype_readiness={row.get('prototype_readiness')} candidate_pool_rank_gap_min={row.get('candidate_pool_rank_gap_min')}"
        )
        lines.append(f"  failure_reason: {row.get('failure_reason')}")
        lines.append(f"  next_step: {row.get('next_step')}")
        if row.get("latest_followup_decision"):
            lines.append(
                f"  latest_followup: decision={row.get('latest_followup_decision')} bottleneck={row.get('latest_followup_downstream_bottleneck')} top_reasons={row.get('latest_followup_top_reasons')}"
            )
        for command in list(row.get("recommended_commands") or []):
            lines.append(f"  command: {command}")
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