"""SessionBatchSealer — store 侧会话批授权 (特权 worker primitive, 2026-08-20).

三段式背书模型的 store 落地面。锁定: 声明集逐成员 store 背书 (cutoff 正确
active 修订 + artifact hash)、btst 完备性 (未声明的同会话 SELECTED 即冲
突)、根由唯一 merkle 实现从**store 真相**计算、恰等重放幂等 / 背离冲突、
cutoff 后发布的证据批外不可见 (PIT)、authority 模型自验证 (篡改任一哈希
或根即构造失败)、verify 零写入全量重推导。

信任栈: regime/排程命名空间用 offline_rig (SNAPSHOT), btst 用 SIGNAL
能力的 ephemeral 链 (crib test_btst_producer_api 帮手) — 三命名空间共享
单 evidence.sqlite3 (trial root 单库布局)。
"""

from __future__ import annotations

import hashlib
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from src.screening.offensive.v3 import trust as v3_trust
from src.screening.offensive.v3.contracts import ExecutionMode, SUPPORTED_SCHEMA_MAJOR
from src.screening.offensive.v3.contracts.base import EvidenceScope, SignalStage
from src.screening.offensive.v3.contracts.btst_candidate import (
    BtstCandidateIndustryState,
    BtstRawCandidatePayload,
)
from src.screening.offensive.v3.contracts.evidence import (
    EvidenceRecord,
    SignalEvidence,
    SnapshotEvidence,
)
from src.screening.offensive.v3.contracts.regime import (
    RegimeObservation,
    RegimeObservationReason,
    RegimeSourceRevision,
    RegimeState,
)
from src.screening.offensive.v3.evidence.blob_store import BlobStore
from src.screening.offensive.v3.evidence.merkle import evidence_set_merkle_root
from src.screening.offensive.v3.evidence.offline_rig import build_offline_evidence_rig
from src.screening.offensive.v3.evidence.regime import (
    RegimeObservationPublisher,
    RegimeObservationReader,
)
from src.screening.offensive.v3.evidence.repository import EvidenceRepository
from src.screening.offensive.v3.evidence.session_batch import (
    BTST_NAMESPACE,
    DECISION_BATCH_RULE_VERSION,
    REGIME_EVIDENCE_ID,
    REGIME_NAMESPACE,
    SCHEDULE_NAMESPACE,
    SessionBatchAuthority,
    SessionBatchError,
    SessionBatchSealer,
)
from src.screening.offensive.v3.evidence.trading_schedule import (
    build_schedule_envelope,
    derive_trading_schedule,
)

# btst SIGNAL 能力链 crib (跨目录)
_BTST_TEST_DIR = Path(__file__).resolve().parents[1] / "services"
if str(_BTST_TEST_DIR) not in sys.path:
    sys.path.insert(0, str(_BTST_TEST_DIR))
from test_btst_producer_api import (  # noqa: E402
    _issuer,
    _root_context,
    _signed,
    _trust_capability,
)

UTC = timezone.utc
SESSION = date(2026, 8, 6)
PUBLISH_AT = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)
CUTOFF = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
BTST_ISSUER = ("btst.producer", "btst-key-1")


