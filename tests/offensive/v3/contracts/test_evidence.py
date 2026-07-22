"""Contract tests for immutable v3 market, signal, and outcome evidence."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError


UTC = timezone.utc
HASH = "a" * 64


def _contracts():
    try:
        from src.screening.offensive.v3.contracts.evidence import (
            SUPPORTED_SCHEMA_MAJOR,
            EvidenceEnvelope,
            OutcomeEvidence,
            SignalEvidence,
            SnapshotEvidence,
        )
    except ModuleNotFoundError:
        pytest.fail("evidence contracts are not implemented", pytrace=False)
    return (
        SUPPORTED_SCHEMA_MAJOR,
        EvidenceEnvelope,
        SnapshotEvidence,
        SignalEvidence,
        OutcomeEvidence,
    )


def _envelope(**overrides):
    from src.screening.offensive.v3.contracts.base import EvidenceScope, ExecutionMode

    payload = {
        "evidence_id": "ev-001",
        "subject_scope": EvidenceScope.STRATEGY_LINEAGE,
        "subject_producer": "btst",
        "family_id": "btst.limit-up-breakout",
        "strategy_semver": "3.0.0",
        "behavior_fingerprint": HASH,
        "policy_epoch": 7,
        "execution_version": "t1-open-t10-open.v1",
        "cost_version": "cn-a-share-costs.v1",
        "effective_at": datetime(2026, 7, 20, 1, 30, tzinfo=UTC),
        "observed_at": datetime(2026, 7, 19, 8, 1, tzinfo=UTC),
        "available_at": datetime(2026, 7, 19, 8, 2, tzinfo=UTC),
        "mode": ExecutionMode.DAILY_BAR_PROXY,
        "source_authority": "exchange-calendar",
        "payload_content_hash": HASH,
        "schema_major": 1,
    }
    payload.update(overrides)
    return payload


def test_envelope_has_exact_required_keys_and_supports_future_effective_facts() -> None:
    major, envelope, *_ = _contracts()
    item = envelope.model_validate(_envelope(schema_major=major))

    assert set(envelope.model_fields) == {
        "evidence_id",
        "subject_scope",
        "subject_producer",
        "family_id",
        "strategy_semver",
        "behavior_fingerprint",
        "policy_epoch",
        "execution_version",
        "cost_version",
        "effective_at",
        "observed_at",
        "available_at",
        "mode",
        "source_authority",
        "payload_content_hash",
        "schema_major",
    }
    assert item.effective_at > item.available_at


def test_envelope_rejects_unknown_schema_major_and_late_observation() -> None:
    major, envelope, *_ = _contracts()

    with pytest.raises(ValidationError, match="schema major"):
        envelope.model_validate(_envelope(schema_major=major + 1))
    with pytest.raises(ValidationError, match="observed_at"):
        envelope.model_validate(
            _envelope(
                schema_major=major,
                observed_at=datetime(2026, 7, 19, 8, 3, tzinfo=UTC),
            )
        )


def test_subject_scope_and_family_id_are_typed_together() -> None:
    from src.screening.offensive.v3.contracts.base import EvidenceScope

    major, envelope, *_ = _contracts()

    global_item = envelope.model_validate(
        _envelope(
            schema_major=major,
            subject_scope=EvidenceScope.GLOBAL,
            family_id=None,
        )
    )
    assert global_item.family_id is None

    with pytest.raises(ValidationError, match="GLOBAL"):
        envelope.model_validate(
            _envelope(schema_major=major, subject_scope=EvidenceScope.GLOBAL)
        )
    with pytest.raises(ValidationError, match="STRATEGY_LINEAGE"):
        envelope.model_validate(_envelope(schema_major=major, family_id=None))
    with pytest.raises(ValidationError, match="at least 1 character"):
        envelope.model_validate(_envelope(schema_major=major, family_id=""))


def test_execution_mode_is_strict_and_not_coerced_from_text() -> None:
    major, envelope, *_ = _contracts()

    with pytest.raises(ValidationError):
        envelope.model_validate(
            _envelope(schema_major=major, mode="daily_bar_proxy")
        )


@pytest.mark.parametrize(
    ("index", "extra"),
    [
        (2, {"evidence_kind": "snapshot"}),
        (3, {"evidence_kind": "signal", "stage": "selected"}),
        (4, {"evidence_kind": "outcome"}),
    ],
)
def test_producer_evidence_cannot_claim_execution_authority(index, extra) -> None:
    from src.screening.offensive.v3.contracts.base import SignalStage

    contracts = _contracts()
    model = contracts[index]
    if "stage" in extra:
        extra["stage"] = SignalStage.SELECTED
    raw = _envelope(schema_major=contracts[0]) | extra | {
        "execution_authorized": True
    }
    with pytest.raises(ValidationError, match="extra_forbidden"):
        model.model_validate(raw)


def test_signal_stage_and_evidence_discriminators_are_exact() -> None:
    from src.screening.offensive.v3.contracts.base import SignalStage

    major, _, snapshot, signal, outcome = _contracts()
    base = _envelope(schema_major=major)

    assert snapshot.model_validate(base | {"evidence_kind": "snapshot"}).evidence_kind == "snapshot"
    selected = signal.model_validate(
        base | {"evidence_kind": "signal", "stage": SignalStage.SELECTED}
    )
    assert selected.stage is SignalStage.SELECTED
    assert outcome.model_validate(base | {"evidence_kind": "outcome"}).evidence_kind == "outcome"
    with pytest.raises(ValidationError):
        signal.model_validate(
            base | {"evidence_kind": "signal", "stage": "selected"}
        )
