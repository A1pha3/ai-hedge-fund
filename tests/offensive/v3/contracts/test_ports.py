"""Stable, storage-free port contracts for later v3 implementation plans."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import inspect
from typing import Any, get_args, get_origin, get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError


UTC = timezone.utc
NOW = datetime(2026, 7, 19, 8, 0, tzinfo=UTC)
HASH = "e" * 64
POLICY_HASH = "1" * 64


def _api():
    try:
        from src.screening.offensive.v3.contracts import revision1
    except ImportError as exc:
        pytest.fail(
            f"Revision 1 compatibility contracts are not isolated: {exc}",
            pytrace=False,
        )
    required = {
        "CapitalAuthorizationBinding",
        "CapitalViewPort",
        "CapabilityVerifier",
        "DecisionInput",
        "EvidenceQueryPort",
        "PublishDecisionCommand",
        "SealWriterPort",
    }
    missing = sorted(required - set(dir(revision1)))
    if missing:
        pytest.fail(
            f"Revision 1 compatibility contracts are incomplete: {missing}",
            pytrace=False,
        )
    return revision1


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
        "capital_snapshot": _capital_snapshot(api),
        "target_portfolio_policy_fingerprint": POLICY_HASH,
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
        "family_id": "btst.limit-up-breakout",
        "mode": api.ExecutionMode.DAILY_BAR_PROXY,
        "target_portfolio_policy_fingerprint": POLICY_HASH,
    }
    values.update(overrides)
    return api.CapitalAuthorizationBinding(**values)


def _capital_snapshot(api, **overrides):
    values = {
        "capital_snapshot_id": "capital-019",
        "portfolio_id": "paper-v3",
        "authority_epoch": 3,
        "risk_epoch": 8,
        "capital_version": 19,
        "stream_version": 29,
        "mode": api.ExecutionMode.DAILY_BAR_PROXY,
        "as_of": NOW,
        "cash": Decimal("50000"),
        "nav": Decimal("100000"),
        "gross_exposure": Decimal("0"),
        "high_water_mark": Decimal("100000"),
        "positions": (),
        "payload_content_hash": HASH,
    }
    values.update(overrides)
    return api.CapitalSnapshot(**values)


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
    edge = api.EdgeAuthorization(
        evidence_id="auth-001",
        subject_scope=api.EvidenceScope.STRATEGY_LINEAGE,
        subject_producer="btst",
        family_id="btst.limit-up-breakout",
        strategy_semver="3.0.0",
        behavior_fingerprint=HASH,
        policy_epoch=3,
        execution_version="t1-open-t10-open.v1",
        cost_version="cost-v1",
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
        target_portfolio_policy_fingerprint=POLICY_HASH,
        evidence_as_of=NOW,
        evidence_set_merkle_root=HASH,
        issued_at=NOW,
        expires_at=datetime(2026, 7, 20, 8, tzinfo=UTC),
        max_capital_tier=2,
        issuer_id="authorizer.service",
        issuer_capability="authorizer.edge.envelope.v1",
        trial_id="trial-1",
        trial_manifest_hash=HASH,
        statistical_analysis_plan_hash=HASH,
        assessment_result_hash=HASH,
        attempt_ledger_checkpoint_hash=HASH,
        alpha_sample_consumption_id="sample-1",
        authorization_payload_hash=HASH,
    )
    return api.CapitalAuthorization(root=edge)


def _seal(api):
    command = api.PublishDecisionCommand(
        decision=_decision_input(api),
        authorization=_binding(api),
    )
    return api.DecisionSeal.from_command(
        command,
        evidence_id="seal-001-r1",
        seal_id="seal-001-r1",
        seal_revision=1,
        source_authority="growth-kernel",
        payload_content_hash="9" * 64,
    )


def test_publish_command_is_immutable_input_plus_reference_not_authority_or_seal() -> (
    None
):
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
        "family_id",
        "mode",
        "target_portfolio_policy_fingerprint",
    }
    assert set(api.DecisionInput.model_fields) == {
        "plan_evidence",
        "capital_snapshot",
        "target_portfolio_policy_fingerprint",
        "evidence_set_merkle_root",
        "authority_epoch",
        "risk_epoch",
        "order_lines",
        "created_at",
        "deadline",
        "idempotency_key",
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
        ({}, {"family_id": "auto.family"}, "family"),
        ({}, {"evidence_set_merkle_root": "f" * 64}, "evidence"),
        (
            {},
            {"target_portfolio_policy_fingerprint": "2" * 64},
            "policy fingerprint",
        ),
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
            decision=_decision_input(
                api,
                plan_evidence=research_plan,
                capital_snapshot=_capital_snapshot(
                    api,
                    mode=api.ExecutionMode.RESEARCH_RECONSTRUCTION,
                ),
            ),
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


def test_plan_evidence_and_publish_path_require_strategy_lineage_scope() -> None:
    api = _api()
    with pytest.raises(ValidationError, match="strategy-lineage|STRATEGY_LINEAGE"):
        _plan(
            api,
            subject_scope=api.EvidenceScope.GLOBAL,
            family_id=None,
        )


@pytest.mark.parametrize(
    ("capital_overrides", "expected_message"),
    [
        (
            {"portfolio_id": "other-portfolio"},
            "capital portfolio must match plan portfolio",
        ),
        ({"mode": None}, "capital mode must match plan mode"),
        (
            {"authority_epoch": 4},
            "capital authority epoch must match decision authority epoch",
        ),
        (
            {"risk_epoch": 9},
            "capital risk epoch must match decision risk epoch",
        ),
        (
            {"as_of": datetime(2026, 7, 19, 8, 1, tzinfo=UTC)},
            "capital snapshot as_of cannot be after decision creation",
        ),
    ],
)
def test_decision_input_rejects_capital_identity_mismatch(
    capital_overrides, expected_message
) -> None:
    api = _api()
    if "mode" in capital_overrides and capital_overrides["mode"] is None:
        capital_overrides["mode"] = api.ExecutionMode.MANUAL_CONFIRMED
    with pytest.raises(ValidationError) as error:
        _decision_input(
            api, capital_snapshot=_capital_snapshot(api, **capital_overrides)
        )
    validation_messages = {
        str(item.get("ctx", {}).get("error", ""))
        for item in error.value.errors(include_url=False)
    }
    assert expected_message in validation_messages


def test_decision_input_binds_exact_capital_revision_and_payload_hash() -> None:
    api = _api()
    current = _decision_input(api)
    stale = _decision_input(
        api,
        capital_snapshot=_capital_snapshot(
            api,
            capital_snapshot_id="capital-018",
            capital_version=18,
            stream_version=28,
            payload_content_hash="3" * 64,
        ),
    )

    assert current.capital_snapshot.capital_snapshot_id == "capital-019"
    assert current.capital_snapshot.capital_version == 19
    assert current.capital_snapshot.stream_version == 29
    assert current.capital_snapshot.payload_content_hash == HASH
    assert stale.capital_snapshot.capital_version == 18
    assert current.content_hash() != stale.content_hash()
    with pytest.raises(ValidationError, match="frozen_instance"):
        current.capital_snapshot.capital_version = 18


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
    assert (
        SealWriter().publish(
            api.PublishDecisionCommand(
                decision=_decision_input(api),
                authorization=_binding(api),
            )
        )
        is seal
    )


def test_capability_verifier_port_preserves_explicit_verification_time() -> None:
    api = _api()

    class Verifier:
        def verify(
            self,
            signed: api.SignedEnvelope,
            required: api.Capability,
            *,
            verification_time: datetime,
        ) -> api.VerifiedIssuer:
            raise NotImplementedError

    assert isinstance(Verifier(), api.CapabilityVerifier)
    signature = inspect.signature(api.CapabilityVerifier.verify)
    assert list(signature.parameters) == [
        "self",
        "signed",
        "required",
        "verification_time",
    ]
    assert (
        signature.parameters["verification_time"].kind is inspect.Parameter.KEYWORD_ONLY
    )
    assert signature.parameters["verification_time"].default is inspect.Parameter.empty
    assert get_type_hints(api.CapabilityVerifier.verify) == {
        "signed": api.SignedEnvelope,
        "required": api.Capability,
        "verification_time": datetime,
        "return": api.VerifiedIssuer,
    }


def test_stable_port_annotations_are_exact_and_contain_no_mutable_or_any_boundary() -> (
    None
):
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

    expected[api.CapabilityVerifier.verify] = {
        "signed": api.SignedEnvelope,
        "required": api.Capability,
        "verification_time": datetime,
        "return": api.VerifiedIssuer,
    }
    forbidden_types = {Any, dict, list, set}
    forbidden_names = {
        "Connection",
        "Cursor",
        "DataFrame",
        "MutableMapping",
        "Session",
    }

    def annotation_nodes(annotation):
        yield annotation
        for argument in get_args(annotation):
            yield from annotation_nodes(argument)

    for method, expected_annotations in expected.items():
        hints = get_type_hints(method)
        assert hints == expected_annotations
        for annotation in hints.values():
            for node in annotation_nodes(annotation):
                origin = get_origin(node)
                assert node not in forbidden_types
                assert origin not in forbidden_types
                assert getattr(node, "__name__", "") not in forbidden_names


def test_revision2_final_ports_are_the_only_current_public_port_surface() -> None:
    from src.screening.offensive.v3 import contracts

    final_ports = {
        "AuthorizationQueryPort",
        "CapitalGatewayCommandPort",
        "CapitalGatewayReadPort",
        "CapabilityVerifier",
        "EvidenceQueryPort",
        "GrowthKernelPort",
    }

    assert final_ports <= set(contracts.__all__)
    assert all(hasattr(contracts, name) for name in final_ports)
    assert "CapitalViewPort" not in contracts.__all__
    assert not hasattr(contracts, "CapitalViewPort")


def test_revision2_final_ports_are_runtime_structural_with_frozen_domain_returns() -> (
    None
):
    from src.screening.offensive.v3 import contracts as api

    risk = api.CapitalRiskSnapshot.model_construct()
    active_records = _active_evidence_records(api)
    active = active_records[0]
    outcome = next(
        record
        for record in active_records
        if isinstance(record.evidence, api.OutcomeEvidence)
    )
    envelope = api.CapitalAuthorizationEnvelope.model_construct()
    status = api.AuthorizationStatus.model_construct()
    proposal = api.PortfolioDecision.model_construct()
    seal = api.PortfolioDecisionSeal.model_construct()
    shadow = api.ShadowDecision.model_construct()
    expected = api.GatewayExpectedVersions.model_construct()
    signed = api.SignedEnvelope.model_construct()
    required = api.Capability.model_construct()
    current_head = api.CurrentTrustHeadWitness.model_construct()
    verified = api.VerifiedIssuer.model_construct()

    class KernelInput(api.CanonicalModel):
        input_id: str

    class NoTradeDecision(api.CanonicalModel):
        reason: str

    frozen_input = KernelInput(input_id="input-1")
    no_trade = NoTradeDecision(reason="no eligible entry")
    expected_proposal = proposal
    expected_versions = expected
    expected_signed = signed
    expected_capability = required
    expected_current_head = current_head

    class CapitalRead:
        def risk_snapshot(
            self, portfolio_id: str, as_of: datetime
        ) -> api.CapitalRiskSnapshot:
            assert portfolio_id == "portfolio-1"
            assert as_of == NOW
            return risk

    class EvidenceQuery:
        def active_revision(
            self, evidence_id: str, cutoff: datetime
        ) -> api.ActiveEvidenceRecord:
            assert evidence_id == "evidence-1"
            assert cutoff == NOW
            return active

        def outcome(
            self, outcome_id: str, revision: int
        ) -> api.EvidenceRecord[api.OutcomeEvidence]:
            assert outcome_id == "outcome-1"
            assert revision == 2
            return outcome

    class AuthorizationQuery:
        def active_envelope(
            self, portfolio_id: str
        ) -> api.CapitalAuthorizationEnvelope:
            assert portfolio_id == "portfolio-1"
            return envelope

        def status(self, authorization_id: str) -> api.AuthorizationStatus:
            assert authorization_id == "authorization-1"
            return status

    class Kernel:
        def decide(
            self, frozen: KernelInput
        ) -> NoTradeDecision | api.ShadowDecision | api.PortfolioDecision:
            assert frozen is frozen_input
            return no_trade

    class Gateway:
        def publish_entry(
            self,
            proposal: api.PortfolioDecision,
            expected: api.GatewayExpectedVersions,
        ) -> api.PortfolioDecisionSeal:
            assert proposal is expected_proposal
            assert expected is expected_versions
            return seal

    class Verifier:
        def verify(
            self,
            signed: api.SignedEnvelope,
            required: api.Capability,
            *,
            current_head: api.CurrentTrustHeadWitness,
            trusted_at: datetime,
        ) -> api.VerifiedIssuer:
            assert signed is expected_signed
            assert required is expected_capability
            assert current_head is expected_current_head
            assert trusted_at == NOW
            return verified

    assert isinstance(CapitalRead(), api.CapitalGatewayReadPort)
    for record in active_records:
        active = record
        assert isinstance(EvidenceQuery(), api.EvidenceQueryPort)
        assert EvidenceQuery().active_revision("evidence-1", NOW) is record
    assert isinstance(AuthorizationQuery(), api.AuthorizationQueryPort)
    assert isinstance(Kernel(), api.GrowthKernelPort)
    assert isinstance(Gateway(), api.CapitalGatewayCommandPort)
    assert isinstance(Verifier(), api.CapabilityVerifier)
    assert CapitalRead().risk_snapshot("portfolio-1", NOW) is risk
    assert EvidenceQuery().outcome("outcome-1", 2) is outcome
    assert AuthorizationQuery().active_envelope("portfolio-1") is envelope
    assert AuthorizationQuery().status("authorization-1") is status
    assert Kernel().decide(frozen_input) is no_trade
    assert Gateway().publish_entry(proposal, expected) is seal
    assert (
        Verifier().verify(
            signed,
            required,
            current_head=current_head,
            trusted_at=NOW,
        )
        is verified
    )

    for returned in (
        risk,
        active,
        outcome,
        envelope,
        status,
        no_trade,
        shadow,
        proposal,
        seal,
        verified,
    ):
        assert returned.model_config["frozen"] is True
        with pytest.raises(ValidationError, match="frozen_instance"):
            returned.illegal_mutation = True


def test_revision2_final_port_signatures_are_exact_and_generic_kernel_is_deferred() -> (
    None
):
    from src.screening.offensive.v3 import contracts as api

    expected = {
        api.CapitalGatewayReadPort.risk_snapshot: {
            "portfolio_id": str,
            "as_of": datetime,
            "return": api.CapitalRiskSnapshot,
        },
        api.EvidenceQueryPort.active_revision: {
            "evidence_id": str,
            "cutoff": datetime,
            "return": api.ActiveEvidenceRecord,
        },
        api.EvidenceQueryPort.outcome: {
            "outcome_id": str,
            "revision": int,
            "return": api.EvidenceRecord[api.OutcomeEvidence],
        },
        api.AuthorizationQueryPort.active_envelope: {
            "portfolio_id": str,
            "return": api.CapitalAuthorizationEnvelope,
        },
        api.AuthorizationQueryPort.status: {
            "authorization_id": str,
            "return": api.AuthorizationStatus,
        },
        api.CapitalGatewayCommandPort.publish_entry: {
            "proposal": api.PortfolioDecision,
            "expected": api.GatewayExpectedVersions,
            "return": api.PortfolioDecisionSeal,
        },
        api.CapabilityVerifier.verify: {
            "signed": api.SignedEnvelope,
            "required": api.Capability,
            "current_head": api.CurrentTrustHeadWitness,
            "trusted_at": datetime,
            "return": api.VerifiedIssuer,
        },
    }
    for method, exact_hints in expected.items():
        assert get_type_hints(method) == exact_hints

    verifier_signature = inspect.signature(api.CapabilityVerifier.verify)
    assert list(verifier_signature.parameters) == [
        "self",
        "signed",
        "required",
        "current_head",
        "trusted_at",
    ]
    for name in ("current_head", "trusted_at"):
        assert (
            verifier_signature.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
        )
        assert verifier_signature.parameters[name].default is inspect.Parameter.empty

    kernel_parameters = api.GrowthKernelPort.__parameters__
    assert len(kernel_parameters) == 2
    frozen_input_type, no_trade_type = kernel_parameters
    assert frozen_input_type.__bound__ is api.CanonicalModel
    assert frozen_input_type.__contravariant__ is True
    assert no_trade_type.__bound__ is api.CanonicalModel
    assert no_trade_type.__covariant__ is True
    kernel_hints = get_type_hints(api.GrowthKernelPort.decide)
    assert kernel_hints["frozen"] is frozen_input_type
    assert set(get_args(kernel_hints["return"])) == {
        no_trade_type,
        api.ShadowDecision,
        api.PortfolioDecision,
    }

    rendered = " ".join(
        str(annotation)
        for method in (*expected, api.GrowthKernelPort.decide)
        for annotation in get_type_hints(method).values()
    )
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
    ):
        assert forbidden not in rendered


def _active_evidence_records(api):
    common = {
        "subject_scope": api.EvidenceScope.STRATEGY_LINEAGE,
        "subject_producer": "btst",
        "family_id": "btst.limit-up-breakout",
        "strategy_semver": "3.0.0",
        "behavior_fingerprint": HASH,
        "policy_epoch": 7,
        "execution_version": "t1-open-t10-open.v1",
        "cost_version": "cn-a-share-costs.v1",
        "effective_at": NOW,
        "provider_published_at": NOW,
        "observed_at": NOW,
        "available_at": NOW + timedelta(minutes=2),
        "mode": api.ExecutionMode.DAILY_BAR_PROXY,
        "source_authority": "trusted-publisher",
        "payload_content_hash": HASH,
        "schema_major": 2,
    }
    evidence = (
        api.SnapshotEvidence(
            **(
                common
                | {
                    "evidence_id": "snapshot-1",
                    "subject_scope": api.EvidenceScope.GLOBAL,
                    "subject_producer": "market-publisher",
                    "family_id": None,
                    "evidence_kind": "snapshot",
                }
            )
        ),
        api.SignalEvidence(
            **(
                common
                | {
                    "evidence_id": "signal-1",
                    "evidence_kind": "signal",
                    "stage": api.SignalStage.SELECTED,
                }
            )
        ),
        api.OutcomeEvidence(
            **(
                common
                | {
                    "evidence_id": "outcome-1",
                    "evidence_kind": "outcome",
                }
            )
        ),
        api.PlanEvidence(
            **(
                common
                | {
                    "evidence_id": "plan-1",
                    "evidence_kind": "plan",
                    "portfolio_id": "portfolio-1",
                    "signal_session": date(2026, 7, 19),
                    "economic_lineage_id": "btst-economic-lineage",
                    "snapshot_id": "snapshot-1",
                    "raw_target_fraction": Decimal("0.02"),
                    "created_at": NOW,
                }
            )
        ),
    )
    return tuple(
        api.EvidenceRecord[type(item)](
            evidence=item,
            ingested_at=NOW + timedelta(minutes=1),
            commit_sequence=index,
            revision=1,
            supersedes_revision=None,
            active_revision=1,
        )
        for index, item in enumerate(evidence, start=1)
    )


def test_active_evidence_record_is_closed_over_all_strict_payloads() -> None:
    from src.screening.offensive.v3 import contracts as api

    records = _active_evidence_records(api)
    assert tuple(type(record.evidence) for record in records) == (
        api.SnapshotEvidence,
        api.SignalEvidence,
        api.OutcomeEvidence,
        api.PlanEvidence,
    )
    assert set(get_args(api.ActiveEvidenceRecord)) == {
        api.EvidenceRecord[api.SnapshotEvidence],
        api.EvidenceRecord[api.SignalEvidence],
        api.EvidenceRecord[api.OutcomeEvidence],
        api.EvidenceRecord[api.PlanEvidence],
    }
    with pytest.raises(ValidationError, match="extra_forbidden"):
        api.EvidenceRecord[api.EvidenceEnvelope](
            evidence=records[0].evidence,
            ingested_at=NOW + timedelta(minutes=1),
            commit_sequence=1,
            revision=1,
            supersedes_revision=None,
            active_revision=1,
        )


def test_active_evidence_record_strict_roundtrip_preserves_concrete_truth() -> None:
    from src.screening.offensive.v3 import contracts as api

    adapter = TypeAdapter(api.ActiveEvidenceRecord)
    for record in _active_evidence_records(api):
        restored = adapter.validate_json(record.model_dump_json(), strict=True)

        assert type(restored) is type(record)
        assert type(restored.evidence) is type(record.evidence)
        assert restored == record
        assert restored.artifact_hash() == record.artifact_hash()


def test_concrete_capability_verifier_satisfies_the_final_port() -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from src.screening.offensive.v3 import contracts
    from src.screening.offensive.v3 import trust
    from tests.offensive.v3.contracts.test_trust_registry import (
        _capability,
        _current_head,
        _issuer,
        _root_verified_bundle,
        _signed,
    )

    private_key = Ed25519PrivateKey.generate()
    required = _capability(trust)
    issuer = _issuer(trust, private_key, required)
    root_verifier, signed_chain = _root_verified_bundle(
        trust,
        trust.TrustedRegistry(issuers=(issuer,)),
        return_context=True,
    )
    verifier = trust.CapabilityVerifier(root_verifier, signed_chain)
    signed = _signed(trust, private_key, required)
    current_head = _current_head(trust, verifier)

    assert isinstance(verifier, contracts.CapabilityVerifier)
    concrete_signature = inspect.signature(type(verifier).verify)
    for name in ("current_head", "trusted_at"):
        assert name in concrete_signature.parameters
        assert (
            concrete_signature.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
        )
    verified = verifier.verify(
        signed,
        required,
        current_head=current_head,
        trusted_at=NOW,
    )
    assert isinstance(verified, contracts.VerifiedIssuer)
