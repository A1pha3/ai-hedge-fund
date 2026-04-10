from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPORTS_DIR = Path("data/reports")
DEFAULT_HARVEST_JSON = REPORTS_DIR / "btst_carryover_aligned_peer_harvest_latest.json"
DEFAULT_PEER_EXPANSION_JSON = REPORTS_DIR / "btst_carryover_peer_expansion_latest.json"
DEFAULT_SELECTED_REFRESH_JSON = REPORTS_DIR / "btst_selected_outcome_refresh_board_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_carryover_aligned_peer_proof_board_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_carryover_aligned_peer_proof_board_latest.md"
SCOPE_PRIORITY = {
    "same_family_source_score_catalyst": 3,
    "same_source_score": 2,
    "same_family_source": 1,
}
PROMOTION_VERDICT_PRIORITY = {
    "ready_for_promotion_review": 4,
    "requires_history_risk_review": 3,
    "await_t_plus_2_close": 2,
    "await_next_day_close": 1,
    "not_promotion_ready": 0,
}


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _best_closed_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    closed_rows = [dict(row or {}) for row in rows if _safe_float((row or {}).get("t_plus_2_close_return")) is not None]
    if not closed_rows:
        return {}
    return max(
        closed_rows,
        key=lambda row: (
            1 if (_safe_float(row.get("next_close_return")) or -999.0) > 0 and (_safe_float(row.get("t_plus_2_close_return")) or -999.0) > 0 and (_safe_float(row.get("next_high_return")) or -999.0) >= 0.02 else 0,
            1 if (_safe_float(row.get("t_plus_2_close_return")) or -999.0) > 0 else 0,
            1 if (_safe_float(row.get("next_close_return")) or -999.0) > 0 else 0,
            _safe_float(row.get("next_high_return")) or -999.0,
            _safe_float(row.get("t_plus_2_close_return")) or -999.0,
            _safe_float(row.get("next_close_return")) or -999.0,
            int(SCOPE_PRIORITY.get(str(row.get("scope") or ""), 0)),
            str(row.get("trade_date") or ""),
        ),
    )


def _classify_peer_proof(latest_row: dict[str, Any], best_closed_row: dict[str, Any], concern_tags: list[str]) -> tuple[str, str, list[str]]:
    blockers: list[str] = []
    latest_next_close_return = _safe_float(latest_row.get("next_close_return"))
    closed_next_close_return = _safe_float(best_closed_row.get("next_close_return"))
    closed_t_plus_2_return = _safe_float(best_closed_row.get("t_plus_2_close_return"))
    closed_next_high_return = _safe_float(best_closed_row.get("next_high_return"))

    if concern_tags:
        blockers.extend(concern_tags)

    if best_closed_row:
        if closed_next_close_return is not None and closed_next_close_return <= 0:
            blockers.append("negative_next_close")
            return "rejected_negative_next_close", "not_promotion_ready", blockers
        if closed_t_plus_2_return is not None and closed_t_plus_2_return <= 0:
            blockers.append("negative_t_plus_2_close")
            return "rejected_negative_t_plus_2", "not_promotion_ready", blockers
        if closed_next_high_return is not None and closed_next_high_return < 0.02:
            blockers.append("next_high_below_breakout_quality")
            return "rejected_low_extension_quality", "not_promotion_ready", blockers
        if concern_tags:
            return "supportive_with_history_risk", "requires_history_risk_review", blockers
        return "supportive_closed_cycle", "ready_for_promotion_review", blockers

    if latest_next_close_return is not None:
        if latest_next_close_return > 0:
            blockers.append("await_t_plus_2_bar")
            return "pending_t_plus_2_close", "await_t_plus_2_close", blockers
        blockers.append("negative_next_close")
        return "rejected_negative_next_close", "not_promotion_ready", blockers

    if latest_row:
        blockers.append("await_next_day_bar")
        return "pending_next_day_close", "await_next_day_close", blockers

    blockers.append("missing_close_loop_data")
    return "no_close_loop_data", "not_promotion_ready", blockers


def _build_entry_recommendation(entry: dict[str, Any]) -> str:
    ticker = str(entry.get("ticker") or "")
    promotion_review_verdict = str(entry.get("promotion_review_verdict") or "")
    proof_verdict = str(entry.get("proof_verdict") or "")
    if promotion_review_verdict == "ready_for_promotion_review":
        return f"{ticker} 已形成 supportive closed-cycle，可进入第二个 aligned peer promotion review。"
    if promotion_review_verdict == "requires_history_risk_review":
        return f"{ticker} 虽然 closed-cycle 支撑为正，但历史风险未解除，只能走 risk-reviewed promotion review。"
    if promotion_review_verdict == "await_t_plus_2_close":
        return f"{ticker} 已有正 next-close，下一步只看 T+2 是否继续转强。"
    if promotion_review_verdict == "await_next_day_close":
        return f"{ticker} 仍缺 next-day 结果，暂时不能把它当成第二个有效 close-loop。"
    if proof_verdict.startswith("rejected_"):
        return f"{ticker} 的 closed-cycle 兑现不足，当前只能作为反例，不能支持 carryover lane 扩容。"
    return f"{ticker} 当前没有足够 close-loop 数据，不进入 promotion proof 主链。"


