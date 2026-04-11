from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.analyze_btst_selected_outcome_proof import (
    _extract_holding_outcome,
    analyze_btst_selected_outcome_proof,
)


REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_selected_outcome_refresh_board_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_selected_outcome_refresh_board_latest.md"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_latest_selected_snapshot(reports_root: str | Path) -> tuple[Path, dict[str, Any]]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    candidates: list[tuple[tuple[str, int, str], Path, dict[str, Any]]] = []
    for snapshot_path in resolved_reports_root.glob("**/selection_artifacts/*/selection_snapshot.json"):
        snapshot = _load_json(snapshot_path)
        selected_count = sum(
            1
            for payload in dict(snapshot.get("selection_targets") or {}).values()
            if str(((payload or {}).get("short_trade") or {}).get("decision") or "") == "selected"
        )
        if selected_count <= 0:
            continue
        trade_date = str(snapshot.get("trade_date") or snapshot_path.parent.name)
        candidates.append(((trade_date, selected_count, str(snapshot_path.parents[2])), snapshot_path, snapshot))
    if not candidates:
        raise ValueError("No BTST snapshot with formal selected entries found")
    _, snapshot_path, snapshot = max(candidates, key=lambda item: item[0])
    return snapshot_path, snapshot


def _selected_tickers(snapshot: dict[str, Any]) -> list[str]:
    tickers = [
        str(ticker)
        for ticker, payload in dict(snapshot.get("selection_targets") or {}).items()
        if str(((payload or {}).get("short_trade") or {}).get("decision") or "") == "selected"
    ]
    return sorted(tickers)