def build_batch_world(tmp_path: Path, *, clock_at: datetime = PUBLISH_AT) -> SimpleNamespace:
    """三命名空间共享单 evidence.sqlite3 + 批封存器 (worker 测试也消费)。

    btst 仓库持**可推进时钟句柄** — 测试能把某次发布挪到 cutoff 之后,
    验证 PIT 语义 (批外不可见) 而不是靠第二个世界叠库。
    """
    database_path = tmp_path / "evidence.sqlite3"
    blobs = BlobStore(tmp_path / "blobs")
    mutable_clock = {"now": clock_at}

    def tick() -> datetime:
        return mutable_clock["now"]

    regime_rig = build_offline_evidence_rig(
        database_path=database_path, blobs_dir=tmp_path / "blobs", namespace="regime",
        clock=tick, trust_now=clock_at,
    )
    schedule_rig = build_offline_evidence_rig(
        database_path=database_path, blobs_dir=tmp_path / "blobs",
        namespace=SCHEDULE_NAMESPACE, clock=tick, trust_now=clock_at,
    )
    key = Ed25519PrivateKey.generate()
    capability = _trust_capability()
    registry = v3_trust.TrustedRegistry(
        issuers=(
            _issuer(
                key,
                capability,
                issuer_id=BTST_ISSUER[0],
                key_id=BTST_ISSUER[1],
                kind=v3_trust.IssuerKind.SIGNAL_PRODUCER,
            ),
        )
    )
    verifier, head_provider = _root_context(registry)
    btst_repository = EvidenceRepository(
        database_path=str(database_path),
        blob_store=blobs,
        verifier=verifier,
        trust_head_provider=head_provider,
        issuer_namespace=BTST_NAMESPACE,
        clock=tick,
    )
    sealer = SessionBatchSealer(
        database_path=str(database_path),
        repositories={
            REGIME_NAMESPACE: regime_rig.repository,
            SCHEDULE_NAMESPACE: schedule_rig.repository,
            BTST_NAMESPACE: btst_repository,
        },
        clock=lambda: clock_at,
    )
    return SimpleNamespace(
        database_path=database_path,
        regime_rig=regime_rig,
        schedule_rig=schedule_rig,
        btst_key=key,
        btst_capability=capability,
        btst_repository=btst_repository,
        sealer=sealer,
        advance_clock=lambda at: mutable_clock.__setitem__("now", at),
        now=tick,
    )


class _RegimeSignerPort:
    def __init__(self, signer) -> None:
        self._signer = signer

    def sign_snapshot(self, snapshot, payload: bytes):
        return self._signer(payload)


def publish_regime(world, *, session: date = SESSION) -> EvidenceRecord:
    now = world.now()
    observation = RegimeObservation(
        signal_session=session,
        state=RegimeState.NORMAL,
        reason=RegimeObservationReason.CLASSIFIED,
        raw_state="normal",
        source_revisions=(
            RegimeSourceRevision(
                evidence_id=REGIME_EVIDENCE_ID, revision=1, artifact_hash="d" * 64
            ),
        ),
        effective_at=now,
        provider_published_at=now,
        observed_at=now,
        classifier_semver="1.0.0",
        behavior_fingerprint="d" * 64,
        input_schema_hash="d" * 64,
    )
    snapshot = SnapshotEvidence(
        evidence_id=REGIME_EVIDENCE_ID,
        subject_scope=EvidenceScope.GLOBAL,
        subject_producer=REGIME_NAMESPACE,
        family_id=None,
        strategy_semver="1.0.0",
        behavior_fingerprint="d" * 64,
        policy_epoch=1,
        execution_version="t0-close-t1-open-t10-open.v1",
        cost_version="cn-a-share-costs.v1",
        effective_at=now,
        provider_published_at=now,
        observed_at=now,
        available_at=now,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        source_authority="regime.classifier",
        payload_content_hash=hashlib.sha256(observation.canonical_bytes()).hexdigest(),
        schema_major=SUPPORTED_SCHEMA_MAJOR,
        evidence_kind="snapshot",
    )
    return RegimeObservationPublisher(world.regime_rig.repository).publish(
        observation, snapshot, _RegimeSignerPort(world.regime_rig.signer)
    )


def publish_schedule(
    world, *, session: date = SESSION, day_offset: int = 1
) -> EvidenceRecord:
    """day_offset 平移日历窗口 → 不同 following 切片 → 不同 evidence_id。

    同 signal_session 的第二条排程 (完备性 v2 的对抗样本) 与另一会话的
    排程 (正例) 都由这一个参数化入口构造。
    """
    now = world.now()
    schedule = derive_trading_schedule(
        signal_session=session,
        calendar_dates=tuple(
            session + timedelta(days=d)
            for d in range(day_offset, day_offset + 15)
        ),
        available_at=now,
    )
    blob = schedule.canonical_bytes()
    blob_hash = world.schedule_rig.repository.persist_payload(blob)
    envelope = build_schedule_envelope(schedule, observed_at=now)
    assert envelope.payload_content_hash == blob_hash
    envelope_bytes = envelope.model_dump_json().encode("utf-8")
    return world.schedule_rig.repository.publish(
        world.schedule_rig.signer(envelope_bytes), envelope_bytes
    )


