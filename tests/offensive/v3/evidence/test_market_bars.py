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
from src.screening.offensive.v3.evidence.market_bars import (
    MarketBarSetPublisher,
    bars_from_record,
    derive_bar_set,
)
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
NS = "market-bars"


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
        "bar_publisher": MarketBarSetPublisher(
            repository=repository, clock=lambda: clock_state["now"], signer=_Signer(key, issuer, capability)
        ),
        "clock": clock_state,
    }




# ---------- 5a: bar-set 证据 ----------


def _bar(sec="000001.SZ", o=1105, c=1105):
    from datetime import date as _d

    from src.screening.offensive.v3.execution.lifecycle import DailyBar

    return DailyBar(security_id=sec, session=SIGNAL, open_cents=o, high_cents=o + 9,
                    low_cents=o - 2, close_cents=c, limit_up_cents=1221, limit_down_cents=999)


def test_derive_bar_set_sorted_unique():
    s = derive_bar_set(session=SIGNAL, bars={"600000.SH": _bar("600000.SH"), "000001.SZ": _bar()})
    assert [b.security_id for b in s.bars] == ["000001.SZ", "600000.SH"]


def test_derive_rejects_session_mismatch_and_duplicate():
    import pytest as _pytest

    from src.screening.offensive.v3.evidence.market_bars import MarketBarEvidenceError as E

    bad = _bar()._replace(session=SIGNAL + timedelta(days=1)) if hasattr(_bar(), "_replace") else None
    if bad is None:  # dataclass frozen → 构造法
        from src.screening.offensive.v3.execution.lifecycle import DailyBar

        bad = DailyBar(security_id="000001.SZ", session=SIGNAL + timedelta(days=1),
                       open_cents=1, high_cents=1, low_cents=1, close_cents=1,
                       limit_up_cents=2, limit_down_cents=1)
    with _pytest.raises(E) as ei:
        derive_bar_set(session=SIGNAL, bars={"000001.SZ": bad})
    assert ei.value.code == "bar_session_mismatch"


def test_publish_round_trip_idempotent_and_conflict(rig, tmp_path):
    import pytest as _pytest

    rec = rig["bar_publisher"].publish(session=SIGNAL, bars={"000001.SZ": _bar()})
    bars = bars_from_record(rig["repository"], rec, expected_session=SIGNAL)
    assert bars["000001.SZ"].close_cents == 1105
    rec2 = rig["bar_publisher"].publish(session=SIGNAL, bars={"000001.SZ": _bar()})
    assert rec2.evidence.evidence_id == rec.evidence.evidence_id  # 同内容幂等
    with _pytest.raises(Exception) as ei:  # noqa: B017 - 同 session 异内容
        rig["bar_publisher"].publish(session=SIGNAL, bars={"000001.SZ": _bar(c=999)})
    assert "evidence_id_conflict" in str(ei.value)


def test_bars_from_record_rejects_session_mismatch(rig, tmp_path):
    import pytest as _pytest

    from src.screening.offensive.v3.evidence.market_bars import MarketBarEvidenceError as E

    rec = rig["bar_publisher"].publish(session=SIGNAL, bars={"000001.SZ": _bar()})
    with _pytest.raises(E) as ei:
        bars_from_record(rig["repository"], rec, expected_session=SIGNAL + timedelta(days=1))
    assert ei.value.code == "session_mismatch"
