"""Completeness gates for the static Revision 2 public-contract snapshots."""

from __future__ import annotations

import base64
from enum import Enum
import hashlib
import importlib
import inspect
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel
import pytest

from src.screening.offensive.v3.contracts.base import CanonicalModel, domain_hash
from src.screening.offensive.v3.contracts.evidence import EvidenceRecord
from tests.offensive.v3.contracts.revision2_snapshot_exemplars import (
    alias_snapshot,
    compact_json_bytes,
    enum_snapshot,
    independent_domain_hash,
    port_snapshot,
    resolve_name,
    schema_snapshot,
    sha256_json,
)
from tests.offensive.v3.contracts.revision2_snapshot_registry import (
    ARTIFACT_HASH_CASES,
    EVIDENCE_RECORD_SPECIALIZATIONS,
    EXCLUDED_MODEL_TYPES,
    PROTECTED_PREIMAGE_CASES,
    PUBLIC_ALIASES,
    PUBLIC_ENUMS,
    PUBLIC_MODEL_CASES,
    PUBLIC_PORTS,
    WIRE_MODEL_EXCEPTIONS,
)


FIXTURE_ROOT = Path(__file__).with_name("fixtures") / "revision2"
REQUIRED_SNAPSHOT_FIXTURES = (
    "public_model_schemas.json",
    "public_model_hashes.json",
    "public_types.json",
    "port_signatures.json",
    "protected_hashes.json",
)
MODEL_MODULES = (
    "src.screening.offensive.v3.contracts.authorization",
    "src.screening.offensive.v3.contracts.base",
    "src.screening.offensive.v3.contracts.btst_candidate",
    "src.screening.offensive.v3.contracts.capital",
    "src.screening.offensive.v3.contracts.compatibility",
    "src.screening.offensive.v3.contracts.decision",
    "src.screening.offensive.v3.contracts.evidence",
    "src.screening.offensive.v3.contracts.execution",
    "src.screening.offensive.v3.contracts.governance",
    "src.screening.offensive.v3.contracts.regime",
    "src.screening.offensive.v3.contracts.trial",
    "src.screening.offensive.v3.contracts.trust",
    "src.screening.offensive.v3.policy.models",
    "src.screening.offensive.v3.trust.registry",
)
ENUM_MODULES = MODEL_MODULES + ("src.screening.offensive.v3.contracts.risk",)


def _fixture(name: str) -> Any:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def _defined_subclasses(base: type[Any], modules: tuple[str, ...]) -> set[str]:
    found: set[str] = set()
    for module_name in modules:
        module = importlib.import_module(module_name)
        for value in vars(module).values():
            if (
                inspect.isclass(value)
                and value.__module__ == module_name
                and issubclass(value, base)
            ):
                found.add(f"{module_name}.{value.__qualname__}")
    return found


def test_static_inventory_cardinality_is_explicit() -> None:
    assert len(PUBLIC_MODEL_CASES) == 109
    assert len(PUBLIC_ENUMS) == 48
    assert len(PUBLIC_ALIASES) == 11
    assert len(PUBLIC_PORTS) == 6
    assert len(ARTIFACT_HASH_CASES) == 32
    assert len(EVIDENCE_RECORD_SPECIALIZATIONS) == 4


@pytest.mark.parametrize("fixture_name", REQUIRED_SNAPSHOT_FIXTURES)
def test_required_snapshot_fixture_is_checked_in(fixture_name: str) -> None:
    fixture_path = FIXTURE_ROOT / fixture_name
    assert fixture_path.is_file(), f"missing literal snapshot fixture: {fixture_path}"


def test_runtime_model_discovery_is_only_an_unclassified_contract_alarm() -> None:
    discovered = _defined_subclasses(BaseModel, MODEL_MODULES)
    discovered |= set(EVIDENCE_RECORD_SPECIALIZATIONS)
    registered_runtime = set(PUBLIC_MODEL_CASES)

    assert set(EXCLUDED_MODEL_TYPES) <= discovered
    assert not (set(EXCLUDED_MODEL_TYPES) & registered_runtime)
    assert discovered == registered_runtime | set(EXCLUDED_MODEL_TYPES)


def test_bare_evidence_record_is_forbidden_and_exact_specializations_are_typed() -> (
    None
):
    bare_name = "src.screening.offensive.v3.contracts.evidence.EvidenceRecord"
    assert bare_name in EXCLUDED_MODEL_TYPES
    assert bare_name not in PUBLIC_MODEL_CASES
    assert len(EVIDENCE_RECORD_SPECIALIZATIONS) == 4
    for name in EVIDENCE_RECORD_SPECIALIZATIONS:
        specialization = resolve_name(name)
        assert specialization is not EvidenceRecord
        assert issubclass(specialization, EvidenceRecord)