def publish_candidate(
    world, ticker: str, *, session: date = SESSION, snapshot_id: str = "snap-1",
    stage: SignalStage = SignalStage.SELECTED,
) -> EvidenceRecord:
    """ticker 驱动全部身份 (candidate_id/security/family — referenced-payload
    绑定校验器逐段核对, 三者必须同源); stage 决定证据 id 后缀。"""
    now = world.now()
    candidate_id = f"btst:{snapshot_id}:{ticker}:btst_breakout"
    payload = BtstRawCandidatePayload(
        payload_kind="btst_raw_candidate",
        schema_major=1,
        candidate_id=candidate_id,
        producer_namespace=BTST_NAMESPACE,
        security_id=f"{ticker}.SZ",
        signal_stage=stage,
        signal_session=session,
        entry_price_micros=1_000_000,
        setup="btst_breakout",
        setup_version="v2",
        target_weight_ppm=100_000,
        trigger_strength_ppm=900_000,
        priority=1,
        industry_state=BtstCandidateIndustryState.KNOWN,
        industry="electronics",
        snapshot_id=snapshot_id,
        setup_consumed_fingerprint="sha256:" + "a" * 64,
        strategy_semver="0.1.0",
        behavior_fingerprint="a" * 64,
        execution_version="btst.funnel.v1",
        cost_version="cn-a-share-costs.v1",
    )
    envelope = SignalEvidence(
        evidence_id=f"{candidate_id}:{stage.value}",
        subject_scope=EvidenceScope.STRATEGY_LINEAGE,
        subject_producer=BTST_NAMESPACE,
        family_id=f"btst:{snapshot_id}",
        strategy_semver="0.1.0",
        behavior_fingerprint="a" * 64,
        policy_epoch=1,
        execution_version="btst.funnel.v1",
        cost_version="cn-a-share-costs.v1",
        effective_at=datetime(session.year, session.month, session.day, 9, 0, tzinfo=UTC),
        provider_published_at=now,
        observed_at=now,
        available_at=now,
        mode=ExecutionMode.RESEARCH_RECONSTRUCTION,
        source_authority="btst.producer",
        payload_content_hash=payload.content_hash(),
        schema_major=SUPPORTED_SCHEMA_MAJOR,
        evidence_kind="signal",
        stage=stage,
    )
    world.btst_repository.persist_payload(payload.canonical_bytes())
    envelope_bytes = envelope.model_dump_json().encode("utf-8")
    signed = _signed(
        world.btst_key,
        world.btst_capability,
        issuer_id=BTST_ISSUER[0],
        key_id=BTST_ISSUER[1],
        payload=envelope_bytes,
    )
    return world.btst_repository.publish(
        signed, envelope_bytes, referenced_payload=payload.canonical_bytes()
    )


def _seal(world, candidate_ids=()):
    return world.sealer.seal_decision_batch(
        session=SESSION,
        cutoff=CUTOFF,
        schedule_evidence_id=publish_schedule(world).evidence.evidence_id,
        candidate_evidence_ids=tuple(candidate_ids),
    )


def test_seal_and_verify_round_trip(tmp_path):
    world = build_batch_world(tmp_path)
    publish_regime(world)
    schedule_record = publish_schedule(world)
    candidate = publish_candidate(world, "300001")
    authority = world.sealer.seal_decision_batch(
        session=SESSION,
        cutoff=CUTOFF,
        schedule_evidence_id=schedule_record.evidence.evidence_id,
        candidate_evidence_ids=(candidate.evidence.evidence_id,),
    )
    assert authority.rule_version == DECISION_BATCH_RULE_VERSION
    keys = [(b.issuer_namespace, b.evidence_id) for b in authority.bindings]
    assert keys == sorted(keys) and len(keys) == 3  # regime + schedule + candidate
    assert authority.evidence_set_merkle_root == evidence_set_merkle_root(
        (b.evidence_id, b.artifact_hash) for b in authority.bindings
    )
    assert authority.commit_sequence_watermark >= 1
    rebuilt = SessionBatchAuthority.model_validate_json(
        authority.model_dump_json(), strict=True
    )
    assert rebuilt == authority
    world.sealer.verify_decision_batch(authority)  # 零写入全量重推导, 不抛即通过
    # regime 经读者面同源: 批内 regime 绑定 = PIT active 记录
    active = RegimeObservationReader(world.regime_rig.repository).active(
        REGIME_EVIDENCE_ID, CUTOFF
    )
    regime_binding = next(
        b for b in authority.bindings if b.issuer_namespace == REGIME_NAMESPACE
    )
    assert regime_binding.artifact_hash == active.record.artifact_hash()


