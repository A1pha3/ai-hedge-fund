"""Checkpoint 2 RED: artifact separation, seal publication, and CAS bindings."""

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
    _shadow_line,
    _shadow_payload,
    _shadow_stage_binding,
    _stage_binding,
    _stage_expected_version,
    _window,
    _window_payload,
)


@pytest.mark.parametrize("name", CHECKPOINT2_NAMES)
def test_each_checkpoint2_public_contract_is_exported_independently(name) -> None:
    from src.screening.offensive.v3 import contracts

    assert hasattr(contracts, name), f"missing independent contract export: {name}"


@pytest.mark.parametrize(
    "name",
    ("PORTFOLIO_DECISION_SEAL", "SHADOW_DECISION", "EXECUTION_PERMIT"),
)
def test_each_checkpoint2_artifact_kind_is_exported_independently(name) -> None:
    from src.screening.offensive.v3.contracts import ArtifactKind

    assert hasattr(ArtifactKind, name), f"missing independent artifact kind: {name}"


def test_checkpoint2_public_api_and_artifact_kinds_are_explicit() -> None:
    api = _api()

    assert api.ArtifactKind.PORTFOLIO_DECISION_SEAL.value == ("portfolio_decision_seal")
    assert api.ArtifactKind.SHADOW_DECISION.value == "shadow_decision"
    assert api.ArtifactKind.EXECUTION_PERMIT.value == "execution_permit"
    assert {item.value for item in api.ClockHealth} == {
        "HEALTHY",
        "UNKNOWN",
        "EXCESSIVE_SKEW",
        "ROLLBACK_DETECTED",
    }
    assert {item.value for item in api.PermitDisposition} == {"ALLOW", "CANCEL"}


def test_seal_shadow_and_permit_use_distinct_type_namespace_and_hash_domain() -> None:
    api = _api()

    seal = _seal(api)
    shadow = _shadow(api)
    permit = _permit(api)
    assert (
        seal.artifact_kind,
        seal.artifact_namespace,
        seal.HASH_DOMAIN,
    ) == (
        api.ArtifactKind.PORTFOLIO_DECISION_SEAL,
        "capital-gateway.entry-seal.v1",
        "ai-hedge-fund.v3.decision.portfolio-seal.v1",
    )
    assert (
        shadow.artifact_kind,
        shadow.artifact_namespace,
        shadow.HASH_DOMAIN,
    ) == (
        api.ArtifactKind.SHADOW_DECISION,
        "growth-kernel.shadow.v1",
        "ai-hedge-fund.v3.decision.shadow-decision.v1",
    )
    assert (
        permit.artifact_kind,
        permit.artifact_namespace,
        permit.HASH_DOMAIN,
    ) == (
        api.ArtifactKind.EXECUTION_PERMIT,
        "capital-gateway.entry-permit.v1",
        "ai-hedge-fund.v3.decision.execution-permit.v1",
    )
    assert (
        len({seal.artifact_hash(), shadow.artifact_hash(), permit.artifact_hash()}) == 3
    )


@pytest.mark.parametrize(
    ("source_builder", "target_name"),
    [
        (_seal, "ExecutionPermit"),
        (_seal, "ShadowDecision"),
        (_shadow, "PortfolioDecisionSeal"),
        (_shadow, "ExecutionPermit"),
        (_shadow, "PortfolioDecision"),
        (_permit, "PortfolioDecisionSeal"),
        (_permit, "ShadowDecision"),
    ],
)
def test_checkpoint2_artifacts_cannot_cross_parse(source_builder, target_name) -> None:
    api = _api()
    source = source_builder(api)

    with pytest.raises(ValidationError):
        getattr(api, target_name).model_validate(
            source.model_dump(mode="python", round_trip=True)
        )


def test_changing_shadow_discriminator_still_cannot_create_seal() -> None:
    api = _api()
    shadow_payload = _shadow(api).model_dump(mode="python", round_trip=True)
    shadow_payload.update(
        artifact_kind=api.ArtifactKind.PORTFOLIO_DECISION_SEAL,
        artifact_namespace="capital-gateway.entry-seal.v1",
    )

    with pytest.raises(ValidationError):
        api.PortfolioDecisionSeal.model_validate(shadow_payload)


