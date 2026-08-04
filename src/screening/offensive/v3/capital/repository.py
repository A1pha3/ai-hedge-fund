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
from datetime import datetime
from decimal import Decimal
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
from src.screening.offensive.v3.capital.fees import (
    FeePolicy,
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
from src.screening.offensive.v3.capital.reserves import (
    CONFIRMED_RELEASE_REASONS,
    CapitalReserveState,
    ReserveEntryRequest,
    ReserveReleaseReason,
    ReserveReleaseRequest,
)
from src.screening.offensive.v3.capital.rounding import (
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
    ExecutionSide,
    ExposureScope,
    content_hash,
    PositionState,
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
    derive_risk_snapshot_id,
    drawdown_ppm,
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


class AccountBinding(CanonicalModel):
    """The immutable account/environment/currency identity of one ledger.

    One real broker account owns exactly one AccountCapitalTruth stream; the
    binding freezes portfolio, account, mode, base currency, and the
    account/environment fingerprint together.
    """

    portfolio_id: NonEmptyStr
    mode: ExecutionMode
    broker_account_id: NonEmptyStr | None
    base_currency: NonEmptyStr
    environment_fingerprint: Sha256 | None

    @model_validator(mode="after")
    def validate_binding(self) -> "AccountBinding":
        if self.mode is ExecutionMode.RESEARCH_RECONSTRUCTION:
            raise ValueError("research mode cannot bind executable capital truth")
        if self.mode is ExecutionMode.DAILY_BAR_PROXY:
            if self.broker_account_id is not None:
                raise ValueError("proxy mode cannot bind a real broker account")
        else:
            if self.broker_account_id is None:
                raise ValueError("manual and broker modes require an account")
            if self.environment_fingerprint is None:
                raise ValueError(
                    "manual and broker modes require an environment fingerprint"
                )
        return self


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

    @model_validator(mode="after")
    def validate_security_attribution(self) -> "CapitalCommandPayload":
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
                    lifecycle_state="ACTIVE",
                    bound_at=utc_iso(as_of),
                )
            )
            self._connection.execute(
                self._table("capital_projection").insert().values(
                    portfolio_id=binding.portfolio_id,
                    available_cash_cents=0,
                    restricted_cash_cents=0,
                    unsettled_cash_cents=0,
                    issued_unit_quanta=0,
                    pending_redeemed_unit_quanta=0,
                    as_observed_nav_cents=0,
                    lifetime_high_water_mark_cents=0,
                    active_epoch_high_water_mark_cents=0,
                    lifecycle_state="ACTIVE",
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
        values: dict[str, Any] = {
            "leg_id": leg.leg_id,
            "economic_event_id": event_id,
            "sequence": sequence,
            "asset_kind": leg.asset_kind.value,
            "direction": leg.direction.value,
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

    # -- risk / stage loss hook -------------------------------------------------

    def recompute_risk_and_stage_loss(self, as_of: datetime, event_id: str) -> None:
        projection = self._connection.execute(
            self._table("capital_projection").select()
        ).one()
        drawdown = drawdown_ppm(
            int(projection.as_observed_nav_cents),
            int(projection.lifetime_high_water_mark_cents),
        )
        halted = drawdown >= DRAWDOWN_HALT_PPM
        latch_state = RiskLatchState.RISK_HALTED if halted else RiskLatchState.CLEAR
        reason = (
            "drawdown reached the 15 percent halt threshold" if halted else None
        )
        self._connection.execute(
            sa.text(
                "INSERT INTO risk_latches (latch_kind, state, reason, set_at,"
                " set_by_event_id) VALUES ('RISK', :state, :reason, :set_at,"
                " :event_id)"
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

        # Reconciliation latch (Task 2 scope): unattributed or plan-violating
        # fills are preserved under sentinel attribution and flag the account
        # until reconciliation flattens them. The full halt/reopen semantics
        # for busts, corrections and negative positions remain Task 6.
        sentinel = self._connection.execute(
            sa.text(
                "SELECT COALESCE(SUM(settled_quantity_units), 0) AS units,"
                " COALESCE(SUM(cost_basis_cents), 0) AS basis"
                " FROM positions WHERE producer_namespace = :sentinel"
            ),
            {"sentinel": UNATTRIBUTED_PRODUCER},
        ).one()
        unattributed_exposure = int(sentinel.units) > 0 or int(sentinel.basis) > 0
        reconciliation_state = (
            ReconciliationLatchState.RECONCILIATION_HALT
            if unattributed_exposure
            else ReconciliationLatchState.CLEAR
        )
        reconciliation_reason = (
            "unattributed fill exposure pending reconciliation"
            if unattributed_exposure
            else None
        )
        self._connection.execute(
            sa.text(
                "INSERT INTO risk_latches (latch_kind, state, reason, set_at,"
                " set_by_event_id) VALUES ('RECONCILIATION', :state, :reason,"
                " :set_at, :event_id)"
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
        # capital transaction as fills/fees/marks/reserves by Task 5's
        # StageLossEngine. Kernel revision 1 has no frozen budget rows, so the
        # recompute is a no-op that keeps the hook atomic with the projection.

    def tombstone_unclaimed_entries_if_versions_changed(self) -> None:
        """Tombstone entry claims that never reached a send claim.

        Entry claim state (sealed/permitted/outbox/send-claim rows) lives in
        the Plan 04 gateway tables of this same database. Kernel revision 1
        registers no entry claims, so the sweep is a no-op; the hook and the
        ``entry_tombstones`` table are in place so that a capital version
        change atomically tombstones unclaimed entries once Plan 04 lands.
        """

        return None

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
                sa.text("SELECT COALESCE(SUM(amount_cents), 0) AS total FROM payables")
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
        # exposure until valuation marks arrive with Task 3/Task 5.
        unattributed_risk_cents = int(
            self._connection.execute(
                sa.text(
                    "SELECT COALESCE(SUM(cost_basis_cents), 0) AS total"
                    " FROM positions WHERE producer_namespace = :sentinel"
                ),
                {"sentinel": UNATTRIBUTED_PRODUCER},
            ).one().total
        )
        position_rows = self._connection.execute(
            sa.text(
                "SELECT * FROM positions"
                " WHERE state IN ('OPEN', 'EXIT_PENDING')"
                " ORDER BY position_lineage_id, economic_lot_id"
            )
        ).all()
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
                # Valuation marks arrive with Task 3/Task 5 close-valuation
                # events; kernel revision 1 carries the unmarked position.
                marked_gross_cents=0,
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
            completeness=RiskSnapshotCompleteness.COMPLETE,
            available_cash_cents=int(projection.available_cash_cents),
            restricted_cash_cents=int(projection.restricted_cash_cents),
            unsettled_cash_cents=int(projection.unsettled_cash_cents),
            cash_receivable_cents=cash_receivable_cents,
            cash_payable_cents=cash_payable_cents,
            subscription_suspense_cents=0,
            redemption_suspense_cents=0,
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


def _order_commission_state(
    connection: sa.engine.Connection,
    order_id: str,
    fee_rowid: int | None,
    policy: "FeePolicy",
) -> tuple[int, int]:
    """Per-order commission state around one fee revision.

    Returns ``(base_now, charged_before)``: the sum of per-fill commission
    bases (under ``policy``) over fills recorded before this fee revision
    row, and the commission actually charged by this order's earlier fee
    revisions. Rowid order is append order, so idempotent retries recompute
    the identical charge even after later fills land on the same order;
    using the actually-charged history keeps the minimum-commission rule
    exact across fee-policy version changes.
    """

    fill_rows = connection.execute(
        sa.text(
            "SELECT er.rowid AS registry_rowid,"
            " l.cash_amount_cents AS notional_cents,"
            " l.direction AS direction"
            " FROM execution_revisions er"
            " JOIN economic_events ee"
            " ON ee.payload_content_hash = er.payload_content_hash"
            " JOIN economic_event_legs l"
            " ON l.economic_event_id = ee.economic_event_id"
            " AND l.asset_kind = 'CASH'"
            " WHERE er.order_id = :order_id"
            " AND er.revision_kind = 'FILL'"
            " ORDER BY er.rowid"
        ),
        {"order_id": order_id},
    ).all()
    base_now = 0
    for row in fill_rows:
        if fee_rowid is not None and row.registry_rowid >= fee_rowid:
            break
        side = (
            ExecutionSide.ENTRY
            if row.direction == EconomicLegDirection.DEBIT.value
            else ExecutionSide.EXIT
        )
        components = compute_fee_components(
            int(row.notional_cents), side, policy
        )
        base_now += components.commission_base_cents

    charged_rows = connection.execute(
        sa.text(
            "SELECT l.cash_amount_cents AS commission_cents"
            " FROM execution_revisions er"
            " JOIN economic_events ee"
            " ON ee.payload_content_hash = er.payload_content_hash"
            " JOIN economic_event_legs l"
            " ON l.economic_event_id = ee.economic_event_id"
            " AND l.asset_kind = 'CASH'"
            " AND l.leg_id LIKE :commission_pattern"
            " WHERE er.order_id = :order_id"
            " AND er.revision_kind = 'FEE'"
            + (" AND er.rowid < :fee_rowid" if fee_rowid is not None else "")
        ),
        {
            "order_id": order_id,
            "fee_rowid": fee_rowid,
            "commission_pattern": "%:commission",
        },
    ).all()
    charged_before = sum(int(row.commission_cents) for row in charged_rows)
    return base_now, charged_before


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
    """Canonical identity of a zero-charge fee revision (no economic event)."""

    return content_hash(
        {
            "kind": "fee_revision_zero_charge",
            "fill_execution_id": request.fill_execution_id,
            "revision": request.revision,
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

    def reserve_entry(self, request: ReserveEntryRequest) -> CapitalRiskSnapshot:
        """Create a LIVE entry reserve consuming available capital."""

        def operation(context: GatewayTransactionContext) -> CapitalRiskSnapshot:
            conn = context._connection
            self._stored_binding(context)
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
    ) -> tuple[FillRevisionReceipt, CapitalRiskSnapshot]:
        """Record one broker execution report as a canonical economic event.

        One fact / one event: the fill's gross cash leg and security leg land
        atomically in one capital transaction. Unattributed fills and late
        fills after a confirmed cancel are preserved under sentinel
        attribution and flagged, never dropped.
        """

        if request.revision != 1:
            raise CapitalConflict(
                "unsupported_revision",
                "fill bust/correction revisions land in Plan 02 Task 6",
                revision=request.revision,
            )
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

    def record_fee_revision(
        self, request: FeeRevisionRequest
    ) -> tuple[FeeRevisionReceipt, CapitalRiskSnapshot]:
        """Record one fee revision linked to its fill as a DISTINCT event.

        The charge is engine-computed from the versioned fee policy and the
        order's fill history: commission base / stamp tax / transfer fee are
        each rounded half-even, and the per-order minimum commission is
        charged exactly once across partial fills.
        """

        if request.revision != 1:
            raise CapitalConflict(
                "unsupported_revision",
                "fee bust/correction revisions land in Plan 02 Task 6",
                revision=request.revision,
            )

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
                    event_id=None,
                    fee_policy_version=request.fee_policy.fee_policy_version,
                    commission_cents=0,
                    stamp_tax_cents=0,
                    transfer_fee_cents=0,
                    total_cents=0,
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
                event_id=derive_event_id(idempotency_key),
                fee_policy_version=request.fee_policy.fee_policy_version,
                commission_cents=commission_cents,
                stamp_tax_cents=components.stamp_tax_cents,
                transfer_fee_cents=components.transfer_fee_cents,
                total_cents=total_cents,
                capital_version=snapshot.capital_version,
                stream_version=context.current_stream_version(),
            )
            return receipt, snapshot

        return self._run_write_transaction(operation)

    def assert_conservation(self) -> ConservationReport:
        """Recompute every projection from history; fail loudly on drift."""

        with self._engine.connect() as conn:
            with conn.begin():
                return verify_conservation(conn, self._metadata)