def test_exact_replay_is_idempotent(tmp_path):
    world = build_batch_world(tmp_path)
    publish_regime(world)
    schedule = publish_schedule(world)
    cid = publish_candidate(world, "300001").evidence.evidence_id
    first = world.sealer.seal_decision_batch(
        session=SESSION, cutoff=CUTOFF,
        schedule_evidence_id=schedule.evidence.evidence_id,
        candidate_evidence_ids=(cid,),
    )
    second = world.sealer.seal_decision_batch(
        session=SESSION, cutoff=CUTOFF,
        schedule_evidence_id=schedule.evidence.evidence_id,
        candidate_evidence_ids=(cid,),
    )
    assert second.model_dump_json() == first.model_dump_json()  # 冻结钟 → 同字节


def test_completeness_violation_for_undeclared_selected(tmp_path):
    world = build_batch_world(tmp_path)
    publish_regime(world)
    schedule = publish_schedule(world)
    declared = publish_candidate(world, "300001")
    publish_candidate(world, "300002")  # 未声明
    with pytest.raises(SessionBatchError) as ei:
        world.sealer.seal_decision_batch(
            session=SESSION, cutoff=CUTOFF,
            schedule_evidence_id=schedule.evidence.evidence_id,
            candidate_evidence_ids=(declared.evidence.evidence_id,),
        )
    assert ei.value.code == "batch_completeness_violation"


def test_evidence_published_after_cutoff_is_out_of_batch(tmp_path):
    world = build_batch_world(tmp_path)
    publish_regime(world)
    schedule = publish_schedule(world)
    publish_candidate(world, "300001")
    # cutoff 后发布 (推进仓库时钟越过 cutoff): 批外不可见 — 不声明也能封存
    world.advance_clock(datetime(2026, 8, 6, 13, 0, tzinfo=UTC))
    publish_candidate(world, "300002")
    authority = world.sealer.seal_decision_batch(
        session=SESSION, cutoff=CUTOFF,
        schedule_evidence_id=schedule.evidence.evidence_id,
        candidate_evidence_ids=("btst:snap-1:300001:btst_breakout:selected",),
    )
    assert len(authority.bindings) == 3  # 迟到候选不在批内 (PIT)
    # 但把迟到候选声明进去则失败: cutoff 前未提交
    with pytest.raises(Exception):
        world.sealer.seal_decision_batch(
            session=SESSION, cutoff=CUTOFF - timedelta(hours=1),
            schedule_evidence_id=schedule.evidence.evidence_id,
            candidate_evidence_ids=("btst:snap-1:300002:btst_breakout:selected",),
        )


def test_declared_candidate_of_other_session_rejected(tmp_path):
    world = build_batch_world(tmp_path)
    publish_regime(world)
    schedule = publish_schedule(world)
    publish_candidate(
        world, "300001", session=SESSION - timedelta(days=1), snapshot_id="snap-0"
    )
    with pytest.raises(SessionBatchError) as ei:
        world.sealer.seal_decision_batch(
            session=SESSION, cutoff=CUTOFF,
            schedule_evidence_id=schedule.evidence.evidence_id,
            candidate_evidence_ids=("btst:snap-0:300001:btst_breakout:selected",),
        )
    assert ei.value.code == "candidate_session_mismatch"


