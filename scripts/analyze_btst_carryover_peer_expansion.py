from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


REPORTS_DIR = Path("data/reports")
DEFAULT_HARVEST_JSON = REPORTS_DIR / "btst_carryover_aligned_peer_harvest_latest.json"
DEFAULT_MULTIDAY_AUDIT_JSON = REPORTS_DIR / "btst_carryover_multiday_continuation_audit_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_carryover_peer_expansion_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_carryover_peer_expansion_latest.md"
SCOPE_PRIORITY = {
    "same_family_source_score_catalyst": 3,
    "same_source_score": 2,
    "same_family_source": 1,
}
EXPANSION_STATUS_PRIORITY = {
    "promotion_review_ready": 5,
    "next_day_watch_priority": 4,
    "next_day_watch_with_history_risk": 3,
    "open_cycle_priority": 2,
    "open_cycle_with_history_risk": 1,
    "closed_cycle_reject": 0,
    "deprioritized": -1,
}


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_historical_concerns(multiday_audit: dict[str, Any]) -> dict[str, dict[str, Any]]:
    selected_ticker = str(multiday_audit.get("selected_ticker") or "")
    concerns: dict[str, dict[str, Any]] = {}
    for raw_row in list(multiday_audit.get("supportive_cohort_rows") or []):
        row = dict(raw_row or {})
        ticker = str(row.get("ticker") or "")
        if not ticker or ticker == selected_ticker:
            continue
        concern_tags: list[str] = []
        if str(row.get("peer_evidence_status") or "") == "broad_family_only":
            concern_tags.append("broad_family_only_history")
        next_close_return = _safe_float(row.get("next_close_return"))
        if next_close_return is not None and next_close_return <= 0:
            concern_tags.append("negative_next_close_history")
        t_plus_2_close_return = _safe_float(row.get("t_plus_2_close_return"))
        if t_plus_2_close_return is not None and t_plus_2_close_return <= 0:
            concern_tags.append("non_positive_t_plus_2_history")
        if not concern_tags:
            continue
        current = concerns.get(ticker)
        candidate = {
            "ticker": ticker,
            "concern_tags": concern_tags,
            "peer_evidence_status": row.get("peer_evidence_status"),
            "trade_date": row.get("trade_date"),
            "cycle_status": row.get("cycle_status"),
            "next_close_return": next_close_return,
            "t_plus_2_close_return": t_plus_2_close_return,
            "score_target": _safe_float(row.get("score_target")),
        }
        candidate_rank = (
            len(concern_tags),
            1 if t_plus_2_close_return is not None else 0,
            1 if next_close_return is not None else 0,
            str(row.get("trade_date") or ""),
        )
        current_rank = (
            len((current or {}).get("concern_tags") or []),
            1 if current and current.get("t_plus_2_close_return") is not None else 0,
            1 if current and current.get("next_close_return") is not None else 0,
            str((current or {}).get("trade_date") or ""),
        )
        if current is None or candidate_rank > current_rank:
            concerns[ticker] = candidate
    return concerns


def _classify_expansion_status(harvest_status: str, concern_tags: list[str]) -> str:
    if harvest_status == "promotion_review_ready":
        return "promotion_review_ready"
    if harvest_status == "next_day_watch":
        return "next_day_watch_with_history_risk" if concern_tags else "next_day_watch_priority"
    if harvest_status == "fresh_open_cycle":
        return "open_cycle_with_history_risk" if concern_tags else "open_cycle_priority"
    if harvest_status == "closed_cycle_weak":
        return "closed_cycle_reject"
    return "deprioritized"


