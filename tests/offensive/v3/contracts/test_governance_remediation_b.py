"""Adversarial tests for Task 2 review remediation B."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import TypeAdapter, ValidationError

from src.screening.offensive.v3.contracts.base import ExecutionMode

from test_governance import HASH, NOW

HASH_B = "b" * 64
HASH_C = "c" * 64


def _approval_attestations(scope: str) -> tuple[dict[str, object], ...]:
    return (
        {
            "approver_id": "alice",
            "key_id": "alice-key",
            "approval_artifact_hash": HASH_B,
            "approval_capability": "governance.manifest.approve.v1",
            "approval_scope": scope,
            "approved_at": NOW - timedelta(minutes=2),
            "schema_major": 2,
        },
        {
            "approver_id": "bob",
            "key_id": "bob-key",
            "approval_artifact_hash": HASH_C,
            "approval_capability": "governance.manifest.approve.v1",
            "approval_scope": scope,
            "approved_at": NOW - timedelta(minutes=1),
            "schema_major": 2,
        },
    )


def _manifest_common(scope: str, capability: str) -> dict[str, object]:
    return {
        "manifest_id": f"{scope.lower()}-1",
        "portfolio_id": "portfolio-1",
        "broker_account_id": "account-1",
        "issued_at": NOW,
        "expires_at": NOW + timedelta(hours=1),
        "one_shot": True,
        "approval_attestations": _approval_attestations(scope),
        "issuer_id": "governance",
        "issuer_capability": capability,
        "schema_major": 2,
    }


def _migration_manifest() -> dict[str, object]:
    return _manifest_common(
        "MIGRATION_APPROVAL_MANIFEST", "governance.migration.approval.v1"
    ) | {
        "source_portfolio_id": "legacy-portfolio",
        "target_portfolio_id": "portfolio-1",
        "source_broker_account_id": "legacy-account",
        "target_broker_account_id": "account-1",
        "source_schema_major": 2,
        "target_schema_major": 3,
        "source_writer_id": "v2-writer",
        "target_writer_id": "v3-writer",
        "migration_program_hash": HASH,
        "allowed_from": NOW,
        "allowed_until": NOW + timedelta(minutes=30),
        "source_trust_bundle_hash": HASH,
        "target_trust_bundle_hash": HASH_B,
        "source_registry_epoch": 2,
        "target_registry_epoch": 3,
        "source_policy_activation_hash": HASH,
        "target_policy_activation_hash": HASH_B,
        "source_policy_epoch": 2,
        "target_policy_epoch": 3,
        "source_authority_epoch": 2,
        "target_authority_epoch": 3,
        "source_risk_epoch": 2,
        "target_risk_epoch": 3,
        "source_capital_root_hash": HASH,
        "target_capital_root_hash": HASH_B,
        "source_capital_version": 20,
        "target_capital_version": 1,
        "source_stream_root_hash": HASH,
        "target_stream_root_hash": HASH_B,
        "source_stream_version": 20,
        "target_stream_version": 1,
        "source_active_authorization_id": "v2-auth",
        "target_active_authorization_id": "v3-auth",
        "source_active_authorization_version": 5,
        "target_active_authorization_version": 1,
        "source_active_authorization_envelope_hash": HASH,
        "target_active_authorization_envelope_hash": HASH_B,
        "source_active_authorization_status_hash": HASH,
        "target_active_authorization_status_hash": HASH_B,
        "source_active_authorization_status_version": 5,
        "target_active_authorization_status_version": 1,
        "source_entry_fence_version": 4,
        "target_entry_fence_version": 1,
        "source_entry_fence_hash": HASH,
        "target_entry_fence_hash": HASH_B,
        "source_writer_fencing_epoch": 8,
        "target_writer_fencing_epoch": 9,
        "shared_inbox_cursor": "shared-1",
        "handoff_cursor": "handoff-1",
        "conservation_formula_hash": HASH,
        "live_order_adoption_hash": HASH,
        "credential_fencing_hash": HASH,
        "rollback_dr_hash": HASH,
    }


def _authorization_status(**overrides: object) -> dict[str, object]:
    from src.screening.offensive.v3.contracts.governance import (
        AuthorizationLifecycle,
    )

    payload: dict[str, object] = {
        "portfolio_id": "portfolio-1",
        "broker_account_id": "account-1",
        "broker_account_fingerprint": HASH,
        "mode": ExecutionMode.BROKER_CONFIRMED,
        "authorization_id": "auth-1",
        "authorization_version": 2,
        "authorization_envelope_hash": HASH,
        "evidence_set_merkle_root": HASH,
        "authorization_issued_at": NOW - timedelta(minutes=3),
        "authorization_expires_at": NOW + timedelta(hours=1),
        "policy_activation_hash": HASH,
        "trust_bundle_hash": HASH,
        "registry_epoch": 2,
        "policy_epoch": 2,
        "authority_epoch": 2,
        "risk_epoch": 2,
        "status_version": 3,
        "predecessor_status_hash": HASH,
        "status": AuthorizationLifecycle.REVALIDATION_REQUIRED,
        "entry_fence_version": 4,
        "activated_at": NOW - timedelta(minutes=2),
        "status_effective_at": NOW - timedelta(minutes=1),
        "status_reason": "evidence revision",
        "status_cause_hash": HASH_B,
        "as_of": NOW,
        "issuer_id": "authority-store",
        "issuer_capability": "gateway.authority-store.authorization-status.publish.v1",
        "schema_major": 2,
    }
    return payload | overrides


def _entry_fence(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "fence_id": "fence-1",
        "portfolio_id": "portfolio-1",
        "broker_account_id": "account-1",
        "broker_account_fingerprint": HASH,
        "mode": ExecutionMode.BROKER_CONFIRMED,
        "fence_version": 4,
        "predecessor_fence_hash": HASH,
        "trust_bundle_hash": HASH,
        "registry_epoch": 2,
        "policy_activation_hash": HASH,
        "policy_epoch": 2,
        "authority_epoch": 2,
        "risk_epoch": 2,
        "predecessor_authorization_status_hash": HASH,
        "authorization_status_version": 3,
        "reason": "evidence revision",
        "cause_revision_id": "revision-1",
        "cause_revision_hash": HASH,
        "raised_at": NOW,
        "affected_authorization_id": "auth-1",
        "affected_authorization_version": 2,
        "affected_authorization_envelope_hash": HASH,
        "affected_evidence_set_merkle_root": HASH,
        "issuer_id": "dependency-tracker",
        "issuer_capability": "dependency-tracker.entry-fence.raise.v1",
        "schema_major": 2,
    }
    return payload | overrides


def test_exact_integer_is_semantically_neutral_and_rejects_numeric_coercion() -> None:
    from src.screening.offensive.v3.contracts.base import ExactInteger

    adapter = TypeAdapter(ExactInteger)
    assert adapter.validate_python(3) == 3
    for invalid in (True, 3.0, "3"):
        with pytest.raises(ValidationError):
            adapter.validate_python(invalid)


def test_authorization_status_requires_authority_store_issuer_and_state_time_proof():
    from src.screening.offensive.v3.contracts.governance import AuthorizationStatus

    status = AuthorizationStatus.model_validate(_authorization_status())
    assert status.activated_at <= status.status_effective_at <= status.as_of
    for omitted in ("issuer_id", "issuer_capability", "activated_at"):
        poisoned = _authorization_status()
        poisoned.pop(omitted)
        with pytest.raises(ValidationError):
            AuthorizationStatus.model_validate(poisoned)
    with pytest.raises(ValidationError):
        AuthorizationStatus.model_validate(
            _authorization_status(issuer_capability="authorizer.edge.envelope.v1")
        )
    with pytest.raises(ValidationError):
        AuthorizationStatus.model_validate(
            _authorization_status(activated_at=NOW + timedelta(seconds=1))
        )


def test_authorization_status_applies_conservative_state_specific_fields() -> None:
    from src.screening.offensive.v3.contracts.governance import (
        AuthorizationLifecycle,
        AuthorizationStatus,
    )

    active = _authorization_status(
        status=AuthorizationLifecycle.ACTIVE,
        activated_at=NOW - timedelta(minutes=1),
        status_effective_at=NOW - timedelta(minutes=1),
        status_reason=None,
        status_cause_hash=None,
    )
    assert AuthorizationStatus.model_validate(active).status.value == "ACTIVE"
    with pytest.raises(ValidationError):
        AuthorizationStatus.model_validate(
            active | {"status_effective_at": NOW, "status_reason": "late"}
        )
    with pytest.raises(ValidationError):
        AuthorizationStatus.model_validate(
            active | {"authorization_expires_at": NOW}
        )
    for state in (
        AuthorizationLifecycle.REVALIDATION_REQUIRED,
        AuthorizationLifecycle.REVOKED,
    ):
        with pytest.raises(ValidationError):
            AuthorizationStatus.model_validate(
                _authorization_status(
                    status=state, status_reason=None, status_cause_hash=None
                )
            )
    expired = _authorization_status(
        status=AuthorizationLifecycle.EXPIRED,
        authorization_expires_at=NOW - timedelta(minutes=1),
        status_effective_at=NOW - timedelta(minutes=1),
        status_reason=None,
        status_cause_hash=None,
    )
    assert AuthorizationStatus.model_validate(expired).status.value == "EXPIRED"
    with pytest.raises(ValidationError):
        AuthorizationStatus.model_validate(
            expired | {"status_effective_at": NOW - timedelta(seconds=30)}
        )
    revoked_after_expiry = _authorization_status(
        status=AuthorizationLifecycle.REVOKED,
        authorization_expires_at=NOW - timedelta(seconds=1),
        status_effective_at=NOW - timedelta(minutes=1),
    )
    assert AuthorizationStatus.model_validate(revoked_after_expiry).status.value == (
        "REVOKED"
    )


def test_entry_fence_request_and_gateway_ack_are_distinct_capabilities() -> None:
    from src.screening.offensive.v3.contracts.governance import (
        EntryFenceAcknowledgement,
        EntryFenceRaised,
    )

    fence = EntryFenceRaised.model_validate(_entry_fence())
    assert fence.issuer_id == "dependency-tracker"
    with pytest.raises(ValidationError):
        EntryFenceRaised.model_validate(
            _entry_fence(
                issuer_capability="capital-gateway.entry-fence.acknowledge.v1"
            )
        )

    acknowledgement = {
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
        "durably_acknowledged_at": NOW + timedelta(seconds=1),
        "gateway_writer_id": "capital-gateway-writer",
        "gateway_writer_version": 7,
        "gateway_fencing_epoch": 9,
        "issuer_id": "capital-gateway",
        "issuer_capability": "capital-gateway.entry-fence.acknowledge.v1",
        "schema_major": 2,
    }
    ack = EntryFenceAcknowledgement.model_validate(acknowledgement)
    assert ack.entry_fence_hash == fence.artifact_hash()
    with pytest.raises(ValidationError):
        EntryFenceAcknowledgement.model_validate(
            acknowledgement
            | {"issuer_capability": "dependency-tracker.entry-fence.raise.v1"}
        )


def test_risk_epoch_freezes_governed_predecessor_authorization_and_fence_context():
    from src.screening.offensive.v3.contracts.governance import RiskEpochStarted

    payload = {
        "portfolio_id": "portfolio-1",
        "broker_account_id": "account-1",
        "broker_account_fingerprint": HASH,
        "mode": ExecutionMode.BROKER_CONFIRMED,
        "predecessor_risk_epoch_hash": HASH,
        "predecessor_authority_epoch_hash": HASH,
        "trust_bundle_hash": HASH,
        "registry_epoch": 2,
        "policy_activation_hash": HASH,
        "policy_epoch": 2,
        "risk_epoch": 3,
        "authority_epoch": 3,
        "predecessor_active_authorization_id": "auth-1",
        "predecessor_active_authorization_version": 2,
        "predecessor_active_authorization_hash": HASH,
        "predecessor_authorization_status_hash": HASH,
        "predecessor_authorization_status_version": 4,
        "predecessor_entry_fence_version": 5,
        "predecessor_entry_fence_hash": HASH,
        "audited_capital_snapshot_id": "capital-1",
        "audited_capital_snapshot_hash": HASH,
        "inherited_risk_hash": HASH,
        "issued_at": NOW,
        "issuer_id": "governance",
        "issuer_capability": "governance.risk.epoch.start.v1",
        "schema_major": 2,
    }
    assert RiskEpochStarted.model_validate(payload).risk_epoch == 3
    for omitted in (
        "trust_bundle_hash",
        "policy_activation_hash",
        "predecessor_authorization_status_hash",
        "predecessor_entry_fence_hash",
    ):
        poisoned = dict(payload)
        poisoned.pop(omitted)
        with pytest.raises(ValidationError):
            RiskEpochStarted.model_validate(poisoned)


def test_migration_allows_exact_2_to_3_and_requires_full_source_target_cas() -> None:
    from src.screening.offensive.v3.contracts.governance import (
        MigrationApprovalManifest,
    )

    manifest = MigrationApprovalManifest.model_validate(_migration_manifest())
    assert (manifest.source_schema_major, manifest.target_schema_major) == (2, 3)
    for field_name in (
        "source_trust_bundle_hash",
        "target_policy_activation_hash",
        "source_capital_root_hash",
        "target_stream_root_hash",
        "source_active_authorization_status_hash",
        "target_entry_fence_hash",
        "source_writer_fencing_epoch",
    ):
        poisoned = _migration_manifest()
        poisoned.pop(field_name)
        with pytest.raises(ValidationError):
            MigrationApprovalManifest.model_validate(poisoned)
    for invalid in (True, 2.0, "2"):
        with pytest.raises(ValidationError):
            MigrationApprovalManifest.model_validate(
                _migration_manifest() | {"source_schema_major": invalid}
            )


def test_broker_and_dr_manifests_bind_currency_governance_and_cursor_proof() -> None:
    from src.screening.offensive.v3.contracts.governance import (
        BrokerEnablementManifest,
        DisasterRecoveryManifest,
    )

    broker = _manifest_common(
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
    assert BrokerEnablementManifest.model_validate(broker).base_currency == "CNY"
    with pytest.raises(ValidationError):
        poisoned = dict(broker)
        poisoned.pop("currency_definition_fingerprint")
        BrokerEnablementManifest.model_validate(poisoned)

    dr = _manifest_common(
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
    assert DisasterRecoveryManifest.model_validate(dr).durable_cursor_proof_hash == HASH
    with pytest.raises(ValidationError):
        poisoned = dict(dr)
        poisoned.pop("durable_cursor_proof_hash")
        DisasterRecoveryManifest.model_validate(poisoned)


@pytest.mark.parametrize(
    ("model_name", "payload"),
    [
        ("MigrationApprovalManifest", _migration_manifest()),
        (
            "BrokerEnablementManifest",
            _manifest_common(
                "BROKER_ENABLEMENT_MANIFEST", "governance.broker.enablement.v1"
            )
            | {
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
            },
        ),
    ],
)
def test_sensitive_manifests_require_signed_distinct_canonical_approvals(
    model_name: str, payload: dict[str, object]
) -> None:
    from src.screening.offensive.v3.contracts import governance

    model = getattr(governance, model_name)
    assert len(model.model_validate(payload).approval_attestations) == 2
    bare_ids = dict(payload)
    bare_ids.pop("approval_attestations")
    bare_ids["approver_ids"] = ("alice", "bob")
    with pytest.raises(ValidationError):
        model.model_validate(bare_ids)
    approvals = list(payload["approval_attestations"])
    for poisoned_approvals in (
        tuple(reversed(approvals)),
        (approvals[0], approvals[1] | {"approver_id": "alice"}),
        (approvals[0], approvals[1] | {"approval_artifact_hash": HASH_B}),
        (approvals[0], approvals[1] | {"approved_at": NOW + timedelta(seconds=1)}),
        (approvals[0], approvals[1] | {"approval_scope": "WRONG_SCOPE"}),
    ):
        with pytest.raises(ValidationError):
            model.model_validate(payload | {"approval_attestations": poisoned_approvals})


def test_task2_artifact_hashes_are_model_scoped_and_caller_cannot_choose_domain():
    from src.screening.offensive.v3.contracts.governance import (
        ApprovalAttestationBinding,
        TrustBundle,
    )

    approval = ApprovalAttestationBinding.model_validate(
        _approval_attestations("MIGRATION_APPROVAL_MANIFEST")[0]
    )
    trust = TrustBundle.model_validate(
        {
            "registry_epoch": 2,
            "predecessor_bundle_hash": HASH,
            "root_hash": HASH,
            "root_key_id": "root-key",
            "trusted_issuer_registry_hash": HASH,
            "issued_at": NOW,
            "expires_at": NOW + timedelta(hours=1),
            "revoked_at": None,
            "issuer_id": "root",
            "issuer_capability": "root.trust.bundle.v1",
            "schema_major": 2,
        }
    )
    assert approval.HASH_DOMAIN != trust.HASH_DOMAIN
    assert approval.artifact_hash() != trust.artifact_hash()
    with pytest.raises(TypeError):
        approval.artifact_hash("caller-chosen-domain")
