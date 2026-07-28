"""Checkpoint 2 RED: strict primitives, canonical ordering, and hashing."""

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
    _gateway_expected_versions,
    _gateway_issuer,
    _permit,
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
    _shadow_issuer,
    _shadow_line,
    _shadow_payload,
    _shadow_stage_binding,
    _stage_binding,
    _stage_expected_version,
    _window,
    _window_payload,
)

INTEGER_FIELDS_BY_FIXTURE = {
    "window": (
        "calendar_snapshot_version",
        "cutoff_snapshot_version",
        "monotonic_observation_ns",
        "monotonic_sequence",
    ),
    "gateway_issuer": ("capability_schema_major", "registry_epoch"),
    "shadow_issuer": ("capability_schema_major", "registry_epoch"),
    "stage": ("expected_stage_loss_version", "post_stage_loss_version"),
    "stage_expected": ("stage_loss_version",),
    "reserve": ("reserved_cash_cents",),
    "prior": (
        "prior_seal_revision",
        "permit_issuance_sequence",
        "fencing_token_issuance_sequence",
        "live_order_count",
    ),
    "gateway_expected": (
        "registry_epoch",
        "policy_epoch",
        "authority_epoch",
        "risk_epoch",
        "authorization_version",
        "authorization_status_version",
        "entry_fence_version",
        "capital_version",
        "capital_stream_version",
        "writer_fencing_epoch",
        "expected_active_seal_revision",
        "schema_major",
    ),
    "seal": (
        "schema_major",
        "seal_revision",
        "supersedes_seal_revision",
        "registry_epoch",
        "policy_epoch",
        "authority_epoch",
        "risk_epoch",
        "authorization_version",
        "authorization_status_version",
        "entry_fence_version",
        "capital_version",
        "capital_stream_version",
        "writer_fencing_epoch",
        "reservation_version",
        "total_reserved_cash_cents",
        "post_admission_capital_version",
        "post_admission_reservation_version",
    ),
    "shadow_line": (
        "target_quantity_units",
        "lot_size_units",
        "limit_price_cents",
        "worst_case_price_cents",
        "exit_session_ordinal",
        "estimated_fee_cents",
        "estimated_cash_reserve_cents",
    ),
    "shadow": ("schema_major", "policy_epoch"),
    "permit_line": (
        "sealed_quantity_units",
        "permitted_quantity_units",
        "limit_price_cents",
        "worst_case_price_cents",
        "exit_session_ordinal",
        "sealed_reserve_cents",
        "remaining_reserve_cents",
        "released_reserve_cents",
    ),
    "send_claim": (
        "active_seal_revision",
        "permit_nonce_sequence",
        "registry_epoch",
        "policy_epoch",
        "authority_epoch",
        "risk_epoch",
        "authorization_version",
        "authorization_status_version",
        "entry_fence_version",
        "capital_version",
        "capital_stream_version",
        "risk_snapshot_version",
        "reservation_version",
        "remaining_reserved_cash_cents",
        "writer_fencing_epoch",
    ),
    "permit": (
        "schema_major",
        "permit_nonce_sequence",
        "seal_revision",
        "total_remaining_reserve_cents",
        "total_released_reserve_cents",
    ),
}


def _strict_fixture(api, fixture_name):
    if fixture_name == "window":
        instance = _window(api)
    elif fixture_name == "gateway_issuer":
        instance = _gateway_issuer(
            api,
            api.ArtifactKind.PORTFOLIO_DECISION_SEAL,
            "capital-gateway.entry-seal.v1",
        )
    elif fixture_name == "shadow_issuer":
        instance = _shadow_issuer(api)
    elif fixture_name == "stage":
        instance = _stage_binding(api)
    elif fixture_name == "stage_expected":
        instance = _stage_expected_version(api, _proposal(api).order_lines[0])
    elif fixture_name == "reserve":
        instance = _reserve_bindings(api, _proposal(api))[0]
    elif fixture_name == "prior":
        instance = _prior_seal_eligibility(api)
    elif fixture_name == "gateway_expected":
        instance = _gateway_expected_versions(api)
    elif fixture_name == "seal":
        instance = _seal(api)
    elif fixture_name == "shadow_line":
        instance = _shadow_line(api)
    elif fixture_name == "shadow":
        instance = _shadow(api)
    elif fixture_name == "permit_line":
        instance = _permit(api).permit_lines[0]
    elif fixture_name == "send_claim":
        instance = _permit(api).send_claim_expected_versions
    elif fixture_name == "permit":
        instance = _permit(api)
    else:  # pragma: no cover - the parameter table is closed above
        raise AssertionError(f"unknown strict fixture: {fixture_name}")
    return type(instance), instance


