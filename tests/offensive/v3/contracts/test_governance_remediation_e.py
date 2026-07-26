"""Adversarial tests for Task 2 review remediation E."""

from __future__ import annotations

from decimal import Decimal
import json
import re

import pytest
from pydantic import TypeAdapter, ValidationError

from test_authorization import _grant
from test_governance_remediation_c import _approved_manifest, _unsigned_manifest


EXACT_TRUE_INVALID_PYTHON = (1, 1.0, Decimal("1"), "true", False)


@pytest.mark.parametrize(
    ("model_name", "field_name"),
    [
        ("MigrationApprovalManifest", "one_shot"),
        ("BrokerEnablementManifest", "one_shot"),
        ("DisasterRecoveryManifest", "one_shot"),
        ("DisasterRecoveryManifest", "reconcile_before_entry"),
    ],
)
@pytest.mark.parametrize("invalid", EXACT_TRUE_INVALID_PYTHON)
def test_public_proposal_rejects_non_exact_true_before_preimage_hash(
    monkeypatch: pytest.MonkeyPatch,
    model_name: str,
    field_name: str,
    invalid: object,
) -> None:
    from src.screening.offensive.v3.contracts import governance

    model_type = getattr(governance, model_name)
    proposal = _unsigned_manifest(model_name) | {field_name: invalid}
    original_domain_hash = governance.domain_hash
    preimage_calls = 0

    def observe_preimage_hash(domain: str, schema_major: int, payload: object) -> str:
        nonlocal preimage_calls
        if domain == model_type.APPROVAL_PREIMAGE_DOMAIN:
            preimage_calls += 1
        return original_domain_hash(domain, schema_major, payload)

    monkeypatch.setattr(governance, "domain_hash", observe_preimage_hash)
    with pytest.raises(ValidationError):
        model_type.approval_preimage_hash_for_proposal(proposal)
    assert preimage_calls == 0


@pytest.mark.parametrize(
    ("model_name", "field_name"),
    [
        ("MigrationApprovalManifest", "one_shot"),
        ("BrokerEnablementManifest", "one_shot"),
        ("DisasterRecoveryManifest", "one_shot"),
        ("DisasterRecoveryManifest", "reconcile_before_entry"),
    ],
)
@pytest.mark.parametrize("invalid", EXACT_TRUE_INVALID_PYTHON)
def test_signed_manifest_python_rejects_non_exact_true(
    model_name: str,
    field_name: str,
    invalid: object,
) -> None:
    from src.screening.offensive.v3.contracts import governance

    model_type = getattr(governance, model_name)
    payload = _approved_manifest(model_name) | {field_name: invalid}
    with pytest.raises(ValidationError):
        model_type.model_validate(payload)


@pytest.mark.parametrize(
    ("model_name", "field_name"),
    [
        ("MigrationApprovalManifest", "one_shot"),
        ("BrokerEnablementManifest", "one_shot"),
        ("DisasterRecoveryManifest", "one_shot"),
        ("DisasterRecoveryManifest", "reconcile_before_entry"),
    ],
)
@pytest.mark.parametrize("invalid", (1, 1.0, "true", False))
def test_signed_manifest_json_rejects_non_exact_true(
    model_name: str,
    field_name: str,
    invalid: object,
) -> None:
    from src.screening.offensive.v3.contracts import governance

    model_type = getattr(governance, model_name)
    valid = model_type.model_validate(_approved_manifest(model_name))
    payload = json.loads(valid.model_dump_json()) | {field_name: invalid}
    with pytest.raises(ValidationError):
        model_type.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize("valid", (2, 5, 10))
def test_capital_tier_accepts_only_allowed_native_ints(valid: int) -> None:
    from src.screening.offensive.v3.contracts.governance import LineageGrant

    grant = LineageGrant.model_validate(_grant(capital_tier=valid))
    assert grant.capital_tier == valid
    assert type(grant.capital_tier) is int
    assert LineageGrant.model_validate_json(grant.model_dump_json()) == grant


@pytest.mark.parametrize("invalid", (True, False, 2.0, Decimal("2"), "2"))
def test_capital_tier_rejects_non_native_ints_in_python(invalid: object) -> None:
    from src.screening.offensive.v3.contracts.governance import LineageGrant

    with pytest.raises(ValidationError):
        LineageGrant.model_validate(_grant(capital_tier=invalid))


@pytest.mark.parametrize("invalid", (True, False, 2.0, "2"))
def test_capital_tier_rejects_non_native_ints_in_json(invalid: object) -> None:
    from src.screening.offensive.v3.contracts.governance import LineageGrant

    valid = LineageGrant.model_validate(_grant())
    payload = json.loads(valid.model_dump_json()) | {"capital_tier": invalid}
    with pytest.raises(ValidationError):
        LineageGrant.model_validate_json(json.dumps(payload))


def test_confidence_wire_schema_exactly_describes_open_unit_interval() -> None:
    from src.screening.offensive.v3.contracts.governance import (
        ConfidenceLevel,
        Fraction,
        StatisticalAnalysisPlan,
        TrialManifest,
    )

    confidence_schema = TypeAdapter(ConfidenceLevel).json_schema()
    fraction_schema = TypeAdapter(Fraction).json_schema()
    pattern = confidence_schema["pattern"]
    assert confidence_schema["type"] == "string"
    assert confidence_schema != fraction_schema
    for value in ("0.95", "0.0001", "0.9999", "0.950"):
        assert re.fullmatch(pattern, value)
        assert (
            TypeAdapter(ConfidenceLevel).validate_json(json.dumps(value))
            == Decimal(value).normalize()
        )
    for value in (
        "0",
        "0.0",
        "1",
        "1.0",
        "-0.1",
        "1.0001",
        "2",
        "1e-1",
        ".95",
        "00.95",
    ):
        assert re.fullmatch(pattern, value) is None
        with pytest.raises(ValidationError):
            TypeAdapter(ConfidenceLevel).validate_json(json.dumps(value))

    for model_type in (TrialManifest, StatisticalAnalysisPlan):
        field_schema = model_type.model_json_schema()["properties"][
            "one_sided_confidence_level"
        ]
        assert field_schema["pattern"] == pattern
        assert field_schema["pattern"] != fraction_schema["pattern"]
