"""Plan 04 Task 6: permit, durable outbox, and SEND_CLAIMED linearization.

Adversarial coverage for the final send-right state machine on the seal
store: SEALED -> PERMITTED -> OUTBOX_DURABLE -> SEND_CLAIMED, then
SUBMISSION_AMBIGUOUS | BROKER_ACK, with TOMBSTONED as the only pre-claim
exit. No network delivery happens anywhere in this file; the gateway only
linearizes the right to send one immutable payload under one client ID.
"""

from __future__ import annotations

import dataclasses
import sqlite3
import threading
from datetime import datetime, timedelta

import pytest

from src.screening.offensive.v3.contracts import (
    ReconciliationLatchState,
    RiskLatchState,
    StageLossLatchState,
)
from src.screening.offensive.v3.gateway.decisions import (
    AdmissionContext,
    CapitalGateway,
    CapitalGatewayError,
    DeliveryOutcome,
    GatewayTruthContext,
    StageLossTruth,
)
from tests.offensive.v3.contracts.checkpoint2_helpers import (
    AUTHORIZATION_ID,
    AUTHORIZATION_VERSION,
    HASH_A,
    HASH_F,
    PERMIT_DEADLINE,
    PERMIT_EXPIRES,
    _api,
    _gateway_expected_versions,
    _permit,
    _permit_evaluation_state,
    _permit_line,
    _prior_seal_eligibility,
    _proposal,
    _receipt,
    _seal,
)


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now_value = start

    def __call__(self) -> datetime:
        return self.now_value


@pytest.fixture()
def api():
    return _api()


@pytest.fixture()
def clock() -> _Clock:
    return _Clock(PERMIT_DEADLINE)


@pytest.fixture()
def gateway(tmp_path, clock) -> CapitalGateway:
    return CapitalGateway(
        database_path=str(tmp_path / "gateway-entry-state.sqlite3"),
        clock=clock,
    )


def _publish(gateway: CapitalGateway, api, seal=None, expected_versions=None):
    if seal is None:
        seal = _seal(api)
    if expected_versions is None:
        expected_versions = _gateway_expected_versions(api)
    gateway.publish_entry(
        seal,
        expected_versions=expected_versions,
        context=AdmissionContext(
            available_cash_cents=1_000_000,
            active_authorization_id=AUTHORIZATION_ID,
            active_authorization_version=AUTHORIZATION_VERSION,
            active_envelope_hash=seal.authorization_envelope_hash,
            policy_activation_hash=seal.policy_activation_hash,
            authorization_status_version=(
                seal.authorization_status_version
            ),
            authorization_status_hash=seal.authorization_status_hash,
            writer_fencing_epoch=seal.writer_fencing_epoch,
        ),
    )
    return seal


def _replacement_seal(api, original):
    """A legal shrink supersede under the same economic key."""

    changed_proposal = _proposal(api).model_copy(
        update={"target_portfolio_policy_fingerprint": "9" * 64}
    )
    expected = _gateway_expected_versions(
        api,
        changed_proposal,
        expected_active_seal_id=original.seal_id,
        expected_active_seal_revision=original.seal_revision,
        expected_active_seal_logical_key=original.logical_key,
        expected_active_seal_artifact_hash=original.artifact_hash(),
    )
    replacement = _seal(
        api,
        seal_id="seal-2",
        seal_revision=2,
        proposal=changed_proposal,
        reservation_id="reservation-2",
        supersedes_seal_id=original.seal_id,
        supersedes_seal_revision=original.seal_revision,
        prior_seal_eligibility=_prior_seal_eligibility(
            api,
            prior_seal_id=original.seal_id,
            prior_seal_revision=original.seal_revision,
            prior_seal_artifact_hash=original.artifact_hash(),
        ),
        consumed_gateway_expected_versions=expected,
    )
    return replacement, expected


def _stage_truths(source) -> tuple[StageLossTruth, ...]:
    return tuple(
        StageLossTruth(
            research_program_id=item.research_program_id,
            economic_lineage_id=item.economic_lineage_id,
            stage_id=item.stage_id,
            stage_loss_budget_id=item.stage_loss_budget_id,
            stage_loss_version=item.stage_loss_version,
            stage_loss_latch=item.stage_loss_latch,
        )
        for item in source
    )


def _truth_context(api, evaluation) -> GatewayTruthContext:
    return GatewayTruthContext(
        policy_activation_hash=evaluation.policy_activation_hash,
        trust_bundle_hash=evaluation.trust_bundle_hash,
        registry_epoch=evaluation.registry_epoch,
        policy_epoch=evaluation.policy_epoch,
        authority_epoch=evaluation.authority_epoch,
        risk_epoch=evaluation.risk_epoch,
        active_authorization_id=evaluation.authorization_id,
        active_authorization_version=evaluation.authorization_version,
        active_envelope_hash=evaluation.authorization_envelope_hash,
        authorization_lifecycle=evaluation.authorization_lifecycle,
        authorization_status_version=(
            evaluation.authorization_status_version
        ),
        authorization_status_hash=evaluation.authorization_status_hash,
        entry_fence_id=evaluation.entry_fence_id,
        entry_fence_hash=evaluation.entry_fence_hash,
        entry_fence_version=evaluation.entry_fence_version,
        capital_version=evaluation.capital_version,
        capital_stream_version=evaluation.capital_stream_version,
        risk_snapshot_artifact_hash=(
            evaluation.risk_snapshot_artifact_hash
        ),
        risk_latch=evaluation.risk_snapshot.risk_latch,
        reconciliation_latch=(
            evaluation.risk_snapshot.reconciliation_latch
        ),
        stage_loss_states=_stage_truths(
            evaluation.stage_loss_bindings
        ),
        writer_fencing_epoch=evaluation.writer_fencing_epoch,
    )