@pytest.mark.parametrize(
    ("fixture_name", "field"),
    [
        (fixture_name, field)
        for fixture_name, fields in INTEGER_FIELDS_BY_FIXTURE.items()
        for field in fields
    ],
)
def test_every_checkpoint2_integer_field_rejects_non_native_integer(
    fixture_name, field
) -> None:
    api = _api()
    model, instance = _strict_fixture(api, fixture_name)
    base = instance.model_dump(mode="python", round_trip=True)
    if base[field] is None:
        if field == "expected_active_seal_revision":
            base["expected_active_seal_id"] = "seal-0"
            base["expected_active_seal_logical_key"] = _proposal(api).logical_key
            base["expected_active_seal_artifact_hash"] = "9" * 64
            base[field] = 1
        elif field == "supersedes_seal_revision":
            eligibility = _prior_seal_eligibility(api)
            base.update(
                seal_revision=2,
                supersedes_seal_id=eligibility.prior_seal_id,
                supersedes_seal_revision=eligibility.prior_seal_revision,
                prior_seal_eligibility=eligibility,
            )
    for bad in (True, 1.0, Decimal("1")):
        with pytest.raises(ValidationError, match="integer|native int|valid integer"):
            model.model_validate(base | {field: bad})


UTC_FIELDS_BY_FIXTURE = {
    "window": (
        "wall_clock_observed_at",
        "t0_close_finalized_at",
        "seal_creation_deadline",
        "permit_issue_deadline",
        "gateway_send_deadline",
        "broker_auction_submission_cutoff",
    ),
    "gateway_issuer": ("verified_at",),
    "shadow_issuer": ("verified_at",),
    "seal": ("created_at",),
    "shadow": ("created_at", "available_at"),
    "permit_line": ("preopen_fact_as_of",),
    "send_claim": ("effective_send_deadline",),
    "permit": ("issued_at", "permit_expires_at"),
}


@pytest.mark.parametrize(
    ("fixture_name", "field"),
    [
        (fixture_name, field)
        for fixture_name, fields in UTC_FIELDS_BY_FIXTURE.items()
        for field in fields
    ],
)
def test_every_checkpoint2_time_field_rejects_naive_or_non_utc(
    fixture_name, field
) -> None:
    api = _api()
    model, instance = _strict_fixture(api, fixture_name)
    for bad_time in (
        SEAL_CREATED.replace(tzinfo=None),
        SEAL_CREATED.astimezone(timezone(timedelta(hours=8))),
    ):
        with pytest.raises(ValidationError, match="UTC|timezone"):
            model.model_validate(
                instance.model_dump(mode="python", round_trip=True) | {field: bad_time}
            )


def test_nested_line_models_forbid_unknown_fields() -> None:
    api = _api()
    seal_line = _reserve_bindings(api, _proposal(api))[0]
    shadow_line = _shadow_line(api)
    permit_line = _permit(api).permit_lines[0]
    cases = (
        (
            api.StageAdmissionBinding,
            _stage_binding(api),
            "expected_stage_loss_version",
        ),
        (api.SealReserveLineBinding, seal_line, "reserved_cash_cents"),
        (api.ShadowOrderLine, shadow_line, "target_quantity_units"),
        (api.ExecutionPermitLine, permit_line, "permitted_quantity_units"),
    )
    for model, instance, _field in cases:
        base = instance.model_dump(mode="python", round_trip=True)
        with pytest.raises(ValidationError, match="extra_forbidden"):
            model.model_validate(base | {"unknown": "forbidden"})


def test_nested_unchecked_models_are_recursively_revalidated() -> None:
    api = _api()
    seal = _seal(api)
    poisoned_reserve = seal.line_reserve_bindings[0].model_construct(
        **(
            seal.line_reserve_bindings[0].model_dump(mode="python")
            | {"reserved_cash_cents": -1}
        )
    )
    poisoned_seal_payload = _seal_payload(
        api,
        line_reserve_bindings=(
            poisoned_reserve,
            *seal.line_reserve_bindings[1:],
        ),
    )
    with pytest.raises(ValidationError):
        api.PortfolioDecisionSeal.model_validate(poisoned_seal_payload)
    poisoned_seal = api.PortfolioDecisionSeal.model_construct(**poisoned_seal_payload)
    with pytest.raises(ValidationError):
        poisoned_seal.artifact_hash()

    permit = _permit(api)
    poisoned_line = permit.permit_lines[0].model_copy(
        update={"permitted_quantity_units": -1}
    )
    poisoned_permit_payload = _permit_payload(
        api,
        permit_lines=(poisoned_line, *permit.permit_lines[1:]),
    )
    with pytest.raises(ValidationError):
        api.ExecutionPermit.model_validate(poisoned_permit_payload)
    poisoned_permit = api.ExecutionPermit.model_construct(**poisoned_permit_payload)
    with pytest.raises(ValidationError):
        poisoned_permit.artifact_hash()


