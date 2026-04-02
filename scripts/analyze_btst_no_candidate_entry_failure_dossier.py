from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.replay_selection_target_calibration import _iter_replay_input_sources


REPORTS_DIR = Path("data/reports")
DEFAULT_TRADEABLE_OPPORTUNITY_POOL_PATH = REPORTS_DIR / "btst_tradeable_opportunity_pool_march.json"
DEFAULT_ACTION_BOARD_PATH = REPORTS_DIR / "btst_no_candidate_entry_action_board_latest.json"
DEFAULT_REPLAY_BUNDLE_PATH = REPORTS_DIR / "btst_no_candidate_entry_replay_bundle_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_no_candidate_entry_failure_dossier_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_no_candidate_entry_failure_dossier_latest.md"
DEFAULT_PRIORITY_LIMIT = 5
DEFAULT_HOTSPOT_LIMIT = 3
PROMISING_RECALL_STATUSES = {
    "filters_focus_and_weaker_than_false_negative_pool",
}
HANDOFF_STAGE_ORDER = [
    "missing_replay_input_artifacts",
    "absent_from_watchlist",
    "watchlist_visible_but_not_candidate_entry",
    "candidate_entry_visible_but_not_selection_target",
    "selection_target_visible_without_candidate_entry",
    "candidate_entry_visible_and_selection_target_attached",
    "buy_order_visible",
]


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _safe_load_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return {}
    return json.loads(resolved.read_text(encoding="utf-8"))