def test_snapshot_fixture_registries_are_exact_and_have_no_orphans() -> None:
    schemas = _fixture("public_model_schemas.json")
    hashes = _fixture("public_model_hashes.json")
    public_types = _fixture("public_types.json")
    ports = _fixture("port_signatures.json")
    protected = _fixture("protected_hashes.json")

    assert set(schemas) == set(PUBLIC_MODEL_CASES)
    assert set(hashes) == set(PUBLIC_MODEL_CASES)
    assert set(public_types) == {"aliases", "enums"}
    assert set(public_types["aliases"]) == set(PUBLIC_ALIASES)
    assert set(public_types["enums"]) == set(PUBLIC_ENUMS)
    assert set(ports) == set(PUBLIC_PORTS)
    assert set(protected) == set(PROTECTED_PREIMAGE_CASES)


@pytest.mark.parametrize("qualified_name", PUBLIC_MODEL_CASES)
def test_every_public_dto_has_a_full_schema_golden(qualified_name: str) -> None:
    expected = _fixture("public_model_schemas.json")[qualified_name]
    model_type = resolve_name(qualified_name)
    actual = {
        "model_module": model_type.__module__,
        "model_name": model_type.__name__,
    } | schema_snapshot(model_type)

    assert actual == expected
    assert expected["fields"] == list(model_type.model_fields)
    assert expected["schema_sha256"] == sha256_json(expected["schema"])
    assert "additionalProperties" in expected["schema"]


@pytest.mark.parametrize("qualified_name", PUBLIC_MODEL_CASES)
def test_every_public_dto_has_a_fixed_strict_json_roundtrip_and_hash(
    qualified_name: str,
) -> None:
    expected = _fixture("public_model_hashes.json")[qualified_name]
    model_type = resolve_name(qualified_name)
    payload = expected["payload"]
    encoded = compact_json_bytes(payload)

    parsed = model_type.model_validate_json(encoded, strict=True)

    assert type(parsed) is model_type
    assert parsed.model_dump(mode="json") == payload
    assert expected["json_payload_sha256"] == hashlib.sha256(encoded).hexdigest()
    assert expected["model_module"] == model_type.__module__
    assert expected["model_name"] == model_type.__name__
    if qualified_name in WIRE_MODEL_EXCEPTIONS:
        assert not isinstance(parsed, CanonicalModel)
        assert "content_hash" not in expected
        assert "canonical_payload_sha256" not in expected
    else:
        assert isinstance(parsed, CanonicalModel)
        assert (
            expected["canonical_payload_sha256"]
            == hashlib.sha256(parsed.canonical_bytes()).hexdigest()
        )
        assert parsed.content_hash() == expected["content_hash"]


def test_artifact_hash_registry_is_exact_for_public_model_cases() -> None:
    actual = {
        name
        for name in PUBLIC_MODEL_CASES
        if callable(getattr(resolve_name(name), "artifact_hash", None))
    }
    assert actual == set(ARTIFACT_HASH_CASES)


@pytest.mark.parametrize("qualified_name", ARTIFACT_HASH_CASES)
def test_artifact_hashes_use_independently_recomputed_domain_preimages(
    qualified_name: str,
) -> None:
    expected = _fixture("public_model_hashes.json")[qualified_name]
    artifact = expected["artifact_hash"]
    model_type = resolve_name(qualified_name)
    model = model_type.model_validate_json(
        compact_json_bytes(expected["payload"]), strict=True
    )

    independently_recomputed = independent_domain_hash(
        domain=artifact["domain"],
        schema_major=artifact["schema_major"],
        payload=expected["payload"],
    )

    assert model_type.HASH_DOMAIN == artifact["domain"]
    assert independently_recomputed == artifact["sha256"]
    assert model.artifact_hash() == independently_recomputed
    assert model.content_hash() == expected["content_hash"]


def test_enum_runtime_discovery_and_literal_snapshots_are_exact() -> None:
    discovered = _defined_subclasses(Enum, ENUM_MODULES)
    expected = _fixture("public_types.json")["enums"]

    assert discovered == set(PUBLIC_ENUMS)
    assert {
        name: enum_snapshot(resolve_name(name)) for name in PUBLIC_ENUMS
    } == expected


def test_named_aliases_remain_separate_exported_contracts() -> None:
    from src.screening.offensive.v3 import contracts

    expected = _fixture("public_types.json")["aliases"]
    actual = {name: alias_snapshot(resolve_name(name)) for name in PUBLIC_ALIASES}

    assert actual == expected
    assert len(actual) == 11
    assert len(set(actual)) == 11
    assert {name.rpartition(".")[2] for name in PUBLIC_ALIASES} <= set(
        contracts.__all__
    )


def test_final_public_protocol_set_and_signatures_are_exact() -> None:
    from src.screening.offensive.v3.contracts import ports

    discovered = {
        f"{ports.__name__}.{name}"
        for name in ports.__all__
        if inspect.isclass(getattr(ports, name))
        and bool(getattr(getattr(ports, name), "_is_protocol", False))
    }
    expected = _fixture("port_signatures.json")
    actual = {name: port_snapshot(resolve_name(name)) for name in PUBLIC_PORTS}

    assert discovered == set(PUBLIC_PORTS)
    assert actual == expected
    assert all(item["is_protocol"] for item in expected.values())
    assert all(item["is_runtime_protocol"] for item in expected.values())


