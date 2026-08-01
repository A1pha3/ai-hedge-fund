"""Second-review regressions for the Task 4 trust and PIT boundary."""

from __future__ import annotations

from base64 import b64encode
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any

import pytest
from pydantic import ValidationError


UTC = timezone.utc
NOW = datetime(2026, 7, 29, 8, 0, tzinfo=UTC)
ZERO_HASH = "0" * 64
EVIDENCE_RECORD_HASH_DOMAIN = "ai-hedge-fund.v3.evidence.store-record.v1"


def _r1_signed_values(api: Any, **overrides: Any) -> dict[str, Any]:
    payload = b"{}"
    values = {
        "issuer_id": "legacy-issuer",
        "key_id": "legacy-key",
        "schema_major": 1,
        "artifact": api.ArtifactKind.PLAN,
        "namespace": "legacy.plan",
        "mode": api.ExecutionMode.DAILY_BAR_PROXY,
        "capability_version": "legacy.plan.v1",
        "capability_scope": "portfolio:paper-v3",
        "payload_hash": hashlib.sha256(payload).hexdigest(),
        "payload": payload,
        "signature": b64encode(b"\0" * 64).decode("ascii"),
    }
    values.update(overrides)
    return values


def test_revision1_trust_wire_is_local_and_exactly_major_one() -> None:
    from src.screening.offensive.v3.contracts import revision1
    from src.screening.offensive.v3.contracts import trust as current

    assert {item.value for item in revision1.ArtifactKind} == {
        "snapshot",
        "signal",
        "outcome",
        "plan",
        "edge",
        "exploration",
        "decision_seal",
        "shadow_decision",
        "execution_permit",
    }
    assert revision1.ArtifactKind is not current.ArtifactKind
    assert revision1.Capability is not current.Capability
    assert revision1.SignedEnvelope is not current.SignedEnvelope
    assert revision1.VerifiedIssuer is not current.VerifiedIssuer

    with pytest.raises(ValidationError, match="Revision 1|schema major"):
        revision1.SignedEnvelope(**_r1_signed_values(revision1, schema_major=2))
    with pytest.raises(ValidationError, match="artifact|ArtifactKind"):
        revision1.SignedEnvelope(
            **_r1_signed_values(
                revision1,
                artifact=current.ArtifactKind.RECOVERY_AUTHORIZATION,
            )
        )


def test_revision1_authorization_and_ports_do_not_alias_revision2() -> None:
    from src.screening.offensive.v3.contracts import revision1
    from src.screening.offensive.v3.contracts import authorization as current
    from src.screening.offensive.v3.contracts import ports as current_ports

    assert {
        "EdgeAuthorization",
        "ExplorationAuthorization",
        "CapitalAuthorization",
    } <= set(revision1.__all__)
    assert {
        "AuthorizationKind",
        "CapitalAuthorizationEnvelope",
        "LineageGrant",
        "ProgramLossBudgetBinding",
    }.isdisjoint(revision1.__all__)
    assert not hasattr(revision1, "CapitalAuthorizationEnvelope")
    assert revision1.CapitalAuthorization is not current.CapitalAuthorizationEnvelope
    assert revision1.CapabilityVerifier is not current_ports.CapabilityVerifier
    assert revision1.CapitalViewPort is not current_ports.CapitalViewPort


@pytest.mark.parametrize(
    ("artifact_name", "issuer_kind_name"),
    [
        ("RISK_EPOCH_STARTED", "GOVERNANCE"),
        ("TRIAL_MANIFEST", "GOVERNANCE"),
        ("STATISTICAL_ANALYSIS_PLAN", "GOVERNANCE"),
        ("STAGE_MANIFEST", "GOVERNANCE"),
        ("AUTHORIZATION_STATUS", "CAPITAL_GATEWAY"),
        ("ENTRY_FENCE_RAISED", "DEPENDENCY_TRACKER"),
        ("ENTRY_FENCE_ACKNOWLEDGEMENT", "CAPITAL_GATEWAY"),
        ("MIGRATION_APPROVAL_MANIFEST", "GOVERNANCE"),
        ("BROKER_ENABLEMENT_MANIFEST", "GOVERNANCE"),
        ("DISASTER_RECOVERY_MANIFEST", "GOVERNANCE"),
    ],
)
def test_every_independently_signed_control_artifact_has_a_major_two_role_route(
    artifact_name: str,
    issuer_kind_name: str,
) -> None:
    from tests.offensive.v3.contracts.test_task4_review_fixes import _trust_context

    context = _trust_context(
        artifact_name=artifact_name,
        issuer_kind_name=issuer_kind_name,
        schema_major=2,
    )
    verified = context.verifier.verify(
        context.envelope,
        context.capability,
        current_head=context.head,
        trusted_at=NOW,
    )

    assert verified.capability.artifact.value
    assert verified.capability.schema_major == 2


