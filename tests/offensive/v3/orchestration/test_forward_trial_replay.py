"""Disabled Task 12 replay boundary and retained fixture specifications.

The official replay engine is a zero-capability object that rejects before
observing inputs or target paths. Skipped tests retain the future deterministic
current-cost and 2x-slippage contract after store-owned session-batch authority
exists; they do not claim that an official replay can currently run.

The fixture world is built with the real GrowthKernel, the real BTST
producer over a verified PIT snapshot, and a real Ed25519-trusted regime
evidence store; the official driver and the replay engine share the same
module-level builders (:func:`freeze_shared_input`,
:func:`build_arm_kernel_inputs`, :func:`build_pair_records`,
:func:`drive_session_lifecycle`) so current-cost reproduces the official
bytes exactly.
"""

from __future__ import annotations

import hashlib
import sys
from base64 import b64encode
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.screening.offensive.v3 import trust as v3_trust
from src.screening.offensive.v3.contracts import (
    ExecutionMode,
    SUPPORTED_SCHEMA_MAJOR,
    canonical_json_bytes,
)
from src.screening.offensive.v3.contracts.base import EvidenceScope, SignalStage
from src.screening.offensive.v3.contracts.evidence import (
    EvidenceRecord,
    SignalEvidence,
    SnapshotEvidence,
)
from src.screening.offensive.v3.contracts.regime import (
    RegimeObservation,
    RegimeObservationReason,
    RegimeSourceRevision,
    RegimeState,
)
from src.screening.offensive.v3.contracts.trial import TrialArm
from src.screening.offensive.v3.evidence.blob_store import BlobStore
from src.screening.offensive.v3.evidence.regime import (
    ActiveRegimeObservation,
    RegimeObservationPublisher,
    RegimeObservationReader,
)
from src.screening.offensive.v3.evidence.repository import EvidenceRepository
from src.screening.offensive.v3.evidence.session_spine import (
    SessionEnrollment,
    SessionSpine,
)
from src.screening.offensive.v3.execution.lifecycle import DailyBar
from src.screening.offensive.v3.execution.shadow_proxy import ShadowProxyAdapter
from src.screening.offensive.v3.gateway.exits import ExitLane
from src.screening.offensive.v3.orchestration.genesis import (
    TrialArmGenesisSource,
    TrialGenesisArchive,
)
from src.screening.offensive.v3.orchestration.paired_trial import (
    CommittedBtstCandidate,
    build_arm_kernel_inputs,
    build_pair_records,
    classify_pair_session,
    freeze_shared_input,
)
from src.screening.offensive.v3.orchestration.replay import (  # RED target
    ForwardTrialReplayEngine,
    PairedReplayResult,
    ReplayScenario,
    ReplaySessionFacts,
    TrialReplayError,
    TrialReplayInput,
    _require_scenario_inputs,
    _require_signal_facts,
    drive_session_lifecycle,
)
from src.screening.offensive.v3.orchestration.trial_store import (
    TrialArmDecisionStore,
)
from src.screening.offensive.v3.services.btst_producer_api import BtstProducerApi

# Reuse the frozen paired world + capital/decision seed helpers.
_ENTRY_TEST_DIR = Path(__file__).resolve().parents[1] / "execution"
if str(_ENTRY_TEST_DIR) not in sys.path:
    sys.path.insert(0, str(_ENTRY_TEST_DIR))
from test_shadow_proxy_entry import (  # noqa: E402
    HASH,
    NOW,
    PORTFOLIO,
    SIGNAL_DATE,
    TRIAL_ID,
    _cost_scenario,
    _record,
)
from test_shadow_proxy_exit import (  # noqa: E402
    ENTRY_SESSION,
    EXIT_DUE_SESSION,
    TRADING_SESSIONS,
    _exit_bar,
)

UTC = timezone.utc
PROGRAM = "research.btst.regime"
ZERO64 = "0" * 64
#: The fixed 13-session ladder starting at the signal day (T+1 entry on
#: 08-06, T+10 exit due on 08-19, run-out through 08-21).
SESSIONS = TRADING_SESSIONS
SIGNALS = (SIGNAL_DATE,)
_ENTRY_DAY = ENTRY_SESSION
_EXIT_DAY = EXIT_DUE_SESSION
#: The close-valuation mark price (micros) applied to every open position.
_MARK_PRICE_MICROS = 10_000_000
#: The frozen exit-policy fingerprint the trial binds.
_EXIT_POLICY_FINGERPRINT = HASH
#: The security id the BTST snapshot produces (ticker 300001).
_SECURITY = "300001.SZ"
#: The entry limit the producer's frozen price derives (1000.0000 yuan).
_ENTRY_LIMIT_CENTS = 1098
_REQUIRES_BATCH_AUTHORITY = pytest.mark.skip(
    reason="target behavior requires store-owned forward session batch authority"
)


def _entry_bar(session: date) -> DailyBar:
    """A bar whose open trades through the decision's 1000-cent entry
    limit (limit touch fills at ``min(open, limit)``)."""

    return DailyBar(
        security_id=_SECURITY,
        session=session,
        open_cents=990,
        high_cents=1005,
        low_cents=985,
        close_cents=995,
        limit_up_cents=1100,
        limit_down_cents=900,
    )


