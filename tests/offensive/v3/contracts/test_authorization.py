"""Contract tests for edge and one-shot exploration authorizations."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError


UTC = timezone.utc
HASH = "b" * 64


def _contracts():
    try:
        from src.screening.offensive.v3.contracts.authorization import (
            CapitalAuthorization,
            EdgeAuthorization,
            ExplorationAuthorization,
        )
        from src.screening.offensive.v3.contracts.evidence import SUPPORTED_SCHEMA_MAJOR
    except ModuleNotFoundError:
        pytest.fail("authorization contracts are not implemented", pytrace=False)
    return SUPPORTED_SCHEMA_MAJOR, CapitalAuthorization, EdgeAuthorization, ExplorationAuthorization


def _base(**overrides):
    from src.screening.offensive.v3.contracts.base import (
        EvidenceScope,
        ExecutionMode,
    )

    payload = {
        "evidence_id": "auth-001",
        "subject_scope": EvidenceScope.STRATEGY_LINEAGE,
        "subject_producer": "btst",
        "family_id": "btst.limit-up-breakout",
        "strategy_semver": "3.0.0",
        "behavior_fingerprint": HASH,
        "policy_epoch": 3,
        "execution_version": "t1-open-t10-open.v1",
        "cost_version": "cn-a-share-costs.v1",
        "effective_at": datetime(2026, 7, 19, 8, 0, tzinfo=UTC),
        "observed_at": datetime(2026, 7, 19, 8, 1, tzinfo=UTC),
        "available_at": datetime(2026, 7, 19, 8, 2, tzinfo=UTC),
        "mode": ExecutionMode.BROKER_CONFIRMED,
        "source_authority": "edge-authorizer",
        "payload_content_hash": HASH,
        "schema_major": 1,
    }
    payload.update(overrides)
    return payload


def _edge(**overrides):
    payload = _base() | {
        "authorization_kind": "edge",
        "authorization_version": 4,
        "economic_lineage_id": "btst-economic-lineage",
        "research_program_id": "growth-program",
        "baseline_portfolio_policy_fingerprint": HASH,
        "target_portfolio_policy_fingerprint": HASH,
        "evidence_as_of": datetime(2026, 7, 19, 7, 55, tzinfo=UTC),
        "evidence_set_merkle_root": HASH,
        "issued_at": datetime(2026, 7, 19, 8, 3, tzinfo=UTC),
        "expires_at": datetime(2026, 8, 19, 8, 3, tzinfo=UTC),
        "max_capital_tier": 5,
        "issuer_id": "authorizer-service",
        "issuer_capability": "edge.authorization.issue.v1",
        "trial_id": "trial-2026-001",
        "trial_manifest_hash": HASH,
        "statistical_analysis_plan_hash": HASH,
        "assessment_result_hash": HASH,
        "attempt_ledger_checkpoint_hash": HASH,
        "alpha_sample_consumption_id": "sample-consumption-001",
        "authorization_payload_hash": HASH,
    }
    payload.update(overrides)
    return payload


def _exploration(**overrides):
    payload = _base(source_authority="growth-governance") | {
        "authorization_kind": "exploration",
        "authorization_version": 1,
        "economic_lineage_id": "btst-economic-lineage",
        "research_program_id": "growth-program",
        "portfolio_id": "paper-v3",
        "evidence_set_merkle_root": HASH,
        "issued_at": datetime(2026, 7, 19, 8, 3, tzinfo=UTC),
        "expires_at": datetime(2026, 8, 2, 8, 3, tzinfo=UTC),
        "max_capital_tier": 2,
        "portfolio_gross_risk_cap": Decimal("0.02"),
        "stress_loss_budget": Decimal("1000.00"),
        "issuer_id": "governance-service",
        "issuer_capability": "exploration.authorization.issue.v1",
        "trial_id": "explore-2026-001",
        "trial_manifest_hash": HASH,
        "one_shot": True,
    }
    payload.update(overrides)
    return payload


def test_edge_authorization_binds_every_required_assessment_field() -> None:
    major, _, edge, _ = _contracts()
    item = edge.model_validate(_edge(schema_major=major))

    required = {
        "economic_lineage_id",
        "research_program_id",
        "baseline_portfolio_policy_fingerprint",
        "target_portfolio_policy_fingerprint",
        "evidence_as_of",
        "evidence_set_merkle_root",
        "issued_at",
        "expires_at",
        "max_capital_tier",
        "issuer_id",
        "issuer_capability",
        "trial_id",
        "trial_manifest_hash",
        "statistical_analysis_plan_hash",
        "assessment_result_hash",
        "attempt_ledger_checkpoint_hash",
        "alpha_sample_consumption_id",
        "authorization_payload_hash",
        "authorization_version",
    }
    assert required <= set(edge.model_fields)


@pytest.mark.parametrize("tier", [2, 5, 10])
def test_edge_authorization_allows_only_governed_capital_tiers(tier) -> None:
    major, _, edge, _ = _contracts()
    assert edge.model_validate(_edge(schema_major=major, max_capital_tier=tier)).max_capital_tier == tier


@pytest.mark.parametrize("tier", [0, 3, 20])
def test_edge_authorization_rejects_ungoverned_capital_tiers(tier) -> None:
    major, _, edge, _ = _contracts()
    with pytest.raises(ValidationError):
        edge.model_validate(_edge(schema_major=major, max_capital_tier=tier))


def test_research_reconstruction_cannot_receive_capital_authorization() -> None:
    from src.screening.offensive.v3.contracts.base import ExecutionMode

    major, _, edge, exploration = _contracts()
    with pytest.raises(ValidationError, match="research reconstruction"):
        edge.model_validate(
            _edge(schema_major=major, mode=ExecutionMode.RESEARCH_RECONSTRUCTION)
        )
    with pytest.raises(ValidationError):
        exploration.model_validate(
            _exploration(
                schema_major=major,
                mode=ExecutionMode.RESEARCH_RECONSTRUCTION,
            )
        )


def test_exploration_is_broker_confirmed_one_shot_and_exactly_two_percent() -> None:
    from src.screening.offensive.v3.contracts.base import ExecutionMode

    major, _, _, exploration = _contracts()
    item = exploration.model_validate(_exploration(schema_major=major))
    assert item.mode is ExecutionMode.BROKER_CONFIRMED
    assert item.max_capital_tier == 2
    assert item.one_shot is True

    for override in (
        {"mode": ExecutionMode.MANUAL_CONFIRMED},
        {"max_capital_tier": 5},
        {"one_shot": False},
    ):
        with pytest.raises(ValidationError):
            exploration.model_validate(_exploration(schema_major=major, **override))


def test_authorizations_require_a_bounded_validity_window() -> None:
    major, _, edge, exploration = _contracts()
    issued = datetime(2026, 7, 19, 8, 3, tzinfo=UTC)
    for model, payload in (
        (edge, _edge(schema_major=major, expires_at=issued)),
        (exploration, _exploration(schema_major=major, expires_at=issued)),
    ):
        with pytest.raises(ValidationError, match="expires_at"):
            model.model_validate(payload)


def test_capital_authorization_is_a_discriminated_union() -> None:
    major, union, edge, exploration = _contracts()
    parsed_edge = union.model_validate(_edge(schema_major=major)).root
    parsed_exploration = union.model_validate(_exploration(schema_major=major)).root

    assert isinstance(parsed_edge, edge)
    assert isinstance(parsed_exploration, exploration)
    with pytest.raises(ValidationError):
        union.model_validate(_edge(schema_major=major, authorization_kind="exploration"))
