"""Plan 05 Task 5 (RED skeleton): BtstProducerApi — BTST raw evidence 服务.

薄适配器: 构造时内部自建 ``EvidenceRepository`` (issuer_namespace="btst")。
``produce_and_publish`` 委托纯函数层 ``produce_btst_signals``, 对每枚信封
payload = envelope.model_dump_json().encode() → 注入 signer 签名 →
``repository.publish`` (store 校验 signed.namespace == "btst")。只产出签名
``SignalEvidence`` (原始 targets/features), 不做 regime / streak /
composite sizing; 信封模型无 authorization 字段, 服务面也不暴露任何
授权/许可方法。

BTST 不做 runtime gate: ``RuntimeMode.BTST_CANARY`` 是 BTST 产出的合法
模式, 因此本服务不注入 ``runtime_mode_provider`` (contrast:
``services/auto_producer_api.AutoProducerApi`` 恒 shadow-only)。

只读面: ``active_signal`` 透传 ``repository.active_revision`` (PIT cutoff);
未知 evidence_id 或早于首笔提交的 cutoff 返回 ``None`` (不抛错)。

signer 私有: 本服务持有 ``_signer``, 不暴露任何公开访问器。

注意: 本模块当前是 RED 骨架 — 所有方法体 ``raise NotImplementedError``,
由主代理随后实现 GREEN (透传 store)。
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Final

from src.screening.offensive.daily_action_snapshot import (
    VerifiedDailyActionSnapshot,
)
from src.screening.offensive.v3.contracts import SignedEnvelope
from src.screening.offensive.v3.contracts.evidence import (
    EvidenceRecord,
    SignalEvidence,
)
from src.screening.offensive.v3.evidence.blob_store import BlobStore
from src.screening.offensive.v3.evidence.repository import (
    EvidenceRepository,
    EvidenceStoreError,
    TrustHeadProvider,
    VerifierProtocol,
)
from src.screening.offensive.v3.producers.btst import (
    BTST_BEHAVIOR_BASELINE,
    BTST_PRODUCER_NAMESPACE,
    produce_btst_signals,
)


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
        for envelope in produce_btst_signals(
            snapshot,
            behavior_fingerprint=self._behavior_fingerprint,
        ):
            payload = envelope.model_dump_json().encode("utf-8")
            signed = self._signer(payload)
            records.append(self._repository.publish(signed, payload))
        return tuple(records)

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


__all__ = ["BtstProducerApi"]