def test_all_three_artifacts_forbid_unknown_and_cross_type_fields() -> None:
    api = _api()
    cases = (
        (api.PortfolioDecisionSeal, _seal_payload(api), "permit_nonce"),
        (api.ShadowDecision, _shadow_payload(api), "reservation_id"),
        (api.ExecutionPermit, _permit_payload(api), "shadow_decision_id"),
    )
    for model, payload, foreign_field in cases:
        with pytest.raises(ValidationError, match="extra_forbidden"):
            model.model_validate(payload | {foreign_field: "forbidden"})


def test_issuer_bindings_have_exact_verified_capability_and_registry_fields() -> None:
    api = _api()
    expected = {
        "issuer_id",
        "key_id",
        "capability_artifact_kind",
        "capability_namespace",
        "capability_mode",
        "capability_schema_major",
        "capability_version",
        "capability_scope",
        "verified_at",
        "trust_bundle_hash",
        "registry_epoch",
    }
    assert set(api.GatewayIssuerBinding.model_fields) == expected
    assert set(api.ShadowIssuerBinding.model_fields) == expected


def test_artifact_issuer_capability_must_match_type_namespace_mode_and_registry() -> (
    None
):
    api = _api()
    seal = _seal(api)
    shadow = _shadow(api)
    permit = _permit(api)
    assert seal.issuer_binding.verified_at <= seal.created_at
    assert shadow.issuer_binding.verified_at <= shadow.created_at
    assert permit.issuer_binding.verified_at <= permit.issued_at
    cases = (
        (
            api.PortfolioDecisionSeal,
            seal,
            seal.issuer_binding.model_copy(
                update={"capability_artifact_kind": api.ArtifactKind.EXECUTION_PERMIT}
            ),
        ),
        (
            api.ShadowDecision,
            shadow,
            shadow.issuer_binding.model_copy(
                update={"capability_namespace": "capital-gateway.entry-seal.v1"}
            ),
        ),
        (
            api.PortfolioDecisionSeal,
            seal,
            seal.issuer_binding.model_copy(
                update={"capability_mode": api.ExecutionMode.MANUAL_CONFIRMED}
            ),
        ),
        (
            api.PortfolioDecisionSeal,
            seal,
            seal.issuer_binding.model_copy(update={"capability_schema_major": 1}),
        ),
        (
            api.PortfolioDecisionSeal,
            seal,
            seal.issuer_binding.model_copy(
                update={"capability_scope": "portfolio:other"}
            ),
        ),
        (
            api.ExecutionPermit,
            permit,
            permit.issuer_binding.model_copy(update={"registry_epoch": 999}),
        ),
        (
            api.PortfolioDecisionSeal,
            seal,
            seal.issuer_binding.model_copy(
                update={"verified_at": seal.created_at + timedelta(microseconds=1)}
            ),
        ),
        (
            api.ExecutionPermit,
            permit,
            permit.issuer_binding.model_copy(update={"trust_bundle_hash": HASH_F}),
        ),
    )
    for model, artifact, issuer in cases:
        with pytest.raises(
            ValidationError,
            match="issuer|capability|namespace|registry|verified|trust|scope",
        ):
            model.model_validate(
                artifact.model_dump(
                    mode="python", round_trip=True, exclude={"issuer_binding"}
                )
                | {"issuer_binding": issuer}
            )

    old_but_current = _gateway_issuer(
        api,
        api.ArtifactKind.PORTFOLIO_DECISION_SEAL,
        "capital-gateway.entry-seal.v1",
        verified_at=CLOSE_FINALIZED - timedelta(days=30),
    )
    assert _seal(api, issuer_binding=old_but_current).issuer_binding == old_but_current