def _claim_context(api, expected) -> GatewayTruthContext:
    snapshot = expected.post_risk_snapshot
    return GatewayTruthContext(
        policy_activation_hash=expected.policy_activation_hash,
        trust_bundle_hash=expected.trust_bundle_hash,
        registry_epoch=expected.registry_epoch,
        policy_epoch=expected.policy_epoch,
        authority_epoch=expected.authority_epoch,
        risk_epoch=expected.risk_epoch,
        active_authorization_id=expected.authorization_id,
        active_authorization_version=expected.authorization_version,
        active_envelope_hash=expected.authorization_envelope_hash,
        authorization_lifecycle=expected.authorization_lifecycle,
        authorization_status_version=(
            expected.authorization_status_version
        ),
        authorization_status_hash=expected.authorization_status_hash,
        entry_fence_id=expected.entry_fence_id,
        entry_fence_hash=expected.entry_fence_hash,
        entry_fence_version=expected.entry_fence_version,
        capital_version=expected.capital_version,
        capital_stream_version=expected.capital_stream_version,
        risk_snapshot_artifact_hash=(
            expected.post_risk_snapshot_artifact_hash
        ),
        risk_latch=snapshot.risk_latch,
        reconciliation_latch=snapshot.reconciliation_latch,
        stage_loss_states=_stage_truths(expected.stage_loss_bindings),
        writer_fencing_epoch=expected.writer_fencing_epoch,
    )


def _issue(gateway: CapitalGateway, api, permit=None, *, context=None):
    if permit is None:
        permit = _permit(api)
    if context is None:
        context = _truth_context(api, permit.evaluation_state)
    return gateway.issue_permit(permit, context=context)


def _seal_reserve_total(api, seal=None) -> int:
    if seal is None:
        seal = _seal(api)
    return int(seal.total_reserved_cash_cents)


# -- happy path: monotone send-right progression -------------------------


def test_issue_permit_transitions_sealed_to_permitted(gateway, api) -> None:
    seal = _publish(gateway, api)
    permit = _permit(api)
    permitted = _issue(gateway, api, permit)
    assert permitted.seal_status == "PERMITTED"
    assert permitted.total_released_reserve_cents == 0
    assert permitted.total_remaining_reserve_cents == _seal_reserve_total(api, seal)
    state = gateway.entry_state(seal.seal_id)
    assert state.status == "PERMITTED"
    assert state.permit_nonce_state == "ACTIVE"
    assert state.outbox_state is None
    assert state.remaining_reserved_cash_cents == _seal_reserve_total(api, seal)


def test_issue_permit_with_shrink_releases_exact_cash(gateway, api) -> None:
    seal = _publish(gateway, api)
    lines = tuple(
        (
            _permit_line(
                api,
                sealed_line,
                permitted_quantity=100,
                reason_code=api.PermitReasonCode.CAPITAL_RISK_REDUCTION,
            )
            if sealed_line.order_line_id == "line-2"
            else _permit_line(api, sealed_line)
        )
        for sealed_line in seal.proposal.order_lines
    )
    permit = _permit(api, permit_lines=lines)
    assert permit.total_released_reserve_cents == 800 * 100
    permitted = _issue(gateway, api, permit)
    assert permitted.total_released_reserve_cents == 800 * 100
    state = gateway.entry_state(seal.seal_id)
    assert state.remaining_reserved_cash_cents == (
        _seal_reserve_total(api, seal) - 800 * 100
    )


def test_full_send_right_linearization_without_network(gateway, api) -> None:
    seal = _publish(gateway, api)
    permit = _permit(api)
    _issue(gateway, api, permit)
    durable = gateway.make_outbox_durable(permit)
    assert durable.state == "DURABLE"
    state = gateway.entry_state(seal.seal_id)
    assert state.status == "OUTBOX_DURABLE"
    assert state.outbox_state == "DURABLE"

    expected = permit.send_claim_expected_versions
    claimed = gateway.claim_send(
        permit, expected, context=_claim_context(api, expected)
    )
    assert claimed.seal_id == seal.seal_id
    assert claimed.outbox_batch_id == expected.outbox_batch_id
    assert claimed.outbox_payload_hash == expected.outbox_payload_hash
    assert claimed.client_order_ids == (
        ("line-1", "client-line-1"),
        ("line-2", "client-line-2"),
    )
    state = gateway.entry_state(seal.seal_id)
    assert state.status == "SEND_CLAIMED"
    assert state.permit_nonce_state == "CONSUMED"
    assert state.send_claim_sequence == 1
    assert state.remaining_reserved_cash_cents == int(
        permit.total_remaining_reserve_cents
    )


def test_claim_survives_reopen_with_worst_case_exposure(
    tmp_path, api, clock
) -> None:
    db_path = str(tmp_path / "reopen.sqlite3")
    gateway = CapitalGateway(database_path=db_path, clock=clock)
    seal = _publish(gateway, api)
    permit = _permit(api)
    _issue(gateway, api, permit)
    gateway.make_outbox_durable(permit)
    expected = permit.send_claim_expected_versions
    gateway.claim_send(permit, expected, context=_claim_context(api, expected))

    reopened = CapitalGateway(database_path=db_path, clock=clock)
    state = reopened.entry_state(seal.seal_id)
    assert state.status == "SEND_CLAIMED"
    # Claimed state is already-in-flight risk: the worst-case reserve
    # must remain fully reserved after any restart.
    assert state.remaining_reserved_cash_cents == int(
        permit.total_remaining_reserve_cents
    )
    receipt = _receipt(api, prior_permit=permit)
    with pytest.raises(CapitalGatewayError) as excinfo:
        reopened.cancel_unclaimed_entry(receipt)
    assert excinfo.value.code == "cancel_forbidden_after_claim"


