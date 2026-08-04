"""Adversarial tests for Task 2 review remediation A."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
import json

import pytest
from pydantic import ValidationError

from test_authorization import HASH, _envelope, _grant
from test_governance import NOW, _trial


def test_json_decimal_numbers_cannot_launder_into_exact_contracts() -> None:
    from src.screening.offensive.v3.contracts.authorization import (
        CapitalAuthorizationEnvelope,
    )

    payload = _envelope()
    payload["portfolio_gross_cap"] = "0.02"
    payload["exploration_aggregate_gross_cap"] = "0"
    payload["lineage_grants"][0]["lineage_gross_cap"] = "0.02"
    encoded = json.dumps(payload, default=str)
    parsed = CapitalAuthorizationEnvelope.model_validate_json(encoded)
    assert parsed.portfolio_gross_cap == Decimal("0.02")
    assert (
        CapitalAuthorizationEnvelope.model_validate_json(parsed.model_dump_json())
        == parsed
    )

    for path in ("portfolio", "grant"):
        for non_string in (0.02, True):
            poisoned = json.loads(encoded)
            if path == "portfolio":
                poisoned["portfolio_gross_cap"] = non_string
            else:
                poisoned["lineage_grants"][0]["lineage_gross_cap"] = non_string
            with pytest.raises(ValidationError):
                CapitalAuthorizationEnvelope.model_validate_json(json.dumps(poisoned))


@pytest.mark.parametrize(
    "value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")]
)
def test_exact_decimal_contracts_reject_non_finite_values(value: Decimal) -> None:
    from src.screening.offensive.v3.contracts.authorization import (
        CapitalAuthorizationEnvelope,
    )

    with pytest.raises(ValidationError):
        CapitalAuthorizationEnvelope.model_validate(
            _envelope(portfolio_gross_cap=value)
        )
    with pytest.raises(ValidationError):
        CapitalAuthorizationEnvelope.model_validate(
            _envelope(lineage_grants=(_grant(lineage_gross_cap=value),))
        )


def test_trial_exact_decimals_use_canonical_json_strings() -> None:
    from src.screening.offensive.v3.contracts.governance import TrialManifest

    payload = _trial()
    payload["minimum_economic_effect"] = "0.0010"
    payload["one_sided_confidence_level"] = "0.950"
    encoded = json.dumps(payload, default=str)
    trial = TrialManifest.model_validate_json(encoded)
    assert trial.minimum_economic_effect == Decimal("0.001")
    assert trial.one_sided_confidence_level == Decimal("0.95")
    assert TrialManifest.model_validate_json(trial.model_dump_json()) == trial

    for field_name, number in (
        ("minimum_economic_effect", 0.001),
        ("one_sided_confidence_level", 0.95),
    ):
        for non_string in (number, True):
            poisoned = json.loads(encoded)
            poisoned[field_name] = non_string
            with pytest.raises(ValidationError):
                TrialManifest.model_validate_json(json.dumps(poisoned))

    for non_finite in (Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")):
        for field_name in (
            "minimum_economic_effect",
            "one_sided_confidence_level",
        ):
            with pytest.raises(ValidationError):
                TrialManifest.model_validate(_trial(**{field_name: non_finite}))


def test_exact_decimal_validation_schemas_accept_strings_only() -> None:
    from src.screening.offensive.v3.contracts.authorization import (
        CapitalAuthorizationEnvelope,
    )
    from src.screening.offensive.v3.contracts.governance import TrialManifest

    envelope_schema = CapitalAuthorizationEnvelope.model_json_schema()
    assert envelope_schema["properties"]["portfolio_gross_cap"]["type"] == "string"
    assert (
        envelope_schema["$defs"]["LineageGrant"]["properties"]["lineage_gross_cap"][
            "type"
        ]
        == "string"
    )
    trial_schema = TrialManifest.model_json_schema()
    assert trial_schema["properties"]["minimum_economic_effect"]["type"] == "string"
    assert trial_schema["properties"]["one_sided_confidence_level"]["type"] == "string"


def test_lineage_grant_enforces_tier_and_exploration_shared_budget() -> None:
    from src.screening.offensive.v3.contracts.governance import GrantKind, LineageGrant

    with pytest.raises(ValidationError):
        LineageGrant.model_validate(_grant(lineage_gross_cap=Decimal("0.021")))
    with pytest.raises(ValidationError):
        LineageGrant.model_validate(
            _grant(grant_kind=GrantKind.EXPLORATION, capital_tier=5)
        )
    with pytest.raises(ValidationError):
        LineageGrant.model_validate(
            _grant(grant_kind=GrantKind.EXPLORATION, capital_tier=2)
        )


def test_trial_sap_and_stage_freeze_portfolio_log_growth_before_enrollment() -> None:
    from src.screening.offensive.v3.contracts.base import ExecutionMode
    from src.screening.offensive.v3.contracts.governance import (
        PrimaryMetric,
        StageManifest,
        StatisticalAnalysisPlan,
        TrialManifest,
    )

    trial = TrialManifest.model_validate(
        _trial(primary_metric=PrimaryMetric.PORTFOLIO_LOG_GROWTH)
    )
    assert trial.issued_at == trial.trial_manifest_sealed_at < trial.enrollment_start
    with pytest.raises(ValidationError):
        TrialManifest.model_validate(_trial(primary_metric="win_rate"))
    with pytest.raises(ValidationError):
        TrialManifest.model_validate(_trial(issued_at=NOW - timedelta(seconds=1)))
    with pytest.raises(ValidationError):
        TrialManifest.model_validate(
            _trial(
                execution_mode=ExecutionMode.MANUAL_CONFIRMED,
                broker_experiment_design="not-allowed",
            )
        )

    sap = {
        "sap_id": "sap-1",
        "trial_manifest_hash": HASH,
        "research_program_id": "program-1",
        "economic_lineage_id": "btst-lineage",
        "primary_metric": PrimaryMetric.PORTFOLIO_LOG_GROWTH,
        "baseline_portfolio_policy_fingerprint": HASH,
        "target_portfolio_policy_fingerprint": HASH,
        "execution_mode": ExecutionMode.BROKER_CONFIRMED,
        "one_sided_confidence_level": Decimal("0.95"),
        "bootstrap_method": "moving",
        "repetitions": 1000,
        "seed": 7,
        "block_rule": "40",
        "multiplicity_policy": "alpha",
        "alpha_or_evalue_budget_consumption_id": "alpha-1",
        "issued_at": NOW,
        "sealed_at": NOW,
        "enrollment_start": NOW + timedelta(days=1),
        "expires_at": NOW + timedelta(days=2),
        "issuer_id": "governance",
        "issuer_capability": "governance.sap.v1",
        "schema_major": 2,
    }
    assert StatisticalAnalysisPlan.model_validate(sap).issued_at == NOW
    with pytest.raises(ValidationError):
        StatisticalAnalysisPlan.model_validate(
            sap | {"issued_at": NOW + timedelta(seconds=1)}
        )

    stage_fields = set(StageManifest.model_fields)
    assert {"primary_metric", "issued_at", "enrollment_start"} <= stage_fields


def test_envelope_requires_exact_program_identity_and_canonical_order() -> None:
    from src.screening.offensive.v3.contracts.authorization import (
        CapitalAuthorizationEnvelope,
    )

    program_1 = _grant(grant_id="grant-1", economic_lineage_id="lineage-1")
    program_2 = _grant(
        grant_id="grant-2",
        economic_lineage_id="lineage-2",
        research_program_id="program-2",
        grant_certificate_hash="b" * 64,
        assessment_result_hash="c" * 64,
        stage_id="stage-2",
        stage_sample_reservation_id="reservation-2",
        stage_loss_budget_id="stage-budget-2",
        attempt_ledger_checkpoint_hash="d" * 64,
        alpha_or_evalue_budget_consumption_id="alpha-2",
        alpha_sample_consumption_id="sample-2",
    )
    budget_1 = _envelope()["program_loss_budget_bindings"][0]
    budget_2 = budget_1 | {
        "research_program_id": "program-2",
        "budget_id": "program-budget-2",
    }
    valid = _envelope(
        research_program_ids=("program-1", "program-2"),
        lineage_grants=(program_1, program_2),
        program_loss_budget_bindings=(budget_1, budget_2),
    )
    CapitalAuthorizationEnvelope.model_validate(valid)
    with pytest.raises(ValidationError):
        CapitalAuthorizationEnvelope.model_validate(
            valid | {"research_program_ids": ("program-2", "program-1")}
        )
    with pytest.raises(ValidationError):
        CapitalAuthorizationEnvelope.model_validate(
            valid | {"lineage_grants": (program_2, program_1)}
        )
    with pytest.raises(ValidationError):
        CapitalAuthorizationEnvelope.model_validate(
            valid
            | {
                "lineage_grants": (
                    program_1,
                    program_2 | {"economic_lineage_id": "lineage-1"},
                )
            }
        )
    for field_name in (
        "grant_id",
        "economic_lineage_id",
        "grant_certificate_hash",
        "assessment_result_hash",
        "stage_id",
        "stage_sample_reservation_id",
        "stage_loss_budget_id",
        "attempt_ledger_checkpoint_hash",
        "alpha_or_evalue_budget_consumption_id",
        "alpha_sample_consumption_id",
    ):
        with pytest.raises(ValidationError):
            CapitalAuthorizationEnvelope.model_validate(
                valid
                | {
                    "lineage_grants": (
                        program_1,
                        program_2 | {field_name: program_1[field_name]},
                    )
                }
            )
    with pytest.raises(ValidationError):
        CapitalAuthorizationEnvelope.model_validate(
            valid | {"program_loss_budget_bindings": (budget_2, budget_1)}
        )
    with pytest.raises(ValidationError):
        CapitalAuthorizationEnvelope.model_validate(
            valid
            | {
                "program_loss_budget_bindings": (
                    budget_1,
                    budget_2 | {"budget_id": budget_1["budget_id"]},
                )
            }
        )
    with pytest.raises(ValidationError):
        CapitalAuthorizationEnvelope.model_validate(
            valid | {"research_program_ids": ("program-1", "program-2", "program-3")}
        )


def test_exploration_and_recovery_bind_predecessor_and_shared_budget() -> None:
    from src.screening.offensive.v3.contracts.authorization import (
        AuthorizationKind,
        CapitalAuthorizationEnvelope,
    )
    from src.screening.offensive.v3.contracts.governance import GrantKind

    edge = _grant(grant_id="edge", grant_certificate_hash="b" * 64)
    exploration = _grant(
        grant_id="explore",
        grant_kind=GrantKind.EXPLORATION,
        grant_certificate_hash="c" * 64,
        economic_lineage_id="explore-lineage",
        stage_loss_budget_id="exploration-loss-1",
        shared_exploration_loss_budget_id="exploration-loss-1",
        assessment_result_hash="d" * 64,
        stage_id="explore-stage",
        stage_sample_reservation_id="explore-reservation",
        attempt_ledger_checkpoint_hash="e" * 64,
        alpha_or_evalue_budget_consumption_id="explore-alpha",
        alpha_sample_consumption_id="explore-sample",
        trial_id="explore-trial",
    )
    predecessor = {
        "predecessor_active_authorization_id": "previous-1",
        "predecessor_active_authorization_version": 1,
        "predecessor_active_authorization_hash": HASH,
        "predecessor_active_authorization_status_hash": HASH,
        "predecessor_target_policy_fingerprint": HASH,
        "predecessor_active_edge_grant_certificate_hashes": ("b" * 64,),
    }
    exploration_only = {
        "exploration_shared_stress_loss_budget_id": "exploration-loss-1",
        "exploration_shared_stress_loss_budget_cents": 100,
        "exploration_shared_stress_loss_consumed_cents": 0,
        "exploration_shared_stress_loss_version": 1,
        "exploration_one_shot_reservation_id": "one-shot-reservation",
        "exploration_one_shot_consumption_id": "one-shot-consumption",
        "exploration_trial_id": "explore-trial",
        "exploration_fixed_assessment_at": NOW + timedelta(days=10),
    }
    payload = _envelope(
        authorization_kind=AuthorizationKind.EXPLORATION,
        issuer_capability="governance.exploration.envelope.v1",
        lineage_grants=(edge, exploration),
        portfolio_gross_cap=Decimal("0.04"),
        exploration_aggregate_gross_cap=Decimal("0.02"),
        **predecessor,
        **exploration_only,
    )
    CapitalAuthorizationEnvelope.model_validate(payload)
    with pytest.raises(ValidationError):
        CapitalAuthorizationEnvelope.model_validate(
            payload | {"predecessor_active_edge_grant_certificate_hashes": ()}
        )
    with pytest.raises(ValidationError):
        CapitalAuthorizationEnvelope.model_validate(
            payload | {"exploration_shared_stress_loss_consumed_cents": 101}
        )
    with pytest.raises(ValidationError):
        CapitalAuthorizationEnvelope.model_validate(_envelope(**exploration_only))
    with pytest.raises(ValidationError):
        CapitalAuthorizationEnvelope.model_validate(
            _envelope(predecessor_active_authorization_id="partial-predecessor")
        )

    recovery = _envelope(
        authorization_kind=AuthorizationKind.RECOVERY,
        issuer_capability="governance.recovery.envelope.v1",
        portfolio_gross_cap=Decimal("0.02"),
        recovery_inherited_risk_version=2,
        recovery_open_pending_risk_version=2,
        recovery_stage_program_loss_consumption_version=2,
        risk_epoch_started_hash=HASH,
        recovery_manifest_hash=HASH,
        **(predecessor | {"predecessor_active_edge_grant_certificate_hashes": (HASH,)}),
    )
    CapitalAuthorizationEnvelope.model_validate(recovery)
    with pytest.raises(ValidationError):
        CapitalAuthorizationEnvelope.model_validate(
            recovery | {"target_portfolio_policy_fingerprint": "f" * 64}
        )
