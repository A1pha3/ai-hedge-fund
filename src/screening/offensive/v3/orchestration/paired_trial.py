"""Plan Task 11: thin forward paired trial runner + terminal SessionSpine.

``ForwardPairedTrialRunner`` orchestrates one signal session of a sealed
paired regime trial against the frozen forward timeline. It is deliberately
thin — no classifier, ranking, sizing, fee, fill, NAV, statistical, signing,
activation, or broker logic:

1.  validate the sealed bundle against the frozen trusted time (enrollment
    window) and the expected session (enrolled, not cancelled);
2.  freeze the trusted clock once — one ``trusted_at`` shared by both arms;
3.  read the active canonical regime observation strictly before cutoff
    (a missing observation is an operational failure, never a back-filled
    ``NORMAL``);
4.  run the BTST producer exactly once; its SELECTED records become the
    candidate set (shared empty candidates classify ``NO_SIGNAL``);
5.  build two arm ``ShadowKernelInput`` over the same frozen shared input
    and the same capital checkpoint, run ``decide_shadow`` exactly once per
    arm, and commit one pair atomically (``commit_pair``);
6.  record one session status (``RUN`` / ``NO_SIGNAL`` / ``BLOCKED`` /
    ``DATA_UNKNOWN``), then reserve both decisions — the pair commit is the
    side-effect boundary, so a crash after commit replays by exact-validating
    the existing pair and never recomputes an alternate proposal.

``finalize_missed_sessions`` writes ``NO_RUN`` only for enrolled sessions
whose decision cutoff has passed and whose pair/status is absent.
``advance_market_session`` remains available for exit-only run-out through
the sealed finality date (wired by the Task 12 replay engine).

Import boundary: the runner may reach evidence/governance read APIs, the
producer, the kernel, the decision store, capital read APIs, and the shadow
lifecycle; it must never import activation/permit/outbox/broker/trust or
production-adapter paths (a static guard test scans the source).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Protocol

from src.screening.offensive.v3.contracts import ExecutionMode, Sha256
from src.screening.offensive.v3.contracts.capital import CapitalRiskSnapshot
from src.screening.offensive.v3.contracts.decision import ShadowDecision
from src.screening.offensive.v3.contracts.evidence import (
    EvidenceRecord,
    SignalEvidence,
)
from src.screening.offensive.v3.contracts.regime import RegimeObservation
from src.screening.offensive.v3.contracts.trial import (
    BaselineShadowPolicyBinding,
    ShadowPolicySourceKind,
    TargetShadowPolicyBinding,
    TrialArm,
)
from src.screening.offensive.v3.evidence.regime import (
    ActiveRegimeObservation,
)
from src.screening.offensive.v3.evidence.session_spine import (
    SessionSpine,
    SessionStatus,
)
from src.screening.offensive.v3.governance.regime_trial import (
    RegimeTrialBundle,
    ValidatedRegimeTrialBundle,
    validate_regime_trial_bundle,
)
from src.screening.offensive.v3.kernel.admission import BTST_FAMILY
from src.screening.offensive.v3.kernel.models import (
    CandidateEvidenceBinding,
    DeadlineContract,
    NoTradeDecision,
    RawCandidate,
    ShadowCapitalCheckpoint,
    ShadowKernelInput,
    ShadowSharedInput,
)
from src.screening.offensive.v3.orchestration.trial_store import (
    ArmDecision,
    TrialArmDecisionRecord,
    TrialArmDecisionStore,
    TrialStoreError,
)


class PairedTrialRunnerError(RuntimeError):
    """Fail-closed rejection of a forward paired-trial session."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


@dataclass(frozen=True)
class SignalSessionRequest:
    """One forward signal session the runner may decide.

    The trusted time is NOT part of the request: the runner freezes the
    trusted clock exactly once per session, and both arm decisions consume
    that single frozen time.
    """

    trial_id: str
    signal_session: date


@dataclass(frozen=True)
class PairedSignalReceipt:
    """The durable outcome of one signal session decision."""

    trial_id: str
    signal_session: date
    pair_key: tuple[str, str, str]
    champion_status: SessionStatus
    challenger_status: SessionStatus
    decision_cycle_id: str
    regime_observation_hash: Sha256


