"""Plan 05 Task 9 S4: shadow 观测编排的 ephemeral 信任上下文 + 合成 authority。

本模块是 CLI 库层 shadow 编排的 composition 辅助 (owner 批准方案 A): 为 shadow
观测构造一次性 ephemeral 信任基建 + 合成 PolicyActivation/CapitalAuthorizationEnvelope
(确定性占位, 满足 kernel admission 硬校验), 使 DailyActionFlow / AutoFlow 的
shadow 管线能真正跑到 kernel decide (ADMITTED), 产出有意义的 ShadowDecision。

-------------------------------------------------------------------------------
为何是"合成" authority 而非真实 governance 激活
-------------------------------------------------------------------------------
Plan 05 是 shadow-only, Plan 全局约束禁止真实 governance 激活 / 持久化签名材料。
但 shadow 观测需要 kernel 实际 ADMIT 才能产出 ShadowDecision (而非恒 BLOCKED);
S2b 已修 family_id 断裂 (flow 用 ``BTST_FAMILY`` 常量), 此处补上"解锁 admission
的占位 envelope"。这不是授权 — flow 的 ``execution_authority`` 恒 ``"none"``,
绝不产生可执行 line; 合成 envelope 只是观测用解锁。真实 governance 激活留待
Plan 06+ privileged worker。

合成 grant 的 ``behavior_fingerprint``/``execution_version``/``cost_version`` 必须
与 BTST producer 信封逐字一致 (kernel/admission.py:106-111 硬校验): producer 在
``producers/auto.py:_signal_envelope`` 固定盖 ``execution_version="btst.funnel.v1"``、
``cost_version="cn-a-share-costs.v1"``, 行为指纹由 ``BtstProducerApi`` 注入
(默认 ``BTST_BEHAVIOR_BASELINE`` = sha256("btst-v1"))。本模块用同一组确定性常量
构造 grant, 保证 ADMITTED。常量写死 + 注释指向 source, 不进 toml (非运维可调)。

-------------------------------------------------------------------------------
机制来源 (已验证正确的信任组装范式)
-------------------------------------------------------------------------------
信任组装与 ``tests/offensive/v3/orchestration/test_auto_flow.py`` 的
``_root_context``/``_issuer``/``_trust_capability``/``_signed``/``_protected_input``
同源 — 这些 helper 已在 Task 5/6/7 测试中证明能驱动真实 ``EvidenceRepository``
publish+verify。本模块把它们提升为生产代码并参数化: 去掉测试常量 (NOW/HASH),
锚定调用方注入的 ``reference_time`` (CLI 用 wall clock), 命名空间由 specs 列表
配置 (btst/auto/outcome)。EvidenceRepository 在 publish 时用
``required_capability(signed)`` (repository.py:135) 从信封自身声明派生所需能力,
故只要注册的 issuer 持有签名所用 capability, 验证自洽通过。

-------------------------------------------------------------------------------
ACL 边界
-------------------------------------------------------------------------------
本模块不 import governance 写面 / authorizer / execution proxy|manual (AST 守卫
锁定, 见 S5 集成测试)。``PolicyActivation``/``CapitalAuthorizationEnvelope``/
``LineageGrant`` 是不可变契约数据类 (构造它们不触发任何写), 仅用作 kernel
``KernelInput`` 的只读输入。签名材料是进程内 ephemeral Ed25519 key (不读持久化
keystore), 与 plan 全局约束一致。
"""

from __future__ import annotations

import hashlib
from base64 import b64encode
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Callable

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.screening.offensive.v3 import trust as v3_trust
from src.screening.offensive.v3.contracts import (
    canonical_json_bytes,
    ExecutionMode,
    SignedEnvelope,
    SUPPORTED_SCHEMA_MAJOR,
)
from src.screening.offensive.v3.contracts.authorization import (
    AuthorizationKind,
    CapitalAuthorizationEnvelope,
)
from src.screening.offensive.v3.contracts.governance import (
    GrantKind,
    LineageGrant,
    PolicyActivation,
    ProgramLossBudgetBinding,
    TrustBundle,
)
from src.screening.offensive.v3.kernel.admission import BTST_FAMILY
from src.screening.offensive.v3.kernel.models import DeadlineContract
from src.screening.offensive.v3.producers.btst import BTST_BEHAVIOR_BASELINE

