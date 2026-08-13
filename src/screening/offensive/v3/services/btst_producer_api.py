"""Plan 05 Task 5: BtstProducerApi — BTST raw evidence 服务.

薄适配器: 构造时内部自建 ``EvidenceRepository`` (issuer_namespace="btst")。
``produce_and_publish`` 委托纯函数层 ``produce_btst_signal_artifacts``；每枚
artifact 先持久化 canonical raw-candidate bytes 并核对其 hash，再签名/发布
``SignalEvidence`` 信封 (store 校验 signed.namespace == "btst")。只产出签名
``SignalEvidence`` (原始 targets/features), 不做 regime / streak /
composite sizing; 信封模型无 authorization 字段, 服务面也不暴露任何
授权/许可方法。

BTST 不做 runtime gate: ``RuntimeMode.BTST_CANARY`` 是 BTST 产出的合法
模式, 因此本服务不注入 ``runtime_mode_provider`` (contrast:
``services/auto_producer_api.AutoProducerApi`` 恒 shadow-only)。

只读面: ``active_signal`` 透传 ``repository.active_revision`` (PIT cutoff);
``candidate_payload`` 读取信封绑定的 raw bytes 并重验 hash/identity/session/
version；未知 evidence_id 或早于首笔提交的 cutoff 返回 ``None`` (不抛错)。

signer 私有: 本服务持有 ``_signer``, 不暴露任何公开访问器。
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Callable

from pydantic import ValidationError

from src.screening.offensive.daily_action_snapshot import (
    VerifiedDailyActionSnapshot,
)
from src.screening.offensive.v3.contracts import SignedEnvelope
from src.screening.offensive.v3.contracts.btst_candidate import (
    BtstRawCandidatePayload,
)
from src.screening.offensive.v3.contracts.evidence import (
    EvidenceRecord,
    SignalEvidence,
)
from src.screening.offensive.v3.evidence.blob_store import BlobStore, BlobStoreError
from src.screening.offensive.v3.evidence.repository import (
    EvidenceRepository,
    EvidenceStoreError,
    TrustHeadProvider,
    VerifierProtocol,
)
from src.screening.offensive.v3.producers.btst import (
    BTST_BEHAVIOR_BASELINE,
    BTST_PRODUCER_NAMESPACE,
    BtstRawCandidateBuildError,
    produce_btst_signal_artifacts,
    qualify_btst_security_id,
)


class BtstCandidateEvidenceError(RuntimeError):
    """Fail-closed rejection of a bound BTST raw-candidate payload."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


