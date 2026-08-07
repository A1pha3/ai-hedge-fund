"""Plan 05 Task 5 (RED skeleton): BTST raw targets/features 信号生产者 (纯函数层).

纯函数: 只消费 ``VerifiedDailyActionSnapshot``, 构造不可变 ``SignalEvidence``
信封并返回; 无网络/文件 I/O, 不触碰 store。内部调用
``scan_from_verified_snapshot`` (同为纯函数, "never reopens cache files")
得到扫描候选, 为每个候选按漏斗阶段生成 CANDIDATE → SELECTED 两枚信封。

BTST 只输出 raw targets/features (候选的 ticker/setup/trigger_strength/
entry_price/signal_date/snapshot_id/setup_consumed_fingerprint/metadata),
不做 regime / streak / composite sizing — 信封模型 (``extra="forbid"``)
没有授权与 sizing 字段, 本模块也不会生成任何授权类字段。

证据身份 (evidence_id) 契约 (GREEN 必须遵守):
    f"{BTST_PRODUCER_NAMESPACE}:{snapshot.snapshot_id}:{ticker}:{setup}:{stage.value}"
- 同一 snapshot 的同一候选同一 stage 两次 produce 得到相同 evidence_id
  (store publish 幂等的前提); behavior 代际变化走 correction revision
  协议, 不改 evidence_id。
- stage 参与 evidence_id: 同一候选的 CANDIDATE 与 SELECTED 是不同的证据行。
- producer 命名空间前缀使 auto 与 btst 的 evidence_id 空间互不混淆。
family_id = f"{BTST_PRODUCER_NAMESPACE}:{snapshot.snapshot_id}"
(STRATEGY_LINEAGE 要求非空 family_id)。

时间链约定: 与 ``producers.auto`` 完全一致 — 信封时间戳全部由
``snapshot.signal_date`` 派生 (observed_at = signal_date 15:00 UTC,
available_at = signal_date+1 15:00 UTC); 测试将 signal_date 选为 clock
前一天以满足 store 的 ingested_at 窗口约束。
"""

from __future__ import annotations

import hashlib
from typing import Final

from src.screening.offensive.daily_action import scan_from_verified_snapshot
from src.screening.offensive.daily_action_snapshot import (
    VerifiedDailyActionSnapshot,
)
from src.screening.offensive.v3.contracts.base import SignalStage
from src.screening.offensive.v3.contracts.evidence import SignalEvidence
from src.screening.offensive.v3.producers.auto import _signal_envelope

BTST_PRODUCER_NAMESPACE: Final[str] = "btst"
"""本生产者专属 issuer namespace, 同时是信封 subject_producer。"""

BTST_BEHAVIOR_BASELINE: Final[str] = hashlib.sha256(b"btst-v1").hexdigest()
"""命名基线: legacy BTST 行为冻结为确定性指纹 (sha256("btst-v1"))。

信封的 behavior_fingerprint 必须是 64-hex; 调用方应注入显式指纹, 本常量
是未注入时的默认基线 — 任何语义变化必须换新基线/走 correction revision,
不得复用本值。"""

BTST_STRATEGY_SEMVER: Final[str] = "0.1.0"
"""本生产者首个 strategy_semver 代际。"""


def produce_btst_signals(
    snapshot: VerifiedDailyActionSnapshot,
    *,
    behavior_fingerprint: str,
    strategy_semver: str = BTST_STRATEGY_SEMVER,
) -> tuple[SignalEvidence, ...]:
    """BTST raw targets/features 信号: 只输出候选原始字段, 无 sizing。

    Args:
        snapshot: 已验证 PIT 快照 (纯函数输入, 不重开缓存文件)。
        behavior_fingerprint: 注入的生产者行为指纹 (64-hex; 由上层服务传入)。
        strategy_semver: 生产者代际版本, 默认 ``BTST_STRATEGY_SEMVER``。

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
                    producer_namespace=BTST_PRODUCER_NAMESPACE,
                )
            )
    return tuple(envelopes)


__all__ = [
    "BTST_BEHAVIOR_BASELINE",
    "BTST_PRODUCER_NAMESPACE",
    "BTST_STRATEGY_SEMVER",
    "produce_btst_signals",
]
