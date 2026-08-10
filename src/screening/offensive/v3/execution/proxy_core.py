"""Task 8: the shared, authority-neutral proxy open-settlement economics.

``settle_proxy_open`` is the stateless economic heart that both the
authorised ``DailyBarProxy`` adapter (entry from a sealed permit) and the
shadow adapter (entry/exit from a committed ``ShadowDecision``) drive. It
takes a normalized intent, one target-session daily bar, the live capital
repository, an explicit cost scenario, and the command timing; it resolves
the open through the existing decision table (:func:`resolve_open_execution`),
applies integer adverse slippage bounded by the limit, and books the fill /
fee / reserve release into capital truth.

The core owns no durable execution-record storage and no clock: the
authorised adapter keeps its ``execution_records`` table, and every
timestamp comes from the injected intent (``recorded_at``) and command
(``command_at``). Capital mutation itself is idempotent - the kernel
deduplicates a fill/fee by execution id and a reserve release by source id
- so an exact replay of the same intent converges quietly without a core
record store. A divergent replay is the caller's protocol breach to latch.

Slippage is adverse and bounded by the limit: a buy degrades toward (never
past) its limit, a sell degrades toward (never past) its limit. The
integer slip is ``round_half_even(base * bps / 10_000)`` so it composes
exactly with the rest of the integer capital arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import sqlalchemy as sa

from src.screening.offensive.v3.capital.fees import FeePolicy, FeeRevisionKind
from src.screening.offensive.v3.capital.fills import (
    FeeRevisionRequest,
    FeeRevisionReceipt,
    FillAttribution,
    FillRevisionReceipt,
    FillRevisionRequest,
)
from src.screening.offensive.v3.capital.provenance import CapitalSourceBinding
from src.screening.offensive.v3.capital.repository import CapitalRepository
from src.screening.offensive.v3.capital.reserves import (
    CapitalReserveState,
    ReserveReleaseReason,
    ReserveReleaseRequest,
)
from src.screening.offensive.v3.capital.rounding import (
    fill_gross_cents,
    round_half_even_div,
)
from src.screening.offensive.v3.contracts import ExecutionSide
from src.screening.offensive.v3.execution.lifecycle import (
    DailyBar,
    OpenExecutionResolution,
    OpenExecutionVerdict,
    REASON_PERMIT_QUANTITY_ZERO,
    resolve_open_execution,
)

_BPS_SCALE: int = 10_000


@dataclass(frozen=True)
class NormalizedProxyOpenIntent:
    """One authority-neutral line to settle against a daily bar.

    Both adapters normalize their sealed/decision line into this shape
    before calling the core: the authorised adapter maps a permit line +
    its sealed proposal line, the shadow adapter maps a ``ShadowOrderLine``
    after the mechanical shrink. The core never sees a permit or a decision.
    """

    side: ExecutionSide
    security_id: str
    limit_price_cents: int
    # Already mechanically shrunk; 0 means no executable quantity.
    quantity_units: int
    lot_size_units: int
    # Stable economic identity (caller-derived, deterministic across replays).
    execution_id: str
    order_id: str
    # Entry reserve binding; None on a zero-quantity line and on every exit.
    reserve_source_id: str | None
    # The LIVE remaining reserve the kernel holds for this line; reported on
    # a no-fill/unknown release and consumed in full on an entry fill.
    reserve_remaining_cents: int
    position_lineage_id: str | None
    economic_lot_id: str | None
    attribution: FillAttribution | None
    source_authority: str
    source_binding: CapitalSourceBinding | None
    recorded_at: datetime


@dataclass(frozen=True)
class ProxyCostScenario:
    """One explicit cost/slippage scenario for a proxy settlement.

    The official Trial current-cost scenario carries 30bps single-side
    adverse slippage; the 2x stress scenario carries 60bps. The fee policy
    pins the commission/stamp/transfer schedule. ``scenario_id`` is opaque
    to the core - it only labels the scenario for the caller.
    """

    scenario_id: str
    entry_slippage_bps: int
    exit_slippage_bps: int
    fee_policy: FeePolicy


@dataclass(frozen=True)
class ProxyOpenSettlement:
    """The economic outcome of settling one normalized intent."""

    verdict: OpenExecutionVerdict
    reason: str
    fill_price_cents: int | None
    fill_receipt: FillRevisionReceipt | None
    fee_receipt: FeeRevisionReceipt | None
    released_reserve_cents: int


def adverse_fill_price_cents(
    base_cents: int, *, side: ExecutionSide, limit_cents: int, bps: int
) -> int:
    """Degrade a base fill price by integer adverse slippage, limit-bounded.

    A buy slips upward toward its limit; a sell slips downward toward its
    limit. The slip is rounded half-even so it stays exact with the rest of
    the integer capital arithmetic.
    """

    slip = round_half_even_div(base_cents * bps, _BPS_SCALE)
    if side is ExecutionSide.ENTRY:
        return min(limit_cents, base_cents + slip)
    return max(limit_cents, base_cents - slip)


def _reserve_is_live(source_id: str, repository: CapitalRepository) -> bool:
    engine = repository._engine  # noqa: SLF001
    with engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT state FROM reserves WHERE source_id = :src"),
            {"src": source_id},
        ).first()
    if row is None:
        return False
    return str(row.state) == CapitalReserveState.LIVE.value


def _release_remaining_reserve(
    intent: NormalizedProxyOpenIntent, repository: CapitalRepository
) -> int:
    """Release an unfilled line's remaining reserve back to cash.

    Reports the intent's LIVE remaining reserve - the amount the kernel
    actually holds. A reserve already walked to RELEASED by a prior attempt
    is left untouched (the release is idempotent), but the reported amount
    is still the frozen permit/decision artifact.
    """

    if intent.reserve_source_id is None:
        return 0
    if _reserve_is_live(intent.reserve_source_id, repository):
        repository.release_reserve(
            ReserveReleaseRequest(
                source_id=intent.reserve_source_id,
                reason=ReserveReleaseReason.ORDER_REJECTED,
                expected_stream_version=repository.stream_version(),
                as_of=intent.recorded_at,
            )
        )
    return intent.reserve_remaining_cents


def _released_surplus(
    fill_receipt: FillRevisionReceipt, gross_cents: int
) -> int:
    """The worst-case reserve surplus the fill did not spend."""

    consumed = fill_receipt.reserve_consumed_cents
    if consumed is None:
        return 0
    return int(consumed) - gross_cents


def settle_proxy_open(
    intent: NormalizedProxyOpenIntent,
    *,
    bar: DailyBar | None,
    repository: CapitalRepository,
    scenario: ProxyCostScenario,
    command_at: datetime,
    send_deadline: datetime,
    _fault_hook: Callable[[str], None] | None = None,
) -> ProxyOpenSettlement:
    """Resolve and settle one normalized open intent into capital truth.

    A zero-quantity intent never reaches the fill table (a zero-quantity
    fill is not a valid capital fact): it resolves NO_FILL and releases no
    reserve. A FILLED line consumes its entry reserve (entry side only),
    books the gross fill and its fee under the scenario policy, and returns
    the worst-case surplus; every other verdict releases the remaining
    reserve and keeps the cash.

    ``_fault_hook`` is a crash-injection seam the authorised adapter threads
    through its own hook; the core is otherwise stateless.
    """

    if intent.quantity_units == 0:
        resolution = OpenExecutionResolution(
            OpenExecutionVerdict.NO_FILL, None, REASON_PERMIT_QUANTITY_ZERO
        )
    else:
        resolution = resolve_open_execution(
            side=intent.side,
            limit_price_cents=intent.limit_price_cents,
            bar=bar,
            command_at=command_at,
            send_deadline=send_deadline,
        )
    if resolution.verdict is not OpenExecutionVerdict.FILLED:
        released = _release_remaining_reserve(intent, repository)
        if _fault_hook is not None:
            _fault_hook("core.after_release")
        return ProxyOpenSettlement(
            verdict=resolution.verdict,
            reason=resolution.reason,
            fill_price_cents=None,
            fill_receipt=None,
            fee_receipt=None,
            released_reserve_cents=released,
        )
    bps = (
        scenario.entry_slippage_bps
        if intent.side is ExecutionSide.ENTRY
        else scenario.exit_slippage_bps
    )
    fill_price_cents = adverse_fill_price_cents(
        resolution.fill_price_cents,
        side=intent.side,
        limit_cents=intent.limit_price_cents,
        bps=bps,
    )
    quantity = intent.quantity_units
    price_micros = fill_price_cents * 10_000
    gross_cents = fill_gross_cents(price_micros, quantity)
    fill_request = FillRevisionRequest(
        execution_id=intent.execution_id,
        revision=1,
        order_id=intent.order_id,
        side=intent.side,
        security_id=intent.security_id,
        price_micros=price_micros,
        quantity=quantity,
        position_lineage_id=intent.position_lineage_id,
        economic_lot_id=intent.economic_lot_id,
        attribution=intent.attribution,
        # Only an entry fill may consume a reserve; exits carry None.
        reserve_source_id=(
            intent.reserve_source_id
            if intent.side is ExecutionSide.ENTRY
            else None
        ),
        source_authority=intent.source_authority,
        source_binding=intent.source_binding,
        effective_at=command_at,
        as_of=intent.recorded_at,
        expected_stream_version=repository.stream_version(),
    )
    fill_receipt, _ = repository.record_fill_revision(fill_request)
    if _fault_hook is not None:
        _fault_hook("core.after_fill")
    fee_request = FeeRevisionRequest(
        fill_execution_id=intent.execution_id,
        revision=1,
        revision_kind=FeeRevisionKind.INITIAL,
        fee_policy=scenario.fee_policy,
        source_authority=intent.source_authority,
        source_binding=intent.source_binding,
        effective_at=command_at,
        as_of=intent.recorded_at,
        expected_stream_version=repository.stream_version(),
    )
    fee_receipt, _ = repository.record_fee_revision(fee_request)
    if _fault_hook is not None:
        _fault_hook("core.after_fee")
    return ProxyOpenSettlement(
        verdict=OpenExecutionVerdict.FILLED,
        reason=resolution.reason,
        fill_price_cents=fill_price_cents,
        fill_receipt=fill_receipt,
        fee_receipt=fee_receipt,
        released_reserve_cents=_released_surplus(fill_receipt, gross_cents),
    )


__all__ = [
    "NormalizedProxyOpenIntent",
    "adverse_fill_price_cents",
    "ProxyCostScenario",
    "ProxyOpenSettlement",
    "settle_proxy_open",
]
