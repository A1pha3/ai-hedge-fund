"""Second-review RED: current trust, reserve ownership, and cancellation safety."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from tests.offensive.v3.contracts.checkpoint2_helpers import (
    HASH_A,
    HASH_F,
    PERMIT_DEADLINE,
    _api,
    _authorization_revalidation,
    _cancellation_binding,
    _permit,
    _permit_clock_observation,
    _permit_evaluation_state,
    _permit_line,
    _receipt,
    _reservation_allocations,
    _seal,
)


def _cancel_lines(api, seal, current, reason):
    current_by_line = {
        item.order_line_id: item.reserved_cash_cents
        for item in current.reservation_allocations
    }
    return tuple(
        _permit_line(
            api,
            line,
            disposition=api.PermitDisposition.CANCEL,
            permitted_quantity=0,
            reason_code=reason,
            current_reserved_cents=current_by_line[line.order_line_id],
        )
        for line in seal.proposal.order_lines
    )


def _local_zero_lines(api, seal, current):
    current_by_line = {
        item.order_line_id: item.reserved_cash_cents
        for item in current.reservation_allocations
    }
    first, second = seal.proposal.order_lines
    return (
        _permit_line(
            api,
            first,
            permitted_quantity=0,
            reason_code=api.PermitReasonCode.AVAILABILITY_REDUCTION,
            current_reserved_cents=current_by_line[first.order_line_id],
        ),
        _permit_line(
            api,
            second,
            current_reserved_cents=current_by_line[second.order_line_id],
        ),
    )


def test_second_review_public_models_have_exact_nonredundant_schemas() -> None:
    api = _api()
    assert set(api.ReservationLineAllocation.model_fields) == {
        "order_line_id",
        "reservation_allocation_id",
        "reserved_cash_cents",
    }
    assert set(api.PermitLineMechanicalBinding.model_fields) == {
        "order_line_id",
        "predicate_policy_version",
        "preopen_fact_snapshot_id",
        "preopen_fact_snapshot_hash",
        "preopen_fact_as_of",
        "availability_cap_units",
        "price_cap_units",
        "capacity_cap_units",
        "cash_cap_units",
        "capital_risk_cap_units",
    }
    assert set(api.AuthorizationIssuerRevalidation.model_fields) == {
        "revalidation_id",
        "authorization_envelope_hash",
        "authorization_issuance_binding_artifact_hash",
        "authorization_issuer_id",
        "authorization_issuer_key_id",
        "authorization_issuer_capability",
        "authorization_issuer_capability_version",
        "authorization_issuer_identity_fingerprint",
        "issuance_registry_epoch",
        "issuance_trust_bundle_hash",
        "current_registry_epoch",
        "current_trust_bundle_hash",
        "verification_result",
        "verified_at",
        "valid_until",
    }
    assert "authorization_revalidation_required" not in (
        api.PermitEvaluationState.model_fields
    )
    assert "risk_snapshot_version" not in api.PermitEvaluationState.model_fields
    assert "authorization_revalidation_required" not in (
        api.SendClaimExpectedVersions.model_fields
    )
    assert "risk_snapshot_version" not in api.SendClaimExpectedVersions.model_fields
    assert api.PermitEvaluationState.model_fields["reservation_allocations"].annotation
    assert api.PermitEvaluationState.model_fields[
        "authorization_revalidation"
    ].annotation
    assert api.SendClaimExpectedVersions.model_fields[
        "post_reservation_allocations"
    ].annotation
    assert {
        "prior_permit_nonce_sequence",
        "active_permit_id",
        "active_permit_artifact_hash",
        "active_permit_nonce",
        "active_permit_nonce_sequence",
        "active_outbox_batch_id",
        "active_outbox_payload_hash",
        "active_outbox_state",
        "active_send_claim_state",
        "send_claim_sequence",
        "active_permit_nonce_state",
    } <= set(api.PermitEvaluationState.model_fields)


def test_allow_accepts_current_trust_rotation_and_revalidates_current_issuer() -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(
        api,
        seal,
        registry_epoch=seal.registry_epoch + 1,
        trust_bundle_hash=HASH_F,
    )
    permit = _permit(api, seal=seal, evaluation_state=current)
    assert permit.issuer_binding.registry_epoch == current.registry_epoch
    assert permit.issuer_binding.trust_bundle_hash == current.trust_bundle_hash
    assert permit.send_claim_expected_versions.registry_epoch == current.registry_epoch
    assert (
        permit.evaluation_state.authorization_revalidation.current_registry_epoch
        == current.registry_epoch
    )
    assert (
        permit.send_claim_expected_versions.authorization_revalidation
        == current.authorization_revalidation
    )


def test_allow_rejects_unproven_or_unbound_current_authorization_revalidation() -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(
        api,
        seal,
        registry_epoch=seal.registry_epoch + 1,
        trust_bundle_hash=HASH_F,
    )
    stale = _authorization_revalidation(api, seal)
    poisoned_current = current.model_copy(update={"authorization_revalidation": stale})
    with pytest.raises(ValidationError, match="revalid|trust|registry|current"):
        _permit(api, seal=seal, evaluation_state=poisoned_current)

    valid = _permit(api, seal=seal, evaluation_state=current)
    poisoned_cas = valid.send_claim_expected_versions.model_copy(
        update={"authorization_revalidation": stale}
    )
    with pytest.raises(ValidationError, match="revalid|send|current"):
        _permit(
            api,
            seal=seal,
            evaluation_state=current,
            send_claim_expected_versions=poisoned_cas,
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"registry_epoch": 6},
        {"trust_bundle_hash": HASH_F},
    ],
)
def test_allow_rejects_registry_rollback_or_same_epoch_trust_drift(changes) -> None:
    api = _api()
    seal = _seal(api)
    with pytest.raises(ValidationError, match="registry|trust|epoch|rollback"):
        current = _permit_evaluation_state(api, seal, **changes)
        _permit(api, seal=seal, evaluation_state=current)


def test_revoked_current_authorization_can_cancel_and_release_truthfully() -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(
        api,
        seal,
        authorization_lifecycle=api.AuthorizationLifecycle.REVOKED,
        authorization_status_version=seal.authorization_status_version + 1,
        authorization_status_hash=HASH_A,
    )
    lines = _cancel_lines(api, seal, current, api.PermitReasonCode.AUTHORIZATION_CANCEL)
    permit = _permit(
        api,
        seal=seal,
        disposition=api.PermitDisposition.CANCEL,
        evaluation_state=current,
        permit_lines=lines,
    )
    assert permit.cancellation_binding.released_cash_cents == sum(
        item.reserved_cash_cents for item in current.reservation_allocations
    )


def test_quiet_account_keeps_equal_versions_and_exact_risk_snapshot() -> None:
    api = _api()
    permit = _permit(api)
    current = permit.evaluation_state
    post = permit.send_claim_expected_versions
    assert post.capital_version == current.capital_version
    assert post.capital_stream_version == current.capital_stream_version
    assert post.reservation_version == current.reservation_version
    assert post.stage_loss_bindings == current.stage_loss_bindings
    assert post.post_risk_snapshot == current.risk_snapshot
    assert post.post_risk_snapshot_artifact_hash == current.risk_snapshot_artifact_hash


def test_same_version_authorization_status_content_drift_is_rejected() -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(
        api,
        seal,
        authorization_lifecycle=api.AuthorizationLifecycle.REVOKED,
        authorization_status_hash=HASH_A,
    )
    lines = _cancel_lines(api, seal, current, api.PermitReasonCode.AUTHORIZATION_CANCEL)
    with pytest.raises(ValidationError, match="status|version|lifecycle|hash"):
        _permit(
            api,
            seal=seal,
            disposition=api.PermitDisposition.CANCEL,
            evaluation_state=current,
            permit_lines=lines,
        )


def test_same_version_stage_latch_drift_is_rejected() -> None:
    api = _api()
    seal = _seal(api)
    clear = _permit_evaluation_state(api, seal)
    halted = clear.stage_loss_bindings[0].model_copy(
        update={"stage_loss_latch": api.StageLossLatchState.STAGE_LOSS_HALTED}
    )
    current = _permit_evaluation_state(
        api,
        seal,
        stage_loss_bindings=(halted, *clear.stage_loss_bindings[1:]),
    )
    lines = _cancel_lines(api, seal, current, api.PermitReasonCode.STAGE_HALT_CANCEL)
    with pytest.raises(ValidationError, match="stage|latch|version"):
        _permit(
            api,
            seal=seal,
            disposition=api.PermitDisposition.CANCEL,
            evaluation_state=current,
            permit_lines=lines,
        )


def test_current_reservation_cannot_reallocate_cash_between_lines() -> None:
    api = _api()
    seal = _seal(api)
    first, second = seal.line_reserve_bindings
    allocations = _reservation_allocations(
        api,
        seal,
        current_cents_by_line={
            first.order_line_id: first.reserved_cash_cents - 100,
            second.order_line_id: second.reserved_cash_cents + 100,
        },
    )
    current = _permit_evaluation_state(
        api,
        seal,
        reservation_version=seal.post_admission_reservation_version + 1,
        reservation_allocations=allocations,
    )
    with pytest.raises(ValidationError, match="allocation|line|reserve|sealed"):
        _permit(api, seal=seal, evaluation_state=current)


def test_cancel_release_must_equal_sum_of_current_line_allocations() -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(
        api,
        seal,
        authorization_lifecycle=api.AuthorizationLifecycle.REVOKED,
        authorization_status_version=seal.authorization_status_version + 1,
        authorization_status_hash=HASH_A,
    )
    lines = _cancel_lines(api, seal, current, api.PermitReasonCode.AUTHORIZATION_CANCEL)
    binding = _cancellation_binding(api, seal, evaluation_state=current).model_copy(
        update={
            "released_cash_cents": (
                sum(
                    item.reserved_cash_cents for item in current.reservation_allocations
                )
                - 1
            )
        }
    )
    with pytest.raises(ValidationError, match="release|allocation|reserve|sum"):
        _permit(
            api,
            seal=seal,
            disposition=api.PermitDisposition.CANCEL,
            evaluation_state=current,
            permit_lines=lines,
            cancellation_binding=binding,
        )


def test_mixed_allow_cannot_hide_global_authorization_cancel_on_one_line() -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(api, seal)
    first, second = seal.proposal.order_lines
    allocations = {
        item.order_line_id: item.reserved_cash_cents
        for item in current.reservation_allocations
    }
    lines = (
        _permit_line(
            api,
            first,
            permitted_quantity=0,
            reason_code=api.PermitReasonCode.AUTHORIZATION_CANCEL,
            current_reserved_cents=allocations[first.order_line_id],
        ),
        _permit_line(
            api,
            second,
            current_reserved_cents=allocations[second.order_line_id],
        ),
    )
    with pytest.raises(
        ValidationError, match="ALLOW|authorization|global|mechanical|reason"
    ):
        _permit(api, seal=seal, evaluation_state=current, permit_lines=lines)


@pytest.mark.parametrize(
    "reason",
    [
        "AUTHORIZATION_CANCEL",
        "RISK_HALT_CANCEL",
        "STAGE_HALT_CANCEL",
        "RECONCILIATION_CANCEL",
        "FACT_INTEGRITY_CANCEL",
        "DEADLINE_CANCEL",
    ],
)
def test_allow_zero_line_rejects_every_portfolio_wide_cancel_reason(reason) -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(api, seal)
    first, second = seal.proposal.order_lines
    current_by_line = {
        item.order_line_id: item.reserved_cash_cents
        for item in current.reservation_allocations
    }
    lines = (
        _permit_line(
            api,
            first,
            permitted_quantity=0,
            reason_code=getattr(api.PermitReasonCode, reason),
            current_reserved_cents=current_by_line[first.order_line_id],
        ),
        _permit_line(
            api,
            second,
            current_reserved_cents=current_by_line[second.order_line_id],
        ),
    )
    with pytest.raises(ValidationError, match="ALLOW|global|cancel|reason"):
        _permit(api, seal=seal, evaluation_state=current, permit_lines=lines)


def test_local_mechanical_cap_can_legally_reduce_one_allow_line_to_zero() -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(api, seal)
    lines = _local_zero_lines(api, seal, current)
    permit = _permit(api, seal=seal, evaluation_state=current, permit_lines=lines)
    assert permit.disposition is api.PermitDisposition.ALLOW
    assert permit.permit_lines[0].permitted_quantity_units == 0
    assert permit.permit_lines[1].permitted_quantity_units > 0
    assert permit.send_claim_expected_versions.reservation_version > (
        current.reservation_version
    )
    assert permit.send_claim_expected_versions.post_risk_snapshot.risk_snapshot_id != (
        current.risk_snapshot.risk_snapshot_id
    )
    post = permit.send_claim_expected_versions
    assert [
        item.reservation_allocation_id for item in post.post_reservation_allocations
    ] == [item.reservation_allocation_id for item in seal.line_reserve_bindings]
    assert {
        item.source_id: item.reserved_entry_gross_cents
        for item in post.post_risk_snapshot.entry_reserves
    } == {
        item.reservation_allocation_id: item.reserved_cash_cents
        for item in post.post_reservation_allocations
        if item.reserved_cash_cents > 0
    }


def test_post_risk_snapshot_changes_iff_capital_risk_state_changes() -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(api, seal)
    changed_lines = _local_zero_lines(api, seal, current)
    changed = _permit(
        api, seal=seal, evaluation_state=current, permit_lines=changed_lines
    )
    poisoned_changed = changed.send_claim_expected_versions.model_copy(
        update={
            "post_risk_snapshot": current.risk_snapshot,
            "post_risk_snapshot_artifact_hash": current.risk_snapshot_artifact_hash,
        }
    )
    with pytest.raises(ValidationError, match="risk|snapshot|capital|reserve"):
        _permit(
            api,
            seal=seal,
            evaluation_state=current,
            permit_lines=changed_lines,
            send_claim_expected_versions=poisoned_changed,
        )

    quiet = _permit(api, seal=seal, evaluation_state=current)
    fictional = current.risk_snapshot.model_copy(
        update={"risk_snapshot_id": "risk-snapshot-fictional"}
    )
    poisoned_quiet = quiet.send_claim_expected_versions.model_copy(
        update={
            "post_risk_snapshot": fictional,
            "post_risk_snapshot_artifact_hash": fictional.artifact_hash(),
        }
    )
    with pytest.raises(ValidationError, match="risk|snapshot|unchanged"):
        _permit(
            api,
            seal=seal,
            evaluation_state=current,
            send_claim_expected_versions=poisoned_quiet,
        )


def test_cancel_atomically_invalidates_nonce_and_rejects_replay_shape() -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(
        api,
        seal,
        authorization_lifecycle=api.AuthorizationLifecycle.REVOKED,
        authorization_status_version=seal.authorization_status_version + 1,
        authorization_status_hash=HASH_A,
    )
    lines = _cancel_lines(api, seal, current, api.PermitReasonCode.AUTHORIZATION_CANCEL)
    permit = _permit(
        api,
        seal=seal,
        disposition=api.PermitDisposition.CANCEL,
        evaluation_state=current,
        permit_lines=lines,
    )
    binding = permit.cancellation_binding
    assert permit.evaluation_state.active_permit_nonce is None
    assert permit.evaluation_state.active_outbox_batch_id is None
    assert permit.permit_nonce_sequence > (
        permit.evaluation_state.prior_permit_nonce_sequence
    )
    assert binding.post_permit_nonce_sequence > permit.permit_nonce_sequence
    assert binding.post_permit_nonce_state is api.PermitNonceState.INVALIDATED
    assert binding.post_risk_snapshot.entry_reserves == ()
    assert binding.post_risk_snapshot.reserved_cash_cents == 0
    replayable = binding.model_copy(
        update={
            "post_permit_nonce_sequence": permit.permit_nonce_sequence,
            "post_permit_nonce_state": api.PermitNonceState.ACTIVE,
        }
    )
    with pytest.raises(ValidationError, match="nonce|sequence|invalidated|replay"):
        _permit(
            api,
            seal=seal,
            disposition=api.PermitDisposition.CANCEL,
            evaluation_state=current,
            permit_lines=lines,
            cancellation_binding=replayable,
        )


def test_deadline_cancel_is_reachable_after_issue_deadline() -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(api, seal)
    lines = _cancel_lines(api, seal, current, api.PermitReasonCode.DEADLINE_CANCEL)
    cancelled_at = PERMIT_DEADLINE + timedelta(seconds=30)
    revalidation = current.authorization_revalidation.model_copy(
        update={
            "verified_at": cancelled_at,
            "valid_until": cancelled_at + timedelta(minutes=1),
        }
    )
    current = type(current).model_validate(
        current.model_dump(mode="python", round_trip=True)
        | {"authorization_revalidation": revalidation}
    )
    lines = _cancel_lines(api, seal, current, api.PermitReasonCode.DEADLINE_CANCEL)
    observation = _permit_clock_observation(api, wall_clock_utc=cancelled_at)
    permit = _permit(
        api,
        seal=seal,
        disposition=api.PermitDisposition.CANCEL,
        evaluation_state=current,
        permit_lines=lines,
        permit_clock_observation=observation,
        issued_at=cancelled_at,
    )
    assert permit.disposition is api.PermitDisposition.CANCEL


def test_unhealthy_clock_can_cancel_but_never_allow() -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(api, seal)
    observation = _permit_clock_observation(
        api,
        wall_clock_utc=PERMIT_DEADLINE,
        clock_health=api.ClockHealth.ROLLBACK_DETECTED,
    )
    event_at = observation.wall_clock_utc
    revalidation = current.authorization_revalidation.model_copy(
        update={
            "verified_at": event_at,
            "valid_until": event_at + timedelta(minutes=1),
        }
    )
    current = type(current).model_validate(
        current.model_dump(mode="python", round_trip=True)
        | {"authorization_revalidation": revalidation}
    )
    lines = _cancel_lines(
        api, seal, current, api.PermitReasonCode.FACT_INTEGRITY_CANCEL
    )
    cancel = _permit(
        api,
        seal=seal,
        disposition=api.PermitDisposition.CANCEL,
        evaluation_state=current,
        permit_lines=lines,
        permit_clock_observation=observation,
        issued_at=PERMIT_DEADLINE,
    )
    assert cancel.disposition is api.PermitDisposition.CANCEL
    with pytest.raises(ValidationError, match="ALLOW|clock|healthy|rollback"):
        _permit(
            api,
            seal=seal,
            evaluation_state=current,
            permit_clock_observation=observation,
            issued_at=PERMIT_DEADLINE,
        )


@pytest.mark.parametrize(
    "clock_change",
    [
        {"monotonic_observation_ns": 1_000_000},
        {"monotonic_sequence": 8},
    ],
)
def test_cancel_clock_must_remain_monotonic_even_when_unhealthy(clock_change) -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(api, seal)
    observation = _permit_clock_observation(
        api,
        clock_health=api.ClockHealth.ROLLBACK_DETECTED,
        **clock_change,
    )
    lines = _cancel_lines(
        api, seal, current, api.PermitReasonCode.FACT_INTEGRITY_CANCEL
    )
    with pytest.raises(ValidationError, match="clock|monotonic|sequence|later"):
        _permit(
            api,
            seal=seal,
            disposition=api.PermitDisposition.CANCEL,
            evaluation_state=current,
            permit_lines=lines,
            permit_clock_observation=observation,
        )


def test_healthy_cancel_issued_at_must_equal_clock_wall_observation() -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(api, seal)
    lines = _cancel_lines(api, seal, current, api.PermitReasonCode.DEADLINE_CANCEL)
    observation = _permit_clock_observation(
        api, wall_clock_utc=PERMIT_DEADLINE + timedelta(seconds=30)
    )
    with pytest.raises(ValidationError, match="clock|wall|issued_at|healthy"):
        _permit(
            api,
            seal=seal,
            disposition=api.PermitDisposition.CANCEL,
            evaluation_state=current,
            permit_lines=lines,
            permit_clock_observation=observation,
            issued_at=PERMIT_DEADLINE + timedelta(seconds=31),
        )


def test_unhealthy_clock_cannot_witness_deadline_cancel() -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(api, seal)
    observation = _permit_clock_observation(
        api,
        wall_clock_utc=PERMIT_DEADLINE + timedelta(seconds=30),
        clock_health=api.ClockHealth.ROLLBACK_DETECTED,
    )
    event_at = observation.wall_clock_utc
    revalidation = current.authorization_revalidation.model_copy(
        update={
            "verified_at": event_at,
            "valid_until": event_at + timedelta(minutes=1),
        }
    )
    current = type(current).model_validate(
        current.model_dump(mode="python", round_trip=True)
        | {"authorization_revalidation": revalidation}
    )
    lines = _cancel_lines(api, seal, current, api.PermitReasonCode.DEADLINE_CANCEL)
    with pytest.raises(ValidationError, match="deadline|clock|witness|reason"):
        _permit(
            api,
            seal=seal,
            disposition=api.PermitDisposition.CANCEL,
            evaluation_state=current,
            permit_lines=lines,
            permit_clock_observation=observation,
            issued_at=PERMIT_DEADLINE + timedelta(seconds=30),
        )


def test_same_line_reason_must_identify_the_binding_that_sets_the_minimum() -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(api, seal)
    first, second = seal.proposal.order_lines
    current_by_line = {
        item.order_line_id: item.reserved_cash_cents
        for item in current.reservation_allocations
    }
    wrong = _permit_line(
        api,
        first,
        permitted_quantity=0,
        reason_code=api.PermitReasonCode.CAPACITY_REDUCTION,
        current_reserved_cents=current_by_line[first.order_line_id],
    )
    wrong_binding = wrong.mechanical_binding.model_copy(
        update={
            "capacity_cap_units": first.sealed_quantity_units,
            "availability_cap_units": 0,
        }
    )
    wrong = wrong.model_copy(update={"mechanical_binding": wrong_binding})
    lines = (
        wrong,
        _permit_line(
            api,
            second,
            current_reserved_cents=current_by_line[second.order_line_id],
        ),
    )
    with pytest.raises(ValidationError, match="reason|availability|minimum|cap"):
        _permit(api, seal=seal, evaluation_state=current, permit_lines=lines)


def test_mechanical_cap_is_lot_floored_before_permitted_quantity() -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(api, seal)
    first, second = seal.proposal.order_lines
    current_by_line = {
        item.order_line_id: item.reserved_cash_cents
        for item in current.reservation_allocations
    }
    reduced = _permit_line(
        api,
        second,
        permitted_quantity=100,
        reason_code=api.PermitReasonCode.AVAILABILITY_REDUCTION,
        current_reserved_cents=current_by_line[second.order_line_id],
    )
    reduced = reduced.model_copy(
        update={
            "mechanical_binding": reduced.mechanical_binding.model_copy(
                update={"availability_cap_units": 150}
            )
        }
    )
    lines = (
        _permit_line(
            api,
            first,
            current_reserved_cents=current_by_line[first.order_line_id],
        ),
        reduced,
    )
    permit = _permit(api, seal=seal, evaluation_state=current, permit_lines=lines)
    assert permit.permit_lines[1].permitted_quantity_units == 100


def test_tied_mechanical_caps_use_frozen_reason_priority() -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(api, seal)
    first, second = seal.proposal.order_lines
    current_by_line = {
        item.order_line_id: item.reserved_cash_cents
        for item in current.reservation_allocations
    }
    first_line = _permit_line(
        api,
        first,
        permitted_quantity=0,
        reason_code=api.PermitReasonCode.PRICE_REDUCTION,
        current_reserved_cents=current_by_line[first.order_line_id],
    )
    first_line = first_line.model_copy(
        update={
            "mechanical_binding": first_line.mechanical_binding.model_copy(
                update={"availability_cap_units": 0, "price_cap_units": 0}
            )
        }
    )
    lines = (
        first_line,
        _permit_line(
            api,
            second,
            current_reserved_cents=current_by_line[second.order_line_id],
        ),
    )
    with pytest.raises(ValidationError, match="reason|priority|availability|tie"):
        _permit(api, seal=seal, evaluation_state=current, permit_lines=lines)


def test_cancel_can_record_authority_context_drift_with_matching_reason() -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(
        api,
        seal,
        policy_activation_hash=HASH_F,
        policy_epoch=seal.policy_epoch + 1,
        authorization_lifecycle=api.AuthorizationLifecycle.REVALIDATION_REQUIRED,
        authorization_status_version=seal.authorization_status_version + 1,
        authorization_status_hash=HASH_A,
    )
    lines = _cancel_lines(api, seal, current, api.PermitReasonCode.AUTHORIZATION_CANCEL)
    permit = _permit(
        api,
        seal=seal,
        disposition=api.PermitDisposition.CANCEL,
        evaluation_state=current,
        permit_lines=lines,
    )
    assert permit.evaluation_state.policy_activation_hash != (
        permit.seal.policy_activation_hash
    )


def test_current_allocation_content_change_requires_reservation_version_advance() -> (
    None
):
    api = _api()
    seal = _seal(api)
    first = seal.line_reserve_bindings[0]
    allocations = _reservation_allocations(
        api,
        seal,
        current_cents_by_line={first.order_line_id: first.reserved_cash_cents - 100},
    )
    current = _permit_evaluation_state(
        api,
        seal,
        reservation_allocations=allocations,
        authorization_lifecycle=api.AuthorizationLifecycle.REVOKED,
        authorization_status_version=seal.authorization_status_version + 1,
        authorization_status_hash=HASH_A,
    )
    lines = _cancel_lines(api, seal, current, api.PermitReasonCode.AUTHORIZATION_CANCEL)
    with pytest.raises(ValidationError, match="reservation|allocation|version"):
        _permit(
            api,
            seal=seal,
            disposition=api.PermitDisposition.CANCEL,
            evaluation_state=current,
            permit_lines=lines,
        )


def test_current_allocation_change_requires_capital_and_stream_version_advance() -> (
    None
):
    api = _api()
    seal = _seal(api)
    first = seal.line_reserve_bindings[0]
    allocations = _reservation_allocations(
        api,
        seal,
        current_cents_by_line={first.order_line_id: 0},
    )
    current = _permit_evaluation_state(
        api,
        seal,
        reservation_allocations=allocations,
        reservation_version=seal.post_admission_reservation_version + 1,
        capital_version=seal.post_admission_capital_version,
        capital_stream_version=seal.post_admission_capital_stream_version,
        authorization_lifecycle=api.AuthorizationLifecycle.REVOKED,
        authorization_status_version=seal.authorization_status_version + 1,
        authorization_status_hash=HASH_A,
    )
    lines = _cancel_lines(api, seal, current, api.PermitReasonCode.AUTHORIZATION_CANCEL)
    with pytest.raises(ValidationError, match="allocation|capital|stream|version"):
        _permit(
            api,
            seal=seal,
            disposition=api.PermitDisposition.CANCEL,
            evaluation_state=current,
            permit_lines=lines,
        )


def test_post_allocations_must_equal_each_permit_line_remaining_reserve() -> None:
    api = _api()
    permit = _permit(api)
    post = permit.send_claim_expected_versions
    first = post.post_reservation_allocations[0]
    poisoned = post.model_copy(
        update={
            "post_reservation_allocations": (
                first.model_copy(
                    update={"reserved_cash_cents": first.reserved_cash_cents - 1}
                ),
                *post.post_reservation_allocations[1:],
            )
        }
    )
    with pytest.raises(ValidationError, match="allocation|line|remaining|reserve"):
        _permit(api, send_claim_expected_versions=poisoned)


@pytest.mark.parametrize(
    ("as_of", "valid_until"),
    [
        (
            PERMIT_DEADLINE + timedelta(microseconds=1),
            PERMIT_DEADLINE + timedelta(minutes=1),
        ),
        (
            PERMIT_DEADLINE - timedelta(minutes=1),
            PERMIT_DEADLINE,
        ),
    ],
)
def test_allow_requires_risk_snapshot_observed_and_valid_at_issuance(
    as_of, valid_until
) -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(api, seal)
    poisoned_snapshot = current.risk_snapshot.model_copy(
        update={"as_of": as_of, "valid_until": valid_until}
    )
    poisoned = _permit_evaluation_state(
        api,
        seal,
        risk_snapshot=poisoned_snapshot,
        risk_snapshot_artifact_hash=poisoned_snapshot.artifact_hash(),
    )
    with pytest.raises(ValidationError, match="risk snapshot|as_of|valid|issuance"):
        _permit(api, seal=seal, evaluation_state=poisoned)


def test_receipt_post_risk_snapshot_is_created_and_valid_at_cancellation() -> None:
    api = _api()
    receipt = _receipt(api)
    binding = receipt.cancellation_binding
    stale_snapshot = binding.post_risk_snapshot.model_copy(
        update={
            "as_of": receipt.cancelled_at - timedelta(minutes=2),
            "valid_until": receipt.cancelled_at - timedelta(minutes=1),
        }
    )
    poisoned = binding.model_copy(
        update={
            "post_risk_snapshot": stale_snapshot,
            "post_risk_snapshot_artifact_hash": stale_snapshot.artifact_hash(),
        }
    )
    with pytest.raises(ValidationError, match="post risk snapshot|as_of|valid|cancel"):
        _receipt(api, cancellation_binding=poisoned)
