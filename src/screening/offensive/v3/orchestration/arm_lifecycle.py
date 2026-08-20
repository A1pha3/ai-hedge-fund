"""Per-arm open settlement driver — Phase 5c/5d merged (2026-08-20, adversarial review).

The complete settlement primitive already exists:
``execution.proxy_core.settle_proxy_open`` resolves the locked decision table,
applies the scenario's adverse slippage (CURRENT_COST 30bps / DOUBLE_SLIPPAGE
60bps per side), books the fill AND its fee under the scenario fee policy, and
consumes/releases the entry reserve — one call, capital truth intact. This
module therefore only constructs the ``NormalizedProxyOpenIntent`` (with the
trial's deterministic execution identity) and delegates. It contains no market
math, no fee math and no reserve logic.

Discipline: EXIT quantity must come from the capital position projection
(constitution #9 — never oversell); the repository is the last line of defense
and rejects security debits against unknown positions.
"""

from __future__ import annotations

from datetime import datetime

from src.screening.offensive.v3.capital.fills import FillAttribution
from src.screening.offensive.v3.capital.repository import CapitalRepository
from src.screening.offensive.v3.contracts.execution import ExecutionSide
from src.screening.offensive.v3.execution.lifecycle import DailyBar
from src.screening.offensive.v3.execution.proxy_core import (
    NormalizedProxyOpenIntent,
    ProxyCostScenario,
    ProxyOpenSettlement,
    settle_proxy_open,
)

#: Scenario parameters come from the engine's own factory (single source of
#: truth — 审查 2026-08-20: 此前本地硬编码 30/60bps 与 replay.scenario_cost
#: 重复, 属漂移温床).
from src.screening.offensive.v3.orchestration.replay import ReplayScenario, scenario_cost

CURRENT_COST_SCENARIO: ProxyCostScenario = scenario_cost(ReplayScenario.CURRENT_COST)
DOUBLE_SLIPPAGE_SCENARIO: ProxyCostScenario = scenario_cost(ReplayScenario.DOUBLE_SLIPPAGE)

_LOT_SIZE_UNITS = 100


class ArmLifecycleError(RuntimeError):
    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


def drive_open_settlement(
    repository: CapitalRepository,
    *,
    arm: str,
    decision_id: str,
    side: ExecutionSide,
    security_id: str,
    position_lineage_id: str,
    economic_lot_id: str,
    limit_price_cents: int,
    quantity: int,
    bar: DailyBar | None,
    command_at: datetime,
    send_deadline: datetime,
    attribution: FillAttribution,
    scenario: ProxyCostScenario,
    reserve_source_id: str | None = None,
    reserve_remaining_cents: int = 0,
) -> ProxyOpenSettlement:
    """Settle one open line through the complete proxy primitive.

    Deterministic identity ``{arm}:{decision_id}:{side.value}`` keeps replays
    idempotent (fill/fee idempotency keys). ``reserve_source_id``/
    ``reserve_remaining_cents`` bind the entry reserve the kernel holds
    (None/0 when the caller's framework has no live reserve to consume).
    """
    if quantity <= 0:
        raise ArmLifecycleError("quantity_not_positive", f"quantity {quantity} must be positive")
    execution_id = f"{arm}:{decision_id}:{side.value}"
    intent = NormalizedProxyOpenIntent(
        side=side,
        security_id=security_id,
        limit_price_cents=limit_price_cents,
        quantity_units=quantity,
        lot_size_units=_LOT_SIZE_UNITS,
        execution_id=execution_id,
        order_id=f"ord-{execution_id}",
        reserve_source_id=reserve_source_id,
        reserve_remaining_cents=reserve_remaining_cents,
        position_lineage_id=position_lineage_id,
        economic_lot_id=economic_lot_id,
        attribution=attribution,
        source_authority="daily-bar-proxy.trial",
        source_binding=None,
        recorded_at=command_at,
    )
    return settle_proxy_open(
        intent,
        bar=bar,
        repository=repository,
        scenario=scenario,
        command_at=command_at,
        send_deadline=send_deadline,
    )


__all__ = [
    "ArmLifecycleError",
    "CURRENT_COST_SCENARIO",
    "DOUBLE_SLIPPAGE_SCENARIO",
    "drive_open_settlement",
]
