"""Plan 03 Task 3: Outcome Finalizer over Plan 02 capital truth."""

from __future__ import annotations

from base64 import b64encode
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import hashlib

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)
import pytest

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
from src.screening.offensive.v3.evidence.outcomes import (
    OutcomeFinalizer,
    OutcomeFinalizerError,
    PlanLineDefinition,
)
from src.screening.offensive.v3.evidence.repository import (
    EvidenceRepository,
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
        verifier, head_provider = _root_context(
            trust.TrustedRegistry(issuers=(issuer,))
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
        self.finalizer = OutcomeFinalizer(
            database_path=str(tmp_path / "finalizer.sqlite3"),
            capital_engine=self.capital.engine,
            evidence_repository=self.evidence,
            session_spine=self.spine,
            signer=self._sign,
            clock=self.clock,
            issuer_namespace="outcome.finalizer",
            behavior_fingerprint=HASH,
        )

    def _sign(self, payload: bytes):
        digest = hashlib.sha256(payload).hexdigest()
        protected = canonical_json_bytes(
            {
                "artifact": self._capability.artifact,
                "capability_scope": self._capability.scope,
                "capability_version": self._capability.capability_version,
                "issuer_id": "outcome.finalizer",
                "key_id": "finalizer-key-1",
                "mode": self._capability.mode,
                "namespace": self._capability.namespace,
                "payload": b64encode(payload).decode("ascii"),
                "payload_hash": digest,
                "schema_major": self._capability.schema_major,
            }
        )
        signature = self.finalizer_key.sign(protected)
        return trust.SignedEnvelope(
            issuer_id="outcome.finalizer",
            key_id="finalizer-key-1",
            schema_major=self._capability.schema_major,
            artifact=self._capability.artifact,
            namespace=self._capability.namespace,
            mode=self._capability.mode,
            capability_version=self._capability.capability_version,
            capability_scope=self._capability.scope,
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


ENTRY_TIME = datetime.combine(
    ENTRY_SESSION, datetime.min.time(), tzinfo=UTC
) + timedelta(hours=9, minutes=30)
EXIT_TIME = datetime.combine(
    EXIT_SESSION, datetime.min.time(), tzinfo=UTC
) + timedelta(hours=9, minutes=30)
DUE = EXIT_TIME + timedelta(hours=7)


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
    # Re-finalizing is idempotent: still exactly one outcome.
    assert world.finalizer.finalize_due(DUE, program=PROGRAM) == ()


def test_no_fill_line_finalizes_as_no_fill(world: _World) -> None:
    definition = world.plan_line("pl-empty")
    world.finalizer.register_plan_line(definition)
    finalized = world.finalizer.finalize_due(DUE, program=PROGRAM)
    assert finalized == ("pl-empty",)
    fact = world.finalizer.outcome_fact("pl-empty")
    assert fact.classification == "NO_FILL"
    assert fact.realized_pnl_cents is None


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


def test_mode_pure_excludes_other_mode_fills(world: _World) -> None:
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
    world.finalizer.register_plan_line(definition)
    assert world.finalizer.finalize_due(DUE, program=PROGRAM) == (
        "pl-broker",
    )
    fact = world.finalizer.outcome_fact("pl-broker")
    assert fact.classification == "NO_FILL"


def test_bust_after_finalization_appends_outcome_revision(
    world: _World,
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
    revision = world.finalizer.revise_outcome("pl-bust", program=PROGRAM)
    assert revision == 2
    fact = world.finalizer.outcome_fact("pl-bust")
    assert fact.classification == "NO_FILL"
    assert fact.realized_pnl_cents is None
    # Nothing changed: a second revise is a no-op.
    assert world.finalizer.revise_outcome(
        "pl-bust", program=PROGRAM
    ) is None


def test_unavailable_calendar_finalizes_unavailable(world: _World) -> None:
    # A signal with only three sessions after it cannot supply T+1/T+10.
    definition = world.plan_line(
        "pl-short",
        signal_session=SESSIONS[8],
    )
    world.finalizer.register_plan_line(definition)
    assert world.finalizer.finalize_due(DUE, program=PROGRAM) == (
        "pl-short",
    )
    fact = world.finalizer.outcome_fact("pl-short")
    assert fact.classification == "UNAVAILABLE"


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


def _side_entry():
    from src.screening.offensive.v3.contracts import ExecutionSide

    return ExecutionSide.ENTRY


def _side_exit():
    from src.screening.offensive.v3.contracts import ExecutionSide

    return ExecutionSide.EXIT