# -- 合成 authority 确定性常量 (与 producer 信封逐字一致; 见模块 docstring) -------
_BTST_EXECUTION_VERSION = "btst.funnel.v1"
"""BTST producer 信封 execution_version (producers/auto.py:_signal_envelope,
namespace="btst" → f"{ns}.funnel.v1")。合成 grant 必须同值才 ADMITTED。"""

_BTST_COST_VERSION = "cn-a-share-costs.v1"
"""BTST producer 信封 cost_version (producers/auto.py:_signal_envelope, 硬编码)。
合成 grant 必须同值才 ADMITTED。"""

_SHADOW_LINEAGE_ID = "btst.shadow.lineage.v1"
_SHADOW_PROGRAM_ID = "btst.shadow.program.v1"
_SHADOW_STAGE_ID = "btst.shadow.stage.v1"
_SHADOW_ECONOMIC_EPOCH = 1
"""合成 grant 的 lineage/stage/program 确定性标识。flow ``_build_kernel_input`` 从
授权 grant 取这些字段构造 RawCandidate (daily_action_flow.py:645-647), admission
再校验 candidate↔grant 同源 (admission.py:102-115) — 同一 grant 自洽通过。"""

_TRUST_VALID_WINDOW = timedelta(days=1)
"""issuer capability / trust bundle 有效窗口半径 (绕 reference_time 双向)。shadow
是一次性观测, 窗口只需覆盖单次 CLI 运行; ±1 天足够容错。"""

_ROOT_VALID_WINDOW = timedelta(days=30)
"""root anchor 有效窗口 (比 issuer 宽, 模拟离线 root 长效)。"""


@dataclass(frozen=True)
class NamespaceSpec:
    """一个 shadow 命名空间的信任规格 (issuer 身份 + 能力声明)。

    每个规格生成一对 ephemeral Ed25519 key + 一个 TrustedIssuer (持对应 capability)
    + 一个 signer callable。composition root 按 flow 需要的命名空间选 specs。
    """

    namespace: str
    artifact: v3_trust.ArtifactKind
    issuer_kind: v3_trust.IssuerKind
    issuer_id: str
    key_id: str
    capability_version: str


SHADOW_BTST_SPEC = NamespaceSpec(
    namespace="btst",
    artifact=v3_trust.ArtifactKind.SIGNAL,
    issuer_kind=v3_trust.IssuerKind.SIGNAL_PRODUCER,
    issuer_id="btst.producer",
    key_id="btst-key-1",
    capability_version="signal-producer.v1",
)
"""BTST producer 命名空间 (DailyActionFlow shadow 管线所需)。artifact=SIGNAL,
issuer_kind=SIGNAL_PRODUCER (trust/registry.py:543 允许 SIGNAL_PRODUCER 持 SIGNAL)。"""

SHADOW_AUTO_SPEC = NamespaceSpec(
    namespace="auto",
    artifact=v3_trust.ArtifactKind.SIGNAL,
    issuer_kind=v3_trust.IssuerKind.SIGNAL_PRODUCER,
    issuer_id="auto.producer",
    key_id="auto-key-1",
    capability_version="signal-producer.v1",
)
"""Auto producer 命名空间 (AutoFlow shadow 管线所需)。"""

SHADOW_OUTCOME_SPEC = NamespaceSpec(
    namespace="outcome",
    artifact=v3_trust.ArtifactKind.OUTCOME,
    issuer_kind=v3_trust.IssuerKind.OUTCOME_FINALIZER,
    issuer_id="outcome.finalizer",
    key_id="outcome-key-1",
    capability_version="outcome-finalizer.v1",
)
"""Outcome finalizer 命名空间 (AutoFlow outcome 步所需)。artifact=OUTCOME,
issuer_kind=OUTCOME_FINALIZER (trust/registry.py:544 允许 OUTCOME_FINALIZER 持 OUTCOME)。"""


# --------------------------------------------------------------------------
# 低层签名 helper (production 版; 与 test_auto_flow._public_key_b64/
# _protected_input/_signed 同源, 去掉测试常量)
# --------------------------------------------------------------------------


def _public_key_b64(private_key: Ed25519PrivateKey) -> str:
    """Ed25519 公钥的 raw bytes → base64 (TrustedIssuer.public_key 格式)。"""
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return b64encode(public_bytes).decode("ascii")


