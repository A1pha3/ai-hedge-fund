"""Market bar-set evidence — Phase 5a of the paired BTST forward trial (2026-08-20).

ReplaySessionFacts consumes per-session bars; constitution #12 requires official
OOS inputs to live on the evidence timeline. This module publishes one
``DailyBarSetEvidence`` per session (bar rows projected from the execution-layer
``DailyBar`` dataclass — the dataclass stays the execution truth, the evidence
model is its canonical serialized projection). Seeding sources (court raw CSVs,
price_cache) are NOT imported here: the evidence layer is source-agnostic and
seeders live in scripts/.

Discipline (isomorphic to trading_schedule.py, 2026-08-20 review rounds):
- envelope ``behavior_fingerprint`` = domain hash over the derivation rule
  constants (recomputable by any consumer), ``strategy_semver`` a plain version;
- ``available_at`` only from the injected clock; the publish call face accepts
  no timestamps;
- same content ⇒ idempotent record; different content for the same session ⇒
  the store's ``evidence_id_conflict`` (a session's bars are attested once).

Offline primitive only: freezes nothing, grants nothing.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from datetime import date, datetime
from typing import ClassVar, Final

from src.screening.offensive.v3.contracts.base import (
    EvidenceScope,
    ExecutionMode,
    domain_hash,
)
from src.screening.offensive.v3.contracts.evidence import (
    SUPPORTED_SCHEMA_MAJOR,
    EvidenceRecord,
    SnapshotEvidence,
)
from src.screening.offensive.v3.evidence.repository import EvidenceRepository
from src.screening.offensive.v3.execution.lifecycle import DailyBar
from src.screening.offensive.v3.contracts.base import CanonicalModel
from src.screening.offensive.v3.trust import SignedEnvelope

BAR_SET_PRODUCER: Final[str] = "market-bars"
_DERIVE_RULE_DOMAIN: Final[str] = "v3.market-bar-set.derive.v1"
_DERIVE_RULE_SCHEMA_MAJOR: Final[int] = SUPPORTED_SCHEMA_MAJOR
_BAR_RULE_FINGERPRINT: Final[str] = domain_hash(
    _DERIVE_RULE_DOMAIN,
    _DERIVE_RULE_SCHEMA_MAJOR,
    {
        "ordering": "unique-sorted-by-security-id",
        "prices": "integer-cents",
        "fences": "limit-up-and-limit-down-required",
        "suspended": "all-zero-prices-allowed-only-when-suspended",
    },
)


class MarketBarEvidenceError(RuntimeError):
    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


class DailyBarEvidence(CanonicalModel):
    """Canonical serialized projection of one execution-layer DailyBar."""

    HASH_DOMAIN: ClassVar[str] = "ai-hedge-fund.v3.evidence.market-bar.v1"

    security_id: str
    session: date
    open_cents: int
    high_cents: int
    low_cents: int
    close_cents: int
    limit_up_cents: int
    limit_down_cents: int
    suspended: bool = False

    @classmethod
    def from_bar(cls, bar: DailyBar) -> "DailyBarEvidence":
        return cls(
            security_id=bar.security_id,
            session=bar.session,
            open_cents=bar.open_cents,
            high_cents=bar.high_cents,
            low_cents=bar.low_cents,
            close_cents=bar.close_cents,
            limit_up_cents=bar.limit_up_cents,
            limit_down_cents=bar.limit_down_cents,
            suspended=bar.suspended,
        )

    def to_bar(self) -> DailyBar:
        return DailyBar(
            security_id=self.security_id,
            session=self.session,
            open_cents=self.open_cents,
            high_cents=self.high_cents,
            low_cents=self.low_cents,
            close_cents=self.close_cents,
            limit_up_cents=self.limit_up_cents,
            limit_down_cents=self.limit_down_cents,
            suspended=self.suspended,
        )


class DailyBarSetEvidence(CanonicalModel):
    """One session's bars, unique and sorted by security id."""

    HASH_DOMAIN: ClassVar[str] = "ai-hedge-fund.v3.evidence.market-bar-set.v1"

    session: date
    bars: tuple[DailyBarEvidence, ...]

    def by_security(self) -> dict[str, DailyBarEvidence]:
        return {b.security_id: b for b in self.bars}