def analyze_btst_carryover_aligned_peer_proof_board(
    harvest_json_path: str | Path,
    peer_expansion_json_path: str | Path,
    selected_refresh_json_path: str | Path,
) -> dict[str, Any]:
    harvest = _load_json(harvest_json_path)
    peer_expansion = _load_json(peer_expansion_json_path)
    selected_refresh = _load_json(selected_refresh_json_path)

    harvest_entries = {str(entry.get("ticker") or ""): dict(entry or {}) for entry in list(harvest.get("harvest_entries") or [])}
    expansion_entries = [dict(entry or {}) for entry in list(peer_expansion.get("entries") or [])]
    selected_entries = [dict(entry or {}) for entry in list(selected_refresh.get("entries") or [])]
    selected_focus = selected_entries[0] if selected_entries else {}

    entries: list[dict[str, Any]] = []
    for expansion_entry in expansion_entries:
        ticker = str(expansion_entry.get("ticker") or "")
        harvest_entry = dict(harvest_entries.get(ticker) or {})
        rows = [dict(row or {}) for row in list(harvest_entry.get("rows") or [])]
        latest_row = rows[0] if rows else {}
        best_closed_row = _best_closed_row(rows)
        concern_tags = list(expansion_entry.get("concern_tags") or [])
        proof_verdict, promotion_review_verdict, blockers = _classify_peer_proof(latest_row, best_closed_row, concern_tags)
        entry = {
            "ticker": ticker,
            "harvest_status": expansion_entry.get("harvest_status") or harvest_entry.get("harvest_status"),
            "expansion_status": expansion_entry.get("expansion_status"),
            "proof_verdict": proof_verdict,
            "promotion_review_verdict": promotion_review_verdict,
            "latest_trade_date": expansion_entry.get("latest_trade_date") or harvest_entry.get("latest_trade_date"),
            "latest_scope": expansion_entry.get("latest_scope") or harvest_entry.get("latest_scope"),
            "latest_score_target": expansion_entry.get("latest_score_target") or harvest_entry.get("latest_score_target"),
            "latest_next_close_return": _safe_float(latest_row.get("next_close_return")),
            "best_closed_trade_date": best_closed_row.get("trade_date"),
            "best_closed_scope": best_closed_row.get("scope"),
            "best_closed_next_high_return": _safe_float(best_closed_row.get("next_high_return")),
            "best_closed_next_close_return": _safe_float(best_closed_row.get("next_close_return")),
            "best_closed_t_plus_2_close_return": _safe_float(best_closed_row.get("t_plus_2_close_return")),
            "closed_cycle_count": harvest_entry.get("closed_cycle_count"),
            "next_day_available_count": harvest_entry.get("next_day_available_count"),
            "concern_tags": concern_tags,
            "blockers": blockers,
        }
        entry["recommendation"] = _build_entry_recommendation(entry)
        entries.append(entry)

    entries.sort(
        key=lambda entry: (
            PROMOTION_VERDICT_PRIORITY.get(str(entry.get("promotion_review_verdict") or ""), -1),
            int(SCOPE_PRIORITY.get(str(entry.get("latest_scope") or ""), 0)),
            float(entry.get("latest_score_target") or 0.0),
            str(entry.get("latest_trade_date") or ""),
            str(entry.get("ticker") or ""),
        ),
        reverse=True,
    )

    ready_for_promotion_review_tickers = [
        str(entry.get("ticker") or "") for entry in entries if str(entry.get("promotion_review_verdict") or "") == "ready_for_promotion_review"
    ][:4]
    risk_review_tickers = [
        str(entry.get("ticker") or "") for entry in entries if str(entry.get("promotion_review_verdict") or "") == "requires_history_risk_review"
    ][:4]
    pending_t_plus_2_tickers = [
        str(entry.get("ticker") or "") for entry in entries if str(entry.get("promotion_review_verdict") or "") == "await_t_plus_2_close"
    ][:4]
    focus = entries[0] if entries else {}

    recommendation_parts: list[str] = []
    if ready_for_promotion_review_tickers:
        recommendation_parts.append(f"当前已经拿到 supportive aligned peer close-loop：{ready_for_promotion_review_tickers}，可进入 promotion review。")
    elif risk_review_tickers:
        recommendation_parts.append(f"{risk_review_tickers} 虽有 supportive close-loop，但历史风险未清，只能走 risk review。")
    elif pending_t_plus_2_tickers:
        recommendation_parts.append(f"当前最关键的是等待 {pending_t_plus_2_tickers} 的 T+2 闭环。")
    elif focus.get("ticker"):
        recommendation_parts.append(f"当前 proof focus 是 {focus.get('ticker')}，verdict={focus.get('proof_verdict')}。")
    if selected_focus:
        recommendation_parts.append(
            f"formal selected {selected_focus.get('ticker')} 当前 contract={selected_focus.get('overall_contract_verdict')}，在第二个 aligned peer 真正闭环前仍维持 T+2 bias 语义。"
        )
    recommendation = " ".join(recommendation_parts) if recommendation_parts else "当前没有可用于 aligned peer promotion proof 的有效 close-loop。"

    return {
        "selected_ticker": selected_focus.get("ticker") or peer_expansion.get("selected_ticker") or harvest.get("ticker"),
        "selected_trade_date": selected_focus.get("trade_date") or selected_refresh.get("trade_date"),
        "selected_cycle_status": selected_focus.get("current_cycle_status"),
        "selected_contract_verdict": selected_focus.get("overall_contract_verdict"),
        "peer_count": len(entries),
        "proof_verdict_counts": {verdict: sum(1 for entry in entries if str(entry.get("proof_verdict") or "") == verdict) for verdict in sorted({str(entry.get("proof_verdict") or "") for entry in entries})},
        "promotion_review_verdict_counts": {
            verdict: sum(1 for entry in entries if str(entry.get("promotion_review_verdict") or "") == verdict)
            for verdict in sorted({str(entry.get("promotion_review_verdict") or "") for entry in entries})
        },
        "ready_for_promotion_review_tickers": ready_for_promotion_review_tickers,
        "risk_review_tickers": risk_review_tickers,
        "pending_t_plus_2_tickers": pending_t_plus_2_tickers,
        "focus_ticker": focus.get("ticker") if focus else None,
        "focus_proof_verdict": focus.get("proof_verdict") if focus else None,
        "focus_promotion_review_verdict": focus.get("promotion_review_verdict") if focus else None,
        "entries": entries,
        "recommendation": recommendation,
    }


