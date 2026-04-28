from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


SafeLoadJson = Callable[[str | Path | None], dict[str, Any]]
PickSelectedFocusEntry = Callable[[list[dict[str, Any]]], dict[str, Any]]


def find_focus_entry(entries: list[dict[str, Any]], focus_ticker: Any) -> dict[str, Any]:
    focus_ticker_str = str(focus_ticker or "").strip()
    if focus_ticker_str:
        for entry in entries:
            if str((entry or {}).get("ticker") or "").strip() == focus_ticker_str:
                return dict(entry or {})
    return dict(entries[0] or {}) if entries else {}


def extract_selected_outcome_refresh_summary(
    manifest: dict[str, Any],
    *,
    reports_dir: Path,
    safe_load_json: SafeLoadJson,
    pick_selected_focus_entry: PickSelectedFocusEntry,
) -> dict[str, Any]:
    summary = dict(manifest.get("selected_outcome_refresh_summary") or {})
    if summary:
        return summary
    reports_root = Path(manifest.get("reports_root") or reports_dir).expanduser().resolve()
    refresh_board = safe_load_json(reports_root / "btst_selected_outcome_refresh_board_latest.json")
    entries = [dict(entry or {}) for entry in list(refresh_board.get("entries") or [])]
    focus_entry = pick_selected_focus_entry(entries)
    if not refresh_board and not focus_entry:
        return {}
    return {
        "trade_date": refresh_board.get("trade_date"),
        "selected_count": refresh_board.get("selected_count"),
        "current_cycle_status_counts": dict(refresh_board.get("current_cycle_status_counts") or {}),
        "focus_ticker": focus_entry.get("ticker"),
        "focus_cycle_status": focus_entry.get("current_cycle_status"),
        "focus_data_status": focus_entry.get("current_data_status"),
        "focus_next_close_return": focus_entry.get("current_next_close_return"),
        "focus_t_plus_2_close_return": focus_entry.get("current_t_plus_2_close_return"),
        "focus_historical_next_close_positive_rate": focus_entry.get("historical_next_close_positive_rate"),
        "focus_historical_t_plus_2_close_positive_rate": focus_entry.get("historical_t_plus_2_close_positive_rate"),
        "focus_next_day_contract_verdict": focus_entry.get("next_day_contract_verdict"),
        "focus_t_plus_2_contract_verdict": focus_entry.get("t_plus_2_contract_verdict"),
        "focus_overall_contract_verdict": focus_entry.get("overall_contract_verdict"),
        "recommendation": refresh_board.get("recommendation"),
    }


def extract_carryover_multiday_continuation_audit_summary(
    manifest: dict[str, Any],
    *,
    reports_dir: Path,
    safe_load_json: SafeLoadJson,
) -> dict[str, Any]:
    summary = dict(manifest.get("carryover_multiday_continuation_audit_summary") or {})
    if summary:
        return summary
    reports_root = Path(manifest.get("reports_root") or reports_dir).expanduser().resolve()
    audit = safe_load_json(reports_root / "btst_carryover_multiday_continuation_audit_latest.json")
    if not audit:
        return {}
    policy_checks = dict(audit.get("policy_checks") or {})
    selected_historical = dict(audit.get("selected_historical_proof_summary") or {})
    broad_family_only = dict(audit.get("broad_family_only_summary") or {})
    return {
        "selected_ticker": audit.get("selected_ticker"),
        "selected_trade_date": audit.get("selected_trade_date"),
        "supportive_case_count": audit.get("supportive_case_count"),
        "peer_status_counts": dict(audit.get("peer_status_counts") or {}),
        "selected_path_t2_bias_only": policy_checks.get("selected_path_t2_bias_only"),
        "broad_family_only_multiday_unsupported": policy_checks.get("broad_family_only_multiday_unsupported"),
        "aligned_peer_multiday_ready": policy_checks.get("aligned_peer_multiday_ready"),
        "open_selected_case_count": policy_checks.get("open_selected_case_count"),
        "selected_next_close_positive_rate": selected_historical.get("next_close_positive_rate"),
        "selected_t_plus_2_close_positive_rate": selected_historical.get("t_plus_2_close_positive_rate"),
        "selected_t_plus_3_close_positive_rate": selected_historical.get("t_plus_3_close_positive_rate"),
        "broad_family_only_next_close_positive_rate": broad_family_only.get("next_close_positive_rate"),
        "broad_family_only_t_plus_2_close_positive_rate": broad_family_only.get("t_plus_2_close_positive_rate"),
        "policy_recommendations": list(audit.get("policy_recommendations") or [])[:3],
        "recommendation": audit.get("recommendation"),
    }


