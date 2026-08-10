"""Contract and adversarial loader tests for frozen v3 policy snapshots."""

from __future__ import annotations

from decimal import Decimal
from base64 import b64encode
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
INITIAL_POLICY_PATH = REPOSITORY_ROOT / "config/policies/v3/policy-v1.json"
REVISION2_POLICY_PATH = REPOSITORY_ROOT / "config/policies/v3/policy-v2.json"
UTC = timezone.utc
NOW = datetime(2026, 7, 29, 8, 0, tzinfo=UTC)


def _policy_api() -> Any:
    try:
        from src.screening.offensive.v3 import policy
    except ImportError as exc:
        pytest.fail(f"v3 policy contract is not implemented: {exc}")
    return policy


def _initial_policy() -> Any:
    return _policy_api().load_policy_snapshot(INITIAL_POLICY_PATH)


def _raw_initial_policy() -> dict[str, Any]:
    return json.loads(INITIAL_POLICY_PATH.read_text(encoding="utf-8"))


def _write_policy(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def _signed_policy_activation(
    *,
    activation_updates: dict[str, Any] | None = None,
    capability_updates: dict[str, Any] | None = None,
    policy_updates: dict[str, Any] | None = None,
    payload_override: bytes | None = None,
) -> tuple[Any, Any, Any, Any, Any]:
    from src.screening.offensive.v3 import trust
    from src.screening.offensive.v3.contracts.governance import (
        PolicyActivation,
        TrustBundle,
    )

    policy_api = _policy_api()
    policy = policy_api.load_policy_snapshot(REVISION2_POLICY_PATH)
    if policy_updates:
        policy = policy_api.PolicySnapshot.model_validate(
            policy.model_dump(mode="python", round_trip=True) | policy_updates,
            strict=True,
        )
    issuer_key = Ed25519PrivateKey.generate()
    capability_values = {
        "artifact": trust.ArtifactKind.POLICY_ACTIVATION,
        "namespace": "governance.policy.activation",
        "mode": trust.ExecutionMode.MANUAL_CONFIRMED,
        "schema_major": 2,
        "capability_version": "governance.policy.activation.v1",
        "scope": "portfolio:paper-v3",
        "valid_from": NOW - timedelta(days=1),
        "valid_until": NOW + timedelta(days=1),
        "revoked_at": None,
    }
    capability_values.update(capability_updates or {})
    capability = trust.Capability(**capability_values)
    issuer_public = issuer_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    issuer = trust.TrustedIssuer(
        issuer_id="governance.service",
        key_id="governance-key-1",
        issuer_kind=trust.IssuerKind.GOVERNANCE,
        public_key=b64encode(issuer_public).decode("ascii"),
        valid_from=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=1),
        revoked_at=None,
        capabilities=(capability,),
    )
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
        valid_from=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=1),
        revoked_at=None,
    )
    bundle = TrustBundle(
        registry_epoch=1,
        predecessor_bundle_hash="0" * 64,
        root_hash=anchor.root_hash,
        root_key_id=anchor.root_key_id,
        trusted_issuer_registry_hash=registry.content_hash(),
        issued_at=NOW - timedelta(minutes=10),
        expires_at=NOW + timedelta(days=1),
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
    trust_verifier = trust.TrustBundleVerifier((anchor,))
    values = {
        "portfolio_id": "paper-v3",
        "broker_account_id": "manual-account-1",
        "broker_account_fingerprint": None,
        "mode": trust.ExecutionMode.MANUAL_CONFIRMED,
        "policy_snapshot_hash": policy.policy_fingerprint,
        "predecessor_policy_activation_hash": "0" * 64,
        "trust_bundle_hash": bundle.artifact_hash(),
        "registry_epoch": 1,
        "policy_epoch": policy.policy_epoch,
        "authority_epoch": policy.authority_epoch,
        "risk_epoch": policy.risk_epoch,
        "effective_from": NOW - timedelta(minutes=1),
        "expires_at": NOW + timedelta(hours=1),
        "issuer_id": issuer.issuer_id,
        "issuer_capability": "governance.policy.activation.v1",
        "schema_major": 2,
    }
    values.update(activation_updates or {})
    activation = PolicyActivation(**values)
    payload = payload_override or activation.canonical_bytes()
    payload_hash = hashlib.sha256(payload).hexdigest()
    protected = trust.canonical_json_bytes(
        {
            "artifact": capability.artifact,
            "capability_scope": capability.scope,
            "capability_version": capability.capability_version,
            "issuer_id": issuer.issuer_id,
            "key_id": issuer.key_id,
            "mode": capability.mode,
            "namespace": capability.namespace,
            "payload": b64encode(payload).decode("ascii"),
            "payload_hash": payload_hash,
            "schema_major": capability.schema_major,
        }
    )
    signed = trust.SignedEnvelope(
        issuer_id=issuer.issuer_id,
        key_id=issuer.key_id,
        schema_major=capability.schema_major,
        artifact=capability.artifact,
        namespace=capability.namespace,
        mode=capability.mode,
        capability_version=capability.capability_version,
        capability_scope=capability.scope,
        payload_hash=payload_hash,
        payload=payload,
        signature=b64encode(issuer_key.sign(protected)).decode("ascii"),
    )
    capability_verifier = trust.CapabilityVerifier(
        trust_verifier,
        (signed_bundle,),
    )
    return policy, activation, signed, capability, capability_verifier


def _current_trust_head(verifier: Any) -> Any:
    from src.screening.offensive.v3 import trust

    bundle = verifier._signed_chain[-1].bundle
    return trust.CurrentTrustHeadWitness(
        active_trust_bundle_hash=bundle.artifact_hash(),
        registry_epoch=bundle.registry_epoch,
        head_version=bundle.registry_epoch,
        store_version=1,
        observed_at=NOW,
    )


@pytest.mark.parametrize(
    ("drawdown", "expected"),
    [
        (Decimal("0"), Decimal("1")),
        (Decimal("0.0999"), Decimal("1")),
        (Decimal("0.10"), Decimal("1")),
        (Decimal("0.125"), Decimal("0.5")),
        (Decimal("0.1499"), Decimal("0.002")),
        (Decimal("0.15"), Decimal("0")),
        (Decimal("0.25"), Decimal("0")),
    ],
)
def test_drawdown_multiplier_boundaries(drawdown: Decimal, expected: Decimal) -> None:
    policy = _policy_api()

    assert policy.PolicySnapshot.drawdown_multiplier(drawdown) == expected


def test_drawdown_multiplier_rejects_invalid_truth() -> None:
    policy = _policy_api()

    for value in (Decimal("-0.0001"), Decimal("NaN"), Decimal("Infinity")):
        with pytest.raises(ValueError, match="drawdown"):
            policy.PolicySnapshot.drawdown_multiplier(value)
    with pytest.raises(TypeError, match="Decimal"):
        policy.PolicySnapshot.drawdown_multiplier(0.10)


def test_initial_policy_is_off_and_contains_governed_risk_contract() -> None:
    policy = _initial_policy()

    assert policy.runtime_mode.value == "off"
    assert tuple(tier.value for tier in policy.capital.governed_tiers) == (2, 5, 10)
    assert policy.capital.exploration_aggregate_gross_cap == Decimal("0")
    assert policy.capital.portfolio_gross_cap == Decimal("0")
    assert policy.capital.single_name_gross_cap == Decimal("0")
    assert policy.capital.industry_gross_cap == Decimal("0")
    assert policy.capital.daily_entry_gross_cap == Decimal("0")
    assert policy.capital.stage_loss_budget_cap == Decimal("0")
    assert policy.risk.drawdown_scale_start == Decimal("0.10")
    assert policy.risk.drawdown_halt == Decimal("0.15")


def test_revision2_policy_candidate_remains_off_and_confers_no_authority() -> None:
    policy_api = _policy_api()
    policy = policy_api.load_policy_snapshot(REVISION2_POLICY_PATH)

    assert policy.policy_version == "policy-v2"
    assert policy.runtime_mode is policy_api.RuntimeMode.OFF
    assert policy.capital.portfolio_gross_cap == 0
    assert policy.producers.any_enabled() is False
    assert "activation" not in type(policy).model_fields
    assert not hasattr(policy_api, "activate_policy")


def test_policy_activation_verification_is_signed_but_has_no_side_effect() -> None:
    from src.screening.offensive.v3 import trust

    policy_api = _policy_api()
    policy, activation, signed, required, verifier = _signed_policy_activation()

    verified = policy_api.verify_policy_activation(
        signed,
        policy,
        verifier,
        required,
        current_trust_head=_current_trust_head(verifier),
        trusted_at=NOW,
        predecessor=None,
        expected_portfolio_id="paper-v3",
        expected_broker_account_id="manual-account-1",
        expected_broker_account_fingerprint=None,
        expected_mode=trust.ExecutionMode.MANUAL_CONFIRMED,
    )

    assert verified.activation == activation
    assert verified.policy_snapshot == policy
    assert verified.trust_bundle_hash == activation.trust_bundle_hash
    assert not hasattr(verified, "activate")


@pytest.mark.parametrize(
    ("activation_updates", "expected_account", "match"),
    [
        ({"policy_epoch": 2}, "manual-account-1", "policy_epoch"),
        (
            {"predecessor_policy_activation_hash": "f" * 64},
            "manual-account-1",
            "predecessor",
        ),
        ({}, "different-account", "account"),
        ({"registry_epoch": 2}, "manual-account-1", "registry_epoch"),
    ],
)
def test_policy_activation_rejects_epoch_predecessor_account_and_trust_mismatch(
    activation_updates: dict[str, Any],
    expected_account: str,
    match: str,
) -> None:
    from src.screening.offensive.v3 import trust

    policy_api = _policy_api()
    policy, _, signed, required, verifier = _signed_policy_activation(
        activation_updates=activation_updates
    )
    with pytest.raises(policy_api.PolicyActivationVerificationError, match=match):
        policy_api.verify_policy_activation(
            signed,
            policy,
            verifier,
            required,
            current_trust_head=_current_trust_head(verifier),
            trusted_at=NOW,
            predecessor=None,
            expected_portfolio_id="paper-v3",
            expected_broker_account_id=expected_account,
            expected_broker_account_fingerprint=None,
            expected_mode=trust.ExecutionMode.MANUAL_CONFIRMED,
        )


def test_policy_activation_payload_rejects_duplicate_json_keys() -> None:
    from src.screening.offensive.v3 import trust

    policy_api = _policy_api()
    policy, activation, _, _, _ = _signed_policy_activation()
    duplicate = activation.canonical_bytes().replace(
        b'"portfolio_id":"paper-v3"',
        b'"portfolio_id":"paper-v3","portfolio_id":"paper-v3"',
        1,
    )
    policy, _, signed, required, verifier = _signed_policy_activation(
        payload_override=duplicate
    )

    with pytest.raises(policy_api.PolicyActivationVerificationError, match="duplicate"):
        policy_api.verify_policy_activation(
            signed,
            policy,
            verifier,
            required,
            current_trust_head=_current_trust_head(verifier),
            trusted_at=NOW,
            predecessor=None,
            expected_portfolio_id="paper-v3",
            expected_broker_account_id="manual-account-1",
            expected_broker_account_fingerprint=None,
            expected_mode=trust.ExecutionMode.MANUAL_CONFIRMED,
        )


def test_policy_activation_requires_fixed_portfolio_capability_context() -> None:
    from src.screening.offensive.v3 import trust

    policy_api = _policy_api()
    policy, _, signed, required, verifier = _signed_policy_activation(
        capability_updates={"scope": "portfolio:other"}
    )

    with pytest.raises(
        policy_api.PolicyActivationVerificationError,
        match="capability.*scope|context",
    ):
        policy_api.verify_policy_activation(
            signed,
            policy,
            verifier,
            required,
            current_trust_head=_current_trust_head(verifier),
            trusted_at=NOW,
            predecessor=None,
            expected_portfolio_id="paper-v3",
            expected_broker_account_id="manual-account-1",
            expected_broker_account_fingerprint=None,
            expected_mode=trust.ExecutionMode.MANUAL_CONFIRMED,
        )


def test_initial_policy_disables_all_producer_and_sizing_switches() -> None:
    policy = _initial_policy()

    assert policy.producers.btst_enabled is False
    assert policy.producers.oversold_bounce_enabled is False
    assert policy.producers.regime_sizing_enabled is False
    assert policy.producers.streak_sizing_enabled is False
    assert policy.producers.trigger_strength_sizing_enabled is False
    assert policy.producers.composite_sizing_enabled is False


def test_runtime_modes_are_typed_but_initial_policy_enables_none() -> None:
    policy_api = _policy_api()

    assert [mode.value for mode in policy_api.RuntimeMode] == [
        "off",
        "shadow",
        "btst_canary",
        "authoritative",
    ]
    assert _initial_policy().runtime_mode is policy_api.RuntimeMode.OFF


def test_initial_policy_binds_adv_execution_and_governance_versions() -> None:
    policy = _initial_policy()

    assert policy.adv.lookback_sessions == 20
    assert policy.adv.max_participation_rate == Decimal("0.05")
    assert policy.adv.missing_data_behavior.value == "fail_closed"
    assert policy.execution.entry_session_ordinal == 1
    assert policy.execution.exit_session_ordinal == 10
    assert policy.execution.order_type == "opening_auction_limit"
    assert policy.execution.seal_deadline_after_t0_close_minutes == 240
    assert policy.execution.permit_deadline_before_auction_minutes == 20
    assert policy.execution.gateway_send_deadline_before_auction_minutes == 10
    assert policy.execution.broker_auction_submission_cutoff_cn == "09:20:00"
    assert policy.versions.cost_version == "cn-a-share-costs-30bps-tax.v2"
    assert policy.versions.board_rule_version == "ashare-board-prefix-v1"
    assert policy.versions.calendar_version == "sse-szse-official-sessions.v1"
    assert policy.versions.lot_rule_version == "cn-board-lot.v1"
    assert policy.versions.setup_version == "daily-action-setups-v1"
    assert policy.versions.execution_contract_version == "t0-close-t1-open-t10-open-slippage.v2"
    assert policy.versions.governance_version == "growth-kernel-governance.v1"


def test_initial_policy_payload_has_no_self_referential_fingerprint() -> None:
    raw = _raw_initial_policy()

    assert "policy_fingerprint" not in raw
    assert "behavior_fingerprint" not in raw
    assert (
        _initial_policy().policy_fingerprint
        == hashlib.sha256(_initial_policy().canonical_bytes()).hexdigest()
    )


def test_policy_fingerprint_covers_the_complete_payload() -> None:
    original = _initial_policy()
    changed = original.model_copy(
        update={
            "versions": original.versions.model_copy(
                update={"governance_version": "growth-kernel-governance.v2"}
            )
        }
    )

    assert original.policy_fingerprint != changed.policy_fingerprint


def test_behavior_fingerprint_is_typed_deterministic_and_policy_bound() -> None:
    policy_api = _policy_api()
    policy = _initial_policy()
    producer = policy_api.ProducerIdentity(
        producer_namespace="daily_action.btst",
        strategy_semver="3.0.0",
    )

    first = policy_api.behavior_fingerprint(producer, policy)
    second = policy_api.behavior_fingerprint(producer, policy)
    changed_producer = producer.model_copy(update={"strategy_semver": "3.0.1"})
    changed_policy = policy.model_copy(
        update={
            "versions": policy.versions.model_copy(
                update={"setup_version": "daily-action-setups-v2"}
            )
        }
    )

    assert first == second
    assert len(first) == 64
    assert first != policy_api.behavior_fingerprint(changed_producer, policy)
    assert first != policy_api.behavior_fingerprint(producer, changed_policy)
    with pytest.raises(TypeError, match="ProducerIdentity"):
        policy_api.behavior_fingerprint(  # type: ignore[arg-type]
            {"producer_namespace": "daily_action.btst", "strategy_semver": "3.0.0"},
            policy,
        )


def test_behavior_fingerprint_excludes_provenance_only_policy_labels() -> None:
    policy_api = _policy_api()
    policy = _initial_policy()
    producer = policy_api.ProducerIdentity(
        producer_namespace="daily_action.btst",
        strategy_semver="3.0.0",
    )
    provenance_revision = policy.model_copy(
        update={
            "policy_id": "growth-kernel-v3-republished",
            "policy_version": "policy-v2",
        }
    )

    assert policy.policy_fingerprint != provenance_revision.policy_fingerprint
    assert policy_api.behavior_fingerprint(
        producer, policy
    ) == policy_api.behavior_fingerprint(producer, provenance_revision)


def test_behavior_fingerprint_includes_policy_epoch() -> None:
    policy_api = _policy_api()
    policy = _initial_policy()
    producer = policy_api.ProducerIdentity(
        producer_namespace="daily_action.btst",
        strategy_semver="3.0.0",
    )
    next_epoch = policy.model_copy(update={"policy_epoch": 2})

    assert policy_api.behavior_fingerprint(
        producer, policy
    ) != policy_api.behavior_fingerprint(producer, next_epoch)


@pytest.mark.parametrize("epoch_field", ["authority_epoch", "risk_epoch"])
def test_behavior_fingerprint_excludes_operational_fencing_epochs(
    epoch_field: str,
) -> None:
    policy_api = _policy_api()
    policy = _initial_policy()
    producer = policy_api.ProducerIdentity(
        producer_namespace="daily_action.btst",
        strategy_semver="3.0.0",
    )
    next_epoch = policy.model_copy(update={epoch_field: 2})

    assert policy_api.behavior_fingerprint(
        producer, policy
    ) == policy_api.behavior_fingerprint(producer, next_epoch)


@pytest.mark.parametrize(
    ("field_path", "value"),
    [
        (("schema_major",), 1),
        (("schema_major",), 3),
        (("policy_version",), ""),
        (("versions", "cost_version"), "  "),
        (("versions", "calendar_version"), "not a version"),
    ],
)
def test_loader_rejects_unknown_major_and_invalid_versions(
    tmp_path: Path, field_path: tuple[str, ...], value: Any
) -> None:
    policy_api = _policy_api()
    raw = _raw_initial_policy()
    target: dict[str, Any] = raw
    for part in field_path[:-1]:
        target = target[part]
    target[field_path[-1]] = value
    path = tmp_path / "policy.json"
    _write_policy(path, raw)

    with pytest.raises(policy_api.PolicyLoadError):
        policy_api.load_policy_snapshot(path)


def test_loader_rejects_duplicate_keys(tmp_path: Path) -> None:
    policy_api = _policy_api()
    raw = INITIAL_POLICY_PATH.read_text(encoding="utf-8")
    duplicate = raw.replace('"schema_major":2', '"schema_major":2,"schema_major":2', 1)
    path = tmp_path / "policy.json"
    path.write_text(duplicate, encoding="utf-8")

    with pytest.raises(policy_api.PolicyLoadError, match="duplicate"):
        policy_api.load_policy_snapshot(path)


def test_loader_rejects_unknown_and_missing_governance_fields(tmp_path: Path) -> None:
    policy_api = _policy_api()
    extra = _raw_initial_policy()
    extra["environment_override"] = True
    extra_path = tmp_path / "extra.json"
    _write_policy(extra_path, extra)

    missing = _raw_initial_policy()
    del missing["versions"]["governance_version"]
    missing_path = tmp_path / "missing.json"
    _write_policy(missing_path, missing)

    with pytest.raises(policy_api.PolicyLoadError, match="extra_forbidden"):
        policy_api.load_policy_snapshot(extra_path)
    with pytest.raises(policy_api.PolicyLoadError, match="governance_version"):
        policy_api.load_policy_snapshot(missing_path)


def test_loader_rejects_symlink_and_non_regular_file(tmp_path: Path) -> None:
    policy_api = _policy_api()
    real = tmp_path / "real.json"
    _write_policy(real, _raw_initial_policy())
    link = tmp_path / "policy-link.json"
    link.symlink_to(real)

    with pytest.raises(policy_api.PolicyLoadError, match="regular|symlink"):
        policy_api.load_policy_snapshot(link)
    with pytest.raises(policy_api.PolicyLoadError, match="regular"):
        policy_api.load_policy_snapshot(tmp_path)

    real_directory = tmp_path / "real-directory"
    real_directory.mkdir()
    nested_policy = real_directory / "policy.json"
    _write_policy(nested_policy, _raw_initial_policy())
    linked_directory = tmp_path / "linked-directory"
    linked_directory.symlink_to(real_directory, target_is_directory=True)
    with pytest.raises(policy_api.PolicyLoadError, match="regular|symlink"):
        policy_api.load_policy_snapshot(linked_directory / "policy.json")


def test_loader_rejects_file_mutation_during_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.screening.offensive.v3.policy import loader

    policy_path = tmp_path / "policy.json"
    original = INITIAL_POLICY_PATH.read_bytes()
    policy_path.write_bytes(original)
    real_read = loader.os.read
    mutated = False

    def mutate_after_first_read(descriptor: int, size: int) -> bytes:
        nonlocal mutated
        chunk = real_read(descriptor, size)
        if chunk and not mutated:
            mutated = True
            policy_path.write_bytes(original)
        return chunk

    monkeypatch.setattr(loader.os, "read", mutate_after_first_read)

    with pytest.raises(loader.PolicyLoadError, match="changed"):
        loader.load_policy_snapshot(policy_path)


def test_loader_rejects_oversized_policy_before_parsing(tmp_path: Path) -> None:
    policy_api = _policy_api()
    policy_path = tmp_path / "oversized-policy.json"
    policy_path.write_bytes(
        (b" " * (1024 * 1024 + 1)) + INITIAL_POLICY_PATH.read_bytes()
    )

    with pytest.raises(policy_api.PolicyLoadError, match="too large"):
        policy_api.load_policy_snapshot(policy_path)


@pytest.mark.parametrize(
    "missing_flag",
    ["O_NOFOLLOW", "O_DIRECTORY", "O_CLOEXEC", "O_NONBLOCK"],
)
def test_loader_fails_closed_when_required_descriptor_flag_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_flag: str,
) -> None:
    from src.screening.offensive.v3.policy import loader

    policy_path = tmp_path / "policy.json"
    policy_path.write_bytes(INITIAL_POLICY_PATH.read_bytes())
    monkeypatch.delattr(loader.os, missing_flag)

    with pytest.raises(loader.PolicyLoadError, match=missing_flag):
        loader.load_policy_snapshot(policy_path)


