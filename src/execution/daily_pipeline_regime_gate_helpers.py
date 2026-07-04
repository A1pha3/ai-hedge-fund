"""P1/P2 regime gate enforcement helpers extracted from daily_pipeline.py.

P1 (shadow): annotates plan.risk_metrics with regime gate metadata.
P2 (enforce): clears buy_orders and marks selection_targets for halt / shadow_only days.

These functions are re-exported from daily_pipeline.py for backward compatibility.
"""

from __future__ import annotations

import os
from typing import Any

from src.execution.btst_shadow_promotion_helpers import (
    resolve_btst_shadow_promotion_payload,
)
from src.execution.models import ExecutionPlan
from src.targets.router import (
    _P2_BLOCKED_GATES,
    apply_p2_regime_gate_enforcement_to_selection_targets,
    summarize_selection_targets,
)

BTST_0422_P1_REGIME_GATE_MODE_ENV = "BTST_0422_P1_REGIME_GATE_MODE"
BTST_0422_P1_REGIME_GATE_MODES = frozenset({"off", "shadow"})
BTST_0422_P2_REGIME_GATE_MODE_ENV = "BTST_0422_P2_REGIME_GATE_MODE"
BTST_0422_P2_REGIME_GATE_MODES = frozenset({"off", "enforce"})


def resolve_btst_regime_gate_mode() -> str:
    normalized_mode = str(os.getenv(BTST_0422_P1_REGIME_GATE_MODE_ENV, "off") or "off").strip().lower()
    return normalized_mode if normalized_mode in BTST_0422_P1_REGIME_GATE_MODES else "off"


def build_btst_regime_gate_payload(market_state: Any | None) -> dict[str, Any]:
    if resolve_btst_regime_gate_mode() == "off":
        return {}
    from src.screening.market_state_helpers import (
        classify_btst_regime_gate_from_market_state,
    )

    gate_payload = dict(classify_btst_regime_gate_from_market_state(market_state) or {})
    if not gate_payload:
        return {}
    gate_payload["mode"] = resolve_btst_regime_gate_mode()
    return gate_payload


def build_downstream_target_market_state_payload(market_state: Any | None) -> dict[str, Any]:
    if market_state is None:
        return {}
    if hasattr(market_state, "model_dump"):
        payload = dict(market_state.model_dump(mode="json") or {})
    elif isinstance(market_state, dict):
        payload = dict(market_state)
    else:
        return {}
    gate_payload = build_btst_regime_gate_payload(payload)
    if gate_payload:
        payload["btst_regime_gate"] = dict(gate_payload)
    return payload


def attach_downstream_target_market_state_payload(
    layer_c_results: list,
    *,
    market_state: Any | None,
) -> list:
    market_state_payload = build_downstream_target_market_state_payload(market_state)
    if not market_state_payload:
        return list(layer_c_results)
    attached_results: list = []
    for item in list(layer_c_results):
        merged_market_state = dict(getattr(item, "market_state", {}) or {})
        merged_market_state.pop("btst_regime_gate", None)
        merged_market_state.update(dict(market_state_payload))
        attached_results.append(item.model_copy(update={"market_state": merged_market_state}))
    return attached_results


def attach_btst_regime_gate_shadow(plan: ExecutionPlan) -> ExecutionPlan:
    gate_payload = build_btst_regime_gate_payload(getattr(plan, "market_state", None))
    if not gate_payload:
        return plan
    plan = plan.model_copy(deep=True)
    risk_metrics = dict(getattr(plan, "risk_metrics", {}) or {})
    risk_metrics["btst_regime_gate"] = gate_payload
    funnel_diagnostics = dict(risk_metrics.get("funnel_diagnostics", {}) or {})
    funnel_diagnostics["btst_regime_gate"] = gate_payload
    risk_metrics["funnel_diagnostics"] = funnel_diagnostics
    plan.risk_metrics = risk_metrics
    return plan


