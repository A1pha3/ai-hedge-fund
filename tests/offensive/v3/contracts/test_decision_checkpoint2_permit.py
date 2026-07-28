"""Checkpoint 2 RED: execution permit shrink, cancel, outbox, and claim bindings."""

from __future__ import annotations

# Explicit shared fixture surface; individual focused files intentionally use subsets.
# ruff: noqa: F401
from datetime import timedelta, timezone
from decimal import Decimal
import hashlib

import pytest
from pydantic import ValidationError

from tests.offensive.v3.contracts.checkpoint2_helpers import (
    APPROVED_SERIALIZATION_DIGESTS,
    BROKER_CUTOFF,
    CHECKPOINT2_NAMES,
    CLOSE_FINALIZED,
    DIFFERENT_LOGICAL_KEY,
    HASH_A,
    HASH_B,
    HASH_C,
    HASH_D,
    HASH_E,
    HASH_F,
    PERMIT_DEADLINE,
    PERMIT_EXPIRES,
    SEAL_CREATED,
    SEAL_DEADLINE,
    SEND_DEADLINE,
    SIGNAL_SESSION,
    TARGET_SESSION,
    _api,
    _cancellation_binding,
    _gateway_expected_versions,
    _gateway_issuer,
    _permit,
    _permit_evaluation_state,
    _permit_line,
    _permit_payload,
    _prior_seal_eligibility,
    _proposal,
    _proposal_line,
    _reserve_bindings,
    _seal,
    _seal_payload,
    _send_claim_versions,
    _shadow,
    _shadow_line,
    _shadow_payload,
    _shadow_stage_binding,
    _stage_binding,
    _stage_expected_version,
    _window,
    _window_payload,
)


def test_execution_permit_has_exact_complete_binding_fields() -> None:
    api = _api()

    assert set(api.ExecutionPermit.model_fields) == {
        "artifact_kind",
        "artifact_namespace",
        "schema_major",
        "permit_id",
        "permit_nonce",
        "permit_nonce_sequence",
        "permit_nonce_state",
        "disposition",
        "seal",
        "seal_id",
        "seal_revision",
        "seal_artifact_hash",
        "logical_key",
        "proposal_artifact_hash",
        "portfolio_id",
        "broker_account_id",
        "broker_account_fingerprint",
        "base_currency",
        "mode",
        "target_entry_session",
        "permit_lines",
        "total_remaining_reserve_cents",
        "total_released_reserve_cents",
        "permit_clock_observation",
        "evaluation_state",
        "send_claim_expected_versions",
        "cancellation_binding",
        "execution_window",
        "issued_at",
        "permit_expires_at",
        "issuer_binding",
    }
    assert set(api.ExecutionPermitLine.model_fields) == {
        "order_line_id",
        "security_id",
        "sealed_quantity_units",
        "permitted_quantity_units",
        "reason_code",
        "predicate_policy_version",
        "preopen_fact_snapshot_id",
        "preopen_fact_snapshot_hash",
        "preopen_fact_as_of",
        "client_order_id",
        "order_type",
        "limit_price_cents",
        "worst_case_price_cents",
        "price_boundary_version",
        "time_in_force",
        "exit_session_ordinal",
        "sealed_reserve_cents",
        "remaining_reserve_cents",
        "released_reserve_cents",
    }


def test_send_claim_expected_versions_freezes_complete_recheck_bundle() -> None:
    api = _api()
    assert set(api.SendClaimExpectedVersions.model_fields) == {
        "active_seal_id",
        "active_seal_revision",
        "active_seal_artifact_hash",
        "active_permit_id",
        "active_permit_nonce",
        "permit_nonce_sequence",
        "permit_nonce_state",
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
        "outbox_batch_id",
        "outbox_payload_hash",
        "outbox_state",
        "outbox_permit_nonce",
        "writer_fencing_epoch",
        "effective_send_deadline",
    }


