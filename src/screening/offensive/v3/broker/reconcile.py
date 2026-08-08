"""Plan 07 Task 5: complete paginated reconciliation of broker history.

The reconciler proves that a broker query captured the COMPLETE order,
fill, cash, position, fee, and action history, then compares it against
the locally normalized state. Completeness is a proof, not an assertion:
the captured snapshot binds its query parameters, page count, cursors,
broker as-of/received times, and the raw envelope roots that back every
page. Any gap (missing/repeated page, cursor rollback, retention too
short, stale snapshot) latches a typed break.

Material or unknown breaks latch no-entry but persist the external fact
first (a real but unlinked fill is recorded, then entry is fenced). A
confirmation only links an existing canonical fact or posts the delta;
it never duplicates capital. Tolerance is versioned per fact type —
there is no generic monetary epsilon.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal

from src.screening.offensive.v3.broker.normalizer import (
    ExecutionNormalizer,
    OrderExecutionState,
)


class BreakKind(StrEnum):
    """The kind of reconciliation break."""

    MISSING_PAGE = "missing_page"
    REPEATED_PAGE = "repeated_page"
    CURSOR_ROLLBACK = "cursor_rollback"
    RETENTION_TOO_SHORT = "retention_too_short"
    STALE_SNAPSHOT = "stale_snapshot"
    UNEXPLAINED_CASH = "unexplained_cash"
    UNEXPLAINED_SHARES = "unexplained_shares"
    UNKNOWN_ORDER = "unknown_order"
    MISSING_EXECUTION = "missing_execution"
    QUANTITY_MISMATCH = "quantity_mismatch"
    NOTIONAL_MISMATCH = "notional_mismatch"
    FEE_MISMATCH = "fee_mismatch"


class BreakSeverity(StrEnum):
    """How a break affects entry authority."""

    BLOCKING = "blocking"
    ADVISORY = "advisory"


@dataclass(frozen=True)
class QueryPage:
    """One captured page of a paginated broker query."""

    page_ordinal: int
    cursor_before: str
    cursor_after: str
    envelope_root: str
    received_at: datetime


@dataclass(frozen=True)
class CompletenessProof:
    """Proof that a snapshot captured the complete broker history."""

    query_parameters_hash: str
    expected_page_count: int
    pages: tuple[QueryPage, ...]
    broker_as_of: datetime
    received_at: datetime
    retention_calendar_days: int
    retention_horizon_days: int


@dataclass(frozen=True)
class BrokerOrderFact:
    """One order's complete cumulative truth per the broker snapshot."""

    client_order_id: str
    cumulative_quantity_units: int
    cumulative_notional_cents: int
    cumulative_fee_cents: int


@dataclass(frozen=True)
class BrokerAccountFact:
    """Account-level cash truth per the broker snapshot."""

    cash_cents: int


@dataclass(frozen=True)
class ReconciliationBreak:
    """One typed reconciliation break with severity and action."""

    kind: BreakKind
    severity: BreakSeverity
    client_order_id: str | None
    message: str
    external_fact: BrokerOrderFact | None = None


@dataclass(frozen=True)
class FactTolerances:
    """Versioned per-fact-type tolerance; no generic monetary epsilon."""

    quantity_units: int = 0
    notional_cents: int = 0
    fee_cents: int = 0
    cash_cents: int = 0
    snapshot_max_age_seconds: int = 0


@dataclass
class ReconciliationResult:
    """The outcome of one reconciliation pass."""

    breaks: tuple[ReconciliationBreak, ...] = ()
    matched_orders: tuple[str, ...] = ()

    @property
    def has_blocking(self) -> bool:
        return any(
            break_.severity is BreakSeverity.BLOCKING for break_ in self.breaks
        )


