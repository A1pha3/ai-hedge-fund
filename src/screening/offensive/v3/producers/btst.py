"""Plan 05 Task 5: BTST raw targets/features 信号生产者 (纯函数层).

纯函数: 只消费 ``VerifiedDailyActionSnapshot``, 构造不可变
``BtstRawCandidatePayload`` 与精确绑定它的 ``SignalEvidence`` 信封并返回;
无网络/文件 I/O, 不触碰 store。内部调用
``scan_from_verified_snapshot`` (同为纯函数, "never reopens cache files")
得到扫描候选, 为每个候选按漏斗阶段生成 CANDIDATE → SELECTED 两枚信封。

BTST 只输出 raw targets/features (候选的 security/setup/trigger_strength/
entry_price/target_weight/signal_date/snapshot_id/setup_consumed_fingerprint/industry),
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
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from typing import Final

from src.screening.offensive.daily_action import scan_from_verified_snapshot
from src.screening.offensive.daily_action_service import PlanCandidate
from src.screening.offensive.daily_action_snapshot import (
    VerifiedDailyActionSnapshot,
)
from src.screening.offensive.v3.contracts.base import SignalStage
from src.screening.offensive.v3.contracts.btst_candidate import (
    BtstCandidateIndustryState,
    BtstRawCandidatePayload,
)
from src.screening.offensive.v3.contracts.evidence import SignalEvidence
from src.screening.offensive.v3.producers.auto import _signal_envelope
from src.tools.ashare_board_utils import (
    BEIJING_EXCHANGE_SYMBOL_PREFIXES,
    SHANGHAI_EXCHANGE_SYMBOL_PREFIXES,
    SHENZHEN_EXCHANGE_SYMBOL_PREFIXES,
    split_ashare_exchange_prefix,
    to_tushare_code,
)

BTST_PRODUCER_NAMESPACE: Final[str] = "btst"
"""本生产者专属 issuer namespace, 同时是信封 subject_producer。"""

BTST_BEHAVIOR_BASELINE: Final[str] = hashlib.sha256(
    b"btst-raw-candidate-payload-v1"
).hexdigest()
"""BTST raw-candidate payload v1 的确定性行为指纹。

信封的 behavior_fingerprint 必须是 64-hex; 调用方应注入显式指纹, 本常量
是未注入时的默认基线 — 任何语义变化必须换新基线/走 correction revision,
不得复用本值。"""

BTST_STRATEGY_SEMVER: Final[str] = "0.2.0"
"""原始候选 payload 可持久化、可重验后的 producer evidence 代际。"""

BTST_EXECUTION_VERSION: Final[str] = "btst.funnel.v1"
BTST_COST_VERSION: Final[str] = "cn-a-share-costs.v1"
BTST_RAW_CANDIDATE_SCHEMA_MAJOR: Final[int] = 1


class BtstRawCandidateBuildError(ValueError):
    """Typed fail-closed rejection while freezing a scanner candidate."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


@dataclass(frozen=True)
class BtstSignalArtifact:
    """A signal envelope paired with the exact raw bytes it binds."""

    envelope: SignalEvidence
    payload: BtstRawCandidatePayload

    def __post_init__(self) -> None:
        if self.envelope.payload_content_hash != self.payload.content_hash():
            raise ValueError("BTST signal envelope does not bind its raw payload")


def _scaled_integer(
    value: object,
    *,
    scale: int,
    field_name: str,
    exact: bool,
) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be numeric, not bool")
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be finite numeric input") from exc
    if not decimal_value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    scaled = decimal_value * scale
    integral = scaled.to_integral_value(rounding=ROUND_HALF_EVEN)
    if exact and scaled != integral:
        raise ValueError(f"{field_name} exceeds the supported precision")
    return int(integral)


def qualify_btst_security_id(ticker: object) -> str:
    """Return the deterministic A-share security id, rejecting unknowns."""

    explicit_exchange, symbol = split_ashare_exchange_prefix(ticker)
    if len(symbol) != 6 or not symbol.isdigit():
        raise BtstRawCandidateBuildError(
            "security_id_unknown",
            "BTST security identity must be a six-digit A-share symbol",
            ticker=str(ticker),
        )
    prefix_exchange: str | None = None
    if symbol.startswith(SHANGHAI_EXCHANGE_SYMBOL_PREFIXES):
        prefix_exchange = "sh"
    elif symbol.startswith(SHENZHEN_EXCHANGE_SYMBOL_PREFIXES):
        prefix_exchange = "sz"
    elif symbol.startswith(BEIJING_EXCHANGE_SYMBOL_PREFIXES):
        prefix_exchange = "bj"
    if prefix_exchange is None or (
        explicit_exchange is not None and explicit_exchange != prefix_exchange
    ):
        raise BtstRawCandidateBuildError(
            "security_id_unknown",
            "BTST security exchange cannot be inferred without guessing",
            ticker=str(ticker),
        )
    return to_tushare_code(symbol)