class SealedBundleReader(Protocol):
    """Reads the sealed paired regime trial bundle by trial id."""

    def __call__(self, trial_id: str) -> RegimeTrialBundle: ...


class RegimeObservationPort(Protocol):
    """PIT-active regime observation before the trusted cutoff."""

    def active(self, evidence_id: str, cutoff: datetime) -> ActiveRegimeObservation: ...


class BtstProducerPort(Protocol):
    """The BTST raw-signal producer; the runner calls it exactly once."""

    def produce_and_publish(self, snapshot) -> tuple[EvidenceRecord[SignalEvidence], ...]: ...


class ShadowKernelPort(Protocol):
    """The pure per-arm decision function; called exactly once per arm."""

    def decide_shadow(self, shadow_input: ShadowKernelInput) -> ArmDecision: ...


class CapitalSnapshotReader(Protocol):
    """The PIT capital risk snapshot for one arm's frozen checkpoint."""

    def __call__(self, portfolio_id: str, as_of: datetime): ...


#: The one regime evidence id the paired trial consumes (published by the
#: RegimeObservationPublisher in evidence/regime.py).
REGIME_EVIDENCE_ID: str = "regime:csi300:1.0"

#: The runner binds the already-verified daily-action snapshot; the producer
#: is called with the snapshot the caller wired (forward trial feed).
_SNAPSHOT: object = None


def classify_pair_session(
    champion: ArmDecision | None,
    challenger: ArmDecision | None,
    *,
    shared_candidate_count: int,
) -> SessionStatus:
    """The pure session-status classification for one committed pair.

    - shared empty candidates (or a NO_SIGNAL no-trade on both arms) →
      ``NO_SIGNAL``;
    - a common capital/risk/integrity block (the same non-NO_SIGNAL no-trade
      reason on both arms) → ``BLOCKED``;
    - no pair at all after the decision cutoff → ``NO_RUN``;
    - otherwise the session ran (a Champion trade with a regime-blocked
      Challenger is a normal paired run) → ``RUN``.
    """

    if champion is None or challenger is None:
        return SessionStatus.NO_RUN
    if shared_candidate_count == 0:
        return SessionStatus.NO_SIGNAL
    champion_block = (
        champion.reason if isinstance(champion, NoTradeDecision) else None
    )
    challenger_block = (
        challenger.reason if isinstance(challenger, NoTradeDecision) else None
    )
    if (
        champion_block is not None
        and challenger_block is not None
        and champion_block == challenger_block
        and champion_block.value != "NO_SIGNAL"
    ):
        return SessionStatus.BLOCKED
    return SessionStatus.RUN


