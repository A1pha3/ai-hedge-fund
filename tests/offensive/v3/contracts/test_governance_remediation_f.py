"""Adversarial tests for Task 2 review remediation F."""

from __future__ import annotations

import json
import re

import pytest
from pydantic import TypeAdapter, ValidationError

from task2_hash_exemplars import task2_hash_exemplars
from test_governance import NOW, _trial
from test_governance_remediation_c import _approved_manifest, _unsigned_manifest


BUSINESS_INVALID_PROPOSALS = (
    (
        "MigrationApprovalManifest",
        {"target_broker_account_id": "wrong-account"},
    ),
    ("MigrationApprovalManifest", {"target_writer_fencing_epoch": 8}),
    ("BrokerEnablementManifest", {"issuer_capability": "governance.other.v1"}),
    ("BrokerEnablementManifest", {"expires_at": NOW}),
    ("DisasterRecoveryManifest", {"expires_at": NOW}),
    ("DisasterRecoveryManifest", {"reconcile_before_entry": False}),
    ("DisasterRecoveryManifest", {"recovery_epoch": 0}),
)


def _count_approval_preimage_hashes(
    monkeypatch: pytest.MonkeyPatch, model_type: type[object]
) -> list[object]:
    from src.screening.offensive.v3.contracts import governance

    observed_payloads: list[object] = []
    original_domain_hash = governance.domain_hash

    def observe_preimage_hash(domain: str, schema_major: int, payload: object) -> str:
        if domain == model_type.APPROVAL_PREIMAGE_DOMAIN:
            observed_payloads.append(payload)
        return original_domain_hash(domain, schema_major, payload)

    monkeypatch.setattr(governance, "domain_hash", observe_preimage_hash)
    return observed_payloads


@pytest.mark.parametrize(("model_name", "invalid_update"), BUSINESS_INVALID_PROPOSALS)
def test_business_invalid_proposal_fails_before_any_preimage_hash(
    monkeypatch: pytest.MonkeyPatch,
    model_name: str,
    invalid_update: dict[str, object],
) -> None:
    from src.screening.offensive.v3.contracts import governance

    model_type = getattr(governance, model_name)
    proposal = _unsigned_manifest(model_name) | invalid_update
    observed_payloads = _count_approval_preimage_hashes(monkeypatch, model_type)

    with pytest.raises(ValidationError):
        model_type.approval_preimage_hash_for_proposal(proposal)
    assert observed_payloads == []


@pytest.mark.parametrize(("model_name", "invalid_update"), BUSINESS_INVALID_PROPOSALS)
def test_signed_business_invalid_manifest_fails_before_any_preimage_hash(
    monkeypatch: pytest.MonkeyPatch,
    model_name: str,
    invalid_update: dict[str, object],
) -> None:
    from src.screening.offensive.v3.contracts import governance

    model_type = getattr(governance, model_name)
    payload = _approved_manifest(model_name) | invalid_update
    observed_payloads = _count_approval_preimage_hashes(monkeypatch, model_type)

    with pytest.raises(ValidationError):
        model_type.model_validate(payload)
    assert observed_payloads == []


@pytest.mark.parametrize(
    "model_name",
    (
        "MigrationApprovalManifest",
        "BrokerEnablementManifest",
        "DisasterRecoveryManifest",
    ),
)
def test_valid_unsigned_proposal_preimage_remains_deterministic(
    model_name: str,
) -> None:
    from src.screening.offensive.v3.contracts import governance

    model_type = getattr(governance, model_name)
    proposal = _unsigned_manifest(model_name)
    first = model_type.approval_preimage_hash_for_proposal(proposal)
    second = model_type.approval_preimage_hash_for_proposal(dict(proposal))
    assert first == second
    assert (
        first
        == model_type.model_validate(
            _approved_manifest(model_name)
        ).approval_preimage_hash()
    )


UNICODE_DECIMALS = (
    "٠.٥",
    "०.५",
    "０.５",
    "0.٥",
    "0.५",
    "0.５",
    "0.5٥",
)


@pytest.mark.parametrize("value", UNICODE_DECIMALS)
def test_exact_decimal_types_reject_all_unicode_digits(value: str) -> None:
    from src.screening.offensive.v3.contracts.governance import (
        ConfidenceLevel,
        ExactDecimal,
    )

    for decimal_type in (ExactDecimal, ConfidenceLevel):
        adapter = TypeAdapter(decimal_type)
        with pytest.raises(ValidationError):
            adapter.validate_python(value)
        with pytest.raises(ValidationError):
            adapter.validate_json(json.dumps(value))


def _sap_payload() -> dict[str, object]:
    return task2_hash_exemplars()["StatisticalAnalysisPlan"].model_dump(
        mode="python", round_trip=True
    )


@pytest.mark.parametrize("value", UNICODE_DECIMALS)
def test_trial_and_sap_json_reject_unicode_decimal_digits(value: str) -> None:
    from src.screening.offensive.v3.contracts.governance import (
        StatisticalAnalysisPlan,
        TrialManifest,
    )

    trial = json.loads(TrialManifest.model_validate(_trial()).model_dump_json())
    sap = json.loads(
        StatisticalAnalysisPlan.model_validate(_sap_payload()).model_dump_json()
    )
    poisoned_payloads = (
        (TrialManifest, trial | {"minimum_economic_effect": value}),
        (TrialManifest, trial | {"one_sided_confidence_level": value}),
        (StatisticalAnalysisPlan, sap | {"one_sided_confidence_level": value}),
    )
    for model_type, payload in poisoned_payloads:
        with pytest.raises(ValidationError):
            model_type.model_validate_json(json.dumps(payload))


def test_decimal_wire_schemas_use_ascii_digits_only() -> None:
    from src.screening.offensive.v3.contracts.governance import (
        ConfidenceLevel,
        ExactDecimal,
        StatisticalAnalysisPlan,
        TrialManifest,
    )

    exact_pattern = TypeAdapter(ExactDecimal).json_schema()["pattern"]
    confidence_pattern = TypeAdapter(ConfidenceLevel).json_schema()["pattern"]
    for pattern in (exact_pattern, confidence_pattern):
        assert r"\d" not in pattern
        assert re.fullmatch(pattern, "0.5")
        for value in UNICODE_DECIMALS:
            assert re.fullmatch(pattern, value) is None

    trial_schema = TrialManifest.model_json_schema()["properties"]
    sap_schema = StatisticalAnalysisPlan.model_json_schema()["properties"]
    assert trial_schema["minimum_economic_effect"]["pattern"] == exact_pattern
    assert trial_schema["one_sided_confidence_level"]["pattern"] == (confidence_pattern)
    assert sap_schema["one_sided_confidence_level"]["pattern"] == confidence_pattern