def resolve_btst_regime_gate_p2_mode() -> str:
    normalized_mode = str(os.getenv(BTST_0422_P2_REGIME_GATE_MODE_ENV, "off") or "off").strip().lower()
    return normalized_mode if normalized_mode in BTST_0422_P2_REGIME_GATE_MODES else "off"


def get_or_classify_gate(plan: ExecutionPlan) -> str | None:
    """Return the gate string for P2 enforcement.

    Reuses the P1 gate payload already stored in risk_metrics when available;
    otherwise classifies independently from the plan's market_state.
    """
    existing_gate = str((plan.risk_metrics or {}).get("btst_regime_gate", {}).get("gate", "") or "").strip()
    if existing_gate:
        return existing_gate
    from src.screening.market_state_helpers import (
        classify_btst_regime_gate_from_market_state,
    )

    result = classify_btst_regime_gate_from_market_state(getattr(plan, "market_state", None))
    if not result:
        return None
    return str(result.get("gate", "") or "").strip() or None


def enforce_btst_regime_gate_p2(plan: ExecutionPlan) -> ExecutionPlan:
    """P2 hard enforcement: clear buy_orders and mark selection_targets for halt / shadow_only days.

    Only active when BTST_0422_P2_REGIME_GATE_MODE=enforce.
    Preserves backward compatibility — off by default.
    Reuses the P1 gate payload from risk_metrics when already computed.
    Also updates plan.selection_targets to mark items as p2_execution_blocked (router-level semantic).
    """
    if resolve_btst_regime_gate_p2_mode() != "enforce":
        return plan

    plan = plan.model_copy(deep=True)
    gate = get_or_classify_gate(plan)
    if gate is None:
        return plan

    risk_metrics = dict(getattr(plan, "risk_metrics", {}) or {})
    funnel_diagnostics = dict(risk_metrics.get("funnel_diagnostics", {}) or {})

    if gate in _P2_BLOCKED_GATES:
        selection_targets = dict(plan.selection_targets or {})
        shadow_promotion_tickers = {str(ticker) for ticker, evaluation in selection_targets.items() if resolve_btst_shadow_promotion_payload(evaluation=evaluation, gate=gate).get("eligible")}
        original_buy_orders = list(plan.buy_orders or [])
        retained_orders = [order for order in original_buy_orders if order.ticker in shadow_promotion_tickers]
        cleared_count = max(0, len(original_buy_orders) - len(retained_orders))
        cleared = cleared_count > 0
        plan.buy_orders = retained_orders
        enforcement_payload: dict[str, Any] = {
            "enforced": True,
            "gate": gate,
            "mode": "enforce",
            "buy_orders_cleared": cleared,
            "buy_orders_cleared_count": cleared_count,
            "shadow_promotion_count": len(shadow_promotion_tickers),
            "shadow_promotion_tickers": sorted(shadow_promotion_tickers),
        }
        counts = dict(risk_metrics.get("counts", {}))
        counts["buy_order_count"] = len(plan.buy_orders)
        risk_metrics["counts"] = counts
        # Router-level: mark formal execution eligibility as blocked in selection_targets.
        if plan.selection_targets:
            apply_p2_regime_gate_enforcement_to_selection_targets(
                plan.selection_targets,
                gate=gate,
                allowed_tickers=shadow_promotion_tickers,
            )
    else:
        enforcement_payload = {
            "enforced": False,
            "gate": gate,
            "mode": "enforce",
            "buy_orders_cleared": False,
            "buy_orders_cleared_count": 0,
            "shadow_promotion_count": 0,
            "shadow_promotion_tickers": [],
        }

    risk_metrics["btst_regime_gate_enforcement"] = enforcement_payload
    funnel_diagnostics["btst_regime_gate_enforcement"] = enforcement_payload
    risk_metrics["funnel_diagnostics"] = funnel_diagnostics
    plan.risk_metrics = risk_metrics
    plan.dual_target_summary = summarize_selection_targets(
        selection_targets=dict(plan.selection_targets or {}),
        target_mode=plan.target_mode,
    )
    return plan
