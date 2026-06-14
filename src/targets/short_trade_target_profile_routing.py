from __future__ import annotations

from typing import Any

from src.screening.market_state_helpers import (
    classify_btst_regime_gate_from_market_state_metrics,
)
from src.targets.short_trade_target_kill_switch_helpers import (
    extract_btst_kill_switch_metrics,
    resolve_btst_kill_switch,
)

BTST_GATE_TO_SHORT_TRADE_TARGET_PROFILE: dict[str, str] = {
    "aggressive_trade": "ignition_breakout",
    "normal_trade": "retention_follow",
    "shadow_only": "shadow_research",
    "halt": "shadow_research",
}


def map_btst_gate_to_short_trade_target_profile_name(gate: str | None, *, fallback: str = "default") -> str:
    normalized_gate = str(gate or "").strip().lower()
    return BTST_GATE_TO_SHORT_TRADE_TARGET_PROFILE.get(normalized_gate, fallback)


def resolve_short_trade_target_profile_name_from_market_state(
    market_state: Any | None,
    *,
    fallback: str = "default",
) -> str:
    gate_payload = classify_btst_regime_gate_from_market_state_metrics(market_state)
    if gate_payload is None:
        return fallback
    if hasattr(market_state, "model_dump"):
        market_state_payload = dict(market_state.model_dump(mode="json") or {})
    elif isinstance(market_state, dict):
        market_state_payload = dict(market_state)
    else:
        market_state_payload = {}
    effective_gate = str(gate_payload.get("gate") or "")
    if effective_gate:
        kill_switch = resolve_btst_kill_switch(extract_btst_kill_switch_metrics(market_state_payload), effective_gate)
        effective_gate = str(kill_switch.get("effective_gate") or effective_gate)
    return map_btst_gate_to_short_trade_target_profile_name(
        effective_gate,
        fallback=fallback,
    )


def resolve_short_trade_target_profile_name_from_target_context(
    *,
    market_state: Any | None,
    historical_prior: dict[str, Any] | None = None,
    fallback: str = "default",
) -> str:
    resolved_from_market_state = resolve_short_trade_target_profile_name_from_market_state(
        market_state,
        fallback="",
    )
    if resolved_from_market_state:
        return resolved_from_market_state

    normalized_historical_prior = dict(historical_prior or {})
    explicit_gate = str(normalized_historical_prior.get("btst_regime_gate") or "").strip().lower()
    if explicit_gate:
        return map_btst_gate_to_short_trade_target_profile_name(explicit_gate, fallback=fallback)
    return resolve_short_trade_target_profile_name_from_market_state(
        market_state,
        fallback=fallback,
    )
