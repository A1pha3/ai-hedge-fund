"""Privileged worker 的前向会话组装面 — offline primitive (2026-08-20).

特权 worker 的**只读组装职责**: 一次信号会话的官方决策输入, 全部从
store 真相派生, 不接受调用方凭空供给任何冻结参数 —

1. 治理交叉核对: 签发回执 ↔ ``GovernanceRepository.sealed_stage`` 的
   封存 manifest 哈希逐字一致 (回执与库真相互证);
2. 会话批授权: ``SessionBatchSealer.seal_decision_batch`` (store 侧逐
   成员背书 + btst 完备性 + 唯一 merkle 根 — 三段式模型);
3. regime/排程/候选从证据时间轴 cutoff 正确解析 (active_revision);
4. ``freeze_shared_input`` 的全部外部参数 (stage 绑定、registry_epoch、
   merkle 根) 取自回执与批授权, 调用方零供给。

诚实边界: 本组装面**不**运行 kernel、不落 pair、不改 runner fail-closed
(``ForwardPairedTrialRunner`` 的解锁是独立 owner 决策); 两臂 PIT capital
snapshot 从各自分化台账的读取仍开放 (现行缺口)。测试与离线播种用
ephemeral 信任链; 真实治理身份/进程边界 (UDS 特权进程) 留下一会话。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src.screening.offensive.v3.contracts.btst_candidate import BtstRawCandidatePayload
from src.screening.offensive.v3.evidence.regime import (
    ActiveRegimeObservation,
    RegimeObservationReader,
)
from src.screening.offensive.v3.evidence.repository import EvidenceRepository
from src.screening.offensive.v3.evidence.session_batch import (
    SessionBatchAuthority,
    SessionBatchSealer,
)
from src.screening.offensive.v3.evidence.trading_schedule import (
    FrozenTradingSessionSchedule,
    schedule_from_record,
)
from src.screening.offensive.v3.governance.regime_trial import (
    ValidatedRegimeTrialBundle,
)
from src.screening.offensive.v3.governance.repository import GovernanceRepository
from src.screening.offensive.v3.governance.stage_issuance import StageIssuanceReceipt
from src.screening.offensive.v3.kernel.models import ShadowSharedInput
from src.screening.offensive.v3.orchestration.paired_trial import (
    REGIME_EVIDENCE_ID,
    CommittedBtstCandidate,
    freeze_shared_input,
)


class PrivilegedWorkerError(RuntimeError):
    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


@dataclass(frozen=True)
class AssembledSession:
    """One signal session's official decision inputs, fully store-derived."""

    authority: SessionBatchAuthority
    shared_input: ShadowSharedInput
    regime: ActiveRegimeObservation
    schedule: FrozenTradingSessionSchedule
    candidates: tuple[CommittedBtstCandidate, ...]
    validated_bundle: ValidatedRegimeTrialBundle


class ForwardSessionAssembler:
    """组装 ≠ 执行: 特权 worker 的证据→冻结输入只读面。"""

    def __init__(
        self,
        *,
        sealer: SessionBatchSealer,
        governance: GovernanceRepository,
        trial_id: str,
        stage_receipt: StageIssuanceReceipt,
        regime_repository: EvidenceRepository,
        schedule_repository: EvidenceRepository,
        btst_repository: EvidenceRepository,
    ) -> None:
        self._sealer = sealer
        self._governance = governance
        self._trial_id = trial_id
        self._stage_receipt = stage_receipt
        self._regime_repository = regime_repository
        self._schedule_repository = schedule_repository
        self._btst_repository = btst_repository

    def assemble(
        self,
        *,
        session: date,
        cutoff: datetime,
        cycle_id: str,
        trusted_at: datetime,
        schedule_evidence_id: str,
        candidate_evidence_ids: tuple[str, ...] = (),
    ) -> AssembledSession:
        # ① 回执 ↔ 封存库真相互证
        sealed = self._governance.sealed_stage(self._stage_receipt.stage_id)
        if (
            sealed.stage_manifest.artifact_hash()
            != self._stage_receipt.stage_manifest_hash
        ):
            raise PrivilegedWorkerError(
                "stage_receipt_seal_mismatch",
                "the receipt no longer matches the sealed governance truth",
                stage_id=self._stage_receipt.stage_id,
            )
        if sealed.trial_id != self._trial_id:
            raise PrivilegedWorkerError(
                "stage_trial_mismatch",
                "the sealed stage belongs to another trial",
                stage_trial=sealed.trial_id,
            )
        # ② store 侧批授权 (三段式: 声明→背书→根; 完备性在封存器内强制)
        authority = self._sealer.seal_decision_batch(
            session=session,
            cutoff=cutoff,
            schedule_evidence_id=schedule_evidence_id,
            candidate_evidence_ids=candidate_evidence_ids,
        )
        # ③ 证据时间轴成员解析 (cutoff 正确)
        regime = RegimeObservationReader(self._regime_repository).active(
            REGIME_EVIDENCE_ID, cutoff
        )
        schedule = schedule_from_record(
            self._schedule_repository,
            self._schedule_repository.active_revision(
                schedule_evidence_id, cutoff
            ),
            expected_signal_session=session,
        )
        candidates = tuple(
            self._committed_candidate(evidence_id, cutoff)
            for evidence_id in candidate_evidence_ids
        )
        # ④ 冻结共享输入: 全部外部参数取自回执与批授权, 调用方零供给
        bundle = self._governance.regime_trial_bundle(self._trial_id)
        validated = ValidatedRegimeTrialBundle(
            champion_policy=bundle.baseline_policy,
            challenger_policy=bundle.target_policy,
            baseline_policy=bundle.baseline_policy,
            target_policy=bundle.target_policy,
            trial_manifest=bundle.trial_manifest,
            sap_manifest=bundle.sap_manifest,
            admission_delta=("producers.btst_regime_admission_mode",),
        )
        shared = freeze_shared_input(
            validated=validated,
            session=session,
            cycle_id=cycle_id,
            regime=regime.observation,
            trusted_at=trusted_at,
            trading_schedule=schedule,
            evidence_set_merkle_root=authority.evidence_set_merkle_root,
            stage_id=self._stage_receipt.stage_id,
            stage_manifest_hash=self._stage_receipt.stage_manifest_hash,
            registry_epoch=self._stage_receipt.registry_epoch,
            trusted_evidence_cutoff=cutoff,
        )
        return AssembledSession(
            authority=authority,
            shared_input=shared,
            regime=regime,
            schedule=schedule,
            candidates=candidates,
            validated_bundle=validated,
        )

    def _committed_candidate(
        self, evidence_id: str, cutoff: datetime
    ) -> CommittedBtstCandidate:
        record = self._btst_repository.active_revision(evidence_id, cutoff)
        envelope = record.evidence
        payload = BtstRawCandidatePayload.model_validate_json(
            self._btst_repository.raw_payload(envelope.payload_content_hash),
            strict=True,
        )
        return CommittedBtstCandidate(record=record, payload=payload)


__all__ = [
    "AssembledSession",
    "ForwardSessionAssembler",
    "PrivilegedWorkerError",
]
