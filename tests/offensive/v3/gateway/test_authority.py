"""Plan 04 Task 4: gateway authority activation and entry fences."""

from __future__ import annotations

from base64 import b64encode
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.screening.offensive.v3 import trust
from src.screening.offensive.v3.contracts import ExecutionMode, SignedEnvelope
from src.screening.offensive.v3.contracts.authorization import (
    AuthorizationKind,
    CapitalAuthorizationEnvelope,
)
from src.screening.offensive.v3.contracts.governance import (
    EntryFenceAcknowledgement,
    EntryFenceRaised,
    GrantKind,
    LineageGrant,
    PolicyActivation,
    ProgramLossBudgetBinding,
    TrustBundle,
)
from src.screening.offensive.v3.gateway.authority import (
    GatewayAuthorityError,
    GatewayAuthorityRepository,
    is_pure_tightening,
)
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)
HASH = "a" * 64
BEHAVIOR = "b" * 64
PORTFOLIO = "paper-v3"


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now_value = start

    def __call__(self) -> datetime:
        return self.now_value


class _ChainBundleVerifier:
    """Gateway-side bundle verifier over the root anchor chain."""

    def __init__(self, verifier: trust.TrustBundleVerifier) -> None:
        self._verifier = verifier

    def verify_signed_bundle(
        self, signed: SignedEnvelope, *, trusted_at: datetime
    ) -> TrustBundle:
        signed_bundle = trust.SignedTrustBundle.model_validate(
            signed.model_dump(mode="python")
        )
        verified = self._verifier.verify_chain(
            (signed_bundle,), trusted_at=trusted_at
        )
        return verified.bundle