def test_portfolio_decision_seal_has_exact_gateway_receipt_fields() -> None:
    api = _api()

    assert set(api.PortfolioDecisionSeal.model_fields) == {
        "artifact_kind",
        "artifact_namespace",
        "schema_major",
        "seal_id",
        "seal_revision",
        "logical_key",
        "supersedes_seal_id",
        "supersedes_seal_revision",
        "prior_seal_eligibility",
        "proposal",
        "proposal_artifact_hash",
        "portfolio_id",
        "broker_account_id",
        "broker_account_fingerprint",
        "base_currency",
        "mode",
        "target_entry_session",
        "target_portfolio_policy_fingerprint",
        "policy_activation_hash",
        "trust_bundle_hash",
        "registry_epoch",
        "policy_epoch",
        "authority_epoch",
        "risk_epoch",
        "authorization_id",
        "authorization_version",
        "authorization_envelope_hash",
        "authorization_status_version",
        "authorization_status_hash",
        "evidence_set_merkle_root",
        "entry_fence_id",
        "entry_fence_hash",
        "entry_fence_version",
        "risk_snapshot_id",
        "risk_snapshot_artifact_hash",
        "capital_version",
        "capital_stream_version",
        "stage_admission_bindings",
        "writer_fencing_epoch",
        "consumed_gateway_expected_versions",
        "consumed_gateway_expected_versions_artifact_hash",
        "reservation_id",
        "reservation_version",
        "line_reserve_bindings",
        "total_reserved_cash_cents",
        "post_admission_capital_version",
        "post_admission_reservation_version",
        "execution_window",
        "created_at",
        "issuer_binding",
    }


def test_stage_and_reserve_bindings_have_exact_composite_fields() -> None:
    api = _api()

    assert set(api.StageAdmissionBinding.model_fields) == {
        "research_program_id",
        "economic_lineage_id",
        "stage_id",
        "stage_loss_budget_id",
        "expected_stage_loss_version",
        "post_stage_loss_version",
        "stage_loss_latch",
    }
    assert set(api.SealReserveLineBinding.model_fields) == {
        "order_line_id",
        "reservation_allocation_id",
        "reserved_cash_cents",
    }
    assert set(api.PriorSealEligibilityBinding.model_fields) == {
        "prior_seal_id",
        "prior_seal_revision",
        "prior_seal_artifact_hash",
        "logical_key",
        "permit_issuance_sequence",
        "fencing_token_issuance_sequence",
        "live_order_count",
    }
    with pytest.raises(ValidationError, match="post|version|monotonic"):
        api.StageAdmissionBinding.model_validate(
            _stage_binding(api).model_dump(mode="python", round_trip=True)
            | {"post_stage_loss_version": 2}
        )


def test_stage_coverage_is_exactly_the_composite_identities_in_proposal_lines() -> None:
    api = _api()
    seal = _seal(api)
    proposal_identities = {
        (line.research_program_id, line.economic_lineage_id, line.stage_id)
        for line in seal.proposal.order_lines
    }
    admission_identities = {
        (item.research_program_id, item.economic_lineage_id, item.stage_id)
        for item in seal.stage_admission_bindings
    }
    consumed_identities = {
        (item.research_program_id, item.economic_lineage_id, item.stage_id)
        for item in (
            seal.consumed_gateway_expected_versions.stage_loss_expected_versions
        )
    }
    assert admission_identities == consumed_identities == proposal_identities

    for changed in (
        seal.stage_admission_bindings[:1],
        seal.stage_admission_bindings
        + (
            seal.stage_admission_bindings[0].model_copy(
                update={"economic_lineage_id": "unrelated-lineage"}
            ),
        ),
    ):
        with pytest.raises(ValidationError, match="stage|lineage|coverage|proposal"):
            api.PortfolioDecisionSeal.model_validate(
                _seal_payload(api, stage_admission_bindings=changed)
            )


