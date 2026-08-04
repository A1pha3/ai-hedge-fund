"""RED contracts for cancelling an unclaimed prior ALLOW permit/outbox."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from tests.offensive.v3.contracts.checkpoint2_helpers import (
    HASH_A,
    HASH_F,
    PERMIT_DEADLINE,
    PERMIT_EXPIRES,
    _active_permit_evaluation_state,
    _api,
    _cancellation_binding,
    _gateway_issuer,
    _permit,
    _permit_evaluation_state,
    _permit_line,
    _receipt,
    _receipt_clock_observation,
    _seal,
)


def test_entry_cancellation_receipt_has_independent_exact_public_schema() -> None:
    api = _api()
    assert api.ArtifactKind.ENTRY_CANCELLATION_RECEIPT.value == (
        "entry_cancellation_receipt"
    )
    assert set(api.EntryCancellationReceipt.model_fields) == {
        "artifact_kind",
        "artifact_namespace",
        "schema_major",
        "cancellation_receipt_id",
        "reason_code",
        "prior_permit",
        "prior_permit_artifact_hash",
        "permit_id",
        "permit_nonce",
        "permit_nonce_sequence",
        "logical_key",
        "evaluation_state",
        "cancellation_binding",
        "cancellation_clock_observation",
        "cancelled_at",
        "issuer_binding",
    }
    assert api.EntryCancellationReceipt.__module__ == (
        "src.screening.offensive.v3.contracts.execution"
    )


def test_valid_expired_unclaimed_allow_receipt_is_replayable_and_isolated() -> None:
    api = _api()
    receipt = _receipt(api)
    assert receipt.artifact_namespace == "capital-gateway.entry-cancellation.v1"
    assert receipt.reason_code is api.PermitReasonCode.DEADLINE_CANCEL
    assert receipt.prior_permit.disposition is api.PermitDisposition.ALLOW
    assert receipt.cancellation_binding.post_permit_nonce_state is (
        api.PermitNonceState.INVALIDATED
    )
    assert receipt.cancellation_binding.post_outbox_state is api.OutboxState.TOMBSTONED
    assert receipt.artifact_hash() != receipt.prior_permit.artifact_hash()
    for foreign in (
        api.ExecutionPermit,
        api.PortfolioDecisionSeal,
        api.ShadowDecision,
    ):
        with pytest.raises(ValidationError):
            foreign.model_validate(receipt.model_dump(mode="python", round_trip=True))
    with pytest.raises(ValidationError):
        api.EntryCancellationReceipt.model_validate(
            receipt.prior_permit.model_dump(mode="python", round_trip=True)
        )


def test_receipt_rejects_prior_cancel_instead_of_allow() -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(
        api,
        seal,
        authorization_lifecycle=api.AuthorizationLifecycle.REVOKED,
        authorization_status_version=seal.authorization_status_version + 1,
        authorization_status_hash=HASH_A,
    )
    lines = tuple(
        _permit_line(
            api,
            line,
            disposition=api.PermitDisposition.CANCEL,
            permitted_quantity=0,
            reason_code=api.PermitReasonCode.AUTHORIZATION_CANCEL,
        )
        for line in seal.proposal.order_lines
    )
    prior_cancel = _permit(
        api,
        seal=seal,
        disposition=api.PermitDisposition.CANCEL,
        evaluation_state=current,
        permit_lines=lines,
    )
    with pytest.raises(ValidationError, match="prior|ALLOW|permit"):
        _receipt(api, prior_permit=prior_cancel)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("active_permit_id", "other-permit"),
        ("active_permit_artifact_hash", HASH_F),
        ("active_permit_nonce", "other-nonce"),
        ("active_permit_nonce_sequence", 2),
        ("active_outbox_state", "TOMBSTONED"),
    ],
)
def test_receipt_requires_exact_active_prior_permit_and_outbox(field, value) -> None:
    api = _api()
    prior = _permit(api)
    with pytest.raises(
        ValidationError, match="active|permit|nonce|outbox|payload|artifact|durable"
    ):
        current = _active_permit_evaluation_state(api, prior, **{field: value})
        _receipt(api, prior_permit=prior, evaluation_state=current)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("active_outbox_batch_id", "other-outbox"),
        ("active_outbox_payload_hash", HASH_F),
    ],
)
def test_current_durable_outbox_drift_can_be_tombstoned_as_fact_integrity(
    field,
    value,
) -> None:
    api = _api()
    prior = _permit(api)
    event_at = PERMIT_EXPIRES + timedelta(seconds=1)
    current = _active_permit_evaluation_state(
        api,
        prior,
        **{field: value},
        authorization_revalidation=prior.evaluation_state.authorization_revalidation.model_copy(
            update={
                "verified_at": event_at,
                "valid_until": event_at + timedelta(minutes=1),
            }
        ),
    )

    receipt = _receipt(
        api,
        prior_permit=prior,
        evaluation_state=current,
        reason_code=api.PermitReasonCode.FACT_INTEGRITY_CANCEL,
    )

    assert receipt.cancellation_binding.outbox_batch_id == (
        current.active_outbox_batch_id
    )
    assert receipt.cancellation_binding.outbox_payload_hash == (
        current.active_outbox_payload_hash
    )
    assert receipt.cancellation_binding.post_outbox_state is api.OutboxState.TOMBSTONED


def test_receipt_rejects_already_send_claimed_entry() -> None:
    api = _api()
    prior = _permit(api)
    current = _active_permit_evaluation_state(
        api,
        prior,
        active_send_claim_state=api.ActiveEntryClaimState.SEND_CLAIMED,
        send_claim_sequence=1,
    )
    with pytest.raises(ValidationError, match="SEND_CLAIMED|claim|unclaimed"):
        _receipt(api, prior_permit=prior, evaluation_state=current)


@pytest.mark.parametrize(
    "cancelled_at",
    [PERMIT_EXPIRES, PERMIT_EXPIRES - timedelta(microseconds=1)],
)
def test_deadline_receipt_requires_healthy_time_strictly_after_send_deadline(
    cancelled_at,
) -> None:
    api = _api()
    observation = _receipt_clock_observation(api, wall_clock_utc=cancelled_at)
    with pytest.raises(ValidationError, match="deadline|strictly after|expired|clock"):
        _receipt(
            api,
            cancellation_clock_observation=observation,
            cancelled_at=cancelled_at,
        )


def test_unhealthy_clock_uses_fact_reason_and_monotonic_order_not_deadline() -> None:
    api = _api()
    observation = _receipt_clock_observation(
        api,
        wall_clock_utc=PERMIT_DEADLINE,
        clock_health=api.ClockHealth.ROLLBACK_DETECTED,
    )
    receipt = _receipt(
        api,
        reason_code=api.PermitReasonCode.FACT_INTEGRITY_CANCEL,
        cancellation_clock_observation=observation,
        cancelled_at=PERMIT_DEADLINE,
    )
    assert receipt.reason_code is api.PermitReasonCode.FACT_INTEGRITY_CANCEL
    with pytest.raises(ValidationError, match="deadline|healthy|clock|reason"):
        _receipt(
            api,
            reason_code=api.PermitReasonCode.DEADLINE_CANCEL,
            cancellation_clock_observation=observation,
            cancelled_at=PERMIT_DEADLINE,
        )
    regressed = observation.model_copy(
        update={
            "monotonic_observation_ns": (
                receipt.prior_permit.permit_clock_observation.monotonic_observation_ns
            )
        }
    )
    with pytest.raises(ValidationError, match="monotonic|sequence|later"):
        _receipt(
            api,
            reason_code=api.PermitReasonCode.FACT_INTEGRITY_CANCEL,
            cancellation_clock_observation=regressed,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("permit_nonce", "other-nonce"),
        ("post_permit_nonce_sequence", 1),
        ("post_permit_nonce_state", "ACTIVE"),
        ("released_cash_cents", 1),
        ("remaining_reserved_cash_cents", 1),
        ("outbox_batch_id", "other-outbox"),
        ("outbox_payload_hash", HASH_F),
        ("post_outbox_state", "DURABLE"),
    ],
)
def test_receipt_cancellation_binding_is_exact_and_nonreplayable(field, value) -> None:
    api = _api()
    prior = _permit(api)
    current = _active_permit_evaluation_state(api, prior)
    binding = _cancellation_binding(
        api, prior.seal, evaluation_state=current, nonce=prior.permit_nonce
    ).model_copy(update={field: value})
    with pytest.raises(
        ValidationError, match="cancel|nonce|release|reserve|outbox|tombstone|replay"
    ):
        _receipt(
            api,
            prior_permit=prior,
            evaluation_state=current,
            cancellation_binding=binding,
        )


def test_receipt_post_risk_snapshot_and_capital_versions_must_reconcile() -> None:
    api = _api()
    receipt = _receipt(api)
    binding = receipt.cancellation_binding
    poisoned = binding.model_copy(
        update={
            "post_risk_snapshot_artifact_hash": HASH_F,
            "post_capital_version": binding.post_capital_version + 1,
        }
    )
    with pytest.raises(ValidationError, match="risk|snapshot|capital|hash"):
        _receipt(api, cancellation_binding=poisoned)


def test_receipt_issuer_must_bind_current_registry_not_prior_issuer() -> None:
    api = _api()
    prior = _permit(api)
    current = _active_permit_evaluation_state(
        api,
        prior,
        registry_epoch=prior.evaluation_state.registry_epoch + 1,
        trust_bundle_hash=HASH_F,
    )
    stale = _gateway_issuer(
        api,
        api.ArtifactKind.ENTRY_CANCELLATION_RECEIPT,
        "capital-gateway.entry-cancellation.v1",
        trust_bundle_hash=prior.evaluation_state.trust_bundle_hash,
        registry_epoch=prior.evaluation_state.registry_epoch,
    )
    with pytest.raises(ValidationError, match="issuer|current|registry|trust"):
        _receipt(
            api,
            prior_permit=prior,
            evaluation_state=current,
            issuer_binding=stale,
        )