def test_divergent_reseal_conflicts(tmp_path):
    world = build_batch_world(tmp_path)
    publish_regime(world)
    schedule = publish_schedule(world)
    first_id = publish_candidate(world, "300001").evidence.evidence_id
    world.sealer.seal_decision_batch(
        session=SESSION, cutoff=CUTOFF,
        schedule_evidence_id=schedule.evidence.evidence_id,
        candidate_evidence_ids=(first_id,),
    )
    second_id = publish_candidate(world, "300002").evidence.evidence_id
    with pytest.raises(SessionBatchError) as ei:
        world.sealer.seal_decision_batch(
            session=SESSION, cutoff=CUTOFF,
            schedule_evidence_id=schedule.evidence.evidence_id,
            candidate_evidence_ids=(first_id, second_id),
        )
    assert ei.value.code == "batch_seal_conflict"


def test_authority_model_is_self_verifying(tmp_path):
    world = build_batch_world(tmp_path)
    publish_regime(world)
    publish_schedule(world)
    authority = _seal(world)
    tampered = authority.model_dump_json().replace(
        authority.bindings[0].artifact_hash, "f" * 64
    )
    with pytest.raises(ValidationError):
        SessionBatchAuthority.model_validate_json(tampered, strict=True)


def test_verify_detects_store_drift(tmp_path):
    world = build_batch_world(tmp_path)
    publish_regime(world)
    publish_schedule(world)
    publish_candidate(world, "300001")
    authority = _seal(world, ("btst:snap-1:300001:btst_breakout:selected",))
    # 封存后又出现同会话 SELECTED (完整批外新证据) → verify 重推导即冲突
    publish_candidate(world, "300002")
    with pytest.raises(SessionBatchError) as ei:
        world.sealer.verify_decision_batch(authority)
    assert ei.value.code == "batch_completeness_violation"


def test_undeclared_non_selected_signal_is_not_a_completeness_violation(tmp_path):
    """CANDIDATE 阶段 (非 SELECTED) 的 signal 证据枚举到但跳过 — 批外不冲突。"""
    world = build_batch_world(tmp_path)
    publish_regime(world)
    schedule = publish_schedule(world)
    publish_candidate(
        world, "300001", stage=SignalStage.CANDIDATE
    )  # 未声明的 CANDIDATE — 完备性应跳过
    authority = world.sealer.seal_decision_batch(
        session=SESSION, cutoff=CUTOFF,
        schedule_evidence_id=schedule.evidence.evidence_id,
        candidate_evidence_ids=(),
    )
    assert len(authority.bindings) == 2  # regime + schedule, 无候选


def test_completeness_propagates_unexpected_store_errors(tmp_path):
    """完备性遇非"cutoff 前未提交"的仓库错误必须 propagate (P2-1 宽吞修复)。"""
    world = build_batch_world(tmp_path)
    publish_regime(world)
    schedule = publish_schedule(world)

    from src.screening.offensive.v3.evidence.repository import EvidenceStoreError

    class _ExplodingRepo:
        def active_revision(self, evidence_id, cutoff):
            raise EvidenceStoreError("active_record_missing", "boom")

        def commit_sequence(self):
            return 1

        def evidence_ids_by_kind(self, evidence_kind):
            return ("btst:snap-1:300001:btst_breakout:selected",)

    sealer = SessionBatchSealer(
        database_path=str(tmp_path / "seal.sqlite3"),
        repositories={
            REGIME_NAMESPACE: world.regime_rig.repository,
            SCHEDULE_NAMESPACE: world.schedule_rig.repository,
            BTST_NAMESPACE: _ExplodingRepo(),
        },
        clock=lambda: PUBLISH_AT,
    )
    with pytest.raises(EvidenceStoreError) as ei:
        sealer.seal_decision_batch(
            session=SESSION, cutoff=CUTOFF,
            schedule_evidence_id=schedule.evidence.evidence_id,
            candidate_evidence_ids=(),
        )
    assert ei.value.code == "active_record_missing"