def test_gateway_expected_versions_is_a_hashable_consumed_cas_artifact() -> None:
    api = _api()
    expected = _gateway_expected_versions(api)

    assert type(expected).HASH_DOMAIN == (
        "ai-hedge-fund.v3.decision.gateway-expected-versions.v1"
    )
    assert expected.artifact_hash() == api.domain_hash(
        type(expected).HASH_DOMAIN,
        expected.schema_major,
        expected,
    )
    assert {
        "expected_active_seal_id",
        "expected_active_seal_revision",
        "expected_active_seal_logical_key",
        "expected_active_seal_artifact_hash",
    }.issubset(type(expected).model_fields)
    assert (
        expected.expected_active_seal_id,
        expected.expected_active_seal_revision,
        expected.expected_active_seal_logical_key,
        expected.expected_active_seal_artifact_hash,
    ) == (None, None, None, None)


def test_seal_embeds_the_exact_consumed_gateway_expected_versions_artifact() -> None:
    api = _api()
    seal = _seal(api)
    consumed = seal.consumed_gateway_expected_versions

    assert seal.consumed_gateway_expected_versions_artifact_hash == (
        consumed.artifact_hash()
    )
    assert consumed.policy_activation_hash == seal.policy_activation_hash
    assert consumed.trust_bundle_hash == seal.trust_bundle_hash
    assert consumed.authorization_envelope_hash == seal.authorization_envelope_hash
    assert consumed.authorization_status_hash == seal.authorization_status_hash
    assert consumed.entry_fence_hash == seal.entry_fence_hash
    assert consumed.risk_snapshot_artifact_hash == seal.risk_snapshot_artifact_hash


def test_seal_logical_key_proposal_hash_and_identity_exactly_match_proposal() -> None:
    api = _api()
    proposal = _proposal(api)
    base = _seal_payload(api)
    drift_cases = (
        {"logical_key": proposal.logical_key.model_copy(update={"portfolio_id": "x"})},
        {"proposal_artifact_hash": HASH_F},
        {"portfolio_id": "other-portfolio"},
        {"broker_account_id": "other-account"},
        {"broker_account_fingerprint": HASH_F},
        {"mode": api.ExecutionMode.MANUAL_CONFIRMED},
        {"target_entry_session": TARGET_SESSION + timedelta(days=1)},
        {"target_portfolio_policy_fingerprint": HASH_F},
        {"policy_activation_hash": HASH_F},
        {"trust_bundle_hash": HASH_F},
        {"registry_epoch": proposal.registry_epoch + 1},
        {"policy_epoch": proposal.policy_epoch + 1},
        {"authority_epoch": proposal.authority_epoch + 1},
        {"risk_epoch": proposal.risk_epoch + 1},
        {"authorization_id": "other-authorization"},
        {"authorization_version": 99},
        {"evidence_set_merkle_root": HASH_F},
        {"risk_snapshot_id": "other-risk-snapshot"},
        {"risk_snapshot_artifact_hash": HASH_F},
        {"capital_version": proposal.capital_version + 1},
        {"capital_stream_version": proposal.capital_stream_version + 1},
        {"writer_fencing_epoch": proposal.writer_fencing_epoch + 1},
    )
    for drift in drift_cases:
        with pytest.raises(
            ValidationError,
            match="proposal|logical|portfolio|account|mode|policy|authorization|evidence",
        ):
            api.PortfolioDecisionSeal.model_validate(base | drift)