def test_permit_identity_and_current_to_post_cas_progression_are_exact() -> None:
    api = _api()
    permit = _permit(api)
    expected = permit.send_claim_expected_versions
    assert permit.seal_artifact_hash == permit.seal.artifact_hash()
    assert permit.logical_key == permit.seal.logical_key
    assert permit.proposal_artifact_hash == permit.seal.proposal_artifact_hash
    assert expected.active_permit_nonce == permit.permit_nonce
    assert expected.outbox_permit_nonce == permit.permit_nonce
    assert expected.effective_send_deadline == min(
        permit.permit_expires_at,
        permit.execution_window.gateway_send_deadline,
    )

    top_level_drifts = (
        {"seal_id": "other-seal"},
        {"seal_revision": permit.seal_revision + 1},
        {"seal_artifact_hash": HASH_F},
        {
            "logical_key": permit.logical_key.model_copy(
                update={"decision_cycle_id": "other-cycle"}
            )
        },
        {"proposal_artifact_hash": HASH_F},
        {"portfolio_id": "other-portfolio"},
        {"broker_account_id": "other-account"},
        {"broker_account_fingerprint": HASH_F},
        {"base_currency": "USD"},
        {"mode": api.ExecutionMode.MANUAL_CONFIRMED},
        {"target_entry_session": TARGET_SESSION + timedelta(days=1)},
    )
    for drift in top_level_drifts:
        with pytest.raises(
            ValidationError,
            match="seal|logical|proposal|portfolio|account|currency|mode|session|nonce",
        ):
            api.ExecutionPermit.model_validate(_permit_payload(api, **drift))

    current = permit.evaluation_state
    assert current.risk_snapshot_id != permit.seal.risk_snapshot_id
    assert current.capital_version > permit.seal.post_admission_capital_version
    assert current.capital_stream_version > permit.seal.capital_stream_version
    assert current.reservation_version > permit.seal.post_admission_reservation_version
    assert expected.capital_version > current.capital_version
    assert expected.capital_stream_version > current.capital_stream_version
    assert expected.reservation_version > current.reservation_version
    assert expected.risk_snapshot_version >= current.risk_snapshot_version
    assert all(
        post.stage_loss_version >= pre.stage_loss_version
        for pre, post in zip(
            current.stage_loss_bindings, expected.stage_loss_bindings, strict=True
        )
    )

    expected_drifts = {
        "active_seal_id": "other-seal",
        "active_seal_revision": expected.active_seal_revision + 1,
        "active_seal_artifact_hash": HASH_F,
        "active_permit_id": "other-permit",
        "active_permit_nonce": "other-nonce",
        "permit_nonce_sequence": expected.permit_nonce_sequence + 1,
        "permit_nonce_state": "CONSUMED",
        "policy_activation_hash": HASH_F,
        "trust_bundle_hash": HASH_F,
        "registry_epoch": expected.registry_epoch + 1,
        "policy_epoch": expected.policy_epoch + 1,
        "authority_epoch": expected.authority_epoch + 1,
        "risk_epoch": expected.risk_epoch + 1,
        "authorization_id": "other-authorization",
        "authorization_version": expected.authorization_version + 1,
        "authorization_envelope_hash": HASH_F,
        "authorization_lifecycle": api.AuthorizationLifecycle.REVOKED,
        "evidence_set_merkle_root": HASH_F,
        "entry_fence_id": "other-fence",
        "entry_fence_hash": HASH_A,
        "entry_fence_version": expected.entry_fence_version + 1,
        "capital_version": current.capital_version,
        "capital_stream_version": current.capital_stream_version,
        "risk_snapshot_version": current.risk_snapshot_version - 1,
        "stage_loss_bindings": current.stage_loss_bindings,
        "reservation_id": "other-reservation",
        "reservation_version": current.reservation_version,
        "reservation_state": api.ReservationState.RELEASED,
        "remaining_reserved_cash_cents": (expected.remaining_reserved_cash_cents + 1),
        "outbox_permit_nonce": "different-nonce",
        "writer_fencing_epoch": expected.writer_fencing_epoch + 1,
        "effective_send_deadline": (
            expected.effective_send_deadline + timedelta(microseconds=1)
        ),
    }
    for field, value in expected_drifts.items():
        changed = expected.model_copy(update={field: value})
        with pytest.raises(
            ValidationError,
            match="seal|permit|nonce|policy|trust|registry|authority|authorization|risk|fence|capital|stage|reservation|outbox|deadline|latch",
        ):
            api.ExecutionPermit.model_validate(
                _permit_payload(api, send_claim_expected_versions=changed)
            )


def test_permit_nonce_contract_is_single_use_shaped_and_cannot_self_claim() -> None:
    api = _api()
    permit = _permit(api)
    assert permit.permit_nonce_state is api.PermitNonceState.ACTIVE
    assert (
        permit.send_claim_expected_versions.permit_nonce_state
        is api.PermitNonceState.ACTIVE
    )
    assert "nonce_consumed_at" not in api.ExecutionPermit.model_fields
    assert "send_claimed_at" not in api.ExecutionPermit.model_fields

    for field, value in (
        ("permit_nonce_state", "CONSUMED"),
        ("permit_nonce_sequence", 0),
    ):
        with pytest.raises(ValidationError, match="nonce|greater than"):
            api.ExecutionPermit.model_validate(_permit_payload(api, **{field: value}))


