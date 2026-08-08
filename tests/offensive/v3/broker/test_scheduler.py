"""Plan 07 Task 6 (RED): durable broker lifecycle scheduling + rate isolation.

锁定约束:
1. rate isolation: exit 不耗 entry 授权, entry 不耗 exit/query/reconcile
   容量 — 每种 kind 只从自己的 bucket 取.
2. entry queue saturation: entry 预算耗尽时 entry 工作延后, exit/query 仍进行.
3. restart lease: 进程 lease acquire/release; 异 owner acquire = LEASE_HELD;
   release 只释放进程 lease, 不释放任何 durable exit-work lease (重启后 exit
   duty 仍在队列).
4. broker throttle: throttle 响应退还本次 attempt, 延后 item, 不失败 cycle.
5. cutoff: 过 cutoff 的 entry 被拒, exit/query/reconcile 继续.
6. unknown sellable shares: 触发 query/reconcile 入队 + 零额卖出, 不猜数量.
7. correction-driven exit reopen: 重开 position 重建 exit duty (新 EXIT 入队).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest

from src.screening.offensive.v3.broker.scheduler import (
    BrokerExecutor,
    BrokerLifecycleScheduler,
    CycleResult,
    ExecutionOutcome,
    ExecutionResult,
    SchedulerError,
    WorkItem,
    WorkKind,
)

T0 = datetime(2026, 8, 7, 9, 30, 0, tzinfo=timezone.utc)
CUTOFF = T0 + timedelta(minutes=30)


class Clock:
    def __init__(self, start: datetime = T0) -> None:
        self.now_value = start

    def __call__(self) -> datetime:
        return self.now_value


@dataclass
class ScriptedExecutor:
    """Replays a list of outcomes per execute() call, in order."""

    outcomes: list[ExecutionOutcome]
    calls: list[WorkItem] = field(default_factory=list)
    _cursor: int = 0

    def execute(self, item: WorkItem, *, now: datetime) -> ExecutionResult:
        self.calls.append(item)
        outcome = (
            self.outcomes[self._cursor]
            if self._cursor < len(self.outcomes)
            else ExecutionOutcome.SUBMITTED
        )
        self._cursor += 1
        return ExecutionResult(
            outcome=outcome,
            item=item,
            deferred_query_id=f"query:{item.item_id}",
            reopened_exit_id=f"exit-reopen:{item.item_id}",
        )


def _scheduler(clock=None) -> BrokerLifecycleScheduler:
    return BrokerLifecycleScheduler(
        entry_budget=2,
        exit_budget=2,
        query_budget=2,
        reconcile_budget=2,
        cutoff=CUTOFF,
        clock=clock or Clock(),
    )


# -- rate isolation ---------------------------------------------------------


def test_exit_does_not_consume_entry_budget() -> None:
    sched = _scheduler()
    sched.enqueue(WorkItem(WorkKind.ENTRY, "e1"))
    sched.enqueue(WorkItem(WorkKind.EXIT, "x1"))
    sched.enqueue(WorkItem(WorkKind.EXIT, "x2"))
    sched.enqueue(WorkItem(WorkKind.EXIT, "x3"))  # over exit budget
    result = sched.run_cycle(ScriptedExecutor([ExecutionOutcome.SUBMITTED] * 4))
    submitted_kinds = [i.kind for i in result.submitted]
    assert WorkKind.ENTRY in submitted_kinds
    assert submitted_kinds.count(WorkKind.EXIT) == 2
    # The third exit is deferred, NOT funded by the entry bucket.
    assert any(i.item_id == "x3" for i in result.deferred)
    assert result.budget_remaining["entry"] == 1
    assert result.budget_remaining["exit"] == 0


def test_entry_does_not_consume_exit_budget() -> None:
    sched = _scheduler()
    for i in range(3):  # over entry budget (2)
        sched.enqueue(WorkItem(WorkKind.ENTRY, f"e{i}"))
    sched.enqueue(WorkItem(WorkKind.EXIT, "x1"))
    result = sched.run_cycle(ScriptedExecutor([ExecutionOutcome.SUBMITTED] * 4))
    assert sum(1 for i in result.submitted if i.kind is WorkKind.ENTRY) == 2
    assert any(i.item_id == "e2" for i in result.deferred)
    # Exit still fully funded.
    assert any(i.kind is WorkKind.EXIT for i in result.submitted)
    assert result.budget_remaining["exit"] == 1


def test_entry_saturation_defers_entry_but_exits_run() -> None:
    sched = _scheduler()
    for i in range(5):
        sched.enqueue(WorkItem(WorkKind.ENTRY, f"e{i}"))
    sched.enqueue(WorkItem(WorkKind.EXIT, "x1"))
    result = sched.run_cycle(ScriptedExecutor([ExecutionOutcome.SUBMITTED] * 6))
    assert sum(1 for i in result.submitted if i.kind is WorkKind.ENTRY) == 2
    assert any(i.kind is WorkKind.EXIT for i in result.submitted)
    assert sched.queue_depth(WorkKind.ENTRY) == 3


# -- restart lease ----------------------------------------------------------


def test_lease_acquire_and_release() -> None:
    sched = _scheduler()
    sched.acquire_lease(owner="worker-A")
    assert sched.has_process_lease()
    sched.release_lease(owner="worker-A")
    assert not sched.has_process_lease()


def test_different_owner_cannot_take_lease() -> None:
    sched = _scheduler()
    sched.acquire_lease(owner="worker-A")
    with pytest.raises(SchedulerError) as excinfo:
        sched.acquire_lease(owner="worker-B")
    assert excinfo.value.code == "SCHEDULER_LEASE_HELD"
    # Original lease still held by A.
    assert sched.has_process_lease()


def test_release_only_releases_process_lease_not_exit_duty() -> None:
    sched = _scheduler()
    sched.acquire_lease(owner="worker-A")
    sched.enqueue(WorkItem(WorkKind.EXIT, "x1"))
    sched.run_cycle(ScriptedExecutor([ExecutionOutcome.THROTTLED]))
    sched.release_lease(owner="worker-A")
    # Exit duty survived the shutdown (deferred back into the queue).
    assert sched.queue_depth(WorkKind.EXIT) == 1
    # A restart re-acquires the lease and resumes.
    sched.acquire_lease(owner="worker-A")
    assert sched.has_process_lease()


# -- broker throttle --------------------------------------------------------


def test_throttle_defers_without_consuming_budget() -> None:
    sched = _scheduler()
    sched.enqueue(WorkItem(WorkKind.EXIT, "x1"))
    result = sched.run_cycle(ScriptedExecutor([ExecutionOutcome.THROTTLED]))
    assert result.submitted == ()
    assert any(i.item_id == "x1" for i in result.deferred)
    # Budget refunded for the throttled attempt.
    assert result.budget_remaining["exit"] == 2
    assert sched.queue_depth(WorkKind.EXIT) == 1


# -- cutoff -----------------------------------------------------------------


def test_cutoff_rejects_entry_but_exits_continue() -> None:
    clock = Clock(T0 + timedelta(minutes=45))  # past cutoff
    sched = _scheduler(clock=clock)
    sched.enqueue(WorkItem(WorkKind.ENTRY, "e1"))
    sched.enqueue(WorkItem(WorkKind.EXIT, "x1"))
    result = sched.run_cycle(ScriptedExecutor([ExecutionOutcome.SUBMITTED]))
    assert any(i.item_id == "e1" for i in result.rejected)
    assert any(i.kind is WorkKind.EXIT for i in result.submitted)


# -- unknown sellable shares ------------------------------------------------


def test_unknown_quantity_enqueues_query_and_sells_zero() -> None:
    sched = _scheduler()
    sched.enqueue(
        WorkItem(WorkKind.EXIT, "x1", sellable_quantity_units=None)
    )
    result = sched.run_cycle(
        ScriptedExecutor([ExecutionOutcome.UNKNOWN_QUANTITY])
    )
    assert result.submitted == ()  # zero additional sell
    assert "query:x1" in result.enqueued_queries
    assert sched.queue_depth(WorkKind.QUERY) == 1
    # The exit is deferred (re-enqueued) pending truth.
    assert sched.queue_depth(WorkKind.EXIT) == 1
    assert result.budget_remaining["exit"] == 2  # exit budget not consumed


# -- correction-driven exit reopen ------------------------------------------


def test_correction_reopen_recreates_exit_duty() -> None:
    sched = _scheduler()
    sched.enqueue(WorkItem(WorkKind.RECONCILE, "r1", reopens_exit=True))
    result = sched.run_cycle(
        ScriptedExecutor([ExecutionOutcome.REOPENED_EXIT])
    )
    assert "exit-reopen:r1" in result.enqueued_exits
    assert sched.queue_depth(WorkKind.EXIT) == 1


# -- partial exit preserves remaining duty ----------------------------------


def test_partial_exit_leaves_remaining_duty_queued() -> None:
    sched = _scheduler()
    # Two exit items; both submitted this cycle, but a third remains queued
    # representing the remaining (partial) exit duty.
    sched.enqueue(WorkItem(WorkKind.EXIT, "x1"))
    sched.enqueue(WorkItem(WorkKind.EXIT, "x2"))
    sched.enqueue(WorkItem(WorkKind.EXIT, "x3"))
    result = sched.run_cycle(
        ScriptedExecutor([ExecutionOutcome.SUBMITTED] * 3)
    )
    assert sum(1 for i in result.submitted if i.kind is WorkKind.EXIT) == 2
    assert sched.queue_depth(WorkKind.EXIT) == 1


# -- negative budget rejected -----------------------------------------------


def test_negative_budget_rejected() -> None:
    with pytest.raises(SchedulerError) as excinfo:
        BrokerLifecycleScheduler(
            entry_budget=-1,
            exit_budget=2,
            query_budget=2,
            reconcile_budget=2,
            cutoff=CUTOFF,
            clock=Clock(),
        )
    assert excinfo.value.code == "SCHEDULER_RATE_BUDGET_NEGATIVE"
