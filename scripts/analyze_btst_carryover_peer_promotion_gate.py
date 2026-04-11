from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.btst_selected_focus import pick_selected_focus_entry


REPORTS_DIR = Path("data/reports")
DEFAULT_PROOF_BOARD_JSON = REPORTS_DIR / "btst_carryover_aligned_peer_proof_board_latest.json"
DEFAULT_SELECTED_REFRESH_JSON = REPORTS_DIR / "btst_selected_outcome_refresh_board_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_carryover_peer_promotion_gate_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_carryover_peer_promotion_gate_latest.md"
GATE_PRIORITY = {
    "promotion_gate_ready": 4,
    "requires_history_risk_review": 3,
    "blocked_selected_contract_open": 2,
    "await_peer_t_plus_2_close": 1,
    "await_peer_next_day_close": 0,
    "blocked_selected_contract_violated": -1,
    "not_promotion_ready": -2,
}


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))


def _classify_gate_verdict(entry: dict[str, Any], selected_contract_verdict: str) -> tuple[str, list[str]]:
    promotion_review_verdict = str(entry.get("promotion_review_verdict") or "")
    blockers: list[str] = []
    if selected_contract_verdict in {"next_close_violated", "t_plus_2_violated"}:
        blockers.append(f"selected_contract={selected_contract_verdict}")
        return "blocked_selected_contract_violated", blockers
    if promotion_review_verdict == "ready_for_promotion_review":
        if selected_contract_verdict == "t_plus_2_confirmed":
            return "promotion_gate_ready", blockers
        blockers.append(f"selected_contract={selected_contract_verdict or 'pending_next_day'}")
        return "blocked_selected_contract_open", blockers
    if promotion_review_verdict == "requires_history_risk_review":
        blockers.extend(list(entry.get("concern_tags") or []))
        if selected_contract_verdict != "t_plus_2_confirmed":
            blockers.append(f"selected_contract={selected_contract_verdict or 'pending_next_day'}")
        return "requires_history_risk_review", blockers
    if promotion_review_verdict == "await_t_plus_2_close":
        blockers.extend(list(entry.get("blockers") or []))
        return "await_peer_t_plus_2_close", blockers
    if promotion_review_verdict == "await_next_day_close":
        blockers.extend(list(entry.get("blockers") or []))
        return "await_peer_next_day_close", blockers
    blockers.extend(list(entry.get("blockers") or []))
    return "not_promotion_ready", blockers


def _build_entry_recommendation(entry: dict[str, Any]) -> str:
    ticker = str(entry.get("ticker") or "")
    gate_verdict = str(entry.get("gate_verdict") or "")
    if gate_verdict == "promotion_gate_ready":
        return f"{ticker} 已满足第二个 aligned peer 的 promotion gate，可进入极窄 lane expansion review。"
    if gate_verdict == "blocked_selected_contract_open":
        return f"{ticker} 自身 proof 已够，但 002001 合约仍未闭环，暂不提前扩容。"
    if gate_verdict == "requires_history_risk_review":
        return f"{ticker} 需要先做 history-risk review，未通过前不进入正式 promotion gate。"
    if gate_verdict == "await_peer_t_plus_2_close":
        return f"{ticker} 已过 next-close，当前只看 T+2 是否继续转强。"
    if gate_verdict == "await_peer_next_day_close":
        return f"{ticker} 仍缺 next-day 兑现，先等第一段 close-loop。"
    if gate_verdict == "blocked_selected_contract_violated":
        return f"{ticker} 即使自身有机会，主票合约已违约，当前必须先收紧而不是扩容。"
    return f"{ticker} 当前不满足 carryover peer promotion gate。"


def analyze_btst_carryover_peer_promotion_gate(
    proof_board_json_path: str | Path,
    selected_refresh_json_path: str | Path,
) -> dict[str, Any]:
    proof_board = _load_json(proof_board_json_path)
    selected_refresh = _load_json(selected_refresh_json_path)

    selected_entries = [dict(entry or {}) for entry in list(selected_refresh.get("entries") or [])]
    selected_focus = pick_selected_focus_entry(selected_entries)
    selected_contract_verdict = str(selected_focus.get("overall_contract_verdict") or proof_board.get("selected_contract_verdict") or "")
    entries = _build_gate_entries(proof_board, selected_contract_verdict)
    return _build_peer_promotion_gate_analysis(
        proof_board=proof_board,
        selected_focus=selected_focus,
        selected_contract_verdict=selected_contract_verdict,
        entries=entries,
    )


