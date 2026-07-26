"""Adversarial tests for Task 2 review remediation D."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
import json

import pytest
from pydantic import TypeAdapter, ValidationError

from task2_hash_exemplars import task2_hash_exemplars
from test_governance import NOW, _trial
from test_governance_remediation_c import _approved_manifest, _unsigned_manifest


@pytest.mark.parametrize(
    ("model_name", "invalid_update"),
    [
        (
            "MigrationApprovalManifest",
            {"target_broker_account_id": "wrong-account"},
        ),
        ("BrokerEnablementManifest", {"one_shot": False}),
        ("DisasterRecoveryManifest", {"expires_at": NOW}),
    ],
)
def test_poisoned_manifest_instances_cannot_emit_any_public_digest(
    model_name: str, invalid_update: dict[str, object]
) -> None:
    from src.screening.offensive.v3.contracts import governance

    model_type = getattr(governance, model_name)
    valid = model_type.model_validate(_approved_manifest(model_name))
    poisoned_copy = valid.model_copy(update=invalid_update)
    constructed_payload = valid.model_dump(mode="python", round_trip=True) | (
        invalid_update
    )
    poisoned_construct = model_type.model_construct(**constructed_payload)

    for poisoned in (poisoned_copy, poisoned_construct):
        with pytest.raises(ValidationError):
            poisoned.artifact_hash()
        with pytest.raises(ValidationError):
            poisoned.approval_preimage_hash()


def test_public_unsigned_preimage_rejects_attestations_extra_and_missing_fields() -> None:
    from src.screening.offensive.v3.contracts.governance import (
        MigrationApprovalManifest,
    )

    unsigned = _unsigned_manifest("MigrationApprovalManifest")
    valid = MigrationApprovalManifest.model_validate(
        _approved_manifest("MigrationApprovalManifest")
    )
    assert MigrationApprovalManifest.approval_preimage_hash_for_proposal(
        unsigned
    ) == valid.approval_preimage_hash()

    with_attestations = valid.model_dump(mode="python", round_trip=True)
    extra = unsigned | {"unexpected": "field"}
    missing = dict(unsigned)
    missing.pop("source_capital_root_hash")
    for poisoned in (with_attestations, extra, missing):
        with pytest.raises(ValidationError):
            MigrationApprovalManifest.approval_preimage_hash_for_proposal(poisoned)


@pytest.mark.parametrize(
    "invalid_update",
    [
        {"source_schema_major": 1, "target_schema_major": 99},
        {"target_writer_fencing_epoch": 7},
        {"target_broker_account_id": "wrong-account"},
        {"allowed_until": NOW - timedelta(seconds=1)},
    ],
)
def test_public_unsigned_migration_preimage_validates_all_business_invariants(
    invalid_update: dict[str, object],
) -> None:
    from src.screening.offensive.v3.contracts.governance import (
        MigrationApprovalManifest,
    )

    proposal = _unsigned_manifest("MigrationApprovalManifest") | invalid_update
    with pytest.raises(ValidationError):
        MigrationApprovalManifest.approval_preimage_hash_for_proposal(proposal)


@pytest.mark.parametrize(
    ("model_name", "invalid_update"),
    [
        (
            "BrokerEnablementManifest",
            {"issuer_capability": "governance.other.v1"},
        ),
        ("BrokerEnablementManifest", {"one_shot": False}),
        ("DisasterRecoveryManifest", {"expires_at": NOW}),
        ("DisasterRecoveryManifest", {"reconcile_before_entry": False}),
    ],
)
def test_public_unsigned_preimage_validates_broker_and_dr_business_invariants(
    model_name: str, invalid_update: dict[str, object]
) -> None:
    from src.screening.offensive.v3.contracts import governance

    model_type = getattr(governance, model_name)
    proposal = _unsigned_manifest(model_name) | invalid_update
    with pytest.raises(ValidationError):
        model_type.approval_preimage_hash_for_proposal(proposal)


def _sap_payload() -> dict[str, object]:
    sap = task2_hash_exemplars()["StatisticalAnalysisPlan"]
    return sap.model_dump(mode="python", round_trip=True)


@pytest.mark.parametrize(
    ("model_name", "payload", "field_name"),
    [
        ("TrialManifest", _trial(), "one_sided_confidence_level"),
        (
            "StatisticalAnalysisPlan",
            _sap_payload(),
            "one_sided_confidence_level",
        ),
    ],
)
def test_confidence_level_is_strictly_inside_zero_and_one_in_python_and_json(
    model_name: str, payload: dict[str, object], field_name: str
) -> None:
    from src.screening.offensive.v3.contracts import governance

    model_type = getattr(governance, model_name)
    valid = model_type.model_validate(payload | {field_name: Decimal("0.95")})
    assert model_type.model_validate_json(valid.model_dump_json()) == valid

    for endpoint in (Decimal("0"), Decimal("1")):
        with pytest.raises(ValidationError):
            model_type.model_validate(payload | {field_name: endpoint})
    encoded = json.loads(valid.model_dump_json())
    for endpoint in ("0", "1"):
        poisoned = encoded | {field_name: endpoint}
        with pytest.raises(ValidationError):
            model_type.model_validate_json(json.dumps(poisoned))


def test_fraction_keeps_closed_endpoints_while_confidence_is_publicly_exported() -> None:
    from src.screening.offensive.v3 import contracts
    from src.screening.offensive.v3.contracts import governance
    from src.screening.offensive.v3.contracts.governance import (
        ConfidenceLevel,
        Fraction,
    )

    fraction = TypeAdapter(Fraction)
    confidence = TypeAdapter(ConfidenceLevel)
    for endpoint in (Decimal("0"), Decimal("1")):
        assert fraction.validate_python(endpoint) == endpoint
        with pytest.raises(ValidationError):
            confidence.validate_python(endpoint)
    assert confidence.validate_python(Decimal("0.95")) == Decimal("0.95")
    assert "ConfidenceLevel" in governance.__all__
    assert contracts.ConfidenceLevel is governance.ConfidenceLevel
