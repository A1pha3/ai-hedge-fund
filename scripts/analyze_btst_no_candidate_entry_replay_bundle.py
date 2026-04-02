from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.analyze_btst_candidate_entry_frontier import analyze_btst_candidate_entry_frontier
from scripts.analyze_btst_candidate_entry_window_scan import analyze_btst_candidate_entry_window_scan
from scripts.btst_report_utils import discover_report_dirs


REPORTS_DIR = Path("data/reports")
DEFAULT_ACTION_BOARD_PATH = REPORTS_DIR / "btst_no_candidate_entry_action_board_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_no_candidate_entry_replay_bundle_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_no_candidate_entry_replay_bundle_latest.md"
DEFAULT_PRIORITY_REPLAY_LIMIT = 3
DEFAULT_HOTSPOT_REPLAY_LIMIT = 2
DEFAULT_GLOBAL_SCAN_FOCUS_LIMIT = 5
PROMISING_RECALL_STATUSES = {
    "filters_focus_and_weaker_than_false_negative_pool",
}


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _parse_limit(value: int | None, default: int) -> int:
    if value is None:
        return default
    return max(int(value), 0)


def _resolve_report_dir(reports_root: Path, report_dir_name: str | None) -> Path | None:
    token = str(report_dir_name or "").strip()
    if not token:
        return None
    resolved = (reports_root / token).expanduser().resolve()
    if resolved.exists():
        return resolved
    return None


def _summarize_frontier_analysis(
    analysis: dict[str, Any],
    *,
    source_kind: str,
    source_label: str,
    focus_tickers: list[str],
    preserve_tickers: list[str],
    priority_rank: int | None,
    report_dir_name: str | None,
    ticker: str | None = None,
) -> dict[str, Any]:
    best_variant = dict(analysis.get("best_variant") or {})
    status = str(best_variant.get("candidate_entry_status") or "no_best_variant")
    focus_filtered_tickers = [str(value) for value in list(best_variant.get("focus_filtered_tickers") or []) if str(value or "").strip()]
    preserve_filtered_tickers = [str(value) for value in list(best_variant.get("preserve_filtered_tickers") or []) if str(value or "").strip()]
    viable_recall_probe = bool(
        status in PROMISING_RECALL_STATUSES
        and not preserve_filtered_tickers
        and (not focus_tickers or focus_filtered_tickers)
    )
    filtered_candidate_entry_count = int(best_variant.get("filtered_candidate_entry_count") or 0)
    return {
        "source_kind": source_kind,
        "source_label": source_label,
        "priority_rank": priority_rank,
        "report_dir": report_dir_name,
        "ticker": ticker,
        "focus_tickers": focus_tickers,
        "preserve_tickers": preserve_tickers,
        "best_variant_name": best_variant.get("variant_name"),
        "candidate_entry_status": status,
        "filtered_candidate_entry_count": filtered_candidate_entry_count,
        "focus_filtered_tickers": focus_filtered_tickers,
        "preserve_filtered_tickers": preserve_filtered_tickers,
        "filtered_next_high_hit_rate_at_threshold": best_variant.get("filtered_next_high_hit_rate_at_threshold"),
        "filtered_next_close_positive_rate": best_variant.get("filtered_next_close_positive_rate"),
        "evidence_tier": best_variant.get("evidence_tier"),
        "comparison_note": best_variant.get("comparison_note"),
        "selection_basis": best_variant.get("selection_basis"),
        "viable_recall_probe": viable_recall_probe,
    }


def _run_frontier_analysis(
    report_dir: Path,
    *,
    source_kind: str,
    source_label: str,
    focus_tickers: list[str],
    preserve_tickers: list[str],
    priority_rank: int | None,
    ticker: str | None = None,
) -> dict[str, Any]:
    analysis = analyze_btst_candidate_entry_frontier(
        report_dir,
        focus_tickers=focus_tickers,
        preserve_tickers=preserve_tickers,
    )
    return _summarize_frontier_analysis(
        analysis,
        source_kind=source_kind,
        source_label=source_label,
        focus_tickers=focus_tickers,
        preserve_tickers=preserve_tickers,
        priority_rank=priority_rank,
        report_dir_name=report_dir.name,
        ticker=ticker,
    )


