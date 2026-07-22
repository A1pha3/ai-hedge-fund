"""Branch-level adversarial tests for stable v3 contract boundaries."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from base64 import b64encode
import hashlib
from typing import Any

import pytest
from pydantic import ValidationError


UTC = timezone.utc
NOW = datetime(2026, 7, 19, 8, 0, tzinfo=UTC)
HASH = "e" * 64
POLICY_HASH = "1" * 64


def _api() -> Any:
    from src.screening.offensive.v3 import contracts

    return contracts


def _plan(api: Any, **overrides: Any) -> Any:
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


def _capital(api: Any, **overrides: Any) -> Any:
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


def _order_line(api: Any, **overrides: Any) -> Any:
    values = {
        "order_line_id": "line-600000-entry",
        "security_id": "600000.SH",
        "order_action": "entry",
        "entry_session": date(2026, 7, 20),
        "exit_session_ordinal": 10,
        "exit_policy_version": "t10-open.v1",
        "sealed_quantity": 100,
        "lot_rule_version": "cn-board-lot.v1",
        "order_type": "limit",
        "limit_price": Decimal("10.50"),
        "worst_case_price": Decimal("10.50"),
        "price_boundary_version": "exchange-limit.v1",
        "time_in_force": "opening-auction",
        "worst_case_fee_reserve": Decimal("5"),
        "worst_case_cash_reserve": Decimal("1055"),
    }
    values.update(overrides)
    return api.SealedOrderLine(**values)


def _decision(api: Any, **overrides: Any) -> Any:
    values = {
        "plan_evidence": _plan(api),
        "capital_snapshot": _capital(api),
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


def _authorization_binding(api: Any, **overrides: Any) -> Any:
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


def _command(api: Any, **overrides: Any) -> Any:
    values = {
        "decision": _decision(api),
        "authorization": _authorization_binding(api),
    }
    values.update(overrides)
    return api.PublishDecisionCommand(**values)


def _unchecked_mutation(model: Any, method: str, **updates: Any) -> Any:
    if method == "model_copy":
        return model.model_copy(update=updates)
    values = {name: getattr(model, name) for name in type(model).model_fields}
    values.update(updates)
    return type(model).model_construct(**values)


def _seal(api: Any, command: Any | None = None, **overrides: Any) -> Any:
    return api.DecisionSeal.from_command(
        command or _command(api),
        evidence_id="seal-001-r1",
        seal_id="seal-001-r1",
        seal_revision=1,
        source_authority="growth-kernel",
        payload_content_hash="9" * 64,
        **overrides,
    )


def test_seal_binding_preserves_exact_publish_command_truth() -> None:
    api = _api()
    command = _command(api)

    seal = _seal(api, command)
    binding = seal.command_binding

    assert binding.publish_command_content_hash == command.content_hash()
    assert binding.portfolio_id == command.decision.plan_evidence.portfolio_id
    assert binding.capital_snapshot_id == "capital-019"
    assert binding.capital_version == 19
    assert binding.capital_stream_version == 29
    assert binding.capital_payload_content_hash == HASH
    assert binding.target_portfolio_policy_fingerprint == POLICY_HASH
    assert binding.capital_authorization_id == "auth-001"
    assert binding.authorization_version == 4
    assert binding.evidence_set_merkle_root == HASH
    assert binding.family_id == "btst.limit-up-breakout"
    assert binding.economic_lineage_id == "btst-economic-lineage"
    assert binding.mode is api.ExecutionMode.DAILY_BAR_PROXY
    assert binding.authority_epoch == 3
    assert binding.risk_epoch == 8


@pytest.mark.parametrize(
    "command_factory",
    [
        lambda api: _command(
            api,
            decision=_decision(
                api,
                capital_snapshot=_capital(api, capital_snapshot_id="capital-020"),
            ),
        ),
        lambda api: _command(
            api,
            decision=_decision(
                api,
                capital_snapshot=_capital(api, capital_version=20),
            ),
        ),
        lambda api: _command(
            api,
            decision=_decision(
                api,
                capital_snapshot=_capital(api, stream_version=30),
            ),
        ),
        lambda api: _command(
            api,
            decision=_decision(
                api,
                capital_snapshot=_capital(api, payload_content_hash="2" * 64),
            ),
        ),
        lambda api: _command(
            api,
            decision=_decision(api, target_portfolio_policy_fingerprint="2" * 64),
            authorization=_authorization_binding(
                api,
                target_portfolio_policy_fingerprint="2" * 64,
            ),
        ),
        lambda api: _command(
            api,
            authorization=_authorization_binding(api, capital_authorization_id="auth-002"),
        ),
        lambda api: _command(
            api,
            authorization=_authorization_binding(api, authorization_version=5),
        ),
        lambda api: _command(
            api,
            decision=_decision(api, evidence_set_merkle_root="2" * 64),
            authorization=_authorization_binding(
                api,
                evidence_set_merkle_root="2" * 64,
            ),
        ),
        lambda api: _command(
            api,
            decision=_decision(api, order_lines=(_order_line(api, sealed_quantity=200, worst_case_cash_reserve=Decimal("2105")),)),
        ),
    ],
)
def test_every_relevant_command_change_changes_the_seal_binding(
    command_factory: Any,
) -> None:
    api = _api()
    original = _seal(api).command_binding
    changed = _seal(api, command_factory(api)).command_binding

    assert changed != original
    assert changed.publish_command_content_hash != original.publish_command_content_hash


@pytest.mark.parametrize(
    "field,value",
    [
        ("portfolio_id", "other-portfolio"),
        ("mode", "manual_confirmed"),
        ("authority_epoch", 4),
        ("risk_epoch", 9),
        ("family_id", "other.family"),
        ("economic_lineage_id", "other-lineage"),
        ("capital_authorization_id", "auth-002"),
        ("authorization_version", 5),
        ("evidence_set_merkle_root", "2" * 64),
    ],
)
def test_seal_rejects_command_binding_mismatch(field: str, value: Any) -> None:
    api = _api()
    seal = _seal(api)
    raw = seal.model_dump(mode="python")
    if field == "mode":
        value = api.ExecutionMode.MANUAL_CONFIRMED
    if field in api.DecisionSealBinding.model_fields:
        raw["command_binding"] = seal.command_binding.model_copy(update={field: value})
    else:
        raw[field] = (
            api.ExecutionMode.MANUAL_CONFIRMED if field == "mode" else value
        )

    with pytest.raises(ValidationError, match="command binding"):
        api.DecisionSeal.model_validate(raw)


@pytest.mark.parametrize("method", ["model_copy", "model_construct"])
@pytest.mark.parametrize("nested_kind", ["plan", "capital"])
def test_decision_input_recursively_revalidates_nested_instances(
    method: str,
    nested_kind: str,
) -> None:
    api = _api()
    overrides: dict[str, Any]
    if nested_kind == "plan":
        overrides = {
            "plan_evidence": _unchecked_mutation(
                _plan(api),
                method,
                raw_target_fraction="0.02",
            )
        }
    else:
        overrides = {
            "capital_snapshot": _unchecked_mutation(
                _capital(api),
                method,
                cash="50000",
            )
        }

    with pytest.raises(ValidationError):
        _decision(api, **overrides)


@pytest.mark.parametrize("method", ["model_copy", "model_construct"])
def test_capital_authorization_root_revalidates_unchecked_instances(
    method: str,
) -> None:
    api = _api()
    valid = api.CapitalAuthorization.model_validate(
        {
            "authorization_kind": "edge",
            "authorization_version": 1,
            "evidence_id": "auth-001",
            "subject_scope": api.EvidenceScope.STRATEGY_LINEAGE,
            "subject_producer": "authorizer",
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
            "source_authority": "authorizer",
            "payload_content_hash": HASH,
            "schema_major": 1,
            "economic_lineage_id": "btst-economic-lineage",
            "research_program_id": "program-001",
            "baseline_portfolio_policy_fingerprint": HASH,
            "target_portfolio_policy_fingerprint": POLICY_HASH,
            "evidence_as_of": NOW,
            "evidence_set_merkle_root": HASH,
            "issued_at": NOW,
            "expires_at": datetime(2026, 7, 20, 8, 0, tzinfo=UTC),
            "max_capital_tier": 2,
            "issuer_id": "authorizer.service",
            "issuer_capability": "capital.edge.btst",
            "trial_id": "trial-001",
            "trial_manifest_hash": HASH,
            "statistical_analysis_plan_hash": HASH,
            "assessment_result_hash": HASH,
            "attempt_ledger_checkpoint_hash": HASH,
            "alpha_sample_consumption_id": "consumption-001",
            "authorization_payload_hash": HASH,
        }
    )
    poisoned_member = _unchecked_mutation(
        valid.root,
        method,
        max_capital_tier=3,
    )
    poisoned = _unchecked_mutation(valid, method, root=poisoned_member)

    with pytest.raises(ValidationError):
        api.CapitalAuthorization.model_validate(poisoned, strict=True)


@pytest.mark.parametrize("method", ["model_copy", "model_construct"])
def test_publish_command_recursively_revalidates_decision_input(
    method: str,
) -> None:
    api = _api()
    poisoned_line = _unchecked_mutation(
        _order_line(api),
        method,
        sealed_quantity="100",
    )
    poisoned_decision = _unchecked_mutation(
        _decision(api),
        method,
        order_lines=(poisoned_line,),
    )

    with pytest.raises(ValidationError):
        api.PublishDecisionCommand(
            decision=poisoned_decision,
            authorization=_authorization_binding(api),
        )


@pytest.mark.parametrize("method", ["model_copy", "model_construct"])
def test_publish_command_revalidates_its_own_unchecked_instance(method: str) -> None:
    api = _api()
    valid = _command(api)
    poisoned_binding = _unchecked_mutation(
        valid.authorization,
        method,
        capital_authorization_id=123,
    )
    poisoned_command = _unchecked_mutation(
        valid,
        method,
        authorization=poisoned_binding,
    )

    with pytest.raises(ValidationError):
        api.PublishDecisionCommand.model_validate(poisoned_command, strict=True)


@pytest.mark.parametrize("method", ["model_copy", "model_construct"])
def test_signed_envelope_revalidates_its_own_unchecked_instance(method: str) -> None:
    api = _api()
    payload = b"{}"
    valid = api.SignedEnvelope(
        issuer_id="issuer.service",
        key_id="issuer-key",
        schema_major=1,
        artifact=api.ArtifactKind.DECISION_SEAL,
        namespace="decision.live",
        mode=api.ExecutionMode.DAILY_BAR_PROXY,
        capability_version="decision-seal.v1",
        capability_scope="portfolio:paper-v3",
        payload_hash=hashlib.sha256(payload).hexdigest(),
        payload=payload,
        signature=b64encode(b"\0" * 64).decode("ascii"),
    )
    poisoned = _unchecked_mutation(
        valid,
        method,
        mode=api.ExecutionMode.DAILY_BAR_PROXY.value,
    )

    with pytest.raises(ValidationError):
        api.SignedEnvelope.model_validate(poisoned, strict=True)


def test_capital_authorization_binding_keeps_family_and_lineage_distinct() -> None:
    api = _api()

    with pytest.raises(ValidationError, match="family.*lineage|lineage.*family"):
        _authorization_binding(
            api,
            family_id="btst-economic-lineage",
            economic_lineage_id="btst-economic-lineage",
        )