def test_seal_rejects_each_consumed_cas_binding_drift_even_with_fresh_hash() -> None:
    api = _api()
    seal = _seal(api)
    expected = seal.consumed_gateway_expected_versions
    scalar_drifts = {
        "policy_activation_hash": HASH_F,
        "trust_bundle_hash": HASH_F,
        "registry_epoch": expected.registry_epoch + 1,
        "policy_epoch": expected.policy_epoch + 1,
        "authority_epoch": expected.authority_epoch + 1,
        "risk_epoch": expected.risk_epoch + 1,
        "authorization_id": "other-authorization",
        "authorization_version": expected.authorization_version + 1,
        "authorization_envelope_hash": HASH_F,
        "authorization_status_version": expected.authorization_status_version + 1,
        "authorization_status_hash": HASH_F,
        "evidence_set_merkle_root": HASH_F,
        "entry_fence_hash": HASH_A,
        "entry_fence_version": expected.entry_fence_version + 1,
        "risk_snapshot_id": "other-risk-snapshot",
        "risk_snapshot_artifact_hash": HASH_F,
        "capital_version": expected.capital_version + 1,
        "capital_stream_version": expected.capital_stream_version + 1,
        "writer_fencing_epoch": expected.writer_fencing_epoch + 1,
    }
    changed_stage = expected.stage_loss_expected_versions[0].model_copy(
        update={
            "stage_loss_version": (
                expected.stage_loss_expected_versions[0].stage_loss_version + 1
            )
        }
    )
    structured_drifts = {
        "stage_loss_expected_versions": (
            changed_stage,
            *expected.stage_loss_expected_versions[1:],
        ),
        "expected_active_seal_id": "seal-0",
    }
    for field, value in scalar_drifts.items():
        changed = type(expected).model_validate(
            expected.model_dump(mode="python", round_trip=True) | {field: value}
        )
        with pytest.raises(ValidationError, match="expected|proposal|seal|CAS|binding"):
            api.PortfolioDecisionSeal.model_validate(
                _seal_payload(
                    api,
                    consumed_gateway_expected_versions=changed,
                    consumed_gateway_expected_versions_artifact_hash=(
                        changed.artifact_hash()
                    ),
                )
            )
    changed = type(expected).model_validate(
        expected.model_dump(mode="python", round_trip=True)
        | {
            "stage_loss_expected_versions": structured_drifts[
                "stage_loss_expected_versions"
            ]
        }
    )
    with pytest.raises(ValidationError, match="stage|expected|proposal|coverage"):
        api.PortfolioDecisionSeal.model_validate(
            _seal_payload(
                api,
                consumed_gateway_expected_versions=changed,
                consumed_gateway_expected_versions_artifact_hash=changed.artifact_hash(),
            )
        )

    with pytest.raises(ValidationError, match="expected|active seal|supersede"):
        type(expected).model_validate(
            expected.model_dump(mode="python", round_trip=True)
            | {"expected_active_seal_id": "seal-0"}
        )


def test_proposal_cannot_supply_gateway_owned_seal_or_reservation_identity() -> None:
    api = _api()
    proposal = _proposal(api)

    for field in (
        "seal_id",
        "seal_revision",
        "reservation_id",
        "reservation_version",
        "gateway_created_at",
        "created_at",
    ):
        with pytest.raises(ValidationError, match="extra_forbidden"):
            api.PortfolioDecision.model_validate(
                proposal.model_dump(mode="python", round_trip=True) | {field: "owned"}
            )


def test_seal_has_one_strictly_revalidated_proposal_economics_representation() -> None:
    api = _api()
    seal = _seal(api)
    assert "order_lines" not in api.PortfolioDecisionSeal.model_fields
    assert seal.proposal.order_lines == _proposal(api).order_lines

    poisoned = seal.proposal.model_copy(
        update={"total_worst_case_cash_reserve_cents": 1}
    )
    with pytest.raises(ValidationError, match="reserve"):
        api.PortfolioDecisionSeal.model_validate(_seal_payload(api, proposal=poisoned))


def test_seal_cannot_change_any_bound_proposal_order_line() -> None:
    api = _api()
    proposal = _proposal(api)
    changed_line = proposal.order_lines[0].model_copy(
        update={"security_id": "000001.SZ"}
    )
    changed_proposal = proposal.model_copy(
        update={"order_lines": (changed_line, *proposal.order_lines[1:])}
    )
    with pytest.raises(ValidationError, match="proposal|artifact hash"):
        api.PortfolioDecisionSeal.model_validate(
            _seal_payload(api, proposal=changed_proposal)
        )