def test_delivery_outcomes_progress_ambiguous_to_broker_ack(
    gateway, api
) -> None:
    seal = _publish(gateway, api)
    permit = _permit(api)
    _issue(gateway, api, permit)
    gateway.make_outbox_durable(permit)
    expected = permit.send_claim_expected_versions
    gateway.claim_send(
        permit, expected, context=_claim_context(api, expected)
    )

    with pytest.raises(CapitalGatewayError) as excinfo:
        gateway.record_delivery_outcome(
            "missing-seal", DeliveryOutcome.BROKER_ACK
        )
    assert excinfo.value.code == "seal_unknown"

    gateway.record_delivery_outcome(
        seal.seal_id, DeliveryOutcome.SUBMISSION_AMBIGUOUS
    )
    assert gateway.entry_state(seal.seal_id).status == "SUBMISSION_AMBIGUOUS"
    # Idempotent ambiguous rerecord while still ambiguous.
    gateway.record_delivery_outcome(
        seal.seal_id, DeliveryOutcome.SUBMISSION_AMBIGUOUS
    )
    gateway.record_delivery_outcome(seal.seal_id, DeliveryOutcome.BROKER_ACK)
    assert gateway.entry_state(seal.seal_id).status == "BROKER_ACK"
    with pytest.raises(CapitalGatewayError) as excinfo:
        gateway.record_delivery_outcome(
            seal.seal_id, DeliveryOutcome.SUBMISSION_AMBIGUOUS
        )
    assert excinfo.value.code == "delivery_state_conflict"


def test_delivery_outcome_requires_same_client_order_ids(
    gateway, api
) -> None:
    seal = _publish(gateway, api)
    permit = _permit(api)
    _issue(gateway, api, permit)
    gateway.make_outbox_durable(permit)
    expected = permit.send_claim_expected_versions
    gateway.claim_send(
        permit, expected, context=_claim_context(api, expected)
    )
    # Retrying with the exact claimed client IDs is the only legal retry.
    gateway.record_delivery_outcome(
        seal.seal_id,
        DeliveryOutcome.SUBMISSION_AMBIGUOUS,
        submission_client_order_ids=("client-line-2", "client-line-1"),
    )
    with pytest.raises(CapitalGatewayError) as excinfo:
        gateway.record_delivery_outcome(
            seal.seal_id,
            DeliveryOutcome.BROKER_ACK,
            submission_client_order_ids=("client-line-1", "guessed-id"),
        )
    assert excinfo.value.code == "client_order_id_mismatch"


def test_delivery_outcome_before_claim_is_rejected(gateway, api) -> None:
    seal = _publish(gateway, api)
    with pytest.raises(CapitalGatewayError) as excinfo:
        gateway.record_delivery_outcome(
            seal.seal_id, DeliveryOutcome.SUBMISSION_AMBIGUOUS
        )
    assert excinfo.value.code == "delivery_state_conflict"


# -- adversarial: stale seals, nonces, quantities ------------------------


def test_old_active_seal_cannot_take_permit(gateway, api) -> None:
    _publish(gateway, api)
    replacement, replacement_expected = _replacement_seal(
        api, _seal(api)
    )
    _publish(gateway, api, replacement, replacement_expected)
    stale_permit = _permit(api)  # binds seal-1, now SUPERSEDED
    with pytest.raises(CapitalGatewayError) as excinfo:
        _issue(gateway, api, stale_permit)
    assert excinfo.value.code == "permit_stale_seal"
    assert gateway.entry_state("seal-2").status == "SEALED"


def test_permit_for_unknown_seal_is_rejected(gateway, api) -> None:
    with pytest.raises(CapitalGatewayError) as excinfo:
        _issue(gateway, api, _permit(api))
    assert excinfo.value.code == "seal_unknown"


def test_supersede_after_permit_is_forbidden(gateway, api) -> None:
    original = _publish(gateway, api)
    _issue(gateway, api, _permit(api))
    replacement, replacement_expected = _replacement_seal(api, original)
    with pytest.raises(CapitalGatewayError) as excinfo:
        _publish(gateway, api, replacement, replacement_expected)
    assert excinfo.value.code == "supersede_forbidden_after_permit"


def test_wrong_permit_nonce_cannot_claim(gateway, api) -> None:
    seal = _publish(gateway, api)
    permit = _permit(api)
    _issue(gateway, api, permit)
    gateway.make_outbox_durable(permit)
    expected = permit.send_claim_expected_versions.model_copy(
        update={"active_permit_nonce": "other-nonce"}
    )
    with pytest.raises(CapitalGatewayError) as excinfo:
        gateway.claim_send(
            permit, expected, context=_claim_context(api, expected)
        )
    assert excinfo.value.code == "permit_nonce_mismatch"
    assert gateway.entry_state(seal.seal_id).status == "OUTBOX_DURABLE"


def test_wrong_permit_identity_cannot_claim(gateway, api) -> None:
    seal = _publish(gateway, api)
    permit = _permit(api)
    _issue(gateway, api, permit)
    gateway.make_outbox_durable(permit)
    expected = permit.send_claim_expected_versions.model_copy(
        update={"active_permit_id": "other-permit"}
    )
    with pytest.raises(CapitalGatewayError) as excinfo:
        gateway.claim_send(
            permit, expected, context=_claim_context(api, expected)
        )
    assert excinfo.value.code == "permit_cas_conflict"
    state = gateway.entry_state(seal.seal_id)
    assert state.status == "OUTBOX_DURABLE"
    assert state.permit_nonce_state == "ACTIVE"