class ForwardPairedTrialRunner:
    """Decide forward signal sessions of one sealed paired regime trial.

    The runner is stateless per call: it re-reads the sealed bundle and the
    current trusted time each session, freezes one shared input, and commits
    exactly one pair + one session status per enrolled signal session. The
    pair commit is the side-effect boundary — after a commit, a replay finds
    and exact-validates the existing pair, skips both kernels, and only
    finishes missing reserves/status using stable IDs.
    """

    def __init__(
        self,
        *,
        trial_id: str,
        research_program_id: str,
        portfolio_id: str,
        decision_store: TrialArmDecisionStore,
        spine: SessionSpine,
        bundle_reader: SealedBundleReader,
        regime_reader: RegimeObservationPort,
        producer: BtstProducerPort,
        kernel: ShadowKernelPort,
        capital_reader: CapitalSnapshotReader,
        clock: Callable[[], datetime],
        reserve_pair: Callable[[tuple[str, str, str]], None] | None = None,
        evidence_id: str = REGIME_EVIDENCE_ID,
    ) -> None:
        self._trial_id = trial_id
        self._research_program_id = research_program_id
        self._portfolio_id = portfolio_id
        self._decision_store = decision_store
        self._spine = spine
        self._bundle_reader = bundle_reader
        self._regime_reader = regime_reader
        self._producer = producer
        self._kernel = kernel
        self._capital_reader = capital_reader
        self._clock = clock
        self._reserve_pair = reserve_pair
        self._evidence_id = evidence_id

    # ===================================================================
    # forward session decision
    # ===================================================================

    def decide_signal_session(
        self, request: SignalSessionRequest
    ) -> PairedSignalReceipt:
        """Decide one enrolled signal session: validate, freeze, commit, reserve.

        The pair commit is the side-effect boundary. After a commit, a replay
        exact-validates the existing pair, skips both kernels, and only
        finishes missing reserves/status using stable IDs — it never
        recomputes an alternate proposal after a pair exists.
        """

        trial_id = request.trial_id
        session = request.signal_session
        # 0. Frozen trusted time (one read, shared by both arms).
        trusted_at = self._clock()
        # 1. Sealed bundle: exact re-validation against the frozen time.
        bundle = self._bundle_reader(trial_id)
        validated = validate_regime_trial_bundle(bundle, trusted_at=trusted_at)
        trial = validated.trial_manifest
        # 2. Expected session: enrolled and not cancelled.
        self._require_session_decidable(trial_id, session)
        # 3. Decision cutoff: the trusted time must sit inside the enrollment
        #    window; a session whose cutoff has passed is an operational NO_RUN
        #    (finalize_missed_sessions), not a decision attempt.
        if not (trial.enrollment_start <= trusted_at < trial.enrollment_end):
            raise PairedTrialRunnerError(
                "enrollment_window_violation",
                "trusted_at falls outside the sealed enrollment window",
                trial_id=trial_id,
                session=session.isoformat(),
            )
        # 4. Prior lifecycle completion: an existing pair (a crashed prior run)
        #    is exact-validated and never recomputed.
        cycle_id = self._decision_cycle_id(session)
        pair_key = (trial_id, session.isoformat(), cycle_id)
        existing = self._find_exact_pair(pair_key)
        if existing is not None:
            return self._resume_after_commit(
                pair_key=pair_key,
                cycle_id=cycle_id,
                champion=existing[0],
                challenger=existing[1],
                trial_id=trial_id,
                session=session,
            )
        # 5. Shared evidence: one canonical regime observation before cutoff.
        active_regime = self._read_regime(trusted_at)
        # 6. Shared input freeze (identical for both arms).
        shared_input = self._shared_freeze(
            validated=validated,
            session=session,
            cycle_id=cycle_id,
            regime=active_regime.observation,
            regime_hash=active_regime.observation_hash,
            trusted_at=trusted_at,
        )
        # 7. Producer exactly once; its SELECTED records are the candidates.
        records = self._producer.produce_and_publish(_SNAPSHOT)  # type: ignore[arg-type]
        candidates = tuple(record for record in records if _is_selected(record))
        # 8. Two pure arm decisions over the same frozen shared input and the
        #    same capital checkpoint (one read, shared by both arms).
        capital_snapshot = self._capital_reader(self._portfolio_id, trusted_at)
        champion, challenger = self._decide_arms(
            validated=validated,
            shared_input=shared_input,
            trusted_at=trusted_at,
            records=candidates,
            capital_snapshot=capital_snapshot,
        )
        # 9. Commit one pair (the side-effect boundary).
        champion_record, challenger_record = self._records(
            trial_id=trial_id,
            session=session,
            cycle_id=cycle_id,
            shared_input=shared_input,
            regime_hash=active_regime.observation_hash,
            champion=champion,
            challenger=challenger,
            trusted_at=trusted_at,
            capital_checkpoint_hash=capital_snapshot.content_hash(),
        )
        self._decision_store.commit_pair(champion_record, challenger_record)
        # 10. One session status, then reserve both decisions.
        champion_status = classify_pair_session(
            champion, challenger, shared_candidate_count=len(candidates)
        )
        challenger_status = (
            SessionStatus.RUN
            if not isinstance(challenger, NoTradeDecision)
            else SessionStatus.NO_SIGNAL
        )
        self._spine.record_session_status(
            self._research_program_id, session, champion_status
        )
        self._finish_reserve(pair_key)
        return PairedSignalReceipt(
            trial_id=trial_id,
            signal_session=session,
            pair_key=pair_key,
            champion_status=champion_status,
            challenger_status=challenger_status,
            decision_cycle_id=cycle_id,
            regime_observation_hash=active_regime.observation_hash,
        )

    # ===================================================================
    # forward market-session advance (exit run-out through finality)
    # ===================================================================

    def advance_market_session(self, request: SignalSessionRequest) -> object:
        """Advance one market session's lifecycle for both arms.

        This remains available for exit-only run-out through the sealed
        finality date; the runner itself never re-decides a pair here.
        """

        raise NotImplementedError(
            "advance_market_session is wired by Task 12 (ForwardTrialReplayEngine)"
        )

    # ===================================================================
    # missed-session finalization
    # ===================================================================

    def finalize_missed_sessions(self, trusted_at: datetime) -> tuple[date, ...]:
        """Write NO_RUN only for enrolled sessions whose decision cutoff has
        passed and whose pair/status is absent."""

        finalized: list[date] = []
        for enrollment in self._spine.enrolled_sessions(
            self._research_program_id
        ):
            session = enrollment.signal_session
            if self._pair_exists(session):
                continue
            status = self._spine.status(self._research_program_id, session)
            if status is not None:
                continue
            if trusted_at < self._decision_cutoff(session):
                continue
            self._spine.mark_no_run(self._research_program_id, session)
            finalized.append(session)
        return tuple(finalized)

    # ===================================================================
    # private helpers
    # ===================================================================

    def _require_session_decidable(self, trial_id: str, session: date) -> None:
        if not self._spine.is_enrolled(self._research_program_id, session):
            raise PairedTrialRunnerError(
                "session_not_enrolled",
                "the signal session is not enrolled in the expected calendar",
                trial_id=trial_id,
                session=session.isoformat(),
            )
        status = self._spine.status(self._research_program_id, session)
        if status is SessionStatus.SESSION_CANCELLED:
            raise PairedTrialRunnerError(
                "session_cancelled",
                "the session is cancelled by a signed calendar revision",
                trial_id=trial_id,
                session=session.isoformat(),
            )

    def _find_exact_pair(
        self, pair_key: tuple[str, str, str]
    ) -> tuple[TrialArmDecisionRecord, TrialArmDecisionRecord] | None:
        try:
            return self._decision_store.pair(pair_key)
        except TrialStoreError as exc:
            if exc.code == "pair_incomplete":
                return None
            raise

    def _resume_after_commit(
        self,
        *,
        pair_key: tuple[str, str, str],
        cycle_id: str,
        champion: TrialArmDecisionRecord,
        challenger: TrialArmDecisionRecord,
        trial_id: str,
        session: date,
    ) -> PairedSignalReceipt:
        """Replay path: exact-validate the existing pair, finish missing
        status/reserve using stable IDs; never recompute an alternate
        proposal after a pair exists."""

        # The store pair() already verified payload integrity (tamper check).
        if self._spine.status(self._research_program_id, session) is None:
            status = classify_pair_session(
                champion.decision,
                challenger.decision,
                shared_candidate_count=1,
            )
            self._spine.record_session_status(
                self._research_program_id, session, status
            )
        self._finish_reserve(pair_key)
        return PairedSignalReceipt(
            trial_id=trial_id,
            signal_session=session,
            pair_key=pair_key,
            champion_status=classify_pair_session(
                champion.decision,
                challenger.decision,
                shared_candidate_count=1,
            ),
            challenger_status=(
                SessionStatus.RUN
                if not isinstance(challenger.decision, NoTradeDecision)
                else SessionStatus.NO_SIGNAL
            ),
            decision_cycle_id=cycle_id,
            regime_observation_hash=champion.regime_observation_hash,
        )

    def _read_regime(self, trusted_at: datetime) -> ActiveRegimeObservation:
        try:
            return self._regime_reader.active(self._evidence_id, trusted_at)
        except Exception as exc:
            raise PairedTrialRunnerError(
                "regime_observation_missing",
                "no active canonical regime observation before the trusted cutoff",
                evidence_id=self._evidence_id,
                reason=str(exc),
            ) from exc

    def _shared_freeze(
        self,
        *,
        validated,
        session: date,
        cycle_id: str,
        regime: RegimeObservation,
        regime_hash: str,
        trusted_at: datetime,
    ) -> object:
        return freeze_shared_input(
            portfolio_id=self._portfolio_id,
            trial_id=self._trial_id,
            validated=validated,
            session=session,
            cycle_id=cycle_id,
            regime=regime,
            regime_hash=regime_hash,
            trusted_at=trusted_at,
        )

    def _decide_arms(
        self,
        *,
        validated,
        shared_input: object,
        trusted_at: datetime,
        records: tuple[EvidenceRecord[SignalEvidence], ...],
        capital_snapshot,
    ) -> tuple[ArmDecision, ArmDecision]:
        champion_input, challenger_input = build_arm_kernel_inputs(
            validated=validated,
            shared_input=shared_input,  # type: ignore[arg-type]
            trusted_at=trusted_at,
            records=records,
            capital_snapshot=capital_snapshot,
        )
        champion = self._kernel.decide_shadow(champion_input)
        challenger = self._kernel.decide_shadow(challenger_input)
        return champion, challenger

    def _records(
        self,
        *,
        trial_id: str,
        session: date,
        cycle_id: str,
        shared_input: object,
        regime_hash: str,
        champion: ArmDecision,
        challenger: ArmDecision,
        trusted_at: datetime,
        capital_checkpoint_hash: str,
    ) -> tuple[TrialArmDecisionRecord, TrialArmDecisionRecord]:
        return build_pair_records(
            trial_id=trial_id,
            session=session,
            cycle_id=cycle_id,
            shared_input=shared_input,  # type: ignore[arg-type]
            regime_hash=regime_hash,
            champion=champion,
            challenger=challenger,
            trusted_at=trusted_at,
            capital_checkpoint_hash=capital_checkpoint_hash,
        )

    def _finish_reserve(self, pair_key: tuple[str, str, str]) -> None:
        """Reserve both decisions after the pair commit (Task 9 adapter).

        The reserve is the final step, invoked idempotently on replay; the
        injected ``reserve_pair`` is the caller's durable reserve (the Task 12
        wiring binds the ShadowProxyAdapter reserve over the arm ledgers).
        A missing wiring fails loudly: a paired trial must not silently
        proceed without its T0 worst-case reserves.
        """

        if self._reserve_pair is None:
            raise PairedTrialRunnerError(
                "reserve_not_wired",
                "no reserve_pair wiring was injected",
                pair_key=pair_key,
            )
        self._reserve_pair(pair_key)

    def _pair_exists(self, session: date) -> bool:
        try:
            self._decision_store.pair(
                (
                    self._trial_id,
                    session.isoformat(),
                    self._decision_cycle_id(session),
                )
            )
            return True
        except TrialStoreError as exc:
            if exc.code == "pair_incomplete":
                return False
            raise

    @staticmethod
    def _decision_cutoff(session: date) -> datetime:
        """The decision cutoff of one signal session (15:00 UTC close)."""

        from datetime import timezone

        return datetime(
            session.year, session.month, session.day, 15, 0, tzinfo=timezone.utc
        )

    def _decision_cycle_id(self, session: date) -> str:
        return f"daily-action-{session.isoformat()}"


