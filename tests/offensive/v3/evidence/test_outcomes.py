"""Plan 03 Task 3: fail-closed Outcome Finalizer boundary."""

from __future__ import annotations

import hashlib
import inspect
from base64 import b64encode
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)
import pytest
import sqlalchemy as sa

from src.screening.offensive.v3 import trust
from src.screening.offensive.v3.contracts import (
    ExecutionMode,
    SUPPORTED_SCHEMA_MAJOR,
    canonical_json_bytes,
)
from src.screening.offensive.v3.contracts.governance import TrustBundle
from src.screening.offensive.v3.capital.fees import FeePolicy, FeeRevisionKind
from src.screening.offensive.v3.capital.fills import (
    FeeRevisionRequest,
    FillAttribution,
    FillRevisionRequest,
)
from src.screening.offensive.v3.capital.identity import AccountBinding
from src.screening.offensive.v3.capital.repository import (
    CapitalCommand,
    CapitalCommandPayload,
    CapitalRepository,
)
from src.screening.offensive.v3.contracts import (
    CashEconomicEventLeg,
    CashReceivableEconomicEventLeg,
    EconomicAssetKind,
    EconomicEventKind,
    EconomicLegDirection,
)
from src.screening.offensive.v3.evidence.blob_store import BlobStore
from src.screening.offensive.v3.evidence.dependency_fix import (
    DependencyFixError,
    DependencyFixLedger,
    DependencyFixManifest,
    FenceActivationGate,
)
from src.screening.offensive.v3.evidence.outcomes import (
    OutcomeFinalizer,
    OutcomeFinalizerError,
    PlanLineDefinition,
)
from src.screening.offensive.v3.evidence.repository import (
    EvidenceRepository,
    EvidenceStoreError,
)
from src.screening.offensive.v3.evidence.session_spine import (
    SessionEnrollment,
    SessionSpine,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)
HASH = "e" * 64
NAMESPACE = "evidence.outcomes.test"
PROGRAM = "prog-1"
LINEAGE = "lineage-outcome"
SIGNAL = date(2026, 6, 1)
SESSIONS = [SIGNAL + timedelta(days=offset) for offset in range(1, 13)]
ENTRY_SESSION = SESSIONS[0]
EXIT_SESSION = SESSIONS[9]

POLICY = FeePolicy(
    fee_policy_version="fee-schedule-2026-v1",
    commission_rate_ppm=3_000,
    min_commission_cents=500,
    stamp_tax_rate_ppm=1_000,
    transfer_fee_rate_ppm=20,
)
ATTRIBUTION = FillAttribution(
    producer_namespace="btst",
    research_program_id=PROGRAM,
    economic_lineage_id=LINEAGE,
    stage_id="stage-1",
)


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now_value = start

    def __call__(self) -> datetime:
        return self.now_value


