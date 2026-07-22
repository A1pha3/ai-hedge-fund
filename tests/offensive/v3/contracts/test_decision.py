"""Contract tests for plan evidence, decisions, seals, and permits."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import subprocess
import sys

import pytest
from pydantic import ValidationError


UTC = timezone.utc
HASH = "c" * 64


def _contracts():
    try:
        from src.screening.offensive.v3.contracts.decision import (
            DecisionSeal,
            DecisionLogicalKey,
            ExecutionPermit,
            PlanEvidence,
            SealedOrderLine,
            ShadowDecision,
        )
    except ModuleNotFoundError:
        pytest.fail("decision contracts are not implemented", pytrace=False)
    return (
        PlanEvidence,
        ShadowDecision,
        DecisionSeal,
        ExecutionPermit,
        DecisionLogicalKey,
        SealedOrderLine,
    )


def _envelope_fields(**overrides):
    from src.screening.offensive.v3.contracts.base import (
        EvidenceScope,
        ExecutionMode,
    )

    payload = {
        "evidence_id": "decision-evidence-001",
        "subject_scope": EvidenceScope.STRATEGY_LINEAGE,
        "subject_producer": "btst",
        "family_id": "btst.limit-up-breakout",
        "strategy_semver": "3.0.0",
        "behavior_fingerprint": HASH,
        "policy_epoch": 3,
        "execution_version": "t1-open-t10-open.v1",
        "cost_version": "cn-a-share-costs.v1",
        "effective_at": datetime(2026, 7, 19, 8, 5, tzinfo=UTC),
        "observed_at": datetime(2026, 7, 19, 8, 6, tzinfo=UTC),
        "available_at": datetime(2026, 7, 19, 8, 7, tzinfo=UTC),
        "mode": ExecutionMode.BROKER_CONFIRMED,
        "source_authority": "growth-kernel",
        "payload_content_hash": HASH,
        "schema_major": 1,
    }
    payload.update(overrides)
    return payload


def _plan(**overrides):
    payload = _envelope_fields(evidence_id="plan-001") | {
        "evidence_kind": "plan",
        "portfolio_id": "paper-v3",
        "signal_session": date(2026, 7, 19),
        "economic_lineage_id": "btst-economic-lineage",
        "snapshot_id": "snapshot-001",
        "raw_target_fraction": Decimal("0.05"),
        "created_at": datetime(2026, 7, 19, 8, 10, tzinfo=UTC),
    }
    payload.update(overrides)
    return payload


def _order_line(**overrides):
    payload = {
        "order_line_id": "line-600000-entry",
        "security_id": "600000.SH",
        "order_action": "entry",
        "entry_session": date(2026, 7, 20),
        "exit_session_ordinal": 10,
        "exit_policy_version": "t10-open.v1",
        "sealed_quantity": 1000,
        "lot_rule_version": "cn-board-lot.v1",
        "order_type": "limit",
        "limit_price": Decimal("10.50"),
        "worst_case_price": Decimal("10.50"),
        "price_boundary_version": "exchange-limit.v1",
        "time_in_force": "opening-auction",
        "worst_case_fee_reserve": Decimal("25.00"),
        "worst_case_cash_reserve": Decimal("10525.00"),
    }
    payload.update(overrides)
    return payload


def _seal(**overrides):
    _, _, _, _, logical_key, _ = _contracts()
    payload = _envelope_fields(evidence_id="seal-001-r1") | {
        "decision_kind": "decision_seal",
        "seal_id": "seal-001-r1",
        "active_seal_id": "seal-001-r1",
        "seal_revision": 1,
        "portfolio_id": "paper-v3",
        "signal_session": date(2026, 7, 19),
        "economic_lineage_id": "btst-economic-lineage",
        "snapshot_id": "snapshot-001",
        "capital_authorization_id": "auth-001",
        "authorization_version": 4,
        "command_binding": {
            "publish_command_content_hash": "d" * 64,
            "portfolio_id": "paper-v3",
            "capital_snapshot_id": "capital-019",
            "capital_version": 19,
            "capital_stream_version": 29,
            "capital_payload_content_hash": HASH,
            "target_portfolio_policy_fingerprint": "1" * 64,
            "capital_authorization_id": "auth-001",
            "authorization_version": 4,
            "evidence_set_merkle_root": HASH,
            "family_id": "btst.limit-up-breakout",
            "economic_lineage_id": "btst-economic-lineage",
            "mode": _envelope_fields()["mode"],
            "authority_epoch": 3,
            "risk_epoch": 8,
        },
        "evidence_set_merkle_root": HASH,
        "authority_epoch": 3,
        "risk_epoch": 8,
        "order_lines": (_order_line(),),
        "created_at": datetime(2026, 7, 19, 8, 10, tzinfo=UTC),
        "deadline": datetime(2026, 7, 19, 8, 20, tzinfo=UTC),
        "idempotency_key": logical_key(
            portfolio_id="paper-v3",
            signal_session=date(2026, 7, 19),
            authority_epoch=3,
        ),
    }
    payload.update(overrides)
    return payload


def _shadow(**overrides):
    payload = _seal() | {
        "decision_kind": "shadow_decision",
        "shadow_decision_id": "shadow-001",
        "gateway_acceptable": False,
    }
    payload.pop("seal_id")
    payload.pop("active_seal_id")
    payload.pop("seal_revision")
    payload.pop("capital_authorization_id")
    payload.pop("authorization_version")
    payload.pop("command_binding")
    payload.update(overrides)
    return payload


def _permit(**overrides):
    from src.screening.offensive.v3.contracts.base import ExecutionMode

    payload = {
        "permit_id": "permit-001",
        "active_seal_id": "seal-001-r1",
        "seal_revision": 1,
        "order_line_id": "line-600000-entry",
        "capital_authorization_id": "auth-001",
        "authorization_version": 4,
        "evidence_set_merkle_root": HASH,
        "mode": ExecutionMode.BROKER_CONFIRMED,
        "sealed_mode": ExecutionMode.BROKER_CONFIRMED,
        "capital_authorization_mode": ExecutionMode.BROKER_CONFIRMED,
        "permitted_quantity": 700,
        "sealed_quantity": 1000,
        "capital_version": 19,
        "risk_snapshot_id": "risk-019",
        "fencing_epoch": 5,
        "permit_nonce": "nonce-001",
        "deadline": datetime(2026, 7, 19, 8, 25, tzinfo=UTC),
    }
    payload.update(overrides)
    return payload


def test_plan_evidence_is_immutable_raw_target_not_an_authorization() -> None:
    plan, *_ = _contracts()
    item = plan.model_validate(_plan())
    assert item.raw_target_fraction == Decimal("0.05")
    assert item.economic_lineage_id == "btst-economic-lineage"
    assert {
        "evidence_id",
        "subject_scope",
        "policy_epoch",
        "execution_version",
        "cost_version",
        "effective_at",
        "observed_at",
        "available_at",
        "source_authority",
        "schema_major",
    } <= set(plan.model_fields)
    with pytest.raises(ValidationError, match="extra_forbidden"):
        plan.model_validate(_plan(execution_authorized=True))
    with pytest.raises(ValidationError, match="frozen_instance"):
        item.raw_target_fraction = Decimal("0.10")


def test_plan_identity_requires_strategy_scope_and_distinct_family_lineage() -> None:
    from src.screening.offensive.v3.contracts.base import EvidenceScope

    plan, *_ = _contracts()
    with pytest.raises(ValidationError, match="strategy-lineage"):
        plan.model_validate(
            _plan(subject_scope=EvidenceScope.GLOBAL, family_id=None)
        )
    with pytest.raises(ValidationError, match="family.*lineage|lineage.*family"):
        plan.model_validate(_plan(family_id="btst-economic-lineage"))


def test_decision_seal_has_exact_execution_and_authority_bindings() -> None:
    _, _, seal, _, _, _ = _contracts()
    item = seal.model_validate(_seal())

    assert set(seal.model_fields) == {
        "evidence_id",
        "subject_scope",
        "decision_kind",
        "seal_id",
        "active_seal_id",
        "seal_revision",
        "portfolio_id",
        "signal_session",
        "economic_lineage_id",
        "subject_producer",
        "family_id",
        "strategy_semver",
        "behavior_fingerprint",
        "policy_epoch",
        "execution_version",
        "cost_version",
        "effective_at",
        "observed_at",
        "available_at",
        "snapshot_id",
        "mode",
        "source_authority",
        "schema_major",
        "capital_authorization_id",
        "authorization_version",
        "command_binding",
        "evidence_set_merkle_root",
        "authority_epoch",
        "risk_epoch",
        "order_lines",
        "created_at",
        "deadline",
        "idempotency_key",
        "payload_content_hash",
    }
    assert item.active_seal_id == item.seal_id
    assert item.order_lines[0].security_id == "600000.SH"
    assert item.order_lines[0].exit_session_ordinal == 10


def test_shadow_and_seal_have_non_interchangeable_discriminators() -> None:
    _, shadow, seal, _, _, _ = _contracts()
    shadow_payload = _shadow()
    seal_payload = _seal()

    assert shadow.model_validate(shadow_payload).gateway_acceptable is False
    with pytest.raises(ValidationError):
        seal.model_validate(shadow_payload)
    with pytest.raises(ValidationError):
        shadow.model_validate(seal_payload)

    with pytest.raises(ValidationError, match="cash reserve"):
        shadow.model_validate(
            _shadow(
                order_lines=(
                    _order_line(worst_case_cash_reserve=Decimal("0")),
                )
            )
        )


@pytest.mark.parametrize("payload_factory", [_seal, _shadow])
def test_direct_decision_projection_requires_strategy_lineage_scope(
    payload_factory,
) -> None:
    from src.screening.offensive.v3.contracts.base import EvidenceScope

    _, shadow, seal, _, _, _ = _contracts()
    model = seal if payload_factory is _seal else shadow
    with pytest.raises(ValidationError, match="strategy-lineage"):
        model.model_validate(
            payload_factory(
                subject_scope=EvidenceScope.GLOBAL,
                family_id=None,
            )
        )


@pytest.mark.parametrize("payload_factory", [_seal, _shadow])
def test_direct_decision_projection_keeps_family_and_lineage_distinct(
    payload_factory,
) -> None:
    _, shadow, seal, _, _, _ = _contracts()
    model = seal if payload_factory is _seal else shadow
    payload = payload_factory(
        family_id="btst-economic-lineage",
        economic_lineage_id="btst-economic-lineage",
    )
    if payload_factory is _seal:
        payload["command_binding"] = payload["command_binding"] | {
            "family_id": "btst-economic-lineage"
        }
    with pytest.raises(ValidationError, match="family.*lineage|lineage.*family"):
        model.model_validate(payload)


def test_seal_requires_positive_integer_quantity_reserves_and_ordered_deadline() -> None:
    from src.screening.offensive.v3.contracts.base import ExecutionMode

    _, _, seal, _, logical_key, _ = _contracts()
    for override in (
        {"order_lines": (_order_line(sealed_quantity=0),)},
        {"order_lines": (_order_line(sealed_quantity=True),)},
        {
            "order_lines": (
                _order_line(worst_case_fee_reserve=Decimal("-0.01")),
            )
        },
        {
            "order_lines": (
                _order_line(worst_case_cash_reserve=Decimal("-0.01")),
            )
        },
        {"deadline": datetime(2026, 7, 19, 8, 9, tzinfo=UTC)},
        {"active_seal_id": "another-seal"},
        {"mode": ExecutionMode.RESEARCH_RECONSTRUCTION},
        {
            "idempotency_key": logical_key(
                portfolio_id="another-portfolio",
                signal_session=date(2026, 7, 19),
                authority_epoch=3,
            )
        },
    ):
        with pytest.raises(ValidationError):
            seal.model_validate(_seal(**override))


@pytest.mark.parametrize("payload_factory", [_seal, _shadow])
def test_decision_projection_cannot_precede_evidence_availability(
    payload_factory,
) -> None:
    _, shadow, seal, _, _, _ = _contracts()
    model = seal if payload_factory is _seal else shadow
    created = datetime(2026, 7, 19, 8, 10, tzinfo=UTC)

    assert model.model_validate(
        payload_factory(available_at=created, created_at=created)
    ).created_at == created
    with pytest.raises(ValidationError, match="available_at|created_at"):
        model.model_validate(
            payload_factory(
                available_at=created + timedelta(microseconds=1),
                created_at=created,
            )
        )


def test_execution_permit_binds_authorization_and_only_shrinks_sealed_quantity() -> None:
    from src.screening.offensive.v3.contracts.base import ExecutionMode

    _, _, _, permit, _, _ = _contracts()
    item = permit.model_validate(_permit())
    assert item.capital_authorization_id == "auth-001"
    assert item.authorization_version == 4
    assert item.evidence_set_merkle_root == HASH
    assert item.order_line_id == "line-600000-entry"
    assert item.mode is ExecutionMode.BROKER_CONFIRMED
    assert item.mode is item.sealed_mode is item.capital_authorization_mode
    assert item.permitted_quantity < item.sealed_quantity

    for quantity in (-1, 1001, True):
        with pytest.raises(ValidationError, match="shrink|integer|greater than"):
            permit.model_validate(_permit(permitted_quantity=quantity))

    for override in (
        {"sealed_mode": ExecutionMode.MANUAL_CONFIRMED},
        {"capital_authorization_mode": ExecutionMode.DAILY_BAR_PROXY},
        {"mode": "broker_confirmed"},
    ):
        with pytest.raises(ValidationError, match="mode|ExecutionMode"):
            permit.model_validate(_permit(**override))


def test_zero_quantity_permit_is_an_explicit_cancellation() -> None:
    _, _, _, permit, _, _ = _contracts()
    assert permit.model_validate(_permit(permitted_quantity=0)).permitted_quantity == 0


def test_serialized_seal_hash_is_stable_across_processes() -> None:
    _, _, seal, _, _, _ = _contracts()
    fixture_json = seal.model_validate(_seal()).model_dump_json()
    script = (
        "from src.screening.offensive.v3.contracts.decision import DecisionSeal;"
        f"print(DecisionSeal.model_validate_json({fixture_json!r}).content_hash())"
    )

    hashes = [
        subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        for _ in range(2)
    ]

    assert (
        hashes[0]
        == hashes[1]
        == "e1ed11871df00c9785fffcf1d51eb34648e31e5de02965de522b4ed70cfecc4d"
    )