def test_sealed_batch_reader_round_trips(tmp_path):
    """sealed_batch 读面: 读回 == 封存 authority; 未知会话类型化拒绝。"""
    world = build_batch_world(tmp_path)
    publish_regime(world)
    schedule = publish_schedule(world)
    candidate = publish_candidate(world, "300001")
    authority = world.sealer.seal_decision_batch(
        session=SESSION, cutoff=CUTOFF,
        schedule_evidence_id=schedule.evidence.evidence_id,
        candidate_evidence_ids=(candidate.evidence.evidence_id,),
    )
    assert world.sealer.sealed_batch(SESSION) == authority
    with pytest.raises(SessionBatchError) as ei:
        world.sealer.sealed_batch(SESSION + timedelta(days=1))
    assert ei.value.code == "batch_seal_unknown"


def test_schedule_completeness_violation_for_second_same_session_schedule(tmp_path):
    """v2: 同会话第二条排程 (不同切片, cutoff 前提交) 存在 → seal 拒绝。

    v1 登记缺口: worker 可在同会话多条排程间选择性声明, merkle 根绑定的
    是声明集而非该会话排程真相 — 与候选完备性不对称。
    """
    world = build_batch_world(tmp_path)
    publish_regime(world)
    declared = publish_schedule(world)  # 窗口 [s+1 .. s+15] 取前 10
    second = publish_schedule(world, day_offset=2)  # 窗口 [s+2 .. s+16], 同 session
    assert second.evidence.evidence_id != declared.evidence.evidence_id
    with pytest.raises(SessionBatchError) as ei:
        world.sealer.seal_decision_batch(
            session=SESSION, cutoff=CUTOFF,
            schedule_evidence_id=declared.evidence.evidence_id,
            candidate_evidence_ids=(),
        )
    assert ei.value.code == "schedule_completeness_violation"
    assert ei.value.details["evidence_id"] == second.evidence.evidence_id


def test_schedule_of_other_session_is_not_a_completeness_violation(tmp_path):
    """v2: 另一会话的排程证据同库共存 → 不冲突 (完备性只对本会话)。"""
    world = build_batch_world(tmp_path)
    publish_regime(world)
    schedule = publish_schedule(world)
    publish_schedule(world, session=SESSION + timedelta(days=1))
    authority = world.sealer.seal_decision_batch(
        session=SESSION, cutoff=CUTOFF,
        schedule_evidence_id=schedule.evidence.evidence_id,
        candidate_evidence_ids=(),
    )
    assert len(authority.bindings) == 2  # regime + 本会话排程


def test_second_schedule_published_after_cutoff_is_out_of_batch(tmp_path):
    """v2: cutoff 后追加的同会话排程 → PIT 批外, 不构成冲突。"""
    world = build_batch_world(tmp_path)
    publish_regime(world)
    schedule = publish_schedule(world)
    world.advance_clock(datetime(2026, 8, 6, 13, 0, tzinfo=UTC))  # 越过 cutoff
    publish_schedule(world, day_offset=2)  # cutoff 后提交 → 批外不可见
    authority = world.sealer.seal_decision_batch(
        session=SESSION, cutoff=CUTOFF,
        schedule_evidence_id=schedule.evidence.evidence_id,
        candidate_evidence_ids=(),
    )
    assert len(authority.bindings) == 2


def test_verify_detects_late_second_same_session_schedule(tmp_path):
    """v2 verify 面: 封存后 cutoff 前窗口内出现同会话第二条排程 → 重推导拒绝。"""
    world = build_batch_world(tmp_path)
    publish_regime(world)
    schedule = publish_schedule(world)
    authority = world.sealer.seal_decision_batch(
        session=SESSION, cutoff=CUTOFF,
        schedule_evidence_id=schedule.evidence.evidence_id,
        candidate_evidence_ids=(),
    )
    # 11:00 仍早于 cutoff 12:00 → cutoff 前可见的第二条同会话排程
    world.advance_clock(datetime(2026, 8, 6, 11, 0, tzinfo=UTC))
    publish_schedule(world, day_offset=2)
    with pytest.raises(SessionBatchError) as ei:
        world.sealer.verify_decision_batch(authority)
    assert ei.value.code == "schedule_completeness_violation"