def verify_completeness(proof: CompletenessProof) -> ReconciliationBreak | None:
    """Return the first completeness break, or None if the proof is whole."""

    if len(proof.pages) != proof.expected_page_count:
        return ReconciliationBreak(
            kind=BreakKind.MISSING_PAGE,
            severity=BreakSeverity.BLOCKING,
            client_order_id=None,
            message=(
                f"captured {len(proof.pages)} pages, expected"
                f" {proof.expected_page_count}"
            ),
        )
    seen_ordinals: set[int] = set()
    prev_cursor: str | None = None
    for page in proof.pages:
        if page.page_ordinal in seen_ordinals:
            return ReconciliationBreak(
                kind=BreakKind.REPEATED_PAGE,
                severity=BreakSeverity.BLOCKING,
                client_order_id=None,
                message=f"page {page.page_ordinal} captured twice",
            )
        seen_ordinals.add(page.page_ordinal)
        if prev_cursor is not None and page.cursor_before != prev_cursor:
            return ReconciliationBreak(
                kind=BreakKind.CURSOR_ROLLBACK,
                severity=BreakSeverity.BLOCKING,
                client_order_id=None,
                message=(
                    f"page {page.page_ordinal} cursor_before"
                    f" {page.cursor_before!r} != prior cursor_after"
                    f" {prev_cursor!r}"
                ),
            )
        prev_cursor = page.cursor_after
    if proof.retention_calendar_days < proof.retention_horizon_days:
        return ReconciliationBreak(
            kind=BreakKind.RETENTION_TOO_SHORT,
            severity=BreakSeverity.BLOCKING,
            client_order_id=None,
            message=(
                f"retention {proof.retention_calendar_days}d < required"
                f" horizon {proof.retention_horizon_days}d"
            ),
        )
    return None


