"""BTST raw-candidate evidence is durable, exact, and replay-verifiable."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.screening.offensive.daily_action_service import PlanCandidate
from src.screening.offensive.setups.base import DetectionResult
from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup
from src.screening.offensive.v3.contracts.base import SignalStage
from src.screening.offensive.v3.contracts.evidence import EvidenceRecord, SignalEvidence
from src.screening.offensive.v3.evidence.repository import EvidenceStoreError
from src.screening.offensive.v3.producers import btst as btst_producer
from tests.offensive.v3.services.test_btst_producer_api import (
    BTST_FINGERPRINT,
    CONSUMED_FP,
    SIGNAL_DATE,
    SNAPSHOT_ID,
    _World,
    _snapshot,
)


def _candidate(
    *,
    ticker: str = "300123",
    entry_price: float = 5.0,
    target_weight: float = 0.09,
    trigger_strength: float = 0.9,
) -> PlanCandidate:
    return PlanCandidate(
        ticker=ticker,
        setup="btst_breakout",
        setup_version="v2",
        signal_date=SIGNAL_DATE,
        target_weight=target_weight,
        priority=1,
        snapshot_id=SNAPSHOT_ID,
        setup_consumed_fingerprint=CONSUMED_FP,
        trigger_strength=trigger_strength,
        entry_price=entry_price,
    )


def _build_payload(
    candidate: PlanCandidate,
    *,
    industry: str | None = "software",
    stage: SignalStage = SignalStage.SELECTED,
):
    builder = getattr(btst_producer, "build_btst_raw_candidate_payload", None)
    assert callable(builder), "BTST producer must expose the raw-candidate builder"
    return builder(
        candidate,
        stage=stage,
        industry=industry,
        behavior_fingerprint=BTST_FINGERPRINT,
    )


@pytest.fixture()
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _World:
    def hit(self, ticker, trade_date, context):
        return DetectionResult(
            hit=True,
            ticker=ticker,
            trade_date=SIGNAL_DATE.strftime("%Y%m%d"),
            trigger_strength=0.9,
            invalidation_condition="price below trigger close",
            metadata={"range_based_stop_pct": -0.08},
            degraded=False,
            degradation_reason="",
        )

    monkeypatch.setattr(BtstBreakoutSetup, "detect", hit)
    return _World(tmp_path, btst_fingerprint=BTST_FINGERPRINT)


def test_five_and_fifty_yuan_candidates_have_distinct_exact_payload_hashes() -> None:
    five = _build_payload(_candidate(entry_price=5.0))
    fifty = _build_payload(_candidate(entry_price=50.0))

    assert five.entry_price_micros == 5_000_000
    assert fifty.entry_price_micros == 50_000_000
    assert five.canonical_bytes() != fifty.canonical_bytes()
    assert five.content_hash() != fifty.content_hash()


@pytest.mark.parametrize(
    ("ticker", "expected_security_id"),
    (("600000", "600000.SH"), ("300123", "300123.SZ")),
)
def test_raw_candidate_uses_exchange_qualified_security_id(
    ticker: str, expected_security_id: str
) -> None:
    payload = _build_payload(_candidate(ticker=ticker))

    assert payload.security_id == expected_security_id


@pytest.mark.parametrize("ticker", ("100000", "ABC"))
def test_unknown_exchange_identity_fails_closed_instead_of_guessing_sz(
    ticker: str,
) -> None:
    with pytest.raises(Exception) as rejected:
        _build_payload(_candidate(ticker=ticker))

    assert getattr(rejected.value, "code", None) == "security_id_unknown"


def test_trigger_strength_above_one_fails_closed() -> None:
    with pytest.raises(Exception) as rejected:
        _build_payload(_candidate(trigger_strength=1.000001))

    assert getattr(rejected.value, "code", None) == "trigger_strength_out_of_range"


def test_missing_industry_is_a_typed_unknown_not_a_guess() -> None:
    payload = _build_payload(_candidate(), industry=None)

    assert payload.industry_state == "UNKNOWN"
    assert payload.industry is None


def test_raw_payload_is_durable_and_bound_to_each_signal_record(world: _World) -> None:
    records = world.service.produce_and_publish(_snapshot())
    reader = getattr(world.service, "candidate_payload", None)
    assert callable(reader), "BTST service must expose the verified payload reader"

    for record in records:
        payload = reader(record, expected_signal_session=SIGNAL_DATE)
        raw = world.blob_store.get(record.evidence.payload_content_hash)
        assert hashlib.sha256(raw).hexdigest() == record.evidence.payload_content_hash
        assert raw == payload.canonical_bytes()
        assert payload.signal_session == SIGNAL_DATE
        assert payload.snapshot_id == SNAPSHOT_ID
        assert payload.signal_stage is record.evidence.stage
        assert payload.behavior_fingerprint == record.evidence.behavior_fingerprint


def test_missing_or_tampered_bound_raw_blob_fails_closed(
    world: _World,
) -> None:
    record = world.service.produce_and_publish(_snapshot())[0]
    reader = getattr(world.service, "candidate_payload", None)
    assert callable(reader), "BTST service must expose the verified payload reader"
    blob_path = world.blob_store.blob_path(record.evidence.payload_content_hash)

    original = blob_path.read_bytes()
    blob_path.unlink()
    with pytest.raises(Exception) as missing:
        reader(record, expected_signal_session=SIGNAL_DATE)
    assert getattr(missing.value, "code", None) == "candidate_payload_missing"

    blob_path.parent.mkdir(parents=True, exist_ok=True)
    blob_path.write_bytes(original + b" ")
    with pytest.raises(Exception) as tampered:
        reader(record, expected_signal_session=SIGNAL_DATE)
    assert getattr(tampered.value, "code", None) == "candidate_payload_hash_mismatch"


def test_reader_rejects_wrong_expected_session_and_candidate_identity(
    world: _World,
) -> None:
    record = world.service.produce_and_publish(_snapshot())[0]
    reader = getattr(world.service, "candidate_payload", None)
    assert callable(reader), "BTST service must expose the verified payload reader"

    with pytest.raises(Exception) as wrong_session:
        reader(
            record,
            expected_signal_session=SIGNAL_DATE + timedelta(days=1),
        )
    assert getattr(wrong_session.value, "code", None) == "signal_session_mismatch"

    other = _build_payload(_candidate(ticker="600000"), stage=record.evidence.stage)
    other_hash = world.raw_repository.persist_payload(other.canonical_bytes())
    wrong_envelope = record.evidence.model_copy(
        update={"payload_content_hash": other_hash}
    )
    wrong_record = record.model_copy(update={"evidence": wrong_envelope})
    with pytest.raises(Exception) as wrong_identity:
        reader(wrong_record, expected_signal_session=SIGNAL_DATE)
    assert getattr(wrong_identity.value, "code", None) == "signal_record_untrusted"


def test_publish_fault_leaves_only_a_safe_orphan_raw_blob(
    world: _World, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact_factory = getattr(
        btst_producer, "produce_btst_signal_artifacts", None
    )
    assert callable(artifact_factory), "BTST producer must expose payload artifacts"
    first = artifact_factory(
        _snapshot(), behavior_fingerprint=BTST_FINGERPRINT
    )[0]

    def fail_publish(*args, **kwargs):
        raise RuntimeError("injected publish fault")

    monkeypatch.setattr(world.service._repository, "publish", fail_publish)
    with pytest.raises(RuntimeError, match="injected publish fault"):
        world.service.produce_and_publish(_snapshot())

    assert world.blob_store.get(first.payload.content_hash()) == (
        first.payload.canonical_bytes()
    )
    assert (
        world.service.active_signal(
            first.envelope.evidence_id,
            cutoff=world.clock.now_value + timedelta(seconds=1),
        )
        is None
    )


def _signed_signal(world: _World, envelope: SignalEvidence):
    payload = envelope.model_dump_json().encode("utf-8")
    return world.sign(payload), payload


def _envelope_for_candidate(world: _World, candidate, **updates) -> SignalEvidence:
    session_time = datetime(2026, 8, 5, 15, tzinfo=timezone.utc)
    values = {
        "family_id": f"btst:{candidate.snapshot_id}",
        "strategy_semver": candidate.strategy_semver,
        "behavior_fingerprint": candidate.behavior_fingerprint,
        "effective_at": session_time,
        "provider_published_at": session_time,
        "observed_at": session_time,
        "available_at": datetime(2026, 8, 6, 15, tzinfo=timezone.utc),
        "payload_content_hash": candidate.content_hash(),
        "stage": candidate.signal_stage,
    }
    values.update(updates)
    return world.signal_envelope(
        f"{candidate.candidate_id}:{candidate.signal_stage.value}",
        **values,
    )


def test_store_rejects_btst_signal_whose_referenced_payload_is_missing(
    world: _World,
) -> None:
    envelope = world.signal_envelope(
        "btst:missing:candidate",
        payload_content_hash="a" * 64,
    )
    signed, payload = _signed_signal(world, envelope)

    with pytest.raises(EvidenceStoreError) as rejected:
        world.raw_repository.publish(signed, payload)

    assert rejected.value.code == "referenced_payload_missing"
    assert world.raw_repository.commit_sequence() == 0


def test_store_rejects_btst_signal_whose_referenced_bytes_are_not_candidate(
    world: _World,
) -> None:
    malformed_hash = world.raw_repository.persist_payload(b"not a candidate")
    envelope = world.signal_envelope(
        "btst:malformed:candidate",
        payload_content_hash=malformed_hash,
    )
    signed, payload = _signed_signal(world, envelope)

    with pytest.raises(EvidenceStoreError) as rejected:
        world.raw_repository.publish(signed, payload)

    assert rejected.value.code == "referenced_payload_invalid"
    assert world.raw_repository.commit_sequence() == 0


@pytest.mark.parametrize(
    "envelope_updates",
    (
        {"evidence_id": "btst:wrong:identity:candidate"},
        {"behavior_fingerprint": "d" * 64},
        {"effective_at": datetime(2026, 8, 6, 8, tzinfo=timezone.utc)},
    ),
)
def test_store_rejects_valid_candidate_bound_to_wrong_identity_session_or_version(
    world: _World,
    envelope_updates: dict[str, object],
) -> None:
    candidate = _build_payload(_candidate(), stage=SignalStage.CANDIDATE)
    world.raw_repository.persist_payload(candidate.canonical_bytes())
    envelope = _envelope_for_candidate(world, candidate).model_copy(
        update=envelope_updates
    )
    signed, payload = _signed_signal(world, envelope)

    with pytest.raises(EvidenceStoreError) as rejected:
        world.raw_repository.publish(signed, payload)

    assert rejected.value.code == "referenced_payload_binding_mismatch"
    assert world.raw_repository.commit_sequence() == 0


def test_prepare_revision_revalidates_btst_referenced_payload(world: _World) -> None:
    published = world.service.produce_and_publish(_snapshot())[0]
    before_sequence = world.raw_repository.commit_sequence()
    revision = published.evidence.model_copy(
        update={"payload_content_hash": "a" * 64}
    )
    signed, payload = _signed_signal(world, revision)

    with pytest.raises(EvidenceStoreError) as rejected:
        world.raw_repository.prepare_revision(signed, payload)

    assert rejected.value.code == "referenced_payload_missing"
    assert world.raw_repository.commit_sequence() == before_sequence


def test_candidate_reader_rejects_uncommitted_self_consistent_record(
    world: _World,
) -> None:
    candidate = _build_payload(_candidate(), stage=SignalStage.SELECTED)
    candidate_hash = world.raw_repository.persist_payload(candidate.canonical_bytes())
    session_time = datetime(2026, 8, 5, 15, tzinfo=timezone.utc)
    envelope = world.signal_envelope(
        f"{candidate.candidate_id}:selected",
        family_id=f"btst:{candidate.snapshot_id}",
        strategy_semver=candidate.strategy_semver,
        behavior_fingerprint=candidate.behavior_fingerprint,
        effective_at=session_time,
        provider_published_at=session_time,
        observed_at=session_time,
        available_at=datetime(2026, 8, 6, 15, tzinfo=timezone.utc),
        payload_content_hash=candidate_hash,
        stage=SignalStage.SELECTED,
    )
    uncommitted = EvidenceRecord[SignalEvidence](
        evidence=envelope,
        ingested_at=world.clock.now_value,
        commit_sequence=999,
        revision=1,
        supersedes_revision=None,
        active_revision=1,
    )

    with pytest.raises(Exception) as rejected:
        world.service.candidate_payload(
            uncommitted,
            expected_signal_session=SIGNAL_DATE,
        )

    assert getattr(rejected.value, "code", None) == "signal_record_untrusted"


def test_candidate_reader_accepts_committed_historical_revision_after_correction(
    world: _World,
) -> None:
    original = world.service.produce_and_publish(_snapshot())[0]
    original_candidate = world.service.candidate_payload(
        original,
        expected_signal_session=SIGNAL_DATE,
    )
    revised_candidate = original_candidate.model_copy(
        update={"behavior_fingerprint": "c" * 64}
    )
    revised_hash = world.raw_repository.persist_payload(
        revised_candidate.canonical_bytes()
    )
    revised_envelope = original.evidence.model_copy(
        update={
            "behavior_fingerprint": "c" * 64,
            "payload_content_hash": revised_hash,
        }
    )
    signed, payload = _signed_signal(world, revised_envelope)
    world.raw_repository.prepare_revision(signed, payload)
    world.raw_repository.activate_revision(original.evidence.evidence_id, 2)

    replayed = world.service.candidate_payload(
        original,
        expected_signal_session=SIGNAL_DATE,
    )

    assert replayed == original_candidate