def test_quantity_increase_via_inflated_allocations_is_rejected(
    gateway, api
) -> None:
    seal = _publish(gateway, api)
    permit = _permit(api)
    # The contracts already refuse honestly-grown allocations; the
    # store-level guard must also catch a forged evaluation that lies
    # about the current reserve truth.
    inflated = tuple(
        item.model_copy(
            update={"reserved_cash_cents": item.reserved_cash_cents + 10_000}
        )
        for item in permit.evaluation_state.reservation_allocations
    )
    forged_evaluation = permit.evaluation_state.model_copy(
        update={"reservation_allocations": inflated}
    )
    forged = permit.model_copy(
        update={"evaluation_state": forged_evaluation}
    )
    with pytest.raises(CapitalGatewayError) as excinfo:
        _issue(gateway, api, forged)
    assert excinfo.value.code == "permit_allocation_conflict"
    assert gateway.entry_state(seal.seal_id).status == "SEALED"
    assert gateway.entry_state(seal.seal_id).remaining_reserved_cash_cents == (
        _seal_reserve_total(api, seal)
    )


def test_reissue_cannot_grow_back_a_shrunk_line(gateway, api) -> None:
    seal = _publish(gateway, api)
    shrunk = _permit(
        api,
        permit_lines=tuple(
            (
                _permit_line(
                    api,
                    sealed_line,
                    permitted_quantity=(
                        100
                        if sealed_line.order_line_id == "line-2"
                        else sealed_line.sealed_quantity_units
                    ),
                    reason_code=(
                        api.PermitReasonCode.CAPITAL_RISK_REDUCTION
                        if sealed_line.order_line_id == "line-2"
                        else api.PermitReasonCode.UNCHANGED
                    ),
                )
                for sealed_line in seal.proposal.order_lines
            )
        ),
    )
    _issue(gateway, api, shrunk)
    # The seal is PERMITTED now: no second permit may reissue any
    # quantity. A fresh permit id forces the state-machine gate.
    base = _permit(api)
    regrow = base.model_copy(
        update={
            "permit_id": "permit-2",
            "send_claim_expected_versions": (
                base.send_claim_expected_versions.model_copy(
                    update={"active_permit_id": "permit-2"}
                )
            ),
        }
    )
    with pytest.raises(CapitalGatewayError) as excinfo:
        _issue(gateway, api, regrow)
    assert excinfo.value.code == "permit_stale_seal"


# -- adversarial: deadlines ------------------------------------------------


def test_expired_issue_deadline_blocks_permit(gateway, api, clock) -> None:
    seal = _publish(gateway, api)
    clock.now_value = PERMIT_DEADLINE + timedelta(seconds=1)
    with pytest.raises(CapitalGatewayError) as excinfo:
        _issue(gateway, api)
    assert excinfo.value.code == "permit_issue_deadline_missed"
    state = gateway.entry_state(seal.seal_id)
    assert state.status == "SEALED"
    assert state.permit_nonce_state is None
    assert state.remaining_reserved_cash_cents == _seal_reserve_total(api, seal)


def test_expired_permit_blocks_outbox(gateway, api, clock) -> None:
    _publish(gateway, api)
    permit = _permit(api)
    _issue(gateway, api, permit)
    clock.now_value = PERMIT_EXPIRES
    with pytest.raises(CapitalGatewayError) as excinfo:
        gateway.make_outbox_durable(permit)
    assert excinfo.value.code == "permit_expired"
    assert gateway.entry_state(permit.seal_id).status == "PERMITTED"


def test_expired_send_deadline_blocks_claim(gateway, api, clock) -> None:
    _publish(gateway, api)
    permit = _permit(api)
    _issue(gateway, api, permit)
    gateway.make_outbox_durable(permit)
    clock.now_value = PERMIT_EXPIRES  # == effective send deadline here
    expected = permit.send_claim_expected_versions
    with pytest.raises(CapitalGatewayError) as excinfo:
        gateway.claim_send(
            permit, expected, context=_claim_context(api, expected)
        )
    assert excinfo.value.code == "send_deadline_missed"
    assert gateway.entry_state(permit.seal_id).status == "OUTBOX_DURABLE"


# -- adversarial: stale CAS truth and halts --------------------------------


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("active_envelope_hash", HASH_F, "envelope_stale"),
        ("policy_activation_hash", HASH_F, "policy_activation_stale"),
        ("trust_bundle_hash", HASH_F, "trust_bundle_stale"),
        ("policy_epoch", 99, "epoch_stale"),
        ("authority_epoch", 99, "epoch_stale"),
        ("risk_epoch", 99, "epoch_stale"),
        ("registry_epoch", 99, "trust_bundle_stale"),
        (
            "active_authorization_id",
            "other-authorization",
            "authorization_stale",
        ),
        ("active_authorization_version", 99, "authorization_stale"),
        ("authorization_status_version", 99, "authorization_status_stale"),
        ("authorization_status_hash", HASH_F, "authorization_status_stale"),
        ("entry_fence_id", "other-fence", "entry_fence_stale"),
        ("entry_fence_hash", "9" * 64, "entry_fence_stale"),
        ("entry_fence_version", 99, "entry_fence_stale"),
        ("writer_fencing_epoch", 99, "writer_fencing_epoch_mismatch"),
        ("capital_version", 99, "capital_version_stale"),
        ("capital_stream_version", 99, "capital_stream_stale"),
        ("risk_snapshot_artifact_hash", HASH_F, "risk_snapshot_stale"),
    ],
)
def test_stale_truth_blocks_issue_permit(
    gateway, api, field, value, code
) -> None:
    _publish(gateway, api)
    permit = _permit(api)
    context = dataclasses.replace(
        _truth_context(api, permit.evaluation_state), **{field: value}
    )
    with pytest.raises(CapitalGatewayError) as excinfo:
        gateway.issue_permit(permit, context=context)
    assert excinfo.value.code == code
    assert gateway.entry_state(permit.seal_id).status == "SEALED"