def _bar(session: date) -> DailyBar:
    """One same-session bar for both entry and exit purposes."""

    if session == _ENTRY_DAY:
        return _entry_bar(session)
    return _exit_bar(session)


def _marks(session: date) -> dict[str, int]:
    """The close mark while a position is open, empty before entry and
    after the exit settles (a mark for a flat security is a conflict)."""

    if _ENTRY_DAY <= session < _EXIT_DAY:
        return {_SECURITY: _MARK_PRICE_MICROS}
    return {}


class _Clock:
    """A mutable wall clock with an explicit freeze seam."""

    def __init__(self, start: datetime) -> None:
        self.moment = start

    def __call__(self) -> datetime:
        return self.moment

    def freeze(self, at: datetime) -> None:
        self.moment = at


def _session_close(session: date) -> datetime:
    return datetime(session.year, session.month, session.day, 16, 0, tzinfo=UTC)


def _session_cutoff(session: date) -> datetime:
    # The post-close decision instant (15:30 UTC): both the regime
    # observation (observed 14:00) and the BTST signals (observed 15:00)
    # are committed strictly before it, so the official driver and the
    # replay engine see the same PIT revisions.
    return datetime(session.year, session.month, session.day, 15, 30, tzinfo=UTC)


def _decision_cycle_id(session: date) -> str:
    return f"daily-action-{session.isoformat()}"


def _pair_key(session: date) -> tuple[str, str, str]:
    return (TRIAL_ID, session.isoformat(), _decision_cycle_id(session))


# =============================================================================
# regime evidence store (real Ed25519 trust chain, real publisher/reader)
# =============================================================================


#: The trial's frozen epoch (5 Aug 2026, before the first signal session).
EPOCH = datetime(2026, 8, 5, 0, 0, tzinfo=UTC)
#: One pre-enrollment genesis issuance fact per arm (units + cash so the
#: PIT NAV is non-zero at the first 15:00 cutoff; the receivable-based seed
#: would leave as_observed_nav_cents == 0 and trip the risk gate).
_GENESIS_AT = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)


def _funded_repo(tmp_path: Path, name: str):
    """An arm ledger funded by one genesis issuance (units + cash)."""

    from src.screening.offensive.v3.capital.flows import GenesisRequest
    from src.screening.offensive.v3.capital.repository import (
        AccountBinding,
        CapitalRepository,
    )

    repository = CapitalRepository.initialize(tmp_path / f"{name}.sqlite3")
    binding = AccountBinding(
        portfolio_id=PORTFOLIO,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        broker_account_id=None,
        base_currency="CNY",
        environment_fingerprint=None,
    )
    repository.initialize_genesis(
        GenesisRequest(
            idempotency_key=f"genesis-{name}",
            account_binding=binding,
            unit_quanta=10_000,
            unit_price_numerator=1_000,
            unit_price_denominator=1,
            source_authority="test.seed",
            authorization_reference="auth-genesis-1",
            effective_at=_GENESIS_AT,
            as_of=_GENESIS_AT,
        )
    )
    return repository


def _regime_capability() -> v3_trust.Capability:
    return v3_trust.Capability(
        artifact=v3_trust.ArtifactKind.SNAPSHOT,
        namespace="regime.classifier",
        mode=ExecutionMode.DAILY_BAR_PROXY,
        schema_major=SUPPORTED_SCHEMA_MAJOR,
        capability_version="regime.snapshot.v1",
        scope="global:regime",
        valid_from=EPOCH - timedelta(days=1),
        valid_until=EPOCH + timedelta(days=120),
        revoked_at=None,
    )


def _regime_issuer(private_key: Ed25519PrivateKey, capability):
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return v3_trust.TrustedIssuer(
        issuer_id="governance.service",
        key_id="regime-key-1",
        issuer_kind=v3_trust.IssuerKind.MARKET_PUBLISHER,
        public_key=b64encode(public_bytes).decode("ascii"),
        valid_from=EPOCH - timedelta(days=1),
        valid_until=EPOCH + timedelta(days=120),
        revoked_at=None,
        capabilities=(capability,),
    )


def _regime_root_context(registry):
    root_key = Ed25519PrivateKey.generate()
    root_public = root_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    root_hash = hashlib.sha256(root_public).hexdigest()
    anchor = v3_trust.RootTrustAnchor(
        root_hash=root_hash,
        root_key_id="root-1",
        public_key=b64encode(root_public).decode("ascii"),
        valid_from=EPOCH - timedelta(days=1),
        valid_until=EPOCH + timedelta(days=120),
        revoked_at=None,
    )
    from src.screening.offensive.v3.contracts.governance import TrustBundle

    bundle = TrustBundle(
        registry_epoch=1,
        predecessor_bundle_hash=ZERO64,
        root_hash=anchor.root_hash,
        root_key_id=anchor.root_key_id,
        trusted_issuer_registry_hash=registry.content_hash(),
        issued_at=EPOCH - timedelta(minutes=10),
        expires_at=EPOCH + timedelta(days=120),
        revoked_at=None,
        issuer_id="offline-governance-root",
        issuer_capability="root.trust.bundle.v1",
        schema_major=SUPPORTED_SCHEMA_MAJOR,
    )
    signed_bundle = v3_trust.SignedTrustBundle(
        bundle=bundle,
        registry=registry,
        signature=b64encode(
            root_key.sign(
                v3_trust.trust_bundle_signature_preimage(bundle, registry)
            )
        ).decode("ascii"),
    )
    verifier = v3_trust.TrustBundleVerifier((anchor,))
    delegate = v3_trust.CapabilityVerifier(verifier, (signed_bundle,))
    head = v3_trust.CurrentTrustHeadWitness(
        active_trust_bundle_hash=bundle.artifact_hash(),
        registry_epoch=1,
        head_version=1,
        store_version=1,
        observed_at=EPOCH,
    )

    class _HeadProvider:
        def current_trust_head(self, trusted_at: datetime):
            return head

    return delegate, _HeadProvider()


