"""BTST raw-candidate evidence is durable, exact, and replay-verifiable."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path

import pytest

from src.screening.offensive.daily_action_service import PlanCandidate
from src.screening.offensive.setups.base import DetectionResult
from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup
from src.screening.offensive.v3.contracts.base import SignalStage
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
    assert getattr(wrong_identity.value, "code", None) == "candidate_identity_mismatch"


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