def _protected_input(
    *,
    issuer_id: str,
    key_id: str,
    capability: v3_trust.Capability,
    payload: bytes,
    payload_hash: str,
) -> bytes:
    """构造 SignedEnvelope 的规范保护头 (与验证侧 required_capability 对齐)。"""
    return canonical_json_bytes(
        {
            "artifact": capability.artifact,
            "capability_scope": capability.scope,
            "capability_version": capability.capability_version,
            "issuer_id": issuer_id,
            "key_id": key_id,
            "mode": capability.mode,
            "namespace": capability.namespace,
            "payload": b64encode(payload).decode("ascii"),
            "payload_hash": payload_hash,
            "schema_major": capability.schema_major,
        }
    )


def _sign_envelope(
    private_key: Ed25519PrivateKey,
    capability: v3_trust.Capability,
    *,
    issuer_id: str,
    key_id: str,
    payload: bytes,
) -> SignedEnvelope:
    """签一枚 SignedEnvelope (payload + 规范保护头签名)。

    与 ``repository.required_capability(signed)`` (repository.py:135) 自洽: 信封
    声明的 artifact/namespace/mode/capability_version 来自签名所用 capability,
    验证侧从信封重新派生同一 capability, 故只要注册 issuer 持此 capability 即通过。
    """
    digest = hashlib.sha256(payload).hexdigest()
    protected = _protected_input(
        issuer_id=issuer_id,
        key_id=key_id,
        capability=capability,
        payload=payload,
        payload_hash=digest,
    )
    signature = private_key.sign(protected)
    return SignedEnvelope(
        issuer_id=issuer_id,
        key_id=key_id,
        schema_major=capability.schema_major,
        artifact=capability.artifact,
        namespace=capability.namespace,
        mode=capability.mode,
        capability_version=capability.capability_version,
        capability_scope=capability.scope,
        payload_hash=digest,
        payload=payload,
        signature=b64encode(signature).decode("ascii"),
    )


class _HeadProvider:
    """``TrustHeadProvider`` 鸭子类型: 恒返回同一 active trust head (shadow 单次观测)。"""

    def __init__(self, head: v3_trust.CurrentTrustHeadWitness) -> None:
        self._head = head

    def current_trust_head(
        self, trusted_at: datetime
    ) -> v3_trust.CurrentTrustHeadWitness:
        return self._head


@dataclass(frozen=True)
class ShadowTrustContext:
    """build_shadow_trust_context 的结果: 验证器 + head provider + 每 namespace signer。

    - ``verifier`` / ``head_provider``: 注入 EvidenceRepository / ProducerApi
      (它们在 publish 时验证签名 evidence)。
    - ``active_bundle_hash``: 当前 signed trust bundle 的 artifact_hash, 用于合成
      authority 的 envelope.trust_bundle_hash (内部一致)。
    - ``signer_for(namespace)``: 返回该 namespace 的 signer callable (注入对应
      ProducerApi / OutcomeFinalizerService 的 ``signer`` 参数)。
    """

    verifier: v3_trust.CapabilityVerifier
    head_provider: _HeadProvider
    active_bundle_hash: str
    _signers: dict[str, Callable[[bytes], SignedEnvelope]]

    def signer_for(self, namespace: str) -> Callable[[bytes], SignedEnvelope]:
        """返回 ``namespace`` 的 signer (btst/auto/outcome); 未知 namespace 抛 KeyError。"""
        return self._signers[namespace]


