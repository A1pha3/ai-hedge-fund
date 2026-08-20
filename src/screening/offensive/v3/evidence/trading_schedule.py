"""Store-owned trading-schedule evidence for the paired BTST forward trial.

Phase 1 primitive (2026-08-20): both production fail-closed sites
(``paired_trial.freeze_shared_input`` and ``DailyActionFlow._run_shadow_pipeline``)
name the missing "store-owned trading schedule receipt". This module publishes
the T+1..T+10 session schedule as world-fact evidence, isomorphic to the
regime observation flow: the ``FrozenTradingSessionSchedule`` blob is persisted
first, a ``SnapshotEvidence`` envelope binds it via ``payload_content_hash``,
an injected signer attests, and the EvidenceRepository owns ingest time and
commit sequence.

Identity discipline (adversarial review rounds 2026-08-19/20):
- ``calendar_version`` is the stable authority identity (``sse-sessions-v1``)
  so one policy snapshot pins the whole trial — ``ShadowKernelInput`` validates
  it against ``policy.versions.calendar_version``;
- ``calendar_artifact_hash`` binds only the consumed slice (signal_session +
  exactly ten following sessions): appends beyond the window never disturb
  identity, a revision inside the window appends a NEW record while every
  prior decision stays verifiable against the slice it actually consumed.

Timing contract: publication must precede the session's
``trusted_evidence_cutoff`` (the kernel contract rejects
``available_at > cutoff``); the natural slot is SessionSpine enrollment, not
the 18:01 evening pipeline. ``available_at`` comes from the injected clock;
the publish call face accepts no timestamps.

Offline primitive only: freezes nothing, activates nothing, grants nothing.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Final

from src.screening.offensive.v3.contracts.base import EvidenceScope, ExecutionMode
from src.screening.offensive.v3.contracts.evidence import (
    SUPPORTED_SCHEMA_MAJOR,
    EvidenceRecord,
    SnapshotEvidence,
)
from src.screening.offensive.v3.evidence.repository import EvidenceRepository
from src.screening.offensive.v3.kernel.models import FrozenTradingSessionSchedule
from src.screening.offensive.v3.contracts.base import domain_hash
from src.screening.offensive.v3.trust import SignedEnvelope, canonical_json_bytes

CALENDAR_ID: Final[str] = "SSE"
CALENDAR_VERSION: Final[str] = "sse-sessions-v1"
SCHEDULE_PRODUCER: Final[str] = "exchange-calendar"
FOLLOWING_SESSION_COUNT: Final[int] = 10
_DERIVE_RULE_DOMAIN: Final[str] = "v3.trading-schedule.derive.v1"
# 推导规则域的 schema major 锚定信封 SUPPORTED_SCHEMA_MAJOR (对抗审查 P3:
# 此前裸字面量 2 是"白名单试出来的"而非语义选定; 现显式与信封契约对齐)
_DERIVE_RULE_SCHEMA_MAJOR: Final[int] = SUPPORTED_SCHEMA_MAJOR


class TradingScheduleError(RuntimeError):
    """Fail-closed rejection of a trading-schedule operation."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


def _slice_fingerprint(signal_session: date, following: tuple[date, ...]) -> str:
    """Bind exactly the consumed slice; window-external appends never change it."""
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "signal_session": signal_session.isoformat(),
                "following_sessions": [d.isoformat() for d in following],
            }
        )
    ).hexdigest()


def derive_trading_schedule(
    *,
    signal_session: date,
    calendar_dates: Iterable[date],
    available_at: datetime,
) -> FrozenTradingSessionSchedule:
    """Derive the frozen schedule: exactly ten sessions strictly after signal."""
    following = tuple(sorted({d for d in calendar_dates if d > signal_session}))
    if len(following) < FOLLOWING_SESSION_COUNT:
        raise TradingScheduleError(
            "insufficient_forward_sessions",
            f"calendar offers {len(following)} sessions after {signal_session}; "
            f"needs {FOLLOWING_SESSION_COUNT}",
        )
    following = following[:FOLLOWING_SESSION_COUNT]
    return FrozenTradingSessionSchedule(
        calendar_id=CALENDAR_ID,
        calendar_version=CALENDAR_VERSION,
        calendar_artifact_hash=_slice_fingerprint(signal_session, following),
        signal_session=signal_session,
        following_sessions=following,
        available_at=available_at,
    )


def load_authoritative_dates(calendar_path: Path | str) -> set[date]:
    """Read the authoritative session calendar JSON (data plane; no v2 imports)."""
    text = Path(calendar_path).read_text(encoding="utf-8")
    dates = json.loads(text)
    if not isinstance(dates, list):
        raise TradingScheduleError("calendar_format_unexpected", "expected a list of YYYYMMDD strings")
    out: set[date] = set()
    for s in dates:
        try:  # 畸形行 fail-closed: 静默跳过可能掩盖日历损坏 (对抗审查 2026-08-20)
            out.add(date(int(s[:4]), int(s[4:6]), int(s[6:8])))
        except (TypeError, ValueError) as exc:
            raise TradingScheduleError(
                "calendar_date_malformed", f"calendar entry {s!r} is not YYYYMMDD"
            ) from exc
    return out