class _RegimeSigner:
    """Signs SnapshotEvidence envelopes with the real trust chain."""

    def __init__(self, issuer_key, issuer, capability) -> None:
        self._key = issuer_key
        self._issuer = issuer
        self._capability = capability

    def sign_snapshot(self, snapshot: SnapshotEvidence, payload: bytes):
        payload_hash = hashlib.sha256(payload).hexdigest()
        protected = canonical_json_bytes(
            {
                "artifact": self._capability.artifact,
                "capability_scope": self._capability.scope,
                "capability_version": self._capability.capability_version,
                "issuer_id": self._issuer.issuer_id,
                "key_id": self._issuer.key_id,
                "mode": self._capability.mode,
                "namespace": self._capability.namespace,
                "payload": b64encode(payload).decode("ascii"),
                "payload_hash": payload_hash,
                "schema_major": self._capability.schema_major,
            }
        )
        return v3_trust.SignedEnvelope(
            issuer_id=self._issuer.issuer_id,
            key_id=self._issuer.key_id,
            schema_major=self._capability.schema_major,
            artifact=self._capability.artifact,
            namespace=self._capability.namespace,
            mode=self._capability.mode,
            capability_version=self._capability.capability_version,
            capability_scope=self._capability.scope,
            payload_hash=payload_hash,
            payload=payload,
            signature=b64encode(self._key.sign(protected)).decode("ascii"),
        )


class _RegimeWorld:
    """A real trusted regime evidence store with publisher + reader."""

    def __init__(self, tmp_path: Path) -> None:
        self.key = Ed25519PrivateKey.generate()
        self.capability = _regime_capability()
        self.issuer = _regime_issuer(self.key, self.capability)
        registry = v3_trust.TrustedRegistry(issuers=(self.issuer,))
        self.verifier, self.head_provider = _regime_root_context(registry)
        self.blob_store = BlobStore(tmp_path / "regime-blobs")
        self.database_path = str(tmp_path / "regime-evidence.sqlite3")
        self.clock = _Clock(
            datetime(2026, 8, 5, 13, 0, tzinfo=UTC)
        )
        self.repository = EvidenceRepository(
            database_path=self.database_path,
            blob_store=self.blob_store,
            verifier=self.verifier,
            trust_head_provider=self.head_provider,
            issuer_namespace="regime.classifier",
            clock=self.clock,
        )
        self.publisher = RegimeObservationPublisher(self.repository)
        self.reader = RegimeObservationReader(self.repository)
        self.signer = _RegimeSigner(
            self.key, self.issuer, self.capability
        )


def _regime_observation(session: date, observed_at: datetime) -> RegimeObservation:
    return RegimeObservation(
        signal_session=session,
        state=RegimeState.NORMAL,
        reason=RegimeObservationReason.CLASSIFIED,
        raw_state="NORMAL",
        source_revisions=(
            RegimeSourceRevision(
                evidence_id="regime:csi300:1.0",
                revision=1,
                artifact_hash=HASH,
            ),
        ),
        effective_at=observed_at - timedelta(minutes=30),
        provider_published_at=observed_at - timedelta(minutes=10),
        observed_at=observed_at,
        classifier_semver="1.0.0",
        behavior_fingerprint=HASH,
        input_schema_hash=HASH,
    )


def _regime_snapshot(
    observation: RegimeObservation, evidence_id: str
) -> SnapshotEvidence:
    return SnapshotEvidence(
        evidence_id=evidence_id,
        subject_scope=EvidenceScope.GLOBAL,
        subject_producer="regime.classifier",
        family_id=None,
        strategy_semver="1.0.0",
        behavior_fingerprint=observation.behavior_fingerprint,
        policy_epoch=1,
        execution_version="t0-close-t1-open-t10-open.v1",
        cost_version="cn-a-share-costs.v1",
        effective_at=observation.effective_at,
        provider_published_at=observation.provider_published_at,
        observed_at=observation.observed_at,
        available_at=observation.observed_at + timedelta(hours=1),
        mode=ExecutionMode.DAILY_BAR_PROXY,
        source_authority="governance.service",
        payload_content_hash=observation.content_hash(),
        schema_major=SUPPORTED_SCHEMA_MAJOR,
        evidence_kind="snapshot",
    )