def _build_priority_replay_rows(
    action_board: dict[str, Any],
    *,
    reports_root: Path,
    preserve_tickers: list[str],
    priority_limit: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source_row in list(action_board.get("priority_queue") or [])[:priority_limit]:
        ticker = str(source_row.get("ticker") or "").strip()
        report_dir_name = str(source_row.get("primary_report_dir") or "").strip()
        report_dir = _resolve_report_dir(reports_root, report_dir_name)
        if not ticker or report_dir is None:
            rows.append(
                {
                    "source_kind": "priority_queue",
                    "source_label": ticker or report_dir_name or "unknown_priority_queue_row",
                    "priority_rank": source_row.get("priority_rank"),
                    "report_dir": report_dir_name or None,
                    "ticker": ticker or None,
                    "focus_tickers": [ticker] if ticker else [],
                    "preserve_tickers": preserve_tickers,
                    "best_variant_name": None,
                    "candidate_entry_status": "missing_report_dir",
                    "filtered_candidate_entry_count": 0,
                    "focus_filtered_tickers": [],
                    "preserve_filtered_tickers": [],
                    "filtered_next_high_hit_rate_at_threshold": None,
                    "filtered_next_close_positive_rate": None,
                    "evidence_tier": None,
                    "comparison_note": "priority queue row is missing a usable report_dir, so no frontier replay was run.",
                    "selection_basis": None,
                    "viable_recall_probe": False,
                }
            )
            continue

        rows.append(
            _run_frontier_analysis(
                report_dir,
                source_kind="priority_queue",
                source_label=ticker,
                focus_tickers=[ticker],
                preserve_tickers=preserve_tickers,
                priority_rank=int(source_row.get("priority_rank") or 0) or None,
                ticker=ticker,
            )
        )
    return rows


def _build_hotspot_replay_rows(
    action_board: dict[str, Any],
    *,
    reports_root: Path,
    preserve_tickers: list[str],
    hotspot_limit: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source_row in list(action_board.get("window_hotspot_rows") or [])[:hotspot_limit]:
        report_dir_name = str(source_row.get("report_dir") or "").strip()
        report_dir = _resolve_report_dir(reports_root, report_dir_name)
        focus_tickers = [str(value) for value in list(source_row.get("top_focus_tickers") or []) if str(value or "").strip()]
        if not focus_tickers or report_dir is None:
            rows.append(
                {
                    "source_kind": "window_hotspot",
                    "source_label": report_dir_name or "unknown_window_hotspot",
                    "priority_rank": source_row.get("priority_rank"),
                    "report_dir": report_dir_name or None,
                    "ticker": None,
                    "focus_tickers": focus_tickers,
                    "preserve_tickers": preserve_tickers,
                    "best_variant_name": None,
                    "candidate_entry_status": "missing_report_dir",
                    "filtered_candidate_entry_count": 0,
                    "focus_filtered_tickers": [],
                    "preserve_filtered_tickers": [],
                    "filtered_next_high_hit_rate_at_threshold": None,
                    "filtered_next_close_positive_rate": None,
                    "evidence_tier": None,
                    "comparison_note": "window hotspot row is missing a usable report_dir, so no frontier replay was run.",
                    "selection_basis": None,
                    "viable_recall_probe": False,
                }
            )
            continue

        rows.append(
            _run_frontier_analysis(
                report_dir,
                source_kind="window_hotspot",
                source_label=report_dir.name,
                focus_tickers=focus_tickers,
                preserve_tickers=preserve_tickers,
                priority_rank=int(source_row.get("priority_rank") or 0) or None,
            )
        )
    return rows


def _summarize_window_scan(analysis: dict[str, Any]) -> dict[str, Any]:
    filtered_ticker_counts = dict(analysis.get("filtered_ticker_counts") or {})
    top_filtered_tickers = [str(label) for label, _ in list(filtered_ticker_counts.items())[:5] if str(label or "").strip()]
    focus_hit_rows = [
        {
            "report_name": str(row.get("report_name") or ""),
            "window_key": str(row.get("window_key") or ""),
            "focus_filtered_tickers": [str(value) for value in list(row.get("focus_filtered_tickers") or []) if str(value or "").strip()],
            "preserve_filtered_tickers": [str(value) for value in list(row.get("preserve_filtered_tickers") or []) if str(value or "").strip()],
            "filtered_candidate_entry_count": int(row.get("filtered_candidate_entry_count") or 0),
            "window_status": row.get("window_status"),
        }
        for row in list(analysis.get("rows") or [])
        if list(row.get("focus_filtered_tickers") or [])
    ][:3]
    return {
        "report_count": analysis.get("report_count"),
        "filtered_report_count": analysis.get("filtered_report_count"),
        "focus_hit_report_count": analysis.get("focus_hit_report_count"),
        "preserve_misfire_report_count": analysis.get("preserve_misfire_report_count"),
        "distinct_window_count_with_filtered_entries": analysis.get("distinct_window_count_with_filtered_entries"),
        "rollout_readiness": analysis.get("rollout_readiness"),
        "recommendation": analysis.get("recommendation"),
        "top_filtered_tickers": top_filtered_tickers,
        "focus_hit_rows": focus_hit_rows,
    }


def _build_next_actions(
    priority_replay_rows: list[dict[str, Any]],
    hotspot_replay_rows: list[dict[str, Any]],
    global_window_scan_summary: dict[str, Any],
) -> list[str]:
    actions: list[str] = []
    promising_priority_tickers = [
        str(row.get("ticker") or "")
        for row in priority_replay_rows
        if row.get("viable_recall_probe") and row.get("ticker")
    ]
    if promising_priority_tickers:
        actions.append(
            f"优先把 {promising_priority_tickers[:3]} 保留为 no-entry shadow recall probe，并继续核对 preserve_ticker 0 误伤。"
        )
    else:
        actions.append("当前 top no-entry backlog 还没有形成 preserve-safe recall probe，继续保持 research-only，不要放松 score frontier。")

    promising_hotspots = [
        str(row.get("report_dir") or "")
        for row in hotspot_replay_rows
        if row.get("viable_recall_probe") and row.get("report_dir")
    ]
    if promising_hotspots:
        actions.append(f"优先回看热点窗口 {promising_hotspots[:2]} 的 candidate-entry selective semantics，确认是否能稳定复现。")

    if int(global_window_scan_summary.get("focus_hit_report_count") or 0) > 0:
        actions.append(
            f"全局 window scan 已命中 {global_window_scan_summary.get('focus_hit_report_count')} 份报告，下一步按 {global_window_scan_summary.get('rollout_readiness')} 继续 shadow 治理。"
        )
    else:
        actions.append("全局 window scan 还没有对 top no-entry tickers 形成跨窗 focus hit，先累积窗口证据，再讨论 lane promotion。")
    return actions[:3]


def analyze_btst_no_candidate_entry_replay_bundle(
    action_board_path: str | Path,
    *,
    priority_replay_limit: int = DEFAULT_PRIORITY_REPLAY_LIMIT,
    hotspot_replay_limit: int = DEFAULT_HOTSPOT_REPLAY_LIMIT,
    global_scan_focus_limit: int = DEFAULT_GLOBAL_SCAN_FOCUS_LIMIT,
) -> dict[str, Any]:
    action_board = _load_json(action_board_path)
    resolved_action_board_path = Path(action_board_path).expanduser().resolve()
    reports_root = Path(action_board.get("reports_root") or resolved_action_board_path.parent).expanduser().resolve()
    preserve_tickers = [str(value) for value in list(action_board.get("preserve_tickers") or []) if str(value or "").strip()]
    priority_replay_limit = _parse_limit(priority_replay_limit, DEFAULT_PRIORITY_REPLAY_LIMIT)
    hotspot_replay_limit = _parse_limit(hotspot_replay_limit, DEFAULT_HOTSPOT_REPLAY_LIMIT)
    global_scan_focus_limit = _parse_limit(global_scan_focus_limit, DEFAULT_GLOBAL_SCAN_FOCUS_LIMIT)

    priority_replay_rows = _build_priority_replay_rows(
        action_board,
        reports_root=reports_root,
        preserve_tickers=preserve_tickers,
        priority_limit=priority_replay_limit,
    )
    hotspot_replay_rows = _build_hotspot_replay_rows(
        action_board,
        reports_root=reports_root,
        preserve_tickers=preserve_tickers,
        hotspot_limit=hotspot_replay_limit,
    )

    top_priority_tickers = [str(value) for value in list(action_board.get("top_priority_tickers") or []) if str(value or "").strip()][:global_scan_focus_limit]
    window_report_dirs = [path for path in discover_report_dirs(reports_root) if "paper_trading_window" in path.name]
    global_window_scan_analysis = analyze_btst_candidate_entry_window_scan(
        window_report_dirs,
        structural_variant="exclude_watchlist_avoid_weak_structure_entries",
        focus_tickers=top_priority_tickers,
        preserve_tickers=preserve_tickers,
    ) if window_report_dirs else {
        "report_count": 0,
        "filtered_report_count": 0,
        "focus_hit_report_count": 0,
        "preserve_misfire_report_count": 0,
        "distinct_window_count_with_filtered_entries": 0,
        "rollout_readiness": "no_window_reports",
        "recommendation": "reports_root 下没有可扫描的 paper_trading_window 报告。",
        "rows": [],
        "filtered_ticker_counts": {},
    }
    global_window_scan_summary = _summarize_window_scan(global_window_scan_analysis)

    all_replay_rows = [*priority_replay_rows, *hotspot_replay_rows]
    best_variant_counts = Counter(
        str(row.get("best_variant_name") or "unknown")
        for row in all_replay_rows
        if row.get("best_variant_name")
    )
    candidate_entry_status_counts = Counter(str(row.get("candidate_entry_status") or "unknown") for row in all_replay_rows)
    promising_priority_tickers = [
        str(row.get("ticker") or "")
        for row in priority_replay_rows
        if row.get("viable_recall_probe") and row.get("ticker")
    ]
    promising_hotspot_report_dirs = [
        str(row.get("report_dir") or "")
        for row in hotspot_replay_rows
        if row.get("viable_recall_probe") and row.get("report_dir")
    ]
    next_actions = _build_next_actions(priority_replay_rows, hotspot_replay_rows, global_window_scan_summary)

    if promising_priority_tickers:
        recommendation = (
            f"当前 no-entry replay bundle 已为 {promising_priority_tickers[:3]} 找到 preserve-safe candidate-entry recall probe，"
            "下一步应优先接回 shadow governance，而不是继续放松 score frontier。"
        )
    else:
        recommendation = (
            "当前 no-entry replay bundle 还没有为 top backlog 找到 preserve-safe recall probe，"
            "应继续保持 no-entry 研究车道，并等待新的窗口证据。"
        )

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "action_board_path": resolved_action_board_path.as_posix(),
        "reports_root": reports_root.as_posix(),
        "priority_replay_limit": priority_replay_limit,
        "hotspot_replay_limit": hotspot_replay_limit,
        "global_scan_focus_limit": global_scan_focus_limit,
        "preserve_tickers": preserve_tickers,
        "priority_replay_rows": priority_replay_rows,
        "hotspot_replay_rows": hotspot_replay_rows,
        "global_window_scan": global_window_scan_summary,
        "promising_priority_tickers": promising_priority_tickers,
        "promising_hotspot_report_dirs": promising_hotspot_report_dirs,
        "best_variant_counts": dict(best_variant_counts.most_common()),
        "candidate_entry_status_counts": dict(candidate_entry_status_counts.most_common()),
        "next_actions": next_actions,
        "keep_guardrails": [
            "只把 preserve-safe 的 recall probe 接回 shadow governance；一旦误伤 preserve_ticker，立即退回 research-only。",
            "no-entry replay bundle 的目标是补 recall 证据，不是放松 score frontier。",
            "若 global window scan 仍缺第二独立窗口 focus hit，不得把单窗 recall probe 提升为默认入口规则。",
        ],
        "recommendation": recommendation,
    }


def render_btst_no_candidate_entry_replay_bundle_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST No Candidate Entry Replay Bundle")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- action_board_path: {analysis.get('action_board_path')}")
    lines.append(f"- promising_priority_tickers: {analysis.get('promising_priority_tickers')}")
    lines.append(f"- promising_hotspot_report_dirs: {analysis.get('promising_hotspot_report_dirs')}")
    lines.append(f"- best_variant_counts: {analysis.get('best_variant_counts')}")
    lines.append(f"- candidate_entry_status_counts: {analysis.get('candidate_entry_status_counts')}")
    lines.append(f"- recommendation: {analysis.get('recommendation')}")
    lines.append("")
    lines.append("## Priority Replays")
    for row in list(analysis.get("priority_replay_rows") or []):
        lines.append(
            f"- rank={row.get('priority_rank')} ticker={row.get('ticker')} report_dir={row.get('report_dir')} status={row.get('candidate_entry_status')} best_variant={row.get('best_variant_name')} viable_recall_probe={row.get('viable_recall_probe')} filtered_count={row.get('filtered_candidate_entry_count')}"
        )
        lines.append(f"  focus_filtered_tickers: {row.get('focus_filtered_tickers')}")
        lines.append(f"  preserve_filtered_tickers: {row.get('preserve_filtered_tickers')}")
        lines.append(f"  comparison_note: {row.get('comparison_note')}")
    if not list(analysis.get("priority_replay_rows") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Hotspot Replays")
    for row in list(analysis.get("hotspot_replay_rows") or []):
        lines.append(
            f"- rank={row.get('priority_rank')} report_dir={row.get('report_dir')} focus_tickers={row.get('focus_tickers')} status={row.get('candidate_entry_status')} best_variant={row.get('best_variant_name')} viable_recall_probe={row.get('viable_recall_probe')} filtered_count={row.get('filtered_candidate_entry_count')}"
        )
        lines.append(f"  focus_filtered_tickers: {row.get('focus_filtered_tickers')}")
        lines.append(f"  preserve_filtered_tickers: {row.get('preserve_filtered_tickers')}")
        lines.append(f"  comparison_note: {row.get('comparison_note')}")
    if not list(analysis.get("hotspot_replay_rows") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Global Window Scan")
    for key, value in dict(analysis.get("global_window_scan") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Guardrails")
    for item in list(analysis.get("keep_guardrails") or []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Next Actions")
    for item in list(analysis.get("next_actions") or []):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a replay bundle for the BTST no-candidate-entry backlog.")
    parser.add_argument("--action-board", default=str(DEFAULT_ACTION_BOARD_PATH))
    parser.add_argument("--priority-replay-limit", type=int, default=DEFAULT_PRIORITY_REPLAY_LIMIT)
    parser.add_argument("--hotspot-replay-limit", type=int, default=DEFAULT_HOTSPOT_REPLAY_LIMIT)
    parser.add_argument("--global-scan-focus-limit", type=int, default=DEFAULT_GLOBAL_SCAN_FOCUS_LIMIT)
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_no_candidate_entry_replay_bundle(
        args.action_board,
        priority_replay_limit=args.priority_replay_limit,
        hotspot_replay_limit=args.hotspot_replay_limit,
        global_scan_focus_limit=args.global_scan_focus_limit,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_no_candidate_entry_replay_bundle_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()