def build_schedule_envelope(schedule: FrozenTradingSessionSchedule, *, observed_at: datetime) -> SnapshotEvidence:
    """Envelope binding the schedule blob; provenance conventions mirror regime evidence."""
    return SnapshotEvidence(
        evidence_id=(
            f"calendar:{CALENDAR_ID.lower()}:"
            f"{schedule.calendar_artifact_hash[:12]}:{schedule.signal_session:%Y%m%d}"
        ),
        subject_scope=EvidenceScope.GLOBAL,
        subject_producer=SCHEDULE_PRODUCER,
        family_id=None,
        strategy_semver="1.0.0",
        behavior_fingerprint=domain_hash(
            _DERIVE_RULE_DOMAIN,
            _DERIVE_RULE_SCHEMA_MAJOR,
            {
                "calendar_id": CALENDAR_ID,
                "calendar_version": CALENDAR_VERSION,
                "following_session_count": FOLLOWING_SESSION_COUNT,
                "ordering": "ascending-strict-after-signal",
                "slice_fingerprint_domain": "signal+following-sessions",
            },
        ),  # 推导规则指纹: 消费方可由同一规则常数复算 (对抗审查 2026-08-20 语义修正)
        policy_epoch=1,
        execution_version="t1-open-t10-open.v1",
        cost_version="cn-a-share-costs.v1",
        effective_at=observed_at,
        provider_published_at=observed_at,
        observed_at=observed_at,
        available_at=schedule.available_at,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        source_authority=f"{SCHEDULE_PRODUCER}.publisher",
        payload_content_hash=hashlib.sha256(schedule.canonical_bytes()).hexdigest(),
        schema_major=SUPPORTED_SCHEMA_MAJOR,
        evidence_kind="snapshot",
    )


class TradingSchedulePublisher:
    """Publishes one schedule per (signal_session, consumed slice) as evidence."""

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

    def publish(self, *, signal_session: date, calendar_path: Path | str) -> EvidenceRecord[SnapshotEvidence]:
        now = self._clock()
        schedule = derive_trading_schedule(
            signal_session=signal_session,
            calendar_dates=load_authoritative_dates(calendar_path),
            available_at=now,
        )
        blob = schedule.canonical_bytes()
        blob_hash = self._repository.persist_payload(blob)
        envelope = build_schedule_envelope(schedule, observed_at=now)
        if envelope.payload_content_hash != blob_hash:
            raise TradingScheduleError(
                "schedule_hash_mismatch",
                "envelope payload_content_hash does not bind the schedule blob",
            )
        envelope_bytes = envelope.model_dump_json().encode("utf-8")
        return self._repository.publish(self._signer(envelope_bytes), envelope_bytes)


def schedule_from_record(
    repository: EvidenceRepository,
    record: EvidenceRecord[SnapshotEvidence],
    *,
    expected_signal_session: date,
) -> FrozenTradingSessionSchedule:
    """Consumer verification face: strict decode + identity cross-checks."""
    envelope = record.evidence
    if not isinstance(envelope, SnapshotEvidence):
        raise TradingScheduleError(
            "evidence_kind_mismatch",
            "trading schedule evidence must be a SnapshotEvidence envelope",
        )
    blob = repository.raw_payload(envelope.payload_content_hash)
    try:
        schedule = FrozenTradingSessionSchedule.model_validate_json(blob, strict=True)
    except Exception as exc:  # noqa: BLE001 - decode failure is fail-closed
        raise TradingScheduleError(
            "schedule_decode_failed", "bound blob is not a strict FrozenTradingSessionSchedule"
        ) from exc
    if schedule.signal_session != expected_signal_session:
        raise TradingScheduleError(
            "signal_session_mismatch",
            f"schedule is for {schedule.signal_session}; expected {expected_signal_session}",
        )
    if schedule.available_at != envelope.available_at:
        raise TradingScheduleError(
            "available_at_mismatch",
            "schedule available_at does not match the envelope",
        )
    if schedule.calendar_artifact_hash != _slice_fingerprint(
        schedule.signal_session, schedule.following_sessions
    ):
        raise TradingScheduleError(
            "slice_fingerprint_mismatch",
            "artifact hash does not bind the stored slice",
        )
    return schedule


__all__ = [
    "CALENDAR_ID",
    "CALENDAR_VERSION",
    "FOLLOWING_SESSION_COUNT",
    "SCHEDULE_PRODUCER",
    "TradingScheduleError",
    "TradingSchedulePublisher",
    "build_schedule_envelope",
    "derive_trading_schedule",
    "load_authoritative_dates",
    "schedule_from_record",
]
