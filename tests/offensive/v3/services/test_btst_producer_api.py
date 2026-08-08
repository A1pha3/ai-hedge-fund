"""Plan 05 Task 5 (RED): BtstProducerApi 信号漏斗 + 无 runtime gate。

覆盖 Step 1 契约 (BTST 侧):
1. full funnel — 2 个可扫候选 → 每个候选 CANDIDATE → SELECTED 两枚信号,
   store 可读回 (active_signal)。
2. behavior fingerprint — 信封行为指纹 == 注入值; 不同注入值 → 不同信封。
3. no cache reopen — monkeypatch pandas.read_csv 抛错, produce 不触碰文件系统。
4. no authorization field — 信封无 authorization 字段 / model_dump 无该 key。
5. OB disabled — oversold_bounce 未启用 → 产出信号中无该 setup。
6. correction provenance — 同 evidence_id 新 revision (prepare+activate)
   → active 指向新 revision, 旧 revision 仍可读 (append-only, 不 rewrite)。
9. btst no gate — 不注入 runtime_mode_provider 也能 publish
   (btst_canary 是合法 mode, BTST 无 shadow gate)。

namespace 分离 (auto vs btst) 的跨服务测试在
``test_auto_producer_api.py::test_auto_and_btst_evidence_id_spaces_are_disjoint``。

本文件引用尚未实现的服务骨架 (方法体一律 raise NotImplementedError);
当前应整体 RED, 由主代理随后实现 GREEN。
"""

from __future__ import annotations

import hashlib
import json
from base64 import b64encode
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from unittest.mock import Mock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from src.screening.offensive.v3 import trust as v3_trust
from src.screening.offensive.v3.contracts import (
    canonical_json_bytes,
    ExecutionMode,
    SUPPORTED_SCHEMA_MAJOR,
)
from src.screening.offensive.v3.contracts.base import (
    EvidenceScope,
    SignalStage,
)
from src.screening.offensive.v3.contracts.evidence import SignalEvidence
from src.screening.offensive.v3.contracts.governance import TrustBundle
from src.screening.offensive.v3.evidence.blob_store import BlobStore
from src.screening.offensive.v3.evidence.repository import EvidenceRepository
from src.screening.offensive.v3.services.btst_producer_api import BtstProducerApi
from src.screening.offensive.daily_action_readiness import (
    BOARD_RULE_VERSION,
    DAILY_ACTION_READINESS_SCHEMA_VERSION,
    NORMALIZATION_VERSION,
    READINESS_POLICY_VERSION,
    DailyActionReadinessManifest,
    DailyActionTickerReadiness,
    SharedReadinessEvidence,
    SuspensionReadinessEvidence,
    _fingerprint,
)
from src.screening.offensive.daily_action_snapshot import (
    FrozenFlowRow,
    FrozenPriceRow,
    VerifiedDailyActionSnapshot,
)
from src.screening.offensive.readiness_reference import ReferenceProvenance
from src.screening.offensive.setup_data_contracts import (
    SETUP_REQUIREMENTS_VERSION,
    SetupCapability,
)
from src.screening.offensive.setups.base import DetectionResult
from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup
from src.utils.date_utils import SIGNAL_SESSION_POLICY_VERSION

UTC = timezone.utc
# clock 落在 signal_date 次日 09:00 UTC: 信封时间链 (signal_date 15:00 UTC →
# signal_date+1 15:00 UTC) 必须包住发布时刻.
NOW = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)
SIGNAL_DATE = date(2026, 8, 5)
HASH = "e" * 64
CONSUMED_FP = "sha256:" + "a" * 64
SNAPSHOT_ID = "sha256:" + "b" * 64
CONTENT_FP = "sha256:" + "c" * 64
INPUT_FP = "sha256:" + "d" * 64
UNIVERSE_FP = "sha256:" + "f" * 64
SUSPENSION_FP = "sha256:" + "1" * 64
TICKERS = ("300001", "300002")
BTST_NS = "btst"
BTST_FINGERPRINT = "b" * 64


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