def test_declared_schedule_of_other_session_rejected(tmp_path):
    """Op2 P1: worker 声明另一会话的排程 → seal 拒绝 (镜像 candidate_session_mismatch)。

    PoC 实锤的洞: 错位排程使 T+1..T+10 执行窗口整体错位, v1/v2 实现均放行。
    """
    world = build_batch_world(tmp_path)
    publish_regime(world)
    other = publish_schedule(world, session=SESSION + timedelta(days=7))
    with pytest.raises(SessionBatchError) as ei:
        world.sealer.seal_decision_batch(
            session=SESSION, cutoff=CUTOFF,
            schedule_evidence_id=other.evidence.evidence_id,
            candidate_evidence_ids=(),
        )
    assert ei.value.code == "schedule_session_mismatch"
    assert ei.value.details["schedule_session"] == (
        SESSION + timedelta(days=7)
    ).isoformat()


def test_verify_rejects_divergent_schedule_binding(tmp_path):
    """Op2 verify 面: merkle 自洽但排程 binding 错位会话的 authority → 重推导拒绝。"""
    world = build_batch_world(tmp_path)
    publish_regime(world)
    own = publish_schedule(world)
    other = publish_schedule(world, session=SESSION + timedelta(days=7))
    # 手工构造自洽 authority (merkle 根对 bindings 复算通过), 但排程成员是错位会话的
    other_binding_record = world.schedule_rig.repository.active_revision(
        other.evidence.evidence_id, CUTOFF
    )
    regime_binding = next(
        b for b in _seal(world).bindings if b.issuer_namespace == REGIME_NAMESPACE
    )  # 仅取 regime 成员做底 — seal 本身用的是 own 排程 (正常路径先封存)
    from src.screening.offensive.v3.evidence.session_batch import BatchBinding
    schedule_binding = BatchBinding(
        issuer_namespace=SCHEDULE_NAMESPACE,
        evidence_id=other.evidence.evidence_id,
        artifact_hash=other_binding_record.artifact_hash(),
    )
    divergent = SessionBatchAuthority(
        session=SESSION,
        rule_version="btst-decision.v2",
        trusted_evidence_cutoff=CUTOFF,
        bindings=tuple(sorted(
            (regime_binding, schedule_binding),
            key=lambda b: (b.issuer_namespace, b.evidence_id),
        )),
        evidence_set_merkle_root=evidence_set_merkle_root(
            (
                (regime_binding.evidence_id, regime_binding.artifact_hash),
                (other.evidence.evidence_id, other_binding_record.artifact_hash()),
            )
        ),
        commit_sequence_watermark=world.schedule_rig.repository.commit_sequence(),
        sealed_at=own.evidence.observed_at,
    )
    with pytest.raises(SessionBatchError) as ei:
        world.sealer.verify_decision_batch(divergent)
    assert ei.value.code == "schedule_session_mismatch"


def test_declared_non_snapshot_envelope_rejected(tmp_path):
    """Op2: 声明的排程库证据信封不是 SnapshotEvidence → schedule_kind_mismatch。

    信任层通常先挡 (排程链是 SNAPSHOT 能力), 此处用鸭子仓库钉死 sealer
    自身的类型断言不依赖上游信任层兜底。
    """
    world = build_batch_world(tmp_path)
    publish_regime(world)
    schedule = publish_schedule(world)
    real = world.schedule_rig.repository

    class _SignalShapedRepo:
        def active_revision(self, evidence_id, cutoff):
            # 无论 id: 返回真实排程 record 但信封伪装成非 snapshot 类型
            record = real.active_revision(schedule.evidence.evidence_id, cutoff)
            object.__setattr__(
                record, "evidence", publish_candidate(world, "300001").evidence
            )
            object.__setattr__(record, "evidence_id", evidence_id)
            return record

        def evidence_ids_by_kind(self, kind):
            return ()

        def raw_payload(self, content_hash):
            return real.raw_payload(content_hash)

        def commit_sequence(self):
            return real.commit_sequence()

    sealer = SessionBatchSealer(
        database_path=str(world.database_path),
        repositories={
            REGIME_NAMESPACE: world.regime_rig.repository,
            SCHEDULE_NAMESPACE: _SignalShapedRepo(),
            BTST_NAMESPACE: world.btst_repository,
        },
        clock=lambda: PUBLISH_AT,
    )
    with pytest.raises(SessionBatchError) as ei:
        sealer.seal_decision_batch(
            session=SESSION, cutoff=CUTOFF,
            schedule_evidence_id="calendar:sse:whatever:20260806",
            candidate_evidence_ids=(),
        )
    assert ei.value.code == "schedule_kind_mismatch"


