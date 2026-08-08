"""Plan 05 Task 2 (RED): MarketPublisherService 能力矩阵 + 快照发布行为。

覆盖 Step 1 能力矩阵(import 边界、无 gateway/capital 方法、kind 隔离、
signer 私有)与 Step 2 Publisher 行为(PIT cutoff、legal empty snapshot
supersede stale、stale fallback、future row、raw payload retention、
v2 readiness adaptation、Evidence Store 控制的 ingest stamps)。

本文件引用尚未实现的服务骨架(方法体一律 raise NotImplementedError);
当前应整体 RED, 由主代理随后实现 GREEN。
"""

from __future__ import annotations

import hashlib
from base64 import b64encode
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from src.screening.offensive.v3 import trust
from src.screening.offensive.v3.contracts import (
    canonical_json_bytes,
    ExecutionMode,
    SUPPORTED_SCHEMA_MAJOR,
)
from src.screening.offensive.v3.contracts.base import (
    EvidenceScope,
    SignalStage,
)
from src.screening.offensive.v3.contracts.evidence import (
    EvidenceRecord,
    SignalEvidence,
    SnapshotEvidence,
)
from src.screening.offensive.v3.contracts.governance import TrustBundle
from src.screening.offensive.v3.evidence.blob_store import BlobStore
from src.screening.offensive.v3.evidence.repository import (
    EvidenceRepository,
    EvidenceStoreError,
)
from src.screening.offensive.v3.services import market_publisher as mp_module
from src.screening.offensive.v3.services.market_publisher import (
    MarketPublisherService,
    NOT_A_SNAPSHOT_ERROR_CODE,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)
OBSERVED = NOW - timedelta(hours=1)
AVAILABLE = NOW + timedelta(hours=1)
HASH = "e" * 64
NAMESPACE = "evidence.market.test"

# gateway/authority.py + gateway/decisions.py 的公开方法名: 本服务一律不得暴露
GATEWAY_METHODS = (
    "activate_trust_bundle",
    "activate_policy_and_envelope",
    "replace_envelope",
    "raise_entry_fence",
    "acknowledge_fence",
    "active_state",
    "publish_entry",
    "issue_permit",
    "make_outbox_durable",
)
# capital/repository.py 的公开方法名: 本服务一律不得暴露
CAPITAL_METHODS = (
    "run_append",
    "append_atomic",
    "record_fill_revision",
    "record_fee_revision",
    "confirm_observed_nav",
)


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now_value = start

    def __call__(self) -> datetime:
        return self.now_value

    def advance(self, **kwargs: float) -> None:
        self.now_value += timedelta(**kwargs)


def _public_key_b64(private_key: Ed25519PrivateKey) -> str:
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return b64encode(public_bytes).decode("ascii")


def _capability(**overrides):
    values = {
        "artifact": trust.ArtifactKind.SNAPSHOT,
        "namespace": NAMESPACE,
        "mode": ExecutionMode.RESEARCH_RECONSTRUCTION,
        "schema_major": SUPPORTED_SCHEMA_MAJOR,
        "capability_version": "evidence-publisher.v1",
        "scope": "evidence:market.test",
        "valid_from": NOW - timedelta(days=1),
        "valid_until": NOW + timedelta(days=1),
        "revoked_at": None,
    }
    values.update(overrides)
    return trust.Capability(**values)


def _issuer(private_key, *capabilities, issuer_id, key_id, kind):
    return trust.TrustedIssuer(
        issuer_id=issuer_id,
        key_id=key_id,
        issuer_kind=kind,
        public_key=_public_key_b64(private_key),
        valid_from=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=1),
        revoked_at=None,
        capabilities=tuple(capabilities),
    )


def _protected_input(*, issuer_id, key_id, capability, payload, payload_hash):
    return canonical_json_bytes(
        {
            "artifact": capability.artifact,
            "capability_scope": capability.scope,
            "capability_version": capability.capability_version,
            "issuer_id": issuer_id,
            "key_id": key_id,
            "mode": capability.mode,
            "namespace": capability.namespace,
            "payload": b64encode(payload).decode("ascii"),
            "payload_hash": payload_hash,
            "schema_major": capability.schema_major,
        }
    )