def build_shadow_trust_context(
    *,
    reference_time: datetime,
    specs: tuple[NamespaceSpec, ...],
) -> ShadowTrustContext:
    """构造一次性 ephemeral 信任上下文 (root key + 每 namespace issuer + signed bundle)。

    与 test_auto_flow._root_context 同源机制, 参数化: reference_time 锚定有效窗口,
    specs 决定命名空间集合。每 spec 生成独立 ephemeral Ed25519 key; root key 签
    trust bundle 使 registry 可信; CapabilityVerifier + head provider 供 services
    在 publish 时验证签名。

    Args:
        reference_time: 信任窗口中心 (CLI 用 wall clock now; 测试可注入固定值)。
        specs: 需要的命名空间规格 (如 (SHADOW_BTST_SPEC,) 给 DailyActionFlow)。

    Returns:
        ShadowTrustContext (verifier / head_provider / active_bundle_hash / signers)。
    """
    valid_from = reference_time - _TRUST_VALID_WINDOW
    valid_until = reference_time + _TRUST_VALID_WINDOW

    issuers: list[v3_trust.TrustedIssuer] = []
    signers: dict[str, Callable[[bytes], SignedEnvelope]] = {}
    for spec in specs:
        key = Ed25519PrivateKey.generate()
        capability = v3_trust.Capability(
            artifact=spec.artifact,
            namespace=spec.namespace,
            mode=ExecutionMode.RESEARCH_RECONSTRUCTION,
            schema_major=SUPPORTED_SCHEMA_MAJOR,
            capability_version=spec.capability_version,
            scope=f"evidence:{spec.namespace}",
            valid_from=valid_from,
            valid_until=valid_until,
            revoked_at=None,
        )
        issuers.append(
            v3_trust.TrustedIssuer(
                issuer_id=spec.issuer_id,
                key_id=spec.key_id,
                issuer_kind=spec.issuer_kind,
                public_key=_public_key_b64(key),
                valid_from=valid_from,
                valid_until=valid_until,
                revoked_at=None,
                capabilities=(capability,),
            )
        )
        # 闭包捕获当前 spec 的 key/capability/身份 (而非循环变量, 避免延迟绑定串台)。
        signers[spec.namespace] = (
            lambda payload, key=key, capability=capability, sid=spec.issuer_id, kid=spec.key_id: _sign_envelope(
                key, capability, issuer_id=sid, key_id=kid, payload=payload
            )
        )

    registry = v3_trust.TrustedRegistry(issuers=tuple(issuers))

    # root key + anchor + signed trust bundle (root 签 registry 使其可信)。
    root_key = Ed25519PrivateKey.generate()
    root_public_bytes = root_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    root_hash = hashlib.sha256(root_public_bytes).hexdigest()
    anchor = v3_trust.RootTrustAnchor(
        root_hash=root_hash,
        root_key_id="offline-root-1",
        public_key=b64encode(root_public_bytes).decode("ascii"),
        valid_from=reference_time - _ROOT_VALID_WINDOW,
        valid_until=reference_time + _ROOT_VALID_WINDOW,
        revoked_at=None,
    )
    bundle = TrustBundle(
        registry_epoch=1,
        predecessor_bundle_hash="0" * 64,
        root_hash=root_hash,
        root_key_id=anchor.root_key_id,
        trusted_issuer_registry_hash=registry.content_hash(),
        issued_at=reference_time - timedelta(minutes=5),
        expires_at=valid_until,
        revoked_at=None,
        issuer_id="offline-governance-root",
        issuer_capability="root.trust.bundle.v1",
        schema_major=2,
    )
    root_signature = b64encode(
        root_key.sign(v3_trust.trust_bundle_signature_preimage(bundle, registry))
    ).decode("ascii")
    signed_bundle = v3_trust.SignedTrustBundle(
        bundle=bundle, registry=registry, signature=root_signature
    )
    verifier = v3_trust.CapabilityVerifier(
        v3_trust.TrustBundleVerifier((anchor,)), (signed_bundle,)
    )
    head = v3_trust.CurrentTrustHeadWitness(
        active_trust_bundle_hash=bundle.artifact_hash(),
        registry_epoch=bundle.registry_epoch,
        head_version=bundle.registry_epoch,
        store_version=1,
        observed_at=reference_time,
    )
    return ShadowTrustContext(
        verifier=verifier,
        head_provider=_HeadProvider(head),
        active_bundle_hash=bundle.artifact_hash(),
        _signers=signers,
    )


@dataclass(frozen=True)
class ShadowAuthority:
    """synthesize_shadow_authority 的结果: 合成 PolicyActivation + Envelope。"""

    policy_activation: PolicyActivation
    envelope: CapitalAuthorizationEnvelope