def _build_entry_recommendation(entry: dict[str, Any]) -> str:
    ticker = str(entry.get("ticker") or "")
    status = str(entry.get("expansion_status") or "")
    if status == "promotion_review_ready":
        return f"{ticker} 已具备 closed-cycle 正兑现，可进入极窄 peer promotion review。"
    if status == "next_day_watch_priority":
        return f"{ticker} 是当前最先闭环的 aligned peer，应优先盯 next-day -> T+2 兑现。"
    if status == "next_day_watch_with_history_risk":
        return f"{ticker} 虽然已到 next-day watch，但历史曾出现 broad-family-only / 兑现偏弱信号，只能保留 close-loop 观察。"
    if status == "open_cycle_priority":
        return f"{ticker} 是当前最值得扩样的 open-cycle aligned peer，应优先保留到 next-day/T+2 队列。"
    if status == "open_cycle_with_history_risk":
        return f"{ticker} 虽在 open-cycle 面里，但历史已暴露风险，暂不把它当成 lane 扩容依据。"
    if status == "closed_cycle_reject":
        return f"{ticker} 已出现 closed-cycle 弱兑现，只能作为反例，不进入扩样主队列。"
    return f"{ticker} 当前不构成 carryover peer expansion 的优先目标。"


def analyze_btst_carryover_peer_expansion(
    harvest_json_path: str | Path,
    multiday_audit_json_path: str | Path,
) -> dict[str, Any]:
    harvest = _load_json(harvest_json_path)
    multiday_audit = _load_json(multiday_audit_json_path)
    concerns = _build_historical_concerns(multiday_audit)
    entries = _build_expansion_entries(harvest, concerns)
    return _build_peer_expansion_analysis(harvest=harvest, multiday_audit=multiday_audit, entries=entries)