def test_permit_line_set_exactly_matches_seal_and_never_grows_own_line() -> None:
    api = _api()
    permit = _permit(api)
    lines = list(permit.permit_lines)
    assert tuple(line.order_line_id for line in lines) == tuple(
        line.order_line_id for line in _seal(api).proposal.order_lines
    )

    added = lines[0].model_copy(
        update={"order_line_id": "new-line", "security_id": "000001.SZ"}
    )
    grown = lines[0].model_copy(
        update={"permitted_quantity_units": lines[0].sealed_quantity_units + 100}
    )
    for changed in ((added, *lines[1:]), (grown, *lines[1:]), tuple(lines[:1])):
        with pytest.raises(ValidationError, match="line|quantity|seal"):
            api.ExecutionPermit.model_validate(
                _permit_payload(api, permit_lines=changed)
            )


def test_permit_accepts_partial_positive_shrink_with_exact_cash_release() -> None:
    api = _api()
    seal = _seal(api)
    lines = (
        _permit_line(api, seal.proposal.order_lines[0]),
        _permit_line(
            api,
            seal.proposal.order_lines[1],
            permitted_quantity=100,
            reason_code=api.PermitReasonCode.CAPITAL_RISK_REDUCTION,
        ),
    )
    permit = _permit(api, seal=seal, permit_lines=lines)
    changed = permit.permit_lines[1]

    assert changed.permitted_quantity_units == 100
    assert changed.remaining_reserve_cents == 800 * 100 + 75
    assert changed.released_reserve_cents == 800 * 100
    assert permit.total_released_reserve_cents == 800 * 100


def test_same_total_quantity_cannot_hide_line_a_shrink_and_line_b_growth() -> None:
    api = _api()
    permit = _permit(api)
    line_b, line_a = permit.permit_lines
    changed = (
        line_b.model_copy(
            update={
                "permitted_quantity_units": line_b.permitted_quantity_units + 100,
                "remaining_reserve_cents": (
                    line_b.worst_case_price_cents
                    * (line_b.permitted_quantity_units + 100)
                    + 50
                ),
            }
        ),
        line_a.model_copy(
            update={
                "permitted_quantity_units": line_a.permitted_quantity_units - 100,
                "reason_code": api.PermitReasonCode.CAPITAL_RISK_REDUCTION,
                "remaining_reserve_cents": (
                    line_a.worst_case_price_cents
                    * (line_a.permitted_quantity_units - 100)
                    + 75
                ),
                "released_reserve_cents": (line_a.worst_case_price_cents * 100),
            }
        ),
    )
    assert sum(line.permitted_quantity_units for line in changed) == sum(
        line.sealed_quantity_units for line in permit.permit_lines
    )
    with pytest.raises(ValidationError, match="line|grow|sealed|quantity"):
        api.ExecutionPermit.model_validate(_permit_payload(api, permit_lines=changed))


def test_permit_cannot_change_line_economics_or_reallocate_released_cash() -> None:
    api = _api()
    permit = _permit(api)
    line = permit.permit_lines[0]
    drift = {
        "security_id": "000001.SZ",
        "sealed_quantity_units": line.sealed_quantity_units + 100,
        "order_type": "MARKET",
        "limit_price_cents": line.limit_price_cents + 1,
        "worst_case_price_cents": line.worst_case_price_cents + 1,
        "price_boundary_version": "other-price-boundary.v2",
        "time_in_force": "DAY",
        "exit_session_ordinal": 9,
        "sealed_reserve_cents": line.sealed_reserve_cents + 1,
        "remaining_reserve_cents": line.remaining_reserve_cents + 1,
        "released_reserve_cents": line.released_reserve_cents + 1,
    }
    for field, value in drift.items():
        changed = line.model_copy(update={field: value})
        with pytest.raises(
            ValidationError, match="line|security|price|order|time|exit|reserve"
        ):
            api.ExecutionPermit.model_validate(
                _permit_payload(
                    api,
                    permit_lines=(changed, *permit.permit_lines[1:]),
                )
            )


