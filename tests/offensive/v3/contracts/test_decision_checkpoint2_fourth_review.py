"""Fourth adversarial RED wave for checkpoint 2 authority contracts."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from tests.offensive.v3.contracts.checkpoint2_helpers import (
    HASH_B,
    HASH_C,
    HASH_D,
    PERMIT_EXPIRES,
    _active_permit_evaluation_state,
    _api,
    _authorization_revalidation,
    _capital_risk_snapshot,
    _gateway_issuer,
    _normalized_reserve_delta_snapshot,
    _permit,
    _permit_evaluation_state,
    _proposal,
    _receipt,
    _seal,
)


def _reduced_active_state(api, prior, *, remaining_fraction: int):
    """Build valid current truth after an earlier monotonic reserve reduction."""

    expected = prior.send_claim_expected_versions
    assert expected is not None
    event_at = PERMIT_EXPIRES + timedelta(seconds=1)
    allocations = tuple(
        item.model_copy(
            update={
                "reserved_cash_cents": (
                    item.reserved_cash_cents * remaining_fraction // 2
                )
            }
        )
        for item in expected.post_reservation_allocations
    )
    candidate = _capital_risk_snapshot(
        api,
        prior.seal,
        allocations,
        snapshot_id=f"risk-snapshot-reduced-{remaining_fraction}",
        as_of=event_at,
        valid_until=event_at + timedelta(minutes=1),
        capital_version=expected.capital_version + 1,
        stage_loss_bindings=expected.stage_loss_bindings,
    )
    snapshot = _normalized_reserve_delta_snapshot(
        expected.post_risk_snapshot, candidate
    )
    revalidation = _authorization_revalidation(
        api,
        prior.seal,
        verified_at=event_at,
        valid_until=event_at + timedelta(minutes=1),
    )
    base = _permit_evaluation_state(
        api,
        prior.seal,
        capital_version=expected.capital_version + 1,
        capital_stream_version=expected.capital_stream_version + 1,
        reservation_version=expected.reservation_version + 1,
        reservation_allocations=allocations,
        remaining_reserved_cash_cents=sum(
            item.reserved_cash_cents for item in allocations
        ),
        risk_snapshot=snapshot,
        risk_snapshot_artifact_hash=snapshot.artifact_hash(),
        authorization_revalidation=revalidation,
    )
    return api.PermitEvaluationState.model_validate(
        base.model_dump(mode="python", round_trip=True)
        | {
            "prior_permit_nonce_sequence": prior.permit_nonce_sequence,
            "active_permit_id": prior.permit_id,
            "active_permit_artifact_hash": prior.artifact_hash(),
            "active_permit_nonce": prior.permit_nonce,
            "active_permit_nonce_sequence": prior.permit_nonce_sequence,
            "active_permit_nonce_state": api.PermitNonceState.ACTIVE,
            "active_outbox_batch_id": expected.outbox_batch_id,
            "active_outbox_payload_hash": expected.outbox_payload_hash,
            "active_outbox_state": api.OutboxState.DURABLE,
            "active_send_claim_state": api.ActiveEntryClaimState.UNCLAIMED,
            "send_claim_sequence": 0,
        }
    )


def test_receipt_can_close_active_reservation_after_owned_reserve_reached_zero() -> (
    None
):
    api = _api()
    prior = _permit(api)
    current = _reduced_active_state(api, prior, remaining_fraction=0)

    receipt = _receipt(api, prior_permit=prior, evaluation_state=current)

    binding = receipt.cancellation_binding
    assert binding.released_cash_cents == 0
    assert binding.post_reservation_state is api.ReservationState.RELEASED
    assert binding.post_reservation_version == current.reservation_version + 1
    assert binding.post_permit_nonce_state is api.PermitNonceState.INVALIDATED
    assert binding.post_outbox_state is api.OutboxState.TOMBSTONED
    assert binding.post_capital_version == current.capital_version
    assert binding.post_capital_stream_version == current.capital_stream_version
    assert binding.post_risk_snapshot == current.risk_snapshot


def test_receipt_can_release_monotonically_reduced_current_reserve() -> None:
    api = _api()
    prior = _permit(api)
    current = _reduced_active_state(api, prior, remaining_fraction=1)

    receipt = _receipt(api, prior_permit=prior, evaluation_state=current)

    assert receipt.cancellation_binding.released_cash_cents == (
        current.remaining_reserved_cash_cents
    )
    assert receipt.cancellation_binding.post_reservation_state is (
        api.ReservationState.RELEASED
    )


def test_seal_accepts_older_authorization_issuance_under_newer_current_trust() -> None:
    api = _api()
    proposal = _proposal(api).model_copy(
        update={"registry_epoch": 8, "trust_bundle_hash": HASH_C}
    )
    issuance = api.AuthorizationIssuanceBinding(
        authorization_envelope_hash=proposal.authorization_artifact_hash,
        authorization_issuer_id="authorizer.service",
        authorization_issuer_key_id="authorizer-key-1",
        authorization_issuer_capability="capital-authorization.edge.v1",
        authorization_issuer_capability_version="authorizer-capability.v1",
        authorization_issuer_identity_fingerprint="a" * 64,
        registry_epoch=7,
        trust_bundle_hash=HASH_B,
    )

    seal = _seal(
        api,
        proposal=proposal,
        authorization_issuance_binding=issuance,
        authorization_issuance_binding_artifact_hash=issuance.artifact_hash(),
        issuer_binding=_gateway_issuer(
            api,
            api.ArtifactKind.PORTFOLIO_DECISION_SEAL,
            "capital-gateway.entry-seal.v1",
            trust_bundle_hash=HASH_C,
            registry_epoch=8,
        ),
    )

    assert seal.authorization_issuance_binding.registry_epoch == 7
    assert seal.registry_epoch == 8


@pytest.mark.parametrize("revision_kind", ["BUSTED", "CORRECTED"])
def test_exit_history_flat_to_positive_requires_reopened_projection(
    revision_kind,
) -> None:
    from tests.offensive.v3.contracts.test_execution_revision_lifecycle import (
        NOW,
        _execution,
        _revision_payload,
    )

    e = _execution()
    recorded = e.ExecutionRevision(
        **_revision_payload(
            e,
            side=e.ExecutionSide.EXIT,
            effective_position_quantity=0,
            effective_position_state=e.EffectivePositionState.FLAT,
            exit_mandate_id=None,
            exit_mandate_revision=None,
        )
    )
    reopened = e.ExecutionRevision(
        **_revision_payload(
            e,
            revision=2,
            revision_kind=getattr(e.ExecutionRevisionKind, revision_kind),
            supersedes_revision=1,
            side=e.ExecutionSide.EXIT,
            effective_filled_quantity=0,
            effective_position_quantity=100,
            effective_gross_cash_cents=0,
            effective_position_state=e.EffectivePositionState.EXIT_PENDING,
            exit_mandate_id="exit-mandate-reopened",
            exit_mandate_revision=1,
            economic_projection_state=e.EconomicProjectionState.RECONCILED,
            observed_at=NOW + timedelta(minutes=1),
        )
    )

    with pytest.raises(ValidationError, match="reopen|projection|flat"):
        e.ExecutionRevisionHistory(
            execution_id=recorded.execution_id,
            order_id=recorded.order_id,
            revisions=(recorded, reopened),
            active_revision=2,
            schema_major=2,
        )


def test_reopened_exit_mandate_revision_exceeds_every_prior_seen_revision() -> None:
    from tests.offensive.v3.contracts.test_execution_revision_lifecycle import (
        NOW,
        _execution,
        _revision_payload,
    )

    e = _execution()
    recorded = e.ExecutionRevision(
        **_revision_payload(
            e,
            side=e.ExecutionSide.EXIT,
            effective_position_quantity=20,
            exit_mandate_revision=3,
        )
    )
    flat = e.ExecutionRevision(
        **_revision_payload(
            e,
            revision=2,
            revision_kind=e.ExecutionRevisionKind.CORRECTED,
            supersedes_revision=1,
            side=e.ExecutionSide.EXIT,
            effective_filled_quantity=100,
            effective_position_quantity=0,
            effective_position_state=e.EffectivePositionState.FLAT,
            exit_mandate_id=None,
            exit_mandate_revision=None,
            observed_at=NOW + timedelta(minutes=1),
        )
    )
    stale_reopen = e.ExecutionRevision(
        **_revision_payload(
            e,
            revision=3,
            revision_kind=e.ExecutionRevisionKind.CORRECTED,
            supersedes_revision=2,
            side=e.ExecutionSide.EXIT,
            effective_filled_quantity=0,
            effective_position_quantity=20,
            effective_gross_cash_cents=0,
            effective_position_state=e.EffectivePositionState.EXIT_PENDING,
            exit_mandate_revision=3,
            economic_projection_state=e.EconomicProjectionState.REOPENED_BY_CORRECTION,
            observed_at=NOW + timedelta(minutes=2),
        )
    )

    with pytest.raises(ValidationError, match="mandate|revision|advance"):
        e.ExecutionRevisionHistory(
            execution_id=recorded.execution_id,
            order_id=recorded.order_id,
            revisions=(recorded, flat, stale_reopen),
            active_revision=3,
            schema_major=2,
        )


def test_authorization_status_advance_witnesses_receipt_authorization_cancel() -> None:
    api = _api()
    prior = _permit(api)
    expected = prior.send_claim_expected_versions
    assert expected is not None
    event_at = PERMIT_EXPIRES + timedelta(seconds=1)
    current = _active_permit_evaluation_state(
        api,
        prior,
        authorization_status_version=expected.authorization_status_version + 1,
        authorization_status_hash=HASH_D,
        authorization_revalidation=_authorization_revalidation(
            api,
            prior.seal,
            verified_at=event_at,
            valid_until=event_at + timedelta(minutes=1),
        ),
    )

    receipt = _receipt(
        api,
        prior_permit=prior,
        evaluation_state=current,
        reason_code=api.PermitReasonCode.AUTHORIZATION_CANCEL,
    )

    assert receipt.reason_code is api.PermitReasonCode.AUTHORIZATION_CANCEL


def test_execution_module_exports_authorization_verification_result() -> None:
    from src.screening.offensive.v3.contracts import execution

    assert "AuthorizationIssuerVerificationResult" in execution.__all__
