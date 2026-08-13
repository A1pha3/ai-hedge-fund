"""Safety-focused adversarial REDs for checkpoint 2."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from tests.offensive.v3.contracts.checkpoint2_helpers import (
    BROKER_CUTOFF,
    PERMIT_DEADLINE,
    PERMIT_EXPIRES,
    _api,
    _authorization_revalidation,
    _cancellation_binding,
    _capital_risk_snapshot,
    _gateway_expected_versions,
    _mechanical_binding,
    _permit,
    _permit_evaluation_state,
    _permit_line,
    _proposal,
    _receipt,
    _receipt_clock_observation,
    _reservation_allocations,
    _seal,
    _seal_payload,
    _stage_binding,
)


def _active_state(api, prior, base=None, **overrides):
    expected = prior.send_claim_expected_versions
    assert expected is not None
    if base is None:
        base = _permit_evaluation_state(
            api,
            prior.seal,
            risk_snapshot=expected.post_risk_snapshot,
            risk_snapshot_artifact_hash=expected.post_risk_snapshot_artifact_hash,
            capital_version=expected.capital_version,
            capital_stream_version=expected.capital_stream_version,
            reservation_version=expected.reservation_version,
            reservation_allocations=expected.post_reservation_allocations,
        )
    values = base.model_dump(mode="python", round_trip=True) | overrides
    values.update(
        {
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
    return api.PermitEvaluationState.model_validate(values)


@pytest.mark.parametrize("clock_health", ["ROLLBACK_DETECTED", "UNKNOWN"])
def test_unhealthy_clock_wall_rollback_can_publish_fact_integrity_receipt(
    clock_health,
) -> None:
    api = _api()
    prior = _permit(api)
    expected = prior.send_claim_expected_versions
    assert expected is not None
    rollback_wall = expected.post_risk_snapshot.as_of - timedelta(seconds=30)
    observation = _receipt_clock_observation(
        api,
        wall_clock_utc=rollback_wall,
        clock_health=getattr(api.ClockHealth, clock_health),
    )
    current = _active_state(
        api,
        prior,
        authorization_revalidation=_authorization_revalidation(
            api,
            prior.seal,
            verified_at=rollback_wall,
            valid_until=BROKER_CUTOFF,
        ),
    )
    binding = _cancellation_binding(
        api,
        prior.seal,
        evaluation_state=current,
        nonce=prior.permit_nonce,
        event_at=rollback_wall,
    )

    receipt = _receipt(
        api,
        prior_permit=prior,
        evaluation_state=current,
        reason_code=api.PermitReasonCode.FACT_INTEGRITY_CANCEL,
        cancellation_clock_observation=observation,
        cancelled_at=rollback_wall,
        cancellation_binding=binding,
    )

    assert receipt.cancelled_at < current.risk_snapshot.as_of


def test_healthy_clock_still_rejects_current_snapshot_future_to_receipt() -> None:
    api = _api()
    prior = _permit(api)
    expected = prior.send_claim_expected_versions
    assert expected is not None
    cancelled_at = PERMIT_DEADLINE + timedelta(seconds=10)
    future_as_of = cancelled_at + timedelta(seconds=10)
    snapshot = expected.post_risk_snapshot.model_copy(
        update={
            "risk_snapshot_id": "risk-snapshot-future-to-healthy-receipt",
            "as_of": future_as_of,
            "valid_until": future_as_of + timedelta(minutes=1),
            "capital_version": expected.capital_version + 1,
        }
    )
    current = _active_state(
        api,
        prior,
        capital_version=expected.capital_version + 1,
        capital_stream_version=expected.capital_stream_version + 1,
        risk_snapshot=snapshot,
        risk_snapshot_artifact_hash=snapshot.artifact_hash(),
        authorization_revalidation=_authorization_revalidation(
            api,
            prior.seal,
            verified_at=cancelled_at,
            valid_until=BROKER_CUTOFF,
        ),
    )
    observation = _receipt_clock_observation(api, wall_clock_utc=cancelled_at)
    binding = _cancellation_binding(
        api,
        prior.seal,
        evaluation_state=current,
        nonce=prior.permit_nonce,
        event_at=cancelled_at,
    )

    with pytest.raises(ValidationError, match="future|snapshot|as_of"):
        _receipt(
            api,
            prior_permit=prior,
            evaluation_state=current,
            reason_code=api.PermitReasonCode.FACT_INTEGRITY_CANCEL,
            cancellation_clock_observation=observation,
            cancelled_at=cancelled_at,
            cancellation_binding=binding,
        )


@pytest.mark.parametrize(
    "ambiguity", ["two_budgets_one_stage", "one_budget_two_stages"]
)
def test_gateway_expected_versions_rejects_ambiguous_stage_budget_mapping(
    ambiguity,
) -> None:
    api = _api()
    proposal = _proposal(api)
    original = _gateway_expected_versions(api, proposal).stage_loss_expected_versions
    if ambiguity == "two_budgets_one_stage":
        duplicate = original[0].model_copy(
            update={"stage_loss_budget_id": "alternate-budget"}
        )
        stages = (*original, duplicate)
    else:
        stages = (
            original[0],
            original[1].model_copy(
                update={"stage_loss_budget_id": original[0].stage_loss_budget_id}
            ),
        )
    stages = tuple(
        sorted(
            stages,
            key=lambda item: (
                item.research_program_id,
                item.economic_lineage_id,
                item.stage_id,
                item.stage_loss_budget_id,
            ),
        )
    )

    with pytest.raises(ValidationError, match="stage|budget|unique"):
        _gateway_expected_versions(
            api,
            proposal,
            stage_loss_expected_versions=stages,
        )


def test_seal_rejects_two_stage_admissions_for_one_stage() -> None:
    api = _api()
    proposal = _proposal(api)
    admissions = tuple(_stage_binding(api, line) for line in proposal.order_lines)
    duplicate = admissions[0].model_copy(
        update={"stage_loss_budget_id": "alternate-budget"}
    )
    admissions = tuple(
        sorted((*admissions, duplicate), key=lambda item: item.identity())
    )
    with pytest.raises(ValidationError, match="stage|budget|unique"):
        api.PortfolioDecisionSeal.model_validate(
            _seal_payload(
                api,
                proposal=proposal,
                stage_admission_bindings=admissions,
            )
        )


def test_all_lot_floored_zero_caps_have_typed_mechanical_cancel() -> None:
    api = _api()
    seal = _seal(api)
    lines = tuple(
        _permit_line(
            api,
            sealed_line,
            disposition=api.PermitDisposition.CANCEL,
            permitted_quantity=0,
            reason_code=api.PermitReasonCode.CAPACITY_REDUCTION,
            mechanical_binding=_mechanical_binding(
                api,
                sealed_line,
                permitted_quantity=0,
                reason_code=api.PermitReasonCode.CAPACITY_REDUCTION,
                capacity_cap_units=sealed_line.lot_size_units - 1,
            ),
        )
        for sealed_line in seal.proposal.order_lines
    )

    permit = _permit(
        api,
        seal=seal,
        disposition=api.PermitDisposition.CANCEL,
        permit_lines=lines,
    )

    assert permit.disposition is api.PermitDisposition.CANCEL
    assert all(line.permitted_quantity_units == 0 for line in permit.permit_lines)
    assert all(line.client_order_id is None for line in permit.permit_lines)
    assert all(line.mechanical_binding is not None for line in permit.permit_lines)


def test_mechanical_zero_cancel_cannot_mix_portfolio_cancel_without_binding() -> None:
    api = _api()
    seal = _seal(api)
    first, second = seal.proposal.order_lines
    lines = (
        _permit_line(
            api,
            first,
            disposition=api.PermitDisposition.CANCEL,
            permitted_quantity=0,
            reason_code=api.PermitReasonCode.CAPACITY_REDUCTION,
            mechanical_binding=_mechanical_binding(
                api,
                first,
                permitted_quantity=0,
                reason_code=api.PermitReasonCode.CAPACITY_REDUCTION,
                capacity_cap_units=first.lot_size_units - 1,
            ),
        ),
        _permit_line(
            api,
            second,
            disposition=api.PermitDisposition.CANCEL,
            permitted_quantity=0,
            reason_code=api.PermitReasonCode.AUTHORIZATION_CANCEL,
            mechanical_binding=None,
        ),
    )

    with pytest.raises(ValidationError, match="mechanical|cancel|reason"):
        _permit(
            api,
            seal=seal,
            disposition=api.PermitDisposition.CANCEL,
            permit_lines=lines,
        )


def test_released_reservation_requires_zero_allocations_and_remaining() -> None:
    api = _api()
    seal = _seal(api)
    with pytest.raises(ValidationError, match="released|allocation|reserve"):
        _permit_evaluation_state(
            api,
            seal,
            reservation_state=api.ReservationState.RELEASED,
        )


def test_active_reservation_may_have_zero_owned_allocations_before_receipt() -> None:
    api = _api()
    seal = _seal(api)
    zero_allocations = tuple(
        item.model_copy(update={"reserved_cash_cents": 0})
        for item in _reservation_allocations(api, seal)
    )
    snapshot = _capital_risk_snapshot(
        api,
        seal,
        zero_allocations,
        capital_version=seal.post_admission_capital_version + 1,
    )

    state = _permit_evaluation_state(
        api,
        seal,
        capital_version=snapshot.capital_version,
        capital_stream_version=seal.capital_stream_version + 1,
        reservation_version=seal.post_admission_reservation_version + 1,
        reservation_state=api.ReservationState.ACTIVE,
        reservation_allocations=zero_allocations,
        remaining_reserved_cash_cents=0,
        risk_snapshot=snapshot,
        risk_snapshot_artifact_hash=snapshot.artifact_hash(),
    )

    assert state.reservation_state is api.ReservationState.ACTIVE
    assert state.remaining_reserved_cash_cents == 0


def test_seal_freezes_post_admission_capital_snapshot_and_stream_anchor() -> None:
    api = _api()
    required = {
        "post_admission_risk_snapshot_id",
        "post_admission_risk_snapshot_artifact_hash",
        "post_admission_capital_stream_version",
    }
    assert required <= set(api.PortfolioDecisionSeal.model_fields)

    base = _seal(api)
    allocations = _reservation_allocations(api, base)
    post = _capital_risk_snapshot(
        api,
        base,
        allocations,
        snapshot_id="post-admission-risk-snapshot",
        capital_version=base.post_admission_capital_version,
    )
    payload = base.model_dump(mode="python", round_trip=True) | {
        "post_admission_risk_snapshot_id": post.risk_snapshot_id,
        "post_admission_risk_snapshot_artifact_hash": post.artifact_hash(),
        "post_admission_capital_stream_version": base.capital_stream_version + 1,
    }
    anchored = api.PortfolioDecisionSeal.model_validate(payload)
    assert anchored.post_admission_risk_snapshot_id == post.risk_snapshot_id


def test_equal_post_admission_versions_require_exact_sealed_snapshot_anchor() -> None:
    api = _api()
    required = {
        "post_admission_risk_snapshot_id",
        "post_admission_risk_snapshot_artifact_hash",
        "post_admission_capital_stream_version",
    }
    assert required <= set(api.PortfolioDecisionSeal.model_fields)

    base = _seal(api)
    allocations = _reservation_allocations(api, base)
    anchored_snapshot = _capital_risk_snapshot(
        api,
        base,
        allocations,
        snapshot_id="post-admission-risk-snapshot",
        capital_version=base.post_admission_capital_version,
    )
    seal = api.PortfolioDecisionSeal.model_validate(
        base.model_dump(mode="python", round_trip=True)
        | {
            "post_admission_risk_snapshot_id": anchored_snapshot.risk_snapshot_id,
            "post_admission_risk_snapshot_artifact_hash": (
                anchored_snapshot.artifact_hash()
            ),
            "post_admission_capital_stream_version": base.capital_stream_version + 1,
        }
    )
    substituted = anchored_snapshot.model_copy(
        update={
            "risk_snapshot_id": "same-version-substituted-snapshot",
            "available_cash_cents": anchored_snapshot.available_cash_cents + 1,
        }
    )
    current = _permit_evaluation_state(
        api,
        seal,
        capital_version=seal.post_admission_capital_version,
        capital_stream_version=seal.post_admission_capital_stream_version,
        risk_snapshot=substituted,
        risk_snapshot_artifact_hash=substituted.artifact_hash(),
    )

    with pytest.raises(ValidationError, match="post-admission|snapshot|exact"):
        _permit(api, seal=seal, evaluation_state=current)


def test_seal_rejects_post_admission_snapshot_identity_reused_from_input() -> None:
    api = _api()
    seal = _seal(api)

    with pytest.raises(ValidationError, match="post-admission|snapshot|new|change"):
        api.PortfolioDecisionSeal.model_validate(
            seal.model_dump(mode="python", round_trip=True)
            | {
                "post_admission_risk_snapshot_id": seal.risk_snapshot_id,
                "post_admission_risk_snapshot_artifact_hash": (
                    seal.risk_snapshot_artifact_hash
                ),
            }
        )


def test_higher_permit_capital_version_requires_new_snapshot_id() -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(api, seal)
    snapshot = current.risk_snapshot.model_copy(
        update={
            "capital_version": current.capital_version + 1,
            "available_cash_cents": current.risk_snapshot.available_cash_cents + 1,
        }
    )
    advanced = _permit_evaluation_state(
        api,
        seal,
        capital_version=current.capital_version + 1,
        capital_stream_version=current.capital_stream_version + 1,
        risk_snapshot=snapshot,
        risk_snapshot_artifact_hash=snapshot.artifact_hash(),
    )

    with pytest.raises(ValidationError, match="snapshot|ID|new|capital"):
        _permit(api, seal=seal, evaluation_state=advanced)


def test_higher_receipt_capital_version_requires_new_snapshot_id() -> None:
    api = _api()
    prior = _permit(api)
    expected = prior.send_claim_expected_versions
    assert expected is not None
    event_at = PERMIT_EXPIRES + timedelta(seconds=1)
    snapshot = expected.post_risk_snapshot.model_copy(
        update={
            "as_of": event_at,
            "valid_until": event_at + timedelta(minutes=1),
            "capital_version": expected.capital_version + 1,
            "available_cash_cents": (
                expected.post_risk_snapshot.available_cash_cents + 1
            ),
        }
    )
    current = _active_state(
        api,
        prior,
        capital_version=expected.capital_version + 1,
        capital_stream_version=expected.capital_stream_version + 1,
        risk_snapshot=snapshot,
        risk_snapshot_artifact_hash=snapshot.artifact_hash(),
        authorization_revalidation=_authorization_revalidation(
            api,
            prior.seal,
            verified_at=event_at,
            valid_until=event_at + timedelta(minutes=1),
        ),
    )

    with pytest.raises(ValidationError, match="snapshot|ID|new|capital"):
        _receipt(
            api,
            prior_permit=prior,
            evaluation_state=current,
            reason_code=api.PermitReasonCode.FACT_INTEGRITY_CANCEL,
        )


@pytest.mark.parametrize("drift", ["capital", "clear_stage"])
def test_receipt_fact_integrity_cancel_closes_monotonic_post_permit_drift(
    drift,
) -> None:
    api = _api()
    prior = _permit(api)
    expected = prior.send_claim_expected_versions
    assert expected is not None
    event_at = PERMIT_EXPIRES + timedelta(seconds=1)
    stages = expected.stage_loss_bindings
    if drift == "clear_stage":
        stages = tuple(
            item.model_copy(update={"stage_loss_version": item.stage_loss_version + 1})
            for item in stages
        )
    snapshot = _capital_risk_snapshot(
        api,
        prior.seal,
        expected.post_reservation_allocations,
        snapshot_id=f"post-permit-{drift}-snapshot",
        as_of=event_at,
        valid_until=event_at + timedelta(minutes=1),
        capital_version=expected.capital_version + 1,
        stage_loss_bindings=stages,
    )
    if drift == "capital":
        snapshot = snapshot.model_copy(
            update={"available_cash_cents": snapshot.available_cash_cents + 1}
        )
    current = _active_state(
        api,
        prior,
        capital_version=expected.capital_version + 1,
        capital_stream_version=expected.capital_stream_version + 1,
        risk_snapshot=snapshot,
        risk_snapshot_artifact_hash=snapshot.artifact_hash(),
        stage_loss_bindings=stages,
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
        reason_code=api.PermitReasonCode.FACT_INTEGRITY_CANCEL,
    )

    assert receipt.reason_code is api.PermitReasonCode.FACT_INTEGRITY_CANCEL


def test_positive_to_positive_cannot_claim_reopened_projection() -> None:
    from tests.offensive.v3.contracts.test_execution_revision_lifecycle import (
        NOW,
        _execution,
        _revision_payload,
    )

    e = _execution()
    recorded = e.ExecutionRevision(**_revision_payload(e))
    mislabeled = e.ExecutionRevision(
        **_revision_payload(
            e,
            revision=2,
            revision_kind=e.ExecutionRevisionKind.CORRECTED,
            supersedes_revision=1,
            effective_filled_quantity=80,
            effective_position_quantity=80,
            effective_gross_cash_cents=80_000,
            exit_mandate_revision=2,
            economic_projection_state=e.EconomicProjectionState.REOPENED_BY_CORRECTION,
            observed_at=NOW + timedelta(minutes=1),
        )
    )

    with pytest.raises(ValidationError, match="reopen|positive|projection"):
        e.ExecutionRevisionHistory(
            execution_id=recorded.execution_id,
            order_id=recorded.order_id,
            revisions=(recorded, mislabeled),
            active_revision=2,
            schema_major=2,
        )


def test_first_reopened_exit_mandate_revision_must_exceed_initial_revision() -> None:
    from tests.offensive.v3.contracts.test_execution_revision_lifecycle import (
        NOW,
        _execution,
        _revision_payload,
    )

    e = _execution()
    flat = e.ExecutionRevision(
        **_revision_payload(
            e,
            side=e.ExecutionSide.EXIT,
            effective_filled_quantity=100,
            effective_position_quantity=0,
            effective_position_state=e.EffectivePositionState.FLAT,
            exit_mandate_id=None,
            exit_mandate_revision=None,
        )
    )
    stale_reopen = e.ExecutionRevision(
        **_revision_payload(
            e,
            revision=2,
            revision_kind=e.ExecutionRevisionKind.CORRECTED,
            supersedes_revision=1,
            side=e.ExecutionSide.EXIT,
            effective_filled_quantity=0,
            effective_position_quantity=100,
            effective_gross_cash_cents=0,
            effective_position_state=e.EffectivePositionState.EXIT_PENDING,
            exit_mandate_id="exit-mandate-reopened",
            exit_mandate_revision=1,
            economic_projection_state=e.EconomicProjectionState.REOPENED_BY_CORRECTION,
            observed_at=NOW + timedelta(minutes=1),
        )
    )

    with pytest.raises(ValidationError, match="mandate|revision|advance"):
        e.ExecutionRevisionHistory(
            execution_id=flat.execution_id,
            order_id=flat.order_id,
            revisions=(flat, stale_reopen),
            active_revision=2,
            schema_major=2,
        )