@pytest.mark.parametrize(
    "reason",
    ["PREOPEN_ALPHA", "NEWS", "QUOTE", "DISCRETIONARY"],
)
def test_permit_reasons_reject_alpha_news_quote_and_discretion(reason) -> None:
    api = _api()
    assert {item.value for item in api.PermitReasonCode} == {
        "UNCHANGED",
        "AVAILABILITY_REDUCTION",
        "PRICE_REDUCTION",
        "CAPACITY_REDUCTION",
        "CASH_REDUCTION",
        "CAPITAL_RISK_REDUCTION",
        "STAGE_HALT_CANCEL",
        "RECONCILIATION_CANCEL",
        "FACT_INTEGRITY_CANCEL",
        "AUTHORIZATION_CANCEL",
        "FENCE_CANCEL",
        "DEADLINE_CANCEL",
    }
    line = _permit(api).permit_lines[0]
    with pytest.raises(ValidationError, match="reason"):
        api.ExecutionPermitLine.model_validate(
            line.model_dump(mode="python", round_trip=True) | {"reason_code": reason}
        )


@pytest.mark.parametrize(
    "reason",
    [
        "AVAILABILITY_REDUCTION",
        "PRICE_REDUCTION",
        "CAPACITY_REDUCTION",
        "CASH_REDUCTION",
        "CAPITAL_RISK_REDUCTION",
        "STAGE_HALT_CANCEL",
        "RECONCILIATION_CANCEL",
        "FACT_INTEGRITY_CANCEL",
        "AUTHORIZATION_CANCEL",
        "FENCE_CANCEL",
        "DEADLINE_CANCEL",
    ],
)
def test_permit_reason_categories_are_typed_mechanical_facts(reason) -> None:
    api = _api()
    assert api.PermitReasonCode(reason).value == reason


@pytest.mark.parametrize(
    ("quantity_delta", "reason"),
    [
        (0, "CAPITAL_RISK_REDUCTION"),
        (-100, "UNCHANGED"),
        (-100, "AUTHORIZATION_CANCEL"),
    ],
)
def test_permit_reason_must_match_unchanged_shrink_or_cancel(
    quantity_delta, reason
) -> None:
    api = _api()
    seal_line = _seal(api).proposal.order_lines[1]
    quantity = seal_line.sealed_quantity_units + quantity_delta
    with pytest.raises(ValidationError, match="reason|unchanged|shrink|cancel"):
        _permit_line(
            api,
            seal_line,
            permitted_quantity=quantity,
            reason_code=api.PermitReasonCode(reason),
        )


def test_permit_rejects_future_preopen_fact_timestamp() -> None:
    api = _api()
    seal = _seal(api)
    line = _permit_line(
        api,
        seal.proposal.order_lines[0],
        preopen_fact_as_of=PERMIT_DEADLINE + timedelta(microseconds=1),
    )
    with pytest.raises(ValidationError, match="preopen|fact|issued|future"):
        api.ExecutionPermit.model_validate(
            _permit_payload(
                api,
                seal=seal,
                permit_lines=(line, _permit_line(api, seal.proposal.order_lines[1])),
            )
        )


@pytest.mark.parametrize("case", ["duplicate", "missing_positive", "present_zero"])
def test_client_order_ids_are_unique_and_exactly_match_sendable_lines(case) -> None:
    api = _api()
    seal = _seal(api)
    lines = [
        _permit_line(api, line, disposition=api.PermitDisposition.ALLOW)
        for line in seal.proposal.order_lines
    ]
    if case == "duplicate":
        lines[1] = lines[1].model_copy(
            update={"client_order_id": lines[0].client_order_id}
        )
    elif case == "missing_positive":
        lines[0] = lines[0].model_copy(update={"client_order_id": None})
    else:
        lines[0] = _permit_line(
            api,
            seal.proposal.order_lines[0],
            permitted_quantity=0,
            reason_code=api.PermitReasonCode.AUTHORIZATION_CANCEL,
            client_order_id="client-zero-line",
        )
    with pytest.raises(ValidationError, match="client|order|sendable|unique|zero"):
        api.ExecutionPermit.model_validate(
            _permit_payload(api, seal=seal, permit_lines=tuple(lines))
        )