def build_btst_raw_candidate_payload(
    candidate: PlanCandidate,
    *,
    stage: SignalStage,
    industry: str | None,
    behavior_fingerprint: str,
    strategy_semver: str = BTST_STRATEGY_SEMVER,
) -> BtstRawCandidatePayload:
    """Freeze one scanner candidate without applying downstream sizing."""

    normalized_industry = (
        industry.strip() if isinstance(industry, str) and industry.strip() else None
    )
    industry_state = (
        BtstCandidateIndustryState.KNOWN
        if normalized_industry is not None
        else BtstCandidateIndustryState.UNKNOWN
    )
    candidate_id = (
        f"{BTST_PRODUCER_NAMESPACE}:{candidate.snapshot_id}:"
        f"{candidate.ticker}:{candidate.setup}"
    )
    trigger_strength_ppm = _scaled_integer(
        candidate.trigger_strength,
        scale=1_000_000,
        field_name="trigger_strength",
        exact=False,
    )
    if trigger_strength_ppm > 1_000_000:
        raise BtstRawCandidateBuildError(
            "trigger_strength_out_of_range",
            "BTST trigger strength must be within [0, 1]",
            trigger_strength_ppm=trigger_strength_ppm,
        )
    return BtstRawCandidatePayload(
        payload_kind="btst_raw_candidate",
        schema_major=BTST_RAW_CANDIDATE_SCHEMA_MAJOR,
        candidate_id=candidate_id,
        producer_namespace=BTST_PRODUCER_NAMESPACE,
        security_id=qualify_btst_security_id(candidate.ticker),
        signal_stage=stage,
        signal_session=candidate.signal_date,
        entry_price_micros=_scaled_integer(
            candidate.entry_price,
            scale=1_000_000,
            field_name="entry_price",
            exact=True,
        ),
        setup=candidate.setup,
        setup_version=candidate.setup_version,
        target_weight_ppm=_scaled_integer(
            candidate.target_weight,
            scale=1_000_000,
            field_name="target_weight",
            exact=False,
        ),
        trigger_strength_ppm=trigger_strength_ppm,
        priority=candidate.priority,
        industry_state=industry_state,
        industry=normalized_industry,
        snapshot_id=candidate.snapshot_id,
        setup_consumed_fingerprint=candidate.setup_consumed_fingerprint,
        strategy_semver=strategy_semver,
        behavior_fingerprint=behavior_fingerprint,
        execution_version=BTST_EXECUTION_VERSION,
        cost_version=BTST_COST_VERSION,
    )


def produce_btst_signal_artifacts(
    snapshot: VerifiedDailyActionSnapshot,
    *,
    behavior_fingerprint: str,
    strategy_semver: str = BTST_STRATEGY_SEMVER,
) -> tuple[BtstSignalArtifact, ...]:
    """Produce envelopes together with the canonical candidate bytes they bind."""

    scan = scan_from_verified_snapshot(snapshot)
    artifacts: list[BtstSignalArtifact] = []
    industries = snapshot.manifest.shared_evidence.industry_by_ticker
    for candidate in scan.candidates:
        if candidate.signal_date != snapshot.signal_date:
            raise ValueError("candidate signal_session does not match snapshot")
        if candidate.snapshot_id != snapshot.snapshot_id:
            raise ValueError("candidate snapshot_id does not match snapshot")
        for stage in (SignalStage.CANDIDATE, SignalStage.SELECTED):
            payload = build_btst_raw_candidate_payload(
                candidate,
                stage=stage,
                industry=industries.get(candidate.ticker),
                behavior_fingerprint=behavior_fingerprint,
                strategy_semver=strategy_semver,
            )
            legacy_envelope = _signal_envelope(
                snapshot=snapshot,
                candidate=candidate,
                stage=stage,
                behavior_fingerprint=behavior_fingerprint,
                strategy_semver=strategy_semver,
                producer_namespace=BTST_PRODUCER_NAMESPACE,
            )
            envelope = SignalEvidence.model_validate(
                legacy_envelope.model_dump(mode="python")
                | {"payload_content_hash": payload.content_hash()},
                strict=True,
            )
            artifacts.append(BtstSignalArtifact(envelope=envelope, payload=payload))
    return tuple(artifacts)


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
    return tuple(
        artifact.envelope
        for artifact in produce_btst_signal_artifacts(
            snapshot,
            behavior_fingerprint=behavior_fingerprint,
            strategy_semver=strategy_semver,
        )
    )


__all__ = [
    "BTST_BEHAVIOR_BASELINE",
    "BTST_COST_VERSION",
    "BTST_EXECUTION_VERSION",
    "BTST_PRODUCER_NAMESPACE",
    "BTST_RAW_CANDIDATE_SCHEMA_MAJOR",
    "BTST_STRATEGY_SEMVER",
    "BtstSignalArtifact",
    "BtstRawCandidateBuildError",
    "build_btst_raw_candidate_payload",
    "produce_btst_signal_artifacts",
    "produce_btst_signals",
    "qualify_btst_security_id",
]