def _build_expansion_entries(
    harvest: dict[str, Any],
    concerns: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for raw_entry in list(harvest.get("harvest_entries") or []):
        entry = dict(raw_entry or {})
        ticker = str(entry.get("ticker") or "")
        concern = dict(concerns.get(ticker) or {})
        concern_tags = list(concern.get("concern_tags") or [])
        expansion_status = _classify_expansion_status(str(entry.get("harvest_status") or ""), concern_tags)
        entries.append(
            {
                "ticker": ticker,
                "harvest_status": entry.get("harvest_status"),
                "expansion_status": expansion_status,
                "latest_trade_date": entry.get("latest_trade_date"),
                "latest_scope": entry.get("latest_scope"),
                "latest_score_target": entry.get("latest_score_target"),
                "occurrence_count": entry.get("occurrence_count"),
                "scope_counts": dict(entry.get("scope_counts") or {}),
                "next_day_available_count": entry.get("next_day_available_count"),
                "closed_cycle_count": entry.get("closed_cycle_count"),
                "concern_tags": concern_tags,
                "historical_concern_trade_date": concern.get("trade_date"),
                "historical_concern_cycle_status": concern.get("cycle_status"),
                "historical_concern_next_close_return": concern.get("next_close_return"),
                "historical_concern_t_plus_2_close_return": concern.get("t_plus_2_close_return"),
                "recommendation": _build_entry_recommendation({"ticker": ticker, "expansion_status": expansion_status}),
            }
        )
    entries.sort(
        key=lambda entry: (
            EXPANSION_STATUS_PRIORITY.get(str(entry.get("expansion_status") or ""), -99),
            int(SCOPE_PRIORITY.get(str(entry.get("latest_scope") or ""), 0)),
            float(entry.get("latest_score_target") or 0.0),
            str(entry.get("latest_trade_date") or ""),
            str(entry.get("ticker") or ""),
        ),
        reverse=True,
    )
    return entries


def _build_peer_expansion_analysis(
    *,
    harvest: dict[str, Any],
    multiday_audit: dict[str, Any],
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    priority_expansion_tickers = [
        str(entry.get("ticker") or "")
        for entry in entries
        if str(entry.get("expansion_status") or "") in {"promotion_review_ready", "next_day_watch_priority", "open_cycle_priority"}
    ][:4]
    watch_with_risk_tickers = [
        str(entry.get("ticker") or "")
        for entry in entries
        if str(entry.get("expansion_status") or "") in {"next_day_watch_with_history_risk", "open_cycle_with_history_risk"}
    ][:4]
    focus = entries[0] if entries else {}
    recommendation_parts: list[str] = []
    if focus:
        recommendation_parts.append(f"当前 expansion 第一优先是 {focus.get('ticker')}，status={focus.get('expansion_status')}。")
    if priority_expansion_tickers:
        recommendation_parts.append(f"主扩样队列先看 {priority_expansion_tickers}。")
    if watch_with_risk_tickers:
        recommendation_parts.append(f"{watch_with_risk_tickers} 仅保留 watch-with-risk 语义，不作为放宽 carryover lane 的依据。")
    if bool(dict(multiday_audit.get("policy_checks") or {}).get("selected_path_t2_bias_only")):
        recommendation_parts.append("在第二个 aligned peer 真正闭环前，002001 仍只应按 T+2 bias 的单票证据处理。")
    recommendation = " ".join(recommendation_parts) if recommendation_parts else "当前没有可用的 carryover peer expansion 队列。"
    return {
        "ticker": harvest.get("ticker") or multiday_audit.get("selected_ticker"),
        "selected_ticker": multiday_audit.get("selected_ticker"),
        "selected_path_t2_bias_only": dict(multiday_audit.get("policy_checks") or {}).get("selected_path_t2_bias_only"),
        "broad_family_only_multiday_unsupported": dict(multiday_audit.get("policy_checks") or {}).get("broad_family_only_multiday_unsupported"),
        "peer_count": len(entries),
        "expansion_status_counts": dict(Counter(str(entry.get("expansion_status") or "") for entry in entries)),
        "priority_expansion_tickers": priority_expansion_tickers,
        "watch_with_risk_tickers": watch_with_risk_tickers,
        "focus_ticker": focus.get("ticker") if focus else None,
        "focus_status": focus.get("expansion_status") if focus else None,
        "entries": entries,
        "recommendation": recommendation,
    }


def render_btst_carryover_peer_expansion_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Carryover Peer Expansion")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- ticker: {analysis.get('ticker')}")
    lines.append(f"- selected_ticker: {analysis.get('selected_ticker')}")
    lines.append(f"- selected_path_t2_bias_only: {analysis.get('selected_path_t2_bias_only')}")
    lines.append(f"- broad_family_only_multiday_unsupported: {analysis.get('broad_family_only_multiday_unsupported')}")
    lines.append(f"- peer_count: {analysis.get('peer_count')}")
    lines.append(f"- expansion_status_counts: {analysis.get('expansion_status_counts')}")
    lines.append(f"- priority_expansion_tickers: {analysis.get('priority_expansion_tickers')}")
    lines.append(f"- watch_with_risk_tickers: {analysis.get('watch_with_risk_tickers')}")
    lines.append(f"- focus_ticker: {analysis.get('focus_ticker')}")
    lines.append(f"- focus_status: {analysis.get('focus_status')}")
    lines.append("")
    lines.append("## Expansion Entries")
    for entry in list(analysis.get("entries") or []):
        lines.append(
            f"- {entry.get('ticker')}: expansion_status={entry.get('expansion_status')}, harvest_status={entry.get('harvest_status')}, "
            f"latest_trade_date={entry.get('latest_trade_date')}, latest_scope={entry.get('latest_scope')}, latest_score_target={entry.get('latest_score_target')}, "
            f"concern_tags={entry.get('concern_tags')}"
        )
        lines.append(f"  recommendation: {entry.get('recommendation')}")
    if not list(analysis.get("entries") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis.get('recommendation')}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Rank carryover peer expansion targets so open-cycle aligned peers and watch-with-risk names are separated.")
    parser.add_argument("--harvest-json", default=str(DEFAULT_HARVEST_JSON))
    parser.add_argument("--multiday-audit-json", default=str(DEFAULT_MULTIDAY_AUDIT_JSON))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_carryover_peer_expansion(args.harvest_json, args.multiday_audit_json)
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_carryover_peer_expansion_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
