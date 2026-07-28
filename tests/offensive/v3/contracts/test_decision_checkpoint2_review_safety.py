"""Task 3 review RED: current truth, cancellation, and typed public contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tests.offensive.v3.contracts.checkpoint2_helpers import (
    HASH_A,
    HASH_F,
    _api,
    _permit,
    _permit_evaluation_state,
    _permit_line,
    _permit_payload,
    _seal,
)


def test_permit_evaluation_state_has_exact_current_truth_schema() -> None:
    api = _api()
    assert set(api.PermitEvaluationState.model_fields) == {
        "policy_activation_hash",
        "trust_bundle_hash",
        "registry_epoch",
        "policy_epoch",
        "authority_epoch",
        "risk_epoch",
        "authorization_id",
        "authorization_version",
        "authorization_envelope_hash",
        "authorization_lifecycle",
        "authorization_status_version",
        "authorization_status_hash",
        "authorization_revalidation_required",
        "evidence_set_merkle_root",
        "entry_fence_id",
        "entry_fence_hash",
        "entry_fence_version",
        "capital_version",
        "capital_stream_version",
        "risk_snapshot_id",
        "risk_snapshot_artifact_hash",
        "risk_snapshot_version",
        "risk_snapshot_freshness",
        "risk_snapshot_completeness",
        "risk_latch",
        "reconciliation_latch",
        "stage_loss_bindings",
        "reservation_id",
        "reservation_version",
        "reservation_state",
        "remaining_reserved_cash_cents",
        "writer_fencing_epoch",
    }
    assert set(api.PermitCancellationBinding.model_fields) == {
        "permit_nonce",
        "reservation_id",
        "pre_reservation_version",
        "post_reservation_version",
        "post_reservation_state",
        "released_cash_cents",
        "remaining_reserved_cash_cents",
        "outbox_batch_id",
        "outbox_payload_hash",
        "post_outbox_state",
        "post_capital_version",
        "post_capital_stream_version",
        "writer_fencing_epoch",
    }


def test_public_state_vocabularies_are_closed_typed_enums() -> None:
    api = _api()
    assert {item.value for item in api.PermitNonceState} == {
        "ACTIVE",
        "CONSUMED",
        "INVALIDATED",
    }
    assert {item.value for item in api.ReservationState} == {"ACTIVE", "RELEASED"}
    assert {item.value for item in api.OutboxState} == {"DURABLE", "TOMBSTONED"}
    assert {item.value for item in api.AuthorizationLifecycle} == {
        "ACTIVE",
        "REVALIDATION_REQUIRED",
        "REVOKED",
        "EXPIRED",
    }
    assert api.ExecutionPermit.model_fields["permit_nonce_state"].annotation is (
        api.PermitNonceState
    )
    assert api.PermitEvaluationState.model_fields[
        "authorization_lifecycle"
    ].annotation is (api.AuthorizationLifecycle)
    assert api.PermitEvaluationState.model_fields["reservation_state"].annotation is (
        api.ReservationState
    )
    assert api.SendClaimExpectedVersions.model_fields["outbox_state"].annotation is (
        api.OutboxState
    )
    for model, field, invalid in (
        (api.ExecutionPermit, "permit_nonce_state", "PENDING"),
        (api.PermitEvaluationState, "reservation_state", "HELD"),
        (api.SendClaimExpectedVersions, "outbox_state", "READY"),
    ):
        assert invalid not in {
            item.value for item in model.model_fields[field].annotation
        }


def test_review_types_have_stable_public_module_identity() -> None:
    api = _api()
    assert api.TrustedClockObservation.__module__ == (
        "src.screening.offensive.v3.contracts.decision"
    )
    for public_type in (
        api.PermitNonceState,
        api.ReservationState,
        api.OutboxState,
        api.PermitEvaluationState,
        api.PermitCancellationBinding,
    ):
        assert (
            public_type.__module__ == "src.screening.offensive.v3.contracts.execution"
        )


@pytest.mark.parametrize(
    ("reason", "state_overrides"),
    [
        ("AUTHORIZATION_CANCEL", {}),
        ("STAGE_HALT_CANCEL", {}),
        ("RECONCILIATION_CANCEL", {}),
        ("FACT_INTEGRITY_CANCEL", {}),
        ("FENCE_CANCEL", {}),
    ],
)
def test_cancel_reason_must_be_witnessed_by_current_evaluation_truth(
    reason: str, state_overrides: dict[str, object]
) -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(api, seal, **state_overrides)
    lines = tuple(
        _permit_line(
            api,
            line,
            disposition=api.PermitDisposition.CANCEL,
            permitted_quantity=0,
            reason_code=api.PermitReasonCode(reason),
        )
        for line in seal.proposal.order_lines
    )
    with pytest.raises(
        ValidationError,
        match="authorization|stage|reconciliation|fact|fresh|complete|fence|reason",
    ):
        api.ExecutionPermit.model_validate(
            _permit_payload(
                api,
                seal=seal,
                disposition=api.PermitDisposition.CANCEL,
                permit_lines=lines,
                evaluation_state=current,
            )
        )


def test_stage_halt_cancel_binds_release_and_tombstone_transaction() -> None:
    api = _api()
    seal = _seal(api)
    clear = _permit_evaluation_state(api, seal)
    halted_stage = clear.stage_loss_bindings[0].model_copy(
        update={"stage_loss_latch": api.StageLossLatchState.STAGE_LOSS_HALTED}
    )
    halted = _permit_evaluation_state(
        api,
        seal,
        stage_loss_bindings=(halted_stage, *clear.stage_loss_bindings[1:]),
    )
    lines = tuple(
        _permit_line(
            api,
            line,
            disposition=api.PermitDisposition.CANCEL,
            permitted_quantity=0,
            reason_code=api.PermitReasonCode.STAGE_HALT_CANCEL,
        )
        for line in seal.proposal.order_lines
    )
    permit = _permit(
        api,
        seal=seal,
        disposition=api.PermitDisposition.CANCEL,
        permit_lines=lines,
        evaluation_state=halted,
    )
    binding = permit.cancellation_binding
    assert permit.send_claim_expected_versions is None
    assert binding.pre_reservation_version == halted.reservation_version
    assert binding.post_reservation_version > binding.pre_reservation_version
    assert binding.post_reservation_state is api.ReservationState.RELEASED
    assert binding.released_cash_cents == halted.remaining_reserved_cash_cents
    assert binding.remaining_reserved_cash_cents == 0
    assert binding.post_outbox_state is api.OutboxState.TOMBSTONED
    assert binding.post_capital_version > halted.capital_version
    assert binding.post_capital_stream_version > halted.capital_stream_version


@pytest.mark.parametrize(
    "cause",
    [
        "authorization_revoked",
        "authorization_revalidation",
        "stale",
        "incomplete",
        "risk_halt",
        "reconciliation_halt",
        "stage_halt",
    ],
)
def test_allow_requires_current_truth_to_remain_sendable(cause: str) -> None:
    api = _api()
    seal = _seal(api)
    state_change = {
        "authorization_revoked": {
            "authorization_lifecycle": api.AuthorizationLifecycle.REVOKED
        },
        "authorization_revalidation": {"authorization_revalidation_required": True},
        "stale": {"risk_snapshot_freshness": api.RiskSnapshotFreshness.STALE},
        "incomplete": {
            "risk_snapshot_completeness": api.RiskSnapshotCompleteness.INCOMPLETE
        },
        "risk_halt": {"risk_latch": api.RiskLatchState.RISK_HALTED},
        "reconciliation_halt": {
            "reconciliation_latch": (api.ReconciliationLatchState.RECONCILIATION_HALT)
        },
        "stage_halt": {},
    }[cause]
    if cause == "stage_halt":
        clear = _permit_evaluation_state(api, seal)
        stage = clear.stage_loss_bindings[0].model_copy(
            update={"stage_loss_latch": api.StageLossLatchState.STAGE_LOSS_HALTED}
        )
        state_change["stage_loss_bindings"] = (
            stage,
            *clear.stage_loss_bindings[1:],
        )
    current = _permit_evaluation_state(api, seal, **state_change)
    with pytest.raises(
        ValidationError,
        match="ALLOW|authorization|revalidation|fresh|complete|risk|reconciliation|stage|halt",
    ):
        api.ExecutionPermit.model_validate(
            _permit_payload(api, seal=seal, evaluation_state=current)
        )


@pytest.mark.parametrize(
    "cause",
    ["authorization", "stage", "reconciliation", "fact_integrity", "fence"],
)
def test_cancel_accepts_only_a_matching_current_truth_witness(cause: str) -> None:
    api = _api()
    seal = _seal(api)
    clear = _permit_evaluation_state(api, seal)
    reason = {
        "authorization": api.PermitReasonCode.AUTHORIZATION_CANCEL,
        "stage": api.PermitReasonCode.STAGE_HALT_CANCEL,
        "reconciliation": api.PermitReasonCode.RECONCILIATION_CANCEL,
        "fact_integrity": api.PermitReasonCode.FACT_INTEGRITY_CANCEL,
        "fence": api.PermitReasonCode.FENCE_CANCEL,
    }[cause]
    changes = {
        "authorization": {
            "authorization_lifecycle": api.AuthorizationLifecycle.REVOKED
        },
        "stage": {
            "stage_loss_bindings": (
                clear.stage_loss_bindings[0].model_copy(
                    update={
                        "stage_loss_latch": (api.StageLossLatchState.STAGE_LOSS_HALTED)
                    }
                ),
                *clear.stage_loss_bindings[1:],
            )
        },
        "reconciliation": {
            "reconciliation_latch": (api.ReconciliationLatchState.RECONCILIATION_HALT)
        },
        "fact_integrity": {"risk_snapshot_freshness": api.RiskSnapshotFreshness.STALE},
        "fence": {
            "entry_fence_id": "entry-fence-2",
            "entry_fence_hash": HASH_A,
            "entry_fence_version": seal.entry_fence_version + 1,
        },
    }[cause]
    current = _permit_evaluation_state(api, seal, **changes)
    lines = tuple(
        _permit_line(
            api,
            line,
            disposition=api.PermitDisposition.CANCEL,
            permitted_quantity=0,
            reason_code=reason,
        )
        for line in seal.proposal.order_lines
    )
    permit = _permit(
        api,
        seal=seal,
        disposition=api.PermitDisposition.CANCEL,
        permit_lines=lines,
        evaluation_state=current,
    )
    assert permit.disposition is api.PermitDisposition.CANCEL
    assert permit.send_claim_expected_versions is None
    assert permit.cancellation_binding is not None


@pytest.mark.parametrize(
    ("field", "value_kind"),
    [
        ("post_reservation_version", "pre_reservation_version"),
        ("post_reservation_state", "active"),
        ("released_cash_cents", "short_release"),
        ("remaining_reserved_cash_cents", "positive"),
        ("post_outbox_state", "durable"),
        ("post_capital_version", "current_capital"),
        ("post_capital_stream_version", "current_stream"),
    ],
)
def test_cancel_binding_must_prove_one_atomic_release_and_tombstone(
    field: str, value_kind: str
) -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(
        api,
        seal,
        authorization_lifecycle=api.AuthorizationLifecycle.REVOKED,
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
    valid = _permit(
        api,
        seal=seal,
        disposition=api.PermitDisposition.CANCEL,
        permit_lines=lines,
        evaluation_state=current,
    )
    values = {
        "pre_reservation_version": valid.cancellation_binding.pre_reservation_version,
        "active": api.ReservationState.ACTIVE,
        "short_release": current.remaining_reserved_cash_cents - 1,
        "positive": 1,
        "durable": api.OutboxState.DURABLE,
        "current_capital": current.capital_version,
        "current_stream": current.capital_stream_version,
    }
    changed = valid.cancellation_binding.model_copy(update={field: values[value_kind]})
    with pytest.raises(
        ValidationError,
        match="cancel|reservation|release|remaining|outbox|tombstone|capital|stream",
    ):
        api.ExecutionPermit.model_validate(
            _permit_payload(
                api,
                seal=seal,
                disposition=api.PermitDisposition.CANCEL,
                permit_lines=lines,
                evaluation_state=current,
                cancellation_binding=changed,
            )
        )


def test_permit_predicate_policy_is_the_sealed_execution_policy() -> None:
    api = _api()
    permit = _permit(api)
    assert {line.predicate_policy_version for line in permit.permit_lines} == {
        permit.execution_window.execution_policy_version
    }
    changed = permit.permit_lines[0].model_copy(
        update={"predicate_policy_version": "preopen-alpha.v1"}
    )
    with pytest.raises(ValidationError, match="predicate|execution|policy|sealed"):
        api.ExecutionPermit.model_validate(
            _permit_payload(
                api,
                permit_lines=(changed, *permit.permit_lines[1:]),
            )
        )


def test_allow_rejects_current_fence_drift_even_when_hash_is_well_formed() -> None:
    api = _api()
    seal = _seal(api)
    drifted = _permit_evaluation_state(
        api,
        seal,
        entry_fence_id="entry-fence-2",
        entry_fence_hash=HASH_A,
        entry_fence_version=seal.entry_fence_version + 1,
    )
    with pytest.raises(ValidationError, match="ALLOW|fence|current|seal"):
        api.ExecutionPermit.model_validate(
            _permit_payload(api, seal=seal, evaluation_state=drifted)
        )


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("policy_activation_hash", HASH_F),
        ("trust_bundle_hash", HASH_F),
        ("registry_epoch", 8),
        ("policy_epoch", 5),
        ("authority_epoch", 6),
        ("risk_epoch", 7),
        ("authorization_id", "other-authorization"),
        ("authorization_version", 4),
        ("authorization_envelope_hash", HASH_F),
        ("evidence_set_merkle_root", HASH_F),
        ("writer_fencing_epoch", 12),
    ],
)
def test_allow_current_truth_preserves_every_immutable_seal_authority_binding(
    field: str, changed: object
) -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(api, seal, **{field: changed})
    with pytest.raises(
        ValidationError,
        match="ALLOW|policy|trust|registry|epoch|authorization|evidence|writer|fence|seal",
    ):
        api.ExecutionPermit.model_validate(
            _permit_payload(api, seal=seal, evaluation_state=current)
        )