def _signed(private_key, capability, *, issuer_id, key_id, payload):
    digest = hashlib.sha256(payload).hexdigest()
    protected = _protected_input(
        issuer_id=issuer_id,
        key_id=key_id,
        capability=capability,
        payload=payload,
        payload_hash=digest,
    )
    signature = private_key.sign(protected)
    return trust.SignedEnvelope(
        issuer_id=issuer_id,
        key_id=key_id,
        schema_major=capability.schema_major,
        artifact=capability.artifact,
        namespace=capability.namespace,
        mode=capability.mode,
        capability_version=capability.capability_version,
        capability_scope=capability.scope,
        payload_hash=digest,
        payload=payload,
        signature=b64encode(signature).decode("ascii"),
    )


def _root_context(registry):
    root_key = Ed25519PrivateKey.generate()
    root_public = _public_key_b64(root_key)
    root_hash = hashlib.sha256(
        root_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).hexdigest()
    anchor = trust.RootTrustAnchor(
        root_hash=root_hash,
        root_key_id="offline-root-1",
        public_key=root_public,
        valid_from=NOW - timedelta(days=30),
        valid_until=NOW + timedelta(days=30),
        revoked_at=None,
    )
    bundle = TrustBundle(
        registry_epoch=1,
        predecessor_bundle_hash="0" * 64,
        root_hash=root_hash,
        root_key_id=anchor.root_key_id,
        trusted_issuer_registry_hash=registry.content_hash(),
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(days=1),
        revoked_at=None,
        issuer_id="offline-governance-root",
        issuer_capability="root.trust.bundle.v1",
        schema_major=2,
    )
    signature = b64encode(
        root_key.sign(trust.trust_bundle_signature_preimage(bundle, registry))
    ).decode("ascii")
    signed_bundle = trust.SignedTrustBundle(
        bundle=bundle, registry=registry, signature=signature
    )
    verifier = trust.TrustBundleVerifier((anchor,))
    delegate = trust.CapabilityVerifier(verifier, (signed_bundle,))
    head = trust.CurrentTrustHeadWitness(
        active_trust_bundle_hash=bundle.artifact_hash(),
        registry_epoch=bundle.registry_epoch,
        head_version=bundle.registry_epoch,
        store_version=1,
        observed_at=NOW,
    )

    class _HeadProvider:
        def current_trust_head(self, trusted_at):
            return head

    return delegate, _HeadProvider()


