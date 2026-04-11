from __future__ import annotations

from typing import Any


def pick_selected_focus_entry(entries: list[dict[str, Any]]) -> dict[str, Any]:
    normalized_entries = [dict(entry or {}) for entry in entries if entry]
    if not normalized_entries:
        return {}
    return max(normalized_entries, key=_selected_focus_priority)


def _selected_focus_priority(entry: dict[str, Any]) -> tuple[int, int, float, str]:
    overall_contract_verdict = str(entry.get("overall_contract_verdict") or "").strip()
    current_cycle_status = str(entry.get("current_cycle_status") or "").strip()
    score_target = _safe_float(entry.get("score_target")) or 0.0
    return (
        _contract_priority(overall_contract_verdict, current_cycle_status),
        _cycle_priority(current_cycle_status),
        score_target,
        str(entry.get("ticker") or ""),
    )


def _contract_priority(overall_contract_verdict: str, current_cycle_status: str) -> int:
    if overall_contract_verdict == "next_close_violated":
        return 6
    if overall_contract_verdict == "t_plus_2_violated":
        return 5
    if overall_contract_verdict in {"pending_next_day", "pending_t_plus_2"}:
        return 4
    if overall_contract_verdict == "next_close_confirmed_wait_t_plus_2":
        return 3
    if current_cycle_status in {"missing_next_day", "t1_only"}:
        return 2
    if overall_contract_verdict == "t_plus_2_confirmed":
        return 1
    return 0


def _cycle_priority(current_cycle_status: str) -> int:
    if current_cycle_status == "t1_only":
        return 3
    if current_cycle_status == "missing_next_day":
        return 2
    if current_cycle_status in {"t_plus_2_closed", "t_plus_3_closed", "t_plus_4_closed"}:
        return 1
    return 0


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