def _unique_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        token = str(value or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return ordered


def _build_priority_rows(action_board: dict[str, Any], tradeable_pool: dict[str, Any], *, priority_limit: int) -> list[dict[str, Any]]:
    priority_queue = [dict(row) for row in list(action_board.get("priority_queue") or []) if str(row.get("ticker") or "").strip()]
    if priority_queue:
        return priority_queue[:priority_limit]

    top_rows = [dict(row) for row in list(dict(tradeable_pool.get("no_candidate_entry_summary") or {}).get("top_ticker_rows") or []) if str(row.get("ticker") or "").strip()]
    for index, row in enumerate(top_rows, start=1):
        row.setdefault("priority_rank", index)
        row.setdefault("primary_report_dir", None)
    return top_rows[:priority_limit]


def _build_hotspot_rows(action_board: dict[str, Any], *, hotspot_limit: int) -> list[dict[str, Any]]:
    return [dict(row) for row in list(action_board.get("window_hotspot_rows") or [])][:hotspot_limit]


def _collect_no_candidate_rows(tradeable_pool: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in list(tradeable_pool.get("rows") or [])
        if str(row.get("first_kill_switch") or "") == "no_candidate_entry"
    ]


def _report_dir_path(reports_root: Path, report_dir_name: str | None) -> Path | None:
    token = str(report_dir_name or "").strip()
    if not token:
        return None
    candidate = Path(token).expanduser()
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (reports_root / token).expanduser().resolve()
    return resolved


def _load_report_context(
    reports_root: Path,
    report_dir_name: str | None,
    *,
    report_cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    key = str(report_dir_name or "").strip() or "__missing__"
    cached = report_cache.get(key)
    if cached is not None:
        return cached

    report_path = _report_dir_path(reports_root, report_dir_name)
    if report_path is None or not report_path.exists():
        context = {
            "report_dir": str(report_dir_name or "").strip() or None,
            "report_dir_exists": False,
            "report_dir_abs": report_path.as_posix() if report_path is not None else None,
            "replay_inputs": [],
        }
        report_cache[key] = context
        return context

    replay_inputs: list[tuple[str, dict[str, Any]]] = []
    try:
        replay_input_sources = _iter_replay_input_sources(report_path)
        replay_inputs = [
            (path.relative_to(report_path).as_posix(), payload)
            for path, payload in replay_input_sources
        ]
    except Exception:
        replay_inputs = []

    context = {
        "report_dir": report_path.name,
        "report_dir_exists": True,
        "report_dir_abs": report_path.as_posix(),
        "replay_inputs": replay_inputs,
    }
    report_cache[key] = context
    return context


def _matching_entries(entries: list[dict[str, Any]], ticker: str) -> list[dict[str, Any]]:
    normalized_ticker = str(ticker).strip()
    return [dict(entry) for entry in list(entries or []) if str(dict(entry).get("ticker") or "").strip() == normalized_ticker]


def _collect_source_presence(payload: dict[str, Any], ticker: str) -> tuple[Counter[str], list[str], list[str]]:
    source_counts: Counter[str] = Counter()
    candidate_sources: list[str] = []
    selection_target_decisions: list[str] = []

    watchlist_matches = _matching_entries(list(payload.get("watchlist") or []), ticker)
    if watchlist_matches:
        source_counts["watchlist"] += len(watchlist_matches)

    rejected_matches = _matching_entries(list(payload.get("rejected_entries") or []), ticker)
    if rejected_matches:
        source_counts["rejected_entries"] += len(rejected_matches)
        candidate_sources.extend(
            str(match.get("candidate_source") or match.get("source") or "watchlist_filter_diagnostics")
            for match in rejected_matches
        )

    supplemental_matches = _matching_entries(list(payload.get("supplemental_short_trade_entries") or []), ticker)
    if supplemental_matches:
        source_counts["supplemental_short_trade_entries"] += len(supplemental_matches)
        candidate_sources.extend(
            str(match.get("candidate_source") or match.get("source") or "layer_b_boundary")
            for match in supplemental_matches
        )

    selection_targets = dict(payload.get("selection_targets") or {})
    selection_target = dict(selection_targets.get(str(ticker).strip()) or {})
    if selection_target:
        source_counts["selection_targets"] += 1
        decision = str(dict(selection_target.get("short_trade") or {}).get("decision") or "").strip()
        if decision:
            selection_target_decisions.append(decision)

    buy_order_tickers = {str(value or "").strip() for value in list(payload.get("buy_order_tickers") or []) if str(value or "").strip()}
    if str(ticker).strip() in buy_order_tickers:
        source_counts["buy_order_tickers"] += 1

    return source_counts, _unique_strings(candidate_sources), _unique_strings(selection_target_decisions)


def _classify_handoff_stage(
    *,
    replay_input_count: int,
    watchlist_visible: bool,
    candidate_entry_visible: bool,
    selection_target_visible: bool,
    buy_order_visible: bool,
) -> str:
    if replay_input_count <= 0:
        return "missing_replay_input_artifacts"
    if buy_order_visible:
        return "buy_order_visible"
    if selection_target_visible and candidate_entry_visible:
        return "candidate_entry_visible_and_selection_target_attached"
    if selection_target_visible:
        return "selection_target_visible_without_candidate_entry"
    if candidate_entry_visible:
        return "candidate_entry_visible_but_not_selection_target"
    if watchlist_visible:
        return "watchlist_visible_but_not_candidate_entry"
    return "absent_from_watchlist"


def _count_handoff_stages(rows: list[dict[str, Any]], key: str = "handoff_stage") -> dict[str, int]:
    counts = Counter(str(row.get(key) or "unknown") for row in rows if str(row.get(key) or "").strip())
    ordered: dict[str, int] = {}
    for stage in HANDOFF_STAGE_ORDER:
        if counts.get(stage):
            ordered[stage] = int(counts[stage])
    for stage, count in counts.most_common():
        if stage not in ordered:
            ordered[stage] = int(count)
    return ordered


def _dominant_handoff_stage(stage_counts: dict[str, int]) -> str | None:
    if not stage_counts:
        return None
    for stage in HANDOFF_STAGE_ORDER:
        if int(stage_counts.get(stage) or 0) > 0:
            return stage
    return next(iter(stage_counts.keys()), None)


def _build_handoff_action(stage: str, *, subject: str) -> tuple[str, str, str]:
    if stage == "missing_replay_input_artifacts":
        return (
            "p0_artifact_gap",
            f"补齐 {subject} 的 selection_artifacts / replay input 产物，避免 no-entry 诊断停在观测缺口。",
            f"先补 {subject} 的 report_dir、selection_snapshot.json 或 selection_target_replay_input.json，再继续 handoff 分析。",
        )
    if stage == "absent_from_watchlist":
        return (
            "p0_upstream_recall",
            f"回查 {subject} 为什么连 watchlist 都没有进入，优先定位 candidate pool -> watchlist 的召回缺口。",
            f"先审 {subject} 的 truth pool / watchlist recall 召回链路，而不是继续 candidate-entry frontier 调参。",
        )
    if stage == "watchlist_visible_but_not_candidate_entry":
        return (
            "p1_watchlist_handoff",
            f"回查 {subject} 在 watchlist 后为何没有进入 rejected_entries / supplemental_short_trade_entries。",
            f"优先核对 {subject} 的 watchlist_filter_diagnostics 与 short-trade candidate handoff。",
        )
    if stage == "candidate_entry_visible_but_not_selection_target":
        return (
            "p2_target_attachment",
            f"回查 {subject} 已进入 candidate-entry 源却没有挂到 selection_targets 的目标附着缺口。",
            f"优先检查 build_selection_targets 与 selection_target contract 是否漏挂 {subject}。",
        )
    if stage == "selection_target_visible_without_candidate_entry":
        return (
            "p2_target_contract",
            f"回查 {subject} 的 selection_target contract，确认为什么 selection_targets 可见但 candidate-entry 源不可见。",
            f"优先核对 {subject} 的 replay input schema / snapshot fallback 是否造成来源断层。",
        )
    if stage == "candidate_entry_visible_and_selection_target_attached":
        return (
            "p3_semantic_replay",
            f"{subject} 已进入 candidate-entry 且挂上 selection_targets，下一步进入 semantic replay 解释层。",
            f"继续用 selective frontier / filter observability 解释 {subject} 为什么仍没有形成 recall probe。",
        )
    return (
        "p4_execution_followup",
        f"{subject} 已进入 buy-order 可视层，这不再是 no-entry 主矛盾。",
        f"把 {subject} 转回执行或 post-entry 诊断，不再停留在 no-entry backlog。",
    )


def _build_priority_handoff_action_queue(priority_ticker_dossiers: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    for row in priority_ticker_dossiers:
        ticker = str(row.get("ticker") or "").strip()
        handoff_stage = str(row.get("handoff_stage") or "").strip()
        if not ticker or not handoff_stage:
            continue
        action_tier, title, next_step = _build_handoff_action(handoff_stage, subject=ticker)
        queue.append(
            {
                "task_id": f"{ticker}_{handoff_stage}",
                "priority_rank": row.get("priority_rank"),
                "ticker": ticker,
                "primary_report_dir": row.get("primary_report_dir"),
                "primary_failure_class": row.get("primary_failure_class"),
                "handoff_stage": handoff_stage,
                "action_tier": action_tier,
                "title": title,
                "why_now": row.get("failure_reason"),
                "next_step": next_step,
                "source_presence_counts": dict(row.get("source_presence_counts") or {}),
            }
        )
    return queue[:limit]


def _build_hotspot_handoff_action_queue(hotspot_report_dossiers: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    for row in hotspot_report_dossiers:
        report_dir = str(row.get("report_dir") or "").strip()
        handoff_stage = str(row.get("dominant_handoff_stage") or "").strip()
        if not report_dir or not handoff_stage:
            continue
        action_tier, title, next_step = _build_handoff_action(handoff_stage, subject=report_dir)
        queue.append(
            {
                "task_id": f"{report_dir}_{handoff_stage}",
                "priority_rank": row.get("priority_rank"),
                "report_dir": report_dir,
                "primary_failure_class": row.get("primary_failure_class"),
                "handoff_stage": handoff_stage,
                "action_tier": action_tier,
                "title": title,
                "why_now": row.get("failure_reason"),
                "next_step": next_step,
                "focus_tickers": list(row.get("focus_tickers") or []),
                "focus_ticker_handoff_stage_counts": dict(row.get("focus_ticker_handoff_stage_counts") or {}),
            }
        )
    return queue[:limit]


def _inspect_report_dir_for_ticker(
    reports_root: Path,
    report_dir_name: str | None,
    *,
    ticker: str,
    report_cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    context = _load_report_context(reports_root, report_dir_name, report_cache=report_cache)
    replay_inputs = list(context.get("replay_inputs") or [])
    if not context.get("report_dir_exists"):
        return {
            "report_dir": context.get("report_dir"),
            "report_dir_exists": False,
            "replay_input_count": 0,
            "replay_input_labels": [],
            "trade_dates": [],
            "ticker_present": False,
            "candidate_entry_visible": False,
            "selection_target_visible": False,
            "source_presence_counts": {},
            "candidate_sources": [],
            "selection_target_decisions": [],
            "presence_class": "missing_report_dir",
        }

    if not replay_inputs:
        return {
            "report_dir": context.get("report_dir"),
            "report_dir_exists": True,
            "replay_input_count": 0,
            "replay_input_labels": [],
            "trade_dates": [],
            "ticker_present": False,
            "candidate_entry_visible": False,
            "selection_target_visible": False,
            "source_presence_counts": {},
            "candidate_sources": [],
            "selection_target_decisions": [],
            "presence_class": "missing_replay_inputs",
        }

    aggregated_source_counts: Counter[str] = Counter()
    candidate_sources: list[str] = []
    selection_target_decisions: list[str] = []
    trade_dates: list[str] = []
    replay_input_labels: list[str] = []
    for replay_input_label, payload in replay_inputs:
        replay_input_labels.append(replay_input_label)
        trade_dates.append(str(payload.get("trade_date") or "").strip())
        source_counts, matched_candidate_sources, matched_selection_target_decisions = _collect_source_presence(payload, ticker)
        aggregated_source_counts.update(source_counts)
        candidate_sources.extend(matched_candidate_sources)
        selection_target_decisions.extend(matched_selection_target_decisions)

    ticker_present = sum(aggregated_source_counts.values()) > 0
    candidate_entry_visible = bool(aggregated_source_counts.get("rejected_entries") or aggregated_source_counts.get("supplemental_short_trade_entries"))
    selection_target_visible = bool(aggregated_source_counts.get("selection_targets"))
    watchlist_visible = bool(aggregated_source_counts.get("watchlist"))
    buy_order_visible = bool(aggregated_source_counts.get("buy_order_tickers"))
    if not ticker_present:
        presence_class = "absent_from_replay_inputs"
    elif candidate_entry_visible:
        presence_class = "candidate_entry_visible"
    else:
        presence_class = "present_but_outside_candidate_entry_universe"
    handoff_stage = _classify_handoff_stage(
        replay_input_count=len(replay_inputs),
        watchlist_visible=watchlist_visible,
        candidate_entry_visible=candidate_entry_visible,
        selection_target_visible=selection_target_visible,
        buy_order_visible=buy_order_visible,
    )

    return {
        "report_dir": context.get("report_dir"),
        "report_dir_exists": True,
        "replay_input_count": len(replay_inputs),
        "replay_input_labels": replay_input_labels[:5],
        "trade_dates": _unique_strings(trade_dates),
        "ticker_present": ticker_present,
        "watchlist_visible": watchlist_visible,
        "candidate_entry_visible": candidate_entry_visible,
        "selection_target_visible": selection_target_visible,
        "buy_order_visible": buy_order_visible,
        "source_presence_counts": dict(aggregated_source_counts),
        "candidate_sources": _unique_strings(candidate_sources),
        "selection_target_decisions": _unique_strings(selection_target_decisions),
        "presence_class": presence_class,
        "handoff_stage": handoff_stage,
    }


def _ranked_report_dirs(priority_row: dict[str, Any], ticker_rows: list[dict[str, Any]]) -> list[str]:
    report_dir_counts = Counter(
        str(row.get("report_dir") or "").strip()
        for row in ticker_rows
        if str(row.get("report_dir") or "").strip()
    )
    prioritized: list[str] = []
    primary_report_dir = str(priority_row.get("primary_report_dir") or "").strip()
    if primary_report_dir:
        prioritized.append(primary_report_dir)
    for report_dir, _ in report_dir_counts.most_common():
        if report_dir not in prioritized:
            prioritized.append(report_dir)
    return prioritized


def _classify_priority_failure(
    *,
    ticker: str,
    frontier_row: dict[str, Any],
    report_dir_evidence: list[dict[str, Any]],
    replay_input_report_count: int,
    replay_input_visible_report_count: int,
    candidate_entry_visible_report_count: int,
) -> tuple[str, str, str]:
    frontier_status = str(frontier_row.get("candidate_entry_status") or "")
    preserve_filtered_tickers = [str(value) for value in list(frontier_row.get("preserve_filtered_tickers") or []) if str(value or "").strip()]
    if frontier_row.get("viable_recall_probe") or frontier_status in PROMISING_RECALL_STATUSES:
        return (
            "preserve_safe_recall_probe",
            f"{ticker} 已在 frontier replay 中形成 preserve-safe recall probe，不再属于 failure backlog。",
            f"把 {ticker} 从 no-entry failure backlog 转回 shadow governance，继续核对 preserve_ticker 0 误伤。",
        )
    if preserve_filtered_tickers:
        return (
            "preserve_guardrail_misfire",
            f"{ticker} 虽然触发了 recall 方向，但同时误伤了 preserve_tickers={preserve_filtered_tickers}。",
            f"继续回放 {ticker}，但优先修正 preserve guardrail，再讨论 recall probe。",
        )
    if replay_input_report_count == 0 or all(str(row.get("presence_class") or "") in {"missing_report_dir", "missing_replay_inputs"} for row in report_dir_evidence):
        return (
            "missing_replay_input_artifacts",
            f"{ticker} 对应的重点 report_dir 缺少可用 replay input / selection_artifacts，当前先是观测缺口。",
            f"先补齐 {ticker} 的 report_dir/selection_artifacts，再决定是否继续 candidate-entry frontier。",
        )
    if replay_input_visible_report_count == 0:
        return (
            "upstream_absent_from_replay_inputs",
            f"{ticker} 在已存在的 replay input 中完全缺席，说明问题主要发生在 candidate-entry 之前的上游召回层。",
            f"先追查 {ticker} 为什么没有进入 replay input / selection_artifacts，而不是继续弱结构规则调参。",
        )
    if candidate_entry_visible_report_count == 0:
        return (
            "present_but_outside_candidate_entry_universe",
            f"{ticker} 在 replay input 中可见，但没有进入 rejected_entries / supplemental_short_trade_entries 这类 candidate-entry 候选源。",
            f"优先回查 {ticker} 在 watchlist 到 candidate-entry 之间的上游分流，而不是直接做 frontier semantic replay。",
        )
    if frontier_status == "misses_focus_tickers":
        return (
            "candidate_entry_semantic_miss",
            f"{ticker} 已进入 candidate-entry 候选源，但当前 frontier 变体没有 selective 命中 focus_ticker。",
            f"继续把 {ticker} 留在 candidate-entry semantic frontier，检查弱结构语义为何没有命中 focus。",
        )
    if frontier_status == "no_candidate_entries_filtered":
        return (
            "candidate_entry_filter_nonfiring",
            f"{ticker} 已进入 candidate-entry 候选源，但当前 frontier 变体没有过滤出任何 candidate-entry 样本。",
            f"对 {ticker} 重查 candidate-entry filter observability，确认是规则前提不满足还是指标阈值完全未触发。",
        )
    if frontier_status in {"filters_weaker_than_false_negative_pool", "filtered_pool_too_strong", "filters_focus_but_filtered_pool_too_strong"}:
        return (
            "recall_probe_quality_too_strong",
            f"{ticker} 的 recall 方向已经有过滤动作，但 filtered pool 质量仍不足以构成 preserve-safe recall probe。",
            f"继续把 {ticker} 留在 quality frontier，比起补上游观测，更应检查 recall cohort 质量是否过强。",
        )
    return (
        "mixed_recall_gap",
        f"{ticker} 的 no-entry failure 证据混合，既不是纯 upstream absence，也没有形成可直接推广的 recall probe。",
        f"把 {ticker} 保留在 mixed backlog，先补更多窗口证据再做细分。",
    )


def _classify_hotspot_failure(
    *,
    report_dir: str,
    focus_ticker_evidence: list[dict[str, Any]],
    hotspot_frontier_row: dict[str, Any],
) -> tuple[str, str, str]:
    frontier_status = str(hotspot_frontier_row.get("candidate_entry_status") or "")
    if hotspot_frontier_row.get("viable_recall_probe") or frontier_status in PROMISING_RECALL_STATUSES:
        return (
            "hotspot_viable_recall_probe",
            f"{report_dir} 已形成窗口级 preserve-safe recall probe。",
            f"把 {report_dir} 作为热点窗口回接 shadow governance，而不是继续停留在 failure dossier。",
        )

    replay_input_ready = any(int(row.get("replay_input_count") or 0) > 0 for row in focus_ticker_evidence)
    replay_input_visible = [row for row in focus_ticker_evidence if row.get("ticker_present")]
    candidate_entry_visible = [row for row in focus_ticker_evidence if row.get("candidate_entry_visible")]
    if not replay_input_ready:
        return (
            "hotspot_missing_replay_inputs",
            f"{report_dir} 作为热点窗口缺少可用 replay input / selection_artifacts。",
            f"先补齐 {report_dir} 的 replay input，再判断热点窗口到底是 absence 还是 semantic miss。",
        )
    if not replay_input_visible:
        return (
            "hotspot_upstream_absence",
            f"{report_dir} 的热点 focus_tickers 在 replay input 中整体缺席，当前更像上游 absence，而不是 frontier semantic miss。",
            f"优先排查 {report_dir} 的 focus_tickers 为什么没进入 replay input。",
        )
    if not candidate_entry_visible:
        return (
            "hotspot_focus_outside_candidate_entry_universe",
            f"{report_dir} 的热点 focus_tickers 虽然出现在 replay input，但没有进入 candidate-entry 候选源。",
            f"优先回查 {report_dir} 的 watchlist 到 candidate-entry handoff，而不是继续 frontier 调参。",
        )
    if frontier_status == "misses_focus_tickers":
        return (
            "hotspot_candidate_entry_semantic_miss",
            f"{report_dir} 的热点窗口已经进入 candidate-entry 候选源，但 frontier 依旧 miss 掉 focus_tickers。",
            f"把 {report_dir} 继续留在热点 semantic replay，重点解释 focus miss。",
        )
    if frontier_status == "no_candidate_entries_filtered":
        return (
            "hotspot_candidate_entry_filter_nonfiring",
            f"{report_dir} 的热点窗口存在 candidate-entry 候选源，但 frontier 没有过滤出任何 candidate-entry 样本。",
            f"检查 {report_dir} 的 candidate-entry filter observability，确认前提与阈值为何完全未触发。",
        )
    return (
        "hotspot_mixed_recall_gap",
        f"{report_dir} 的热点窗口证据混合，暂时不能简化成纯 absence 或纯 semantic miss。",
        f"把 {report_dir} 继续保留在 mixed hotspot backlog，等待更多窗口证据。",
    )


def _build_priority_ticker_dossiers(
    priority_rows: list[dict[str, Any]],
    no_candidate_rows: list[dict[str, Any]],
    *,
    reports_root: Path,
    replay_bundle: dict[str, Any],
    report_cache: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    replay_rows_by_ticker = {
        str(row.get("ticker") or "").strip(): dict(row)
        for row in list(replay_bundle.get("priority_replay_rows") or [])
        if str(row.get("ticker") or "").strip()
    }
    dossiers: list[dict[str, Any]] = []
    for priority_row in priority_rows:
        ticker = str(priority_row.get("ticker") or "").strip()
        if not ticker:
            continue
        ticker_rows = [row for row in no_candidate_rows if str(row.get("ticker") or "").strip() == ticker]
        report_dir_counts = Counter(
            str(row.get("report_dir") or "").strip()
            for row in ticker_rows
            if str(row.get("report_dir") or "").strip()
        )
        report_dir_evidence = [
            _inspect_report_dir_for_ticker(
                reports_root,
                report_dir_name,
                ticker=ticker,
                report_cache=report_cache,
            )
            for report_dir_name in _ranked_report_dirs(priority_row, ticker_rows)
        ]
        source_presence_counts: Counter[str] = Counter()
        candidate_sources: list[str] = []
        selection_target_decisions: list[str] = []
        for evidence_row in report_dir_evidence:
            source_presence_counts.update(dict(evidence_row.get("source_presence_counts") or {}))
            candidate_sources.extend(list(evidence_row.get("candidate_sources") or []))
            selection_target_decisions.extend(list(evidence_row.get("selection_target_decisions") or []))

        replay_input_report_count = sum(1 for row in report_dir_evidence if int(row.get("replay_input_count") or 0) > 0)
        replay_input_visible_report_count = sum(1 for row in report_dir_evidence if bool(row.get("ticker_present")))
        watchlist_visible_report_count = sum(1 for row in report_dir_evidence if bool(row.get("watchlist_visible")))
        candidate_entry_visible_report_count = sum(1 for row in report_dir_evidence if bool(row.get("candidate_entry_visible")))
        selection_target_visible_report_count = sum(1 for row in report_dir_evidence if bool(row.get("selection_target_visible")))
        buy_order_visible_report_count = sum(1 for row in report_dir_evidence if bool(row.get("buy_order_visible")))
        frontier_row = dict(replay_rows_by_ticker.get(ticker) or {})
        primary_failure_class, failure_reason, next_step = _classify_priority_failure(
            ticker=ticker,
            frontier_row=frontier_row,
            report_dir_evidence=report_dir_evidence,
            replay_input_report_count=replay_input_report_count,
            replay_input_visible_report_count=replay_input_visible_report_count,
            candidate_entry_visible_report_count=candidate_entry_visible_report_count,
        )
        handoff_stage = _classify_handoff_stage(
            replay_input_count=replay_input_report_count,
            watchlist_visible=watchlist_visible_report_count > 0,
            candidate_entry_visible=candidate_entry_visible_report_count > 0,
            selection_target_visible=selection_target_visible_report_count > 0,
            buy_order_visible=buy_order_visible_report_count > 0,
        )

        dossiers.append(
            {
                "priority_rank": priority_row.get("priority_rank"),
                "ticker": ticker,
                "occurrence_count": int(priority_row.get("occurrence_count") or len(ticker_rows)),
                "strict_goal_case_count": int(priority_row.get("strict_goal_case_count") or sum(1 for row in ticker_rows if row.get("strict_btst_goal_case"))),
                "distinct_report_count": int(priority_row.get("distinct_report_count") or len(report_dir_counts)),
                "primary_report_dir": priority_row.get("primary_report_dir"),
                "report_dir_counts": {key: int(value) for key, value in report_dir_counts.most_common()},
                "replay_input_report_count": replay_input_report_count,
                "replay_input_visible_report_count": replay_input_visible_report_count,
                "watchlist_visible_report_count": watchlist_visible_report_count,
                "candidate_entry_visible_report_count": candidate_entry_visible_report_count,
                "selection_target_visible_report_count": selection_target_visible_report_count,
                "buy_order_visible_report_count": buy_order_visible_report_count,
                "source_presence_counts": dict(source_presence_counts),
                "candidate_sources": _unique_strings(candidate_sources),
                "selection_target_decisions": _unique_strings(selection_target_decisions),
                "frontier_status": frontier_row.get("candidate_entry_status"),
                "frontier_best_variant": frontier_row.get("best_variant_name"),
                "frontier_viable_recall_probe": bool(frontier_row.get("viable_recall_probe")),
                "frontier_comparison_note": frontier_row.get("comparison_note"),
                "primary_failure_class": primary_failure_class,
                "handoff_stage": handoff_stage,
                "failure_reason": failure_reason,
                "next_step": next_step,
                "report_dir_evidence": report_dir_evidence,
            }
        )
    return dossiers


def _build_hotspot_report_dossiers(
    hotspot_rows: list[dict[str, Any]],
    *,
    reports_root: Path,
    replay_bundle: dict[str, Any],
    report_cache: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    replay_rows_by_report_dir = {
        str(row.get("report_dir") or "").strip(): dict(row)
        for row in list(replay_bundle.get("hotspot_replay_rows") or [])
        if str(row.get("report_dir") or "").strip()
    }
    dossiers: list[dict[str, Any]] = []
    for hotspot_row in hotspot_rows:
        report_dir = str(hotspot_row.get("report_dir") or "").strip()
        focus_tickers = [str(value) for value in list(hotspot_row.get("top_focus_tickers") or hotspot_row.get("focus_tickers") or []) if str(value or "").strip()]
        if not report_dir:
            continue
        focus_ticker_evidence = [
            {
                "ticker": ticker,
                **_inspect_report_dir_for_ticker(
                    reports_root,
                    report_dir,
                    ticker=ticker,
                    report_cache=report_cache,
                ),
            }
            for ticker in focus_tickers
        ]
        frontier_row = dict(replay_rows_by_report_dir.get(report_dir) or {})
        primary_failure_class, failure_reason, next_step = _classify_hotspot_failure(
            report_dir=report_dir,
            focus_ticker_evidence=focus_ticker_evidence,
            hotspot_frontier_row=frontier_row,
        )
        focus_ticker_handoff_stage_counts = _count_handoff_stages(focus_ticker_evidence)
        dossiers.append(
            {
                "priority_rank": hotspot_row.get("priority_rank"),
                "report_dir": report_dir,
                "focus_tickers": focus_tickers,
                "frontier_status": frontier_row.get("candidate_entry_status"),
                "frontier_best_variant": frontier_row.get("best_variant_name"),
                "frontier_viable_recall_probe": bool(frontier_row.get("viable_recall_probe")),
                "frontier_comparison_note": frontier_row.get("comparison_note"),
                "primary_failure_class": primary_failure_class,
                "focus_ticker_handoff_stage_counts": focus_ticker_handoff_stage_counts,
                "dominant_handoff_stage": _dominant_handoff_stage(focus_ticker_handoff_stage_counts),
                "failure_reason": failure_reason,
                "next_step": next_step,
                "focus_ticker_evidence": focus_ticker_evidence,
            }
        )
    return dossiers


def _top_tickers_by_failure(priority_ticker_dossiers: list[dict[str, Any]], failure_class: str) -> list[str]:
    return [
        str(row.get("ticker") or "")
        for row in priority_ticker_dossiers
        if str(row.get("primary_failure_class") or "") == failure_class and str(row.get("ticker") or "").strip()
    ][:3]


def _top_report_dirs_by_failure(hotspot_report_dossiers: list[dict[str, Any]], failure_class: str) -> list[str]:
    return [
        str(row.get("report_dir") or "")
        for row in hotspot_report_dossiers
        if str(row.get("primary_failure_class") or "") == failure_class and str(row.get("report_dir") or "").strip()
    ][:3]


def _top_tickers_by_handoff_stage(priority_ticker_dossiers: list[dict[str, Any]], handoff_stage: str) -> list[str]:
    return [
        str(row.get("ticker") or "")
        for row in priority_ticker_dossiers
        if str(row.get("handoff_stage") or "") == handoff_stage and str(row.get("ticker") or "").strip()
    ][:3]


def _build_recommendation(
    *,
    priority_failure_class_counts: Counter[str],
    top_upstream_absence_tickers: list[str],
    top_absent_from_watchlist_tickers: list[str],
    top_watchlist_handoff_gap_tickers: list[str],
    top_candidate_entry_to_target_gap_tickers: list[str],
    top_outside_candidate_entry_tickers: list[str],
    top_semantic_miss_tickers: list[str],
    promising_priority_tickers: list[str],
) -> str:
    if top_upstream_absence_tickers:
        if top_absent_from_watchlist_tickers:
            return (
                f"当前 top no-entry backlog 的主矛盾是上游 absence，而且具体断点先落在 watchlist 之前：{top_absent_from_watchlist_tickers} 连 watchlist 都没有进入。"
                "下一步应先补 candidate pool -> watchlist 的召回观测，而不是继续 candidate-entry semantic 调参。"
            )
        return (
            f"当前 top no-entry backlog 的主矛盾是上游 absence：{top_upstream_absence_tickers} 在 replay input / candidate-entry source 中没有被看见。"
            "下一步应先补 observability 与上游 handoff，而不是继续 candidate-entry semantic 调参。"
        )
    if top_watchlist_handoff_gap_tickers:
        return (
            f"当前 top no-entry backlog 的主矛盾已经收敛到 watchlist handoff gap：{top_watchlist_handoff_gap_tickers} 已进入 watchlist，"
            "但没有进入 candidate-entry 候选源。下一步应优先回查 watchlist filter diagnostics 与 short-trade candidate handoff。"
        )
    if top_candidate_entry_to_target_gap_tickers:
        return (
            f"当前 top no-entry backlog 的主矛盾已经收敛到 candidate-entry -> selection_target gap：{top_candidate_entry_to_target_gap_tickers} 已进入候选源，"
            "但没有挂上 selection_targets。下一步应优先检查 target attachment contract。"
        )
    if top_outside_candidate_entry_tickers:
        return (
            f"当前 top no-entry backlog 的主矛盾是 handoff gap：{top_outside_candidate_entry_tickers} 已出现在 replay input，"
            "但没有进入 candidate-entry 候选源。下一步应先补 watchlist 到 candidate-entry 的交接解释。"
        )
    if top_semantic_miss_tickers:
        return (
            f"当前 top no-entry backlog 的主矛盾已经下沉到 candidate-entry semantic miss：{top_semantic_miss_tickers} 已进入候选源，"
            "但 frontier 仍没命中 focus。下一步应继续 semantic replay，而不是上游补数。"
        )
    if promising_priority_tickers:
        return (
            f"当前 no-entry failure backlog 已经为 {promising_priority_tickers} 找到 preserve-safe recall probe。"
            "下一步应优先把它们接回 shadow governance。"
        )
    dominant_failure_class = next(iter(priority_failure_class_counts.keys()), "no_priority_tickers")
    return (
        f"当前 no-entry failure backlog 仍以 {dominant_failure_class} 为主，"
        "应继续保留 research-only 审查，不要直接把 candidate-entry frontier 当作默认放松路线。"
    )


def _build_next_actions(
    *,
    top_upstream_absence_tickers: list[str],
    top_absent_from_watchlist_tickers: list[str],
    top_watchlist_handoff_gap_tickers: list[str],
    top_candidate_entry_to_target_gap_tickers: list[str],
    top_outside_candidate_entry_tickers: list[str],
    top_semantic_miss_tickers: list[str],
    top_hotspot_semantic_miss_report_dirs: list[str],
    promising_priority_tickers: list[str],
) -> list[str]:
    actions: list[str] = []
    if top_absent_from_watchlist_tickers:
        actions.append(f"先补 {top_absent_from_watchlist_tickers} 的 candidate pool -> watchlist 召回观测，确认它们为何连 watchlist 都没进入。")
    if top_upstream_absence_tickers:
        actions.append(f"先补 {top_upstream_absence_tickers} 的 replay-input / selection_artifacts 观测，确认它们为何完全未进入候选证据层。")
    if top_watchlist_handoff_gap_tickers:
        actions.append(f"回查 {top_watchlist_handoff_gap_tickers} 的 watchlist -> rejected_entries / supplemental_short_trade_entries handoff。")
    if top_candidate_entry_to_target_gap_tickers:
        actions.append(f"回查 {top_candidate_entry_to_target_gap_tickers} 的 candidate-entry -> selection_targets contract，确认目标附着为何丢失。")
    if top_outside_candidate_entry_tickers:
        actions.append(f"回查 {top_outside_candidate_entry_tickers} 的 watchlist -> rejected_entries / supplemental_short_trade_entries handoff，定位 no-entry 前的上游分流。")
    if top_semantic_miss_tickers:
        actions.append(f"仅把 {top_semantic_miss_tickers} 继续留在 candidate-entry semantic frontier 车道，因为它们已经进入候选源但仍未命中 focus。")
    if top_hotspot_semantic_miss_report_dirs:
        actions.append(f"优先复盘热点窗口 {top_hotspot_semantic_miss_report_dirs}，明确它们是窗口级 focus miss，而不是上游 absence。")
    if promising_priority_tickers:
        actions.append(f"把 {promising_priority_tickers} 接回 shadow governance，并持续核对 preserve_ticker 0 误伤。")
    if not actions:
        actions.append("当前 failure dossier 没有发现可直接推进的 recall probe，继续保留 research-only。")
    return actions[:4]


def analyze_btst_no_candidate_entry_failure_dossier(
    tradeable_opportunity_pool_path: str | Path,
    *,
    action_board_path: str | Path | None = None,
    replay_bundle_path: str | Path | None = None,
    priority_limit: int = DEFAULT_PRIORITY_LIMIT,
    hotspot_limit: int = DEFAULT_HOTSPOT_LIMIT,
) -> dict[str, Any]:
    tradeable_pool = _load_json(tradeable_opportunity_pool_path)
    resolved_tradeable_pool_path = Path(tradeable_opportunity_pool_path).expanduser().resolve()
    action_board = _safe_load_json(action_board_path)
    replay_bundle = _safe_load_json(replay_bundle_path)
    reports_root = Path(
        action_board.get("reports_root")
        or resolved_tradeable_pool_path.parent
    ).expanduser().resolve()
    no_candidate_rows = _collect_no_candidate_rows(tradeable_pool)
    priority_rows = _build_priority_rows(action_board, tradeable_pool, priority_limit=max(int(priority_limit), 0))
    hotspot_rows = _build_hotspot_rows(action_board, hotspot_limit=max(int(hotspot_limit), 0))
    report_cache: dict[str, dict[str, Any]] = {}

    priority_ticker_dossiers = _build_priority_ticker_dossiers(
        priority_rows,
        no_candidate_rows,
        reports_root=reports_root,
        replay_bundle=replay_bundle,
        report_cache=report_cache,
    )
    hotspot_report_dossiers = _build_hotspot_report_dossiers(
        hotspot_rows,
        reports_root=reports_root,
        replay_bundle=replay_bundle,
        report_cache=report_cache,
    )

    priority_failure_class_counts: Counter[str] = Counter(
        str(row.get("primary_failure_class") or "unknown")
        for row in priority_ticker_dossiers
    )
    hotspot_failure_class_counts: Counter[str] = Counter(
        str(row.get("primary_failure_class") or "unknown")
        for row in hotspot_report_dossiers
    )
    priority_handoff_stage_counts = _count_handoff_stages(priority_ticker_dossiers)
    hotspot_handoff_stage_counts = _count_handoff_stages(hotspot_report_dossiers, key="dominant_handoff_stage")
    promising_priority_tickers = [
        str(row.get("ticker") or "")
        for row in priority_ticker_dossiers
        if str(row.get("primary_failure_class") or "") == "preserve_safe_recall_probe" and str(row.get("ticker") or "").strip()
    ]
    top_upstream_absence_tickers = _top_tickers_by_failure(priority_ticker_dossiers, "upstream_absent_from_replay_inputs")
    top_absent_from_watchlist_tickers = _top_tickers_by_handoff_stage(priority_ticker_dossiers, "absent_from_watchlist")
    top_watchlist_handoff_gap_tickers = _top_tickers_by_handoff_stage(priority_ticker_dossiers, "watchlist_visible_but_not_candidate_entry")
    top_candidate_entry_to_target_gap_tickers = _top_tickers_by_handoff_stage(priority_ticker_dossiers, "candidate_entry_visible_but_not_selection_target")
    top_outside_candidate_entry_tickers = _top_tickers_by_failure(priority_ticker_dossiers, "present_but_outside_candidate_entry_universe")
    top_semantic_miss_tickers = _top_tickers_by_failure(priority_ticker_dossiers, "candidate_entry_semantic_miss")
    top_missing_replay_input_tickers = _top_tickers_by_failure(priority_ticker_dossiers, "missing_replay_input_artifacts")
    top_hotspot_semantic_miss_report_dirs = _top_report_dirs_by_failure(hotspot_report_dossiers, "hotspot_candidate_entry_semantic_miss")
    top_hotspot_upstream_absence_report_dirs = _top_report_dirs_by_failure(hotspot_report_dossiers, "hotspot_upstream_absence")
    priority_handoff_action_queue = _build_priority_handoff_action_queue(priority_ticker_dossiers, limit=max(int(priority_limit), 0))
    hotspot_handoff_action_queue = _build_hotspot_handoff_action_queue(hotspot_report_dossiers, limit=max(int(hotspot_limit), 0))

    recommendation = _build_recommendation(
        priority_failure_class_counts=priority_failure_class_counts,
        top_upstream_absence_tickers=top_upstream_absence_tickers,
        top_absent_from_watchlist_tickers=top_absent_from_watchlist_tickers,
        top_watchlist_handoff_gap_tickers=top_watchlist_handoff_gap_tickers,
        top_candidate_entry_to_target_gap_tickers=top_candidate_entry_to_target_gap_tickers,
        top_outside_candidate_entry_tickers=top_outside_candidate_entry_tickers,
        top_semantic_miss_tickers=top_semantic_miss_tickers,
        promising_priority_tickers=promising_priority_tickers,
    )
    next_actions = _build_next_actions(
        top_upstream_absence_tickers=top_upstream_absence_tickers,
        top_absent_from_watchlist_tickers=top_absent_from_watchlist_tickers,
        top_watchlist_handoff_gap_tickers=top_watchlist_handoff_gap_tickers,
        top_candidate_entry_to_target_gap_tickers=top_candidate_entry_to_target_gap_tickers,
        top_outside_candidate_entry_tickers=top_outside_candidate_entry_tickers,
        top_semantic_miss_tickers=top_semantic_miss_tickers,
        top_hotspot_semantic_miss_report_dirs=top_hotspot_semantic_miss_report_dirs,
        promising_priority_tickers=promising_priority_tickers,
    )

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tradeable_opportunity_pool_path": resolved_tradeable_pool_path.as_posix(),
        "action_board_path": Path(action_board_path).expanduser().resolve().as_posix() if action_board_path else None,
        "replay_bundle_path": Path(replay_bundle_path).expanduser().resolve().as_posix() if replay_bundle_path else None,
        "reports_root": reports_root.as_posix(),
        "priority_limit": max(int(priority_limit), 0),
        "hotspot_limit": max(int(hotspot_limit), 0),
        "priority_failure_class_counts": dict(priority_failure_class_counts.most_common()),
        "hotspot_failure_class_counts": dict(hotspot_failure_class_counts.most_common()),
        "priority_handoff_stage_counts": priority_handoff_stage_counts,
        "hotspot_handoff_stage_counts": hotspot_handoff_stage_counts,
        "top_upstream_absence_tickers": top_upstream_absence_tickers,
        "top_absent_from_watchlist_tickers": top_absent_from_watchlist_tickers,
        "top_watchlist_visible_but_not_candidate_entry_tickers": top_watchlist_handoff_gap_tickers,
        "top_candidate_entry_visible_but_not_selection_target_tickers": top_candidate_entry_to_target_gap_tickers,
        "top_present_but_outside_candidate_entry_tickers": top_outside_candidate_entry_tickers,
        "top_candidate_entry_semantic_miss_tickers": top_semantic_miss_tickers,
        "top_missing_replay_input_tickers": top_missing_replay_input_tickers,
        "top_hotspot_semantic_miss_report_dirs": top_hotspot_semantic_miss_report_dirs,
        "top_hotspot_upstream_absence_report_dirs": top_hotspot_upstream_absence_report_dirs,
        "promising_priority_tickers": promising_priority_tickers,
        "priority_ticker_dossiers": priority_ticker_dossiers,
        "hotspot_report_dossiers": hotspot_report_dossiers,
        "priority_handoff_action_queue": priority_handoff_action_queue,
        "hotspot_handoff_action_queue": hotspot_handoff_action_queue,
        "next_actions": next_actions,
        "recommendation": recommendation,
    }


def render_btst_no_candidate_entry_failure_dossier_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST No Candidate Entry Failure Dossier")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- tradeable_opportunity_pool_path: {analysis.get('tradeable_opportunity_pool_path')}")
    lines.append(f"- action_board_path: {analysis.get('action_board_path')}")
    lines.append(f"- replay_bundle_path: {analysis.get('replay_bundle_path')}")
    lines.append(f"- priority_failure_class_counts: {analysis.get('priority_failure_class_counts')}")
    lines.append(f"- hotspot_failure_class_counts: {analysis.get('hotspot_failure_class_counts')}")
    lines.append(f"- priority_handoff_stage_counts: {analysis.get('priority_handoff_stage_counts')}")
    lines.append(f"- hotspot_handoff_stage_counts: {analysis.get('hotspot_handoff_stage_counts')}")
    lines.append(f"- top_upstream_absence_tickers: {analysis.get('top_upstream_absence_tickers')}")
    lines.append(f"- top_absent_from_watchlist_tickers: {analysis.get('top_absent_from_watchlist_tickers')}")
    lines.append(f"- top_watchlist_visible_but_not_candidate_entry_tickers: {analysis.get('top_watchlist_visible_but_not_candidate_entry_tickers')}")
    lines.append(f"- top_candidate_entry_visible_but_not_selection_target_tickers: {analysis.get('top_candidate_entry_visible_but_not_selection_target_tickers')}")
    lines.append(f"- top_present_but_outside_candidate_entry_tickers: {analysis.get('top_present_but_outside_candidate_entry_tickers')}")
    lines.append(f"- top_candidate_entry_semantic_miss_tickers: {analysis.get('top_candidate_entry_semantic_miss_tickers')}")
    lines.append(f"- recommendation: {analysis.get('recommendation')}")
    lines.append("")
    lines.append("## Priority Ticker Dossiers")
    for row in list(analysis.get("priority_ticker_dossiers") or []):
        lines.append(
            f"- rank={row.get('priority_rank')} ticker={row.get('ticker')} failure_class={row.get('primary_failure_class')} handoff_stage={row.get('handoff_stage')} frontier_status={row.get('frontier_status')} primary_report_dir={row.get('primary_report_dir')} replay_input_visible_reports={row.get('replay_input_visible_report_count')} candidate_entry_visible_reports={row.get('candidate_entry_visible_report_count')}"
        )
        lines.append(f"  source_presence_counts: {row.get('source_presence_counts')}")
        lines.append(f"  candidate_sources: {row.get('candidate_sources')}")
        lines.append(f"  failure_reason: {row.get('failure_reason')}")
        lines.append(f"  next_step: {row.get('next_step')}")
        for evidence_row in list(row.get("report_dir_evidence") or [])[:4]:
            lines.append(
                f"  report_evidence: report_dir={evidence_row.get('report_dir')} presence_class={evidence_row.get('presence_class')} replay_input_count={evidence_row.get('replay_input_count')} source_presence_counts={evidence_row.get('source_presence_counts')}"
            )
    if not list(analysis.get("priority_ticker_dossiers") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Hotspot Report Dossiers")
    for row in list(analysis.get("hotspot_report_dossiers") or []):
        lines.append(
            f"- rank={row.get('priority_rank')} report_dir={row.get('report_dir')} failure_class={row.get('primary_failure_class')} dominant_handoff_stage={row.get('dominant_handoff_stage')} frontier_status={row.get('frontier_status')} focus_tickers={row.get('focus_tickers')}"
        )
        lines.append(f"  failure_reason: {row.get('failure_reason')}")
        lines.append(f"  next_step: {row.get('next_step')}")
        lines.append(f"  focus_ticker_handoff_stage_counts: {row.get('focus_ticker_handoff_stage_counts')}")
        for evidence_row in list(row.get("focus_ticker_evidence") or []):
            lines.append(
                f"  focus_evidence: ticker={evidence_row.get('ticker')} presence_class={evidence_row.get('presence_class')} handoff_stage={evidence_row.get('handoff_stage')} replay_input_count={evidence_row.get('replay_input_count')} source_presence_counts={evidence_row.get('source_presence_counts')}"
            )
    if not list(analysis.get("hotspot_report_dossiers") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Handoff Action Queue")
    for row in list(analysis.get("priority_handoff_action_queue") or []):
        lines.append(
            f"- task_id={row.get('task_id')} ticker={row.get('ticker')} action_tier={row.get('action_tier')} handoff_stage={row.get('handoff_stage')}"
        )
        lines.append(f"  why_now: {row.get('why_now')}")
        lines.append(f"  next_step: {row.get('next_step')}")
    for row in list(analysis.get("hotspot_handoff_action_queue") or []):
        lines.append(
            f"- hotspot_task_id={row.get('task_id')} report_dir={row.get('report_dir')} action_tier={row.get('action_tier')} handoff_stage={row.get('handoff_stage')}"
        )
        lines.append(f"  why_now: {row.get('why_now')}")
        lines.append(f"  next_step: {row.get('next_step')}")
    if not list(analysis.get("priority_handoff_action_queue") or []) and not list(analysis.get("hotspot_handoff_action_queue") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Next Actions")
    for item in list(analysis.get("next_actions") or []):
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify why top no_candidate_entry backlog names fail to form recall probes.")
    parser.add_argument("--tradeable-opportunity-pool", default=str(DEFAULT_TRADEABLE_OPPORTUNITY_POOL_PATH))
    parser.add_argument("--action-board", default=str(DEFAULT_ACTION_BOARD_PATH))
    parser.add_argument("--replay-bundle", default=str(DEFAULT_REPLAY_BUNDLE_PATH))
    parser.add_argument("--priority-limit", type=int, default=DEFAULT_PRIORITY_LIMIT)
    parser.add_argument("--hotspot-limit", type=int, default=DEFAULT_HOTSPOT_LIMIT)
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_no_candidate_entry_failure_dossier(
        args.tradeable_opportunity_pool,
        action_board_path=args.action_board or None,
        replay_bundle_path=args.replay_bundle or None,
        priority_limit=args.priority_limit,
        hotspot_limit=args.hotspot_limit,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_no_candidate_entry_failure_dossier_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()