def _publish_regime(world: _RegimeWorld, session: date) -> ActiveRegimeObservation:
    """Publish one canonical regime observation for one signal session.

    The evidence id is per-session so the close-valuation idempotency key
    differs across sessions (the lifecycle binds the same-session snapshot).
    """

    observed_at = datetime(
        session.year, session.month, session.day, 14, 0, tzinfo=UTC
    )
    observation = _regime_observation(session, observed_at)
    evidence_id = f"regime:{session.isoformat()}"
    record = world.publisher.publish(
        observation,
        _regime_snapshot(observation, evidence_id),
        world.signer,
    )
    return ActiveRegimeObservation(
        record=record,
        observation=observation,
        observation_hash=observation.content_hash(),
    )


# =============================================================================
# BTST producer world (real produce_and_publish over a verified snapshot)
# =============================================================================


class _ProducerWorld:
    """A real BtstProducerApi over its own evidence store.

    Mirrors the producer test's world fixture: the real BTST funnel runs
    over the frozen snapshot; ``BtstBreakoutSetup.detect`` is pinned to a
    hit (see the rig fixture) so every ticker yields its canonical
    CANDIDATE + SELECTED pair.
    """

    def __init__(self, tmp_path: Path) -> None:
        from tests.offensive.v3.services.test_btst_producer_api import (
            _World,
        )

        self._world = _World(tmp_path / "btst")
        self.service: BtstProducerApi = self._world.service
        self.raw_repository = self._world.raw_repository

    def freeze(self, at: datetime) -> None:
        # The producer test's mutable clock only exposes ``advance``; set
        # its moment directly (test-only seam).
        self._world.clock.now_value = at


def _producer_snapshot(session: date):
    """A verified PIT snapshot bound to one signal session (2 candidates).

    Mirrors the producer test's frozen snapshot exactly, so the real funnel
    emits its canonical SELECTED envelopes (the runner's candidate truth).
    """

    from src.screening.offensive.daily_action_readiness import (
        BOARD_RULE_VERSION,
        NORMALIZATION_VERSION,
    )
    from src.screening.offensive.daily_action_snapshot import (
        VerifiedDailyActionSnapshot,
    )
    from src.screening.offensive.setup_data_contracts import (
        SETUP_REQUIREMENTS_VERSION,
    )
    from tests.offensive.v3.services.test_btst_producer_api import (
        _flows,
        _manifest,
        _prices,
    )

    tickers = ("300001", "300002")
    return VerifiedDailyActionSnapshot(
        signal_date=session,
        snapshot_id="sha256:" + "b" * 64,
        manifest=_manifest(),
        universe_tickers=tickers,
        prices_by_ticker=MappingProxyType(
            {ticker: _prices() for ticker in tickers}
        ),
        fund_flow_by_ticker=MappingProxyType(
            {ticker: _flows() for ticker in tickers}
        ),
        industry_day_pct_by_ticker=MappingProxyType(
            {ticker: 3.2 for ticker in tickers}
        ),
        regime="normal",
        board_rule_version=BOARD_RULE_VERSION,
        normalization_version=NORMALIZATION_VERSION,
        setup_requirements_version=SETUP_REQUIREMENTS_VERSION,
        ticker_blocks=MappingProxyType({}),
        consumed_fingerprint_by_ticker=MappingProxyType(
            {
                ticker: MappingProxyType(
                    {"btst_breakout": "sha256:" + "a" * 64}
                )
                for ticker in tickers
            }
        ),
    )


def _is_selected(record: EvidenceRecord) -> bool:
    return record.evidence.stage is SignalStage.SELECTED


# =============================================================================
# the official paired-trial world + shared drive
# =============================================================================


@dataclass
class _ArmWorld:
    repository: object
    adapter: ShadowProxyAdapter
    exit_lane: ExitLane


def reserve_committed_pair(store, arms, lease, pair_key) -> None:
    from src.screening.offensive.v3.execution.shadow_proxy import (
        ShadowArmExecutionContext,
    )

    for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER):
        contexts = {
            arm: ShadowArmExecutionContext(
                trial_id=TRIAL_ID,
                arm=arm,
                portfolio_id=PORTFOLIO,
                decision_store=store,
                capital_repository=arms[arm].repository,
                writer_lease=lease,
            )
            for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER)
        }
        arms[arm].adapter.reserve_committed_pair(pair_key, contexts)