def test_checkpoint2_artifacts_are_frozen_and_canonical_ordered() -> None:
    api = _api()
    for artifact in (_seal(api), _shadow(api), _permit(api)):
        with pytest.raises(ValidationError, match="frozen_instance"):
            artifact.schema_major = 2

    seal = _seal(api)
    with pytest.raises(ValidationError, match="canonical|order"):
        api.PortfolioDecisionSeal.model_validate(
            _seal_payload(
                api,
                line_reserve_bindings=tuple(reversed(seal.line_reserve_bindings)),
            )
        )
    permit = _permit(api)
    with pytest.raises(ValidationError, match="canonical|order"):
        api.ExecutionPermit.model_validate(
            _permit_payload(api, permit_lines=tuple(reversed(permit.permit_lines)))
        )


def test_nested_binding_identities_are_unique_and_composite() -> None:
    api = _api()
    stage = _stage_binding(api)
    duplicate_stages = (stage, stage)
    with pytest.raises(ValidationError, match="stage|unique|duplicate"):
        api.PortfolioDecisionSeal.model_validate(
            _seal_payload(api, stage_admission_bindings=duplicate_stages)
        )

    shadow = _shadow(api)
    with pytest.raises(ValidationError, match="line|unique|duplicate"):
        api.ShadowDecision.model_validate(
            _shadow_payload(
                api,
                counterfactual_lines=(
                    shadow.counterfactual_lines[0],
                    shadow.counterfactual_lines[0],
                ),
            )
        )

    permit = _permit(api)
    with pytest.raises(ValidationError, match="line|unique|duplicate"):
        api.ExecutionPermit.model_validate(
            _permit_payload(
                api,
                permit_lines=(permit.permit_lines[0], permit.permit_lines[0]),
            )
        )


def test_seal_shadow_and_permit_have_stable_canonical_serialization_fixtures() -> None:
    api = _api()
    fixtures = (
        ("seal", _seal(api)),
        ("shadow", _shadow(api)),
        ("permit", _permit(api)),
    )
    for label, artifact in fixtures:
        approved_canonical_digest, approved_artifact_hash = (
            APPROVED_SERIALIZATION_DIGESTS[label]
        )
        assert hashlib.sha256(api.canonical_json_bytes(artifact)).hexdigest() == (
            approved_canonical_digest
        )
        assert artifact.artifact_hash() == approved_artifact_hash


def test_every_authority_reserve_line_or_deadline_change_changes_artifact_hash() -> (
    None
):
    api = _api()
    permit = _permit(api)
    seal = permit.seal
    partial_lines = (
        permit.permit_lines[0],
        _permit_line(
            api,
            seal.proposal.order_lines[1],
            permitted_quantity=100,
            reason_code=api.PermitReasonCode.CAPITAL_RISK_REDUCTION,
        ),
    )
    outbox_expected = api.SendClaimExpectedVersions.model_validate(
        permit.send_claim_expected_versions.model_dump(mode="python", round_trip=True)
        | {"outbox_payload_hash": HASH_F}
    )
    earlier_expiry = PERMIT_EXPIRES - timedelta(microseconds=1)
    deadline_expected = api.SendClaimExpectedVersions.model_validate(
        permit.send_claim_expected_versions.model_dump(mode="python", round_trip=True)
        | {"effective_send_deadline": earlier_expiry}
    )
    valid_permit_variants = {
        "line": _permit(api, seal=seal, permit_lines=partial_lines),
        "nonce": _permit(api, permit_nonce="permit-nonce-2"),
        "outbox": _permit(api, send_claim_expected_versions=outbox_expected),
        "deadline": _permit(
            api,
            permit_expires_at=earlier_expiry,
            send_claim_expected_versions=deadline_expected,
        ),
        "issuer": _permit(
            api,
            issuer_binding=permit.issuer_binding.model_copy(
                update={"key_id": "capital-gateway-key-2"}
            ),
        ),
    }
    for label, valid_variant in valid_permit_variants.items():
        assert valid_variant.artifact_hash() != permit.artifact_hash(), label

    shadow = _shadow(api)
    changed_shadow = _shadow(api, evidence_set_merkle_root=HASH_F)
    assert changed_shadow.artifact_hash() != shadow.artifact_hash()


def test_hash_preimage_excludes_self_hash_and_signature_fields() -> None:
    api = _api()
    forbidden = {"artifact_hash", "signature", "self_hash"}
    for model in (
        api.PortfolioDecisionSeal,
        api.ShadowDecision,
        api.ExecutionPermit,
        api.GatewayIssuerBinding,
        api.ShadowIssuerBinding,
    ):
        assert forbidden.isdisjoint(model.model_fields)