def _is_selected(record: EvidenceRecord[SignalEvidence]) -> bool:
    from src.screening.offensive.v3.contracts.base import SignalStage

    return record.evidence.stage is SignalStage.SELECTED


def _with_arm(shared_input: object, arm: TrialArm):
    return shared_input.model_copy(update={"trial_arm": arm})  # type: ignore[attr-defined]


def _candidate_security_id(envelope: SignalEvidence) -> str:
    """The SELECTED record's ticker.

    Real producer evidence ids are ``btst:<snapshot_id>:<ticker>:<setup>:
    <stage>`` where the snapshot id itself is ``sha256:<hex>`` and contains
    a colon, so the ticker is always the third-from-last component.
    """

    ticker = envelope.evidence_id.split(":")[-3]
    return f"{ticker}.SZ"


def _candidate_price_micros(envelope: SignalEvidence) -> int:
    """The entry-price micros frozen on the SELECTED record (fallback 1 yuan)."""

    entry = getattr(envelope, "entry_price", None)
    if entry is None:
        return 10_000_000
    return int(float(entry) * 1_000_000)


def freeze_shared_input(
    *,
    portfolio_id: str,
    trial_id: str,
    validated: ValidatedRegimeTrialBundle,
    session: date,
    cycle_id: str,
    regime: RegimeObservation,
    regime_hash: str,
    trusted_at: datetime,
) -> ShadowSharedInput:
    """One frozen shared input, identical for both arms (official + replay).

    The single construction is shared by the forward runner and the Task 12
    replay engine so a current-cost replay reproduces the official decision
    bytes exactly.
    """

    trial = validated.trial_manifest
    sap = validated.sap_manifest
    return ShadowSharedInput(
        portfolio_id=portfolio_id,
        signal_session=session,
        decision_cycle_id=cycle_id,
        trial_manifest_hash=trial.artifact_hash(),
        sap_manifest_hash=sap.artifact_hash(),
        trial_arm=TrialArm.CHAMPION,  # overwritten per arm below
        mode=ExecutionMode.DAILY_BAR_PROXY,
        trusted_evidence_cutoff=trusted_at,
        evidence_set_merkle_root=regime_hash,
        regime_observation=regime,
        trial_id=trial_id,
        research_program_id=trial.research_program_id,
        economic_lineage_id=trial.economic_lineage_id,
        stage_id="stage-1",
        stage_manifest_hash="1" * 64,
        trust_bundle_hash=trial.trust_bundle_hash,
        registry_epoch=trial.registry_epoch,
        trusted_at=trusted_at,
    )