class _Rig:
    """The official paired-trial world: sealed genesis, official decision
    store, official spine, official evidence, and the shared lifecycle.

    The official driver replays the same pure construction the forward
    runner uses (the module-level builders) with the same frozen
    ``trusted_at`` as the replay engine — the session cutoff — so a
    current-cost replay reproduces the official bytes exactly.
    """

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.regime_world = _RegimeWorld(tmp_path)
        self.producer_world = _ProducerWorld(tmp_path)
        self.clock = _Clock(NOW)
        self.spine = SessionSpine(
            database_path=str(tmp_path / "spine.sqlite3"),
            clock=self.clock,
        )
        _enroll(self.spine, *SIGNALS)
        self.champion_repo = _funded_repo(tmp_path, "champion-genesis")
        self.challenger_repo = _funded_repo(tmp_path, "challenger-genesis")
        archive = TrialGenesisArchive(tmp_path / "archive")
        self.genesis_manifest = archive.seal(
            TRIAL_ID,
            TrialArmGenesisSource(self.champion_repo),
            TrialArmGenesisSource(self.challenger_repo),
        )
        self.archive_root = archive.root
        self.store = TrialArmDecisionStore(
            database_path=str(tmp_path / "official-trial.sqlite3")
        )
        self.store.register_trial(_reanchored_bundle(), self.genesis_manifest)
        self.lease = self.store.claim_writer()
        self.arms = {
            TrialArm.CHAMPION: _ArmWorld(
                self.champion_repo,
                ShadowProxyAdapter(
                    database_path=str(tmp_path / "official-champ-proxy.sqlite3"),
                    clock=self.clock,
                ),
                ExitLane(
                    database_path=str(tmp_path / "official-champ-exits.sqlite3"),
                    clock=self.clock,
                ),
            ),
            TrialArm.CHALLENGER: _ArmWorld(
                self.challenger_repo,
                ShadowProxyAdapter(
                    database_path=str(tmp_path / "official-chall-proxy.sqlite3"),
                    clock=self.clock,
                ),
                ExitLane(
                    database_path=str(tmp_path / "official-chall-exits.sqlite3"),
                    clock=self.clock,
                ),
            ),
        }
        from src.screening.offensive.v3.kernel.decide import GrowthKernel
        from src.screening.offensive.v3.kernel.sizing import SizingConfig

        self.kernel = GrowthKernel(
            SizingConfig(
                per_ticker_gross_cap_cents=200_000,
                per_industry_gross_cap_cents=300_000,
                per_day_gross_cap_cents=500_000,
                portfolio_gross_cap_cents=400_000,
                worst_case_fee_ppm=3_000,
            )
        )
        self.replayer = ForwardTrialReplayEngine()
        self.session_facts: dict[date, ReplaySessionFacts] = {}
        self.active_regimes: dict[date, ActiveRegimeObservation] = {}
        self.selected: dict[date, tuple[CommittedBtstCandidate, ...]] = {}

    # -- evidence helpers ----------------------------------------------------

    def active_regime(self, session: date) -> ActiveRegimeObservation:
        if session not in self.active_regimes:
            self.regime_world.clock.freeze(
                datetime(
                    session.year,
                    session.month,
                    session.day,
                    14,
                    10,
                    tzinfo=UTC,
                )
            )
            self.active_regimes[session] = _publish_regime(
                self.regime_world, session
            )
        return self.active_regimes[session]

    def selected_candidates(
        self, session: date
    ) -> tuple[CommittedBtstCandidate, ...]:
        if session not in self.selected:
            snapshot = _producer_snapshot(session)
            # The funnel's envelopes are observed at the signal-date 15:00
            # close; ingest them shortly after so they are active at the
            # 15:30 decision instant.
            self.producer_world.freeze(
                datetime(
                    session.year,
                    session.month,
                    session.day,
                    15,
                    10,
                    tzinfo=UTC,
                )
            )
            records = self.producer_world.service.produce_and_publish(snapshot)
            selected = tuple(record for record in records if _is_selected(record))
            self.selected[session] = tuple(
                CommittedBtstCandidate(
                    record=record,
                    payload=self.producer_world.service.candidate_payload(
                        record,
                        expected_signal_session=session,
                    ),
                )
                for record in selected
            )
        return self.selected[session]

    def snapshot_evidence(self, session: date) -> EvidenceRecord:
        """The same-session snapshot record bound to the close valuation."""

        return self.active_regime(session).record

    # -- facts ---------------------------------------------------------------

    def build_session_facts(self) -> None:
        for session in SESSIONS:
            self.session_facts[session] = ReplaySessionFacts(
                session=session,
                snapshot_evidence=self.snapshot_evidence(session),
                bars={_SECURITY: _bar(session)},
                marks=_marks(session),
                regime_observation=(
                    self.active_regime(session)
                    if session in SIGNALS
                    else None
                ),
                selected_candidates=(
                    self.selected_candidates(session)
                    if session in SIGNALS
                    else ()
                ),
            )

    # -- official drive ------------------------------------------------------

    def run_official(self) -> None:
        """Drive the official full timeline with the shared builders.

        Each signal session: freeze the shared input at the session cutoff,
        read the champion ledger's PIT capital snapshot, run one kernel
        decision per arm, commit one pair, record the session status, and
        reserve both arms. Every trading session then drives the shared
        lifecycle (entry/exit/valuation/finalize) at the session close.

        RETAINED-SPEC STALENESS: this body predates the capital-checkpoint-v2
        / economic-input-v4 migration. It still calls ``freeze_shared_input``
        (now unconditionally fail-closed) and the single-``capital_snapshot``
        signatures of ``build_arm_kernel_inputs`` / ``build_pair_records``,
        which were replaced by per-arm ``ShadowCapitalCheckpoint`` +
        ``champion_input``/``challenger_input``. It cannot execute until the
        store-owned batch authority lands, at which point it must be rewritten
        against the checkpoint-v2 API (calling convention: the green builders
        in tests/offensive/v3/kernel/test_shadow_kernel.py).
        """

        self.build_session_facts()
        latest_pair_key: tuple[str, str, str] | None = None
        for session in SESSIONS:
            if session in SIGNALS:
                facts = self.session_facts[session]
                regime = facts.regime_observation
                assert regime is not None
                trusted_at = _session_cutoff(session)
                self.clock.freeze(trusted_at)
                shared_input = freeze_shared_input(
                    portfolio_id=PORTFOLIO,
                    trial_id=TRIAL_ID,
                    validated=_validated_bundle(),
                    session=session,
                    cycle_id=_decision_cycle_id(session),
                    regime=regime.observation,
                    regime_hash=regime.observation_hash,
                    trusted_at=trusted_at,
                )
                capital_snapshot = (
                    self.champion_repo.capital_risk_snapshot(trusted_at)
                )
                champion_input, challenger_input = build_arm_kernel_inputs(
                    validated=_validated_bundle(),
                    shared_input=shared_input,
                    trusted_at=trusted_at,
                    candidates=facts.selected_candidates or (),
                    capital_snapshot=capital_snapshot,
                )
                champion = self.kernel.decide_shadow(champion_input)
                challenger = self.kernel.decide_shadow(challenger_input)
                records = build_pair_records(
                    trial_id=TRIAL_ID,
                    session=session,
                    cycle_id=_decision_cycle_id(session),
                    shared_input=shared_input,
                    regime_hash=regime.observation_hash,
                    champion=champion,
                    challenger=challenger,
                    trusted_at=trusted_at,
                    capital_checkpoint_hash=capital_snapshot.content_hash(),
                )
                self.store.commit_pair(records[0], records[1])
                self.spine.record_session_status(
                    PROGRAM,
                    session,
                    classify_pair_session(
                        champion,
                        challenger,
                        shared_candidate_count=len(facts.selected_candidates or ()),
                    ),
                )
                latest_pair_key = _pair_key(session)
            assert latest_pair_key is not None
            self.clock.freeze(_session_close(session))
            reserve_committed_pair(
                self.store, self.arms, self.lease, latest_pair_key
            )
            drive_session_lifecycle(
                input=self.replay_input(),
                arms=self.arms,
                replay_store=self.store,
                lease=self.lease,
                pair_key=latest_pair_key,
                session=session,
                facts=self.session_facts[session],
                scenario_cost=_cost_scenario(30),
                clock=self.clock,
            )

    def replay_input(self) -> TrialReplayInput:
        return TrialReplayInput(
            trial_id=TRIAL_ID,
            research_program_id=PROGRAM,
            portfolio_id=PORTFOLIO,
            bundle=_reanchored_bundle(),
            genesis_manifest=self.genesis_manifest,
            archive_root=self.archive_root,
            spine=self.spine,
            evidence_store=self.regime_world.repository,
            trading_sessions=SESSIONS,
            sessions=tuple(self.session_facts.values()),
            fixed_exit_policy_fingerprint=_EXIT_POLICY_FINGERPRINT,
            signal_evidence_store=self.producer_world.raw_repository,
            official_store=self.store,
        )

    def official_hashes(self) -> tuple[str, str, str, str]:
        from src.screening.offensive.v3.orchestration.replay import (
            _checkpoint_root,
            _decision_root,
            _nav_path_hash,
        )

        return (
            _nav_path_hash(self.champion_repo),
            _nav_path_hash(self.challenger_repo),
            _decision_root(
                self.store,
                tuple(_pair_key(session) for session in SIGNALS),
            ),
            _checkpoint_root((self.champion_repo, self.challenger_repo)),
        )


