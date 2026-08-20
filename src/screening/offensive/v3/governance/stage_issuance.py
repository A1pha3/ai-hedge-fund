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
不核验 (与全局 attempt ledger / 资本 truth 的交叉核验属特权 worker);
真实密钥与信任链注入 (替代测试的 ephemeral 链) 同样留给特权 worker。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from src.screening.offensive.v3.contracts.base import ExecutionMode
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
    一方核验 (见模块 docstring 的诚实边界)。
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


class StageIssuanceReceipt:
    """签发回执: 恰是 ``freeze_shared_input`` 需要的冻结参数集。

    冻结参数 (stage_id / stage_manifest_hash / trial/SAP 哈希 / 版本 /
    enrollment 窗口) 全部派生自已封存真相, 回执自身不可变; 它不是权限,
    是未来特权 worker 组装 ``ShadowSharedInput`` 时的唯一合法来源。
    """

    def __init__(
        self,
        *,
        stage_id: str,
        trial_id: str,
        stage_manifest_hash: str,
        trial_manifest_hash: str,
        statistical_analysis_plan_hash: str,
        baseline_portfolio_policy_fingerprint: str,
        target_portfolio_policy_fingerprint: str,
        execution_version: str,
        cost_version: str,
        execution_mode: ExecutionMode,
        enrollment_start: datetime,
        followup_finality_date: datetime,
        fixed_assessment_date: datetime,
        sealed_at: datetime,
        signed_stage_envelope: SignedEnvelope,
    ) -> None:
        self.stage_id = stage_id
        self.trial_id = trial_id
        self.stage_manifest_hash = stage_manifest_hash
        self.trial_manifest_hash = trial_manifest_hash
        self.statistical_analysis_plan_hash = statistical_analysis_plan_hash
        self.baseline_portfolio_policy_fingerprint = baseline_portfolio_policy_fingerprint
        self.target_portfolio_policy_fingerprint = target_portfolio_policy_fingerprint
        self.execution_version = execution_version
        self.cost_version = cost_version
        self.execution_mode = execution_mode
        self.enrollment_start = enrollment_start
        self.followup_finality_date = followup_finality_date
        self.fixed_assessment_date = fixed_assessment_date
        self.sealed_at = sealed_at
        self.signed_stage_envelope = signed_stage_envelope


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
        不可能补签 stage。
        """
        bundle = self._repository.regime_trial_bundle(request.trial_id)
        trial = bundle.trial_manifest
        sap = bundle.sap_manifest
        now = self._clock()
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
            issued_at=now,
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
            baseline_portfolio_policy_fingerprint=trial.baseline_portfolio_policy_fingerprint,
            target_portfolio_policy_fingerprint=trial.target_portfolio_policy_fingerprint,
            execution_version=trial.execution_version,
            cost_version=trial.cost_version,
            execution_mode=trial.execution_mode,
            enrollment_start=trial.enrollment_start,
            followup_finality_date=trial.followup_finality_date,
            fixed_assessment_date=trial.fixed_assessment_date,
            sealed_at=now,
            signed_stage_envelope=signed,
        )


__all__ = [
    "GovernanceStageIssuer",
    "STAGE_ISSUER_CAPABILITY",
    "StageIssuanceError",
    "StageIssuanceReceipt",
    "StageIssuanceRequest",
]