def _shadow_grant() -> LineageGrant:
    """合成 BTST 授权 grant (确定性, 与 producer 信封逐字一致)。

    ``behavior_fingerprint``/``execution_version``/``cost_version`` 必须与
    ``producers/auto.py:_signal_envelope`` 盖的值一致 (admission.py:106-111);
    ``subject_producer="btst"`` + ``family_id=BTST_FAMILY`` 使 flow
    ``_authorized_grant`` 选中本 grant 且 family 进白名单 (admission.py:100)。
    其余字段确定性占位 (lineage/stage/program 自洽, 见 _build_kernel_input)。
    """
    return LineageGrant(
        grant_id="btst.shadow.grant.v1",
        grant_kind=GrantKind.EDGE,
        grant_certificate_hash=hashlib.sha256(b"btst-shadow-grant").hexdigest(),
        grant_issuer_id="shadow.authority.placeholder",
        subject_producer="btst",
        family_id=BTST_FAMILY,
        economic_lineage_id=_SHADOW_LINEAGE_ID,
        research_program_id=_SHADOW_PROGRAM_ID,
        behavior_fingerprint=BTST_BEHAVIOR_BASELINE,
        execution_version=_BTST_EXECUTION_VERSION,
        cost_version=_BTST_COST_VERSION,
        capital_tier=2,
        lineage_gross_cap=Decimal("0.02"),
        trial_id="btst.shadow.trial.v1",
        trial_manifest_hash=hashlib.sha256(b"btst-shadow-trial").hexdigest(),
        statistical_analysis_plan_hash=hashlib.sha256(b"btst-shadow-sap").hexdigest(),
        stage_id=_SHADOW_STAGE_ID,
        stage_manifest_hash=hashlib.sha256(b"btst-shadow-stage").hexdigest(),
        stage_sample_reservation_id="btst.shadow.reservation.v1",
        stage_loss_budget_id="btst.shadow.budget.v1",
        stage_loss_budget_cents=100_000,
        stage_loss_version=_SHADOW_ECONOMIC_EPOCH,
        assessment_result_hash=hashlib.sha256(b"btst-shadow-assessment").hexdigest(),
        grant_evidence_set_merkle_root=hashlib.sha256(b"btst-shadow-merkle").hexdigest(),
        attempt_ledger_checkpoint_hash=hashlib.sha256(
            b"btst-shadow-checkpoint"
        ).hexdigest(),
        alpha_or_evalue_budget_consumption_id="btst.shadow.consumption.v1",
        alpha_sample_consumption_id="btst.shadow.sample.v1",
        schema_major=2,
    )