class _World:
    """Trusted registry + raw evidence store + the service under test."""

    def __init__(self, tmp_path: Path) -> None:
        self.clock = _Clock(NOW)
        self.publisher_key = Ed25519PrivateKey.generate()
        self.snapshot_capability = _capability(
            artifact=trust.ArtifactKind.SNAPSHOT
        )
        registry = trust.TrustedRegistry(
            issuers=(
                _issuer(
                    self.publisher_key,
                    self.snapshot_capability,
                    issuer_id="market.publisher",
                    key_id="publisher-key-1",
                    kind=trust.IssuerKind.MARKET_PUBLISHER,
                ),
            )
        )
        verifier, head_provider = _root_context(registry)
        self.blob_store = BlobStore(tmp_path / "blobs")
        self.database_path = str(tmp_path / "evidence.sqlite3")
        # 底层 store 用于构造 revision 时间线(prepare/activate);
        # 服务查询面只暴露 publish_snapshot/active_snapshot/raw_payload。
        self.repository = EvidenceRepository(
            database_path=self.database_path,
            blob_store=self.blob_store,
            verifier=verifier,
            trust_head_provider=head_provider,
            issuer_namespace=NAMESPACE,
            clock=self.clock,
        )
        self.service = MarketPublisherService(
            database_path=self.database_path,
            blob_store=self.blob_store,
            verifier=verifier,
            trust_head_provider=head_provider,
            issuer_namespace=NAMESPACE,
            clock=self.clock,
            signer=self._sign,
        )
        self.signed_payloads: list[bytes] = []

    def _sign(self, payload: bytes):
        self.signed_payloads.append(payload)
        return _signed(
            self.publisher_key,
            self.snapshot_capability,
            issuer_id="market.publisher",
            key_id="publisher-key-1",
            payload=payload,
        )

    def snapshot_envelope(self, evidence_id="snap-1", **overrides):
        values = {
            "evidence_id": evidence_id,
            "subject_scope": EvidenceScope.GLOBAL,
            "subject_producer": "market.test",
            "family_id": None,
            "strategy_semver": "3.0.0",
            "behavior_fingerprint": HASH,
            "policy_epoch": 1,
            "execution_version": "readiness.v2",
            "cost_version": "cn-a-share-costs.v1",
            "effective_at": OBSERVED,
            "provider_published_at": OBSERVED,
            "observed_at": OBSERVED,
            "available_at": AVAILABLE,
            "mode": ExecutionMode.RESEARCH_RECONSTRUCTION,
            "source_authority": "market.publisher",
            "payload_content_hash": HASH,
            "schema_major": SUPPORTED_SCHEMA_MAJOR,
            "evidence_kind": "snapshot",
        }
        values.update(overrides)
        return SnapshotEvidence(**values)

    def signal_envelope(self, evidence_id="sig-1", **overrides):
        values = {
            "evidence_id": evidence_id,
            "subject_scope": EvidenceScope.STRATEGY_LINEAGE,
            "subject_producer": "btst",
            "family_id": "btst.limit-up-breakout",
            "strategy_semver": "3.0.0",
            "behavior_fingerprint": HASH,
            "policy_epoch": 1,
            "execution_version": "t1-open-t10-open.v1",
            "cost_version": "cn-a-share-costs.v1",
            "effective_at": OBSERVED,
            "provider_published_at": OBSERVED,
            "observed_at": OBSERVED,
            "available_at": AVAILABLE,
            "mode": ExecutionMode.RESEARCH_RECONSTRUCTION,
            "source_authority": "signal.producer",
            "payload_content_hash": HASH,
            "schema_major": SUPPORTED_SCHEMA_MAJOR,
            "evidence_kind": "signal",
            "stage": SignalStage.SELECTED,
        }
        values.update(overrides)
        return SignalEvidence(**values)


@pytest.fixture()
def world(tmp_path: Path) -> _World:
    return _World(tmp_path)


def _forbidden_import_segments(source: str) -> list[str]:
    """顶层 import 行中命中的禁止模块段 (capital/gateway/execution)。

    只检查 column-0 的 import/from 行; 参数名(如 capital_engine)与字符串
    内容不参与检查, 避免误伤。
    """
    violations: list[str] = []
    for line in source.splitlines():
        if not line or line[0].isspace():
            continue
        if line.startswith("import "):
            module = (
                line[len("import "):].split(" as ")[0].split(",")[0].strip()
            )
        elif line.startswith("from "):
            module = line[len("from "):].split(" import ")[0].strip()
        else:
            continue
        for segment in module.split("."):
            if segment in {"capital", "gateway", "execution"}:
                violations.append(line)
                break
    return violations


# --------------------------------------------------------------------------
# Step 1: 能力矩阵
# --------------------------------------------------------------------------


def test_import_boundaries_no_capital_gateway_execution(world: _World) -> None:
    source = Path(mp_module.__file__).read_text(encoding="utf-8")
    assert _forbidden_import_segments(source) == []


