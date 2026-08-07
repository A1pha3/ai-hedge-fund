"""Plan 05 Task 3: CapitalGatewayApi — 唯一的资本 authority writer 面.

薄适配器包装 Plan 02/04 已存在的仓库: capital ledger
(``CapitalRepository``)、gateway authority CAS (``GatewayAuthorityRepository``)、
entry admission/send-right 线性化 (``CapitalGateway``) 与 exit mandate lane
(``ExitLane``)。本服务是 Plan 05 中**唯一**被允许 import ``capital`` /
``gateway`` / ``execution`` 的服务(能力矩阵测试扫描源码), 因此它是资本
ledger 的唯一 writer 句柄与唯一 authority 激活面。

能力矩阵(本服务必须拥有、其它服务不得拥有的方法):
- authority 激活/fence: ``activate_trust_bundle`` / ``activate_policy_and_envelope`` /
  ``raise_entry_fence`` / ``acknowledge_fence``
- 可执行 entry: ``publish_entry`` / ``issue_permit`` / ``make_outbox_durable`` /
  ``claim_send`` / ``cancel_unclaimed_entry`` / ``record_delivery_outcome``
- exit/reconcile lifecycle: ``derive_exit_mandates`` / ``claim_due_exit_work`` /
  ``record_exit_attempt`` / ``reconcile_exit``
本服务**不**暴露 publisher/finalizer/authorizer/governance 的写面, 也**不**暴露
capital 裸写(``append_atomic`` / ``run_append`` / ``record_fill_revision`` /
``record_fee_revision`` / ``confirm_observed_nav`` — 这些是 capital/repository 的
内部, gateway 只通过 execution proxy 间接写)。

runtime-mode 守卫: 构造时注入 ``runtime_mode_provider``(默认 ``None`` →
恒 ``RuntimeMode.AUTHORITATIVE``)。每次 gated entry 路由调用时最先读
``provider()``; ``OFF`` / ``SHADOW`` 抛 ``CapitalGatewayError`` code
``execution_authority_disabled``。exit/reconcile/correction lifecycle 路由
**不**经过此 gate(entry halt 期间仍可用)。

``activate_policy_and_envelope`` 要求**显式签名批准**输入(参照 Task 2
GovernanceApi 的 ``approval: SignedEnvelope`` 模式, 无环境变量 fallback):
approval 必须存在、namespace 必须等于 ``POLICY_APPROVAL_NAMESPACE``、artifact
必须是 PLAN/TRUST-class(``POLICY_APPROVAL_ARTIFACT_KINDS``); 任一不符抛
``CapitalGatewayError`` 且不触达底层仓库。任何本地(无签名)policy 激活不可能。

``claim_send`` 在本 plan 被显式禁用: runtime gate 之后无条件抛
``CapitalGatewayError`` code ``send_claimed_disabled`` — 真实发送路径
(SEND_CLAIMED) 不在此 plan 开放。

Import 边界: 模块顶层只允许 import ``contracts`` / ``capital`` / ``gateway`` /
``policy.models``(与 services 兄弟模块); **不得** import ``evidence`` /
``governance`` / ``producers`` 段(能力矩阵测试扫描源码断言)。

signer 私有: 本服务持有 ``_signer``(若后续 plan 引入签名面)不得暴露任何
公开访问器。

注意: 本模块当前是 RED 骨架 — 所有方法体 ``raise NotImplementedError``, 由主
代理随后实现 GREEN(直接透传底层 + 上述 fail-closed 守卫)。
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Callable, Final

from src.screening.offensive.v3.capital.repository import CapitalRepository
from src.screening.offensive.v3.contracts import (
    ArtifactKind,
    CapitalAuthorizationEnvelope,
    CapitalRiskSnapshot,
    DecisionLogicalKey,
    EntryCancellationReceipt,
    EntryFenceAcknowledgement,
    EntryFenceRaised,
    ExecutionMode,
    ExecutionPermit,
    ExitMandate,
    GatewayExpectedVersions,
    PolicyActivation,
    PortfolioDecisionSeal,
    SendClaimExpectedVersions,
    SignedEnvelope,
    TrustBundle,
)
from src.screening.offensive.v3.gateway.authority import (
    ActiveAuthorityState,
    GatewayAuthorityRepository,
    TrustBundleVerifierProtocol,
)
from src.screening.offensive.v3.gateway.decisions import (
    AdmissionContext,
    CapitalGateway,
    CapitalGatewayError,
    ClaimedSend,
    DeliveryOutcome,
    DurableOutbox,
    EntryStateProjection,
    GatewayTruthContext,
    PermittedEntry,
    SealedEntry,
)
from src.screening.offensive.v3.gateway.exits import (
    ClaimedExitWork,
    ExitAttemptOutcome,
    ExitDerivationContext,
    ExitLane,
    ExitLaneProjection,
    ExitLotTruth,
)
from src.screening.offensive.v3.policy.models import RuntimeMode

POLICY_APPROVAL_NAMESPACE: Final[str] = "capital-governance.policy-activation.v1"
"""policy+envelope 联合激活的显式批准必须签名在此 namespace 之下。"""

POLICY_APPROVAL_ARTIFACT_KINDS: Final[frozenset] = frozenset(
    {ArtifactKind.POLICY_ACTIVATION, ArtifactKind.PLAN}
)
"""接受为 policy 激活批准的 artifact: POLICY_ACTIVATION 或 PLAN-class。"""

POLICY_APPROVAL_REQUIRED: Final[str] = "policy_approval_required"
"""稳定 error code: activate_policy_and_envelope 缺少显式签名批准输入。"""

POLICY_APPROVAL_NAMESPACE_MISMATCH: Final[str] = (
    "policy_approval_namespace_mismatch"
)
"""稳定 error code: 批准签名在错误的 namespace 之下。"""

POLICY_APPROVAL_ARTIFACT_REJECTED: Final[str] = (
    "policy_approval_artifact_rejected"
)
"""稳定 error code: 批准 artifact 不是 POLICY_ACTIVATION/PLAN-class。"""

EXECUTION_AUTHORITY_DISABLED: Final[str] = "execution_authority_disabled"
"""稳定 error code: runtime OFF|SHADOW 下可执行 entry 写入被拒绝。"""

SEND_CLAIMED_DISABLED: Final[str] = "send_claimed_disabled"
"""稳定 error code: 本 plan 禁用 SEND_CLAIMED 真实发送路径。"""


class CapitalGatewayApi:
    """唯一的资本 authority writer 面: authority CAS + entry + exit lane。

    服务持有四个私有句柄: ``_capital``(ledger)、``_authority``(authority CAS)、
    ``_gateway``(entry 线性化)、``_exits``(exit lane); ``database_path`` 是
    authority/decisions/exits 共享的 gateway DB, ``capital_path`` 是独立的
    Plan 02 ledger(``CapitalRepository.open`` 校验 schema)。所有公开方法都是
    底层仓库的薄透传, 叠加 fail-closed 守卫。
    """

    _capital: CapitalRepository
    """Plan 02 capital ledger 的唯一服务内句柄(顶层 import 面含 capital)。"""

    _authority: GatewayAuthorityRepository
    """gateway authority CAS 仓库(trust bundle/policy/envelope/fence)。"""

    _gateway: CapitalGateway
    """entry admission 与 send-right 线性化(seal/permit/outbox/delivery)。"""

    _exits: ExitLane
    """独立的 exit mandate lane(derive/claim/attempt/reconcile)。"""

    _signer: object | None
    """私有 signer 占位: 无任何公开访问器; 本 plan 不开放签名面。"""

    def __init__(
        self,
        *,
        database_path: str,
        capital_path: str | Path,
        clock: Callable[[], datetime],
        bundle_verifier: TrustBundleVerifierProtocol,
        mode: ExecutionMode,
        broker_account_id: str | None,
        runtime_mode_provider: Callable[[], RuntimeMode] | None = None,
    ) -> None:
        """构造唯一的资本 authority writer。

        - ``database_path``: gateway 专属 DB(authority + decisions + exits 共享)。
        - ``capital_path``: Plan 02 capital ledger 路径; 打开时 ``.open()``
          校验 schema, 不匹配 fail-closed。
        - ``clock``: 可信时钟源, 透传给三个 gateway 仓库。
        - ``bundle_verifier``: 透传给 ``GatewayAuthorityRepository``。
        - ``mode`` / ``broker_account_id``: 本 gateway writer 的账户身份。
        - ``runtime_mode_provider``: 每次 gated route 调用时读取; ``None``
          等价于恒返回 ``RuntimeMode.AUTHORITATIVE``。
        """
        self._signer: object | None = None
        self._runtime_mode_provider = runtime_mode_provider
        self._capital = CapitalRepository.open(capital_path)
        self._authority = GatewayAuthorityRepository(
            database_path=database_path,
            mode=mode,
            broker_account_id=broker_account_id,
            bundle_verifier=bundle_verifier,
            clock=clock,
        )
        self._gateway = CapitalGateway(
            database_path=database_path,
            clock=clock,
        )
        self._exits = ExitLane(
            database_path=database_path,
            clock=clock,
        )

    # -- 读面(任何 principal 可调用, quiet) ------------------------------------

    def risk_snapshot(
        self, portfolio_id: str, as_of: datetime
    ) -> CapitalRiskSnapshot:
        """只读风险快照: 透传 ``capital.capital_risk_snapshot(as_of)``。

        quiet 读: 绝不增长 stream/capital version。``portfolio_id`` 声明调用方
        期望的 portfolio, 读取本身按 ledger 单账户进行。
        """
        return self._capital.capital_risk_snapshot(as_of)

    def authority_state(self, portfolio_id: str) -> ActiveAuthorityState:
        """只读投影: 一个 portfolio 的 authority 状态(active envelope/fence)。"""
        return self._authority.active_state(portfolio_id)

    def entry_state(self, seal_id: str) -> EntryStateProjection | None:
        """只读投影: 一个 entry 的 send-right 状态机; 无该 seal 返回 None。"""
        return self._gateway.entry_state(seal_id)

    def active_seal(
        self, logical_key: DecisionLogicalKey
    ) -> tuple[str, int] | None:
        """只读投影: 一个 economic key 的 active seal (seal_id, revision)。"""
        return self._gateway.active_seal(logical_key)

    def exit_state(
        self, position_lineage_id: str, economic_lot_id: str
    ) -> ExitLaneProjection | None:
        """只读投影: 一个 lot 的 exit 义务; 无 mandate 返回 None。"""
        return self._exits.exit_state(position_lineage_id, economic_lot_id)

    # -- authority 激活 / fence(必须显式签名批准输入) --------------------------

    def activate_trust_bundle(
        self, signed: SignedEnvelope, *, trusted_at: datetime
    ) -> TrustBundle:
        """激活一个签名 trust bundle; epochs 单调不回退。

        ``signed`` 本身即批准输入(经 ``bundle_verifier`` 验证); 底层错误
        (``registry_epoch_rollback`` / ``trust_bundle_already_active``) 透传。
        """
        return self._authority.activate_trust_bundle(signed, trusted_at=trusted_at)

    def activate_policy_and_envelope(
        self,
        policy: PolicyActivation,
        envelope: CapitalAuthorizationEnvelope,
        *,
        approval: SignedEnvelope,
    ) -> None:
        """联合激活一个 behavior policy 与其 envelope(单事务 CAS)。

        Fail-closed 守卫(按序):
        - ``approval`` 必须为显式签名批准输入(缺失/``None`` → code
          ``POLICY_APPROVAL_REQUIRED``; 无环境变量 fallback);
        - ``approval.namespace`` 必须等于 ``POLICY_APPROVAL_NAMESPACE``
          (code ``POLICY_APPROVAL_NAMESPACE_MISMATCH``);
        - ``approval.artifact`` 必须在 ``POLICY_APPROVAL_ARTIFACT_KINDS``
          (code ``POLICY_APPROVAL_ARTIFACT_REJECTED``);
        - runtime gate: ``OFF`` / ``SHADOW`` → code
          ``EXECUTION_AUTHORITY_DISABLED``(本地 policy 激活不可能)。
        底层 CAS 错误(``envelope_already_active`` / ``policy_epoch_rollback`` /
        ``mode_mismatch`` …)原样透传。
        """
        if approval is None:
            raise CapitalGatewayError(
                POLICY_APPROVAL_REQUIRED,
                "activate_policy_and_envelope requires an explicit signed"
                " approval input",
            )
        if approval.namespace != POLICY_APPROVAL_NAMESPACE:
            raise CapitalGatewayError(
                POLICY_APPROVAL_NAMESPACE_MISMATCH,
                "policy approval is signed under a different namespace",
                expected=POLICY_APPROVAL_NAMESPACE,
                observed=approval.namespace,
            )
        if approval.artifact not in POLICY_APPROVAL_ARTIFACT_KINDS:
            raise CapitalGatewayError(
                POLICY_APPROVAL_ARTIFACT_REJECTED,
                "policy approval artifact is not POLICY_ACTIVATION/PLAN-class",
                artifact=approval.artifact.value,
            )
        self._require_execution_authority()
        self._authority.activate_policy_and_envelope(policy, envelope)

    def raise_entry_fence(self, fence: EntryFenceRaised) -> None:
        """持久化一个 entry fence 并 fencen 该 portfolio(幂等)。

        底层错误(``fence_identity_conflict``)透传; exit lane 永不受影响。
        """
        self._authority.raise_entry_fence(fence)

    def acknowledge_fence(self, ack: EntryFenceAcknowledgement) -> None:
        """durable ACK 一个已提交 fence; 幂等。

        ACK 只能引用已提交的 fence: 未 raise 的 fence 抛底层
        ``fence_unknown``; hash 不匹配抛 ``fence_hash_mismatch``。
        """
        self._authority.acknowledge_fence(ack)

    # -- lifecycle(exit/reconcile/correction; entry halt 期间仍可用) -----------

    def derive_exit_mandates(
        self,
        lots: tuple[ExitLotTruth, ...],
        *,
        context: ExitDerivationContext,
    ) -> tuple[ExitMandate, ...]:
        """从注入的 capital truth 派生/刷新每个 lot 的 exit mandate。

        不经过 runtime gate: entry halt(OFF/SHADOW)不影响 exit 义务。
        """
        return self._exits.derive_exit_mandates(lots, context=context)

    def claim_due_exit_work(
        self,
        *,
        as_of_session: date,
        worker_id: str,
        blocked_securities: frozenset[str] = frozenset(),
        max_claims: int | None = None,
    ) -> tuple[ClaimedExitWork, ...]:
        """租借到期、已知、可执行的 mandate 给一个 worker。

        不经过 runtime gate: 入口 halt 期间 exit 调度保持可用。
        """
        return self._exits.claim_due_exit_work(
            as_of_session=as_of_session,
            worker_id=worker_id,
            blocked_securities=blocked_securities,
            max_claims=max_claims,
        )

    def record_exit_attempt(
        self,
        *,
        exit_mandate_id: str,
        attempt_id: str,
        client_order_id: str,
        outcome: ExitAttemptOutcome,
        submitted_leaves: int = 0,
        filled_quantity: int = 0,
    ) -> None:
        """记录一个 durable exit dispatch fact; 不经过 runtime gate。"""
        self._exits.record_exit_attempt(
            exit_mandate_id=exit_mandate_id,
            attempt_id=attempt_id,
            client_order_id=client_order_id,
            outcome=outcome,
            submitted_leaves=submitted_leaves,
            filled_quantity=filled_quantity,
        )

    def reconcile_exit(
        self,
        *,
        position_lineage_id: str,
        economic_lot_id: str,
        reason: str,
        verified_tradable_quantity: int | None = None,
        live_exit_leaves: int = 0,
    ) -> ExitMandate | None:
        """解决或排期一个 lot 的 quantity reconciliation; 不经过 runtime gate。"""
        return self._exits.reconcile_exit(
            position_lineage_id=position_lineage_id,
            economic_lot_id=economic_lot_id,
            reason=reason,
            verified_tradable_quantity=verified_tradable_quantity,
            live_exit_leaves=live_exit_leaves,
        )

    # -- gated entry(runtime OFF|SHADOW 拒绝可执行 entry) ----------------------

    def publish_entry(
        self,
        seal: PortfolioDecisionSeal,
        *,
        expected_versions: GatewayExpectedVersions,
        context: AdmissionContext,
    ) -> SealedEntry:
        """原子 admit 一个 proposal: CAS + reserve + seal。

        Runtime gate 最先执行: ``OFF`` / ``SHADOW`` → code
        ``EXECUTION_AUTHORITY_DISABLED``; 之后透传 ``CapitalGateway``
        (``reserve_insufficient`` / ``seal_cas_conflict`` …)。
        """
        self._require_execution_authority()
        return self._gateway.publish_entry(
            seal, expected_versions=expected_versions, context=context
        )

    def issue_permit(
        self,
        permit: ExecutionPermit,
        *,
        context: GatewayTruthContext,
    ) -> PermittedEntry:
        """permit 一个已 seal 的 plan(preserve/shrink/cancel)。

        Runtime gate 最先执行(``EXECUTION_AUTHORITY_DISABLED``), 之后透传
        底层 deadline/halt/truth 校验(``permit_expired`` …)。
        """
        self._require_execution_authority()
        return self._gateway.issue_permit(permit, context=context)

    def make_outbox_durable(self, permit: ExecutionPermit) -> DurableOutbox:
        """持久化 permit 的 frozen outbox batch。

        Runtime gate 最先执行(``EXECUTION_AUTHORITY_DISABLED``), 之后透传
        底层(``permit_expired`` / ``outbox_requires_sendable`` …)。
        """
        self._require_execution_authority()
        return self._gateway.make_outbox_durable(permit)

    def claim_send(
        self,
        permit: ExecutionPermit,
        expected_versions: SendClaimExpectedVersions,
        *,
        context: GatewayTruthContext,
    ) -> ClaimedSend:
        """send-right 最终线性化 — **本 plan 显式禁用**。

        守卫(按序):
        1. runtime gate: ``OFF`` / ``SHADOW`` → code
           ``EXECUTION_AUTHORITY_DISABLED``;
        2. 无论 runtime_mode 如何, 本 plan 不开放真实发送路径 → code
           ``SEND_CLAIMED_DISABLED``。
        """
        self._require_execution_authority()
        raise CapitalGatewayError(
            SEND_CLAIMED_DISABLED,
            "SEND_CLAIMED real send path is disabled in this plan",
        )

    def cancel_unclaimed_entry(
        self, receipt: EntryCancellationReceipt
    ) -> None:
        """原子 tombstone 一个 unclaimed ALLOW permit/outbox。

        Runtime gate 最先执行(``EXECUTION_AUTHORITY_DISABLED``); claim 后的
        entry 不可取消(底层 ``cancel_forbidden_after_claim``)。
        """
        self._require_execution_authority()
        self._gateway.cancel_unclaimed_entry(receipt)

    def record_delivery_outcome(
        self,
        seal_id: str,
        outcome: DeliveryOutcome,
        *,
        submission_client_order_ids: tuple[str, ...] | None = None,
    ) -> None:
        """记录 SUBMISSION_AMBIGUOUS | BROKER_ACK(无任何网络调用)。

        Runtime gate 最先执行(``EXECUTION_AUTHORITY_DISABLED``); client ids
        必须精确复用 claim 集合(底层 ``client_order_id_mismatch``)。
        """
        self._require_execution_authority()
        self._gateway.record_delivery_outcome(
            seal_id,
            outcome,
            submission_client_order_ids=submission_client_order_ids,
        )

    # -- 私有守卫 ----------------------------------------------------------------

    def _require_execution_authority(self) -> None:
        """Fail-closed runtime gate: OFF|SHADOW 拒绝可执行 entry 写入。

        每次 gated route 调用时**最先**执行: 读 ``runtime_mode_provider()``
        (默认 ``None`` → 恒 ``RuntimeMode.AUTHORITATIVE``); 若为
        ``RuntimeMode.OFF`` 或 ``RuntimeMode.SHADOW`` 抛 ``CapitalGatewayError``
        code ``EXECUTION_AUTHORITY_DISABLED``。exit/reconcile/correction
        lifecycle 路由不经过此 gate。
        """
        if self._runtime_mode_provider is None:
            return
        if self._runtime_mode_provider() in (
            RuntimeMode.OFF,
            RuntimeMode.SHADOW,
        ):
            raise CapitalGatewayError(
                EXECUTION_AUTHORITY_DISABLED,
                "executable entry requires authoritative runtime mode",
            )


__all__ = [
    "EXECUTION_AUTHORITY_DISABLED",
    "POLICY_APPROVAL_ARTIFACT_KINDS",
    "POLICY_APPROVAL_ARTIFACT_REJECTED",
    "POLICY_APPROVAL_NAMESPACE",
    "POLICY_APPROVAL_NAMESPACE_MISMATCH",
    "POLICY_APPROVAL_REQUIRED",
    "SEND_CLAIMED_DISABLED",
    "CapitalGatewayApi",
]
