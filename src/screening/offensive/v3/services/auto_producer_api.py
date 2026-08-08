"""Plan 05 Task 5: AutoProducerApi — Auto 全市场 shadow-only 证据服务.

薄适配器: 构造时内部自建 ``EvidenceRepository`` (issuer_namespace="auto")。
``produce_and_publish`` 先过 runtime gate, 再委托纯函数层
``produce_auto_signals``, 对每枚信封 payload = envelope.model_dump_json()
.encode() → 注入 signer 签名 → ``repository.publish`` (store 校验
signed.namespace == "auto")。只产出签名 ``SignalEvidence``, 永不含授权:
信封模型无 authorization 字段, 服务面也不暴露任何授权/许可方法。

runtime gate (fail-closed): ``runtime_mode_provider`` 在每次
``produce_and_publish`` 最先读取; 非 ``RuntimeMode.SHADOW`` (含默认
``None``) 抛 ``AutoProducerApiError`` code ``AUTO_PRODUCER_NOT_SHADOW``
且不触达 store — auto 恒 shadow-only, 任何非 shadow 模式都是配置错误。

只读面: ``active_signal`` 透传 ``repository.active_revision`` (PIT cutoff);
未知 evidence_id 或早于首笔提交的 cutoff 返回 ``None`` (不抛错)。

signer 私有: 本服务持有 ``_signer``, 不暴露任何公开访问器。
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
from src.screening.offensive.v3.policy.models import RuntimeMode
from src.screening.offensive.v3.producers.auto import (
    AUTO_BEHAVIOR_BASELINE,
    AUTO_PRODUCER_NAMESPACE,
    produce_auto_signals,
)

AUTO_PRODUCER_NOT_SHADOW: Final[str] = "auto_producer_not_shadow"
"""稳定 error code: auto 生产者只在 SHADOW 模式下产出 (fail-closed)。"""


class AutoProducerApiError(RuntimeError):
    """Auto 生产者边界失败; code 是稳定机器码, details 携带诊断字段。"""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


class AutoProducerApi:
    """Auto 全市场 shadow-only 证据服务: 只产签名 SignalEvidence, 永不含授权。"""

    def __init__(
        self,
        *,
        database_path: str,
        blob_store: BlobStore,
        verifier: VerifierProtocol,
        trust_head_provider: TrustHeadProvider,
        clock: Callable[[], datetime],
        signer: Callable[[bytes], SignedEnvelope],
        behavior_fingerprint: str = AUTO_BEHAVIOR_BASELINE,
        runtime_mode_provider: Callable[[], RuntimeMode] | None = None,
    ) -> None:
        """构造 Auto 证据服务: 内部自建 issuer_namespace="auto" 的仓库。

        Args:
            database_path / blob_store / verifier / trust_head_provider:
                透传给内部 ``EvidenceRepository`` (issuer_namespace="auto")。
            clock: 注入可信时钟 (store 拥有 ingested_at, 本服务不落时间)。
            signer: 注入签名器; 每个 payload 签名声明 ArtifactKind.SIGNAL
                且 namespace == "auto", 否则 store 验证拒绝。
            behavior_fingerprint: 注入本服务产出信封的行为指纹
                (64-hex; 占位符默认值由 GREEN 解析)。
            runtime_mode_provider: 每次 ``produce_and_publish`` 最先读取;
                非 ``RuntimeMode.SHADOW`` (含 ``None``) fail-closed 拒绝。
        """
        self._clock = clock
        self._signer = signer
        self._behavior_fingerprint = behavior_fingerprint
        self._runtime_mode_provider = runtime_mode_provider
        self._repository = EvidenceRepository(
            database_path=database_path,
            blob_store=blob_store,
            verifier=verifier,
            trust_head_provider=trust_head_provider,
            issuer_namespace=AUTO_PRODUCER_NAMESPACE,
            clock=clock,
        )

    def produce_and_publish(
        self, snapshot: VerifiedDailyActionSnapshot
    ) -> tuple[EvidenceRecord[SignalEvidence], ...]:
        """运行 Auto 信号漏斗并发布全部签名 SignalEvidence (shadow-only)。

        Fail-closed 守卫: 最先读取 ``runtime_mode_provider()``; 非
        ``RuntimeMode.SHADOW`` (含默认 ``None``) 抛 ``AutoProducerApiError``
        code ``AUTO_PRODUCER_NOT_SHADOW``, 不签名、不触碰 store。
        通过 gate 后委托 ``produce_auto_signals`` 并逐信封发布, 返回
        与信封一一对应的发布记录 (每个候选 CANDIDATE → SELECTED 两枚)。
        """
        self._require_shadow_mode()
        records: list[EvidenceRecord[SignalEvidence]] = []
        for envelope in produce_auto_signals(
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

    # -- 私有守卫 ----------------------------------------------------------------

    def _require_shadow_mode(self) -> None:
        """Fail-closed shadow gate: auto 恒 shadow-only。

        每次 ``produce_and_publish`` 最先调用: 读 ``runtime_mode_provider()``
        (默认 ``None`` → 拒绝 — auto 恒 shadow-only, 无 provider 即配置错误);
        非 ``RuntimeMode.SHADOW`` 抛 ``AutoProducerApiError`` code
        ``AUTO_PRODUCER_NOT_SHADOW``。
        """
        mode = (
            None
            if self._runtime_mode_provider is None
            else self._runtime_mode_provider()
        )
        if mode is not RuntimeMode.SHADOW:
            raise AutoProducerApiError(
                AUTO_PRODUCER_NOT_SHADOW,
                "auto producer publishes only in SHADOW runtime mode",
                mode=None if mode is None else mode.value,
            )


__all__ = [
    "AUTO_PRODUCER_NOT_SHADOW",
    "AutoProducerApi",
    "AutoProducerApiError",
]