def test_completeness_enum_hits_non_snapshot_envelope(tmp_path):
    """Op2: 完备性枚举撞见非 SnapshotEvidence 信封 → schedule_namespace_polluted。"""
    world = build_batch_world(tmp_path)
    publish_regime(world)
    schedule = publish_schedule(world)
    real = world.schedule_rig.repository
    polluted_id = "calendar:sse:polluted:20260806"

    class _PollutedRepo:
        def active_revision(self, evidence_id, cutoff):
            if evidence_id == polluted_id:
                record = real.active_revision(
                    schedule.evidence.evidence_id, cutoff
                )
                object.__setattr__(
                    record, "evidence", publish_candidate(world, "300001").evidence
                )
                object.__setattr__(record, "evidence_id", polluted_id)
                return record
            return real.active_revision(evidence_id, cutoff)

        def evidence_ids_by_kind(self, kind):
            return (schedule.evidence.evidence_id, polluted_id)

        def raw_payload(self, content_hash):
            return real.raw_payload(content_hash)

        def commit_sequence(self):
            return real.commit_sequence()

    sealer = SessionBatchSealer(
        database_path=str(world.database_path),
        repositories={
            REGIME_NAMESPACE: world.regime_rig.repository,
            SCHEDULE_NAMESPACE: _PollutedRepo(),
            BTST_NAMESPACE: world.btst_repository,
        },
        clock=lambda: PUBLISH_AT,
    )
    with pytest.raises(SessionBatchError) as ei:
        sealer.seal_decision_batch(
            session=SESSION, cutoff=CUTOFF,
            schedule_evidence_id=schedule.evidence.evidence_id,
            candidate_evidence_ids=(),
        )
    assert ei.value.code == "schedule_namespace_polluted"


def test_declared_schedule_blob_decode_failure_is_fail_closed(tmp_path):
    """Op2: 声明的排程证据 blob 解不出 FrozenTradingSessionSchedule → fail-closed。"""
    world = build_batch_world(tmp_path)
    publish_regime(world)
    real = world.schedule_rig.repository
    # 在排程库发布一个信封合法但 blob 是 regime observation 字节的"排程"
    observation_bytes = b'{"not":"a schedule"}'
    blob_hash = real.persist_payload(observation_bytes)
    now = world.now()
    envelope = SnapshotEvidence(
        evidence_id="calendar:sse:fakedecode:20260806",
        subject_scope=EvidenceScope.GLOBAL,
        subject_producer=world.schedule_rig.repository.issuer_namespace,
        family_id=None,
        strategy_semver="1.0.0",
        behavior_fingerprint="d" * 64,
        policy_epoch=1,
        execution_version="t1-open-t10-open.v1",
        cost_version="cn-a-share-costs.v1",
        effective_at=now,
        provider_published_at=now,
        observed_at=now,
        available_at=now,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        source_authority="exchange-calendar.publisher",
        payload_content_hash=blob_hash,
        schema_major=SUPPORTED_SCHEMA_MAJOR,
        evidence_kind="snapshot",
    )
    envelope_bytes = envelope.model_dump_json().encode("utf-8")
    real.publish(
        world.schedule_rig.signer(envelope_bytes), envelope_bytes
    )
    with pytest.raises(SessionBatchError) as ei:
        world.sealer.seal_decision_batch(
            session=SESSION, cutoff=CUTOFF,
            schedule_evidence_id=envelope.evidence_id,
            candidate_evidence_ids=(),
        )
    assert ei.value.code == "schedule_decode_failed"