def _build_gate_entries(proof_board: dict[str, Any], selected_contract_verdict: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for raw_entry in list(proof_board.get("entries") or []):
        entry = dict(raw_entry or {})
        gate_verdict, gate_blockers = _classify_gate_verdict(entry, selected_contract_verdict)
        gate_entry = {
            "ticker": entry.get("ticker"),
            "proof_verdict": entry.get("proof_verdict"),
            "promotion_review_verdict": entry.get("promotion_review_verdict"),
            "gate_verdict": gate_verdict,
            "latest_trade_date": entry.get("latest_trade_date"),
            "latest_scope": entry.get("latest_scope"),
            "best_closed_trade_date": entry.get("best_closed_trade_date"),
            "best_closed_next_close_return": entry.get("best_closed_next_close_return"),
            "best_closed_t_plus_2_close_return": entry.get("best_closed_t_plus_2_close_return"),
            "concern_tags": list(entry.get("concern_tags") or []),
            "gate_blockers": gate_blockers,
        }
        gate_entry["recommendation"] = _build_entry_recommendation(gate_entry)
        entries.append(gate_entry)

    entries.sort(
        key=lambda entry: (
            GATE_PRIORITY.get(str(entry.get("gate_verdict") or ""), -99),
            str(entry.get("latest_trade_date") or ""),
            str(entry.get("ticker") or ""),
        ),
        reverse=True,
    )
    return entries


def _select_gate_focus_entry(
    entries: list[dict[str, Any]],
    *,
    proof_board: dict[str, Any],
    selected_contract_verdict: str,
) -> dict[str, Any]:
    if not entries:
        return {}
    proof_focus_ticker = str(proof_board.get("focus_ticker") or "").strip()
    if proof_focus_ticker:
        for entry in entries:
            if str(entry.get("ticker") or "").strip() == proof_focus_ticker:
                return entry
    if selected_contract_verdict not in {"next_close_violated", "t_plus_2_violated"}:
        return entries[0]
    return entries[0]


def _prioritize_focus_ticker(tickers: list[str], focus_ticker: str, *, limit: int = 4) -> list[str]:
    normalized_focus_ticker = str(focus_ticker or "").strip()
    ordered = [str(ticker).strip() for ticker in tickers if str(ticker).strip()]
    if normalized_focus_ticker and normalized_focus_ticker in ordered:
        ordered = [normalized_focus_ticker] + [ticker for ticker in ordered if ticker != normalized_focus_ticker]
    return ordered[:limit]


def _build_peer_promotion_gate_analysis(
    *,
    proof_board: dict[str, Any],
    selected_focus: dict[str, Any],
    selected_contract_verdict: str,
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    focus = _select_gate_focus_entry(
        entries,
        proof_board=proof_board,
        selected_contract_verdict=selected_contract_verdict,
    )
    focus_ticker = str(focus.get("ticker") or "").strip()
    ready_tickers = _prioritize_focus_ticker(
        [str(entry.get("ticker") or "") for entry in entries if str(entry.get("gate_verdict") or "") == "promotion_gate_ready"],
        focus_ticker,
    )
    blocked_open_tickers = _prioritize_focus_ticker(
        [str(entry.get("ticker") or "") for entry in entries if str(entry.get("gate_verdict") or "") == "blocked_selected_contract_open"],
        focus_ticker,
    )
    risk_review_tickers = _prioritize_focus_ticker(
        [str(entry.get("ticker") or "") for entry in entries if str(entry.get("gate_verdict") or "") == "requires_history_risk_review"],
        focus_ticker,
    )
    pending_t_plus_2_tickers = _prioritize_focus_ticker(
        [str(entry.get("ticker") or "") for entry in entries if str(entry.get("gate_verdict") or "") == "await_peer_t_plus_2_close"],
        focus_ticker,
    )

    recommendation_parts: list[str] = []
    if ready_tickers:
        recommendation_parts.append(f"当前已满足 promotion gate 的 peer: {ready_tickers}。")
    elif blocked_open_tickers:
        recommendation_parts.append(f"{blocked_open_tickers} 的 peer proof 已够，但仍被 002001 未闭环的 contract 挡住。")
    elif risk_review_tickers:
        recommendation_parts.append(f"{risk_review_tickers} 需先完成 history-risk review。")
    elif pending_t_plus_2_tickers:
        recommendation_parts.append(f"当前最关键的是等待 {pending_t_plus_2_tickers} 的 T+2 闭环。")
    elif focus.get("ticker"):
        recommendation_parts.append(f"当前 promotion gate focus 是 {focus.get('ticker')}，gate_verdict={focus.get('gate_verdict')}。")
    recommendation_parts.append(
        f"formal selected {selected_focus.get('ticker') or proof_board.get('selected_ticker')} 当前 contract={selected_contract_verdict or 'pending_next_day'}。"
    )
    return {
        "selected_ticker": selected_focus.get("ticker") or proof_board.get("selected_ticker"),
        "selected_trade_date": selected_focus.get("trade_date") or proof_board.get("selected_trade_date"),
        "selected_contract_verdict": selected_contract_verdict or "pending_next_day",
        "peer_count": len(entries),
        "gate_verdict_counts": {verdict: sum(1 for entry in entries if str(entry.get("gate_verdict") or "") == verdict) for verdict in sorted({str(entry.get("gate_verdict") or "") for entry in entries})},
        "ready_tickers": ready_tickers,
        "blocked_open_tickers": blocked_open_tickers,
        "risk_review_tickers": risk_review_tickers,
        "pending_t_plus_2_tickers": pending_t_plus_2_tickers,
        "focus_ticker": focus.get("ticker") if focus else None,
        "focus_gate_verdict": focus.get("gate_verdict") if focus else None,
        "entries": entries,
        "recommendation": " ".join(recommendation_parts),
    }


def render_btst_carryover_peer_promotion_gate_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Carryover Peer Promotion Gate")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- selected_ticker: {analysis.get('selected_ticker')}")
    lines.append(f"- selected_trade_date: {analysis.get('selected_trade_date')}")
    lines.append(f"- selected_contract_verdict: {analysis.get('selected_contract_verdict')}")
    lines.append(f"- peer_count: {analysis.get('peer_count')}")
    lines.append(f"- gate_verdict_counts: {analysis.get('gate_verdict_counts')}")
    lines.append(f"- ready_tickers: {analysis.get('ready_tickers')}")
    lines.append(f"- blocked_open_tickers: {analysis.get('blocked_open_tickers')}")
    lines.append(f"- risk_review_tickers: {analysis.get('risk_review_tickers')}")
    lines.append(f"- pending_t_plus_2_tickers: {analysis.get('pending_t_plus_2_tickers')}")
    lines.append(f"- focus_ticker: {analysis.get('focus_ticker')}")
    lines.append(f"- focus_gate_verdict: {analysis.get('focus_gate_verdict')}")
    lines.append("")
    lines.append("## Entries")
    for entry in list(analysis.get("entries") or []):
        lines.append(
            f"- {entry.get('ticker')}: gate_verdict={entry.get('gate_verdict')}, proof_verdict={entry.get('proof_verdict')}, promotion_review_verdict={entry.get('promotion_review_verdict')}, gate_blockers={entry.get('gate_blockers')}"
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
    parser = argparse.ArgumentParser(description="Turn aligned peer proof verdicts into a narrow promotion gate so lane expansion only happens after both peer proof and selected-contract checks pass.")
    parser.add_argument("--proof-board-json", default=str(DEFAULT_PROOF_BOARD_JSON))
    parser.add_argument("--selected-refresh-json", default=str(DEFAULT_SELECTED_REFRESH_JSON))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_carryover_peer_promotion_gate(args.proof_board_json, args.selected_refresh_json)
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_carryover_peer_promotion_gate_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
