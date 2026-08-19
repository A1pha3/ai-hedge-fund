"""Trading-schedule evidence — Phase 1 primitive of the paired BTST forward trial.

锁定 (四轮对抗审查收敛, 2026-08-20):
- derive: 恰 10 后继会话 / 不足 fail-closed / 切片指纹只绑消费窗口;
- 身份: version 恒为权威身份 (policy 一次钉死), artifact_hash 窗口外追加零扰动,
  窗口内修订 = 新证据记录追加而旧记录完好 (时间旅行正确性);
- 发布: blob 先行 → 信封绑定 → 签名 → repository.publish; available_at 只来自
  注入 clock, publish 调用面零时间参数 (签名断言);
- 复核面: strict 解码 + session/available_at/切片指纹三重交叉.
"""

from __future__ import annotations

import hashlib
import inspect
from base64 import b64encode
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.screening.offensive.v3 import trust as v3trust
from src.screening.offensive.v3.contracts.base import ExecutionMode
from src.screening.offensive.v3.evidence.blob_store import BlobStore
from src.screening.offensive.v3.evidence.repository import EvidenceRepository
from src.screening.offensive.v3.evidence.trading_schedule import (
    CALENDAR_VERSION,
    FOLLOWING_SESSION_COUNT,
    TradingScheduleError,
    TradingSchedulePublisher,
    derive_trading_schedule,
    schedule_from_record,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
SIGNAL = date(2026, 8, 20)
# 12 个后继日历日 (比 10 多 2, 验证"恰取 10")
DATES = {SIGNAL + timedelta(days=i) for i in range(1, 13)} | {SIGNAL, SIGNAL - timedelta(days=5)}
NS = "exchange-calendar"


def _dates_json(dates: set[date], tmp: Path) -> Path:
    p = tmp / "trade_calendar.json"
    p.write_text("[" + ",".join(f'"{d:%Y%m%d}"' for d in sorted(dates)) + "]", encoding="utf-8")
    return p


class _Signer:
    def __init__(self, key, issuer, capability) -> None:
        self._key, self._issuer, self._capability = key, issuer, capability

    def __call__(self, payload: bytes):
        payload_hash = hashlib.sha256(payload).hexdigest()
        protected = v3trust.canonical_json_bytes(
            {
                "artifact": self._capability.artifact,
                "capability_scope": self._capability.scope,
                "capability_version": self._capability.capability_version,
                "issuer_id": self._issuer.issuer_id,
                "key_id": self._issuer.key_id,
                "mode": self._capability.mode,
                "namespace": self._capability.namespace,
                "payload": b64encode(payload).decode("ascii"),
                "payload_hash": payload_hash,
                "schema_major": self._capability.schema_major,
            }
        )
        return v3trust.SignedEnvelope(
            issuer_id=self._issuer.issuer_id,
            key_id=self._issuer.key_id,
            schema_major=self._capability.schema_major,
            artifact=self._capability.artifact,
            namespace=self._capability.namespace,
            mode=self._capability.mode,
            capability_version=self._capability.capability_version,
            capability_scope=self._capability.scope,
            payload_hash=payload_hash,
            payload=payload,
            signature=b64encode(self._key.sign(protected)).decode("ascii"),
        )


class _TrustHeadProvider:
    def __init__(self, head) -> None:
        self._head = head

    def current_trust_head(self, trusted_at: datetime):
        return self._head


@pytest.fixture()
def rig(tmp_path: Path):
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    capability = v3trust.Capability(
        artifact=v3trust.ArtifactKind.SNAPSHOT,
        namespace=NS,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        schema_major=2,
        capability_version="calendar.snapshot.v1",
        scope="global:calendar",
        valid_from=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=120),
        revoked_at=None,
    )
    issuer = v3trust.TrustedIssuer(
        issuer_id="governance.service",
        key_id="calendar-key-1",
        issuer_kind=v3trust.IssuerKind.MARKET_PUBLISHER,
        public_key=b64encode(public).decode("ascii"),
        valid_from=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=120),
        revoked_at=None,
        capabilities=(capability,),
    )
    registry = v3trust.TrustedRegistry(issuers=(issuer,))
    root_key = Ed25519PrivateKey.generate()
    root_public = root_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    anchor = v3trust.RootTrustAnchor(
        root_hash=hashlib.sha256(root_public).hexdigest(),
        root_key_id="root-1",
        public_key=b64encode(root_public).decode("ascii"),
        valid_from=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=120),
        revoked_at=None,
    )
    from src.screening.offensive.v3.contracts.governance import TrustBundle

    bundle = TrustBundle(
        registry_epoch=1,
        predecessor_bundle_hash="0" * 64,
        root_hash=anchor.root_hash,
        root_key_id=anchor.root_key_id,
        trusted_issuer_registry_hash=registry.content_hash(),
        issued_at=NOW - timedelta(minutes=10),
        expires_at=NOW + timedelta(days=120),
        revoked_at=None,
        issuer_id="offline-governance-root",
        issuer_capability="root.trust.bundle.v1",
        schema_major=2,
    )
    signed_bundle = v3trust.SignedTrustBundle(
        bundle=bundle,
        registry=registry,
        signature=b64encode(
            root_key.sign(v3trust.trust_bundle_signature_preimage(bundle, registry))
        ).decode("ascii"),
    )
    head = v3trust.CurrentTrustHeadWitness(
        active_trust_bundle_hash=bundle.artifact_hash(),
        registry_epoch=1,
        head_version=1,
        store_version=1,
        observed_at=NOW,
    )
    repository = EvidenceRepository(
        database_path=str(tmp_path / "schedule-evidence.sqlite3"),
        blob_store=BlobStore(tmp_path / "blobs"),
        verifier=v3trust.CapabilityVerifier(v3trust.TrustBundleVerifier((anchor,)), (signed_bundle,)),
        trust_head_provider=_TrustHeadProvider(head),
        issuer_namespace=NS,
        clock=lambda: NOW,
    )
    clock_state = {"now": NOW}
    return {
        "repository": repository,
        "publisher": TradingSchedulePublisher(
            repository=repository, clock=lambda: clock_state["now"], signer=_Signer(key, issuer, capability)
        ),
        "clock": clock_state,
    }