def _trust_capability(**overrides):
    values = {
        "artifact": v3_trust.ArtifactKind.SIGNAL,
        "namespace": BTST_NS,
        "mode": ExecutionMode.RESEARCH_RECONSTRUCTION,
        "schema_major": SUPPORTED_SCHEMA_MAJOR,
        "capability_version": "signal-producer.v1",
        "scope": f"evidence:{BTST_NS}",
        "valid_from": NOW - timedelta(days=1),
        "valid_until": NOW + timedelta(days=1),
        "revoked_at": None,
    }
    values.update(overrides)
    return v3_trust.Capability(**values)


def _issuer(private_key, *capabilities, issuer_id, key_id, kind):
    return v3_trust.TrustedIssuer(
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
    return v3_trust.SignedEnvelope(
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
    anchor = v3_trust.RootTrustAnchor(
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
        root_key.sign(v3_trust.trust_bundle_signature_preimage(bundle, registry))
    ).decode("ascii")
    signed_bundle = v3_trust.SignedTrustBundle(
        bundle=bundle, registry=registry, signature=signature
    )
    verifier = v3_trust.TrustBundleVerifier((anchor,))
    delegate = v3_trust.CapabilityVerifier(verifier, (signed_bundle,))
    head = v3_trust.CurrentTrustHeadWitness(
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


# --------------------------------------------------------------------------
# VerifiedDailyActionSnapshot fixture (2 个可扫候选, OB 默认禁用)
# --------------------------------------------------------------------------


def _hit_result(ticker: str) -> DetectionResult:
    return DetectionResult(
        hit=True,
        ticker=ticker,
        trade_date=SIGNAL_DATE.strftime("%Y%m%d"),
        trigger_strength=0.90,
        invalidation_condition="price below trigger close",
        metadata={"range_based_stop_pct": -0.08},
        degraded=False,
        degradation_reason="",
    )


def _capability() -> SetupCapability:
    return SetupCapability(
        enabled=True,
        scannable=True,
        plan_eligible=True,
        degraded=False,
        block_reasons=(),
        warnings=(),
        consumed_fingerprint=CONSUMED_FP,
    )


def _disabled_capability() -> SetupCapability:
    return SetupCapability(
        enabled=False,
        scannable=False,
        plan_eligible=False,
        degraded=False,
        block_reasons=("setup_disabled_by_default",),
        warnings=(),
        consumed_fingerprint=None,
    )


def _shared_evidence() -> SharedReadinessEvidence:
    regime_row = {"trade_date": SIGNAL_DATE.isoformat(), "regime": "normal"}
    industry_by_ticker = {ticker: "software" for ticker in TICKERS}
    industry_day_pct = {ticker: 3.2 for ticker in TICKERS}
    security_status_by_ticker = {ticker: "listed" for ticker in TICKERS}
    security_reference = ReferenceProvenance.create(
        observed_on=SIGNAL_DATE,
        effective_from=SIGNAL_DATE,
        effective_through=SIGNAL_DATE,
        source="tushare.stock_basic",
        version="test-stock-basic-v1",
        content_fingerprint=_fingerprint({"security": TICKERS}),
    )
    sw_reference = ReferenceProvenance.create(
        observed_on=SIGNAL_DATE,
        effective_from=SIGNAL_DATE,
        effective_through=SIGNAL_DATE,
        source="tushare.index_classify+index_member",
        version="test-sw-v1",
        content_fingerprint=_fingerprint({"sw": TICKERS}),
    )
    return SharedReadinessEvidence(
        as_of_date=SIGNAL_DATE,
        regime_row=regime_row,
        industry_by_ticker=industry_by_ticker,
        industry_day_pct=industry_day_pct,
        security_status_by_ticker=security_status_by_ticker,
        regime_fingerprint=_fingerprint(
            {"as_of_date": SIGNAL_DATE.isoformat(), "regime_row": regime_row}
        ),
        industry_fingerprint=_fingerprint(
            {
                "as_of_date": SIGNAL_DATE.isoformat(),
                "industry_by_ticker": industry_by_ticker,
                "industry_day_pct": industry_day_pct,
            }
        ),
        security_fingerprint=_fingerprint(
            {
                "as_of_date": SIGNAL_DATE.isoformat(),
                "security_status_by_ticker": security_status_by_ticker,
            }
        ),
        security_reference=security_reference,
        sw_reference=sw_reference,
        frozen_source_fingerprint=_fingerprint({"frozen": TICKERS}),
        board_rule_version=BOARD_RULE_VERSION,
        normalization_version=NORMALIZATION_VERSION,
        signal_session_policy_version=SIGNAL_SESSION_POLICY_VERSION,
    )


def _manifest() -> DailyActionReadinessManifest:
    return DailyActionReadinessManifest(
        schema_version=DAILY_ACTION_READINESS_SCHEMA_VERSION,
        domain="daily_action",
        run_id="plan05t5",
        trade_date=SIGNAL_DATE,
        created_at="2026-08-05T12:00:00+00:00",
        status="healthy",
        universe_kind="resolved_refresh_universe",
        universe_tickers=TICKERS,
        universe_fingerprint=UNIVERSE_FP,
        input_fingerprint=INPUT_FP,
        suspension_evidence=SuspensionReadinessEvidence(
            "available_empty", (), SUSPENSION_FP
        ),
        ticker_readiness=MappingProxyType(
            {
                ticker: DailyActionTickerReadiness(
                    evidence_status="verified",
                    capabilities=MappingProxyType(
                        {
                            "btst_breakout": _capability(),
                            "oversold_bounce": _disabled_capability(),
                        }
                    ),
                )
                for ticker in TICKERS
            }
        ),
        warnings=(),
        shared_evidence=_shared_evidence(),
        policy_versions=MappingProxyType(
            {
                "readiness_policy": READINESS_POLICY_VERSION,
                "normalization": NORMALIZATION_VERSION,
                "board_rule": BOARD_RULE_VERSION,
                "setup_requirements": SETUP_REQUIREMENTS_VERSION,
                "signal_session_cutoff": SIGNAL_SESSION_POLICY_VERSION,
            }
        ),
        content_fingerprint=CONTENT_FP,
    )


def _prices() -> tuple[FrozenPriceRow, ...]:
    rows: list[FrozenPriceRow] = []
    for index in range(22):
        session = SIGNAL_DATE - timedelta(days=21 - index)
        close = 10.0
        pct = 0.0
        if index == 16:
            close = 10.5
        if index == 21:
            close = 11.0
            pct = 10.0
        rows.append(
            FrozenPriceRow(
                trade_date=session,
                open=close,
                high=close,
                low=close,
                close=close,
                volume=1000000,
                pct_change=pct,
            )
        )
    return tuple(rows)


def _flows() -> tuple[FrozenFlowRow, ...]:
    return tuple(
        FrozenFlowRow(
            trade_date=SIGNAL_DATE - timedelta(days=offset),
            close=11.0,
            pct_change=0.0,
            main_net_inflow=1000000,
        )
        for offset in range(3)
    )


def _snapshot() -> VerifiedDailyActionSnapshot:
    return VerifiedDailyActionSnapshot(
        signal_date=SIGNAL_DATE,
        snapshot_id=SNAPSHOT_ID,
        manifest=_manifest(),
        universe_tickers=TICKERS,
        prices_by_ticker=MappingProxyType(
            {ticker: _prices() for ticker in TICKERS}
        ),
        fund_flow_by_ticker=MappingProxyType(
            {ticker: _flows() for ticker in TICKERS}
        ),
        industry_day_pct_by_ticker=MappingProxyType(
            {ticker: 3.2 for ticker in TICKERS}
        ),
        regime="normal",
        board_rule_version=BOARD_RULE_VERSION,
        normalization_version=NORMALIZATION_VERSION,
        setup_requirements_version=SETUP_REQUIREMENTS_VERSION,
        ticker_blocks=MappingProxyType({}),
        consumed_fingerprint_by_ticker=MappingProxyType(
            {
                ticker: MappingProxyType({"btst_breakout": CONSUMED_FP})
                for ticker in TICKERS
            }
        ),
    )


# --------------------------------------------------------------------------
# World: trusted registry + BtstProducerApi + 裸 store
# --------------------------------------------------------------------------


class _World:
    """信任上下文 + 同一 evidence DB (issuer_namespace="btst") 上的服务与裸仓库."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        btst_fingerprint: str = BTST_FINGERPRINT,
    ) -> None:
        self.clock = _Clock(NOW)
        self.key = Ed25519PrivateKey.generate()
        self.capability = _trust_capability()
        registry = v3_trust.TrustedRegistry(
            issuers=(
                _issuer(
                    self.key,
                    self.capability,
                    issuer_id="btst.producer",
                    key_id="btst-key-1",
                    kind=v3_trust.IssuerKind.SIGNAL_PRODUCER,
                ),
            )
        )
        self.verifier, self.head_provider = _root_context(registry)
        self.blob_store = BlobStore(tmp_path / "blobs")
        self.database_path = str(tmp_path / "evidence.sqlite3")
        # 裸仓库用于构造 correction 时间线 (prepare/activate); 服务查询面
        # 只暴露 produce_and_publish / active_signal。
        self.raw_repository = EvidenceRepository(
            database_path=self.database_path,
            blob_store=self.blob_store,
            verifier=self.verifier,
            trust_head_provider=self.head_provider,
            issuer_namespace=BTST_NS,
            clock=self.clock,
        )
        self.service = BtstProducerApi(
            database_path=self.database_path,
            blob_store=self.blob_store,
            verifier=self.verifier,
            trust_head_provider=self.head_provider,
            clock=self.clock,
            signer=self.sign,
            behavior_fingerprint=btst_fingerprint,
        )
        self.signed_payloads: list[bytes] = []

    def sign(self, payload: bytes):
        self.signed_payloads.append(payload)
        return _signed(
            self.key,
            self.capability,
            issuer_id="btst.producer",
            key_id="btst-key-1",
            payload=payload,
        )

    def signal_envelope(self, evidence_id: str, **overrides):
        values = {
            "evidence_id": evidence_id,
            "subject_scope": EvidenceScope.STRATEGY_LINEAGE,
            "subject_producer": BTST_NS,
            "family_id": f"{BTST_NS}:{SNAPSHOT_ID}",
            "strategy_semver": "0.1.0",
            "behavior_fingerprint": HASH,
            "policy_epoch": 1,
            "execution_version": "btst.funnel.v1",
            "cost_version": "cn-a-share-costs.v1",
            "effective_at": NOW - timedelta(hours=1),
            "provider_published_at": NOW - timedelta(hours=1),
            "observed_at": NOW - timedelta(hours=1),
            "available_at": NOW + timedelta(hours=1),
            "mode": ExecutionMode.RESEARCH_RECONSTRUCTION,
            "source_authority": "btst.producer",
            "payload_content_hash": HASH,
            "schema_major": SUPPORTED_SCHEMA_MAJOR,
            "evidence_kind": "signal",
            "stage": SignalStage.CANDIDATE,
        }
        values.update(overrides)
        return SignalEvidence(**values)


@pytest.fixture()
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _World:
    # scan_from_verified_snapshot 会真实跑 BtstBreakoutSetup.detect;
    # 固定为命中, 使每个 ticker 都产生候选 (2 个可扫候选)。
    monkeypatch.setattr(
        BtstBreakoutSetup,
        "detect",
        lambda self, ticker, trade_date, context: _hit_result(ticker),
    )
    return _World(tmp_path)


# --------------------------------------------------------------------------
# 契约测试
# --------------------------------------------------------------------------


def test_full_funnel_publishes_candidate_and_selected_per_candidate(
    world: _World,
) -> None:
    records = world.service.produce_and_publish(_snapshot())

    assert len(records) == 4  # 2 候选 × (CANDIDATE → SELECTED)
    assert all(r.evidence.evidence_kind == "signal" for r in records)
    assert all(r.evidence.subject_producer == "btst" for r in records)
    assert all(r.evidence.family_id == f"btst:{SNAPSHOT_ID}" for r in records)
    assert all(r.revision == 1 and r.is_active for r in records)
    stages = [r.evidence.stage for r in records]
    assert stages.count(SignalStage.CANDIDATE) == 2
    assert stages.count(SignalStage.SELECTED) == 2

    # store 可读回: 推进 clock 后每个 evidence_id 的 active 信号可用
    world.clock.advance(seconds=1)
    for record in records:
        active = world.service.active_signal(
            record.evidence.evidence_id, cutoff=world.clock.now_value
        )
        assert active is not None
        assert active.evidence.evidence_id == record.evidence.evidence_id
        assert active.evidence.stage == record.evidence.stage


def test_behavior_fingerprint_is_injected_onto_every_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        BtstBreakoutSetup,
        "detect",
        lambda self, ticker, trade_date, context: _hit_result(ticker),
    )
    fingerprint_a = "a" * 64
    fingerprint_b = "b" * 64
    world_a = _World(tmp_path / "fp-a", btst_fingerprint=fingerprint_a)
    world_b = _World(tmp_path / "fp-b", btst_fingerprint=fingerprint_b)

    records_a = world_a.service.produce_and_publish(_snapshot())
    records_b = world_b.service.produce_and_publish(_snapshot())

    assert len(records_a) == 4 and len(records_b) == 4
    assert all(
        r.evidence.behavior_fingerprint == fingerprint_a for r in records_a
    )
    assert all(
        r.evidence.behavior_fingerprint == fingerprint_b for r in records_b
    )
    # 不同注入值 → 信封 (签名 payload) 内容不同
    assert world_a.signed_payloads != world_b.signed_payloads


def test_produce_never_reopens_cache_files(
    world: _World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "pandas.read_csv",
        Mock(side_effect=AssertionError("producer reopened cache file")),
    )

    records = world.service.produce_and_publish(_snapshot())

    assert len(records) == 4


def test_signal_envelopes_carry_no_authorization_field(world: _World) -> None:
    records = world.service.produce_and_publish(_snapshot())
    assert len(records) == 4

    for payload in world.signed_payloads:
        data = json.loads(payload.decode("utf-8"))
        assert "authorization" not in data
        envelope = SignalEvidence.model_validate_json(payload)
        # 模型面也没有 authorization 字段 (extra="forbid" 模型不可能携带)
        assert not hasattr(envelope, "authorization")


def test_oversold_bounce_disabled_produces_no_ob_signals(world: _World) -> None:
    records = world.service.produce_and_publish(_snapshot())

    # manifest 中 oversold_bounce 未启用 → 无 OB 候选, 信号只有 2 候选 × 2 阶段
    assert len(records) == 4
    for record in records:
        assert "oversold_bounce" not in record.evidence.evidence_id
        assert record.evidence.family_id == f"btst:{SNAPSHOT_ID}"


def test_correction_revision_appends_without_rewriting(world: _World) -> None:
    records = world.service.produce_and_publish(_snapshot())
    evidence_id = records[0].evidence.evidence_id

    # 同 evidence_id 的新 revision: 经裸 store prepare + activate (append-only)
    world.clock.advance(minutes=1)
    prepare_time = world.clock.now_value
    revised = world.signal_envelope(
        evidence_id,
        behavior_fingerprint="c" * 64,
        payload_content_hash="d" * 64,
        observed_at=prepare_time - timedelta(minutes=1),
        available_at=prepare_time + timedelta(hours=1),
        effective_at=prepare_time - timedelta(minutes=1),
        provider_published_at=prepare_time - timedelta(minutes=1),
    )
    payload = revised.model_dump_json().encode("utf-8")
    world.raw_repository.prepare_revision(world.sign(payload), payload)
    world.clock.advance(minutes=1)
    world.raw_repository.activate_revision(evidence_id, 2)

    world.clock.advance(minutes=1)
    active = world.service.active_signal(
        evidence_id, cutoff=world.clock.now_value
    )
    assert active is not None
    assert active.revision == 2
    assert active.evidence.behavior_fingerprint == "c" * 64

    # append-only: revision 1 仍可读, 只是不再是 active 投影
    legacy = world.raw_repository.get(evidence_id, revision=1)
    assert legacy.revision == 1
    assert not legacy.is_active
    assert legacy.evidence.behavior_fingerprint == "b" * 64


def test_btst_has_no_runtime_gate(world: _World) -> None:
    # 不注入 runtime_mode_provider (btst_canary 是合法 mode): 无 gate, 直接 publish
    records = world.service.produce_and_publish(_snapshot())
    assert len(records) == 4
    assert len(world.signed_payloads) == 4
