"""Stable, storage-free port contracts for later v3 implementation plans."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import inspect
from typing import get_type_hints

import pytest
from pydantic import ValidationError


UTC = timezone.utc
NOW = datetime(2026, 7, 19, 8, 0, tzinfo=UTC)
HASH = "e" * 64


def _api():
    try:
        from src.screening.offensive.v3 import contracts
    except ImportError as exc:
        pytest.fail(f"stable v3 ports are not implemented: {exc}", pytrace=False)
    required = {
        "CapitalAuthorizationBinding",
        "CapitalViewPort",
        "CapabilityVerifier",
        "DecisionInput",
        "EvidenceQueryPort",
        "PublishDecisionCommand",
        "SealWriterPort",
    }
    missing = sorted(required - set(dir(contracts)))
    if missing:
        pytest.fail(f"stable v3 ports are not implemented: {missing}", pytrace=False)
    return contracts


def _plan(api, **overrides):
    values = {
        "evidence_id": "plan-001",
        "subject_scope": api.EvidenceScope.STRATEGY_LINEAGE,
        "subject_producer": "btst",
        "family_id": "btst.limit-up-breakout",
        "strategy_semver": "3.0.0",
        "behavior_fingerprint": HASH,
        "policy_epoch": 3,
        "execution_version": "t1-open-t10-open.v1",
        "cost_version": "cn-a-share-costs.v1",
        "effective_at": NOW,
        "observed_at": NOW,
        "available_at": NOW,
        "mode": api.ExecutionMode.DAILY_BAR_PROXY,
        "source_authority": "btst-producer",
        "payload_content_hash": HASH,
        "schema_major": 1,
        "evidence_kind": "plan",
        "portfolio_id": "paper-v3",
        "signal_session": date(2026, 7, 19),
        "economic_lineage_id": "btst-economic-lineage",
        "snapshot_id": "snapshot-001",
        "raw_target_fraction": Decimal("0.02"),
        "created_at": NOW,
    }
    values.update(overrides)
    return api.PlanEvidence(**values)


def _order_line(api):
    return api.SealedOrderLine(
        order_line_id="line-600000-entry",
        security_id="600000.SH",
        order_action="entry",
        entry_session=date(2026, 7, 20),
        exit_session_ordinal=10,
        exit_policy_version="t10-open.v1",
        sealed_quantity=100,
        lot_rule_version="cn-board-lot.v1",
        order_type="limit",
        limit_price=Decimal("10.50"),
        worst_case_price=Decimal("10.50"),
        price_boundary_version="exchange-limit.v1",
        time_in_force="opening-auction",
        worst_case_fee_reserve=Decimal("5"),
        worst_case_cash_reserve=Decimal("1055"),
    )


def _decision_input(api, **overrides):
    values = {
        "plan_evidence": _plan(api),
        "evidence_set_merkle_root": HASH,
        "authority_epoch": 3,
        "risk_epoch": 8,
        "order_lines": (_order_line(api),),
        "created_at": NOW,
        "deadline": datetime(2026, 7, 19, 8, 20, tzinfo=UTC),
        "idempotency_key": api.DecisionLogicalKey(
            portfolio_id="paper-v3",
            signal_session=date(2026, 7, 19),
            authority_epoch=3,
        ),
    }
    values.update(overrides)
    return api.DecisionInput(**values)


def _binding(api, **overrides):
    values = {
        "capital_authorization_id": "auth-001",
        "authorization_version": 4,
        "evidence_set_merkle_root": HASH,
        "economic_lineage_id": "btst-economic-lineage",
        "mode": api.ExecutionMode.DAILY_BAR_PROXY,
    }
    values.update(overrides)
    return api.CapitalAuthorizationBinding(**values)


def _capital_snapshot(api):
    return api.CapitalSnapshot(
        capital_snapshot_id="capital-019",
        portfolio_id="paper-v3",
        authority_epoch=3,
        risk_epoch=8,
        capital_version=19,
        stream_version=29,
        mode=api.ExecutionMode.DAILY_BAR_PROXY,
        as_of=NOW,
        cash=Decimal("50000"),
        nav=Decimal("100000"),
        gross_exposure=Decimal("0"),
        high_water_mark=Decimal("100000"),
        positions=(),
        payload_content_hash=HASH,
    )


def _snapshot_evidence(api):
    return api.SnapshotEvidence(
        evidence_id="snapshot-001",
        subject_scope=api.EvidenceScope.GLOBAL,
        subject_producer="market-publisher",
        family_id=None,
        strategy_semver="3.0.0",
        behavior_fingerprint=HASH,
        policy_epoch=3,
        execution_version="t1-open-t10-open.v1",
        cost_version="cn-a-share-costs.v1",
        effective_at=NOW,
        observed_at=NOW,
        available_at=NOW,
        mode=api.ExecutionMode.DAILY_BAR_PROXY,
        source_authority="market-publisher",
        payload_content_hash=HASH,
        schema_major=1,
        evidence_kind="snapshot",
    )


def _authorization(api):
    return api.CapitalAuthorization(
        root=api.EdgeAuthorization(
            evidence_id="auth-001",
            subject_scope=api.EvidenceScope.STRATEGY_LINEAGE,
            subject_producer="authorizer",
            family_id="btst.limit-up-breakout",
            strategy_semver="3.0.0",
            behavior_fingerprint=HASH,
            policy_epoch=3,
            execution_version="t1-open-t10-open.v1",
            cost_version="cn-a-share-costs.v1",
            effective_at=NOW,
            observed_at=NOW,
            available_at=NOW,
            mode=api.ExecutionMode.DAILY_BAR_PROXY,
            source_authority="authorizer",
            payload_content_hash=HASH,
            schema_major=1,
            authorization_kind="edge",
            authorization_version=4,
            economic_lineage_id="btst-economic-lineage",
            research_program_id="program-001",
            baseline_portfolio_policy_fingerprint=HASH,
            target_portfolio_policy_fingerprint=HASH,
            evidence_as_of=NOW,
            evidence_set_merkle_root=HASH,
            issued_at=NOW,
            expires_at=datetime(2026, 7, 20, 8, 0, tzinfo=UTC),
            max_capital_tier=2,
            issuer_id="authorizer.service",
            issuer_capability="capital.edge.btst",
            trial_id="trial-001",
            trial_manifest_hash=HASH,
            statistical_analysis_plan_hash=HASH,
            assessment_result_hash=HASH,
            attempt_ledger_checkpoint_hash=HASH,
            alpha_sample_consumption_id="consumption-001",
            authorization_payload_hash=HASH,
        )
    )


def _seal(api):
    command = api.PublishDecisionCommand(
        decision=_decision_input(api),
        authorization=_binding(api),
    )
    plan = command.decision.plan_evidence
    return api.DecisionSeal(
        **plan.model_dump(
            mode="python",
            exclude={
                "evidence_id",
                "evidence_kind",
                "raw_target_fraction",
                "source_authority",
            },
        ),
        evidence_id="seal-001-r1",
        source_authority="growth-kernel",
        decision_kind="decision_seal",
        seal_id="seal-001-r1",
        active_seal_id="seal-001-r1",
        seal_revision=1,
        capital_authorization_id=command.authorization.capital_authorization_id,
        authorization_version=command.authorization.authorization_version,
        evidence_set_merkle_root=command.decision.evidence_set_merkle_root,
        authority_epoch=command.decision.authority_epoch,
        risk_epoch=command.decision.risk_epoch,
        order_lines=command.decision.order_lines,
        deadline=command.decision.deadline,
        idempotency_key=command.decision.idempotency_key,
    )


def test_publish_command_is_immutable_input_plus_reference_not_authority_or_seal() -> None:
    api = _api()
    command = api.PublishDecisionCommand(
        decision=_decision_input(api),
        authorization=_binding(api),
    )

    assert set(api.PublishDecisionCommand.model_fields) == {
        "decision",
        "authorization",
    }
    assert set(api.CapitalAuthorizationBinding.model_fields) == {
        "capital_authorization_id",
        "authorization_version",
        "evidence_set_merkle_root",
        "economic_lineage_id",
        "mode",
    }
    assert {
        "seal_id",
        "active_seal_id",
        "seal_revision",
        "signature",
        "private_key",
        "execution_authorized",
    }.isdisjoint(api.PublishDecisionCommand.model_fields)
    assert command.decision.order_lines[0].sealed_quantity == 100
    with pytest.raises(ValidationError, match="frozen_instance"):
        command.authorization = _binding(api)
    with pytest.raises(ValidationError, match="extra_forbidden"):
        api.PublishDecisionCommand(
            decision=_decision_input(api),
            authorization=_binding(api),
            execution_authorized=True,
        )


@pytest.mark.parametrize(
    ("decision_overrides", "binding_overrides", "message"),
    [
        ({}, {"mode": None}, "mode"),
        ({}, {"economic_lineage_id": "auto-lineage"}, "lineage"),
        ({}, {"evidence_set_merkle_root": "f" * 64}, "evidence"),
    ],
)
def test_publish_command_requires_exact_authorization_binding(
    decision_overrides, binding_overrides, message
) -> None:
    api = _api()
    if "mode" in binding_overrides and binding_overrides["mode"] is None:
        binding_overrides["mode"] = api.ExecutionMode.MANUAL_CONFIRMED
    with pytest.raises(ValidationError, match=message):
        api.PublishDecisionCommand(
            decision=_decision_input(api, **decision_overrides),
            authorization=_binding(api, **binding_overrides),
        )


def test_publish_command_rejects_research_and_mismatched_logical_key() -> None:
    api = _api()
    research_plan = _plan(api, mode=api.ExecutionMode.RESEARCH_RECONSTRUCTION)
    with pytest.raises(ValidationError, match="research"):
        api.PublishDecisionCommand(
            decision=_decision_input(api, plan_evidence=research_plan),
            authorization=_binding(
                api,
                mode=api.ExecutionMode.RESEARCH_RECONSTRUCTION,
            ),
        )

    wrong_key = api.DecisionLogicalKey(
        portfolio_id="other-portfolio",
        signal_session=date(2026, 7, 19),
        authority_epoch=3,
    )
    with pytest.raises(ValidationError, match="idempotency"):
        api.DecisionInput(
            **_decision_input(api).model_dump(
                mode="python",
                exclude={"idempotency_key"},
            ),
            idempotency_key=wrong_key,
        )


def test_stable_ports_are_runtime_structural_and_return_domain_objects() -> None:
    api = _api()
    capital = _capital_snapshot(api)
    snapshot = _snapshot_evidence(api)
    authorization = _authorization(api)
    seal = _seal(api)

    class CapitalView:
        def snapshot(self, portfolio_id: str, as_of: datetime) -> api.CapitalSnapshot:
            assert portfolio_id == capital.portfolio_id
            assert as_of == capital.as_of
            return capital

    class EvidenceQuery:
        def snapshot(self, evidence_id: str) -> api.SnapshotEvidence:
            assert evidence_id == snapshot.evidence_id
            return snapshot

        def authorization(self, authorization_id: str) -> api.CapitalAuthorization:
            assert authorization_id == authorization.root.evidence_id
            return authorization

    class SealWriter:
        def publish(self, command: api.PublishDecisionCommand) -> api.DecisionSeal:
            assert command.authorization.capital_authorization_id == "auth-001"
            return seal

    assert isinstance(CapitalView(), api.CapitalViewPort)
    assert isinstance(EvidenceQuery(), api.EvidenceQueryPort)
    assert isinstance(SealWriter(), api.SealWriterPort)
    assert CapitalView().snapshot("paper-v3", NOW) is capital
    assert EvidenceQuery().snapshot("snapshot-001") is snapshot
    assert EvidenceQuery().authorization("auth-001") is authorization
    assert SealWriter().publish(
        api.PublishDecisionCommand(
            decision=_decision_input(api),
            authorization=_binding(api),
        )
    ) is seal


def test_capability_verifier_port_preserves_explicit_verification_time() -> None:
    api = _api()
    from src.screening.offensive.v3 import trust

    class Verifier:
        def verify(
            self,
            signed: trust.SignedEnvelope,
            required: trust.Capability,
            *,
            verification_time: datetime,
        ) -> trust.VerifiedIssuer:
            raise NotImplementedError

    assert isinstance(Verifier(), api.CapabilityVerifier)
    signature = inspect.signature(api.CapabilityVerifier.verify)
    assert list(signature.parameters) == [
        "self",
        "signed",
        "required",
        "verification_time",
    ]
    assert signature.parameters["verification_time"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["verification_time"].default is inspect.Parameter.empty


def test_stable_port_annotations_are_exact_and_contain_no_mutable_or_any_boundary() -> None:
    api = _api()
    expected = {
        api.CapitalViewPort.snapshot: {
            "portfolio_id": str,
            "as_of": datetime,
            "return": api.CapitalSnapshot,
        },
        api.EvidenceQueryPort.snapshot: {
            "evidence_id": str,
            "return": api.SnapshotEvidence,
        },
        api.EvidenceQueryPort.authorization: {
            "authorization_id": str,
            "return": api.CapitalAuthorization,
        },
        api.SealWriterPort.publish: {
            "command": api.PublishDecisionCommand,
            "return": api.DecisionSeal,
        },
    }
    for method, expected_annotations in expected.items():
        assert get_type_hints(method) == expected_annotations
        rendered = " ".join(str(value) for value in expected_annotations.values())
        assert not any(
            forbidden in rendered
            for forbidden in (
                "typing.Any",
                "dict",
                "list",
                "set",
                "Mapping",
                "DataFrame",
                "Connection",
                "Session",
                "Cursor",
            )
        )
