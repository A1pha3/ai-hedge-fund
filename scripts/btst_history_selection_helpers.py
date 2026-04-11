from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


LooksLikeReportDir = Callable[[Path], bool]
SafeLoadJson = Callable[[str | Path | None], dict[str, Any]]
NormalizeTradeDate = Callable[[Any], str | None]
ExtractCatalystThemeFrontierSummary = Callable[[dict[str, Any]], dict[str, Any]]


def extract_btst_report_candidate(
    report_dir: Path,
    *,
    looks_like_report_dir: LooksLikeReportDir,
    safe_load_json: SafeLoadJson,
    normalize_trade_date: NormalizeTradeDate,
) -> dict[str, Any] | None:
    if not looks_like_report_dir(report_dir):
        return None
    session_summary = safe_load_json(report_dir / "session_summary.json")
    if not session_summary:
        return None
    followup = dict(session_summary.get("btst_followup") or {})
    artifacts = dict(session_summary.get("artifacts") or {})
    priority_board_json_path = followup.get("priority_board_json") or artifacts.get("btst_next_day_priority_board_json")
    brief_json_path = followup.get("brief_json") or artifacts.get("btst_next_day_trade_brief_json")
    catalyst_theme_frontier_json_path = followup.get("catalyst_theme_frontier_json") or artifacts.get("btst_catalyst_theme_frontier_json")
    catalyst_theme_frontier_markdown_path = followup.get("catalyst_theme_frontier_markdown") or artifacts.get("btst_catalyst_theme_frontier_markdown")
    if not priority_board_json_path:
        return None

    plan_generation = dict(session_summary.get("plan_generation") or {})
    selection_target = str(plan_generation.get("selection_target") or session_summary.get("selection_target") or "") or None
    trade_date = normalize_trade_date(followup.get("trade_date") or session_summary.get("end_date"))
    next_trade_date = normalize_trade_date(followup.get("next_trade_date"))
    return {
        "report_dir": str(report_dir.resolve()),
        "report_dir_name": report_dir.name,
        "selection_target": selection_target,
        "trade_date": trade_date,
        "next_trade_date": next_trade_date,
        "priority_board_json_path": str(Path(priority_board_json_path).expanduser().resolve()),
        "brief_json_path": str(Path(brief_json_path).expanduser().resolve()) if brief_json_path else None,
        "catalyst_theme_frontier_json_path": str(Path(catalyst_theme_frontier_json_path).expanduser().resolve()) if catalyst_theme_frontier_json_path else None,
        "catalyst_theme_frontier_markdown_path": str(Path(catalyst_theme_frontier_markdown_path).expanduser().resolve()) if catalyst_theme_frontier_markdown_path else None,
        "rank": (trade_date or "", report_dir.stat().st_mtime_ns, report_dir.name),
    }


def select_previous_btst_report_snapshot(
    reports_root: str | Path,
    *,
    current_report_dir: str | None,
    selection_target: str | None,
    extract_btst_report_candidate: Callable[[Path], dict[str, Any] | None],
    safe_load_json: SafeLoadJson,
    extract_catalyst_theme_frontier_summary: ExtractCatalystThemeFrontierSummary,
) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    candidates = [
        candidate
        for candidate in (extract_btst_report_candidate(path) for path in resolved_reports_root.iterdir())
        if candidate and candidate.get("report_dir") != current_report_dir
    ]
    if selection_target:
        scoped_candidates = [candidate for candidate in candidates if candidate.get("selection_target") == selection_target]
        if scoped_candidates:
            candidates = scoped_candidates
    if not candidates:
        return {}

    selected_candidate = max(candidates, key=lambda candidate: candidate["rank"])
    priority_board = safe_load_json(selected_candidate.get("priority_board_json_path"))
    brief = safe_load_json(selected_candidate.get("brief_json_path"))
    catalyst_theme_frontier = safe_load_json(selected_candidate.get("catalyst_theme_frontier_json_path"))
    return {
        "reference_kind": "previous_btst_report",
        "report_dir": selected_candidate.get("report_dir_name"),
        "report_dir_abs": selected_candidate.get("report_dir"),
        "selection_target": selected_candidate.get("selection_target"),
        "trade_date": selected_candidate.get("trade_date"),
        "next_trade_date": selected_candidate.get("next_trade_date"),
        "priority_board": priority_board,
        "brief_summary": dict(brief.get("summary") or {}),
        "priority_board_json_path": selected_candidate.get("priority_board_json_path"),
        "catalyst_theme_frontier_summary": extract_catalyst_theme_frontier_summary(catalyst_theme_frontier),
        "catalyst_theme_frontier_json_path": selected_candidate.get("catalyst_theme_frontier_json_path"),
        "catalyst_theme_frontier_markdown_path": selected_candidate.get("catalyst_theme_frontier_markdown_path"),
    }
