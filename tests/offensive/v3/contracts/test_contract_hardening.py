"""Branch-level adversarial tests for stable v3 contract boundaries."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from base64 import b64encode
import hashlib
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest
from pydantic import ValidationError


UTC = timezone.utc
NOW = datetime(2026, 7, 19, 8, 0, tzinfo=UTC)
HASH = "e" * 64
POLICY_HASH = "1" * 64


def _api() -> Any:
    from src.screening.offensive.v3.contracts import revision1

    return revision1


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


def _signed_seal_envelope(api: Any, payload: bytes) -> tuple[Any, Any, Any]:
    from src.screening.offensive.v3 import trust

    private_key = Ed25519PrivateKey.generate()
    public_key = b64encode(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")
    required = trust.Capability(
        artifact=trust.ArtifactKind.DECISION_SEAL,
        namespace="decision.live",
        mode=trust.ExecutionMode.DAILY_BAR_PROXY,
        schema_major=1,
        capability_version="growth-kernel.v1",
        scope="portfolio:paper-v3",
        valid_from=datetime(2026, 7, 18, 8, 0, tzinfo=UTC),
        valid_until=datetime(2026, 7, 20, 8, 0, tzinfo=UTC),
        revoked_at=None,
    )
    issuer = trust.TrustedIssuer(
        issuer_id="growth-kernel.service",
        key_id="growth-kernel-key-2026-07",
        issuer_kind=trust.IssuerKind.GROWTH_KERNEL,
        public_key=public_key,
        valid_from=datetime(2026, 7, 18, 8, 0, tzinfo=UTC),
        valid_until=datetime(2026, 7, 20, 8, 0, tzinfo=UTC),
        revoked_at=None,
        capabilities=(required,),
    )
    payload_hash = hashlib.sha256(payload).hexdigest()
    protected = api.canonical_json_bytes(
        {
            "artifact": required.artifact,
            "capability_scope": required.scope,
            "capability_version": required.capability_version,
            "issuer_id": issuer.issuer_id,
            "key_id": issuer.key_id,
            "mode": required.mode,
            "namespace": required.namespace,
            "payload": b64encode(payload).decode("ascii"),
            "payload_hash": payload_hash,
            "schema_major": required.schema_major,
        }
    )
    signed = trust.SignedEnvelope(
        issuer_id=issuer.issuer_id,
        key_id=issuer.key_id,
        schema_major=required.schema_major,
        artifact=required.artifact,
        namespace=required.namespace,
        mode=required.mode,
        capability_version=required.capability_version,
        capability_scope=required.scope,
        payload_hash=payload_hash,
        payload=payload,
        signature=b64encode(private_key.sign(protected)).decode("ascii"),
    )
    from src.screening.offensive.v3.contracts.governance import TrustBundle

    registry = trust.TrustedRegistry(issuers=(issuer,))
    root_key = Ed25519PrivateKey.generate()
    root_public = root_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    anchor = trust.RootTrustAnchor(
        root_hash=hashlib.sha256(root_public).hexdigest(),
        root_key_id="offline-root-1",
        public_key=b64encode(root_public).decode("ascii"),
        valid_from=datetime(2026, 7, 18, 8, 0, tzinfo=UTC),
        valid_until=datetime(2026, 7, 20, 8, 0, tzinfo=UTC),
        revoked_at=None,
    )
    bundle = TrustBundle(
        registry_epoch=1,
        predecessor_bundle_hash="0" * 64,
        root_hash=anchor.root_hash,
        root_key_id=anchor.root_key_id,
        trusted_issuer_registry_hash=registry.content_hash(),
        issued_at=datetime(2026, 7, 18, 8, 0, tzinfo=UTC),
        expires_at=datetime(2026, 7, 20, 8, 0, tzinfo=UTC),
        revoked_at=None,
        issuer_id="offline-governance-root",
        issuer_capability="root.trust.bundle.v1",
        schema_major=2,
    )
    signed_bundle = trust.SignedTrustBundle(
        bundle=bundle,
        registry=registry,
        signature=b64encode(
            root_key.sign(trust.trust_bundle_signature_preimage(bundle, registry))
        ).decode("ascii"),
    )
    verifier = trust.CapabilityVerifier(
        trust.TrustBundleVerifier((anchor,)),
        (signed_bundle,),
    )
    return signed, verifier, required


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


def test_seal_binding_contains_the_complete_publish_command() -> None:
    api = _api()
    command = _command(api)

    binding = _seal(api, command).command_binding

    assert binding.publish_command == command
    assert (
        binding.publish_command_content_hash == binding.publish_command.content_hash()
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("publish_command_content_hash", "2" * 64),
        ("portfolio_id", "other-portfolio"),
        ("capital_snapshot_id", "capital-020"),
        ("capital_version", 20),
        ("capital_stream_version", 30),
        ("capital_payload_content_hash", "2" * 64),
        ("target_portfolio_policy_fingerprint", "2" * 64),
        ("capital_authorization_id", "auth-002"),
        ("authorization_version", 5),
        ("evidence_set_merkle_root", "2" * 64),
        ("family_id", "other.family"),
        ("economic_lineage_id", "other-lineage"),
        ("mode", "manual_confirmed"),
        ("authority_epoch", 4),
        ("risk_epoch", 9),
    ],
)
def test_binding_rejects_every_flat_field_drift(field: str, value: Any) -> None:
    api = _api()
    raw = _seal(api).command_binding.model_dump(mode="python", round_trip=True)
    raw[field] = api.ExecutionMode.MANUAL_CONFIRMED if field == "mode" else value

    with pytest.raises(ValidationError, match="command binding|publish command"):
        api.DecisionSealBinding.model_validate(raw, strict=True)


@pytest.mark.parametrize(
    "drift",
    [
        "order_quantity",
        "order_price",
        "snapshot",
        "deadline",
        "logical_key",
        "policy",
        "capital",
    ],
)
def test_validly_signed_schema_drift_cannot_escape_embedded_command(
    drift: str,
) -> None:
    from src.screening.offensive.v3 import trust

    api = _api()
    raw = _seal(api).model_dump(mode="python", round_trip=True)
    if drift == "order_quantity":
        raw["order_lines"][0]["sealed_quantity"] = 200
        raw["order_lines"][0]["worst_case_cash_reserve"] = Decimal("2105")
    elif drift == "order_price":
        raw["order_lines"][0]["limit_price"] = Decimal("11")
        raw["order_lines"][0]["worst_case_price"] = Decimal("11")
        raw["order_lines"][0]["worst_case_cash_reserve"] = Decimal("1105")
    elif drift == "snapshot":
        raw["snapshot_id"] = "snapshot-002"
    elif drift == "deadline":
        raw["deadline"] = datetime(2026, 7, 19, 8, 21, tzinfo=UTC)
    elif drift == "logical_key":
        raw["signal_session"] = date(2026, 7, 18)
        raw["idempotency_key"]["signal_session"] = date(2026, 7, 18)
    elif drift == "policy":
        raw["policy_epoch"] = 4
    else:
        raw["command_binding"]["capital_version"] = 20

    signed, verifier, required = _signed_seal_envelope(
        api,
        api.canonical_json_bytes(raw),
    )
    bundle = verifier._signed_chain[-1].bundle
    current_head = trust.CurrentTrustHeadWitness(
        active_trust_bundle_hash=bundle.artifact_hash(),
        registry_epoch=bundle.registry_epoch,
        head_version=bundle.registry_epoch,
        store_version=1,
        observed_at=NOW,
    )
    with pytest.raises(
        trust.TrustVerificationError,
        match="legacy|unsupported",
    ):
        verifier.verify(
            signed,
            required,
            current_head=current_head,
            verification_time=NOW,
        )
    with pytest.raises(ValidationError, match="command binding|publish command"):
        api.DecisionSeal.model_validate_json(signed.payload, strict=True)


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
            authorization=_authorization_binding(
                api, capital_authorization_id="auth-002"
            ),
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
            decision=_decision(
                api,
                order_lines=(
                    _order_line(
                        api,
                        sealed_quantity=200,
                        worst_case_cash_reserve=Decimal("2105"),
                    ),
                ),
            ),
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
        raw[field] = api.ExecutionMode.MANUAL_CONFIRMED if field == "mode" else value

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
def test_capital_authorization_revalidates_unchecked_nested_member(
    method: str,
) -> None:
    api = _api()
    from test_ports import _authorization

    valid = _authorization(api)
    poisoned_member = _unchecked_mutation(
        valid.root,
        method,
        authorization_version="4",
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


@pytest.mark.parametrize("method", ["model_copy", "model_construct"])
@pytest.mark.parametrize(
    "serializer",
    [
        lambda api, model: model.canonical_bytes(),
        lambda api, model: model.content_hash(),
        lambda api, model: api.canonical_json_bytes(model),
        lambda api, model: api.content_hash(model),
    ],
)
def test_canonical_hashing_rejects_unchecked_top_level_models(
    method: str,
    serializer: Any,
) -> None:
    api = _api()
    poisoned = _unchecked_mutation(
        _plan(api),
        method,
        raw_target_fraction="0.02",
    )

    with pytest.raises(ValidationError):
        serializer(api, poisoned)


@pytest.mark.parametrize("method", ["model_copy", "model_construct"])
@pytest.mark.parametrize(
    "serializer",
    [
        lambda api, model: model.canonical_bytes(),
        lambda api, model: model.content_hash(),
        lambda api, model: api.canonical_json_bytes(model),
        lambda api, model: api.content_hash(model),
    ],
)
def test_canonical_hashing_rejects_unchecked_nested_models(
    method: str,
    serializer: Any,
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
    poisoned_command = _unchecked_mutation(
        _command(api),
        method,
        decision=poisoned_decision,
    )

    with pytest.raises(ValidationError):
        serializer(api, poisoned_command)