def test_api_surface_excludes_gateway_capital_and_store_mutations(
    world: _World,
) -> None:
    service = world.service
    # 服务应暴露的恰好是三个方法
    assert callable(service.publish_snapshot)
    assert callable(service.active_snapshot)
    assert callable(service.raw_payload)
    # gateway 状态激活/入口发布/permits 一律不得出现
    for name in GATEWAY_METHODS:
        assert not hasattr(service, name), name
    # capital 写入/读面一律不得出现
    for name in CAPITAL_METHODS:
        assert not hasattr(service, name), name
    # 底层 store 的裸发布/修订面不得被服务暴露
    for name in (
        "publish",
        "prepare_revision",
        "activate_revision",
        "persist_payload",
        "payload_bytes",
        "outcome",
        "get",
        "commit_sequence",
        "dependency_root",
    ):
        assert not hasattr(service, name), name


def test_kind_isolation_rejects_non_snapshot(world: _World) -> None:
    signal = world.signal_envelope()
    with pytest.raises(EvidenceStoreError) as excinfo:
        world.service.publish_snapshot(signal)
    assert excinfo.value.code == NOT_A_SNAPSHOT_ERROR_CODE
    # 被拒绝的 payload 不得进入 store
    with pytest.raises(EvidenceStoreError):
        world.repository.active_revision("sig-1", NOW)


def test_signer_is_private_no_public_accessor(world: _World) -> None:
    service = world.service
    # 签名材料只作为私有字段存在
    assert hasattr(service, "_signer")
    for name in ("signer", "get_signer", "sign", "signing_key"):
        assert not hasattr(service, name), name


# --------------------------------------------------------------------------
# Step 2: Publisher 行为
# --------------------------------------------------------------------------


def test_publish_commits_snapshot_with_store_owned_ingest_stamp(
    world: _World,
) -> None:
    envelope = world.snapshot_envelope()
    world.clock.advance(seconds=30)
    record = world.service.publish_snapshot(envelope)

    assert isinstance(record, EvidenceRecord)
    assert isinstance(record.evidence, SnapshotEvidence)
    assert record.evidence == envelope
    assert record.revision == 1
    assert record.active_revision == 1
    assert record.is_active
    assert record.supersedes_revision is None
    assert record.commit_sequence == 1
    # The store owns ingested_at: it is the trusted clock instant at publish,
    # not any producer-supplied time.
    assert record.ingested_at == NOW + timedelta(seconds=30)
    assert record.evidence.observed_at <= record.ingested_at
    assert record.ingested_at <= record.evidence.available_at


def test_raw_payload_retention_after_publish(world: _World) -> None:
    envelope = world.snapshot_envelope()
    record = world.service.publish_snapshot(envelope)
    payload = envelope.model_dump_json().encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    assert world.service.raw_payload(digest) == payload
    assert record.evidence.payload_content_hash


def test_pit_cutoff_projection_and_stale_fallback(world: _World) -> None:
    # revision 1 在 t0 发布
    envelope = world.snapshot_envelope(payload_content_hash="a" * 64)
    world.service.publish_snapshot(envelope)
    publish_time = world.clock.now_value
    # 刚发布的 instant 不参与严格 cutoff (activated_at < cutoff)
    with pytest.raises(EvidenceStoreError) as excinfo:
        world.service.active_snapshot("snap-1", publish_time)
    assert excinfo.value.code == "evidence_not_committed_before_cutoff"

    # revision 2 经底层 store prepare+activate (服务面无法表达的修订时间线)
    world.clock.advance(minutes=10)
    revised = world.snapshot_envelope(
        payload_content_hash="b" * 64,
        observed_at=world.clock.now_value - timedelta(minutes=1),
        available_at=world.clock.now_value + timedelta(hours=1),
        effective_at=world.clock.now_value - timedelta(minutes=1),
        provider_published_at=world.clock.now_value - timedelta(minutes=1),
    )
    payload_rev = revised.model_dump_json().encode("utf-8")
    signed_rev = _signed(
        world.publisher_key,
        world.snapshot_capability,
        issuer_id="market.publisher",
        key_id="publisher-key-1",
        payload=payload_rev,
    )
    world.repository.prepare_revision(signed_rev, payload_rev)
    world.clock.advance(minutes=5)
    world.repository.activate_revision("snap-1", 2)
    activation_time = world.clock.now_value

    # cutoff 在 activation 之前 → stale fallback 返回旧 active (revision 1)
    before = world.service.active_snapshot("snap-1", activation_time)
    assert before.revision == 1
    assert before.is_active
    # future 数据不参与: 在首个 publish 之前的 cutoff 看不到任何数据
    with pytest.raises(EvidenceStoreError) as excinfo:
        world.service.active_snapshot(
            "snap-1", publish_time - timedelta(minutes=1)
        )
    assert excinfo.value.code == "evidence_not_committed_before_cutoff"
    # cutoff 在 activation 之后 → 新 active (revision 2)
    world.clock.advance(minutes=1)
    after = world.service.active_snapshot("snap-1", world.clock.now_value)
    assert after.revision == 2
    assert after.ingested_at < activation_time  # store-owned ingest time