def _public_key_b64(private_key: Ed25519PrivateKey) -> str:
    return b64encode(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")


def _root_context(registry):
    root_key = Ed25519PrivateKey.generate()
    root_public = _public_key_b64(root_key)
    root_hash = hashlib.sha256(
        root_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).hexdigest()
    anchor = trust.RootTrustAnchor(
        root_hash=root_hash,
        root_key_id="offline-root-1",
        public_key=root_public,
        valid_from=NOW - timedelta(days=30),
        valid_until=NOW + timedelta(days=30),
        revoked_at=None,
    )
    bundle = TrustBundle(
        registry_epoch=1,
        predecessor_bundle_hash="0" * 64,
        root_hash=root_hash,
        root_key_id=anchor.root_key_id,
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
    signed_bundle = trust.SignedTrustBundle(
        bundle=bundle, registry=registry, signature=signature
    )
    verifier = trust.TrustBundleVerifier((anchor,))
    delegate = trust.CapabilityVerifier(verifier, (signed_bundle,))
    head = trust.CurrentTrustHeadWitness(
        active_trust_bundle_hash=bundle.artifact_hash(),
        registry_epoch=bundle.registry_epoch,
        head_version=bundle.registry_epoch,
        store_version=1,
        observed_at=NOW,
    )

    class _HeadProvider:
        def current_trust_head(self, trusted_at):
            return head

    return delegate, _HeadProvider()


class _World:
    def __init__(self, tmp_path: Path) -> None:
        self.clock = _Clock(NOW)
        # Plan 02 capital ledger (read model for the finalizer). The
        # account binds implicitly on the first appended command.
        self.capital = CapitalRepository.initialize(
            tmp_path / "capital.sqlite3"
        )
        self._seed_cash(10_000_000, 0)
        # Session spine.
        self.spine = SessionSpine(
            database_path=str(tmp_path / "spine.sqlite3"),
            clock=self.clock,
        )
        self.spine.enroll_expected_sessions(
            tuple(
                SessionEnrollment(
                    research_program_id=PROGRAM,
                    signal_session=session,
                    assessment_date=session,
                )
                for session in SESSIONS
            )
            + (
                SessionEnrollment(
                    research_program_id=PROGRAM,
                    signal_session=SIGNAL,
                    assessment_date=SIGNAL,
                ),
            )
        )
        # Evidence store with an OUTCOME_FINALIZER issuer.
        self.finalizer_key = Ed25519PrivateKey.generate()
        self.broker_finalizer_key = Ed25519PrivateKey.generate()
        capability = trust.Capability(
            artifact=trust.ArtifactKind.OUTCOME,
            namespace=NAMESPACE,
            mode=ExecutionMode.DAILY_BAR_PROXY,
            schema_major=SUPPORTED_SCHEMA_MAJOR,
            capability_version="outcome-finalizer.v1",
            scope="evidence:outcomes.test",
            valid_from=NOW - timedelta(days=1),
            valid_until=NOW + timedelta(days=1),
            revoked_at=None,
        )
        broker_capability = capability.model_copy(
            update={
                "mode": ExecutionMode.BROKER_CONFIRMED,
                "capability_version": "outcome-finalizer.broker.v1",
                "scope": "evidence:outcomes.test:broker",
            }
        )
        issuer = trust.TrustedIssuer(
            issuer_id="outcome.finalizer",
            key_id="finalizer-key-1",
            issuer_kind=trust.IssuerKind.OUTCOME_FINALIZER,
            public_key=_public_key_b64(self.finalizer_key),
            valid_from=NOW - timedelta(days=1),
            valid_until=NOW + timedelta(days=1),
            revoked_at=None,
            capabilities=(capability,),
        )
        broker_issuer = trust.TrustedIssuer(
            issuer_id="outcome.finalizer.broker",
            key_id="finalizer-broker-key-1",
            issuer_kind=trust.IssuerKind.OUTCOME_FINALIZER,
            public_key=_public_key_b64(self.broker_finalizer_key),
            valid_from=NOW - timedelta(days=1),
            valid_until=NOW + timedelta(days=1),
            revoked_at=None,
            capabilities=(broker_capability,),
        )
        verifier, head_provider = _root_context(
            trust.TrustedRegistry(issuers=(issuer, broker_issuer))
        )
        self.evidence = EvidenceRepository(
            database_path=str(tmp_path / "evidence.sqlite3"),
            blob_store=BlobStore(tmp_path / "blobs"),
            verifier=verifier,
            trust_head_provider=head_provider,
            issuer_namespace=NAMESPACE,
            clock=self.clock,
        )
        self._capability = capability
        self._broker_capability = broker_capability
        self.finalizer = OutcomeFinalizer(
            database_path=str(tmp_path / "finalizer.sqlite3"),
            capital_engine=self.capital.engine,
            evidence_repository=self.evidence,
            session_spine=self.spine,
            signer=self._sign,
            signer_capability=self._capability,
            clock=self.clock,
            issuer_namespace="outcome.finalizer",
            behavior_fingerprint=HASH,
            execution_mode=ExecutionMode.DAILY_BAR_PROXY,
        )

    def finalizer_for(
        self,
        database_path: Path,
        *,
        execution_mode: ExecutionMode,
        signer_mode: ExecutionMode | None = None,
        capital_engine=None,
        source_authority: str | None = None,
        capability_override=None,
    ) -> OutcomeFinalizer:
        resolved_signer_mode = signer_mode or execution_mode
        if resolved_signer_mode is ExecutionMode.BROKER_CONFIRMED:
            signer = self._sign_broker
            signer_capability = self._broker_capability
            issuer_namespace = "outcome.finalizer.broker"
        else:
            signer = self._sign
            signer_capability = self._capability
            issuer_namespace = "outcome.finalizer"
        return OutcomeFinalizer(
            database_path=str(database_path),
            capital_engine=capital_engine or self.capital.engine,
            evidence_repository=self.evidence,
            session_spine=self.spine,
            signer=signer,
            signer_capability=capability_override or signer_capability,
            clock=self.clock,
            issuer_namespace=source_authority or issuer_namespace,
            behavior_fingerprint=HASH,
            execution_mode=execution_mode,
        )

    def _sign(self, payload: bytes):
        return self._sign_with(
            payload,
            capability=self._capability,
            private_key=self.finalizer_key,
            issuer_id="outcome.finalizer",
            key_id="finalizer-key-1",
        )

    def _sign_broker(self, payload: bytes):
        return self._sign_with(
            payload,
            capability=self._broker_capability,
            private_key=self.broker_finalizer_key,
            issuer_id="outcome.finalizer.broker",
            key_id="finalizer-broker-key-1",
        )

    @staticmethod
    def _sign_with(
        payload: bytes,
        *,
        capability,
        private_key: Ed25519PrivateKey,
        issuer_id: str,
        key_id: str,
    ):
        digest = hashlib.sha256(payload).hexdigest()
        protected = canonical_json_bytes(
            {
                "artifact": capability.artifact,
                "capability_scope": capability.scope,
                "capability_version": capability.capability_version,
                "issuer_id": issuer_id,
                "key_id": key_id,
                "mode": capability.mode,
                "namespace": capability.namespace,
                "payload": b64encode(payload).decode("ascii"),
                "payload_hash": digest,
                "schema_major": capability.schema_major,
            }
        )
        signature = private_key.sign(protected)
        return trust.SignedEnvelope(
            issuer_id=issuer_id,
            key_id=key_id,
            schema_major=capability.schema_major,
            artifact=capability.artifact,
            namespace=capability.namespace,
            mode=capability.mode,
            capability_version=capability.capability_version,
            capability_scope=capability.scope,
            payload_hash=digest,
            payload=payload,
            signature=b64encode(signature).decode("ascii"),
        )

    def _seed_cash(self, cents: int, seq: int) -> None:
        from decimal import Decimal

        amount = Decimal(cents) / 100
        binding = self._binding()
        receivable_id = f"rcv-{seq}"
        self.capital.append_atomic(
            CapitalCommand(
                idempotency_key=f"declare-{seq}",
                account_binding=binding,
                expected_stream_version=self.capital.stream_version(),
                as_of=NOW,
                payload=CapitalCommandPayload(
                    event_kind=EconomicEventKind.DIVIDEND_RECEIVABLE,
                    effective_at=NOW,
                    source_authority="test.seed",
                    legs=(
                        CashReceivableEconomicEventLeg(
                            leg_id=f"declare-{seq}-r",
                            direction=EconomicLegDirection.CREDIT,
                            asset_kind=EconomicAssetKind.CASH_RECEIVABLE,
                            receivable_id=receivable_id,
                            security_id="000001.SZ",
                            cash_amount=amount,
                        ),
                    ),
                ),
            )
        )
        self.capital.append_atomic(
            CapitalCommand(
                idempotency_key=f"settle-{seq}",
                account_binding=binding,
                expected_stream_version=self.capital.stream_version(),
                as_of=NOW + timedelta(seconds=30),
                payload=CapitalCommandPayload(
                    event_kind=EconomicEventKind.DIVIDEND_CASH_SETTLED,
                    effective_at=NOW + timedelta(seconds=30),
                    source_authority="test.seed",
                    legs=(
                        CashReceivableEconomicEventLeg(
                            leg_id=f"settle-{seq}-r",
                            direction=EconomicLegDirection.DEBIT,
                            asset_kind=EconomicAssetKind.CASH_RECEIVABLE,
                            receivable_id=receivable_id,
                            security_id="000001.SZ",
                            cash_amount=amount,
                        ),
                        CashEconomicEventLeg(
                            leg_id=f"settle-{seq}-c",
                            direction=EconomicLegDirection.CREDIT,
                            asset_kind=EconomicAssetKind.CASH,
                            cash_amount=amount,
                        ),
                    ),
                ),
            )
        )

    def _binding(self) -> AccountBinding:
        return AccountBinding(
            portfolio_id="pf-finalize",
            mode=ExecutionMode.DAILY_BAR_PROXY,
            broker_account_id=None,
            base_currency="CNY",
            environment_fingerprint="ab" * 32,
        )

    def fill(
        self,
        execution_id: str,
        *,
        side,
        price_micros: int,
        quantity: int,
        effective_at: datetime,
        lot: str = "lot-1",
        revision: int = 1,
        revision_kind=None,
    ):
        kwargs = {}
        if revision_kind is not None:
            kwargs["revision_kind"] = revision_kind
        request = FillRevisionRequest(
            execution_id=execution_id,
            revision=revision,
            order_id=f"ord-{execution_id}",
            side=side,
            security_id="600000.SH",
            price_micros=price_micros,
            quantity=quantity,
            position_lineage_id=LINEAGE,
            economic_lot_id=lot,
            attribution=ATTRIBUTION,
            source_authority="broker.test",
            effective_at=effective_at,
            as_of=effective_at + timedelta(seconds=1),
            expected_stream_version=self.capital.stream_version(),
            **kwargs,
        )
        return self.capital.record_fill_revision(request)

    def fee(self, execution_id: str, *, effective_at: datetime) -> None:
        self.capital.record_fee_revision(
            FeeRevisionRequest(
                fill_execution_id=execution_id,
                revision=1,
                fee_policy=POLICY,
                source_authority="broker.test",
                effective_at=effective_at,
                as_of=effective_at + timedelta(seconds=2),
                expected_stream_version=self.capital.stream_version(),
            )
        )

    def plan_line(self, contract_key: str = "pl-1", **overrides):
        values = {
            "plan_line_economic_contract_key": contract_key,
            "producer_namespace": "btst",
            "economic_lineage_id": LINEAGE,
            "stage_id": "stage-1",
            "family_id": "btst.limit-up-breakout",
            "mode": ExecutionMode.DAILY_BAR_PROXY,
            "execution_version": "t1-open-t10-open.v1",
            "cost_version": "cn-a-share-costs.v1",
            "signal_session": SIGNAL,
            "entry_session_ordinal": 1,
            "exit_session_ordinal": 10,
        }
        values.update(overrides)
        return PlanLineDefinition(**values)


@pytest.fixture()
def world(tmp_path: Path) -> _World:
    return _World(tmp_path)


requires_future_outcome_authority = pytest.mark.skip(
    reason=(
        "future authority: outcome publication requires exact plan-line,"
        " calendar, reducer, and single-writer bindings"
    )
)


def _fence_gate(tmp_path: Path, *, activate: bool = True):
    ledger = DependencyFixLedger(
        str(tmp_path / "fence.sqlite3"), clock=world_clock()
    )
    manifest = DependencyFixManifest(
        dependency_fix_id="fence-outcome",
        revision_ordinal=1,
        plan_evidence_fence="a" * 64,
        trial_manifest_fence="b" * 64,
        target_policy_fence="c" * 64,
    )
    payload = manifest.model_dump_json().encode("utf-8")
    import hashlib
    from base64 import b64encode

    from src.screening.offensive.v3 import trust

    signed = trust.SignedEnvelope(
        issuer_id="governance.service",
        key_id="key-1",
        schema_major=2,
        artifact=trust.ArtifactKind.PLAN,
        namespace="governance.dependency-fix",
        mode=ExecutionMode.DAILY_BAR_PROXY,
        capability_version="governance.dependency-fix.v1",
        capability_scope="dependency-fix:outcome",
        payload_hash=hashlib.sha256(payload).hexdigest(),
        payload=payload,
        signature=b64encode(b"0" * 64).decode("ascii"),
    )
    ledger.submit(manifest, signed)
    if activate:
        for fence in manifest.fences():
            ledger.acknowledge_fence("fence-outcome", fence)
        ledger.activate("fence-outcome")
    return FenceActivationGate(ledger)


def world_clock():
    return _Clock(NOW)


ENTRY_TIME = datetime.combine(
    ENTRY_SESSION, datetime.min.time(), tzinfo=UTC
) + timedelta(hours=9, minutes=30)
EXIT_TIME = datetime.combine(
    EXIT_SESSION, datetime.min.time(), tzinfo=UTC
) + timedelta(hours=9, minutes=30)
DUE = EXIT_TIME + timedelta(hours=7)


@requires_future_outcome_authority
def test_filled_plan_line_finalizes_exactly_one_outcome(
    world: _World,
) -> None:
    world.fill(
        "exec-e",
        side=_side_entry(),
        price_micros=10_000_000,
        quantity=100,
        effective_at=ENTRY_TIME,
    )
    world.fee("exec-e", effective_at=ENTRY_TIME)
    world.fill(
        "exec-x",
        side=_side_exit(),
        price_micros=11_000_000,
        quantity=100,
        effective_at=EXIT_TIME,
        lot="lot-1",
    )
    definition = world.plan_line()
    world.finalizer.register_plan_line(definition)
    finalized = world.finalizer.finalize_due(DUE, program=PROGRAM)
    assert finalized == ("pl-1",)
    fact = world.finalizer.outcome_fact("pl-1")
    assert fact.classification == "FILLED"
    # T+1 entry / T+10 exit session ordinals.
    assert fact.entry_session == ENTRY_SESSION
    assert fact.exit_session == EXIT_SESSION
    # Realized = exit gross - entry gross - fees; raw closes never enter.
    assert fact.entry_gross_cents == 100_000
    assert fact.exit_gross_cents == 110_000
    assert fact.fees_cents > 0
    assert fact.realized_pnl_cents == (
        fact.exit_gross_cents - fact.entry_gross_cents - fact.fees_cents
    )
    assert (
        world.evidence.get("outcome:pl-1").evidence.family_id
        == definition.family_id
    )
    # Re-finalizing is idempotent: still exactly one outcome.
    assert world.finalizer.finalize_due(DUE, program=PROGRAM) == ()


@requires_future_outcome_authority
def test_absent_execution_fact_finalizes_as_unavailable(world: _World) -> None:
    definition = world.plan_line("pl-empty")
    world.finalizer.register_plan_line(definition)
    finalized = world.finalizer.finalize_due(DUE, program=PROGRAM)
    assert finalized == ("pl-empty",)
    fact = world.finalizer.outcome_fact("pl-empty")
    assert fact.classification == "UNAVAILABLE"
    assert fact.realized_pnl_cents is None


@requires_future_outcome_authority
def test_exit_pending_stays_unfinalized_until_late_exit_lands(
    world: _World,
) -> None:
    world.fill(
        "exec-e",
        side=_side_entry(),
        price_micros=10_000_000,
        quantity=100,
        effective_at=ENTRY_TIME,
    )
    world.finalizer.register_plan_line(world.plan_line("pl-pending"))
    # Due date passed but no exit yet: nothing finalizes.
    assert world.finalizer.finalize_due(DUE, program=PROGRAM) == ()
    # A late exit (effective at T+10, ingested afterwards) is legitimate.
    world.fill(
        "exec-x",
        side=_side_exit(),
        price_micros=11_000_000,
        quantity=100,
        effective_at=EXIT_TIME,
    )
    finalized = world.finalizer.finalize_due(
        DUE + timedelta(days=1), program=PROGRAM
    )
    assert finalized == ("pl-pending",)
    fact = world.finalizer.outcome_fact("pl-pending")
    assert fact.classification == "FILLED"


@requires_future_outcome_authority
def test_mode_pure_excludes_other_mode_fills(
    world: _World,
    tmp_path: Path,
) -> None:
    world.fill(
        "exec-e",
        side=_side_entry(),
        price_micros=10_000_000,
        quantity=100,
        effective_at=ENTRY_TIME,
    )
    # The plan line runs under BROKER_CONFIRMED; the fills above are
    # DAILY_BAR_PROXY and must not enter this outcome.
    definition = world.plan_line(
        "pl-broker", mode=ExecutionMode.BROKER_CONFIRMED
    )
    broker_finalizer = world.finalizer_for(
        tmp_path / "broker-finalizer.sqlite3",
        execution_mode=ExecutionMode.BROKER_CONFIRMED,
    )
    broker_finalizer.register_plan_line(definition)
    assert broker_finalizer.finalize_due(DUE, program=PROGRAM) == (
        "pl-broker",
    )
    fact = broker_finalizer.outcome_fact("pl-broker")
    # Absence of an exact-mode execution fact is not proof of NO_FILL.
    assert fact.classification == "UNAVAILABLE"
    record = world.evidence.get("outcome:pl-broker")
    assert record.evidence.mode is ExecutionMode.BROKER_CONFIRMED


def test_register_rejects_plan_line_from_another_execution_mode(
    world: _World,
) -> None:
    foreign = world.plan_line(
        "pl-foreign-register",
        mode=ExecutionMode.BROKER_CONFIRMED,
    )

    with pytest.raises(OutcomeFinalizerError) as excinfo:
        world.finalizer.register_plan_line(foreign)

    assert excinfo.value.code == "execution_mode_mismatch"
    assert excinfo.value.details == {
        "expected_mode": ExecutionMode.DAILY_BAR_PROXY.value,
        "actual_mode": ExecutionMode.BROKER_CONFIRMED.value,
    }
    world.finalizer.register_plan_line(world.plan_line("pl-foreign-register"))


def test_register_rejects_non_enum_mode_with_typed_error(world: _World) -> None:
    invalid = world.plan_line("pl-invalid-mode")
    object.__setattr__(invalid, "mode", "daily_bar_proxy")

    with pytest.raises(OutcomeFinalizerError) as excinfo:
        world.finalizer.register_plan_line(invalid)

    assert excinfo.value.code == "execution_mode_invalid"


def test_registered_plan_line_is_database_immutable(world: _World) -> None:
    world.finalizer.register_plan_line(world.plan_line("pl-db-immutable"))

    for mutation in (
        "UPDATE plan_lines SET stage_id = 'tampered'",
        "DELETE FROM plan_lines",
    ):
        with pytest.raises(sa.exc.IntegrityError):
            with world.finalizer._engine.begin() as conn:
                conn.execute(sa.text(mutation))


class _PoisonDependency:
    """Any interaction proves the unavailable gate was not the first action."""

    def __getattr__(self, name: str):
        raise AssertionError(f"unexpected dependency access: {name}")

    def __call__(self, *_args, **_kwargs):
        raise AssertionError("unexpected dependency call")


def _poison_outcome_dependencies(finalizer: OutcomeFinalizer) -> None:
    poison = _PoisonDependency()
    finalizer._engine = poison
    finalizer._capital_engine = poison
    finalizer._evidence = poison
    finalizer._spine = poison
    finalizer._signer = poison
    finalizer._clock = poison


def test_finalize_due_is_disabled_before_every_dependency(world: _World) -> None:
    _poison_outcome_dependencies(world.finalizer)

    with pytest.raises(OutcomeFinalizerError) as excinfo:
        world.finalizer.finalize_due(DUE, program=PROGRAM)

    assert excinfo.value.code == "outcome_input_authority_unavailable"


def test_revise_outcome_is_disabled_before_fence_and_every_dependency(
    world: _World,
) -> None:
    _poison_outcome_dependencies(world.finalizer)
    poison_gate = _PoisonDependency()

    with pytest.raises(OutcomeFinalizerError) as excinfo:
        world.finalizer.revise_outcome(
            "pl-never-read",
            program=PROGRAM,
            activation_gate=poison_gate,
            fence_manifest_id="must-not-be-read",
        )

    assert excinfo.value.code == "outcome_input_authority_unavailable"


def test_outcome_fact_is_disabled_before_every_dependency(world: _World) -> None:
    _poison_outcome_dependencies(world.finalizer)

    with pytest.raises(OutcomeFinalizerError) as excinfo:
        world.finalizer.outcome_fact("pl-never-read")

    assert excinfo.value.code == "outcome_input_authority_unavailable"


def test_disabled_finalizer_has_no_publication_implementation() -> None:
    source = inspect.getsource(OutcomeFinalizer)

    for forbidden in (
        "outcome_publication_intents",
        ".persist_payload(",
        ".publish(",
        ".prepare_revision(",
        ".activate_revision(",
    ):
        assert forbidden not in source


def test_local_finalized_marker_cannot_enable_historical_reads(
    world: _World,
) -> None:
    definition = world.plan_line("pl-marker-only")
    world.finalizer.register_plan_line(definition)
    with world.finalizer._engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO finalized_plan_lines ("
                " plan_line_economic_contract_key, outcome_evidence_id,"
                " finality, revision, finalized_at)"
                " VALUES (:key, :evidence_id, :finality, :revision, :at)"
            ),
            {
                "key": definition.plan_line_economic_contract_key,
                "evidence_id": "outcome:pl-marker-only",
                "finality": "FILLED",
                "revision": 1,
                "at": DUE.isoformat(),
            },
        )

    with pytest.raises(OutcomeFinalizerError) as excinfo:
        world.finalizer.outcome_fact("pl-marker-only")

    assert excinfo.value.code == "outcome_input_authority_unavailable"


def test_broker_finalizer_rejects_daily_signer_context(
    world: _World,
    tmp_path: Path,
) -> None:
    with pytest.raises(OutcomeFinalizerError) as excinfo:
        world.finalizer_for(
            tmp_path / "bad-signer-finalizer.sqlite3",
            execution_mode=ExecutionMode.BROKER_CONFIRMED,
            signer_mode=ExecutionMode.DAILY_BAR_PROXY,
        )

    assert excinfo.value.code == "signer_context_mismatch"
    assert excinfo.value.details["expected_mode"] == "broker_confirmed"
    assert excinfo.value.details["capability_mode"] == "daily_bar_proxy"
    assert not (tmp_path / "bad-signer-finalizer.sqlite3").exists()


def test_constructor_rejects_foreign_namespace_before_write(
    world: _World,
    tmp_path: Path,
) -> None:
    foreign_database = tmp_path / "foreign-namespace-finalizer.sqlite3"
    foreign_capability = world._capability.model_copy(
        update={"namespace": "evidence.somewhere-else"}
    )
    with pytest.raises(OutcomeFinalizerError) as namespace_error:
        world.finalizer_for(
            foreign_database,
            execution_mode=ExecutionMode.DAILY_BAR_PROXY,
            capability_override=foreign_capability,
        )
    assert namespace_error.value.code == "signer_context_mismatch"
    assert not foreign_database.exists()


@requires_future_outcome_authority
def test_signed_issuer_must_equal_outcome_source_authority(
    world: _World,
    tmp_path: Path,
) -> None:
    finalizer = world.finalizer_for(
        tmp_path / "spoofed-authority-finalizer.sqlite3",
        execution_mode=ExecutionMode.DAILY_BAR_PROXY,
        source_authority="spoofed.outcome.finalizer",
    )
    finalizer.register_plan_line(world.plan_line("pl-spoofed-authority"))

    with pytest.raises(OutcomeFinalizerError) as excinfo:
        finalizer.finalize_due(DUE, program=PROGRAM)

    assert excinfo.value.code == "signer_source_authority_mismatch"
    with pytest.raises(EvidenceStoreError) as missing:
        world.evidence.get("outcome:pl-spoofed-authority")
    assert missing.value.code == "evidence_unknown"


@requires_future_outcome_authority
def test_bust_after_finalization_appends_outcome_revision(
    world: _World, tmp_path: Path,
) -> None:
    world_tmp_path = tmp_path
    from src.screening.offensive.v3.contracts import ExecutionRevisionKind

    world.fill(
        "exec-e",
        side=_side_entry(),
        price_micros=10_000_000,
        quantity=100,
        effective_at=ENTRY_TIME,
    )
    world.fill(
        "exec-x",
        side=_side_exit(),
        price_micros=11_000_000,
        quantity=100,
        effective_at=EXIT_TIME,
    )
    world.finalizer.register_plan_line(world.plan_line("pl-bust"))
    assert world.finalizer.finalize_due(DUE, program=PROGRAM) == (
        "pl-bust",
    )
    assert world.finalizer.outcome_fact("pl-bust").classification == (
        "FILLED"
    )
    # The entry is busted after finalization: the outcome revises; the
    # original outcome record is preserved as revision 1.
    world.fill(
        "exec-e",
        side=_side_entry(),
        price_micros=10_000_000,
        quantity=100,
        effective_at=ENTRY_TIME,
        revision=2,
        revision_kind=ExecutionRevisionKind.BUSTED,
    )
    gate = _fence_gate(world_tmp_path)
    revision = world.finalizer.revise_outcome(
        "pl-bust",
        program=PROGRAM,
        activation_gate=gate,
        fence_manifest_id="fence-outcome",
    )
    assert revision == 2
    fact = world.finalizer.outcome_fact("pl-bust")
    assert fact.classification == "NO_FILL"
    assert fact.realized_pnl_cents is None
    # Nothing changed: a second revise is a no-op.
    assert world.finalizer.revise_outcome(
        "pl-bust",
        program=PROGRAM,
        activation_gate=gate,
        fence_manifest_id="fence-outcome",
    ) is None


@requires_future_outcome_authority
def test_multiple_partial_fills_count_one_outcome(world: _World) -> None:
    # Two partial entries build one lot, then two partial exits close it:
    # one plan-line contract, ONE mature outcome, never four samples.
    world.fill(
        "exec-e1",
        side=_side_entry(),
        price_micros=10_000_000,
        quantity=60,
        effective_at=ENTRY_TIME,
        lot="lot-a",
    )
    world.fill(
        "exec-e2",
        side=_side_entry(),
        price_micros=10_000_000,
        quantity=40,
        effective_at=ENTRY_TIME,
        lot="lot-a",
    )
    world.fill(
        "exec-x1",
        side=_side_exit(),
        price_micros=11_000_000,
        quantity=50,
        effective_at=EXIT_TIME,
        lot="lot-a",
    )
    world.fill(
        "exec-x2",
        side=_side_exit(),
        price_micros=11_000_000,
        quantity=50,
        effective_at=EXIT_TIME,
        lot="lot-a",
    )
    world.finalizer.register_plan_line(world.plan_line("pl-multi"))
    assert world.finalizer.finalize_due(DUE, program=PROGRAM) == (
        "pl-multi",
    )
    fact = world.finalizer.outcome_fact("pl-multi")
    assert fact.classification == "FILLED"
    assert fact.entry_quantity_units == 100
    assert fact.exit_quantity_units == 100
    store = world.evidence
    assert store.get("outcome:pl-multi").revision == 1


def test_plan_line_registration_is_immutable(world: _World) -> None:
    definition = world.plan_line("pl-dup")
    world.finalizer.register_plan_line(definition)
    with pytest.raises(OutcomeFinalizerError) as excinfo:
        world.finalizer.register_plan_line(definition)
    assert excinfo.value.code == "plan_line_already_registered"


@requires_future_outcome_authority
def test_same_lineage_plan_lines_only_receive_their_own_order_fees(
    world: _World,
) -> None:
    second_entry = datetime.combine(
        SESSIONS[1], datetime.min.time(), tzinfo=UTC
    ) + timedelta(hours=9, minutes=30)
    second_exit = datetime.combine(
        SESSIONS[10], datetime.min.time(), tzinfo=UTC
    ) + timedelta(hours=9, minutes=30)
    world.fill(
        "fee-a-entry",
        side=_side_entry(),
        price_micros=10_000_000,
        quantity=100,
        effective_at=ENTRY_TIME,
        lot="lot-fee-a",
    )
    world.fee("fee-a-entry", effective_at=ENTRY_TIME)
    world.fill(
        "fee-a-exit",
        side=_side_exit(),
        price_micros=11_000_000,
        quantity=100,
        effective_at=EXIT_TIME,
        lot="lot-fee-a",
    )
    world.fill(
        "fee-b-entry",
        side=_side_entry(),
        price_micros=20_000_000,
        quantity=100,
        effective_at=second_entry,
        lot="lot-fee-b",
    )
    world.fill(
        "fee-b-exit",
        side=_side_exit(),
        price_micros=21_000_000,
        quantity=100,
        effective_at=second_exit,
        lot="lot-fee-b",
    )
    world.finalizer.register_plan_line(world.plan_line("pl-fee-a"))
    world.finalizer.register_plan_line(
        world.plan_line("pl-fee-b", signal_session=SESSIONS[0])
    )

    assert world.finalizer.finalize_due(
        second_exit + timedelta(hours=7), program=PROGRAM
    ) == ("pl-fee-a", "pl-fee-b")
    assert world.finalizer.outcome_fact("pl-fee-a").fees_cents > 0
    assert world.finalizer.outcome_fact("pl-fee-b").fees_cents == 0


@requires_future_outcome_authority
def test_same_session_publication_order_is_contract_key_deterministic(
    world: _World,
) -> None:
    world.finalizer.register_plan_line(world.plan_line("pl-z"))
    world.finalizer.register_plan_line(world.plan_line("pl-a"))

    assert world.finalizer.finalize_due(DUE, program=PROGRAM) == (
        "pl-a",
        "pl-z",
    )
    assert (
        world.evidence.get("outcome:pl-a").commit_sequence
        < world.evidence.get("outcome:pl-z").commit_sequence
    )


def _side_entry():
    from src.screening.offensive.v3.contracts import ExecutionSide

    return ExecutionSide.ENTRY


def _side_exit():
    from src.screening.offensive.v3.contracts import ExecutionSide

    return ExecutionSide.EXIT


@requires_future_outcome_authority
def test_outcome_revision_requires_active_fence(
    world: _World, tmp_path: Path
) -> None:
    from src.screening.offensive.v3.contracts import ExecutionRevisionKind

    world.fill(
        "exec-e",
        side=_side_entry(),
        price_micros=10_000_000,
        quantity=100,
        effective_at=ENTRY_TIME,
    )
    world.fill(
        "exec-x",
        side=_side_exit(),
        price_micros=11_000_000,
        quantity=100,
        effective_at=EXIT_TIME,
    )
    world.finalizer.register_plan_line(world.plan_line("pl-fence"))
    world.finalizer.finalize_due(DUE, program=PROGRAM)
    world.fill(
        "exec-e",
        side=_side_entry(),
        price_micros=10_000_000,
        quantity=100,
        effective_at=ENTRY_TIME,
        revision=2,
        revision_kind=ExecutionRevisionKind.BUSTED,
    )
    pending_gate = _fence_gate(tmp_path, activate=False)
    with pytest.raises(DependencyFixError) as excinfo:
        world.finalizer.revise_outcome(
            "pl-fence",
            program=PROGRAM,
            activation_gate=pending_gate,
            fence_manifest_id="fence-outcome",
        )
    assert excinfo.value.code == "fence_not_active"
    # The outcome stays revision 1 (nothing activated).
    assert world.evidence.get("outcome:pl-fence").revision == 1