def test_seal_reserve_is_exact_per_line_and_in_aggregate() -> None:
    api = _api()
    seal = _seal(api)
    assert tuple(item.order_line_id for item in seal.line_reserve_bindings) == tuple(
        line.order_line_id for line in seal.proposal.order_lines
    )
    assert seal.total_reserved_cash_cents == sum(
        line.worst_case_cash_reserve_cents for line in seal.proposal.order_lines
    )

    reserve_lines = list(seal.line_reserve_bindings)
    reserve_lines[0] = reserve_lines[0].model_copy(
        update={"reserved_cash_cents": reserve_lines[0].reserved_cash_cents - 1}
    )
    for drift in (
        {"line_reserve_bindings": tuple(reserve_lines)},
        {"total_reserved_cash_cents": seal.total_reserved_cash_cents - 1},
    ):
        with pytest.raises(ValidationError, match="reserve"):
            api.PortfolioDecisionSeal.model_validate(_seal_payload(api, **drift))

    duplicate_allocations = (
        seal.line_reserve_bindings[0],
        seal.line_reserve_bindings[1].model_copy(
            update={
                "reservation_allocation_id": (
                    seal.line_reserve_bindings[0].reservation_allocation_id
                )
            }
        ),
    )
    with pytest.raises(ValidationError, match="allocation|reserve|unique|duplicate"):
        api.PortfolioDecisionSeal.model_validate(
            _seal_payload(api, line_reserve_bindings=duplicate_allocations)
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("post_admission_capital_version", 10),
        ("post_admission_capital_version", 9),
        ("post_admission_reservation_version", 1),
        ("post_admission_reservation_version", 0),
    ],
)
def test_post_admission_versions_must_strictly_advance_without_exact_step_claim(
    field, value
) -> None:
    api = _api()
    with pytest.raises(ValidationError, match="post|version|strict|advance"):
        api.PortfolioDecisionSeal.model_validate(_seal_payload(api, **{field: value}))

    legal_non_unit_advance = _seal(
        api,
        post_admission_capital_version=12,
        post_admission_reservation_version=4,
    )
    assert legal_non_unit_advance.post_admission_capital_version > (
        legal_non_unit_advance.capital_version
    )
    assert legal_non_unit_advance.post_admission_reservation_version > (
        legal_non_unit_advance.reservation_version
    )


def test_first_publication_has_no_supersede_or_expected_active_seal_claim() -> None:
    api = _api()
    assert "active_seal_id" not in api.PortfolioDecisionSeal.model_fields
    seal = _seal(api)
    expected = seal.consumed_gateway_expected_versions
    assert seal.supersedes_seal_id is None
    assert seal.supersedes_seal_revision is None
    assert seal.prior_seal_eligibility is None
    assert expected.expected_active_seal_id is None
    assert expected.expected_active_seal_revision is None
    assert expected.expected_active_seal_logical_key is None
    assert expected.expected_active_seal_artifact_hash is None


def test_legal_supersede_has_one_exact_prior_identity_in_all_representations() -> None:
    api = _api()

    eligible = _prior_seal_eligibility(api)
    superseding = _seal(
        api,
        seal_revision=2,
        supersedes_seal_id=eligible.prior_seal_id,
        supersedes_seal_revision=eligible.prior_seal_revision,
        prior_seal_eligibility=eligible,
    )
    assert superseding.seal_revision > eligible.prior_seal_revision
    consumed = superseding.consumed_gateway_expected_versions
    assert (
        superseding.supersedes_seal_id,
        eligible.prior_seal_id,
        consumed.expected_active_seal_id,
    ) == (eligible.prior_seal_id,) * 3
    assert (
        superseding.supersedes_seal_revision,
        eligible.prior_seal_revision,
        consumed.expected_active_seal_revision,
    ) == (eligible.prior_seal_revision,) * 3
    assert (
        eligible.logical_key
        == consumed.expected_active_seal_logical_key
        == (superseding.logical_key)
    )
    assert eligible.prior_seal_artifact_hash == (
        consumed.expected_active_seal_artifact_hash
    )