def synthesize_shadow_authority(
    *,
    portfolio_id: str,
    trust_bundle_hash: str,
    reference_time: datetime,
) -> ShadowAuthority:
    """合成 shadow 观测用 PolicyActivation + CapitalAuthorizationEnvelope (确定性占位)。

    满足 kernel admission 硬校验 (admission.py:60): ``envelope.policy_activation_hash
    == policy_activation.artifact_hash()``。envelope 内嵌一个 btst 授权 grant
    (``_shadow_grant``), 被 flow ``_authorized_grant`` 选中。这不是真实 governance
    激活 (issuer="shadow.authority.placeholder"), 仅解锁 admission 使 kernel 能
    ADMIT — flow ``execution_authority`` 恒 ``"none"`` 保证不产生可执行 line。

    Args:
        portfolio_id: 本 flow 治理的 portfolio (从 toml config)。
        trust_bundle_hash: 当前 active trust bundle 的 artifact_hash (内部一致;
            来自 ``ShadowTrustContext.active_bundle_hash``)。
        reference_time: 合成 authority 的有效窗口中心 (CLI wall clock)。

    Returns:
        ShadowAuthority (policy_activation + envelope, 互斥 hash 一致)。
    """
    snapshot_hash = hashlib.sha256(b"btst-shadow-policy-snapshot").hexdigest()
    policy_activation = PolicyActivation(
        portfolio_id=portfolio_id,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        policy_snapshot_hash=snapshot_hash,
        predecessor_policy_activation_hash="0" * 64,
        trust_bundle_hash=trust_bundle_hash,
        registry_epoch=1,
        policy_epoch=1,
        authority_epoch=1,
        risk_epoch=1,
        effective_from=reference_time,
        expires_at=reference_time + _TRUST_VALID_WINDOW,
        issuer_id="shadow.authority.placeholder",
        issuer_capability="governance.policy.activation.v1",
        schema_major=2,
    )
    binding = ProgramLossBudgetBinding(
        research_program_id=_SHADOW_PROGRAM_ID,
        budget_id="btst.shadow.budget.v1",
        budget_cents=100_000,
        consumed_cents=0,
        version=1,
        schema_major=2,
    )
    baseline_hash = hashlib.sha256(b"btst-shadow-baseline-policy").hexdigest()
    target_hash = hashlib.sha256(b"btst-shadow-target-policy").hexdigest()
    assessment_hash = hashlib.sha256(b"btst-shadow-portfolio-assessment").hexdigest()
    checkpoint_hash = hashlib.sha256(b"btst-shadow-global-checkpoint").hexdigest()
    snapshot_evidence_hash = hashlib.sha256(b"btst-shadow-capital-snapshot").hexdigest()
    envelope = CapitalAuthorizationEnvelope(
        authorization_kind=AuthorizationKind.EDGE,
        authorization_id="btst.shadow.authorization.v1",
        authorization_version=1,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        portfolio_id=portfolio_id,
        broker_account_id=None,
        broker_account_fingerprint=None,
        base_currency="CNY",
        policy_activation_hash=policy_activation.artifact_hash(),
        trust_bundle_hash=trust_bundle_hash,
        registry_epoch=1,
        policy_epoch=1,
        authority_epoch=1,
        risk_epoch=1,
        research_program_ids=(_SHADOW_PROGRAM_ID,),
        baseline_portfolio_policy_fingerprint=baseline_hash,
        target_portfolio_policy_fingerprint=target_hash,
        lineage_grants=(_shadow_grant(),),
        evidence_as_of=reference_time,
        evidence_set_merkle_root=hashlib.sha256(b"btst-shadow-evidence-set").hexdigest(),
        issued_at=reference_time,
        expires_at=reference_time + _TRUST_VALID_WINDOW,
        activation_capital_snapshot_id="btst.shadow.capital.snapshot.v1",
        activation_capital_snapshot_hash=snapshot_evidence_hash,
        portfolio_gross_cap=Decimal("0.02"),
        exploration_aggregate_gross_cap=Decimal("0"),
        program_loss_budget_bindings=(binding,),
        issuer_id="shadow.authority.placeholder",
        issuer_capability="authorizer.edge.envelope.v1",
        portfolio_assessment_result_hash=assessment_hash,
        global_attempt_ledger_checkpoint_hash=checkpoint_hash,
        global_multiplicity_budget_consumption_id="btst.shadow.multiplicity.v1",
        schema_major=2,
    )
    return ShadowAuthority(
        policy_activation=policy_activation, envelope=envelope
    )


def derive_deadline_contract(
    *,
    close_finalized_at: datetime,
) -> DeadlineContract:
    """从收盘 finalized 时刻派生 shadow 观测用 DeadlineContract (6 UtcInstant)。

    满足 ``DeadlineContract.ordering_valid()`` (kernel/models.py):
    ``close_finalized_at <= seal_creation_deadline < permit_issue_deadline <
    permit_expires_at <= gateway_send_deadline < broker_auction_cutoff``。

    shadow 模式不执行真实 seal/permit/send, deadlines 仅作 KernelInput 结构输入;
    偏移取 A 股 T+1 集合竞价窗口的合理近似 (收盘 15:00 UTC → seal +4h →
    permit +20min → 次日竞价 cutoff)。与 test_daily_action_flow._deadlines 同比例。
    """
    return DeadlineContract(
        close_finalized_at=close_finalized_at,
        seal_creation_deadline=close_finalized_at + timedelta(hours=4),
        permit_issue_deadline=close_finalized_at + timedelta(hours=4, minutes=20),
        permit_expires_at=close_finalized_at + timedelta(hours=18, minutes=20),
        gateway_send_deadline=close_finalized_at + timedelta(hours=18, minutes=20),
        broker_auction_cutoff=close_finalized_at + timedelta(hours=18, minutes=30),
    )


__all__ = [
    "SHADOW_AUTO_SPEC",
    "SHADOW_BTST_SPEC",
    "SHADOW_OUTCOME_SPEC",
    "NamespaceSpec",
    "ShadowAuthority",
    "ShadowTrustContext",
    "build_shadow_trust_context",
    "derive_deadline_contract",
    "synthesize_shadow_authority",
]