def test_all_protected_preimage_literals_have_independent_stdlib_hashes() -> None:
    protected = _fixture("protected_hashes.json")
    for expected in protected.values():
        assert (
            hashlib.sha256(compact_json_bytes(expected["preimage"])).hexdigest()
            == expected["sha256"]
        )


def test_signed_envelope_and_trust_bundle_preimages_are_frozen() -> None:
    from src.screening.offensive.v3 import trust

    hashes = _fixture("public_model_hashes.json")
    protected = _fixture("protected_hashes.json")
    signed_type = resolve_name(
        "src.screening.offensive.v3.contracts.trust.SignedEnvelope"
    )
    signed = signed_type.model_validate_json(
        compact_json_bytes(
            hashes["src.screening.offensive.v3.contracts.trust.SignedEnvelope"][
                "payload"
            ]
        ),
        strict=True,
    )
    signed_bundle_type = resolve_name(
        "src.screening.offensive.v3.trust.registry.SignedTrustBundle"
    )
    signed_bundle = signed_bundle_type.model_validate_json(
        compact_json_bytes(
            hashes["src.screening.offensive.v3.trust.registry.SignedTrustBundle"][
                "payload"
            ]
        ),
        strict=True,
    )

    assert signed._protected_signing_input() == compact_json_bytes(
        protected["signed_envelope_signing_input"]["preimage"]
    )
    assert trust.trust_bundle_signature_preimage(
        signed_bundle.bundle, signed_bundle.registry
    ) == compact_json_bytes(protected["trust_bundle_signature_preimage"]["preimage"])


def test_issuer_policy_and_behavior_fingerprint_preimages_are_frozen() -> None:
    from src.screening.offensive.v3 import policy

    hashes = _fixture("public_model_hashes.json")
    protected = _fixture("protected_hashes.json")
    issuer_payload = hashes["src.screening.offensive.v3.trust.registry.TrustedIssuer"][
        "payload"
    ]
    identity = protected["issuer_identity_fingerprint"]
    public_key_fingerprint = hashlib.sha256(
        base64.b64decode(issuer_payload["public_key"], validate=True)
    ).hexdigest()

    assert public_key_fingerprint == identity["public_key_fingerprint"]
    assert identity["identity_fingerprint"] == domain_hash(
        identity["domain"],
        identity["preimage"]["schema_major"],
        identity["preimage"]["payload"],
    )

    policy_name = "src.screening.offensive.v3.policy.models.PolicySnapshot"
    producer_name = "src.screening.offensive.v3.policy.models.ProducerIdentity"
    policy_model = resolve_name(policy_name).model_validate_json(
        compact_json_bytes(hashes[policy_name]["payload"]), strict=True
    )
    producer = resolve_name(producer_name).model_validate_json(
        compact_json_bytes(hashes[producer_name]["payload"]), strict=True
    )
    assert (
        policy_model.policy_fingerprint
        == protected["policy_fingerprint"]["fingerprint"]
    )
    assert (
        policy.behavior_fingerprint(producer, policy_model)
        == protected["behavior_fingerprint"]["fingerprint"]
    )


@pytest.mark.parametrize(
    ("model_name", "protected_name"),
    (
        ("MigrationApprovalManifest", "migration_approval_preimage"),
        ("BrokerEnablementManifest", "broker_enablement_approval_preimage"),
        ("DisasterRecoveryManifest", "disaster_recovery_approval_preimage"),
    ),
)
def test_two_person_manifest_approval_preimages_are_frozen(
    model_name: str, protected_name: str
) -> None:
    qualified_name = "src.screening.offensive.v3.contracts.governance." + model_name
    hashes = _fixture("public_model_hashes.json")
    expected = _fixture("protected_hashes.json")[protected_name]
    model_type = resolve_name(qualified_name)
    model = model_type.model_validate_json(
        compact_json_bytes(hashes[qualified_name]["payload"]), strict=True
    )

    assert model_type.APPROVAL_PREIMAGE_DOMAIN == expected["domain"]
    assert model.approval_preimage_hash() == expected["approval_preimage_hash"]
    assert model.approval_preimage_hash() == expected["sha256"]


def test_literal_fixtures_contain_no_private_key_or_seed_material() -> None:
    for fixture_name in REQUIRED_SNAPSHOT_FIXTURES:
        fixture_text = (FIXTURE_ROOT / fixture_name).read_text(encoding="utf-8").lower()
        assert '"private_key"' not in fixture_text
        assert '"private-key"' not in fixture_text
        assert '"private_seed"' not in fixture_text
        assert '"secret_seed"' not in fixture_text
