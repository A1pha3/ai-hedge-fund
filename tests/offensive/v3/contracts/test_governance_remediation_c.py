"""Adversarial tests for Task 2 review remediation C."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
import json

import pytest
from pydantic import TypeAdapter, ValidationError

from test_authorization import HASH, _envelope, _grant
from test_governance import (
    NOW,
    _exploration_controls,
    _exploration_grant,
    _predecessor,
    _trial,
)
from test_governance_remediation_b import (
    HASH_B,
    HASH_C,
    _approval_attestations,
    _entry_fence,
    _manifest_common,
    _migration_manifest,
)


def _unsigned_manifest(model_name: str) -> dict[str, object]:
    if model_name == "MigrationApprovalManifest":
        payload = _migration_manifest()
    elif model_name == "BrokerEnablementManifest":
        payload = _manifest_common(
            "BROKER_ENABLEMENT_MANIFEST", "governance.broker.enablement.v1"
        ) | {
            "broker_account_fingerprint": HASH,
            "broker_environment_fingerprint": HASH,
            "base_currency": "CNY",
            "currency_definition_fingerprint": HASH,
            "trusted_clock_hash": HASH,
            "authenticated_raw_envelope_hash": HASH,
            "pagination_cursor_retention_hash": HASH,
            "client_order_idempotency_hash": HASH,
            "auction_tif_cutoff_hash": HASH,
            "exit_rate_limit_hash": HASH,
            "credential_session_network_fencing_hash": HASH,
        }
    else:
        payload = _manifest_common(
            "DISASTER_RECOVERY_MANIFEST", "governance.disaster.recovery.v1"
        ) | {
            "broker_account_fingerprint": HASH,
            "trust_bundle_hash": HASH,
            "registry_epoch": 2,
            "policy_activation_hash": HASH,
            "policy_epoch": 2,
            "authority_epoch": 2,
            "risk_epoch": 2,
            "authorization_status_hash": HASH,
            "authorization_status_version": 4,
            "entry_fence_hash": HASH,
            "entry_fence_version": 5,
            "backup_root_hash": HASH,
            "durable_inbox_cursor": "inbox-1",
            "durable_outbox_cursor": "outbox-1",
            "broker_cursor": "broker-1",
            "durable_cursor_proof_hash": HASH,
            "source_writer_id": "source-writer",
            "target_writer_id": "recovery-writer",
            "recovery_epoch": 2,
            "fencing_epoch": 2,
            "reconciliation_proof_hash": HASH,
            "reconcile_before_entry": True,
        }
    payload.pop("approval_attestations", None)
    return payload


def _approve_proposal(
    model_name: str, proposal: dict[str, object]
) -> dict[str, object]:
    from src.screening.offensive.v3.contracts import governance

    model = getattr(governance, model_name)
    preimage_hash = model.approval_preimage_hash_for_proposal(proposal)
    scope = {
        "MigrationApprovalManifest": "MIGRATION_APPROVAL_MANIFEST",
        "BrokerEnablementManifest": "BROKER_ENABLEMENT_MANIFEST",
        "DisasterRecoveryManifest": "DISASTER_RECOVERY_MANIFEST",
    }[model_name]
    approvals = tuple(
        approval | {"approved_manifest_preimage_hash": preimage_hash}
        for approval in _approval_attestations(scope)
    )
    return proposal | {"approval_attestations": approvals}


def _approved_manifest(model_name: str) -> dict[str, object]:
    return _approve_proposal(model_name, _unsigned_manifest(model_name))


@pytest.mark.parametrize(
    ("model_name", "tampered_field", "tampered_value"),
    [
        ("MigrationApprovalManifest", "source_capital_root_hash", HASH_B),
        ("BrokerEnablementManifest", "currency_definition_fingerprint", HASH_B),
        ("DisasterRecoveryManifest", "broker_cursor", "broker-2"),
    ],
)
def test_two_person_approvals_share_complete_manifest_preimage_and_detect_tamper(
    model_name: str, tampered_field: str, tampered_value: object
) -> None:
    from src.screening.offensive.v3.contracts import governance

    model = getattr(governance, model_name)
    payload = _approved_manifest(model_name)
    manifest = model.model_validate(payload)
    approved_hashes = {
        approval.approved_manifest_preimage_hash
        for approval in manifest.approval_attestations
    }
    assert approved_hashes == {manifest.approval_preimage_hash()}
    assert model.APPROVAL_PREIMAGE_DOMAIN != model.HASH_DOMAIN
    assert model.APPROVAL_PREIMAGE_DOMAIN.endswith(".v1")
    assert model.approval_preimage_hash_for_proposal(
        _unsigned_manifest(model_name)
    ) == (
        manifest.approval_preimage_hash()
    )
    with pytest.raises(ValidationError):
        model.model_validate(payload | {tampered_field: tampered_value})


def test_two_person_approvals_require_distinct_people_keys_and_artifacts() -> None:
    from src.screening.offensive.v3.contracts.governance import (
        BrokerEnablementManifest,
    )

    payload = _approved_manifest("BrokerEnablementManifest")
    approvals = payload["approval_attestations"]
    assert isinstance(approvals, tuple)
    for poisoned in (
        (approvals[0], approvals[1] | {"approver_id": "alice"}),
        (approvals[0], approvals[1] | {"key_id": "alice-key"}),
        (approvals[0], approvals[1] | {"approval_artifact_hash": HASH_B}),
        (
            approvals[0],
            approvals[1] | {"approved_manifest_preimage_hash": HASH_C},
        ),
    ):
        with pytest.raises(ValidationError):
            BrokerEnablementManifest.model_validate(
                payload | {"approval_attestations": poisoned}
            )


def test_exploration_grants_bind_declared_trial_but_edge_trial_stays_independent() -> None:
    from src.screening.offensive.v3.contracts.authorization import (
        AuthorizationKind,
        CapitalAuthorizationEnvelope,
    )

    exploration = _exploration_grant(trial_id="explore-trial")
    payload = _envelope(
        authorization_kind=AuthorizationKind.EXPLORATION,
        issuer_capability="governance.exploration.envelope.v1",
        lineage_grants=(exploration,),
        exploration_aggregate_gross_cap=Decimal("0.02"),
        portfolio_gross_cap=Decimal("0.02"),
        **_exploration_controls(),
    )
    assert CapitalAuthorizationEnvelope.model_validate(payload).exploration_trial_id == (
        "explore-trial"
    )
    with pytest.raises(ValidationError):
        CapitalAuthorizationEnvelope.model_validate(
            payload
            | {
                "lineage_grants": (
                    exploration | {"trial_id": "different-trial"},
                )
            }
        )

    edge = _grant(grant_id="edge", lineage_gross_cap=Decimal("0.01"))
    mixed = payload | {
        "lineage_grants": (edge, exploration),
        "portfolio_gross_cap": Decimal("0.02"),
        **_predecessor(),
    }
    assert CapitalAuthorizationEnvelope.model_validate(mixed).lineage_grants[0].trial_id == (
        "trial-1"
    )


@pytest.mark.parametrize(
    ("value", "rendered"),
    [
        (Decimal("0.0000001"), "0.0000001"),
        (Decimal("1E+3"), "1000"),
        (Decimal("1.2300"), "1.23"),
        (Decimal("-0"), "0"),
    ],
)
def test_exact_decimal_uses_expanded_canonical_json_and_roundtrips(
    value: Decimal, rendered: str
) -> None:
    from src.screening.offensive.v3.contracts.base import canonical_decimal_string
    from src.screening.offensive.v3.contracts.governance import Fraction, TrialManifest

    assert canonical_decimal_string(value) == rendered
    if value.is_zero():
        assert TypeAdapter(Fraction).validate_python(value) == Decimal("0")
        return
    field_name = "minimum_economic_effect"
    trial = TrialManifest.model_validate(_trial(**{field_name: value}))
    encoded = trial.model_dump_json()
    assert json.loads(encoded)[field_name] == rendered
    assert TrialManifest.model_validate_json(encoded) == trial


def test_entry_fence_acknowledgement_cannot_predate_raised_fence() -> None:
    from src.screening.offensive.v3.contracts.governance import (
        EntryFenceAcknowledgement,
        EntryFenceRaised,
    )

    fence = EntryFenceRaised.model_validate(_entry_fence())
    payload = {
        "acknowledgement_id": "fence-ack-1",
        "fence_id": fence.fence_id,
        "entry_fence_hash": fence.artifact_hash(),
        "fence_version": fence.fence_version,
        "portfolio_id": fence.portfolio_id,
        "broker_account_id": fence.broker_account_id,
        "broker_account_fingerprint": fence.broker_account_fingerprint,
        "mode": fence.mode,
        "authority_epoch": fence.authority_epoch,
        "risk_epoch": fence.risk_epoch,
        "authorization_status_hash": fence.predecessor_authorization_status_hash,
        "authorization_status_version": fence.authorization_status_version,
        "fence_raised_at": fence.raised_at,
        "durably_acknowledged_at": fence.raised_at,
        "gateway_writer_id": "capital-gateway-writer",
        "gateway_writer_version": 7,
        "gateway_fencing_epoch": 9,
        "issuer_id": "capital-gateway",
        "issuer_capability": "capital-gateway.entry-fence.acknowledge.v1",
        "schema_major": 2,
    }
    assert EntryFenceAcknowledgement.model_validate(payload).fence_raised_at == NOW
    with pytest.raises(ValidationError):
        EntryFenceAcknowledgement.model_validate(
            payload
            | {"durably_acknowledged_at": fence.raised_at - timedelta(microseconds=1)}
        )


@pytest.mark.parametrize("encoded", ["true", "3.0", '"3"'])
def test_exact_integer_json_rejects_bool_float_and_string(encoded: str) -> None:
    from src.screening.offensive.v3.contracts.base import ExactInteger

    with pytest.raises(ValidationError):
        TypeAdapter(ExactInteger).validate_json(encoded)


def test_authorization_lifecycle_is_exported_consistently() -> None:
    from src.screening.offensive.v3 import contracts
    from src.screening.offensive.v3.contracts import governance

    assert "AuthorizationLifecycle" in governance.__all__
    assert contracts.AuthorizationLifecycle is governance.AuthorizationLifecycle
    assert set(governance.__all__) <= set(contracts.__all__)
    assert all(getattr(contracts, name) is getattr(governance, name) for name in governance.__all__)


@pytest.mark.parametrize(
    ("source_schema_major", "target_schema_major"),
    [
        (1, 2),
        (1, 99),
        (2, 4),
        (3, 4),
        (2.0, 3),
        (2, 3.0),
        (True, 3),
        (2, True),
    ],
)
def test_migration_accepts_only_native_exact_v2_to_v3(
    source_schema_major: object, target_schema_major: object
) -> None:
    from src.screening.offensive.v3.contracts.governance import (
        MigrationApprovalManifest,
    )

    proposal = _unsigned_manifest("MigrationApprovalManifest") | {
        "source_schema_major": source_schema_major,
        "target_schema_major": target_schema_major,
    }
    payload = (
        _approved_manifest("MigrationApprovalManifest")
        | {
            "source_schema_major": source_schema_major,
            "target_schema_major": target_schema_major,
        }
        if type(source_schema_major) is float or type(target_schema_major) is float
        else _approve_proposal("MigrationApprovalManifest", proposal)
    )
    with pytest.raises(ValidationError):
        MigrationApprovalManifest.model_validate(payload)


@pytest.mark.parametrize(("source_epoch", "target_epoch"), [(8, 8), (8, 7)])
def test_migration_target_writer_fencing_epoch_must_advance(
    source_epoch: int, target_epoch: int
) -> None:
    from src.screening.offensive.v3.contracts.governance import (
        MigrationApprovalManifest,
    )

    proposal = _unsigned_manifest("MigrationApprovalManifest") | {
        "source_writer_fencing_epoch": source_epoch,
        "target_writer_fencing_epoch": target_epoch,
    }
    with pytest.raises(ValidationError):
        MigrationApprovalManifest.model_validate(
            _approve_proposal("MigrationApprovalManifest", proposal)
        )
