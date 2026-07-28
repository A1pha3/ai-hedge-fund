"""Checkpoint 2 RED: non-authoritative shadow decisions."""

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


def test_shadow_has_complete_counterfactual_provenance_and_independent_lines() -> None:
    api = _api()
    assert set(api.CounterfactualDecisionKey.model_fields) == {
        "portfolio_id",
        "signal_session",
        "counterfactual_cycle_id",
    }
    assert set(api.ShadowDecision.model_fields) == {
        "artifact_kind",
        "artifact_namespace",
        "schema_major",
        "shadow_decision_id",
        "counterfactual_key",
        "portfolio_id",
        "mode",
        "target_entry_session",
        "producer_namespace",
        "family_id",
        "research_program_id",
        "economic_lineage_id",
        "stage_id",
        "trial_id",
        "policy_activation_hash",
        "policy_epoch",
        "evidence_set_merkle_root",
        "shadow_stage_binding",
        "counterfactual_lines",
        "cost_assumption_version",
        "execution_assumption_version",
        "created_at",
        "available_at",
        "execution_authority",
        "issuer_binding",
    }
    assert set(api.ShadowOrderLine.model_fields) == {
        "shadow_line_id",
        "security_id",
        "producer_namespace",
        "family_id",
        "economic_lineage_id",
        "research_program_id",
        "stage_id",
        "trial_id",
        "stage_manifest_hash",
        "evidence_id",
        "evidence_artifact_hash",
        "evidence_payload_hash",
        "target_quantity_units",
        "lot_size_units",
        "lot_rule_version",
        "order_type",
        "limit_price_cents",
        "worst_case_price_cents",
        "price_boundary_version",
        "time_in_force",
        "exit_session_ordinal",
        "estimated_fee_cents",
        "estimated_cash_reserve_cents",
        "cost_assumption_version",
        "execution_assumption_version",
    }
    shadow = _shadow(api)
    assert shadow.execution_authority == "NONE"
    assert len(shadow.counterfactual_lines) == 2
    assert set(api.ShadowStageBinding.model_fields) == {
        "research_program_id",
        "economic_lineage_id",
        "stage_id",
        "trial_id",
        "stage_manifest_hash",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("producer_namespace", "different-producer"),
        ("family_id", "different-family"),
        ("research_program_id", "different-program"),
        ("economic_lineage_id", "different-lineage"),
        ("stage_id", "different-stage"),
        ("trial_id", "different-trial"),
        ("cost_assumption_version", "different-cost"),
        ("execution_assumption_version", "different-execution"),
    ],
)
def test_shadow_lines_must_match_header_provenance_and_assumptions(
    field, value
) -> None:
    api = _api()
    shadow = _shadow(api)
    changed = shadow.counterfactual_lines[0].model_copy(update={field: value})
    with pytest.raises(
        ValidationError,
        match="producer|family|program|lineage|stage|trial|cost|execution|header",
    ):
        api.ShadowDecision.model_validate(
            _shadow_payload(
                api,
                counterfactual_lines=(changed, *shadow.counterfactual_lines[1:]),
            )
        )


def test_single_shadow_stage_binding_exactly_matches_every_line() -> None:
    api = _api()
    shadow = _shadow(api)
    expected = {
        (
            line.research_program_id,
            line.economic_lineage_id,
            line.stage_id,
            line.trial_id,
            line.stage_manifest_hash,
        )
        for line in shadow.counterfactual_lines
    }
    actual = (
        shadow.shadow_stage_binding.research_program_id,
        shadow.shadow_stage_binding.economic_lineage_id,
        shadow.shadow_stage_binding.stage_id,
        shadow.shadow_stage_binding.trial_id,
        shadow.shadow_stage_binding.stage_manifest_hash,
    )
    assert expected == {actual}

    changed_manifest_line = shadow.counterfactual_lines[0].model_copy(
        update={"stage_manifest_hash": HASH_F}
    )
    with pytest.raises(ValidationError, match="stage|manifest|binding|header"):
        api.ShadowDecision.model_validate(
            _shadow_payload(
                api,
                counterfactual_lines=(
                    changed_manifest_line,
                    *shadow.counterfactual_lines[1:],
                ),
            )
        )
    with pytest.raises(ValidationError, match="stage|binding|required"):
        api.ShadowDecision.model_validate(
            _shadow_payload(api, shadow_stage_binding=None)
        )
    with pytest.raises(ValidationError, match="line|canonical|order"):
        api.ShadowDecision.model_validate(
            _shadow_payload(
                api,
                counterfactual_lines=tuple(reversed(shadow.counterfactual_lines)),
            )
        )


def test_shadow_rejects_same_stage_identity_with_different_manifest_hash() -> None:
    api = _api()
    shadow = _shadow(api)
    changed_binding = shadow.shadow_stage_binding.model_copy(
        update={"stage_manifest_hash": HASH_F}
    )
    with pytest.raises(ValidationError, match="stage|manifest|line|binding"):
        api.ShadowDecision.model_validate(
            _shadow_payload(api, shadow_stage_binding=changed_binding)
        )


def test_shadow_schema_forbids_every_authority_and_execution_field() -> None:
    api = _api()
    forbidden = {
        "seal_id",
        "seal_revision",
        "active_seal_id",
        "authorization_id",
        "authorization_status",
        "gateway_expected_versions",
        "reservation_id",
        "reserve_cents",
        "permit_nonce",
        "outbox_batch_id",
        "client_order_id",
        "broker_ack_id",
        "fill_id",
    }
    assert forbidden.isdisjoint(api.ShadowDecision.model_fields)
    for field in forbidden:
        with pytest.raises(ValidationError, match="extra_forbidden"):
            api.ShadowDecision.model_validate(
                _shadow_payload(api) | {field: "forbidden"}
            )


def test_shadow_counterfactual_key_is_not_a_seal_logical_key() -> None:
    api = _api()
    key = _shadow(api).counterfactual_key
    with pytest.raises(ValidationError):
        api.DecisionLogicalKey.model_validate(
            key.model_dump(mode="python", round_trip=True)
        )