def _validated_bundle():
    from src.screening.offensive.v3.governance.regime_trial import (
        validate_regime_trial_bundle,
    )

    return validate_regime_trial_bundle(_reanchored_bundle(), trusted_at=NOW)


def _reanchored_bundle():
    """The shared trial bundle re-anchored to this test's epoch.

    The replay timeline runs 08-05 (signal cutoff 15:00 UTC) through
    08-21, but the shared kernel-test fixture anchors the enrollment
    window and the policy activation to ``NOW`` (08-05 15:30) — one
    open-auction cycle ahead of the first cutoff. Official and replay both
    decide at the original cutoffs, so the window/activation must open
    before the first cutoff for every drive to validate. Only time
    bindings change; every hash binding stays intact, so the replay
    store's bundle bytes equal the official store's bytes.
    """

    from src.screening.offensive.v3.governance.regime_trial import (
        RegimeTrialBundle,
    )
    from test_shadow_proxy_entry import _bundle

    bundle = _bundle()
    baseline, target = bundle.baseline_policy, bundle.target_policy
    activation = bundle.baseline_policy_activation.model_copy(
        update={
            "effective_from": EPOCH - timedelta(days=1),
            "expires_at": EPOCH + timedelta(days=120),
        }
    )
    trial = bundle.trial_manifest.model_copy(
        update={
            "enrollment_start": EPOCH - timedelta(days=1),
            "enrollment_end": EPOCH + timedelta(days=30),
            "followup_finality_date": EPOCH + timedelta(days=60),
            "fixed_assessment_date": EPOCH + timedelta(days=90),
            "trial_manifest_sealed_at": EPOCH - timedelta(days=2),
            "issued_at": EPOCH - timedelta(days=2),
            "expires_at": EPOCH + timedelta(days=120),
        }
    )
    sap = bundle.sap_manifest.model_copy(
        update={
            "trial_manifest_hash": trial.artifact_hash(),
            "enrollment_start": trial.enrollment_start,
            "issued_at": EPOCH - timedelta(days=2),
            "sealed_at": EPOCH - timedelta(days=2),
            "expires_at": EPOCH + timedelta(days=120),
        }
    )
    return RegimeTrialBundle(
        baseline_policy=baseline,
        target_policy=target,
        trial_manifest=trial,
        sap_manifest=sap,
        baseline_policy_activation=activation,
    )