@pytest.mark.parametrize(
    ("artifact_name", "wrong_issuer_kind"),
    [
        ("RISK_EPOCH_STARTED", "AUTHORIZER"),
        ("AUTHORIZATION_STATUS", "GOVERNANCE"),
        ("ENTRY_FENCE_RAISED", "CAPITAL_GATEWAY"),
    ],
)
def test_new_control_artifacts_reject_wrong_roles(
    artifact_name: str,
    wrong_issuer_kind: str,
) -> None:
    from tests.offensive.v3.contracts.test_task4_review_fixes import _trust_context

    context = _trust_context(
        artifact_name=artifact_name,
        issuer_kind_name=wrong_issuer_kind,
    )
    with pytest.raises(context.api.TrustVerificationError, match="cannot sign"):
        context.verifier.verify(
            context.envelope,
            context.capability,
            current_head=context.head,
            trusted_at=NOW,
        )


def test_new_control_artifacts_reject_legacy_schema_major() -> None:
    from tests.offensive.v3.contracts.test_task4_review_fixes import _trust_context

    context = _trust_context(
        artifact_name="RISK_EPOCH_STARTED",
        issuer_kind_name="GOVERNANCE",
        schema_major=1,
    )
    with pytest.raises(context.api.TrustVerificationError, match="schema major"):
        context.verifier.verify(
            context.envelope,
            context.capability,
            current_head=context.head,
            trusted_at=NOW,
        )


def test_embedded_bindings_do_not_invent_independent_artifact_authorities() -> None:
    from src.screening.offensive.v3 import trust

    artifact_names = set(trust.ArtifactKind.__members__)
    assert {
        "LINEAGE_GRANT",
        "PROGRAM_LOSS_BUDGET_BINDING",
        "APPROVAL_ATTESTATION_BINDING",
    }.isdisjoint(artifact_names)


@pytest.mark.parametrize(
    "created_at",
    [
        NOW + timedelta(minutes=1),
        NOW + timedelta(minutes=3),
    ],
)
def test_plan_cannot_be_created_after_its_trusted_observation(
    created_at: datetime,
) -> None:
    from src.screening.offensive.v3 import contracts as api
    from tests.offensive.v3.contracts.checkpoint2_helpers import _plan

    raw = _plan(api).model_dump(mode="python", round_trip=True)
    raw.update(
        {
            "observed_at": NOW,
            "available_at": NOW + timedelta(minutes=2),
            "created_at": created_at,
        }
    )

    with pytest.raises(ValidationError, match="created_at.*observed_at"):
        api.PlanEvidence.model_validate(raw, strict=True)


def _verify_policy_candidate(
    policy: Any,
    signed: Any,
    required: Any,
    verifier: Any,
) -> Any:
    from src.screening.offensive.v3 import policy as policy_api
    from src.screening.offensive.v3 import trust
    from tests.offensive.v3.contracts.test_policy import _current_trust_head

    return policy_api.verify_policy_activation(
        signed,
        policy,
        verifier,
        required,
        current_trust_head=_current_trust_head(verifier),
        trusted_at=NOW,
        predecessor=None,
        expected_portfolio_id="paper-v3",
        expected_broker_account_id="manual-account-1",
        expected_broker_account_fingerprint=None,
        expected_mode=trust.ExecutionMode.MANUAL_CONFIRMED,
    )


def test_verified_issuer_exposes_complete_effective_validity_start() -> None:
    from tests.offensive.v3.contracts.test_task4_review_fixes import _trust_context

    context = _trust_context()
    verified = context.verifier.verify(
        context.envelope,
        context.capability,
        current_head=context.head,
        trusted_at=NOW,
    )

    assert verified.valid_from == context.genesis.bundle.issued_at