def render_btst_carryover_aligned_peer_proof_board_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Carryover Aligned Peer Proof Board")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- selected_ticker: {analysis.get('selected_ticker')}")
    lines.append(f"- selected_trade_date: {analysis.get('selected_trade_date')}")
    lines.append(f"- selected_cycle_status: {analysis.get('selected_cycle_status')}")
    lines.append(f"- selected_contract_verdict: {analysis.get('selected_contract_verdict')}")
    lines.append(f"- peer_count: {analysis.get('peer_count')}")
    lines.append(f"- proof_verdict_counts: {analysis.get('proof_verdict_counts')}")
    lines.append(f"- promotion_review_verdict_counts: {analysis.get('promotion_review_verdict_counts')}")
    lines.append(f"- ready_for_promotion_review_tickers: {analysis.get('ready_for_promotion_review_tickers')}")
    lines.append(f"- risk_review_tickers: {analysis.get('risk_review_tickers')}")
    lines.append(f"- pending_t_plus_2_tickers: {analysis.get('pending_t_plus_2_tickers')}")
    lines.append(f"- focus_ticker: {analysis.get('focus_ticker')}")
    lines.append(f"- focus_proof_verdict: {analysis.get('focus_proof_verdict')}")
    lines.append(f"- focus_promotion_review_verdict: {analysis.get('focus_promotion_review_verdict')}")
    lines.append("")
    lines.append("## Entries")
    for entry in list(analysis.get("entries") or []):
        lines.append(
            f"- {entry.get('ticker')}: proof_verdict={entry.get('proof_verdict')}, promotion_review_verdict={entry.get('promotion_review_verdict')}, "
            f"latest_trade_date={entry.get('latest_trade_date')}, latest_scope={entry.get('latest_scope')}, "
            f"best_closed_trade_date={entry.get('best_closed_trade_date')}, best_closed_next_close_return={entry.get('best_closed_next_close_return')}, "
            f"best_closed_t_plus_2_close_return={entry.get('best_closed_t_plus_2_close_return')}, blockers={entry.get('blockers')}"
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
    parser = argparse.ArgumentParser(description="Convert aligned peer close-loop rows into promotion-proof verdicts so carryover expansion can stay evidence-backed.")
    parser.add_argument("--harvest-json", default=str(DEFAULT_HARVEST_JSON))
    parser.add_argument("--peer-expansion-json", default=str(DEFAULT_PEER_EXPANSION_JSON))
    parser.add_argument("--selected-refresh-json", default=str(DEFAULT_SELECTED_REFRESH_JSON))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_carryover_aligned_peer_proof_board(args.harvest_json, args.peer_expansion_json, args.selected_refresh_json)
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_carryover_aligned_peer_proof_board_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
