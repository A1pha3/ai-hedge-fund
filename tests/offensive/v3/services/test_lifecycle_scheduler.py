"""Plan 05 Task 4 (RED): 独立 durable lifecycle scheduler 骨架测试。

覆盖 13 条约束:
1/2. 只接受 risk-maintaining/reducing 命令 — API 面没有 publish_entry /
     issue_permit / make_outbox_durable / claim_send /
     activate_policy_and_envelope(not hasattr 断言);
3.   无 CLI 依赖 — 只用 scheduler 实例 + 模拟时钟驱动完整 cycle;
4.   Publisher/Authorizer outage — ExitDependencies 全部注入抛错 probes,
     exit lifecycle(claim→submit→reconcile)仍完整执行;
5.   claim 后 worker 崩溃 — lease 到期自动释放回池, 新 worker 接管;
6.   lease expiry — 过期 lease 被释放, 同一 mandate 可被重新 claim;
7.   duplicate worker — 已 lease 的 mandate 第二个 worker 拿不到(不双发);
8.   entry saturation — entry 面在 API 层面不存在(not hasattr);
9.   independent exit rate budget — 每轮提交 ≤ exit_rate_budget, 超出留队;
10.  unknown sellable quantity — claim 跳过, verified reconcile 后 KNOWN;
11.  correction-driven lot reopen — CLOSED 经 ReopenedEconomicLot 重新派生;
12.  24h 模拟时钟 — T+10 exit 在 due session 生成并提交, 失败提交下轮重试;
13.  shutdown 不释放 durable claims — TTL 后新 worker recover。

本文件引用尚未实现的调度器骨架(方法体一律 raise NotImplementedError);
当前应整体 RED(每个测试在构造点/方法体失败于 NotImplementedError), 由主
代理随后实现 GREEN。
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.screening.offensive.v3.capital.execution_revisions import (
    MANDATE_REVISION_FLOOR,
    ReopenedEconomicLot,
)
from src.screening.offensive.v3.contracts import (
    ExecutionMode,
    ExitQuantityKnowledge,
    PositionState,
)
from src.screening.offensive.v3.gateway.exits import (
    ExitDerivationContext,
    ExitDependencies,
    ExitLane,
    ExitLotTruth,
)
from src.screening.offensive.v3.services import lifecycle_scheduler as ls_module
from src.screening.offensive.v3.services.common import StaleLeaseError
from src.screening.offensive.v3.services.identity import ServiceIdentity
from src.screening.offensive.v3.services.lifecycle_scheduler import (
    LifecycleCycleResult,
    LifecycleScheduler,
    LifecycleSchedulerError,
    SCHEDULER_EXIT_BUDGET_EXHAUSTED,
    SCHEDULER_MAX_CLAIMS_NEGATIVE,
    SCHEDULER_RATE_BUDGET_NEGATIVE,
    SCHEDULER_RECONCILE_BUDGET_EXHAUSTED,
    SCHEDULER_SHUTDOWN,
)

UTC = timezone.utc
NOW = datetime(2026, 7, 30, 1, 0, tzinfo=UTC)
SIGNAL_SESSION = date(2026, 7, 16)  # Thursday
HASH = "a" * 64
FINGERPRINT = "c" * 64


def _sessions_after_signal(count: int) -> tuple[date, ...]:
    sessions: list[date] = []
    day = SIGNAL_SESSION
    while len(sessions) < count:
        day = day + timedelta(days=1)
        if day.weekday() < 5:
            sessions.append(day)
    return tuple(sessions)


ALL_SESSIONS = _sessions_after_signal(15)
DUE_SESSION = ALL_SESSIONS[9]  # 10th session after signal (entry ordinal 1)


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now_value = start

    def __call__(self) -> datetime:
        return self.now_value


@pytest.fixture()
def clock() -> _Clock:
    return _Clock(NOW)


def _lot(**overrides) -> ExitLotTruth:
    values = {
        "position_lineage_id": "lin-1",
        "economic_lot_id": "lot-1",
        "security_id": "600000.SH",
        "producer_namespace": "btst",
        "research_program_id": "prog-1",
        "economic_lineage_id": "eline-1",
        "stage_id": "stage-1",
        "position_state": PositionState.OPEN,
        "signal_session": SIGNAL_SESSION,
        "entry_session_ordinal": 1,
        "entry_plan_evidence_artifact_hash": HASH,
        "settled_quantity": 200,
        "tradable_quantity": 200,
        "live_exit_leaves": 0,
        "successor_security_id": None,
        "reopen": None,
    }
    values.update(overrides)
    return ExitLotTruth(**values)


def _context(**overrides) -> ExitDerivationContext:
    values = {
        "portfolio_id": "paper-v3",
        "broker_account_id": None,
        "base_currency": "CNY",
        "mode": ExecutionMode.DAILY_BAR_PROXY,
        "capital_version": 1,
        "writer_fencing_epoch": 1,
        "fixed_exit_policy_fingerprint": FINGERPRINT,
        "source_risk_snapshot_id": "risk-snap-exit-1",
        "source_risk_snapshot_hash": HASH,
        "trading_sessions": ALL_SESSIONS,
    }
    values.update(overrides)
    return ExitDerivationContext(**values)


def _reopen(**overrides) -> ReopenedEconomicLot:
    values = {
        "reopen_id": "reopen-1",
        "position_lineage_id": "lin-1",
        "economic_lot_id": "lot-1",
        "security_id": "600000.SH",
        "producer_namespace": "btst",
        "research_program_id": "prog-1",
        "economic_lineage_id": "eline-1",
        "stage_id": "stage-1",
        "reopened_quantity_units": 100,
        "position_state": PositionState.EXIT_PENDING,
        "reopen_reason": "exit bust restored positive holding",
        "mandate_revision_floor": MANDATE_REVISION_FLOOR,
        "reopened_by_execution_revision_id": "fill:exec-x:2",
        "reopened_by_event_id": "event-1",
        "capital_version": 2,
        "stream_version": 2,
    }
    values.update(overrides)
    return ReopenedEconomicLot(**values)


def _identity(tmp_path: Path, *, service_name: str = "lifecycle-scheduler") -> ServiceIdentity:
    return ServiceIdentity(
        service_name=service_name,
        capability_namespace="lifecycle.durable.v2",
        owner_uid=os.getuid(),
        owner_gid=os.getgid(),
        socket_path=tmp_path / f"{service_name}.sock",
        db_dsn=f"sqlite:///{tmp_path}/lifecycle.sqlite",
    )


def _make_scheduler(
    tmp_path: Path,
    clock: _Clock,
    *,
    exit_rate_budget: int = 100,
    reconcile_rate_budget: int = 100,
    max_claims_per_round: int = 20,
    worker_id: str = "lifecycle-scheduler-1",
    dependencies: ExitDependencies | None = None,
    fault_hook=None,
) -> LifecycleScheduler:
    lane = ExitLane(
        database_path=str(tmp_path / "lifecycle.sqlite3"),
        clock=clock,
        dependencies=dependencies,
        _fault_hook=fault_hook,
    )
    return LifecycleScheduler(
        identity=_identity(tmp_path),
        exit_lane=lane,
        exit_rate_budget=exit_rate_budget,
        reconcile_rate_budget=reconcile_rate_budget,
        max_claims_per_round=max_claims_per_round,
        worker_id=worker_id,
    )


def _broken_dependencies() -> ExitDependencies:
    def explode(name: str):
        def probe() -> object:
            raise RuntimeError(f"{name} endpoint unavailable")

        return probe

    return ExitDependencies(
        policy_probe=explode("policy"),
        envelope_probe=explode("envelope"),
        authorizer_probe=explode("authorizer"),
        publisher_probe=explode("publisher"),
        entry_probe=explode("entry"),
    )


# --------------------------------------------------------------------------
# 约束 1/2/8: API 面只有 derive/claim/submit/reconcile/query(risk-reducing)
# --------------------------------------------------------------------------

REQUIRED_SURFACE = (
    "run_cycle",
    "derive_and_claim",
    "claim_due_exit_work",
    "submit_exit",
    "reconcile",
    "exit_state",
    "write_process_lease",
    "validate_process_lease",
    "shutdown",
)
FORBIDDEN_SURFACE = (
    # entry proposal / permit 拓宽(约束 1/2/8: API 层面不存在)
    "publish_entry",
    "issue_permit",
    "make_outbox_durable",
    "claim_send",
    "activate_policy_and_envelope",
    "activate_trust_bundle",
    "raise_entry_fence",
    "acknowledge_fence",
    "cancel_unclaimed_entry",
    "record_delivery_outcome",
)


def test_scheduler_surface_exposes_only_risk_reducing_commands(
    tmp_path, clock
) -> None:
    scheduler = _make_scheduler(tmp_path, clock)
    for name in REQUIRED_SURFACE:
        assert callable(getattr(scheduler, name)), name
    for name in FORBIDDEN_SURFACE:
        assert not hasattr(scheduler, name), name


def test_scheduler_module_does_not_import_entry_machinery(
    tmp_path, clock
) -> None:
    # RED 阶段在构造点失败(NotImplementedError); GREEN 后同时验证 import 面
    # 没有 entry 侧机器: 禁入 capital / decisions / authority / evidence /
    # governance / producers / policy 段; 唯一的 gateway 面是 exit lane。
    _make_scheduler(tmp_path, clock)
    source = Path(ls_module.__file__).read_text(encoding="utf-8")
    forbidden = {"capital", "decisions", "authority", "evidence",
                 "governance", "producers", "policy"}
    assert _forbidden_import_hits(source, forbidden) == []
    assert "gateway.exits" in source


def _forbidden_import_hits(source: str, forbidden: set[str]) -> list[str]:
    """返回顶层 import 行中命中 forbidden 段的模块名。"""
    hits: list[str] = []
    for line in source.splitlines():
        if not line or line[0].isspace():
            continue
        if line.startswith("import "):
            module = line[len("import "):].split(" as ")[0].split(",")[0].strip()
        elif line.startswith("from "):
            module = line[len("from "):].split(" import ")[0].strip()
        else:
            continue
        if module.startswith("."):
            continue
        parts = module.split(".")
        # <...>.v3.<segment>(如 capital / evidence / policy)
        if len(parts) >= 5 and parts[4] in forbidden:
            hits.append(module)
        # <...>.v3.gateway.<submodule>(如 decisions / authority)
        if len(parts) >= 6 and parts[4] == "gateway" and parts[5] in forbidden:
            hits.append(module)
    return hits


# --------------------------------------------------------------------------
# 构造守卫(fail-closed)
# --------------------------------------------------------------------------


def test_negative_exit_rate_budget_is_rejected(tmp_path, clock) -> None:
    with pytest.raises(LifecycleSchedulerError) as excinfo:
        LifecycleScheduler(
            identity=_identity(tmp_path),
            exit_lane=ExitLane(
                database_path=str(tmp_path / "x.sqlite3"), clock=clock
            ),
            exit_rate_budget=-1,
            reconcile_rate_budget=100,
        )
    assert excinfo.value.code == SCHEDULER_RATE_BUDGET_NEGATIVE


def test_negative_reconcile_rate_budget_is_rejected(tmp_path, clock) -> None:
    with pytest.raises(LifecycleSchedulerError) as excinfo:
        LifecycleScheduler(
            identity=_identity(tmp_path),
            exit_lane=ExitLane(
                database_path=str(tmp_path / "x.sqlite3"), clock=clock
            ),
            exit_rate_budget=100,
            reconcile_rate_budget=-1,
        )
    assert excinfo.value.code == SCHEDULER_RATE_BUDGET_NEGATIVE


def test_negative_max_claims_is_rejected(tmp_path, clock) -> None:
    with pytest.raises(LifecycleSchedulerError) as excinfo:
        LifecycleScheduler(
            identity=_identity(tmp_path),
            exit_lane=ExitLane(
                database_path=str(tmp_path / "x.sqlite3"), clock=clock
            ),
            exit_rate_budget=100,
            reconcile_rate_budget=100,
            max_claims_per_round=-1,
        )
    assert excinfo.value.code == SCHEDULER_MAX_CLAIMS_NEGATIVE


# --------------------------------------------------------------------------
# 约束 3/4: 完整 cycle(无 CLI) + Publisher/Authorizer outage 独立性
# --------------------------------------------------------------------------


def test_full_cycle_runs_without_any_cli_command(tmp_path, clock) -> None:
    # 只用 scheduler 实例 + 模拟时钟驱动 derive→claim→submit→reconcile:
    # 没有任何 CLI 命令参与。
    scheduler = _make_scheduler(tmp_path, clock)
    scheduler.derive_and_claim(
        lots=(
            _lot(),
            _lot(
                position_lineage_id="lin-2",
                economic_lot_id="lot-2",
                tradable_quantity=None,
            ),
        ),
        context=_context(),
        as_of_session=SIGNAL_SESSION,
    )
    result = scheduler.run_cycle(as_of_session=DUE_SESSION)
    assert isinstance(result, LifecycleCycleResult)
    assert result.as_of_session == DUE_SESSION
    assert result.worker_id == "lifecycle-scheduler-1"
    assert result.claims_acquired == 1
    assert result.exits_submitted == 1
    assert result.submit_failures == 0
    assert result.reconciles_attempted == 1  # lin-2 pending → reconcile pass
    assert result.reconciles_resolved == 0  # 无 verified 数量, 仅保持 query
    assert result.reconcile_failures == 0
    assert result.exit_budget_remaining == 99
    assert result.reconcile_budget_remaining == 99
    # lin-1 的 T+10 exit 已提交(200 leaves on book); lin-2 保持 reconciliation
    state = scheduler.exit_state("lin-1", "lot-1")
    assert state.status == "PENDING"
    assert state.outstanding_attempt_leaves == 200
    pending = scheduler.exit_state("lin-2", "lot-2")
    assert pending.reconciliation_pending is True
    assert pending.outstanding_query_count == 1


def test_full_cycle_survives_publisher_and_authorizer_outage(
    tmp_path, clock
) -> None:
    # entry 侧依赖(policy/envelope/authorizer/publisher/entry)全部注入抛错
    # probes: exit lifecycle 从不调用它们, claim→submit→reconcile 仍完整。
    scheduler = _make_scheduler(
        tmp_path, clock, dependencies=_broken_dependencies()
    )
    scheduler.derive_and_claim(
        lots=(
            _lot(),
            _lot(
                position_lineage_id="lin-2",
                economic_lot_id="lot-2",
                tradable_quantity=None,
            ),
        ),
        context=_context(),
        as_of_session=SIGNAL_SESSION,
    )
    result = scheduler.run_cycle(as_of_session=DUE_SESSION)
    assert result.claims_acquired == 1
    assert result.exits_submitted == 1
    assert result.submit_failures == 0
    assert result.reconciles_attempted == 1
    assert result.reconcile_failures == 0
    assert scheduler.exit_state("lin-1", "lot-1").outstanding_attempt_leaves == 200


# --------------------------------------------------------------------------
# 约束 5/6/7: lease 生命周期 — 崩溃恢复、过期释放、duplicate worker 不双发
# --------------------------------------------------------------------------


def test_claim_survives_worker_crash_and_is_reclaimed_after_lease_expiry(
    tmp_path, clock
) -> None:
    crashed = _make_scheduler(tmp_path, clock, worker_id="worker-crashy")
    (work,) = crashed.derive_and_claim(
        lots=(_lot(),),
        context=_context(),
        as_of_session=DUE_SESSION,
    )
    assert work.lease_id
    mandate_id = crashed.exit_state("lin-1", "lot-1").exit_mandate_id
    # worker 崩溃: 不释放 lease, 直接丢弃实例; 新 worker 接管同一 DB。
    recovered = _make_scheduler(tmp_path, clock, worker_id="worker-2")
    clock.now_value = NOW + timedelta(minutes=31)
    result = recovered.run_cycle(as_of_session=DUE_SESSION)
    assert result.claims_acquired == 1
    assert result.exits_submitted == 1
    assert result.submit_failures == 0
    state = recovered.exit_state("lin-1", "lot-1")
    assert state.exit_mandate_id == mandate_id
    assert state.outstanding_attempt_leaves == 200


def test_expired_lease_is_released_and_reclaimable_by_same_worker(
    tmp_path, clock
) -> None:
    scheduler = _make_scheduler(tmp_path, clock)
    (work,) = scheduler.derive_and_claim(
        lots=(_lot(),),
        context=_context(),
        as_of_session=DUE_SESSION,
    )
    assert scheduler.exit_state("lin-1", "lot-1").leased is True
    clock.now_value = NOW + timedelta(minutes=31)
    result = scheduler.run_cycle(as_of_session=DUE_SESSION)
    # 过期 lease 被释放回池, 同一 mandate 被重新 claim 并提交
    assert result.claims_acquired == 1
    assert result.exits_submitted == 1
    assert scheduler.exit_state("lin-1", "lot-1").outstanding_attempt_leaves == 200
    del work


def test_second_worker_claims_nothing_while_lease_active(tmp_path, clock) -> None:
    first = _make_scheduler(tmp_path, clock, worker_id="worker-a")
    first.derive_and_claim(
        lots=(_lot(),),
        context=_context(),
        as_of_session=DUE_SESSION,
    )
    assert first.exit_state("lin-1", "lot-1").leased is True
    # 同一 mandate 已被 lease: 第二个 worker 拿不到它(lease 到期前不双发)
    second = _make_scheduler(tmp_path, clock, worker_id="worker-b")
    result = second.run_cycle(as_of_session=DUE_SESSION)
    assert result.claims_acquired == 0
    assert result.exits_submitted == 0
    assert second.exit_state("lin-1", "lot-1").outstanding_attempt_leaves == 0
    # lease 到期后第二个 worker 可以接管并提交(恰好一次)
    clock.now_value = NOW + timedelta(minutes=31)
    result = second.run_cycle(as_of_session=DUE_SESSION)
    assert result.claims_acquired == 1
    assert result.exits_submitted == 1
    assert second.exit_state("lin-1", "lot-1").outstanding_attempt_leaves == 200


# --------------------------------------------------------------------------
# 约束 9: 独立 exit 速率预算(每轮; 超出部分留在队列/下轮)
# --------------------------------------------------------------------------


def test_exit_rate_budget_caps_submissions_per_cycle(tmp_path, clock) -> None:
    scheduler = _make_scheduler(tmp_path, clock, exit_rate_budget=1)
    scheduler.derive_and_claim(
        lots=(_lot(), _lot(position_lineage_id="lin-2", economic_lot_id="lot-2")),
        context=_context(),
        as_of_session=SIGNAL_SESSION,
    )
    result = scheduler.run_cycle(as_of_session=DUE_SESSION)
    assert result.claims_acquired == 2
    assert result.exits_submitted == 1
    assert result.exit_budget_remaining == 0
    # 超预算的 claim 不提交: 保持 leased, 没有 attempt 落账
    second = scheduler.exit_state("lin-2", "lot-2")
    assert second.leased is True
    assert second.outstanding_attempt_leaves == 0
    # lease 到期后下一轮重取并提交
    clock.now_value = NOW + timedelta(minutes=31)
    result = scheduler.run_cycle(as_of_session=DUE_SESSION)
    assert result.exits_submitted == 1
    assert scheduler.exit_state("lin-2", "lot-2").outstanding_attempt_leaves == 200


def test_submit_exit_enforces_exit_rate_budget_directly(tmp_path, clock) -> None:
    scheduler = _make_scheduler(tmp_path, clock, exit_rate_budget=1)
    (first, second) = scheduler.derive_and_claim(
        lots=(_lot(), _lot(position_lineage_id="lin-2", economic_lot_id="lot-2")),
        context=_context(),
        as_of_session=DUE_SESSION,
    )
    scheduler.submit_exit(claim=first, attempt_id="attempt-1")
    with pytest.raises(LifecycleSchedulerError) as excinfo:
        scheduler.submit_exit(claim=second, attempt_id="attempt-2")
    assert excinfo.value.code == SCHEDULER_EXIT_BUDGET_EXHAUSTED
    # 预算耗尽未触达 lane: 第二个 mandate 没有任何 attempt
    assert scheduler.exit_state("lin-2", "lot-2").outstanding_attempt_leaves == 0


def test_reconcile_enforces_reconcile_rate_budget_directly(tmp_path, clock) -> None:
    scheduler = _make_scheduler(tmp_path, clock, reconcile_rate_budget=1)
    scheduler.derive_and_claim(
        lots=(_lot(tradable_quantity=None),),
        context=_context(),
        as_of_session=SIGNAL_SESSION,
    )
    resolved = scheduler.reconcile(
        position_lineage_id="lin-1",
        economic_lot_id="lot-1",
        reason="broker query",
    )
    assert resolved is None  # 无 verified 数量 → 仅排期 query
    with pytest.raises(LifecycleSchedulerError) as excinfo:
        scheduler.reconcile(
            position_lineage_id="lin-1",
            economic_lot_id="lot-1",
            reason="second query",
        )
    assert excinfo.value.code == SCHEDULER_RECONCILE_BUDGET_EXHAUSTED


# --------------------------------------------------------------------------
# 约束 10: unknown sellable quantity — claim 跳过, verified reconcile 后 KNOWN
# --------------------------------------------------------------------------


def test_unknown_quantity_is_skipped_until_verified_reconcile(
    tmp_path, clock
) -> None:
    scheduler = _make_scheduler(tmp_path, clock)
    claimed = scheduler.derive_and_claim(
        lots=(_lot(tradable_quantity=None),),
        context=_context(),
        as_of_session=DUE_SESSION,
    )
    assert claimed == ()
    state = scheduler.exit_state("lin-1", "lot-1")
    assert state.reconciliation_pending is True
    assert state.outstanding_query_count == 1
    # reconcile 带 verified 数量后 UNKNOWN → KNOWN, 可 claim
    resolved = scheduler.reconcile(
        position_lineage_id="lin-1",
        economic_lot_id="lot-1",
        reason="broker statement confirms holding",
        verified_tradable_quantity=150,
        live_exit_leaves=50,
    )
    assert resolved is not None
    assert resolved.quantity_knowledge is ExitQuantityKnowledge.KNOWN
    assert resolved.executable_quantity == 100
    (work,) = scheduler.claim_due_exit_work(as_of_session=DUE_SESSION)
    assert work.executable_quantity == 100
    assert work.stable_client_order_id == "exit-client-lin-1:lot-1"


def test_release_exit_lease_frees_claim_for_reclaim(tmp_path, clock) -> None:
    scheduler = _make_scheduler(tmp_path, clock)
    scheduler.derive_and_claim(
        lots=(_lot(),),
        context=_context(),
        as_of_session=SIGNAL_SESSION,
    )
    (work,) = scheduler.claim_due_exit_work(as_of_session=DUE_SESSION)
    # While leased, a second claim finds nothing.
    assert scheduler.claim_due_exit_work(as_of_session=DUE_SESSION) == ()
    # The scheduler releases its own lease; the obligation is reclaimable.
    scheduler.release_exit_lease(lease_id=work.lease_id)
    (reclaimed,) = scheduler.claim_due_exit_work(as_of_session=DUE_SESSION)
    assert reclaimed.exit_mandate_id == work.exit_mandate_id
    assert reclaimed.lease_id != work.lease_id


def test_release_exit_lease_after_shutdown_fails_closed(tmp_path, clock) -> None:
    scheduler = _make_scheduler(tmp_path, clock)
    scheduler.derive_and_claim(
        lots=(_lot(),),
        context=_context(),
        as_of_session=SIGNAL_SESSION,
    )
    (work,) = scheduler.claim_due_exit_work(as_of_session=DUE_SESSION)
    scheduler.shutdown()
    with pytest.raises(LifecycleSchedulerError, match="scheduler_shutdown"):
        scheduler.release_exit_lease(lease_id=work.lease_id)


# --------------------------------------------------------------------------
# 约束 11: correction-driven lot reopen(引用 ExitLane 的 reopen 链)
# --------------------------------------------------------------------------


def test_correction_reopen_revives_closed_lot_through_scheduler(
    tmp_path, clock
) -> None:
    scheduler = _make_scheduler(tmp_path, clock)
    scheduler.derive_and_claim(
        lots=(_lot(),),
        context=_context(),
        as_of_session=SIGNAL_SESSION,
    )
    # Lot 全部退出: truth 归零, mandate 关闭
    scheduler.derive_and_claim(
        lots=(_lot(tradable_quantity=0, settled_quantity=0),),
        context=_context(),
        as_of_session=SIGNAL_SESSION,
    )
    assert scheduler.exit_state("lin-1", "lot-1").status == "CLOSED"
    # 修正事实(correction-driven lot reopen)复活已关闭的 lot
    scheduler.derive_and_claim(
        lots=(
            _lot(
                position_state=PositionState.EXIT_PENDING,
                settled_quantity=100,
                tradable_quantity=100,
                reopen=_reopen(),
            ),
        ),
        context=_context(),
        as_of_session=SIGNAL_SESSION,
    )
    state = scheduler.exit_state("lin-1", "lot-1")
    assert state.status == "PENDING"
    assert state.mandate_revision == 3
    (work,) = scheduler.claim_due_exit_work(as_of_session=DUE_SESSION)
    assert work.executable_quantity == 100


# --------------------------------------------------------------------------
# 约束 12: 24h 模拟时钟 — T+10 exit 在 due session 生成并提交, 无 CLI;
# 失败提交在下一轮自动重试
# --------------------------------------------------------------------------


def test_t10_exit_is_generated_and_submitted_across_simulated_clock(
    tmp_path, clock
) -> None:
    scheduler = _make_scheduler(tmp_path, clock)
    before = clock.now_value
    # 信号日派生 T+10 义务
    scheduler.derive_and_claim(
        lots=(_lot(),),
        context=_context(),
        as_of_session=SIGNAL_SESSION,
    )
    # 模拟时钟分多个 session 推进(总计 ≥ 24h); due 之前绝不提交
    intermediate = [s for s in ALL_SESSIONS if SIGNAL_SESSION < s < DUE_SESSION]
    for session in intermediate:
        clock.now_value += timedelta(days=1)
        result = scheduler.run_cycle(as_of_session=session)
        assert result.claims_acquired == 0
        assert result.exits_submitted == 0
    clock.now_value += timedelta(hours=2)
    result = scheduler.run_cycle(as_of_session=DUE_SESSION)
    assert clock.now_value - before >= timedelta(hours=24)
    assert result.claims_acquired == 1
    assert result.exits_submitted == 1
    assert result.submit_failures == 0
    state = scheduler.exit_state("lin-1", "lot-1")
    assert state.due_session == DUE_SESSION
    assert state.outstanding_attempt_leaves == 200


def test_failed_submission_is_retried_next_round(tmp_path, clock) -> None:
    fired = {"n": 0}

    def fault_once(name: str) -> None:
        if name == "attempt.after_insert" and fired["n"] == 0:
            fired["n"] += 1
            raise RuntimeError("simulated submit crash")

    scheduler = _make_scheduler(tmp_path, clock, fault_hook=fault_once)
    scheduler.derive_and_claim(
        lots=(_lot(),),
        context=_context(),
        as_of_session=SIGNAL_SESSION,
    )
    first = scheduler.run_cycle(as_of_session=DUE_SESSION)
    assert first.claims_acquired == 1
    assert first.exits_submitted == 0
    assert first.submit_failures == 1
    # 失败提交回滚(lane 事务), claim 保持 leased 直到 TTL
    state = scheduler.exit_state("lin-1", "lot-1")
    assert state.outstanding_attempt_leaves == 0
    assert state.leased is True
    # 下一轮(时钟推进过 lease TTL)自动重试
    clock.now_value = NOW + timedelta(minutes=31)
    second = scheduler.run_cycle(as_of_session=DUE_SESSION)
    assert second.claims_acquired == 1
    assert second.exits_submitted == 1
    assert second.submit_failures == 0
    assert scheduler.exit_state("lin-1", "lot-1").outstanding_attempt_leaves == 200


# --------------------------------------------------------------------------
# 约束 13: shutdown 释放进程 lease 但保留 durable work claim(可恢复)
# --------------------------------------------------------------------------


def test_process_lease_roundtrip(tmp_path, clock) -> None:
    identity = _identity(tmp_path)
    scheduler = LifecycleScheduler(
        identity=identity,
        exit_lane=ExitLane(
            database_path=str(tmp_path / "lifecycle.sqlite3"), clock=clock
        ),
        exit_rate_budget=100,
        reconcile_rate_budget=100,
    )
    lease_path = tmp_path / "lifecycle-scheduler.lease.json"
    scheduler.write_process_lease(lease_path)
    payload = json.loads(lease_path.read_text(encoding="utf-8"))
    assert payload["pid"] == os.getpid()
    assert payload["service_name"] == identity.service_name
    assert payload["owner_uid"] == identity.owner_uid
    scheduler.validate_process_lease(lease_path)  # 自身 pid 存活, 不抛即通过


def test_shutdown_releases_process_lease_but_keeps_durable_claims(
    tmp_path, clock
) -> None:
    lease_path = tmp_path / "lifecycle-scheduler.lease.json"
    first = _make_scheduler(tmp_path, clock, worker_id="worker-a")
    first.write_process_lease(lease_path)
    (work,) = first.derive_and_claim(
        lots=(_lot(),),
        context=_context(),
        as_of_session=DUE_SESSION,
    )
    assert work.lease_id
    first.shutdown()
    # 进程 lease 被释放: 校验失败(fail-closed)
    with pytest.raises(StaleLeaseError):
        first.validate_process_lease(lease_path)
    # shutdown 后实例不再驱动 lifecycle
    with pytest.raises(LifecycleSchedulerError) as excinfo:
        first.run_cycle(as_of_session=DUE_SESSION)
    assert excinfo.value.code == SCHEDULER_SHUTDOWN
    # 但 durable work claim 仍在 DB 中(未释放): 新 worker 在 lease 到期后
    # 可以 recover 并提交
    recovered = _make_scheduler(tmp_path, clock, worker_id="worker-b")
    assert recovered.exit_state("lin-1", "lot-1").leased is True
    clock.now_value = NOW + timedelta(minutes=31)
    result = recovered.run_cycle(as_of_session=DUE_SESSION)
    assert result.claims_acquired == 1
    assert result.exits_submitted == 1
    assert recovered.exit_state("lin-1", "lot-1").outstanding_attempt_leaves == 200