def test_stale_stage_loss_version_blocks_issue_permit(gateway, api) -> None:
    seal = _publish(gateway, api)
    permit = _permit(api)
    context = _truth_context(api, permit.evaluation_state)
    drifted_stage = dataclasses.replace(
        context.stage_loss_states[0],
        stage_loss_version=context.stage_loss_states[0].stage_loss_version + 1,
    )
    drifted = dataclasses.replace(
        context, stage_loss_states=(drifted_stage, *context.stage_loss_states[1:])
    )
    with pytest.raises(CapitalGatewayError) as excinfo:
        gateway.issue_permit(permit, context=drifted)
    assert excinfo.value.code == "stage_loss_stale"
    assert gateway.entry_state(seal.seal_id).status == "SEALED"


@pytest.mark.parametrize(
    ("latch_field", "latch_value", "code"),
    [
        ("risk_latch", RiskLatchState.RISK_HALTED, "risk_halt_blocks_send"),
        (
            "reconciliation_latch",
            ReconciliationLatchState.RECONCILIATION_HALT,
            "reconciliation_halt_blocks_send",
        ),
    ],
)
def test_halt_blocks_issue_permit(
    gateway, api, latch_field, latch_value, code
) -> None:
    seal = _publish(gateway, api)
    permit = _permit(api)
    context = dataclasses.replace(
        _truth_context(api, permit.evaluation_state),
        **{latch_field: latch_value},
    )
    with pytest.raises(CapitalGatewayError) as excinfo:
        gateway.issue_permit(permit, context=context)
    assert excinfo.value.code == code
    assert gateway.entry_state(seal.seal_id).status == "SEALED"


def test_stage_halt_blocks_issue_permit(gateway, api) -> None:
    seal = _publish(gateway, api)
    permit = _permit(api)
    context = _truth_context(api, permit.evaluation_state)
    halted_stage = dataclasses.replace(
        context.stage_loss_states[0],
        stage_loss_latch=StageLossLatchState.STAGE_LOSS_HALTED,
    )
    halted = dataclasses.replace(
        context, stage_loss_states=(halted_stage, *context.stage_loss_states[1:])
    )
    with pytest.raises(CapitalGatewayError) as excinfo:
        gateway.issue_permit(permit, context=halted)
    assert excinfo.value.code == "stage_halt_blocks_send"
    assert gateway.entry_state(seal.seal_id).status == "SEALED"


def test_halt_and_stale_truth_block_claim_send(gateway, api) -> None:
    _publish(gateway, api)
    permit = _permit(api)
    _issue(gateway, api, permit)
    gateway.make_outbox_durable(permit)
    expected = permit.send_claim_expected_versions

    halted = dataclasses.replace(
        _claim_context(api, expected), risk_latch=RiskLatchState.RISK_HALTED
    )
    with pytest.raises(CapitalGatewayError) as excinfo:
        gateway.claim_send(permit, expected, context=halted)
    assert excinfo.value.code == "risk_halt_blocks_send"

    stale_fence = dataclasses.replace(
        _claim_context(api, expected), entry_fence_version=99
    )
    with pytest.raises(CapitalGatewayError) as excinfo:
        gateway.claim_send(permit, expected, context=stale_fence)
    assert excinfo.value.code == "entry_fence_stale"

    stale_capital = dataclasses.replace(
        _claim_context(api, expected), capital_version=99
    )
    with pytest.raises(CapitalGatewayError) as excinfo:
        gateway.claim_send(permit, expected, context=stale_capital)
    assert excinfo.value.code == "capital_version_stale"
    assert gateway.entry_state(permit.seal_id).status == "OUTBOX_DURABLE"


# -- adversarial: duplicate and competing claims ---------------------------


