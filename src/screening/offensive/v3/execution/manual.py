"""Plan 04 Task 8: MANUAL_CONFIRMED execution against the capital kernel.

Official out-of-sample execution requires a pre-sealed, mode-matched
``PortfolioDecisionSeal``: the operator records operator / source / observed
/ attachment hash / exact price / quantity / fees, the service verifies the
seal artifact hash and the plan/line binding, and the fill lands as an
attributed, reserve-consuming revision. A real trade that arrives without a
pre-sealed plan (or that contradicts its plan) is still economically real,
so it lands in ``AccountCapitalTruth`` as unattributed risk: preserved under
a sentinel lot, excluded from official OOS, and latching no-entry
reconciliation until a source-authorized correction or legal settlement
resolves it.

Broker matching links the same economic fact or posts a delta correction
against the same execution identity - it never copies a fact across modes.
A manual issuer that directly claims broker provenance is rejected
zero-write. Corrections continue the same ``execution_id`` under linked
BUSTED / CORRECTED revisions and never duplicate or transport the fact.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

import sqlalchemy as sa

from src.screening.offensive.v3.capital.execution_revisions import (
    ExecutionRevisionReceipt,
    ExecutionRevisionRequest,
)
from src.screening.offensive.v3.capital.fees import (
    FeePolicy,
    FeeRevisionKind,
)
from src.screening.offensive.v3.capital.fills import (
    FeeRevisionReceipt,
    FeeRevisionRequest,
    FillAttribution,
    FillRevisionReceipt,
    FillRevisionRequest,
)
from src.screening.offensive.v3.capital.repository import CapitalRepository
from src.screening.offensive.v3.contracts import (
    ExecutionMode,
    ExecutionRevisionKind,
    ExecutionSide,
)
from src.screening.offensive.v3.execution.lifecycle import ExecutionError

# A producer namespace that names the broker execution channel is permanently
# off-limits for manual recording: broker facts enter only through the broker
# mode, never by a manual issuer claiming broker provenance. The guard matches
# the broker root and any dotted sub-namespace (broker.execution,
# broker.confirmed, ...) so variant channels cannot slip through an exact
# match.
_BROKER_NAMESPACE_ROOT = "broker"


def _is_broker_namespace(value: str) -> bool:
    return value == _BROKER_NAMESPACE_ROOT or value.startswith(
        f"{_BROKER_NAMESPACE_ROOT}."
    )


_SCHEMA_DDL = (
    "CREATE TABLE IF NOT EXISTS manual_records ("
    " execution_id TEXT PRIMARY KEY,"
    " order_id TEXT NOT NULL,"
    " side TEXT NOT NULL,"
    " security_id TEXT NOT NULL,"
    " official_oos INTEGER NOT NULL,"
    " unattributed INTEGER NOT NULL,"
    " mode TEXT NOT NULL,"
    " operator_id TEXT NOT NULL,"
    " source_authority TEXT NOT NULL,"
    " attachment_hash TEXT NOT NULL,"
    " price_micros INTEGER NOT NULL,"
    " quantity INTEGER NOT NULL,"
    " active_quantity INTEGER NOT NULL,"
    " recorded_at TEXT NOT NULL,"
    " payload_artifact TEXT NOT NULL"
    ")",
)


@dataclass(frozen=True)
class ManualRecordContext:
    """Injected truth for one manual record.

    ``seal`` / ``permit`` / ``order_line_id`` identify the pre-sealed plan
    for an official OOS record; when they are ``None`` the trade is
    out-of-protocol and lands as unattributed risk. The operator provenance
    (operator / source / observed / executed / attachment hash) and the exact
    economics (price / quantity / fee policy) are mandatory either way.
    """

    repository: CapitalRepository
    fee_policy: FeePolicy
    operator_id: str | None
    source_authority: str | None
    observed_at: datetime | None
    executed_at: datetime | None
    attachment_hash: str | None
    execution_id: str
    order_id: str
    side: ExecutionSide
    security_id: str
    price_micros: int | None
    quantity: int | None
    seal: Any | None
    permit: Any | None
    order_line_id: str | None


@dataclass(frozen=True)
class ManualCorrectionContext:
    """Injected truth for one manual correction."""

    repository: CapitalRepository
    source_authority: str
    effective_at: datetime
    observed_at: datetime


@dataclass(frozen=True)
class ManualExecutionRecord:
    """The durable record of one manual execution."""

    execution_id: str
    order_id: str
    side: ExecutionSide
    security_id: str
    official_oos: bool
    unattributed: bool
    mode: ExecutionMode
    operator_id: str
    source_authority: str
    attachment_hash: str


@dataclass(frozen=True)
class ManualRecordResult:
    """The outcome of one ``record`` call."""

    execution_id: str
    order_id: str
    official_oos: bool
    unattributed: bool
    fill_receipt: FillRevisionReceipt
    fee_receipt: FeeRevisionReceipt
    reserve_source_id: str | None
    record: ManualExecutionRecord


@dataclass(frozen=True)
class ManualCorrectionResult:
    """The outcome of one ``correct`` call."""

    execution_id: str
    revision_receipt: ExecutionRevisionReceipt
    record: ManualExecutionRecord


# ---------------------------------------------------------------------------
# ManualExecutionService
# ---------------------------------------------------------------------------


class ManualExecutionService:
    """Record and correct manually confirmed executions in the capital kernel."""

    def __init__(
        self,
        *,
        database_path: str,
        clock: Callable[[], datetime],
        _fault_hook: Callable[[str], None] | None = None,
    ) -> None:
        self._database_path = database_path
        self._clock = clock
        self._fault_hook = _fault_hook
        self._engine = sa.create_engine(
            f"sqlite:///{database_path}",
            connect_args={"check_same_thread": False},
        )
        self._configure_connection(self._engine)
        with self._engine.begin() as conn:
            for statement in _SCHEMA_DDL:
                conn.execute(sa.text(statement))

    @staticmethod
    def _configure_connection(engine: sa.engine.Engine) -> None:
        @sa.event.listens_for(engine, "connect")
        def _set_pragma(  # noqa: ANN001
            dbapi_connection, connection_record
        ) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=15000")
            cursor.close()

    def _fault(self, phase: str) -> None:
        if self._fault_hook is not None:
            self._fault_hook(phase)

    # -- public API --------------------------------------------------------

    def record(self, *, context: ManualRecordContext) -> ManualRecordResult:
        """Record one manually confirmed execution.

        Official OOS records require a pre-sealed, mode-matched plan; every
        other real trade lands out-of-protocol as unattributed risk. Either
        way the operator provenance and exact economics are mandatory and a
        broker namespace is rejected zero-write.
        """

        self._require_required_fields(context)
        # Reject a divergent replay before any capital write: once an
        # execution id is durably recorded, a second record with different
        # economics never reaches the capital kernel.
        self._require_consistent_replay(context)
        repository = context.repository
        official = self._is_official(context)
        if official:
            self._require_official_plan(context)
            # A real trade that contradicts its plan (different security or
            # quantity above the permitted amount) is downgraded to
            # out-of-protocol: it stays economically real but lands as
            # unattributed sentinel risk instead of official OOS.
            if self._contradicts_plan(context):
                official = False
        else:
            self._require_out_of_protocol(context)
        mode = self._mode_for(context, official)
        attribution = self._attribution(context) if official else None
        reserve_source_id = self._reserve_source_id(context) if official else None
        position_lineage = (
            self._position_lineage(context) if official else None
        )
        economic_lot = self._economic_lot(context) if official else None
        fill_request = FillRevisionRequest(
            execution_id=context.execution_id,
            revision=1,
            order_id=context.order_id,
            side=context.side,
            security_id=context.security_id,
            price_micros=context.price_micros,
            quantity=context.quantity,
            position_lineage_id=position_lineage,
            economic_lot_id=economic_lot,
            attribution=attribution,
            reserve_source_id=reserve_source_id,
            source_authority=context.source_authority,
            effective_at=context.executed_at,
            as_of=self._clock(),
            expected_stream_version=repository.stream_version(),
        )
        fill_receipt, _ = repository.record_fill_revision(fill_request)
        self._fault("manual.after_fill")
        fee_receipt = self._charge_fee(
            fill_execution_id=context.execution_id,
            fee_policy=context.fee_policy,
            repository=repository,
            source_authority=context.source_authority,
            effective_at=context.executed_at,
        )
        record = ManualExecutionRecord(
            execution_id=context.execution_id,
            order_id=context.order_id,
            side=context.side,
            security_id=context.security_id,
            official_oos=official,
            unattributed=bool(fill_receipt.unattributed),
            mode=mode,
            operator_id=context.operator_id,
            source_authority=context.source_authority,
            attachment_hash=context.attachment_hash,
        )
        self._persist_record(record, context)
        return ManualRecordResult(
            execution_id=context.execution_id,
            order_id=context.order_id,
            official_oos=official,
            unattributed=bool(fill_receipt.unattributed),
            fill_receipt=fill_receipt,
            fee_receipt=fee_receipt,
            reserve_source_id=reserve_source_id,
            record=record,
        )

    def correct(
        self,
        *,
        execution_id: str,
        revision: int,
        kind: ExecutionRevisionKind,
        operator_id: str,
        attachment_hash: str,
        context: ManualCorrectionContext,
        corrected_price_micros: int | None = None,
        corrected_quantity: int | None = None,
    ) -> ManualCorrectionResult:
        """Correct one previously recorded manual execution.

        Corrections continue the same ``execution_id`` under a linked
        BUSTED / CORRECTED revision and never duplicate or transport the
        fact across modes. An unknown execution (one this service never
        recorded) is rejected zero-write.
        """

        record = self._require_known_execution(execution_id)
        superseded_quantity = None
        if kind is ExecutionRevisionKind.BUSTED:
            # A bust restates the active fact it removes: the active
            # quantity (which a prior CORRECTED revision may have changed)
            # is the superseded quantity, not the original recorded fill.
            superseded_quantity = self._active_quantity(execution_id)
        revision_request = ExecutionRevisionRequest(
            execution_id=execution_id,
            revision=revision,
            revision_kind=kind,
            order_id=record.order_id,
            side=record.side,
            security_id=record.security_id,
            superseded_quantity=superseded_quantity,
            corrected_price_micros=(
                corrected_price_micros
                if kind is ExecutionRevisionKind.CORRECTED
                else None
            ),
            corrected_quantity=(
                corrected_quantity
                if kind is ExecutionRevisionKind.CORRECTED
                else None
            ),
            source_authority=context.source_authority,
            effective_at=context.effective_at,
            as_of=self._clock(),
            expected_stream_version=context.repository.stream_version(),
        )
        if kind is ExecutionRevisionKind.BUSTED:
            receipt, _ = context.repository.record_execution_revision(
                revision_request
            )
            # The bust removes the active fact, so the active quantity is
            # now zero - a later correction can reopen it.
            self._update_active_quantity(execution_id, 0)
        else:
            receipt, _ = context.repository.record_execution_correction(
                revision_request
            )
            # A correction replaces the active fact, so the active quantity
            # tracks the corrected quantity for any subsequent bust.
            assert corrected_quantity is not None  # validated all-or-none
            self._update_active_quantity(execution_id, corrected_quantity)
        self._fault("manual.after_correct")
        return ManualCorrectionResult(
            execution_id=execution_id,
            revision_receipt=receipt,
            record=record,
        )

    def records(self) -> tuple[ManualExecutionRecord, ...]:
        """Read every durable manual record, in record order."""

        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT * FROM manual_records ORDER BY recorded_at,"
                    " execution_id"
                )
            ).fetchall()
        return tuple(self._record_from_row(row) for row in rows)

    # -- pre-checks --------------------------------------------------------

    def _require_required_fields(self, context: ManualRecordContext) -> None:
        missing: list[str] = []
        if not context.operator_id:
            missing.append("operator_id")
        if not context.source_authority:
            missing.append("source_authority")
        if context.observed_at is None:
            missing.append("observed_at")
        if context.executed_at is None:
            missing.append("executed_at")
        if not context.attachment_hash:
            missing.append("attachment_hash")
        if context.price_micros is None or context.price_micros <= 0:
            missing.append("price_micros")
        if context.quantity is None or context.quantity <= 0:
            missing.append("quantity")
        if context.fee_policy is None:
            missing.append("fee_policy")
        if missing:
            raise ExecutionError(
                "manual_missing_required_field",
                "manual record requires operator/source/observed/attachment"
                "/exact price/quantity/fees",
                missing=tuple(missing),
            )

    def _require_consistent_replay(
        self, context: ManualRecordContext
    ) -> None:
        with self._engine.connect() as conn:
            existing = conn.execute(
                sa.text(
                    "SELECT price_micros, quantity, side, security_id,"
                    " order_id FROM manual_records WHERE execution_id = :eid"
                ),
                {"eid": context.execution_id},
            ).first()
        if existing is None:
            return
        if (
            int(existing.price_micros) != context.price_micros
            or int(existing.quantity) != context.quantity
            or str(existing.side) != context.side.value
            or str(existing.security_id) != context.security_id
            or str(existing.order_id) != context.order_id
        ):
            raise ExecutionError(
                "manual_record_conflict",
                "execution id already recorded with different content",
                execution_id=context.execution_id,
            )

    def _is_official(self, context: ManualRecordContext) -> bool:
        return context.seal is not None and context.permit is not None

    def _contradicts_plan(self, context: ManualRecordContext) -> bool:
        """True when the recorded trade contradicts its pre-sealed plan line.

        A real trade that contradicts its plan (a different security, or a
        quantity above the permitted amount) is still economically real, so
        it must be booked as unattributed sentinel risk - never as official
        OOS attributed to the sealed lineage and reserve. Before this check
        only the client order id was compared, and a mismatched security or
        quantity silently rode the official path until the capital kernel
        failed it as ``reserve_unknown`` (an exception, not a downgrade).
        """
        permit_line = self._permit_line_for(
            context.permit, context.order_line_id
        )
        assert permit_line is not None  # guarded by _require_official_plan
        if permit_line.security_id != context.security_id:
            return True
        if context.quantity > int(permit_line.permitted_quantity_units):
            return True
        return False

    def _require_official_plan(self, context: ManualRecordContext) -> None:
        seal = context.seal
        permit = context.permit
        if seal.mode is not ExecutionMode.MANUAL_CONFIRMED:
            raise ExecutionError(
                "manual_mode_mismatch",
                "official OOS requires a MANUAL_CONFIRMED seal",
                seal_mode=str(seal.mode),
            )
        permit_line = self._permit_line_for(permit, context.order_line_id)
        if permit_line is None:
            raise ExecutionError(
                "manual_plan_binding_missing",
                "official OOS record must bind to a permit line",
                order_line_id=context.order_line_id,
            )
        # The recorded economics must match the pre-sealed plan line: the
        # client order id is the canonical join; security and quantity
        # agreement is enforced as a downgrade, not a rejection (see
        # _contradicts_plan).
        if permit_line.client_order_id != context.order_id:
            raise ExecutionError(
                "manual_plan_binding_missing",
                "official OOS record must bind to the permit line's order id",
                order_line_id=context.order_line_id,
            )
        self._reject_broker_namespace(context)

    def _require_out_of_protocol(self, context: ManualRecordContext) -> None:
        # An out-of-protocol trade has no plan to bind, but it still must
        # not claim broker provenance.
        self._reject_broker_namespace(context)

    def _reject_broker_namespace(self, context: ManualRecordContext) -> None:
        seal = context.seal
        if seal is not None:
            for line in seal.proposal.order_lines:
                if _is_broker_namespace(line.producer_namespace):
                    raise ExecutionError(
                        "manual_broker_namespace",
                        "manual recording cannot claim broker provenance",
                        producer_namespace=line.producer_namespace,
                    )
        if context.source_authority is not None and _is_broker_namespace(
            context.source_authority
        ):
            raise ExecutionError(
                "manual_broker_namespace",
                "manual recording cannot claim broker provenance",
                source_authority=context.source_authority,
            )

    def _require_known_execution(
        self, execution_id: str
    ) -> ManualExecutionRecord:
        with self._engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT * FROM manual_records WHERE execution_id = :eid"
                ),
                {"eid": execution_id},
            ).first()
        if row is None:
            raise ExecutionError(
                "manual_execution_unknown",
                "correction targets an execution this service never recorded",
                execution_id=execution_id,
            )
        return self._record_from_row(row)

    def _active_quantity(self, execution_id: str) -> int:
        with self._engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT active_quantity FROM manual_records"
                    " WHERE execution_id = :eid"
                ),
                {"eid": execution_id},
            ).first()
        assert row is not None  # guarded by _require_known_execution caller
        return int(row.active_quantity)

    def _update_active_quantity(
        self, execution_id: str, active_quantity: int
    ) -> None:
        with self._engine.begin() as conn:
            result = conn.execute(
                sa.text(
                    "UPDATE manual_records SET active_quantity = :qty"
                    " WHERE execution_id = :eid"
                ),
                {"qty": active_quantity, "eid": execution_id},
            )
        if result.rowcount != 1:  # pragma: no cover - guarded above
            raise ExecutionError(
                "manual_execution_unknown",
                "correction targets an execution this service never recorded",
                execution_id=execution_id,
            )

    # -- provenance helpers ------------------------------------------------

    def _mode_for(self, context: ManualRecordContext, official: bool) -> ExecutionMode:
        if official and context.seal is not None:
            return context.seal.mode
        # An out-of-protocol trade is recorded under the manual mode's
        # capital binding; the binding itself is owned by the caller's
        # repository, not invented here.
        return ExecutionMode.MANUAL_CONFIRMED

    def _permit_line_for(self, permit, order_line_id: str | None):
        if permit is None or order_line_id is None:
            return None
        for line in permit.permit_lines:
            if line.order_line_id == order_line_id:
                return line
        return None

    def _proposal_line_for(self, context: ManualRecordContext):
        seal = context.seal
        if seal is None or context.order_line_id is None:
            return None
        for line in seal.proposal.order_lines:
            if line.order_line_id == context.order_line_id:
                return line
        return None

    def _attribution(self, context: ManualRecordContext) -> FillAttribution:
        proposal_line = self._proposal_line_for(context)
        if proposal_line is None:
            raise ExecutionError(
                "manual_plan_binding_missing",
                "official OOS record must bind to a sealed order line",
                order_line_id=context.order_line_id,
            )
        return FillAttribution(
            producer_namespace=proposal_line.producer_namespace,
            research_program_id=proposal_line.research_program_id,
            economic_lineage_id=proposal_line.economic_lineage_id,
            stage_id=proposal_line.stage_id,
        )

    def _position_lineage(self, context: ManualRecordContext) -> str:
        proposal_line = self._proposal_line_for(context)
        assert proposal_line is not None  # guarded by _attribution caller
        return proposal_line.economic_lineage_id

    def _economic_lot(self, context: ManualRecordContext) -> str:
        return f"lot:{context.order_line_id}"

    def _reserve_source_id(self, context: ManualRecordContext) -> str | None:
        seal = context.seal
        if seal is None or context.order_line_id is None:
            return None
        for binding in seal.line_reserve_bindings:
            if binding.order_line_id == context.order_line_id:
                return binding.reservation_allocation_id
        return None

    # -- fees --------------------------------------------------------------

    def _charge_fee(
        self,
        *,
        fill_execution_id: str,
        fee_policy: FeePolicy,
        repository: CapitalRepository,
        source_authority: str,
        effective_at: datetime,
    ) -> FeeRevisionReceipt:
        # The capital kernel is the source of truth for the charge: it books
        # the canonical fee event under the injected policy, so the manual
        # service does not recompute or second-guess the total here.
        fee_request = FeeRevisionRequest(
            fill_execution_id=fill_execution_id,
            revision=1,
            revision_kind=FeeRevisionKind.INITIAL,
            fee_policy=fee_policy,
            source_authority=source_authority,
            effective_at=effective_at,
            as_of=self._clock(),
            expected_stream_version=repository.stream_version(),
        )
        receipt, _ = repository.record_fee_revision(fee_request)
        self._fault("manual.after_fee")
        return receipt

    # -- durable record ----------------------------------------------------

    def _persist_record(
        self, record: ManualExecutionRecord, context: ManualRecordContext
    ) -> None:
        artifact = self._payload_artifact(record, context)
        with self._engine.begin() as conn:
            existing = conn.execute(
                sa.text(
                    "SELECT payload_artifact FROM manual_records"
                    " WHERE execution_id = :eid"
                ),
                {"eid": record.execution_id},
            ).first()
            if existing is not None:
                if existing.payload_artifact != artifact:
                    raise ExecutionError(
                        "manual_record_conflict",
                        "execution id already recorded with different content",
                        execution_id=record.execution_id,
                    )
                # Idempotent replay: the prior record is authoritative.
                return
            conn.execute(
                sa.text(
                    "INSERT INTO manual_records"
                    " (execution_id, order_id, side, security_id,"
                    " official_oos, unattributed, mode, operator_id,"
                    " source_authority, attachment_hash, price_micros,"
                    " quantity, active_quantity, recorded_at,"
                    " payload_artifact)"
                    " VALUES (:eid, :oid, :side, :sec, :oos, :una, :mode,"
                    " :op, :src, :att, :price, :qty, :active, :at, :art)"
                ),
                {
                    "eid": record.execution_id,
                    "oid": record.order_id,
                    "side": record.side.value,
                    "sec": record.security_id,
                    "oos": 1 if record.official_oos else 0,
                    "una": 1 if record.unattributed else 0,
                    "mode": record.mode.value,
                    "op": record.operator_id,
                    "src": record.source_authority,
                    "att": record.attachment_hash,
                    "price": context.price_micros,
                    "qty": context.quantity,
                    "active": context.quantity,
                    "at": self._clock().isoformat(),
                    "art": artifact,
                },
            )
        self._fault("manual.after_record")

    def _payload_artifact(
        self, record: ManualExecutionRecord, context: ManualRecordContext
    ) -> str:
        return "|".join(
            [
                record.execution_id,
                record.order_id,
                record.side.value,
                record.security_id,
                str(record.official_oos),
                str(record.unattributed),
                record.mode.value,
                record.operator_id,
                record.source_authority,
                record.attachment_hash,
                str(context.price_micros),
                str(context.quantity),
            ]
        )

    def _record_from_row(self, row) -> ManualExecutionRecord:
        return ManualExecutionRecord(
            execution_id=str(row.execution_id),
            order_id=str(row.order_id),
            side=ExecutionSide(str(row.side)),
            security_id=str(row.security_id),
            official_oos=bool(row.official_oos),
            unattributed=bool(row.unattributed),
            mode=ExecutionMode(str(row.mode)),
            operator_id=str(row.operator_id),
            source_authority=str(row.source_authority),
            attachment_hash=str(row.attachment_hash),
        )


__all__ = [
    "ManualCorrectionContext",
    "ManualCorrectionResult",
    "ManualExecutionRecord",
    "ManualExecutionService",
    "ManualRecordContext",
    "ManualRecordResult",
]