def derive_bar_set(*, session: date, bars: Mapping[str, DailyBar]) -> DailyBarSetEvidence:
    """Project execution bars into one canonical, unique, sorted session set."""
    out: dict[str, DailyBarEvidence] = {}
    for security_id, bar in bars.items():
        if bar.session != session:
            raise MarketBarEvidenceError(
                "bar_session_mismatch",
                f"bar for {security_id} is {bar.session}; set is {session}",
            )
        if security_id in out:
            raise MarketBarEvidenceError("bar_duplicate", f"duplicate bar for {security_id}")
        out[security_id] = DailyBarEvidence.from_bar(bar)
    return DailyBarSetEvidence(session=session, bars=tuple(out[k] for k in sorted(out)))


def build_bar_set_envelope(bar_set: DailyBarSetEvidence, *, observed_at: datetime) -> SnapshotEvidence:
    return SnapshotEvidence(
        evidence_id=f"market:bars:{bar_set.session:%Y%m%d}",
        subject_scope=EvidenceScope.GLOBAL,
        subject_producer=BAR_SET_PRODUCER,
        family_id=None,
        strategy_semver="1.0.0",
        behavior_fingerprint=_BAR_RULE_FINGERPRINT,
        policy_epoch=1,
        execution_version="t1-open-t10-open.v1",
        cost_version="cn-a-share-costs.v1",
        effective_at=observed_at,
        provider_published_at=observed_at,
        observed_at=observed_at,
        available_at=observed_at,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        source_authority=f"{BAR_SET_PRODUCER}.publisher",
        payload_content_hash=hashlib.sha256(bar_set.canonical_bytes()).hexdigest(),
        schema_major=SUPPORTED_SCHEMA_MAJOR,
        evidence_kind="snapshot",
    )


class MarketBarSetPublisher:
    """Publishes one bar set per session (blob first, bind, sign, commit)."""

    def __init__(
        self,
        *,
        repository: EvidenceRepository,
        clock: Callable[[], datetime],
        signer: Callable[[bytes], SignedEnvelope],
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._signer = signer

    def publish(self, *, session: date, bars: Mapping[str, DailyBar]) -> EvidenceRecord[SnapshotEvidence]:
        now = self._clock()
        bar_set = derive_bar_set(session=session, bars=bars)
        blob = bar_set.canonical_bytes()
        blob_hash = self._repository.persist_payload(blob)
        envelope = build_bar_set_envelope(bar_set, observed_at=now)
        if envelope.payload_content_hash != blob_hash:
            raise MarketBarEvidenceError(
                "bar_set_hash_mismatch",
                "envelope payload_content_hash does not bind the bar-set blob",
            )
        envelope_bytes = envelope.model_dump_json().encode("utf-8")
        return self._repository.publish(self._signer(envelope_bytes), envelope_bytes)


def bars_from_record(
    repository: EvidenceRepository,
    record: EvidenceRecord[SnapshotEvidence],
    *,
    expected_session: date,
) -> dict[str, DailyBar]:
    """Consumer verification face: strict decode + session cross-check."""
    envelope = record.evidence
    if not isinstance(envelope, SnapshotEvidence):
        raise MarketBarEvidenceError(
            "evidence_kind_mismatch", "bar-set evidence must be a SnapshotEvidence envelope"
        )
    blob = repository.raw_payload(envelope.payload_content_hash)
    try:
        bar_set = DailyBarSetEvidence.model_validate_json(blob, strict=True)
    except Exception as exc:  # noqa: BLE001 - decode failure is fail-closed
        raise MarketBarEvidenceError(
            "bar_set_decode_failed", "bound blob is not a strict DailyBarSetEvidence"
        ) from exc
    if bar_set.session != expected_session:
        raise MarketBarEvidenceError(
            "session_mismatch",
            f"bar set is for {bar_set.session}; expected {expected_session}",
        )
    return {b.security_id: b.to_bar() for b in bar_set.bars}


__all__ = [
    "BAR_SET_PRODUCER",
    "DailyBarEvidence",
    "DailyBarSetEvidence",
    "MarketBarEvidenceError",
    "MarketBarSetPublisher",
    "bars_from_record",
    "build_bar_set_envelope",
    "derive_bar_set",
]