def build_arm_kernel_inputs(
    *,
    validated: ValidatedRegimeTrialBundle,
    shared_input: ShadowSharedInput,
    trusted_at: datetime,
    records: tuple[EvidenceRecord[SignalEvidence], ...],
    capital_snapshot: CapitalRiskSnapshot,
) -> tuple[ShadowKernelInput, ShadowKernelInput]:
    """Both arm kernel inputs over one shared freeze and one capital truth.

    Candidates are built exclusively from the producer's SELECTED records;
    every binding is frozen from the record, never synthesized. Shared with
    the replay engine so current-cost decisions reproduce byte-for-byte.
    """

    trial = validated.trial_manifest
    capital_checkpoint = ShadowCapitalCheckpoint(
        capital_snapshot_hash=capital_snapshot.content_hash(),
        capital_snapshot=capital_snapshot,
    )
    # Forward-decision deadline contract: the trusted time sits inside the
    # enrollment window, one open-auction cycle ahead of the T0 close.
    deadlines = DeadlineContract(
        close_finalized_at=trusted_at - timedelta(hours=18, minutes=30),
        seal_creation_deadline=trusted_at,
        permit_issue_deadline=trusted_at + timedelta(minutes=20),
        permit_expires_at=trusted_at + timedelta(hours=18, minutes=20),
        gateway_send_deadline=trusted_at + timedelta(hours=18, minutes=20),
        broker_auction_cutoff=trusted_at + timedelta(hours=18, minutes=30),
    )
    raw_candidates: list[RawCandidate] = []
    evidence_bindings: list[CandidateEvidenceBinding] = []
    prices: list[tuple[str, int]] = []
    for record in records:
        envelope = record.evidence
        candidate_id = envelope.evidence_id
        raw_candidates.append(
            RawCandidate(
                candidate_id=candidate_id,
                producer_namespace=envelope.subject_producer,
                family_id=BTST_FAMILY,
                economic_lineage_id=trial.economic_lineage_id,
                research_program_id=trial.research_program_id,
                stage_id="stage-1",
                security_id=_candidate_security_id(envelope),
                direction="LONG",
                unscaled_target_gross_cents=max(
                    int(capital_snapshot.as_observed_nav_cents // 4),
                    100_000,
                ),
                behavior_fingerprint=envelope.behavior_fingerprint,
                execution_version=envelope.execution_version,
                cost_version=envelope.cost_version,
                evidence_ids=(),
            )
        )
        evidence_bindings.append(
            CandidateEvidenceBinding(
                candidate_id=candidate_id,
                evidence_id=envelope.evidence_id,
                evidence_artifact_hash=record.artifact_hash(),
                evidence_payload_hash=envelope.payload_content_hash,
            )
        )
        prices.append((candidate_id, _candidate_price_micros(envelope)))
    champion_binding = BaselineShadowPolicyBinding(
        source_kind=ShadowPolicySourceKind.BASELINE_POLICY_ACTIVATION,
        baseline_policy_activation_hash=trial.baseline_policy_activation_hash,
        policy_snapshot_hash=validated.baseline_policy.content_hash(),
        policy_fingerprint=validated.baseline_policy.policy_fingerprint,
    )
    challenger_binding = TargetShadowPolicyBinding(
        source_kind=ShadowPolicySourceKind.TARGET_POLICY_REGISTRATION,
        target_policy_registration_hash=trial.target_policy_snapshot_registration_hash,
        policy_snapshot_hash=validated.target_policy.content_hash(),
        policy_fingerprint=validated.target_policy.policy_fingerprint,
    )
    champion_input = ShadowKernelInput(
        shared=_with_arm(shared_input, TrialArm.CHAMPION),
        policy_snapshot=validated.baseline_policy,
        shadow_policy_binding=champion_binding,
        capital_checkpoint=capital_checkpoint,
        deadlines=deadlines,
        candidate_evidence_bindings=tuple(evidence_bindings),
        raw_candidates=tuple(raw_candidates),
        price_micros_by_candidate=tuple(prices),
        industry_by_candidate=tuple(
            (candidate_id, "unknown") for candidate_id, _ in prices
        ),
    )
    challenger_input = ShadowKernelInput(
        shared=_with_arm(shared_input, TrialArm.CHALLENGER),
        policy_snapshot=validated.target_policy,
        shadow_policy_binding=challenger_binding,
        capital_checkpoint=capital_checkpoint,
        deadlines=deadlines,
        candidate_evidence_bindings=tuple(evidence_bindings),
        raw_candidates=tuple(raw_candidates),
        price_micros_by_candidate=tuple(prices),
        industry_by_candidate=tuple(
            (candidate_id, "unknown") for candidate_id, _ in prices
        ),
    )
    return champion_input, challenger_input


def build_pair_records(
    *,
    trial_id: str,
    session: date,
    cycle_id: str,
    shared_input: ShadowSharedInput,
    regime_hash: str,
    champion: ArmDecision,
    challenger: ArmDecision,
    trusted_at: datetime,
    capital_checkpoint_hash: str,
) -> tuple[TrialArmDecisionRecord, TrialArmDecisionRecord]:
    """The two immutable arm records of one committed pair (official + replay).

    ``created_at`` freezes the same trusted instant both paths consume so a
    current-cost replay reproduces the official rows byte-for-byte.
    """

    shared_hash = shared_input.content_hash()
    return (
        TrialArmDecisionRecord(
            trial_id=trial_id,
            signal_session=session,
            decision_cycle_id=cycle_id,
            arm=TrialArm.CHAMPION,
            shared_input_hash=shared_hash,
            arm_policy_fingerprint=(
                champion.shadow_policy_binding.policy_fingerprint
                if isinstance(champion, ShadowDecision)
                else None
            ),
            arm_capital_checkpoint_hash=capital_checkpoint_hash,
            regime_observation_hash=regime_hash,
            decision=champion,
            created_at=trusted_at,
            artifact_hash=champion.content_hash(),
        ),
        TrialArmDecisionRecord(
            trial_id=trial_id,
            signal_session=session,
            decision_cycle_id=cycle_id,
            arm=TrialArm.CHALLENGER,
            shared_input_hash=shared_hash,
            arm_policy_fingerprint=(
                challenger.shadow_policy_binding.policy_fingerprint
                if isinstance(challenger, ShadowDecision)
                else None
            ),
            arm_capital_checkpoint_hash=capital_checkpoint_hash,
            regime_observation_hash=regime_hash,
            decision=challenger,
            created_at=trusted_at,
            artifact_hash=challenger.content_hash(),
        ),
    )


__all__ = [
    "ForwardPairedTrialRunner",
    "PairedSignalReceipt",
    "PairedTrialRunnerError",
    "REGIME_EVIDENCE_ID",
    "SignalSessionRequest",
    "build_arm_kernel_inputs",
    "build_pair_records",
    "classify_pair_session",
    "freeze_shared_input",
]