def test_two_competing_permits_linearize_one(tmp_path, api, clock) -> None:
    db_path = str(tmp_path / "permit-race.sqlite3")
    setup = CapitalGateway(database_path=db_path, clock=clock)
    _publish(setup, api)

    permit_a = _permit(api)
    base_b = _permit(api)
    permit_b = base_b.model_copy(
        update={
            "permit_id": "permit-2",
            "permit_nonce": "permit-nonce-2",
            "send_claim_expected_versions": (
                base_b.send_claim_expected_versions.model_copy(
                    update={
                        "active_permit_id": "permit-2",
                        "active_permit_nonce": "permit-nonce-2",
                        "outbox_permit_nonce": "permit-nonce-2",
                    }
                )
            ),
        }
    )
    context_a = _truth_context(api, permit_a.evaluation_state)
    context_b = _truth_context(api, permit_b.evaluation_state)
    barrier = threading.Barrier(2)
    outcomes: list[object] = [None, None]

    def worker(index: int, permit, context) -> None:
        gateway = CapitalGateway(database_path=db_path, clock=clock)
        barrier.wait()
        try:
            gateway.issue_permit(permit, context=context)
            outcomes[index] = "permitted"
        except CapitalGatewayError as exc:
            outcomes[index] = exc.code

    threads = [
        threading.Thread(target=worker, args=(0, permit_a, context_a)),
        threading.Thread(target=worker, args=(1, permit_b, context_b)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Exactly one permit may win the seal; the loser rolls back wholly.
    assert set(outcomes) == {"permitted", "permit_stale_seal"}
    state = setup.entry_state("seal-1")
    assert state.status == "PERMITTED"
    assert state.remaining_reserved_cash_cents == _seal_reserve_total(api)
    raw = sqlite3.connect(db_path)
    try:
        permit_rows = raw.execute(
            "SELECT COUNT(*) FROM entry_permits WHERE seal_id = 'seal-1'"
        ).fetchone()[0]
        line_rows = raw.execute(
            "SELECT COUNT(*) FROM entry_permit_lines"
        ).fetchone()[0]
    finally:
        raw.close()
    assert permit_rows == 1
    assert line_rows == 2


def test_cancel_claim_race_never_splits_state(
    tmp_path, api, clock
) -> None:
    seal_total = _seal_reserve_total(api)
    for iteration in range(8):
        db_path = str(tmp_path / f"race-{iteration}.sqlite3")
        setup = CapitalGateway(database_path=db_path, clock=clock)
        _publish(setup, api)
        permit = _permit(api)
        _issue(setup, api, permit)
        setup.make_outbox_durable(permit)
        expected = permit.send_claim_expected_versions
        claim_context = _claim_context(api, expected)
        receipt = _receipt(api, prior_permit=permit)
        barrier = threading.Barrier(2)
        outcomes: list[object] = [None, None]

        def claim_worker() -> None:
            gateway = CapitalGateway(database_path=db_path, clock=clock)
            barrier.wait()
            try:
                gateway.claim_send(
                    permit, expected, context=claim_context
                )
                outcomes[0] = "claimed"
            except CapitalGatewayError as exc:
                outcomes[0] = exc.code

        def cancel_worker() -> None:
            gateway = CapitalGateway(database_path=db_path, clock=clock)
            barrier.wait()
            try:
                gateway.cancel_unclaimed_entry(receipt)
                outcomes[1] = "cancelled"
            except CapitalGatewayError as exc:
                outcomes[1] = exc.code

        threads = [
            threading.Thread(target=claim_worker),
            threading.Thread(target=cancel_worker),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        final = CapitalGateway(
            database_path=db_path, clock=clock
        ).entry_state(permit.seal_id)
        winners = [
            outcome
            for outcome in outcomes
            if outcome in {"claimed", "cancelled"}
        ]
        assert len(winners) == 1, outcomes
        if final.status == "SEND_CLAIMED":
            # Claimed state is in-flight risk: worst-case reserve must
            # survive the race untouched.
            assert outcomes[0] == "claimed"
            assert final.permit_nonce_state == "CONSUMED"
            assert final.outbox_state == "DURABLE"
            assert final.send_claim_sequence == 1
            assert final.remaining_reserved_cash_cents == seal_total
        elif final.status == "TOMBSTONED":
            assert outcomes[1] == "cancelled"
            assert final.permit_nonce_state == "INVALIDATED"
            assert final.outbox_state == "TOMBSTONED"
            assert final.remaining_reserved_cash_cents == 0
        else:
            pytest.fail(f"split entry state after race: {final}")


def test_duplicate_claim_is_rejected(gateway, api) -> None:
    seal = _publish(gateway, api)
    permit = _permit(api)
    _issue(gateway, api, permit)
    gateway.make_outbox_durable(permit)
    expected = permit.send_claim_expected_versions
    context = _claim_context(api, expected)
    gateway.claim_send(permit, expected, context=context)
    with pytest.raises(CapitalGatewayError) as excinfo:
        gateway.claim_send(permit, expected, context=context)
    assert excinfo.value.code == "send_claim_conflict"
    state = gateway.entry_state(seal.seal_id)
    assert state.status == "SEND_CLAIMED"
    assert state.send_claim_sequence == 1


def test_two_competing_dispatchers_linearize_one_claim(
    tmp_path, api, clock
) -> None:
    db_path = str(tmp_path / "dispatchers.sqlite3")
    gateway_a = CapitalGateway(database_path=db_path, clock=clock)
    permit = _permit(api)
    _publish(gateway_a, api)
    _issue(gateway_a, api, permit)
    gateway_a.make_outbox_durable(permit)
    expected = permit.send_claim_expected_versions
    context = _claim_context(api, expected)

    gateway_b = CapitalGateway(database_path=db_path, clock=clock)
    # Both dispatchers hold the identical expected bundle; exactly one
    # may win the send right.
    winner, loser = gateway_a, gateway_b
    winner.claim_send(permit, expected, context=context)
    with pytest.raises(CapitalGatewayError) as excinfo:
        loser.claim_send(permit, expected, context=context)
    assert excinfo.value.code == "send_claim_conflict"
    state = gateway_b.entry_state(permit.seal_id)
    assert state.status == "SEND_CLAIMED"
    assert state.send_claim_sequence == 1


def test_claim_before_outbox_is_rejected(gateway, api) -> None:
    seal = _publish(gateway, api)
    permit = _permit(api)
    _issue(gateway, api, permit)
    expected = permit.send_claim_expected_versions
    with pytest.raises(CapitalGatewayError) as excinfo:
        gateway.claim_send(
            permit, expected, context=_claim_context(api, expected)
        )
    assert excinfo.value.code == "outbox_not_durable"
    state = gateway.entry_state(seal.seal_id)
    assert state.status == "PERMITTED"
    assert state.permit_nonce_state == "ACTIVE"
    assert state.remaining_reserved_cash_cents == _seal_reserve_total(api, seal)


def test_outbox_replay_is_idempotent_but_forged_payload_is_rejected(
    gateway, api
) -> None:
    _publish(gateway, api)
    permit = _permit(api)
    _issue(gateway, api, permit)
    gateway.make_outbox_durable(permit)
    # Idempotent identical replay is fine.
    replayed = gateway.make_outbox_durable(permit)
    assert replayed.payload_hash == (
        permit.send_claim_expected_versions.outbox_payload_hash
    )
    # Forging the payload reuses the batch id with different content;
    # the store rejects the colliding batch identity fail-closed.
    forged = permit.model_copy(
        update={
            "send_claim_expected_versions": (
                permit.send_claim_expected_versions.model_copy(
                    update={"outbox_payload_hash": HASH_F}
                )
            )
        }
    )
    with pytest.raises(CapitalGatewayError) as excinfo:
        gateway.make_outbox_durable(forged)
    assert excinfo.value.code == "outbox_identity_conflict"


def test_outbox_requires_permitted_seal(gateway, api) -> None:
    seal = _publish(gateway, api)
    permit = _permit(api)
    with pytest.raises(CapitalGatewayError) as excinfo:
        gateway.make_outbox_durable(permit)
    assert excinfo.value.code == "outbox_requires_permitted"
    assert gateway.entry_state(seal.seal_id).status == "SEALED"


# -- cancellation before claim ----------------------------------------------


def test_cancel_permit_from_sealed_tombstones_and_releases(
    gateway, api
) -> None:
    seal = _publish(gateway, api)
    cancelled_state = _permit_evaluation_state(
        api,
        seal,
        authorization_lifecycle=api.AuthorizationLifecycle.REVOKED,
        authorization_status_version=seal.authorization_status_version + 1,
        authorization_status_hash=HASH_A,
    )
    cancel_lines = tuple(
        _permit_line(
            api,
            sealed_line,
            disposition=api.PermitDisposition.CANCEL,
            permitted_quantity=0,
        )
        for sealed_line in seal.proposal.order_lines
    )
    cancel = _permit(
        api,
        disposition=api.PermitDisposition.CANCEL,
        evaluation_state=cancelled_state,
        permit_lines=cancel_lines,
    )
    context = _truth_context(api, cancelled_state)
    permitted = gateway.issue_permit(cancel, context=context)
    assert permitted.seal_status == "TOMBSTONED"
    assert permitted.total_remaining_reserve_cents == 0
    state = gateway.entry_state(seal.seal_id)
    assert state.status == "TOMBSTONED"
    assert state.permit_nonce_state == "INVALIDATED"
    assert state.remaining_reserved_cash_cents == 0


def test_halted_truth_allows_cancel_but_not_allow(gateway, api) -> None:
    seal = _publish(gateway, api)
    halted_context = dataclasses.replace(
        _truth_context(api, _permit(api).evaluation_state),
        risk_latch=RiskLatchState.RISK_HALTED,
    )
    with pytest.raises(CapitalGatewayError):
        _issue(gateway, api, context=halted_context)
    # A CANCEL permit witnessed by the halt is the legal exit path.
    cancelled_state = _permit_evaluation_state(
        api,
        seal,
        risk_latch=RiskLatchState.RISK_HALTED,
    )
    cancel_lines = tuple(
        _permit_line(
            api,
            sealed_line,
            disposition=api.PermitDisposition.CANCEL,
            permitted_quantity=0,
            reason_code=api.PermitReasonCode.RISK_HALT_CANCEL,
        )
        for sealed_line in seal.proposal.order_lines
    )
    cancel = _permit(
        api,
        disposition=api.PermitDisposition.CANCEL,
        evaluation_state=cancelled_state,
        permit_lines=cancel_lines,
    )
    context = _truth_context(api, cancelled_state)
    gateway.issue_permit(cancel, context=context)
    assert gateway.entry_state(seal.seal_id).status == "TOMBSTONED"


def test_cancel_receipt_tombstones_unclaimed_outbox(gateway, api) -> None:
    seal = _publish(gateway, api)
    permit = _permit(api)
    _issue(gateway, api, permit)
    gateway.make_outbox_durable(permit)
    receipt = _receipt(api, prior_permit=permit)
    gateway.cancel_unclaimed_entry(receipt)
    state = gateway.entry_state(seal.seal_id)
    assert state.status == "TOMBSTONED"
    assert state.permit_nonce_state == "INVALIDATED"
    assert state.outbox_state == "TOMBSTONED"
    assert state.remaining_reserved_cash_cents == 0


def test_cancel_receipt_is_idempotent_for_identical_replay(
    gateway, api
) -> None:
    seal = _publish(gateway, api)
    permit = _permit(api)
    _issue(gateway, api, permit)
    gateway.make_outbox_durable(permit)
    receipt = _receipt(api, prior_permit=permit)
    gateway.cancel_unclaimed_entry(receipt)
    gateway.cancel_unclaimed_entry(receipt)  # identical replay
    assert gateway.entry_state(seal.seal_id).status == "TOMBSTONED"


def test_cancel_receipt_binds_exact_store_permit(gateway, api) -> None:
    seal = _publish(gateway, api)
    permit = _permit(api)
    _issue(gateway, api, permit)
    gateway.make_outbox_durable(permit)
    forged = _receipt(api, prior_permit=permit).model_copy(
        update={"permit_nonce": "other-nonce"}
    )
    with pytest.raises(CapitalGatewayError) as excinfo:
        gateway.cancel_unclaimed_entry(forged)
    assert excinfo.value.code == "receipt_store_mismatch"
    assert gateway.entry_state(seal.seal_id).status == "OUTBOX_DURABLE"


def test_cancel_receipt_requires_unclaimed_state(gateway, api) -> None:
    seal = _publish(gateway, api)
    receipt = _receipt(api)  # prior permit never issued in this store
    with pytest.raises(CapitalGatewayError) as excinfo:
        gateway.cancel_unclaimed_entry(receipt)
    assert excinfo.value.code == "cancel_state_conflict"
    state = gateway.entry_state(seal.seal_id)
    assert state.status == "SEALED"
    assert state.remaining_reserved_cash_cents == _seal_reserve_total(api, seal)


# -- crash matrix: before/after every state ---------------------------------


def _crashing_gateway(tmp_path, clock, phase: str) -> CapitalGateway:
    def hook(name: str) -> None:
        if name == phase:
            raise RuntimeError(f"simulated crash at {name}")

    return CapitalGateway(
        database_path=str(tmp_path / "crash.sqlite3"),
        clock=clock,
        _fault_hook=hook,
    )


@pytest.mark.parametrize(
    "phase",
    [
        "issue.after_permit_row",
        "issue.after_line_rows",
        "issue.after_reserve_update",
        "issue.after_seal_status",
        "outbox.after_row",
        "outbox.after_seal_status",
        "claim.after_seal_status",
        "claim.after_nonce_consumed",
        "claim.after_claim_rows",
    ],
)
def test_crash_mid_transition_leaves_prior_state_intact(
    tmp_path, api, clock, phase
) -> None:
    seal = _permit(api).seal
    crashing = _crashing_gateway(tmp_path, clock, phase)
    _publish(crashing, api, seal)
    permit = _permit(api)
    expected = permit.send_claim_expected_versions
    context = _claim_context(api, expected)

    crashed = False

    def drive(gateway: CapitalGateway) -> None:
        nonlocal crashed
        try:
            gateway.issue_permit(
                permit, context=_truth_context(api, permit.evaluation_state)
            )
            gateway.make_outbox_durable(permit)
            gateway.claim_send(permit, expected, context=context)
        except CapitalGatewayError:
            raise
        except RuntimeError as exc:
            assert "simulated crash" in str(exc)
            crashed = True

    drive(crashing)
    assert crashed

    # The store must be in exactly one of the states preceding the crash
    # point, with no partial rows, and the transition must be replayable.
    recovered = CapitalGateway(
        database_path=str(tmp_path / "crash.sqlite3"), clock=clock
    )
    state = recovered.entry_state(seal.seal_id)
    pre_states = {
        "issue.after_permit_row": ("SEALED", None),
        "issue.after_line_rows": ("SEALED", None),
        "issue.after_reserve_update": ("SEALED", None),
        "issue.after_seal_status": ("SEALED", None),
        "outbox.after_row": ("PERMITTED", None),
        "outbox.after_seal_status": ("PERMITTED", None),
        "claim.after_seal_status": ("OUTBOX_DURABLE", "DURABLE"),
        "claim.after_nonce_consumed": ("OUTBOX_DURABLE", "DURABLE"),
        "claim.after_claim_rows": ("OUTBOX_DURABLE", "DURABLE"),
    }
    expected_status, expected_outbox = pre_states[phase]
    assert state.status == expected_status
    assert state.outbox_state == expected_outbox
    # Unchanged permit: the full worst-case reserve stays reserved in
    # every pre-crash state.
    assert state.remaining_reserved_cash_cents == _seal_reserve_total(api, seal)

    drive(recovered)
    final = recovered.entry_state(seal.seal_id)
    assert final.status == "SEND_CLAIMED"
    assert final.permit_nonce_state == "CONSUMED"
    assert final.send_claim_sequence == 1


def test_crashed_unclaimed_outbox_is_tombstoneable(tmp_path, api, clock) -> None:
    db_path = str(tmp_path / "tombstone.sqlite3")
    gateway = CapitalGateway(database_path=db_path, clock=clock)
    seal = _publish(gateway, api)
    permit = _permit(api)
    _issue(gateway, api, permit)
    gateway.make_outbox_durable(permit)

    # Simulate a dispatcher crash right after durability: a fresh gateway
    # process must still see the unclaimed outbox and may tombstone it.
    reopened = CapitalGateway(database_path=db_path, clock=clock)
    state = reopened.entry_state(seal.seal_id)
    assert state.status == "OUTBOX_DURABLE"
    assert state.remaining_reserved_cash_cents == _seal_reserve_total(api, seal)
    receipt = _receipt(api, prior_permit=permit)
    reopened.cancel_unclaimed_entry(receipt)
    final = reopened.entry_state(seal.seal_id)
    assert final.status == "TOMBSTONED"
    assert final.remaining_reserved_cash_cents == 0


@pytest.mark.parametrize(
    "phase",
    [
        "cancel.after_seal_status",
        "cancel.after_outbox",
        "cancel.after_permit_nonce",
        "cancel.after_reserves",
    ],
)
def test_crash_mid_cancel_leaves_unclaimed_entry_intact(
    tmp_path, api, clock, phase
) -> None:
    crashing = _crashing_gateway(tmp_path, clock, phase)
    _publish(crashing, api)
    permit = _permit(api)
    _issue(crashing, api, permit)
    crashing.make_outbox_durable(permit)
    receipt = _receipt(api, prior_permit=permit)
    with pytest.raises(RuntimeError, match="simulated crash"):
        crashing.cancel_unclaimed_entry(receipt)

    # Every write belongs to the one cancel transaction: a crash at any
    # phase leaves the unclaimed entry wholly intact and tombstoneable.
    recovered = CapitalGateway(
        database_path=str(tmp_path / "crash.sqlite3"), clock=clock
    )
    state = recovered.entry_state(permit.seal_id)
    assert state.status == "OUTBOX_DURABLE"
    assert state.permit_nonce_state == "ACTIVE"
    assert state.outbox_state == "DURABLE"
    assert state.remaining_reserved_cash_cents == _seal_reserve_total(api)
    recovered.cancel_unclaimed_entry(receipt)
    final = recovered.entry_state(permit.seal_id)
    assert final.status == "TOMBSTONED"
    assert final.outbox_state == "TOMBSTONED"
    assert final.remaining_reserved_cash_cents == 0
