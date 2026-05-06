from __future__ import annotations

from typing import Any

from src.screening.market_state_helpers import classify_btst_regime_gate_from_market_state


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
    gate_payload = classify_btst_regime_gate_from_market_state(market_state)
    if gate_payload is None:
        return fallback
    return map_btst_gate_to_short_trade_target_profile_name(
        str(gate_payload.get("gate") or ""),
        fallback=fallback,
    )


def resolve_short_trade_target_profile_name_from_target_context(
    *,
    market_state: Any | None,
    historical_prior: dict[str, Any] | None = None,
    fallback: str = "default",
) -> str:
    normalized_historical_prior = dict(historical_prior or {})
    explicit_gate = str(normalized_historical_prior.get("btst_regime_gate") or "").strip().lower()
    if explicit_gate:
        return map_btst_gate_to_short_trade_target_profile_name(explicit_gate, fallback=fallback)
    return resolve_short_trade_target_profile_name_from_market_state(
        market_state,
        fallback=fallback,
    )
