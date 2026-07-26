"""Revision 2 portfolio authorization envelope contracts."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

UTC = timezone.utc
HASH = "a" * 64


def _grant(**overrides):
    from src.screening.offensive.v3.contracts.governance import GrantKind

    payload = {
        "grant_id": "grant-1",
        "grant_kind": GrantKind.EDGE,
        "grant_certificate_hash": HASH,
        "grant_issuer_id": "authorizer",
        "subject_producer": "btst",
        "family_id": "btst-family",
        "economic_lineage_id": "btst-lineage",
        "research_program_id": "program-1",
        "behavior_fingerprint": HASH,
        "execution_version": "t1-open",
        "cost_version": "cost-v1",
        "capital_tier": 2,
        "lineage_gross_cap": Decimal("0.02"),
        "trial_id": "trial-1",
        "trial_manifest_hash": HASH,
        "statistical_analysis_plan_hash": HASH,
        "stage_id": "stage-1",
        "stage_manifest_hash": HASH,
        "stage_sample_reservation_id": "reservation-1",
        "stage_loss_budget_id": "stage-budget-1",
        "stage_loss_budget_cents": 100,
        "stage_loss_version": 1,
        "assessment_result_hash": HASH,
        "grant_evidence_set_merkle_root": HASH,
        "attempt_ledger_checkpoint_hash": HASH,
        "alpha_or_evalue_budget_consumption_id": "alpha-1",
        "alpha_sample_consumption_id": "sample-1",
        "schema_major": 2,
    }
    return payload | overrides


def _envelope(**overrides):
    from src.screening.offensive.v3.contracts.base import ExecutionMode
    from src.screening.offensive.v3.contracts.authorization import AuthorizationKind

    payload = {
        "authorization_kind": AuthorizationKind.EDGE,
        "authorization_id": "envelope-1",
        "authorization_version": 1,
        "mode": ExecutionMode.BROKER_CONFIRMED,
        "portfolio_id": "portfolio-1",
        "broker_account_id": "account-1",
        "broker_account_fingerprint": HASH,
        "base_currency": "CNY",
        "policy_activation_hash": HASH,
        "trust_bundle_hash": HASH,
        "registry_epoch": 2,
        "policy_epoch": 2,
        "authority_epoch": 2,
        "risk_epoch": 2,
        "research_program_ids": ("program-1",),
        "baseline_portfolio_policy_fingerprint": HASH,
        "target_portfolio_policy_fingerprint": HASH,
        "lineage_grants": (_grant(),),
        "evidence_as_of": datetime(2026, 7, 19, 8, tzinfo=UTC),
        "evidence_set_merkle_root": HASH,
        "issued_at": datetime(2026, 7, 19, 9, tzinfo=UTC),
        "expires_at": datetime(2026, 7, 20, 9, tzinfo=UTC),
        "activation_capital_snapshot_id": "capital-1",
        "activation_capital_snapshot_hash": HASH,
        "portfolio_gross_cap": Decimal("0.02"),
        "exploration_aggregate_gross_cap": Decimal("0"),
        "program_loss_budget_bindings": (
            {
                "research_program_id": "program-1",
                "budget_id": "program-budget-1",
                "budget_cents": 200,
                "consumed_cents": 0,
                "version": 1,
                "schema_major": 2,
            },
        ),
        "issuer_id": "authorizer",
        "issuer_capability": "authorizer.edge.envelope.v1",
        "portfolio_assessment_result_hash": HASH,
        "global_attempt_ledger_checkpoint_hash": HASH,
        "global_multiplicity_budget_consumption_id": "global-1",
        "schema_major": 2,
    }
    return payload | overrides


def test_envelope_is_one_complete_portfolio_policy_and_has_no_self_hash():
    from src.screening.offensive.v3.contracts.authorization import (
        CapitalAuthorizationEnvelope,
    )

    item = CapitalAuthorizationEnvelope.model_validate(_envelope())
    assert item.authorization_kind.value == "EDGE"
    assert "authorization_payload_hash" not in CapitalAuthorizationEnvelope.model_fields
    assert {
        "portfolio_id",
        "target_portfolio_policy_fingerprint",
        "lineage_grants",
    } <= set(CapitalAuthorizationEnvelope.model_fields)
    with pytest.raises(ValidationError):
        CapitalAuthorizationEnvelope.model_validate(_envelope(lineage_grants=()))
    with pytest.raises(ValidationError):
        CapitalAuthorizationEnvelope.model_validate(
            _envelope(research_program_ids=("program-1", "program-1"))
        )


def test_envelope_rejects_top_level_legacy_lineage_authorizations_and_float_truth():
    from src.screening.offensive.v3.contracts.authorization import (
        CapitalAuthorizationEnvelope,
    )

    with pytest.raises(ValidationError):
        CapitalAuthorizationEnvelope.model_validate(
            _envelope(edge_authorizations=(_grant(),))
        )
    with pytest.raises(ValidationError):
        CapitalAuthorizationEnvelope.model_validate(
            _envelope(
                program_loss_budget_bindings=(
                    {
                        "research_program_id": "program-1",
                        "budget_id": "budget",
                        "budget_cents": 1.0,
                        "consumed_cents": 0,
                        "version": 1,
                        "schema_major": 2,
                    },
                )
            )
        )


def test_envelope_requires_exact_broker_binding_and_capability_per_kind():
    from src.screening.offensive.v3.contracts.authorization import (
        CapitalAuthorizationEnvelope,
    )

    payload = _envelope()
    for override in (
        {"broker_account_id": None},
        {"broker_account_fingerprint": None},
        {"issuer_capability": "governance.exploration.envelope.v1"},
        {"mode": "research_reconstruction"},
    ):
        with pytest.raises(ValidationError):
            CapitalAuthorizationEnvelope.model_validate(payload | override)
    manual = payload | {"mode": "manual_confirmed", "broker_account_fingerprint": HASH}
    with pytest.raises(ValidationError):
        CapitalAuthorizationEnvelope.model_validate(manual)


def test_envelope_rejects_duplicate_grant_budget_ids_and_bad_budget_conservation():
    from src.screening.offensive.v3.contracts.authorization import (
        CapitalAuthorizationEnvelope,
    )

    payload = _envelope()
    duplicate_grant = _grant(grant_id="grant-1")
    bad_budget = {
        "research_program_id": "program-1",
        "budget_id": "budget-1",
        "budget_cents": 1,
        "consumed_cents": 2,
        "version": 1,
        "schema_major": 2,
    }
    for override in (
        {"lineage_grants": (_grant(), duplicate_grant)},
        {"program_loss_budget_bindings": (bad_budget,)},
        {"research_program_ids": ("program-1", "program-2")},
        {"authorization_version": True},
    ):
        with pytest.raises(ValidationError):
            CapitalAuthorizationEnvelope.model_validate(payload | override)
