"""Plan 07 Task 6: durable broker lifecycle scheduling and rate isolation.

The broker lifecycle scheduler owns independent entry, exit, query, and
reconcile work queues and per-cycle rate buckets. The core invariants:

- Rate isolation: an exit cannot consume entry authorization and an entry
  cannot exhaust exit/query/reconcile capacity. Each kind draws only from
  its own bucket.
- Durable restart: a process lease is acquired on start; ``shutdown()``
  releases the process lease but never any durable exit-work lease, so a
  restart resumes in-flight exit duty. Re-opening the scheduler re-acquires
  the lease fail-closed.
- Cutoff: past the certified broker cutoff, entry work is rejected while
  exit/query/reconcile continue (exits are always preserved).
- Broker throttle: a throttle response defers the item (re-enqueue) without
  consuming the bucket for that attempt or failing the cycle.
- Unknown sellable quantity: an exit whose sellable shares are unknown
  enqueues a query and sells zero additional shares — it never guesses a
  quantity. The executor invocation still consumed a broker round-trip, so
  the exit rate budget is NOT refunded (a consumed attempt cannot fund a
  second exit in the same cycle). Duplicate query items are never
  re-enqueued, and once the unknown-quantity retries exceed the configured
  bound the exit escalates to RECONCILE and is raised as a blocking
  escalation rather than livelocking.
- Correction-driven exit reopen: a correction that reopens a position
  recreates exit duty (a new EXIT work item) so an exit is never orphaned.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class SchedulerError(RuntimeError):
    """Scheduler failure with a stable machine-readable ``code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class WorkKind(StrEnum):
    ENTRY = "entry"
    EXIT = "exit"
    QUERY = "query"
    RECONCILE = "reconcile"


class ExecutionOutcome(StrEnum):
    SUBMITTED = "submitted"
    THROTTLED = "throttled"
    UNKNOWN_QUANTITY = "unknown_quantity"
    CUTOFF_REJECTED = "cutoff_rejected"
    REOPENED_EXIT = "reopened_exit"


@dataclass(frozen=True)
class WorkItem:
    """One unit of broker lifecycle work."""

    kind: WorkKind
    item_id: str
    sellable_quantity_units: int | None = None
    reopens_exit: bool = False
    # Number of unknown-quantity retries this exit has already consumed;
    # bounds escalation so a persistent unknown never livelocks.
    attempts: int = 0


@dataclass(frozen=True)
class ExecutionResult:
    outcome: ExecutionOutcome
    item: WorkItem
    deferred_query_id: str | None = None
    reopened_exit_id: str | None = None


class BrokerExecutor(Protocol):
    """Executes one work item against the broker; returns the outcome."""

    def execute(self, item: WorkItem, *, now: datetime) -> ExecutionResult: ...


@dataclass
class _RateBucket:
    capacity: int
    remaining: int

    def try_consume(self, n: int = 1) -> bool:
        if self.remaining >= n:
            self.remaining -= n
            return True
        return False

    def reset(self) -> None:
        self.remaining = self.capacity


@dataclass
class CycleResult:
    """Outcome of one scheduler cycle."""

    submitted: tuple[WorkItem, ...] = ()
    deferred: tuple[WorkItem, ...] = ()
    rejected: tuple[WorkItem, ...] = ()
    enqueued_queries: tuple[str, ...] = ()
    enqueued_exits: tuple[str, ...] = ()
    enqueued_reconciles: tuple[str, ...] = ()
    escalations: tuple[str, ...] = ()
    budget_remaining: dict[str, int] = field(default_factory=dict)