def test_future_row_not_visible_at_earlier_cutoff(world: _World) -> None:
    world.service.publish_snapshot(world.snapshot_envelope())
    world.clock.advance(hours=2)
    # 第二个 snapshot 的时间戳必须跟踪推进后的 clock, 否则 store 的 PIT
    # 时间线契约会拒绝 (ingested_at 必须落在 observed/available 窗口内)
    future_time = world.clock.now_value
    world.service.publish_snapshot(
        world.snapshot_envelope(
            evidence_id="snap-future",
            observed_at=future_time - timedelta(minutes=1),
            available_at=future_time + timedelta(hours=1),
            effective_at=future_time - timedelta(minutes=1),
            provider_published_at=future_time - timedelta(minutes=1),
        )
    )
    # 一个早于 future row commit 的 cutoff 不得看到它
    with pytest.raises(EvidenceStoreError) as excinfo:
        world.service.active_snapshot(
            "snap-future", NOW + timedelta(hours=1)
        )
    assert excinfo.value.code == "evidence_not_committed_before_cutoff"
    world.clock.advance(minutes=1)
    active = world.service.active_snapshot(
        "snap-future", world.clock.now_value
    )
    assert active.revision == 1
    assert active.evidence.evidence_id == "snap-future"


def test_legal_empty_snapshot_supersedes_stale(world: _World) -> None:
    stale = world.snapshot_envelope(payload_content_hash="d" * 64)
    world.service.publish_snapshot(stale)

    world.clock.advance(minutes=3)
    # Today's authoritative EMPTY observation supersedes the stale one.
    empty_envelope = world.snapshot_envelope(
        evidence_id="snap-empty",
        payload_content_hash="f" * 64,
        observed_at=world.clock.now_value - timedelta(seconds=10),
        available_at=world.clock.now_value + timedelta(hours=1),
        effective_at=world.clock.now_value - timedelta(seconds=10),
        provider_published_at=world.clock.now_value - timedelta(seconds=10),
    )
    record = world.service.publish_snapshot(empty_envelope)
    assert record.is_active
    world.clock.advance(minutes=1)
    active = world.service.active_snapshot(
        "snap-empty", world.clock.now_value
    )
    assert active.evidence == empty_envelope
    assert active.revision == 1


def test_v2_readiness_execution_version_publishes(world: _World) -> None:
    envelope = world.snapshot_envelope(execution_version="readiness.v2")
    record = world.service.publish_snapshot(envelope)
    assert record.evidence.execution_version == "readiness.v2"
    assert record.is_active


def test_signer_receives_exact_snapshot_payload(world: _World) -> None:
    # 服务必须用注入的 signer 签名恰好一份 payload, 内容与快照 JSON 一致
    envelope = world.snapshot_envelope()
    record = world.service.publish_snapshot(envelope)
    assert len(world.signed_payloads) == 1
    assert world.signed_payloads[0] == envelope.model_dump_json().encode(
        "utf-8"
    )
    # 签名信封声明 SNAPSHOT artifact 与本服务 namespace → store 验证通过
    assert record.commit_sequence == 1