@pytest.mark.parametrize(
    "case",
    [
        "missing_supersedes_id",
        "missing_supersedes_revision",
        "missing_prior_eligibility",
        "missing_expected_active",
        "missing_expected_id",
        "missing_expected_revision",
        "missing_expected_logical_key",
        "missing_expected_artifact_hash",
        "mismatch_supersedes_id",
        "mismatch_supersedes_revision",
        "mismatch_prior_id",
        "mismatch_prior_revision",
        "mismatch_prior_logical_key",
        "mismatch_prior_artifact_hash",
        "mismatch_expected_id",
        "mismatch_expected_revision",
        "mismatch_expected_logical_key",
        "mismatch_expected_artifact_hash",
    ],
)
def test_supersede_rejects_every_missing_or_mismatched_prior_representation(
    case,
) -> None:
    api = _api()
    eligibility = _prior_seal_eligibility(api)
    payload = _seal_payload(
        api,
        seal_revision=2,
        supersedes_seal_id=eligibility.prior_seal_id,
        supersedes_seal_revision=eligibility.prior_seal_revision,
        prior_seal_eligibility=eligibility,
    )
    expected = payload["consumed_gateway_expected_versions"]

    if case == "missing_supersedes_id":
        payload["supersedes_seal_id"] = None
    elif case == "missing_supersedes_revision":
        payload["supersedes_seal_revision"] = None
    elif case == "missing_prior_eligibility":
        payload["prior_seal_eligibility"] = None
    elif case == "missing_expected_active":
        first_expected = _gateway_expected_versions(api)
        payload["consumed_gateway_expected_versions"] = first_expected
        payload["consumed_gateway_expected_versions_artifact_hash"] = (
            first_expected.artifact_hash()
        )
    elif case.startswith("missing_expected_"):
        field = case.removeprefix("missing_expected_")
        field = {
            "id": "expected_active_seal_id",
            "revision": "expected_active_seal_revision",
            "logical_key": "expected_active_seal_logical_key",
            "artifact_hash": "expected_active_seal_artifact_hash",
        }[field]
        payload["consumed_gateway_expected_versions"] = expected.model_copy(
            update={field: None}
        )
    elif case == "mismatch_supersedes_id":
        payload["supersedes_seal_id"] = "other-seal"
    elif case == "mismatch_supersedes_revision":
        payload["supersedes_seal_revision"] = 99
    elif case.startswith("mismatch_prior_"):
        field = case.removeprefix("mismatch_prior_")
        field = {
            "id": "prior_seal_id",
            "revision": "prior_seal_revision",
            "logical_key": "logical_key",
            "artifact_hash": "prior_seal_artifact_hash",
        }[field]
        value = {
            "prior_seal_id": "other-seal",
            "prior_seal_revision": 99,
            "logical_key": eligibility.logical_key.model_copy(
                update={"decision_cycle_id": "other-cycle"}
            ),
            "prior_seal_artifact_hash": HASH_F,
        }[field]
        payload["prior_seal_eligibility"] = eligibility.model_copy(
            update={field: value}
        )
    else:
        field = case.removeprefix("mismatch_expected_")
        field = {
            "id": "expected_active_seal_id",
            "revision": "expected_active_seal_revision",
            "logical_key": "expected_active_seal_logical_key",
            "artifact_hash": "expected_active_seal_artifact_hash",
        }[field]
        value = {
            "expected_active_seal_id": "other-seal",
            "expected_active_seal_revision": 99,
            "expected_active_seal_logical_key": eligibility.logical_key.model_copy(
                update={"decision_cycle_id": "other-cycle"}
            ),
            "expected_active_seal_artifact_hash": HASH_F,
        }[field]
        changed = type(expected).model_validate(
            expected.model_dump(mode="python", round_trip=True) | {field: value}
        )
        payload["consumed_gateway_expected_versions"] = changed
        payload["consumed_gateway_expected_versions_artifact_hash"] = (
            changed.artifact_hash()
        )

    with pytest.raises(
        ValidationError, match="supersede|prior|expected active|logical|artifact"
    ):
        api.PortfolioDecisionSeal.model_validate(payload)


