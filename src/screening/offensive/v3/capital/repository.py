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
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Any, Callable, TypeAlias

import sqlalchemy as sa
from pydantic import Field, ValidationError, model_validator
from sqlalchemy.exc import DBAPIError, IntegrityError

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
    ExecutionMode,
    ExposureScope,
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
        new_settled = int(row.settled_quantity_units) - quantity
        new_tradable = int(row.tradable_quantity_units) - quantity
        if new_settled < 0 or new_tradable < 0:
            raise CapitalConflict(
                "projection_rejected",
                "security projection would become negative; impossible states are"
                " preserved for reconciliation, never clamped",
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
                updated_by_event_id=event.economic_event_id,
                updated_at=now,
            )
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
        latches_table = self._table("risk_latches")
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
        reserved_cash_cents = int(
            self._connection.execute(
                sa.text(
                    "SELECT COALESCE(SUM(reserved_entry_gross_cents), 0) AS total"
                    " FROM reserves"
                )
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
            entry_reserves=(),
            pending_stress_components=(),
            corporate_action_risk_components=(),
            unattributed_risk_cents=0,
            exposures=_exposure_buckets(binding_row.portfolio_id, components),
            total_gross_exposure_cents=sum(
                position.marked_gross_cents for position in components
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
        self.apply_legs_and_projection(event, command)
        self.recompute_risk_and_stage_loss(command.as_of, event.economic_event_id)
        self.tombstone_unclaimed_entries_if_versions_changed()
        return self.read_capital_risk_snapshot(command.as_of)


def _exposure_buckets(
    portfolio_id: str, components: tuple[CapitalPositionRisk, ...]
) -> tuple[RiskExposureBucket, ...]:
    """Build exposure buckets in the canonical identity order.

    The order mirrors ``canonical_exposure_identities``: GLOBAL, PORTFOLIO,
    then research program / economic lineage / stage buckets in first-seen
    component order. Kernel revision 1 components are unmarked positions, so
    live-order, reserve, pending-stress and corporate-action fields are zero
    until Tasks 2-5 populate them.
    """

    def bucket(
        scope: ExposureScope,
        pid: str | None,
        program: str | None,
        lineage: str | None,
        stage: str | None,
        marked_gross_cents: int,
    ) -> RiskExposureBucket:
        return RiskExposureBucket(
            scope=scope,
            portfolio_id=pid,
            research_program_id=program,
            economic_lineage_id=lineage,
            stage_id=stage,
            position_marked_gross_cents=marked_gross_cents,
            live_order_leaves_gross_cents=0,
            reserved_entry_gross_cents=0,
            pending_stress_cents=0,
            corporate_action_pending_risk_cents=0,
            unattributed_risk_cents=0,
            total_gross_cents=marked_gross_cents,
        )

    total_marked = sum(component.marked_gross_cents for component in components)
    buckets = [
        bucket(ExposureScope.GLOBAL, None, None, None, None, total_marked),
        bucket(ExposureScope.PORTFOLIO, portfolio_id, None, None, None, total_marked),
    ]

    program_order: list[str] = []
    lineage_by_program: dict[str, list[str]] = {}
    stage_by_lineage: dict[tuple[str, str], list[str]] = {}
    marked_by_program: dict[str, int] = {}
    marked_by_lineage: dict[tuple[str, str], int] = {}
    marked_by_stage: dict[tuple[str, str, str], int] = {}

    for component in components:
        program = component.research_program_id
        lineage = component.economic_lineage_id
        stage = component.stage_id
        if program not in lineage_by_program:
            program_order.append(program)
            lineage_by_program[program] = []
        if lineage not in lineage_by_program[program]:
            lineage_by_program[program].append(lineage)
            stage_by_lineage[(program, lineage)] = []
        if stage not in stage_by_lineage[(program, lineage)]:
            stage_by_lineage[(program, lineage)].append(stage)
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

    for program in program_order:
        buckets.append(
            bucket(
                ExposureScope.RESEARCH_PROGRAM,
                portfolio_id,
                program,
                None,
                None,
                marked_by_program[program],
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
                    marked_by_lineage[(program, lineage)],
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
                        marked_by_stage[(program, lineage, stage)],
                    )
                )
    return tuple(buckets)


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