# ---------- derive ----------


def test_derive_exactly_ten_following_sessions():
    s = derive_trading_schedule(signal_session=SIGNAL, calendar_dates=DATES, available_at=NOW)
    assert len(s.following_sessions) == FOLLOWING_SESSION_COUNT
    assert s.following_sessions == tuple(sorted(s.following_sessions))
    assert all(d > SIGNAL for d in s.following_sessions)
    assert s.calendar_version == CALENDAR_VERSION  # policy 绑定前提: 恒定权威身份


def test_derive_insufficient_fail_closed():
    with pytest.raises(TradingScheduleError) as ei:
        derive_trading_schedule(
            signal_session=SIGNAL, calendar_dates={SIGNAL + timedelta(days=1)}, available_at=NOW
        )
    assert ei.value.code == "insufficient_forward_sessions"


def test_slice_stability_window_external_appends_zero_disturbance():
    base = derive_trading_schedule(signal_session=SIGNAL, calendar_dates=DATES, available_at=NOW)
    grown = derive_trading_schedule(
        signal_session=SIGNAL, calendar_dates=DATES | {SIGNAL + timedelta(days=40)}, available_at=NOW
    )
    assert base.calendar_artifact_hash == grown.calendar_artifact_hash
    assert base.calendar_version == grown.calendar_version


def test_window_revision_changes_hash_not_version():
    revised = DATES - {SIGNAL + timedelta(days=3)} | {SIGNAL + timedelta(days=99)}
    s2 = derive_trading_schedule(signal_session=SIGNAL, calendar_dates=revised, available_at=NOW)
    base = derive_trading_schedule(signal_session=SIGNAL, calendar_dates=DATES, available_at=NOW)
    assert s2.calendar_artifact_hash != base.calendar_artifact_hash
    assert s2.calendar_version == base.calendar_version


# ---------- publish / verify ----------


def test_publish_round_trip_and_idempotence(rig, tmp_path):
    cal = _dates_json(DATES, tmp_path)
    rec1 = rig["publisher"].publish(signal_session=SIGNAL, calendar_path=cal)
    s = schedule_from_record(rig["repository"], rec1, expected_signal_session=SIGNAL)
    assert s.following_sessions == tuple(sorted(d for d in DATES if d > SIGNAL))[:10]
    rec2 = rig["publisher"].publish(signal_session=SIGNAL, calendar_path=cal)
    assert rec2.evidence.evidence_id == rec1.evidence.evidence_id  # 同内容幂等


def test_window_revision_appends_new_record_old_intact(rig, tmp_path):
    rec1 = rig["publisher"].publish(signal_session=SIGNAL, calendar_path=_dates_json(DATES, tmp_path))
    revised = DATES - {SIGNAL + timedelta(days=3)} | {SIGNAL + timedelta(days=99)}
    rec2 = rig["publisher"].publish(signal_session=SIGNAL, calendar_path=_dates_json(revised, tmp_path))
    assert rec2.evidence.evidence_id != rec1.evidence.evidence_id  # 新切片 = 新记录
    old = rig["repository"].active_revision(rec1.evidence.evidence_id, NOW + timedelta(hours=1))
    s_old = schedule_from_record(rig["repository"], old, expected_signal_session=SIGNAL)
    assert SIGNAL + timedelta(days=3) in s_old.following_sessions  # 旧决策对旧切片依然可验


def test_available_at_from_injected_clock_not_call_face(rig, tmp_path):
    params = inspect.signature(rig["publisher"].publish).parameters
    assert not ({"available_at", "observed_at", "now"} & set(params))
    rec = rig["publisher"].publish(signal_session=SIGNAL, calendar_path=_dates_json(DATES, tmp_path))
    assert rec.evidence.available_at == NOW  # 只来自注入 clock


def test_same_slice_resigned_later_is_conflict(rig, tmp_path):
    """同 id 必须同内容: 同一切片晚些时候重签 = store 的 evidence_id_conflict。

    语义上正确 — 同一世界事实不允许事后重新 attestation (且更晚的 available_at
    本就会被 cutoff 校验拒绝)。排程每 session 发布一次 (spine 注册时)。
    """
    rig["publisher"].publish(signal_session=SIGNAL, calendar_path=_dates_json(DATES, tmp_path))
    rig["clock"]["now"] = NOW + timedelta(minutes=30)
    with pytest.raises(Exception) as ei:  # noqa: B017 - EvidenceStoreError
        rig["publisher"].publish(signal_session=SIGNAL, calendar_path=_dates_json(DATES, tmp_path))
    assert "evidence_id_conflict" in str(ei.value)


def test_schedule_from_record_rejects_session_mismatch(rig, tmp_path):
    rec = rig["publisher"].publish(signal_session=SIGNAL, calendar_path=_dates_json(DATES, tmp_path))
    with pytest.raises(TradingScheduleError) as ei:
        schedule_from_record(rig["repository"], rec, expected_signal_session=SIGNAL + timedelta(days=1))
    assert ei.value.code == "signal_session_mismatch"