class BrokerLifecycleScheduler:
    """Independent entry/exit/query/reconcile queues with rate isolation."""

    def __init__(
        self,
        *,
        entry_budget: int,
        exit_budget: int,
        query_budget: int,
        reconcile_budget: int,
        cutoff: datetime,
        clock,
        max_unknown_retries: int = 3,
    ) -> None:
        if min(entry_budget, exit_budget, query_budget, reconcile_budget) < 0:
            raise SchedulerError(
                "SCHEDULER_RATE_BUDGET_NEGATIVE",
                "rate budgets must be non-negative",
            )
        if max_unknown_retries < 1:
            raise SchedulerError(
                "SCHEDULER_UNKNOWN_RETRY_BOUND",
                "max_unknown_retries must be at least 1",
            )
        self._max_unknown_retries = max_unknown_retries
        self._buckets: dict[WorkKind, _RateBucket] = {
            WorkKind.ENTRY: _RateBucket(entry_budget, entry_budget),
            WorkKind.EXIT: _RateBucket(exit_budget, exit_budget),
            WorkKind.QUERY: _RateBucket(query_budget, query_budget),
            WorkKind.RECONCILE: _RateBucket(reconcile_budget, reconcile_budget),
        }
        self._cutoff = cutoff
        self._clock = clock
        self._queue: list[WorkItem] = []
        self._pending_queries: set[str] = set()
        self._pending_reconciles: set[str] = set()
        self._lease_holder: str | None = None
        self._lease_owner: str

    # -- process lease -----------------------------------------------------

    def acquire_lease(self, *, owner: str) -> None:
        if self._lease_holder is not None and self._lease_holder != owner:
            raise SchedulerError(
                "SCHEDULER_LEASE_HELD",
                f"lease held by {self._lease_holder!r}",
            )
        self._lease_holder = owner
        self._lease_owner = owner

    def release_lease(self, *, owner: str) -> None:
        if self._lease_holder != owner:
            raise SchedulerError(
                "SCHEDULER_LEASE_OWNER_MISMATCH",
                "only the lease owner may release",
            )
        # Release the PROCESS lease only — never any durable exit-work lease.
        self._lease_holder = None

    def has_process_lease(self) -> bool:
        return self._lease_holder is not None

    # -- enqueue -----------------------------------------------------------

    def enqueue(self, item: WorkItem) -> None:
        self._queue.append(item)

    def queue_depth(self, kind: WorkKind | None = None) -> int:
        if kind is None:
            return len(self._queue)
        return sum(1 for i in self._queue if i.kind is kind)

    # -- cycle -------------------------------------------------------------

    def run_cycle(self, executor: BrokerExecutor) -> CycleResult:
        """Process queued work under independent rate budgets."""

        now = self._clock()
        for bucket in self._buckets.values():
            bucket.reset()
        submitted: list[WorkItem] = []
        deferred: list[WorkItem] = []
        rejected: list[WorkItem] = []
        enqueued_queries: list[str] = []
        enqueued_exits: list[str] = []
        enqueued_reconciles: list[str] = []
        escalations: list[str] = []
        # Snapshot the queue; deferred items are re-appended after.
        pending = self._queue[:]
        self._queue.clear()
        for item in pending:
            # Cutoff: entries past the cutoff are rejected; exits/queries/
            # reconciles always continue.
            if item.kind is WorkKind.ENTRY and now > self._cutoff:
                rejected.append(item)
                continue
            bucket = self._buckets[item.kind]
            if not bucket.try_consume():
                # Budget exhausted for this kind: defer, do not draw from
                # any other kind's bucket.
                deferred.append(item)
                self._queue.append(item)
                continue
            result = executor.execute(item, now=now)
            if result.outcome is ExecutionOutcome.THROTTLED:
                # Broker throttle: refund this attempt and defer.
                bucket.remaining += 1
                deferred.append(item)
                self._queue.append(item)
                continue
            if result.outcome is ExecutionOutcome.UNKNOWN_QUANTITY:
                # Unknown sellable shares: sell zero. The executor was invoked,
                # so the round-trip already consumed rate budget — do NOT
                # refund it (a consumed attempt cannot fund a second item this
                # cycle, audit M2). An exit enqueues ONE deduped query to
                # resolve the truth (never duplicated, so the queue cannot
                # compound across cycles).
                deferred.append(item)
                if item.kind is WorkKind.EXIT:
                    query_id = result.deferred_query_id or f"query:{item.item_id}"
                    if query_id not in self._pending_queries:
                        self._pending_queries.add(query_id)
                        enqueued_queries.append(query_id)
                        self._queue.append(WorkItem(kind=WorkKind.QUERY, item_id=query_id))
                if item.attempts + 1 > self._max_unknown_retries:
                    # Persistent unknown truth: surface as a blocking
                    # escalation (audit M3). An exit hands its duty to ONE
                    # deduped reconcile; a query/reconcile/entry that cannot
                    # resolve truth escalates out of the loop entirely rather
                    # than spawning more work.
                    escalations.append(item.item_id)
                    if item.kind is WorkKind.EXIT:
                        reconcile_id = f"reconcile:{item.item_id}"
                        if reconcile_id not in self._pending_reconciles:
                            self._pending_reconciles.add(reconcile_id)
                            enqueued_reconciles.append(item.item_id)
                            self._queue.append(
                                WorkItem(kind=WorkKind.RECONCILE, item_id=reconcile_id)
                            )
                else:
                    self._queue.append(replace(item, attempts=item.attempts + 1))
                continue
            if result.outcome is ExecutionOutcome.REOPENED_EXIT:
                # A correction reopened a position: recreate exit duty so the
                # exit is never orphaned.
                enqueued_exits.append(
                    result.reopened_exit_id or f"exit:{item.item_id}"
                )
                self._queue.append(
                    WorkItem(
                        kind=WorkKind.EXIT,
                        item_id=result.reopened_exit_id or f"exit:{item.item_id}",
                    )
                )
            if result.outcome is ExecutionOutcome.CUTOFF_REJECTED:
                bucket.remaining += 1
                rejected.append(item)
                continue
            submitted.append(item)
        return CycleResult(
            submitted=tuple(submitted),
            deferred=tuple(deferred),
            rejected=tuple(rejected),
            enqueued_queries=tuple(enqueued_queries),
            enqueued_exits=tuple(enqueued_exits),
            enqueued_reconciles=tuple(enqueued_reconciles),
            escalations=tuple(escalations),
            budget_remaining={
                kind.value: bucket.remaining for kind, bucket in self._buckets.items()
            },
        )
