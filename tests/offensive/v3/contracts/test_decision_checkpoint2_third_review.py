"""Third-review RED tests for complete capital and cancellation truth.

These tests intentionally describe the next contract behavior before the
production validators implement it.  They keep full-account facts distinct
from the one reservation being permitted or cancelled.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from tests.offensive.v3.contracts.checkpoint2_helpers import (
    HASH_A,
    HASH_F,
    PERMIT_DEADLINE,
    PERMIT_EXPIRES,
    SEAL_CREATED,
    _active_permit_evaluation_state,
    _api,
    _authorization_revalidation,
    _cancellation_binding,
    _mechanical_binding,
    _permit,
    _permit_evaluation_state,
    _permit_line,
    _receipt,
    _receipt_clock_observation,
    _reservation_allocations,
    _seal,
    _send_claim_versions,
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


def _cancel_lines_without_mechanical_binding(api, seal, current, reason):
    return tuple(
        api.ExecutionPermitLine.model_validate(
            line.model_dump(mode="python", round_trip=True)
            | {"mechanical_binding": None}
        )
        for line in _cancel_lines(api, seal, current, reason)
    )


def _state_with_snapshot(current, snapshot, *, advance_versions=False):
    if advance_versions:
        snapshot = snapshot.model_copy(
            update={
                "risk_snapshot_id": f"{snapshot.risk_snapshot_id}-next",
                "capital_version": current.capital_version + 1,
                "as_of": PERMIT_DEADLINE,
            }
        )
    payload = current.model_dump(mode="python", round_trip=True) | {
        "risk_snapshot": snapshot,
        "risk_snapshot_artifact_hash": snapshot.artifact_hash(),
    }
    if advance_versions:
        payload.update(
            {
                "capital_version": current.capital_version + 1,
                "capital_stream_version": current.capital_stream_version + 1,
            }
        )
    return type(current).model_validate(payload)


def _snapshot_with_components(
    api,
    snapshot,
    *,
    entry_reserves=None,
    extra_entry_reserves=(),
    extra_stage_latches=(),
    snapshot_id=None,
    capital_version=None,
    as_of=None,
    valid_until=None,
):
    """Rebuild a valid full-account snapshot from itemized reserve truth."""

    reserves = list(
        snapshot.entry_reserves if entry_reserves is None else entry_reserves
    )
    reserves.extend(extra_entry_reserves)
    reserves = tuple(sorted(reserves, key=lambda item: item.identity()))
    latches = tuple(
        sorted(
            (*snapshot.stage_loss_latches, *extra_stage_latches),
            key=lambda item: item.identity(),
        )
    )

    total = sum(item.reserved_entry_gross_cents for item in reserves)
    hierarchy: list[tuple[object, str | None, str | None, str | None]] = [
        (api.ExposureScope.GLOBAL, None, None, None),
        (api.ExposureScope.PORTFOLIO, None, None, None),
    ]
    seen: set[tuple[object, str | None, str | None, str | None]] = set(hierarchy)
    for reserve in reserves:
        for identity in (
            (
                api.ExposureScope.RESEARCH_PROGRAM,
                reserve.research_program_id,
                None,
                None,
            ),
            (
                api.ExposureScope.ECONOMIC_LINEAGE,
                reserve.research_program_id,
                reserve.economic_lineage_id,
                None,
            ),
            (
                api.ExposureScope.STAGE,
                reserve.research_program_id,
                reserve.economic_lineage_id,
                reserve.stage_id,
            ),
        ):
            if identity not in seen:
                hierarchy.append(identity)
                seen.add(identity)

    def reserve_total(scope, program, lineage, stage):
        if scope in {api.ExposureScope.GLOBAL, api.ExposureScope.PORTFOLIO}:
            return total
        return sum(
            item.reserved_entry_gross_cents
            for item in reserves
            if item.research_program_id == program
            and (
                scope is api.ExposureScope.RESEARCH_PROGRAM
                or item.economic_lineage_id == lineage
            )
            and (scope is not api.ExposureScope.STAGE or item.stage_id == stage)
        )

    exposures = tuple(
        api.RiskExposureBucket(
            scope=scope,
            portfolio_id=(
                None if scope is api.ExposureScope.GLOBAL else snapshot.portfolio_id
            ),
            research_program_id=program,
            economic_lineage_id=lineage,
            stage_id=stage,
            position_marked_gross_cents=0,
            live_order_leaves_gross_cents=0,
            reserved_entry_gross_cents=reserve_total(scope, program, lineage, stage),
            pending_stress_cents=0,
            corporate_action_pending_risk_cents=0,
            unattributed_risk_cents=0,
            total_gross_cents=reserve_total(scope, program, lineage, stage),
        )
        for scope, program, lineage, stage in hierarchy
    )
    payload = snapshot.model_dump(mode="python", round_trip=True) | {
        "risk_snapshot_id": snapshot_id or snapshot.risk_snapshot_id,
        "entry_reserves": reserves,
        "reserved_cash_cents": total,
        "exposures": exposures,
        "total_gross_exposure_cents": total,
        "stage_loss_latches": latches,
        "stage_loss_state_version": max(
            (item.stage_loss_version for item in latches),
            default=snapshot.stage_loss_state_version,
        ),
        "capital_version": capital_version or snapshot.capital_version,
        "as_of": as_of or snapshot.as_of,
        "valid_until": valid_until or snapshot.valid_until,
    }
    return type(snapshot).model_validate(payload)


def _unrelated_reserve(api, *, source_id="reserve-unrelated", amount=12_345):
    return api.EntryReserveRiskComponent(
        research_program_id="zz-unrelated-program",
        economic_lineage_id="zz-unrelated-lineage",
        stage_id="zz-unrelated-stage",
        source_id=source_id,
        covered_live_order_id=None,
        reserved_entry_gross_cents=amount,
    )


def _unrelated_stage_latch(api):
    return api.StageLossLatchSnapshot(
        research_program_id="zz-unrelated-program",
        economic_lineage_id="zz-unrelated-lineage",
        stage_id="zz-unrelated-stage",
        stage_loss_budget_id="zz-unrelated-budget",
        frozen_budget_cents=100_000,
        consumed_cents=0,
        stage_loss_version=9,
        state=api.StageLossLatchState.CLEAR,
    )


def test_full_snapshot_may_preserve_unrelated_reserve_and_stage_latch() -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(api, seal)
    unrelated_reserve = _unrelated_reserve(api)
    unrelated_latch = _unrelated_stage_latch(api)
    full_snapshot = _snapshot_with_components(
        api,
        current.risk_snapshot,
        extra_entry_reserves=(unrelated_reserve,),
        extra_stage_latches=(unrelated_latch,),
    )
    current = _state_with_snapshot(current, full_snapshot, advance_versions=True)

    permit = _permit(api, seal=seal, evaluation_state=current)

    post = permit.send_claim_expected_versions.post_risk_snapshot
    assert unrelated_reserve in post.entry_reserves
    assert unrelated_latch in post.stage_loss_latches
    assert post == current.risk_snapshot


def test_post_snapshot_applies_owned_delta_and_preserves_unrelated_truth() -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(api, seal)
    unrelated_reserve = _unrelated_reserve(api)
    unrelated_latch = _unrelated_stage_latch(api)
    current_snapshot = _snapshot_with_components(
        api,
        current.risk_snapshot,
        extra_entry_reserves=(unrelated_reserve,),
        extra_stage_latches=(unrelated_latch,),
    )
    current = _state_with_snapshot(current, current_snapshot, advance_versions=True)
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
            reason_code=api.PermitReasonCode.AVAILABILITY_REDUCTION,
            current_reserved_cents=current_by_line[first.order_line_id],
        ),
        _permit_line(
            api,
            second,
            current_reserved_cents=current_by_line[second.order_line_id],
        ),
    )
    expected = _send_claim_versions(api, seal, lines, evaluation_state=current)
    first_source = current.reservation_allocations[0].reservation_allocation_id
    post_snapshot = _snapshot_with_components(
        api,
        current_snapshot,
        entry_reserves=tuple(
            item
            for item in current_snapshot.entry_reserves
            if item.source_id != first_source
        ),
        snapshot_id="risk-snapshot-post-owned-delta",
        capital_version=current.capital_version + 1,
        as_of=PERMIT_DEADLINE,
        valid_until=PERMIT_EXPIRES,
    )
    expected = type(expected).model_validate(
        expected.model_dump(mode="python", round_trip=True)
        | {
            "post_risk_snapshot": post_snapshot,
            "post_risk_snapshot_artifact_hash": post_snapshot.artifact_hash(),
        }
    )

    permit = _permit(
        api,
        seal=seal,
        evaluation_state=current,
        permit_lines=lines,
        send_claim_expected_versions=expected,
    )

    assert (
        unrelated_reserve
        in permit.send_claim_expected_versions.post_risk_snapshot.entry_reserves
    )
    assert (
        unrelated_latch
        in permit.send_claim_expected_versions.post_risk_snapshot.stage_loss_latches
    )
    assert (
        current_snapshot.reserved_cash_cents
        - permit.send_claim_expected_versions.post_risk_snapshot.reserved_cash_cents
        == lines[0].released_reserve_cents
    )


def test_reserve_delta_cannot_smuggle_unwitnessed_capital_truth_change() -> None:
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
            reason_code=api.PermitReasonCode.AVAILABILITY_REDUCTION,
            current_reserved_cents=current_by_line[first.order_line_id],
        ),
        _permit_line(
            api,
            second,
            current_reserved_cents=current_by_line[second.order_line_id],
        ),
    )
    expected = _send_claim_versions(api, seal, lines, evaluation_state=current)
    poisoned_snapshot = expected.post_risk_snapshot.model_copy(
        update={
            "available_cash_cents": (
                expected.post_risk_snapshot.available_cash_cents + 1
            )
        }
    )
    poisoned = type(expected).model_validate(
        expected.model_dump(mode="python", round_trip=True)
        | {
            "post_risk_snapshot": poisoned_snapshot,
            "post_risk_snapshot_artifact_hash": poisoned_snapshot.artifact_hash(),
        }
    )

    with pytest.raises(ValidationError, match="capital|snapshot|unrelated|delta|cash"):
        _permit(
            api,
            seal=seal,
            evaluation_state=current,
            permit_lines=lines,
            send_claim_expected_versions=poisoned,
        )


def test_owned_reserve_source_requires_full_attribution_tuple() -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(api, seal)
    first, second = current.risk_snapshot.entry_reserves
    swapped = (
        first.model_copy(
            update={
                "research_program_id": second.research_program_id,
                "economic_lineage_id": second.economic_lineage_id,
                "stage_id": second.stage_id,
            }
        ),
        second.model_copy(
            update={
                "research_program_id": first.research_program_id,
                "economic_lineage_id": first.economic_lineage_id,
                "stage_id": first.stage_id,
            }
        ),
    )
    poisoned_snapshot = _snapshot_with_components(
        api, current.risk_snapshot, entry_reserves=swapped
    )
    poisoned = _state_with_snapshot(current, poisoned_snapshot, advance_versions=True)

    with pytest.raises(
        ValidationError, match="reserve|attribution|lineage|stage|program"
    ):
        _permit(api, seal=seal, evaluation_state=poisoned)


def test_owned_reserve_source_cannot_be_ambiguous_across_attributions() -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(api, seal)
    duplicate = _unrelated_reserve(
        api,
        source_id=current.risk_snapshot.entry_reserves[0].source_id,
        amount=1,
    )
    with pytest.raises(ValidationError, match="reserve|source|duplicate|ambiguous"):
        poisoned_snapshot = _snapshot_with_components(
            api, current.risk_snapshot, extra_entry_reserves=(duplicate,)
        )
        poisoned = _state_with_snapshot(current, poisoned_snapshot)
        _permit(api, seal=seal, evaluation_state=poisoned)


def _strong_revalidation(api, seal, **overrides):
    issuance = seal.authorization_issuance_binding
    payload = _authorization_revalidation(api, seal).model_dump(
        mode="python", round_trip=True
    ) | {
        "authorization_envelope_hash": seal.authorization_envelope_hash,
        "authorization_issuance_binding_artifact_hash": (
            seal.authorization_issuance_binding_artifact_hash
        ),
        "authorization_issuer_id": issuance.authorization_issuer_id,
        "authorization_issuer_key_id": issuance.authorization_issuer_key_id,
        "authorization_issuer_capability": issuance.authorization_issuer_capability,
        "authorization_issuer_capability_version": (
            issuance.authorization_issuer_capability_version
        ),
        "authorization_issuer_identity_fingerprint": (
            issuance.authorization_issuer_identity_fingerprint
        ),
        "issuance_registry_epoch": issuance.registry_epoch,
        "issuance_trust_bundle_hash": issuance.trust_bundle_hash,
        "verification_result": api.AuthorizationIssuerVerificationResult.VALID,
        "verified_at": PERMIT_DEADLINE,
        "valid_until": PERMIT_EXPIRES,
    }
    payload.update(overrides)
    if isinstance(payload.get("verification_result"), str):
        payload["verification_result"] = api.AuthorizationIssuerVerificationResult(
            payload["verification_result"]
        )
    return api.AuthorizationIssuerRevalidation.model_validate(payload)


def test_authorization_revalidation_has_typed_result_envelope_and_validity() -> None:
    api = _api()
    assert api.AuthorizationIssuanceBinding.__module__ == (
        "src.screening.offensive.v3.contracts.decision"
    )
    assert {
        "authorization_envelope_hash",
        "authorization_issuer_id",
        "authorization_issuer_key_id",
        "authorization_issuer_capability",
        "authorization_issuer_capability_version",
        "authorization_issuer_identity_fingerprint",
        "registry_epoch",
        "trust_bundle_hash",
    } <= set(api.AuthorizationIssuanceBinding.model_fields)
    assert {
        "authorization_issuance_binding",
        "authorization_issuance_binding_artifact_hash",
    } <= set(api.PortfolioDecisionSeal.model_fields)
    assert api.AuthorizationIssuerVerificationResult.__module__ == (
        "src.screening.offensive.v3.contracts.execution"
    )
    assert [item.value for item in api.AuthorizationIssuerVerificationResult] == [
        "VALID",
        "INVALID",
    ]
    assert {
        "authorization_envelope_hash",
        "authorization_issuance_binding_artifact_hash",
        "verification_result",
        "verified_at",
        "valid_until",
    } <= set(api.AuthorizationIssuerRevalidation.model_fields)


def test_valid_current_authorization_revalidation_allows_entry() -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(api, seal)
    revalidation = _strong_revalidation(api, seal)
    current = type(current).model_validate(
        current.model_dump(mode="python", round_trip=True)
        | {"authorization_revalidation": revalidation}
    )

    assert _permit(api, seal=seal, evaluation_state=current).disposition is (
        api.PermitDisposition.ALLOW
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"authorization_issuer_id": "mallory.service"},
        {"authorization_issuer_key_id": "bogus-key"},
        {"authorization_issuer_capability": "bogus-capability"},
        {"authorization_issuer_identity_fingerprint": HASH_F},
    ],
)
def test_allow_rejects_self_asserted_bogus_authorization_issuer(changes) -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(api, seal)
    poisoned_revalidation = _strong_revalidation(api, seal).model_copy(update=changes)
    poisoned = type(current).model_validate(
        current.model_dump(mode="python", round_trip=True)
        | {"authorization_revalidation": poisoned_revalidation}
    )
    with pytest.raises(
        ValidationError, match="authoriz|issuer|key|capability|identity"
    ):
        _permit(api, seal=seal, evaluation_state=poisoned)


def test_allow_requires_authorization_revalidation_at_permit_event() -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(api, seal)
    stale = current.authorization_revalidation.model_copy(
        update={"verified_at": SEAL_CREATED}
    )
    poisoned = type(current).model_validate(
        current.model_dump(mode="python", round_trip=True)
        | {"authorization_revalidation": stale}
    )
    with pytest.raises(ValidationError, match="revalid|current|issued|event|stale"):
        _permit(api, seal=seal, evaluation_state=poisoned)


@pytest.mark.parametrize(
    "changes",
    [
        {"verification_result": "INVALID"},
        {"authorization_envelope_hash": HASH_F},
        {"verified_at": SEAL_CREATED, "valid_until": PERMIT_DEADLINE},
    ],
)
def test_allow_rejects_invalid_unbound_or_expired_revalidation(changes) -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(api, seal)
    with pytest.raises(ValidationError, match="authoriz|envelope|valid|expired|result"):
        poisoned_revalidation = _strong_revalidation(api, seal, **changes)
        poisoned = type(current).model_validate(
            current.model_dump(mode="python", round_trip=True)
            | {"authorization_revalidation": poisoned_revalidation}
        )
        _permit(api, seal=seal, evaluation_state=poisoned)


def test_invalid_issuer_result_can_still_witness_safe_initial_cancel() -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(api, seal)
    invalid = current.authorization_revalidation.model_copy(
        update={
            "verification_result": (api.AuthorizationIssuerVerificationResult.INVALID)
        }
    )
    current = type(current).model_validate(
        current.model_dump(mode="python", round_trip=True)
        | {"authorization_revalidation": invalid}
    )
    lines = _cancel_lines(api, seal, current, api.PermitReasonCode.AUTHORIZATION_CANCEL)
    permit = _permit(
        api,
        seal=seal,
        disposition=api.PermitDisposition.CANCEL,
        evaluation_state=current,
        permit_lines=lines,
    )

    assert permit.disposition is api.PermitDisposition.CANCEL


def test_full_cancel_omits_unconsumed_mechanical_fact_binding() -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(
        api,
        seal,
        authorization_lifecycle=api.AuthorizationLifecycle.REVOKED,
        authorization_status_version=seal.authorization_status_version + 1,
        authorization_status_hash=HASH_A,
    )
    lines = _cancel_lines_without_mechanical_binding(
        api, seal, current, api.PermitReasonCode.AUTHORIZATION_CANCEL
    )

    permit = _permit(
        api,
        seal=seal,
        disposition=api.PermitDisposition.CANCEL,
        evaluation_state=current,
        permit_lines=lines,
    )

    assert all(line.mechanical_binding is None for line in permit.permit_lines)


def test_full_cancel_rejects_arbitrary_unconsumed_mechanical_fact_binding() -> None:
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
    lines = tuple(
        line.model_copy(
            update={
                "mechanical_binding": _mechanical_binding(
                    api,
                    sealed,
                    permitted_quantity=0,
                    reason_code=api.PermitReasonCode.AUTHORIZATION_CANCEL,
                )
            }
        )
        for line, sealed in zip(lines, seal.proposal.order_lines, strict=True)
    )

    with pytest.raises(ValidationError, match="CANCEL|mechanical|fact|binding"):
        _permit(
            api,
            seal=seal,
            disposition=api.PermitDisposition.CANCEL,
            evaluation_state=current,
            permit_lines=lines,
        )


def test_allow_requires_mechanical_fact_binding_on_every_line() -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(api, seal)
    lines = tuple(
        line.model_copy(update={"mechanical_binding": None})
        for line in (
            _permit_line(api, sealed_line) for sealed_line in seal.proposal.order_lines
        )
    )

    with pytest.raises(ValidationError, match="ALLOW|mechanical|fact|binding"):
        _permit(
            api,
            seal=seal,
            evaluation_state=current,
            permit_lines=lines,
        )


def test_invalid_or_expired_issuer_can_still_witness_safe_receipt_cancel() -> None:
    api = _api()
    prior = _permit(api)
    current = _active_permit_evaluation_state(api, prior)
    cancellation_time = PERMIT_EXPIRES + timedelta(seconds=1)
    revalidation = current.authorization_revalidation.model_copy(
        update={
            "verification_result": api.AuthorizationIssuerVerificationResult.INVALID,
            "verified_at": cancellation_time,
            "valid_until": cancellation_time + timedelta(minutes=1),
        }
    )
    current = type(current).model_validate(
        current.model_dump(mode="python", round_trip=True)
        | {"authorization_revalidation": revalidation}
    )

    receipt = _receipt(
        api,
        prior_permit=prior,
        evaluation_state=current,
        reason_code=api.PermitReasonCode.AUTHORIZATION_CANCEL,
    )

    assert receipt.reason_code is api.PermitReasonCode.AUTHORIZATION_CANCEL


@pytest.mark.parametrize(
    "changes",
    [
        {"entry_fence_version": 1},
        {"entry_fence_id": "same-version-fork"},
        {"entry_fence_hash": HASH_A},
    ],
)
def test_initial_cancel_rejects_fence_rollback_or_same_version_fork(changes) -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(api, seal, **changes)
    lines = _cancel_lines(api, seal, current, api.PermitReasonCode.FENCE_CANCEL)
    with pytest.raises(ValidationError, match="fence|version|rollback|same"):
        _permit(
            api,
            seal=seal,
            disposition=api.PermitDisposition.CANCEL,
            evaluation_state=current,
            permit_lines=lines,
        )


def test_higher_fence_version_is_a_valid_initial_cancel_witness() -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(
        api,
        seal,
        entry_fence_version=seal.entry_fence_version + 1,
        entry_fence_id="entry-fence-2",
        entry_fence_hash=HASH_A,
    )
    lines = _cancel_lines(api, seal, current, api.PermitReasonCode.FENCE_CANCEL)
    permit = _permit(
        api,
        seal=seal,
        disposition=api.PermitDisposition.CANCEL,
        evaluation_state=current,
        permit_lines=lines,
    )
    assert permit.disposition is api.PermitDisposition.CANCEL


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        (
            {"policy_epoch": 5, "policy_activation_hash": HASH_F},
            "AUTHORIZATION_CANCEL",
        ),
        ({"authority_epoch": 6}, "AUTHORIZATION_CANCEL"),
        ({"risk_epoch": 7}, "AUTHORIZATION_CANCEL"),
        (
            {
                "authorization_id": "authorization-v4",
                "authorization_version": 4,
                "authorization_envelope_hash": HASH_F,
            },
            "AUTHORIZATION_CANCEL",
        ),
        ({"evidence_set_merkle_root": HASH_F}, "AUTHORIZATION_CANCEL"),
        ({"writer_fencing_epoch": 12}, "FENCE_CANCEL"),
    ],
)
def test_initial_cancel_accepts_broad_higher_authority_or_fence_witness(
    changes, reason
) -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(api, seal, **changes)
    reason_code = getattr(api.PermitReasonCode, reason)
    lines = _cancel_lines(api, seal, current, reason_code)

    permit = _permit(
        api,
        seal=seal,
        disposition=api.PermitDisposition.CANCEL,
        evaluation_state=current,
        permit_lines=lines,
    )

    assert permit.permit_lines[0].reason_code is reason_code


@pytest.mark.parametrize(
    "changes",
    [
        {"policy_epoch": 3},
        {"authority_epoch": 4},
        {"risk_epoch": 5},
        {"writer_fencing_epoch": 10},
        {"policy_activation_hash": HASH_F},
    ],
)
def test_initial_cancel_rejects_authority_rollback_or_same_version_fork(
    changes,
) -> None:
    api = _api()
    seal = _seal(api)
    current = _permit_evaluation_state(api, seal, **changes)
    reason = (
        api.PermitReasonCode.FENCE_CANCEL
        if "writer_fencing_epoch" in changes
        else api.PermitReasonCode.AUTHORIZATION_CANCEL
    )
    lines = _cancel_lines(api, seal, current, reason)
    with pytest.raises(
        ValidationError, match="policy|authority|risk|writer|rollback|same"
    ):
        _permit(
            api,
            seal=seal,
            disposition=api.PermitDisposition.CANCEL,
            evaluation_state=current,
            permit_lines=lines,
        )


def test_zero_release_cancel_advances_only_reservation_state_version() -> None:
    api = _api()
    seal = _seal(api)
    zero_allocations = tuple(
        item.model_copy(update={"reserved_cash_cents": 0})
        for item in _reservation_allocations(api, seal)
    )
    current = _permit_evaluation_state(
        api,
        seal,
        reservation_allocations=zero_allocations,
        reservation_version=seal.post_admission_reservation_version + 1,
        capital_version=seal.post_admission_capital_version + 1,
        capital_stream_version=seal.post_admission_capital_stream_version + 1,
        authorization_lifecycle=api.AuthorizationLifecycle.REVOKED,
        authorization_status_version=seal.authorization_status_version + 1,
        authorization_status_hash=HASH_A,
    )
    lines = _cancel_lines(api, seal, current, api.PermitReasonCode.AUTHORIZATION_CANCEL)
    binding = _cancellation_binding(api, seal, evaluation_state=current).model_copy(
        update={"post_reservation_version": current.reservation_version + 1}
    )

    permit = _permit(
        api,
        seal=seal,
        disposition=api.PermitDisposition.CANCEL,
        evaluation_state=current,
        permit_lines=lines,
        cancellation_binding=binding,
    )

    assert binding.post_reservation_version == current.reservation_version + 1
    assert binding.post_capital_version == current.capital_version
    assert binding.post_capital_stream_version == current.capital_stream_version
    assert binding.post_risk_snapshot == current.risk_snapshot
    assert permit.cancellation_binding.released_cash_cents == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"reservation_id": "unrelated-reservation"},
        {"reservation_state": "RELEASED"},
    ],
)
def test_receipt_requires_exact_active_reservation_and_prevents_double_release(
    changes,
) -> None:
    api = _api()
    prior = _permit(api)
    if changes.get("reservation_state") == "RELEASED":
        changes = {"reservation_state": api.ReservationState.RELEASED}
        with pytest.raises(
            ValidationError, match="reservation|released|zero|remaining"
        ):
            _active_permit_evaluation_state(api, prior, **changes)
        return
    current = _active_permit_evaluation_state(api, prior, **changes)
    with pytest.raises(ValidationError, match="reservation|ACTIVE|released|double"):
        _receipt(api, prior_permit=prior, evaluation_state=current)


def test_receipt_rejects_same_capital_version_risk_snapshot_drift() -> None:
    api = _api()
    prior = _permit(api)
    current = _active_permit_evaluation_state(api, prior)
    drifted_snapshot = current.risk_snapshot.model_copy(
        update={"available_cash_cents": current.risk_snapshot.available_cash_cents + 1}
    )
    drifted = _state_with_snapshot(current, drifted_snapshot)
    with pytest.raises(
        ValidationError, match="risk snapshot|capital version|drift|exact"
    ):
        _receipt(api, prior_permit=prior, evaluation_state=drifted)


@pytest.mark.parametrize(
    ("claim_state", "sequence"),
    [("UNCLAIMED", 7), ("SEND_CLAIMED", 0)],
)
def test_claim_state_and_sequence_are_biconditional(claim_state, sequence) -> None:
    api = _api()
    prior = _permit(api)
    with pytest.raises(ValidationError, match="claim|sequence|zero|positive"):
        _active_permit_evaluation_state(
            api,
            prior,
            active_send_claim_state=claim_state,
            send_claim_sequence=sequence,
        )


def test_active_permit_nonce_state_is_typed_and_consistent() -> None:
    api = _api()
    assert "active_permit_nonce_state" in api.PermitEvaluationState.model_fields
    prior = _permit(api)
    payload = _active_permit_evaluation_state(api, prior).model_dump(
        mode="python", round_trip=True
    )
    payload["active_permit_nonce_state"] = "INVALIDATED"
    with pytest.raises(ValidationError, match="nonce|ACTIVE|invalidated"):
        api.PermitEvaluationState.model_validate(payload)


def test_healthy_receipt_wall_clock_cannot_rollback_before_prior_permit() -> None:
    api = _api()
    prior = _permit(api)
    current = _active_permit_evaluation_state(
        api,
        prior,
        authorization_lifecycle=api.AuthorizationLifecycle.REVOKED,
        authorization_status_version=(
            prior.send_claim_expected_versions.authorization_status_version + 1
        ),
        authorization_status_hash=HASH_A,
    )
    rollback_time = prior.issued_at - timedelta(microseconds=1)
    snapshot = current.risk_snapshot.model_copy(
        update={"as_of": SEAL_CREATED, "valid_until": PERMIT_EXPIRES}
    )
    revalidation = current.authorization_revalidation.model_copy(
        update={"verified_at": SEAL_CREATED}
    )
    current = type(current).model_validate(
        current.model_dump(mode="python", round_trip=True)
        | {
            "risk_snapshot": snapshot,
            "risk_snapshot_artifact_hash": snapshot.artifact_hash(),
            "authorization_revalidation": revalidation,
        }
    )
    observation = _receipt_clock_observation(api, wall_clock_utc=rollback_time)
    binding = _cancellation_binding(
        api, prior.seal, evaluation_state=current, nonce=prior.permit_nonce
    )
    post_snapshot = binding.post_risk_snapshot.model_copy(
        update={"as_of": rollback_time, "valid_until": PERMIT_EXPIRES}
    )
    binding = binding.model_copy(
        update={
            "post_risk_snapshot": post_snapshot,
            "post_risk_snapshot_artifact_hash": post_snapshot.artifact_hash(),
        }
    )
    with pytest.raises(ValidationError, match="wall|clock|rollback|prior|later"):
        _receipt(
            api,
            prior_permit=prior,
            evaluation_state=current,
            reason_code=api.PermitReasonCode.AUTHORIZATION_CANCEL,
            cancellation_clock_observation=observation,
            cancelled_at=rollback_time,
            cancellation_binding=binding,
        )


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"entry_fence_version": 1}, "FENCE_CANCEL"),
        ({"entry_fence_id": "same-version-fork"}, "FENCE_CANCEL"),
        ({"policy_epoch": 3}, "AUTHORIZATION_CANCEL"),
        ({"policy_activation_hash": HASH_F}, "AUTHORIZATION_CANCEL"),
        ({"authority_epoch": 4}, "AUTHORIZATION_CANCEL"),
        ({"risk_epoch": 5}, "AUTHORIZATION_CANCEL"),
        ({"writer_fencing_epoch": 10}, "FENCE_CANCEL"),
    ],
)
def test_receipt_rejects_rollback_or_same_version_fork(changes, reason) -> None:
    api = _api()
    prior = _permit(api)
    current = _active_permit_evaluation_state(api, prior, **changes)
    with pytest.raises(
        ValidationError, match="fence|policy|authority|risk|writer|rollback|same"
    ):
        _receipt(
            api,
            prior_permit=prior,
            evaluation_state=current,
            reason_code=getattr(api.PermitReasonCode, reason),
        )


def test_busted_exit_reopens_positive_position_and_exit_mandate() -> None:
    from tests.offensive.v3.contracts.test_capital import _exit_mandate_payload
    from tests.offensive.v3.contracts.test_execution import (
        NOW,
        _execution,
        _revision_payload,
    )

    from src.screening.offensive.v3 import contracts as c

    e = _execution()
    original_mandate = c.ExitMandate(**_exit_mandate_payload(c))
    reopened_mandate = c.ExitMandate(
        **_exit_mandate_payload(
            c,
            mandate_revision=2,
            revision_kind=c.ExitMandateRevisionKind.REOPENED_BY_CORRECTION,
            supersedes_mandate_hash=original_mandate.artifact_hash(),
            reopened_by_execution_revision_id="execution-001:2",
            tradable_quantity=100,
            live_exit_leaves_quantity=0,
            executable_quantity=100,
        )
    )
    recorded_exit = e.ExecutionRevision(
        **_revision_payload(
            e,
            side=e.ExecutionSide.EXIT,
            effective_position_quantity=0,
            effective_position_state=e.EffectivePositionState.FLAT,
            exit_mandate_id=None,
            exit_mandate_revision=None,
        )
    )
    busted_exit = e.ExecutionRevision(
        **_revision_payload(
            e,
            revision=2,
            revision_kind=e.ExecutionRevisionKind.BUSTED,
            supersedes_revision=1,
            side=e.ExecutionSide.EXIT,
            effective_filled_quantity=0,
            effective_position_quantity=100,
            effective_gross_cash_cents=0,
            effective_position_state=e.EffectivePositionState.EXIT_PENDING,
            exit_mandate_id=reopened_mandate.exit_mandate_id,
            exit_mandate_revision=reopened_mandate.mandate_revision,
            economic_projection_state=e.EconomicProjectionState.REOPENED_BY_CORRECTION,
            observed_at=NOW + timedelta(minutes=1),
        )
    )
    history = e.ExecutionRevisionHistory(
        execution_id=recorded_exit.execution_id,
        order_id=recorded_exit.order_id,
        revisions=(recorded_exit, busted_exit),
        active_revision=2,
        schema_major=2,
    )

    assert history.revisions[-1].effective_position_state is (
        e.EffectivePositionState.EXIT_PENDING
    )
    assert history.revisions[-1].economic_projection_state is (
        e.EconomicProjectionState.REOPENED_BY_CORRECTION
    )
    assert reopened_mandate.revision_kind is (
        c.ExitMandateRevisionKind.REOPENED_BY_CORRECTION
    )