def extract_carryover_aligned_peer_harvest_summary(
    manifest: dict[str, Any],
    *,
    reports_dir: Path,
    safe_load_json: SafeLoadJson,
) -> dict[str, Any]:
    summary = dict(manifest.get("carryover_aligned_peer_harvest_summary") or {})
    if summary:
        return summary
    reports_root = Path(manifest.get("reports_root") or reports_dir).expanduser().resolve()
    harvest = safe_load_json(reports_root / "btst_carryover_aligned_peer_harvest_latest.json")
    if not harvest:
        return {}
    entries = [dict(entry or {}) for entry in list(harvest.get("harvest_entries") or [])]
    focus_entry = find_focus_entry(entries, harvest.get("focus_ticker"))
    fresh_open_cycle_tickers = [
        str(entry.get("ticker") or "")
        for entry in entries
        if str(entry.get("harvest_status") or "") == "fresh_open_cycle" and entry.get("ticker")
    ][:4]
    return {
        "ticker": harvest.get("ticker"),
        "peer_row_count": harvest.get("peer_row_count"),
        "peer_count": harvest.get("peer_count"),
        "status_counts": dict(harvest.get("status_counts") or {}),
        "focus_ticker": harvest.get("focus_ticker") or focus_entry.get("ticker"),
        "focus_status": harvest.get("focus_status") or focus_entry.get("harvest_status"),
        "focus_latest_trade_date": focus_entry.get("latest_trade_date"),
        "focus_latest_scope": focus_entry.get("latest_scope"),
        "focus_closed_cycle_count": focus_entry.get("closed_cycle_count"),
        "focus_next_day_available_count": focus_entry.get("next_day_available_count"),
        "focus_recommendation": focus_entry.get("recommendation"),
        "fresh_open_cycle_tickers": fresh_open_cycle_tickers,
        "recommendation": harvest.get("recommendation"),
    }


def extract_carryover_peer_expansion_summary(
    manifest: dict[str, Any],
    *,
    reports_dir: Path,
    safe_load_json: SafeLoadJson,
) -> dict[str, Any]:
    summary = dict(manifest.get("carryover_peer_expansion_summary") or {})
    if summary:
        return summary
    reports_root = Path(manifest.get("reports_root") or reports_dir).expanduser().resolve()
    expansion = safe_load_json(reports_root / "btst_carryover_peer_expansion_latest.json")
    if not expansion:
        return {}
    entries = [dict(entry or {}) for entry in list(expansion.get("entries") or [])]
    focus_entry = find_focus_entry(entries, expansion.get("focus_ticker"))
    return {
        "selected_ticker": expansion.get("selected_ticker"),
        "selected_path_t2_bias_only": expansion.get("selected_path_t2_bias_only"),
        "broad_family_only_multiday_unsupported": expansion.get("broad_family_only_multiday_unsupported"),
        "peer_count": expansion.get("peer_count"),
        "expansion_status_counts": dict(expansion.get("expansion_status_counts") or {}),
        "priority_expansion_tickers": list(expansion.get("priority_expansion_tickers") or []),
        "watch_with_risk_tickers": list(expansion.get("watch_with_risk_tickers") or []),
        "focus_ticker": expansion.get("focus_ticker") or focus_entry.get("ticker"),
        "focus_status": expansion.get("focus_status") or focus_entry.get("expansion_status"),
        "focus_latest_trade_date": focus_entry.get("latest_trade_date"),
        "focus_latest_scope": focus_entry.get("latest_scope"),
        "focus_recommendation": focus_entry.get("recommendation"),
        "recommendation": expansion.get("recommendation"),
    }


