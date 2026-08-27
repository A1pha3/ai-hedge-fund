"""BTST raw-candidate evidence is durable, exact, and replay-verifiable."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.screening.offensive.daily_action_service import PlanCandidate
from src.screening.offensive.setups.base import DetectionResult
from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup
from src.screening.offensive.v3.contracts.base import SignalStage
from src.screening.offensive.v3.contracts.evidence import EvidenceRecord, SignalEvidence
from src.screening.offensive.v3.evidence.repository import (
    EVIDENCE_STORE_SCHEMA_VERSION,
    EvidenceRepository,
    EvidenceStoreError,
)
from src.screening.offensive.v3.producers import btst as btst_producer
from src.screening.offensive.v3.services.btst_producer_api import (
    BtstCandidateEvidenceError,
)
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


def test_external_blob_loss_does_not_override_authoritative_raw_payload(
    world: _World,
) -> None:
    record = world.service.produce_and_publish(_snapshot())[0]
    reader = getattr(world.service, "candidate_payload", None)
    assert callable(reader), "BTST service must expose the verified payload reader"
    blob_path = world.blob_store.blob_path(record.evidence.payload_content_hash)

    blob_path.unlink()
    payload = reader(record, expected_signal_session=SIGNAL_DATE)

    assert payload.content_hash() == record.evidence.payload_content_hash


def test_tampered_authoritative_raw_payload_fails_closed(world: _World) -> None:
    record = world.service.produce_and_publish(_snapshot())[0]
    content_hash = record.evidence.payload_content_hash
    with sqlite3.connect(world.database_path) as conn:
        conn.execute("DROP TRIGGER evidence_referenced_payloads_no_update")
        conn.execute(
            "UPDATE evidence_referenced_payloads SET payload = ?"
            " WHERE issuer_namespace = ? AND content_hash = ?",
            (b"tampered", "btst", content_hash),
        )

    with pytest.raises(Exception) as tampered:
        world.service.candidate_payload(
            record,
            expected_signal_session=SIGNAL_DATE,
        )

    assert getattr(tampered.value, "code", None) == "referenced_payload_corrupt"


def test_missing_authoritative_raw_payload_never_falls_back_to_external_mirror(
    world: _World,
) -> None:
    record = world.service.produce_and_publish(_snapshot())[0]
    content_hash = record.evidence.payload_content_hash
    assert world.blob_store.blob_path(content_hash).is_file()
    with sqlite3.connect(world.database_path) as conn:
        conn.execute("DROP TRIGGER evidence_referenced_payloads_no_delete")
        conn.execute(
            "DELETE FROM evidence_referenced_payloads"
            " WHERE issuer_namespace = ? AND content_hash = ?",
            ("btst", content_hash),
        )

    with pytest.raises(BtstCandidateEvidenceError) as missing:
        world.service.candidate_payload(
            record,
            expected_signal_session=SIGNAL_DATE,
        )

    assert getattr(missing.value, "code", None) == "referenced_payload_missing"
    with pytest.raises(EvidenceStoreError) as reopen:
        EvidenceRepository(
            database_path=world.database_path,
            blob_store=world.blob_store,
            verifier=world.verifier,
            trust_head_provider=world.head_provider,
            issuer_namespace="btst",
            clock=world.clock,
        )
    assert reopen.value.code == "referenced_payload_missing"


def test_missing_indexed_binding_never_falls_back_to_btst_blob_mirror(
    world: _World,
) -> None:
    record = world.service.produce_and_publish(_snapshot())[0]
    content_hash = record.evidence.payload_content_hash
    assert world.blob_store.blob_path(content_hash).is_file()
    with sqlite3.connect(world.database_path) as conn:
        conn.execute("DROP TRIGGER evidence_referenced_bindings_no_delete")
        conn.execute(
            "DELETE FROM evidence_referenced_bindings"
            " WHERE issuer_namespace = ? AND evidence_id = ? AND revision = ?",
            ("btst", record.evidence.evidence_id, record.revision),
        )

    with pytest.raises(BtstCandidateEvidenceError) as rejected:
        world.service.candidate_payload(
            record,
            expected_signal_session=SIGNAL_DATE,
        )

    assert rejected.value.code == "referenced_payload_binding_missing"


def test_idempotent_publish_never_repairs_missing_authoritative_raw_from_mirror(
    world: _World,
) -> None:
    record = world.service.produce_and_publish(_snapshot())[0]
    content_hash = record.evidence.payload_content_hash
    raw = world.blob_store.get(content_hash)
    payload = record.evidence.model_dump_json().encode("utf-8")
    signed = world.sign(payload)
    with sqlite3.connect(world.database_path) as conn:
        conn.execute("DROP TRIGGER evidence_referenced_payloads_no_delete")
        conn.execute(
            "DELETE FROM evidence_referenced_payloads"
            " WHERE issuer_namespace = ? AND content_hash = ?",
            ("btst", content_hash),
        )

    with pytest.raises(EvidenceStoreError) as rejected:
        world.raw_repository.publish(
            signed,
            payload,
            referenced_payload=raw,
        )

    assert rejected.value.code == "referenced_payload_missing"
    with sqlite3.connect(world.database_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM evidence_referenced_payloads"
            " WHERE issuer_namespace = ? AND content_hash = ?",
            ("btst", content_hash),
        ).fetchone()
    assert count == (0,)


def test_authoritative_raw_payload_rows_are_sqlite_immutable(world: _World) -> None:
    record = world.service.produce_and_publish(_snapshot())[0]
    content_hash = record.evidence.payload_content_hash

    with sqlite3.connect(world.database_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="immutable table"):
            conn.execute(
                "UPDATE evidence_referenced_payloads SET payload = ?"
                " WHERE issuer_namespace = ? AND content_hash = ?",
                (b"tampered", "btst", content_hash),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable table"):
            conn.execute(
                "DELETE FROM evidence_referenced_payloads"
                " WHERE issuer_namespace = ? AND content_hash = ?",
                ("btst", content_hash),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable table"):
            conn.execute(
                "UPDATE evidence_schema_meta SET schema_version = 1"
                " WHERE issuer_namespace = 'btst'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable table"):
            conn.execute(
                "DELETE FROM evidence_schema_meta"
                " WHERE issuer_namespace = 'btst'"
            )

    assert (
        world.raw_repository.raw_payload(content_hash)
        == world.blob_store.get(content_hash)
    )


def test_nonempty_legacy_store_requires_explicit_offline_cutover(
    world: _World,
) -> None:
    record = world.service.produce_and_publish(_snapshot())[0]
    legacy_path = str(Path(world.database_path).with_name("legacy.sqlite3"))
    with sqlite3.connect(legacy_path) as conn:
        conn.execute(
            "CREATE TABLE evidence_head ("
            "issuer_namespace TEXT PRIMARY KEY,"
            "last_commit_sequence BIGINT NOT NULL,"
            "dependency_root TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE evidence_records ("
            "issuer_namespace TEXT NOT NULL, evidence_id TEXT NOT NULL,"
            "revision BIGINT NOT NULL, evidence_kind TEXT NOT NULL,"
            "record_json TEXT NOT NULL, payload_content_hash TEXT NOT NULL,"
            "ingested_at TEXT NOT NULL, activated_at TEXT NOT NULL,"
            "commit_sequence BIGINT NOT NULL, supersedes_revision BIGINT,"
            "dependency_root TEXT NOT NULL,"
            "PRIMARY KEY (issuer_namespace, evidence_id, revision))"
        )
        conn.execute(
            "CREATE TABLE evidence_prepared ("
            "issuer_namespace TEXT NOT NULL, evidence_id TEXT NOT NULL,"
            "revision BIGINT NOT NULL, evidence_kind TEXT NOT NULL,"
            "record_json TEXT NOT NULL, payload_content_hash TEXT NOT NULL,"
            "ingested_at TEXT NOT NULL, commit_sequence BIGINT NOT NULL,"
            "supersedes_revision BIGINT NOT NULL, dependency_root TEXT NOT NULL,"
            "PRIMARY KEY (issuer_namespace, evidence_id, revision))"
        )
        conn.execute(
            "INSERT INTO evidence_head VALUES (?, ?, ?)",
            ("btst", 1, "1" * 64),
        )
        conn.execute(
            "INSERT INTO evidence_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "btst",
                record.evidence.evidence_id,
                1,
                "signal",
                record.model_dump_json(),
                hashlib.sha256(record.evidence.canonical_bytes()).hexdigest(),
                record.ingested_at.isoformat(),
                record.ingested_at.isoformat(),
                1,
                None,
                "1" * 64,
            ),
        )

    with pytest.raises(EvidenceStoreError) as rejected:
        EvidenceRepository(
            database_path=legacy_path,
            blob_store=world.blob_store,
            verifier=world.verifier,
            trust_head_provider=world.head_provider,
            issuer_namespace="btst",
            clock=world.clock,
        )

    assert rejected.value.code == "legacy_store_requires_offline_cutover"
    with sqlite3.connect(legacy_path) as conn:
        v2_objects = conn.execute(
            "SELECT name FROM sqlite_schema"
            " WHERE name IN ('evidence_schema_meta',"
            " 'evidence_referenced_payloads', 'evidence_referenced_bindings')"
        ).fetchall()
    assert v2_objects == []


def test_empty_legacy_namespace_initializes_exact_schema_v2(world: _World) -> None:
    empty_path = str(Path(world.database_path).with_name("empty-legacy.sqlite3"))
    with sqlite3.connect(empty_path) as conn:
        conn.execute(
            "CREATE TABLE evidence_head ("
            "issuer_namespace TEXT PRIMARY KEY,"
            "last_commit_sequence BIGINT NOT NULL,"
            "dependency_root TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO evidence_head VALUES (?, ?, ?)",
            ("btst", 0, "0" * 64),
        )

    EvidenceRepository(
        database_path=empty_path,
        blob_store=world.blob_store,
        verifier=world.verifier,
        trust_head_provider=world.head_provider,
        issuer_namespace="btst",
        clock=world.clock,
    )

    with sqlite3.connect(empty_path) as conn:
        version = conn.execute(
            "SELECT schema_version FROM evidence_schema_meta"
            " WHERE issuer_namespace = 'btst'"
        ).fetchone()
    assert version == (EVIDENCE_STORE_SCHEMA_VERSION,)


def test_reopen_rejects_same_named_but_weakened_immutability_trigger(
    world: _World,
) -> None:
    with sqlite3.connect(world.database_path) as conn:
        conn.execute("DROP TRIGGER evidence_referenced_payloads_no_update")
        conn.execute(
            "CREATE TRIGGER evidence_referenced_payloads_no_update"
            " BEFORE UPDATE ON evidence_referenced_payloads"
            " BEGIN SELECT 1; END"
        )

    with pytest.raises(EvidenceStoreError) as rejected:
        EvidenceRepository(
            database_path=world.database_path,
            blob_store=world.blob_store,
            verifier=world.verifier,
            trust_head_provider=world.head_provider,
            issuer_namespace="btst",
            clock=world.clock,
        )

    assert rejected.value.code == "evidence_schema_definition_mismatch"


def test_open_rejects_same_named_but_weakened_schema_table(world: _World) -> None:
    malformed_path = str(Path(world.database_path).with_name("malformed-v2.sqlite3"))
    with sqlite3.connect(malformed_path) as conn:
        conn.execute(
            "CREATE TABLE evidence_referenced_payloads ("
            "issuer_namespace TEXT NOT NULL, content_hash TEXT NOT NULL,"
            "payload BLOB NOT NULL, rogue_column TEXT,"
            "PRIMARY KEY (issuer_namespace, content_hash))"
        )

    with pytest.raises(EvidenceStoreError) as rejected:
        EvidenceRepository(
            database_path=malformed_path,
            blob_store=world.blob_store,
            verifier=world.verifier,
            trust_head_provider=world.head_provider,
            issuer_namespace="btst",
            clock=world.clock,
        )

    assert rejected.value.code == "evidence_schema_definition_mismatch"


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

    assert rejected.value.code == "referenced_payload_ingress_required"
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
        world.raw_repository.publish(
            signed,
            payload,
            referenced_payload=b"not a candidate",
        )

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
        world.raw_repository.publish(
            signed,
            payload,
            referenced_payload=candidate.canonical_bytes(),
        )

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

    assert rejected.value.code == "referenced_payload_ingress_required"
    assert world.raw_repository.commit_sequence() == before_sequence


def test_db_trigger_rejects_btst_signal_row_without_indexed_raw_binding(
    world: _World,
) -> None:
    record = world.service.produce_and_publish(_snapshot())[0]
    forged_id = f"{record.evidence.evidence_id}:unbound"
    forged = record.model_copy(
        update={"evidence": record.evidence.model_copy(update={"evidence_id": forged_id})}
    )

    with sqlite3.connect(world.database_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="referenced payload binding"):
            conn.execute(
                "INSERT INTO evidence_records (issuer_namespace, evidence_id,"
                " revision, evidence_kind, record_json, payload_content_hash,"
                " ingested_at, activated_at, commit_sequence,"
                " supersedes_revision, dependency_root)"
                " VALUES (?, ?, 1, 'signal', ?, ?, ?, ?, ?, NULL, ?)",
                (
                    "btst",
                    forged_id,
                    forged.model_dump_json(),
                    "f" * 64,
                    forged.ingested_at.isoformat(),
                    forged.ingested_at.isoformat(),
                    999,
                    "f" * 64,
                ),
            )


def test_authoritative_raw_hit_does_not_scan_evidence_history(
    world: _World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = world.service.produce_and_publish(_snapshot())[0]
    content_hash = record.evidence.payload_content_hash

    def fail_scan(*_args, **_kwargs):
        raise AssertionError("raw hit scanned evidence history")

    monkeypatch.setattr(
        world.raw_repository,
        "_committed_record_references",
        fail_scan,
        raising=False,
    )

    assert (
        hashlib.sha256(world.raw_repository.raw_payload(content_hash)).hexdigest()
        == content_hash
    )


def test_concurrent_identical_publish_converges_without_sqlite_error(
    world: _World,
) -> None:
    candidate = _build_payload(_candidate(), stage=SignalStage.SELECTED)
    raw = candidate.canonical_bytes()
    envelope = _envelope_for_candidate(world, candidate)
    signed, payload = _signed_signal(world, envelope)
    peer = EvidenceRepository(
        database_path=world.database_path,
        blob_store=world.blob_store,
        verifier=world.verifier,
        trust_head_provider=world.head_provider,
        issuer_namespace="btst",
        clock=world.clock,
    )
    barrier = threading.Barrier(2)

    def publish(repository: EvidenceRepository):
        barrier.wait()
        return repository.publish(
            signed,
            payload,
            referenced_payload=raw,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        records = tuple(executor.map(publish, (world.raw_repository, peer)))

    assert records[0].canonical_bytes() == records[1].canonical_bytes()
    assert world.raw_repository.commit_sequence() == 1


def test_publish_commits_authoritative_raw_bytes_before_external_blob_can_vanish(
    world: _World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _build_payload(_candidate(), stage=SignalStage.SELECTED)
    candidate_bytes = candidate.canonical_bytes()
    candidate_hash = world.raw_repository.persist_payload(candidate_bytes)
    envelope = _envelope_for_candidate(world, candidate)
    signed, payload = _signed_signal(world, envelope)
    candidate_path = world.blob_store.blob_path(candidate_hash)
    original_put = world.blob_store.put_durable

    def remove_candidate_after_validation(bytes_to_store: bytes) -> str:
        if bytes_to_store == payload and candidate_path.exists():
            os.unlink(candidate_path)
        return original_put(bytes_to_store)

    monkeypatch.setattr(
        world.blob_store,
        "put_durable",
        remove_candidate_after_validation,
    )

    record = world.raw_repository.publish(
        signed,
        payload,
        referenced_payload=candidate_bytes,
    )

    assert not candidate_path.exists()
    assert world.raw_repository.raw_payload(candidate_hash) == candidate_bytes
    assert (
        world.service.candidate_payload(
            record,
            expected_signal_session=SIGNAL_DATE,
        )
        == candidate
    )


def test_prepare_commits_authoritative_raw_bytes_before_external_blob_can_vanish(
    world: _World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = world.service.produce_and_publish(_snapshot())[0]
    original_candidate = world.service.candidate_payload(
        original,
        expected_signal_session=SIGNAL_DATE,
    )
    revised_candidate = original_candidate.model_copy(
        update={"target_weight_ppm": original_candidate.target_weight_ppm - 1}
    )
    revised_bytes = revised_candidate.canonical_bytes()
    revised_hash = world.raw_repository.persist_payload(revised_bytes)
    revised_envelope = original.evidence.model_copy(
        update={
            "payload_content_hash": revised_hash,
        }
    )
    signed, payload = _signed_signal(world, revised_envelope)
    revised_path = world.blob_store.blob_path(revised_hash)
    original_put = world.blob_store.put_durable

    def remove_candidate_after_validation(bytes_to_store: bytes) -> str:
        if bytes_to_store == payload and revised_path.exists():
            os.unlink(revised_path)
        return original_put(bytes_to_store)

    monkeypatch.setattr(
        world.blob_store,
        "put_durable",
        remove_candidate_after_validation,
    )

    prepared = world.raw_repository.prepare_revision(
        signed,
        payload,
        referenced_payload=revised_bytes,
    )
    world.raw_repository.activate_revision(original.evidence.evidence_id, 2)

    assert prepared.revision == 2
    assert not revised_path.exists()
    assert world.raw_repository.raw_payload(revised_hash) == revised_bytes


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
        update={"target_weight_ppm": original_candidate.target_weight_ppm - 1}
    )
    revised_hash = world.raw_repository.persist_payload(
        revised_candidate.canonical_bytes()
    )
    revised_envelope = original.evidence.model_copy(
        update={
            "payload_content_hash": revised_hash,
        }
    )
    signed, payload = _signed_signal(world, revised_envelope)
    world.raw_repository.prepare_revision(
        signed,
        payload,
        referenced_payload=revised_candidate.canonical_bytes(),
    )
    world.raw_repository.activate_revision(original.evidence.evidence_id, 2)

    historical_projection = world.raw_repository.get(
        original.evidence.evidence_id,
        revision=1,
    )
    replayed = world.service.candidate_payload(
        historical_projection,
        expected_signal_session=SIGNAL_DATE,
    )

    assert replayed == original_candidate


def test_candidate_reader_rejects_caller_owned_active_projection(
    world: _World,
) -> None:
    original = world.service.produce_and_publish(_snapshot())[0]
    original_candidate = world.service.candidate_payload(
        original,
        expected_signal_session=SIGNAL_DATE,
    )
    revised_candidate = original_candidate.model_copy(
        update={"target_weight_ppm": original_candidate.target_weight_ppm - 1}
    )
    revised_hash = world.raw_repository.persist_payload(
        revised_candidate.canonical_bytes()
    )
    revised_envelope = original.evidence.model_copy(
        update={
            "payload_content_hash": revised_hash,
        }
    )
    signed, payload = _signed_signal(world, revised_envelope)
    world.raw_repository.prepare_revision(
        signed,
        payload,
        referenced_payload=revised_candidate.canonical_bytes(),
    )
    world.raw_repository.activate_revision(original.evidence.evidence_id, 2)

    forged_active = original.model_copy(update={"active_revision": 1})
    assert forged_active.is_active
    with pytest.raises(Exception) as rejected:
        world.service.candidate_payload(
            forged_active,
            expected_signal_session=SIGNAL_DATE,
        )

    assert getattr(rejected.value, "code", None) == "signal_record_untrusted"


class TestCandidateIngestionWindow:
    """D6 (R48): 候选入库窗谓词是信封时间链的单一事实源。

    store 的时间线契约是双端闭 (``observed_at <= ingested_at <=
    available_at``); 驱动器首步守卫与 CLI pre-flight 必须消费与
    ``_signal_envelope`` 完全相同的派生, 不得各自复制常量。
    """

    def test_window_bounds_are_the_envelope_timestamps(self) -> None:
        from src.screening.offensive.v3.producers.auto import (
            _signal_envelope,
            candidate_ingestion_window,
        )

        window_open, window_close = candidate_ingestion_window(SIGNAL_DATE)
        assert window_open == datetime(2026, 8, 5, 15, 0, tzinfo=timezone.utc)
        assert window_close == datetime(2026, 8, 6, 15, 0, tzinfo=timezone.utc)
        assert window_close - window_open == timedelta(hours=24)

        envelope = _signal_envelope(
            snapshot=_snapshot(),
            candidate=_candidate(),
            stage=SignalStage.SELECTED,
            behavior_fingerprint=BTST_FINGERPRINT,
            strategy_semver=btst_producer.BTST_STRATEGY_SEMVER,
            producer_namespace=btst_producer.BTST_PRODUCER_NAMESPACE,
        )
        assert envelope.observed_at == window_open
        assert envelope.available_at == window_close