def _enroll(spine: SessionSpine, *sessions: date) -> None:
    spine.enroll_expected_sessions(
        tuple(
            SessionEnrollment(
                research_program_id=PROGRAM,
                signal_session=session,
                assessment_date=session,
            )
            for session in sessions
        )
    )


@pytest.fixture()
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Rig:
    # The real BTST funnel runs over the frozen snapshot; pin the setup
    # detector to a hit so every ticker yields its canonical CANDIDATE +
    # SELECTED pair (mirroring the producer test's world fixture).
    from src.screening.offensive.setups.btst_breakout import (
        BtstBreakoutSetup,
    )
    from tests.offensive.v3.services.test_btst_producer_api import (
        _hit_result,
    )

    monkeypatch.setattr(
        BtstBreakoutSetup,
        "detect",
        lambda self, ticker, trade_date, context: _hit_result(ticker),
    )
    # The producer world's trust chain is anchored to the producer test's
    # module NOW (08-06 09:00); re-anchor it before the first signal day so
    # the chain is valid at the 08-05 publish/decision instants.
    import tests.offensive.v3.services.test_btst_producer_api as producer_test

    monkeypatch.setattr(
        producer_test,
        "NOW",
        datetime(2026, 8, 5, 9, 0, tzinfo=UTC),
    )
    return _Rig(tmp_path)


# =============================================================================
# Step 1: CURRENT_COST byte-for-byte reproduction
# =============================================================================


@pytest.mark.parametrize(
    "scenario",
    (ReplayScenario.CURRENT_COST, ReplayScenario.DOUBLE_SLIPPAGE),
)
def test_replay_requires_store_owned_session_batch_authority(
    tmp_path: Path,
    scenario: ReplayScenario,
) -> None:
    target = tmp_path / scenario.value
    replayer = ForwardTrialReplayEngine()

    with pytest.raises(TrialReplayError) as rejected:
        replayer.replay(object(), scenario, target)  # type: ignore[arg-type]

    assert rejected.value.code == "forward_input_authority_unavailable"
    assert not target.exists()


def test_unavailable_replay_does_not_even_resolve_target_path() -> None:
    class PoisonPath:
        def __fspath__(self) -> str:
            raise AssertionError("target path was resolved before authority gate")

    with pytest.raises(TrialReplayError) as rejected:
        ForwardTrialReplayEngine().replay(
            object(),  # type: ignore[arg-type]
            ReplayScenario.CURRENT_COST,
            PoisonPath(),  # type: ignore[arg-type]
        )

    assert rejected.value.code == "forward_input_authority_unavailable"


@_REQUIRES_BATCH_AUTHORITY
def test_current_cost_replay_is_deterministic_across_delete_and_rerun(
    rig: _Rig, tmp_path: Path
) -> None:
    import shutil

    rig.run_official()
    first = rig.replayer.replay(
        rig.replay_input(), ReplayScenario.CURRENT_COST, tmp_path / "run-1"
    )
    shutil.rmtree(tmp_path / "run-1")
    second = rig.replayer.replay(
        rig.replay_input(), ReplayScenario.CURRENT_COST, tmp_path / "run-2"
    )
    assert second.champion_nav_path_hash == first.champion_nav_path_hash
    assert second.challenger_nav_path_hash == first.challenger_nav_path_hash
    assert second.decision_root == first.decision_root
    assert second.lifecycle_root == first.lifecycle_root
    assert second.decision_hashes == first.decision_hashes


@_REQUIRES_BATCH_AUTHORITY
def test_current_cost_replay_rejects_divergent_decision_bytes(
    rig: _Rig, tmp_path: Path
) -> None:
    rig.run_official()
    # A facts bundle whose SELECTED records differ from the official
    # evidence (here: none at all) must produce a divergent decision and
    # fail closed before the replay directory is written.
    input_ = rig.replay_input()
    input_ = replace(
        input_,
        sessions=tuple(
            replace(
                f,
                selected_candidates=()
                if f.session in SIGNALS
                else f.selected_candidates,
            )
            for f in input_.sessions
        ),
    )
    with pytest.raises(TrialReplayError) as exc:
        rig.replayer.replay(
            input_, ReplayScenario.CURRENT_COST, tmp_path / "bad"
        )
    assert exc.value.code == "decision_divergence"


def test_signal_session_replay_requires_authoritative_candidate_store(
    rig: _Rig,
) -> None:
    with pytest.raises(TrialReplayError) as rejected:
        rig.replayer.replay(
            replace(rig.replay_input(), signal_evidence_store=None),
            ReplayScenario.CURRENT_COST,
            object(),  # type: ignore[arg-type]
        )

    assert rejected.value.code == "forward_input_authority_unavailable"


def test_replay_facts_share_exact_store_owned_raw_candidate_bytes(rig: _Rig) -> None:
    rig.build_session_facts()

    for session in SIGNALS:
        candidates = rig.session_facts[session].selected_candidates
        assert candidates is not None
        for candidate in candidates:
            raw = rig.producer_world.raw_repository.raw_payload(
                candidate.record.evidence.payload_content_hash
            )
            assert raw == candidate.payload.canonical_bytes()