def extract_carryover_aligned_peer_proof_summary(
    manifest: dict[str, Any],
    *,
    reports_dir: Path,
    safe_load_json: SafeLoadJson,
) -> dict[str, Any]:
    summary = dict(manifest.get("carryover_aligned_peer_proof_summary") or {})
    if summary:
        return summary
    reports_root = Path(manifest.get("reports_root") or reports_dir).expanduser().resolve()
    proof_board = safe_load_json(reports_root / "btst_carryover_aligned_peer_proof_board_latest.json")
    if not proof_board:
        return {}
    entries = [dict(entry or {}) for entry in list(proof_board.get("entries") or [])]
    focus_entry = find_focus_entry(entries, proof_board.get("focus_ticker"))
    return {
        "selected_ticker": proof_board.get("selected_ticker"),
        "selected_trade_date": proof_board.get("selected_trade_date"),
        "selected_cycle_status": proof_board.get("selected_cycle_status"),
        "selected_contract_verdict": proof_board.get("selected_contract_verdict"),
        "peer_count": proof_board.get("peer_count"),
        "proof_verdict_counts": dict(proof_board.get("proof_verdict_counts") or {}),
        "promotion_review_verdict_counts": dict(proof_board.get("promotion_review_verdict_counts") or {}),
        "ready_for_promotion_review_tickers": list(proof_board.get("ready_for_promotion_review_tickers") or []),
        "risk_review_tickers": list(proof_board.get("risk_review_tickers") or []),
        "pending_t_plus_2_tickers": list(proof_board.get("pending_t_plus_2_tickers") or []),
        "focus_ticker": proof_board.get("focus_ticker") or focus_entry.get("ticker"),
        "focus_proof_verdict": proof_board.get("focus_proof_verdict") or focus_entry.get("proof_verdict"),
        "focus_promotion_review_verdict": proof_board.get("focus_promotion_review_verdict") or focus_entry.get("promotion_review_verdict"),
        "focus_latest_trade_date": focus_entry.get("latest_trade_date"),
        "focus_latest_scope": focus_entry.get("latest_scope"),
        "focus_recommendation": focus_entry.get("recommendation"),
        "recommendation": proof_board.get("recommendation"),
    }


def extract_carryover_peer_promotion_gate_summary(
    manifest: dict[str, Any],
    *,
    reports_dir: Path,
    safe_load_json: SafeLoadJson,
) -> dict[str, Any]:
    summary = dict(manifest.get("carryover_peer_promotion_gate_summary") or {})
    if summary:
        return summary
    reports_root = Path(manifest.get("reports_root") or reports_dir).expanduser().resolve()
    promotion_gate = safe_load_json(reports_root / "btst_carryover_peer_promotion_gate_latest.json")
    if not promotion_gate:
        return {}
    entries = [dict(entry or {}) for entry in list(promotion_gate.get("entries") or [])]
    focus_entry = find_focus_entry(entries, promotion_gate.get("focus_ticker"))
    return {
        "selected_ticker": promotion_gate.get("selected_ticker"),
        "selected_trade_date": promotion_gate.get("selected_trade_date"),
        "selected_contract_verdict": promotion_gate.get("selected_contract_verdict"),
        "peer_count": promotion_gate.get("peer_count"),
        "gate_verdict_counts": dict(promotion_gate.get("gate_verdict_counts") or {}),
        "default_expansion_status": promotion_gate.get("default_expansion_status"),
        "ready_tickers": list(promotion_gate.get("ready_tickers") or []),
        "blocked_open_tickers": list(promotion_gate.get("blocked_open_tickers") or []),
        "risk_review_tickers": list(promotion_gate.get("risk_review_tickers") or []),
        "pending_t_plus_2_tickers": list(promotion_gate.get("pending_t_plus_2_tickers") or []),
        "pending_next_day_tickers": list(promotion_gate.get("pending_next_day_tickers") or []),
        "focus_ticker": promotion_gate.get("focus_ticker") or focus_entry.get("ticker"),
        "focus_gate_verdict": promotion_gate.get("focus_gate_verdict") or focus_entry.get("gate_verdict"),
        "focus_recommendation": focus_entry.get("recommendation"),
        "recommendation": promotion_gate.get("recommendation"),
    }
