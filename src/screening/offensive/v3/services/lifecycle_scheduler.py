"""Plan 05 Task 4: 独立 durable lifecycle scheduler.

可重启的 worker 服务: 每轮 ``run_cycle`` 做 bounded work — claim 到期 exit
义务 → 在**独立** exit/reconcile 速率预算内提交 dispatch fact → 处理注册
lot 的 quantity reconciliation。调度器**只接受 risk-maintaining/reducing
命令**: 公开面上只有 derive / claim / submit / reconcile / query(exit_state);
不存在 ``publish_entry`` / ``issue_permit`` / ``make_outbox_durable`` /
``claim_send`` / ``activate_policy_and_envelope`` 等方法 — entry proposal
的创建与 permit 的拓宽在 API 面与 import 面双重不存在(能力矩阵测试扫描)。
entry 侧依赖(policy/envelope/authorizer/publisher/entry probes)由
``ExitDependencies`` 注入到 ExitLane, exit lifecycle 从不调用它们: 注入
抛错 probes 时 claim→submit→reconcile 仍完整执行。

进程生命周期: ``write_process_lease`` / ``validate_process_lease`` 用
``ServiceIdentity`` 写/校验进程 lease(复用 ``common.validate_process_lease``);
``shutdown()`` 释放进程 lease 但**不**释放任何 exit work lease — durable
claims 留在 lane DB, TTL 到期后由新 worker 接管(进程 kill / 崩溃 / 优雅
shutdown 同路径恢复)。shutdown 后的实例不再驱动 lifecycle(code
``SCHEDULER_SHUTDOWN``, fail-closed), 只读 query(``exit_state``)仍可用。

速率预算: ``exit_rate_budget`` / ``reconcile_rate_budget`` 是**每轮**独立
预算, 在构造时初始化、每轮 ``run_cycle`` 开始时重置。``submit_exit`` /
``reconcile`` 各自维护本轮剩余预算并在耗尽时抛
``SCHEDULER_EXIT_BUDGET_EXHAUSTED`` / ``SCHEDULER_RECONCILE_BUDGET_EXHAUSTED``
(fail-closed, 不触达 lane); ``run_cycle`` 循环内先查预算再调用, 超预算的
claim 不提交, 留在队列(lease 保持, TTL 后下轮重取)。单个提交抛错计入
``submit_failures`` 不终止本轮 — 该 claim 保持 leased, TTL 后下轮自动重试
(lane 的 attempt 记录是事务的, 失败即回滚, 重试用同一 attempt 语义幂等重放)。

worker 身份: 每轮 claim 以本实例的 ``worker_id`` 为 lease 主体; 同一
mandate 已被 lease 时其他 worker 拿不到它(到期前不双发)。``derive_and_claim``
将返回的 claims 交给调用方(可直接 ``submit_exit``); ``run_cycle`` 只提交
自己 claim 阶段拿到的 claims。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Final

from src.screening.offensive.v3.contracts import ExitMandate
from src.screening.offensive.v3.gateway.exits import (
    ClaimedExitWork,
    ExitAttemptOutcome,
    ExitDerivationContext,
    ExitLane,
    ExitLaneProjection,
    ExitLotTruth,
)
from src.screening.offensive.v3.services.common import (
    validate_process_lease as validate_common_process_lease,
)
from src.screening.offensive.v3.services.identity import ServiceIdentity

SCHEDULER_RATE_BUDGET_NEGATIVE: Final[str] = "scheduler_rate_budget_negative"
"""稳定 error code: 构造时 exit/reconcile 速率预算为负(fail-closed)。"""

SCHEDULER_MAX_CLAIMS_NEGATIVE: Final[str] = "scheduler_max_claims_negative"
"""稳定 error code: 构造时每轮 claim 上限为负(fail-closed)。"""

SCHEDULER_EXIT_BUDGET_EXHAUSTED: Final[str] = "scheduler_exit_budget_exhausted"
"""稳定 error code: 本轮 exit 速率预算耗尽, 拒绝继续提交。"""

SCHEDULER_RECONCILE_BUDGET_EXHAUSTED: Final[str] = (
    "scheduler_reconcile_budget_exhausted"
)
"""稳定 error code: 本轮 reconcile 速率预算耗尽, 拒绝继续 reconcile。"""

SCHEDULER_SHUTDOWN: Final[str] = "scheduler_shutdown"
"""稳定 error code: shutdown 后实例仍尝试驱动 lifecycle(fail-closed)。"""

RECONCILE_PASS_REASON: Final[str] = "scheduler_reconcile_pass"
"""run_cycle reconcile 阶段发起 unverified reconcile 时使用的 reason。"""


class LifecycleSchedulerError(RuntimeError):
    """调度器边界失败; code 是稳定机器码, details 携带诊断字段。"""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


@dataclass(frozen=True)
class LifecycleCycleResult:
    """一轮 ``run_cycle`` 的结果快照。

    - ``claims_acquired``: 本轮 claim 阶段新拿到的 lease 数(≤ max_claims)。
    - ``exits_submitted``: 本轮成功提交的 exit dispatch fact 数(≤ exit 预算)。
    - ``submit_failures``: 本轮提交抛错数(claim 保持 leased, 下轮重试)。
    - ``reconciles_attempted``: 本轮发起的 reconcile 数(≤ reconcile 预算)。
    - ``reconciles_resolved``: 其中带 verified 数量解决、返回刷新 mandate 的 lot 数。
    - ``reconcile_failures``: 本轮 reconcile 抛错数(下轮重试)。
    - ``exit_budget_remaining`` / ``reconcile_budget_remaining``: 本轮剩余预算
      (独立速率预算的实现位置: 每轮 run_cycle 开始时重置)。
    """

    as_of_session: date
    worker_id: str
    claims_acquired: int
    exits_submitted: int
    submit_failures: int
    reconciles_attempted: int
    reconciles_resolved: int
    reconcile_failures: int
    exit_budget_remaining: int
    reconcile_budget_remaining: int


class LifecycleScheduler:
    """独立 durable lifecycle worker: 只接受 risk-maintaining/reducing 命令。

    持有四个私有句柄/状态: ``_identity``(进程身份)、``_exit_lane``(exit
    mandate lane)、``_tracked_lots``(reconcile pass 候选注册表)与
    ``_process_lease_path``(write_process_lease 写入的进程 lease 路径)。
    """

    _identity: ServiceIdentity
    """服务进程身份: socket/lease/DB 归属声明, 用于进程 lease 写/校验。"""

    _exit_lane: ExitLane
    """注入的独立 exit mandate lane(derive/claim/attempt/reconcile/query)。"""

    _exit_rate_budget: int
    """每轮 exit 提交的独立速率预算(构造校验非负)。"""

    _reconcile_rate_budget: int
    """每轮 reconcile 的独立速率预算(构造校验非负)。"""

    _max_claims_per_round: int
    """每轮 run_cycle claim 阶段的上限(构造校验非负)。"""

    _worker_id: str
    """本 worker 的 lease 主体身份(默认 lifecycle-scheduler-1)。"""

    _shutdown: bool
    """shutdown 后置 True: lifecycle 驱动一律 fail-closed(SCHEDULER_SHUTDOWN)。"""

    _exit_budget_remaining: int
    """本轮 exit 预算剩余; run_cycle 每轮开始时重置为 _exit_rate_budget。"""

    _reconcile_budget_remaining: int
    """本轮 reconcile 预算剩余; run_cycle 每轮开始时重置。"""

    _tracked_lots: set[tuple[str, str]]
    """(position_lineage_id, economic_lot_id) 注册表: derive_and_claim 与
    reconcile 调用注册, run_cycle 的 reconcile 阶段在此候选内处理
    reconciliation_pending 的 lot。"""

    _process_lease_path: Path | None
    """最近一次 write_process_lease 写入的进程 lease 路径(shutdown 时释放)。"""

    def __init__(
        self,
        *,
        identity: ServiceIdentity,
        exit_lane: ExitLane,
        exit_rate_budget: int,
        reconcile_rate_budget: int,
        max_claims_per_round: int = 20,
        worker_id: str = "lifecycle-scheduler-1",
    ) -> None:
        """构造一个可重启的 lifecycle worker。

        守卫(按序):
        - ``exit_rate_budget`` < 0 或 ``reconcile_rate_budget`` < 0 → code
          ``SCHEDULER_RATE_BUDGET_NEGATIVE``(fail-closed);
        - ``max_claims_per_round`` < 0 → code ``SCHEDULER_MAX_CLAIMS_NEGATIVE``。

        实例化不创建任何 entry 面: 本类**没有** publish_entry / issue_permit /
        make_outbox_durable / claim_send / activate_policy_and_envelope 等
        方法(能力矩阵测试以 not hasattr 断言)。两个速率预算初始化为配置值
        (每轮 run_cycle 开始时重置); ``_tracked_lots`` 初始为空;
        ``_shutdown`` 初始 False; ``_process_lease_path`` 初始 None。
        """
        if exit_rate_budget < 0 or reconcile_rate_budget < 0:
            raise LifecycleSchedulerError(
                SCHEDULER_RATE_BUDGET_NEGATIVE,
                "scheduler rate budgets must be non-negative",
                exit_rate_budget=exit_rate_budget,
                reconcile_rate_budget=reconcile_rate_budget,
            )
        if max_claims_per_round < 0:
            raise LifecycleSchedulerError(
                SCHEDULER_MAX_CLAIMS_NEGATIVE,
                "max claims per round must be non-negative",
                max_claims_per_round=max_claims_per_round,
            )
        self._identity = identity
        self._exit_lane = exit_lane
        self._exit_rate_budget = exit_rate_budget
        self._reconcile_rate_budget = reconcile_rate_budget
        self._max_claims_per_round = max_claims_per_round
        self._worker_id = worker_id
        self._shutdown = False
        self._exit_budget_remaining = exit_rate_budget
        self._reconcile_budget_remaining = reconcile_rate_budget
        self._tracked_lots: set[tuple[str, str]] = set()
        self._process_lease_path: Path | None = None

    # -- 一轮 bounded work ----------------------------------------------------

    def run_cycle(self, *, as_of_session: date) -> LifecycleCycleResult:
        """一轮 bounded work: claim → 提交(exit 预算内) → reconcile(预算内)。

        步骤:
        1. claim: ``_exit_lane.claim_due_exit_work(as_of_session,
           worker_id=_worker_id, max_claims=_max_claims_per_round)`` —
           过期 lease 先由 lane 释放回池; 已 lease 的 mandate 不重复发;
           只有 KNOWN + 可执行 + 到期的义务会被 claim。
        2. submit: 对每个 claim, 若 exit 预算剩余 > 0 则 ``submit_exit``
           (SUBMITTED, submitted_leaves=claim.executable_quantity); 单个
           提交抛错计入 ``submit_failures`` 不终止本轮 — 该 claim 保持
           leased, TTL 后下轮自动重试(lane 的 attempt 记录事务回滚, 重试
           幂等); 超预算的 claim 不提交, 留在队列/下轮。
        3. reconcile: 对本实例注册过的 lot(derive_and_claim / reconcile
           调用注册)中 ``reconciliation_pending`` 的 lot, 在 reconcile
           预算内以 ``RECONCILE_PASS_REASON`` 发起 unverified ``reconcile``
           (无 verified 数量, 保持 query 打开 — 带 verified 数量的解决由
           调用方直接调用 ``reconcile``); 单个 reconcile 抛错计入
           ``reconcile_failures``。

        每轮开始重置 exit/reconcile 预算为构造配置。claim 阶段异常直接传播
        (lease 插入是事务的, 无部分 claim 需要恢复)。shutdown 后调用 →
        code ``SCHEDULER_SHUTDOWN``。本方法不依赖任何 CLI 命令 — 只用本
        实例 + 模拟时钟即可完整驱动。
        """
        self._require_active()
        self._exit_budget_remaining = self._exit_rate_budget
        self._reconcile_budget_remaining = self._reconcile_rate_budget
        claims = self._exit_lane.claim_due_exit_work(
            as_of_session=as_of_session,
            worker_id=self._worker_id,
            max_claims=self._max_claims_per_round,
        )
        exits_submitted = 0
        submit_failures = 0
        for claim in claims:
            if self._exit_budget_remaining <= 0:
                break  # 超预算的 claim 不提交: 保持 leased, TTL 后下轮重取
            try:
                self._submit_exit_claim(claim)
            except Exception:
                submit_failures += 1
            else:
                exits_submitted += 1
        reconciles_attempted = 0
        reconciles_resolved = 0
        reconcile_failures = 0
        for lineage, lot in sorted(self._tracked_lots):
            if self._reconcile_budget_remaining <= 0:
                break
            state = self._exit_lane.exit_state(lineage, lot)
            if state is None or not state.reconciliation_pending:
                continue
            try:
                resolved = self.reconcile(
                    position_lineage_id=lineage,
                    economic_lot_id=lot,
                    reason=RECONCILE_PASS_REASON,
                )
            except Exception:
                reconcile_failures += 1
            else:
                reconciles_attempted += 1
                if resolved is not None:
                    reconciles_resolved += 1
        return LifecycleCycleResult(
            as_of_session=as_of_session,
            worker_id=self._worker_id,
            claims_acquired=len(claims),
            exits_submitted=exits_submitted,
            submit_failures=submit_failures,
            reconciles_attempted=reconciles_attempted,
            reconciles_resolved=reconciles_resolved,
            reconcile_failures=reconcile_failures,
            exit_budget_remaining=self._exit_budget_remaining,
            reconcile_budget_remaining=self._reconcile_budget_remaining,
        )

    def derive_and_claim(
        self,
        *,
        lots: tuple[ExitLotTruth, ...],
        context: ExitDerivationContext,
        as_of_session: date,
        worker_id: str | None = None,
    ) -> tuple[ClaimedExitWork, ...]:
        """derive 后 claim: 先 ``derive_exit_mandates`` 再 ``claim_due_exit_work``。

        顺序保证 derive→claim; ``worker_id`` 缺省用本实例的 ``_worker_id``。
        返回的 claims 归调用方(可直接 ``submit_exit``, 或由 ``run_cycle``
        在 lease 到期后重新 claim)。每个派生 lot 注册进 ``_tracked_lots``
        (reconcile pass 候选)。shutdown 后调用 → code ``SCHEDULER_SHUTDOWN``。
        """
        self._require_active()
        self._exit_lane.derive_exit_mandates(lots, context=context)
        for lot in lots:
            self._tracked_lots.add(
                (lot.position_lineage_id, lot.economic_lot_id)
            )
        return self._exit_lane.claim_due_exit_work(
            as_of_session=as_of_session,
            worker_id=worker_id or self._worker_id,
            max_claims=self._max_claims_per_round,
        )

    def claim_due_exit_work(
        self,
        *,
        as_of_session: date,
        worker_id: str | None = None,
        blocked_securities: frozenset[str] = frozenset(),
        max_claims: int | None = None,
    ) -> tuple[ClaimedExitWork, ...]:
        """纯 claim(不过速率预算): 透传 lane 的 lease 语义。

        ``worker_id`` 缺省用本实例的 ``_worker_id``; ``max_claims`` 缺省用
        本实例的 ``_max_claims_per_round``。过期 lease 由 lane 先释放回池。
        shutdown 后调用 → code ``SCHEDULER_SHUTDOWN``。
        """
        self._require_active()
        return self._exit_lane.claim_due_exit_work(
            as_of_session=as_of_session,
            worker_id=worker_id or self._worker_id,
            blocked_securities=blocked_securities,
            max_claims=(
                self._max_claims_per_round if max_claims is None else max_claims
            ),
        )

    def submit_exit(
        self,
        *,
        claim: ClaimedExitWork,
        attempt_id: str,
        client_order_id: str | None = None,
        outcome: ExitAttemptOutcome = ExitAttemptOutcome.SUBMITTED,
        submitted_leaves: int | None = None,
    ) -> None:
        """提交一个 exit dispatch fact(exit 速率预算计数)。

        守卫: 本轮 exit 预算剩余 ≤ 0 → code ``SCHEDULER_EXIT_BUDGET_EXHAUSTED``
        (fail-closed, 不触达 lane); 成功记录后递减预算。缺省:
        ``client_order_id`` → ``claim.stable_client_order_id``(lane 强制稳定
        id, 猜测新 id 会抛 ``client_order_id_mismatch``); ``submitted_leaves``
        → ``claim.executable_quantity``。底层 lane 守卫(oversell / state
        conflict / attempt replay 等)原样透传。shutdown 后调用 → code
        ``SCHEDULER_SHUTDOWN``。
        """
        self._require_active()
        if self._exit_budget_remaining <= 0:
            raise LifecycleSchedulerError(
                SCHEDULER_EXIT_BUDGET_EXHAUSTED,
                "exit rate budget exhausted for this cycle",
            )
        self._exit_lane.record_exit_attempt(
            exit_mandate_id=claim.exit_mandate_id,
            attempt_id=attempt_id,
            client_order_id=(
                claim.stable_client_order_id
                if client_order_id is None
                else client_order_id
            ),
            outcome=outcome,
            submitted_leaves=(
                claim.executable_quantity
                if submitted_leaves is None
                else submitted_leaves
            ),
            filled_quantity=0,
        )
        self._exit_budget_remaining -= 1

    def reconcile(
        self,
        *,
        position_lineage_id: str,
        economic_lot_id: str,
        reason: str,
        verified_tradable_quantity: int | None = None,
        live_exit_leaves: int = 0,
    ) -> ExitMandate | None:
        """reconcile 一个 lot(reconcile 速率预算计数)。

        守卫: 本轮 reconcile 预算剩余 ≤ 0 → code
        ``SCHEDULER_RECONCILE_BUDGET_EXHAUSTED``(fail-closed, 不触达 lane);
        成功调用后递减预算。透传 lane 的 ``reconcile_exit`` 语义: 带 verified
        数量则解决并返回刷新 mandate(UNKNOWN → KNOWN, 之后可 claim);
        无 verified 数量仅排期 query 并返回 None。该 lot 注册进
        ``_tracked_lots``。shutdown 后调用 → code ``SCHEDULER_SHUTDOWN``。
        """
        self._require_active()
        if self._reconcile_budget_remaining <= 0:
            raise LifecycleSchedulerError(
                SCHEDULER_RECONCILE_BUDGET_EXHAUSTED,
                "reconcile rate budget exhausted for this cycle",
            )
        resolved = self._exit_lane.reconcile_exit(
            position_lineage_id=position_lineage_id,
            economic_lot_id=economic_lot_id,
            reason=reason,
            verified_tradable_quantity=verified_tradable_quantity,
            live_exit_leaves=live_exit_leaves,
        )
        self._tracked_lots.add((position_lineage_id, economic_lot_id))
        self._reconcile_budget_remaining -= 1
        return resolved

    # -- 只读 query -----------------------------------------------------------

    def exit_state(
        self, position_lineage_id: str, economic_lot_id: str
    ) -> ExitLaneProjection | None:
        """只读 query: 一个 lot 的 exit 义务投影; 无 mandate 返回 None。

        任何时刻可用(包括 shutdown 之后): 不驱动 lifecycle, 不消费速率
        预算, 不触达任何 entry 侧依赖。
        """
        return self._exit_lane.exit_state(position_lineage_id, economic_lot_id)

    # -- 进程 lease -----------------------------------------------------------

    def write_process_lease(self, path: Path) -> None:
        """用 ServiceIdentity 写进程 lease JSON(common.ProcessLease 字段)。

        写入 ``{pid: os.getpid(), service_name: identity.service_name,
        started_at: <UTC now iso>, owner_uid: identity.owner_uid}`` 至
        ``path``; 记住该路径供 shutdown 释放。已存在的 lease 被本身份的
        字段覆盖。GREEN 实现不得把签名材料或 writable DSN 暴露给 CLI
        principal(见 ``ServiceIdentity.require_private_access``)。
        """
        self._process_lease_path = path
        payload = {
            "pid": os.getpid(),
            "service_name": self._identity.service_name,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "owner_uid": self._identity.owner_uid,
        }
        path.write_text(json.dumps(payload), encoding="utf-8")

    def validate_process_lease(self, path: Path) -> None:
        """校验进程 lease: 委托 ``common.validate_process_lease``。

        期望 ``service_name=identity.service_name``、
        ``owner_uid=identity.owner_uid``; 缺失/损坏/pid 已死/身份不匹配 →
        ``StaleLeaseError``(fail-closed)。
        """
        validate_common_process_lease(
            path,
            expected_service_name=self._identity.service_name,
            expected_owner_uid=self._identity.owner_uid,
        )

    def shutdown(self) -> None:
        """释放进程 lease(删除 write_process_lease 写入的 lease 文件, 幂等)。

        **不**释放任何 exit work lease — durable claims 留在 lane DB, TTL
        到期后由新 worker(或重启的进程)接管恢复。shutdown 后本实例不再
        驱动 lifecycle(``run_cycle`` / ``derive_and_claim`` /
        ``claim_due_exit_work`` / ``submit_exit`` / ``reconcile`` → code
        ``SCHEDULER_SHUTDOWN``), 只读 query(``exit_state``)仍可用。
        """
        if self._process_lease_path is not None:
            try:
                self._process_lease_path.unlink()
            except FileNotFoundError:
                pass
            self._process_lease_path = None
        self._shutdown = True

    # -- 私有守卫 ----------------------------------------------------------------

    def _require_active(self) -> None:
        """Fail-closed: shutdown 后不得驱动 lifecycle。

        ``run_cycle`` / ``derive_and_claim`` / ``claim_due_exit_work`` /
        ``submit_exit`` / ``reconcile`` 最先调用本方法; shutdown 之后抛
        ``LifecycleSchedulerError`` code ``SCHEDULER_SHUTDOWN``。只读 query
        (``exit_state``) 与进程 lease 写/校验不经过本守卫。
        """
        if self._shutdown:
            raise LifecycleSchedulerError(
                SCHEDULER_SHUTDOWN,
                "lifecycle scheduler has been shut down",
            )

    def _submit_exit_claim(self, claim: ClaimedExitWork) -> None:
        """提交一个 claim 为 SUBMITTED exit fact(调用方已查预算)。

        ``run_cycle`` 内部使用的提交路径: 与公开 ``submit_exit`` 同一守卫
        语义(预算剩余 ≤ 0 抛 ``SCHEDULER_EXIT_BUDGET_EXHAUSTED``), 但以
        稳定的 attempt_id 幂等重放 — 同一 claim 的重试必须复用同一 attempt
        id(lane 的 attempt 记录是事务的, 失败即回滚, 重试幂等)。
        """
        self._require_active()
        if self._exit_budget_remaining <= 0:
            raise LifecycleSchedulerError(
                SCHEDULER_EXIT_BUDGET_EXHAUSTED,
                "exit rate budget exhausted for this cycle",
            )
        self._exit_lane.record_exit_attempt(
            exit_mandate_id=claim.exit_mandate_id,
            attempt_id=(
                f"attempt:{claim.exit_mandate_id}:"
                f"{claim.lease_id.replace('lease:', '')}"
            ),
            client_order_id=claim.stable_client_order_id,
            outcome=ExitAttemptOutcome.SUBMITTED,
            submitted_leaves=claim.executable_quantity,
            filled_quantity=0,
        )
        self._exit_budget_remaining -= 1


__all__ = [
    "LifecycleCycleResult",
    "LifecycleScheduler",
    "LifecycleSchedulerError",
    "RECONCILE_PASS_REASON",
    "SCHEDULER_EXIT_BUDGET_EXHAUSTED",
    "SCHEDULER_MAX_CLAIMS_NEGATIVE",
    "SCHEDULER_RATE_BUDGET_NEGATIVE",
    "SCHEDULER_RECONCILE_BUDGET_EXHAUSTED",
    "SCHEDULER_SHUTDOWN",
]