def test_cancel_and_allow_dispositions_are_typed_and_non_interchangeable() -> None:
    api = _api()
    assert set(api.PermitDisposition) == {
        api.PermitDisposition.ALLOW,
        api.PermitDisposition.CANCEL,
    }
    allow = _permit(api)
    assert any(line.permitted_quantity_units > 0 for line in allow.permit_lines)

    seal = _seal(api)
    cancelled_lines = tuple(
        _permit_line(
            api,
            line,
            disposition=api.PermitDisposition.CANCEL,
            permitted_quantity=0,
        )
        for line in seal.proposal.order_lines
    )
    cancelled_state = _permit_evaluation_state(
        api,
        seal,
        authorization_lifecycle=api.AuthorizationLifecycle.REVOKED,
    )
    cancel = api.ExecutionPermit.model_validate(
        _permit_payload(
            api,
            disposition=api.PermitDisposition.CANCEL,
            permit_lines=cancelled_lines,
            total_remaining_reserve_cents=0,
            total_released_reserve_cents=sum(
                line.released_reserve_cents for line in cancelled_lines
            ),
            evaluation_state=cancelled_state,
        )
    )
    assert all(line.permitted_quantity_units == 0 for line in cancel.permit_lines)
    assert all(line.client_order_id is None for line in cancel.permit_lines)
    assert cancel.send_claim_expected_versions is None
    assert cancel.cancellation_binding.post_outbox_state is api.OutboxState.TOMBSTONED
    assert (
        cancel.cancellation_binding.post_reservation_state
        is api.ReservationState.RELEASED
    )

    with pytest.raises(ValidationError, match="ALLOW|positive|sendable"):
        api.ExecutionPermit.model_validate(
            cancel.model_dump(mode="python", round_trip=True)
            | {"disposition": api.PermitDisposition.ALLOW}
        )


def test_cancel_rejects_positive_line_or_durable_sendable_outbox() -> None:
    api = _api()
    seal = _seal(api)
    positive_lines = tuple(
        _permit_line(api, line, disposition=api.PermitDisposition.ALLOW)
        for line in seal.proposal.order_lines
    )
    with pytest.raises(ValidationError, match="CANCEL|zero|positive|sendable"):
        api.ExecutionPermit.model_validate(
            _permit_payload(
                api,
                seal=seal,
                disposition=api.PermitDisposition.CANCEL,
                permit_lines=positive_lines,
            )
        )

    zero_lines = tuple(
        _permit_line(
            api,
            line,
            disposition=api.PermitDisposition.CANCEL,
            permitted_quantity=0,
        )
        for line in seal.proposal.order_lines
    )
    cancelled_state = _permit_evaluation_state(
        api,
        seal,
        authorization_lifecycle=api.AuthorizationLifecycle.REVOKED,
    )
    durable = _send_claim_versions(
        api, seal, zero_lines, evaluation_state=cancelled_state
    )
    with pytest.raises(ValidationError, match="CANCEL|outbox|tombstone|sendable"):
        api.ExecutionPermit.model_validate(
            _permit_payload(
                api,
                seal=seal,
                disposition=api.PermitDisposition.CANCEL,
                permit_lines=zero_lines,
                evaluation_state=cancelled_state,
                send_claim_expected_versions=durable,
            )
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("outbox_batch_id", None),
        ("outbox_batch_id", ""),
        ("outbox_payload_hash", None),
        ("outbox_payload_hash", ""),
        ("outbox_state", "TOMBSTONED"),
        ("outbox_permit_nonce", None),
        ("outbox_permit_nonce", ""),
        ("outbox_permit_nonce", "different-nonce"),
        ("active_permit_nonce", ""),
        ("active_permit_nonce", "different-nonce"),
    ],
)
def test_allow_positive_sendable_lines_require_exact_durable_outbox_binding(
    field, value
) -> None:
    api = _api()
    permit = _permit(api)
    assert any(line.permitted_quantity_units > 0 for line in permit.permit_lines)
    assert all(
        line.client_order_id
        for line in permit.permit_lines
        if line.permitted_quantity_units > 0
    )
    expected = permit.send_claim_expected_versions
    assert expected.outbox_batch_id
    assert expected.outbox_payload_hash
    assert expected.outbox_state is api.OutboxState.DURABLE
    assert expected.outbox_permit_nonce == permit.permit_nonce

    if value == "":
        with pytest.raises(
            ValidationError,
            match="nonempty|empty|hash|nonce|outbox|identifier",
        ):
            type(expected).model_validate(
                expected.model_dump(mode="python", round_trip=True) | {field: value}
            )

    changed = expected.model_copy(update={field: value})
    with pytest.raises(
        ValidationError, match="ALLOW|outbox|durable|nonce|sendable|positive"
    ):
        api.ExecutionPermit.model_validate(
            _permit_payload(api, send_claim_expected_versions=changed)
        )