def _build_recommendation(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return "当前没有 formal selected，refresh board 暂无可跟踪主票。"
    confirmed_entries = [entry for entry in entries if str(entry.get("overall_contract_verdict") or "") == "t_plus_2_confirmed"]
    closed_without_positive_expectation_entries = [
        entry for entry in entries if "observed_without_positive_expectation" in str(entry.get("overall_contract_verdict") or "")
    ]
    violated_entries = [entry for entry in entries if "violated" in str(entry.get("overall_contract_verdict") or "")]
    open_entries = [entry for entry in entries if str(entry.get("current_cycle_status") or "").startswith("missing") or entry.get("current_cycle_status") == "missing_next_day"]
    t1_entries = [entry for entry in entries if str(entry.get("current_cycle_status") or "") == "t1_only"]
    t2_plus_entries = [entry for entry in entries if str(entry.get("current_cycle_status") or "") in {"t_plus_2_closed", "t_plus_3_closed", "t_plus_4_closed"}]
    if violated_entries:
        return "至少有一只 formal selected 已出现 contract 违约，优先复核当前 next_close / T+2 兑现为何偏离 historical proof，再决定是否收紧 selected 语义。"
    if confirmed_entries:
        return "至少有一只 formal selected 已完成 T+2 contract 确认，可把 live realized 与 historical proof 一并作为 carryover lane 是否扩容的核心证据。"
    if closed_without_positive_expectation_entries:
        return "至少有一只 formal selected 已完成 closed-cycle，但历史并不要求 next-close/T+2 为正；应按已闭环 contract 复核执行质量，而不是继续把它当作 pending open case。"
    if t2_plus_entries:
        return "至少有一只 formal selected 已进入 T+2+ closed-cycle，可直接把当前兑现与 historical prior proof 对照，用于是否扩容 carryover lane。"
    if t1_entries:
        return "formal selected 已进入 next-day 可评估阶段，优先比较当前 next_close / T+2 兑现与 historical prior 是否一致。"
    if open_entries:
        return "formal selected 仍处于 open case，refresh board 应持续自动刷新，暂不基于未闭环结果改动策略阈值。"
    return "formal selected refresh board 已建立，后续只需随价格数据自动更新即可。"


def _historical_positive_expectation(rate: Any) -> bool:
    return rate is not None and float(rate) >= 0.5


def _resolve_cycle_contract_verdict(
    current_close_return: Any,
    *,
    expectation_positive: bool,
    pending_verdict: str,
) -> str:
    if current_close_return is None:
        return pending_verdict
    current_close_positive = float(current_close_return) > 0
    if expectation_positive:
        return "matched_positive_expectation" if current_close_positive else "violated_positive_expectation"
    return "observed_without_positive_expectation"


def _resolve_overall_contract_verdict(next_day_contract_verdict: str, t_plus_2_contract_verdict: str) -> str:
    if "violated" in next_day_contract_verdict:
        return "next_close_violated"
    if "violated" in t_plus_2_contract_verdict:
        return "t_plus_2_violated"
    if t_plus_2_contract_verdict == "matched_positive_expectation":
        return "t_plus_2_confirmed"
    if t_plus_2_contract_verdict == "observed_without_positive_expectation":
        return "t_plus_2_observed_without_positive_expectation"
    if next_day_contract_verdict == "matched_positive_expectation":
        return "next_close_confirmed_wait_t_plus_2"
    if next_day_contract_verdict == "observed_without_positive_expectation":
        return "next_close_observed_without_positive_expectation"
    return "pending_next_day"


def _resolve_contract_alignment(proof: dict[str, Any], current_outcome: dict[str, Any]) -> dict[str, Any]:
    proof_summary = dict(proof.get("summary") or {})
    current_next_close_return = current_outcome.get("next_close_return")
    current_t_plus_2_close_return = current_outcome.get("t_plus_2_close_return")
    historical_next_close_positive_rate = proof_summary.get("next_close_positive_rate")
    historical_t_plus_2_close_positive_rate = proof_summary.get("t_plus_2_close_positive_rate")

    next_day_expectation_positive = _historical_positive_expectation(historical_next_close_positive_rate)
    t_plus_2_expectation_positive = _historical_positive_expectation(historical_t_plus_2_close_positive_rate)
    next_day_contract_verdict = _resolve_cycle_contract_verdict(
        current_next_close_return,
        expectation_positive=next_day_expectation_positive,
        pending_verdict="pending_next_day",
    )
    t_plus_2_contract_verdict = _resolve_cycle_contract_verdict(
        current_t_plus_2_close_return,
        expectation_positive=t_plus_2_expectation_positive,
        pending_verdict="pending_t_plus_2",
    )
    overall_contract_verdict = _resolve_overall_contract_verdict(next_day_contract_verdict, t_plus_2_contract_verdict)

    return {
        "historical_next_close_expectation_positive": next_day_expectation_positive,
        "historical_t_plus_2_expectation_positive": t_plus_2_expectation_positive,
        "next_day_contract_verdict": next_day_contract_verdict,
        "t_plus_2_contract_verdict": t_plus_2_contract_verdict,
        "overall_contract_verdict": overall_contract_verdict,
    }


def analyze_btst_selected_outcome_refresh_board(reports_root: str | Path) -> dict[str, Any]:
    snapshot_path, snapshot = _resolve_latest_selected_snapshot(reports_root)
    report_dir = snapshot_path.parents[2]
    trade_date = str(snapshot.get("trade_date") or snapshot_path.parent.name)
    selected_tickers = _selected_tickers(snapshot)
    price_cache: dict[tuple[str, str], Any] = {}
    entries = _build_refresh_board_entries(
        report_dir=report_dir,
        trade_date=trade_date,
        selected_tickers=selected_tickers,
        price_cache=price_cache,
    )
    return _build_refresh_board_analysis(
        report_dir=report_dir,
        snapshot_path=snapshot_path,
        trade_date=trade_date,
        entries=entries,
    )


def _build_refresh_board_entries(
    *,
    report_dir: Path,
    trade_date: str,
    selected_tickers: list[str],
    price_cache: dict[tuple[str, str], Any],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for ticker in selected_tickers:
        proof = analyze_btst_selected_outcome_proof(report_dir, ticker=ticker)
        current_outcome = _extract_holding_outcome(ticker, trade_date, price_cache)
        contract_alignment = _resolve_contract_alignment(proof, current_outcome)
        entries.append(
            {
                "ticker": ticker,
                "trade_date": trade_date,
                "decision": proof.get("decision"),
                "candidate_source": proof.get("candidate_source"),
                "preferred_entry_mode": proof.get("preferred_entry_mode"),
                "score_target": proof.get("score_target"),
                "effective_select_threshold": proof.get("effective_select_threshold"),
                "selected_score_tolerance": proof.get("selected_score_tolerance"),
                "selected_within_tolerance": proof.get("selected_within_tolerance"),
                "historical_evidence_case_count": ((proof.get("summary") or {}).get("evidence_case_count")),
                "historical_next_close_positive_rate": ((proof.get("summary") or {}).get("next_close_positive_rate")),
                "historical_t_plus_2_close_positive_rate": ((proof.get("summary") or {}).get("t_plus_2_close_positive_rate")),
                "historical_t_plus_3_close_positive_rate": ((proof.get("summary") or {}).get("t_plus_3_close_positive_rate")),
                "historical_t_plus_4_close_positive_rate": ((proof.get("summary") or {}).get("t_plus_4_close_positive_rate")),
                "historical_recommendation": proof.get("recommendation"),
                "current_data_status": current_outcome.get("data_status"),
                "current_cycle_status": current_outcome.get("cycle_status"),
                "current_next_trade_date": current_outcome.get("next_trade_date"),
                "current_next_open_return": current_outcome.get("next_open_return"),
                "current_next_high_return": current_outcome.get("next_high_return"),
                "current_next_close_return": current_outcome.get("next_close_return"),
                "current_t_plus_2_close_return": current_outcome.get("t_plus_2_close_return"),
                "current_t_plus_3_close_return": current_outcome.get("t_plus_3_close_return"),
                "current_t_plus_4_close_return": current_outcome.get("t_plus_4_close_return"),
                **contract_alignment,
            }
        )
    entries.sort(key=lambda entry: (str(entry.get("current_cycle_status") or ""), -(entry.get("score_target") or 0.0), str(entry.get("ticker") or "")))
    return entries


def _build_refresh_board_analysis(
    *,
    report_dir: Path,
    snapshot_path: Path,
    trade_date: str,
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "report_dir": str(report_dir),
        "snapshot_path": str(snapshot_path),
        "trade_date": trade_date,
        "selected_count": len(entries),
        "current_cycle_status_counts": dict(Counter(str(entry.get("current_cycle_status") or "unknown") for entry in entries)),
        "entries": entries,
        "recommendation": _build_recommendation(entries),
    }


def render_btst_selected_outcome_refresh_board_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Selected Outcome Refresh Board")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- trade_date: {analysis.get('trade_date')}")
    lines.append(f"- report_dir: {analysis.get('report_dir')}")
    lines.append(f"- selected_count: {analysis.get('selected_count')}")
    lines.append(f"- current_cycle_status_counts: {analysis.get('current_cycle_status_counts')}")
    lines.append("")
    lines.append("## Entries")
    for entry in list(analysis.get("entries") or []):
        lines.append(
            f"- {entry.get('ticker')}: cycle={entry.get('current_cycle_status')}, contract={entry.get('overall_contract_verdict')}, next_close={entry.get('current_next_close_return')}, "
            f"t_plus_2={entry.get('current_t_plus_2_close_return')}, t_plus_3={entry.get('current_t_plus_3_close_return')}, "
            f"t_plus_4={entry.get('current_t_plus_4_close_return')}, historical_next_close_positive_rate={entry.get('historical_next_close_positive_rate')}, "
            f"historical_t_plus_2_close_positive_rate={entry.get('historical_t_plus_2_close_positive_rate')}"
        )
    if not list(analysis.get("entries") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis.get('recommendation')}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-refresh current and historical outcome tracking for the latest formal BTST selected entries.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_selected_outcome_refresh_board(args.reports_root)
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_selected_outcome_refresh_board_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
