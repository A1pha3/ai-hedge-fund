"""Plan 05 Task 5: Auto 全市场 shadow-only 信号生产者 (纯函数层).

纯函数: 只消费 ``VerifiedDailyActionSnapshot``, 构造不可变 ``SignalEvidence``
信封并返回; 无网络/文件 I/O, 不触碰 store。内部调用
``scan_from_verified_snapshot`` (同为纯函数, "never reopens cache files")
得到扫描候选, 为每个候选按漏斗阶段生成 CANDIDATE → SELECTED 两枚信封。

Auto 信号只反映候选原始打分 (``PlanCandidate.trigger_strength`` /
``entry_price``), 不携带任何 regime / streak / composite sizing 输出;
信封模型 (``contracts/evidence.SignalEvidence``, ``extra="forbid"``) 没有
authorization 字段, 本模块也不会生成任何授权类字段。

证据身份 (evidence_id) 契约 (GREEN 必须遵守):
    f"{AUTO_PRODUCER_NAMESPACE}:{snapshot.snapshot_id}:{ticker}:{setup}:{stage.value}"
- 同一 snapshot 的同一候选同一 stage 两次 produce 得到相同 evidence_id
  (store publish 幂等的前提); behavior 代际变化走 correction revision
  协议, 不改 evidence_id。
- stage 参与 evidence_id: 同一候选的 CANDIDATE 与 SELECTED 是不同的证据行。
- producer 命名空间前缀使 auto 与 btst 的 evidence_id 空间互不混淆。
family_id = f"{AUTO_PRODUCER_NAMESPACE}:{snapshot.snapshot_id}"
(STRATEGY_LINEAGE 要求非空 family_id)。

时间链约定: 信封时间戳全部由 ``snapshot.signal_date`` 派生 —
observed_at = effective_at = provider_published_at = signal_date 15:00 UTC,
available_at = signal_date+1 15:00 UTC (24 小时窗口)。发布 (store
ingested_at = clock()) 必须落在此窗口内; 测试将 signal_date 选为 clock
前一天以满足该约束。
"""

from __future__ import annotations

import hashlib
from datetime import datetime, time, timedelta, timezone
from typing import Final

from src.screening.offensive.daily_action import scan_from_verified_snapshot
from src.screening.offensive.daily_action_service import PlanCandidate
from src.screening.offensive.daily_action_snapshot import (
    VerifiedDailyActionSnapshot,
)
from src.screening.offensive.v3.contracts import ExecutionMode
from src.screening.offensive.v3.contracts.base import (
    EvidenceScope,
    SignalStage,
)
from src.screening.offensive.v3.contracts.evidence import SignalEvidence

AUTO_PRODUCER_NAMESPACE: Final[str] = "auto"
"""本生产者专属 issuer namespace, 同时是信封 subject_producer。"""

AUTO_BEHAVIOR_BASELINE: Final[str] = hashlib.sha256(b"auto-v1").hexdigest()
"""命名基线: legacy 自动全市场行为冻结为确定性指纹 (sha256("auto-v1"))。

信封的 behavior_fingerprint 必须是 64-hex; 调用方应注入显式指纹, 本常量
是未注入时的默认基线 — 任何语义变化必须换新基线/走 correction revision,
不得复用本值。"""

AUTO_STRATEGY_SEMVER: Final[str] = "0.1.0"
"""本生产者首个 strategy_semver 代际。"""


def produce_auto_signals(
    snapshot: VerifiedDailyActionSnapshot,
    *,
    behavior_fingerprint: str,
    strategy_semver: str = AUTO_STRATEGY_SEMVER,
) -> tuple[SignalEvidence, ...]:
    """Auto 全市场 shadow-only 信号漏斗: 对每个候选生成 CANDIDATE → SELECTED。

    Args:
        snapshot: 已验证 PIT 快照 (纯函数输入, 不重开缓存文件)。
        behavior_fingerprint: 注入的生产者行为指纹 (64-hex; 由上层服务传入)。
        strategy_semver: 生产者代际版本, 默认 ``AUTO_STRATEGY_SEMVER``。

    Returns:
        每个候选两枚信封 (CANDIDATE → SELECTED), 顺序与扫描一致
        (trigger_strength 降序、ticker 升序)。无候选时返回空元组。
    """
    scan = scan_from_verified_snapshot(snapshot)
    envelopes: list[SignalEvidence] = []
    for candidate in scan.candidates:
        for stage in (SignalStage.CANDIDATE, SignalStage.SELECTED):
            envelopes.append(
                _signal_envelope(
                    snapshot=snapshot,
                    candidate=candidate,
                    stage=stage,
                    behavior_fingerprint=behavior_fingerprint,
                    strategy_semver=strategy_semver,
                    producer_namespace=AUTO_PRODUCER_NAMESPACE,
                )
            )
    return tuple(envelopes)


def _signal_envelope(
    *,
    snapshot: VerifiedDailyActionSnapshot,
    candidate: PlanCandidate,
    stage: SignalStage,
    behavior_fingerprint: str,
    strategy_semver: str,
    producer_namespace: str,
) -> SignalEvidence:
    """构造一枚候选漏斗阶段的不可变信号信封。

    时间链由 ``snapshot.signal_date`` 派生: observed_at = effective_at =
    provider_published_at = signal_date 15:00 UTC, available_at =
    signal_date+1 15:00 UTC (24 小时窗口)。evidence_id 与 family_id 契约
    见模块 docstring。信封只携带原始候选字段, 不含任何授权/sizing 输出。
    """
    session_start = datetime.combine(
        snapshot.signal_date, time(15, 0), tzinfo=timezone.utc
    )
    return SignalEvidence(
        evidence_id=(
            f"{producer_namespace}:{snapshot.snapshot_id}:"
            f"{candidate.ticker}:{candidate.setup}:{stage.value}"
        ),
        subject_scope=EvidenceScope.STRATEGY_LINEAGE,
        subject_producer=producer_namespace,
        family_id=f"{producer_namespace}:{snapshot.snapshot_id}",
        strategy_semver=strategy_semver,
        behavior_fingerprint=behavior_fingerprint,
        policy_epoch=1,
        execution_version=f"{producer_namespace}.funnel.v1",
        cost_version="cn-a-share-costs.v1",
        effective_at=session_start,
        provider_published_at=session_start,
        observed_at=session_start,
        available_at=session_start + timedelta(days=1),
        mode=ExecutionMode.RESEARCH_RECONSTRUCTION,
        source_authority=f"{producer_namespace}.producer",
        payload_content_hash=hashlib.sha256(
            (
                f"{snapshot.snapshot_id}:{candidate.ticker}:"
                f"{candidate.setup}:{stage.value}:{behavior_fingerprint}"
            ).encode("utf-8")
        ).hexdigest(),
        schema_major=2,
        evidence_kind="signal",
        stage=stage,
    )


__all__ = [
    "AUTO_BEHAVIOR_BASELINE",
    "AUTO_PRODUCER_NAMESPACE",
    "AUTO_STRATEGY_SEMVER",
    "produce_auto_signals",
]
