"""Plan 07 Task 3: SEND_CLAIMED dispatcher and ambiguous-submission handling.

The dispatcher is the only worker that may submit to a broker. It consumes
the immutable send right released by the Gateway ``claim_send`` transition
(Plan 04) and:

1. Request the Gateway ``SEND_CLAIMED`` transition (linearize the send
   right; no network inside that transaction).
2. Send the exact immutable payload under the exact client order id.
3. Durably append the authenticated raw receipt (or record a timeout)
   BEFORE reporting status.
4. Report ``BROKER_ACK`` or ``SUBMISSION_AMBIGUOUS`` to the Gateway.

Recovery rule: a claimed command without a durable authenticated ACK
becomes ``SUBMISSION_AMBIGUOUS``. If certified idempotency holds and both
the send and broker cutoff deadlines remain valid, the dispatcher retries
the EXACT same client id and payload; otherwise it may only query, cancel,
or reconcile. Generating a new client id to "guess" a resend is forbidden.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from src.screening.offensive.v3.broker.ports import (
    BrokerAccountBinding,
    BrokerPort,
    BrokerRawEnvelope,
    BrokerTimeoutError,
    NewOrderCommand,
)
from src.screening.offensive.v3.broker.raw_inbox import BrokerRawInbox
from src.screening.offensive.v3.gateway.decisions import (
    CapitalGateway,
    DeliveryOutcome,
)


class DispatcherError(RuntimeError):
    """Dispatcher failure with a stable machine-readable ``code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class LineSubmission:
    """One order line's send result."""

    order_line_id: str
    client_order_id: str
    security_id: str
    quantity_units: int
    status: Literal["acked", "rejected", "timeout"]
    raw_revision: int | None


@dataclass(frozen=True)
class DispatchOutcome:
    """The result of one dispatch pass over a claimed entry."""

    seal_id: str
    delivery: DeliveryOutcome
    submissions: tuple[LineSubmission, ...]