@pytest.mark.filterwarnings("error::ResourceWarning")
def test_policy_loader_closes_leaf_if_parent_descriptor_close_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.screening.offensive.v3.policy import loader

    policy_path = tmp_path / "policy.json"
    policy_path.write_bytes(INITIAL_POLICY_PATH.read_bytes())
    real_open = loader.os.open
    real_close = loader.os.close
    leaf_descriptor: int | None = None
    parent_descriptor: int | None = None
    leaf_close_attempted = False
    parent_close_failed = False
    closed_descriptors: set[int] = set()

    def track_open(
        file: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal leaf_descriptor, parent_descriptor
        descriptor = real_open(file, flags, mode, dir_fd=dir_fd)
        if os.fspath(file) == policy_path.name and not flags & os.O_DIRECTORY:
            leaf_descriptor = descriptor
            parent_descriptor = dir_fd
        return descriptor

    def fail_parent_close_once(descriptor: int) -> None:
        nonlocal leaf_close_attempted, parent_close_failed
        if descriptor == leaf_descriptor:
            leaf_close_attempted = True
        if descriptor == parent_descriptor and not parent_close_failed:
            parent_close_failed = True
            raise OSError("simulated parent close failure")
        real_close(descriptor)
        closed_descriptors.add(descriptor)

    monkeypatch.setattr(loader.os, "open", track_open)
    monkeypatch.setattr(loader.os, "close", fail_parent_close_once)
    caught: Exception | None = None
    try:
        loader.load_policy_snapshot(policy_path)
    except Exception as exc:  # noqa: BLE001 - public-boundary assertion
        caught = exc
    finally:
        for descriptor in (leaf_descriptor, parent_descriptor):
            if descriptor is not None and descriptor not in closed_descriptors:
                try:
                    real_close(descriptor)
                except OSError:
                    pass

    assert (
        isinstance(caught, loader.PolicyLoadError),
        leaf_close_attempted,
    ) == (True, True)


@pytest.mark.filterwarnings("error::ResourceWarning")
def test_policy_loader_normalizes_leaf_close_failure_and_cleans_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.screening.offensive.v3.policy import loader

    policy_path = tmp_path / "policy.json"
    policy_path.write_bytes(INITIAL_POLICY_PATH.read_bytes())
    real_open = loader.os.open
    real_close = loader.os.close
    leaf_descriptor: int | None = None
    parent_descriptor: int | None = None
    leaf_close_failed = False
    parent_closed_after_failure = False
    closed_descriptors: set[int] = set()

    def track_open(
        file: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal leaf_descriptor, parent_descriptor
        descriptor = real_open(file, flags, mode, dir_fd=dir_fd)
        if os.fspath(file) == policy_path.name and not flags & os.O_DIRECTORY:
            leaf_descriptor = descriptor
            parent_descriptor = dir_fd
        return descriptor

    def fail_leaf_close_once(descriptor: int) -> None:
        nonlocal leaf_close_failed, parent_closed_after_failure
        if descriptor == leaf_descriptor and not leaf_close_failed:
            leaf_close_failed = True
            raise OSError("simulated leaf close failure")
        if descriptor == parent_descriptor and leaf_close_failed:
            parent_closed_after_failure = True
        real_close(descriptor)
        closed_descriptors.add(descriptor)

    monkeypatch.setattr(loader.os, "open", track_open)
    monkeypatch.setattr(loader.os, "close", fail_leaf_close_once)
    caught: Exception | None = None
    try:
        loader.load_policy_snapshot(policy_path)
    except Exception as exc:  # noqa: BLE001 - public-boundary assertion
        caught = exc
    finally:
        if leaf_descriptor is not None and leaf_descriptor not in closed_descriptors:
            try:
                real_close(leaf_descriptor)
            except OSError:
                pass

    assert isinstance(caught, loader.PolicyLoadError)
    assert (leaf_close_failed, parent_closed_after_failure) == (True, True)


@pytest.mark.filterwarnings("error::ResourceWarning")
def test_policy_loader_owns_parent_before_fstat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.screening.offensive.v3.policy import loader

    nested = tmp_path / "nested"
    nested.mkdir()
    policy_path = nested / "policy.json"
    policy_path.write_bytes(INITIAL_POLICY_PATH.read_bytes())
    real_open = loader.os.open
    real_close = loader.os.close
    real_fstat = loader.os.fstat
    target_descriptor: int | None = None
    target_close_attempted = False

    def track_open(
        file: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal target_descriptor
        descriptor = real_open(file, flags, mode, dir_fd=dir_fd)
        if os.fspath(file) == nested.name and flags & os.O_DIRECTORY:
            target_descriptor = descriptor
        return descriptor

    def fail_target_fstat(descriptor: int) -> os.stat_result:
        if descriptor == target_descriptor:
            raise OSError("simulated parent fstat failure")
        return real_fstat(descriptor)

    def track_close(descriptor: int) -> None:
        nonlocal target_close_attempted
        if descriptor == target_descriptor:
            target_close_attempted = True
        real_close(descriptor)

    monkeypatch.setattr(loader.os, "open", track_open)
    monkeypatch.setattr(loader.os, "fstat", fail_target_fstat)
    monkeypatch.setattr(loader.os, "close", track_close)
    try:
        with pytest.raises(loader.PolicyLoadError):
            loader.load_policy_snapshot(policy_path)
    finally:
        if target_descriptor is not None and not target_close_attempted:
            real_close(target_descriptor)

    assert target_close_attempted is True


@pytest.mark.filterwarnings("error::ResourceWarning")
def test_policy_loader_preserves_primary_read_error_when_leaf_close_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.screening.offensive.v3.policy import loader

    policy_path = tmp_path / "policy.json"
    policy_path.write_bytes(INITIAL_POLICY_PATH.read_bytes())
    real_open = loader.os.open
    real_close = loader.os.close
    real_read = loader.os.read
    leaf_descriptor: int | None = None
    leaf_close_failed = False

    def track_open(
        file: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal leaf_descriptor
        descriptor = real_open(file, flags, mode, dir_fd=dir_fd)
        if os.fspath(file) == policy_path.name and not flags & os.O_DIRECTORY:
            leaf_descriptor = descriptor
        return descriptor

    def fail_leaf_read(descriptor: int, size: int) -> bytes:
        if descriptor == leaf_descriptor:
            raise OSError("simulated policy read failure")
        return real_read(descriptor, size)

    def fail_leaf_close_once(descriptor: int) -> None:
        nonlocal leaf_close_failed
        if descriptor == leaf_descriptor and not leaf_close_failed:
            leaf_close_failed = True
            raise OSError("simulated leaf close failure")
        real_close(descriptor)

    monkeypatch.setattr(loader.os, "open", track_open)
    monkeypatch.setattr(loader.os, "read", fail_leaf_read)
    monkeypatch.setattr(loader.os, "close", fail_leaf_close_once)
    try:
        with pytest.raises(loader.PolicyLoadError, match="unable to read"):
            loader.load_policy_snapshot(policy_path)
    finally:
        if leaf_descriptor is not None:
            try:
                real_close(leaf_descriptor)
            except OSError:
                pass

    assert leaf_close_failed is True


@pytest.mark.filterwarnings("error::ResourceWarning")
def test_policy_loader_closes_leaf_after_fstat_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.screening.offensive.v3.policy import loader

    policy_path = tmp_path / "policy.json"
    policy_path.write_bytes(INITIAL_POLICY_PATH.read_bytes())
    real_open = loader.os.open
    real_close = loader.os.close
    real_fstat = loader.os.fstat
    leaf_descriptor: int | None = None
    leaf_close_attempted = False

    def track_open(
        file: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal leaf_descriptor
        descriptor = real_open(file, flags, mode, dir_fd=dir_fd)
        if os.fspath(file) == policy_path.name and not flags & os.O_DIRECTORY:
            leaf_descriptor = descriptor
        return descriptor

    def fail_leaf_fstat(descriptor: int) -> os.stat_result:
        if descriptor == leaf_descriptor:
            raise OSError("simulated leaf fstat failure")
        return real_fstat(descriptor)

    def track_close(descriptor: int) -> None:
        nonlocal leaf_close_attempted
        if descriptor == leaf_descriptor:
            leaf_close_attempted = True
        real_close(descriptor)

    monkeypatch.setattr(loader.os, "open", track_open)
    monkeypatch.setattr(loader.os, "fstat", fail_leaf_fstat)
    monkeypatch.setattr(loader.os, "close", track_close)

    with pytest.raises(loader.PolicyLoadError, match="unable to read"):
        loader.load_policy_snapshot(policy_path)

    assert leaf_close_attempted is True


def test_loader_does_not_consult_permissive_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy_api = _policy_api()
    path = tmp_path / "policy.json"
    _write_policy(path, _raw_initial_policy())
    expected = policy_api.load_policy_snapshot(path)
    permissive = {
        "V3_RUNTIME_MODE": "authoritative",
        "V3_PORTFOLIO_GROSS_CAP": "1",
        "V3_ADV_MISSING_FAIL_OPEN": "true",
        "DAILY_ACTION_DISABLED_SETUPS": "none",
        "DAILY_ACTION_REGIME_SIZING": "true",
        "DAILY_ACTION_STREAK_SIZING": "true",
    }
    for name, value in permissive.items():
        monkeypatch.setenv(name, value)

    loaded = policy_api.load_policy_snapshot(path)

    assert loaded == expected
    assert loaded.policy_fingerprint == expected.policy_fingerprint
    assert loaded.runtime_mode.value == "off"
    assert loaded.capital.portfolio_gross_cap == Decimal("0")
    assert loaded.producers.oversold_bounce_enabled is False


def test_off_policy_cannot_hide_nonzero_executable_risk(tmp_path: Path) -> None:
    policy_api = _policy_api()
    raw = _raw_initial_policy()
    raw["capital"]["portfolio_gross_cap"] = 0.02
    path = tmp_path / "policy.json"
    _write_policy(path, raw)

    with pytest.raises(policy_api.PolicyLoadError, match="off.*zero|zero.*off"):
        policy_api.load_policy_snapshot(path)


def test_policy_model_forbids_mutation_and_extra_fields() -> None:
    policy_api = _policy_api()
    policy = _initial_policy()

    with pytest.raises(ValidationError, match="frozen_instance"):
        policy.runtime_mode = policy_api.RuntimeMode.AUTHORITATIVE
    with pytest.raises(ValidationError, match="extra_forbidden"):
        policy_api.ProducerIdentity.model_validate(
            {
                "producer_namespace": "daily_action.btst",
                "strategy_semver": "3.0.0",
                "environment": dict(os.environ),
            }
        )


def test_fingerprints_revalidate_copied_policy_models() -> None:
    policy_api = _policy_api()
    policy = _initial_policy()
    producer = policy_api.ProducerIdentity(
        producer_namespace="daily_action.btst",
        strategy_semver="3.0.0",
    )
    invalid_capital = policy.capital.model_copy(
        update={"portfolio_gross_cap": Decimal("1")}
    )
    invalid_policy = policy.model_copy(update={"capital": invalid_capital})

    with pytest.raises(ValidationError, match="gross cap"):
        _ = invalid_policy.policy_fingerprint
    with pytest.raises(ValidationError, match="gross cap"):
        policy_api.behavior_fingerprint(producer, invalid_policy)