def test_policy_candidate_cannot_backdate_before_issuer_authority() -> None:
    from src.screening.offensive.v3 import policy as policy_api
    from tests.offensive.v3.contracts.test_policy import _signed_policy_activation

    policy, _, signed, required, verifier = _signed_policy_activation(
        activation_updates={"effective_from": NOW - timedelta(minutes=11)}
    )
    with pytest.raises(
        policy_api.PolicyActivationVerificationError,
        match="effective_from.*issuer|authority.*valid",
    ):
        _verify_policy_candidate(policy, signed, required, verifier)


def test_future_policy_candidate_verifies_without_becoming_active() -> None:
    from tests.offensive.v3.contracts.test_policy import _signed_policy_activation

    policy, activation, signed, required, verifier = _signed_policy_activation(
        activation_updates={"effective_from": NOW + timedelta(minutes=10)}
    )
    verified = _verify_policy_candidate(policy, signed, required, verifier)

    assert verified.activation == activation
    assert verified.activation.effective_from > verified.trusted_at
    assert not hasattr(verified, "activate")


def _independent_domain_hash(domain: str, schema_major: int, payload: Any) -> str:
    encoded = json.dumps(
        {
            "domain": domain,
            "payload": payload.model_dump(mode="json", round_trip=True),
            "schema_major": schema_major,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_evidence_record_has_an_independently_recomputed_artifact_hash() -> None:
    from src.screening.offensive.v3 import contracts as api
    from tests.offensive.v3.contracts.checkpoint2_helpers import _proposal

    record = _proposal(api).order_lines[0].plan_evidence
    expected = _independent_domain_hash(
        EVIDENCE_RECORD_HASH_DOMAIN,
        record.evidence.schema_major,
        record,
    )

    assert record.HASH_DOMAIN == EVIDENCE_RECORD_HASH_DOMAIN
    assert record.artifact_hash() == expected
    assert record.content_hash() == expected


def test_evidence_record_hash_is_separate_from_an_equal_field_domain() -> None:
    from src.screening.offensive.v3 import contracts as api
    from tests.offensive.v3.contracts.checkpoint2_helpers import _proposal

    class UnrelatedEqualFieldRecord(api.CanonicalModel):
        evidence: api.PlanEvidence
        ingested_at: datetime
        commit_sequence: int
        revision: int
        supersedes_revision: int | None
        active_revision: int

    record = _proposal(api).order_lines[0].plan_evidence
    unrelated = UnrelatedEqualFieldRecord.model_validate(
        record.model_dump(mode="python", round_trip=True),
        strict=True,
    )

    assert record.content_hash() != unrelated.content_hash()


def test_current_head_cannot_be_observed_before_bundle_issuance() -> None:
    from tests.offensive.v3.contracts.test_task4_review_fixes import _trust_context

    context = _trust_context()
    premature = context.head.model_copy(
        update={
            "observed_at": context.genesis.bundle.issued_at - timedelta(microseconds=1)
        }
    )

    with pytest.raises(
        context.api.TrustVerificationError,
        match="observed_at.*issu|issu.*observed_at",
    ):
        context.verifier.verify(
            context.envelope,
            context.capability,
            current_head=premature,
            trusted_at=NOW,
        )


def test_active_policy_predecessor_witness_rejects_genesis_sentinel() -> None:
    from src.screening.offensive.v3 import policy
    from src.screening.offensive.v3 import trust

    with pytest.raises(ValidationError, match="active.*hash|zero.*sentinel"):
        policy.ActivePolicyActivationWitness(
            active_policy_activation_hash=ZERO_HASH,
            portfolio_id="paper-v3",
            broker_account_id=None,
            broker_account_fingerprint=None,
            mode=trust.ExecutionMode.DAILY_BAR_PROXY,
            trust_bundle_hash="a" * 64,
            registry_epoch=1,
            policy_epoch=1,
            authority_epoch=1,
            risk_epoch=1,
            effective_from=NOW - timedelta(minutes=1),
            store_version=1,
            observed_at=NOW,
        )