class BtstProducerApi:
    """BTST raw evidence 服务: 只产签名 SignalEvidence (原始 targets/features)。"""

    def __init__(
        self,
        *,
        database_path: str,
        blob_store: BlobStore,
        verifier: VerifierProtocol,
        trust_head_provider: TrustHeadProvider,
        clock: Callable[[], datetime],
        signer: Callable[[bytes], SignedEnvelope],
        behavior_fingerprint: str = BTST_BEHAVIOR_BASELINE,
    ) -> None:
        """构造 BTST 证据服务: 内部自建 issuer_namespace="btst" 的仓库。

        Args:
            database_path / blob_store / verifier / trust_head_provider:
                透传给内部 ``EvidenceRepository`` (issuer_namespace="btst")。
            clock: 注入可信时钟 (store 拥有 ingested_at, 本服务不落时间)。
            signer: 注入签名器; 每个 payload 签名声明 ArtifactKind.SIGNAL
                且 namespace == "btst", 否则 store 验证拒绝。
            behavior_fingerprint: 注入本服务产出信封的行为指纹
                (64-hex; 占位符默认值由 GREEN 解析)。
        """
        self._signer = signer
        self._behavior_fingerprint = behavior_fingerprint
        self._repository = EvidenceRepository(
            database_path=database_path,
            blob_store=blob_store,
            verifier=verifier,
            trust_head_provider=trust_head_provider,
            issuer_namespace=BTST_PRODUCER_NAMESPACE,
            clock=clock,
        )

    def produce_and_publish(
        self, snapshot: VerifiedDailyActionSnapshot
    ) -> tuple[EvidenceRecord[SignalEvidence], ...]:
        """运行 BTST 原始信号漏斗并发布全部签名 SignalEvidence。

        无 runtime gate (btst_canary 是合法 mode): 直接委托
        ``produce_btst_signals`` 并逐信封发布, 返回与信封一一对应的
        发布记录 (每个候选 CANDIDATE → SELECTED 两枚)。
        """
        records: list[EvidenceRecord[SignalEvidence]] = []
        for artifact in produce_btst_signal_artifacts(
            snapshot,
            behavior_fingerprint=self._behavior_fingerprint,
        ):
            envelope = artifact.envelope
            candidate_bytes = artifact.payload.canonical_bytes()
            candidate_hash = self._repository.persist_payload(candidate_bytes)
            if candidate_hash != envelope.payload_content_hash:
                raise BtstCandidateEvidenceError(
                    "candidate_payload_hash_mismatch",
                    "signal envelope does not bind the durable candidate bytes",
                    evidence_id=envelope.evidence_id,
                )
            payload = envelope.model_dump_json().encode("utf-8")
            signed = self._signer(payload)
            records.append(
                self._repository.publish(
                    signed,
                    payload,
                    referenced_payload=candidate_bytes,
                )
            )
        return tuple(records)

    def candidate_payload(
        self,
        record: EvidenceRecord[SignalEvidence],
        *,
        expected_signal_session: date,
    ) -> BtstRawCandidatePayload:
        """Read and cross-verify the raw candidate bound by one signal record."""

        envelope = record.evidence
        if type(envelope) is not SignalEvidence:
            raise BtstCandidateEvidenceError(
                "signal_evidence_required",
                "record does not carry an exact SignalEvidence envelope",
            )
        try:
            stored = self._repository.get(
                envelope.evidence_id,
                revision=record.revision,
            )
        except EvidenceStoreError as exc:
            raise BtstCandidateEvidenceError(
                "signal_record_untrusted",
                "signal record is not committed in this evidence store",
                evidence_id=envelope.evidence_id,
                revision=record.revision,
                reason=exc.code,
            ) from exc
        if (
            type(stored.evidence) is not SignalEvidence
            or stored.canonical_bytes() != record.canonical_bytes()
        ):
            raise BtstCandidateEvidenceError(
                "signal_record_untrusted",
                "signal record does not exactly match its committed revision",
                evidence_id=envelope.evidence_id,
                revision=record.revision,
            )
        try:
            raw = self._repository.raw_payload(
                envelope.payload_content_hash,
                evidence_id=envelope.evidence_id,
                revision=record.revision,
            )
        except EvidenceStoreError as exc:
            raise BtstCandidateEvidenceError(
                exc.code,
                "authoritative raw candidate payload is unavailable",
                evidence_id=envelope.evidence_id,
                reason=exc.code,
            ) from exc
        except BlobStoreError as exc:
            code = (
                "candidate_payload_missing"
                if exc.code == "blob_not_found"
                else "candidate_payload_read_failed"
            )
            raise BtstCandidateEvidenceError(
                code,
                "bound raw candidate payload is unavailable",
                evidence_id=envelope.evidence_id,
                reason=exc.code,
            ) from exc
        if hashlib.sha256(raw).hexdigest() != envelope.payload_content_hash:
            raise BtstCandidateEvidenceError(
                "candidate_payload_hash_mismatch",
                "bound raw candidate bytes do not match payload_content_hash",
                evidence_id=envelope.evidence_id,
            )
        try:
            candidate = BtstRawCandidatePayload.model_validate_json(raw, strict=True)
        except (ValidationError, ValueError) as exc:
            raise BtstCandidateEvidenceError(
                "candidate_payload_decode_failed",
                "bound bytes are not a strict BTST raw-candidate payload",
                evidence_id=envelope.evidence_id,
                reason=str(exc),
            ) from exc

        identity_parts = candidate.candidate_id.rsplit(":", 2)
        expected_prefix = f"{BTST_PRODUCER_NAMESPACE}:{candidate.snapshot_id}"
        try:
            identity_security_id = qualify_btst_security_id(identity_parts[1])
        except (BtstRawCandidateBuildError, IndexError):
            identity_security_id = None
        identity_valid = (
            len(identity_parts) == 3
            and identity_parts[0] == expected_prefix
            and identity_parts[2] == candidate.setup
            and identity_security_id == candidate.security_id
            and envelope.evidence_id
            == f"{candidate.candidate_id}:{candidate.signal_stage.value}"
            and envelope.family_id == expected_prefix
            and envelope.stage is candidate.signal_stage
        )
        if not identity_valid:
            raise BtstCandidateEvidenceError(
                "candidate_identity_mismatch",
                "raw candidate identity does not match its signal envelope",
                evidence_id=envelope.evidence_id,
            )
        if (
            candidate.producer_namespace != BTST_PRODUCER_NAMESPACE
            or envelope.subject_producer != BTST_PRODUCER_NAMESPACE
        ):
            raise BtstCandidateEvidenceError(
                "candidate_producer_mismatch",
                "raw candidate and envelope must remain in the BTST namespace",
                evidence_id=envelope.evidence_id,
            )
        if (
            type(expected_signal_session) is not date
            or candidate.signal_session != expected_signal_session
            or envelope.effective_at.date() != candidate.signal_session
        ):
            raise BtstCandidateEvidenceError(
                "signal_session_mismatch",
                "raw candidate session does not match the requested signal session",
                evidence_id=envelope.evidence_id,
            )
        if (
            candidate.strategy_semver != envelope.strategy_semver
            or candidate.behavior_fingerprint != envelope.behavior_fingerprint
            or candidate.execution_version != envelope.execution_version
            or candidate.cost_version != envelope.cost_version
        ):
            raise BtstCandidateEvidenceError(
                "candidate_version_mismatch",
                "raw candidate version bindings do not match its signal envelope",
                evidence_id=envelope.evidence_id,
            )
        return candidate

    def active_signal(
        self, evidence_id: str, *, cutoff: datetime
    ) -> EvidenceRecord[SignalEvidence] | None:
        """evidence_id 在 cutoff 时刻的 active 信号记录 (PIT 只读投影)。

        透传 ``repository.active_revision``; 未知 evidence_id 或早于
        首笔提交的 cutoff 返回 ``None`` (不抛错)。
        """
        try:
            return self._repository.active_revision(evidence_id, cutoff)
        except EvidenceStoreError:
            return None


__all__ = ["BtstCandidateEvidenceError", "BtstProducerApi"]
