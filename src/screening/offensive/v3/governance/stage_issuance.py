"""Governance stage issuance — 治理签名 primitive (2026-08-20).

前向 Trial 的诚实缺口 (AGENTS 能力边界): "Phase 3 的 stage 绑定/evidence
merkle 参数尚无签发机制" — ``freeze_shared_input`` 消费的
``stage_id``/``stage_manifest_hash`` 此前只有测试夹具与 shadow_trust 的
占位哈希。本模块补上签发机制: **从已封存的 regime trial bundle 派生**
StageManifest (单一事实源 — 调用方不能重复发明 trial/SAP/指纹/版本/日期),
注入签名器签名 canonical bytes, 经 ``GovernanceRepository.seal_stage``
验签 (capability + 信任头 + 载荷绑定) 后不可变落库, 返回类型化回执。

诚实边界 (offline primitive): 回执与签名 stage 不构成权限、不激活任何
authorization envelope、不解锁 runner/replay 的 fail-closed; 请求中的
attempt checkpoint / 消费 id / loss budget 是**外部台账事实**, 本层只冻结
不核验 — loss budget 的真实验证点是**激活时与 capital truth 的 stage
loss state 逐分比对** (特权 worker 职责); 本层对调用方自报 NAV 的任何
"交叉核对"都是安全剧场, 有意不实现。真实密钥与信任链注入 (替代测试的
ephemeral 链) 同样留给特权 worker。
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar, Self

from pydantic import ValidationError, model_validator

from src.screening.offensive.v3.contracts import CanonicalModel, Sha256
from src.screening.offensive.v3.contracts.base import ExecutionMode, UtcInstant
from src.screening.offensive.v3.contracts.capital import PositiveExactInt
from src.screening.offensive.v3.contracts.evidence import NonEmptyStr
from src.screening.offensive.v3.contracts.governance import StageManifest
from src.screening.offensive.v3.governance.regime_trial import (
    GovernanceArtifactVerifierPort,
)
from src.screening.offensive.v3.governance.repository import GovernanceRepository
from src.screening.offensive.v3.trust import (
    Capability,
    CurrentTrustHeadWitness,
    SignedEnvelope,
)

#: StageManifest 契约钉死的签发能力 (capability 字符串由契约校验器背书)
STAGE_ISSUER_CAPABILITY: str = "governance.stage.manifest.v1"
_STAGE_SCHEMA_MAJOR: int = 2


class StageIssuanceError(RuntimeError):
    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


@dataclass(frozen=True)
class StageIssuanceRequest:
    """一次签发的外部参数 — 只含台账事实与阶段身份, 无一可从封存 trial 派生。

    ``attempt_ledger_checkpoint_hash`` / ``alpha_*_consumption_id`` /
    ``stage_loss_*`` / ``maximum_loss_budget_cents`` 是全局 attempt ledger、
    alpha 预算与资本 truth 的事实; 本层原样冻结进签名 manifest, 不替任何
    一方核验 (见模块 docstring 的诚实边界)。``issued_at`` 是签发行为的
    **显式时刻** (第三轮 P2-c 最优解): 签发行为身份 = (trial, stage,
    内容+时刻) — 同一请求 crash 后重试逐字节收敛, 幂等不再依赖环境钟;
    换时刻重签同一 ``stage_id`` 是不同行为, 落 ``stage_seal_conflict``
    (保守安全, 强制显式调查)。签发方不得声明未来时刻 (对注入钟校验);
    遗留的滞后上界由契约 ``issued_at < enrollment_start`` 钉死。
    """

    trial_id: str
    stage_id: str
    stage_sample_reservation_id: str
    alpha_sample_consumption_id: str
    alpha_or_evalue_budget_consumption_id: str
    attempt_ledger_checkpoint_hash: str
    stage_loss_budget_id: str
    stage_loss_version: int
    maximum_loss_budget_cents: int
    issuer_id: str
    issued_at: datetime


#: 回执与签名 StageManifest 同名的字段 — 校验器逐一钉死两者不可漂移
_RECEIPT_MANIFEST_FIELDS: tuple[str, ...] = (
    "stage_id",
    "trial_manifest_hash",
    "statistical_analysis_plan_hash",
    "baseline_portfolio_policy_fingerprint",
    "target_portfolio_policy_fingerprint",
    "execution_version",
    "cost_version",
    "execution_mode",
    "enrollment_start",
    "followup_finality_date",
    "fixed_assessment_date",
    "issued_at",
)


class StageIssuanceReceipt(CanonicalModel):
    """签发回执: ``freeze_shared_input`` 冻结参数集的自足哈希绑定工件。

    第二轮对抗审查返工 (2026-08-20): frozen CanonicalModel (可 content_hash /
    严格往返, 归宿是 trial root archive 的耐久工件); 补齐 ``registry_epoch``
    与 ``trust_bundle_hash`` (冻结参数集自足, 不再要求消费方回封存库取);
    时间戳字段是 ``issued_at`` — 与 manifest 签发时刻同源同义, **不是**
    store 落库时刻 (seal_stage 内部自读时钟, 本回执不代述)。签名信封以
    canonical JSON 字符串入模 (镜像 store 的 TEXT 列表示 — 信封 payload
    是 bytes, 直接嵌套会使 content_hash 的 canonical JSON 失败)。校验器
    解析信封 + 严格解析其中 StageManifest 并逐一核对同名字段 — 回执与
    签名 manifest 的任何漂移在构造时即拒绝, 冗余字段因此不可被单独篡改。
    """

    HASH_DOMAIN: ClassVar[str] = (
        "ai-hedge-fund.v3.governance.stage-issuance-receipt.v1"
    )

    stage_id: NonEmptyStr
    trial_id: NonEmptyStr
    stage_manifest_hash: Sha256
    trial_manifest_hash: Sha256
    statistical_analysis_plan_hash: Sha256
    trust_bundle_hash: Sha256
    registry_epoch: PositiveExactInt
    baseline_portfolio_policy_fingerprint: Sha256
    target_portfolio_policy_fingerprint: Sha256
    execution_version: NonEmptyStr
    cost_version: NonEmptyStr
    execution_mode: ExecutionMode
    enrollment_start: UtcInstant
    followup_finality_date: UtcInstant
    fixed_assessment_date: UtcInstant
    issued_at: UtcInstant
    signed_stage_envelope_json: str

    @property
    def signed_stage_envelope(self) -> SignedEnvelope:
        return SignedEnvelope.model_validate_json(
            self.signed_stage_envelope_json, strict=True
        )

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        try:
            envelope = self.signed_stage_envelope
        except ValidationError as exc:
            raise ValueError(
                "signed stage envelope field is not a strict SignedEnvelope"
            ) from exc
        if hashlib.sha256(envelope.payload).hexdigest() != envelope.payload_hash:
            raise ValueError("signed envelope payload_hash does not bind its payload")
        try:
            manifest = StageManifest.model_validate_json(envelope.payload, strict=True)
        except ValidationError as exc:
            raise ValueError(
                "signed stage envelope does not carry a strict StageManifest"
            ) from exc
        if manifest.artifact_hash() != self.stage_manifest_hash:
            raise ValueError("receipt stage hash does not bind the signed manifest")
        for name in _RECEIPT_MANIFEST_FIELDS:
            if getattr(manifest, name) != getattr(self, name):
                raise ValueError(
                    f"receipt field {name} does not match the signed manifest"
                )
        return self


class GovernanceStageIssuer:
    """进程内签发服务对象 (Plan 05 服务对象风格): 派生 → 签名 → 验签封存。"""

    def __init__(
        self,
        *,
        repository: GovernanceRepository,
        signer: Callable[[bytes], SignedEnvelope],
        stage_capability: Capability,
        verifier: GovernanceArtifactVerifierPort,
        trust_head: Callable[[], CurrentTrustHeadWitness],
        clock: Callable[[], datetime],
    ) -> None:
        self._repository = repository
        self._signer = signer
        self._stage_capability = stage_capability
        self._verifier = verifier
        self._trust_head = trust_head
        self._clock = clock

    def issue(self, request: StageIssuanceRequest) -> StageIssuanceReceipt:
        """Derive from sealed truth, sign, verify, seal — one stage, one receipt.

        派生纪律: trial/SAP 哈希、program/lineage、主度量、双策略指纹、
        执行/成本版本、模式、enrollment 窗口、晋级布尔式全部取自
        ``regime_trial_bundle`` 严格重解析的封存字节; governance_policy_version
        取自封存 baseline policy 的 versions (语义单 delta 契约保证双臂一致)。
        契约校验器另钉死 ``issued_at < enrollment_start`` — 入场窗口开始后
        不可能补签。重试语义 (第三轮 P2-c 落地): ``issued_at`` 在请求内,
        同一请求重试逐字节收敛且与墙钟无关; 换时刻重签同一 ``stage_id``
        落 ``stage_seal_conflict``。请求声明的未来时刻在派生前拒绝。
        """
        bundle = self._repository.regime_trial_bundle(request.trial_id)
        trial = bundle.trial_manifest
        sap = bundle.sap_manifest
        now = self._clock()
        if request.issued_at > now:
            raise StageIssuanceError(
                "future_issuance_instant",
                "issuance instant cannot be ahead of the injected clock",
                issued_at=request.issued_at.isoformat(),
                clock=now.isoformat(),
            )
        manifest = StageManifest(
            stage_id=request.stage_id,
            trial_manifest_hash=trial.artifact_hash(),
            statistical_analysis_plan_hash=sap.artifact_hash(),
            research_program_id=trial.research_program_id,
            economic_lineage_id=trial.economic_lineage_id,
            primary_metric=trial.primary_metric,
            baseline_portfolio_policy_fingerprint=trial.baseline_portfolio_policy_fingerprint,
            target_portfolio_policy_fingerprint=trial.target_portfolio_policy_fingerprint,
            execution_version=trial.execution_version,
            cost_version=trial.cost_version,
            governance_policy_version=bundle.baseline_policy.versions.governance_version,
            execution_mode=trial.execution_mode,
            stage_sample_reservation_id=request.stage_sample_reservation_id,
            alpha_sample_consumption_id=request.alpha_sample_consumption_id,
            alpha_or_evalue_budget_consumption_id=request.alpha_or_evalue_budget_consumption_id,
            attempt_ledger_checkpoint_hash=request.attempt_ledger_checkpoint_hash,
            stage_loss_budget_id=request.stage_loss_budget_id,
            stage_loss_version=request.stage_loss_version,
            enrollment_start=trial.enrollment_start,
            followup_finality_date=trial.followup_finality_date,
            fixed_assessment_date=trial.fixed_assessment_date,
            maximum_loss_budget_cents=request.maximum_loss_budget_cents,
            promotion_boolean_expression=trial.promotion_boolean_expression,
            issued_at=request.issued_at,
            issuer_id=request.issuer_id,
            issuer_capability=STAGE_ISSUER_CAPABILITY,
            schema_major=_STAGE_SCHEMA_MAJOR,
        )
        signed = self._signer(manifest.canonical_bytes())
        # manifest.issuer_id 已在签名载荷内; 再与信封签发者身份交叉核对,
        # 堵住"载荷声称 A、密钥是 B"的错位。
        if signed.issuer_id != request.issuer_id:
            raise StageIssuanceError(
                "issuer_identity_mismatch",
                "signed envelope issuer does not match the manifest issuer_id",
                envelope_issuer=signed.issuer_id,
                manifest_issuer=request.issuer_id,
            )
        self._repository.seal_stage(
            signed,
            manifest,
            self._stage_capability,
            verifier=self._verifier,
            current_head=self._trust_head(),
            trusted_at=now,
        )
        return StageIssuanceReceipt(
            stage_id=manifest.stage_id,
            trial_id=trial.trial_id,
            stage_manifest_hash=manifest.artifact_hash(),
            trial_manifest_hash=trial.artifact_hash(),
            statistical_analysis_plan_hash=sap.artifact_hash(),
            trust_bundle_hash=trial.trust_bundle_hash,
            registry_epoch=trial.registry_epoch,
            baseline_portfolio_policy_fingerprint=trial.baseline_portfolio_policy_fingerprint,
            target_portfolio_policy_fingerprint=trial.target_portfolio_policy_fingerprint,
            execution_version=trial.execution_version,
            cost_version=trial.cost_version,
            execution_mode=trial.execution_mode,
            enrollment_start=trial.enrollment_start,
            followup_finality_date=trial.followup_finality_date,
            fixed_assessment_date=trial.fixed_assessment_date,
            issued_at=request.issued_at,
            signed_stage_envelope_json=signed.model_dump_json(),
        )


__all__ = [
    "GovernanceStageIssuer",
    "STAGE_ISSUER_CAPABILITY",
    "StageIssuanceError",
    "StageIssuanceReceipt",
    "StageIssuanceRequest",
]