@dataclass
class BrokerDispatcher:
    """Drives claim → send → durable-append → report for one entry.

    The dispatcher never modifies authorization, seals, reserves, or
    capital; it only sends what ``claim_send`` released and reports the
    delivery outcome. The account binding comes from the verified broker
    enablement (Plan 07 Task 2).
    """

    gateway: CapitalGateway
    broker: BrokerPort
    inbox: BrokerRawInbox
    account: BrokerAccountBinding

    def __post_init__(self) -> None:
        if not isinstance(self.broker, BrokerPort):
            raise TypeError(
                "dispatcher requires a real BrokerPort; shadow/proxy/manual"
                " inputs must never reach broker submission"
            )

    def _acked_client_ids(self) -> frozenset[str]:
        """Client ids holding a durable authenticated terminal receipt.

        Derived from the durable inbox so it survives a dispatcher restart.
        Both ``order_ack`` (accepted) and ``order_reject`` (refused) receipts
        make a line terminal: neither is ever resent. Critically, a REJECT is
        NOT an acceptance — it only means the line is finished, so it must
        never allow the entry to claim ``BROKER_ACK``.
        """

        terminal: set[str] = set()
        for record in self.inbox.iter_all():
            payload = record.envelope.payload
            client_id = payload.get("client_order_id")
            kind = payload.get("kind")
            if (
                isinstance(client_id, str)
                and kind in {"order_ack", "order_reject"}
            ):
                terminal.add(client_id)
        return frozenset(terminal)

    def _rejected_client_ids(self) -> frozenset[str]:
        """Client ids holding a durable authenticated REJECT receipt.

        A rejected line is proof of refusal; it must never be folded into an
        entry-level ``BROKER_ACK``, even after a later resend re-reads the
        inbox.
        """

        rejected: set[str] = set()
        for record in self.inbox.iter_all():
            payload = record.envelope.payload
            client_id = payload.get("client_order_id")
            if isinstance(client_id, str) and payload.get("kind") == "order_reject":
                rejected.add(client_id)
        return frozenset(rejected)

    def _commands_for(
        self,
        permit,
        claimed,
    ) -> tuple[tuple[str, str, NewOrderCommand], ...]:
        """Map each claimed client id to its immutable NewOrderCommand.

        The dispatcher sends only the lines the Gateway claimed, under the
        exact claimed client ids. A line the permit shrank to zero has no
        client id and is never sent.
        """

        claimed_ids = {
            line_id: client_id for line_id, client_id in claimed.client_order_ids
        }
        commands: list[tuple[str, str, NewOrderCommand]] = []
        for line in permit.permit_lines:
            client_id = claimed_ids.get(line.order_line_id)
            if client_id is None:
                continue
            if line.permitted_quantity_units <= 0:
                raise DispatcherError(
                    "CLAIMED_ZERO_QUANTITY",
                    f"line {line.order_line_id} claimed but permitted"
                    f" quantity is zero",
                )
            command = NewOrderCommand(
                client_order_id=client_id,
                security_id=line.security_id,
                side="BUY",
                quantity_units=line.permitted_quantity_units,
                order_type=line.order_type,
                limit_price_cents=line.limit_price_cents,
                time_in_force=line.time_in_force,
                account=self.account,
            )
            commands.append((line.order_line_id, client_id, command))
        if not commands:
            raise DispatcherError(
                "NO_CLAIMED_LINES", "claim released no sendable lines"
            )
        return tuple(commands)

    def _send_one(
        self, order_line_id: str, client_id: str, command: NewOrderCommand
    ) -> LineSubmission:
        try:
            envelope = self.broker.submit(command)
        except BrokerTimeoutError:
            return LineSubmission(
                order_line_id=order_line_id,
                client_order_id=client_id,
                security_id=command.security_id,
                quantity_units=command.quantity_units,
                status="timeout",
                raw_revision=None,
            )
        if not envelope.authenticated:
            # An unauthenticated response is not a broker acceptance; treat
            # it as ambiguous (no durable ACK) rather than fabricating one.
            return LineSubmission(
                order_line_id=order_line_id,
                client_order_id=client_id,
                security_id=command.security_id,
                quantity_units=command.quantity_units,
                status="timeout",
                raw_revision=None,
            )
        record = self.inbox.append(
            envelope, envelope_id=f"submit:{client_id}:{envelope.source_sequence}"
        )
        # An authenticated envelope is a durable receipt, but only an
        # order_ack is a broker acceptance. A broker REJECT is durable proof
        # the line was refused: it is never an ACK, never resent, and never
        # lets the entry claim BROKER_ACK (the entry stays ambiguous pending
        # reconciliation rather than misrepresenting a rejected line as held).
        status = "acked" if envelope.payload.get("kind") == "order_ack" else "rejected"
        return LineSubmission(
            order_line_id=order_line_id,
            client_order_id=client_id,
            security_id=command.security_id,
            quantity_units=command.quantity_units,
            status=status,
            raw_revision=record.revision,
        )

    def run_once(self, permit, expected_versions, *, context) -> DispatchOutcome:
        """Claim → send → durable-append → report for one entry."""

        claimed = self.gateway.claim_send(
            permit, expected_versions, context=context
        )
        commands = self._commands_for(permit, claimed)
        submissions = tuple(
            self._send_one(line_id, client_id, command)
            for line_id, client_id, command in commands
        )
        delivery = self._delivery_for(permit, submissions)
        self.gateway.record_delivery_outcome(
            claimed.seal_id,
            delivery,
            submission_client_order_ids=tuple(
                sub.client_order_id for sub in submissions
            ),
        )
        return DispatchOutcome(
            seal_id=claimed.seal_id,
            delivery=delivery,
            submissions=submissions,
        )

    def _delivery_for(
        self, permit, submissions: tuple[LineSubmission, ...]
    ) -> DeliveryOutcome:
        """Fail-closed delivery truth across the permit's lines.

        ``BROKER_ACK`` requires every permit line to hold a durable
        authenticated acceptance (this pass's acked submissions plus any
        previously persisted receipts) AND no line to have been rejected.
        A rejected line is durable proof of refusal — never an ACK — so the
        entry stays ``SUBMISSION_AMBIGUOUS`` pending reconciliation rather
        than misrepresenting a rejected line as a held position.
        """

        receipted = set(self._acked_client_ids())
        receipted.update(
            sub.client_order_id
            for sub in submissions
            if sub.status in {"acked", "rejected"}
        )
        claimed_ids = {
            line.client_order_id
            for line in permit.permit_lines
            if line.client_order_id is not None
        }
        rejected = set(self._rejected_client_ids())
        rejected.update(
            sub.client_order_id for sub in submissions if sub.status == "rejected"
        )
        any_rejected = bool(claimed_ids & rejected)
        if claimed_ids <= receipted and not any_rejected:
            return DeliveryOutcome.BROKER_ACK
        return DeliveryOutcome.SUBMISSION_AMBIGUOUS

    def resend(
        self,
        permit,
        *,
        context,
        broker_cutoff: datetime | None = None,
        certified_idempotent: bool | None = None,
        now: datetime | None = None,
    ) -> DispatchOutcome:
        """Retry the EXACT claimed client ids still lacking a durable receipt.

        The send right is already claimed (in-flight risk); resend reuses the
        same client ids and payload for every line that does NOT yet hold a
        durable authenticated terminal receipt (ack or reject). Lines already
        terminal are never resent (no double-submit). Generating a new client
        id is forbidden.

        The plan permits a same-id retry only when certified idempotency
        holds AND the broker cutoff remains valid. If a cutoff is supplied and
        has already passed, or the caller explicitly reports idempotency is
        not certified, a resend that would re-fire is refused: the operator
        must query, cancel, or reconcile instead.
        """

        state = self.gateway.entry_state(permit.seal_id)
        if state is None:
            raise DispatcherError("SEAL_UNKNOWN", "no seal for resend")
        if state.status not in {"SUBMISSION_AMBIGUOUS", "SEND_CLAIMED"}:
            raise DispatcherError(
                "RESEND_STATE_CONFLICT",
                f"resend requires SUBMISSION_AMBIGUOUS, got {state.status}",
            )
        terminal = self._acked_client_ids()
        commands: list[tuple[str, str, NewOrderCommand]] = []
        for line in permit.permit_lines:
            client_id = line.client_order_id
            if client_id is None or client_id in terminal:
                continue
            command = NewOrderCommand(
                client_order_id=client_id,
                security_id=line.security_id,
                side="BUY",
                quantity_units=line.permitted_quantity_units,
                order_type=line.order_type,
                limit_price_cents=line.limit_price_cents,
                time_in_force=line.time_in_force,
                account=self.account,
            )
            commands.append((line.order_line_id, client_id, command))
        if commands:
            # A resend would re-fire live orders: enforce the plan's retry
            # preconditions (certified idempotency + broker cutoff).
            if broker_cutoff is not None and now is not None and now > broker_cutoff:
                raise DispatcherError(
                    "BROKER_CUTOFF_PASSED",
                    "broker cutoff passed; resend forbidden — reconcile only",
                )
            if certified_idempotent is False:
                raise DispatcherError(
                    "IDEMPOTENCY_UNPROVEN",
                    "client-order-id idempotency not certified for this"
                    " resend; same-id retry forbidden",
                )
        submissions = tuple(
            self._send_one(line_id, client_id, command)
            for line_id, client_id, command in commands
        )
        delivery = self._delivery_for(permit, submissions)
        self.gateway.record_delivery_outcome(
            permit.seal_id,
            delivery,
            submission_client_order_ids=tuple(
                line.client_order_id
                for line in permit.permit_lines
                if line.client_order_id is not None
            ),
        )
        return DispatchOutcome(
            seal_id=permit.seal_id,
            delivery=delivery,
            submissions=submissions,
        )
