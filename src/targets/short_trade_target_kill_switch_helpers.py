from __future__ import annotations

from typing import Any

BTST_KILL_SWITCH_CHECKS: tuple[tuple[str, Any], ...] = (
    ("rolling_8_trade_close_win_rate", lambda value: value < 0.375),
    ("rolling_8_trade_payoff_ratio", lambda value: value < 0.85),
    ("rolling_20d_selected_expectation", lambda value: value < -0.015),
    ("rolling_shadow_minus_formal_close_rate", lambda value: value > 0.08),
)
BTST_KILL_SWITCH_RECOVERY_KEYS: tuple[str, ...] = (
    "kill_switch_recovery_trade_count",
    "kill_switch_recovery_day_count",
)
BTST_KILL_SWITCH_RECOVERY_TRADE_MIN = 8.0
BTST_KILL_SWITCH_RECOVERY_DAY_MIN = 10.0


def extract_btst_kill_switch_metrics(payload: dict[str, Any] | None) -> dict[str, float]:
    normalized_payload = dict(payload or {})
    nested_metrics = dict(normalized_payload.get("btst_kill_switch_metrics") or normalized_payload.get("committee_kill_switch_metrics") or normalized_payload.get("kill_switch_metrics") or {})
    metrics_source = nested_metrics or normalized_payload
    extracted: dict[str, float] = {}
    for key, _ in BTST_KILL_SWITCH_CHECKS:
        raw_value = metrics_source.get(key)
        if raw_value is None:
            continue
        extracted[key] = float(raw_value or 0.0)
    for key in BTST_KILL_SWITCH_RECOVERY_KEYS:
        raw_value = metrics_source.get(key)
        if raw_value is None:
            continue
        extracted[key] = max(float(raw_value or 0.0), 0.0)
    return extracted


def resolve_btst_kill_switch(metrics: dict[str, Any] | None, gate: str) -> dict[str, Any]:
    normalized_metrics = extract_btst_kill_switch_metrics(metrics)
    triggered_metrics: list[str] = []
    for key, predicate in BTST_KILL_SWITCH_CHECKS:
        raw_value = normalized_metrics.get(key)
        if raw_value is None:
            continue
        if predicate(float(raw_value or 0.0)):
            triggered_metrics.append(key)

    recovery_trade_count = max(float(normalized_metrics.get("kill_switch_recovery_trade_count", 0.0) or 0.0), 0.0)
    recovery_day_count = max(float(normalized_metrics.get("kill_switch_recovery_day_count", 0.0) or 0.0), 0.0)
    recovery_window_observed = any(key in normalized_metrics for key in BTST_KILL_SWITCH_RECOVERY_KEYS)
    recovery_pending = not triggered_metrics and recovery_window_observed and recovery_trade_count < BTST_KILL_SWITCH_RECOVERY_TRADE_MIN and recovery_day_count < BTST_KILL_SWITCH_RECOVERY_DAY_MIN
    recovery_release_ready = not triggered_metrics and recovery_window_observed and not recovery_pending

    effective_gate = str(gate or "")
    if triggered_metrics or recovery_pending:
        if effective_gate == "aggressive_trade":
            effective_gate = "normal_trade"
        elif effective_gate == "normal_trade":
            effective_gate = "shadow_only"

    return {
        "active": bool(triggered_metrics or recovery_pending),
        "triggered_metrics": triggered_metrics,
        "effective_gate": effective_gate,
        "metrics": normalized_metrics,
        "recovery_pending": recovery_pending,
        "recovery_release_ready": recovery_release_ready,
        "recovery_trade_count": recovery_trade_count if recovery_window_observed else 0.0,
        "recovery_day_count": recovery_day_count if recovery_window_observed else 0.0,
    }
