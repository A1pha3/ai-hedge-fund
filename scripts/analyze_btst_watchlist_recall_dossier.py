from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


REPORTS_DIR = Path("data/reports")
DEFAULT_TRADEABLE_OPPORTUNITY_POOL_PATH = REPORTS_DIR / "btst_tradeable_opportunity_pool_march.json"
DEFAULT_FAILURE_DOSSIER_PATH = REPORTS_DIR / "btst_no_candidate_entry_failure_dossier_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_watchlist_recall_dossier_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_watchlist_recall_dossier_latest.md"
DEFAULT_PRIORITY_LIMIT = 5
RECALL_STAGE_ORDER = [
    "missing_candidate_pool_snapshot",
    "absent_from_candidate_pool",
    "candidate_pool_visible_but_missing_layer_b",
    "layer_b_visible_but_missing_watchlist",
    "watchlist_visible_but_missing_candidate_entry",
    "candidate_entry_visible_or_later_stage",
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


def _snapshot_paths(snapshots_root: Path, trade_date: str) -> list[Path]:
    compact_trade_date = "".join(ch for ch in str(trade_date or "") if ch.isdigit())
    return [
        snapshots_root / f"candidate_pool_{compact_trade_date}_top300.json",
        snapshots_root / f"candidate_pool_{compact_trade_date}.json",
    ]


def _load_candidate_pool_snapshot(
    snapshots_root: Path,
    trade_date: str,
    *,
    snapshot_cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    compact_trade_date = "".join(ch for ch in str(trade_date or "") if ch.isdigit())
    cached = snapshot_cache.get(compact_trade_date)
    if cached is not None:
        return cached

    for path in _snapshot_paths(snapshots_root, trade_date):
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        ticker_ranks: dict[str, int] = {}
        for index, item in enumerate(list(payload or []), start=1):
            if not isinstance(item, dict):
                continue
            ticker = str(item.get("ticker") or "").strip()
            if ticker and ticker not in ticker_ranks:
                ticker_ranks[ticker] = index
        cached = {
            "snapshot_path": path.as_posix(),
            "snapshot_name": path.name,
            "snapshot_size": len(ticker_ranks),
            "ticker_ranks": ticker_ranks,
        }
        snapshot_cache[compact_trade_date] = cached
        return cached

    cached = {
        "snapshot_path": None,
        "snapshot_name": None,
        "snapshot_size": 0,
        "ticker_ranks": {},
    }
    snapshot_cache[compact_trade_date] = cached
    return cached


def _classify_recall_stage(*, candidate_pool_visible: bool, system_seen_stage: str | None, candidate_source: str | None) -> str:
    normalized_stage = str(system_seen_stage or "").strip()
    normalized_source = str(candidate_source or "").strip()
    if not candidate_pool_visible:
        return "absent_from_candidate_pool"
    if normalized_stage == "boundary" or normalized_source == "layer_b_boundary":
        return "layer_b_visible_but_missing_watchlist"
    if normalized_stage == "candidate_entry" or normalized_source in {"watchlist_filter_diagnostics", "layer_c_watchlist"}:
        return "watchlist_visible_but_missing_candidate_entry"
    if normalized_stage in {"short_trade_candidate", "selection_target", "execution"} or normalized_source in {"short_trade_boundary", "catalyst_theme", "catalyst_theme_shadow"}:
        return "candidate_entry_visible_or_later_stage"
    return "candidate_pool_visible_but_missing_layer_b"


def _build_focus_tickers(tradeable_pool: dict[str, Any], failure_dossier: dict[str, Any], *, priority_limit: int) -> list[str]:
    priority_limit = max(int(priority_limit), 0)
    top_absent_from_watchlist_tickers = [
        str(value)
        for value in list(failure_dossier.get("top_absent_from_watchlist_tickers") or [])
        if str(value or "").strip()
    ]
    if top_absent_from_watchlist_tickers:
        return top_absent_from_watchlist_tickers[:priority_limit]

    top_ticker_rows = [
        dict(row)
        for row in list(dict(tradeable_pool.get("no_candidate_entry_summary") or {}).get("top_ticker_rows") or [])
        if str(row.get("ticker") or "").strip()
    ]
    return [str(row.get("ticker") or "") for row in top_ticker_rows[:priority_limit] if str(row.get("ticker") or "").strip()]


def _count_recall_stages(rows: list[dict[str, Any]], key: str = "recall_stage") -> dict[str, int]:
    counts = Counter(str(row.get(key) or "unknown") for row in rows if str(row.get(key) or "").strip())
    ordered: dict[str, int] = {}
    for stage in RECALL_STAGE_ORDER:
        if counts.get(stage):
            ordered[stage] = int(counts[stage])
    for stage, count in counts.most_common():
        if stage not in ordered:
            ordered[stage] = int(count)
    return ordered


def _dominant_recall_stage(stage_counts: dict[str, int]) -> str | None:
    if not stage_counts:
        return None
    for stage in RECALL_STAGE_ORDER:
        if int(stage_counts.get(stage) or 0) > 0:
            return stage
    return next(iter(stage_counts.keys()), None)


def _build_recall_action(stage: str, *, subject: str) -> tuple[str, str, str]:
    if stage == "missing_candidate_pool_snapshot":
        return (
            "p0_snapshot_gap",
            f"补齐 {subject} 对应 trade_date 的 candidate_pool snapshot，避免 watchlist recall 诊断停在产物缺口。",
            f"先补 {subject} 的 candidate_pool_YYYYMMDD_top300.json 或 legacy snapshot，再继续上游召回定位。",
        )
    if stage == "absent_from_candidate_pool":
        return (
            "p0_candidate_pool_recall",
            f"回查 {subject} 为什么连 candidate_pool snapshot 都没有进入，主矛盾还在 Layer A 候选池召回。",
            f"先审 {subject} 的 candidate_pool 构建、池大小截断与 Layer A 先验过滤，而不是继续调 watchlist 或 candidate-entry。",
        )
    if stage == "candidate_pool_visible_but_missing_layer_b":
        return (
            "p1_layer_b_handoff",
            f"回查 {subject} 已进入 candidate_pool，却没有出现在 layer_b 过滤诊断中。",
            f"先核对 {subject} 的 score_batch/fuse_batch 是否丢失，以及 high_pool 前的 Layer B handoff。",
        )
    if stage == "layer_b_visible_but_missing_watchlist":
        return (
            "p2_watchlist_gate",
            f"回查 {subject} 已进入 layer_b，但没有进入 watchlist。",
            f"优先检查 {subject} 的 score_final、decision_avoid 与 watchlist_score_threshold，而不是继续 candidate-entry frontier。",
        )
    if stage == "watchlist_visible_but_missing_candidate_entry":
        return (
            "p3_candidate_entry_handoff",
            f"{subject} 已进入 watchlist，但后续没有形成 candidate-entry 证据。",
            f"把 {subject} 转入 watchlist -> candidate-entry handoff 诊断，不再停留在 candidate_pool recall 层。",
        )
    return (
        "p4_downstream_followup",
        f"{subject} 已进入 candidate-entry 或更下游阶段，这不再是 watchlist recall 主矛盾。",
        f"把 {subject} 转回更下游的 candidate-entry / execution 诊断。",
    )


def _build_priority_ticker_dossiers(
    focus_tickers: list[str],
    tradeable_pool: dict[str, Any],
    *,
    snapshots_root: Path,
    snapshot_cache: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    no_candidate_rows = [
        dict(row)
        for row in list(tradeable_pool.get("rows") or [])
        if str(row.get("first_kill_switch") or "") == "no_candidate_entry"
    ]
    dossiers: list[dict[str, Any]] = []
    for priority_rank, ticker in enumerate(focus_tickers, start=1):
        ticker_rows = [row for row in no_candidate_rows if str(row.get("ticker") or "").strip() == ticker]
        occurrence_evidence: list[dict[str, Any]] = []
        report_dir_counts = Counter(str(row.get("report_dir") or "") for row in ticker_rows if str(row.get("report_dir") or "").strip())
        for row in sorted(ticker_rows, key=lambda current: (str(current.get("trade_date") or ""), str(current.get("report_dir") or ""))):
            trade_date = str(row.get("trade_date") or "").strip()
            snapshot_payload = _load_candidate_pool_snapshot(snapshots_root, trade_date, snapshot_cache=snapshot_cache)
            ticker_ranks = dict(snapshot_payload.get("ticker_ranks") or {})
            candidate_pool_rank = ticker_ranks.get(ticker)
            if not snapshot_payload.get("snapshot_path"):
                recall_stage = "missing_candidate_pool_snapshot"
            else:
                recall_stage = _classify_recall_stage(
                    candidate_pool_visible=candidate_pool_rank is not None,
                    system_seen_stage=row.get("system_seen_stage"),
                    candidate_source=row.get("candidate_source"),
                )
            occurrence_evidence.append(
                {
                    "trade_date": trade_date,
                    "report_dir": row.get("report_dir"),
                    "report_mode": row.get("report_mode"),
                    "strict_btst_goal_case": bool(row.get("strict_btst_goal_case")),
                    "system_seen_stage": row.get("system_seen_stage"),
                    "candidate_source": row.get("candidate_source"),
                    "short_trade_decision": row.get("short_trade_decision"),
                    "next_high_return": row.get("next_high_return"),
                    "t_plus_2_close_return": row.get("t_plus_2_close_return"),
                    "candidate_pool_snapshot": snapshot_payload.get("snapshot_name"),
                    "candidate_pool_snapshot_path": snapshot_payload.get("snapshot_path"),
                    "candidate_pool_snapshot_size": snapshot_payload.get("snapshot_size"),
                    "candidate_pool_visible": candidate_pool_rank is not None,
                    "candidate_pool_rank": candidate_pool_rank,
                    "recall_stage": recall_stage,
                }
            )

        recall_stage_counts = _count_recall_stages(occurrence_evidence)
        dominant_recall_stage = _dominant_recall_stage(recall_stage_counts)
        action_tier, title, next_step = _build_recall_action(dominant_recall_stage or "missing_candidate_pool_snapshot", subject=ticker)
        candidate_pool_visible_count = sum(1 for row in occurrence_evidence if bool(row.get("candidate_pool_visible")))
        layer_b_visible_count = sum(1 for row in occurrence_evidence if str(row.get("system_seen_stage") or "") == "boundary")
        watchlist_visible_count = sum(
            1
            for row in occurrence_evidence
            if str(row.get("system_seen_stage") or "") == "candidate_entry" or str(row.get("candidate_source") or "") in {"watchlist_filter_diagnostics", "layer_c_watchlist"}
        )
        strict_goal_case_count = sum(1 for row in occurrence_evidence if bool(row.get("strict_btst_goal_case")))
        failure_reason = {
            "missing_candidate_pool_snapshot": f"{ticker} 对应的 trade_date 缺少 candidate_pool snapshot，当前先是候选池观测缺口。",
            "absent_from_candidate_pool": f"{ticker} 在已存在的 candidate_pool snapshot 中持续缺席，说明问题先发生在 Layer A 候选池召回。",
            "candidate_pool_visible_but_missing_layer_b": f"{ticker} 已进入 candidate_pool，但没有进入 layer_b 过滤诊断，当前断点落在 candidate_pool -> layer_b handoff。",
            "layer_b_visible_but_missing_watchlist": f"{ticker} 已进入 layer_b，但没有进入 watchlist，当前断点落在 layer_b -> watchlist gate。",
            "watchlist_visible_but_missing_candidate_entry": f"{ticker} 已进入 watchlist，因此不再属于 watchlist recall 主矛盾。",
            "candidate_entry_visible_or_later_stage": f"{ticker} 已进入 candidate-entry 或更下游阶段，watchlist recall 已不是首要问题。",
        }.get(dominant_recall_stage or "", f"{ticker} 的 watchlist recall 证据混合，仍需更多 occurrence 样本。")

        dossiers.append(
            {
                "priority_rank": priority_rank,
                "ticker": ticker,
                "occurrence_count": len(occurrence_evidence),
                "strict_btst_goal_case_count": strict_goal_case_count,
                "primary_report_dir": report_dir_counts.most_common(1)[0][0] if report_dir_counts else None,
                "report_dir_counts": {key: int(value) for key, value in report_dir_counts.most_common()},
                "candidate_pool_visible_count": candidate_pool_visible_count,
                "layer_b_visible_count": layer_b_visible_count,
                "watchlist_visible_count": watchlist_visible_count,
                "recall_stage_counts": recall_stage_counts,
                "dominant_recall_stage": dominant_recall_stage,
                "action_tier": action_tier,
                "title": title,
                "failure_reason": failure_reason,
                "next_step": next_step,
                "occurrence_evidence": occurrence_evidence,
            }
        )
    return dossiers


def _top_tickers_by_recall_stage(priority_ticker_dossiers: list[dict[str, Any]], recall_stage: str) -> list[str]:
    return [
        str(row.get("ticker") or "")
        for row in priority_ticker_dossiers
        if str(row.get("dominant_recall_stage") or "") == recall_stage and str(row.get("ticker") or "").strip()
    ][:3]


def _build_action_queue(priority_ticker_dossiers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    for row in priority_ticker_dossiers:
        ticker = str(row.get("ticker") or "").strip()
        dominant_recall_stage = str(row.get("dominant_recall_stage") or "").strip()
        if not ticker or not dominant_recall_stage:
            continue
        action_tier, title, next_step = _build_recall_action(dominant_recall_stage, subject=ticker)
        queue.append(
            {
                "task_id": f"{ticker}_{dominant_recall_stage}",
                "priority_rank": row.get("priority_rank"),
                "ticker": ticker,
                "dominant_recall_stage": dominant_recall_stage,
                "action_tier": action_tier,
                "title": title,
                "why_now": row.get("failure_reason"),
                "next_step": next_step,
            }
        )
    return queue


def _build_recommendation(
    *,
    top_absent_from_candidate_pool_tickers: list[str],
    top_candidate_pool_visible_but_missing_layer_b_tickers: list[str],
    top_layer_b_visible_but_missing_watchlist_tickers: list[str],
) -> str:
    if top_absent_from_candidate_pool_tickers:
        return (
            f"当前 watchlist recall backlog 的主矛盾已经进一步前移到 candidate_pool：{top_absent_from_candidate_pool_tickers} 连 candidate_pool snapshot 都没有进入。"
            "下一步应先补 Layer A 候选池召回与池内截断观测，而不是继续调 watchlist 阈值或 candidate-entry 语义。"
        )
    if top_candidate_pool_visible_but_missing_layer_b_tickers:
        return (
            f"当前 watchlist recall backlog 的主矛盾落在 candidate_pool -> layer_b：{top_candidate_pool_visible_but_missing_layer_b_tickers} 已进入 candidate_pool，"
            "但没有进入 layer_b 过滤诊断。下一步应先核对 Layer B 计分/融合 handoff。"
        )
    if top_layer_b_visible_but_missing_watchlist_tickers:
        return (
            f"当前 watchlist recall backlog 的主矛盾落在 layer_b -> watchlist gate：{top_layer_b_visible_but_missing_watchlist_tickers} 已进入 layer_b，"
            "但没有进入 watchlist。下一步应先回查 score_final、decision_avoid 与 watchlist 阈值。"
        )
    return "当前 watchlist recall dossier 没有形成单一主矛盾，继续累积 occurrence 证据再推进。"


def _build_next_actions(
    *,
    top_absent_from_candidate_pool_tickers: list[str],
    top_candidate_pool_visible_but_missing_layer_b_tickers: list[str],
    top_layer_b_visible_but_missing_watchlist_tickers: list[str],
) -> list[str]:
    actions: list[str] = []
    if top_absent_from_candidate_pool_tickers:
        actions.append(f"先补 {top_absent_from_candidate_pool_tickers} 的 Layer A candidate_pool 召回观测，确认它们为何连候选池都没进入。")
    if top_candidate_pool_visible_but_missing_layer_b_tickers:
        actions.append(f"回查 {top_candidate_pool_visible_but_missing_layer_b_tickers} 的 candidate_pool -> layer_b handoff，核对 score_batch / fuse_batch 是否丢样本。")
    if top_layer_b_visible_but_missing_watchlist_tickers:
        actions.append(f"回查 {top_layer_b_visible_but_missing_watchlist_tickers} 的 layer_b -> watchlist gate，重点看 score_final 与 decision_avoid。")
    if not actions:
        actions.append("当前 watchlist recall dossier 没有新增明确动作，继续保留研究观察。")
    return actions[:4]


def analyze_btst_watchlist_recall_dossier(
    tradeable_opportunity_pool_path: str | Path,
    *,
    failure_dossier_path: str | Path | None = None,
    priority_limit: int = DEFAULT_PRIORITY_LIMIT,
) -> dict[str, Any]:
    tradeable_pool = _load_json(tradeable_opportunity_pool_path)
    failure_dossier = _safe_load_json(failure_dossier_path)
    resolved_tradeable_pool_path = Path(tradeable_opportunity_pool_path).expanduser().resolve()
    reports_root = Path(tradeable_pool.get("reports_root") or resolved_tradeable_pool_path.parent).expanduser().resolve()
    snapshots_root = reports_root.parent / "snapshots"
    focus_tickers = _build_focus_tickers(tradeable_pool, failure_dossier, priority_limit=priority_limit)
    snapshot_cache: dict[str, dict[str, Any]] = {}
    priority_ticker_dossiers = _build_priority_ticker_dossiers(
        focus_tickers,
        tradeable_pool,
        snapshots_root=snapshots_root,
        snapshot_cache=snapshot_cache,
    )
    priority_recall_stage_counts = _count_recall_stages(priority_ticker_dossiers, key="dominant_recall_stage")
    top_absent_from_candidate_pool_tickers = _top_tickers_by_recall_stage(priority_ticker_dossiers, "absent_from_candidate_pool")
    top_candidate_pool_visible_but_missing_layer_b_tickers = _top_tickers_by_recall_stage(priority_ticker_dossiers, "candidate_pool_visible_but_missing_layer_b")
    top_layer_b_visible_but_missing_watchlist_tickers = _top_tickers_by_recall_stage(priority_ticker_dossiers, "layer_b_visible_but_missing_watchlist")
    action_queue = _build_action_queue(priority_ticker_dossiers)
    recommendation = _build_recommendation(
        top_absent_from_candidate_pool_tickers=top_absent_from_candidate_pool_tickers,
        top_candidate_pool_visible_but_missing_layer_b_tickers=top_candidate_pool_visible_but_missing_layer_b_tickers,
        top_layer_b_visible_but_missing_watchlist_tickers=top_layer_b_visible_but_missing_watchlist_tickers,
    )
    next_actions = _build_next_actions(
        top_absent_from_candidate_pool_tickers=top_absent_from_candidate_pool_tickers,
        top_candidate_pool_visible_but_missing_layer_b_tickers=top_candidate_pool_visible_but_missing_layer_b_tickers,
        top_layer_b_visible_but_missing_watchlist_tickers=top_layer_b_visible_but_missing_watchlist_tickers,
    )
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tradeable_opportunity_pool_path": resolved_tradeable_pool_path.as_posix(),
        "failure_dossier_path": Path(failure_dossier_path).expanduser().resolve().as_posix() if failure_dossier_path else None,
        "reports_root": reports_root.as_posix(),
        "snapshots_root": snapshots_root.as_posix(),
        "priority_limit": max(int(priority_limit), 0),
        "focus_tickers": focus_tickers,
        "priority_recall_stage_counts": priority_recall_stage_counts,
        "top_absent_from_candidate_pool_tickers": top_absent_from_candidate_pool_tickers,
        "top_candidate_pool_visible_but_missing_layer_b_tickers": top_candidate_pool_visible_but_missing_layer_b_tickers,
        "top_layer_b_visible_but_missing_watchlist_tickers": top_layer_b_visible_but_missing_watchlist_tickers,
        "priority_ticker_dossiers": priority_ticker_dossiers,
        "action_queue": action_queue,
        "next_actions": next_actions,
        "recommendation": recommendation,
    }


def render_btst_watchlist_recall_dossier_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Watchlist Recall Dossier")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- tradeable_opportunity_pool_path: {analysis.get('tradeable_opportunity_pool_path')}")
    lines.append(f"- failure_dossier_path: {analysis.get('failure_dossier_path')}")
    lines.append(f"- priority_recall_stage_counts: {analysis.get('priority_recall_stage_counts')}")
    lines.append(f"- top_absent_from_candidate_pool_tickers: {analysis.get('top_absent_from_candidate_pool_tickers')}")
    lines.append(f"- top_candidate_pool_visible_but_missing_layer_b_tickers: {analysis.get('top_candidate_pool_visible_but_missing_layer_b_tickers')}")
    lines.append(f"- top_layer_b_visible_but_missing_watchlist_tickers: {analysis.get('top_layer_b_visible_but_missing_watchlist_tickers')}")
    lines.append(f"- recommendation: {analysis.get('recommendation')}")
    lines.append("")
    lines.append("## Priority Ticker Dossiers")
    for row in list(analysis.get("priority_ticker_dossiers") or []):
        lines.append(
            f"- rank={row.get('priority_rank')} ticker={row.get('ticker')} dominant_recall_stage={row.get('dominant_recall_stage')} occurrence_count={row.get('occurrence_count')} candidate_pool_visible_count={row.get('candidate_pool_visible_count')} layer_b_visible_count={row.get('layer_b_visible_count')}"
        )
        lines.append(f"  recall_stage_counts: {row.get('recall_stage_counts')}")
        lines.append(f"  failure_reason: {row.get('failure_reason')}")
        lines.append(f"  next_step: {row.get('next_step')}")
        for evidence_row in list(row.get("occurrence_evidence") or [])[:6]:
            lines.append(
                f"  occurrence: trade_date={evidence_row.get('trade_date')} report_dir={evidence_row.get('report_dir')} recall_stage={evidence_row.get('recall_stage')} candidate_pool_visible={evidence_row.get('candidate_pool_visible')} candidate_pool_rank={evidence_row.get('candidate_pool_rank')} system_seen_stage={evidence_row.get('system_seen_stage')}"
            )
    if not list(analysis.get("priority_ticker_dossiers") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Action Queue")
    for row in list(analysis.get("action_queue") or []):
        lines.append(
            f"- task_id={row.get('task_id')} ticker={row.get('ticker')} action_tier={row.get('action_tier')} dominant_recall_stage={row.get('dominant_recall_stage')}"
        )
        lines.append(f"  why_now: {row.get('why_now')}")
        lines.append(f"  next_step: {row.get('next_step')}")
    if not list(analysis.get("action_queue") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Next Actions")
    for item in list(analysis.get("next_actions") or []):
        lines.append(f"- {item}")
    if not list(analysis.get("next_actions") or []):
        lines.append("- none")
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify whether absent-from-watchlist backlog names fail before candidate_pool, before layer_b, or at the watchlist gate.")
    parser.add_argument("--tradeable-opportunity-pool", default=str(DEFAULT_TRADEABLE_OPPORTUNITY_POOL_PATH))
    parser.add_argument("--failure-dossier", default=str(DEFAULT_FAILURE_DOSSIER_PATH))
    parser.add_argument("--priority-limit", type=int, default=DEFAULT_PRIORITY_LIMIT)
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_watchlist_recall_dossier(
        args.tradeable_opportunity_pool,
        failure_dossier_path=args.failure_dossier or None,
        priority_limit=args.priority_limit,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_watchlist_recall_dossier_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()