def test_first_publication_rejects_consumed_expected_active_seal_pair() -> None:
    api = _api()
    eligibility = _prior_seal_eligibility(api)
    proposal = _proposal(api)
    expected = _gateway_expected_versions(
        api,
        proposal,
        expected_active_seal_id=eligibility.prior_seal_id,
        expected_active_seal_revision=eligibility.prior_seal_revision,
        expected_active_seal_logical_key=eligibility.logical_key,
        expected_active_seal_artifact_hash=eligibility.prior_seal_artifact_hash,
    )
    with pytest.raises(ValidationError, match="first|supersede|expected active"):
        api.PortfolioDecisionSeal.model_validate(
            _seal_payload(
                api,
                proposal=proposal,
                consumed_gateway_expected_versions=expected,
                consumed_gateway_expected_versions_artifact_hash=(
                    expected.artifact_hash()
                ),
            )
        )


@pytest.mark.parametrize(
    "drift",
    [
        {"logical_key": DIFFERENT_LOGICAL_KEY},
        {"permit_issuance_sequence": 1},
        {"fencing_token_issuance_sequence": 1},
        {"live_order_count": 1},
    ],
)
def test_supersede_requires_same_key_no_prior_permit_fence_or_live_order(drift) -> None:
    api = _api()
    if drift.get("logical_key") is DIFFERENT_LOGICAL_KEY:
        drift = {
            "logical_key": _proposal(api).logical_key.model_copy(
                update={"decision_cycle_id": "other-cycle"}
            )
        }
    eligibility = _prior_seal_eligibility(api, **drift)
    with pytest.raises(
        ValidationError, match="supersede|logical|permit|fenc|live order|eligib"
    ):
        api.PortfolioDecisionSeal.model_validate(
            _seal_payload(
                api,
                seal_revision=2,
                supersedes_seal_id=eligibility.prior_seal_id,
                supersedes_seal_revision=eligibility.prior_seal_revision,
                prior_seal_eligibility=eligibility,
            )
        )


def test_supersede_revision_must_be_strictly_higher_than_prior_revision() -> None:
    api = _api()
    eligibility = _prior_seal_eligibility(api)
    with pytest.raises(ValidationError, match="revision|higher|supersede"):
        api.PortfolioDecisionSeal.model_validate(
            _seal_payload(
                api,
                seal_revision=eligibility.prior_seal_revision,
                supersedes_seal_id=eligibility.prior_seal_id,
                supersedes_seal_revision=eligibility.prior_seal_revision,
                prior_seal_eligibility=eligibility,
            )
        )


def test_seal_hash_covers_proposal_and_every_gateway_binding() -> None:
    api = _api()
    seal = _seal(api)
    proposal = _proposal(api)
    proposal_variant = api.PortfolioDecision.model_validate(
        proposal.model_dump(mode="python", round_trip=True)
        | {
            "logical_key": proposal.logical_key.model_copy(
                update={"decision_cycle_id": "daily-t1-open-v2"}
            )
        }
    )
    expected_variant = _gateway_expected_versions(
        api,
        proposal,
        authorization_status_version=6,
        authorization_status_hash=HASH_F,
    )
    reserve_variant = tuple(
        item.model_copy(
            update={
                "reservation_allocation_id": (
                    f"replacement-{item.reservation_allocation_id}"
                )
            }
        )
        for item in seal.line_reserve_bindings
    )
    issuer_variant = seal.issuer_binding.model_copy(
        update={"key_id": "capital-gateway-key-2"}
    )
    window_variant = _window(
        api,
        broker_auction_submission_cutoff=BROKER_CUTOFF + timedelta(microseconds=1),
    )
    eligibility = _prior_seal_eligibility(api)
    valid_variants = {
        "proposal": _seal(api, proposal=proposal_variant),
        "consumed_expected": _seal(
            api, consumed_gateway_expected_versions=expected_variant
        ),
        "reserve": _seal(api, line_reserve_bindings=reserve_variant),
        "issuer": _seal(api, issuer_binding=issuer_variant),
        "deadline": _seal(api, execution_window=window_variant),
        "supersede": _seal(
            api,
            seal_revision=2,
            supersedes_seal_id=eligibility.prior_seal_id,
            supersedes_seal_revision=eligibility.prior_seal_revision,
            prior_seal_eligibility=eligibility,
        ),
    }
    for label, valid_variant in valid_variants.items():
        assert valid_variant.artifact_hash() != seal.artifact_hash(), label