def _public_key_b64(private_key: Ed25519PrivateKey) -> str:
    return b64encode(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")


def _signed_bundle(
    *, registry_epoch: int = 1, root_key=None, registry=None
):
    if root_key is None:
        root_key = Ed25519PrivateKey.generate()
    root_public = _public_key_b64(root_key)
    import hashlib

    root_hash = hashlib.sha256(
        root_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).hexdigest()
    if registry is None:
        registry = trust.TrustedRegistry(issuers=())
    bundle = TrustBundle(
        registry_epoch=registry_epoch,
        predecessor_bundle_hash="0" * 64,
        root_hash=root_hash,
        root_key_id="offline-root-1",
        trusted_issuer_registry_hash=registry.content_hash(),
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(days=1),
        revoked_at=None,
        issuer_id="offline-governance-root",
        issuer_capability="root.trust.bundle.v1",
        schema_major=2,
    )
    signature = b64encode(
        root_key.sign(trust.trust_bundle_signature_preimage(bundle, registry))
    ).decode("ascii")
    anchor = trust.RootTrustAnchor(
        root_hash=root_hash,
        root_key_id="offline-root-1",
        public_key=root_public,
        valid_from=NOW - timedelta(days=30),
        valid_until=NOW + timedelta(days=30),
        revoked_at=None,
    )
    verifier = trust.TrustBundleVerifier((anchor,))
    signed = trust.SignedTrustBundle(
        bundle=bundle, registry=registry, signature=signature
    )
    return signed, _ChainBundleVerifier(verifier), root_key


def _policy_activation(
    policy_epoch: int = 1, authority_epoch: int = 1
) -> PolicyActivation:
    return PolicyActivation(
        portfolio_id=PORTFOLIO,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        policy_snapshot_hash=HASH,
        predecessor_policy_activation_hash="0" * 64,
        trust_bundle_hash=HASH,
        registry_epoch=1,
        policy_epoch=policy_epoch,
        authority_epoch=authority_epoch,
        risk_epoch=1,
        effective_from=NOW,
        expires_at=NOW + timedelta(days=1),
        issuer_id="governance.service",
        issuer_capability="governance.policy.activation.v1",
        schema_major=2,
    )


def _grant(**overrides) -> LineageGrant:
    values = {
        "grant_id": "grant-1",
        "grant_kind": GrantKind.EDGE,
        "grant_certificate_hash": HASH,
        "grant_issuer_id": "authorizer.service",
        "subject_producer": "btst",
        "family_id": "btst.limit-up-breakout",
        "economic_lineage_id": "eline-1",
        "research_program_id": "prog-1",
        "behavior_fingerprint": BEHAVIOR,
        "execution_version": "t1-open-t10-open.v1",
        "cost_version": "cn-a-share-costs.v1",
        "capital_tier": 2,
        "lineage_gross_cap": Decimal("0.02"),
        "trial_id": "trial-1",
        "trial_manifest_hash": HASH,
        "statistical_analysis_plan_hash": HASH,
        "stage_id": "stage-1",
        "stage_manifest_hash": HASH,
        "stage_sample_reservation_id": "reservation-1",
        "stage_loss_budget_id": "budget-1",
        "stage_loss_budget_cents": 100_000,
        "stage_loss_version": 1,
        "assessment_result_hash": HASH,
        "grant_evidence_set_merkle_root": HASH,
        "attempt_ledger_checkpoint_hash": HASH,
        "alpha_or_evalue_budget_consumption_id": "consumption-1",
        "alpha_sample_consumption_id": "sample-1",
        "schema_major": 2,
    }
    values.update(overrides)
    return LineageGrant(**values)


def _binding() -> ProgramLossBudgetBinding:
    return ProgramLossBudgetBinding(
        research_program_id="prog-1",
        budget_id="budget-1",
        budget_cents=100_000,
        consumed_cents=0,
        version=1,
        schema_major=2,
    )


def _envelope(
    policy_activation: PolicyActivation,
    *,
    authorization_id="auth-1",
    authorization_version=1,
    grants=None,
    portfolio_gross_cap=Decimal("0.02"),
    exploration_cap=Decimal("0"),
) -> CapitalAuthorizationEnvelope:
    return CapitalAuthorizationEnvelope(
        authorization_kind=AuthorizationKind.EDGE,
        authorization_id=authorization_id,
        authorization_version=authorization_version,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        portfolio_id=PORTFOLIO,
        broker_account_id=None,
        broker_account_fingerprint=None,
        base_currency="CNY",
        policy_activation_hash=policy_activation.artifact_hash(),
        trust_bundle_hash=HASH,
        registry_epoch=1,
        policy_epoch=policy_activation.policy_epoch,
        authority_epoch=policy_activation.authority_epoch,
        risk_epoch=1,
        research_program_ids=("prog-1",),
        baseline_portfolio_policy_fingerprint=HASH,
        target_portfolio_policy_fingerprint="c" * 64,
        lineage_grants=(grants if grants is not None else (_grant(),)),
        evidence_as_of=NOW,
        evidence_set_merkle_root=HASH,
        issued_at=NOW,
        expires_at=NOW + timedelta(days=1),
        activation_capital_snapshot_id="snapshot-1",
        activation_capital_snapshot_hash=HASH,
        portfolio_gross_cap=portfolio_gross_cap,
        exploration_aggregate_gross_cap=exploration_cap,
        program_loss_budget_bindings=(_binding(),),
        issuer_id="authorizer.service",
        issuer_capability="authorizer.edge.envelope.v1",
        portfolio_assessment_result_hash=HASH,
        global_attempt_ledger_checkpoint_hash=HASH,
        global_multiplicity_budget_consumption_id="consumption-1",
        schema_major=2,
    )


def _fence(
    fence_id="fence-1",
    *,
    fence_version=1,
    raised_at=None,
) -> EntryFenceRaised:
    return EntryFenceRaised(
        fence_id=fence_id,
        portfolio_id=PORTFOLIO,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        fence_version=fence_version,
        predecessor_fence_hash="0" * 64,
        trust_bundle_hash=HASH,
        registry_epoch=1,
        policy_activation_hash=HASH,
        policy_epoch=1,
        authority_epoch=1,
        risk_epoch=1,
        predecessor_authorization_status_hash=HASH,
        authorization_status_version=1,
        reason="entry correction requires fence",
        cause_revision_id="revision-1",
        cause_revision_hash=HASH,
        raised_at=raised_at or NOW,
        affected_authorization_id=None,
        affected_authorization_version=None,
        affected_authorization_envelope_hash=None,
        affected_evidence_set_merkle_root=None,
        issuer_id="dependency.tracker",
        issuer_capability="dependency-tracker.entry-fence.raise.v1",
        schema_major=2,
    )


def _ack(
    fence: EntryFenceRaised,
    *,
    ack_id="ack-1",
    acknowledged_at=None,
) -> EntryFenceAcknowledgement:
    return EntryFenceAcknowledgement(
        acknowledgement_id=ack_id,
        fence_id=fence.fence_id,
        entry_fence_hash=fence.artifact_hash(),
        fence_version=fence.fence_version,
        portfolio_id=PORTFOLIO,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        authority_epoch=1,
        risk_epoch=1,
        authorization_status_hash=HASH,
        authorization_status_version=2,
        fence_raised_at=fence.raised_at,
        durably_acknowledged_at=acknowledged_at
        or (fence.raised_at + timedelta(minutes=1)),
        gateway_writer_id="gateway-1",
        gateway_writer_version=1,
        gateway_fencing_epoch=1,
        issuer_id="capital.gateway",
        issuer_capability="capital-gateway.entry-fence.acknowledge.v1",
        schema_major=2,
    )


@pytest.fixture()
def gateway(tmp_path):
    clock = _Clock(NOW)
    repo = GatewayAuthorityRepository(
        database_path=str(tmp_path / "gateway.sqlite3"),
        mode=ExecutionMode.DAILY_BAR_PROXY,
        broker_account_id=None,
        bundle_verifier=_signed_bundle()[1],
        clock=clock,
    )
    return repo, clock


def test_trust_bundle_activation_is_monotonic(gateway) -> None:
    repo, _ = gateway
    signed, verifier, root_key = _signed_bundle(registry_epoch=1)
    repo._bundle_verifier = verifier
    bundle = repo.activate_trust_bundle(signed, trusted_at=NOW)
    assert bundle.registry_epoch == 1
    # Same epoch again is a rollback/repeat: rejected.
    signed_again, verifier2, _ = _signed_bundle(
        registry_epoch=1, root_key=root_key
    )
    repo._bundle_verifier = verifier2
    with pytest.raises(GatewayAuthorityError) as excinfo:
        repo.activate_trust_bundle(signed_again, trusted_at=NOW)
    assert excinfo.value.code == "registry_epoch_rollback"


def test_invalid_bundle_signature_is_rejected(gateway) -> None:
    repo, _ = gateway
    signed, verifier, _ = _signed_bundle(registry_epoch=1)
    # A verifier anchored on a DIFFERENT root rejects the signature.
    _, other_verifier, _ = _signed_bundle(registry_epoch=99)
    repo._bundle_verifier = other_verifier
    with pytest.raises(Exception):
        repo.activate_trust_bundle(signed, trusted_at=NOW)


def test_policy_and_envelope_activate_jointly(gateway) -> None:
    repo, _ = gateway
    policy = _policy_activation()
    envelope = _envelope(policy)
    repo.activate_policy_and_envelope(policy, envelope)
    state = repo.active_state(PORTFOLIO)
    assert state.active_authorization_id == "auth-1"
    assert state.active_authorization_version == 1
    assert state.active_envelope_hash == envelope.artifact_hash()
    assert state.policy_activation_hash == policy.artifact_hash()


def test_policy_envelope_fingerprint_mismatch_is_rejected(gateway) -> None:
    repo, _ = gateway
    policy = _policy_activation()
    other_policy = _policy_activation(policy_epoch=2)
    envelope = _envelope(policy)
    with pytest.raises(GatewayAuthorityError) as excinfo:
        repo.activate_policy_and_envelope(other_policy, envelope)
    assert excinfo.value.code == "policy_envelope_fingerprint_mismatch"


def test_wrong_mode_is_rejected(gateway) -> None:
    repo, _ = gateway
    policy = _policy_activation()
    broker_envelope = _envelope(policy).model_copy(
        update={
            "mode": ExecutionMode.MANUAL_CONFIRMED,
            "broker_account_id": "acct-1",
            "broker_account_fingerprint": HASH,
        }
    )
    with pytest.raises(GatewayAuthorityError) as excinfo:
        repo.activate_policy_and_envelope(policy, broker_envelope)
    assert excinfo.value.code == "mode_mismatch"


def test_epoch_rollback_is_rejected(gateway) -> None:
    repo, _ = gateway
    policy = _policy_activation(policy_epoch=5, authority_epoch=5)
    repo.activate_policy_and_envelope(policy, _envelope(policy))
    old_policy = _policy_activation(policy_epoch=4, authority_epoch=6)
    with pytest.raises(GatewayAuthorityError) as excinfo:
        repo.activate_policy_and_envelope(
            old_policy,
            _envelope(old_policy, authorization_id="auth-old"),
        )
    assert excinfo.value.code == "policy_epoch_rollback"


def test_second_active_envelope_is_rejected(gateway) -> None:
    repo, _ = gateway
    policy = _policy_activation()
    repo.activate_policy_and_envelope(policy, _envelope(policy))
    policy2 = _policy_activation(policy_epoch=2, authority_epoch=2)
    with pytest.raises(GatewayAuthorityError) as excinfo:
        repo.activate_policy_and_envelope(
            policy2,
            _envelope(policy2, authorization_id="auth-2"),
        )
    assert excinfo.value.code == "envelope_already_active"


def test_pure_tightening_replaces_alone(gateway) -> None:
    repo, _ = gateway
    policy = _policy_activation()
    envelope = _envelope(policy)
    repo.activate_policy_and_envelope(policy, envelope)
    tightened = _envelope(
        policy,
        authorization_id="auth-tight",
        authorization_version=2,
        portfolio_gross_cap=Decimal("0.01"),
        grants=(
            _grant(capital_tier=2, lineage_gross_cap=Decimal("0.01")),
        ),
    )
    assert is_pure_tightening(envelope, tightened)
    repo.replace_envelope(envelope, tightened)
    state = repo.active_state(PORTFOLIO)
    assert state.active_authorization_id == "auth-tight"
    assert state.active_authorization_version == 2


def test_fake_tightening_adding_behavior_is_rejected(gateway) -> None:
    repo, _ = gateway
    policy = _policy_activation()
    envelope = _envelope(policy)
    repo.activate_policy_and_envelope(policy, envelope)
    sneaky = _envelope(
        policy,
        authorization_id="auth-sneaky",
        authorization_version=2,
        grants=(
            _grant(),
            _grant(
                grant_id="grant-2",
                grant_certificate_hash="d" * 64,
                economic_lineage_id="eline-2",
                stage_id="stage-2",
                stage_manifest_hash="f" * 64,
                stage_loss_budget_id="budget-2",
                assessment_result_hash="e" * 64,
                stage_sample_reservation_id="reservation-2",
                attempt_ledger_checkpoint_hash="f1" * 32,
                alpha_or_evalue_budget_consumption_id="consumption-2",
                alpha_sample_consumption_id="sample-2",
            ),
        ),
    )
    assert not is_pure_tightening(envelope, sneaky)
    with pytest.raises(GatewayAuthorityError) as excinfo:
        repo.replace_envelope(envelope, sneaky)
    assert excinfo.value.code == "behavior_change_requires_joint_activation"


def test_concurrent_replacement_one_wins(gateway) -> None:
    repo, _ = gateway
    policy = _policy_activation()
    envelope = _envelope(policy)
    repo.activate_policy_and_envelope(policy, envelope)
    tightened_grants = (
        _grant(capital_tier=2, lineage_gross_cap=Decimal("0.015")),
    )
    first = _envelope(
        policy,
        authorization_id="auth-first",
        authorization_version=2,
        portfolio_gross_cap=Decimal("0.015"),
        grants=tightened_grants,
    )
    second = _envelope(
        policy,
        authorization_id="auth-second",
        authorization_version=2,
        portfolio_gross_cap=Decimal("0.01"),
        grants=(
            _grant(capital_tier=2, lineage_gross_cap=Decimal("0.01")),
        ),
    )
    repo.replace_envelope(envelope, first)
    # The second replacement still holds the OLD envelope: CAS conflict.
    with pytest.raises(GatewayAuthorityError) as excinfo:
        repo.replace_envelope(envelope, second)
    assert excinfo.value.code == "envelope_cas_conflict"


def test_concurrent_replacement_never_yields_two_active(
    tmp_path,
) -> None:
    # Real concurrency (threading.Barrier), not the serial simulation above:
    # two dispatchers both read the same ACTIVE envelope and race to
    # SUPERSEDE it. The rowcount guard plus the partial unique index on
    # ACTIVE rows must leave exactly one ACTIVE envelope either way.
    import threading

    db_path = str(tmp_path / "gateway-race.sqlite3")
    clock = _Clock(NOW)
    setup = GatewayAuthorityRepository(
        database_path=db_path,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        broker_account_id=None,
        bundle_verifier=None,
        clock=clock,
    )
    policy = _policy_activation()
    envelope = _envelope(policy)
    setup.activate_policy_and_envelope(policy, envelope)
    first = _envelope(
        policy,
        authorization_id="auth-race-first",
        authorization_version=2,
        portfolio_gross_cap=Decimal("0.015"),
        grants=(
            _grant(capital_tier=2, lineage_gross_cap=Decimal("0.015")),
        ),
    )
    second = _envelope(
        policy,
        authorization_id="auth-race-second",
        authorization_version=2,
        portfolio_gross_cap=Decimal("0.01"),
        grants=(
            _grant(capital_tier=2, lineage_gross_cap=Decimal("0.01")),
        ),
    )
    barrier = threading.Barrier(2)
    outcomes: list[str] = [None, None]

    def worker(idx: int, replacement) -> None:
        repo = GatewayAuthorityRepository(
            database_path=db_path,
            mode=ExecutionMode.DAILY_BAR_PROXY,
            broker_account_id=None,
            bundle_verifier=None,
            clock=clock,
        )
        barrier.wait()
        try:
            repo.replace_envelope(envelope, replacement)
            outcomes[idx] = "replaced"
        except GatewayAuthorityError as exc:
            outcomes[idx] = exc.code

    threads = [
        threading.Thread(target=worker, args=(0, first)),
        threading.Thread(target=worker, args=(1, second)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    winners = [outcome for outcome in outcomes if outcome == "replaced"]
    # The race may be won by exactly one writer (the other fails its CAS),
    # or - when the SQLite snapshot serializes the writes - by one writer
    # with the other hitting the unique-index conflict. Two winners must be
    # impossible; every outcome must be a clean conflict or success.
    assert len(winners) == 1, outcomes
    final = GatewayAuthorityRepository(
        database_path=db_path,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        broker_account_id=None,
        bundle_verifier=None,
        clock=clock,
    )
    with final._engine.connect() as conn:
        rows = final._active_envelope_row(conn, envelope.portfolio_id)
    assert rows is not None
    assert rows[0] in {"auth-race-first", "auth-race-second"}


def test_fence_raise_is_idempotent_and_fences_portfolio(gateway) -> None:
    repo, _ = gateway
    policy = _policy_activation()
    envelope = _envelope(policy)
    repo.activate_policy_and_envelope(policy, envelope)
    fence = _fence()
    before = repo.active_state(PORTFOLIO)
    repo.raise_entry_fence(fence)
    repo.raise_entry_fence(fence)  # idempotent identical retry
    state = repo.active_state(PORTFOLIO)
    assert state.fencing_epoch == before.fencing_epoch + 1
    assert state.authorization_status_version == (
        before.authorization_status_version + 1
    )
    # The active envelope is FENCED: no active envelope remains, so no
    # new seal can issue; the fence never touches exits.
    assert state.active_authorization_id is None
    assert state.open_fence_count == 1


def test_fence_identity_conflict_is_rejected(gateway) -> None:
    repo, _ = gateway
    fence = _fence()
    repo.raise_entry_fence(fence)
    different = _fence(fence_version=2)
    with pytest.raises(GatewayAuthorityError) as excinfo:
        repo.raise_entry_fence(different)
    assert excinfo.value.code == "fence_identity_conflict"


def test_ack_requires_committed_fence(gateway) -> None:
    repo, _ = gateway
    fence = _fence()
    ack = _ack(fence)
    with pytest.raises(GatewayAuthorityError) as excinfo:
        repo.acknowledge_fence(ack)
    assert excinfo.value.code == "fence_unknown"


def test_ack_lands_after_commit_and_is_idempotent(gateway) -> None:
    repo, _ = gateway
    fence = _fence()
    repo.raise_entry_fence(fence)
    ack = _ack(fence)
    before = repo.active_state(PORTFOLIO)
    repo.acknowledge_fence(ack)
    repo.acknowledge_fence(ack)  # idempotent identical retry
    state = repo.active_state(PORTFOLIO)
    assert state.authorization_status_version == (
        before.authorization_status_version + 1
    )
    assert state.open_fence_count == 0


def test_ack_with_wrong_fence_hash_is_rejected(gateway) -> None:
    repo, _ = gateway
    fence = _fence()
    repo.raise_entry_fence(fence)
    ack = _ack(fence).model_copy(update={"entry_fence_hash": "f" * 64})
    with pytest.raises(GatewayAuthorityError) as excinfo:
        repo.acknowledge_fence(ack)
    assert excinfo.value.code == "fence_hash_mismatch"


def test_fence_does_not_touch_policy_activations(gateway) -> None:
    repo, _ = gateway
    policy = _policy_activation()
    envelope = _envelope(policy)
    repo.activate_policy_and_envelope(policy, envelope)
    import sqlalchemy as sa

    with repo._engine.connect() as conn:
        before = conn.execute(
            sa.text("SELECT COUNT(*) AS n FROM policy_activations")
        ).one().n
    repo.raise_entry_fence(_fence())
    with repo._engine.connect() as conn:
        after = conn.execute(
            sa.text("SELECT COUNT(*) AS n FROM policy_activations")
        ).one().n
    # Entry fencing never alters policy activations (and exits, which key
    # off capital truth, are not represented here at all).
    assert before == after == 1
