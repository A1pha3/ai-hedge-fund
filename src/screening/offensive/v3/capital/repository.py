"""Append-only AccountCapitalTruth repository and gateway transaction kernel.

Plan 02 Task 1 scope: account/environment/currency binding, stream-version
CAS, idempotent canonical event append, integer-quanta projection for cash,
securities and cash receivables, the risk/stage-loss recompute hook, entry
tombstone hook, and a complete ``CapitalRiskSnapshot`` read at one capital
version inside one SQLite transaction (WAL + BEGIN IMMEDIATE).

Kernel revision 1 supports CASH, SECURITY and CASH_RECEIVABLE legs. Every
other economic fact fails closed with a rollback; the named extension points
land in later Plan 02 tasks:

- fee policies, fill/fee revisions, reserve lifecycle: Task 2 / Plan 04;
- genesis units, external flows, NAV lifecycle, payables/suspense: Task 3;
- share receivables, cost basis restatement, corporate actions: Task 4;
- marks, stage-loss budgets, full exposure aggregation: Task 5;
- execution bust/correction, event revisions, reopen: Task 6;
- checkpoints, backup, rebuild and verification: Task 7.

The sentinel governance values surfaced by snapshots carry no authority;
they keep consumers fail-closed until the Governance Control Plane binds a
real policy activation through the Plan 04 gateway.
"""

from __future__ import annotations

import contextlib
import json
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Any, Callable, TypeAlias

import sqlalchemy as sa
from pydantic import Field, ValidationError, model_validator
from sqlalchemy.exc import DBAPIError, IntegrityError

from src.screening.offensive.v3.capital.conservation import (
    ConservationReport,
    verify_conservation,
)
from src.screening.offensive.v3.capital.execution_revisions import (
    EVENT_REVISION_LINK_KIND,
    FEE_KIND,
    FEE_REVISION_KINDS,
    FILL_BUST_KIND,
    FILL_CORRECTION_KIND,
    FILL_KIND,
    FILL_REVISION_KINDS,
    MANDATE_REVISION_FLOOR,
    REOPEN_POSITION_STATE,
    TOMBSTONE_REASON_ENTRY_INVALIDATED,
    TOMBSTONE_REASON_EXECUTION_BUSTED,
    ExecutionRevisionFact,
    ExecutionRevisionFactKind,
    ExecutionRevisionReceipt,
    ExecutionRevisionRequest,
    LotEventFact,
    LotReplayState,
    ReconciliationDiscrepancy,
    ReopenedEconomicLot,
    execution_revision_legs,
    lot_tombstone_identity,
    registry_kind_for_fee_revision,
    registry_kind_for_fill_revision,
    replay_lot_fact,
    reserve_tombstone_identity,
)
from src.screening.offensive.v3.capital.corporate_actions import (
    ENTITLEMENT_KINDS,
    SOURCE_AUTHORITY_RANK,
    CashInLieuReceipt,
    CashInLieuRequest,
    ConversionDestination,
    ConversionReceipt,
    ConversionRequest,
    CorporateActionFact,
    CorporateActionKind,
    CorporateActionRecord,
    CorporateActionState,
    EntitlementReceipt,
    EntitlementRequest,
    SharesTradableReceipt,
    SharesTradableRequest,
    SourceAuthorityTier,
    SplitMergeReceipt,
    SplitMergeRequest,
    TerminalCashReceipt,
    TerminalCashRequest,
    WriteOffReceipt,
    WriteOffRequest,
    cash_in_lieu_receivable_id,
    cash_receivable_id,
    conversion_idempotency_key,
    entitlement_idempotency_key,
    exact_entitlement_cents,
    exact_quantity,
    lowest_terms,
    settlement_idempotency_key,
    share_receivable_id,
    split_entitlement,
    split_merge_idempotency_key,
    successor_share_receivable_id,
    terminal_cash_idempotency_key,
    tradable_idempotency_key,
    write_off_idempotency_key,
)
from src.screening.offensive.v3.capital.fees import (
    FeePolicy,
    FeeRevisionKind,
    compute_fee_components,
    fee_execution_id,
)
from src.screening.offensive.v3.capital.fills import (
    UNATTRIBUTED_LINEAGE,
    UNATTRIBUTED_PRODUCER,
    UNATTRIBUTED_PROGRAM,
    UNATTRIBUTED_STAGE,
    FeeRevisionRequest,
    FeeRevisionReceipt,
    FillRevisionRequest,
    FillRevisionReceipt,
    fee_idempotency_key,
    fill_idempotency_key,
    unattributed_position_identity,
)
from src.screening.offensive.v3.capital.flows import (
    NEW_RISK_BLOCKED_STATES,
    REDEMPTION_PAYABLE,
    SUBSCRIPTION_PAYABLE,
    FlowCancelRequest,
    FlowKind,
    FlowPriceReceipt,
    FlowPriceRequest,
    FlowRequestKind,
    FlowRequestState,
    FlowSettleReceipt,
    FlowSettleRequest,
    GenesisReceipt,
    GenesisRequest,
    LifecycleState,
    PayableState,
    RedemptionPaymentReceipt,
    RedemptionPaymentRequest,
    RedemptionRequest,
    RedemptionRequestReceipt,
    RiskEpochReceipt,
    RiskEpochRecord,
    RiskEpochRequest,
    SubscriptionReceipt,
    SubscriptionRequest,
    genesis_cash_cents,
)
from src.screening.offensive.v3.capital.identity import AccountBinding
from src.screening.offensive.v3.capital.nav import (
    LogGrowthKind,
    NavObservation,
    NavProjectionPath,
    ObservationKind,
    RestatementReceipt,
    RestatementRequest,
    ValuationReceipt,
    ValuationRequest,
    log_growth_kind_for,
    nav_ratio_lowest_terms,
    unit_price_lowest_terms,
)
from src.screening.offensive.v3.capital.reserves import (
    CONFIRMED_RELEASE_REASONS,
    CapitalReserveState,
    ReserveEntryRequest,
    ReserveReleaseReason,
    ReserveReleaseRequest,
)
from src.screening.offensive.v3.capital.risk_snapshot import (
    BuildRiskSnapshotRequest,
    CloseRiskSnapshotRequest,
    RiskSnapshotCloseReceipt,
    StageLossBudgetActivationRequest,
    StageLossChargeReceipt,
    StageLossChargeRequest,
)
from src.screening.offensive.v3.capital.risk_snapshot import (
    activate_stage_loss_budget as _activate_stage_loss_budget,
)
from src.screening.offensive.v3.capital.risk_snapshot import (
    build_capital_risk_snapshot as _build_capital_risk_snapshot,
)
from src.screening.offensive.v3.capital.risk_snapshot import (
    close_risk_snapshot as _close_risk_snapshot,
)
from src.screening.offensive.v3.capital.risk_snapshot import (
    record_stage_loss as _record_stage_loss,
)
from src.screening.offensive.v3.capital.risk_snapshot import (
    recompute_global_stage_loss_floor,
)
from src.screening.offensive.v3.capital.rounding import (
    MICROS_PER_CENT,
    fill_gross_cents,
    round_half_even_div,
)
from src.screening.offensive.v3.contracts import (
    CanonicalModel,
    CapitalPositionRisk,
    CapitalRiskSnapshot,
    CashEconomicEventLeg,
    CashReceivableEconomicEventLeg,
    CostBasisEconomicEventLeg,
    EconomicAssetKind,
    EconomicEvent,
    EconomicEventKind,
    EconomicEventLeg,
    EconomicLegDirection,
    EntryReserveRiskComponent,
    ExecutionMode,
    ExecutionRevisionKind,
    ExecutionSide,
    ExposureScope,
    content_hash,
    PositionState,
    RationalQuantity,
    ReconciliationLatchState,
    RiskExposureBucket,
    RiskLatchState,
    RiskSnapshotCompleteness,
    RiskSnapshotFreshness,
    SecurityEconomicEventLeg,
    Sha256,
    ShareReceivableEconomicEventLeg,
    StageLossLatchSnapshot,
    StageLossLatchState,
    UtcInstant,
    ValuationMarkEconomicEventLeg,
)
from src.screening.offensive.v3.contracts.evidence import NonEmptyStr
from src.screening.offensive.v3.storage.metadata import (
    CENT_SCALE,
    DRAWDOWN_HALT_PPM,
    GATEWAY_META_DEFAULTS,
    LEDGER_SCHEMA_VERSION,
    PRICE_MICRO_SCALE,
    RISK_SNAPSHOT_VALIDITY,
    SCHEMA_MAJOR,
    derive_event_id,
    derive_flow_event_id,
    derive_nav_observation_id,
    derive_risk_snapshot_id,
    drawdown_ppm,
    parse_utc,
    scaled_int,
    utc_iso,
    utc_now,
)
from src.screening.offensive.v3.storage.schema import (
    IMMUTABILITY_TRIGGER_DDL,
    build_metadata,
    configure_sqlite_connection,
)


__all__ = [
    "AccountBinding",
    "CapitalCommand",
    "CapitalCommandPayload",
    "CapitalConflict",
    "CapitalRepository",
    "GatewayTransactionContext",
]


class CapitalConflict(RuntimeError):
    """Fail-closed rejection of a capital command, retry, or store open."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = MappingProxyType(details)


# ``AccountBinding`` lives in ``capital/identity.py`` since Plan 02 Task 3 so
# the financing-flow DTOs can carry it without importing this module; it is
# imported above and re-exported unchanged through ``__all__``.


class CapitalCommandPayload(CanonicalModel):
    """The economic payload of one append command.

    The payload content hash is the canonical fact fingerprint: identical
    payloads deduplicate, divergent payloads under one idempotency key
    conflict.
    """

    event_kind: EconomicEventKind
    effective_at: UtcInstant
    source_authority: NonEmptyStr
    position_lineage_id: NonEmptyStr | None = None
    economic_lot_id: NonEmptyStr | None = None
    correction_of_event_id: NonEmptyStr | None = None
    legs: Annotated[tuple[EconomicEventLeg, ...], Field(min_length=1)]
    producer_namespace: NonEmptyStr | None = None
    research_program_id: NonEmptyStr | None = None
    economic_lineage_id: NonEmptyStr | None = None
    stage_id: NonEmptyStr | None = None
    # Plan 02 Task 4: the action-level corporate fact context (entitlement
    # rationals, authority tier, recorded inputs) persisted with the event.
    corporate_action: CorporateActionFact | None = None
    # Plan 02 Task 6: the execution bust/correction fact (fill or fee)
    # persisted with LATE_CORRECTION revision events; the projection and
    # the conservation replay both recompute from it.
    execution_revision: ExecutionRevisionFact | None = None

    @model_validator(mode="after")
    def validate_security_attribution(self) -> "CapitalCommandPayload":
        if any(
            leg.asset_kind is EconomicAssetKind.SHARE_RECEIVABLE
            for leg in self.legs
        ):
            if (
                self.position_lineage_id is None
                or self.economic_lot_id is None
            ):
                raise ValueError(
                    "share receivable legs require an economic lot identity"
                )
        if not any(
            leg.asset_kind is EconomicAssetKind.SECURITY for leg in self.legs
        ):
            return self
        required = {
            "position_lineage_id": self.position_lineage_id,
            "economic_lot_id": self.economic_lot_id,
            "producer_namespace": self.producer_namespace,
            "research_program_id": self.research_program_id,
            "economic_lineage_id": self.economic_lineage_id,
            "stage_id": self.stage_id,
        }
        missing = sorted(name for name, value in required.items() if value is None)
        if missing:
            raise ValueError(
                "security legs require lot identity and full risk attribution: "
                + ", ".join(missing)
            )
        return self


class CapitalCommand(CanonicalModel):
    """One atomic append request against the gateway transaction kernel."""

    idempotency_key: NonEmptyStr
    account_binding: AccountBinding
    expected_stream_version: Annotated[int, Field(ge=0)]
    as_of: UtcInstant
    payload: CapitalCommandPayload


ProjectorHook: TypeAlias = Callable[["GatewayTransactionContext"], None]


# Event kinds whose legs are projected by the Plan 02 Task 4 corporate
# action rules instead of the trade/fee loop. DIVIDEND_RECEIVABLE and
# DIVIDEND_CASH_SETTLED keep the generic receivable/cash projection, and
# SHARE_RECEIVABLE bookings use the generic loop with a dedicated leg
# handler (the projection difference lives in the share bucket only).
_CORPORATE_PROJECTION_KINDS = frozenset(
    {
        EconomicEventKind.SPLIT,
        EconomicEventKind.MERGE,
        EconomicEventKind.SECURITY_CONVERTED,
        EconomicEventKind.CORPORATE_CASH_SETTLED,
        EconomicEventKind.LEGAL_WRITE_OFF,
        EconomicEventKind.LATE_CORRECTION,
    }
)


class _SentinelType:
    """Distinguishes 'argument omitted' from an explicit None."""

    def __repr__(self) -> str:  # pragma: no cover - debug aid only
        return "<unset>"


_SENTINEL_UNSET = _SentinelType()


class GatewayTransactionContext:
    """One ``BEGIN IMMEDIATE ... COMMIT`` gateway transaction.

    Plan 04 composes seal/reserve/admission steps against the same context so
    the whole portfolio decision lands atomically; Plan 02 Task 1 wires the
    capital append path.
    """

    def __init__(self, repository: "CapitalRepository", connection: sa.engine.Connection) -> None:
        self._repository = repository
        self._connection = connection
        self._tables = repository._metadata.tables

    # -- step primitives ------------------------------------------------------

    def _table(self, name: str) -> sa.Table:
        return self._tables[name]

    def require_account_binding(self, binding: AccountBinding, as_of: datetime) -> None:
        table = self._table("account_capital_truth")
        row = self._connection.execute(table.select()).first()
        if row is None:
            self._connection.execute(
                table.insert().values(
                    portfolio_id=binding.portfolio_id,
                    broker_account_id=binding.broker_account_id,
                    execution_mode=binding.mode.value,
                    base_currency=binding.base_currency,
                    environment_fingerprint=binding.environment_fingerprint,
                    binding_content_hash=binding.content_hash(),
                    lifecycle_state=LifecycleState.ACTIVE.value,
                    bound_at=utc_iso(as_of),
                )
            )
            self._connection.execute(
                self._table("capital_projection").insert().values(
                    portfolio_id=binding.portfolio_id,
                    available_cash_cents=0,
                    restricted_cash_cents=0,
                    unsettled_cash_cents=0,
                    subscription_suspense_cash_cents=0,
                    redemption_suspense_cash_cents=0,
                    issued_unit_quanta=0,
                    pending_redeemed_unit_quanta=0,
                    as_observed_nav_cents=0,
                    lifetime_high_water_mark_cents=0,
                    active_epoch_high_water_mark_cents=0,
                    lifecycle_state=LifecycleState.ACTIVE.value,
                    capital_version=0,
                    updated_at=utc_iso(as_of),
                    updated_by_event_id=None,
                )
            )
            return
        stored = AccountBinding(
            portfolio_id=row.portfolio_id,
            mode=ExecutionMode(row.execution_mode),
            broker_account_id=row.broker_account_id,
            base_currency=row.base_currency,
            environment_fingerprint=row.environment_fingerprint,
        )
        if stored.content_hash() != binding.content_hash():
            raise CapitalConflict(
                "account_binding_mismatch",
                "command binding differs from the bound AccountCapitalTruth identity",
                bound_portfolio_id=row.portfolio_id,
                requested_portfolio_id=binding.portfolio_id,
            )

    def current_stream_version(self) -> int:
        row = self._connection.execute(
            sa.text("SELECT COALESCE(MAX(stream_version), 0) AS v FROM economic_events")
        ).one()
        return int(row.v)

    def require_stream_version(self, expected: int) -> None:
        actual = self.current_stream_version()
        if actual != expected:
            raise CapitalConflict(
                "stream_version_mismatch",
                "compare-and-swap failed: the capital stream advanced",
                expected=expected,
                actual=actual,
            )

    def insert_canonical_event(self, command: CapitalCommand) -> EconomicEvent:
        """Insert the canonical event plus legs for an already-CAS-checked command.

        Idempotency and payload-conflict detection happen in ``run_append``
        before the stream CAS; the UNIQUE constraints on ``idempotency_key``
        and ``payload_content_hash`` remain the last line of defense.
        """

        binding = command.account_binding
        payload_hash = command.payload.content_hash()
        stream_version = self.current_stream_version() + 1
        try:
            event = EconomicEvent(
                economic_event_id=derive_event_id(command.idempotency_key),
                event_kind=command.payload.event_kind,
                portfolio_id=binding.portfolio_id,
                position_lineage_id=command.payload.position_lineage_id,
                economic_lot_id=command.payload.economic_lot_id,
                mode=binding.mode,
                source_authority=command.payload.source_authority,
                effective_at=command.payload.effective_at,
                recorded_at=command.as_of,
                stream_version=stream_version,
                correction_of_event_id=command.payload.correction_of_event_id,
                legs=command.payload.legs,
                payload_content_hash=payload_hash,
            )
        except ValidationError as exc:
            raise CapitalConflict(
                "event_contract_rejected",
                "command payload violates the EconomicEvent contract",
                detail=str(exc),
            ) from exc

        events_table = self._table("economic_events")
        self._connection.execute(
            events_table.insert().values(
                economic_event_id=event.economic_event_id,
                idempotency_key=command.idempotency_key,
                stream_version=event.stream_version,
                event_kind=event.event_kind.value,
                portfolio_id=event.portfolio_id,
                position_lineage_id=event.position_lineage_id,
                economic_lot_id=event.economic_lot_id,
                execution_mode=event.mode.value,
                source_authority=event.source_authority,
                effective_at=utc_iso(event.effective_at),
                recorded_at=utc_iso(event.recorded_at),
                correction_of_event_id=event.correction_of_event_id,
                payload_json=command.payload.model_dump_json(),
                payload_content_hash=payload_hash,
                canonical_event_json=event.model_dump_json(),
            )
        )
        legs_table = self._table("economic_event_legs")
        for sequence, leg in enumerate(event.legs):
            self._connection.execute(
                legs_table.insert().values(
                    **self._leg_row_values(event.economic_event_id, sequence, leg)
                )
            )
        return event

    def _leg_row_values(
        self, event_id: str, sequence: int, leg: Any
    ) -> dict[str, Any]:
        # Valuation-mark legs carry no debit/credit direction.
        direction = getattr(leg, "direction", None)
        values: dict[str, Any] = {
            "leg_id": leg.leg_id,
            "economic_event_id": event_id,
            "sequence": sequence,
            "asset_kind": leg.asset_kind.value,
            "direction": direction.value if direction is not None else None,
            "cash_amount_cents": None,
            "security_id": None,
            "quantity_units": None,
            "receivable_id": None,
            "cost_basis_cents": None,
            "mark_price_micros": None,
        }
        try:
            if isinstance(leg, CashEconomicEventLeg):
                values["cash_amount_cents"] = scaled_int(
                    leg.cash_amount, CENT_SCALE, "cash_amount"
                )
            elif isinstance(leg, SecurityEconomicEventLeg):
                values["security_id"] = leg.security_id
                values["quantity_units"] = leg.quantity
            elif isinstance(leg, CashReceivableEconomicEventLeg):
                values["receivable_id"] = leg.receivable_id
                values["security_id"] = leg.security_id
                values["cash_amount_cents"] = scaled_int(
                    leg.cash_amount, CENT_SCALE, "cash_amount"
                )
            elif isinstance(leg, ShareReceivableEconomicEventLeg):
                values["receivable_id"] = leg.receivable_id
                values["security_id"] = leg.security_id
                values["quantity_units"] = leg.quantity
            elif isinstance(leg, CostBasisEconomicEventLeg):
                values["security_id"] = leg.security_id
                values["cost_basis_cents"] = scaled_int(
                    leg.cost_basis_amount, CENT_SCALE, "cost_basis_amount"
                )
            elif isinstance(leg, ValuationMarkEconomicEventLeg):
                values["security_id"] = leg.security_id
                values["mark_price_micros"] = scaled_int(
                    leg.mark_price, PRICE_MICRO_SCALE, "mark_price"
                )
            else:  # pragma: no cover - discriminated union is closed
                raise ValueError(f"unknown economic leg type: {type(leg).__name__}")
        except ValueError as exc:
            raise CapitalConflict(
                "projection_rejected",
                f"leg quanta encoding failed: {exc}",
                leg_id=leg.leg_id,
            ) from exc
        return values

    # -- projection -----------------------------------------------------------

    def apply_legs_and_projection(
        self, event: EconomicEvent, command: CapitalCommand
    ) -> None:
        if event.event_kind is EconomicEventKind.VALUATION:
            # Valuation events only update marks/NAV; they never change
            # position state, cash, or shares (Plan 02 Task 3).
            self._apply_valuation_event(event, command)
            return

        if event.event_kind in _CORPORATE_PROJECTION_KINDS:
            # Splits, conversions, terminal settlements, write-offs and
            # their corrections own dedicated projection rules (Plan 02
            # Task 4): trade state-machine and basis rules never apply.
            self._apply_corporate_action_event(event, command)
            return

        projection_table = self._table("capital_projection")
        projection = self._connection.execute(projection_table.select()).one()
        available_cash_cents = int(projection.available_cash_cents)

        for leg in event.legs:
            if leg.asset_kind is EconomicAssetKind.CASH:
                amount_cents = scaled_int(leg.cash_amount, CENT_SCALE, "cash_amount")
                if leg.direction is EconomicLegDirection.CREDIT:
                    available_cash_cents += amount_cents
                else:
                    available_cash_cents -= amount_cents
            elif leg.asset_kind is EconomicAssetKind.SECURITY:
                self._apply_security_leg(event, command, leg)
            elif leg.asset_kind is EconomicAssetKind.CASH_RECEIVABLE:
                self._apply_cash_receivable_leg(event, leg)
            elif leg.asset_kind is EconomicAssetKind.SHARE_RECEIVABLE:
                # Ex-date bonus/transfer entitlements book vested but not
                # yet tradable shares (Plan 02 Task 4); every other event
                # kind routes share receivable legs through the corporate
                # action projection instead.
                if event.event_kind is not EconomicEventKind.SHARE_RECEIVABLE:
                    raise CapitalConflict(
                        "projection_rejected",
                        "share receivable legs require a SHARE_RECEIVABLE event",
                        economic_event_id=event.economic_event_id,
                    )
                self._apply_share_receivable_leg(event, leg)
            else:
                raise CapitalConflict(
                    "projection_rejected",
                    "asset kind "
                    f"{leg.asset_kind.value} is reserved for later Plan 02 tasks",
                    economic_event_id=event.economic_event_id,
                )

        if available_cash_cents < 0:
            raise CapitalConflict(
                "projection_rejected",
                "cash projection would become negative",
                available_cash_cents=available_cash_cents,
            )

        self._connection.execute(
            projection_table.update()
            .where(projection_table.c.portfolio_id == projection.portfolio_id)
            .values(
                available_cash_cents=available_cash_cents,
                capital_version=int(projection.capital_version) + 1,
                updated_at=utc_iso(command.as_of),
                updated_by_event_id=event.economic_event_id,
            )
        )

    def _apply_security_leg(
        self, event: EconomicEvent, command: CapitalCommand, leg: Any
    ) -> None:
        positions_table = self._table("positions")
        row = self._connection.execute(
            positions_table.select().where(
                sa.and_(
                    positions_table.c.position_lineage_id == event.position_lineage_id,
                    positions_table.c.economic_lot_id == event.economic_lot_id,
                )
            )
        ).first()
        quantity = int(leg.quantity)
        now = utc_iso(event.recorded_at)

        if leg.direction is EconomicLegDirection.CREDIT:
            if row is not None and row.state != PositionState.OPEN.value:
                raise CapitalConflict(
                    "projection_rejected",
                    "entry into an exiting or closed economic lot is rejected",
                    economic_lot_id=event.economic_lot_id,
                    state=row.state,
                )
            if row is None:
                payload = command.payload
                if (
                    payload.producer_namespace is None
                    or payload.research_program_id is None
                    or payload.economic_lineage_id is None
                    or payload.stage_id is None
                ):  # pragma: no cover - command validator enforces attribution
                    raise CapitalConflict(
                        "projection_rejected",
                        "position requires full risk attribution",
                    )
                self._connection.execute(
                    positions_table.insert().values(
                        position_lineage_id=event.position_lineage_id,
                        economic_lot_id=event.economic_lot_id,
                        security_id=leg.security_id,
                        state=PositionState.OPEN.value,
                        settled_quantity_units=quantity,
                        tradable_quantity_units=quantity,
                        share_receivable_quantity_units=0,
                        cost_basis_cents=0,
                        producer_namespace=payload.producer_namespace,
                        research_program_id=payload.research_program_id,
                        economic_lineage_id=payload.economic_lineage_id,
                        stage_id=payload.stage_id,
                        opened_by_event_id=event.economic_event_id,
                        updated_by_event_id=event.economic_event_id,
                        updated_at=now,
                    )
                )
            else:
                if row.security_id != leg.security_id:
                    raise CapitalConflict(
                        "projection_rejected",
                        "security identity mismatch on economic lot",
                        economic_lot_id=event.economic_lot_id,
                    )
                self._connection.execute(
                    positions_table.update()
                    .where(
                        sa.and_(
                            positions_table.c.position_lineage_id
                            == event.position_lineage_id,
                            positions_table.c.economic_lot_id == event.economic_lot_id,
                        )
                    )
                    .values(
                        settled_quantity_units=int(row.settled_quantity_units)
                        + quantity,
                        tradable_quantity_units=int(row.tradable_quantity_units)
                        + quantity,
                        updated_by_event_id=event.economic_event_id,
                        updated_at=now,
                    )
                )
            if event.event_kind is EconomicEventKind.TRADE_EXECUTED:
                cash_debit_cents = sum(
                    scaled_int(item.cash_amount, CENT_SCALE, "cash_amount")
                    for item in event.legs
                    if item.asset_kind is EconomicAssetKind.CASH
                    and item.direction is EconomicLegDirection.DEBIT
                )
                self._connection.execute(
                    positions_table.update()
                    .where(
                        sa.and_(
                            positions_table.c.position_lineage_id
                            == event.position_lineage_id,
                            positions_table.c.economic_lot_id == event.economic_lot_id,
                        )
                    )
                    .values(
                        cost_basis_cents=positions_table.c.cost_basis_cents
                        + cash_debit_cents
                    )
                )
            return

        if row is None:
            raise CapitalConflict(
                "projection_rejected",
                "security debit against unknown position",
                economic_lot_id=event.economic_lot_id,
            )
        if row.state in (
            PositionState.CLOSED.value,
            PositionState.LEGAL_TERMINAL.value,
        ):
            raise CapitalConflict(
                "projection_rejected",
                "exit against a terminal economic lot is rejected",
                economic_lot_id=event.economic_lot_id,
                state=row.state,
            )
        old_settled = int(row.settled_quantity_units)
        new_settled = old_settled - quantity
        new_tradable = int(row.tradable_quantity_units) - quantity
        if new_settled < 0 or new_tradable < 0:
            raise CapitalConflict(
                "projection_rejected",
                "security projection would become negative; impossible states are"
                " preserved for reconciliation, never clamped",
                economic_lot_id=event.economic_lot_id,
            )
        values: dict[str, Any] = {
            "settled_quantity_units": new_settled,
            "tradable_quantity_units": new_tradable,
            "updated_by_event_id": event.economic_event_id,
            "updated_at": now,
        }
        if event.event_kind is EconomicEventKind.TRADE_EXECUTED:
            # Versioned average-cost basis consumption (round-half-even); a
            # fill exhausting the lot consumes the exact remainder so closed
            # lots never carry a rounding residue.
            basis_cents = int(row.cost_basis_cents)
            if quantity == old_settled:
                consumed_cents = basis_cents
            else:
                consumed_cents = round_half_even_div(
                    basis_cents * quantity, old_settled
                )
            values["cost_basis_cents"] = basis_cents - consumed_cents
        if new_settled == 0:
            values["state"] = PositionState.CLOSED.value
        else:
            values["state"] = PositionState.EXIT_PENDING.value
        self._connection.execute(
            positions_table.update()
            .where(
                sa.and_(
                    positions_table.c.position_lineage_id
                    == event.position_lineage_id,
                    positions_table.c.economic_lot_id == event.economic_lot_id,
                )
            )
            .values(**values)
        )

    def _apply_cash_receivable_leg(self, event: EconomicEvent, leg: Any) -> None:
        receivables_table = self._table("receivables")
        row = self._connection.execute(
            receivables_table.select().where(
                receivables_table.c.receivable_id == leg.receivable_id
            )
        ).first()
        amount_cents = scaled_int(leg.cash_amount, CENT_SCALE, "cash_amount")
        now = utc_iso(event.recorded_at)

        if leg.direction is EconomicLegDirection.CREDIT:
            if row is not None:
                raise CapitalConflict(
                    "projection_rejected",
                    "receivable already exists",
                    receivable_id=leg.receivable_id,
                )
            self._connection.execute(
                receivables_table.insert().values(
                    receivable_id=leg.receivable_id,
                    receivable_kind="CASH",
                    security_id=leg.security_id,
                    position_lineage_id=event.position_lineage_id,
                    amount_cents=amount_cents,
                    quantity_units=None,
                    settled=0,
                    created_by_event_id=event.economic_event_id,
                    settled_by_event_id=None,
                    updated_at=now,
                )
            )
            return

        if row is None:
            raise CapitalConflict(
                "projection_rejected",
                "receivable debit against unknown receivable",
                receivable_id=leg.receivable_id,
            )
        if int(row.settled) != 0:
            raise CapitalConflict(
                "projection_rejected",
                "receivable already settled",
                receivable_id=leg.receivable_id,
            )
        if int(row.amount_cents) != amount_cents:
            raise CapitalConflict(
                "projection_rejected",
                "receivable settlement amount mismatch",
                receivable_id=leg.receivable_id,
                expected_cents=int(row.amount_cents),
                requested_cents=amount_cents,
            )
        self._connection.execute(
            receivables_table.update()
            .where(receivables_table.c.receivable_id == leg.receivable_id)
            .values(
                settled=1,
                settled_by_event_id=event.economic_event_id,
                updated_at=now,
            )
        )

    # -- Plan 02 Task 4: corporate action projection --------------------------

    def corporate_action_row(
        self, action_id: str, position_lineage_id: str, economic_lot_id: str
    ) -> Any | None:
        table = self._table("corporate_actions")
        return self._connection.execute(
            table.select().where(
                sa.and_(
                    table.c.action_id == action_id,
                    table.c.position_lineage_id == position_lineage_id,
                    table.c.economic_lot_id == economic_lot_id,
                )
            )
        ).first()

    def position_row(self, position_lineage_id: str, economic_lot_id: str) -> Any | None:
        table = self._table("positions")
        return self._connection.execute(
            table.select().where(
                sa.and_(
                    table.c.position_lineage_id == position_lineage_id,
                    table.c.economic_lot_id == economic_lot_id,
                )
            )
        ).first()

    def receivable_row(self, receivable_id: str) -> Any | None:
        table = self._table("receivables")
        return self._connection.execute(
            table.select().where(table.c.receivable_id == receivable_id)
        ).first()

    def unsettled_share_receivable_rows(
        self, position_lineage_id: str
    ) -> tuple[Any, ...]:
        return tuple(
            self._connection.execute(
                sa.text(
                    "SELECT * FROM receivables"
                    " WHERE receivable_kind = 'SHARE' AND settled = 0"
                    " AND position_lineage_id = :lineage"
                    " ORDER BY receivable_id"
                ),
                {"lineage": position_lineage_id},
            ).all()
        )

    def _book_share_receivable_row(
        self, event: EconomicEvent, receivable_id: str, security_id: str, quantity: int
    ) -> None:
        if self.receivable_row(receivable_id) is not None:
            raise CapitalConflict(
                "projection_rejected",
                "share receivable already exists",
                receivable_id=receivable_id,
            )
        self._connection.execute(
            self._table("receivables").insert().values(
                receivable_id=receivable_id,
                receivable_kind="SHARE",
                security_id=security_id,
                position_lineage_id=event.position_lineage_id,
                amount_cents=None,
                quantity_units=quantity,
                settled=0,
                created_by_event_id=event.economic_event_id,
                settled_by_event_id=None,
                updated_at=utc_iso(event.recorded_at),
            )
        )

    def _settle_share_receivable_row(
        self, event: EconomicEvent, receivable_id: str, quantity: int
    ) -> None:
        row = self.receivable_row(receivable_id)
        if row is None:
            raise CapitalConflict(
                "projection_rejected",
                "share receivable debit against unknown receivable",
                receivable_id=receivable_id,
            )
        if int(row.settled) != 0:
            raise CapitalConflict(
                "projection_rejected",
                "share receivable already settled",
                receivable_id=receivable_id,
            )
        if int(row.quantity_units) != quantity:
            raise CapitalConflict(
                "projection_rejected",
                "share receivable settlement quantity mismatch",
                receivable_id=receivable_id,
                expected_units=int(row.quantity_units),
                requested_units=quantity,
            )
        self._connection.execute(
            self._table("receivables").update()
            .where(self._table("receivables").c.receivable_id == receivable_id)
            .values(
                settled=1,
                settled_by_event_id=event.economic_event_id,
                updated_at=utc_iso(event.recorded_at),
            )
        )

    def _adjust_position_share_buckets(
        self,
        event: EconomicEvent,
        *,
        settled_delta: int = 0,
        tradable_delta: int = 0,
        share_receivable_delta: int = 0,
    ) -> Any:
        """Apply share-bucket deltas to the lot row, never clamping.

        Impossible negative states are preserved for reconciliation (they
        fail closed here instead of being hidden), mirroring the trade
        projection rule.
        """

        positions_table = self._table("positions")
        row = self.position_row(
            event.position_lineage_id, event.economic_lot_id
        )
        if row is None:
            raise CapitalConflict(
                "projection_rejected",
                "corporate action references an unknown economic lot",
                economic_lot_id=event.economic_lot_id,
            )
        new_settled = int(row.settled_quantity_units) + settled_delta
        new_tradable = int(row.tradable_quantity_units) + tradable_delta
        new_receivable = (
            int(row.share_receivable_quantity_units) + share_receivable_delta
        )
        if new_settled < 0 or new_tradable < 0 or new_receivable < 0:
            raise CapitalConflict(
                "projection_rejected",
                "corporate action share projection would become negative;"
                " impossible states are preserved for reconciliation, never"
                " clamped",
                economic_lot_id=event.economic_lot_id,
            )
        self._connection.execute(
            positions_table.update()
            .where(
                sa.and_(
                    positions_table.c.position_lineage_id
                    == event.position_lineage_id,
                    positions_table.c.economic_lot_id == event.economic_lot_id,
                )
            )
            .values(
                settled_quantity_units=new_settled,
                tradable_quantity_units=new_tradable,
                share_receivable_quantity_units=new_receivable,
                updated_by_event_id=event.economic_event_id,
                updated_at=utc_iso(event.recorded_at),
            )
        )
        return row

    def _apply_share_receivable_leg(self, event: EconomicEvent, leg: Any) -> None:
        """Book one vested-but-untradable share entitlement (ex date)."""

        positions_table = self._table("positions")
        row = self.position_row(
            event.position_lineage_id, event.economic_lot_id
        )
        if row is None:
            raise CapitalConflict(
                "projection_rejected",
                "share entitlement references an unknown economic lot",
                economic_lot_id=event.economic_lot_id,
            )
        if row.state not in (
            PositionState.OPEN.value,
            PositionState.EXIT_PENDING.value,
        ):
            raise CapitalConflict(
                "projection_rejected",
                "share entitlement against a terminal economic lot",
                economic_lot_id=event.economic_lot_id,
                state=row.state,
            )
        if row.security_id != leg.security_id:
            raise CapitalConflict(
                "projection_rejected",
                "share entitlement security does not match the economic lot",
                economic_lot_id=event.economic_lot_id,
            )
        quantity = int(leg.quantity)
        self._book_share_receivable_row(
            event, leg.receivable_id, leg.security_id, quantity
        )
        self._connection.execute(
            positions_table.update()
            .where(
                sa.and_(
                    positions_table.c.position_lineage_id
                    == event.position_lineage_id,
                    positions_table.c.economic_lot_id == event.economic_lot_id,
                )
            )
            .values(
                share_receivable_quantity_units=(
                    positions_table.c.share_receivable_quantity_units + quantity
                ),
                updated_by_event_id=event.economic_event_id,
                updated_at=utc_iso(event.recorded_at),
            )
        )

    def _apply_corporate_action_event(
        self, event: EconomicEvent, command: CapitalCommand
    ) -> None:
        kind = event.event_kind
        if (
            kind is EconomicEventKind.LATE_CORRECTION
            and command.payload.execution_revision is not None
        ):
            # Plan 02 Task 6: execution bust/correction facts own their
            # projection rules (exact reversal, reopen, preserved negative
            # states); receivable-only corporate corrections keep theirs.
            self._apply_execution_revision_event(event, command)
        elif kind in (EconomicEventKind.SPLIT, EconomicEventKind.MERGE):
            self._apply_split_merge(event)
        elif kind is EconomicEventKind.SECURITY_CONVERTED:
            self._apply_security_conversion(event)
        elif kind is EconomicEventKind.CORPORATE_CASH_SETTLED:
            self._apply_corporate_cash_settlement(event)
        elif kind is EconomicEventKind.LEGAL_WRITE_OFF:
            self._apply_legal_write_off(event)
        elif kind is EconomicEventKind.LATE_CORRECTION:
            self._apply_late_correction(event)
        else:  # pragma: no cover - dispatch table is closed
            raise CapitalConflict(
                "projection_rejected",
                f"unsupported corporate action event kind {kind.value}",
            )

        # One capital fact changed: bump the capital version exactly once,
        # in the same transaction as the projection update.
        projection_table = self._table("capital_projection")
        projection = self._connection.execute(projection_table.select()).one()
        self._connection.execute(
            projection_table.update()
            .where(projection_table.c.portfolio_id == projection.portfolio_id)
            .values(
                capital_version=int(projection.capital_version) + 1,
                updated_at=utc_iso(command.as_of),
                updated_by_event_id=event.economic_event_id,
            )
        )

    def _apply_split_merge(self, event: EconomicEvent) -> None:
        """Quantity transformation with the aggregate basis preserved."""

        for leg in event.legs:
            if leg.asset_kind is EconomicAssetKind.COST_BASIS:
                raise CapitalConflict(
                    "projection_rejected",
                    "COST_BASIS legs remain fail-closed; the aggregate basis"
                    " is preserved by the position projection instead",
                    economic_event_id=event.economic_event_id,
                )
        debits = [
            leg
            for leg in event.legs
            if leg.asset_kind is EconomicAssetKind.SECURITY
            and leg.direction is EconomicLegDirection.DEBIT
        ]
        credits = [
            leg
            for leg in event.legs
            if leg.asset_kind is EconomicAssetKind.SECURITY
            and leg.direction is EconomicLegDirection.CREDIT
        ]
        if len(debits) != 1 or len(credits) != 1:
            raise CapitalConflict(
                "projection_rejected",
                "split/merge requires exactly one security debit and one"
                " security credit leg",
                economic_event_id=event.economic_event_id,
            )
        debit, credit = debits[0], credits[0]
        row = self.position_row(
            event.position_lineage_id, event.economic_lot_id
        )
        if row is None:
            raise CapitalConflict(
                "projection_rejected",
                "split/merge references an unknown economic lot",
                economic_lot_id=event.economic_lot_id,
            )
        if row.state not in (
            PositionState.OPEN.value,
            PositionState.EXIT_PENDING.value,
        ):
            raise CapitalConflict(
                "projection_rejected",
                "split/merge against a terminal economic lot",
                economic_lot_id=event.economic_lot_id,
                state=row.state,
            )
        if debit.security_id != row.security_id or (
            credit.security_id != row.security_id
        ):
            raise CapitalConflict(
                "projection_rejected",
                "split/merge security does not match the economic lot",
                economic_lot_id=event.economic_lot_id,
            )
        if int(debit.quantity) != int(row.settled_quantity_units):
            raise CapitalConflict(
                "projection_rejected",
                "split/merge must transform the whole settled quantity",
                economic_lot_id=event.economic_lot_id,
            )
        # Aggregate basis is untouched: the per-share basis becomes the
        # exact rational basis / new quantity (never a float). Position
        # state is preserved, so a due exit obligation survives the split.
        self._adjust_position_share_buckets(
            event,
            settled_delta=int(credit.quantity) - int(debit.quantity),
            tradable_delta=int(credit.quantity) - int(debit.quantity),
        )

    def _apply_security_conversion(self, event: EconomicEvent) -> None:
        """Successor mapping or the tradable-date representation change.

        Two validated shapes:

        - tradable date (representation change): one same-security
          debit/credit pair of equal quantity plus one or more share
          receivable debits. The pair nets to zero settled shares; the
          share receivable debits move vested shares into settled
          tradable quantity. The pair never consumes settled shares, so
          a bonus larger than the holding still converts cleanly.
        - whole-lot conversion: the security debits sweep the whole
          economic holding (settled plus vested receivable), and the
          single destination representation is either a successor
          security credit (tradable) or a successor share receivable
          credit (restricted).
        """

        for leg in event.legs:
            if leg.asset_kind is EconomicAssetKind.COST_BASIS:
                raise CapitalConflict(
                    "projection_rejected",
                    "COST_BASIS legs remain fail-closed; conversion carries"
                    " the aggregate basis through the position projection",
                    economic_event_id=event.economic_event_id,
                )
        security_debits = [
            leg
            for leg in event.legs
            if leg.asset_kind is EconomicAssetKind.SECURITY
            and leg.direction is EconomicLegDirection.DEBIT
        ]
        security_credits = [
            leg
            for leg in event.legs
            if leg.asset_kind is EconomicAssetKind.SECURITY
            and leg.direction is EconomicLegDirection.CREDIT
        ]
        share_debits = [
            leg
            for leg in event.legs
            if leg.asset_kind is EconomicAssetKind.SHARE_RECEIVABLE
            and leg.direction is EconomicLegDirection.DEBIT
        ]
        share_credits = [
            leg
            for leg in event.legs
            if leg.asset_kind is EconomicAssetKind.SHARE_RECEIVABLE
            and leg.direction is EconomicLegDirection.CREDIT
        ]
        row = self.position_row(
            event.position_lineage_id, event.economic_lot_id
        )
        if row is None:
            raise CapitalConflict(
                "projection_rejected",
                "conversion references an unknown economic lot",
                economic_lot_id=event.economic_lot_id,
            )
        if row.state not in (
            PositionState.OPEN.value,
            PositionState.EXIT_PENDING.value,
        ):
            raise CapitalConflict(
                "projection_rejected",
                "conversion against a terminal economic lot",
                economic_lot_id=event.economic_lot_id,
                state=row.state,
            )

        representation_change = (
            len(security_debits) == 1
            and len(security_credits) == 1
            and security_debits[0].security_id == security_credits[0].security_id
            and int(security_debits[0].quantity)
            == int(security_credits[0].quantity)
            and bool(share_debits)
            and not share_credits
        )
        if representation_change:
            quantity = int(security_debits[0].quantity)
            share_debit_total = sum(int(leg.quantity) for leg in share_debits)
            if share_debit_total != quantity:
                raise CapitalConflict(
                    "projection_rejected",
                    "tradable-date conversion legs do not balance",
                    economic_lot_id=event.economic_lot_id,
                )
            for leg in share_debits:
                self._settle_share_receivable_row(
                    event, leg.receivable_id, int(leg.quantity)
                )
            # Vested receivable shares become settled AND tradable; the
            # same-security pair is a representation change only and never
            # touches settled quantity.
            self._adjust_position_share_buckets(
                event,
                settled_delta=quantity,
                tradable_delta=quantity,
                share_receivable_delta=-quantity,
            )
            return

        total_held = int(row.settled_quantity_units) + int(
            row.share_receivable_quantity_units
        )
        debit_total = sum(int(leg.quantity) for leg in security_debits)
        if debit_total != total_held:
            raise CapitalConflict(
                "projection_rejected",
                "conversion must sweep the whole economic holding of the lot",
                economic_lot_id=event.economic_lot_id,
                expected_units=total_held,
                requested_units=debit_total,
            )
        for leg in security_debits:
            if leg.security_id != row.security_id:
                raise CapitalConflict(
                    "projection_rejected",
                    "conversion source security does not match the lot",
                    economic_lot_id=event.economic_lot_id,
                )
        if len(security_credits) > 1 or len(share_credits) > 1:
            raise CapitalConflict(
                "projection_rejected",
                "conversion requires exactly one destination representation",
                economic_lot_id=event.economic_lot_id,
            )
        share_debit_total = sum(int(leg.quantity) for leg in share_debits)
        if share_debit_total != int(row.share_receivable_quantity_units):
            raise CapitalConflict(
                "projection_rejected",
                "conversion must settle every outstanding share receivable"
                " of the lot",
                economic_lot_id=event.economic_lot_id,
            )
        for leg in share_debits:
            self._settle_share_receivable_row(
                event, leg.receivable_id, int(leg.quantity)
            )

        positions_table = self._table("positions")
        now = utc_iso(event.recorded_at)
        if security_credits:
            destination = security_credits[0]
            if destination.security_id == row.security_id:
                raise CapitalConflict(
                    "projection_rejected",
                    "conversion successor must differ from the source"
                    " security",
                    economic_lot_id=event.economic_lot_id,
                )
            new_quantity = int(destination.quantity)
            # The successor inherits the lot identity, attribution, cost
            # basis, and state (the due exit obligation). Only the
            # security and the quantities move.
            self._connection.execute(
                positions_table.update()
                .where(
                    sa.and_(
                        positions_table.c.position_lineage_id
                        == event.position_lineage_id,
                        positions_table.c.economic_lot_id
                        == event.economic_lot_id,
                    )
                )
                .values(
                    security_id=destination.security_id,
                    settled_quantity_units=new_quantity,
                    tradable_quantity_units=new_quantity,
                    share_receivable_quantity_units=0,
                    updated_by_event_id=event.economic_event_id,
                    updated_at=now,
                )
            )
            return

        destination = share_credits[0]
        if destination.security_id == row.security_id:
            raise CapitalConflict(
                "projection_rejected",
                "conversion successor must differ from the source security",
                economic_lot_id=event.economic_lot_id,
            )
        new_quantity = int(destination.quantity)
        self._book_share_receivable_row(
            event,
            destination.receivable_id,
            destination.security_id,
            new_quantity,
        )
        self._connection.execute(
            positions_table.update()
            .where(
                sa.and_(
                    positions_table.c.position_lineage_id
                    == event.position_lineage_id,
                    positions_table.c.economic_lot_id == event.economic_lot_id,
                )
            )
            .values(
                security_id=destination.security_id,
                settled_quantity_units=0,
                tradable_quantity_units=0,
                share_receivable_quantity_units=new_quantity,
                updated_by_event_id=event.economic_event_id,
                updated_at=now,
            )
        )

    def _apply_terminal_lot_sweep(
        self, event: EconomicEvent, *, consume_cash_legs: bool
    ) -> tuple[Any, int]:
        """Sweep every remaining share asset of the lot and terminate it.

        Shared by CORPORATE_CASH_SETTLED (proceeds credit follows) and
        LEGAL_WRITE_OFF (no proceeds). The aggregate basis is consumed in
        full: the lot is legally gone, so its basis becomes a realized
        result, never a lingering asset.
        """

        positions_table = self._table("positions")
        row = self.position_row(
            event.position_lineage_id, event.economic_lot_id
        )
        if row is None:
            raise CapitalConflict(
                "projection_rejected",
                "terminal corporate action references an unknown economic lot",
                economic_lot_id=event.economic_lot_id,
            )
        if row.state not in (
            PositionState.OPEN.value,
            PositionState.EXIT_PENDING.value,
        ):
            raise CapitalConflict(
                "projection_rejected",
                "terminal corporate action against a terminal economic lot",
                economic_lot_id=event.economic_lot_id,
                state=row.state,
            )
        security_debits = [
            leg
            for leg in event.legs
            if leg.asset_kind is EconomicAssetKind.SECURITY
            and leg.direction is EconomicLegDirection.DEBIT
        ]
        share_debits = [
            leg
            for leg in event.legs
            if leg.asset_kind is EconomicAssetKind.SHARE_RECEIVABLE
            and leg.direction is EconomicLegDirection.DEBIT
        ]
        security_debit_total = sum(int(leg.quantity) for leg in security_debits)
        if security_debit_total != int(row.settled_quantity_units):
            raise CapitalConflict(
                "projection_rejected",
                "terminal corporate action must sweep the whole settled"
                " quantity",
                economic_lot_id=event.economic_lot_id,
            )
        for leg in security_debits:
            if leg.security_id != row.security_id:
                raise CapitalConflict(
                    "projection_rejected",
                    "terminal corporate action security does not match the lot",
                    economic_lot_id=event.economic_lot_id,
                )
        share_debit_total = sum(int(leg.quantity) for leg in share_debits)
        if share_debit_total != int(row.share_receivable_quantity_units):
            raise CapitalConflict(
                "projection_rejected",
                "terminal corporate action must settle every outstanding"
                " share receivable of the lot",
                economic_lot_id=event.economic_lot_id,
            )
        for leg in share_debits:
            self._settle_share_receivable_row(
                event, leg.receivable_id, int(leg.quantity)
            )
        for leg in event.legs:
            if leg.asset_kind is EconomicAssetKind.CASH_RECEIVABLE:
                self._apply_cash_receivable_leg(event, leg)
            elif leg.asset_kind is EconomicAssetKind.COST_BASIS:
                raise CapitalConflict(
                    "projection_rejected",
                    "COST_BASIS legs remain fail-closed; terminal settlement"
                    " consumes the aggregate basis through the position"
                    " projection",
                    economic_event_id=event.economic_event_id,
                )

        cash_credit_cents = 0
        for leg in event.legs:
            if leg.asset_kind is not EconomicAssetKind.CASH:
                continue
            if leg.direction is not EconomicLegDirection.CREDIT:
                raise CapitalConflict(
                    "projection_rejected",
                    "terminal corporate action cash legs must be credits",
                    economic_event_id=event.economic_event_id,
                )
            if not consume_cash_legs:
                raise CapitalConflict(
                    "projection_rejected",
                    "legal write-off cannot move cash",
                    economic_event_id=event.economic_event_id,
                )
            cash_credit_cents += scaled_int(
                leg.cash_amount, CENT_SCALE, "cash_amount"
            )
        if consume_cash_legs:
            projection_table = self._table("capital_projection")
            projection = self._connection.execute(
                projection_table.select()
            ).one()
            self._connection.execute(
                projection_table.update()
                .where(
                    projection_table.c.portfolio_id == projection.portfolio_id
                )
                .values(
                    available_cash_cents=(
                        int(projection.available_cash_cents) + cash_credit_cents
                    )
                )
            )

        # OPEN -> EXIT_PENDING -> LEGAL_TERMINAL walked atomically inside
        # this one capital transaction (the frozen transition map admits no
        # direct OPEN -> LEGAL_TERMINAL edge).
        self._connection.execute(
            positions_table.update()
            .where(
                sa.and_(
                    positions_table.c.position_lineage_id
                    == event.position_lineage_id,
                    positions_table.c.economic_lot_id == event.economic_lot_id,
                )
            )
            .values(
                settled_quantity_units=0,
                tradable_quantity_units=0,
                share_receivable_quantity_units=0,
                cost_basis_cents=0,
                state=PositionState.LEGAL_TERMINAL.value,
                updated_by_event_id=event.economic_event_id,
                updated_at=utc_iso(event.recorded_at),
            )
        )
        return row, cash_credit_cents

    def _apply_corporate_cash_settlement(self, event: EconomicEvent) -> None:
        self._apply_terminal_lot_sweep(event, consume_cash_legs=True)

    def _apply_legal_write_off(self, event: EconomicEvent) -> None:
        self._apply_terminal_lot_sweep(event, consume_cash_legs=False)

    def _apply_late_correction(self, event: EconomicEvent) -> None:
        """Apply a corrected entitlement: settle the superseded receivable
        and book its replacement, preserving both facts in the stream.

        Corrections touch receivables only; quantity/basis corrections of
        executions are Plan 02 Task 6 compensation territory.
        """

        share_credit_total = 0
        share_debit_total = 0
        for leg in event.legs:
            if leg.asset_kind is EconomicAssetKind.CASH_RECEIVABLE:
                self._apply_cash_receivable_leg(event, leg)
            elif leg.asset_kind is EconomicAssetKind.SHARE_RECEIVABLE:
                if leg.direction is EconomicLegDirection.CREDIT:
                    self._book_share_receivable_row(
                        event,
                        leg.receivable_id,
                        leg.security_id,
                        int(leg.quantity),
                    )
                    share_credit_total += int(leg.quantity)
                else:
                    self._settle_share_receivable_row(
                        event, leg.receivable_id, int(leg.quantity)
                    )
                    share_debit_total += int(leg.quantity)
            else:
                raise CapitalConflict(
                    "projection_rejected",
                    "corporate action corrections are limited to receivable"
                    " deltas; execution corrections land in Plan 02 Task 6",
                    economic_event_id=event.economic_event_id,
                )
        if share_credit_total or share_debit_total:
            self._adjust_position_share_buckets(
                event,
                share_receivable_delta=share_credit_total - share_debit_total,
            )

    # -- Plan 02 Task 3: valuation, NAV, lifecycle, and flow helpers ----------

    def projection_row(self) -> Any:
        return self._connection.execute(
            self._table("capital_projection").select()
        ).one()

    def lifecycle_state(self) -> LifecycleState:
        return LifecycleState(self.projection_row().lifecycle_state)

    def require_lifecycle(
        self, allowed: frozenset[LifecycleState]
    ) -> LifecycleState:
        """Fail closed when the account lifecycle blocks this command.

        ``TERMINATED`` is reported with its own terminal code; every other
        blocked state reports ``lifecycle_blocks_new_risk``.
        """

        state = self.lifecycle_state()
        if state in allowed:
            return state
        if state is LifecycleState.TERMINATED:
            raise CapitalConflict(
                "lifecycle_terminal",
                "the account is TERMINATED and cannot accept new facts",
                lifecycle_state=state.value,
            )
        raise CapitalConflict(
            "lifecycle_blocks_new_risk",
            f"lifecycle state {state.value} blocks this command",
            lifecycle_state=state.value,
        )

    def open_position_rows(self) -> tuple[Any, ...]:
        return tuple(
            self._connection.execute(
                sa.text(
                    "SELECT * FROM positions"
                    " WHERE state IN ('OPEN', 'EXIT_PENDING')"
                    " ORDER BY position_lineage_id, economic_lot_id"
                )
            ).all()
        )

    def latest_valuation_event(self) -> tuple[str, dict[str, int]] | None:
        """The newest as-observed VALUATION event and its marks.

        Restated valuations (``correction_of_event_id`` set) never feed the
        as-observed mark set: they belong to the restated-final path only.
        """

        row = self._connection.execute(
            sa.text(
                "SELECT economic_event_id FROM economic_events"
                " WHERE event_kind = 'VALUATION'"
                " AND correction_of_event_id IS NULL"
                " ORDER BY stream_version DESC LIMIT 1"
            )
        ).first()
        if row is None:
            return None
        leg_rows = self._connection.execute(
            sa.text(
                "SELECT security_id, mark_price_micros FROM economic_event_legs"
                " WHERE economic_event_id = :event_id ORDER BY sequence"
            ),
            {"event_id": row.economic_event_id},
        ).all()
        marks = {
            leg_row.security_id: int(leg_row.mark_price_micros)
            for leg_row in leg_rows
        }
        return row.economic_event_id, marks

    def marked_gross_cents(self, marks: dict[str, int]) -> int:
        """Total marked gross over open positions (round-half-even cents)."""

        total = 0
        for row in self.open_position_rows():
            micros = marks.get(row.security_id, 0)
            total += round_half_even_div(
                int(row.settled_quantity_units) * micros, MICROS_PER_CENT
            )
        return total

    def outstanding_receivable_cents(self) -> int:
        return int(
            self._connection.execute(
                sa.text(
                    "SELECT COALESCE(SUM(amount_cents), 0) AS total"
                    " FROM receivables WHERE settled = 0"
                )
            ).one().total
        )

    def open_payable_cents(self) -> int:
        return int(
            self._connection.execute(
                sa.text(
                    "SELECT COALESCE(SUM(amount_cents), 0) AS total"
                    " FROM payables WHERE state = :state"
                ),
                {"state": PayableState.OPEN.value},
            ).one().total
        )

    def equity_cents(
        self,
        marks: dict[str, int] | None = None,
        projection: Any | None = None,
    ) -> int:
        """Exact NAV: cash buckets + receivables + marked gross - payables."""

        row = projection if projection is not None else self.projection_row()
        if marks is None:
            latest = self.latest_valuation_event()
            marks = latest[1] if latest is not None else {}
        cash_total = (
            int(row.available_cash_cents)
            + int(row.restricted_cash_cents)
            + int(row.unsettled_cash_cents)
            + int(row.subscription_suspense_cash_cents)
            + int(row.redemption_suspense_cash_cents)
        )
        return (
            cash_total
            + self.outstanding_receivable_cents()
            + self.marked_gross_cents(marks)
            - self.open_payable_cents()
        )

    def equity_after_projection(
        self,
        *,
        available_cash_cents: int,
        restricted_cash_cents: int,
        unsettled_cash_cents: int,
        subscription_suspense_cash_cents: int,
        redemption_suspense_cash_cents: int,
        payable_delta_cents: int,
    ) -> int:
        """Exact post-fact equity for a flow settle/pay.

        Receivables and marks are read live (flows never move shares);
        ``payable_delta_cents`` is applied against the currently OPEN
        payables before this transaction's payable update is visible.
        """

        latest = self.latest_valuation_event()
        marks = latest[1] if latest is not None else {}
        cash_total = (
            available_cash_cents
            + restricted_cash_cents
            + unsettled_cash_cents
            + subscription_suspense_cash_cents
            + redemption_suspense_cash_cents
        )
        return (
            cash_total
            + self.outstanding_receivable_cents()
            + self.marked_gross_cents(marks)
            - (self.open_payable_cents() + payable_delta_cents)
        )

    def require_pricing_inputs(self) -> tuple[int, int]:
        """Flow pricing inputs: (V_pre, live unit quanta).

        Subscription suspense cash carries an equal payable, so an
        unsettled subscription is equity-neutral: the current equity
        already equals the pre-flow portfolio value. Fails closed while
        any open position is unmarked or the live denominator is empty.
        """

        projection = self.projection_row()
        latest = self.latest_valuation_event()
        marks = latest[1] if latest is not None else {}
        for row in self.open_position_rows():
            if row.security_id not in marks:
                raise CapitalConflict(
                    "valuation_required_for_pricing",
                    "every open position must be marked before flow pricing",
                    security_id=row.security_id,
                )
        v_pre = self.equity_cents(projection=projection)
        units_pre = (
            int(projection.issued_unit_quanta)
            - int(projection.pending_redeemed_unit_quanta)
        )
        if units_pre <= 0:
            raise CapitalConflict(
                "no_live_units_for_pricing",
                "the live unit denominator is empty; it is never reused for"
                " NAV or new risk while units are pending redemption",
            )
        return v_pre, units_pre

    def latest_observation_row(self, kind: ObservationKind) -> Any | None:
        return self._connection.execute(
            sa.text(
                "SELECT * FROM nav_observations"
                " WHERE observation_kind = :kind ORDER BY rowid DESC LIMIT 1"
            ),
            {"kind": kind.value},
        ).first()

    def observation_row_for_event(
        self, kind: ObservationKind, event_id: str
    ) -> Any | None:
        return self._connection.execute(
            sa.text(
                "SELECT * FROM nav_observations"
                " WHERE observation_kind = :kind"
                " AND created_by_event_id = :event_id"
            ),
            {"kind": kind.value, "event_id": event_id},
        ).first()

    def insert_nav_observation(
        self,
        *,
        event_id: str,
        kind: ObservationKind,
        supersedes_observation_id: str | None,
        as_of: datetime,
        recorded_at: datetime,
        capital_version: int,
        nav_cents: int,
        prior_nav_cents: int | None,
    ) -> str:
        projection = self.projection_row()
        issued = int(projection.issued_unit_quanta)
        pending = int(projection.pending_redeemed_unit_quanta)
        live = issued - pending
        price = unit_price_lowest_terms(nav_cents, live)
        growth = log_growth_kind_for(nav_cents, prior_nav_cents)
        if growth is LogGrowthKind.NO_PRIOR_OBSERVATION:
            ratio_numerator: int | None = None
            ratio_denominator: int | None = None
        elif growth is LogGrowthKind.NEGATIVE_INFINITY:
            ratio_numerator, ratio_denominator = 0, 1
        else:
            assert prior_nav_cents is not None
            ratio_numerator, ratio_denominator = nav_ratio_lowest_terms(
                nav_cents, prior_nav_cents
            )
        observation_id = derive_nav_observation_id(event_id, kind.value)
        self._connection.execute(
            self._table("nav_observations").insert().values(
                nav_observation_id=observation_id,
                portfolio_id=projection.portfolio_id,
                observation_kind=kind.value,
                supersedes_observation_id=supersedes_observation_id,
                as_of=utc_iso(as_of),
                recorded_at=utc_iso(recorded_at),
                capital_version=capital_version,
                created_by_event_id=event_id,
                nav_cents=nav_cents,
                issued_unit_quanta=issued,
                live_unit_quanta=live,
                unit_price_numerator=(price[0] if price is not None else None),
                unit_price_denominator=(price[1] if price is not None else None),
                log_growth_kind=growth.value,
                log_growth_nav_numerator=ratio_numerator,
                log_growth_nav_denominator=ratio_denominator,
            )
        )
        return observation_id

    def _apply_execution_revision_event(
        self, event: EconomicEvent, command: CapitalCommand
    ) -> None:
        """Project one execution revision fact onto cash and the lot.

        Capital is re-projected from the append-only history: the original
        fact is never patched, the revision event's legs move cash, and the
        position row advances by the exact signed deltas. Negative results
        are preserved (never clamped) and latch the account through the
        risk recompute; a flat/nonpositive-to-positive transition reopens
        the exit obligation durably.
        """

        fact = command.payload.execution_revision
        if fact is None:
            raise CapitalConflict(
                "projection_rejected",
                "execution revision events carry their revision fact",
                economic_event_id=event.economic_event_id,
            )

        projection_table = self._table("capital_projection")
        projection = self._connection.execute(projection_table.select()).one()
        # The corporate-action wrapper bumps capital_version by exactly one
        # after this projection step, in the same transaction; the durable
        # tombstone/reopen rows record that post-bump version so their
        # audit identity matches the committed capital version.
        recorded_capital_version = int(projection.capital_version) + 1
        available_cash_cents = int(projection.available_cash_cents)
        for leg in event.legs:
            if leg.asset_kind is not EconomicAssetKind.CASH:
                continue
            amount_cents = scaled_int(leg.cash_amount, CENT_SCALE, "cash_amount")
            if leg.direction is EconomicLegDirection.CREDIT:
                available_cash_cents += amount_cents
            else:
                available_cash_cents -= amount_cents
        if available_cash_cents < 0:
            raise CapitalConflict(
                "projection_rejected",
                "cash projection would become negative",
                available_cash_cents=available_cash_cents,
            )

        quantity_delta = 0
        basis_delta = 0
        if fact.fact_kind is ExecutionRevisionFactKind.FILL:
            if fact.superseded_quantity is not None:
                assert fact.superseded_gross_cents is not None
                superseded_quantity = int(fact.superseded_quantity)
                superseded_gross = int(fact.superseded_gross_cents)
                if fact.side is ExecutionSide.ENTRY:
                    quantity_delta -= superseded_quantity
                    basis_delta -= superseded_gross
                else:
                    quantity_delta += superseded_quantity
                    basis_delta += int(
                        fact.reversed_consumed_basis_cents or 0
                    )
            if fact.corrected_quantity is not None:
                assert fact.corrected_gross_cents is not None
                corrected_quantity = int(fact.corrected_quantity)
                corrected_gross = int(fact.corrected_gross_cents)
                if fact.side is ExecutionSide.ENTRY:
                    quantity_delta += corrected_quantity
                    basis_delta += corrected_gross
                else:
                    quantity_delta -= corrected_quantity
                    basis_delta -= int(
                        fact.corrected_consumed_basis_cents or 0
                    )
            positions_table = self._table("positions")
            row = self._connection.execute(
                positions_table.select().where(
                    sa.and_(
                        positions_table.c.position_lineage_id
                        == fact.position_lineage_id,
                        positions_table.c.economic_lot_id
                        == fact.economic_lot_id,
                    )
                )
            ).first()
            if row is None:
                raise CapitalConflict(
                    "conservation_violation",
                    "execution revision lost its economic lot projection",
                    economic_lot_id=fact.economic_lot_id,
                )
            quantity_before = int(row.settled_quantity_units)
            quantity_after = quantity_before + quantity_delta
            now = utc_iso(event.recorded_at)
            values: dict[str, Any] = {
                "settled_quantity_units": quantity_after,
                "tradable_quantity_units": (
                    int(row.tradable_quantity_units) + quantity_delta
                ),
                "cost_basis_cents": int(row.cost_basis_cents) + basis_delta,
                "updated_by_event_id": event.economic_event_id,
                "updated_at": now,
            }
            if quantity_after > 0:
                if quantity_before <= 0:
                    # Flat/nonpositive-to-positive: the lot reappears with
                    # its due exit obligation (charter item 9).
                    values["state"] = PositionState.EXIT_PENDING.value
                    self.reopen_exit_obligation(
                        fact=fact,
                        reopened_quantity=quantity_after,
                        as_of=event.recorded_at,
                        capital_version=recorded_capital_version,
                    )
            elif quantity_after == 0:
                values["state"] = PositionState.CLOSED.value
            # Negative projections keep their prior state: impossible states
            # are preserved for reconciliation, never clamped or dropped.
            self._connection.execute(
                positions_table.update()
                .where(
                    sa.and_(
                        positions_table.c.position_lineage_id
                        == fact.position_lineage_id,
                        positions_table.c.economic_lot_id
                        == fact.economic_lot_id,
                    )
                )
                .values(**values)
            )
            removed_entry = (
                fact.superseded_quantity is not None
                and fact.side is ExecutionSide.ENTRY
            )
            if removed_entry and quantity_after <= 0:
                assert fact.position_lineage_id is not None
                assert fact.economic_lot_id is not None
                self.tombstone_removed_entry_lot(
                    fact.position_lineage_id,
                    fact.economic_lot_id,
                    event.recorded_at,
                    capital_version=recorded_capital_version,
                )

        # The corporate-action wrapper bumps the capital version exactly
        # once after this projection step; only the cash leg lands here.
        self._connection.execute(
            projection_table.update()
            .where(projection_table.c.portfolio_id == projection.portfolio_id)
            .values(available_cash_cents=available_cash_cents)
        )

    def _apply_valuation_event(
        self, event: EconomicEvent, command: CapitalCommand
    ) -> None:
        """Mark-only projection: NAV, water marks, lifecycle, observation.

        Restatements (``correction_of_event_id`` set) append a
        RESTATED_FINAL observation linked to the as-observed row and bump
        the capital version; they never rewrite the decision-time NAV, HWM,
        or lifecycle.
        """

        conn = self._connection
        marks: dict[str, int] = {}
        for leg in event.legs:
            marks[leg.security_id] = scaled_int(
                leg.mark_price, PRICE_MICRO_SCALE, "mark_price"
            )
        restatement = event.correction_of_event_id is not None
        if not restatement:
            open_securities = {
                row.security_id for row in self.open_position_rows()
            }
            missing = sorted(open_securities - set(marks))
            if missing:
                raise CapitalConflict(
                    "valuation_mark_missing",
                    "close valuation must mark every open position",
                    missing_securities=missing,
                )
            unexpected = sorted(set(marks) - open_securities)
            if unexpected:
                raise CapitalConflict(
                    "valuation_mark_unexpected",
                    "valuation marks a security with no open position",
                    unexpected_securities=unexpected,
                )

        projection_table = self._table("capital_projection")
        projection = conn.execute(projection_table.select()).one()
        nav_cents = self.equity_cents(marks=marks, projection=projection)
        new_version = int(projection.capital_version) + 1
        now = utc_iso(command.as_of)

        if restatement:
            superseded = self.observation_row_for_event(
                ObservationKind.AS_OBSERVED, event.correction_of_event_id
            )
            if superseded is None:
                raise CapitalConflict(
                    "restatement_target_unknown",
                    "restated valuation has no as-observed observation",
                    correction_of_event_id=event.correction_of_event_id,
                )
            # The restated-final path is its own preserved series: log
            # growth chains the restated observations in append order (the
            # first restated row has no prior in the series).
            prior_restated = self.latest_observation_row(
                ObservationKind.RESTATED_FINAL
            )
            prior_nav = (
                int(prior_restated.nav_cents)
                if prior_restated is not None
                else None
            )
            conn.execute(
                projection_table.update()
                .where(projection_table.c.portfolio_id == projection.portfolio_id)
                .values(
                    capital_version=new_version,
                    updated_at=now,
                    updated_by_event_id=event.economic_event_id,
                )
            )
            self.insert_nav_observation(
                event_id=event.economic_event_id,
                kind=ObservationKind.RESTATED_FINAL,
                supersedes_observation_id=superseded.nav_observation_id,
                as_of=event.effective_at,
                recorded_at=event.recorded_at,
                capital_version=new_version,
                nav_cents=nav_cents,
                prior_nav_cents=prior_nav,
            )
            return

        prior = self.latest_observation_row(ObservationKind.AS_OBSERVED)
        if prior is None and int(projection.issued_unit_quanta) == 0:
            raise CapitalConflict(
                "valuation_before_genesis",
                "close valuation requires an initialized genesis",
            )
        self.confirm_observed_nav(
            nav_cents=nav_cents,
            event_id=event.economic_event_id,
            effective_at=event.effective_at,
            recorded_at=event.recorded_at,
            prior_nav_cents=(int(prior.nav_cents) if prior is not None else None),
        )

    def confirm_observed_nav(
        self,
        *,
        nav_cents: int,
        event_id: str,
        effective_at: datetime,
        recorded_at: datetime,
        prior_nav_cents: int | None,
    ) -> int:
        """Confirm one as-observed NAV: projection, water marks, lifecycle
        (NAV <= 0 sets INSOLVENT), and the append-only observation row.
        Returns the new capital version."""

        projection_table = self._table("capital_projection")
        projection = self._connection.execute(projection_table.select()).one()
        lifetime_hwm = max(
            int(projection.lifetime_high_water_mark_cents), nav_cents
        )
        active_hwm = max(
            int(projection.active_epoch_high_water_mark_cents), nav_cents
        )
        lifecycle = LifecycleState(projection.lifecycle_state)
        if nav_cents <= 0 and lifecycle in (
            LifecycleState.ACTIVE,
            LifecycleState.TERMINATING,
        ):
            # Confirmed NAV <= 0 after investment loss: insolvency is not
            # auto-recoverable; only exits, liquidation, and reconciliation
            # continue.
            lifecycle = LifecycleState.INSOLVENT
        new_version = int(projection.capital_version) + 1
        self._connection.execute(
            projection_table.update()
            .where(projection_table.c.portfolio_id == projection.portfolio_id)
            .values(
                as_observed_nav_cents=nav_cents,
                lifetime_high_water_mark_cents=lifetime_hwm,
                active_epoch_high_water_mark_cents=active_hwm,
                lifecycle_state=lifecycle.value,
                capital_version=new_version,
                updated_at=utc_iso(recorded_at),
                updated_by_event_id=event_id,
            )
        )
        self.insert_nav_observation(
            event_id=event_id,
            kind=ObservationKind.AS_OBSERVED,
            supersedes_observation_id=None,
            as_of=effective_at,
            recorded_at=recorded_at,
            capital_version=new_version,
            nav_cents=nav_cents,
            prior_nav_cents=prior_nav_cents,
        )
        return new_version

    # -- flow stream primitives -------------------------------------------------

    def current_flow_version(self) -> int:
        row = self._connection.execute(
            sa.text(
                "SELECT COALESCE(MAX(flow_version), 0) AS v"
                " FROM capital_flow_events"
            )
        ).one()
        return int(row.v)

    def require_flow_version(self, expected: int) -> None:
        actual = self.current_flow_version()
        if actual != expected:
            raise CapitalConflict(
                "flow_version_mismatch",
                "compare-and-swap failed: the financing flow stream advanced",
                expected=expected,
                actual=actual,
            )

    def flow_request_row(self, request_id: str) -> Any | None:
        return self._connection.execute(
            sa.text("SELECT * FROM flow_requests WHERE flow_request_id = :id"),
            {"id": request_id},
        ).first()

    def existing_flow_event(self, idempotency_key: str) -> Any | None:
        return self._connection.execute(
            sa.text(
                "SELECT * FROM capital_flow_events"
                " WHERE idempotency_key = :key"
            ),
            {"key": idempotency_key},
        ).first()

    def require_flow_payload_idempotent(
        self, idempotency_key: str, payload_hash: str
    ) -> Any | None:
        """Return the committed flow event for an identical retry, fail
        closed on a divergent payload under the same key."""

        existing = self.existing_flow_event(idempotency_key)
        if existing is None:
            return None
        if existing.payload_content_hash != payload_hash:
            raise CapitalConflict(
                "payload_conflict",
                "flow idempotency key already committed with a different"
                " payload",
                idempotency_key=idempotency_key,
            )
        return existing

    def insert_flow_event(
        self,
        *,
        idempotency_key: str,
        flow_kind: FlowKind,
        portfolio_id: str,
        request_id: str | None,
        source_authority: str,
        effective_at: datetime,
        recorded_at: datetime,
        payload: dict[str, Any],
        cash_amount_cents: int | None = None,
        refund_cents: int | None = None,
        reserved_cents: int | None = None,
        issued_unit_quanta: int | None = None,
        cancelled_unit_quanta: int | None = None,
        pending_unit_quanta: int | None = None,
        burnt_unit_quanta: int | None = None,
        unit_price_numerator: int | None = None,
        unit_price_denominator: int | None = None,
        payable_id: str | None = None,
    ) -> tuple[str, int]:
        payload_hash = content_hash(payload)
        flow_version = self.current_flow_version() + 1
        flow_event_id = derive_flow_event_id(idempotency_key)
        self._connection.execute(
            self._table("capital_flow_events").insert().values(
                flow_event_id=flow_event_id,
                idempotency_key=idempotency_key,
                flow_kind=flow_kind.value,
                portfolio_id=portfolio_id,
                flow_version=flow_version,
                flow_request_id=request_id,
                source_authority=source_authority,
                effective_at=utc_iso(effective_at),
                recorded_at=utc_iso(recorded_at),
                cash_amount_cents=cash_amount_cents,
                refund_cents=refund_cents,
                reserved_cents=reserved_cents,
                issued_unit_quanta=issued_unit_quanta,
                cancelled_unit_quanta=cancelled_unit_quanta,
                pending_unit_quanta=pending_unit_quanta,
                burnt_unit_quanta=burnt_unit_quanta,
                unit_price_numerator=unit_price_numerator,
                unit_price_denominator=unit_price_denominator,
                payable_id=payable_id,
                payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
                payload_content_hash=payload_hash,
            )
        )
        return flow_event_id, flow_version

    def bump_projection(
        self, event_id: str | None, as_of: datetime, **values: Any
    ) -> int:
        """Apply flow-level projection changes and bump the capital version.

        The risk/reconciliation latch is recomputed in the same transaction
        so flow-driven NAV changes (e.g. a full redemption to zero) keep
        the snapshot fail-closed rules satisfied.
        """

        projection_table = self._table("capital_projection")
        projection = self._connection.execute(projection_table.select()).one()
        values["capital_version"] = int(projection.capital_version) + 1
        values["updated_at"] = utc_iso(as_of)
        values["updated_by_event_id"] = event_id
        self._connection.execute(
            projection_table.update()
            .where(projection_table.c.portfolio_id == projection.portfolio_id)
            .values(**values)
        )
        self.recompute_risk_and_stage_loss(as_of, event_id)
        return int(values["capital_version"])

    # -- risk / stage loss hook -------------------------------------------------

    def recompute_risk_and_stage_loss(self, as_of: datetime, event_id: str) -> None:
        projection = self._connection.execute(
            self._table("capital_projection").select()
        ).first()
        if projection is None:
            return
        # The 10%/15% trading authority operates on the active-epoch
        # operational baseline (charter item 11 / spec 11.2); the lifetime
        # drawdown remains performance/disclosure only.
        drawdown = drawdown_ppm(
            int(projection.as_observed_nav_cents),
            int(projection.active_epoch_high_water_mark_cents),
        )
        risk_latch_table = self._table("risk_latches")
        existing_risk = self._connection.execute(
            risk_latch_table.select().where(
                risk_latch_table.c.latch_kind == "RISK"
            )
        ).first()
        already_halted = (
            existing_risk is not None
            and existing_risk.state == RiskLatchState.RISK_HALTED.value
        )
        # The latch is one-way within the risk epoch: once halted, only a new
        # governance risk epoch (start_risk_epoch) clears it; NAV recovery in
        # the same epoch never does.
        if not already_halted:
            halted = drawdown >= DRAWDOWN_HALT_PPM
            latch_state = (
                RiskLatchState.RISK_HALTED if halted else RiskLatchState.CLEAR
            )
            reason = (
                "active-epoch drawdown reached the 15 percent halt threshold"
                if halted
                else None
            )
            self._connection.execute(
                sa.text(
                    "INSERT INTO risk_latches (latch_kind, state, reason,"
                    " set_at, set_by_event_id) VALUES ('RISK', :state,"
                    " :reason, :set_at, :event_id)"
                    " ON CONFLICT(latch_kind) DO UPDATE SET"
                    " state = excluded.state, reason = excluded.reason,"
                    " set_at = excluded.set_at,"
                    " set_by_event_id = excluded.set_by_event_id"
                ),
                {
                    "state": latch_state.value,
                    "reason": reason,
                    "set_at": utc_iso(as_of),
                    "event_id": event_id,
                },
            )

        # Reconciliation latch. Two triggers:
        # - unattributed or plan-violating fills are preserved under
        #   sentinel attribution and flag the account until reconciliation
        #   flattens them (Task 2);
        # - active revisions exporting negative shares or basis (busts and
        #   corrections of terminal history) are long-only impossibilities
        #   that flag the account while they persist (Task 6 / charter item
        #   15).
        # The latch tracks the current projection: it is re-evaluated on
        # every projection and clears exactly when the impossible state is
        # resolved by a source-authorized correction or flattening. (The
        # one-way rule applies to the RISK drawdown latch, not here.)
        sentinel = self._connection.execute(
            sa.text(
                "SELECT COALESCE(SUM(settled_quantity_units), 0) AS units,"
                " COALESCE(SUM(cost_basis_cents), 0) AS basis"
                " FROM positions WHERE producer_namespace = :sentinel"
            ),
            {"sentinel": UNATTRIBUTED_PRODUCER},
        ).one()
        unattributed_exposure = (
            int(sentinel.units) > 0 or int(sentinel.basis) > 0
        )
        negative_positions = int(
            self._connection.execute(
                sa.text(
                    "SELECT COUNT(*) AS n FROM positions"
                    " WHERE settled_quantity_units < 0"
                    " OR tradable_quantity_units < 0"
                    " OR cost_basis_cents < 0"
                )
            ).one().n
        )
        halted = unattributed_exposure or negative_positions > 0
        reconciliation_state = (
            ReconciliationLatchState.RECONCILIATION_HALT
            if halted
            else ReconciliationLatchState.CLEAR
        )
        if negative_positions > 0:
            reconciliation_reason = (
                "active revisions export a negative position; impossible"
                " states are preserved until reconciliation"
            )
        elif unattributed_exposure:
            reconciliation_reason = (
                "unattributed fill exposure pending reconciliation"
            )
        else:
            reconciliation_reason = None
        self._connection.execute(
            sa.text(
                "INSERT INTO risk_latches (latch_kind, state, reason,"
                " set_at, set_by_event_id) VALUES ('RECONCILIATION',"
                " :state, :reason, :set_at, :event_id)"
                " ON CONFLICT(latch_kind) DO UPDATE SET"
                " state = excluded.state, reason = excluded.reason,"
                " set_at = excluded.set_at,"
                " set_by_event_id = excluded.set_by_event_id"
            ),
            {
                "state": reconciliation_state.value,
                "reason": reconciliation_reason,
                "set_at": utc_iso(as_of),
                "event_id": event_id,
            },
        )
        # Stage-loss budgets are frozen at activation and consumed in the same
        # capital transaction as fills/fees/marks/reserves. The derived
        # worst-case floor (cumulative fees plus mark-to-market unrealized
        # loss) lands in the portfolio-global budget because those ledger
        # facts carry no stage attribution. The floor is a no-op until
        # governance freezes a global budget row.
        recompute_global_stage_loss_floor(self, as_of, event_id)

    def tombstone_unclaimed_entries_if_versions_changed(self) -> None:
        """Tombstone entry claims that never reached a fill.

        One tombstone per entry identity, written in the same transaction
        as the capital fact that invalidates it:

        - released reserves are invalidated entries (their cancel/reject/
          expiry confirmed the entry never filled), so every sweep claims
          the released rows that are not yet tombstoned;
        - entry lots removed by a bust/correction are tombstoned by the
          revision projection itself (it knows the removal fact).

        Entry claim state beyond the kernel (sealed/permitted/outbox/send
        claims) belongs to the Plan 04 gateway tables of this same
        database; Plan 04 registers those identities through this same
        sweep so a capital version change atomically tombstones every
        unclaimed entry. Tombstones are append-only audit: they are never
        updated or deleted, and a tombstoned entry that reappears through
        a correction must re-create real exposure through the reopen
        machinery instead of silently reviving.
        """

        conn = self._connection
        released = conn.execute(
            sa.text(
                "SELECT source_id FROM reserves"
                " WHERE state = 'RELEASED'"
                " AND NOT EXISTS ("
                " SELECT 1 FROM entry_tombstones t"
                " WHERE t.entry_identity ="
                " 'reserve:' || reserves.source_id"
                ")"
            )
        ).all()
        if not released:
            return
        projection = conn.execute(
            self._table("capital_projection").select()
        ).one()
        tombstones = self._table("entry_tombstones")
        now = utc_iso(utc_now())
        for row in released:
            conn.execute(
                tombstones.insert().values(
                    entry_identity=reserve_tombstone_identity(row.source_id),
                    tombstone_reason=TOMBSTONE_REASON_ENTRY_INVALIDATED,
                    capital_version=int(projection.capital_version),
                    stream_version=self.current_stream_version(),
                    tombstoned_at=now,
                )
            )

    def tombstone_removed_entry_lot(
        self,
        position_lineage_id: str,
        economic_lot_id: str,
        as_of: datetime,
        capital_version: int | None = None,
    ) -> None:
        """Idempotently tombstone an entry lot a revision flattened.

        Append-only: the first removal owns the tombstone row; later
        revisions of the same lot converge on it. ``capital_version``
        overrides the projection read for callers that know the
        same-transaction post-bump version.
        """

        identity = lot_tombstone_identity(position_lineage_id, economic_lot_id)
        tombstones = self._table("entry_tombstones")
        existing = self._connection.execute(
            tombstones.select().where(
                tombstones.c.entry_identity == identity
            )
        ).first()
        if existing is not None:
            return
        projection = self._connection.execute(
            self._table("capital_projection").select()
        ).one()
        version = (
            capital_version
            if capital_version is not None
            else int(projection.capital_version)
        )
        self._connection.execute(
            tombstones.insert().values(
                entry_identity=identity,
                tombstone_reason=TOMBSTONE_REASON_EXECUTION_BUSTED,
                capital_version=version,
                stream_version=self.current_stream_version(),
                tombstoned_at=utc_iso(as_of),
            )
        )

    def reopen_exit_obligation(
        self,
        *,
        fact: ExecutionRevisionFact,
        reopened_quantity: int,
        as_of: datetime,
        capital_version: int | None = None,
    ) -> str:
        """Append the durable reopened exit obligation for one lot.

        Plan 04's ExitMandate projection consumes these rows: the stable
        lot identity and attribution name the mandate, the restored state
        is ``EXIT_PENDING`` with the ``REOPENED_BY_CORRECTION`` reason,
        and ``mandate_revision_floor`` keeps revision 1 reserved for
        INITIAL mandates (Plan 04 advances it strictly beyond every
        mandate revision the lot has ever seen).
        """

        reopen_id = f"reopen:fill:{fact.execution_id}:{fact.revision}"
        reopens = self._table("exit_obligation_reopens")
        existing = self._connection.execute(
            reopens.select().where(reopens.c.reopen_id == reopen_id)
        ).first()
        if existing is not None:
            return reopen_id
        projection = self._connection.execute(
            self._table("capital_projection").select()
        ).one()
        version = (
            capital_version
            if capital_version is not None
            else int(projection.capital_version)
        )
        self._connection.execute(
            reopens.insert().values(
                reopen_id=reopen_id,
                position_lineage_id=fact.position_lineage_id,
                economic_lot_id=fact.economic_lot_id,
                security_id=fact.security_id,
                producer_namespace=fact.producer_namespace,
                research_program_id=fact.research_program_id,
                economic_lineage_id=fact.economic_lineage_id,
                stage_id=fact.stage_id,
                reopened_quantity_units=reopened_quantity,
                position_state=REOPEN_POSITION_STATE.value,
                reopen_reason=(
                    ExecutionRevisionKind.CORRECTED.value
                    if fact.revision_kind is ExecutionRevisionKind.CORRECTED
                    else ExecutionRevisionKind.BUSTED.value
                ),
                mandate_revision_floor=MANDATE_REVISION_FLOOR,
                reopened_by_execution_revision_id=(
                    fill_idempotency_key(fact.execution_id, fact.revision)
                ),
                reopened_by_event_id=derive_event_id(
                    fill_idempotency_key(fact.execution_id, fact.revision)
                ),
                capital_version=version,
                stream_version=self.current_stream_version(),
                recorded_at=utc_iso(as_of),
            )
        )
        return reopen_id

    # -- snapshot read -----------------------------------------------------------

    def read_capital_risk_snapshot(self, as_of: datetime) -> CapitalRiskSnapshot:
        binding_row = self._connection.execute(
            self._table("account_capital_truth").select()
        ).one()
        projection = self._connection.execute(
            self._table("capital_projection").select()
        ).one()
        cash_receivable_cents = int(
            self._connection.execute(
                sa.text(
                    "SELECT COALESCE(SUM(amount_cents), 0) AS total FROM receivables"
                    " WHERE receivable_kind = 'CASH' AND settled = 0"
                )
            ).one().total
        )
        cash_payable_cents = int(
            self._connection.execute(
                sa.text(
                    "SELECT COALESCE(SUM(amount_cents), 0) AS total FROM payables"
                    " WHERE state = :state"
                ),
                {"state": PayableState.OPEN.value},
            ).one().total
        )
        # Only LIVE and CANCEL_PENDING reserves still restrict capital; both
        # count toward the worst-case reserved exposure. RELEASED/CONSUMED
        # rows remain for audit but drop out of the snapshot.
        reserve_rows = self._connection.execute(
            sa.text(
                "SELECT * FROM reserves"
                " WHERE state IN ('LIVE', 'CANCEL_PENDING')"
                " ORDER BY research_program_id, economic_lineage_id, stage_id,"
                " source_id"
            )
        ).all()
        entry_reserves = tuple(
            EntryReserveRiskComponent(
                research_program_id=row.research_program_id,
                economic_lineage_id=row.economic_lineage_id,
                stage_id=row.stage_id,
                source_id=row.source_id,
                # Kernel revision 2 has no live-order registry yet; Plan 04
                # binds covered orders through the gateway.
                covered_live_order_id=None,
                reserved_entry_gross_cents=int(row.reserved_entry_gross_cents),
            )
            for row in reserve_rows
        )
        reserved_cash_cents = sum(
            reserve.reserved_entry_gross_cents for reserve in entry_reserves
        )
        # Unattributed or plan-violating fills are preserved under sentinel
        # attribution; their cost basis is the only known non-optimistic
        # exposure until valuation marks arrive with Task 3/Task 5. A
        # negative sentinel basis is a reconciliation discrepancy (the
        # snapshot contract is nonnegative; the signed value stays in the
        # ledger and surfaces via ``reconciliation_discrepancies``).
        unattributed_risk_cents = max(
            0,
            int(
                self._connection.execute(
                    sa.text(
                        "SELECT COALESCE(SUM(cost_basis_cents), 0) AS total"
                        " FROM positions WHERE producer_namespace = :sentinel"
                    ),
                    {"sentinel": UNATTRIBUTED_PRODUCER},
                ).one().total
            ),
        )
        # Negative projections are preserved in the ledger but cannot be
        # represented by the frozen snapshot contract (nonnegative
        # quantities): they are excluded from ``positions`` and the
        # snapshot fails closed as INCOMPLETE while the reconciliation
        # latch carries the halt. ``reconciliation_discrepancies()`` keeps
        # them visible, never clamped or dropped.
        position_rows = self._connection.execute(
            sa.text(
                "SELECT * FROM positions"
                " WHERE state IN ('OPEN', 'EXIT_PENDING')"
                " AND settled_quantity_units >= 0"
                " AND tradable_quantity_units >= 0"
                " AND cost_basis_cents >= 0"
                " ORDER BY position_lineage_id, economic_lot_id"
            )
        ).all()
        negative_position_count = int(
            self._connection.execute(
                sa.text(
                    "SELECT COUNT(*) AS n FROM positions"
                    " WHERE settled_quantity_units < 0"
                    " OR tradable_quantity_units < 0"
                    " OR cost_basis_cents < 0"
                )
            ).one().n
        )
        # Marks come from the newest as-observed close-valuation event; a
        # position opened after the last valuation stays unmarked (zero)
        # until its first valuation confirms a price (Task 5 owns stale and
        # unknown mark policy). Restated valuations never feed as-observed
        # marks.
        latest_valuation = self.latest_valuation_event()
        valuation_marks = latest_valuation[1] if latest_valuation is not None else {}
        latch_rows = self._connection.execute(
            self._table("risk_latches").select()
        ).all()
        stage_rows = self._connection.execute(
            sa.text(
                "SELECT * FROM stage_loss_state"
                " ORDER BY research_program_id, economic_lineage_id, stage_id"
            )
        ).all()
        meta_rows = self._connection.execute(
            self._table("gateway_meta").select()
        ).all()
        meta = {row.key: row.value for row in meta_rows}

        mode = ExecutionMode(binding_row.execution_mode)
        components = tuple(
            CapitalPositionRisk(
                portfolio_id=binding_row.portfolio_id,
                broker_account_id=binding_row.broker_account_id,
                mode=mode,
                position_lineage_id=row.position_lineage_id,
                economic_lot_id=row.economic_lot_id,
                security_id=row.security_id,
                producer_namespace=row.producer_namespace,
                research_program_id=row.research_program_id,
                economic_lineage_id=row.economic_lineage_id,
                stage_id=row.stage_id,
                state=PositionState(row.state),
                settled_quantity=int(row.settled_quantity_units),
                tradable_quantity=int(row.tradable_quantity_units),
                share_receivable_quantity=int(row.share_receivable_quantity_units),
                # Marked gross from the newest as-observed valuation event
                # (round-half-even cents); unmarked positions stay zero.
                marked_gross_cents=round_half_even_div(
                    int(row.settled_quantity_units)
                    * valuation_marks.get(row.security_id, 0),
                    MICROS_PER_CENT,
                ),
            )
            for row in position_rows
        )

        latches = {row.latch_kind: row.state for row in latch_rows}
        stage_loss_latches = tuple(
            StageLossLatchSnapshot(
                research_program_id=row.research_program_id,
                economic_lineage_id=row.economic_lineage_id,
                stage_id=row.stage_id,
                stage_loss_budget_id=row.stage_loss_budget_id,
                frozen_budget_cents=int(row.frozen_budget_cents),
                consumed_cents=int(row.consumed_cents),
                stage_loss_version=int(row.stage_loss_version),
                state=StageLossLatchState(row.state),
            )
            for row in stage_rows
        )

        nav_cents = int(projection.as_observed_nav_cents)
        lifetime_hwm_cents = int(projection.lifetime_high_water_mark_cents)
        active_hwm_cents = int(projection.active_epoch_high_water_mark_cents)
        capital_version = int(projection.capital_version)

        return CapitalRiskSnapshot(
            risk_snapshot_id=derive_risk_snapshot_id(
                binding_row.portfolio_id, capital_version
            ),
            portfolio_id=binding_row.portfolio_id,
            broker_account_id=binding_row.broker_account_id,
            base_currency=binding_row.base_currency,
            mode=mode,
            as_of=as_of,
            valid_until=as_of + RISK_SNAPSHOT_VALIDITY,
            freshness=RiskSnapshotFreshness.FRESH,
            completeness=(
                RiskSnapshotCompleteness.INCOMPLETE
                if negative_position_count > 0
                else RiskSnapshotCompleteness.COMPLETE
            ),
            available_cash_cents=int(projection.available_cash_cents),
            restricted_cash_cents=int(projection.restricted_cash_cents),
            unsettled_cash_cents=int(projection.unsettled_cash_cents),
            cash_receivable_cents=cash_receivable_cents,
            cash_payable_cents=cash_payable_cents,
            subscription_suspense_cents=int(
                projection.subscription_suspense_cash_cents
            ),
            redemption_suspense_cents=int(
                projection.redemption_suspense_cash_cents
            ),
            reserved_cash_cents=reserved_cash_cents,
            issued_unit_quanta=int(projection.issued_unit_quanta),
            pending_redeemed_unit_quanta=int(
                projection.pending_redeemed_unit_quanta
            ),
            positions=components,
            live_orders=(),
            entry_reserves=entry_reserves,
            pending_stress_components=(),
            corporate_action_risk_components=(),
            unattributed_risk_cents=unattributed_risk_cents,
            exposures=_exposure_buckets(
                binding_row.portfolio_id,
                components,
                entry_reserves,
                unattributed_risk_cents,
            ),
            total_gross_exposure_cents=_gross_total(
                components, entry_reserves, unattributed_risk_cents
            ),
            as_observed_nav_cents=nav_cents,
            lifetime_high_water_mark_cents=lifetime_hwm_cents,
            active_epoch_high_water_mark_cents=active_hwm_cents,
            lifetime_drawdown_ppm=drawdown_ppm(nav_cents, lifetime_hwm_cents),
            active_epoch_drawdown_ppm=drawdown_ppm(nav_cents, active_hwm_cents),
            risk_latch=RiskLatchState(latches.get("RISK", RiskLatchState.CLEAR.value)),
            stage_loss_latches=stage_loss_latches,
            reconciliation_latch=ReconciliationLatchState(
                latches.get("RECONCILIATION", ReconciliationLatchState.CLEAR.value)
            ),
            policy_activation_hash=meta["policy_activation_hash"],
            policy_epoch=int(meta["policy_epoch"]),
            authority_epoch=int(meta["authority_epoch"]),
            risk_epoch=int(meta["risk_epoch"]),
            registry_epoch=int(meta["registry_epoch"]),
            authorization_id=meta["authorization_id"],
            authorization_version=int(meta["authorization_version"]),
            stage_loss_state_version=int(meta["stage_loss_state_version"]),
            writer_fencing_epoch=int(meta["writer_fencing_epoch"]),
            capital_version=capital_version,
            schema_major=SCHEMA_MAJOR,
        )

    # -- composed append -----------------------------------------------------------

    def run_append(
        self,
        command: CapitalCommand,
        after_event_insert_hook: ProjectorHook | None,
        before_projection_hook: ProjectorHook | None = None,
        after_projection_hook: ProjectorHook | None = None,
    ) -> CapitalRiskSnapshot:
        self.require_account_binding(command.account_binding, command.as_of)
        # A TERMINATED account accepts no new economic facts of any kind.
        self.require_lifecycle(
            frozenset(
                {
                    LifecycleState.ACTIVE,
                    LifecycleState.TERMINATING,
                    LifecycleState.INSOLVENT,
                }
            )
        )
        existing = self._connection.execute(
            sa.text(
                "SELECT payload_content_hash FROM economic_events"
                " WHERE idempotency_key = :key"
            ),
            {"key": command.idempotency_key},
        ).first()
        if existing is not None:
            if existing.payload_content_hash != command.payload.content_hash():
                raise CapitalConflict(
                    "payload_conflict",
                    "idempotency key already committed with a different payload",
                    idempotency_key=command.idempotency_key,
                )
            # Identical command retry: converge on the committed event without
            # touching the stream, so callers may resend the original command
            # object (including its original expected_stream_version).
            return self.read_capital_risk_snapshot(command.as_of)

        self.require_stream_version(command.expected_stream_version)
        event = self.insert_canonical_event(command)
        if after_event_insert_hook is not None:
            after_event_insert_hook(self)
        if before_projection_hook is not None:
            before_projection_hook(self)
        self.apply_legs_and_projection(event, command)
        if after_projection_hook is not None:
            after_projection_hook(self)
        self.recompute_risk_and_stage_loss(command.as_of, event.economic_event_id)
        self.tombstone_unclaimed_entries_if_versions_changed()
        return self.read_capital_risk_snapshot(command.as_of)


def _gross_total(
    components: tuple[CapitalPositionRisk, ...],
    entry_reserves: tuple[EntryReserveRiskComponent, ...],
    unattributed_risk_cents: int,
) -> int:
    """Kernel revision 2 gross exposure: marks + reserves + unattributed.

    Live-order leaves, pending stress and corporate-action risk stay zero
    until Plan 04 orders and Tasks 3-5 land; every reserve here is
    uncovered, so it counts in full (never optimistic).
    """

    return (
        sum(component.marked_gross_cents for component in components)
        + sum(reserve.reserved_entry_gross_cents for reserve in entry_reserves)
        + unattributed_risk_cents
    )


def _exposure_buckets(
    portfolio_id: str,
    components: tuple[CapitalPositionRisk, ...],
    entry_reserves: tuple[EntryReserveRiskComponent, ...],
    unattributed_risk_cents: int,
) -> tuple[RiskExposureBucket, ...]:
    """Build exposure buckets in the canonical identity order.

    The order mirrors ``canonical_exposure_identities``: GLOBAL, PORTFOLIO,
    then research program / economic lineage / stage buckets in first-seen
    component order over positions followed by entry reserves. Kernel
    revision 2 components are unmarked positions plus reserves, so
    live-order, pending-stress and corporate-action fields are zero until
    Plan 04 and Tasks 3-5 populate them. Unattributed risk lives only in
    the GLOBAL/PORTFOLIO buckets.
    """

    def bucket(
        scope: ExposureScope,
        pid: str | None,
        program: str | None,
        lineage: str | None,
        stage: str | None,
        marked_gross_cents: int,
        reserved_gross_cents: int,
        unattributed_cents: int,
    ) -> RiskExposureBucket:
        return RiskExposureBucket(
            scope=scope,
            portfolio_id=pid,
            research_program_id=program,
            economic_lineage_id=lineage,
            stage_id=stage,
            position_marked_gross_cents=marked_gross_cents,
            live_order_leaves_gross_cents=0,
            reserved_entry_gross_cents=reserved_gross_cents,
            pending_stress_cents=0,
            corporate_action_pending_risk_cents=0,
            unattributed_risk_cents=unattributed_cents,
            total_gross_cents=(
                marked_gross_cents + reserved_gross_cents + unattributed_cents
            ),
        )

    total_marked = sum(component.marked_gross_cents for component in components)
    total_reserved = sum(
        reserve.reserved_entry_gross_cents for reserve in entry_reserves
    )
    buckets = [
        bucket(
            ExposureScope.GLOBAL,
            None,
            None,
            None,
            None,
            total_marked,
            total_reserved,
            unattributed_risk_cents,
        ),
        bucket(
            ExposureScope.PORTFOLIO,
            portfolio_id,
            None,
            None,
            None,
            total_marked,
            total_reserved,
            unattributed_risk_cents,
        ),
    ]

    program_order: list[str] = []
    lineage_by_program: dict[str, list[str]] = {}
    stage_by_lineage: dict[tuple[str, str], list[str]] = {}
    marked_by_program: dict[str, int] = {}
    marked_by_lineage: dict[tuple[str, str], int] = {}
    marked_by_stage: dict[tuple[str, str, str], int] = {}
    reserved_by_program: dict[str, int] = {}
    reserved_by_lineage: dict[tuple[str, str], int] = {}
    reserved_by_stage: dict[tuple[str, str, str], int] = {}

    def register(program: str, lineage: str, stage: str) -> None:
        if program not in lineage_by_program:
            program_order.append(program)
            lineage_by_program[program] = []
        if lineage not in lineage_by_program[program]:
            lineage_by_program[program].append(lineage)
            stage_by_lineage[(program, lineage)] = []
        if stage not in stage_by_lineage[(program, lineage)]:
            stage_by_lineage[(program, lineage)].append(stage)

    for component in components:
        program = component.research_program_id
        lineage = component.economic_lineage_id
        stage = component.stage_id
        register(program, lineage, stage)
        marked_by_program[program] = (
            marked_by_program.get(program, 0) + component.marked_gross_cents
        )
        marked_by_lineage[(program, lineage)] = (
            marked_by_lineage.get((program, lineage), 0)
            + component.marked_gross_cents
        )
        marked_by_stage[(program, lineage, stage)] = (
            marked_by_stage.get((program, lineage, stage), 0)
            + component.marked_gross_cents
        )

    for reserve in entry_reserves:
        program = reserve.research_program_id
        lineage = reserve.economic_lineage_id
        stage = reserve.stage_id
        register(program, lineage, stage)
        reserved_by_program[program] = (
            reserved_by_program.get(program, 0)
            + reserve.reserved_entry_gross_cents
        )
        reserved_by_lineage[(program, lineage)] = (
            reserved_by_lineage.get((program, lineage), 0)
            + reserve.reserved_entry_gross_cents
        )
        reserved_by_stage[(program, lineage, stage)] = (
            reserved_by_stage.get((program, lineage, stage), 0)
            + reserve.reserved_entry_gross_cents
        )

    for program in program_order:
        buckets.append(
            bucket(
                ExposureScope.RESEARCH_PROGRAM,
                portfolio_id,
                program,
                None,
                None,
                marked_by_program.get(program, 0),
                reserved_by_program.get(program, 0),
                0,
            )
        )
        for lineage in lineage_by_program[program]:
            buckets.append(
                bucket(
                    ExposureScope.ECONOMIC_LINEAGE,
                    portfolio_id,
                    program,
                    lineage,
                    None,
                    marked_by_lineage.get((program, lineage), 0),
                    reserved_by_lineage.get((program, lineage), 0),
                    0,
                )
            )
            for stage in stage_by_lineage[(program, lineage)]:
                buckets.append(
                    bucket(
                        ExposureScope.STAGE,
                        portfolio_id,
                        program,
                        lineage,
                        stage,
                        marked_by_stage.get((program, lineage, stage), 0),
                        reserved_by_stage.get((program, lineage, stage), 0),
                        0,
                    )
                )
    return tuple(buckets)


def _fill_legs(
    request: FillRevisionRequest, gross_cents: int
) -> tuple[EconomicEventLeg, ...]:
    """Atomic gross cash + security legs for one fill fact."""

    cash_amount = Decimal(gross_cents) / CENT_SCALE
    idempotency_label = fill_idempotency_key(request.execution_id, request.revision)
    if request.side is ExecutionSide.ENTRY:
        return (
            CashEconomicEventLeg(
                leg_id=f"{idempotency_label}:cash",
                direction=EconomicLegDirection.DEBIT,
                asset_kind=EconomicAssetKind.CASH,
                cash_amount=cash_amount,
            ),
            SecurityEconomicEventLeg(
                leg_id=f"{idempotency_label}:security",
                direction=EconomicLegDirection.CREDIT,
                asset_kind=EconomicAssetKind.SECURITY,
                security_id=request.security_id,
                quantity=request.quantity,
            ),
        )
    return (
        CashEconomicEventLeg(
            leg_id=f"{idempotency_label}:cash",
            direction=EconomicLegDirection.CREDIT,
            asset_kind=EconomicAssetKind.CASH,
            cash_amount=cash_amount,
        ),
        SecurityEconomicEventLeg(
            leg_id=f"{idempotency_label}:security",
            direction=EconomicLegDirection.DEBIT,
            asset_kind=EconomicAssetKind.SECURITY,
            security_id=request.security_id,
            quantity=request.quantity,
        ),
    )


def _fill_fact_from_event_json(canonical_event_json: str) -> tuple[int, ExecutionSide]:
    """Recover (notional cents, side) from a canonical fill event."""

    event = EconomicEvent.model_validate_json(canonical_event_json)
    for leg in event.legs:
        if leg.asset_kind is EconomicAssetKind.CASH:
            cents = scaled_int(leg.cash_amount, CENT_SCALE, "cash_amount")
            side = (
                ExecutionSide.ENTRY
                if leg.direction is EconomicLegDirection.DEBIT
                else ExecutionSide.EXIT
            )
            return cents, side
    raise CapitalConflict(
        "conservation_violation",
        "fill event lost its cash leg",
        economic_event_id=event.economic_event_id,
    )


def _order_fee_state(
    connection: sa.engine.Connection,
    order_id: str,
    fee_rowid: int | None,
    policy: "FeePolicy",
) -> tuple[int, int, int, int, int, int, int]:
    """Active-fact fee state of one order around one fee revision row.

    Returns ``(base_now, stamp_owed, transfer_owed, commission_charged,
    stamp_charged, transfer_charged, active_fill_count)``:

    - ``base_now`` / ``stamp_owed`` / ``transfer_owed`` recompute the fee
      target from the order's ACTIVE fill facts below the cutoff rowid
      (busted fills drop out, corrected fills contribute their corrected
      notional);
    - ``*_charged`` sum what the order's fee streams have actually booked
      below the cutoff (initial charges plus signed bust/correction
      deltas).

    Rowid order is append order, so idempotent retries recompute the
    identical charge even after later fills, busts or corrections land on
    the same order; using the actually-charged history keeps the
    minimum-commission rule exact across fee-policy version changes.
    """

    registry_rows = connection.execute(
        sa.text(
            "SELECT er.rowid AS registry_rowid,"
            " er.execution_id AS execution_id,"
            " er.revision_kind AS revision_kind,"
            " er.payload_content_hash AS payload_content_hash"
            " FROM execution_revisions er"
            " WHERE er.order_id = :order_id"
            " AND er.revision_kind IN ('FILL', 'FILL_BUST',"
            " 'FILL_CORRECTION', 'FEE', 'FEE_BUST', 'FEE_CORRECTION')"
            " ORDER BY er.rowid"
        ),
        {"order_id": order_id},
    ).all()

    event_cache: dict[str, Any] = {}

    def event_row_for(payload_hash: str) -> Any:
        if payload_hash not in event_cache:
            event_cache[payload_hash] = connection.execute(
                sa.text(
                    "SELECT canonical_event_json, payload_json"
                    " FROM economic_events"
                    " WHERE payload_content_hash = :hash"
                ),
                {"hash": payload_hash},
            ).first()
        return event_cache[payload_hash]

    fill_active: dict[str, tuple[int, ExecutionSide] | None] = {}
    stream_totals: dict[str, dict[str, int]] = {}

    for row in registry_rows:
        if fee_rowid is not None and row.registry_rowid >= fee_rowid:
            break
        kind = row.revision_kind
        if kind == "FILL":
            event_row = event_row_for(row.payload_content_hash)
            notional, side = _fill_fact_from_event_json(
                event_row.canonical_event_json
            )
            fill_active[row.execution_id] = (notional, side)
        elif kind == "FILL_BUST":
            fill_active[row.execution_id] = None
        elif kind == "FILL_CORRECTION":
            event_row = event_row_for(row.payload_content_hash)
            payload = CapitalCommandPayload.model_validate_json(
                event_row.payload_json
            )
            fact = payload.execution_revision
            assert fact is not None and fact.side is not None
            fill_active[row.execution_id] = (
                int(fact.corrected_gross_cents or 0),
                fact.side,
            )
        else:
            totals = stream_totals.setdefault(
                row.execution_id,
                {"commission": 0, "stamp_tax": 0, "transfer_fee": 0},
            )
            if kind == "FEE":
                event_row = event_row_for(row.payload_content_hash)
                if event_row is None:
                    # Registry-only zero-charge fact: nothing was booked.
                    continue
                event = EconomicEvent.model_validate_json(
                    event_row.canonical_event_json
                )
                for leg in event.legs:
                    if leg.asset_kind is not EconomicAssetKind.CASH:
                        continue
                    cents = scaled_int(
                        leg.cash_amount, CENT_SCALE, "cash_amount"
                    )
                    signed = (
                        cents
                        if leg.direction is EconomicLegDirection.DEBIT
                        else -cents
                    )
                    if leg.leg_id.endswith(":commission"):
                        totals["commission"] += signed
                    elif leg.leg_id.endswith(":stamp_tax"):
                        totals["stamp_tax"] += signed
                    elif leg.leg_id.endswith(":transfer_fee"):
                        totals["transfer_fee"] += signed
            else:
                event_row = event_row_for(row.payload_content_hash)
                payload = CapitalCommandPayload.model_validate_json(
                    event_row.payload_json
                )
                fact = payload.execution_revision
                assert fact is not None
                totals["commission"] += int(
                    fact.fee_commission_delta_cents or 0
                )
                totals["stamp_tax"] += int(
                    fact.fee_stamp_tax_delta_cents or 0
                )
                totals["transfer_fee"] += int(
                    fact.fee_transfer_fee_delta_cents or 0
                )

    base_now = 0
    stamp_owed = 0
    transfer_owed = 0
    active_fill_count = 0
    for active in fill_active.values():
        if active is None:
            continue
        active_fill_count += 1
        notional, side = active
        components = compute_fee_components(notional, side, policy)
        base_now += components.commission_base_cents
        stamp_owed += components.stamp_tax_cents
        transfer_owed += components.transfer_fee_cents

    commission_charged = sum(
        totals["commission"] for totals in stream_totals.values()
    )
    stamp_charged = sum(
        totals["stamp_tax"] for totals in stream_totals.values()
    )
    transfer_charged = sum(
        totals["transfer_fee"] for totals in stream_totals.values()
    )
    return (
        base_now,
        stamp_owed,
        transfer_owed,
        commission_charged,
        stamp_charged,
        transfer_charged,
        active_fill_count,
    )


def _order_commission_state(
    connection: sa.engine.Connection,
    order_id: str,
    fee_rowid: int | None,
    policy: "FeePolicy",
) -> tuple[int, int]:
    """Per-order commission state around one INITIAL fee revision.

    Returns ``(base_now, charged_before)``: the active-fact commission
    base and the commission actually charged by this order's earlier fee
    rows (see :func:`_order_fee_state`).
    """

    base_now, _, _, commission_charged, _, _, _ = _order_fee_state(
        connection, order_id, fee_rowid, policy
    )
    return base_now, commission_charged


def _fee_payload(
    request: FeeRevisionRequest,
    idempotency_key: str,
    named_components: tuple[tuple[str, int], ...],
) -> CapitalCommandPayload:
    """One FEE_CHARGED payload with one cash debit leg per positive component.

    Leg identities embed the fee-policy version, so two revisions charging
    identical cents under different schedules remain distinct facts.
    """

    legs = tuple(
        CashEconomicEventLeg(
            leg_id=(
                f"{idempotency_key}:"
                f"{request.fee_policy.fee_policy_version}:{name}"
            ),
            direction=EconomicLegDirection.DEBIT,
            asset_kind=EconomicAssetKind.CASH,
            cash_amount=Decimal(cents) / CENT_SCALE,
        )
        for name, cents in named_components
        if cents > 0
    )
    return CapitalCommandPayload(
        event_kind=EconomicEventKind.FEE_CHARGED,
        effective_at=request.effective_at,
        source_authority=request.source_authority,
        legs=legs,
    )


def _zero_fee_receipt_hash(request: FeeRevisionRequest) -> str:
    """Canonical identity of a zero-delta fee revision (no economic event)."""

    return content_hash(
        {
            "kind": "fee_revision_zero_charge",
            "fill_execution_id": request.fill_execution_id,
            "revision": request.revision,
            "revision_kind": request.revision_kind.value,
            "fee_policy_version": request.fee_policy.fee_policy_version,
        }
    )


class CapitalRepository:
    """Gateway-owned store for one AccountCapitalTruth stream."""

    def __init__(self, engine: sa.engine.Engine, database_path: Path) -> None:
        self._engine = engine
        self._database_path = database_path
        self._metadata = build_metadata()

    @property
    def engine(self) -> sa.engine.Engine:
        return self._engine

    @property
    def database_path(self) -> Path:
        return self._database_path

    @classmethod
    def _connect(cls, database_path: Path) -> "CapitalRepository":
        engine = sa.create_engine(f"sqlite:///{database_path}", future=True)
        sa.event.listen(engine, "connect", configure_sqlite_connection)
        return cls(engine, database_path)

    @classmethod
    def initialize(cls, database_path: str | Path) -> "CapitalRepository":
        """Create (idempotently) the ledger schema and sentinel meta rows."""

        path = Path(database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        repository = cls._connect(path)
        with repository._engine.begin() as conn:
            repository._metadata.create_all(conn)
            for ddl in IMMUTABILITY_TRIGGER_DDL:
                conn.exec_driver_sql(ddl)
            now = utc_iso(utc_now())
            for key, value in GATEWAY_META_DEFAULTS.items():
                conn.execute(
                    sa.text(
                        "INSERT OR IGNORE INTO gateway_meta (key, value, updated_at)"
                        " VALUES (:key, :value, :updated_at)"
                    ),
                    {"key": key, "value": value, "updated_at": now},
                )
        return repository

    @classmethod
    def open(cls, database_path: str | Path) -> "CapitalRepository":
        """Open an existing ledger, failing closed on schema mismatch."""

        path = Path(database_path)
        if not path.exists():
            raise FileNotFoundError(f"capital ledger not found: {path}")
        repository = cls._connect(path)
        with repository._engine.connect() as conn:
            row = conn.execute(
                sa.text("SELECT value FROM gateway_meta WHERE key = 'schema_version'")
            ).first()
        actual = int(row.value) if row is not None else None
        if actual != LEDGER_SCHEMA_VERSION:
            raise CapitalConflict(
                "schema_version_mismatch",
                "capital ledger schema does not match this kernel revision",
                expected=LEDGER_SCHEMA_VERSION,
                actual=actual,
            )
        return repository

    def append_atomic(
        self,
        command: CapitalCommand,
        *,
        after_event_insert_hook: ProjectorHook | None = None,
    ) -> CapitalRiskSnapshot:
        """Append one canonical event and its projection in one transaction.

        The whole kernel step set runs inside ``BEGIN IMMEDIATE`` so any
        failure - contract rejection, CAS conflict, projector error, or crash
        before COMMIT - leaves zero partial writes.
        """

        if not isinstance(command, CapitalCommand):
            raise TypeError("append_atomic requires a CapitalCommand instance")
        conn = self._engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        try:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                context = GatewayTransactionContext(self, conn)
                snapshot = context.run_append(command, after_event_insert_hook)
            except IntegrityError as exc:
                with contextlib.suppress(DBAPIError):
                    conn.exec_driver_sql("ROLLBACK")
                raise CapitalConflict(
                    "canonical_fact_conflict",
                    "a canonical event identity already exists for this fact",
                    detail=str(exc.orig),
                ) from exc
            except BaseException:
                with contextlib.suppress(DBAPIError):
                    conn.exec_driver_sql("ROLLBACK")
                raise
            conn.exec_driver_sql("COMMIT")
            return snapshot
        finally:
            conn.close()

    def events(self) -> tuple[EconomicEvent, ...]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT canonical_event_json FROM economic_events"
                    " ORDER BY stream_version"
                )
            ).all()
        return tuple(
            EconomicEvent.model_validate_json(row.canonical_event_json) for row in rows
        )

    def stream_version(self) -> int:
        with self._engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT COALESCE(MAX(stream_version), 0) AS v FROM economic_events"
                )
            ).one()
        return int(row.v)

    def capital_version(self) -> int:
        with self._engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT COALESCE("
                    " (SELECT capital_version FROM capital_projection), 0) AS v"
                )
            ).one()
        return int(row.v)

    def schema_version(self) -> int:
        with self._engine.connect() as conn:
            value = conn.execute(
                sa.text("SELECT value FROM gateway_meta WHERE key = 'schema_version'")
            ).scalar()
        return int(value)

    # -- Plan 02 Task 2: fills, fees, reserves, conservation -------------------

    def _run_write_transaction(self, operation: Callable[[GatewayTransactionContext], Any]) -> Any:
        """Run one BEGIN IMMEDIATE gateway transaction for a Task 2 command.

        Mirrors ``append_atomic`` crash semantics: any failure before COMMIT
        rolls the whole command back with zero partial writes.
        """

        conn = self._engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        try:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                context = GatewayTransactionContext(self, conn)
                result = operation(context)
            except IntegrityError as exc:
                with contextlib.suppress(DBAPIError):
                    conn.exec_driver_sql("ROLLBACK")
                raise CapitalConflict(
                    "canonical_fact_conflict",
                    "a canonical identity already exists for this fact",
                    detail=str(exc.orig),
                ) from exc
            except BaseException:
                with contextlib.suppress(DBAPIError):
                    conn.exec_driver_sql("ROLLBACK")
                raise
            conn.exec_driver_sql("COMMIT")
            return result
        finally:
            conn.close()

    def _stored_binding(self, context: GatewayTransactionContext) -> AccountBinding:
        row = context._connection.execute(
            context._table("account_capital_truth").select()
        ).first()
        if row is None:
            raise CapitalConflict(
                "account_not_bound",
                "the ledger must be bound before Task 2 commands may write",
            )
        return AccountBinding(
            portfolio_id=row.portfolio_id,
            mode=ExecutionMode(row.execution_mode),
            broker_account_id=row.broker_account_id,
            base_currency=row.base_currency,
            environment_fingerprint=row.environment_fingerprint,
        )

    def capital_risk_snapshot(self, as_of: datetime) -> CapitalRiskSnapshot:
        """Read the complete CapitalRiskSnapshot at one capital version.

        The read is quiet: it never grows the stream or capital version.
        """

        with self._engine.connect() as conn:
            row = conn.execute(
                self._metadata.tables["account_capital_truth"].select()
            ).first()
            if row is None:
                raise CapitalConflict(
                    "account_not_bound",
                    "no AccountCapitalTruth is bound to this ledger",
                )
            context = GatewayTransactionContext(self, conn)
            return context.read_capital_risk_snapshot(as_of)

    # -- Plan 02 Task 5: complete risk snapshot, drawdown latch, stage loss ---

    def build_capital_risk_snapshot(
        self, request: BuildRiskSnapshotRequest
    ) -> CapitalRiskSnapshot:
        """Build the complete DERIVED risk snapshot with fail-closed marks.

        Unlike ``capital_risk_snapshot`` (which is quiet and lenient for
        audit reads), this builder validates that every open position has a
        current, authorized, valid mark and refuses to emit a snapshot when
        any component is unknown or stale. The read is quiet: it never grows
        the stream or capital version.
        """

        def operation(context: GatewayTransactionContext) -> CapitalRiskSnapshot:
            self._stored_binding(context)
            return _build_capital_risk_snapshot(context, request)

        conn = self._engine.connect()
        try:
            context = GatewayTransactionContext(self, conn)
            return operation(context)
        finally:
            conn.close()

    def activate_stage_loss_budget(
        self, request: StageLossBudgetActivationRequest
    ) -> CapitalRiskSnapshot:
        """Freeze one non-replenishable stage-loss budget in integer cents."""

        def operation(context: GatewayTransactionContext) -> CapitalRiskSnapshot:
            self._stored_binding(context)
            # A budget gates new entry risk; only an ACTIVE account can have
            # one frozen. TERMINATING/INSOLVENT drain without new budgets.
            context.require_lifecycle(frozenset({LifecycleState.ACTIVE}))
            return _activate_stage_loss_budget(context, request)

        return self._run_write_transaction(operation)

    def record_stage_loss(
        self, request: StageLossChargeRequest
    ) -> tuple[StageLossChargeReceipt, CapitalRiskSnapshot]:
        """Consume one attributed stage-loss charge monotonically."""

        def operation(
            context: GatewayTransactionContext,
        ) -> tuple[StageLossChargeReceipt, CapitalRiskSnapshot]:
            self._stored_binding(context)
            # Stage-loss measurement continues through drain and insolvency
            # (exits and reconciliation never stop); only TERMINATED rejects.
            context.require_lifecycle(
                frozenset(
                    {
                        LifecycleState.ACTIVE,
                        LifecycleState.TERMINATING,
                        LifecycleState.INSOLVENT,
                    }
                )
            )
            return _record_stage_loss(context, request)

        return self._run_write_transaction(operation)

    def close_risk_snapshot(
        self, request: CloseRiskSnapshotRequest
    ) -> tuple[RiskSnapshotCloseReceipt, CapitalRiskSnapshot]:
        """Seal the session snapshot as one append-only RISK_SNAPSHOT record.

        Identical closes converge on the sealed artifact; divergent closes
        conflict and never overwrite. Sealing is a finalization fact: it
        records the observed capital/stream versions without growing them.
        """

        def operation(
            context: GatewayTransactionContext,
        ) -> tuple[RiskSnapshotCloseReceipt, CapitalRiskSnapshot]:
            self._stored_binding(context)
            context.require_lifecycle(
                frozenset(
                    {
                        LifecycleState.ACTIVE,
                        LifecycleState.TERMINATING,
                        LifecycleState.INSOLVENT,
                    }
                )
            )
            return _close_risk_snapshot(context, request)

        return self._run_write_transaction(operation)

    def stage_loss_latches(self) -> tuple[StageLossLatchSnapshot, ...]:
        """Read the current per-stage loss consumption/latch projection."""

        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT * FROM stage_loss_state"
                    " ORDER BY research_program_id, economic_lineage_id,"
                    " stage_id"
                )
            ).all()
        return tuple(
            StageLossLatchSnapshot(
                research_program_id=row.research_program_id,
                economic_lineage_id=row.economic_lineage_id,
                stage_id=row.stage_id,
                stage_loss_budget_id=row.stage_loss_budget_id,
                frozen_budget_cents=int(row.frozen_budget_cents),
                consumed_cents=int(row.consumed_cents),
                stage_loss_version=int(row.stage_loss_version),
                state=StageLossLatchState(row.state),
            )
            for row in rows
        )

    def reserve_entry(self, request: ReserveEntryRequest) -> CapitalRiskSnapshot:
        """Create a LIVE entry reserve consuming available capital."""

        def operation(context: GatewayTransactionContext) -> CapitalRiskSnapshot:
            conn = context._connection
            self._stored_binding(context)
            # New entry risk is blocked once the account is terminating,
            # terminated, or insolvent (exits and reconciliation continue).
            context.require_lifecycle(
                frozenset({LifecycleState.ACTIVE})
            )
            reserves_table = context._table("reserves")
            existing = conn.execute(
                reserves_table.select().where(
                    reserves_table.c.source_id == request.source_id
                )
            ).first()
            if existing is not None:
                identical = (
                    existing.research_program_id == request.research_program_id
                    and existing.economic_lineage_id
                    == request.economic_lineage_id
                    and existing.stage_id == request.stage_id
                    and int(existing.reserved_entry_gross_cents)
                    == request.reserved_entry_gross_cents
                )
                if identical:
                    return context.read_capital_risk_snapshot(request.as_of)
                raise CapitalConflict(
                    "reserve_source_conflict",
                    "reserve source identity already committed with different"
                    " content",
                    source_id=request.source_id,
                )
            projection_table = context._table("capital_projection")
            projection = conn.execute(projection_table.select()).one()
            available = int(projection.available_cash_cents)
            if available < request.reserved_entry_gross_cents:
                raise CapitalConflict(
                    "insufficient_available_cash",
                    "reserve exceeds available capital",
                    available_cash_cents=available,
                    requested_cents=request.reserved_entry_gross_cents,
                )
            now = utc_iso(request.as_of)
            conn.execute(
                projection_table.update()
                .where(
                    projection_table.c.portfolio_id == projection.portfolio_id
                )
                .values(
                    available_cash_cents=(
                        available - request.reserved_entry_gross_cents
                    ),
                    restricted_cash_cents=(
                        int(projection.restricted_cash_cents)
                        + request.reserved_entry_gross_cents
                    ),
                    capital_version=int(projection.capital_version) + 1,
                    updated_at=now,
                    updated_by_event_id=None,
                )
            )
            conn.execute(
                reserves_table.insert().values(
                    reserve_id=f"rsv:{request.source_id}",
                    source_id=request.source_id,
                    research_program_id=request.research_program_id,
                    economic_lineage_id=request.economic_lineage_id,
                    stage_id=request.stage_id,
                    covered_live_order_id=None,
                    reserved_entry_gross_cents=(
                        request.reserved_entry_gross_cents
                    ),
                    state=CapitalReserveState.LIVE.value,
                    created_at=now,
                )
            )
            # Reserves are risk: latch and stage-loss state update in the
            # same transaction as the reserve fact.
            context.recompute_risk_and_stage_loss(
                request.as_of, f"reserve:{request.source_id}:entry"
            )
            return context.read_capital_risk_snapshot(request.as_of)

        return self._run_write_transaction(operation)

    def release_reserve(self, request: ReserveReleaseRequest) -> CapitalRiskSnapshot:
        """Walk one reserve through the cancel/release state machine.

        ``SUBMISSION_AMBIGUOUS`` never releases: the worst-case reserve stays
        live in the risk snapshot until a confirmed fill or a confirmed
        terminal order state resolves the ambiguity.
        """

        def operation(context: GatewayTransactionContext) -> CapitalRiskSnapshot:
            conn = context._connection
            self._stored_binding(context)
            reserves_table = context._table("reserves")
            row = conn.execute(
                reserves_table.select().where(
                    reserves_table.c.source_id == request.source_id
                )
            ).first()
            if row is None:
                raise CapitalConflict(
                    "reserve_unknown",
                    "no reserve exists for this source identity",
                    source_id=request.source_id,
                )
            state = CapitalReserveState(row.state)
            cents = int(row.reserved_entry_gross_cents)
            reason = request.reason

            if reason is ReserveReleaseReason.SUBMISSION_AMBIGUOUS:
                raise CapitalConflict(
                    "submission_ambiguous_worst_case_retained",
                    "ambiguous submission keeps the worst-case reserve live;"
                    " resolve it with a confirmed fill or terminal order state",
                    source_id=request.source_id,
                    state=state.value,
                )

            projection_table = context._table("capital_projection")
            projection = conn.execute(projection_table.select()).one()
            now = utc_iso(request.as_of)

            if reason is ReserveReleaseReason.CANCEL_REQUESTED:
                if state is CapitalReserveState.CANCEL_PENDING:
                    # Quiet idempotent convergence: no capital fact changed.
                    return context.read_capital_risk_snapshot(request.as_of)
                if state is not CapitalReserveState.LIVE:
                    raise CapitalConflict(
                        "reserve_state_conflict",
                        "cancel request against a terminal reserve state",
                        source_id=request.source_id,
                        state=state.value,
                    )
                conn.execute(
                    reserves_table.update()
                    .where(reserves_table.c.source_id == request.source_id)
                    .values(state=CapitalReserveState.CANCEL_PENDING.value)
                )
                conn.execute(
                    projection_table.update()
                    .where(
                        projection_table.c.portfolio_id
                        == projection.portfolio_id
                    )
                    .values(
                        capital_version=int(projection.capital_version) + 1,
                        updated_at=now,
                        updated_by_event_id=None,
                    )
                )
                context.recompute_risk_and_stage_loss(
                    request.as_of,
                    f"reserve:{request.source_id}:cancel_requested",
                )
                return context.read_capital_risk_snapshot(request.as_of)

            # Confirmed terminal reasons release LIVE and CANCEL_PENDING alike.
            if state in (
                CapitalReserveState.LIVE,
                CapitalReserveState.CANCEL_PENDING,
            ):
                conn.execute(
                    reserves_table.update()
                    .where(reserves_table.c.source_id == request.source_id)
                    .values(state=CapitalReserveState.RELEASED.value)
                )
                conn.execute(
                    projection_table.update()
                    .where(
                        projection_table.c.portfolio_id
                        == projection.portfolio_id
                    )
                    .values(
                        available_cash_cents=(
                            int(projection.available_cash_cents) + cents
                        ),
                        restricted_cash_cents=(
                            int(projection.restricted_cash_cents) - cents
                        ),
                        capital_version=int(projection.capital_version) + 1,
                        updated_at=now,
                        updated_by_event_id=None,
                    )
                )
                context.recompute_risk_and_stage_loss(
                    request.as_of,
                    f"reserve:{request.source_id}:released:{reason.value}",
                )
                # The released reservation is an invalidated entry: the
                # tombstone lands atomically in this capital transaction.
                context.tombstone_unclaimed_entries_if_versions_changed()
                return context.read_capital_risk_snapshot(request.as_of)
            if state is CapitalReserveState.RELEASED:
                # Quiet idempotent convergence: already released.
                return context.read_capital_risk_snapshot(request.as_of)
            raise CapitalConflict(
                "reserve_state_conflict",
                "a consumed reserve cannot be released; its cash became a fill",
                source_id=request.source_id,
                state=state.value,
            )

        return self._run_write_transaction(operation)

    def record_fill_revision(
        self, request: FillRevisionRequest
    ) -> tuple[
        FillRevisionReceipt | ExecutionRevisionReceipt, CapitalRiskSnapshot
    ]:
        """Record one broker execution report as a canonical economic event.

        One fact / one event: the fill's gross cash leg and security leg land
        atomically in one capital transaction. Unattributed fills and late
        fills after a confirmed cancel are preserved under sentinel
        attribution and flagged, never dropped.

        ``revision > 1`` requests are broker bust/correction supersessions
        (Plan 02 Task 6) and dispatch to the execution-revision machinery;
        the recorded fact is preserved and capital re-projects from the
        append-only history.
        """

        if request.revision != 1:
            revision_request = ExecutionRevisionRequest(
                execution_id=request.execution_id,
                revision=request.revision,
                revision_kind=request.revision_kind,
                order_id=request.order_id,
                side=request.side,
                security_id=request.security_id,
                position_lineage_id=request.position_lineage_id,
                economic_lot_id=request.economic_lot_id,
                superseded_quantity=(
                    request.quantity
                    if request.revision_kind is ExecutionRevisionKind.BUSTED
                    else None
                ),
                corrected_price_micros=(
                    request.price_micros
                    if request.revision_kind
                    is ExecutionRevisionKind.CORRECTED
                    else None
                ),
                corrected_quantity=(
                    request.quantity
                    if request.revision_kind
                    is ExecutionRevisionKind.CORRECTED
                    else None
                ),
                source_authority=request.source_authority,
                effective_at=request.effective_at,
                as_of=request.as_of,
                expected_stream_version=request.expected_stream_version,
            )
            return self._record_execution_bust_or_correction(revision_request)
        gross_cents = fill_gross_cents(request.price_micros, request.quantity)
        if gross_cents < 1:
            raise CapitalConflict(
                "fill_gross_rounds_to_zero",
                "fill notional rounds to zero cents under the frozen policy",
                price_micros=request.price_micros,
                quantity=request.quantity,
            )

        def operation(
            context: GatewayTransactionContext,
        ) -> tuple[FillRevisionReceipt, CapitalRiskSnapshot]:
            conn = context._connection
            binding = self._stored_binding(context)
            # TERMINATED rejects every fill; TERMINATING/INSOLVENT keep
            # exits and reconciliation alive but block new entry risk.
            if request.side is ExecutionSide.ENTRY:
                context.require_lifecycle(frozenset({LifecycleState.ACTIVE}))
            else:
                context.require_lifecycle(
                    frozenset(
                        {
                            LifecycleState.ACTIVE,
                            LifecycleState.TERMINATING,
                            LifecycleState.INSOLVENT,
                        }
                    )
                )
            reserves_table = context._table("reserves")
            reserve_row = None
            if request.reserve_source_id is not None:
                reserve_row = conn.execute(
                    reserves_table.select().where(
                        reserves_table.c.source_id == request.reserve_source_id
                    )
                ).first()
                if reserve_row is None:
                    raise CapitalConflict(
                        "reserve_unknown",
                        "fill references an unknown reserve",
                        source_id=request.reserve_source_id,
                    )

            reserve_state = (
                CapitalReserveState(reserve_row.state)
                if reserve_row is not None
                else None
            )
            # A fill after a CONFIRMED cancel is plan-violating: it is still
            # economically real, so it is preserved under sentinel
            # attribution and flagged for reconciliation. The fill's own
            # execution identity becomes its lot: the plan it contradicted
            # cannot vouch for any claimed lot identity.
            late_fill = reserve_state is CapitalReserveState.RELEASED
            unattributed = request.attribution is None or late_fill
            if late_fill:
                lineage, lot = unattributed_position_identity(request.execution_id)
            elif request.position_lineage_id is None:
                lineage, lot = unattributed_position_identity(request.execution_id)
            else:
                lineage = request.position_lineage_id
                lot = request.economic_lot_id
            reserve_consumed_cents = (
                int(reserve_row.reserved_entry_gross_cents)
                if reserve_state
                in (
                    CapitalReserveState.LIVE,
                    CapitalReserveState.CANCEL_PENDING,
                )
                else None
            )

            # Late/plan-violating fills lose their claimed attribution: the
            # entry decision they contradicted cannot vouch for them.
            attribution = None if unattributed else request.attribution
            payload = CapitalCommandPayload(
                event_kind=EconomicEventKind.TRADE_EXECUTED,
                effective_at=request.effective_at,
                source_authority=request.source_authority,
                position_lineage_id=lineage,
                economic_lot_id=lot,
                legs=_fill_legs(request, gross_cents),
                producer_namespace=(
                    attribution.producer_namespace
                    if attribution is not None
                    else UNATTRIBUTED_PRODUCER
                ),
                research_program_id=(
                    attribution.research_program_id
                    if attribution is not None
                    else UNATTRIBUTED_PROGRAM
                ),
                economic_lineage_id=(
                    attribution.economic_lineage_id
                    if attribution is not None
                    else UNATTRIBUTED_LINEAGE
                ),
                stage_id=(
                    attribution.stage_id
                    if attribution is not None
                    else UNATTRIBUTED_STAGE
                ),
            )
            idempotency_key = fill_idempotency_key(
                request.execution_id, request.revision
            )
            payload_hash = payload.content_hash()

            registry = context._table("execution_revisions")
            registry_row = conn.execute(
                registry.select().where(
                    sa.and_(
                        registry.c.execution_id == request.execution_id,
                        registry.c.revision == request.revision,
                    )
                )
            ).first()
            if registry_row is not None:
                if registry_row.revision_kind != "FILL":
                    raise CapitalConflict(
                        "revision_kind_conflict",
                        "execution revision identity reused by another fact kind",
                        execution_id=request.execution_id,
                        revision=request.revision,
                    )
                if registry_row.payload_content_hash != payload_hash:
                    raise CapitalConflict(
                        "payload_conflict",
                        "fill revision already committed with different content",
                        execution_id=request.execution_id,
                        revision=request.revision,
                    )
                # Idempotent convergence: rebuild the receipt from the
                # committed canonical event and reserve state.
                event_row = conn.execute(
                    sa.text(
                        "SELECT canonical_event_json FROM economic_events"
                        " WHERE idempotency_key = :key"
                    ),
                    {"key": idempotency_key},
                ).one()
                event = EconomicEvent.model_validate_json(
                    event_row.canonical_event_json
                )
                snapshot = context.read_capital_risk_snapshot(request.as_of)
                # The consuming fill left the reserve CONSUMED; reconstruct
                # the original receipt's consumed amount from that terminal
                # state (only this fill can have consumed it: its registry
                # row and payload hash match).
                consumed_on_retry = (
                    int(reserve_row.reserved_entry_gross_cents)
                    if reserve_state is CapitalReserveState.CONSUMED
                    else reserve_consumed_cents
                )
                receipt = FillRevisionReceipt(
                    execution_id=request.execution_id,
                    order_id=request.order_id,
                    revision=request.revision,
                    event_id=event.economic_event_id,
                    side=request.side,
                    security_id=request.security_id,
                    gross_cents=gross_cents,
                    quantity=request.quantity,
                    position_lineage_id=event.position_lineage_id,
                    economic_lot_id=event.economic_lot_id,
                    unattributed=unattributed,
                    reserve_consumed_cents=consumed_on_retry,
                    capital_version=snapshot.capital_version,
                    stream_version=event.stream_version,
                )
                return receipt, snapshot

            if reserve_state is CapitalReserveState.CONSUMED:
                raise CapitalConflict(
                    "reserve_state_conflict",
                    "reserve already consumed by another fill",
                    source_id=request.reserve_source_id,
                )

            command = CapitalCommand(
                idempotency_key=idempotency_key,
                account_binding=binding,
                expected_stream_version=request.expected_stream_version,
                as_of=request.as_of,
                payload=payload,
            )

            def consume_reserve(tx: GatewayTransactionContext) -> None:
                if reserve_consumed_cents is None:
                    return
                projection_table = tx._table("capital_projection")
                projection = tx._connection.execute(
                    projection_table.select()
                ).one()
                tx._connection.execute(
                    projection_table.update()
                    .where(
                        projection_table.c.portfolio_id
                        == projection.portfolio_id
                    )
                    .values(
                        available_cash_cents=(
                            int(projection.available_cash_cents)
                            + reserve_consumed_cents
                        ),
                        restricted_cash_cents=(
                            int(projection.restricted_cash_cents)
                            - reserve_consumed_cents
                        ),
                        updated_at=utc_iso(request.as_of),
                    )
                )
                tx._connection.execute(
                    reserves_table.update()
                    .where(
                        reserves_table.c.source_id == request.reserve_source_id
                    )
                    .values(state=CapitalReserveState.CONSUMED.value)
                )

            def register_revision(tx: GatewayTransactionContext) -> None:
                tx._connection.execute(
                    registry.insert().values(
                        execution_revision_id=idempotency_key,
                        execution_id=request.execution_id,
                        revision=request.revision,
                        revision_kind="FILL",
                        order_id=request.order_id,
                        payload_content_hash=payload_hash,
                        recorded_at=utc_iso(request.as_of),
                    )
                )

            snapshot = context.run_append(
                command,
                after_event_insert_hook=None,
                before_projection_hook=consume_reserve,
                after_projection_hook=register_revision,
            )
            receipt = FillRevisionReceipt(
                execution_id=request.execution_id,
                order_id=request.order_id,
                revision=request.revision,
                event_id=derive_event_id(idempotency_key),
                side=request.side,
                security_id=request.security_id,
                gross_cents=gross_cents,
                quantity=request.quantity,
                position_lineage_id=lineage,
                economic_lot_id=lot,
                unattributed=unattributed,
                reserve_consumed_cents=reserve_consumed_cents,
                capital_version=snapshot.capital_version,
                stream_version=context.current_stream_version(),
            )
            return receipt, snapshot

        return self._run_write_transaction(operation)

    # -- Plan 02 Task 6: execution bust/correction and reopen ----------------

    def record_execution_revision(
        self, request: ExecutionRevisionRequest
    ) -> tuple[ExecutionRevisionReceipt, CapitalRiskSnapshot]:
        """Record one broker bust of a recorded fill execution.

        The bust appends an exact compensation of the active fact under
        ``(execution_id, revision)``: its effective filled quantity and
        gross cash become zero, the recorded history is preserved, and the
        capital projection is recomputed from the append-only stream. An
        entry bust flattens the lot (tombstoning it); an exit bust can
        restore a positive holding and reopens the exit obligation.
        """

        if request.revision_kind is not ExecutionRevisionKind.BUSTED:
            raise CapitalConflict(
                "revision_kind_conflict",
                "record_execution_revision records BUSTED revisions",
                revision_kind=request.revision_kind.value,
            )
        return self._record_execution_bust_or_correction(request)

    def record_execution_correction(
        self, request: ExecutionRevisionRequest
    ) -> tuple[ExecutionRevisionReceipt, CapitalRiskSnapshot]:
        """Record one broker correction of a recorded fill execution.

        ``CORRECTED`` equals busting the active value and applying the
        corrected value in one canonical event: the superseded fact is
        reversed exactly (refunding the basis an exit consumed) and the
        corrected fact is applied. A correction that transitions the lot
        from flat/nonpositive back to positive reopens the exit
        obligation. Corrections that would create negative shares are
        preserved and latch ``RECONCILIATION_HALT``, never clamped.
        """

        if request.revision_kind is not ExecutionRevisionKind.CORRECTED:
            raise CapitalConflict(
                "revision_kind_conflict",
                "record_execution_correction records CORRECTED revisions",
                revision_kind=request.revision_kind.value,
            )
        return self._record_execution_bust_or_correction(request)

    def reopen_exit_obligations(self) -> tuple[ReopenedEconomicLot, ...]:
        """Durable reopened exit obligations for Plan 04 consumption."""

        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT * FROM exit_obligation_reopens"
                    " ORDER BY capital_version, stream_version, reopen_id"
                )
            ).all()
        return tuple(
            ReopenedEconomicLot(
                reopen_id=row.reopen_id,
                position_lineage_id=row.position_lineage_id,
                economic_lot_id=row.economic_lot_id,
                security_id=row.security_id,
                producer_namespace=row.producer_namespace,
                research_program_id=row.research_program_id,
                economic_lineage_id=row.economic_lineage_id,
                stage_id=row.stage_id,
                reopened_quantity_units=int(row.reopened_quantity_units),
                position_state=PositionState(row.position_state),
                reopen_reason=row.reopen_reason,
                mandate_revision_floor=int(row.mandate_revision_floor),
                reopened_by_execution_revision_id=(
                    row.reopened_by_execution_revision_id
                ),
                reopened_by_event_id=row.reopened_by_event_id,
                capital_version=int(row.capital_version),
                stream_version=int(row.stream_version),
            )
            for row in rows
        )

    def reconciliation_discrepancies(
        self,
    ) -> tuple[ReconciliationDiscrepancy, ...]:
        """Preserved impossible position states under reconciliation halt.

        Negative (long-only impossible) projections are kept signed in the
        ledger and surfaced here; they are never clamped to zero, dropped,
        or papered over with valuation events (charter item 15).
        """

        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT * FROM positions"
                    " WHERE settled_quantity_units < 0"
                    " OR tradable_quantity_units < 0"
                    " OR cost_basis_cents < 0"
                    " ORDER BY position_lineage_id, economic_lot_id"
                )
            ).all()
        return tuple(
            ReconciliationDiscrepancy(
                position_lineage_id=row.position_lineage_id,
                economic_lot_id=row.economic_lot_id,
                security_id=row.security_id,
                settled_quantity_units=int(row.settled_quantity_units),
                tradable_quantity_units=int(row.tradable_quantity_units),
                cost_basis_cents=int(row.cost_basis_cents),
            )
            for row in rows
        )

    # -- revision internals ----------------------------------------------------

    def _fill_registry_rows(
        self, conn: sa.engine.Connection, execution_id: str
    ) -> tuple[Any, ...]:
        registry = self._metadata.tables["execution_revisions"]
        return tuple(
            conn.execute(
                registry.select()
                .where(
                    sa.and_(
                        registry.c.execution_id == execution_id,
                        registry.c.revision_kind.in_(
                            tuple(sorted(FILL_REVISION_KINDS))
                        ),
                    )
                )
                .order_by(registry.c.revision)
            ).all()
        )

    def _event_row_by_payload_hash(
        self, conn: sa.engine.Connection, payload_hash: str
    ) -> Any:
        row = conn.execute(
            sa.text(
                "SELECT * FROM economic_events"
                " WHERE payload_content_hash = :hash"
            ),
            {"hash": payload_hash},
        ).first()
        if row is None:
            raise CapitalConflict(
                "conservation_violation",
                "execution revision registry row lost its canonical event",
                payload_content_hash=payload_hash,
            )
        return row

    def _original_fill_context(
        self, conn: sa.engine.Connection, fill_rows: tuple[Any, ...]
    ) -> dict[str, Any]:
        """The immutable identity and attribution of the recorded fill."""

        event_row = self._event_row_by_payload_hash(
            conn, fill_rows[0].payload_content_hash
        )
        payload = CapitalCommandPayload.model_validate_json(
            event_row.payload_json
        )
        gross_cents, side = _fill_fact_from_event_json(
            event_row.canonical_event_json
        )
        quantity = 0
        for leg in payload.legs:
            if leg.asset_kind is EconomicAssetKind.SECURITY:
                quantity = int(leg.quantity)
        return {
            "event_id": event_row.economic_event_id,
            "order_id": fill_rows[0].order_id,
            "side": side,
            "gross_cents": gross_cents,
            "quantity": quantity,
            "position_lineage_id": event_row.position_lineage_id,
            "economic_lot_id": event_row.economic_lot_id,
            "security_id": next(
                leg.security_id
                for leg in payload.legs
                if leg.asset_kind is EconomicAssetKind.SECURITY
            ),
            "producer_namespace": payload.producer_namespace,
            "research_program_id": payload.research_program_id,
            "economic_lineage_id": payload.economic_lineage_id,
            "stage_id": payload.stage_id,
        }

    def _active_fill_fact(
        self,
        conn: sa.engine.Connection,
        fill_rows: tuple[Any, ...],
        original: dict[str, Any],
        before_revision: int,
    ) -> dict[str, Any] | None:
        """The fill's active fact below ``before_revision``.

        Returns ``None`` exactly when the newest committed revision below
        the boundary is a bust (the execution currently contributes
        nothing). For a corrected active fact the consumed basis is the
        amount recorded on the correction event itself.
        """

        active_row = None
        for row in fill_rows:
            if int(row.revision) < before_revision:
                active_row = row
        if active_row is None:
            raise CapitalConflict(
                "execution_unknown",
                "execution revision chain lost its recorded fill",
            )
        kind = active_row.revision_kind
        if kind == FILL_KIND:
            return {
                "event_id": self._event_row_by_payload_hash(
                    conn, active_row.payload_content_hash
                ).economic_event_id,
                "side": original["side"],
                "gross_cents": original["gross_cents"],
                "quantity": original["quantity"],
                "consumed_basis_cents": None,
            }
        if kind == FILL_BUST_KIND:
            return {
                "event_id": self._event_row_by_payload_hash(
                    conn, active_row.payload_content_hash
                ).economic_event_id,
                "side": None,
                "gross_cents": 0,
                "quantity": 0,
                "consumed_basis_cents": None,
            }
        event_row = self._event_row_by_payload_hash(
            conn, active_row.payload_content_hash
        )
        payload = CapitalCommandPayload.model_validate_json(
            event_row.payload_json
        )
        fact = payload.execution_revision
        if fact is None or fact.fact_kind is not (
            ExecutionRevisionFactKind.FILL
        ):
            raise CapitalConflict(
                "conservation_violation",
                "fill correction registry row lost its revision fact",
            )
        return {
            "event_id": event_row.economic_event_id,
            "side": fact.side,
            "gross_cents": (
                int(fact.corrected_gross_cents)
                if fact.corrected_gross_cents is not None
                else 0
            ),
            "quantity": (
                int(fact.corrected_quantity)
                if fact.corrected_quantity is not None
                else 0
            ),
            "consumed_basis_cents": fact.corrected_consumed_basis_cents,
        }

    def _lot_event_facts(
        self,
        conn: sa.engine.Connection,
        position_lineage_id: str,
        economic_lot_id: str,
        upto_stream_version: int | None = None,
    ) -> tuple[LotEventFact, ...]:
        """The lot's trade/revision facts in stream order (pure inputs)."""

        rows = conn.execute(
            sa.text(
                "SELECT economic_event_id, stream_version, event_kind,"
                " payload_json FROM economic_events"
                " WHERE position_lineage_id = :lineage"
                " AND economic_lot_id = :lot"
                " ORDER BY stream_version"
            ),
            {"lineage": position_lineage_id, "lot": economic_lot_id},
        ).all()
        facts: list[LotEventFact] = []
        for row in rows:
            if (
                upto_stream_version is not None
                and int(row.stream_version) > upto_stream_version
            ):
                break
            kind = EconomicEventKind(row.event_kind)
            payload = CapitalCommandPayload.model_validate_json(
                row.payload_json
            )
            if kind is EconomicEventKind.TRADE_EXECUTED:
                gross_cents = 0
                side = ExecutionSide.ENTRY
                quantity = 0
                for leg in payload.legs:
                    if leg.asset_kind is EconomicAssetKind.CASH:
                        gross_cents = scaled_int(
                            leg.cash_amount, CENT_SCALE, "cash_amount"
                        )
                        side = (
                            ExecutionSide.ENTRY
                            if leg.direction is EconomicLegDirection.DEBIT
                            else ExecutionSide.EXIT
                        )
                    elif leg.asset_kind is EconomicAssetKind.SECURITY:
                        quantity = int(leg.quantity)
                facts.append(
                    LotEventFact(
                        event_id=row.economic_event_id,
                        stream_version=int(row.stream_version),
                        kind="TRADE",
                        side=side,
                        gross_cents=gross_cents,
                        quantity=quantity,
                    )
                )
                continue
            if (
                kind is EconomicEventKind.LATE_CORRECTION
                and payload.execution_revision is not None
                and payload.execution_revision.fact_kind
                is ExecutionRevisionFactKind.FILL
            ):
                fact = payload.execution_revision
                facts.append(
                    LotEventFact(
                        event_id=row.economic_event_id,
                        stream_version=int(row.stream_version),
                        kind="REVISION",
                        revision_kind=fact.revision_kind,
                        superseded_side=fact.side,
                        superseded_gross_cents=(
                            int(fact.superseded_gross_cents)
                            if fact.superseded_gross_cents is not None
                            else 0
                        ),
                        superseded_quantity=(
                            int(fact.superseded_quantity)
                            if fact.superseded_quantity is not None
                            else 0
                        ),
                        reversed_consumed_basis_cents=(
                            int(fact.reversed_consumed_basis_cents)
                            if fact.reversed_consumed_basis_cents is not None
                            else 0
                        ),
                        corrected_gross_cents=(
                            int(fact.corrected_gross_cents)
                            if fact.corrected_gross_cents is not None
                            else 0
                        ),
                        corrected_quantity=(
                            int(fact.corrected_quantity)
                            if fact.corrected_quantity is not None
                            else 0
                        ),
                        corrected_consumed_basis_cents=(
                            int(fact.corrected_consumed_basis_cents)
                            if fact.corrected_consumed_basis_cents is not None
                            else 0
                        ),
                    )
                )
        return tuple(facts)

    def _replayed_basis_consumed_by_exit(
        self,
        conn: sa.engine.Connection,
        position_lineage_id: str,
        economic_lot_id: str,
        exit_event_id: str,
    ) -> int:
        """Exact basis one exit event consumed, recomputed from history."""

        state = LotReplayState()
        for fact in self._lot_event_facts(
            conn, position_lineage_id, economic_lot_id
        ):
            replay_lot_fact(state, fact)
            if fact.event_id == exit_event_id:
                break
        assert state.consumed_basis_by_exit_event is not None
        return state.consumed_basis_by_exit_event.get(exit_event_id, 0)

    def _record_execution_bust_or_correction(
        self, request: ExecutionRevisionRequest
    ) -> tuple[ExecutionRevisionReceipt, CapitalRiskSnapshot]:
        def operation(
            context: GatewayTransactionContext,
        ) -> tuple[ExecutionRevisionReceipt, CapitalRiskSnapshot]:
            conn = context._connection
            binding = self._stored_binding(context)
            registry = context._table("execution_revisions")

            fill_rows = self._fill_registry_rows(conn, request.execution_id)
            if not fill_rows or int(fill_rows[0].revision) != 1:
                raise CapitalConflict(
                    "execution_unknown",
                    "execution revision references no recorded fill",
                    execution_id=request.execution_id,
                )
            newest_revision = int(fill_rows[-1].revision)
            if request.revision > newest_revision + 1:
                raise CapitalConflict(
                    "revision_sequence_conflict",
                    "execution revisions are monotonic and contiguous",
                    execution_id=request.execution_id,
                    active_revision=newest_revision,
                    requested_revision=request.revision,
                )

            original = self._original_fill_context(conn, fill_rows)
            if request.order_id != original["order_id"]:
                raise CapitalConflict(
                    "revision_content_conflict",
                    "revision order identity differs from the recorded fill",
                    execution_id=request.execution_id,
                )
            if request.side is not original["side"]:
                raise CapitalConflict(
                    "revision_content_conflict",
                    "revision side differs from the recorded fill",
                    execution_id=request.execution_id,
                )
            if request.security_id != original["security_id"]:
                raise CapitalConflict(
                    "revision_content_conflict",
                    "revision security differs from the recorded fill",
                    execution_id=request.execution_id,
                )
            lineage = original["position_lineage_id"]
            lot = original["economic_lot_id"]
            if (
                request.position_lineage_id is not None
                and (
                    request.position_lineage_id != lineage
                    or request.economic_lot_id != lot
                )
            ):
                raise CapitalConflict(
                    "revision_content_conflict",
                    "revision lot identity differs from the recorded fill",
                    execution_id=request.execution_id,
                )

            # The superseded fact is whatever revision request.revision-1
            # left active (the recorded fill, a correction, or nothing after
            # a bust).
            active = self._active_fill_fact(
                conn, fill_rows, original, before_revision=request.revision
            )
            if request.revision_kind is ExecutionRevisionKind.BUSTED:
                if active["side"] is None:
                    raise CapitalConflict(
                        "revision_active_fact_missing",
                        "the execution is already busted; there is no active"
                        " fact to remove",
                        execution_id=request.execution_id,
                    )
                # The bust must restate the active fact's quantity exactly;
                # verified after the registry idempotence check below, so a
                # divergent retry of a committed revision reports
                # payload_conflict rather than this restatement error.
            else:
                if active["side"] is None:
                    if request.superseded_quantity is not None:
                        raise CapitalConflict(
                            "revision_content_conflict",
                            "the active fact is busted; the correction"
                            " restates no superseded quantity",
                            execution_id=request.execution_id,
                        )

            # Corporate restructurings change the share language of the lot;
            # revising pre-restructuring fills is source-authorized
            # settlement territory and stays fail-closed here.
            original_stream = int(
                conn.execute(
                    sa.text(
                        "SELECT stream_version FROM economic_events"
                        " WHERE economic_event_id = :event_id"
                    ),
                    {"event_id": original["event_id"]},
                ).one().stream_version
            )
            restructured = conn.execute(
                sa.text(
                    "SELECT COUNT(*) AS n FROM economic_events"
                    " WHERE position_lineage_id = :lineage"
                    " AND economic_lot_id = :lot"
                    " AND stream_version > :stream_version"
                    " AND event_kind IN ('SPLIT', 'MERGE',"
                    " 'SECURITY_CONVERTED', 'SHARE_RECEIVABLE',"
                    " 'CORPORATE_CASH_SETTLED', 'LEGAL_WRITE_OFF')"
                ),
                {
                    "lineage": lineage,
                    "lot": lot,
                    "stream_version": original_stream,
                },
            ).one().n
            if int(restructured) > 0:
                raise CapitalConflict(
                    "revision_lot_restructured",
                    "the lot changed through a corporate action after this"
                    " fill; revisions of restructured lots stay fail-closed",
                    execution_id=request.execution_id,
                )
            position_row = context.position_row(lineage, lot)
            if position_row is not None and position_row.state == (
                PositionState.LEGAL_TERMINAL.value
            ):
                raise CapitalConflict(
                    "revision_lot_legal_terminal",
                    "legally derecognized lots are settled by legal facts,"
                    " not execution revisions",
                    execution_id=request.execution_id,
                )

            # Superseded contribution (the fact this revision removes).
            superseded_side = active["side"]
            # A correction after a bust supersedes nothing, but the
            # corrected fact still belongs to the recorded fill's side;
            # replay routing and the exit basis rule key off that side.
            effective_side = (
                superseded_side
                if superseded_side is not None
                else original["side"]
            )
            superseded_gross = int(active["gross_cents"])
            superseded_quantity = int(active["quantity"])
            reversed_consumed_basis: int | None = None
            if superseded_side is ExecutionSide.EXIT:
                reversed_consumed_basis = (
                    int(active["consumed_basis_cents"])
                    if active["consumed_basis_cents"] is not None
                    else self._replayed_basis_consumed_by_exit(
                        conn, lineage, lot, active["event_id"]
                    )
                )

            corrected_gross = 0
            if request.revision_kind is ExecutionRevisionKind.CORRECTED:
                corrected_gross = fill_gross_cents(
                    request.corrected_price_micros,
                    request.corrected_quantity,
                )
                if corrected_gross < 1:
                    raise CapitalConflict(
                        "fill_gross_rounds_to_zero",
                        "corrected notional rounds to zero cents under the"
                        " frozen policy",
                        price_micros=request.corrected_price_micros,
                        quantity=request.corrected_quantity,
                    )
                if (
                    superseded_side is not None
                    and superseded_quantity == request.corrected_quantity
                    and superseded_gross == corrected_gross
                ):
                    raise CapitalConflict(
                        "revision_changes_nothing",
                        "the corrected fact equals the active fact; no"
                        " economic fact changed",
                        execution_id=request.execution_id,
                    )

            # Replayed lot state around this revision: before, after the
            # reversal only (for the corrected exit's basis rule), and
            # after the whole fact.
            prior_state = LotReplayState()
            for fact in self._lot_event_facts(conn, lineage, lot):
                replay_lot_fact(prior_state, fact)
            quantity_before = prior_state.quantity
            basis_before = prior_state.basis_cents
            reversed_only = LotEventFact(
                event_id="",
                stream_version=0,
                kind="REVISION",
                revision_kind=ExecutionRevisionKind.BUSTED,
                superseded_side=superseded_side,
                superseded_gross_cents=superseded_gross,
                superseded_quantity=superseded_quantity,
                reversed_consumed_basis_cents=reversed_consumed_basis or 0,
            )
            reversed_state = LotReplayState(
                quantity=quantity_before,
                basis_cents=basis_before,
                consumed_basis_total_cents=prior_state.consumed_basis_total_cents,
            )
            if superseded_side is not None:
                replay_lot_fact(reversed_state, reversed_only)
            corrected_consumed_basis: int | None = None
            if (
                request.revision_kind is ExecutionRevisionKind.CORRECTED
                and effective_side is ExecutionSide.EXIT
            ):
                if request.corrected_quantity == reversed_state.quantity:
                    corrected_consumed_basis = reversed_state.basis_cents
                elif reversed_state.quantity > 0:
                    corrected_consumed_basis = round_half_even_div(
                        reversed_state.basis_cents
                        * request.corrected_quantity,
                        reversed_state.quantity,
                    )
                else:
                    corrected_consumed_basis = 0
                # Consumption is capped at the lot's available basis (see
                # replay_lot_fact): an oversized corrected exit exports the
                # excess shares as a preserved negative quantity.
                corrected_consumed_basis = min(
                    corrected_consumed_basis,
                    max(reversed_state.basis_cents, 0),
                )

            full_fact = LotEventFact(
                event_id="",
                stream_version=0,
                kind="REVISION",
                revision_kind=request.revision_kind,
                superseded_side=effective_side,
                superseded_gross_cents=superseded_gross,
                superseded_quantity=superseded_quantity,
                reversed_consumed_basis_cents=reversed_consumed_basis or 0,
                corrected_gross_cents=corrected_gross,
                corrected_quantity=(
                    request.corrected_quantity
                    if request.corrected_quantity is not None
                    else 0
                ),
                corrected_consumed_basis_cents=(
                    corrected_consumed_basis or 0
                ),
            )
            after_state = LotReplayState(
                quantity=quantity_before,
                basis_cents=basis_before,
                consumed_basis_total_cents=prior_state.consumed_basis_total_cents,
            )
            replay_lot_fact(after_state, full_fact)
            quantity_after = after_state.quantity
            basis_after = after_state.basis_cents
            reopened = quantity_before <= 0 < quantity_after
            impossible = quantity_after < 0 or basis_after < 0

            fact = ExecutionRevisionFact(
                fact_kind=ExecutionRevisionFactKind.FILL,
                revision_kind=request.revision_kind,
                execution_id=request.execution_id,
                revision=request.revision,
                order_id=request.order_id,
                side=original["side"],
                security_id=original["security_id"],
                position_lineage_id=lineage,
                economic_lot_id=lot,
                producer_namespace=original["producer_namespace"],
                research_program_id=original["research_program_id"],
                economic_lineage_id=original["economic_lineage_id"],
                stage_id=original["stage_id"],
                superseded_quantity=(
                    superseded_quantity if superseded_side is not None else None
                ),
                superseded_gross_cents=(
                    superseded_gross if superseded_side is not None else None
                ),
                reversed_consumed_basis_cents=reversed_consumed_basis,
                corrected_price_micros=request.corrected_price_micros,
                corrected_quantity=request.corrected_quantity,
                corrected_gross_cents=(
                    corrected_gross
                    if request.revision_kind
                    is ExecutionRevisionKind.CORRECTED
                    else None
                ),
                corrected_consumed_basis_cents=corrected_consumed_basis,
            )
            idempotency_key = fill_idempotency_key(
                request.execution_id, request.revision
            )
            payload = CapitalCommandPayload(
                event_kind=EconomicEventKind.LATE_CORRECTION,
                effective_at=request.effective_at,
                source_authority=request.source_authority,
                position_lineage_id=lineage,
                economic_lot_id=lot,
                correction_of_event_id=active["event_id"],
                legs=self._execution_revision_legs(
                    idempotency_key, fact
                ),
                producer_namespace=original["producer_namespace"],
                research_program_id=original["research_program_id"],
                economic_lineage_id=original["economic_lineage_id"],
                stage_id=original["stage_id"],
                execution_revision=fact,
            )
            payload_hash = payload.content_hash()

            existing_row = conn.execute(
                registry.select().where(
                    sa.and_(
                        registry.c.execution_id == request.execution_id,
                        registry.c.revision == request.revision,
                    )
                )
            ).first()
            if request.superseded_quantity is not None and (
                request.superseded_quantity != active["quantity"]
            ):
                # A divergent restatement of the active fact under this
                # revision identity: payload_conflict when the identity is
                # already committed (the committed revision restated the
                # active fact exactly), revision_content_conflict when new.
                raise CapitalConflict(
                    (
                        "payload_conflict"
                        if existing_row is not None
                        else "revision_content_conflict"
                    ),
                    "the revision restates a different superseded quantity"
                    " than the active fact",
                    execution_id=request.execution_id,
                    active_quantity=active["quantity"],
                    restated_quantity=request.superseded_quantity,
                )
            if existing_row is not None:
                expected_kind = registry_kind_for_fill_revision(
                    request.revision_kind
                )
                if existing_row.revision_kind != expected_kind:
                    raise CapitalConflict(
                        "revision_kind_conflict",
                        "execution revision identity reused by another fact"
                        " kind",
                        execution_id=request.execution_id,
                        revision=request.revision,
                    )
                if existing_row.payload_content_hash != payload_hash:
                    raise CapitalConflict(
                        "payload_conflict",
                        "execution revision already committed with different"
                        " content",
                        execution_id=request.execution_id,
                        revision=request.revision,
                    )
                snapshot = context.read_capital_risk_snapshot(request.as_of)
                receipt = ExecutionRevisionReceipt(
                    execution_id=request.execution_id,
                    order_id=request.order_id,
                    revision=request.revision,
                    revision_kind=request.revision_kind,
                    event_id=derive_event_id(idempotency_key),
                    superseded_event_id=active["event_id"],
                    side=original["side"],
                    security_id=original["security_id"],
                    position_lineage_id=lineage,
                    economic_lot_id=lot,
                    reversed_gross_cents=superseded_gross,
                    reversed_quantity=superseded_quantity,
                    reversed_consumed_basis_cents=reversed_consumed_basis,
                    applied_gross_cents=corrected_gross,
                    applied_quantity=(
                        request.corrected_quantity
                        if request.corrected_quantity is not None
                        else 0
                    ),
                    applied_consumed_basis_cents=corrected_consumed_basis,
                    reopened=reopened,
                    reconciliation_halted=impossible,
                    capital_version=snapshot.capital_version,
                    stream_version=context.current_stream_version(),
                )
                return receipt, snapshot

            command = CapitalCommand(
                idempotency_key=idempotency_key,
                account_binding=binding,
                expected_stream_version=request.expected_stream_version,
                as_of=request.as_of,
                payload=payload,
            )

            def register_revision(tx: GatewayTransactionContext) -> None:
                tx._connection.execute(
                    registry.insert().values(
                        execution_revision_id=idempotency_key,
                        execution_id=request.execution_id,
                        revision=request.revision,
                        revision_kind=registry_kind_for_fill_revision(
                            request.revision_kind
                        ),
                        order_id=request.order_id,
                        payload_content_hash=payload_hash,
                        recorded_at=utc_iso(request.as_of),
                    )
                )
                tx._connection.execute(
                    tx._table("event_revisions").insert().values(
                        canonical_event_id=active["event_id"],
                        revision_event_id=derive_event_id(idempotency_key),
                        revision_kind=EVENT_REVISION_LINK_KIND,
                        recorded_at=utc_iso(request.as_of),
                    )
                )

            snapshot = context.run_append(
                command,
                after_event_insert_hook=None,
                after_projection_hook=register_revision,
            )
            receipt = ExecutionRevisionReceipt(
                execution_id=request.execution_id,
                order_id=request.order_id,
                revision=request.revision,
                revision_kind=request.revision_kind,
                event_id=derive_event_id(idempotency_key),
                superseded_event_id=active["event_id"],
                side=original["side"],
                security_id=original["security_id"],
                position_lineage_id=lineage,
                economic_lot_id=lot,
                reversed_gross_cents=superseded_gross,
                reversed_quantity=superseded_quantity,
                reversed_consumed_basis_cents=reversed_consumed_basis,
                applied_gross_cents=corrected_gross,
                applied_quantity=(
                    request.corrected_quantity
                    if request.corrected_quantity is not None
                    else 0
                ),
                applied_consumed_basis_cents=corrected_consumed_basis,
                reopened=reopened,
                reconciliation_halted=impossible,
                capital_version=snapshot.capital_version,
                stream_version=context.current_stream_version(),
            )
            return receipt, snapshot

        return self._run_write_transaction(operation)

    def _execution_revision_legs(
        self, idempotency_key: str, fact: ExecutionRevisionFact
    ) -> tuple[EconomicEventLeg, ...]:
        """Exact reversal (and corrected) legs for one revision fact.

        Cash amounts reuse the recorded gross cents, so a busted fill
        reverses its cash and security legs exactly — rounding residue
        included — and fee revision legs carry the signed booked deltas.
        """

        return execution_revision_legs(idempotency_key, fact)

    def record_fee_revision(
        self, request: FeeRevisionRequest
    ) -> tuple[FeeRevisionReceipt, CapitalRiskSnapshot]:
        """Record one fee revision linked to its fill as a DISTINCT event.

        The charge is engine-computed from the versioned fee policy and the
        order's fill history: commission base / stamp tax / transfer fee are
        each rounded half-even, and the per-order minimum commission is
        charged exactly once across partial fills.

        Higher revisions (Plan 02 Task 6) follow a busted/corrected fill:
        they recompute the order's fee target from the active fill facts
        and book the signed delta against what the order's fee streams
        have actually charged.
        """

        if request.revision != 1:
            return self._record_fee_bust_or_correction(request)

        def operation(
            context: GatewayTransactionContext,
        ) -> tuple[FeeRevisionReceipt, CapitalRiskSnapshot]:
            conn = context._connection
            binding = self._stored_binding(context)
            registry = context._table("execution_revisions")

            fill_row = conn.execute(
                registry.select().where(
                    sa.and_(
                        registry.c.execution_id == request.fill_execution_id,
                        registry.c.revision == 1,
                        registry.c.revision_kind == "FILL",
                    )
                )
            ).first()
            if fill_row is None:
                raise CapitalConflict(
                    "fill_unknown",
                    "fee revision references no recorded fill",
                    fill_execution_id=request.fill_execution_id,
                )
            order_id = fill_row.order_id

            fill_event_row = conn.execute(
                sa.text(
                    "SELECT canonical_event_json FROM economic_events"
                    " WHERE payload_content_hash = :hash"
                ),
                {"hash": fill_row.payload_content_hash},
            ).first()
            if fill_event_row is None:
                raise CapitalConflict(
                    "conservation_violation",
                    "fill registry row lost its canonical event",
                    fill_execution_id=request.fill_execution_id,
                )
            notional_cents, side = _fill_fact_from_event_json(
                fill_event_row.canonical_event_json
            )

            fee_exec_id = fee_execution_id(request.fill_execution_id)
            fee_row = conn.execute(
                sa.text(
                    "SELECT rowid AS fee_rowid, payload_content_hash"
                    " FROM execution_revisions"
                    " WHERE execution_id = :execution_id AND revision = :revision"
                ),
                {"execution_id": fee_exec_id, "revision": request.revision},
            ).first()
            # Deterministic charge window: fills recorded before this fee
            # revision row (all fills on the first pass, the same frozen set
            # on idempotent retries).
            cutoff = fee_row.fee_rowid if fee_row is not None else None
            base_now, charged_before = _order_commission_state(
                conn, order_id, cutoff, request.fee_policy
            )
            components = compute_fee_components(
                notional_cents, side, request.fee_policy
            )
            # Per-order minimum commission: cumulative owed commission is
            # max(minimum, cumulative base); charge the delta against what
            # earlier fee revisions of this order actually charged.
            commission_cents = max(
                0,
                max(request.fee_policy.min_commission_cents, base_now)
                - charged_before,
            )
            total_cents = (
                commission_cents
                + components.stamp_tax_cents
                + components.transfer_fee_cents
            )

            idempotency_key = fee_idempotency_key(
                request.fill_execution_id, request.revision
            )
            if total_cents > 0:
                payload = _fee_payload(request, idempotency_key, (
                    ("commission", commission_cents),
                    ("stamp_tax", components.stamp_tax_cents),
                    ("transfer_fee", components.transfer_fee_cents),
                ))
                expected_hash = payload.content_hash()
            else:
                payload = None
                expected_hash = _zero_fee_receipt_hash(request)

            if fee_row is not None:
                if fee_row.payload_content_hash != expected_hash:
                    raise CapitalConflict(
                        "payload_conflict",
                        "fee revision already committed with different content",
                        fill_execution_id=request.fill_execution_id,
                        revision=request.revision,
                    )
                snapshot = context.read_capital_risk_snapshot(request.as_of)
                if total_cents > 0:
                    event_row = conn.execute(
                        sa.text(
                            "SELECT stream_version FROM economic_events"
                            " WHERE idempotency_key = :key"
                        ),
                        {"key": idempotency_key},
                    ).one()
                    stream_version = int(event_row.stream_version)
                else:
                    stream_version = context.current_stream_version()
                receipt = FeeRevisionReceipt(
                    fill_execution_id=request.fill_execution_id,
                    order_id=order_id,
                    revision=request.revision,
                    revision_kind=FeeRevisionKind.INITIAL,
                    event_id=(
                        derive_event_id(idempotency_key)
                        if total_cents > 0
                        else None
                    ),
                    fee_policy_version=request.fee_policy.fee_policy_version,
                    commission_cents=commission_cents,
                    stamp_tax_cents=components.stamp_tax_cents,
                    transfer_fee_cents=components.transfer_fee_cents,
                    total_cents=total_cents,
                    booked_delta_cents=total_cents,
                    capital_version=snapshot.capital_version,
                    stream_version=stream_version,
                )
                return receipt, snapshot

            if payload is None:
                # Zero charge: the registry records the fee fact, but no
                # capital changed, so no event and a quiet capital version.
                conn.execute(
                    registry.insert().values(
                        execution_revision_id=idempotency_key,
                        execution_id=fee_exec_id,
                        revision=request.revision,
                        revision_kind="FEE",
                        order_id=order_id,
                        payload_content_hash=expected_hash,
                        recorded_at=utc_iso(request.as_of),
                    )
                )
                snapshot = context.read_capital_risk_snapshot(request.as_of)
                receipt = FeeRevisionReceipt(
                    fill_execution_id=request.fill_execution_id,
                    order_id=order_id,
                    revision=request.revision,
                    revision_kind=FeeRevisionKind.INITIAL,
                    event_id=None,
                    fee_policy_version=request.fee_policy.fee_policy_version,
                    commission_cents=0,
                    stamp_tax_cents=0,
                    transfer_fee_cents=0,
                    total_cents=0,
                    booked_delta_cents=0,
                    capital_version=snapshot.capital_version,
                    stream_version=context.current_stream_version(),
                )
                return receipt, snapshot

            command = CapitalCommand(
                idempotency_key=idempotency_key,
                account_binding=binding,
                expected_stream_version=request.expected_stream_version,
                as_of=request.as_of,
                payload=payload,
            )

            def register_revision(tx: GatewayTransactionContext) -> None:
                tx._connection.execute(
                    registry.insert().values(
                        execution_revision_id=idempotency_key,
                        execution_id=fee_exec_id,
                        revision=request.revision,
                        revision_kind="FEE",
                        order_id=order_id,
                        payload_content_hash=expected_hash,
                        recorded_at=utc_iso(request.as_of),
                    )
                )

            snapshot = context.run_append(
                command,
                after_event_insert_hook=None,
                after_projection_hook=register_revision,
            )
            receipt = FeeRevisionReceipt(
                fill_execution_id=request.fill_execution_id,
                order_id=order_id,
                revision=request.revision,
                revision_kind=FeeRevisionKind.INITIAL,
                event_id=derive_event_id(idempotency_key),
                fee_policy_version=request.fee_policy.fee_policy_version,
                commission_cents=commission_cents,
                stamp_tax_cents=components.stamp_tax_cents,
                transfer_fee_cents=components.transfer_fee_cents,
                total_cents=total_cents,
                booked_delta_cents=total_cents,
                capital_version=snapshot.capital_version,
                stream_version=context.current_stream_version(),
            )
            return receipt, snapshot

        return self._run_write_transaction(operation)

    def _record_fee_bust_or_correction(
        self, request: FeeRevisionRequest
    ) -> tuple[FeeRevisionReceipt, CapitalRiskSnapshot]:
        """Fee revisions follow fill revisions (Plan 02 Task 6).

        A fee bust/correction is accepted only after the linked fill has
        been busted/corrected. It recomputes the order's fee target from
        the active fill facts under the request's policy and books the
        signed per-component delta against what the order's fee streams
        actually charged: a LATE_CORRECTION event when the delta is
        nonzero, a registry-only fact when the target is unchanged.
        """

        def operation(
            context: GatewayTransactionContext,
        ) -> tuple[FeeRevisionReceipt, CapitalRiskSnapshot]:
            conn = context._connection
            binding = self._stored_binding(context)
            registry = context._table("execution_revisions")

            fill_rows = self._fill_registry_rows(
                conn, request.fill_execution_id
            )
            if not fill_rows or int(fill_rows[0].revision) != 1:
                raise CapitalConflict(
                    "fill_unknown",
                    "fee revision references no recorded fill",
                    fill_execution_id=request.fill_execution_id,
                )
            newest_fill_row = fill_rows[-1]
            expected_fill_kind = (
                FILL_BUST_KIND
                if request.revision_kind is FeeRevisionKind.BUSTED
                else FILL_CORRECTION_KIND
            )
            if (
                int(newest_fill_row.revision) == 1
                or newest_fill_row.revision_kind != expected_fill_kind
            ):
                raise CapitalConflict(
                    "fee_revision_requires_fill_revision",
                    "fee revisions follow fill revisions: the linked fill"
                    " must already carry the matching bust/correction",
                    fill_execution_id=request.fill_execution_id,
                    fill_revision_kind=newest_fill_row.revision_kind,
                    requested_fee_kind=request.revision_kind.value,
                )
            order_id = newest_fill_row.order_id

            fee_exec_id = fee_execution_id(request.fill_execution_id)
            fee_rows = tuple(
                conn.execute(
                    registry.select()
                    .where(
                        sa.and_(
                            registry.c.execution_id == fee_exec_id,
                            registry.c.revision_kind.in_(
                                tuple(sorted(FEE_REVISION_KINDS))
                            ),
                        )
                    )
                    .order_by(registry.c.revision)
                ).all()
            )
            if not fee_rows:
                raise CapitalConflict(
                    "revision_sequence_conflict",
                    "fee revisions supersede the initial fee charge",
                    fill_execution_id=request.fill_execution_id,
                )
            newest_fee_revision = int(fee_rows[-1].revision)
            if request.revision > newest_fee_revision + 1:
                raise CapitalConflict(
                    "revision_sequence_conflict",
                    "fee revisions are monotonic and contiguous",
                    fill_execution_id=request.fill_execution_id,
                    active_revision=newest_fee_revision,
                    requested_revision=request.revision,
                )

            fee_row = conn.execute(
                sa.text(
                    "SELECT rowid AS fee_rowid, payload_content_hash,"
                    " revision_kind FROM execution_revisions"
                    " WHERE execution_id = :execution_id"
                    " AND revision = :revision"
                ),
                {
                    "execution_id": fee_exec_id,
                    "revision": request.revision,
                },
            ).first()
            cutoff = fee_row.fee_rowid if fee_row is not None else None
            (
                base_now,
                stamp_owed,
                transfer_owed,
                commission_charged,
                stamp_charged,
                transfer_charged,
                active_fill_count,
            ) = _order_fee_state(conn, order_id, cutoff, request.fee_policy)
            # The per-order minimum commission applies while the order
            # holds an active fill; a fully busted order owes nothing
            # (minimum included), so the bust refunds every component.
            if active_fill_count > 0:
                commission_target = max(
                    request.fee_policy.min_commission_cents, base_now
                )
            else:
                commission_target = 0
            commission_delta = commission_target - commission_charged
            stamp_delta = stamp_owed - stamp_charged
            transfer_delta = transfer_owed - transfer_charged
            total_delta = commission_delta + stamp_delta + transfer_delta
            target_total = commission_target + stamp_owed + transfer_owed

            idempotency_key = fee_idempotency_key(
                request.fill_execution_id, request.revision
            )
            # The superseded fee fact is the previous revision's event when
            # it exists (zero-charge revisions record no event).
            prior_row = next(
                (
                    row
                    for row in fee_rows
                    if int(row.revision) == request.revision - 1
                ),
                None,
            )
            prior_event_id: str | None = None
            if prior_row is not None:
                prior_event_row = conn.execute(
                    sa.text(
                        "SELECT economic_event_id FROM economic_events"
                        " WHERE payload_content_hash = :hash"
                    ),
                    {"hash": prior_row.payload_content_hash},
                ).first()
                if prior_event_row is not None:
                    prior_event_id = prior_event_row.economic_event_id

            if total_delta != 0:
                fact = ExecutionRevisionFact(
                    fact_kind=ExecutionRevisionFactKind.FEE,
                    revision_kind=(
                        ExecutionRevisionKind.BUSTED
                        if request.revision_kind is FeeRevisionKind.BUSTED
                        else ExecutionRevisionKind.CORRECTED
                    ),
                    execution_id=fee_exec_id,
                    revision=request.revision,
                    order_id=order_id,
                    fee_commission_delta_cents=commission_delta,
                    fee_stamp_tax_delta_cents=stamp_delta,
                    fee_transfer_fee_delta_cents=transfer_delta,
                )
                payload = CapitalCommandPayload(
                    event_kind=EconomicEventKind.LATE_CORRECTION,
                    effective_at=request.effective_at,
                    source_authority=request.source_authority,
                    correction_of_event_id=prior_event_id,
                    legs=self._execution_revision_legs(
                        idempotency_key, fact
                    ),
                    execution_revision=fact,
                )
                expected_hash = payload.content_hash()
            else:
                payload = None
                expected_hash = _zero_fee_receipt_hash(request)

            registry_kind = registry_kind_for_fee_revision(
                request.revision_kind
            )

            def build_receipt(
                snapshot: CapitalRiskSnapshot,
                event_id: str | None,
                stream_version: int,
            ) -> FeeRevisionReceipt:
                return FeeRevisionReceipt(
                    fill_execution_id=request.fill_execution_id,
                    order_id=order_id,
                    revision=request.revision,
                    revision_kind=request.revision_kind,
                    event_id=event_id,
                    fee_policy_version=(
                        request.fee_policy.fee_policy_version
                    ),
                    commission_cents=commission_target,
                    stamp_tax_cents=stamp_owed,
                    transfer_fee_cents=transfer_owed,
                    total_cents=target_total,
                    booked_delta_cents=total_delta,
                    capital_version=snapshot.capital_version,
                    stream_version=stream_version,
                )

            if fee_row is not None:
                if fee_row.revision_kind != registry_kind:
                    raise CapitalConflict(
                        "revision_kind_conflict",
                        "fee revision identity reused by another fact kind",
                        fill_execution_id=request.fill_execution_id,
                        revision=request.revision,
                    )
                if fee_row.payload_content_hash != expected_hash:
                    raise CapitalConflict(
                        "payload_conflict",
                        "fee revision already committed with different"
                        " content",
                        fill_execution_id=request.fill_execution_id,
                        revision=request.revision,
                    )
                snapshot = context.read_capital_risk_snapshot(request.as_of)
                if total_delta != 0:
                    event_row = conn.execute(
                        sa.text(
                            "SELECT stream_version FROM economic_events"
                            " WHERE idempotency_key = :key"
                        ),
                        {"key": idempotency_key},
                    ).one()
                    stream_version = int(event_row.stream_version)
                    event_id = derive_event_id(idempotency_key)
                else:
                    stream_version = context.current_stream_version()
                    event_id = None
                return build_receipt(snapshot, event_id, stream_version), snapshot

            if payload is None:
                # Zero delta: the registry records the fee fact, but no
                # capital changed, so no event and a quiet capital version.
                conn.execute(
                    registry.insert().values(
                        execution_revision_id=idempotency_key,
                        execution_id=fee_exec_id,
                        revision=request.revision,
                        revision_kind=registry_kind,
                        order_id=order_id,
                        payload_content_hash=expected_hash,
                        recorded_at=utc_iso(request.as_of),
                    )
                )
                snapshot = context.read_capital_risk_snapshot(request.as_of)
                return (
                    build_receipt(
                        snapshot, None, context.current_stream_version()
                    ),
                    snapshot,
                )

            command = CapitalCommand(
                idempotency_key=idempotency_key,
                account_binding=binding,
                expected_stream_version=request.expected_stream_version,
                as_of=request.as_of,
                payload=payload,
            )

            def register_revision(tx: GatewayTransactionContext) -> None:
                tx._connection.execute(
                    registry.insert().values(
                        execution_revision_id=idempotency_key,
                        execution_id=fee_exec_id,
                        revision=request.revision,
                        revision_kind=registry_kind,
                        order_id=order_id,
                        payload_content_hash=expected_hash,
                        recorded_at=utc_iso(request.as_of),
                    )
                )
                if prior_event_id is not None:
                    tx._connection.execute(
                        tx._table("event_revisions").insert().values(
                            canonical_event_id=prior_event_id,
                            revision_event_id=derive_event_id(
                                idempotency_key
                            ),
                            revision_kind=EVENT_REVISION_LINK_KIND,
                            recorded_at=utc_iso(request.as_of),
                        )
                    )

            snapshot = context.run_append(
                command,
                after_event_insert_hook=None,
                after_projection_hook=register_revision,
            )
            return (
                build_receipt(
                    snapshot,
                    derive_event_id(idempotency_key),
                    context.current_stream_version(),
                ),
                snapshot,
            )

        return self._run_write_transaction(operation)

    def assert_conservation(self) -> ConservationReport:
        """Recompute every projection from history; fail loudly on drift."""

        with self._engine.connect() as conn:
            with conn.begin():
                return verify_conservation(conn, self._metadata)

    # -- Plan 02 Task 3: genesis units, external flows, NAV lifecycle ---------

    def lifecycle_state(self) -> LifecycleState:
        """The typed account lifecycle state of the bound ledger."""

        with self._engine.connect() as conn:
            row = conn.execute(
                sa.text("SELECT lifecycle_state FROM capital_projection")
            ).first()
        if row is None:
            raise CapitalConflict(
                "account_not_bound",
                "no AccountCapitalTruth is bound to this ledger",
            )
        return LifecycleState(row.lifecycle_state)

    def flow_version(self) -> int:
        """The current financing flow stream version (CAS anchor)."""

        with self._engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT COALESCE(MAX(flow_version), 0) AS v"
                    " FROM capital_flow_events"
                )
            ).one()
        return int(row.v)

    def flow_request_state(self, request_id: str) -> FlowRequestState:
        with self._engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT state FROM flow_requests WHERE flow_request_id = :id"
                ),
                {"id": request_id},
            ).first()
        if row is None:
            raise CapitalConflict(
                "flow_request_unknown",
                "no flow request exists for this identity",
                request_id=request_id,
            )
        return FlowRequestState(row.state)

    def risk_epoch_history(self) -> tuple[RiskEpochRecord, ...]:
        """The durable monotonic risk-epoch chain (append-only)."""

        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT * FROM risk_epoch_history ORDER BY risk_epoch"
                )
            ).all()
        return tuple(
            RiskEpochRecord(
                risk_epoch=int(row.risk_epoch),
                predecessor_risk_epoch=int(row.predecessor_risk_epoch),
                audited_nav_cents=int(row.audited_nav_cents),
                active_epoch_baseline_nav_cents=int(
                    row.active_epoch_baseline_nav_cents
                ),
                lifetime_high_water_mark_cents=int(
                    row.lifetime_high_water_mark_cents
                ),
                source_authority=row.source_authority,
                authorization_reference=row.authorization_reference,
                started_at=parse_utc(row.started_at),
            )
            for row in rows
        )

    def nav_projections(self) -> NavProjectionPath:
        """Both preserved NAV series: as-observed and restated-final."""

        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.text("SELECT * FROM nav_observations ORDER BY rowid")
            ).all()

        def observation(row: Any) -> NavObservation:
            return NavObservation(
                nav_observation_id=row.nav_observation_id,
                observation_kind=ObservationKind(row.observation_kind),
                supersedes_observation_id=row.supersedes_observation_id,
                as_of=parse_utc(row.as_of),
                capital_version=int(row.capital_version),
                created_by_event_id=row.created_by_event_id,
                nav_cents=int(row.nav_cents),
                issued_unit_quanta=int(row.issued_unit_quanta),
                live_unit_quanta=int(row.live_unit_quanta),
                unit_price_numerator=row.unit_price_numerator,
                unit_price_denominator=row.unit_price_denominator,
                log_growth_kind=LogGrowthKind(row.log_growth_kind),
                log_growth_nav_numerator=row.log_growth_nav_numerator,
                log_growth_nav_denominator=row.log_growth_nav_denominator,
            )

        as_observed = tuple(
            observation(row)
            for row in rows
            if row.observation_kind == ObservationKind.AS_OBSERVED.value
        )
        restated_final = tuple(
            observation(row)
            for row in rows
            if row.observation_kind == ObservationKind.RESTATED_FINAL.value
        )
        return NavProjectionPath(
            as_observed=as_observed, restated_final=restated_final
        )

    def initialize_genesis(
        self, request: GenesisRequest
    ) -> tuple[GenesisReceipt, CapitalRiskSnapshot]:
        """The one-time atomic genesis issuance of explicit units.

        Fails closed when any economic or financing history already exists,
        when the frozen genesis price does not divide to exact integer cents,
        or when the account left the ACTIVE state. Retries with the identical
        payload converge on the committed genesis fact.
        """

        def operation(
            context: GatewayTransactionContext,
        ) -> tuple[GenesisReceipt, CapitalRiskSnapshot]:
            conn = context._connection
            context.require_account_binding(request.account_binding, request.as_of)
            context.require_lifecycle(frozenset({LifecycleState.ACTIVE}))

            payload = {
                "flow_kind": FlowKind.GENESIS.value,
                "idempotency_key": request.idempotency_key,
                "unit_quanta": request.unit_quanta,
                "unit_price_numerator": request.unit_price_numerator,
                "unit_price_denominator": request.unit_price_denominator,
                "source_authority": request.source_authority,
                "authorization_reference": request.authorization_reference,
                "effective_at": utc_iso(request.effective_at),
            }
            payload_hash = content_hash(payload)
            existing = context.require_flow_payload_idempotent(
                request.idempotency_key, payload_hash
            )
            if existing is not None:
                observation_row = context.observation_row_for_event(
                    ObservationKind.AS_OBSERVED, existing.flow_event_id
                )
                projection = context.projection_row()
                receipt = GenesisReceipt(
                    flow_event_id=existing.flow_event_id,
                    observation_id=observation_row.nav_observation_id,
                    cash_amount_cents=int(existing.cash_amount_cents),
                    unit_quanta=int(existing.issued_unit_quanta),
                    unit_price_numerator=int(existing.unit_price_numerator),
                    unit_price_denominator=int(existing.unit_price_denominator),
                    capital_version=int(projection.capital_version),
                    flow_version=int(existing.flow_version),
                )
                return receipt, context.read_capital_risk_snapshot(request.as_of)

            # One-time genesis: no economic history, no flow history, and a
            # zeroed projection are all required.
            event_count = int(
                conn.execute(
                    sa.text("SELECT COUNT(*) AS n FROM economic_events")
                ).scalar()
            )
            projection = context.projection_row()
            history_exists = (
                context.current_flow_version() > 0
                or event_count > 0
                or int(projection.available_cash_cents) != 0
                or int(projection.issued_unit_quanta) != 0
            )
            if history_exists:
                raise CapitalConflict(
                    "genesis_already_committed",
                    "genesis is one-time: economic or flow history already"
                    " exists for this account",
                )

            cash_cents = genesis_cash_cents(
                request.unit_quanta,
                request.unit_price_numerator,
                request.unit_price_denominator,
            )
            if cash_cents is None or cash_cents <= 0:
                raise CapitalConflict(
                    "genesis_price_not_exact_cents",
                    "the frozen genesis price must divide to exact integer"
                    " cents; genesis never rounds",
                    unit_quanta=request.unit_quanta,
                    unit_price_numerator=request.unit_price_numerator,
                    unit_price_denominator=request.unit_price_denominator,
                )

            flow_event_id, flow_version = context.insert_flow_event(
                idempotency_key=request.idempotency_key,
                flow_kind=FlowKind.GENESIS,
                portfolio_id=request.account_binding.portfolio_id,
                request_id=None,
                source_authority=request.source_authority,
                effective_at=request.effective_at,
                recorded_at=request.as_of,
                payload=payload,
                cash_amount_cents=cash_cents,
                issued_unit_quanta=request.unit_quanta,
                unit_price_numerator=request.unit_price_numerator,
                unit_price_denominator=request.unit_price_denominator,
            )
            new_version = context.bump_projection(
                flow_event_id,
                request.as_of,
                available_cash_cents=cash_cents,
                issued_unit_quanta=request.unit_quanta,
                as_observed_nav_cents=cash_cents,
                lifetime_high_water_mark_cents=cash_cents,
                active_epoch_high_water_mark_cents=cash_cents,
            )
            observation_id = context.insert_nav_observation(
                event_id=flow_event_id,
                kind=ObservationKind.AS_OBSERVED,
                supersedes_observation_id=None,
                as_of=request.effective_at,
                recorded_at=request.as_of,
                capital_version=new_version,
                nav_cents=cash_cents,
                prior_nav_cents=None,
            )
            # Genesis establishes risk epoch 1 as the chain predecessor.
            conn.execute(
                context._table("risk_epoch_history").insert().values(
                    risk_epoch=1,
                    portfolio_id=request.account_binding.portfolio_id,
                    idempotency_key=f"{request.idempotency_key}:risk_epoch:1",
                    predecessor_risk_epoch=0,
                    audited_nav_cents=cash_cents,
                    active_epoch_baseline_nav_cents=cash_cents,
                    lifetime_high_water_mark_cents=cash_cents,
                    source_authority=request.source_authority,
                    authorization_reference=request.authorization_reference,
                    started_at=utc_iso(request.as_of),
                )
            )
            snapshot = context.read_capital_risk_snapshot(request.as_of)
            receipt = GenesisReceipt(
                flow_event_id=flow_event_id,
                observation_id=observation_id,
                cash_amount_cents=cash_cents,
                unit_quanta=request.unit_quanta,
                unit_price_numerator=request.unit_price_numerator,
                unit_price_denominator=request.unit_price_denominator,
                capital_version=new_version,
                flow_version=flow_version,
            )
            return receipt, snapshot

        return self._run_write_transaction(operation)

    def request_subscription(
        self, request: SubscriptionRequest
    ) -> tuple[SubscriptionReceipt, CapitalRiskSnapshot]:
        """Receive subscription cash as restricted suspense with an equal
        ``subscription_payable``: net equity and units stay unchanged until
        pricing settles the flow (flow-before-price ordering)."""

        def operation(
            context: GatewayTransactionContext,
        ) -> tuple[SubscriptionReceipt, CapitalRiskSnapshot]:
            conn = context._connection
            binding = self._stored_binding(context)
            context.require_lifecycle(frozenset({LifecycleState.ACTIVE}))

            idempotency_key = f"sub:{request.request_id}:received"
            payload = {
                "flow_kind": FlowKind.SUBSCRIPTION_RECEIVED.value,
                "request_id": request.request_id,
                "cash_amount_cents": request.cash_amount_cents,
                "source_authority": request.source_authority,
                "effective_at": utc_iso(request.effective_at),
            }
            existing = context.require_flow_payload_idempotent(
                idempotency_key, content_hash(payload)
            )
            if existing is not None:
                projection = context.projection_row()
                receipt = SubscriptionReceipt(
                    request_id=request.request_id,
                    flow_event_id=existing.flow_event_id,
                    cash_amount_cents=int(existing.cash_amount_cents),
                    payable_id=existing.payable_id,
                    capital_version=int(projection.capital_version),
                    flow_version=int(existing.flow_version),
                )
                return receipt, context.read_capital_risk_snapshot(request.as_of)

            context.require_flow_version(request.expected_flow_version)
            if context.flow_request_row(request.request_id) is not None:
                raise CapitalConflict(
                    "flow_request_conflict",
                    "flow request identity already in use",
                    request_id=request.request_id,
                )

            now = utc_iso(request.as_of)
            payable_id = f"pay:{idempotency_key}"
            conn.execute(
                context._table("flow_requests").insert().values(
                    flow_request_id=request.request_id,
                    flow_kind=FlowRequestKind.SUBSCRIPTION.value,
                    state=FlowRequestState.RECEIVED.value,
                    cash_amount_cents=request.cash_amount_cents,
                    unit_quanta=None,
                    issued_unit_quanta=None,
                    unit_price_numerator=None,
                    unit_price_denominator=None,
                    v_pre_cents=None,
                    units_pre_quanta=None,
                    frozen_capital_version=None,
                    payable_id=payable_id,
                    source_authority=request.source_authority,
                    created_at=now,
                    updated_at=now,
                )
            )
            conn.execute(
                context._table("payables").insert().values(
                    payable_id=payable_id,
                    payable_kind=SUBSCRIPTION_PAYABLE,
                    amount_cents=request.cash_amount_cents,
                    state=PayableState.OPEN.value,
                    created_at=now,
                    created_by_event_id=None,
                )
            )
            flow_event_id, flow_version = context.insert_flow_event(
                idempotency_key=idempotency_key,
                flow_kind=FlowKind.SUBSCRIPTION_RECEIVED,
                portfolio_id=binding.portfolio_id,
                request_id=request.request_id,
                source_authority=request.source_authority,
                effective_at=request.effective_at,
                recorded_at=request.as_of,
                payload=payload,
                cash_amount_cents=request.cash_amount_cents,
                payable_id=payable_id,
            )
            projection = context.projection_row()
            new_version = context.bump_projection(
                flow_event_id,
                request.as_of,
                subscription_suspense_cash_cents=(
                    int(projection.subscription_suspense_cash_cents)
                    + request.cash_amount_cents
                ),
            )
            snapshot = context.read_capital_risk_snapshot(request.as_of)
            receipt = SubscriptionReceipt(
                request_id=request.request_id,
                flow_event_id=flow_event_id,
                cash_amount_cents=request.cash_amount_cents,
                payable_id=payable_id,
                capital_version=new_version,
                flow_version=flow_version,
            )
            return receipt, snapshot

        return self._run_write_transaction(operation)

    def _price_flow(
        self,
        context: GatewayTransactionContext,
        request: FlowPriceRequest,
        flow_kind: FlowRequestKind,
    ) -> FlowPriceReceipt:
        """Shared flow-before-price freeze for subscriptions and redemptions.

        V_pre excludes the caller's own subscription suspense cash; every
        open position must be marked and the live unit denominator must be
        nonempty before any price may be frozen.
        """

        row = context.flow_request_row(request.request_id)
        if row is None or row.flow_kind != flow_kind.value:
            raise CapitalConflict(
                "flow_request_unknown",
                "no matching flow request exists for this identity",
                request_id=request.request_id,
            )
        priced_states = {
            FlowRequestState.RECEIVED.value,
            FlowRequestState.REQUESTED.value,
            FlowRequestState.PRICED.value,
        }
        if row.state not in priced_states:
            raise CapitalConflict(
                "flow_request_state_conflict",
                f"flow request state {row.state} cannot be priced",
                request_id=request.request_id,
                state=row.state,
            )
        # An unsettled subscription's suspense cash and payable already net
        # to zero in equity, so no exclusion is needed for either kind.
        v_pre, units_pre = context.require_pricing_inputs()
        price = Fraction(v_pre, units_pre)
        if flow_kind is FlowRequestKind.REDEMPTION:
            cash_amount_cents = round_half_even_div(
                int(row.unit_quanta) * v_pre, units_pre
            )
        else:
            cash_amount_cents = int(row.cash_amount_cents)
        projection = context.projection_row()
        context._connection.execute(
            context._table("flow_requests").update()
            .where(
                context._table("flow_requests").c.flow_request_id
                == request.request_id
            )
            .values(
                state=FlowRequestState.PRICED.value,
                cash_amount_cents=cash_amount_cents,
                unit_price_numerator=price.numerator,
                unit_price_denominator=price.denominator,
                v_pre_cents=v_pre,
                units_pre_quanta=units_pre,
                frozen_capital_version=int(projection.capital_version),
                updated_at=utc_iso(request.as_of),
            )
        )
        return FlowPriceReceipt(
            request_id=request.request_id,
            v_pre_cents=v_pre,
            units_pre_quanta=units_pre,
            unit_price_numerator=price.numerator,
            unit_price_denominator=price.denominator,
            cash_amount_cents=cash_amount_cents,
            frozen_capital_version=int(projection.capital_version),
        )

    def price_subscription(self, request: FlowPriceRequest) -> FlowPriceReceipt:
        """Freeze V_pre and the issue price for one subscription request.

        Pricing changes no capital fact, so the capital version stays quiet;
        settle must still verify the freeze is fresh.
        """

        def operation(context: GatewayTransactionContext) -> FlowPriceReceipt:
            self._stored_binding(context)
            context.require_lifecycle(frozenset({LifecycleState.ACTIVE}))
            return self._price_flow(
                context, request, FlowRequestKind.SUBSCRIPTION
            )

        return self._run_write_transaction(operation)

    def price_redemption(self, request: FlowPriceRequest) -> FlowPriceReceipt:
        """Freeze the unit price and payout for one redemption request."""

        def operation(context: GatewayTransactionContext) -> FlowPriceReceipt:
            self._stored_binding(context)
            context.require_lifecycle(
                frozenset({LifecycleState.ACTIVE, LifecycleState.INSOLVENT})
            )
            return self._price_flow(
                context, request, FlowRequestKind.REDEMPTION
            )

        return self._run_write_transaction(operation)

    def _subscription_pricing(
        self, context: GatewayTransactionContext, row: Any, cash_cents: int
    ) -> tuple[int, int, int, int, int]:
        """Resolve (price_num, price_den, v_pre, units_pre, units_issued)
        for one subscription settle, honoring a fresh frozen price or pricing
        atomically in-transaction."""

        projection = context.projection_row()
        if row.state == FlowRequestState.PRICED.value:
            if int(row.frozen_capital_version) != int(
                projection.capital_version
            ):
                raise CapitalConflict(
                    "flow_price_stale",
                    "the frozen flow price is stale; reprice before settling",
                    frozen_capital_version=int(row.frozen_capital_version),
                    capital_version=int(projection.capital_version),
                )
            price_numerator = int(row.unit_price_numerator)
            price_denominator = int(row.unit_price_denominator)
            v_pre = int(row.v_pre_cents)
            units_pre = int(row.units_pre_quanta)
        else:
            v_pre, units_pre = context.require_pricing_inputs()
            price = Fraction(v_pre, units_pre)
            price_numerator = price.numerator
            price_denominator = price.denominator
        units_issued = (cash_cents * units_pre) // v_pre
        if units_issued <= 0:
            raise CapitalConflict(
                "subscription_below_unit_price",
                "the subscription cash cannot buy one unit quanta at the"
                " pre-flow price",
                cash_amount_cents=cash_cents,
            )
        return price_numerator, price_denominator, v_pre, units_pre, units_issued

    def settle_subscription(
        self, request: FlowSettleRequest
    ) -> tuple[FlowSettleReceipt, CapitalRiskSnapshot]:
        """Issue units at the pre-flow price, release suspense, and clear
        the subscription payable in one capital transaction.

        Unit quanta are never over-issued: the exact-integer floor of the
        pre-flow price is issued and any residual cents are refunded
        immediately (the rounding direction is frozen policy).
        """

        def operation(
            context: GatewayTransactionContext,
        ) -> tuple[FlowSettleReceipt, CapitalRiskSnapshot]:
            conn = context._connection
            binding = self._stored_binding(context)
            context.require_lifecycle(frozenset({LifecycleState.ACTIVE}))

            row = context.flow_request_row(request.request_id)
            if row is None or row.flow_kind != FlowRequestKind.SUBSCRIPTION.value:
                raise CapitalConflict(
                    "flow_request_unknown",
                    "no subscription request exists for this identity",
                    request_id=request.request_id,
                )
            idempotency_key = f"sub:{request.request_id}:settled"
            if row.state in (
                FlowRequestState.SETTLED.value,
                FlowRequestState.CANCELLED.value,
                FlowRequestState.PAID.value,
            ):
                if row.state != FlowRequestState.SETTLED.value:
                    raise CapitalConflict(
                        "flow_request_state_conflict",
                        "flow request already reached a terminal state",
                        request_id=request.request_id,
                        state=row.state,
                    )
                existing = context.existing_flow_event(idempotency_key)
                projection = context.projection_row()
                receipt = FlowSettleReceipt(
                    request_id=request.request_id,
                    flow_event_id=existing.flow_event_id,
                    issued_unit_quanta=int(existing.issued_unit_quanta),
                    refund_cents=int(existing.refund_cents or 0),
                    unit_price_numerator=int(existing.unit_price_numerator),
                    unit_price_denominator=int(existing.unit_price_denominator),
                    payable_id=None,
                    lifecycle_state=LifecycleState(projection.lifecycle_state),
                    capital_version=int(projection.capital_version),
                    flow_version=int(existing.flow_version),
                )
                return receipt, context.read_capital_risk_snapshot(request.as_of)
            cash_cents = int(row.cash_amount_cents)
            (
                price_numerator,
                price_denominator,
                v_pre,
                units_pre,
                units_issued,
            ) = self._subscription_pricing(context, row, cash_cents)
            consumed_cents = round_half_even_div(
                units_issued * v_pre, units_pre
            )
            refund_cents = cash_cents - consumed_cents

            payload = {
                "flow_kind": FlowKind.SUBSCRIPTION_SETTLED.value,
                "request_id": request.request_id,
                "consumed_cents": consumed_cents,
                "refund_cents": refund_cents,
                "issued_unit_quanta": units_issued,
                "unit_price_numerator": price_numerator,
                "unit_price_denominator": price_denominator,
                "payable_id": row.payable_id,
                "source_authority": request.source_authority,
            }
            existing = context.require_flow_payload_idempotent(
                idempotency_key, content_hash(payload)
            )
            if existing is not None:
                projection = context.projection_row()
                receipt = FlowSettleReceipt(
                    request_id=request.request_id,
                    flow_event_id=existing.flow_event_id,
                    issued_unit_quanta=int(existing.issued_unit_quanta),
                    refund_cents=int(existing.refund_cents or 0),
                    unit_price_numerator=int(existing.unit_price_numerator),
                    unit_price_denominator=int(existing.unit_price_denominator),
                    payable_id=None,
                    lifecycle_state=LifecycleState(projection.lifecycle_state),
                    capital_version=int(projection.capital_version),
                    flow_version=int(existing.flow_version),
                )
                return receipt, context.read_capital_risk_snapshot(request.as_of)

            context.require_flow_version(request.expected_flow_version)
            projection = context.projection_row()
            new_available = int(projection.available_cash_cents) + consumed_cents
            new_subscription_suspense = (
                int(projection.subscription_suspense_cash_cents) - cash_cents
            )
            # NAV is set to the exact post-fact equity; both water marks
            # shift by the net external cents and never fall below NAV, so a
            # deposit at the pre-flow price creates no performance and no
            # drawdown. The payable is still OPEN in the tables here, so the
            # delta must be applied before the row is settled below.
            nav_new = context.equity_after_projection(
                available_cash_cents=new_available,
                restricted_cash_cents=int(projection.restricted_cash_cents),
                unsettled_cash_cents=int(projection.unsettled_cash_cents),
                subscription_suspense_cash_cents=new_subscription_suspense,
                redemption_suspense_cash_cents=int(
                    projection.redemption_suspense_cash_cents
                ),
                payable_delta_cents=-cash_cents,
            )
            lifetime_new = max(
                int(projection.lifetime_high_water_mark_cents) + consumed_cents,
                nav_new,
            )
            active_new = max(
                int(projection.active_epoch_high_water_mark_cents)
                + consumed_cents,
                nav_new,
            )
            conn.execute(
                context._table("payables").update()
                .where(context._table("payables").c.payable_id == row.payable_id)
                .values(state=PayableState.SETTLED.value)
            )
            flow_event_id, flow_version = context.insert_flow_event(
                idempotency_key=idempotency_key,
                flow_kind=FlowKind.SUBSCRIPTION_SETTLED,
                portfolio_id=binding.portfolio_id,
                request_id=request.request_id,
                source_authority=request.source_authority,
                effective_at=request.as_of,
                recorded_at=request.as_of,
                payload=payload,
                cash_amount_cents=consumed_cents,
                refund_cents=refund_cents,
                issued_unit_quanta=units_issued,
                unit_price_numerator=price_numerator,
                unit_price_denominator=price_denominator,
                payable_id=row.payable_id,
            )
            conn.execute(
                context._table("flow_requests").update()
                .where(
                    context._table("flow_requests").c.flow_request_id
                    == request.request_id
                )
                .values(
                    state=FlowRequestState.SETTLED.value,
                    issued_unit_quanta=units_issued,
                    unit_price_numerator=price_numerator,
                    unit_price_denominator=price_denominator,
                    updated_at=utc_iso(request.as_of),
                )
            )
            new_version = context.bump_projection(
                flow_event_id,
                request.as_of,
                available_cash_cents=new_available,
                subscription_suspense_cash_cents=new_subscription_suspense,
                issued_unit_quanta=(
                    int(projection.issued_unit_quanta) + units_issued
                ),
                as_observed_nav_cents=nav_new,
                lifetime_high_water_mark_cents=lifetime_new,
                active_epoch_high_water_mark_cents=active_new,
            )
            snapshot = context.read_capital_risk_snapshot(request.as_of)
            receipt = FlowSettleReceipt(
                request_id=request.request_id,
                flow_event_id=flow_event_id,
                issued_unit_quanta=units_issued,
                refund_cents=refund_cents,
                unit_price_numerator=price_numerator,
                unit_price_denominator=price_denominator,
                payable_id=None,
                lifecycle_state=LifecycleState.ACTIVE,
                capital_version=new_version,
                flow_version=flow_version,
            )
            return receipt, snapshot

        return self._run_write_transaction(operation)

    def cancel_subscription(
        self, request: FlowCancelRequest
    ) -> CapitalRiskSnapshot:
        """Cancel an unsettled subscription: refund the suspense cash and
        clear the payable. Blocked once units exist (terminal obligation)."""

        def operation(
            context: GatewayTransactionContext,
        ) -> CapitalRiskSnapshot:
            conn = context._connection
            binding = self._stored_binding(context)
            context.require_lifecycle(frozenset({LifecycleState.ACTIVE}))

            row = context.flow_request_row(request.request_id)
            if row is None or row.flow_kind != FlowRequestKind.SUBSCRIPTION.value:
                raise CapitalConflict(
                    "flow_request_unknown",
                    "no subscription request exists for this identity",
                    request_id=request.request_id,
                )
            if row.state == FlowRequestState.CANCELLED.value:
                return context.read_capital_risk_snapshot(request.as_of)
            if row.state not in (
                FlowRequestState.RECEIVED.value,
                FlowRequestState.PRICED.value,
            ):
                raise CapitalConflict(
                    "flow_cancel_blocked_terminal_obligations",
                    "units were issued for this subscription; cancellation"
                    " cannot erase existing obligations",
                    request_id=request.request_id,
                    state=row.state,
                )

            idempotency_key = f"sub:{request.request_id}:cancelled"
            refund_cents = int(row.cash_amount_cents)
            payload = {
                "flow_kind": FlowKind.SUBSCRIPTION_CANCELLED.value,
                "request_id": request.request_id,
                "refund_cents": refund_cents,
                "payable_id": row.payable_id,
                "source_authority": request.source_authority,
            }
            existing = context.require_flow_payload_idempotent(
                idempotency_key, content_hash(payload)
            )
            if existing is None:
                context.require_flow_version(request.expected_flow_version)
                conn.execute(
                    context._table("payables").update()
                    .where(
                        context._table("payables").c.payable_id
                        == row.payable_id
                    )
                    .values(state=PayableState.SETTLED.value)
                )
                flow_event_id, _ = context.insert_flow_event(
                    idempotency_key=idempotency_key,
                    flow_kind=FlowKind.SUBSCRIPTION_CANCELLED,
                    portfolio_id=binding.portfolio_id,
                    request_id=request.request_id,
                    source_authority=request.source_authority,
                    effective_at=request.as_of,
                    recorded_at=request.as_of,
                    payload=payload,
                    cash_amount_cents=refund_cents,
                    refund_cents=refund_cents,
                    payable_id=row.payable_id,
                )
                conn.execute(
                    context._table("flow_requests").update()
                    .where(
                        context._table("flow_requests").c.flow_request_id
                        == request.request_id
                    )
                    .values(
                        state=FlowRequestState.CANCELLED.value,
                        updated_at=utc_iso(request.as_of),
                    )
                )
                projection = context.projection_row()
                context.bump_projection(
                    flow_event_id,
                    request.as_of,
                    subscription_suspense_cash_cents=(
                        int(projection.subscription_suspense_cash_cents)
                        - refund_cents
                    ),
                )
            return context.read_capital_risk_snapshot(request.as_of)

        return self._run_write_transaction(operation)

    def request_redemption(
        self, request: RedemptionRequest
    ) -> RedemptionRequestReceipt:
        """Record an off-ledger memo redemption reserve.

        Before reliable pricing a redemption request confirms no payable,
        cancels no unit, and changes no NAV/HWM/drawdown; cancelling the
        memo has no return impact either. The capital version stays quiet.
        """

        def operation(
            context: GatewayTransactionContext,
        ) -> RedemptionRequestReceipt:
            conn = context._connection
            self._stored_binding(context)
            context.require_lifecycle(
                frozenset({LifecycleState.ACTIVE, LifecycleState.INSOLVENT})
            )
            row = context.flow_request_row(request.request_id)
            if row is not None:
                if (
                    row.flow_kind == FlowRequestKind.REDEMPTION.value
                    and int(row.unit_quanta or 0) == request.unit_quanta
                    and row.state == FlowRequestState.REQUESTED.value
                ):
                    return RedemptionRequestReceipt(
                        request_id=request.request_id,
                        unit_quanta=request.unit_quanta,
                    )
                raise CapitalConflict(
                    "flow_request_conflict",
                    "flow request identity already in use",
                    request_id=request.request_id,
                )
            now = utc_iso(request.as_of)
            conn.execute(
                context._table("flow_requests").insert().values(
                    flow_request_id=request.request_id,
                    flow_kind=FlowRequestKind.REDEMPTION.value,
                    state=FlowRequestState.REQUESTED.value,
                    cash_amount_cents=None,
                    unit_quanta=request.unit_quanta,
                    issued_unit_quanta=None,
                    unit_price_numerator=None,
                    unit_price_denominator=None,
                    v_pre_cents=None,
                    units_pre_quanta=None,
                    frozen_capital_version=None,
                    payable_id=None,
                    source_authority=request.source_authority,
                    created_at=now,
                    updated_at=now,
                )
            )
            return RedemptionRequestReceipt(
                request_id=request.request_id,
                unit_quanta=request.unit_quanta,
            )

        return self._run_write_transaction(operation)

    def settle_redemption(
        self, request: FlowSettleRequest
    ) -> tuple[FlowSettleReceipt, CapitalRiskSnapshot]:
        """Settle one redemption at the pre-flow NAV.

        Partial redemption cancels the units immediately and reserves the
        payout cash against a confirmed ``redemption_payable``. Full
        redemption converts every live unit into ``pending_redeemed_units``
        and enters settle-only ``TERMINATING``; the pending units are only
        burnt once payment and every other obligation are zero.
        """

        def operation(
            context: GatewayTransactionContext,
        ) -> tuple[FlowSettleReceipt, CapitalRiskSnapshot]:
            conn = context._connection
            binding = self._stored_binding(context)
            state = context.require_lifecycle(
                frozenset({LifecycleState.ACTIVE, LifecycleState.INSOLVENT})
            )

            row = context.flow_request_row(request.request_id)
            if row is None or row.flow_kind != FlowRequestKind.REDEMPTION.value:
                raise CapitalConflict(
                    "flow_request_unknown",
                    "no redemption request exists for this identity",
                    request_id=request.request_id,
                )
            idempotency_key = f"red:{request.request_id}:settled"
            if row.state in (
                FlowRequestState.SETTLED.value,
                FlowRequestState.PAID.value,
            ):
                existing = context.existing_flow_event(idempotency_key)
                projection = context.projection_row()
                receipt = FlowSettleReceipt(
                    request_id=request.request_id,
                    flow_event_id=existing.flow_event_id,
                    cancelled_unit_quanta=int(
                        existing.cancelled_unit_quanta or 0
                    ),
                    pending_unit_quanta=int(existing.pending_unit_quanta or 0),
                    unit_price_numerator=int(existing.unit_price_numerator),
                    unit_price_denominator=int(existing.unit_price_denominator),
                    payable_id=existing.payable_id,
                    lifecycle_state=LifecycleState(projection.lifecycle_state),
                    capital_version=int(projection.capital_version),
                    flow_version=int(existing.flow_version),
                )
                return receipt, context.read_capital_risk_snapshot(request.as_of)
            if row.state not in (
                FlowRequestState.REQUESTED.value,
                FlowRequestState.PRICED.value,
            ):
                raise CapitalConflict(
                    "flow_request_state_conflict",
                    f"flow request state {row.state} cannot be settled",
                    request_id=request.request_id,
                    state=row.state,
                )

            projection = context.projection_row()
            if row.state == FlowRequestState.PRICED.value:
                if int(row.frozen_capital_version) != int(
                    projection.capital_version
                ):
                    raise CapitalConflict(
                        "flow_price_stale",
                        "the frozen flow price is stale; reprice before"
                        " settling",
                        frozen_capital_version=int(
                            row.frozen_capital_version
                        ),
                        capital_version=int(projection.capital_version),
                    )
                price_numerator = int(row.unit_price_numerator)
                price_denominator = int(row.unit_price_denominator)
                v_pre = int(row.v_pre_cents)
                units_pre = int(row.units_pre_quanta)
            else:
                v_pre, units_pre = context.require_pricing_inputs()
                price = Fraction(v_pre, units_pre)
                price_numerator = price.numerator
                price_denominator = price.denominator

            units = int(row.unit_quanta)
            if units > units_pre:
                raise CapitalConflict(
                    "redemption_exceeds_live_units",
                    "redemption requests cannot exceed the live unit count",
                    requested_unit_quanta=units,
                    live_unit_quanta=units_pre,
                )
            payout_cents = round_half_even_div(units * v_pre, units_pre)
            full_redemption = units == units_pre

            if full_redemption:
                # A full redemption requires a liquid portfolio: with open
                # positions, receivables, reserves, or unsettled cash the
                # frozen payout could outrun the assets before liquidation,
                # and pending units must never be erased before obligations
                # settle.
                if (
                    context.open_position_rows()
                    or context.outstanding_receivable_cents() > 0
                    or int(projection.restricted_cash_cents) != 0
                    or int(projection.unsettled_cash_cents) != 0
                ):
                    raise CapitalConflict(
                        "full_redemption_requires_liquid_portfolio",
                        "full redemption requires positions, receivables,"
                        " reserves, and unsettled cash to be settled first",
                        request_id=request.request_id,
                    )
            else:
                if int(projection.available_cash_cents) < payout_cents:
                    raise CapitalConflict(
                        "insufficient_available_cash",
                        "partial redemption payout exceeds available cash",
                        available_cash_cents=int(
                            projection.available_cash_cents
                        ),
                        payout_cents=payout_cents,
                    )

            payable_id = f"pay:{idempotency_key}"
            payload = {
                "flow_kind": FlowKind.REDEMPTION_SETTLED.value,
                "request_id": request.request_id,
                "payout_cents": payout_cents,
                "cancelled_unit_quanta": 0 if full_redemption else units,
                "pending_unit_quanta": units if full_redemption else 0,
                "full_redemption": full_redemption,
                "unit_price_numerator": price_numerator,
                "unit_price_denominator": price_denominator,
                "payable_id": payable_id,
                "source_authority": request.source_authority,
            }
            existing = context.require_flow_payload_idempotent(
                idempotency_key, content_hash(payload)
            )
            if existing is not None:
                projection = context.projection_row()
                receipt = FlowSettleReceipt(
                    request_id=request.request_id,
                    flow_event_id=existing.flow_event_id,
                    cancelled_unit_quanta=int(
                        existing.cancelled_unit_quanta or 0
                    ),
                    pending_unit_quanta=int(existing.pending_unit_quanta or 0),
                    unit_price_numerator=int(existing.unit_price_numerator),
                    unit_price_denominator=int(existing.unit_price_denominator),
                    payable_id=existing.payable_id,
                    lifecycle_state=LifecycleState(projection.lifecycle_state),
                    capital_version=int(projection.capital_version),
                    flow_version=int(existing.flow_version),
                )
                return receipt, context.read_capital_risk_snapshot(request.as_of)

            context.require_flow_version(request.expected_flow_version)
            now = utc_iso(request.as_of)
            reserved_cents = (
                min(int(projection.available_cash_cents), payout_cents)
                if full_redemption
                else payout_cents
            )
            updates: dict[str, Any] = {
                "available_cash_cents": (
                    int(projection.available_cash_cents) - reserved_cents
                ),
                "redemption_suspense_cash_cents": (
                    int(projection.redemption_suspense_cash_cents)
                    + reserved_cents
                ),
            }
            new_lifecycle = state
            if full_redemption:
                updates["pending_redeemed_unit_quanta"] = (
                    int(projection.pending_redeemed_unit_quanta) + units
                )
                new_lifecycle = LifecycleState.TERMINATING
                updates["lifecycle_state"] = new_lifecycle.value
            else:
                updates["issued_unit_quanta"] = (
                    int(projection.issued_unit_quanta) - units
                )
            # Confirming the redemption payable converts that much equity
            # into a liability: NAV drops by the payout, while the water
            # marks shift by zero external cents (no cash left the account
            # yet) and never fall below NAV. The payable row is inserted
            # after this computation so the delta applies to the pre-fact
            # table state.
            nav_new = context.equity_after_projection(
                available_cash_cents=int(updates["available_cash_cents"]),
                restricted_cash_cents=int(projection.restricted_cash_cents),
                unsettled_cash_cents=int(projection.unsettled_cash_cents),
                subscription_suspense_cash_cents=int(
                    projection.subscription_suspense_cash_cents
                ),
                redemption_suspense_cash_cents=int(
                    updates["redemption_suspense_cash_cents"]
                ),
                payable_delta_cents=payout_cents,
            )
            updates["as_observed_nav_cents"] = nav_new
            updates["lifetime_high_water_mark_cents"] = max(
                int(projection.lifetime_high_water_mark_cents), nav_new
            )
            updates["active_epoch_high_water_mark_cents"] = max(
                int(projection.active_epoch_high_water_mark_cents), nav_new
            )
            conn.execute(
                context._table("payables").insert().values(
                    payable_id=payable_id,
                    payable_kind=REDEMPTION_PAYABLE,
                    amount_cents=payout_cents,
                    state=PayableState.OPEN.value,
                    created_at=now,
                    created_by_event_id=None,
                )
            )
            flow_event_id, flow_version = context.insert_flow_event(
                idempotency_key=idempotency_key,
                flow_kind=FlowKind.REDEMPTION_SETTLED,
                portfolio_id=binding.portfolio_id,
                request_id=request.request_id,
                source_authority=request.source_authority,
                effective_at=request.as_of,
                recorded_at=request.as_of,
                payload=payload,
                cash_amount_cents=payout_cents,
                reserved_cents=reserved_cents,
                cancelled_unit_quanta=0 if full_redemption else units,
                pending_unit_quanta=units if full_redemption else 0,
                unit_price_numerator=price_numerator,
                unit_price_denominator=price_denominator,
                payable_id=payable_id,
            )
            conn.execute(
                context._table("flow_requests").update()
                .where(
                    context._table("flow_requests").c.flow_request_id
                    == request.request_id
                )
                .values(
                    state=FlowRequestState.SETTLED.value,
                    cash_amount_cents=payout_cents,
                    unit_price_numerator=price_numerator,
                    unit_price_denominator=price_denominator,
                    v_pre_cents=v_pre,
                    units_pre_quanta=units_pre,
                    payable_id=payable_id,
                    updated_at=now,
                )
            )
            new_version = context.bump_projection(
                flow_event_id, request.as_of, **updates
            )
            snapshot = context.read_capital_risk_snapshot(request.as_of)
            receipt = FlowSettleReceipt(
                request_id=request.request_id,
                flow_event_id=flow_event_id,
                cancelled_unit_quanta=0 if full_redemption else units,
                pending_unit_quanta=units if full_redemption else 0,
                unit_price_numerator=price_numerator,
                unit_price_denominator=price_denominator,
                payable_id=payable_id,
                lifecycle_state=new_lifecycle,
                capital_version=new_version,
                flow_version=flow_version,
            )
            return receipt, snapshot

        return self._run_write_transaction(operation)

    def cancel_redemption(
        self, request: FlowCancelRequest
    ) -> CapitalRiskSnapshot:
        """Cancel a memo redemption reserve (quiet; no return impact).

        Once the redemption settled, the confirmed payable is a terminal
        obligation and cancellation fails closed.
        """

        def operation(
            context: GatewayTransactionContext,
        ) -> CapitalRiskSnapshot:
            conn = context._connection
            self._stored_binding(context)
            row = context.flow_request_row(request.request_id)
            if row is None or row.flow_kind != FlowRequestKind.REDEMPTION.value:
                raise CapitalConflict(
                    "flow_request_unknown",
                    "no redemption request exists for this identity",
                    request_id=request.request_id,
                )
            if row.state == FlowRequestState.CANCELLED.value:
                return context.read_capital_risk_snapshot(request.as_of)
            if row.state not in (
                FlowRequestState.REQUESTED.value,
                FlowRequestState.PRICED.value,
            ):
                raise CapitalConflict(
                    "flow_cancel_blocked_terminal_obligations",
                    "the redemption payable is a terminal obligation and"
                    " cannot be cancelled",
                    request_id=request.request_id,
                    state=row.state,
                )
            conn.execute(
                context._table("flow_requests").update()
                .where(
                    context._table("flow_requests").c.flow_request_id
                    == request.request_id
                )
                .values(
                    state=FlowRequestState.CANCELLED.value,
                    updated_at=utc_iso(request.as_of),
                )
            )
            return context.read_capital_risk_snapshot(request.as_of)

        return self._run_write_transaction(operation)

    def _obligations_remaining(self, context: GatewayTransactionContext) -> bool:
        """True while any asset, liability, reserve, or unit obligation
        remains on the books (the TERMINATED gate)."""

        projection = context.projection_row()
        if (
            int(projection.available_cash_cents) != 0
            or int(projection.restricted_cash_cents) != 0
            or int(projection.unsettled_cash_cents) != 0
            or int(projection.subscription_suspense_cash_cents) != 0
            or int(projection.redemption_suspense_cash_cents) != 0
            or int(projection.issued_unit_quanta) != 0
            or int(projection.pending_redeemed_unit_quanta) != 0
        ):
            return True
        if context.open_position_rows():
            return True
        if context.outstanding_receivable_cents() != 0:
            return True
        if context.open_payable_cents() != 0:
            return True
        reserve_count = int(
            context._connection.execute(
                sa.text(
                    "SELECT COUNT(*) AS n FROM reserves"
                    " WHERE state IN ('LIVE', 'CANCEL_PENDING')"
                )
            ).scalar()
        )
        return reserve_count > 0

    def pay_redemption(
        self, request: RedemptionPaymentRequest
    ) -> tuple[RedemptionPaymentReceipt, CapitalRiskSnapshot]:
        """Pay (part of) a settled redemption payable.

        Payment consumes ring-fenced suspense cash first, then available
        cash. Pending redeemed units burn only when the payable and every
        other obligation reach zero; full redemption therefore cannot erase
        units before liabilities, receivables, and positions settle.
        """

        def operation(
            context: GatewayTransactionContext,
        ) -> tuple[RedemptionPaymentReceipt, CapitalRiskSnapshot]:
            conn = context._connection
            binding = self._stored_binding(context)
            state = context.require_lifecycle(
                frozenset(
                    {
                        LifecycleState.ACTIVE,
                        LifecycleState.TERMINATING,
                        LifecycleState.INSOLVENT,
                    }
                )
            )

            row = context.flow_request_row(request.request_id)
            if row is None or row.flow_kind != FlowRequestKind.REDEMPTION.value:
                raise CapitalConflict(
                    "flow_request_unknown",
                    "no redemption request exists for this identity",
                    request_id=request.request_id,
                )
            idempotency_key = f"red:{request.request_id}:paid"
            if row.state == FlowRequestState.PAID.value:
                existing = context.existing_flow_event(idempotency_key)
                projection = context.projection_row()
                receipt = RedemptionPaymentReceipt(
                    request_id=request.request_id,
                    flow_event_id=existing.flow_event_id,
                    cash_amount_cents=int(existing.cash_amount_cents),
                    burnt_unit_quanta=int(existing.burnt_unit_quanta or 0),
                    remaining_payable_cents=0,
                    lifecycle_state=LifecycleState(projection.lifecycle_state),
                    capital_version=int(projection.capital_version),
                    flow_version=int(existing.flow_version),
                )
                return receipt, context.read_capital_risk_snapshot(request.as_of)
            if row.state != FlowRequestState.SETTLED.value:
                raise CapitalConflict(
                    "flow_request_state_conflict",
                    f"flow request state {row.state} cannot be paid",
                    request_id=request.request_id,
                    state=row.state,
                )

            projection = context.projection_row()
            payable_table = context._table("payables")
            payable_row = conn.execute(
                payable_table.select().where(
                    payable_table.c.payable_id == row.payable_id
                )
            ).one()
            remaining_before = int(payable_row.amount_cents)
            accessible = (
                int(projection.available_cash_cents)
                + int(projection.redemption_suspense_cash_cents)
            )
            payment_cents = min(remaining_before, accessible)
            if payment_cents <= 0:
                raise CapitalConflict(
                    "no_payable_cash_available",
                    "no cash is available to pay the redemption payable",
                    request_id=request.request_id,
                    remaining_payable_cents=remaining_before,
                )
            from_suspense = min(
                int(projection.redemption_suspense_cash_cents), payment_cents
            )
            from_available = payment_cents - from_suspense
            remaining_after = remaining_before - payment_cents

            payload = {
                "flow_kind": FlowKind.REDEMPTION_PAID.value,
                "request_id": request.request_id,
                "payment_cents": payment_cents,
                "from_suspense_cents": from_suspense,
                "payable_id": row.payable_id,
                "source_authority": request.source_authority,
            }
            existing = context.require_flow_payload_idempotent(
                idempotency_key, content_hash(payload)
            )
            if existing is not None:
                projection = context.projection_row()
                receipt = RedemptionPaymentReceipt(
                    request_id=request.request_id,
                    flow_event_id=existing.flow_event_id,
                    cash_amount_cents=int(existing.cash_amount_cents),
                    burnt_unit_quanta=int(existing.burnt_unit_quanta or 0),
                    remaining_payable_cents=remaining_after,
                    lifecycle_state=LifecycleState(projection.lifecycle_state),
                    capital_version=int(projection.capital_version),
                    flow_version=int(existing.flow_version),
                )
                return receipt, context.read_capital_risk_snapshot(request.as_of)

            context.require_flow_version(request.expected_flow_version)

            updates: dict[str, Any] = {
                "available_cash_cents": (
                    int(projection.available_cash_cents) - from_available
                ),
                "redemption_suspense_cash_cents": (
                    int(projection.redemption_suspense_cash_cents)
                    - from_suspense
                ),
            }
            burnt_units = 0
            pending = int(projection.pending_redeemed_unit_quanta)

            # Payment discharges the liability one-for-one with assets, so
            # equity is unchanged; the external outflow shifts both water
            # marks down by the paid cents (never below NAV), keeping a
            # redemption at price free of fabricated return or drawdown.
            # The payable row still carries its pre-payment state here, so
            # the delta is applied before the row updates below.
            nav_new = context.equity_after_projection(
                available_cash_cents=int(updates["available_cash_cents"]),
                restricted_cash_cents=int(projection.restricted_cash_cents),
                unsettled_cash_cents=int(projection.unsettled_cash_cents),
                subscription_suspense_cash_cents=int(
                    projection.subscription_suspense_cash_cents
                ),
                redemption_suspense_cash_cents=int(
                    updates["redemption_suspense_cash_cents"]
                ),
                payable_delta_cents=-payment_cents,
            )
            updates["as_observed_nav_cents"] = nav_new
            updates["lifetime_high_water_mark_cents"] = max(
                int(projection.lifetime_high_water_mark_cents) - payment_cents,
                nav_new,
            )
            updates["active_epoch_high_water_mark_cents"] = max(
                int(projection.active_epoch_high_water_mark_cents)
                - payment_cents,
                nav_new,
            )

            # Persist the payable/request state: the burn decision below
            # must see the payable already settled.
            if remaining_after == 0:
                conn.execute(
                    payable_table.update()
                    .where(payable_table.c.payable_id == row.payable_id)
                    .values(
                        state=PayableState.SETTLED.value,
                        amount_cents=0,
                    )
                )
                conn.execute(
                    context._table("flow_requests").update()
                    .where(
                        context._table("flow_requests").c.flow_request_id
                        == request.request_id
                    )
                    .values(
                        state=FlowRequestState.PAID.value,
                        updated_at=utc_iso(request.as_of),
                    )
                )
            else:
                conn.execute(
                    payable_table.update()
                    .where(payable_table.c.payable_id == row.payable_id)
                    .values(amount_cents=remaining_after)
                )

            if remaining_after == 0 and pending > 0:
                if not self._obligations_remaining(
                    context, overrides=updates, include_units=False
                ):
                    # Burn the pending units only now that the payable and
                    # every other obligation are zero.
                    burnt_units = pending
                    updates["issued_unit_quanta"] = (
                        int(projection.issued_unit_quanta) - pending
                    )
                    updates["pending_redeemed_unit_quanta"] = 0

            new_lifecycle = state
            if state is LifecycleState.TERMINATING and not (
                self._obligations_remaining(context, overrides=updates)
            ):
                # Authorized full redemption with every obligation zero:
                # TERMINATED (this is not insolvency).
                new_lifecycle = LifecycleState.TERMINATED
                updates["lifecycle_state"] = new_lifecycle.value

            flow_event_id, flow_version = context.insert_flow_event(
                idempotency_key=idempotency_key,
                flow_kind=FlowKind.REDEMPTION_PAID,
                portfolio_id=binding.portfolio_id,
                request_id=request.request_id,
                source_authority=request.source_authority,
                effective_at=request.as_of,
                recorded_at=request.as_of,
                payload=payload,
                cash_amount_cents=payment_cents,
                burnt_unit_quanta=burnt_units or None,
                payable_id=row.payable_id,
            )
            new_version = context.bump_projection(
                flow_event_id, request.as_of, **updates
            )

            snapshot = context.read_capital_risk_snapshot(request.as_of)
            receipt = RedemptionPaymentReceipt(
                request_id=request.request_id,
                flow_event_id=flow_event_id,
                cash_amount_cents=payment_cents,
                burnt_unit_quanta=burnt_units,
                remaining_payable_cents=remaining_after,
                lifecycle_state=new_lifecycle,
                capital_version=new_version,
                flow_version=flow_version,
            )
            return receipt, snapshot

        return self._run_write_transaction(operation)

    def _obligations_remaining(
        self,
        context: GatewayTransactionContext,
        overrides: dict[str, Any] | None = None,
        *,
        include_units: bool = True,
    ) -> bool:
        """True while any asset, liability, reserve, or unit obligation
        remains on the books (the burn/TERMINATED gate).

        ``overrides`` carries the in-flight projection values of the
        enclosing transaction so the check observes the post-fact state.
        """

        overrides = overrides or {}
        projection = context.projection_row()
        cash_values = (
            overrides.get(
                "available_cash_cents", projection.available_cash_cents
            ),
            overrides.get(
                "restricted_cash_cents", projection.restricted_cash_cents
            ),
            overrides.get(
                "unsettled_cash_cents", projection.unsettled_cash_cents
            ),
            overrides.get(
                "subscription_suspense_cash_cents",
                projection.subscription_suspense_cash_cents,
            ),
            overrides.get(
                "redemption_suspense_cash_cents",
                projection.redemption_suspense_cash_cents,
            ),
        )
        if any(int(value) != 0 for value in cash_values):
            return True
        if include_units:
            issued = overrides.get(
                "issued_unit_quanta", projection.issued_unit_quanta
            )
            pending = overrides.get(
                "pending_redeemed_unit_quanta",
                projection.pending_redeemed_unit_quanta,
            )
            if int(issued) != 0 or int(pending) != 0:
                return True
        if context.open_position_rows():
            return True
        if context.outstanding_receivable_cents() != 0:
            return True
        if context.open_payable_cents() != 0:
            return True
        reserve_count = int(
            context._connection.execute(
                sa.text(
                    "SELECT COUNT(*) AS n FROM reserves"
                    " WHERE state IN ('LIVE', 'CANCEL_PENDING')"
                )
            ).scalar()
        )
        return reserve_count > 0

    def close_valuation(
        self, request: ValuationRequest
    ) -> tuple[ValuationReceipt, CapitalRiskSnapshot]:
        """Append one close valuation: a mark-only VALUATION event plus the
        confirmed as-observed NAV observation, water marks, and lifecycle
        (NAV <= 0 sets INSOLVENT).

        A valuation of a fully liquid portfolio carries no mark legs; the
        economic event contract requires at least one leg, so such a NAV
        confirmation lands as an event-less projection fact anchored by a
        deterministic observation identity (the same pattern Task 2 uses
        for zero-charge fee revisions).
        """

        def operation(
            context: GatewayTransactionContext,
        ) -> tuple[ValuationReceipt, CapitalRiskSnapshot]:
            binding = self._stored_binding(context)
            context.require_lifecycle(
                frozenset(
                    {
                        LifecycleState.ACTIVE,
                        LifecycleState.TERMINATING,
                        LifecycleState.INSOLVENT,
                    }
                )
            )
            if not request.marks and context.open_position_rows():
                raise CapitalConflict(
                    "valuation_mark_missing",
                    "close valuation must mark every open position",
                )
            if not request.marks:
                return self._close_valuation_liquid(context, request)

            legs = tuple(
                ValuationMarkEconomicEventLeg(
                    leg_id=f"{request.idempotency_key}:mark:{mark.security_id}",
                    asset_kind=EconomicAssetKind.VALUATION_MARK,
                    security_id=mark.security_id,
                    mark_price=Decimal(mark.price_micros) / PRICE_MICRO_SCALE,
                )
                for mark in request.marks
            )
            payload = CapitalCommandPayload(
                event_kind=EconomicEventKind.VALUATION,
                effective_at=request.effective_at,
                source_authority=request.source_authority,
                legs=legs,
            )
            command = CapitalCommand(
                idempotency_key=request.idempotency_key,
                account_binding=binding,
                expected_stream_version=request.expected_stream_version,
                as_of=request.as_of,
                payload=payload,
            )
            snapshot = context.run_append(command, after_event_insert_hook=None)

            event_id = derive_event_id(request.idempotency_key)
            observation_row = context.observation_row_for_event(
                ObservationKind.AS_OBSERVED, event_id
            )
            projection = context.projection_row()
            receipt = ValuationReceipt(
                event_id=event_id,
                observation_id=observation_row.nav_observation_id,
                nav_cents=int(projection.as_observed_nav_cents),
                lifetime_high_water_mark_cents=int(
                    projection.lifetime_high_water_mark_cents
                ),
                active_epoch_high_water_mark_cents=int(
                    projection.active_epoch_high_water_mark_cents
                ),
                log_growth_kind=LogGrowthKind(observation_row.log_growth_kind),
                capital_version=int(projection.capital_version),
                stream_version=context.current_stream_version(),
            )
            return receipt, snapshot

        return self._run_write_transaction(operation)

    def _close_valuation_liquid(
        self,
        context: GatewayTransactionContext,
        request: ValuationRequest,
    ) -> tuple[ValuationReceipt, CapitalRiskSnapshot]:
        """Event-less NAV confirmation for a fully liquid portfolio.

        No economic event is appended (the event contract requires at least
        one leg and a liquid valuation has none), so the stream CAS is not
        exercised; idempotency converges on the deterministic observation
        identity.
        """

        anchor_event_id = derive_event_id(request.idempotency_key)
        observation_row = context.observation_row_for_event(
            ObservationKind.AS_OBSERVED, anchor_event_id
        )
        if observation_row is not None:
            projection = context.projection_row()
            receipt = ValuationReceipt(
                event_id=anchor_event_id,
                observation_id=observation_row.nav_observation_id,
                nav_cents=int(projection.as_observed_nav_cents),
                lifetime_high_water_mark_cents=int(
                    projection.lifetime_high_water_mark_cents
                ),
                active_epoch_high_water_mark_cents=int(
                    projection.active_epoch_high_water_mark_cents
                ),
                log_growth_kind=LogGrowthKind(observation_row.log_growth_kind),
                capital_version=int(projection.capital_version),
                stream_version=context.current_stream_version(),
            )
            return receipt, context.read_capital_risk_snapshot(request.as_of)

        projection = context.projection_row()
        if int(projection.issued_unit_quanta) == 0:
            raise CapitalConflict(
                "valuation_before_genesis",
                "close valuation requires an initialized genesis",
            )
        prior = context.latest_observation_row(ObservationKind.AS_OBSERVED)
        nav_cents = context.equity_cents(marks={}, projection=projection)
        new_version = context.confirm_observed_nav(
            nav_cents=nav_cents,
            event_id=anchor_event_id,
            effective_at=request.effective_at,
            recorded_at=request.as_of,
            prior_nav_cents=(int(prior.nav_cents) if prior is not None else None),
        )
        context.recompute_risk_and_stage_loss(request.as_of, anchor_event_id)
        snapshot = context.read_capital_risk_snapshot(request.as_of)
        projection = context.projection_row()
        observation_row = context.observation_row_for_event(
            ObservationKind.AS_OBSERVED, anchor_event_id
        )
        receipt = ValuationReceipt(
            event_id=anchor_event_id,
            observation_id=observation_row.nav_observation_id,
            nav_cents=nav_cents,
            lifetime_high_water_mark_cents=int(
                projection.lifetime_high_water_mark_cents
            ),
            active_epoch_high_water_mark_cents=int(
                projection.active_epoch_high_water_mark_cents
            ),
            log_growth_kind=LogGrowthKind(observation_row.log_growth_kind),
            capital_version=new_version,
            stream_version=context.current_stream_version(),
        )
        return receipt, snapshot

    def restate_valuation(
        self, request: RestatementRequest
    ) -> tuple[RestatementReceipt, CapitalRiskSnapshot]:
        """Append a restated valuation linked to the observation it
        supersedes (append-only; the as-observed path is preserved)."""

        def operation(
            context: GatewayTransactionContext,
        ) -> tuple[RestatementReceipt, CapitalRiskSnapshot]:
            conn = context._connection
            binding = self._stored_binding(context)
            context.require_lifecycle(
                frozenset(
                    {
                        LifecycleState.ACTIVE,
                        LifecycleState.TERMINATING,
                        LifecycleState.INSOLVENT,
                    }
                )
            )
            target_row = conn.execute(
                sa.text(
                    "SELECT event_kind, correction_of_event_id"
                    " FROM economic_events WHERE economic_event_id = :id"
                ),
                {"id": request.restates_event_id},
            ).first()
            if target_row is None:
                raise CapitalConflict(
                    "restatement_target_unknown",
                    "restatement references no recorded valuation event",
                    restates_event_id=request.restates_event_id,
                )
            if (
                target_row.event_kind != EconomicEventKind.VALUATION.value
                or target_row.correction_of_event_id is not None
            ):
                raise CapitalConflict(
                    "restatement_target_conflict",
                    "restatement must reference an as-observed valuation"
                    " event",
                    restates_event_id=request.restates_event_id,
                )

            legs = tuple(
                ValuationMarkEconomicEventLeg(
                    leg_id=f"{request.idempotency_key}:mark:{mark.security_id}",
                    asset_kind=EconomicAssetKind.VALUATION_MARK,
                    security_id=mark.security_id,
                    mark_price=Decimal(mark.price_micros) / PRICE_MICRO_SCALE,
                )
                for mark in request.marks
            )
            payload = CapitalCommandPayload(
                event_kind=EconomicEventKind.VALUATION,
                effective_at=request.effective_at,
                source_authority=request.source_authority,
                correction_of_event_id=request.restates_event_id,
                legs=legs,
            )
            command = CapitalCommand(
                idempotency_key=request.idempotency_key,
                account_binding=binding,
                expected_stream_version=request.expected_stream_version,
                as_of=request.as_of,
                payload=payload,
            )
            event_id = derive_event_id(request.idempotency_key)

            def register_revision(tx: GatewayTransactionContext) -> None:
                tx._connection.execute(
                    tx._table("event_revisions").insert().values(
                        canonical_event_id=request.restates_event_id,
                        revision_event_id=event_id,
                        revision_kind=ObservationKind.RESTATED_FINAL.value,
                        recorded_at=utc_iso(request.as_of),
                    )
                )

            snapshot = context.run_append(
                command,
                after_event_insert_hook=None,
                after_projection_hook=register_revision,
            )
            observation_row = context.observation_row_for_event(
                ObservationKind.RESTATED_FINAL, event_id
            )
            projection = context.projection_row()
            receipt = RestatementReceipt(
                event_id=event_id,
                restates_event_id=request.restates_event_id,
                observation_id=observation_row.nav_observation_id,
                nav_cents=int(observation_row.nav_cents),
                capital_version=int(projection.capital_version),
                stream_version=context.current_stream_version(),
            )
            return receipt, snapshot

        return self._run_write_transaction(operation)

    def start_risk_epoch(
        self, request: RiskEpochRequest
    ) -> tuple[RiskEpochReceipt, CapitalRiskSnapshot]:
        """Start a new monotonic risk epoch from an audited capital snapshot.

        ``RiskEpochStarted`` is a governance authority fact, not an economic
        event: it lands in the append-only ``risk_epoch_history`` chain and
        bumps ``gateway_meta.risk_epoch``. It re-establishes only the
        active-epoch operational baseline (the audited NAV); the lifetime
        high-water mark and every history row are preserved. INSOLVENT is
        not recoverable through a risk epoch.
        """

        def operation(
            context: GatewayTransactionContext,
        ) -> tuple[RiskEpochReceipt, CapitalRiskSnapshot]:
            conn = context._connection
            self._stored_binding(context)
            context.require_lifecycle(frozenset({LifecycleState.ACTIVE}))

            epoch_table = context._table("risk_epoch_history")
            existing = conn.execute(
                epoch_table.select().where(
                    epoch_table.c.idempotency_key == request.idempotency_key
                )
            ).first()
            if existing is not None:
                if (
                    int(existing.risk_epoch) != request.risk_epoch
                    or int(existing.audited_nav_cents)
                    != request.audited_nav_cents
                ):
                    raise CapitalConflict(
                        "payload_conflict",
                        "risk epoch idempotency key already committed with"
                        " different content",
                        idempotency_key=request.idempotency_key,
                    )
                projection = context.projection_row()
                receipt = RiskEpochReceipt(
                    risk_epoch=int(existing.risk_epoch),
                    predecessor_risk_epoch=int(
                        existing.predecessor_risk_epoch
                    ),
                    audited_nav_cents=int(existing.audited_nav_cents),
                    active_epoch_baseline_nav_cents=int(
                        existing.active_epoch_baseline_nav_cents
                    ),
                    lifetime_high_water_mark_cents=int(
                        existing.lifetime_high_water_mark_cents
                    ),
                    capital_version=int(projection.capital_version),
                )
                return receipt, context.read_capital_risk_snapshot(request.as_of)

            meta_table = context._table("gateway_meta")
            current_epoch = int(
                conn.execute(
                    meta_table.select().where(meta_table.c.key == "risk_epoch")
                ).one().value
            )
            if request.risk_epoch != current_epoch + 1:
                raise CapitalConflict(
                    "risk_epoch_predecessor_mismatch",
                    "risk epochs are monotonic: the request must start the"
                    " successor of the active epoch",
                    active_epoch=current_epoch,
                    requested_epoch=request.risk_epoch,
                )
            projection = context.projection_row()
            if request.audited_nav_cents != int(
                projection.as_observed_nav_cents
            ):
                raise CapitalConflict(
                    "risk_epoch_audit_mismatch",
                    "the audited NAV must equal the confirmed as-observed"
                    " NAV of this ledger",
                    audited_nav_cents=request.audited_nav_cents,
                    as_observed_nav_cents=int(
                        projection.as_observed_nav_cents
                    ),
                )
            binding_row = conn.execute(
                context._table("account_capital_truth").select()
            ).one()
            conn.execute(
                epoch_table.insert().values(
                    risk_epoch=request.risk_epoch,
                    portfolio_id=binding_row.portfolio_id,
                    idempotency_key=request.idempotency_key,
                    predecessor_risk_epoch=current_epoch,
                    audited_nav_cents=request.audited_nav_cents,
                    active_epoch_baseline_nav_cents=request.audited_nav_cents,
                    lifetime_high_water_mark_cents=int(
                        projection.lifetime_high_water_mark_cents
                    ),
                    source_authority=request.source_authority,
                    authorization_reference=request.authorization_reference,
                    started_at=utc_iso(request.as_of),
                )
            )
            # The active-epoch operational baseline becomes the audited NAV;
            # the lifetime HWM is never reset.
            new_version = context.bump_projection(
                None,
                request.as_of,
                active_epoch_high_water_mark_cents=request.audited_nav_cents,
            )
            conn.execute(
                meta_table.update()
                .where(meta_table.c.key == "risk_epoch")
                .values(
                    value=str(request.risk_epoch),
                    updated_at=utc_iso(request.as_of),
                )
            )
            # The RISK latch is one-way WITHIN an epoch; starting the
            # successor epoch is the governance recovery act that clears it
            # against the new audited operational baseline. Stage-loss
            # consumption/latches are never reset by a risk epoch.
            context._connection.execute(
                sa.text(
                    "INSERT INTO risk_latches (latch_kind, state, reason,"
                    " set_at, set_by_event_id) VALUES ('RISK', :state,"
                    " :reason, :set_at, NULL)"
                    " ON CONFLICT(latch_kind) DO UPDATE SET"
                    " state = excluded.state, reason = excluded.reason,"
                    " set_at = excluded.set_at,"
                    " set_by_event_id = excluded.set_by_event_id"
                ),
                {
                    "state": RiskLatchState.CLEAR.value,
                    "reason": "risk epoch recovery cleared the halt",
                    "set_at": utc_iso(request.as_of),
                },
            )
            snapshot = context.read_capital_risk_snapshot(request.as_of)
            receipt = RiskEpochReceipt(
                risk_epoch=request.risk_epoch,
                predecessor_risk_epoch=current_epoch,
                audited_nav_cents=request.audited_nav_cents,
                active_epoch_baseline_nav_cents=request.audited_nav_cents,
                lifetime_high_water_mark_cents=int(
                    projection.lifetime_high_water_mark_cents
                ),
                capital_version=new_version,
            )
            return receipt, snapshot

        return self._run_write_transaction(operation)

    # -- Plan 02 Task 4: corporate actions and lot continuity -----------------
    #
    # One fact / one event per action revision. Corporate actions keep
    # running through TERMINATING and INSOLVENT (exits, corporate actions
    # and reconciliation are never blocked by a risk halt); only a
    # TERMINATED account rejects them. The source-authority matrix is
    # monotonic: AS_OBSERVED -> CONFIRMED upgrades are allowed, downgrades
    # fail closed, and a confirmation changes only the unresolved delta
    # (settled legs/cash are never rewritten).

    def _economic_event_row(
        self, context: GatewayTransactionContext, idempotency_key: str
    ) -> Any | None:
        return context._connection.execute(
            sa.text(
                "SELECT * FROM economic_events WHERE idempotency_key = :key"
            ),
            {"key": idempotency_key},
        ).first()

    def _outstanding_lot_share_receivable_rows(
        self, context: GatewayTransactionContext, lineage: str, lot: str
    ) -> tuple[Any, ...]:
        """Unsettled SHARE receivables attached to one economic lot.

        Share receivables only enter through Task 4 corporate actions, so
        the ``corporate_actions`` projection is the lot-scoped index.
        """

        rows = context._connection.execute(
            sa.text(
                "SELECT receivable_id FROM corporate_actions"
                " WHERE position_lineage_id = :lineage"
                " AND economic_lot_id = :lot"
                " AND receivable_id IS NOT NULL"
                " ORDER BY rowid"
            ),
            {"lineage": lineage, "lot": lot},
        ).all()
        outstanding = []
        for row in rows:
            receivable = context.receivable_row(row.receivable_id)
            if (
                receivable is not None
                and receivable.receivable_kind == "SHARE"
                and int(receivable.settled) == 0
            ):
                outstanding.append(receivable)
        return tuple(outstanding)

    @staticmethod
    def _require_fact_fields_match(
        checks: tuple[tuple[str, object, object], ...]
    ) -> None:
        for name, requested, committed in checks:
            if requested != committed:
                raise CapitalConflict(
                    "payload_conflict",
                    "corporate action identity already committed with"
                    " different content",
                    field=name,
                )

    def record_entitlement(
        self, request: EntitlementRequest
    ) -> tuple[EntitlementReceipt, CapitalRiskSnapshot]:
        """Record one ex-date entitlement fact (or correction revision)."""

        def operation(
            context: GatewayTransactionContext,
        ) -> tuple[EntitlementReceipt, CapitalRiskSnapshot]:
            binding = self._stored_binding(context)
            context.require_lifecycle(
                frozenset(
                    {
                        LifecycleState.ACTIVE,
                        LifecycleState.TERMINATING,
                        LifecycleState.INSOLVENT,
                    }
                )
            )
            position = context.position_row(
                request.position_lineage_id, request.economic_lot_id
            )
            if position is None:
                raise CapitalConflict(
                    "lot_unknown",
                    "entitlement references an unknown economic lot",
                    economic_lot_id=request.economic_lot_id,
                )
            if position.state not in (
                PositionState.OPEN.value,
                PositionState.EXIT_PENDING.value,
            ):
                raise CapitalConflict(
                    "lot_not_live",
                    "entitlement against a terminal economic lot",
                    economic_lot_id=request.economic_lot_id,
                    state=position.state,
                )
            if position.security_id != request.security_id:
                raise CapitalConflict(
                    "security_mismatch",
                    "entitlement security does not match the economic lot",
                    economic_lot_id=request.economic_lot_id,
                    lot_security_id=position.security_id,
                    requested_security_id=request.security_id,
                )
            if request.entitlement.numerator < 1:
                raise CapitalConflict(
                    "entitlement_must_be_positive",
                    "entitlement ratio must be positive",
                )

            key = entitlement_idempotency_key(
                request.action_id,
                request.position_lineage_id,
                request.economic_lot_id,
                revision=request.revision,
            )
            existing = self._economic_event_row(context, key)
            if existing is not None:
                committed_payload = CapitalCommandPayload.model_validate_json(
                    existing.payload_json
                )
                fact = committed_payload.corporate_action
                assert fact is not None
                self._require_fact_fields_match(
                    (
                        ("action_kind", request.action_kind, fact.action_kind),
                        ("entitlement", request.entitlement, fact.entitlement),
                        (
                            "cash_in_lieu_cents",
                            request.cash_in_lieu_cents,
                            fact.cash_in_lieu_cents,
                        ),
                        ("tier", request.tier, fact.tier),
                    )
                )
                receipt = self._entitlement_receipt_from_committed(
                    context, request, existing, committed_payload
                )
                return receipt, context.read_capital_risk_snapshot(request.as_of)

            row = context.corporate_action_row(
                request.action_id,
                request.position_lineage_id,
                request.economic_lot_id,
            )
            if request.revision == 1:
                if row is not None:
                    raise CapitalConflict(
                        "corporate_action_revision_conflict",
                        "entitlement revision 1 already committed",
                        action_id=request.action_id,
                    )
                return self._record_initial_entitlement(
                    context, binding, request, position
                )
            return self._record_entitlement_correction(
                context, binding, request, position, row
            )

        return self._run_write_transaction(operation)

    def _entitlement_payloads(
        self,
        request: EntitlementRequest,
        recorded_quantity: int,
    ) -> tuple[tuple[str, CapitalCommandPayload], ...]:
        """Deterministic entitlement payloads for one recorded quantity.

        Pure function of (request, recorded quantity): the committed fact
        stores the quantity consumed at record time so idempotent retries
        rebuild the identical payload after later splits or settlements.
        """

        key = entitlement_idempotency_key(
            request.action_id,
            request.position_lineage_id,
            request.economic_lot_id,
            revision=request.revision,
        )
        numerator = request.entitlement.numerator
        denominator = request.entitlement.denominator

        if request.action_kind is CorporateActionKind.CASH_DIVIDEND:
            try:
                cents = exact_entitlement_cents(
                    recorded_quantity, numerator, denominator
                )
            except ValueError as exc:
                raise CapitalConflict(
                    "entitlement_not_exact",
                    "cash entitlement does not divide to exact cents; the"
                    " kernel has no frozen sub-cent rounding policy",
                    detail=str(exc),
                ) from exc
            if cents < 1:
                raise CapitalConflict(
                    "entitlement_must_be_positive",
                    "entitlement rounds to zero whole cents",
                )
            receivable_id = cash_receivable_id(
                request.action_id,
                request.position_lineage_id,
                request.economic_lot_id,
                revision=request.revision,
            )
            payload = CapitalCommandPayload(
                event_kind=EconomicEventKind.DIVIDEND_RECEIVABLE,
                effective_at=request.effective_at,
                source_authority=request.source_authority,
                position_lineage_id=request.position_lineage_id,
                economic_lot_id=request.economic_lot_id,
                legs=(
                    CashReceivableEconomicEventLeg(
                        leg_id=f"{key}:cash",
                        direction=EconomicLegDirection.CREDIT,
                        asset_kind=EconomicAssetKind.CASH_RECEIVABLE,
                        receivable_id=receivable_id,
                        security_id=request.security_id,
                        cash_amount=Decimal(cents) / CENT_SCALE,
                    ),
                ),
                corporate_action=CorporateActionFact(
                    action_id=request.action_id,
                    action_kind=request.action_kind,
                    revision=request.revision,
                    tier=request.tier,
                    entitlement=request.entitlement,
                    recorded_quantity_units=recorded_quantity,
                ),
            )
            return ((key, payload),)

        whole, remainder_num, remainder_den = split_entitlement(
            recorded_quantity, numerator, denominator
        )
        fact = CorporateActionFact(
            action_id=request.action_id,
            action_kind=request.action_kind,
            revision=request.revision,
            tier=request.tier,
            entitlement=request.entitlement,
            fractional_remainder=RationalQuantity(
                numerator=remainder_num, denominator=remainder_den
            ),
            cash_in_lieu_cents=request.cash_in_lieu_cents,
            recorded_quantity_units=recorded_quantity,
        )
        payloads: list[tuple[str, CapitalCommandPayload]] = []
        if whole > 0:
            share_id = share_receivable_id(
                request.action_id,
                request.position_lineage_id,
                request.economic_lot_id,
                revision=request.revision,
            )
            payloads.append(
                (
                    key,
                    CapitalCommandPayload(
                        event_kind=EconomicEventKind.SHARE_RECEIVABLE,
                        effective_at=request.effective_at,
                        source_authority=request.source_authority,
                        position_lineage_id=request.position_lineage_id,
                        economic_lot_id=request.economic_lot_id,
                        legs=(
                            ShareReceivableEconomicEventLeg(
                                leg_id=f"{key}:share",
                                direction=EconomicLegDirection.CREDIT,
                                asset_kind=EconomicAssetKind.SHARE_RECEIVABLE,
                                receivable_id=share_id,
                                security_id=request.security_id,
                                quantity=whole,
                            ),
                        ),
                        corporate_action=fact,
                    ),
                )
            )
        if request.cash_in_lieu_cents is not None:
            cash_in_lieu_id = cash_in_lieu_receivable_id(
                request.action_id,
                request.position_lineage_id,
                request.economic_lot_id,
                revision=request.revision,
            )
            payloads.append(
                (
                    f"{key}:cil",
                    CapitalCommandPayload(
                        event_kind=EconomicEventKind.DIVIDEND_RECEIVABLE,
                        effective_at=request.effective_at,
                        source_authority=request.source_authority,
                        position_lineage_id=request.position_lineage_id,
                        economic_lot_id=request.economic_lot_id,
                        legs=(
                            CashReceivableEconomicEventLeg(
                                leg_id=f"{key}:cil",
                                direction=EconomicLegDirection.CREDIT,
                                asset_kind=EconomicAssetKind.CASH_RECEIVABLE,
                                receivable_id=cash_in_lieu_id,
                                security_id=request.security_id,
                                cash_amount=(
                                    Decimal(request.cash_in_lieu_cents)
                                    / CENT_SCALE
                                ),
                            ),
                        ),
                        corporate_action=fact,
                    ),
                )
            )
        if not payloads:
            raise CapitalConflict(
                "entitlement_must_be_positive",
                "fractional entitlement has no recordable leg; declare a"
                " cash-in-lieu amount for the remainder",
            )
        return tuple(payloads)

    def _append_entitlement_payloads(
        self,
        context: GatewayTransactionContext,
        binding: AccountBinding,
        request: EntitlementRequest,
        payloads: tuple[tuple[str, CapitalCommandPayload], ...],
        revision_links: tuple[tuple[str, str], ...] = (),
        row_updater: Callable[[GatewayTransactionContext, str], None] | None = None,
    ) -> CapitalRiskSnapshot:
        snapshot: CapitalRiskSnapshot | None = None
        primary_event_id: str | None = None
        for index, (idem_key, payload) in enumerate(payloads):
            command = CapitalCommand(
                idempotency_key=idem_key,
                account_binding=binding,
                expected_stream_version=(
                    request.expected_stream_version
                    if index == 0
                    else context.current_stream_version()
                ),
                as_of=request.as_of,
                payload=payload,
            )
            event_id = derive_event_id(idem_key)

            def register(tx: GatewayTransactionContext) -> None:
                for canonical_id, _ in revision_links:
                    tx._connection.execute(
                        tx._table("event_revisions").insert().values(
                            canonical_event_id=canonical_id,
                            revision_event_id=event_id,
                            revision_kind="LATE_CORRECTION",
                            recorded_at=utc_iso(request.as_of),
                        )
                    )
                if index == 0 and row_updater is not None:
                    row_updater(tx, event_id)

            snapshot = context.run_append(
                command,
                after_event_insert_hook=None,
                after_projection_hook=register,
            )
            if primary_event_id is None:
                primary_event_id = event_id
        assert snapshot is not None
        return snapshot

    def _record_initial_entitlement(
        self,
        context: GatewayTransactionContext,
        binding: AccountBinding,
        request: EntitlementRequest,
        position: Any,
    ) -> tuple[EntitlementReceipt, CapitalRiskSnapshot]:
        recorded_quantity = int(position.settled_quantity_units)
        payloads = self._entitlement_payloads(request, recorded_quantity)

        def insert_row(tx: GatewayTransactionContext, event_id: str) -> None:
            entitlement = request.entitlement
            fractional = payloads[0][1].corporate_action
            assert fractional is not None
            remainder = fractional.fractional_remainder
            share_id = share_receivable_id(
                request.action_id,
                request.position_lineage_id,
                request.economic_lot_id,
                revision=request.revision,
            )
            cash_id = cash_receivable_id(
                request.action_id,
                request.position_lineage_id,
                request.economic_lot_id,
                revision=request.revision,
            )
            cil_id = cash_in_lieu_receivable_id(
                request.action_id,
                request.position_lineage_id,
                request.economic_lot_id,
                revision=request.revision,
            )
            receivable_id = (
                cash_id
                if request.action_kind is CorporateActionKind.CASH_DIVIDEND
                else (share_id if tx.receivable_row(share_id) is not None else None)
            )
            tx._connection.execute(
                tx._table("corporate_actions").insert().values(
                    action_id=request.action_id,
                    position_lineage_id=request.position_lineage_id,
                    economic_lot_id=request.economic_lot_id,
                    action_kind=request.action_kind.value,
                    state=CorporateActionState.PENDING.value,
                    source_authority_tier=request.tier.value,
                    source_authority=request.source_authority,
                    security_id=request.security_id,
                    revision=request.revision,
                    entitlement_numerator=entitlement.numerator,
                    entitlement_denominator=entitlement.denominator,
                    fractional_remainder_numerator=(
                        remainder.numerator if remainder is not None else None
                    ),
                    fractional_remainder_denominator=(
                        remainder.denominator if remainder is not None else None
                    ),
                    cash_in_lieu_cents=request.cash_in_lieu_cents,
                    receivable_id=receivable_id,
                    cash_in_lieu_receivable_id=(
                        cil_id
                        if request.cash_in_lieu_cents is not None
                        else None
                    ),
                    ex_effective_at=utc_iso(request.effective_at),
                    pay_effective_at=None,
                    tradable_effective_at=None,
                    successor_security_id=None,
                    successor_quantity_units=None,
                    successor_receivable_id=None,
                    inherited_position_state=None,
                    opened_by_event_id=event_id,
                    updated_by_event_id=event_id,
                    updated_at=utc_iso(request.as_of),
                )
            )

        snapshot = self._append_entitlement_payloads(
            context, binding, request, payloads, row_updater=insert_row
        )
        event_id = derive_event_id(
            entitlement_idempotency_key(
                request.action_id,
                request.position_lineage_id,
                request.economic_lot_id,
                revision=request.revision,
            )
        )
        receipt = self._entitlement_receipt(
            context,
            request,
            payloads,
            event_id=event_id,
            correction=False,
            supersedes_event_id=None,
        )
        return receipt, snapshot

    def _record_entitlement_correction(
        self,
        context: GatewayTransactionContext,
        binding: AccountBinding,
        request: EntitlementRequest,
        position: Any,
        row: Any,
    ) -> tuple[EntitlementReceipt, CapitalRiskSnapshot]:
        if row is None:
            raise CapitalConflict(
                "corporate_action_unknown",
                "correction references no recorded corporate action",
                action_id=request.action_id,
            )
        committed_tier = SourceAuthorityTier(row.source_authority_tier)
        if SOURCE_AUTHORITY_RANK[request.tier] < SOURCE_AUTHORITY_RANK[
            committed_tier
        ]:
            raise CapitalConflict(
                "source_authority_downgrade",
                "a confirmed corporate action fact cannot be downgraded by a"
                " later as-observed one",
                action_id=request.action_id,
                committed_tier=committed_tier.value,
                requested_tier=request.tier.value,
            )
        if request.revision == int(row.revision):
            # Idempotent re-recording of the active revision. An identical
            # confirmation appends no event (no capital fact changes), so
            # the idempotency-key lookup above cannot see it; converge on
            # the committed projection row instead. Divergent content under
            # the same revision identity fails closed.
            self._require_fact_fields_match(
                (
                    (
                        "action_kind",
                        request.action_kind.value,
                        row.action_kind,
                    ),
                    (
                        "entitlement",
                        request.entitlement,
                        RationalQuantity(
                            numerator=int(row.entitlement_numerator),
                            denominator=int(row.entitlement_denominator),
                        ),
                    ),
                    (
                        "cash_in_lieu_cents",
                        request.cash_in_lieu_cents,
                        (
                            int(row.cash_in_lieu_cents)
                            if row.cash_in_lieu_cents is not None
                            else None
                        ),
                    ),
                    ("tier", request.tier, committed_tier),
                )
            )
            return self._receipt_for_active_revision(
                context, request, position, row
            )
        if request.revision != int(row.revision) + 1:
            raise CapitalConflict(
                "revision_sequence_conflict",
                "corporate action revisions are monotonic",
                action_id=request.action_id,
                active_revision=int(row.revision),
                requested_revision=request.revision,
            )
        if row.action_kind == CorporateActionKind.CASH_DIVIDEND.value:
            return self._correct_cash_entitlement(
                context, binding, request, position, row
            )
        return self._correct_share_entitlement(
            context, binding, request, position, row
        )

    def _receipt_for_active_revision(
        self,
        context: GatewayTransactionContext,
        request: EntitlementRequest,
        position: Any,
        row: Any,
    ) -> tuple[EntitlementReceipt, CapitalRiskSnapshot]:
        """Converge an idempotent re-recording of the active revision.

        Provenance-only confirmations append no event (no capital fact
        changed), so the receipt rebuilds from the committed projection
        row and its receivable instead of an event payload. Nothing is
        written: the stream, capital, and risk versions stay quiet.
        """

        receivable = (
            context.receivable_row(row.receivable_id)
            if row.receivable_id is not None
            else None
        )
        if receivable is None:
            raise CapitalConflict(
                "corporate_action_unknown",
                "corporate action lost its entitlement receivable",
                action_id=request.action_id,
            )
        if request.action_kind is CorporateActionKind.CASH_DIVIDEND:
            cash_amount: int | None = int(receivable.amount_cents)
            share_quantity: int | None = None
            remainder_numerator, remainder_denominator = 0, 1
        else:
            cash_amount = None
            share_quantity = int(receivable.quantity_units)
            # The provenance-only path is only reachable while the
            # recomputed entitlement matches the committed receivable, so
            # the remainder recomputes exactly as the original receipt.
            _, remainder_numerator, remainder_denominator = split_entitlement(
                int(position.settled_quantity_units),
                request.entitlement.numerator,
                request.entitlement.denominator,
            )
        snapshot = context.read_capital_risk_snapshot(request.as_of)
        receipt = EntitlementReceipt(
            action_id=request.action_id,
            revision=request.revision,
            event_id=receivable.created_by_event_id,
            receivable_id=row.receivable_id,
            cash_amount_cents=cash_amount,
            share_quantity=share_quantity,
            fractional_remainder_numerator=remainder_numerator,
            fractional_remainder_denominator=remainder_denominator,
            cash_in_lieu_cents=(
                int(row.cash_in_lieu_cents)
                if row.cash_in_lieu_cents is not None
                else None
            ),
            cash_in_lieu_receivable_id=row.cash_in_lieu_receivable_id,
            source_authority_tier=request.tier,
            correction=True,
            supersedes_event_id=receivable.created_by_event_id,
            capital_version=snapshot.capital_version,
            stream_version=context.current_stream_version(),
        )
        return receipt, snapshot

    def _correct_cash_entitlement(
        self,
        context: GatewayTransactionContext,
        binding: AccountBinding,
        request: EntitlementRequest,
        position: Any,
        row: Any,
    ) -> tuple[EntitlementReceipt, CapitalRiskSnapshot]:
        receivable = context.receivable_row(row.receivable_id)
        if receivable is None:
            raise CapitalConflict(
                "corporate_action_unknown",
                "corporate action lost its entitlement receivable",
                action_id=request.action_id,
            )
        recorded_quantity = int(position.settled_quantity_units)
        try:
            new_cents = exact_entitlement_cents(
                recorded_quantity,
                request.entitlement.numerator,
                request.entitlement.denominator,
            )
        except ValueError as exc:
            raise CapitalConflict(
                "entitlement_not_exact",
                "corrected cash entitlement does not divide to exact cents",
                detail=str(exc),
            ) from exc
        prior_amount = int(receivable.amount_cents)
        key = entitlement_idempotency_key(
            request.action_id,
            request.position_lineage_id,
            request.economic_lot_id,
            revision=request.revision,
        )
        superseded_event_id = receivable.created_by_event_id

        if new_cents == prior_amount:
            # Provenance upgrade only: no capital fact changed, so the
            # stream and capital version stay quiet.
            self._update_corporate_action_row(
                context,
                request,
                row,
                event_id=superseded_event_id,
                receivable_id=row.receivable_id,
            )
            snapshot = context.read_capital_risk_snapshot(request.as_of)
            receipt = EntitlementReceipt(
                action_id=request.action_id,
                revision=request.revision,
                event_id=superseded_event_id,
                receivable_id=row.receivable_id,
                cash_amount_cents=prior_amount,
                share_quantity=None,
                fractional_remainder_numerator=0,
                fractional_remainder_denominator=1,
                cash_in_lieu_cents=None,
                cash_in_lieu_receivable_id=None,
                source_authority_tier=request.tier,
                correction=True,
                supersedes_event_id=superseded_event_id,
                capital_version=snapshot.capital_version,
                stream_version=context.current_stream_version(),
            )
            return receipt, snapshot

        if int(receivable.settled) == 0:
            new_receivable_id = cash_receivable_id(
                request.action_id,
                request.position_lineage_id,
                request.economic_lot_id,
                revision=request.revision,
            )
            payload = CapitalCommandPayload(
                event_kind=EconomicEventKind.LATE_CORRECTION,
                effective_at=request.effective_at,
                source_authority=request.source_authority,
                position_lineage_id=request.position_lineage_id,
                economic_lot_id=request.economic_lot_id,
                correction_of_event_id=superseded_event_id,
                legs=(
                    CashReceivableEconomicEventLeg(
                        leg_id=f"{key}:supersede",
                        direction=EconomicLegDirection.DEBIT,
                        asset_kind=EconomicAssetKind.CASH_RECEIVABLE,
                        receivable_id=row.receivable_id,
                        security_id=request.security_id,
                        cash_amount=Decimal(prior_amount) / CENT_SCALE,
                    ),
                    CashReceivableEconomicEventLeg(
                        leg_id=f"{key}:corrected",
                        direction=EconomicLegDirection.CREDIT,
                        asset_kind=EconomicAssetKind.CASH_RECEIVABLE,
                        receivable_id=new_receivable_id,
                        security_id=request.security_id,
                        cash_amount=Decimal(new_cents) / CENT_SCALE,
                    ),
                ),
                corporate_action=CorporateActionFact(
                    action_id=request.action_id,
                    action_kind=request.action_kind,
                    revision=request.revision,
                    tier=request.tier,
                    entitlement=request.entitlement,
                    recorded_quantity_units=recorded_quantity,
                    superseded_receivable_id=row.receivable_id,
                    superseded_amount_cents=prior_amount,
                ),
            )

            def update_row(tx: GatewayTransactionContext, event_id: str) -> None:
                self._update_corporate_action_row(
                    tx,
                    request,
                    row,
                    event_id=event_id,
                    receivable_id=new_receivable_id,
                )

            snapshot = self._append_entitlement_payloads(
                context,
                binding,
                request,
                ((key, payload),),
                revision_links=((superseded_event_id, ""),),
                row_updater=update_row,
            )
            event_id = derive_event_id(key)
            receipt = EntitlementReceipt(
                action_id=request.action_id,
                revision=request.revision,
                event_id=event_id,
                receivable_id=new_receivable_id,
                cash_amount_cents=new_cents,
                share_quantity=None,
                fractional_remainder_numerator=0,
                fractional_remainder_denominator=1,
                cash_in_lieu_cents=None,
                cash_in_lieu_receivable_id=None,
                source_authority_tier=request.tier,
                correction=True,
                supersedes_event_id=superseded_event_id,
                capital_version=snapshot.capital_version,
                stream_version=context.current_stream_version(),
            )
            return receipt, snapshot

        # Settled: the paid leg is never rewritten. Only a positive
        # unresolved delta is booked as a fresh receivable; a negative
        # delta is a compensation obligation the kernel cannot yet
        # represent (Plan 02 Task 6).
        if new_cents < prior_amount:
            raise CapitalConflict(
                "confirmation_delta_unsupported",
                "confirmed amount is below the settled amount; the"
                " compensation obligation lands with Plan 02 Task 6",
                action_id=request.action_id,
                settled_cents=prior_amount,
                confirmed_cents=new_cents,
            )
        delta_cents = new_cents - prior_amount
        delta_receivable_id = cash_receivable_id(
            request.action_id,
            request.position_lineage_id,
            request.economic_lot_id,
            revision=request.revision,
        )
        payload = CapitalCommandPayload(
            event_kind=EconomicEventKind.DIVIDEND_RECEIVABLE,
            effective_at=request.effective_at,
            source_authority=request.source_authority,
            position_lineage_id=request.position_lineage_id,
            economic_lot_id=request.economic_lot_id,
            correction_of_event_id=superseded_event_id,
            legs=(
                CashReceivableEconomicEventLeg(
                    leg_id=f"{key}:delta",
                    direction=EconomicLegDirection.CREDIT,
                    asset_kind=EconomicAssetKind.CASH_RECEIVABLE,
                    receivable_id=delta_receivable_id,
                    security_id=request.security_id,
                    cash_amount=Decimal(delta_cents) / CENT_SCALE,
                ),
            ),
            corporate_action=CorporateActionFact(
                action_id=request.action_id,
                action_kind=request.action_kind,
                revision=request.revision,
                tier=request.tier,
                entitlement=request.entitlement,
                recorded_quantity_units=recorded_quantity,
                superseded_receivable_id=row.receivable_id,
                superseded_amount_cents=prior_amount,
                delta_amount_cents=delta_cents,
            ),
        )

        def update_row(tx: GatewayTransactionContext, event_id: str) -> None:
            self._update_corporate_action_row(
                tx,
                request,
                row,
                event_id=event_id,
                receivable_id=delta_receivable_id,
            )

        snapshot = self._append_entitlement_payloads(
            context,
            binding,
            request,
            ((key, payload),),
            revision_links=((superseded_event_id, ""),),
            row_updater=update_row,
        )
        event_id = derive_event_id(key)
        receipt = EntitlementReceipt(
            action_id=request.action_id,
            revision=request.revision,
            event_id=event_id,
            receivable_id=delta_receivable_id,
            cash_amount_cents=delta_cents,
            share_quantity=None,
            fractional_remainder_numerator=0,
            fractional_remainder_denominator=1,
            cash_in_lieu_cents=None,
            cash_in_lieu_receivable_id=None,
            source_authority_tier=request.tier,
            correction=True,
            supersedes_event_id=superseded_event_id,
            capital_version=snapshot.capital_version,
            stream_version=context.current_stream_version(),
        )
        return receipt, snapshot

    def _correct_share_entitlement(
        self,
        context: GatewayTransactionContext,
        binding: AccountBinding,
        request: EntitlementRequest,
        position: Any,
        row: Any,
    ) -> tuple[EntitlementReceipt, CapitalRiskSnapshot]:
        receivable = (
            context.receivable_row(row.receivable_id)
            if row.receivable_id is not None
            else None
        )
        if receivable is None or int(receivable.settled) != 0:
            raise CapitalConflict(
                "corporate_action_correction_unsupported",
                "share entitlement corrections apply only while the share"
                " receivable is unsettled; later corrections land with Plan"
                " 02 Task 6",
                action_id=request.action_id,
            )
        recorded_quantity = int(position.settled_quantity_units)
        whole, remainder_num, remainder_den = split_entitlement(
            recorded_quantity,
            request.entitlement.numerator,
            request.entitlement.denominator,
        )
        old_quantity = int(receivable.quantity_units)
        old_cil = int(row.cash_in_lieu_cents or 0)
        new_cil = request.cash_in_lieu_cents or 0
        key = entitlement_idempotency_key(
            request.action_id,
            request.position_lineage_id,
            request.economic_lot_id,
            revision=request.revision,
        )
        superseded_event_id = receivable.created_by_event_id

        if whole == old_quantity and new_cil == old_cil:
            self._update_corporate_action_row(
                context,
                request,
                row,
                event_id=superseded_event_id,
                receivable_id=row.receivable_id,
            )
            snapshot = context.read_capital_risk_snapshot(request.as_of)
            receipt = EntitlementReceipt(
                action_id=request.action_id,
                revision=request.revision,
                event_id=superseded_event_id,
                receivable_id=row.receivable_id,
                cash_amount_cents=None,
                share_quantity=old_quantity,
                fractional_remainder_numerator=remainder_num,
                fractional_remainder_denominator=remainder_den,
                cash_in_lieu_cents=request.cash_in_lieu_cents,
                cash_in_lieu_receivable_id=row.cash_in_lieu_receivable_id,
                source_authority_tier=request.tier,
                correction=True,
                supersedes_event_id=superseded_event_id,
                capital_version=snapshot.capital_version,
                stream_version=context.current_stream_version(),
            )
            return receipt, snapshot

        legs: list[EconomicEventLeg] = [
            ShareReceivableEconomicEventLeg(
                leg_id=f"{key}:supersede",
                direction=EconomicLegDirection.DEBIT,
                asset_kind=EconomicAssetKind.SHARE_RECEIVABLE,
                receivable_id=row.receivable_id,
                security_id=request.security_id,
                quantity=old_quantity,
            )
        ]
        new_share_id: str | None = None
        if whole > 0:
            new_share_id = share_receivable_id(
                request.action_id,
                request.position_lineage_id,
                request.economic_lot_id,
                revision=request.revision,
            )
            legs.append(
                ShareReceivableEconomicEventLeg(
                    leg_id=f"{key}:corrected",
                    direction=EconomicLegDirection.CREDIT,
                    asset_kind=EconomicAssetKind.SHARE_RECEIVABLE,
                    receivable_id=new_share_id,
                    security_id=request.security_id,
                    quantity=whole,
                )
            )
        new_cil_id = row.cash_in_lieu_receivable_id
        if new_cil != old_cil:
            cil_receivable = (
                context.receivable_row(row.cash_in_lieu_receivable_id)
                if row.cash_in_lieu_receivable_id is not None
                else None
            )
            if cil_receivable is not None and int(cil_receivable.settled) != 0:
                raise CapitalConflict(
                    "corporate_action_correction_unsupported",
                    "the settled cash-in-lieu leg is never rewritten",
                    action_id=request.action_id,
                )
            if cil_receivable is not None:
                legs.append(
                    CashReceivableEconomicEventLeg(
                        leg_id=f"{key}:cil-supersede",
                        direction=EconomicLegDirection.DEBIT,
                        asset_kind=EconomicAssetKind.CASH_RECEIVABLE,
                        receivable_id=row.cash_in_lieu_receivable_id,
                        security_id=request.security_id,
                        cash_amount=(
                            Decimal(int(cil_receivable.amount_cents))
                            / CENT_SCALE
                        ),
                    )
                )
            if new_cil > 0:
                new_cil_id = cash_in_lieu_receivable_id(
                    request.action_id,
                    request.position_lineage_id,
                    request.economic_lot_id,
                    revision=request.revision,
                )
                legs.append(
                    CashReceivableEconomicEventLeg(
                        leg_id=f"{key}:cil-corrected",
                        direction=EconomicLegDirection.CREDIT,
                        asset_kind=EconomicAssetKind.CASH_RECEIVABLE,
                        receivable_id=new_cil_id,
                        security_id=request.security_id,
                        cash_amount=Decimal(new_cil) / CENT_SCALE,
                    )
                )
            else:
                new_cil_id = None

        payload = CapitalCommandPayload(
            event_kind=EconomicEventKind.LATE_CORRECTION,
            effective_at=request.effective_at,
            source_authority=request.source_authority,
            position_lineage_id=request.position_lineage_id,
            economic_lot_id=request.economic_lot_id,
            correction_of_event_id=superseded_event_id,
            legs=tuple(legs),
            corporate_action=CorporateActionFact(
                action_id=request.action_id,
                action_kind=request.action_kind,
                revision=request.revision,
                tier=request.tier,
                entitlement=request.entitlement,
                fractional_remainder=RationalQuantity(
                    numerator=remainder_num, denominator=remainder_den
                ),
                cash_in_lieu_cents=request.cash_in_lieu_cents,
                recorded_quantity_units=recorded_quantity,
                superseded_receivable_id=row.receivable_id,
                superseded_quantity_units=old_quantity,
                superseded_cash_in_lieu_cents=old_cil or None,
            ),
        )

        def update_row(tx: GatewayTransactionContext, event_id: str) -> None:
            self._update_corporate_action_row(
                tx,
                request,
                row,
                event_id=event_id,
                receivable_id=new_share_id,
                cash_in_lieu_receivable_id=new_cil_id,
            )

        snapshot = self._append_entitlement_payloads(
            context,
            binding,
            request,
            ((key, payload),),
            revision_links=((superseded_event_id, ""),),
            row_updater=update_row,
        )
        event_id = derive_event_id(key)
        receipt = EntitlementReceipt(
            action_id=request.action_id,
            revision=request.revision,
            event_id=event_id,
            receivable_id=new_share_id,
            cash_amount_cents=None,
            share_quantity=whole if whole > 0 else None,
            fractional_remainder_numerator=remainder_num,
            fractional_remainder_denominator=remainder_den,
            cash_in_lieu_cents=request.cash_in_lieu_cents,
            cash_in_lieu_receivable_id=new_cil_id,
            source_authority_tier=request.tier,
            correction=True,
            supersedes_event_id=superseded_event_id,
            capital_version=snapshot.capital_version,
            stream_version=context.current_stream_version(),
        )
        return receipt, snapshot

    def _update_corporate_action_row(
        self,
        context: GatewayTransactionContext,
        request: EntitlementRequest,
        row: Any,
        *,
        event_id: str,
        receivable_id: str | None,
        cash_in_lieu_receivable_id: str | None | object = _SENTINEL_UNSET,
    ) -> None:
        values: dict[str, Any] = {
            "revision": request.revision,
            "source_authority_tier": request.tier.value,
            "source_authority": request.source_authority,
            "entitlement_numerator": request.entitlement.numerator,
            "entitlement_denominator": request.entitlement.denominator,
            "receivable_id": receivable_id,
            "updated_by_event_id": event_id,
            "updated_at": utc_iso(request.as_of),
        }
        if cash_in_lieu_receivable_id is not _SENTINEL_UNSET:
            values["cash_in_lieu_receivable_id"] = cash_in_lieu_receivable_id
        context._connection.execute(
            context._table("corporate_actions").update()
            .where(
                sa.and_(
                    context._table("corporate_actions").c.action_id
                    == row.action_id,
                    context._table("corporate_actions").c.position_lineage_id
                    == row.position_lineage_id,
                    context._table("corporate_actions").c.economic_lot_id
                    == row.economic_lot_id,
                )
            )
            .values(**values)
        )

    def _entitlement_receipt(
        self,
        context: GatewayTransactionContext,
        request: EntitlementRequest,
        payloads: tuple[tuple[str, CapitalCommandPayload], ...],
        *,
        event_id: str,
        correction: bool,
        supersedes_event_id: str | None,
    ) -> EntitlementReceipt:
        cash_amount: int | None = None
        share_quantity: int | None = None
        receivable_id: str | None = None
        cil_amount: int | None = None
        cil_receivable_id: str | None = None
        remainder = (0, 1)
        for _key, payload in payloads:
            fact = payload.corporate_action
            assert fact is not None
            if fact.fractional_remainder is not None:
                remainder = (
                    fact.fractional_remainder.numerator,
                    fact.fractional_remainder.denominator,
                )
            for leg in payload.legs:
                if leg.asset_kind is EconomicAssetKind.CASH_RECEIVABLE:
                    amount = scaled_int(
                        leg.cash_amount, CENT_SCALE, "cash_amount"
                    )
                    if (
                        request.action_kind
                        is CorporateActionKind.CASH_DIVIDEND
                    ):
                        cash_amount = amount
                        receivable_id = leg.receivable_id
                    else:
                        cil_amount = amount
                        cil_receivable_id = leg.receivable_id
                elif leg.asset_kind is EconomicAssetKind.SHARE_RECEIVABLE:
                    share_quantity = int(leg.quantity)
                    receivable_id = leg.receivable_id
        snapshot = context.read_capital_risk_snapshot(request.as_of)
        return EntitlementReceipt(
            action_id=request.action_id,
            revision=request.revision,
            event_id=event_id,
            receivable_id=receivable_id,
            cash_amount_cents=cash_amount,
            share_quantity=share_quantity,
            fractional_remainder_numerator=remainder[0],
            fractional_remainder_denominator=remainder[1],
            cash_in_lieu_cents=cil_amount,
            cash_in_lieu_receivable_id=cil_receivable_id,
            source_authority_tier=request.tier,
            correction=correction,
            supersedes_event_id=supersedes_event_id,
            capital_version=snapshot.capital_version,
            stream_version=context.current_stream_version(),
        )

    def _entitlement_receipt_from_committed(
        self,
        context: GatewayTransactionContext,
        request: EntitlementRequest,
        event_row: Any,
        committed_payload: CapitalCommandPayload,
    ) -> EntitlementReceipt:
        """Rebuild the receipt from the committed event's own legs.

        Reading the canonical legs (never recomputing them) keeps an
        idempotent retry byte-identical to the original receipt for every
        committed shape, including post-settlement delta corrections whose
        legs differ from a fresh entitlement booking.
        """

        fact = committed_payload.corporate_action
        assert fact is not None
        cash_amount: int | None = None
        share_quantity: int | None = None
        receivable_id: str | None = None
        cil_amount: int | None = None
        cil_receivable_id: str | None = None
        for leg in committed_payload.legs:
            if leg.direction is not EconomicLegDirection.CREDIT:
                continue
            if leg.asset_kind is EconomicAssetKind.CASH_RECEIVABLE:
                amount = scaled_int(
                    leg.cash_amount, CENT_SCALE, "cash_amount"
                )
                if (
                    request.action_kind
                    is CorporateActionKind.CASH_DIVIDEND
                ):
                    cash_amount = amount
                    receivable_id = leg.receivable_id
                else:
                    cil_amount = amount
                    cil_receivable_id = leg.receivable_id
            elif leg.asset_kind is EconomicAssetKind.SHARE_RECEIVABLE:
                share_quantity = int(leg.quantity)
                receivable_id = leg.receivable_id
        remainder = fact.fractional_remainder
        snapshot = context.read_capital_risk_snapshot(request.as_of)
        return EntitlementReceipt(
            action_id=request.action_id,
            revision=request.revision,
            event_id=event_row.economic_event_id,
            receivable_id=receivable_id,
            cash_amount_cents=cash_amount,
            share_quantity=share_quantity,
            fractional_remainder_numerator=(
                remainder.numerator if remainder is not None else 0
            ),
            fractional_remainder_denominator=(
                remainder.denominator if remainder is not None else 1
            ),
            cash_in_lieu_cents=cil_amount,
            cash_in_lieu_receivable_id=cil_receivable_id,
            source_authority_tier=request.tier,
            correction=request.revision > 1,
            supersedes_event_id=event_row.correction_of_event_id,
            capital_version=snapshot.capital_version,
            stream_version=context.current_stream_version(),
        )

    def settle_cash_in_lieu(
        self, request: CashInLieuRequest
    ) -> tuple[CashInLieuReceipt, CapitalRiskSnapshot]:
        """Settle the action's outstanding cash entitlement receivable.

        One fact per receivable (pay date / cash-in-lieu receipt): the
        receivable debit and the cash credit land atomically as one
        DIVIDEND_CASH_SETTLED event. The settled amount always equals the
        outstanding receivable; the pay date cannot precede the ex date.
        """

        def operation(
            context: GatewayTransactionContext,
        ) -> tuple[CashInLieuReceipt, CapitalRiskSnapshot]:
            binding = self._stored_binding(context)
            context.require_lifecycle(
                frozenset(
                    {
                        LifecycleState.ACTIVE,
                        LifecycleState.TERMINATING,
                        LifecycleState.INSOLVENT,
                    }
                )
            )
            row = context.corporate_action_row(
                request.action_id,
                request.position_lineage_id,
                request.economic_lot_id,
            )
            if row is None:
                raise CapitalConflict(
                    "corporate_action_unknown",
                    "settlement references no recorded corporate action",
                    action_id=request.action_id,
                )
            if row.action_kind not in (
                CorporateActionKind.CASH_DIVIDEND.value,
                CorporateActionKind.SHARE_ENTITLEMENT.value,
            ):
                raise CapitalConflict(
                    "corporate_action_kind_conflict",
                    "cash settlement applies to entitlement actions only",
                    action_id=request.action_id,
                    action_kind=row.action_kind,
                )
            receivable_id = (
                row.receivable_id
                if row.action_kind == CorporateActionKind.CASH_DIVIDEND.value
                else row.cash_in_lieu_receivable_id
            )
            if receivable_id is None:
                raise CapitalConflict(
                    "corporate_action_nothing_to_settle",
                    "the action carries no cash entitlement receivable",
                    action_id=request.action_id,
                )
            receivable = context.receivable_row(receivable_id)
            if receivable is None:
                raise CapitalConflict(
                    "corporate_action_nothing_to_settle",
                    "the action lost its cash entitlement receivable",
                    action_id=request.action_id,
                )
            idempotency_key = settlement_idempotency_key(receivable_id)
            if int(receivable.settled) != 0:
                existing = self._economic_event_row(context, idempotency_key)
                if existing is None:
                    raise CapitalConflict(
                        "corporate_action_settlement_conflict",
                        "receivable settled outside this settlement fact",
                        receivable_id=receivable_id,
                    )
                snapshot = context.read_capital_risk_snapshot(request.as_of)
                receipt = CashInLieuReceipt(
                    action_id=request.action_id,
                    receivable_id=receivable_id,
                    event_id=existing.economic_event_id,
                    amount_cents=int(receivable.amount_cents),
                    capital_version=snapshot.capital_version,
                    stream_version=context.current_stream_version(),
                )
                return receipt, snapshot

            if request.tier is not SourceAuthorityTier.CONFIRMED:
                raise CapitalConflict(
                    "source_authority_insufficient",
                    "cash settlement is a confirmed broker/legal fact",
                    action_id=request.action_id,
                    tier=request.tier.value,
                )
            ex_effective_at = parse_utc(row.ex_effective_at)
            if request.effective_at < ex_effective_at:
                raise CapitalConflict(
                    "corporate_action_ordering_violation",
                    "the pay date cannot precede the ex date",
                    action_id=request.action_id,
                )

            amount_cents = int(receivable.amount_cents)
            payload = CapitalCommandPayload(
                event_kind=EconomicEventKind.DIVIDEND_CASH_SETTLED,
                effective_at=request.effective_at,
                source_authority=request.source_authority,
                position_lineage_id=request.position_lineage_id,
                economic_lot_id=request.economic_lot_id,
                legs=(
                    CashReceivableEconomicEventLeg(
                        leg_id=f"{idempotency_key}:receivable",
                        direction=EconomicLegDirection.DEBIT,
                        asset_kind=EconomicAssetKind.CASH_RECEIVABLE,
                        receivable_id=receivable_id,
                        security_id=receivable.security_id,
                        cash_amount=Decimal(amount_cents) / CENT_SCALE,
                    ),
                    CashEconomicEventLeg(
                        leg_id=f"{idempotency_key}:cash",
                        direction=EconomicLegDirection.CREDIT,
                        asset_kind=EconomicAssetKind.CASH,
                        cash_amount=Decimal(amount_cents) / CENT_SCALE,
                    ),
                ),
                corporate_action=CorporateActionFact(
                    action_id=request.action_id,
                    action_kind=CorporateActionKind(row.action_kind),
                    revision=int(row.revision),
                    tier=request.tier,
                    superseded_receivable_id=receivable_id,
                    superseded_amount_cents=amount_cents,
                ),
            )
            command = CapitalCommand(
                idempotency_key=idempotency_key,
                account_binding=binding,
                expected_stream_version=request.expected_stream_version,
                as_of=request.as_of,
                payload=payload,
            )
            event_id = derive_event_id(idempotency_key)

            def update_row(tx: GatewayTransactionContext) -> None:
                tx._connection.execute(
                    tx._table("corporate_actions").update()
                    .where(
                        sa.and_(
                            tx._table("corporate_actions").c.action_id
                            == request.action_id,
                            tx._table("corporate_actions")
                            .c.position_lineage_id
                            == request.position_lineage_id,
                            tx._table("corporate_actions").c.economic_lot_id
                            == request.economic_lot_id,
                        )
                    )
                    .values(
                        state=CorporateActionState.CASH_SETTLED.value,
                        source_authority_tier=request.tier.value,
                        source_authority=request.source_authority,
                        pay_effective_at=utc_iso(request.effective_at),
                        updated_by_event_id=event_id,
                        updated_at=utc_iso(request.as_of),
                    )
                )

            snapshot = context.run_append(
                command,
                after_event_insert_hook=None,
                after_projection_hook=update_row,
            )
            receipt = CashInLieuReceipt(
                action_id=request.action_id,
                receivable_id=receivable_id,
                event_id=event_id,
                amount_cents=amount_cents,
                capital_version=snapshot.capital_version,
                stream_version=context.current_stream_version(),
            )
            return receipt, snapshot

        return self._run_write_transaction(operation)

    def make_shares_tradable(
        self, request: SharesTradableRequest
    ) -> tuple[SharesTradableReceipt, CapitalRiskSnapshot]:
        """Move the action's vested share receivable into settled tradable
        shares on the tradable date.

        Represented as a same-security SECURITY_CONVERTED representation
        change: the debit/credit pair nets to zero settled shares while
        the share receivable debit moves the vested shares into settled
        tradable quantity (never consuming pre-existing settled shares).
        """

        def operation(
            context: GatewayTransactionContext,
        ) -> tuple[SharesTradableReceipt, CapitalRiskSnapshot]:
            binding = self._stored_binding(context)
            context.require_lifecycle(
                frozenset(
                    {
                        LifecycleState.ACTIVE,
                        LifecycleState.TERMINATING,
                        LifecycleState.INSOLVENT,
                    }
                )
            )
            row = context.corporate_action_row(
                request.action_id,
                request.position_lineage_id,
                request.economic_lot_id,
            )
            if row is None:
                raise CapitalConflict(
                    "corporate_action_unknown",
                    "tradable date references no recorded corporate action",
                    action_id=request.action_id,
                )
            if row.action_kind not in (
                CorporateActionKind.SHARE_ENTITLEMENT.value,
                CorporateActionKind.SECURITY_CONVERSION.value,
            ):
                raise CapitalConflict(
                    "corporate_action_kind_conflict",
                    "tradable dates apply to share entitlements and"
                    " restricted conversions only",
                    action_id=request.action_id,
                    action_kind=row.action_kind,
                )
            receivable_id = row.receivable_id
            receivable = (
                context.receivable_row(receivable_id)
                if receivable_id is not None
                else None
            )
            if receivable is None or receivable.receivable_kind != "SHARE":
                raise CapitalConflict(
                    "corporate_action_nothing_to_settle",
                    "the action carries no share receivable",
                    action_id=request.action_id,
                )
            idempotency_key = tradable_idempotency_key(receivable_id)
            if int(receivable.settled) != 0:
                existing = self._economic_event_row(context, idempotency_key)
                if existing is None:
                    raise CapitalConflict(
                        "corporate_action_settlement_conflict",
                        "share receivable settled outside this tradable fact",
                        receivable_id=receivable_id,
                    )
                snapshot = context.read_capital_risk_snapshot(request.as_of)
                receipt = SharesTradableReceipt(
                    action_id=request.action_id,
                    receivable_id=receivable_id,
                    event_id=existing.economic_event_id,
                    quantity=int(receivable.quantity_units),
                    shares_became_tradable_at=parse_utc(
                        row.tradable_effective_at
                    ),
                    capital_version=snapshot.capital_version,
                    stream_version=context.current_stream_version(),
                )
                return receipt, snapshot

            if request.tier is not SourceAuthorityTier.CONFIRMED:
                raise CapitalConflict(
                    "source_authority_insufficient",
                    "tradable dates are confirmed exchange facts",
                    action_id=request.action_id,
                    tier=request.tier.value,
                )
            ex_effective_at = parse_utc(row.ex_effective_at)
            if request.effective_at < ex_effective_at:
                raise CapitalConflict(
                    "corporate_action_ordering_violation",
                    "the tradable date cannot precede the ex date",
                    action_id=request.action_id,
                )

            quantity = int(receivable.quantity_units)
            security_id = receivable.security_id
            position = context.position_row(
                request.position_lineage_id, request.economic_lot_id
            )
            if position is None:
                raise CapitalConflict(
                    "lot_unknown",
                    "tradable date references an unknown economic lot",
                    economic_lot_id=request.economic_lot_id,
                )
            payload = CapitalCommandPayload(
                event_kind=EconomicEventKind.SECURITY_CONVERTED,
                effective_at=request.effective_at,
                source_authority=request.source_authority,
                position_lineage_id=request.position_lineage_id,
                economic_lot_id=request.economic_lot_id,
                legs=(
                    SecurityEconomicEventLeg(
                        leg_id=f"{idempotency_key}:source",
                        direction=EconomicLegDirection.DEBIT,
                        asset_kind=EconomicAssetKind.SECURITY,
                        security_id=security_id,
                        quantity=quantity,
                    ),
                    SecurityEconomicEventLeg(
                        leg_id=f"{idempotency_key}:tradable",
                        direction=EconomicLegDirection.CREDIT,
                        asset_kind=EconomicAssetKind.SECURITY,
                        security_id=security_id,
                        quantity=quantity,
                    ),
                    ShareReceivableEconomicEventLeg(
                        leg_id=f"{idempotency_key}:receivable",
                        direction=EconomicLegDirection.DEBIT,
                        asset_kind=EconomicAssetKind.SHARE_RECEIVABLE,
                        receivable_id=receivable_id,
                        security_id=security_id,
                        quantity=quantity,
                    ),
                ),
                producer_namespace=position.producer_namespace,
                research_program_id=position.research_program_id,
                economic_lineage_id=position.economic_lineage_id,
                stage_id=position.stage_id,
                corporate_action=CorporateActionFact(
                    action_id=request.action_id,
                    action_kind=CorporateActionKind(row.action_kind),
                    revision=int(row.revision),
                    tier=request.tier,
                    superseded_receivable_id=receivable_id,
                    superseded_quantity_units=quantity,
                ),
            )
            command = CapitalCommand(
                idempotency_key=idempotency_key,
                account_binding=binding,
                expected_stream_version=request.expected_stream_version,
                as_of=request.as_of,
                payload=payload,
            )
            event_id = derive_event_id(idempotency_key)

            def update_row(tx: GatewayTransactionContext) -> None:
                tx._connection.execute(
                    tx._table("corporate_actions").update()
                    .where(
                        sa.and_(
                            tx._table("corporate_actions").c.action_id
                            == request.action_id,
                            tx._table("corporate_actions")
                            .c.position_lineage_id
                            == request.position_lineage_id,
                            tx._table("corporate_actions").c.economic_lot_id
                            == request.economic_lot_id,
                        )
                    )
                    .values(
                        state=CorporateActionState.SHARES_TRADABLE.value,
                        source_authority_tier=request.tier.value,
                        source_authority=request.source_authority,
                        tradable_effective_at=utc_iso(request.effective_at),
                        updated_by_event_id=event_id,
                        updated_at=utc_iso(request.as_of),
                    )
                )

            snapshot = context.run_append(
                command,
                after_event_insert_hook=None,
                after_projection_hook=update_row,
            )
            receipt = SharesTradableReceipt(
                action_id=request.action_id,
                receivable_id=receivable_id,
                event_id=event_id,
                quantity=quantity,
                shares_became_tradable_at=request.effective_at,
                capital_version=snapshot.capital_version,
                stream_version=context.current_stream_version(),
            )
            return receipt, snapshot

        return self._run_write_transaction(operation)

    def apply_split_merge(
        self, request: SplitMergeRequest
    ) -> tuple[SplitMergeReceipt, CapitalRiskSnapshot]:
        """Transform lot quantity with the aggregate basis preserved.

        The ratio must divide the settled quantity exactly (the kernel has
        no frozen fractional-share rounding policy); the per-share basis
        becomes the exact rational ``basis / new_quantity``. Position state
        is preserved, so a due exit obligation survives the split/merge.
        """

        def operation(
            context: GatewayTransactionContext,
        ) -> tuple[SplitMergeReceipt, CapitalRiskSnapshot]:
            binding = self._stored_binding(context)
            context.require_lifecycle(
                frozenset(
                    {
                        LifecycleState.ACTIVE,
                        LifecycleState.TERMINATING,
                        LifecycleState.INSOLVENT,
                    }
                )
            )
            position = context.position_row(
                request.position_lineage_id, request.economic_lot_id
            )
            if position is None:
                raise CapitalConflict(
                    "lot_unknown",
                    "split/merge references an unknown economic lot",
                    economic_lot_id=request.economic_lot_id,
                )
            if position.state not in (
                PositionState.OPEN.value,
                PositionState.EXIT_PENDING.value,
            ):
                raise CapitalConflict(
                    "lot_not_live",
                    "split/merge against a terminal economic lot",
                    economic_lot_id=request.economic_lot_id,
                    state=position.state,
                )
            if position.security_id != request.security_id:
                raise CapitalConflict(
                    "security_mismatch",
                    "split/merge security does not match the economic lot",
                    economic_lot_id=request.economic_lot_id,
                )
            if (
                context._connection.execute(
                    sa.text(
                        "SELECT 1 FROM receivables"
                        " WHERE receivable_kind = 'SHARE' AND settled = 0"
                        " AND position_lineage_id = :lineage LIMIT 1"
                    ),
                    {"lineage": request.position_lineage_id},
                ).first()
                is not None
            ):
                raise CapitalConflict(
                    "entitlement_pending",
                    "split/merge while a share entitlement receivable is"
                    " unsettled; make the shares tradable first",
                    economic_lot_id=request.economic_lot_id,
                )
            split_kind = request.action_kind is CorporateActionKind.SPLIT
            ratio_gt_one = (
                request.ratio.numerator > request.ratio.denominator
            )
            if split_kind != ratio_gt_one:
                raise CapitalConflict(
                    "split_ratio_conflict",
                    "split ratios must exceed one and merge ratios must be"
                    " below one",
                    action_kind=request.action_kind.value,
                )

            prior_quantity = int(position.settled_quantity_units)
            basis_cents = int(position.cost_basis_cents)
            idempotency_key = split_merge_idempotency_key(
                request.action_id,
                request.position_lineage_id,
                request.economic_lot_id,
            )
            existing = self._economic_event_row(context, idempotency_key)
            if existing is not None:
                committed_payload = CapitalCommandPayload.model_validate_json(
                    existing.payload_json
                )
                fact = committed_payload.corporate_action
                assert fact is not None
                self._require_fact_fields_match(
                    (
                        ("action_kind", request.action_kind, fact.action_kind),
                        ("ratio", request.ratio, fact.entitlement),
                        ("tier", request.tier, fact.tier),
                    )
                )
                snapshot = context.read_capital_risk_snapshot(request.as_of)
                committed_prior = int(fact.recorded_quantity_units or 0)
                new_quantity = exact_quantity(
                    committed_prior,
                    request.ratio.numerator,
                    request.ratio.denominator,
                )
                basis_num, basis_den = lowest_terms(
                    basis_cents, new_quantity
                )
                receipt = SplitMergeReceipt(
                    action_id=request.action_id,
                    event_id=existing.economic_event_id,
                    prior_quantity=committed_prior,
                    new_quantity=new_quantity,
                    cost_basis_cents=basis_cents,
                    per_share_basis_numerator=basis_num,
                    per_share_basis_denominator=basis_den,
                    capital_version=snapshot.capital_version,
                    stream_version=context.current_stream_version(),
                )
                return receipt, snapshot

            try:
                new_quantity = exact_quantity(
                    prior_quantity,
                    request.ratio.numerator,
                    request.ratio.denominator,
                )
            except ValueError as exc:
                raise CapitalConflict(
                    "split_quantity_not_exact",
                    "ratio does not divide the lot quantity into exact"
                    " share units",
                    detail=str(exc),
                ) from exc

            payload = CapitalCommandPayload(
                event_kind=EconomicEventKind.SPLIT
                if split_kind
                else EconomicEventKind.MERGE,
                effective_at=request.effective_at,
                source_authority=request.source_authority,
                position_lineage_id=request.position_lineage_id,
                economic_lot_id=request.economic_lot_id,
                legs=(
                    SecurityEconomicEventLeg(
                        leg_id=f"{idempotency_key}:prior",
                        direction=EconomicLegDirection.DEBIT,
                        asset_kind=EconomicAssetKind.SECURITY,
                        security_id=request.security_id,
                        quantity=prior_quantity,
                    ),
                    SecurityEconomicEventLeg(
                        leg_id=f"{idempotency_key}:new",
                        direction=EconomicLegDirection.CREDIT,
                        asset_kind=EconomicAssetKind.SECURITY,
                        security_id=request.security_id,
                        quantity=new_quantity,
                    ),
                ),
                producer_namespace=position.producer_namespace,
                research_program_id=position.research_program_id,
                economic_lineage_id=position.economic_lineage_id,
                stage_id=position.stage_id,
                corporate_action=CorporateActionFact(
                    action_id=request.action_id,
                    action_kind=request.action_kind,
                    revision=1,
                    tier=request.tier,
                    entitlement=request.ratio,
                    recorded_quantity_units=prior_quantity,
                ),
            )
            command = CapitalCommand(
                idempotency_key=idempotency_key,
                account_binding=binding,
                expected_stream_version=request.expected_stream_version,
                as_of=request.as_of,
                payload=payload,
            )
            event_id = derive_event_id(idempotency_key)

            def insert_row(tx: GatewayTransactionContext) -> None:
                tx._connection.execute(
                    tx._table("corporate_actions").insert().values(
                        action_id=request.action_id,
                        position_lineage_id=request.position_lineage_id,
                        economic_lot_id=request.economic_lot_id,
                        action_kind=request.action_kind.value,
                        state=CorporateActionState.APPLIED.value,
                        source_authority_tier=request.tier.value,
                        source_authority=request.source_authority,
                        security_id=request.security_id,
                        revision=1,
                        entitlement_numerator=request.ratio.numerator,
                        entitlement_denominator=request.ratio.denominator,
                        fractional_remainder_numerator=None,
                        fractional_remainder_denominator=None,
                        cash_in_lieu_cents=None,
                        receivable_id=None,
                        cash_in_lieu_receivable_id=None,
                        ex_effective_at=utc_iso(request.effective_at),
                        pay_effective_at=None,
                        tradable_effective_at=None,
                        successor_security_id=None,
                        successor_quantity_units=None,
                        successor_receivable_id=None,
                        inherited_position_state=None,
                        opened_by_event_id=event_id,
                        updated_by_event_id=event_id,
                        updated_at=utc_iso(request.as_of),
                    )
                )

            snapshot = context.run_append(
                command,
                after_event_insert_hook=None,
                after_projection_hook=insert_row,
            )
            basis_num, basis_den = lowest_terms(basis_cents, new_quantity)
            receipt = SplitMergeReceipt(
                action_id=request.action_id,
                event_id=event_id,
                prior_quantity=prior_quantity,
                new_quantity=new_quantity,
                cost_basis_cents=basis_cents,
                per_share_basis_numerator=basis_num,
                per_share_basis_denominator=basis_den,
                capital_version=snapshot.capital_version,
                stream_version=context.current_stream_version(),
            )
            return receipt, snapshot

        return self._run_write_transaction(operation)

    def convert_security(
        self, request: ConversionRequest
    ) -> tuple[ConversionReceipt, CapitalRiskSnapshot]:
        """Convert a whole economic lot into a successor security.

        The successor inherits the lot identity, entry provenance,
        attribution, cost basis, and the due exit obligation (position
        state is preserved through the conversion and recorded on the
        action row for Task 6 / Plan 04 consumption).
        """

        def operation(
            context: GatewayTransactionContext,
        ) -> tuple[ConversionReceipt, CapitalRiskSnapshot]:
            binding = self._stored_binding(context)
            context.require_lifecycle(
                frozenset(
                    {
                        LifecycleState.ACTIVE,
                        LifecycleState.TERMINATING,
                        LifecycleState.INSOLVENT,
                    }
                )
            )
            position = context.position_row(
                request.position_lineage_id, request.economic_lot_id
            )
            if position is None:
                raise CapitalConflict(
                    "lot_unknown",
                    "conversion references an unknown economic lot",
                    economic_lot_id=request.economic_lot_id,
                )
            if position.state not in (
                PositionState.OPEN.value,
                PositionState.EXIT_PENDING.value,
            ):
                raise CapitalConflict(
                    "lot_not_live",
                    "conversion against a terminal economic lot",
                    economic_lot_id=request.economic_lot_id,
                    state=position.state,
                )
            if position.security_id != request.source_security_id:
                raise CapitalConflict(
                    "security_mismatch",
                    "conversion source security does not match the lot",
                    economic_lot_id=request.economic_lot_id,
                )
            if request.successor_security_id == request.source_security_id:
                raise CapitalConflict(
                    "conversion_identity_conflict",
                    "successor security must differ from the source",
                    security_id=request.source_security_id,
                )
            outstanding_shares = (
                self._outstanding_lot_share_receivable_rows(
                    context,
                    request.position_lineage_id,
                    request.economic_lot_id,
                )
            )
            if (
                request.destination is ConversionDestination.RESTRICTED
                and outstanding_shares
            ):
                raise CapitalConflict(
                    "entitlement_pending",
                    "restricted conversions cannot sweep outstanding share"
                    " receivables; make the shares tradable first",
                    economic_lot_id=request.economic_lot_id,
                )

            prior_settled = int(position.settled_quantity_units)
            prior_receivable = int(position.share_receivable_quantity_units)
            total_held = prior_settled + prior_receivable
            basis_cents = int(position.cost_basis_cents)
            idempotency_key = conversion_idempotency_key(
                request.action_id,
                request.position_lineage_id,
                request.economic_lot_id,
            )
            existing = self._economic_event_row(context, idempotency_key)
            if existing is not None:
                committed_payload = CapitalCommandPayload.model_validate_json(
                    existing.payload_json
                )
                fact = committed_payload.corporate_action
                assert fact is not None
                self._require_fact_fields_match(
                    (
                        ("ratio", request.ratio, fact.entitlement),
                        (
                            "successor_security_id",
                            request.successor_security_id,
                            fact.successor_security_id,
                        ),
                        ("destination", request.destination, fact.destination),
                        ("tier", request.tier, fact.tier),
                    )
                )
                snapshot = context.read_capital_risk_snapshot(request.as_of)
                committed_total = int(fact.recorded_quantity_units or 0)
                successor_quantity = exact_quantity(
                    committed_total,
                    request.ratio.numerator,
                    request.ratio.denominator,
                )
                # Reconstruct the committed prior split from the canonical
                # legs: the position row already carries the successor.
                committed_share_debits = sum(
                    int(leg.quantity)
                    for leg in committed_payload.legs
                    if leg.asset_kind is EconomicAssetKind.SHARE_RECEIVABLE
                    and leg.direction is EconomicLegDirection.DEBIT
                )
                receipt = ConversionReceipt(
                    action_id=request.action_id,
                    event_id=existing.economic_event_id,
                    source_security_id=request.source_security_id,
                    successor_security_id=request.successor_security_id,
                    prior_settled_quantity=(
                        committed_total - committed_share_debits
                    ),
                    prior_share_receivable_quantity=committed_share_debits,
                    successor_quantity=successor_quantity,
                    destination=request.destination,
                    successor_receivable_id=(
                        successor_share_receivable_id(
                            request.action_id,
                            request.position_lineage_id,
                            request.economic_lot_id,
                        )
                        if request.destination
                        is ConversionDestination.RESTRICTED
                        else None
                    ),
                    inherited_position_state=PositionState(position.state),
                    cost_basis_cents=basis_cents,
                    capital_version=snapshot.capital_version,
                    stream_version=context.current_stream_version(),
                )
                return receipt, snapshot

            try:
                successor_quantity = exact_quantity(
                    total_held,
                    request.ratio.numerator,
                    request.ratio.denominator,
                )
            except ValueError as exc:
                raise CapitalConflict(
                    "successor_quantity_not_exact",
                    "ratio does not divide the lot holding into exact"
                    " successor share units",
                    detail=str(exc),
                ) from exc
            if successor_quantity < 1:
                raise CapitalConflict(
                    "successor_quantity_not_exact",
                    "conversion rounds to zero successor shares",
                )

            legs: list[EconomicEventLeg] = [
                SecurityEconomicEventLeg(
                    leg_id=f"{idempotency_key}:source",
                    direction=EconomicLegDirection.DEBIT,
                    asset_kind=EconomicAssetKind.SECURITY,
                    security_id=request.source_security_id,
                    quantity=total_held,
                )
            ]
            for receivable in outstanding_shares:
                legs.append(
                    ShareReceivableEconomicEventLeg(
                        leg_id=(
                            f"{idempotency_key}:receivable:"
                            f"{receivable.receivable_id}"
                        ),
                        direction=EconomicLegDirection.DEBIT,
                        asset_kind=EconomicAssetKind.SHARE_RECEIVABLE,
                        receivable_id=receivable.receivable_id,
                        security_id=receivable.security_id,
                        quantity=int(receivable.quantity_units),
                    )
                )
            successor_receivable_id: str | None = None
            if request.destination is ConversionDestination.TRADABLE:
                legs.append(
                    SecurityEconomicEventLeg(
                        leg_id=f"{idempotency_key}:successor",
                        direction=EconomicLegDirection.CREDIT,
                        asset_kind=EconomicAssetKind.SECURITY,
                        security_id=request.successor_security_id,
                        quantity=successor_quantity,
                    )
                )
            else:
                successor_receivable_id = successor_share_receivable_id(
                    request.action_id,
                    request.position_lineage_id,
                    request.economic_lot_id,
                )
                legs.append(
                    ShareReceivableEconomicEventLeg(
                        leg_id=f"{idempotency_key}:successor-receivable",
                        direction=EconomicLegDirection.CREDIT,
                        asset_kind=EconomicAssetKind.SHARE_RECEIVABLE,
                        receivable_id=successor_receivable_id,
                        security_id=request.successor_security_id,
                        quantity=successor_quantity,
                    )
                )

            payload = CapitalCommandPayload(
                event_kind=EconomicEventKind.SECURITY_CONVERTED,
                effective_at=request.effective_at,
                source_authority=request.source_authority,
                position_lineage_id=request.position_lineage_id,
                economic_lot_id=request.economic_lot_id,
                legs=tuple(legs),
                producer_namespace=position.producer_namespace,
                research_program_id=position.research_program_id,
                economic_lineage_id=position.economic_lineage_id,
                stage_id=position.stage_id,
                corporate_action=CorporateActionFact(
                    action_id=request.action_id,
                    action_kind=CorporateActionKind.SECURITY_CONVERSION,
                    revision=1,
                    tier=request.tier,
                    entitlement=request.ratio,
                    recorded_quantity_units=total_held,
                    successor_security_id=request.successor_security_id,
                    destination=request.destination,
                ),
            )
            command = CapitalCommand(
                idempotency_key=idempotency_key,
                account_binding=binding,
                expected_stream_version=request.expected_stream_version,
                as_of=request.as_of,
                payload=payload,
            )
            event_id = derive_event_id(idempotency_key)

            def insert_row(tx: GatewayTransactionContext) -> None:
                tx._connection.execute(
                    tx._table("corporate_actions").insert().values(
                        action_id=request.action_id,
                        position_lineage_id=request.position_lineage_id,
                        economic_lot_id=request.economic_lot_id,
                        action_kind=(
                            CorporateActionKind.SECURITY_CONVERSION.value
                        ),
                        state=CorporateActionState.CONVERTED.value,
                        source_authority_tier=request.tier.value,
                        source_authority=request.source_authority,
                        security_id=request.source_security_id,
                        revision=1,
                        entitlement_numerator=request.ratio.numerator,
                        entitlement_denominator=request.ratio.denominator,
                        fractional_remainder_numerator=None,
                        fractional_remainder_denominator=None,
                        cash_in_lieu_cents=None,
                        receivable_id=successor_receivable_id,
                        cash_in_lieu_receivable_id=None,
                        ex_effective_at=utc_iso(request.effective_at),
                        pay_effective_at=None,
                        tradable_effective_at=None,
                        successor_security_id=request.successor_security_id,
                        successor_quantity_units=successor_quantity,
                        successor_receivable_id=successor_receivable_id,
                        inherited_position_state=position.state,
                        opened_by_event_id=event_id,
                        updated_by_event_id=event_id,
                        updated_at=utc_iso(request.as_of),
                    )
                )

            snapshot = context.run_append(
                command,
                after_event_insert_hook=None,
                after_projection_hook=insert_row,
            )
            receipt = ConversionReceipt(
                action_id=request.action_id,
                event_id=event_id,
                source_security_id=request.source_security_id,
                successor_security_id=request.successor_security_id,
                prior_settled_quantity=prior_settled,
                prior_share_receivable_quantity=prior_receivable,
                successor_quantity=successor_quantity,
                destination=request.destination,
                successor_receivable_id=successor_receivable_id,
                inherited_position_state=PositionState(position.state),
                cost_basis_cents=basis_cents,
                capital_version=snapshot.capital_version,
                stream_version=context.current_stream_version(),
            )
            return receipt, snapshot

        return self._run_write_transaction(operation)

    def settle_terminal_cash(
        self, request: TerminalCashRequest
    ) -> tuple[TerminalCashReceipt, CapitalRiskSnapshot]:
        """Legal terminal cash settlement of one lot (CORPORATE_CASH_SETTLED).

        One of the only two facts that may terminate a lot's economic
        obligation. Requires CONFIRMED authority; sweeps the whole settled
        quantity, every outstanding share receivable of the lot, and any
        cash receivables named by the request. The aggregate basis is
        consumed in full, so the master identity sees the proceeds as a
        realized result.
        """

        def operation(
            context: GatewayTransactionContext,
        ) -> tuple[TerminalCashReceipt, CapitalRiskSnapshot]:
            binding = self._stored_binding(context)
            context.require_lifecycle(
                frozenset(
                    {
                        LifecycleState.ACTIVE,
                        LifecycleState.TERMINATING,
                        LifecycleState.INSOLVENT,
                    }
                )
            )
            if request.tier is not SourceAuthorityTier.CONFIRMED:
                raise CapitalConflict(
                    "source_authority_insufficient",
                    "legal terminal settlement is a confirmed fact",
                    action_id=request.action_id,
                    tier=request.tier.value,
                )
            position = context.position_row(
                request.position_lineage_id, request.economic_lot_id
            )
            if position is None:
                raise CapitalConflict(
                    "lot_unknown",
                    "terminal settlement references an unknown economic lot",
                    economic_lot_id=request.economic_lot_id,
                )
            if position.state not in (
                PositionState.OPEN.value,
                PositionState.EXIT_PENDING.value,
            ):
                raise CapitalConflict(
                    "lot_not_live",
                    "terminal settlement against a terminal economic lot",
                    economic_lot_id=request.economic_lot_id,
                    state=position.state,
                )
            if position.security_id != request.security_id:
                raise CapitalConflict(
                    "security_mismatch",
                    "terminal settlement security does not match the lot",
                    economic_lot_id=request.economic_lot_id,
                )

            idempotency_key = terminal_cash_idempotency_key(
                request.action_id,
                request.position_lineage_id,
                request.economic_lot_id,
            )
            existing = self._economic_event_row(context, idempotency_key)
            if existing is not None:
                committed_payload = CapitalCommandPayload.model_validate_json(
                    existing.payload_json
                )
                fact = committed_payload.corporate_action
                assert fact is not None
                self._require_fact_fields_match(
                    (
                        (
                            "proceeds_cents",
                            request.proceeds_cents,
                            fact.proceeds_cents,
                        ),
                        ("tier", request.tier, fact.tier),
                    )
                )
                snapshot = context.read_capital_risk_snapshot(request.as_of)
                consumed = int(fact.superseded_amount_cents or 0)
                receipt = TerminalCashReceipt(
                    action_id=request.action_id,
                    event_id=existing.economic_event_id,
                    proceeds_cents=request.proceeds_cents,
                    swept_quantity=int(fact.recorded_quantity_units or 0),
                    consumed_basis_cents=consumed,
                    realized_pnl_cents=request.proceeds_cents - consumed,
                    capital_version=snapshot.capital_version,
                    stream_version=context.current_stream_version(),
                )
                return receipt, snapshot

            settled = int(position.settled_quantity_units)
            share_receivable = int(position.share_receivable_quantity_units)
            basis_cents = int(position.cost_basis_cents)
            outstanding_shares = (
                self._outstanding_lot_share_receivable_rows(
                    context,
                    request.position_lineage_id,
                    request.economic_lot_id,
                )
            )
            if share_receivable != sum(
                int(item.quantity_units) for item in outstanding_shares
            ):
                raise CapitalConflict(
                    "projection_rejected",
                    "share receivable projection drifted from its receivable"
                    " rows",
                    economic_lot_id=request.economic_lot_id,
                )

            legs: list[EconomicEventLeg] = [
                SecurityEconomicEventLeg(
                    leg_id=f"{idempotency_key}:security",
                    direction=EconomicLegDirection.DEBIT,
                    asset_kind=EconomicAssetKind.SECURITY,
                    security_id=request.security_id,
                    quantity=settled,
                )
            ]
            for receivable in outstanding_shares:
                legs.append(
                    ShareReceivableEconomicEventLeg(
                        leg_id=(
                            f"{idempotency_key}:share:"
                            f"{receivable.receivable_id}"
                        ),
                        direction=EconomicLegDirection.DEBIT,
                        asset_kind=EconomicAssetKind.SHARE_RECEIVABLE,
                        receivable_id=receivable.receivable_id,
                        security_id=receivable.security_id,
                        quantity=int(receivable.quantity_units),
                    )
                )
            for receivable_id in request.sweep_receivable_ids:
                receivable = context.receivable_row(receivable_id)
                if (
                    receivable is None
                    or receivable.receivable_kind != "CASH"
                    or int(receivable.settled) != 0
                    or receivable.position_lineage_id
                    != request.position_lineage_id
                ):
                    raise CapitalConflict(
                        "receivable_unknown",
                        "terminal settlement may only sweep outstanding lot"
                        " cash receivables",
                        receivable_id=receivable_id,
                    )
                legs.append(
                    CashReceivableEconomicEventLeg(
                        leg_id=(
                            f"{idempotency_key}:cash-receivable:"
                            f"{receivable_id}"
                        ),
                        direction=EconomicLegDirection.DEBIT,
                        asset_kind=EconomicAssetKind.CASH_RECEIVABLE,
                        receivable_id=receivable_id,
                        security_id=receivable.security_id,
                        cash_amount=(
                            Decimal(int(receivable.amount_cents)) / CENT_SCALE
                        ),
                    )
                )
            legs.append(
                CashEconomicEventLeg(
                    leg_id=f"{idempotency_key}:proceeds",
                    direction=EconomicLegDirection.CREDIT,
                    asset_kind=EconomicAssetKind.CASH,
                    cash_amount=(
                        Decimal(request.proceeds_cents) / CENT_SCALE
                    ),
                )
            )

            payload = CapitalCommandPayload(
                event_kind=EconomicEventKind.CORPORATE_CASH_SETTLED,
                effective_at=request.effective_at,
                source_authority=request.source_authority,
                position_lineage_id=request.position_lineage_id,
                economic_lot_id=request.economic_lot_id,
                legs=tuple(legs),
                producer_namespace=position.producer_namespace,
                research_program_id=position.research_program_id,
                economic_lineage_id=position.economic_lineage_id,
                stage_id=position.stage_id,
                corporate_action=CorporateActionFact(
                    action_id=request.action_id,
                    action_kind=CorporateActionKind.CASH_SETTLEMENT,
                    revision=1,
                    tier=request.tier,
                    recorded_quantity_units=settled + share_receivable,
                    superseded_amount_cents=basis_cents,
                    proceeds_cents=request.proceeds_cents,
                    legal_evidence_reference=(
                        request.legal_evidence_reference
                    ),
                ),
            )
            command = CapitalCommand(
                idempotency_key=idempotency_key,
                account_binding=binding,
                expected_stream_version=request.expected_stream_version,
                as_of=request.as_of,
                payload=payload,
            )
            event_id = derive_event_id(idempotency_key)

            def insert_row(tx: GatewayTransactionContext) -> None:
                tx._connection.execute(
                    tx._table("corporate_actions").insert().values(
                        action_id=request.action_id,
                        position_lineage_id=request.position_lineage_id,
                        economic_lot_id=request.economic_lot_id,
                        action_kind=CorporateActionKind.CASH_SETTLEMENT.value,
                        state=CorporateActionState.TERMINAL_SETTLED.value,
                        source_authority_tier=request.tier.value,
                        source_authority=request.source_authority,
                        security_id=request.security_id,
                        revision=1,
                        entitlement_numerator=None,
                        entitlement_denominator=None,
                        fractional_remainder_numerator=None,
                        fractional_remainder_denominator=None,
                        cash_in_lieu_cents=None,
                        receivable_id=None,
                        cash_in_lieu_receivable_id=None,
                        ex_effective_at=utc_iso(request.effective_at),
                        pay_effective_at=utc_iso(request.effective_at),
                        tradable_effective_at=None,
                        successor_security_id=None,
                        successor_quantity_units=None,
                        successor_receivable_id=None,
                        inherited_position_state=None,
                        opened_by_event_id=event_id,
                        updated_by_event_id=event_id,
                        updated_at=utc_iso(request.as_of),
                    )
                )

            snapshot = context.run_append(
                command,
                after_event_insert_hook=None,
                after_projection_hook=insert_row,
            )
            receipt = TerminalCashReceipt(
                action_id=request.action_id,
                event_id=event_id,
                proceeds_cents=request.proceeds_cents,
                swept_quantity=settled + share_receivable,
                consumed_basis_cents=basis_cents,
                realized_pnl_cents=request.proceeds_cents - basis_cents,
                capital_version=snapshot.capital_version,
                stream_version=context.current_stream_version(),
            )
            return receipt, snapshot

        return self._run_write_transaction(operation)

    def legal_write_off(
        self, request: WriteOffRequest
    ) -> tuple[WriteOffReceipt, CapitalRiskSnapshot]:
        """Legal derecognition of a worthless lot (LEGAL_WRITE_OFF).

        The second of the only two facts that may terminate a lot's
        economic obligation. Requires CONFIRMED authority and an explicit
        legal evidence reference. The remaining basis leaves as a realized
        loss with zero proceeds; swept entitlement receivables reverse the
        income that was never paid.
        """

        def operation(
            context: GatewayTransactionContext,
        ) -> tuple[WriteOffReceipt, CapitalRiskSnapshot]:
            binding = self._stored_binding(context)
            context.require_lifecycle(
                frozenset(
                    {
                        LifecycleState.ACTIVE,
                        LifecycleState.TERMINATING,
                        LifecycleState.INSOLVENT,
                    }
                )
            )
            if request.tier is not SourceAuthorityTier.CONFIRMED:
                raise CapitalConflict(
                    "source_authority_insufficient",
                    "legal write-off is a confirmed fact",
                    action_id=request.action_id,
                    tier=request.tier.value,
                )
            position = context.position_row(
                request.position_lineage_id, request.economic_lot_id
            )
            if position is None:
                raise CapitalConflict(
                    "lot_unknown",
                    "write-off references an unknown economic lot",
                    economic_lot_id=request.economic_lot_id,
                )
            if position.state not in (
                PositionState.OPEN.value,
                PositionState.EXIT_PENDING.value,
            ):
                raise CapitalConflict(
                    "lot_not_live",
                    "write-off against a terminal economic lot",
                    economic_lot_id=request.economic_lot_id,
                    state=position.state,
                )
            if position.security_id != request.security_id:
                raise CapitalConflict(
                    "security_mismatch",
                    "write-off security does not match the lot",
                    economic_lot_id=request.economic_lot_id,
                )

            idempotency_key = write_off_idempotency_key(
                request.action_id,
                request.position_lineage_id,
                request.economic_lot_id,
            )
            existing = self._economic_event_row(context, idempotency_key)
            if existing is not None:
                committed_payload = CapitalCommandPayload.model_validate_json(
                    existing.payload_json
                )
                fact = committed_payload.corporate_action
                assert fact is not None
                self._require_fact_fields_match(
                    (
                        ("tier", request.tier, fact.tier),
                        (
                            "legal_evidence_reference",
                            request.legal_evidence_reference,
                            fact.legal_evidence_reference,
                        ),
                    )
                )
                snapshot = context.read_capital_risk_snapshot(request.as_of)
                written_off = int(fact.recorded_quantity_units or 0)
                share_written = int(fact.superseded_quantity_units or 0)
                receipt = WriteOffReceipt(
                    action_id=request.action_id,
                    event_id=existing.economic_event_id,
                    written_off_quantity=written_off,
                    share_receivable_written_off=share_written,
                    written_off_basis_cents=int(
                        fact.superseded_amount_cents or 0
                    ),
                    receivables_written_off=tuple(
                        leg.receivable_id
                        for leg in committed_payload.legs
                        if leg.asset_kind
                        is EconomicAssetKind.CASH_RECEIVABLE
                    ),
                    capital_version=snapshot.capital_version,
                    stream_version=context.current_stream_version(),
                )
                return receipt, snapshot

            settled = int(position.settled_quantity_units)
            share_receivable = int(position.share_receivable_quantity_units)
            basis_cents = int(position.cost_basis_cents)
            outstanding_shares = (
                self._outstanding_lot_share_receivable_rows(
                    context,
                    request.position_lineage_id,
                    request.economic_lot_id,
                )
            )
            if settled == 0 and not outstanding_shares and not (
                request.sweep_receivable_ids
            ):
                raise CapitalConflict(
                    "corporate_action_nothing_to_settle",
                    "write-off requires remaining shares or receivables",
                    economic_lot_id=request.economic_lot_id,
                )

            legs: list[EconomicEventLeg] = []
            if settled > 0:
                legs.append(
                    SecurityEconomicEventLeg(
                        leg_id=f"{idempotency_key}:security",
                        direction=EconomicLegDirection.DEBIT,
                        asset_kind=EconomicAssetKind.SECURITY,
                        security_id=request.security_id,
                        quantity=settled,
                    )
                )
            for receivable in outstanding_shares:
                legs.append(
                    ShareReceivableEconomicEventLeg(
                        leg_id=(
                            f"{idempotency_key}:share:"
                            f"{receivable.receivable_id}"
                        ),
                        direction=EconomicLegDirection.DEBIT,
                        asset_kind=EconomicAssetKind.SHARE_RECEIVABLE,
                        receivable_id=receivable.receivable_id,
                        security_id=receivable.security_id,
                        quantity=int(receivable.quantity_units),
                    )
                )
            receivables_written_off: list[str] = []
            for receivable_id in request.sweep_receivable_ids:
                receivable = context.receivable_row(receivable_id)
                if (
                    receivable is None
                    or receivable.receivable_kind != "CASH"
                    or int(receivable.settled) != 0
                    or receivable.position_lineage_id
                    != request.position_lineage_id
                ):
                    raise CapitalConflict(
                        "receivable_unknown",
                        "write-off may only sweep outstanding lot cash"
                        " receivables",
                        receivable_id=receivable_id,
                    )
                receivables_written_off.append(receivable_id)
                legs.append(
                    CashReceivableEconomicEventLeg(
                        leg_id=(
                            f"{idempotency_key}:cash-receivable:"
                            f"{receivable_id}"
                        ),
                        direction=EconomicLegDirection.DEBIT,
                        asset_kind=EconomicAssetKind.CASH_RECEIVABLE,
                        receivable_id=receivable_id,
                        security_id=receivable.security_id,
                        cash_amount=(
                            Decimal(int(receivable.amount_cents)) / CENT_SCALE
                        ),
                    )
                )

            payload = CapitalCommandPayload(
                event_kind=EconomicEventKind.LEGAL_WRITE_OFF,
                effective_at=request.effective_at,
                source_authority=request.source_authority,
                position_lineage_id=request.position_lineage_id,
                economic_lot_id=request.economic_lot_id,
                legs=tuple(legs),
                producer_namespace=position.producer_namespace,
                research_program_id=position.research_program_id,
                economic_lineage_id=position.economic_lineage_id,
                stage_id=position.stage_id,
                corporate_action=CorporateActionFact(
                    action_id=request.action_id,
                    action_kind=CorporateActionKind.LEGAL_WRITE_OFF,
                    revision=1,
                    tier=request.tier,
                    recorded_quantity_units=settled,
                    superseded_quantity_units=share_receivable,
                    superseded_amount_cents=basis_cents,
                    legal_evidence_reference=(
                        request.legal_evidence_reference
                    ),
                ),
            )
            command = CapitalCommand(
                idempotency_key=idempotency_key,
                account_binding=binding,
                expected_stream_version=request.expected_stream_version,
                as_of=request.as_of,
                payload=payload,
            )
            event_id = derive_event_id(idempotency_key)

            def insert_row(tx: GatewayTransactionContext) -> None:
                tx._connection.execute(
                    tx._table("corporate_actions").insert().values(
                        action_id=request.action_id,
                        position_lineage_id=request.position_lineage_id,
                        economic_lot_id=request.economic_lot_id,
                        action_kind=(
                            CorporateActionKind.LEGAL_WRITE_OFF.value
                        ),
                        state=CorporateActionState.WRITTEN_OFF.value,
                        source_authority_tier=request.tier.value,
                        source_authority=request.source_authority,
                        security_id=request.security_id,
                        revision=1,
                        entitlement_numerator=None,
                        entitlement_denominator=None,
                        fractional_remainder_numerator=None,
                        fractional_remainder_denominator=None,
                        cash_in_lieu_cents=None,
                        receivable_id=None,
                        cash_in_lieu_receivable_id=None,
                        ex_effective_at=utc_iso(request.effective_at),
                        pay_effective_at=None,
                        tradable_effective_at=None,
                        successor_security_id=None,
                        successor_quantity_units=None,
                        successor_receivable_id=None,
                        inherited_position_state=None,
                        opened_by_event_id=event_id,
                        updated_by_event_id=event_id,
                        updated_at=utc_iso(request.as_of),
                    )
                )

            snapshot = context.run_append(
                command,
                after_event_insert_hook=None,
                after_projection_hook=insert_row,
            )
            receipt = WriteOffReceipt(
                action_id=request.action_id,
                event_id=event_id,
                written_off_quantity=settled,
                share_receivable_written_off=share_receivable,
                written_off_basis_cents=basis_cents,
                receivables_written_off=tuple(receivables_written_off),
                capital_version=snapshot.capital_version,
                stream_version=context.current_stream_version(),
            )
            return receipt, snapshot

        return self._run_write_transaction(operation)

    def corporate_action_record(
        self, action_id: str, position_lineage_id: str, economic_lot_id: str
    ) -> CorporateActionRecord | None:
        """Typed read of one corporate action projection row."""

        with self._engine.connect() as conn:
            context = GatewayTransactionContext(self, conn)
            row = context.corporate_action_row(
                action_id, position_lineage_id, economic_lot_id
            )
            if row is None:
                return None
            return _corporate_action_record(row)

    def corporate_action_records(self) -> tuple[CorporateActionRecord, ...]:
        """All corporate action projection rows in canonical order."""

        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT * FROM corporate_actions"
                    " ORDER BY position_lineage_id, economic_lot_id, action_id"
                )
            ).all()
        return tuple(_corporate_action_record(row) for row in rows)


def _corporate_action_record(row: Any) -> CorporateActionRecord:
    def rational(
        numerator: Any, denominator: Any
    ) -> tuple[int, int] | None:
        if numerator is None or denominator is None:
            return None
        return (int(numerator), int(denominator))

    return CorporateActionRecord(
        action_id=row.action_id,
        position_lineage_id=row.position_lineage_id,
        economic_lot_id=row.economic_lot_id,
        action_kind=CorporateActionKind(row.action_kind),
        state=CorporateActionState(row.state),
        source_authority_tier=SourceAuthorityTier(row.source_authority_tier),
        source_authority=row.source_authority,
        security_id=row.security_id,
        revision=int(row.revision),
        entitlement=rational(
            row.entitlement_numerator, row.entitlement_denominator
        ),
        fractional_remainder=rational(
            row.fractional_remainder_numerator,
            row.fractional_remainder_denominator,
        ),
        cash_in_lieu_cents=(
            int(row.cash_in_lieu_cents)
            if row.cash_in_lieu_cents is not None
            else None
        ),
        receivable_id=row.receivable_id,
        cash_in_lieu_receivable_id=row.cash_in_lieu_receivable_id,
        ex_effective_at=parse_utc(row.ex_effective_at),
        pay_effective_at=(
            parse_utc(row.pay_effective_at)
            if row.pay_effective_at is not None
            else None
        ),
        tradable_effective_at=(
            parse_utc(row.tradable_effective_at)
            if row.tradable_effective_at is not None
            else None
        ),
        successor_security_id=row.successor_security_id,
        successor_quantity_units=(
            int(row.successor_quantity_units)
            if row.successor_quantity_units is not None
            else None
        ),
        successor_receivable_id=row.successor_receivable_id,
        inherited_position_state=row.inherited_position_state,
        opened_by_event_id=row.opened_by_event_id,
        updated_by_event_id=row.updated_by_event_id,
        updated_at=parse_utc(row.updated_at),
    )