# =============================================================================
# Step 2: DOUBLE_SLIPPAGE full alternate path
# =============================================================================


@_REQUIRES_BATCH_AUTHORITY
def test_double_slippage_is_a_full_path_replay_not_a_return_drag(
    rig: _Rig, tmp_path: Path
) -> None:
    rig.run_official()
    current = rig.replayer.replay(
        rig.replay_input(), ReplayScenario.CURRENT_COST, tmp_path / "current"
    )
    stress = rig.replayer.replay(
        rig.replay_input(), ReplayScenario.DOUBLE_SLIPPAGE, tmp_path / "stress"
    )
    # Both scenarios consume the identical decision timeline; the stress
    # ledger must be a real, distinct capital path.
    assert stress.sessions_replayed == current.sessions_replayed
    assert stress.decision_hashes == current.decision_hashes
    assert len(stress.stress_ledger_hashes) == 2
    assert stress.champion_nav_path_hash != current.champion_nav_path_hash
    assert stress.challenger_nav_path_hash != current.challenger_nav_path_hash
    assert stress.stress_ledger_hashes[0] != current.champion_nav_path_hash
    assert stress.stress_ledger_hashes[1] != current.challenger_nav_path_hash


@_REQUIRES_BATCH_AUTHORITY
def test_double_slippage_never_compares_to_official_bytes(
    rig: _Rig, tmp_path: Path
) -> None:
    rig.run_official()
    # DOUBLE_SLIPPAGE may run without the official store (its decisions
    # legitimately diverge; only the temporary ledgers are persisted).
    input_ = replace(rig.replay_input(), official_store=None)
    result = rig.replayer.replay(
        input_, ReplayScenario.DOUBLE_SLIPPAGE, tmp_path / "stress"
    )
    assert result.sessions_replayed == len(SESSIONS)
    assert result.champion_capital_report.endswith(":True")
    assert result.challenger_capital_report.endswith(":True")


# =============================================================================
# Step 3: PIT verification + fail-closed guards
# =============================================================================


def test_missing_regime_fact_fails_before_any_commit(rig: _Rig) -> None:
    rig.build_session_facts()
    session = SIGNALS[0]
    facts = replace(rig.session_facts[session], regime_observation=None)

    with pytest.raises(TrialReplayError) as exc:
        _require_signal_facts(session, facts)

    assert exc.value.code == "signal_facts_missing"


def test_revised_after_cutoff_regime_fails_closed(
    rig: _Rig,
) -> None:
    # Even an input carrying revised facts is not inspected before the
    # store-owned session-batch authority exists.
    with pytest.raises(TrialReplayError) as exc:
        rig.replayer.replay(
            object(),  # type: ignore[arg-type]
            ReplayScenario.CURRENT_COST,
            object(),  # type: ignore[arg-type]
        )
    assert exc.value.code == "forward_input_authority_unavailable"


def _fake_regime(rig: _Rig, session: date) -> ActiveRegimeObservation:
    observed_at = datetime(
        session.year, session.month, session.day, 13, 0, tzinfo=UTC
    )
    observation = _regime_observation(session, observed_at)
    return ActiveRegimeObservation(
        record=rig.active_regime(session).record,
        observation=observation,
        observation_hash=observation.content_hash(),
    )


@_REQUIRES_BATCH_AUTHORITY
def test_replay_never_calls_producer_or_creates_signal_evidence(
    rig: _Rig, tmp_path: Path
) -> None:
    rig.run_official()
    before = _evidence_count(rig.producer_world.raw_repository)
    rig.replayer.replay(
        rig.replay_input(), ReplayScenario.CURRENT_COST, tmp_path / "replay"
    )
    assert _evidence_count(rig.producer_world.raw_repository) == before
    rig.replayer.replay(
        rig.replay_input(), ReplayScenario.DOUBLE_SLIPPAGE, tmp_path / "stress"
    )
    assert _evidence_count(rig.producer_world.raw_repository) == before


def _evidence_count(repository: EvidenceRepository) -> int:
    import sqlalchemy as sa

    with repository._engine.connect() as conn:  # noqa: SLF001
        return int(
            conn.execute(
                sa.text("SELECT COUNT(*) FROM evidence_records")
            ).scalar()
        )


def test_replay_refuses_nonempty_target_directory(tmp_path: Path) -> None:
    target = tmp_path / "occupied"
    target.mkdir()
    (target / "existing.txt").write_text("x", encoding="utf-8")
    replayer = ForwardTrialReplayEngine()
    with pytest.raises(TrialReplayError) as exc:
        replayer.replay(
            object(), ReplayScenario.CURRENT_COST, target  # type: ignore[arg-type]
        )
    assert exc.value.code == "forward_input_authority_unavailable"
    assert (target / "existing.txt").read_text(encoding="utf-8") == "x"


def test_replay_requires_official_store_for_current_cost(
    rig: _Rig,
) -> None:
    input_ = replace(rig.replay_input(), official_store=None)

    with pytest.raises(TrialReplayError) as exc:
        _require_scenario_inputs(input_, ReplayScenario.CURRENT_COST)

    assert exc.value.code == "official_store_required"