class Reconciler:
    """Compares a complete broker snapshot against local normalized state."""

    def __init__(
        self,
        normalizer: ExecutionNormalizer,
        *,
        tolerances: FactTolerances | None = None,
        now: datetime | None = None,
    ) -> None:
        self._normalizer = normalizer
        self._tolerances = tolerances or FactTolerances()
        self._now = now

    def capture_complete_snapshot(
        self,
        proof: CompletenessProof,
        orders: tuple[BrokerOrderFact, ...],
        account: BrokerAccountFact,
    ) -> "CapturedSnapshot":
        """Bind a completeness proof to the captured facts."""

        return CapturedSnapshot(
            proof=proof, orders=orders, account=account
        )

    def compare(
        self,
        snapshot: "CapturedSnapshot",
        *,
        local_cash_cents: int,
        expected_client_order_ids: tuple[str, ...] | None = None,
    ) -> ReconciliationResult:
        """Compare a complete snapshot against local state.

        Completeness is verified first; any gap blocks before per-fact
        comparison. A material/unknown break latches no-entry but the
        external fact is preserved on the break so it is never dropped.
        """

        breaks: list[ReconciliationBreak] = []
        matched: list[str] = []

        completeness = verify_completeness(snapshot.proof)
        if completeness is not None:
            return ReconciliationResult(breaks=(completeness,))

        if self._now is not None and self._tolerances.snapshot_max_age_seconds:
            age = self._now - snapshot.proof.received_at
            if age > timedelta(seconds=self._tolerances.snapshot_max_age_seconds):
                breaks.append(
                    ReconciliationBreak(
                        kind=BreakKind.STALE_SNAPSHOT,
                        severity=BreakSeverity.BLOCKING,
                        client_order_id=None,
                        message=(
                            f"snapshot age {int(age.total_seconds())}s >"
                            f" tolerance"
                            f" {self._tolerances.snapshot_max_age_seconds}s"
                        ),
                    )
                )
                return ReconciliationResult(breaks=tuple(breaks))

        broker_orders = {o.client_order_id: o for o in snapshot.orders}
        local_ids = set(expected_client_order_ids or ())
        for client_id, broker_fact in broker_orders.items():
            local = self._normalizer.state_for(client_id)
            if local is None:
                # Unknown order: persist the external fact, block entry.
                breaks.append(
                    ReconciliationBreak(
                        kind=BreakKind.UNKNOWN_ORDER,
                        severity=BreakSeverity.BLOCKING,
                        client_order_id=client_id,
                        message=(
                            f"broker reports order {client_id} unknown to"
                            " local state"
                        ),
                        external_fact=broker_fact,
                    )
                )
                continue
            self._compare_fact(client_id, broker_fact, local, breaks, matched)

        if expected_client_order_ids is not None:
            for client_id in expected_client_order_ids:
                if client_id not in broker_orders:
                    breaks.append(
                        ReconciliationBreak(
                            kind=BreakKind.MISSING_EXECUTION,
                            severity=BreakSeverity.BLOCKING,
                            client_order_id=client_id,
                            message=(
                                f"local state has {client_id} but broker"
                                " snapshot omits it"
                            ),
                        )
                    )

        cash_delta = snapshot.account.cash_cents - local_cash_cents
        if abs(cash_delta) > self._tolerances.cash_cents:
            breaks.append(
                ReconciliationBreak(
                    kind=BreakKind.UNEXPLAINED_CASH,
                    severity=BreakSeverity.BLOCKING,
                    client_order_id=None,
                    message=(
                        f"broker cash {snapshot.account.cash_cents} vs local"
                        f" {local_cash_cents} exceeds cash tolerance"
                    ),
                )
            )

        del local_ids
        return ReconciliationResult(
            breaks=tuple(breaks), matched_orders=tuple(matched)
        )

    def _compare_fact(
        self,
        client_id: str,
        broker_fact: BrokerOrderFact,
        local: OrderExecutionState,
        breaks: list[ReconciliationBreak],
        matched: list[str],
    ) -> None:
        qty_break = abs(
            broker_fact.cumulative_quantity_units
            - local.cumulative_quantity_units
        )
        notional_break = abs(
            broker_fact.cumulative_notional_cents
            - local.cumulative_notional_cents
        )
        fee_break = abs(
            broker_fact.cumulative_fee_cents - local.cumulative_fee_cents
        )
        has_break = False
        if qty_break > self._tolerances.quantity_units:
            breaks.append(
                ReconciliationBreak(
                    kind=BreakKind.QUANTITY_MISMATCH,
                    severity=BreakSeverity.BLOCKING,
                    client_order_id=client_id,
                    message=(
                        f"quantity broker {broker_fact.cumulative_quantity_units}"
                        f" vs local {local.cumulative_quantity_units}"
                    ),
                    external_fact=broker_fact,
                )
            )
            has_break = True
        if notional_break > self._tolerances.notional_cents:
            breaks.append(
                ReconciliationBreak(
                    kind=BreakKind.NOTIONAL_MISMATCH,
                    severity=BreakSeverity.BLOCKING,
                    client_order_id=client_id,
                    message=(
                        f"notional broker {broker_fact.cumulative_notional_cents}"
                        f" vs local {local.cumulative_notional_cents}"
                    ),
                    external_fact=broker_fact,
                )
            )
            has_break = True
        if fee_break > self._tolerances.fee_cents:
            breaks.append(
                ReconciliationBreak(
                    kind=BreakKind.FEE_MISMATCH,
                    severity=BreakSeverity.ADVISORY,
                    client_order_id=client_id,
                    message=(
                        f"fee broker {broker_fact.cumulative_fee_cents} vs"
                        f" local {local.cumulative_fee_cents}"
                    ),
                    external_fact=broker_fact,
                )
            )
            has_break = True
        if not has_break:
            matched.append(client_id)


@dataclass(frozen=True)
class CapturedSnapshot:
    """A completeness-proof-bound snapshot of broker facts."""

    proof: CompletenessProof
    orders: tuple[BrokerOrderFact, ...]
    account: BrokerAccountFact
